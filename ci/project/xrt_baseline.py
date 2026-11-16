#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0.
"""Plan or run a bounded vendor XRT hardware-emulation smoke without accepting gates."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from baseline_host import collect_host
from baseline_inventory import LIBRARIES, TOOL_BINARIES as BASE_TOOL_BINARIES, _bundle_identity
from baseline_process import GIB, MIB, run_bounded
from preflight import available_memory_bytes
from xrt_contract import (CONFIGS, CONTRACT_ID, MAX_JSON_BYTES, file_identity,
                          load_manifest, read_verified, safe_path)
from xrt_inventory import (BINARY_FILES, STAMP_FILES, inspect_build,
                           inspect_effective, inspect_manifest, probe_environment)
from xrt_runtime import inspect_runtime
from xrt_signals import terminate_as_interrupt


HERE = Path(__file__).resolve().parent
TOOLING_FILES = (
    "xrt_baseline.py", "xrt_contract.py", "xrt_inventory.py", "xrt_runtime.py", "xrt_signals.py", "xrt_source.py", "baseline_host.py",
    "baseline_inventory.py", "baseline_process.py", "preflight.py",
)
TOOL_BINARIES = {**BASE_TOOL_BINARIES, "llvm_clangxx": "llvm-vortex/bin/clang++"}
LICENSE_KEYS = ("XILINXD_LICENSE_FILE", "LM_LICENSE_FILE")
MAX_FAILURE_CHECKPOINT_BYTES = 16 * 1024
RETAINED_CONFIGS = STAMP_FILES + (
    ".config.stamp", "config.mk", "sw/runtime/xrt/xrt.ini",
    "sw/VX_config.h", "sw/VX_types.h", "hw/VX_config.vh", "hw/VX_types.vh",
)
SMOKE_INI = ("[Runtime]\nruntime_log=console\n\n[Emulation]\ndebug_mode=off\n\n"
             "[Debug]\nprofile=false\ntimeline_trace=false\n"
             "data_transfer_trace=off\nstall_trace=off\n")
MARKERS = (
    "open device connection", "data type: integer", "number of points: 16",
    "buffer size: 64 bytes", "upload source buffer0", "upload source buffer1",
    "launch kernel", "download destination buffer", "wait for completion",
    "verify result", "cleanup", "PASSED!",
)
LIMITATIONS = [
    "A passing plan or fixture test is not a GPU execution result.",
    "A passing smoke is a candidate integration result requiring independent acceptance review; phase_complete remains false.",
    "The fixed integer demo checks host-observed transfer, launch, completion and reference milestones, not tensor arithmetic or bus traces.",
    "Vendor hw_emu is not physical FPGA execution; no physical performance or silicon claim follows.",
    "The runner neither installs vendor software nor synthesizes an FPGA image; reviewed matching artifacts must already exist.",
    "File hashes identify selected inputs, not complete vendor installations, platform dependencies or license entitlement.",
    "Resource monitoring samples a Linux process group; it is not a hard quota or containment of descendants that leave that group.",
    "Retained payload writes require their byte size above the disk reserve; only a failure-status checkpoint of at most 16 KiB may use that reserve.",
    "Raw local logs and retained input files can contain machine paths or vendor output; review them before publication.",
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
    for name, value, scale in (
        ("timeout_seconds", args.timeout_seconds, 1),
        ("min_free_bytes", args.min_free_gib, GIB),
        ("max_log_bytes", args.max_log_mib, MIB),
        ("max_rss_bytes", args.max_rss_gib, GIB),
    ):
        try:
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and 0 < value * scale <= 2**63 - 1
                     and (scale == 1 or value * scale >= 1))
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("budgets must be positive, finite and representable")
        result[name] = value if scale == 1 else int(value * scale)
    if result["max_log_bytes"] > 16 * MIB:
        raise ValueError("max-log-mib must not exceed the 16 MiB retained-log ceiling")
    return result


def _path(value, *, exists=False):
    supplied = safe_path(os.path.abspath(value))
    if supplied.resolve(strict=exists) != supplied:
        raise ValueError("input and output roots must not traverse symlinks")
    return supplied


def _overlap(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _fresh_build(build):
    _path(build)
    if not build.parent.is_dir() or (build.exists() and (not build.is_dir() or any(build.iterdir()))):
        raise ValueError("build must be a fresh or empty directory under an existing parent")


def _validate_roots(paths, *, initial=False):
    for key in ("source", "build", "tools", "output"):
        if paths[key] is None:
            raise ValueError("run requires a dedicated output root")
        _path(paths[key], exists=key == "source")
    if initial:
        _fresh_build(paths["build"])
        output = paths["output"]
        if not output.parent.is_dir() or os.path.lexists(output):
            raise ValueError("output must be fresh under an existing parent")
    else:
        for name in ("logs", "artifacts", "tmp"):
            _path(paths["output"] / name, exists=True)


def resolve_paths(args):
    if any(getattr(args, key) is None for key in ("build_dir", "tool_dir", "manifest")):
        raise ValueError("plan/run requires --build-dir, --tool-dir and --manifest")
    paths = {"source": _path(args.source, exists=True),
             "build": _path(args.build_dir), "tools": _path(args.tool_dir),
             "manifest": _path(args.manifest, exists=True),
             "bundle": _path(args.bundle_manifest, exists=True),
             "output": _path(args.output) if args.output is not None else None}
    if not paths["source"].is_dir():
        raise ValueError("source must be a directory")
    if any(_overlap(paths[a], paths[b]) for a, b in (
            ("source", "build"), ("source", "tools"), ("build", "tools"))):
        raise ValueError("source, dedicated build and tool roots must not overlap")
    _fresh_build(paths["build"])
    output = paths["output"]
    if args.mode == "run" and output is None:
        raise ValueError("run requires --output")
    if output is not None:
        if not output.parent.is_dir() or os.path.lexists(output):
            raise ValueError("output must be fresh under an existing parent")
        if any(_overlap(output, paths[key]) for key in ("source", "build", "tools")):
            raise ValueError("output must not overlap source, build or tools")
    return paths


def _input_paths(data):
    records = [data["platform"]["file"], data["build_receipt"], data["qualification_review"]]
    records.extend(data["vendor"]["files"].values())
    records.extend(data["artifacts"].values())
    return [Path(record["path"]) for record in records]


def _validate_outputs(paths, data):
    protected = _input_paths(data) + [paths["manifest"], paths["bundle"]]
    protected.extend(Path(data["vendor"][key]) for key in ("vitis_root", "vivado_root", "xrt_root"))
    for target in (paths["build"], paths["output"]):
        if target is not None and any(_overlap(target, item) for item in protected):
            raise ValueError("build/output overlaps a frozen input")


def _redact(value, paths, data=None):
    replacements = [(str(path), "$" + key.upper()) for key, path in paths.items() if path is not None]
    if data is not None:
        replacements.extend((str(path), "$INPUT_" + str(i)) for i, path in enumerate(_input_paths(data)))
        replacements.extend((data["vendor"][key], "$" + key.upper())
                            for key in ("vitis_root", "vivado_root", "xrt_root"))
        replacements.append((str(Path(data["artifacts"]["xclbin"]["path"]).parent), "$ARTIFACTS"))
    if isinstance(value, str):
        for original, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            value = value.replace(original, replacement)
        return value
    if isinstance(value, list):
        return [_redact(item, paths, data) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, paths, data) for key, item in value.items()}
    return value


def native_inventory(tools, bundle):
    report = {"blockers": [], "identities": {}, "bundle": None}
    try:
        file_identity(bundle, max_bytes=MAX_JSON_BYTES)
        report["bundle"] = _bundle_identity(bundle)
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report["blockers"].append("native tool lock: " + str(error))
    for role, relative in list(TOOL_BINARIES.items()) + [(name, name) for name in LIBRARIES]:
        try:
            selected = (tools / relative).resolve(strict=True)
            if not selected.is_relative_to(tools):
                raise ValueError("native tool lookup escapes its root")
            if role in TOOL_BINARIES and not os.access(selected, os.X_OK):
                raise ValueError("native tool is not executable")
            report["identities"][role] = {"resolved": str(selected), **file_identity(selected)}
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append("native prerequisite " + role + ": " + str(error))
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def tooling_inventory():
    return {name: file_identity(HERE / name, max_bytes=MIB) for name in TOOLING_FILES}


def clean_environment(data, paths, jobs=2, environ=None):
    if type(jobs) is not int or jobs not in (1, 2):
        raise ValueError("jobs must be one or two")
    inherited = os.environ if environ is None else environ
    path = inherited.get("PATH", os.defpath)
    if (type(path) is not str or any(not item or not Path(item).is_absolute()
                                   for item in path.split(":"))):
        raise ValueError("PATH entries must be nonempty absolute directories")
    result = {key: inherited[key] for key in ("PATH", "HOME") + LICENSE_KEYS if key in inherited}
    result["PATH"] = path
    result.update({
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "MAKEFLAGS": "-j" + str(jobs),
        "THREADS": str(jobs), "JOBS": str(jobs), "IMPL_MAX_THREADS": str(jobs),
        "CMAKE_BUILD_PARALLEL_LEVEL": str(jobs), "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "CONFIGS": " ".join(CONFIGS), "TARGET": "hw_emu",
        "XILINX_VITIS": data["vendor"]["vitis_root"],
        "XILINX_VIVADO": data["vendor"]["vivado_root"],
        "XILINX_XRT": data["vendor"]["xrt_root"],
    })
    if paths.get("output") is not None:
        result["TMPDIR"] = str(paths["output"] / "tmp")
    return result


def commands_for(paths, jobs):
    make = ["make", "-j" + str(jobs), "TARGET=hw_emu", "CONFIGS=" + " ".join(CONFIGS),
            "JOBS=" + str(jobs), "IMPL_MAX_THREADS=" + str(jobs)]
    return [
        {"id": "configure", "cwd": str(paths["build"]), "argv": [
            str(paths["source"] / "configure"), "--xlen=64", "--osversion=ubuntu/focal",
            "--tooldir=" + str(paths["tools"])]},
        {"id": "kernel-library", "cwd": str(paths["build"]), "argv": make + ["-C", "sw/kernel"]},
        {"id": "runtime-stub", "cwd": str(paths["build"]), "argv": make + ["-C", "sw/runtime/stub"]},
        {"id": "application", "cwd": str(paths["build"]), "argv": make + ["-C", "tests/regression/demo", "all"]},
        {"id": "vendor-runtime", "cwd": str(paths["build"]), "argv": make + ["-C", "tests/regression/demo", "runtime-xrt"]},
        {"id": "smoke", "cwd": str(paths["build"] / "tests/regression/demo"),
         "argv": [str(paths["build"] / "tests/regression/demo/demo"), "-n1"]},
    ]


def plan_run(args, paths=None):
    paths = resolve_paths(args) if paths is None else paths
    data = load_manifest(paths["manifest"])
    _validate_outputs(paths, data)
    budget = _budget(args)
    report = {"schema_version": 1, "id": CONTRACT_ID, "mode": args.mode,
              "started_at": _now(), "state": "planned", "outcome": "not_run",
              "phase_complete": False, "acceptance": "not_evaluated",
              "driver": "xrt", "target": "hw_emu", "configuration": data["configuration"],
              "budget": budget, "commands": [], "blockers": [],
              "integration": {"gate": "P01-A03", "outcome": "not_run", "exit_code": None},
              "limitations": list(LIMITATIONS),
              "manifest_identity": file_identity(paths["manifest"], max_bytes=MIB),
              "inventory_before": inspect_manifest(data, paths["source"]),
              "native_before": native_inventory(paths["tools"], paths["bundle"]),
              "tooling_before": tooling_inventory(), "planned_commands": commands_for(paths, args.jobs)}
    if report["tooling_before"] != LOADED_TOOLING:
        report["blockers"].append("executing helpers changed after import")
    for key in ("inventory_before", "native_before"):
        report["blockers"].extend(report[key]["blockers"])
    try:
        clean_environment(data, paths, args.jobs)
    except ValueError as error:
        report["blockers"].append(str(error))
    resource_paths = [paths["source"], paths["build"].parent, paths["tools"],
                      Path(tempfile.gettempdir())]
    if paths["output"] is not None:
        resource_paths.append(paths["output"].parent)
    resource_paths.append(Path(data["artifacts"]["xclbin"]["path"]).parent)
    report["resources"] = {"free_disk_bytes": [], "host_available_ram_bytes": available_memory_bytes(),
                           "effective_cgroup_limit_bytes": None}
    for path in resource_paths:
        try:
            free = shutil.disk_usage(path).free
            report["resources"]["free_disk_bytes"].append({"path": str(path), "bytes": free})
            if free < budget["min_free_bytes"]:
                report["blockers"].append("free disk is below the selected reserve")
        except OSError:
            report["blockers"].append("resource filesystem is unavailable")
    if sys.platform != "linux" or not Path("/proc/self/stat").is_file():
        report["blockers"].append("bounded execution requires Linux /proc process-group monitoring")
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    if report["blockers"]:
        report["integration"]["outcome"] = "blocked"
    return report


def reference_passed(path):
    identity = file_identity(path, max_bytes=16 * MIB)
    text = read_verified({"path": str(path), **identity}, max_bytes=16 * MIB).decode("utf-8", errors="replace")
    lines = text.splitlines()
    if any(lines.count(marker) != 1 for marker in MARKERS):
        return False
    if [lines.index(marker) for marker in MARKERS] != sorted(lines.index(marker) for marker in MARKERS):
        return False
    for prefix in ("data type:", "number of points:", "buffer size:"):
        if sum(line.startswith(prefix) for line in lines) != 1:
            return False
    return re.search(r"\b(?:FAILED|FAILURE|ERROR)\b|Found [1-9][0-9]* errors!|XRT exception",
                     text, re.IGNORECASE) is None


class _DiskReserveError(RuntimeError):
    pass


def _require_disk_space(path, minimum, required=0):
    if shutil.disk_usage(path).free < minimum + required:
        raise _DiskReserveError("free disk is below the selected reserve")


def _failure_checkpoint(report):
    compact = {key: report[key] for key in (
        "schema_version", "id", "mode", "state", "outcome", "phase_complete",
        "acceptance", "started_at", "finished_at", "integration") if key in report}
    compact["checkpoint_scope"] = "failure_status_only"
    compact["reason"] = str(report.get("reason", "execution is blocked"))[:512]
    compact["blockers"] = [str(item)[:256] for item in report.get("blockers", [])[:2]]
    compact["commands"] = [{key: entry[key] for key in (
        "id", "outcome", "exit_code", "log") if key in entry}
        for entry in report["commands"]]
    return compact


def _checkpoint(output, report, paths, data):
    _path(output, exists=True)
    temporary = output / "report.json.tmp"
    content = (json.dumps(_redact(report, paths, data), indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    try:
        _require_disk_space(output, report["budget"]["min_free_bytes"], len(content))
    except _DiskReserveError:
        if report["outcome"] not in ("blocked", "fail"):
            raise
        # Bounded failure metadata may cross the reserve so the last checkpoint
        # cannot falsely remain running after resource exhaustion.
        content = (json.dumps(_redact(_failure_checkpoint(report), paths, data),
                              sort_keys=True, allow_nan=False) + "\n").encode()
        if len(content) > MAX_FAILURE_CHECKPOINT_BYTES:
            raise ValueError("compact failure checkpoint exceeds its size limit")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output / "report.json")
    finally:
        temporary.unlink(missing_ok=True)


def _write_retained(destination, contents, min_free_bytes):
    _path(destination)
    _require_disk_space(destination.parent, min_free_bytes, len(contents))
    with destination.open("xb") as stream:
        stream.write(contents)


def _retain(path, destination, expected=None, *, min_free_bytes, max_bytes=MIB):
    identity = file_identity(path, max_bytes=max_bytes)
    if expected is not None and identity != expected:
        raise ValueError("retained input differs from its frozen identity")
    contents = read_verified({"path": str(path), **identity}, max_bytes=max_bytes)
    _write_retained(destination, contents, min_free_bytes)
    return {"path": str(destination), **identity}


@terminate_as_interrupt()
def execute_run(args, report, paths=None):
    paths = resolve_paths(args) if paths is None else paths
    _validate_roots(paths, initial=True)
    data, load_error = None, None
    try:
        if file_identity(paths["manifest"], max_bytes=MIB) != report["manifest_identity"]:
            raise ValueError("manifest changed after planning")
        data = load_manifest(paths["manifest"])
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        load_error = str(error)
    if data is not None:
        _validate_outputs(paths, data)
    output = paths["output"]
    output.mkdir(mode=0o700)
    for name in ("logs", "artifacts", "tmp"):
        _path(output / name).mkdir(mode=0o700)
    report["mode"] = "run"
    report["state"] = "blocked" if report["blockers"] else "running"
    report["outcome"] = "blocked" if report["blockers"] else "not_run"
    if load_error is not None:
        report.update(state="finished", outcome="fail", finished_at=_now(),
                      reason="manifest became invalid after planning: " + load_error)
        _checkpoint(output, report, paths, data)
        return report
    if report["blockers"]:
        report["finished_at"] = _now()
        _checkpoint(output, report, paths, data)
        return report
    environment, smoke_environment = None, None
    budget = {key: report["budget"][key] for key in (
        "timeout_seconds", "min_free_bytes", "max_log_bytes", "max_rss_bytes")}
    budget["resource_paths"] = (paths["source"], paths["build"], paths["tools"], output,
                                Path(data["artifacts"]["xclbin"]["path"]).parent, output / "tmp",
                                Path(tempfile.gettempdir()))

    def check_resources():
        for path in budget["resource_paths"]:
            selected = path.parent if path == paths["build"] and not path.exists() else path
            _require_disk_space(selected, budget["min_free_bytes"])

    def frozen():
        _validate_roots(paths)
        check_resources()
        if file_identity(paths["manifest"], max_bytes=MIB) != report["manifest_identity"]:
            raise ValueError("manifest changed after planning")
        observed = inspect_manifest(data, paths["source"])
        if observed != report["inventory_before"] or observed["outcome"] != "pass":
            raise ValueError("source, vendor inputs or artifact provenance changed after planning")
        if native_inventory(paths["tools"], paths["bundle"]) != report["native_before"]:
            raise ValueError("native tool identities changed after planning")
        if tooling_inventory() != report["tooling_before"]:
            raise ValueError("executing helpers changed after planning")
        if "host_before" in report and collect_host(environment) != report["host_before"]:
            raise ValueError("host tool identities changed during execution")
        return observed

    try:
        _checkpoint(output, report, paths, data)
        environment = clean_environment(data, paths, args.jobs)
        frozen()
        report["host_before"] = collect_host(environment)
        if report["host_before"]["outcome"] != "pass":
            report["blockers"].extend(report["host_before"]["blockers"])
            report["outcome"] = report["integration"]["outcome"] = "blocked"
            return report
        _fresh_build(paths["build"])
        paths["build"].mkdir(mode=0o700, exist_ok=True)
        artifacts = output / "artifacts"
        _path(artifacts / "tooling").mkdir(mode=0o700)
        retained_budget = {"min_free_bytes": budget["min_free_bytes"]}
        report["retained"] = [_retain(paths["manifest"], artifacts / "manifest.json",
                                      report["manifest_identity"], **retained_budget)]
        for name, identity in report["tooling_before"].items():
            report["retained"].append(_retain(HERE / name, artifacts / "tooling" / name,
                                              identity, **retained_budget))
        for key in ("build_receipt", "qualification_review"):
            expected = {name: data[key][name] for name in ("sha256", "size_bytes")}
            report["retained"].append(_retain(Path(data[key]["path"]), artifacts / key,
                                              expected, **retained_budget))
        emconfig = data["artifacts"]["emconfig"]
        report["retained"].append(_retain(
            Path(emconfig["path"]), artifacts / "emconfig.json",
            {key: emconfig[key] for key in ("sha256", "size_bytes")}, **retained_budget))
        _path(artifacts / "build-logs").mkdir(mode=0o700)
        for index, command in enumerate(report["inventory_before"]["receipt_commands"]):
            log = command["log"]
            report["retained"].append(_retain(
                Path(log["path"]), artifacts / "build-logs" / (str(index) + ".log"),
                {key: log[key] for key in ("sha256", "size_bytes")},
                max_bytes=16 * MIB, **retained_budget))
        ini = artifacts / "xrt.ini"
        _write_retained(ini, SMOKE_INI.encode("utf-8"), budget["min_free_bytes"])
        ini_identity = file_identity(ini, max_bytes=MIB)
        report["smoke_ini"] = {"path": str(ini), **ini_identity}
        for planned in commands_for(paths, args.jobs):
            frozen()
            current = dict(environment)
            if planned["id"] == "smoke":
                report["build_before_smoke"] = inspect_build(paths["build"], paths["source"])
                report["effective_before"] = inspect_effective(paths["build"])
                if any(report[key]["outcome"] != "pass" for key in ("build_before_smoke", "effective_before")):
                    raise ValueError("generated vendor build or effective configuration failed validation")
                report["configuration_before"] = {
                    name: file_identity(paths["build"] / name, max_bytes=MIB)
                    for name in RETAINED_CONFIGS}
                if file_identity(ini, max_bytes=MIB) != ini_identity:
                    raise ValueError("smoke INI changed before launch")
                current.update({"VORTEX_DRIVER": "xrt", "XCL_EMULATION_MODE": "hw_emu",
                                "XCLBIN_PATH": data["artifacts"]["xclbin"]["path"],
                                "EMCONFIG_PATH": str(Path(data["artifacts"]["emconfig"]["path"]).parent),
                                "XRT_INI_PATH": str(ini), "XRT_DEVICE_INDEX": "0",
                                "LD_LIBRARY_PATH": str(paths["build"] / "sw/runtime") + ":" + data["vendor"]["xrt_root"] + "/lib"})
                smoke_environment = current
                report["runtime_before"] = inspect_runtime(data, paths["build"], smoke_environment)
                if report["runtime_before"]["outcome"] != "pass":
                    raise ValueError("generated vendor runtime loader binding failed validation")
            entry = dict(planned, outcome="not_run", exit_code=None, log="logs/" + planned["id"] + ".log")
            _path(output / entry["log"])
            report["commands"].append(entry)
            report["active_command"] = planned["id"]
            _checkpoint(output, report, paths, data)
            _validate_roots(paths)
            if planned["id"] == "configure":
                _fresh_build(paths["build"])
            _path(Path(planned["cwd"]), exists=True)
            if "-C" in planned["argv"]:
                _path(Path(planned["cwd"]) / planned["argv"][planned["argv"].index("-C") + 1], exists=True)
            _path(output / entry["log"])
            entry.update(run_bounded(planned["argv"], Path(planned["cwd"]), current, output / entry["log"], **budget))
            if planned["id"] == "smoke":
                report["integration"].update(outcome="fail", exit_code=entry["exit_code"])
            report.pop("active_command", None)
            _checkpoint(output, report, paths, data)
            if entry["outcome"] != "pass" or not entry.get("cleanup_complete", False):
                report["outcome"] = "blocked" if entry["outcome"] == "blocked" else "fail"
                report["reason"] = "command did not pass: " + planned["id"]
                if planned["id"] == "smoke":
                    report["integration"].update(outcome=report["outcome"], exit_code=entry["exit_code"])
                return report
            frozen()
            if planned["id"] == "configure":
                report["build_configured"] = inspect_build(paths["build"], paths["source"])
                if report["build_configured"]["outcome"] != "pass":
                    raise ValueError("fresh generated build identity failed")
            if planned["id"] == "smoke":
                report["integration"]["exit_code"] = entry["exit_code"]
                report["reference_markers_verified"] = reference_passed(output / entry["log"])
                if not report["reference_markers_verified"]:
                    raise ValueError("smoke lacks the unique ordered integer reference milestones")
        for relative in RETAINED_CONFIGS:
            report["retained"].append(_retain(
                paths["build"] / relative, artifacts / relative.replace("/", "_"),
                report["configuration_before"][relative], **retained_budget))
        report["binary_identities"] = {name: file_identity(paths["build"] / name) for name in BINARY_FILES}
        report["effective_after"] = inspect_effective(paths["build"])
        check_resources()
        report["build_after"] = inspect_build(paths["build"], paths["source"])
        report["host_after"] = collect_host(environment)
        report["inventory_after"] = frozen()
        report["runtime_after"] = inspect_runtime(data, paths["build"], smoke_environment)
        if (report["effective_after"] != report["effective_before"]
                or report["build_after"] != report["build_before_smoke"]
                or report["host_after"] != report["host_before"]
                or report["runtime_after"] != report["runtime_before"]
                or report["runtime_after"]["outcome"] != "pass"
                or file_identity(ini, max_bytes=MIB) != ini_identity
                or any(report["binary_identities"][name] != report["effective_before"]["identities"][name]
                       for name in BINARY_FILES)):
            raise ValueError("build, host, runtime binding or smoke configuration changed during execution")
        for entry in report["commands"]:
            if file_identity(output / entry["log"], max_bytes=16 * MIB) != {
                    "sha256": entry["log_sha256"], "size_bytes": entry["log_size_bytes"]}:
                raise ValueError("command log changed after execution")
        for record in report["retained"]:
            if file_identity(record["path"], max_bytes=16 * MIB) != {
                    key: record[key] for key in ("sha256", "size_bytes")}:
                raise ValueError("retained artifact changed before final recording")
        report["outcome"] = report["integration"]["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report["outcome"] = "fail"
        report["reason"] = _redact(str(error), paths, data)
        if report["integration"]["exit_code"] is not None:
            report["integration"]["outcome"] = "fail"
    except KeyboardInterrupt:
        report["outcome"] = "fail"
        report["reason"] = "execution interrupted"
    finally:
        report["finished_at"] = _now()
        report["state"] = "finished"
        report.pop("active_command", None)
        try:
            _checkpoint(output, report, paths, data)
        except _DiskReserveError as error:
            report["outcome"] = "fail"
            report["reason"] = str(error)
            if report["integration"]["exit_code"] is not None:
                report["integration"]["outcome"] = "fail"
            _checkpoint(output, report, paths, data)
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "plan", "run"))
    parser.add_argument("--source", type=Path, default=HERE.parents[1])
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--tool-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bundle-manifest", type=Path, default=HERE / "p01_toolchain.lock.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=_positive, default=1800)
    parser.add_argument("--min-free-gib", type=_positive, default=15)
    parser.add_argument("--max-log-mib", type=_positive, default=16)
    parser.add_argument("--max-rss-gib", type=_positive, default=6)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    paths, data = None, None
    try:
        if args.mode == "probe":
            report = probe_environment()
            report.update(schema_version=1, mode="probe", id=CONTRACT_ID)
        else:
            paths = resolve_paths(args)
            data = load_manifest(paths["manifest"])
            report = plan_run(args, paths)
            if args.mode == "run":
                report = execute_run(args, report, paths)
            report = _redact(report, paths, data)
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        reason = _redact(str(error), paths, data) if paths is not None else "invalid or inaccessible XRT baseline arguments"
        print(json.dumps({"schema_version": 1, "outcome": "blocked", "phase_complete": False,
                          "acceptance": "not_evaluated", "blockers": [reason]}, sort_keys=True))
        return 1


LOADED_TOOLING = tooling_inventory()


if __name__ == "__main__":
    sys.exit(main())
