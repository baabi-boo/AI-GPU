#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0.
"""Plan or execute the frozen native baseline without closing project gates."""

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

from baseline_host import collect_host
from baseline_inventory import _git, collect_build, collect_source, collect_tools, hash_artifacts
from baseline_matrix import command_for, config_for, load_matrix, select_cases
from baseline_process import GIB, MIB, run_bounded
from preflight import available_memory_bytes


HERE = Path(__file__).resolve().parent
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./+-]+\Z")
MAX_STAMP_BYTES = 1024 * 1024
MAX_TOOLING_FILE_BYTES = 1024 * 1024
TOOLING_FILES = (
    "baseline.py", "baseline_inventory.py", "baseline_matrix.py",
    "baseline_process.py", "baseline_host.py", "preflight.py",
)
LOADED_TOOLING = hash_artifacts(HERE, list(TOOLING_FILES))
DEPENDENCIES = (
    "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
    "third_party/ramulator/libramulator.so",
    "third_party/ramulator_ext/libramulator-vortex.so",
)
ENVIRONMENT_KEYS = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT")
LIMITATIONS = [
    "A passing plan is a prerequisite screen, not a GPU execution result.",
    "Selected-case success does not accept P01; independent review and full XRT hw_emu remain required.",
    "Processor rtlsim bypasses the AFU and is not XRT hw_emu or physical FPGA evidence.",
    "SimX arithmetic is software simulation; TFR/STD identify the paired native RTL configuration.",
    "The runner does not install dependencies or certify a container/cgroup memory allocation.",
    "Raw local command logs can contain source/build/tool paths; review and redact paths before publication.",
]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _positive(value):
    try:
        number = float(value)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("expected a positive finite number") from error
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected a positive finite number")
    return number


def _path(value, *, exists=False):
    supplied = Path(os.path.abspath(value))
    resolved = supplied.resolve(strict=exists)
    if supplied != resolved or not SAFE_PATH.fullmatch(str(resolved)):
        raise ValueError("paths must contain only safe characters and no symlink traversal")
    return resolved


def _overlap(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def resolve_paths(args):
    source = _path(args.source, exists=True)
    tools = _path(args.tool_dir, exists=True)
    build = _path(args.build_dir)
    if not source.is_dir() or not tools.is_dir():
        raise ValueError("source and tool roots must be existing directories")
    if source == build or source.is_relative_to(build):
        raise ValueError("build directory must be separate from source inputs")
    if build.is_relative_to(source):
        relative = build.relative_to(source)
        if len(relative.parts) != 1 or not relative.name.startswith("build"):
            raise ValueError("an in-checkout build must be a top-level build-prefixed directory")
    if _overlap(tools, source) or _overlap(tools, build):
        raise ValueError("the dedicated tool directory must not overlap source or build")
    if not build.parent.is_dir() or (build.exists() and not build.is_dir()):
        raise ValueError("build parent must exist and build must be a directory")
    output = None
    if args.output is not None:
        output = _path(args.output)
        if not output.parent.is_dir() or os.path.lexists(output):
            raise ValueError("output must be a fresh directory under an existing parent")
        if any(_overlap(output, item) for item in (source, tools, build)):
            raise ValueError("output must not overlap source, build or tools")
    if args.mode == "run" and output is None:
        raise ValueError("run requires --output with a fresh directory")
    return {"source": source, "build": build, "tools": tools, "output": output,
            "matrix": _path(args.matrix, exists=True),
            "bundle": _path(args.bundle_manifest, exists=True)}


def clean_environment(environ=None, jobs=2):
    if type(jobs) is not int or not 1 <= jobs <= 2:
        raise ValueError("native baseline jobs must be one or two")
    current = os.environ if environ is None else environ
    environment = {key: current[key] for key in ENVIRONMENT_KEYS if key in current}
    if not environment.get("PATH"):
        environment["PATH"] = os.defpath
    environment.update({
        "MAKEFLAGS": "-j" + str(jobs), "THREADS": str(jobs),
        "CMAKE_BUILD_PARALLEL_LEVEL": str(jobs), "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
    })
    return environment


def _budget(args):
    if type(args.jobs) is not int or not 1 <= args.jobs <= 2:
        raise ValueError("native baseline jobs must be one or two")
    values = {}
    for name, value, scale in (
        ("timeout_seconds", args.timeout_seconds, 1),
        ("min_free_bytes", args.min_free_gib, GIB),
        ("max_log_bytes", args.max_log_mib, MIB),
        ("max_rss_bytes", args.max_rss_gib, GIB),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("budgets must be finite positive numbers")
        scaled = value * scale
        if not math.isfinite(scaled) or scaled < 1 or scaled > 2**63 - 1:
            raise ValueError("budget is outside the supported range")
        values[name] = value if scale == 1 else int(scaled)
    values["jobs"] = args.jobs
    return values


def _redact(value, paths):
    if isinstance(value, str):
        replacements = [(str(paths[key]), "$" + label) for key, label in (
            ("source", "SOURCE"), ("build", "BUILD"), ("tools", "TOOLS"),
            ("output", "OUTPUT")) if paths.get(key) is not None]
        for original, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            value = value.replace(original, replacement)
        return value
    if isinstance(value, list):
        return [_redact(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, paths) for key, item in value.items()}
    return value


def _same_source(left, right):
    return (right.get("outcome") == "pass" and not right.get("dirty")
            and all(left.get(key) == right.get(key)
                    for key in ("revision", "tree", "pins", "submodules", "inputs")))


def _manifest_identity(path):
    identity = hash_artifacts(path.parent, [path.name])[0]
    return {key: value for key, value in identity.items() if key != "path"}


def collect_tooling():
    report = {"files": [], "checkout": {"revision": None, "tree": None, "dirty": None},
              "blockers": [], "limitations": [
                  "Helper content hashes and retained sources identify the executing instrumentation independently of the GPU source checkout."]}
    try:
        report["files"] = hash_artifacts(HERE, list(TOOLING_FILES))
        if (any(item["size_bytes"] > MAX_TOOLING_FILE_BYTES for item in report["files"])
                or report["files"] != LOADED_TOOLING):
            raise ValueError("helper contents changed after import or exceed their size limit")
    except (OSError, ValueError, RuntimeError):
        report["blockers"].append("executing helper identities are unavailable or changed after import")
    try:
        root = HERE.parents[1]
        toplevel = _git(root, "rev-parse", "--show-toplevel").decode().strip()
        if Path(toplevel).resolve() != root:
            raise ValueError("executing helpers are not in their expected checkout")
        for key, ref in (("revision", "HEAD"), ("tree", "HEAD^{tree}")):
            revision = _git(root, "rev-parse", "--verify", ref).decode("ascii").strip()
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ValueError("executing checkout revision is malformed")
            report["checkout"][key] = revision
        report["checkout"]["dirty"] = bool(_git(
            root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
            "--ignore-submodules=all"))
    except (OSError, ValueError, RuntimeError, UnicodeError):
        report["limitations"].append("Executing checkout metadata is unavailable; helper hashes and snapshots remain the content identity.")
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def _dependency_identity(source):
    report = {"artifacts": [], "blockers": []}
    for name in DEPENDENCIES:
        try:
            report["artifacts"].extend(hash_artifacts(source, [name]))
        except (OSError, ValueError, RuntimeError):
            report["blockers"].append("built dependency identity unavailable: " + name)
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def _verify_dependencies(source, expected, destination, key):
    observed = _dependency_identity(source)
    destination[key] = observed
    if observed["outcome"] != "pass" or observed["artifacts"] != expected:
        raise ValueError("built dependency identities changed or became unavailable")


def _verify_tooling(expected, destination, key):
    observed = collect_tooling()
    destination[key] = observed
    if observed["outcome"] != "pass" or observed["files"] != expected["files"]:
        raise ValueError("executing helper identities changed during execution")


def _snapshot_tooling(output, expected):
    target = output / "artifacts" / "tooling"
    target.mkdir(mode=0o700)
    names = []
    for identity in expected["files"]:
        with (HERE / identity["path"]).open("rb") as stream:
            contents = stream.read(MAX_TOOLING_FILE_BYTES + 1)
        if (len(contents) != identity["size_bytes"]
                or hashlib.sha256(contents).hexdigest() != identity["sha256"]):
            raise ValueError("executing helper changed while being snapshotted")
        with (target / identity["path"]).open("xb") as stream:
            stream.write(contents)
        names.append("artifacts/tooling/" + identity["path"])
    return hash_artifacts(output, names)


def plan_run(args, paths=None):
    paths = resolve_paths(args) if paths is None else paths
    matrix = load_matrix(paths["matrix"])
    selected = select_cases(matrix, args.case)
    budget = _budget(args)
    report = {
        "schema_version": 1, "mode": args.mode, "started_at": _now(),
        "state": "planned", "outcome": "not_run", "phase_complete": False,
        "scope": "Frozen P01 native software-simulation and processor-RTL baseline",
        "matrix": {"id": matrix["id"], **_manifest_identity(paths["matrix"])},
        "budget": budget, "source_before": collect_source(paths["source"]),
        "tools_before": collect_tools(paths["tools"], paths["bundle"]),
        "host_before": collect_host(clean_environment(jobs=args.jobs)),
        "tooling_before": collect_tooling(),
        "dependencies": [], "commands": [], "blockers": [],
        "coverage": {"selected_ids": [case["id"] for case in selected],
                     "required_ids": [case["id"] for case in matrix["cases"]],
                     "full_matrix_selected": len(selected) == len(matrix["cases"]),
                     "full_native_matrix_passed": False},
        "cases": [{"id": case["id"], "app": case["app"],
                   "driver": case["driver"], "configs": case["configs"],
                   "args": case["args"], "reference": case["reference"],
                   "arithmetic": case["arithmetic"], "outcome": "not_run",
                   "reason": "execution has not started", "artifacts": []}
                  for case in selected],
        "integration": {"gate": "P01-A03", "driver": "xrt", "target": "hw_emu",
                        "outcome": "blocked", "exit_code": None,
                        "reason": "A separately qualified vendor tool/platform environment and full AFU run are required; this runner does not execute them."},
        "limitations": list(LIMITATIONS),
    }
    for key in ("source_before", "tools_before", "host_before", "tooling_before"):
        report["blockers"].extend(report[key]["blockers"])
    report["dependencies_planned"] = _dependency_identity(paths["source"])
    report["dependencies"] = report["dependencies_planned"]["artifacts"]
    if report["dependencies_planned"]["outcome"] != "pass":
        report["blockers"].append("built pinned SoftFloat/Ramulator dependencies are missing")
    build = paths["build"]
    if build.exists() and any(build.iterdir()):
        report["build_before"] = collect_build(build, paths["source"])
        report["blockers"].extend(report["build_before"]["blockers"])
    else:
        report["build_before"] = {"outcome": "not_run", "reason": "fresh build will be configured"}
    try:
        report["resources"] = {
            "source_free_disk_bytes": shutil.disk_usage(paths["source"]).free,
            "build_free_disk_bytes": shutil.disk_usage(build if build.exists() else build.parent).free,
            "tools_free_disk_bytes": shutil.disk_usage(paths["tools"]).free,
            "output_free_disk_bytes": shutil.disk_usage(paths["output"].parent if paths["output"] else build.parent).free,
            "host_available_ram_bytes": available_memory_bytes(),
            "effective_cgroup_limit_bytes": None,
        }
        if any(value < budget["min_free_bytes"] for key, value in report["resources"].items()
               if key.endswith("free_disk_bytes")):
            report["blockers"].append("free disk is below the selected reserve")
    except OSError:
        report["blockers"].append("disk resource inventory is unavailable")
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def _checkpoint(output, report, paths):
    temporary = output / "report.json.tmp"
    encoded = (json.dumps(_redact(report, paths), indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output / "report.json")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _stamp_paths(case):
    return ["tests/regression/" + case["app"] + "/config.stamp",
            "sw/runtime/" + case["driver"] + "_config.stamp",
            "sw/runtime/" + case["driver"] + "_rt_config.stamp"]


def _defines(text):
    values = {}
    for token in re.findall(r"(?<!\S)-D([A-Za-z_][A-Za-z0-9_]*)(?:=([^\s]+))?", text):
        name, value = token
        if name in values and values[name] != value:
            raise ValueError("configuration stamp contains conflicting defines")
        values[name] = value
    return values


def capture_case(paths, output, case):
    build = paths["build"]
    stamps = _stamp_paths(case)
    identities = hash_artifacts(build, stamps)
    captured = []
    expected = _defines(config_for(case))
    for identity in identities:
        if identity["size_bytes"] > MAX_STAMP_BYTES:
            raise ValueError("configuration stamp exceeds its limit")
        contents = (build / identity["path"]).read_text(encoding="utf-8")
        defines = _defines(contents)
        if any(defines.get(name) != value for name, value in expected.items()):
            raise ValueError("application/backend stamp disagrees with the frozen configuration")
        if any(name.startswith("VX_CFG_TCU_TYPE_") and name != "VX_CFG_TCU_TYPE_TFR"
               or name.startswith("VX_CFG_FPU_TYPE_") and name != "VX_CFG_FPU_TYPE_STD"
               for name in defines):
            raise ValueError("non-native arithmetic appears in the effective configuration")
        if (defines.get("VX_CFG_TCU_TYPE", "TFR") != "TFR"
                or defines.get("VX_CFG_FPU_TYPE", "STD") != "STD"):
            raise ValueError("resolved arithmetic type contradicts the native configuration")
        if defines.get("VX_CFG_XLEN") != "64":
            raise ValueError("configuration stamp does not identify RV64")
        name = case["id"] + "-" + identity["path"].replace("/", "_")
        destination = output / "artifacts" / name
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(_redact(contents, paths))
        copied = hash_artifacts(output, ["artifacts/" + name])[0]
        captured.append({**copied, "source": identity,
                         "redaction": "source/build/tool/output roots replaced by symbolic labels"})
    binaries = ["tests/regression/" + case["app"] + "/" + case["app"],
                "tests/regression/" + case["app"] + "/kernel.vxbin",
                "sw/runtime/libvortex-" + case["driver"] + ".so",
                "sw/runtime/lib" + case["driver"] + ".so"]
    return {"configuration_artifacts": captured,
            "binary_identities": hash_artifacts(build, binaries),
            "native_flags_verified": True}


def reference_passed(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return (len(re.findall(r"^PASSED!\s*$", text, re.MULTILINE)) == 1
            and re.search(r"^(?:FAILED!|Found [1-9][0-9]* errors!)\s*$", text, re.MULTILINE) is None)


def execute_run(args, report, paths=None):
    paths = resolve_paths(args) if paths is None else paths
    output = paths["output"]
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    (output / "artifacts").mkdir()
    report["mode"] = "run"
    report["state"] = "blocked" if report["blockers"] else "running"
    report["outcome"] = "blocked" if report["blockers"] else "not_run"
    _checkpoint(output, report, paths)
    if report["blockers"]:
        return report
    matrix = load_matrix(paths["matrix"])
    if _manifest_identity(paths["matrix"]) != {key: report["matrix"][key] for key in ("sha256", "size_bytes")}:
        report["blockers"].append("matrix changed after prerequisite screening")
        report["outcome"] = report["state"] = "blocked"
        _checkpoint(output, report, paths)
        return report
    selected = select_cases(matrix, report["coverage"]["selected_ids"])
    (output / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    environment = clean_environment(jobs=args.jobs)
    budget = report["budget"]
    run_budget = {name: budget[name] for name in (
        "timeout_seconds", "min_free_bytes", "max_log_bytes", "max_rss_bytes")}
    run_budget["resource_paths"] = (paths["source"], paths["tools"], output)
    configure = [str(paths["source"] / "configure"), "--xlen=64", "--osversion=ubuntu/focal",
                 "--tooldir=" + str(paths["tools"])]

    def command(name, argv, current_environment):
        entry = {"id": name, "argv": argv, "cwd": "$BUILD", "outcome": "not_run",
                 "environment": {key: current_environment[key] for key in (
                     "MAKEFLAGS", "THREADS", "CCACHE_DISABLE", "OBJCACHE", "CONFIGS") if key in current_environment},
                 "log": "logs/" + name + ".log"}
        report["commands"].append(entry)
        report["active_command"] = name
        _checkpoint(output, report, paths)
        entry.update(run_bounded(argv, paths["build"], current_environment,
                                 output / entry["log"], **run_budget))
        report.pop("active_command", None)
        _checkpoint(output, report, paths)
        return entry

    try:
        paths["build"].mkdir(exist_ok=True)
        if not _same_source(report["source_before"], collect_source(paths["source"])):
            raise ValueError("source changed after prerequisite screening")
        _verify_dependencies(paths["source"], report["dependencies"], report,
                             "dependencies_before_execution")
        _verify_tooling(report["tooling_before"], report, "tooling_before_execution")
        report["host_before_execution"] = collect_host(environment)
        if report["host_before_execution"] != report["host_before"]:
            raise ValueError("host tool identities changed after prerequisite screening")
        report["tooling_snapshots"] = _snapshot_tooling(output, report["tooling_before"])
        _checkpoint(output, report, paths)
        for name, argv in (
            ("configure", configure),
            ("kernel-library", ["make", "-j" + str(args.jobs), "-C", "sw/kernel"]),
            ("runtime-stub", ["make", "-j" + str(args.jobs), "-C", "sw/runtime/stub"]),
        ):
            result = command(name, argv, environment)
            if result["outcome"] != "pass":
                report["outcome"] = result["outcome"]
                report["reason"] = "prerequisite command did not pass: " + name
                return report
            if name == "configure":
                report["build_configured"] = collect_build(paths["build"], paths["source"])
                if report["build_configured"]["outcome"] != "pass":
                    raise ValueError("generated build identity failed after configuration")
        for case, result in zip(selected, report["cases"]):
            result["reason"] = "execution in progress"
            report["active_case"] = case["id"]
            _verify_dependencies(paths["source"], report["dependencies"], result,
                                 "dependencies_before")
            _verify_tooling(report["tooling_before"], result, "tooling_before")
            result["source_before"] = collect_source(paths["source"])
            if not _same_source(report["source_before"], result["source_before"]):
                raise ValueError("source changed before case execution")
            prepared = command(case["id"] + "-configure", configure, environment)
            if prepared["outcome"] != "pass":
                result["outcome"] = prepared["outcome"]
                result["reason"] = "case reconfiguration did not pass"
                report["outcome"] = prepared["outcome"]
                return report
            result["build_before"] = collect_build(paths["build"], paths["source"])
            if result["build_before"]["outcome"] != "pass":
                raise ValueError("case build identity failed before execution")
            _verify_dependencies(paths["source"], report["dependencies"], result,
                                 "dependencies_at_launch")
            case_environment = dict(environment, CONFIGS=config_for(case))
            observed = command(case["id"], command_for(case), case_environment)
            result["outcome"] = observed["outcome"]
            result["reason"] = observed["reason"]
            _verify_dependencies(paths["source"], report["dependencies"], result,
                                 "dependencies_after")
            _verify_tooling(report["tooling_before"], result, "tooling_after")
            result["source_after"] = collect_source(paths["source"])
            result["build_after"] = collect_build(paths["build"], paths["source"])
            if not _same_source(report["source_before"], result["source_after"]):
                raise ValueError("source changed during case execution")
            if result["build_after"]["outcome"] != "pass":
                raise ValueError("case build identity failed after execution")
            if observed["outcome"] != "pass":
                report["outcome"] = observed["outcome"]
                return report
            result["reference_marker_verified"] = reference_passed(output / observed["log"])
            if not result["reference_marker_verified"]:
                raise ValueError("case exited successfully without its unique CPU-reference PASSED marker")
            result.update(capture_case(paths, output, case))
            result["reason"] = None
            report.pop("active_case", None)
            _checkpoint(output, report, paths)
        report["tools_after"] = collect_tools(paths["tools"], paths["bundle"])
        if report["tools_after"] != report["tools_before"]:
            raise ValueError("tool identities changed during execution")
        report["host_after"] = collect_host(environment)
        if report["host_after"] != report["host_before"]:
            raise ValueError("host tool identities changed during execution")
        _verify_dependencies(paths["source"], report["dependencies"], report, "dependencies_after")
        _verify_tooling(report["tooling_before"], report, "tooling_after")
        report["outcome"] = "pass"
        report["coverage"]["full_native_matrix_passed"] = report["coverage"]["full_matrix_selected"]
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report["outcome"] = "fail"
        report["reason"] = _redact(str(error), paths)
        for result in report["cases"]:
            if result["id"] == report.get("active_case"):
                result["outcome"] = "fail"
                result["reason"] = report["reason"]
    except KeyboardInterrupt:
        report["outcome"] = "fail"
        report["reason"] = "execution interrupted"
    finally:
        report["finished_at"] = _now()
        report["state"] = "finished"
        report.pop("active_case", None)
        report.pop("active_command", None)
        _checkpoint(output, report, paths)
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "run"))
    parser.add_argument("--source", type=Path, default=HERE.parents[1])
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--tool-dir", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, default=HERE / "p01_baseline.json")
    parser.add_argument("--bundle-manifest", type=Path, default=HERE / "p01_toolchain.lock.json")
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
        reason = _redact(str(error), paths) if paths is not None else "invalid or inaccessible baseline arguments"
        print(json.dumps({"schema_version": 1, "outcome": "blocked", "phase_complete": False,
                          "blockers": [reason]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
