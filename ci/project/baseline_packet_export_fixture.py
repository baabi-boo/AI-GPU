# SPDX-License-Identifier: Apache-2.0
"""Independent synthetic published exports for offline packet-verifier tests.

Only the synthetic packet builder is imported. Published file mappings and
redactions are assembled here without the runner, exporter, or verifier. The
temporary raw packet is removed before return; no native evidence is copied.
"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from baseline_packet_fixture import SYNTHETIC, make_packet, refresh_log, save_report


PUBLIC_PREFIX = "docs/project/evidence/p01/native"
SOURCE_PACKET = "synthetic-native"
RAW_WORKSPACE = "/synthetic-workspace"
SANITIZATION_RULES = (
    ("${RAW_WORKSPACE}/AI-GPU-baseline/build64-p01-clean-simx", "$CLEAN_BUILD"),
    ("${RAW_WORKSPACE}/AI-GPU-baseline/build64-p01-xrtsim", "$XRTSIM_BUILD"),
    ("${RAW_WORKSPACE}/AI-GPU-baseline/build64-p01-gcc11", "$BUILD"),
    ("${RAW_WORKSPACE}/AI-GPU-baseline/build64-p01", "$INITIAL_BUILD"),
    ("${RAW_WORKSPACE}/p01-native-final", "$OUTPUT"),
    ("${RAW_WORKSPACE}/AI-GPU-baseline", "$SOURCE"),
    ("${RAW_WORKSPACE}/p01-native-run", "$HISTORICAL_OUTPUT"),
    ("${RAW_WORKSPACE}/baseline-venv", "$VENV"),
    ("${RAW_WORKSPACE}/tools-v3.0.2", "$TOOLS"),
    ("${RAW_WORKSPACE}/host-headers", "$HOST_HEADERS"),
    ("${RAW_WORKSPACE}/host-gcc11", "$HOST_GCC11"),
    ("${RAW_WORKSPACE}/AI-GPU", "$INSTRUMENTATION"),
    ("${RAW_WORKSPACE}", "$WORKSPACE"),
)


def _identity(contents):
    return {"sha256": hashlib.sha256(contents).hexdigest(),
            "size_bytes": len(contents)}


def save_export_manifest(root, manifest):
    """Save the supplied manifest without refreshing or repairing its identities."""
    path = Path(root) / "export-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")
    return path


def make_export(root, selected_ids=None, failed_case=None):
    """Create an independent synthetic export in an absent or empty directory.

    Selection and failure behavior follow ``make_packet``. The returned object
    is the saved export manifest; ``report.json`` retains original raw log
    identities, including those whose published bytes have been redacted.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("synthetic export root must be empty")

    manifest = {
        "schema_version": 1,
        "scope": "Completed execution packet export; this manifest does not accept a project gate.",
        "source_packet": SOURCE_PACKET,
        "sanitization": {
            "method": "Decode UTF-8, replace literal prefixes in listed order, encode UTF-8 without any other change. RAW_WORKSPACE is omitted from publication.",
            "nested_hash_policy": "All hashes and sizes inside copied records retain their original raw meanings. Use the artifacts mapping for published bytes; no result, exit, configuration, tolerance, matrix or helper claim is rewritten.",
            "rules": [{"source_prefix": prefix, "replacement": replacement}
                      for prefix, replacement in SANITIZATION_RULES],
        },
        "limitations": [
            SYNTHETIC,
            "Only text records and snapshots are included; compiled binaries and installed tool archives remain hash observations.",
            "Completed state permits retained failures and blockers; export is not proof of acceptance.",
            "The source is expected quiescent. Identity checks detect observed changes but are not an adversarial filesystem lock.",
        ],
        "artifacts": [],
    }
    with TemporaryDirectory(prefix="synthetic-p01-export-") as directory:
        raw_root = Path(directory) / "raw"
        report = make_packet(raw_root, selected_ids=selected_ids, failed_case=failed_case)
        redacted_logs = set()
        for command in report["commands"]:
            if command["id"] == "configure" or command["id"].endswith("-configure"):
                continue
            path = raw_root / command["log"]
            contents = path.read_bytes() + (
                "synthetic working directory: " + RAW_WORKSPACE + "/build\n"
                "synthetic diagnostic source: " + RAW_WORKSPACE + "/source/input.cc\n"
            ).encode("utf-8")
            refresh_log(raw_root, command, contents)
            redacted_logs.add(command["log"])
        save_report(raw_root, report)
        manifest["reported_outcome"] = report["outcome"]

        for source in sorted(raw_root.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(raw_root).as_posix()
            raw = source.read_bytes()
            public = raw
            if relative in redacted_logs:
                public = raw.decode("utf-8").replace(RAW_WORKSPACE, "$WORKSPACE").encode("utf-8")
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(public)
            raw_identity = _identity(raw)
            manifest["artifacts"].append({
                "path": PUBLIC_PREFIX + "/" + relative,
                **_identity(public),
                "source_path": SOURCE_PACKET + "/" + relative,
                "source_sha256": raw_identity["sha256"],
                "source_size_bytes": raw_identity["size_bytes"],
                "transformation": ("byte_preserving_copy" if public == raw
                                   else "literal_path_redaction"),
            })
    save_export_manifest(root, manifest)
    return manifest
