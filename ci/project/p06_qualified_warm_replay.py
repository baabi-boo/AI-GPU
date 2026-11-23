#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reconstruct the explicitly selected complete qualified warm original."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import p06_qualified_warm_admission as admission
import p06_qualified_warm_contract as contract
import p06_qualified_warm_records as records
import p06_qualified_warm_analyze as analysis
import p06_counter_qualification_replay as historical_replay
import p06_counter_qualification_prerequisites as prerequisites
import p06_dependency_native_replay as native
from p06_replay import _same, require


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-replay-v1"
SCOPE = "complete-qualified-warm-retained-consistency"
PROOF_MEMBER = "artifacts/counter-qualification/proof.json"
REPORT_FIELDS = historical_replay.REPORT_FIELDS | {"qualified_warm_passed"}
RUNNER_HELPERS = tuple(sorted(set(historical_replay.RUNNER_HELPERS) | {
    "ci/project/p06_qualified_warm_" + name + ".py"
    for name in ("admission", "contract", "execute", "records")
}))
ADMISSION_HELPERS = tuple(sorted(set(historical_replay.ADMISSION_HELPERS) | {
    "ci/project/p06_qualified_warm_admission.py", "ci/project/p06_qualified_warm_contract.py",
    native.warm_contract.MANIFEST_PATH, *native.warm_contract._SOURCE_HASHES,
}))
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_REPORT_NODES = 750000
MAX_REPORT_DEPTH = 64
LIMITATIONS = [
    "This explicitly selected local reader reconstructs the complete 24-process warm original and both independently pinned historical prerequisites.",
    "Replay executes no native process or retained code; the original supplies execution evidence separately and is not authenticated by consistent records.",
    "Counter qualification applies only to these 24 completed seed-free processes and their reviewed source, build, dependency and lifetime relationships.",
    "The producer revision, source manifest, native report, dependency receipt, proof and archive identities are independent caller expectations.",
    "The source manifest binds retained bytes, not independent Git membership or the honesty of an untrusted producer.",
    "Historical diagnostics and controls retain their original identities, false claims and separate populations.",
    "The unchanged warm-v1 block, performance acceptance and phase acceptance remain separate.",
    *native.producer.base.PROCESS_LIMITATIONS,
]


def decode_report(body):
    """The complete warm population has a larger report, not larger individual records."""
    require(type(body) is bytes and 0 < len(body) <= MAX_REPORT_BYTES,
            "qualified warm report exceeds its byte bound")

    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate qualified warm report field")
            result[key] = value
        return result

    def integer(token):
        require(len(token) <= 64, "oversized qualified warm report integer")
        return int(token)

    def finite(token):
        require(len(token) <= 64, "oversized qualified warm report number")
        value = float(token)
        require(math.isfinite(value), "nonfinite qualified warm report number")
        return value

    def constant(_):
        raise ValueError("nonfinite qualified warm report constant")

    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=pairs,
                           parse_int=integer, parse_float=finite, parse_constant=constant)
    except (UnicodeError, RecursionError, OverflowError, json.JSONDecodeError) as error:
        raise ValueError("invalid bounded qualified warm report") from error
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        require(depth <= MAX_REPORT_DEPTH and count <= MAX_REPORT_NODES,
                "qualified warm report exceeds its structure bound")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    require(type(value) is dict, "qualified warm report must be an object")
    return value


class _WarmReportView:
    def __init__(self, view):
        self.view = view

    def __getattr__(self, name):
        return getattr(self.view, name)

    def json(self, name, *, integers_only=False):
        if name == "report.json":
            require(integers_only is False, "qualified warm report contains supervised durations")
            return decode_report(self.view.read(name, limit=MAX_REPORT_BYTES))
        return self.view.json(name, integers_only=integers_only)


def _reader_sources():
    rows = {row["path"]: row for row in historical_replay._reader_sources()}
    helper_rows = admission.reader_sources()
    _same(tuple(row["path"] for row in helper_rows), ADMISSION_HELPERS,
          "fixed qualified warm admission helper inventory")
    rows.update({row["path"]: row for row in helper_rows})
    for module in (records, analysis, sys.modules[__name__]):
        path = ROOT / "ci/project" / (module.__name__ + ".py")
        require(Path(module.__file__).resolve(strict=True) == path,
                "qualified warm reader loaded outside the trusted checkout")
        name = path.relative_to(ROOT).as_posix()
        body = path.read_bytes()
        rows[name] = {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
    for expected in admission.prerequisite_input_rows(contract.validate_proof(
            (ROOT / contract.SOURCE_PROOF_PATH).read_bytes())):
        body = (ROOT / expected["path"]).read_bytes()
        identity = {"path": expected["path"], "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        _same(identity, expected, "trusted qualified warm prerequisite input")
        rows[identity["path"]] = identity
    return [rows[name] for name in sorted(rows)]


class _QualifiedWarmReplay(native._NativeReplay):
    route_module = admission
    report_fields = REPORT_FIELDS
    runner_helpers = RUNNER_HELPERS
    result_contract_id = CONTRACT_ID
    result_scope = SCOPE
    result_limitations = LIMITATIONS
    complete_counts = contract.COMPLETE_COUNTS
    command_count = 57
    process_population_label = "expected exactly 24 qualified warm processes"

    def __init__(self, view, api, revision, *, expected_qualification_sha256,
                 diagnostic_archive, diagnostic_sha256, control_archive, control_sha256, **kwargs):
        super().__init__(_WarmReportView(view), api, revision, **kwargs)
        self.plan = contract.process_plan(ROOT)
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
              "original warm counter qualification outcome")
        _same(self.report["qualified_warm_passed"], True,
              "original complete warm qualification outcome")
        body = self.verified(self.report["retained_counter_qualification"], PROOF_MEMBER)
        _same(hashlib.sha256(body).hexdigest(), self.qualification_pin,
              "retained qualification proof identity")
        self.proof = contract.validate_proof(body)
        self.original_proof = contract.base_proof()
        _same(self.source_body(contract.SOURCE_PROOF_PATH), body,
              "executing and retained qualification proof bytes")
        _same(self.diagnostic_sha256, self.original_proof["diagnostics"]["archive"]["sha256"],
              "externally selected diagnostic original")
        _same(self.control_sha256, self.original_proof["controls"]["archive"]["sha256"],
              "externally selected control original")
        source_projection = contract.verify_source_projection(self.proof, self.source["files"])
        dependency_projection = prerequisites.verify_dependency_projection(self.original_proof, self.dependency_document)
        diagnostics = prerequisites.verify_prerequisites(self.original_proof,
            diagnostic_archive=self.diagnostic_archive, diagnostic_sha256=self.diagnostic_sha256)
        controls = prerequisites.verify_control_prerequisite(self.original_proof,
            archive=self.control_archive, sha256=self.control_sha256)
        self.counter_admission = admission.admission_summary(self.proof, source_projection,
            dependency_projection, diagnostics, controls)
        _same(self.report["counter_qualification_admission"], self.counter_admission,
              "reconstructed counter qualification admission")
        require(set(ADMISSION_HELPERS) <= set(self.sources),
                "retained source omits a qualification admission helper")
        helper_rows = [self.sources[name] for name in ADMISSION_HELPERS]
        inputs = admission.prerequisite_input_rows(self.proof)
        for row in inputs:
            _same(self.sources.get(row["path"]), row, "retained prerequisite source inventory")
        self.counter_stability = admission.stability_summary(self.proof, helper_rows, inputs)
        for name in ("counter_qualification_admission_before", "counter_qualification_admission_after"):
            _same(self.report[name], self.counter_stability, "counter qualification final stability")

    def build_binding_extra(self):
        return {"counter_qualification_sha256": self.qualification_pin,
                "counter_qualification_admission": self.counter_admission,
                "warm_sampling": contract.sampling_binding(ROOT)}

    def process_binding_extra(self, planned):
        return {"counter_qualification_sha256": self.qualification_pin,
                "warm_sampling": contract.sampling_binding(ROOT)}

    def stability_extra(self):
        return {"counter_qualification_admission": self.counter_stability}

    def result_extra(self):
        return {"counter_qualification_passed": True,
            "counter_qualification_scope": "recorded-complete-24-process-warm-attempt-only",
            "qualified_warm_passed": True, "warm_sampling": contract.sampling_binding(ROOT),
            "counter_qualification_sha256": self.qualification_pin,
            "counter_qualification_admission": self.counter_admission,
            "counter_qualification_stability": self.counter_stability,
            "counter_population": {"selectors": 33, "components": 40, "unavailable_selectors": 12},
            "lifetime_premises": list(contract.PREMISE_IDS)}


    def process_arguments(self, planned, binding_id):
        app = self.build / native.APP
        return [app / "ai_counter_preflight", native.lifetime.APP_FLAG, "--qualified-warm",
            "--policy", planned["policy"], "--module", app / "kernel.vxbin",
            "--qualification-id", binding_id, "--sample-id", planned["sample_id"],
            "--pair-index", str(planned["pair_index"]), "--phase", planned["phase"]]

    def verify_process_output(self, text, planned, binding_id):
        return records.verify_output(text, contract=self.contract, case=self.case, fmt=self.fmt,
            policy=planned["policy"], binding_id=binding_id, sample_id=planned["sample_id"],
            process_id=planned["id"], expected_libraries=self.libraries,
            pair_index=planned["pair_index"], phase=planned["phase"])

    def process_result_extra(self, planned, observed):
        return {name: planned[name] for name in ("sample_id", "pair_index", "phase")}


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
    body = native_view.read("report.json", limit=MAX_REPORT_BYTES)
    _same(hashlib.sha256(body).hexdigest(), expected_native_report_sha256, "externally pinned native report")
    checked = native.dependency_replay.verify_view(dependency_view,
        expected_revision=expected_revision, expected_receipt_sha256=expected_receipt_sha256)
    dependency_body = dependency_view.read("report.json", limit=native.dependency_contract.MAX_RECEIPT_BYTES)
    _same(hashlib.sha256(dependency_body).hexdigest(), expected_receipt_sha256,
          "dependency receipt after complete replay")
    replay = _QualifiedWarmReplay(native_view, api, expected_revision,
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
    result["analysis"] = analysis.analyze_population(replay.report["processes"], replay.bindings,
                                                   expected_revision=expected_revision)
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted qualification reader changed during analysis")
    return result, replay


def replay_archive(path, sha256, *, expected_revision, expected_receipt_sha256,
                   expected_native_report_sha256, expected_source_manifest_sha256,
                   expected_qualification_sha256, diagnostic_archive, diagnostic_sha256,
                   control_archive, control_sha256, prefix=""):
    """Read exactly a local dependency-build and qualified-warm archive pair."""
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
            native_view = archive.view(stem + "qualified-warm")
            expected_members = ({stem + "dependency-build/" + name for name in dependency_view.files()}
                | {stem + "qualified-warm/" + name for name in native_view.files()})
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
                "counter_qualification_passed": True, "qualified_warm_passed": True,
                "hypothesis_evaluation": result["analysis"]["hypothesis_evaluation"],
                "native_execution": "not_run",
                "retained_code_executed": False, **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "counter_qualification_passed": False,
            "qualified_warm_passed": False, "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
