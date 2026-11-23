#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reconstruct an explicitly selected local counter-qualification original."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import p06_counter_qualification_admission as admission
import p06_counter_qualification_contract as contract
import p06_counter_qualification_prerequisites as prerequisites
import p06_dependency_native_replay as native
from p06_replay import _same, require


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-managed-counter-qualification-replay-v1"
SCOPE = "complete-local-counter-qualification-retained-consistency"
PROOF_MEMBER = "artifacts/counter-qualification/proof.json"
REPORT_FIELDS = native.REPORT_FIELDS | {
    "counter_qualification_sha256", "counter_qualification_admission",
    "counter_qualification_admission_before", "counter_qualification_admission_after",
    "retained_counter_qualification", "counter_qualification_passed",
}
RUNNER_HELPERS = tuple(sorted(set(native.RUNNER_HELPERS) | {
    "ci/project/" + name + ".py" for name in (
        "p06_checked_execute", "p06_counter_diagnostics_replay", "p06_counter_public_build",
        "p06_counter_public_records", "p06_counter_public_replay",
        "p06_counter_qualification_admission", "p06_counter_qualification_contract",
        "p06_counter_qualification_execute", "p06_counter_qualification_prerequisites",
        "p06_counter_source_inventory", "p06_dependency_build", "p06_dependency_control_replay",
        "p06_dependency_local_execute", "p06_dependency_local_replay",
        "p06_dependency_native_replay", "p06_dependency_replay", "p06_dependency_substitution",
        "p06_managed_preflight_backend_build", "p06_managed_preflight_derivation",
        "p06_managed_preflight_generated", "p06_managed_preflight_replay",
        "p06_managed_preflight_replay_build", "p06_managed_preflight_replay_hosted",
        "p06_mpm_execute", "p06_pending_probe", "p06_replay", "p06_warm_analyze",
        "p06_warm_replay", "p06_workspace_execute", "p06_workspace_replay")
}))
ADMISSION_HELPERS = tuple(sorted((set(RUNNER_HELPERS) - {
    "ci/project/p06_dependency_lifetime_execute.py",
    "ci/project/p06_counter_qualification_execute.py",
}) | {"ci/gen_config.py", "ci/project/p01_toolchain.lock.json",
       native.archive_helpers.ARCHIVE_READER_PATH, "tests/unittest/pending_reads/main.cpp"}))
PUBLIC_INVENTORY = "docs/project/evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json"
LIMITATIONS = [
    "This explicitly selected local reader reconstructs the new four-process qualification original and both independently pinned historical prerequisites.",
    "Replay executes no native process or retained code; the original supplies execution evidence separately and is not authenticated by consistent records.",
    "Counter qualification applies only to these four completed seed-free processes and their reviewed source, build, dependency and lifetime relationships.",
    "The producer revision, source manifest, native report, dependency receipt, proof and archive identities are independent caller expectations.",
    "The source manifest binds retained bytes, not independent Git membership or the honesty of an untrusted producer.",
    "Historical diagnostics and controls retain their original identities, false claims and separate populations.",
    "The unchanged warm-v1 block, future warm-process qualification and all warm, phase and performance acceptance claims remain separate.",
    *native.producer.base.PROCESS_LIMITATIONS,
]


def _reader_sources():
    rows = {row["path"]: row for row in native._reader_sources()}
    helper_rows = admission.reader_sources()
    _same(tuple(row["path"] for row in helper_rows), ADMISSION_HELPERS,
          "fixed qualification admission helper inventory")
    rows.update({row["path"]: row for row in helper_rows})
    expected = ROOT / "ci/project/p06_counter_qualification_replay.py"
    require(Path(sys.modules[__name__].__file__).resolve(strict=True) == expected,
            "qualification reader loaded outside the trusted checkout")
    for name in (expected.relative_to(ROOT).as_posix(), contract.SOURCE_PROOF_PATH, PUBLIC_INVENTORY):
        body = (ROOT / name).read_bytes()
        rows[name] = {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
    require(rows[contract.SOURCE_PROOF_PATH]["sha256"] == contract.SOURCE_PROOF_SHA256,
            "trusted qualification proof differs from its frozen identity")
    warm = native.warm_contract
    reference_pins = {**warm._SOURCE_HASHES, warm.MANIFEST_PATH: native.manifest.WARM_CONTRACT_SHA256}
    for name, expected_sha256 in reference_pins.items():
        maximum = warm.MAX_MANIFEST_BYTES if name == warm.MANIFEST_PATH else warm.MAX_SOURCE_BYTES
        body = warm._read_file(ROOT / name, maximum)
        identity = {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        require(identity["sha256"] == expected_sha256, "trusted qualification reference changed: " + name)
        rows[name] = identity
    return [rows[name] for name in sorted(rows)]


class _QualifiedReplay(native._NativeReplay):
    route_module = admission
    report_fields = REPORT_FIELDS
    runner_helpers = RUNNER_HELPERS
    result_contract_id = CONTRACT_ID
    result_scope = SCOPE
    result_limitations = LIMITATIONS

    def __init__(self, *args, expected_qualification_sha256,
                 diagnostic_archive, diagnostic_sha256, control_archive, control_sha256, **kwargs):
        super().__init__(*args, **kwargs)
        _same(expected_qualification_sha256, contract.SOURCE_PROOF_SHA256,
              "externally selected frozen qualification proof")
        self.qualification_pin = expected_qualification_sha256
        self.diagnostic_archive = diagnostic_archive
        self.diagnostic_sha256 = diagnostic_sha256
        self.control_archive = control_archive
        self.control_sha256 = control_sha256

    def validate_route_provenance(self):
        _same(self.report["counter_qualification_sha256"], self.qualification_pin,
              "externally pinned qualification identity")
        _same(self.report["counter_qualification_passed"], True,
              "original four-process qualification outcome")
        body = self.verified(self.report["retained_counter_qualification"], PROOF_MEMBER)
        _same(hashlib.sha256(body).hexdigest(), self.qualification_pin,
              "retained qualification proof identity")
        self.proof = contract.validate_proof(body)
        _same(self.source_body(contract.SOURCE_PROOF_PATH), body,
              "executing and retained qualification proof bytes")
        _same(self.diagnostic_sha256, self.proof["diagnostics"]["archive"]["sha256"],
              "externally selected diagnostic original")
        _same(self.control_sha256, self.proof["controls"]["archive"]["sha256"],
              "externally selected control original")
        source_projection = contract.verify_source_projection(self.proof, self.source["files"])
        dependency_projection = prerequisites.verify_dependency_projection(self.proof, self.dependency_document)
        diagnostics = prerequisites.verify_prerequisites(self.proof,
            diagnostic_archive=self.diagnostic_archive, diagnostic_sha256=self.diagnostic_sha256)
        controls = prerequisites.verify_control_prerequisite(self.proof,
            archive=self.control_archive, sha256=self.control_sha256)
        self.counter_admission = admission.admission_summary(self.proof, source_projection,
            dependency_projection, diagnostics, controls)
        _same(self.report["counter_qualification_admission"], self.counter_admission,
              "reconstructed counter qualification admission")
        require(set(ADMISSION_HELPERS) <= set(self.sources),
                "retained source omits a qualification admission helper")
        helper_rows = [self.sources[name] for name in ADMISSION_HELPERS]
        inputs = [self.proof["diagnostics"]["public_source_inventory"]]
        for row in inputs:
            _same(self.sources.get(row["path"]), row, "retained prerequisite source inventory")
        self.counter_stability = admission.stability_summary(self.proof, helper_rows, inputs)
        for name in ("counter_qualification_admission_before", "counter_qualification_admission_after"):
            _same(self.report[name], self.counter_stability, "counter qualification final stability")

    def build_binding_extra(self):
        return {"counter_qualification_sha256": self.qualification_pin,
                "counter_qualification_admission": self.counter_admission}

    def process_binding_extra(self, planned):
        return {"counter_qualification_sha256": self.qualification_pin}

    def stability_extra(self):
        return {"counter_qualification_admission": self.counter_stability}

    def result_extra(self):
        return {"counter_qualification_passed": True,
            "counter_qualification_scope": "recorded-four-process-preflight-only",
            "counter_qualification_sha256": self.qualification_pin,
            "counter_qualification_admission": self.counter_admission,
            "counter_qualification_stability": self.counter_stability,
            "counter_population": {"selectors": 33, "components": 40, "unavailable_selectors": 12},
            "lifetime_premises": list(contract.PREMISE_IDS)}


def verify_view(native_view, dependency_view, api, *, expected_revision,
                expected_receipt_sha256, expected_native_report_sha256,
                expected_source_manifest_sha256, expected_qualification_sha256,
                diagnostic_archive, diagnostic_sha256, control_archive, control_sha256):
    """Reconstruct both selected packets, never accepting supplied verification summaries."""
    for value, label in ((expected_receipt_sha256, "dependency receipt"),
            (expected_native_report_sha256, "native report"),
            (expected_source_manifest_sha256, "native source manifest"),
            (expected_qualification_sha256, "qualification proof"),
            (diagnostic_sha256, "diagnostic original"), (control_sha256, "control original")):
        native._pin(value, label)
    _same(expected_qualification_sha256, contract.SOURCE_PROOF_SHA256, "external frozen qualification proof")
    require(type(expected_revision) is str and native.dependency_receipt.REVISION.fullmatch(expected_revision),
            "exact external source revision is required")
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted qualification reader changed after import")
    body = native_view.read("report.json", limit=native.dependency_contract.MAX_RECEIPT_BYTES)
    _same(hashlib.sha256(body).hexdigest(), expected_native_report_sha256, "externally pinned native report")
    checked = native.dependency_replay.verify_view(dependency_view,
        expected_revision=expected_revision, expected_receipt_sha256=expected_receipt_sha256)
    dependency_body = dependency_view.read("report.json", limit=native.dependency_contract.MAX_RECEIPT_BYTES)
    _same(hashlib.sha256(dependency_body).hexdigest(), expected_receipt_sha256,
          "dependency receipt after complete replay")
    replay = _QualifiedReplay(native_view, api, expected_revision,
        dependency_document=native.dependency_receipt.decode(dependency_body),
        dependency_verification=checked["retained_dependency_verification"],
        dependency_body=dependency_body, dependency_receipt_sha256=expected_receipt_sha256,
        source_manifest_sha256=expected_source_manifest_sha256,
        expected_qualification_sha256=expected_qualification_sha256,
        diagnostic_archive=diagnostic_archive, diagnostic_sha256=diagnostic_sha256,
        control_archive=control_archive, control_sha256=control_sha256)
    result = replay.run()
    result.update(dependency_verification=checked, native_report_sha256=expected_native_report_sha256)
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted qualification reader changed during review")
    return result, replay


def replay_archive(path, sha256, *, expected_revision, expected_receipt_sha256,
                   expected_native_report_sha256, expected_source_manifest_sha256,
                   expected_qualification_sha256, diagnostic_archive, diagnostic_sha256,
                   control_archive, control_sha256, prefix=""):
    """Read exactly a local dependency-build and native-qualification archive pair."""
    native._pin(sha256, "local qualification ZIP")
    require(type(prefix) is str, "qualification prefix must be literal text")
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted qualification reader changed after import")
    api = native.dependency_replay._archive_api()
    if prefix:
        api.relative_name(prefix)
    try:
        with api.ArchiveReader(path, sha256) as archive:
            stem = prefix + "/" if prefix else ""
            dependency_view = archive.view(stem + "dependency-build")
            native_view = archive.view(stem + "native-qualification")
            expected_members = ({stem + "dependency-build/" + name for name in dependency_view.files()}
                | {stem + "native-qualification/" + name for name in native_view.files()})
            _same(set(archive.view("").files()), expected_members, "complete local qualification archive roots")
            result, _ = verify_view(native_view, dependency_view, api,
                expected_revision=expected_revision, expected_receipt_sha256=expected_receipt_sha256,
                expected_native_report_sha256=expected_native_report_sha256,
                expected_source_manifest_sha256=expected_source_manifest_sha256,
                expected_qualification_sha256=expected_qualification_sha256,
                diagnostic_archive=diagnostic_archive, diagnostic_sha256=diagnostic_sha256,
                control_archive=control_archive, control_sha256=control_sha256)
            result.update(execution_origin="local", origin_authenticated=False, prefix=prefix,
                archive_read=archive.receipt(), trusted_reader_sources=TRUSTED_READER_SOURCES,
                trusted_archive_reader={"path": native.archive_helpers.ARCHIVE_READER_PATH,
                    "sha256": native.archive_helpers.ARCHIVE_READER_SHA256})
        require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted qualification reader changed during review")
        return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed retained counter qualification: " + str(error)) from error


TRUSTED_READER_SOURCES = _reader_sources()


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--dependency-receipt-sha256", required=True)
    parser.add_argument("--native-report-sha256", required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--counter-qualification-sha256", required=True)
    parser.add_argument("--diagnostic-archive", type=Path, required=True)
    parser.add_argument("--diagnostic-archive-sha256", required=True)
    parser.add_argument("--control-archive", type=Path, required=True)
    parser.add_argument("--control-archive-sha256", required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
            expected_receipt_sha256=args.dependency_receipt_sha256,
            expected_native_report_sha256=args.native_report_sha256,
            expected_source_manifest_sha256=args.source_manifest_sha256,
            expected_qualification_sha256=args.counter_qualification_sha256,
            diagnostic_archive=args.diagnostic_archive, diagnostic_sha256=args.diagnostic_archive_sha256,
            control_archive=args.control_archive, control_sha256=args.control_archive_sha256, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "scope": result["scope"], "report": str(args.output),
                "counter_qualification_passed": True, "native_execution": "not_run",
                "retained_code_executed": False, **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "counter_qualification_passed": False,
            "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
