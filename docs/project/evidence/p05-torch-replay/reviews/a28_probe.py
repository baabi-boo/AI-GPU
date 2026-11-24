#!/usr/bin/env python3
"""Bounded host-only CLI failures; no mocks, originals, or retained execution."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import warnings
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
DRIVER = ROOT / "ci/project/p05_torch_replay.py"
sys.path.insert(0, str(DRIVER.parent))
import p05_torch_replay as replay

REVISION = "1" * 40
REQUIRED_FLAGS = {
    "native_execution": "not_run",
    "retained_code_executed": False,
    "acceptance_claimed": False,
    "phase_acceptance": False,
}
FAILURE_FIELDS = set(REQUIRED_FLAGS) | {"schema_version", "contract_id", "outcome", "reason"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def zip_bytes(rows):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, body in rows:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, body)
    return stream.getvalue()


def empty_name_zip():
    body = b"x"
    crc = zlib.crc32(body)
    local = struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 0, 0, 0, 0, crc, 1, 1, 0, 0) + body
    central = struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 20, 20, 0, 0, 0, 0,
                          crc, 1, 1, 0, 0, 0, 0, 0, 0, 0)
    end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, len(central), len(local), 0)
    return local + central + end


def source_hashes():
    return {row["path"]: digest(ROOT / row["path"]) for row in replay.READER_SOURCES}


def main():
    before_sources = source_hashes()
    results = []
    checks = []
    with tempfile.TemporaryDirectory(prefix="a28-real-cli-") as temporary:
        scratch = Path(temporary)

        def save(name, body):
            target = scratch / name
            target.write_bytes(body)
            return target

        basic_raw = zip_bytes([("torch/report.json", b"{}")])
        basic = save("input with spaces;$(never-run).data", basic_raw)
        valid_sha = digest(basic)
        report = dict.fromkeys(replay.REPORT_FIELDS)
        report.update(schema_version=1, contract_id="p05-installed-torch-execution-v1",
                      backend="simx", format="fp16", state="finished", outcome="pass", reason=None,
                      development=False, source_stable=True, acceptance_claimed=False,
                      phase_complete=False, iterations=2, budget=replay.BUDGET,
                      limitations=list(replay.REPORT_LIMITATIONS),
                      started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:00:01+00:00")
        wrong_format = save("wrong-format.zip", zip_bytes([("torch/report.json", encoded(report))]))
        source = {"checkout": {"revision": "2" * 40, "tree": "3" * 40, "dirty": False,
                               "changed_paths": [], "untracked_paths": [], "submodules": {},
                               "pins": {}, "blockers": [], "inputs": [], "outcome": "pass"}, "files": []}
        source_raw = encoded(source)
        source_rows = []
        for key in ("source_before", "source_after"):
            name = "snapshots/" + key.replace("_", "-") + ".json"
            report[key] = {"path": name, "sha256": hashlib.sha256(source_raw).hexdigest(),
                           "size_bytes": len(source_raw)}
            source_rows.append(("torch/" + name, source_raw))
        wrong_revision = save("wrong-revision.zip", zip_bytes([("torch/report.json", encoded(report)), *source_rows]))
        linked = scratch / "linked.zip"
        linked.symlink_to(basic)
        (scratch / "child").mkdir()

        def case(label, reason, *, path=basic, sha=None, revision=REVISION, fmt="fp16", extra=None, argv=None):
            selected = Path(path)
            selected_live = selected if selected.is_absolute() else scratch / selected
            before = digest(selected_live)
            size = selected_live.stat().st_size if selected_live.is_file() else None
            arguments = argv if argv is not None else [
                "--archive", str(path), "--sha256", sha if sha is not None else before or "0" * 64,
                "--expected-revision", revision, "--format", fmt, *(extra or []),
            ]
            has_selected_input = "--archive" in arguments
            if not has_selected_input:
                before, size = None, None
            command = [sys.executable, "-B", str(DRIVER), *arguments]
            process = subprocess.run(command, cwd=scratch, capture_output=True, text=True, timeout=15)
            after = digest(selected_live) if has_selected_input else None
            row = {"case": label, "argv": command, "exit_code": process.returncode,
                   "stdout": process.stdout, "stderr": process.stderr,
                   "selected_size": size, "selected_sha256_before": before,
                   "selected_sha256_after": after,
                   "selected_bytes_unchanged": before == after if before is not None else None}
            results.append(row)
            assert before == after, row
            if label.startswith("grammar_"):
                assert process.returncode == 2 and process.stdout == "", row
                assert "usage:" in process.stderr and reason in process.stderr, row
                row["classification"] = "argparse_usage_error"
            else:
                assert process.returncode == 1 and process.stderr == "", row
                value = json.loads(process.stdout)
                assert set(value) == FAILURE_FIELDS, row
                assert value["schema_version"] == 1 and value["contract_id"] == replay.CONTRACT_ID, row
                assert value["outcome"] == "fail" and reason in value["reason"], row
                for key, expected in REQUIRED_FLAGS.items():
                    assert value[key] == expected and type(value[key]) is type(expected), row
                assert len(process.stdout.splitlines()) == 1, row
                assert '"outcome": "pass"' not in process.stdout, row
                row["classification"] = "structured_validation_failure"

        for label, sha in (("short", "0" * 63), ("upper", "A" * 64), ("nonhex", "g" * 64)):
            case("bad_sha_" + label, "external original archive SHA-256 required", sha=sha)
        case("sha_mismatch", "original ZIP SHA-256 differs", sha="0" * 64)
        for label, revision in (("short", "1" * 39), ("upper", "A" * 40), ("nonhex", "g" * 40)):
            case("bad_revision_" + label, "exact execution revision required", revision=revision)
        case("wrong_selected_format", "framework report format differs", path=wrong_format, fmt="bf16")
        case("wrong_selected_revision", "source checkout revision differs", path=wrong_revision)
        case("missing_archive", "No such file or directory", path=scratch / "absent.zip")
        case("relative_archive", "absolute and canonical", path=Path(basic.name), sha=valid_sha)
        case("symlink_archive", "absolute and canonical", path=linked)
        case("parent_traversal_archive", "absolute and canonical", path=scratch / "child/../" / basic.name)
        case("directory_archive", "Is a directory", path=scratch)

        case("empty_file", "bounded regular file", path=save("empty.zip", b""))
        case("non_zip", "missing ZIP end record", path=save("not-zip.data", b"synthetic host-only junk"))
        case("truncated_end_record", "missing ZIP end record", path=save("truncated.zip", basic_raw[:-1]))
        corrupt = bytearray(basic_raw)
        central = corrupt.index(b"PK\x01\x02")
        corrupt[central] = 0
        case("invalid_central_header", "invalid original ZIP structure", path=save("bad-central.zip", corrupt))
        case("empty_member_name", "invalid retained member name", path=save("empty-name.zip", empty_name_zip()))
        case("duplicate_member", "duplicate ZIP member", path=save("duplicate.zip", zip_bytes([
            ("torch/report.json", b"{}"), ("torch/report.json", b"{}")])) )
        case("unsafe_member", "unsafe or noncanonical retained member name", path=save("unsafe.zip", zip_bytes([
            ("../escape", b"inert")])) )
        crc_bad = bytearray(basic_raw)
        crc_bad[30 + len("torch/report.json")] ^= 1
        case("corrupt_payload_crc", "invalid retained member payload: torch/report.json",
             path=save("bad-crc.zip", crc_bad))
        local_bad = bytearray(basic_raw)
        local_bad[30] = ord("x")
        case("local_central_name_disagreement", "invalid retained member payload: torch/report.json",
             path=save("names-disagree.zip", local_bad))
        utf8_bad = bytearray(basic_raw)
        central = utf8_bad.index(b"PK\x01\x02")
        struct.pack_into("<H", utf8_bad, central + 8, 0x800)
        utf8_bad[central + 46] = 0xff
        case("invalid_utf8_member", "invalid original ZIP structure", path=save("bad-utf8-name.zip", utf8_bad))

        case("missing_torch_prefix", "packet prefix has no retained files",
             path=save("no-torch.zip", zip_bytes([("other.json", b"{}")])) )
        case("missing_report", "missing retained member: torch/report.json",
             path=save("no-report.zip", zip_bytes([("torch/other.json", b"{}")])) )
        case("malformed_report_json", "invalid bounded JSON",
             path=save("bad-json.zip", zip_bytes([("torch/report.json", b"{")])) )
        case("invalid_report_fields", "invalid framework report fields")
        case("duplicate_report_key", "duplicate JSON field: outcome",
             path=save("duplicate-key.zip", zip_bytes([("torch/report.json", b'{"outcome":"pass","outcome":"pass"}')])) )

        case("grammar_wrong_format", "invalid choice", fmt="tf32")
        case("grammar_missing_required", "the following arguments are required", argv=[])
        case("grammar_unknown_option", "unrecognized arguments", extra=["--unrecognized"])

        for label, overrides, reason in (
            ("api_wrong_format", {"expected_format": "tf32"}, "expected format must be fp16 or bf16"),
            ("api_revision_type", {"expected_revision": None}, "exact execution revision required"),
            ("api_sha_type", {"sha256": None}, "external original archive SHA-256 required"),
        ):
            arguments = {"path": basic, "sha256": valid_sha, "expected_revision": REVISION,
                         "expected_format": "fp16", **overrides}
            before = digest(basic)
            try:
                replay.replay_archive(**arguments)
            except ValueError as error:
                assert str(error) == reason
                checks.append({"case": label, "exception": type(error).__name__, "reason": str(error),
                               "selected_sha256_before": before, "selected_sha256_after": digest(basic)})
            else:
                raise AssertionError("API accepted invalid selection: " + label)
            assert digest(basic) == before

        after_sources = source_hashes()
        assert before_sources == after_sources, "trusted source changed during bounded probe"
        output = {
            "scope": "host-only rejection probes; incomplete synthetic packets; no full successful replay",
            "cli_process_count": len(results),
            "structured_failures": sum(row["classification"] == "structured_validation_failure" for row in results),
            "argparse_usage_errors": sum(row["classification"] == "argparse_usage_error" for row in results),
            "cli_existing_input_hash_comparisons": sum(row["selected_sha256_before"] is not None for row in results),
            "api_checks": checks, "cli_results": results,
            "reader_source_count": len(before_sources), "source_hashes_before": before_sources,
            "source_hashes_after": after_sources, "all_sources_unchanged": before_sources == after_sources,
            "max_synthetic_file_bytes": max(row["selected_size"] or 0 for row in results),
            "findings": [], "all_assertions_passed": True,
        }
        print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
