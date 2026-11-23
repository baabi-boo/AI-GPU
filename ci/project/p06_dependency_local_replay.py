#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replay an explicitly local dependency/native/control original without execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
import p06_dependency_contract as contract
import p06_dependency_control_replay as controls
import p06_dependency_local_execute as producer
import p06_dependency_native_replay as native_replay
import p06_dependency_receipt as receipts
import p06_local_toolchain as toolchain
from p06_replay import _fields, _integer, _same, _timestamp, require


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-local-dependency-replay-v1"
ENVELOPE = "local-execution.json"
PRODUCER_SOURCE = "ci/project/p06_dependency_local_execute.py"
RETAINED_PRODUCER = "local-sources/" + PRODUCER_SOURCE
LOCK = "ci/project/p01_toolchain.lock.json"
REPORTS = {
    "preparation": "dependency-preparation.json",
    "dependency-build": "dependency-build/report.json",
    "native-lifetime": "native-lifetime/report.json",
    "pending-probe": "pending-probe/report.json",
    "dependency-substitution": "dependency-substitution/report.json",
}
ENVELOPE_FIELDS = {
    "schema_version", "contract_id", "execution_origin", "expected_revision", "state", "outcome",
    "reason", "failures", "started_at", "finished_at", "duration_seconds", "source_dir", "workspace_dir",
    "archive_root", "dependency_repositories_root", "host_bin", "interpreter", "environment", "budget",
    "source_before", "source_after", "orchestrator_source", "stages", "reports", "native_execution",
    "fresh_dependency_build_passed", "dependency_source_to_loaded_binary_verified", "separate_controls_passed",
    "limitations", *contract.FALSE_CLAIMS,
}
STAGE_FIELDS = {
    "id", "argv", "cwd", "environment", "timeout_seconds", "log", "started_at", "finished_at",
    "outcome", "exit_code", "reason", "process_started", "duration_seconds", "log_sha256",
    "log_size_bytes", "peak_rss_bytes", "cleanup_complete", "limitations",
}
IDENTITY_FIELDS = {"path", "resolved_path", "sha256", "size_bytes"}
LIMITATIONS = [
    "This verifies retained consistency of an explicitly local original; it is not a GitHub run or authenticated execution origin.",
    "The caller independently pins the ZIP, local envelope, source revision, dependency receipt, native report/source snapshot and both separate controls.",
    "Dependency, complete native lifetime and both control semantic readers run inside one bounded archive; retained code, binaries, commands and producer paths remain inert.",
    "Toolchain metadata joins the reviewed immutable archive lock and selected installed identities to the native inventory; replay does not rehash producer archives or re-extract their contents.",
    "Actual execution and archive-to-installed-byte observations belong to the independently reviewed local original; consistent invented observations remain invented.",
    "The four managed processes, pending-read probe/zero control and alternate-library process remain separate populations.",
    "Complete counter qualification, absolute no-wrap bounds, warm performance and phase acceptance remain separate; all seven claims stay false.",
]


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _reader_sources():
    rows = {row["path"]: row for row in controls._reader_sources()}
    for name, module in (("p06_dependency_local_replay", sys.modules[__name__]),
                         ("p06_dependency_local_execute", producer)):
        path = ROOT / "ci/project" / (name + ".py")
        require(Path(module.__file__).resolve(strict=True) == path,
                "local replay helper loaded outside the trusted checkout")
        body = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        rows[relative] = {"path": relative, "sha256": _digest(body), "size_bytes": len(body)}
    lock = ROOT / LOCK
    body = lock.read_bytes()
    rows[LOCK] = {"path": LOCK, "sha256": _digest(body), "size_bytes": len(body)}
    toolchain._locked_manifest()
    return [rows[name] for name in sorted(rows)]


def _number(value, lower, upper, label):
    require(type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper,
            label + " must be a finite bounded number")
    return value


def _external_pins(sha256, expected_revision, pins):
    native_replay._pin(sha256, "original ZIP")
    require(type(expected_revision) is str and receipts.REVISION.fullmatch(expected_revision),
            "exact external source revision is required")
    for name, value in pins.items():
        native_replay._pin(value, name)


def _envelope_header(document, expected_revision):
    _fields(document, ENVELOPE_FIELDS, "local execution envelope")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1,
            "local execution schema version differs")
    for name, expected in (("contract_id", producer.CONTRACT_ID), ("execution_origin", "local"),
                           ("expected_revision", expected_revision), ("state", "finished"),
                           ("outcome", "pass"), ("reason", None), ("failures", []),
                           ("native_execution", "run")):
        _same(document[name], expected, "local execution " + name)
    for name in ("fresh_dependency_build_passed", "dependency_source_to_loaded_binary_verified", "separate_controls_passed"):
        require(document[name] is True, "local execution lacks " + name)
    require(all(document[name] is False for name in contract.FALSE_CLAIMS),
            "local execution advances qualification or acceptance")
    _same(document["budget"], producer.BUDGET, "local execution budget")
    require(all(type(document["budget"][name]) is type(value) for name, value in producer.BUDGET.items()),
            "local execution budget types differ")
    _same(document["limitations"], producer.LIMITATIONS, "local execution limitations")
    require(_timestamp(document["started_at"]) <= _timestamp(document["finished_at"]),
            "local execution time interval is reversed")


def _terminal(stage, native, alternate):
    if stage == "preparation":
        return {"contract_id": receipts.local_prepare.CONTRACT_ID, "execution_origin": "local",
                "outcome": "pass", "reason": None, "native_execution": "not_run"}
    if stage == "dependency-build":
        return {"outcome": "pass", "reason": None, "fresh_dependency_build_passed": True}
    if stage == "native-lifetime":
        return {"outcome": "pass", "reason": None,
                "report": str(native.paths["output"] / "report.json"), "completed_counts": native_replay.COUNTS,
                "native_preflight_passed": True, "native_lifetime_passed": True,
                "dependency_source_to_loaded_binary_verified": True, **dict.fromkeys(contract.FALSE_CLAIMS, False)}
    if stage == "pending-probe":
        return {"outcome": "pass", "reason": None, "native_execution": "run",
                "native_probe_passed": True, "zero_mutation_rejected": True}
    return {"outcome": "pass", "reason": None, "native_execution": "run", "control_passed": True,
            "alternate_dependency_built": True, "numerical_control_passed": True,
            "original_provenance_rejected": True, "control_counts": alternate["control_counts"]}


def _local_identity(document, outer, dependency_view, native, pending, alternate, pins):
    _envelope_header(document, native.revision)
    paths = {name: document[field] for name, field in (("source", "source_dir"), ("workspace", "workspace_dir"),
             ("archive", "archive_root"), ("repositories", "dependency_repositories_root"), ("host_bin", "host_bin"))}
    for name, value in paths.items():
        if value is not None or name != "host_bin":
            receipts.absolute(value)
    source, workspace = PurePosixPath(paths["source"]), PurePosixPath(paths["workspace"])
    _same(str(source), str(native.paths["source"]), "local source root")
    _same(str(workspace / "tools"), str(native.paths["tools"]), "local native toolchain root")
    _same(str(workspace / "work"), str(native.paths["work"]), "local native build root")
    _same(str(workspace / "evidence/native-lifetime"), str(native.paths["output"]), "local native evidence root")
    _same(paths["host_bin"], str(native.paths["host_bin"]) if native.paths["host_bin"] is not None else None,
          "local native host-tool directory")
    _same(document["source_before"], native.source["checkout"], "local initial source checkout")
    _same(document["source_after"], document["source_before"], "local final source checkout")
    preparation_body = dependency_view.verified(native.dependency_document["preparation"])
    _same(outer.read(REPORTS["preparation"], limit=contract.MAX_RECEIPT_BYTES), preparation_body,
          "local preparation original copy")
    preparation = receipts.decode(preparation_body)
    # Its complete schema/immutable lock has already passed the dependency reader.
    _same(preparation["contract_id"], receipts.local_prepare.CONTRACT_ID, "local preparation contract")
    _same(preparation["execution_origin"], "local", "local preparation origin")
    for name in ("source_dir", "workspace_dir", "archive_root", "dependency_repositories_root", "host_bin"):
        _same(preparation[name], document[name], "local preparation " + name)
    _same(preparation["source_before"], document["source_before"], "local preparation source checkout")
    _same(preparation["tools_dir"], str(native.paths["tools"]), "prepared native toolchain root")
    prepared_tools = preparation["toolchain_receipt"]["tools"]
    _fields(prepared_tools, set(toolchain.NATIVE_TOOLS), "prepared native tools")
    for name, identity in prepared_tools.items():
        _same(identity, native.tools[name], "prepared native tool " + name)
    for name, identity in preparation["host_tools"].items():
        if name in native.tools:
            _same(identity, native.tools[name], "prepared shared host tool " + name)
    interpreter = document["interpreter"]
    _fields(interpreter, IDENTITY_FIELDS | {"python_version", "implementation", "platform"}, "local interpreter")
    _same({name: interpreter[name] for name in IDENTITY_FIELDS}, native.tools["executing_python"],
          "local executing interpreter")
    require(interpreter["python_version"] == [3, 12, 14]
            and all(type(value) is int for value in interpreter["python_version"])
            and interpreter["implementation"] == "CPython" and interpreter["platform"] == "linux",
            "local interpreter differs from the pinned native interpreter")
    environment = producer.clean_environment(paths, interpreter["path"])
    _same(document["environment"], environment, "local child environment")
    source_body = outer.verified(document["orchestrator_source"], RETAINED_PRODUCER)
    _same(source_body, (ROOT / PRODUCER_SOURCE).read_bytes(), "local orchestrator source")
    _same(native.source_body(LOCK), (ROOT / LOCK).read_bytes(), "retained immutable toolchain lock")
    report_paths = dict(REPORTS, **{"native-source": "native-lifetime/" + native.report["source_before"]["path"]})
    _fields(document["reports"], set(report_paths), "local report pins")
    bodies = {}
    for name, path in report_paths.items():
        row = document["reports"][name]
        body = outer.verified(row, path)
        if name in pins:
            _same(_digest(body), pins[name], "externally pinned local " + name)
        bodies[name] = receipts.decode(body)
    _same(document["reports"]["native-source"]["sha256"], native.report["source_before"]["sha256"],
          "local native source descriptor")
    specs = producer.stage_specs(paths, native.revision, interpreter["path"],
                                 dependency_pin=pins["dependency-build"])
    stages = document["stages"]
    require(type(stages) is list and len(stages) == len(specs) == 5, "local stage population differs")
    started, finished = _timestamp(document["started_at"]), _timestamp(document["finished_at"])
    total_duration = _number(document["duration_seconds"], 0, 5400, "local execution duration")
    last, elapsed = started, 0.0
    log_names = set()
    for stage, spec in zip(stages, specs):
        _fields(stage, STAGE_FIELDS, "local stage")
        for name in ("id", "argv", "cwd"):
            _same(stage[name], spec[name], "local stage " + name)
        _same(stage["environment"], environment, "local stage environment")
        timeout = _number(stage["timeout_seconds"], 0, spec["timeout_seconds_max"], "local stage timeout")
        require(timeout > 0, "local stage timeout must be positive")
        # Each preceding monitor duration is rounded to six decimals. Setup
        # overhead is not subtracted here, so this is a conservative remaining
        # budget check with only its accumulated rounding allowance.
        require(timeout <= producer.BUDGET["execution_timeout_seconds"] - elapsed + 0.00001,
                "local stage timeout exceeds the remaining execution budget")
        require(stage["process_started"] is True and stage["cleanup_complete"] is True
                and type(stage["exit_code"]) is int and stage["exit_code"] == 0
                and stage["outcome"] == "pass" and stage["reason"] is None,
                "local stage did not complete successfully")
        _same(stage["limitations"], list(PROCESS_LIMITATIONS), "local process supervision limitations")
        begin, end = _timestamp(stage["started_at"]), _timestamp(stage["finished_at"])
        require(last <= begin <= end <= finished, "local stage ordering differs")
        last = end
        elapsed += _number(stage["duration_seconds"], 0, timeout, "local stage duration")
        _integer(stage["peak_rss_bytes"], 0, contract.BUDGET["max_rss_bytes"], "local stage peak RSS")
        expected_log = "local-logs/" + stage["id"] + ".log"
        _same(stage["log"], expected_log, "local stage log path")
        log_names.add(expected_log)
        body = outer.read(expected_log, limit=contract.BUDGET["max_log_bytes"])
        require(type(stage["log_size_bytes"]) is int and stage["log_size_bytes"] == len(body),
                "local stage log size differs")
        _same(stage["log_sha256"], _digest(body), "local stage log digest")
        _same(producer._terminal(body), _terminal(stage["id"], native, alternate), "local stage terminal output")
        child = bodies[stage["id"]]
        if "started_at" in child or "finished_at" in child:
            require(begin <= _timestamp(child["started_at"]) <= _timestamp(child["finished_at"]) <= end,
                    "child execution lies outside its local stage interval")
    require(elapsed <= total_duration, "local stage durations exceed their enclosing duration")
    require(_timestamp(bodies["pending-probe"]["finished_at"])
            <= _timestamp(bodies["dependency-substitution"]["started_at"]),
            "substitution precedes completed pending-probe control")
    expected_members = {ENVELOPE, REPORTS["preparation"], RETAINED_PRODUCER, *log_names}
    for prefix in ("dependency-build", "native-lifetime", "pending-probe", "dependency-substitution"):
        expected_members.update(prefix + "/" + name for name in outer.subview(prefix).files())
    _same(set(outer.files()), expected_members, "complete local packet member inventory")
    return {"execution_origin": "local", "source_revision": native.revision,
            "envelope": outer.identity(ENVELOPE), "preparation": document["reports"]["preparation"],
            "stages_checked": len(stages), "toolchain_identities_joined": len(prepared_tools),
            "source_checkout_unchanged": True, "separate_control_packets_semantically_verified": True,
            "retained_members_checked": len(expected_members), "native_execution": "not_run",
            "retained_code_executed": False, "origin_authenticated": False}


def replay_archive(path, sha256, *, expected_revision, expected_receipt_sha256,
                   expected_native_report_sha256, expected_source_manifest_sha256,
                   expected_probe_report_sha256, expected_substitution_report_sha256,
                   expected_local_execution_sha256, prefix=""):
    pins = {"local execution envelope": expected_local_execution_sha256,
            "dependency-build": expected_receipt_sha256, "native-lifetime": expected_native_report_sha256,
            "native-source": expected_source_manifest_sha256, "pending-probe": expected_probe_report_sha256,
            "dependency-substitution": expected_substitution_report_sha256}
    _external_pins(sha256, expected_revision, pins)
    require(type(prefix) is str, "local prefix must be literal text")
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted local replay source changed after import")
    api = native_replay.dependency_replay._archive_api()
    if prefix:
        api.relative_name(prefix)
    try:
        with api.ArchiveReader(path, sha256) as archive:
            outer = archive.view(prefix)
            envelope_body = outer.read(ENVELOPE, limit=contract.MAX_RECEIPT_BYTES)
            _same(_digest(envelope_body), expected_local_execution_sha256, "externally pinned local envelope")
            envelope = receipts.decode(envelope_body)
            _envelope_header(envelope, expected_revision)
            dependency_view = outer.subview("dependency-build")
            probe_view, substitution_view = outer.subview("pending-probe"), outer.subview("dependency-substitution")
            for view, pin in ((probe_view, expected_probe_report_sha256),
                              (substitution_view, expected_substitution_report_sha256)):
                _same(_digest(view.read("report.json", limit=contract.MAX_RECEIPT_BYTES)), pin,
                      "externally pinned local control report")
            native_result, native = native_replay.verify_view(outer.subview("native-lifetime"), dependency_view, api,
                expected_revision=expected_revision, expected_receipt_sha256=expected_receipt_sha256,
                expected_native_report_sha256=expected_native_report_sha256,
                expected_source_manifest_sha256=expected_source_manifest_sha256)
            pending = controls.verify_probe_view(probe_view, native=native,
                expected_report_sha256=expected_probe_report_sha256,
                expected_native_report_sha256=expected_native_report_sha256)
            alternate = controls.verify_substitution_view(substitution_view, native=native,
                expected_report_sha256=expected_substitution_report_sha256,
                expected_native_report_sha256=expected_native_report_sha256)
            local = _local_identity(envelope, outer, dependency_view, native, pending, alternate, pins)
            result = {"schema_version": 1, "contract_id": CONTRACT_ID,
                "scope": "local-dependency-native-and-separate-controls-retained-consistency", "outcome": "pass",
                "retained_consistency": True, "native_execution": "not_run", "retained_code_executed": False,
                **dict.fromkeys(contract.FALSE_CLAIMS, False), "source_revision": expected_revision,
                "managed_counts": native_result["counts"], "pending_probe": pending,
                "dependency_substitution": alternate, "native_review": native_result, "local_identity": local,
                "prefix": prefix, "archive_read": archive.receipt(), "trusted_reader_sources": TRUSTED_READER_SOURCES,
                "trusted_archive_reader": {"path": native_replay.archive_helpers.ARCHIVE_READER_PATH,
                                           "sha256": native_replay.archive_helpers.ARCHIVE_READER_SHA256},
                "limitations": list(LIMITATIONS)}
        require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted local replay source changed during review")
        return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError, StopIteration) as error:
        raise ValueError("malformed local dependency original: " + str(error)) from error


TRUSTED_READER_SOURCES = _reader_sources()


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    for name in ("sha256", "expected-revision", "dependency-receipt-sha256", "native-report-sha256",
                 "source-manifest-sha256", "probe-report-sha256", "substitution-report-sha256", "local-execution-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.expected_revision,
            expected_receipt_sha256=args.dependency_receipt_sha256,
            expected_native_report_sha256=args.native_report_sha256,
            expected_source_manifest_sha256=args.source_manifest_sha256,
            expected_probe_report_sha256=args.probe_report_sha256,
            expected_substitution_report_sha256=args.substitution_report_sha256,
            expected_local_execution_sha256=args.local_execution_sha256, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "report": str(args.output), "native_execution": "not_run",
                "retained_consistency": True, "retained_code_executed": False,
                **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "retained_consistency": False,
            "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
