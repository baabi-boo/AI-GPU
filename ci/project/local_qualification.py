#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0.
"""Run bounded, supplemental AFU and RTL checks with retained provenance."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

from baseline import clean_environment as baseline_environment
from baseline_inventory import hash_artifacts
from baseline_process import GIB, MIB, LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from local_qualification_cases import CONTRACT_ID, command_for, select_cases, verify_log
from local_qualification_inventory import collect_generated, collect_helpers, collect_inputs
from preflight import available_memory_bytes


HERE = Path(__file__).resolve().parent
LOADED_HELPERS = collect_helpers()
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./+-]+\Z")
MAX_SNAPSHOT_BYTES = 2 * MIB
MAX_REPORT_BYTES = 8 * MIB
MAX_PACKET_BYTES = 512 * MIB
FAILURE_CHECKPOINT_BYTES = 16 * 1024
LIMITATIONS = [
    "This is supplemental local RTL qualification, not vendor XRT hw_emu or phase acceptance.",
    "The AFU uses a local XRT shim and modeled host/device memory; vendor loading, platform and cache-coherence semantics are unqualified.",
    "Focused RTL unit tests cover their named modules, not every whole-system backpressure condition.",
    "Arithmetic and workload coverage is restricted to the selected fixed cases and retained configurations.",
    "Reused dependency libraries are identified inputs, not dependencies freshly rebuilt by this runner.",
    "Compiler records are retained for independent review; this runner does not claim generic compiler-record validation.",
    "Tool identities do not inventory every system library or compiler support file.",
    "The runner neither downloads tools nor produces FPGA images or physical measurements.",
    "Raw local logs and snapshots can contain machine paths; review them before publication.",
    *PROCESS_LIMITATIONS,
]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise argparse.ArgumentTypeError("expected a positive finite number") from error
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected a positive finite number")
    return number


def _budget(args):
    if type(args.jobs) is not int or args.jobs not in (1, 2):
        raise ValueError("jobs must be one or two")
    result = {"jobs": args.jobs}
    for name, value, scale, ceiling in (
        ("timeout_seconds", args.timeout_seconds, 1, 1800),
        ("max_rss_bytes", args.max_rss_gib, GIB, 6 * GIB),
        ("max_log_bytes", args.max_log_mib, MIB, 16 * MIB),
        ("min_free_bytes", args.min_free_gib, GIB, 2**63 - 1),
    ):
        try:
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and 1 <= value * scale <= ceiling)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("budgets must be positive, finite and within the fixed ceilings")
        result[name] = value if scale == 1 else int(value * scale)
    if result["min_free_bytes"] < 15 * GIB:
        raise ValueError("min-free-gib must preserve at least 15 GiB")
    return result


def _path(value, *, exists=False):
    path = Path(os.path.abspath(value))
    if not SAFE_PATH.fullmatch(str(path)) or path.resolve(strict=exists) != path:
        raise ValueError("paths must use safe literal characters without symlink traversal")
    return path


def _overlap(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def resolve_paths(args):
    paths = {
        "source": _path(args.source, exists=True),
        "tools": _path(args.tool_dir, exists=True),
        "dependencies": _path(args.dependency_source, exists=True),
        "headers": _path(args.header_dir, exists=True),
        "build": _path(args.build_root),
        "output": _path(args.output) if args.output is not None else None,
    }
    inputs = [paths[name] for name in ("source", "tools", "dependencies", "headers")]
    if any(not path.is_dir() for path in inputs):
        raise ValueError("all input roots must be existing directories")
    build = paths["build"]
    if (not build.parent.is_dir() or any(_overlap(build, path) for path in inputs)
            or os.path.lexists(build)):
        raise ValueError("build-root must be fresh, outside input roots, under an existing parent")
    output = paths["output"]
    if args.mode == "run" and output is None:
        raise ValueError("run requires --output")
    if output is not None and (not output.parent.is_dir() or os.path.lexists(output)
                               or any(_overlap(output, path) for path in inputs + [build])):
        raise ValueError("output must be fresh and separate from build and input roots")
    return paths


def clean_environment(paths, jobs=2, environ=None):
    current = os.environ if environ is None else environ
    path = current.get("PATH", os.defpath)
    if (not isinstance(path, str) or any(not entry or not Path(entry).is_absolute()
                                        for entry in path.split(os.pathsep))):
        raise ValueError("PATH must contain nonempty absolute directories")
    result = baseline_environment(current, jobs)
    for key in ("TMPDIR", "TMP", "TEMP"):
        result.pop(key, None)
    result.update({
        "PATH": path, "PYTHONDONTWRITEBYTECODE": "1",
        "THIRD_PARTY_DIR": str(paths["dependencies"] / "third_party"),
        "CPLUS_INCLUDE_PATH": str(paths["headers"]),
    })
    return result


def _inputs(paths, environment):
    return collect_inputs(paths["source"], paths["tools"], paths["dependencies"],
                          paths["headers"], environment)


def _helpers():
    current = collect_helpers()
    if current != LOADED_HELPERS:
        raise ValueError("executing helper identities changed after import")
    return current


def _groups(cases):
    result = {}
    for case in cases:
        group = result.setdefault(case["group"], [])
        if group and group[0]["configs"] != case["configs"]:
            raise ValueError("one generated build cannot mix configurations")
        group.append(case)
    return result


def _resource_observation(paths):
    return {
        "free_disk_bytes": {key: shutil.disk_usage(path if path.exists() else path.parent).free
                            for key, path in paths.items() if path is not None},
        "host_available_ram_bytes": available_memory_bytes(),
        "effective_cgroup_limit_bytes": None,
    }


def plan_run(args, paths=None):
    paths = resolve_paths(args) if paths is None else paths
    budget = _budget(args)
    cases = select_cases(args.case)
    environment = clean_environment(paths, budget["jobs"])
    inputs = _inputs(paths, environment)
    helpers = _helpers()
    resources = _resource_observation(paths)
    blockers = list(inputs.get("blockers", []))
    if inputs.get("outcome") != "pass" and not blockers:
        blockers.append("input inventory did not pass")
    if any(value < budget["min_free_bytes"] for value in resources["free_disk_bytes"].values()):
        blockers.append("free disk is below the retained reserve")
    schedule = []
    for group, selected in _groups(cases).items():
        build = paths["build"] / group
        schedule.append({"group": group, "build": str(build),
                         "configs": selected[0]["configs"],
                         "case_ids": [case["id"] for case in selected],
                         "workload_commands": [command_for(case, budget["jobs"]) for case in selected]})
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID, "mode": args.mode,
        "scope": "Supplemental vendor-free full-AFU and focused RTL qualification",
        "supplemental": True, "qualifies_P01_A03": False,
        "vendor_execution_performed": False, "phase_complete": False,
        "execution_performed": False, "workload_command_started": False,
        "workload_execution_verified": False,
        "state": "planned", "outcome": "blocked" if blockers else "pass",
        "started_at": _now(), "finished_at": None, "paths": {key: str(value) if value else None
                                                                 for key, value in paths.items()},
        "budget": budget, "resources_before": resources, "inputs_before": inputs,
        "helpers_before": helpers, "environment": environment, "schedule": schedule,
        "selected_ids": [case["id"] for case in cases],
        "cases": [{**case, "outcome": "not_run", "reason": "execution has not started"}
                  for case in cases],
        "commands": [], "checks": [], "snapshots": [], "generated": {},
        "blockers": blockers, "limitations": list(LIMITATIONS),
    }


def _packet_size(output):
    total = 0
    for root, dirs, files in os.walk(output, followlinks=False):
        for name in dirs + files:
            path = Path(root, name)
            if path.is_symlink():
                raise ValueError("packet contains a symlink")
        total += sum(Path(root, name).stat().st_size for name in files)
    return total


def _reserve(output, budget, size):
    if (_packet_size(output) + size > MAX_PACKET_BYTES
            or shutil.disk_usage(output).free < budget["min_free_bytes"] + size):
        raise ValueError("retained packet budget or disk reserve would be exceeded")


def _write_exclusive(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _checkpoint(output, report, budget):
    data = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("qualification report exceeds its retained limit")
    _reserve(output, budget, len(data))
    temporary = output / "report.json.tmp"
    _write_exclusive(temporary, data)
    try:
        os.replace(temporary, output / "report.json")
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _failure_checkpoint(output, report):
    compact = {key: report.get(key) for key in (
        "schema_version", "contract_id", "scope", "supplemental", "qualifies_P01_A03",
        "vendor_execution_performed", "phase_complete", "execution_performed",
        "workload_command_started", "workload_execution_verified", "state", "outcome", "reason", "started_at", "finished_at")}
    compact["full_report_checkpoint_failed"] = True
    compact["completed_command_ids"] = [item["id"] for item in report["commands"]]
    data = (json.dumps(compact, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > FAILURE_CHECKPOINT_BYTES:
        raise ValueError("failure checkpoint exceeds its reserve allowance")
    _write_exclusive(output / "failure.json", data)


def _snapshot(root, records, output, label, report, budget):
    retained = []
    for record in records:
        if record["size_bytes"] > MAX_SNAPSHOT_BYTES:
            raise ValueError("text snapshot exceeds its retained limit: " + record["path"])
        observed = hash_artifacts(root, [record["path"]])[0]
        if observed != record:
            raise ValueError("snapshot source identity changed: " + record["path"])
        data = (root / record["path"]).read_bytes()
        if len(data) != record["size_bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("snapshot source changed while reading")
        target = "artifacts/" + label + "/" + record["path"]
        destination = output / target
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _path(destination.parent, exists=True)
        _reserve(output, budget, len(data))
        _write_exclusive(destination, data)
        identity = hash_artifacts(output, [target])[0]
        retained.append({"source": record, "retained": identity})
    report["snapshots"].extend(retained)
    return retained


def _text_artifacts(records):
    return [record for record in records if Path(record["path"]).suffix in (
        ".stamp", ".mk", ".h", ".vh", ".vlt", ".json", ".ini")]


class CommandStopped(Exception):
    pass


def execute_run(args, report, paths=None):
    paths = resolve_paths(args) if paths is None else paths
    if report["outcome"] != "pass":
        return report
    cases = select_cases(args.case)
    if report["selected_ids"] != [case["id"] for case in cases] or report["budget"] != _budget(args):
        raise ValueError("plan no longer matches selected cases or budget")
    environment = clean_environment(paths, report["budget"]["jobs"])
    if environment != report["environment"]:
        raise ValueError("execution environment changed since planning")
    budget = report["budget"]
    output = paths["output"]
    if output is None or os.path.lexists(output) or os.path.lexists(paths["build"]):
        raise ValueError("run requires fresh output and build roots")
    created = False
    active_case = None
    generated = {}
    commands = report["commands"]

    def checkpoint():
        _checkpoint(output, report, budget)

    def stable(label):
        observed = _inputs(paths, environment)
        helpers = _helpers()
        result = {"stage": label, "inputs_match": observed == report["inputs_before"],
                  "helpers_match": helpers == report["helpers_before"]}
        report["checks"].append(result)
        if not result["inputs_match"] or not result["helpers_match"] or observed.get("outcome") != "pass":
            report["drift_observation"] = {"inputs": observed, "helpers": helpers}
            raise ValueError("source, tools, dependency, host, header or helper identities changed")
        for group, expected in generated.items():
            current = collect_generated(paths["build"] / group, paths["source"], _groups(cases)[group])
            if current != expected or current.get("outcome") != "pass":
                report["generated_drift"] = {"group": group, "observed": current}
                raise ValueError("generated recipe or configuration changed")

    def command(name, argv, build, current, *, workload=False):
        stable("before-" + name)
        _reserve(output, budget, budget["max_log_bytes"] + MAX_REPORT_BYTES)
        log = "logs/" + name + ".log"
        entry = {"id": name, "argv": argv, "cwd": str(build), "environment": current,
                 "log": log, "outcome": "not_run", "workload": workload}
        commands.append(entry)
        report["active_command"] = name
        checkpoint()
        entry.update(run_bounded(argv, build, current, output / log,
                                 **{key: value for key, value in budget.items() if key != "jobs"},
                                 resource_paths=tuple(path for path in paths.values() if path is not None)))
        started = entry.get("process_started") is True
        report["execution_performed"] |= started
        report["workload_command_started"] |= workload and started
        report.pop("active_command", None)
        stable("after-" + name)
        checkpoint()
        if (not started or entry["outcome"] != "pass" or entry.get("exit_code") != 0
                or not entry.get("cleanup_complete", False)):
            report["outcome"] = "fail"
            report["reason"] = name + ": " + str(entry.get("reason") or "command did not pass")
            raise CommandStopped()
        return entry

    try:
        output.mkdir(mode=0o700)
        created = True
        for name in ("logs", "artifacts"):
            (output / name).mkdir(mode=0o700)
        report.update({"state": "running", "outcome": "not_run", "started_at": _now()})
        stable("preflight")
        checkpoint()
        _snapshot(HERE, report["helpers_before"], output, "tooling", report, budget)
        source_files = sorted(set(path for case in cases for path in case["sources"]))
        _snapshot(paths["source"], hash_artifacts(paths["source"], source_files),
                  output, "source", report, budget)
        paths["build"].mkdir(mode=0o700)
        for group, selected in _groups(cases).items():
            build = paths["build"] / group
            build.mkdir(mode=0o700)
            current = {**environment, "CONFIGS": selected[0]["configs"]}
            command(group + "-configure", [str(paths["source"] / "configure"), "--xlen=64",
                    "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, current)
            observed = collect_generated(build, paths["source"], selected)
            if observed.get("outcome") != "pass":
                report["generated_failure"] = observed
                raise ValueError("generated build input validation failed")
            generated[group] = observed
            report["generated"][group] = observed
            _snapshot(build, observed["files"], output, "generated-" + group, report, budget)
            if any(case["kind"] == "app" for case in selected):
                for name, directory in (("kernel", "sw/kernel"), ("stub", "sw/runtime/stub")):
                    argv = ["make", "-j" + str(budget["jobs"]), "-C", directory]
                    command(group + "-" + name, argv, build, current)
            for case in selected:
                active_case = next(item for item in report["cases"] if item["id"] == case["id"])
                current = {**environment, "CONFIGS": case["configs"], **case["env"]}
                directory = ("tests/regression/" if case["kind"] == "app" else "hw/unittest/") + case["app"]
                make = ["make", "-j" + str(budget["jobs"]), "-C", directory]
                if case["kind"] == "app":
                    command(case["id"] + "-runtime", [*make, "runtime-xrt", "TARGET=xrtsim"], build, current)
                    make.append("TARGET=xrtsim")
                command(case["id"] + "-build", make, build, current)
                before = hash_artifacts(build, case["artifacts"])
                active_case["artifacts_before"] = before
                _snapshot(build, _text_artifacts(before), output, case["id"] + "-before", report, budget)
                entry = command(case["id"] + "-run", command_for(case, budget["jobs"]), build, current, workload=True)
                after = hash_artifacts(build, case["artifacts"])
                active_case["artifacts_after"] = after
                if before != after:
                    raise ValueError("case binaries or effective configuration changed during launch")
                observations = verify_log(case, (output / entry["log"]).read_text(encoding="utf-8", errors="strict"))
                active_case.update({"outcome": "pass", "reason": None, "observations": observations,
                                    "command_id": entry["id"]})
                report["workload_execution_verified"] = True
                checkpoint()
                active_case = None
        stable("final")
        report["outcome"] = "pass"
    except CommandStopped:
        if active_case is not None:
            active_case.update({"outcome": "fail", "reason": report["reason"]})
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError) as error:
        report["outcome"] = "fail" if commands else "blocked"
        report["reason"] = str(error)
        if active_case is not None:
            active_case.update({"outcome": "fail", "reason": str(error)})
    except KeyboardInterrupt:
        report.update({"outcome": "fail", "reason": "execution interrupted"})
        if active_case is not None:
            active_case.update({"outcome": "fail", "reason": "execution interrupted"})
    finally:
        report["state"] = "finished"
        report["finished_at"] = _now()
        report.pop("active_command", None)
        try:
            report["resources_after"] = _resource_observation(paths)
        except OSError:
            report["resources_after"] = {"observation_unavailable": True}
        if created:
            try:
                checkpoint()
            except (OSError, ValueError, RuntimeError):
                report.update({"outcome": "fail", "reason": "final report could not be retained within its budget"})
                _failure_checkpoint(output, report)
    return report


def _redact(value, paths):
    if isinstance(value, str):
        for key, path in sorted(paths.items(), key=lambda item: len(str(item[1])), reverse=True):
            if path is not None:
                value = value.replace(str(path), "$" + key.upper())
        return value
    if isinstance(value, list):
        return [_redact(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, paths) for key, item in value.items()}
    return value


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "run"))
    parser.add_argument("--source", type=Path, default=HERE.parents[1])
    parser.add_argument("--tool-dir", type=Path, required=True)
    parser.add_argument("--dependency-source", type=Path, required=True)
    parser.add_argument("--header-dir", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=_positive, default=1800)
    parser.add_argument("--min-free-gib", type=_positive, default=15)
    parser.add_argument("--max-log-mib", type=_positive, default=16)
    parser.add_argument("--max-rss-gib", type=_positive, default=6)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    paths = None
    try:
        paths = resolve_paths(args)
        report = plan_run(args, paths)
        if args.mode == "run":
            report = execute_run(args, report, paths)
        print(json.dumps(_redact(report, paths), indent=2, sort_keys=True, allow_nan=False))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        print(json.dumps({"schema_version": 1, "contract_id": CONTRACT_ID, "outcome": "blocked",
                          "supplemental": True, "qualifies_P01_A03": False,
                          "vendor_execution_performed": False, "phase_complete": False,
                          "blockers": [_redact(str(error), paths) if paths else "invalid qualification arguments"]},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
