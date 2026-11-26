#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Supervise one fresh qualified warm attempt and retain its orchestration records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import time

sys.dont_write_bytecode = True

from baseline_packet_io import load_json_bytes
from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from p06_qualified_warm_inputs import collect_source_isolated as collect_source
import p02_matrix as base
import p06_dependency_contract as dependency
import p06_qualified_warm_contract as qualification
import p06_qualified_warm_replay as qualified_warm_replay
from preflight import available_memory_bytes
from xrt_signals import terminate_as_interrupt


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-run-v1"
SCOPE = "local-three-stage-orchestration-records-only"
SOURCE_FILE = "ci/project/p06_qualified_warm_run.py"
RECEIPT_PATH = "qualified-warm-run.json"
LOG_ROOT = "qualified-warm-run-logs"
SOURCE_ROOT = "qualified-warm-run-sources"
STAGE_NAMES = ("preparation", "dependency-build", "qualified-warm")
BUDGET = dict(dependency.BUDGET, execution_timeout_seconds=90 * 60)
COMPLETE_COUNTS = dict(qualification.COMPLETE_COUNTS)
MAX_INPUT_BYTES = 64 * 1024**2
MAX_SOURCE_FILES = 256
MAX_SOURCE_FILE_BYTES = 4 * 1024**2
MAX_SOURCE_TOTAL_BYTES = 32 * 1024**2
MAX_TERMINAL_BYTES = 64 * 1024
SOURCE_FILES = tuple(sorted(set(qualified_warm_replay.RUNNER_HELPERS)
    | set(qualified_warm_replay.ADMISSION_HELPERS)
    | {row["path"] for row in qualified_warm_replay.TRUSTED_READER_SOURCES}
    | {SOURCE_FILE, "ci/project/p06_qualified_warm_inputs.py", "ci/project/xrt_signals.py"}))
# These are the unchanged original ZIP identities in the historical proof.
ORIGINAL_ARCHIVES = {
    "diagnostic_archive": {"sha256": "6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb",
                           "size_bytes": 4290949},
    "control_archive": {"sha256": "d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f",
                        "size_bytes": 47632218},
}
FROZEN_SOURCES = {
    "source_proof": (qualification.SOURCE_PROOF_PATH, qualification.SOURCE_PROOF_SHA256),
    "historical_source_proof": (qualification.historical.SOURCE_PROOF_PATH,
                                qualification.historical.SOURCE_PROOF_SHA256),
    "sampling_contract": (qualification.warm.MANIFEST_PATH, qualification.WARM_CONTRACT_SHA256),
}
LIMITATIONS = [
    "This receipt reconciles local orchestration records; it is not independent native replay, producer authentication, or performance or phase acceptance.",
    "Only the three explicitly selected producers execute. Historical prerequisite archives remain separate original inputs, not newly executed controls.",
    "Child producers enforce their unchanged source, build and process contracts. This monitor does not aggregate child-created process groups or establish hard descendant containment.",
    "The fixed 90-minute ceiling is a polled execution budget; bounded termination and receipt finalization can finish after its deadline.",
    "Selected helper bytes and before/after identities do not establish complete system-input closure or defend against malicious concurrent filesystem writers.",
    "No performance predicate is evaluated or forced by this wrapper. Complete inert replay and the frozen analysis remain separate obligations.",
    *PROCESS_LIMITATIONS,
]
ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, UnicodeError, KeyboardInterrupt)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _canonical(value, *, existing=False):
    require(Path(value).is_absolute(), "paths must be explicit canonical absolute literals")
    result = base._path(value, existing=existing)
    require(all(not parent.is_symlink() for parent in (result, *result.parents)),
            "paths must not traverse symlinks")
    return result


def _relative(value):
    require(type(value) is str and value and str(PurePosixPath(value)) == value
            and not value.startswith("/") and not {".", ".."} & set(value.split("/"))
            and len(value.encode("utf-8")) <= 4096,
            "retained path is not a safe relative literal")
    return value


def _file(path, maximum, *, contents=False, allow_empty=False):
    """Hash a bounded, single-link regular file, checking identity through the read."""
    path = _canonical(path, existing=True)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and (0 if allow_empty else 1) <= before.st_size <= maximum,
            "retained input is not a bounded single-link regular file: " + str(path))
    signature = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_nlink,
                              row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    digest, size, chunks = hashlib.sha256(), 0, []
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(signature(opened) == signature(before), "input changed before reading: " + str(path))
        while chunk := stream.read(min(1024 * 1024, maximum + 1 - size)):
            size += len(chunk)
            require(size <= maximum, "input grew beyond its byte bound: " + str(path))
            digest.update(chunk)
            if contents:
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    require(size == before.st_size and signature(before) == signature(after) == signature(path.stat()),
            "input changed while reading: " + str(path))
    return ({"path": str(path), "sha256": digest.hexdigest(), "size_bytes": size},
            b"".join(chunks) if contents else None)


def _descriptor(root, relative, maximum=dependency.MAX_RECEIPT_BYTES, **options):
    row, body = _file(root / _relative(relative), maximum, **options)
    return dict(row, path=relative), body


def selected_sources(source, destination=None):
    """Retain the existing explicit producer/reader helper closure, never test imports."""
    require(0 < len(SOURCE_FILES) <= MAX_SOURCE_FILES and tuple(sorted(set(SOURCE_FILES))) == SOURCE_FILES,
            "selected helper inventory exceeds its file bound or is ambiguous")
    rows, total = [], 0
    for name in SOURCE_FILES:
        row, body = _descriptor(source, name, MAX_SOURCE_FILE_BYTES, contents=destination is not None)
        total += row["size_bytes"]
        require(total <= MAX_SOURCE_TOTAL_BYTES, "selected helper closure exceeds its total byte bound")
        if destination is not None:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(body)
            require(_descriptor(destination, name, MAX_SOURCE_FILE_BYTES)[0] == row,
                    "selected helper copy differs from the original")
        rows.append(row)
    return rows


def interpreter_identity():
    return dict(base._file_identity(sys.executable), python_version=list(sys.version_info[:3]),
                implementation=platform.python_implementation(), platform=sys.platform)


def clean_environment(paths, interpreter):
    entries = [paths["host_bin"], str(PurePosixPath(interpreter).parent), "/usr/bin", "/bin"]
    return {"PATH": os.pathsep.join(dict.fromkeys(entries)),
        "HOME": paths["workspace"] + "/local-home", "TMPDIR": paths["workspace"] + "/local-tmp",
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}


def stage_specs(paths, revision, interpreter, dependency_pin=None):
    """Build argv as inert strings; no retained path or command is opened here."""
    source, workspace = paths["source"], paths["workspace"]
    evidence = workspace + "/evidence"
    common = ["--source-dir", source, "--expected-revision", revision]
    host = ["--host-bin", paths["host_bin"]]

    def stage(name, module, arguments, report, maximum=5400):
        return {"id": name, "argv": [interpreter, "-B", source + "/ci/project/" + module + ".py", *arguments],
                "cwd": source, "timeout_seconds_max": maximum, "report_path": report}

    rows = [
        stage("preparation", "p06_dependency_local_prepare", [*common,
            "--workspace-dir", workspace, "--archive-root", paths["archive"],
            "--dependency-repositories", paths["repositories"], *host], "dependency-preparation.json", 1800),
        stage("dependency-build", "p06_dependency_build", [*common,
            "--workspace-dir", workspace, "--preparation", evidence + "/dependency-preparation.json",
            "--output-dir", evidence + "/dependency-build", *host], "dependency-build/report.json"),
    ]
    if dependency_pin is None:
        return rows
    require(type(dependency_pin) is str and re.fullmatch(r"[0-9a-f]{64}", dependency_pin),
            "qualified warm execution requires the raw dependency receipt SHA-256")
    rows.append(stage("qualified-warm", "p06_qualified_warm_execute", ["run", *common,
        "--tools-dir", workspace + "/tools", "--work-dir", workspace + "/work",
        "--output-dir", evidence + "/qualified-warm",
        "--dependency-receipt", evidence + "/dependency-build/report.json",
        "--dependency-receipt-sha256", dependency_pin, *host,
        "--counter-qualification", source + "/" + qualification.SOURCE_PROOF_PATH,
        "--counter-qualification-sha256", qualification.SOURCE_PROOF_SHA256,
        "--diagnostic-archive", paths["diagnostic_archive"],
        "--diagnostic-archive-sha256", ORIGINAL_ARCHIVES["diagnostic_archive"]["sha256"],
        "--control-archive", paths["control_archive"],
        "--control-archive-sha256", ORIGINAL_ARCHIVES["control_archive"]["sha256"],
        "--jobs", "2", "--timeout-seconds", "1800", "--run-timeout-seconds", "180"],
        "qualified-warm/report.json"))
    return rows


def report_terminal(name, document, paths):
    if name == "preparation":
        fields = ("contract_id", "execution_origin", "outcome", "reason", "native_execution")
    elif name == "dependency-build":
        fields = ("outcome", "reason", "fresh_dependency_build_passed")
    else:
        require(name == "qualified-warm", "unexpected qualified warm stage")
        fields = ("outcome", "reason", "completed_counts", "native_preflight_passed", "native_lifetime_passed",
            "dependency_source_to_loaded_binary_verified", "counter_qualification_passed", "qualified_warm_passed",
            *qualification.FALSE_CLAIMS)
    result = {field: document[field] for field in fields}
    if name == "qualified-warm":
        result["report"] = paths["workspace"] + "/evidence/qualified-warm/report.json"
    return result


def _terminal(body):
    lines = body.decode("utf-8", errors="strict").splitlines()
    require(lines and lines[-1].strip(), "child terminal output is absent")
    final = lines[-1].encode("utf-8")
    require(len(final) <= MAX_TERMINAL_BYTES, "child terminal output exceeds its byte bound")
    return load_json_bytes(final, "qualified warm child terminal output")


def _same_json(left, right):
    return dependency.json_bytes(left) == dependency.json_bytes(right)


def validate_stage_report(name, document, revision, dependency_pin, plan):
    identifiers = {"preparation": "p06-local-dependency-preparation-v1",
        "dependency-build": dependency.CONTRACT_ID, "qualified-warm": qualification.CONTRACT_ID}
    require(type(document) is dict and type(document.get("schema_version")) is int
            and document["schema_version"] == 1 and document.get("contract_id") == identifiers[name]
            and document.get("expected_revision") == revision and document.get("outcome") == "pass"
            and document.get("reason") is None and document.get("failures") == []
            and all(document.get(field) is False for field in qualification.FALSE_CLAIMS),
            name + " lacks a successful matching non-acceptance report")
    if name == "preparation":
        require(document.get("execution_origin") == "local" and document.get("native_execution") == "not_run",
                "preparation changes its local execution scope")
        return
    require(document.get("state") == "finished", name + " report is not finished")
    if name == "dependency-build":
        require(document.get("fresh_dependency_build_passed") is True, "fresh dependency build did not pass")
        return
    require(document.get("scope") == qualification.SCOPE and document.get("native_execution") == "run"
            and document.get("dependency_receipt_sha256") == dependency_pin
            and document.get("counter_qualification_sha256") == qualification.SOURCE_PROOF_SHA256,
            "qualified warm report changes its source, dependency or execution binding")
    for field in ("native_preflight_passed", "native_lifetime_passed", "dependency_source_to_loaded_binary_verified",
                  "counter_qualification_passed", "qualified_warm_passed"):
        require(document.get(field) is True, "qualified warm report did not complete " + field)
    require(_same_json(document.get("expected_counts"), COMPLETE_COUNTS)
            and _same_json(document.get("completed_counts"), COMPLETE_COUNTS),
            "qualified warm counts differ from the frozen 24-process population")
    require(_same_json(document.get("expected_processes"), plan)
            and type(document.get("processes")) is list and len(document["processes"]) == 24,
            "qualified warm process plan is incomplete or changed")
    per_process = {key: value // 24 for key, value in COMPLETE_COUNTS.items()}
    for process, expected in zip(document["processes"], plan):
        require(type(process) is dict and process.get("outcome") == "pass"
                and _same_json({key: process.get(key) for key in expected}, expected),
                "qualified warm process population is changed or reordered")
        warm, witness = process["observation"]["warm"], process["observation"]["witness"]
        operations = warm["operations"]
        require(type(operations) is list and len(operations) == 33
                and all(type(row["checked"]) is int and row["checked"] == 32
                    and type(row["dispatch"]["launches"]) is int and row["dispatch"]["launches"] == 1
                    for row in operations),
                "qualified warm process omits a prime or timed operation")
        require(all(type(witness[field]) is list and all(type(row) is dict for row in witness[field])
                    for field in ("snapshots", "reads", "cache_flush_reads")),
                "qualified warm witness populations must be arrays of records")
        require(type(warm["summary"]["snapshots"]) is dict,
                "qualified warm counter snapshots must be an object")
        observed = qualified_warm_replay.native.producer.completion_counts([process])
        require(_same_json(observed, per_process), "qualified warm process observation counts differ")
    commands = document.get("commands")
    require(type(commands) is list and len(commands) == 57
            and all(type(row) is dict and row.get("outcome") == "pass"
                and row.get("process_started") is True and type(row.get("exit_code")) is int
                and row["exit_code"] == 0 and row.get("reason") is None
                and row.get("cleanup_complete") is True for row in commands),
            "qualified warm command receipts are incomplete or unsuccessful")
    require([row["id"] for row in commands if row.get("native_process") is True]
            == [row["id"] for row in plan], "qualified warm command population is changed or reordered")
    require(all(type(row.get("id")) is str and row["id"] for row in commands)
            and len({row["id"] for row in commands}) == 57, "qualified warm command identities are duplicated")


def _summary(document):
    """A bounded convenience summary; the unmodified raw report is authoritative."""
    summary = {}
    for field in ("contract_id", "state", "outcome", "reason", "native_execution",
                  "fresh_dependency_build_passed", "native_preflight_passed", "native_lifetime_passed",
                  "dependency_source_to_loaded_binary_verified", "counter_qualification_passed",
                  "qualified_warm_passed", *qualification.FALSE_CLAIMS):
        value = document.get(field)
        if field in document:
            summary[field] = value[:4096] if type(value) is str else value if value is None or type(value) is bool else "invalid type"
    return summary


def _report_limit(relative):
    return (qualified_warm_replay.MAX_REPORT_BYTES if relative == "qualified-warm/report.json"
            else dependency.MAX_RECEIPT_BYTES)


def _observe_stage(report, active, evidence):
    """Keep partial originals even when the child or its monitor failed."""
    child = None
    active["retention_errors"] = []
    relative = active["report_path"]
    if os.path.lexists(evidence / relative):
        try:
            identity, body = _descriptor(evidence, relative, _report_limit(relative), contents=True)
            report["reports"][active["id"]] = identity
            child = (qualified_warm_replay.decode_report(body) if active["id"] == "qualified-warm"
                     else load_json_bytes(body, "qualified warm stage report"))
            active["report_summary"] = _summary(child)
        except ERRORS as error:
            active["retention_errors"].append("report: " + (str(error) or "interrupted"))
    if os.path.lexists(evidence / active["log"]):
        try:
            active["raw_log"], body = _descriptor(evidence, active["log"], BUDGET["max_log_bytes"],
                                                 contents=True, allow_empty=True)
            active["terminal_output"] = _terminal(body)
        except ERRORS as error:
            active["retention_errors"].append("log: " + (str(error) or "interrupted"))
    if active["id"] == "qualified-warm" and child is not None:
        observed = child.get("native_execution")
        if observed in ("run", "not_run", "unknown"):
            report["native_execution"] = observed
        for field in ("source_before", "source_after"):
            if child.get(field) is None:
                continue
            try:
                selected = child[field]
                identity, _ = _descriptor(evidence, "qualified-warm/" + _relative(selected["path"]))
                report["reports"]["native-" + field.replace("_", "-")] = identity
                require(_same_json({key: identity[key] for key in ("sha256", "size_bytes")},
                                   {key: selected[key] for key in ("sha256", "size_bytes")}),
                        "native source snapshot differs from its report")
            except ERRORS as error:
                active["retention_errors"].append(field + ": " + (str(error) or "interrupted"))
    return child


def execute(args):
    source = _canonical(args.source_dir, existing=True)
    workspace = _canonical(args.workspace_dir)
    require(source == ROOT and source.is_dir(), "execute the wrapper from the selected source checkout")
    require(not os.path.lexists(workspace) and workspace.parent.is_dir(),
            "qualified warm workspace must be new under an existing parent; implicit resume is forbidden")
    require(not base._overlap(source, workspace), "qualified warm workspace overlaps its source")
    workspace.mkdir(mode=0o700)
    evidence = workspace / "evidence"
    evidence.mkdir(mode=0o700)
    (evidence / LOG_ROOT).mkdir(mode=0o700)
    for name in ("local-home", "local-tmp"):
        (workspace / name).mkdir(mode=0o700)
    started = time.monotonic()
    deadline = started + BUDGET["execution_timeout_seconds"]
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "scope": SCOPE, "execution_origin": "local",
        "expected_revision": args.expected_revision, "source_dir": str(source), "workspace_dir": str(workspace),
        "state": "running", "outcome": "blocked", "reason": None, "failures": [],
        "started_at": base._now(), "finished_at": None, "duration_seconds": 0.0,
        "orchestration_passed": False, "native_execution": "not_run", "completed_counts": None,
        "expected_counts": dict(COMPLETE_COUNTS), "budget": dict(BUDGET),
        "source_before": None, "source_after": None, "source_stable": None,
        "selected_sources_before": None, "selected_sources_after": None, "selected_sources_stable": None,
        "retained_sources_root": SOURCE_ROOT, "selected_source_limits": {
            "files": MAX_SOURCE_FILES, "per_file_bytes": MAX_SOURCE_FILE_BYTES, "total_bytes": MAX_SOURCE_TOTAL_BYTES},
        "inputs_before": {}, "inputs_after": {}, "inputs_stable": None,
        "interpreter": None, "interpreter_after": None, "environment": None, "paths": None,
        "stages": [], "reports": {}, "dependency_receipt_sha256": None, "qualified_warm_report_sha256": None,
        **dict.fromkeys(qualification.FALSE_CLAIMS, False), "limitations": list(LIMITATIONS)}
    target = evidence / RECEIPT_PATH
    active, paths, input_paths, dependency_pin, plan = None, None, {}, None, None

    def checkpoint():
        base._write_json(target, report)

    def failure(stage, error):
        reason = str(error) or "interrupted"
        report["failures"].append({"stage": stage, "reason": reason, "at": base._now()})
        if report["reason"] is None:
            report["reason"] = reason
        report["outcome"] = "fail" if any(row.get("process_started") is not False for row in report["stages"]) else "blocked"
        report["orchestration_passed"] = False

    def stable_inputs():
        require(interpreter_identity() == report["interpreter"], "executing interpreter changed")
        require(selected_sources(source) == report["selected_sources_before"], "selected helper source changed")
        for name, previous in report["inputs_before"].items():
            require(_file(input_paths[name], MAX_INPUT_BYTES)[0] == previous,
                    "selected original input changed: " + name)

    try:
        checkpoint()
        require(type(args.expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision),
                "qualified warm execution requires an exact source revision")
        report["source_before"] = collect_source(source)
        base._source_ok({"checkout": report["source_before"]}, False)
        require(report["source_before"]["revision"] == args.expected_revision,
                "qualified warm source differs from its expected revision")
        archives = _canonical(args.archive_root, existing=True)
        repositories = _canonical(args.dependency_repositories, existing=True)
        host = _canonical(args.host_bin, existing=True)
        require(all(path.is_dir() for path in (archives, repositories, host)), "input roots must be directories")
        roots = (source, workspace, archives, repositories)
        require(all(not base._overlap(left, right) for index, left in enumerate(roots)
                    for right in roots[index + 1:]), "qualified warm input/output roots overlap")
        require(not base._overlap(host, workspace), "host-bin overlaps the fresh workspace")
        paths = {"source": str(source), "workspace": str(workspace), "archive": str(archives),
            "repositories": str(repositories), "host_bin": str(host),
            "diagnostic_archive": str(_canonical(args.diagnostic_archive, existing=True)),
            "control_archive": str(_canonical(args.control_archive, existing=True))}
        report["paths"] = paths
        input_paths = {name: Path(paths[name]) for name in ORIGINAL_ARCHIVES}
        input_paths.update({name: source / value[0] for name, value in FROZEN_SOURCES.items()})
        for name, path in input_paths.items():
            require(not base._overlap(path, workspace), "original input overlaps the workspace")
            identity, _ = _file(path, MAX_INPUT_BYTES)
            report["inputs_before"][name] = identity
            if name in ORIGINAL_ARCHIVES:
                require(all(identity[key] == value for key, value in ORIGINAL_ARCHIVES[name].items()),
                        "prerequisite archive differs from its frozen original: " + name)
            else:
                require(identity["sha256"] == FROZEN_SOURCES[name][1], "frozen source input differs: " + name)
        report["interpreter"] = interpreter_identity()
        require(report["interpreter"]["python_version"] == [3, 12, 14]
                and report["interpreter"]["implementation"] == "CPython"
                and report["interpreter"]["platform"] == "linux", "the local route requires pinned Linux CPython 3.12.14")
        report["environment"] = clean_environment(paths, report["interpreter"]["path"])
        require(shutil.which("python3", path=report["environment"]["PATH"]) == report["interpreter"]["path"],
                "child Python selection differs from the executing interpreter")
        report["resources_before"] = {"free_disk_bytes": {str(path): shutil.disk_usage(path).free for path in roots},
                                      "available_memory_bytes": available_memory_bytes()}
        require(min(report["resources_before"]["free_disk_bytes"].values()) >= BUDGET["min_free_bytes"]
                and (report["resources_before"]["available_memory_bytes"] or 0) >= BUDGET["max_rss_bytes"],
                "qualified warm execution requires the 15 GiB disk reserve and 4 GiB available RAM")
        report["selected_sources_before"] = selected_sources(source, evidence / SOURCE_ROOT)
        plan = qualification.process_plan(source)
        checkpoint()
        for name in STAGE_NAMES:
            require(time.monotonic() < deadline, "qualified warm execution exceeded its 90-minute budget")
            stable_inputs()
            spec = next(row for row in stage_specs(paths, args.expected_revision,
                        report["interpreter"]["path"], dependency_pin) if row["id"] == name)
            remaining = deadline - time.monotonic()
            require(remaining > 0, "qualified warm execution exceeded its 90-minute budget")
            active = {"id": name, "argv": spec["argv"], "cwd": spec["cwd"],
                "environment": dict(report["environment"]), "report_path": spec["report_path"],
                "timeout_seconds": min(spec["timeout_seconds_max"], remaining),
                "log": LOG_ROOT + "/" + name + ".log", "started_at": base._now(), "finished_at": None,
                "process_started": None}
            report["stages"].append(active)
            if name == "qualified-warm":
                report["native_execution"] = "unknown"
            try:
                checkpoint()
            except ERRORS as error:
                # No child can start until its launch intent is retained.
                active.update(process_started=False, cleanup_complete=True,
                    outcome="blocked", reason=str(error) or "interrupted", finished_at=base._now())
                if name == "qualified-warm":
                    report["native_execution"] = "not_run"
                raise
            try:
                active.update(run_bounded(active["argv"], source, active["environment"], evidence / active["log"],
                    timeout_seconds=active["timeout_seconds"], min_free_bytes=BUDGET["min_free_bytes"],
                    max_rss_bytes=BUDGET["max_rss_bytes"], max_log_bytes=BUDGET["max_log_bytes"],
                    resource_paths=(source, workspace)))
                if name == "qualified-warm" and active.get("process_started") is False:
                    report["native_execution"] = "not_run"
            finally:
                active["finished_at"] = base._now()
                child = _observe_stage(report, active, evidence)
                checkpoint()
            require(active.get("process_started") is True and active.get("outcome") == "pass"
                    and type(active.get("exit_code")) is int and active["exit_code"] == 0
                    and active.get("reason") is None and active.get("cleanup_complete") is True,
                    name + " child failed: " + str(active.get("reason")))
            require(not active["retention_errors"], name + " retained data invalid: " + "; ".join(active["retention_errors"]))
            require(child is not None, name + " did not retain its original report")
            validate_stage_report(name, child, args.expected_revision, dependency_pin, plan)
            require(active.get("raw_log") is not None and _same_json(
                {key: active["raw_log"][key] for key in ("sha256", "size_bytes")},
                {"sha256": active.get("log_sha256"), "size_bytes": active.get("log_size_bytes")}),
                "child log differs from its bounded observation")
            require(_same_json(active.get("terminal_output"), report_terminal(name, child, paths)),
                    "child terminal output differs from its retained report")
            if name == "dependency-build":
                dependency_pin = report["reports"][name]["sha256"]
                report["dependency_receipt_sha256"] = dependency_pin
            elif name == "qualified-warm":
                before = report["reports"].get("native-source-before")
                after = report["reports"].get("native-source-after")
                require(before is not None and after is not None
                        and (before["sha256"], before["size_bytes"]) == (after["sha256"], after["size_bytes"]),
                        "native source before/after identities are missing or changed")
                report["qualified_warm_report_sha256"] = report["reports"][name]["sha256"]
                report["completed_counts"] = dict(child["completed_counts"])
            checkpoint()
            active = None
        report["outcome"] = "pass"
    except ERRORS as error:
        failure(active["id"] if active is not None else "orchestration", error)
    finally:
        # Failure closeout makes the same observations as success closeout. It
        # never rewrites, removes, resumes, or fabricates a child subpacket.
        try:
            report["source_after"] = collect_source(source)
            report["source_stable"] = report["source_before"] == report["source_after"]
            if report["source_before"] is not None:
                require(report["source_stable"], "source changed during qualified warm execution")
        except ERRORS as error:
            failure("final-source", error)
        if report["selected_sources_before"] is not None:
            try:
                report["selected_sources_after"] = selected_sources(source)
                report["selected_sources_stable"] = report["selected_sources_before"] == report["selected_sources_after"]
                require(report["selected_sources_stable"], "selected helper source changed during execution")
                require(selected_sources(evidence / SOURCE_ROOT) == report["selected_sources_before"],
                        "retained helper source changed after copying")
            except ERRORS as error:
                failure("final-selected-sources", error)
        for name, path in input_paths.items():
            try:
                report["inputs_after"][name] = _file(path, MAX_INPUT_BYTES)[0]
                if name in report["inputs_before"]:
                    require(report["inputs_before"][name] == report["inputs_after"][name],
                            "selected original input changed: " + name)
            except ERRORS as error:
                failure("final-input-" + name, error)
        report["inputs_stable"] = bool(input_paths) and set(report["inputs_before"]) == set(input_paths) \
            and report["inputs_before"] == report["inputs_after"]
        if report["interpreter"] is not None:
            try:
                report["interpreter_after"] = interpreter_identity()
                require(report["interpreter_after"] == report["interpreter"], "executing interpreter changed")
            except ERRORS as error:
                failure("final-interpreter", error)
        for name, descriptor in report["reports"].items():
            try:
                require(_descriptor(evidence, descriptor["path"], _report_limit(descriptor["path"]))[0] == descriptor,
                        "original child report changed after its stage: " + name)
            except ERRORS as error:
                failure("final-report-" + name, error)
        for row in report["stages"]:
            if "raw_log" in row:
                try:
                    require(_descriptor(evidence, row["log"], BUDGET["max_log_bytes"], allow_empty=True)[0] == row["raw_log"],
                            "original child log changed after its stage: " + row["id"])
                except ERRORS as error:
                    failure("final-log-" + row["id"], error)
        duration = time.monotonic() - started
        if duration > BUDGET["execution_timeout_seconds"]:
            failure("deadline", "qualified warm execution exceeded its 90-minute budget")
        report.update(state="finished", finished_at=base._now(), duration_seconds=round(duration, 6),
                      orchestration_passed=report["outcome"] == "pass")
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source-dir", "workspace-dir", "archive-root", "dependency-repositories", "host-bin",
                 "diagnostic-archive", "control-archive"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    return parser


@terminate_as_interrupt()
def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute(args)
        summary = {name: report[name] for name in ("contract_id", "scope", "execution_origin", "outcome", "reason",
            "orchestration_passed", "native_execution", "completed_counts", "dependency_receipt_sha256",
            "qualified_warm_report_sha256", *qualification.FALSE_CLAIMS)}
        summary["report"] = str(args.workspace_dir / "evidence" / RECEIPT_PATH)
        print(json.dumps(summary, sort_keys=True))
        return 0 if report["orchestration_passed"] else 1
    except ERRORS as error:
        print(json.dumps({"contract_id": CONTRACT_ID, "scope": SCOPE, "outcome": "blocked",
            "reason": str(error) or "interrupted", "orchestration_passed": False,
            **dict.fromkeys(qualification.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
