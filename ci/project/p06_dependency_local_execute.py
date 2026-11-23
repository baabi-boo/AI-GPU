#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the fresh dependency and native controls with an explicit local origin."""

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

from baseline_inventory import collect_source
from baseline_packet_io import load_json_bytes
from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
import p02_matrix as base
import p06_dependency_contract as contract
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-local-dependency-execution-v1"
SOURCE_FILE = "ci/project/p06_dependency_local_execute.py"
BUDGET = dict(contract.BUDGET, execution_timeout_seconds=90 * 60)
STAGE_NAMES = ("preparation", "dependency-build", "native-lifetime", "pending-probe", "dependency-substitution")
COMPLETE_COUNTS = {"processes": 4, "launches": 132, "checked_words": 4224,
    "snapshots": 16, "available_queries": 528, "half_replies": 1056,
    "cache_flush_reads": 132, "dcr_reads": 1188, "unavailable_rows": 192}
LIMITATIONS = [
    "This envelope records local child execution, not a GitHub job, restored cache or authenticated producer.",
    "The managed four-process population, pending-read probe and substitution process remain separate.",
    "Each producer runs in a fresh interpreter; no retained command, source or binary is executed by replay.",
    "Child producers enforce their own unchanged process budgets. The outer process-group monitor does not aggregate child-created process groups or establish hard descendant containment.",
    "The fixed 90-minute ceiling is a polled execution budget; bounded termination and receipt writing can finish after its deadline.",
    "The original subpackets and independent review establish their declared evidence scope; this envelope alone is not complete qualification or performance acceptance.",
    *PROCESS_LIMITATIONS,
]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def clean_environment(paths, interpreter):
    entries = ([paths["host_bin"]] if paths["host_bin"] is not None else [])
    entries += [str(PurePosixPath(interpreter).parent), "/usr/bin", "/bin"]
    return {"PATH": os.pathsep.join(dict.fromkeys(entries)),
        "HOME": paths["workspace"] + "/local-home", "TMPDIR": paths["workspace"] + "/local-tmp",
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}


def stage_specs(paths, revision, interpreter, dependency_pin=None):
    source, workspace = paths["source"], paths["workspace"]
    evidence = workspace + "/evidence"
    host = ["--host-bin", paths["host_bin"]] if paths["host_bin"] is not None else []
    common = ["--source-dir", source, "--expected-revision", revision]
    dependency_report = evidence + "/dependency-build/report.json"

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
            "native stages require an exact dependency receipt digest")
    bound = ["--dependency-receipt", dependency_report, "--dependency-receipt-sha256", dependency_pin]
    managed = ["--managed-report", evidence + "/native-lifetime/report.json",
               "--build-dir", workspace + "/work/simx-fp16"]
    rows += [
        stage("native-lifetime", "p06_dependency_lifetime_execute", ["run", *common,
            "--tools-dir", workspace + "/tools", "--work-dir", workspace + "/work",
            "--output-dir", evidence + "/native-lifetime", *bound, *host,
            "--jobs", "2", "--timeout-seconds", "1800", "--run-timeout-seconds", "180"],
            "native-lifetime/report.json"),
        stage("pending-probe", "p06_pending_probe", [*common, *managed,
            "--output-dir", evidence + "/pending-probe", "--dependency-receipt-sha256", dependency_pin, *host],
            "pending-probe/report.json"),
        stage("dependency-substitution", "p06_dependency_substitution", [*common, *managed, *bound,
            "--output-dir", evidence + "/dependency-substitution"], "dependency-substitution/report.json"),
    ]
    return rows


def interpreter_identity():
    return dict(base._file_identity(sys.executable), python_version=list(sys.version_info[:3]),
                implementation=platform.python_implementation(), platform=sys.platform)


def _descriptor(root, relative, limit=contract.MAX_RECEIPT_BYTES):
    require(type(relative) is str and str(PurePosixPath(relative)) == relative
            and not relative.startswith("/") and not {".", ".."} & set(relative.split("/")),
            "local retained path is not a safe relative literal")
    path = root / relative
    require(path.resolve(strict=True) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "local retained data traverses a symlink")
    status = path.stat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1 and 0 < status.st_size <= limit,
            "local retained data is not a bounded regular file")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    require(len(body) == status.st_size and len(body) <= limit, "local retained data changed while reading")
    return {"path": relative, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}, body


def _terminal(body):
    lines = body.decode("utf-8", errors="strict").splitlines()
    require(lines and lines[-1].strip(), "child terminal output is absent")
    result = load_json_bytes(lines[-1].encode("utf-8"), "local child terminal output")
    require(type(result) is dict, "child terminal output is not an object")
    return result


def report_terminal(name, document, paths):
    if name == "preparation":
        fields = ("contract_id", "execution_origin", "outcome", "reason", "native_execution")
    elif name == "dependency-build":
        fields = ("outcome", "reason", "fresh_dependency_build_passed")
    elif name == "native-lifetime":
        fields = ("outcome", "reason", "completed_counts", "native_preflight_passed",
                  "native_lifetime_passed", "dependency_source_to_loaded_binary_verified", *contract.FALSE_CLAIMS)
    elif name == "pending-probe":
        fields = ("outcome", "reason", "native_execution", "native_probe_passed", "zero_mutation_rejected")
    else:
        require(name == "dependency-substitution", "unexpected local stage")
        fields = ("outcome", "reason", "native_execution", "control_passed", "alternate_dependency_built",
                  "numerical_control_passed", "original_provenance_rejected", "control_counts")
    result = {field: document[field] for field in fields}
    if name == "native-lifetime":
        result["report"] = paths["workspace"] + "/evidence/native-lifetime/report.json"
    return result


def validate_stage_report(name, document, revision, dependency_pin):
    identifiers = {"preparation": "p06-local-dependency-preparation-v1",
        "dependency-build": contract.CONTRACT_ID, "native-lifetime": contract.MANAGED_CONTRACT_ID,
        "pending-probe": "p06-pending-read-probe-v1",
        "dependency-substitution": "p06-dependency-substitution-control-v1"}
    require(type(document) is dict and type(document.get("schema_version")) is int
            and document["schema_version"] == 1 and document.get("contract_id") == identifiers[name]
            and document.get("expected_revision") == revision and document.get("outcome") == "pass"
            and document.get("reason") is None and document.get("failures") == []
            and all(document.get(field) is False for field in contract.FALSE_CLAIMS),
            name + " did not produce a successful matching non-acceptance report")
    if name == "preparation":
        require(document.get("execution_origin") == "local" and document.get("native_execution") == "not_run",
                "preparation changes its local execution scope")
        return
    require(document.get("state") == "finished", name + " report is not finished")
    if name == "dependency-build":
        require(document.get("fresh_dependency_build_passed") is True,
                "fresh dependency build did not pass")
        return
    require(document.get("native_execution") == "run"
            and document.get("dependency_receipt_sha256") == dependency_pin,
            name + " lacks native execution bound to the dependency original")
    flags = {"native-lifetime": ("native_preflight_passed", "native_lifetime_passed",
                                 "dependency_source_to_loaded_binary_verified"),
             "pending-probe": ("native_probe_passed", "zero_mutation_rejected"),
             "dependency-substitution": ("control_passed", "alternate_dependency_built",
                                         "numerical_control_passed", "original_provenance_rejected")}
    require(all(document.get(field) is True for field in flags[name]), name + " did not pass its required observations")
    if name == "native-lifetime":
        require(document.get("completed_counts") == COMPLETE_COUNTS
                and all(type(value) is int for value in document["completed_counts"].values()),
                "native managed population differs from the fixed four-process matrix")


def execute(args):
    source = base._path(args.source_dir, existing=True)
    workspace = base._path(args.workspace_dir)
    require(source == ROOT and source.is_dir(), "execute the local runner from the selected source checkout")
    require(not os.path.lexists(workspace) and workspace.parent.is_dir(),
            "local execution workspace must be fresh under an existing parent")
    require(not base._overlap(source, workspace), "local execution workspace overlaps its source")
    workspace.mkdir(mode=0o700)
    evidence = workspace / "evidence"
    evidence.mkdir(mode=0o700)
    (evidence / "local-logs").mkdir(mode=0o700)
    for name in ("local-home", "local-tmp"):
        (workspace / name).mkdir(mode=0o700)
    started = time.monotonic()
    deadline = started + BUDGET["execution_timeout_seconds"]
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "execution_origin": "local",
        "expected_revision": args.expected_revision, "state": "running", "outcome": "blocked", "reason": None,
        "failures": [], "started_at": base._now(), "finished_at": None, "duration_seconds": 0.0,
        "source_dir": str(source), "workspace_dir": str(workspace), "archive_root": None,
        "dependency_repositories_root": None, "host_bin": None, "interpreter": None,
        "environment": None, "budget": dict(BUDGET), "source_before": None, "source_after": None,
        "orchestrator_source": None, "stages": [], "reports": {}, "native_execution": "not_run",
        "fresh_dependency_build_passed": False, "dependency_source_to_loaded_binary_verified": False,
        "separate_controls_passed": False, **dict.fromkeys(contract.FALSE_CLAIMS, False),
        "limitations": list(LIMITATIONS)}
    target = evidence / "local-execution.json"
    active = None
    paths = None
    dependency_pin = None

    def checkpoint():
        body = contract.json_bytes(report)
        require(len(body) <= contract.MAX_RECEIPT_BYTES, "local envelope exceeds its byte bound")
        base._write_json(target, report)

    checkpoint()
    try:
        require(type(args.expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision),
                "local execution requires an exact source revision")
        archives = base._path(args.archive_root, existing=True)
        repositories = base._path(args.dependency_repositories, existing=True)
        host_bin = base._path(args.host_bin, existing=True) if getattr(args, "host_bin", None) else None
        require(archives.is_dir() and repositories.is_dir() and (host_bin is None or host_bin.is_dir()),
                "local execution input roots must be directories")
        roots = (source, workspace, archives, repositories)
        require(all(not base._overlap(left, right) for index, left in enumerate(roots)
                    for right in roots[index + 1:]), "local execution input/output roots overlap")
        paths = {"source": str(source), "workspace": str(workspace), "archive": str(archives),
                 "repositories": str(repositories), "host_bin": str(host_bin) if host_bin is not None else None}
        report.update(archive_root=paths["archive"], dependency_repositories_root=paths["repositories"],
                      host_bin=paths["host_bin"], interpreter=interpreter_identity())
        require(report["interpreter"]["python_version"] == [3, 12, 14]
                and report["interpreter"]["implementation"] == "CPython"
                and report["interpreter"]["platform"] == "linux", "the local route requires pinned Linux CPython 3.12.14")
        report["environment"] = clean_environment(paths, report["interpreter"]["path"])
        require(shutil.which("python3", path=report["environment"]["PATH"]) == report["interpreter"]["path"],
                "local child Python selection differs from the executing interpreter")
        report["source_before"] = collect_source(source)
        base._source_ok({"checkout": report["source_before"]}, False)
        require(report["source_before"]["revision"] == args.expected_revision,
                "local execution source differs from its expected revision")
        require(min(shutil.disk_usage(path).free for path in roots) >= BUDGET["min_free_bytes"]
                and (available_memory_bytes() or 0) >= BUDGET["max_rss_bytes"],
                "local execution requires the 15 GiB disk reserve and 4 GiB available RAM")
        copied = evidence / "local-sources" / SOURCE_FILE
        copied.parent.mkdir(parents=True)
        original = (source / SOURCE_FILE).read_bytes()
        with copied.open("xb") as stream:
            stream.write(original)
        report["orchestrator_source"], _ = _descriptor(evidence, copied.relative_to(evidence).as_posix())
        checkpoint()
        for name in STAGE_NAMES:
            require(time.monotonic() < deadline, "local execution exceeded its 90-minute budget")
            require(interpreter_identity() == report["interpreter"], "local executing interpreter changed")
            spec = next(row for row in stage_specs(paths, args.expected_revision,
                        report["interpreter"]["path"], dependency_pin) if row["id"] == name)
            active = {"id": name, "argv": spec["argv"], "cwd": spec["cwd"],
                "environment": dict(report["environment"]),
                "timeout_seconds": min(spec["timeout_seconds_max"], deadline - time.monotonic()),
                "log": "local-logs/" + name + ".log", "started_at": base._now(), "finished_at": None}
            report["stages"].append(active)
            previous_native_execution = report["native_execution"]
            if name == "native-lifetime" and previous_native_execution != "run":
                report["native_execution"] = "unknown"
            checkpoint()
            active.update(run_bounded(active["argv"], source, active["environment"], evidence / active["log"],
                timeout_seconds=active["timeout_seconds"], min_free_bytes=BUDGET["min_free_bytes"],
                max_rss_bytes=BUDGET["max_rss_bytes"], max_log_bytes=BUDGET["max_log_bytes"],
                resource_paths=(source, workspace)))
            active["finished_at"] = base._now()
            if name == "native-lifetime" and active.get("process_started") is False:
                report["native_execution"] = previous_native_execution
            child = None
            if (evidence / spec["report_path"]).exists():
                identity, body = _descriptor(evidence, spec["report_path"])
                report["reports"][name] = identity
                json_limits = ({"max_tokens": contract.MANAGED_REPORT_MAX_JSON_TOKENS}
                               if name == "native-lifetime" else {})
                child = load_json_bytes(body, "local child report", **json_limits)
                if name in ("native-lifetime", "pending-probe", "dependency-substitution") and type(child) is dict:
                    observed = child.get("native_execution")
                    if observed == "run" or (report["native_execution"] != "run" and observed in ("not_run", "unknown")):
                        report["native_execution"] = observed
            checkpoint()
            require(active.get("process_started") is True and active.get("outcome") == "pass"
                    and type(active.get("exit_code")) is int and active["exit_code"] == 0
                    and active.get("reason") is None and active.get("cleanup_complete") is True,
                    name + " child failed: " + str(active.get("reason")))
            require(child is not None, name + " did not retain its original report")
            validate_stage_report(name, child, args.expected_revision, dependency_pin)
            log_identity, body = _descriptor(evidence, active["log"], BUDGET["max_log_bytes"])
            require((log_identity["sha256"], log_identity["size_bytes"])
                    == (active["log_sha256"], active["log_size_bytes"]), "child log differs from the bounded observation")
            require(_terminal(body) == report_terminal(name, child, paths), "child terminal output differs from its retained report")
            if name == "dependency-build":
                dependency_pin = report["reports"][name]["sha256"]
            elif name == "native-lifetime":
                descriptor = child["source_before"]
                identity, _ = _descriptor(evidence, "native-lifetime/" + descriptor["path"])
                require((identity["sha256"], identity["size_bytes"]) == (descriptor["sha256"], descriptor["size_bytes"]),
                        "native source snapshot differs from its retained report")
                report["reports"]["native-source"] = identity
            checkpoint()
            active = None
        require(time.monotonic() <= deadline, "local execution exceeded its 90-minute budget")
        report["source_after"] = collect_source(source)
        require(report["source_after"] == report["source_before"], "source changed during local execution")
        require(interpreter_identity() == report["interpreter"], "local executing interpreter changed")
        require((source / SOURCE_FILE).read_bytes() == original, "local orchestrator source changed")
        for descriptor in report["reports"].values():
            require(_descriptor(evidence, descriptor["path"])[0] == descriptor, "original child report changed after its stage")
        require(time.monotonic() <= deadline, "local execution exceeded its 90-minute budget")
        report.update(outcome="pass", fresh_dependency_build_passed=True,
                      dependency_source_to_loaded_binary_verified=True, separate_controls_passed=True)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, StopIteration, UnicodeError, KeyboardInterrupt) as error:
        reason = str(error) or "interrupted"
        report["reason"] = reason
        report["outcome"] = "fail" if any(row.get("process_started") for row in report["stages"]) else "blocked"
        report["failures"].append({"stage": active["id"] if active is not None else "local-execution", "reason": reason})
    finally:
        duration = time.monotonic() - started
        if report["outcome"] == "pass" and duration > BUDGET["execution_timeout_seconds"]:
            reason = "local execution exceeded its 90-minute budget"
            report.update(outcome="fail", reason=reason, fresh_dependency_build_passed=False,
                          dependency_source_to_loaded_binary_verified=False, separate_controls_passed=False)
            report["failures"].append({"stage": "local-execution", "reason": reason})
        report.update(state="finished", finished_at=base._now(), duration_seconds=round(duration, 6))
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--dependency-repositories", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    return parser


def main(argv=None):
    try:
        report = execute(argument_parser().parse_args(argv))
        print(json.dumps({name: report[name] for name in ("contract_id", "execution_origin", "outcome", "reason",
            "native_execution", "fresh_dependency_build_passed", "dependency_source_to_loaded_binary_verified",
            "separate_controls_passed", *contract.FALSE_CLAIMS)}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "execution_origin": "local", "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
