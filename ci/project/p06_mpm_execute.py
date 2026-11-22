#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and separately execute native MPM transport units in fresh trees.

The exit status covers the selected cells; the report always lists all eight
required cells. Formal runs require clean, tracked source. --development permits
investigation with incomplete tracking/submodule metadata. Neither mode grants
acceptance or qualifies historical packets. Dependencies must already be installed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _digest, _git, collect_source, hash_artifacts
from baseline_process import GIB, MIB, LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
BUDGET = {"max_rss_bytes": 4 * GIB, "min_free_bytes": 15 * GIB, "max_log_bytes": 16 * MIB}
TIMEOUTS = {"configure": 120, "build": 1800, "run": 180}
UNITS = {"rtl": "hw/unittest/mpm_transport", "simx": "sim/simx"}
BINARIES = {"rtl": "mpm_transport", "simx": "mpm_transport_test"}
HELPERS = tuple("ci/project/" + name for name in (
    "p06_mpm_execute.py", "baseline_inventory.py", "baseline_process.py", "preflight.py"))
CRITICAL = HELPERS + (
    "configure", "config.mk.in", "VERSION", ".gitmodules", "VX_config.toml",
    "VX_types.toml", "vortex_opae.toml", "ci/gen_config.py",
    "docs/designs/host_mpm_transport_v1.md", "hw/unittest/common.mk", "hw/unittest/common/vl_simulator.h",
    "hw/unittest/verilator.vlt.in", "hw/unittest/mpm_transport/Makefile",
    "hw/unittest/mpm_transport/main.cpp", "hw/unittest/mpm_transport/VX_mpm_transport_top.sv",
    "hw/rtl/VX_gpu_pkg.sv", "hw/rtl/VX_trace_pkg.sv", "hw/rtl/core/VX_dcr_data.sv",
    "hw/rtl/core/VX_csr_mpm.sv", "hw/rtl/core/VX_csr_data.sv",
    "sim/common.mk", "sim/simx/Makefile", "sim/simx/mpm_transport.mk", "sim/simx/core.cpp", "sim/simx/core.h",
    "sim/simx/csr_unit.cpp", "sim/simx/csr_unit.h", "sim/simx/processor.cpp",
    "sim/simx/cluster.cpp", "sim/simx/socket.cpp", "tests/unittest/mpm_transport/main.cpp",
    "sw/runtime/common/perf.cpp",
)
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "sw/vortex_opae.h", "hw/VX_config.vh", "hw/VX_types.vh", "hw/vortex_opae.vh",
             "hw/unittest/verilator.vlt")
COPIED = ("ci/gen_config.py", "hw/unittest/common.mk", "hw/unittest/mpm_transport/Makefile",
          "sim/common.mk", "sim/simx/Makefile", "sim/simx/mpm_transport.mk")
DEPENDENCIES = ("third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
                "third_party/ramulator/libramulator.so", "third_party/ramulator_ext/libramulator-vortex.so")
LOADED_HELPERS = hash_artifacts(ROOT, HELPERS)
LIMITATIONS = [
    "Selected-cell success does not establish completion of the eight-cell required matrix.",
    "Development runs are nonqualifying even when every selected cell passes.",
    "Development hashes cover critical inputs, not a reproducible archive of every dirty or cached source file.",
    "These are native directed units: the RTL leaf has no VX_csr_data/full AFU; SimX uses its model route.",
    "Public-runtime end-to-end execution, wider topology, parent regressions and timing comparisons are separate.",
    "No phase acceptance, historical counter qualification, absolute no-wrap bound or hardware result is claimed.",
    "Tools and dependency libraries are reused; hashes do not inventory all host headers/support files/dynamic libraries.",
    "Logs/configuration retain local paths; binaries stay in the work tree and are identified, not archived.",
    "Before/after identities do not defend against malicious concurrent filesystem writers.",
    *PROCESS_LIMITATIONS,
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_paths(args):
    paths = {}
    for name, value in (("source", args.source_dir), ("tools", args.tools_dir),
                        ("work", args.work_dir), ("output", args.output)):
        path = Path(os.path.abspath(value))
        require(re.fullmatch(r"[A-Za-z0-9_./+-]+", str(path)) and path.resolve() == path,
                name + " path must be a safe literal without symlink traversal")
        paths[name] = path
    require(paths["source"] == ROOT, "execute the runner from the selected source checkout")
    require(all(paths[name].is_dir() for name in ("source", "tools")), "source/tools directory missing")
    for name in ("work", "output"):
        path = paths[name]
        require(not os.path.lexists(path) and path.parent.is_dir(), name + " must be fresh under an existing parent")
        require(not any(path.is_relative_to(other) or other.is_relative_to(path)
                        for key, other in paths.items() if key != name), name + " overlaps another root")
    return paths


def clean_environment(work):
    path = [entry for entry in os.environ.get("PATH", os.defpath).split(os.pathsep)
            if entry and Path(entry).is_absolute()]
    path += [str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    return {"PATH": os.pathsep.join(dict.fromkeys(path)), "HOME": str(work / "home"),
            "TMPDIR": str(work / "tmp"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1",
            "MAKEFLAGS": "-j2", "THREADS": "1", "CMAKE_BUILD_PARALLEL_LEVEL": "2"}


def source_snapshot(source):
    checkout = collect_source(source)
    tracked = set(_git(source, "ls-files", "-z", "--", *CRITICAL).decode("utf-8").split("\0"))
    return {"checkout": checkout, "untracked_critical": sorted(set(CRITICAL) - tracked),
            "files": hash_artifacts(source, sorted(CRITICAL))}


def check_source(snapshot, development):
    checkout = snapshot["checkout"]
    require(all(re.fullmatch(r"[0-9a-f]{40}", str(checkout[key])) for key in ("revision", "tree")),
            "source revision/tree identity unavailable")
    if development:
        return
    require(not checkout["blockers"], "source identity blocked: " + "; ".join(checkout["blockers"]))
    require(checkout["dirty"] is False and not snapshot["untracked_critical"],
            "formal execution requires clean source and every critical input tracked")


def file_identity(path):
    path = Path(path).absolute()
    resolved = path.resolve(strict=True)
    digest, size = _digest(resolved)
    return {"path": str(path), "resolved_path": str(resolved), "sha256": digest, "size_bytes": size}


def tools_snapshot(paths, env, engines):
    selected = {name: shutil.which(name, path=env["PATH"])
                for name in ("make", "g++", "gcc", "ar", "as", "ld", "bash", "python3")}
    if "rtl" in engines:
        selected.update({name: paths["tools"] / "verilator/bin" / name
                         for name in ("verilator", "verilator_bin")})
        selected["perl"] = shutil.which("perl", path=env["PATH"])
    ccache = shutil.which("ccache", path=env["PATH"])
    if ccache:
        selected["ccache"] = ccache
    result = {"tools": {}, "dependencies": {}, "missing": []}
    for name, path in selected.items():
        try:
            require(path is not None and os.access(path, os.X_OK), "tool unavailable")
            result["tools"][name] = file_identity(path)
        except (OSError, ValueError, RuntimeError):
            result["missing"].append(name)
    if "simx" in engines:
        for name in DEPENDENCIES:
            try:
                result["dependencies"][name] = file_identity(paths["source"] / name)
            except (OSError, ValueError, RuntimeError):
                result["missing"].append(name)
    return result


def generated_identity(build, source, tools, xlen, osversion):
    text = (build / "config.mk").read_text(encoding="utf-8")
    expected = {"XLEN": str(xlen), "PROFILE": "", "VORTEX_HOME": str(source), "TOOLDIR": str(tools)}
    if osversion:
        expected["OSVERSION"] = osversion
    for name, value in expected.items():
        require(re.findall(r"^" + name + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE) == [value],
                "generated configuration differs: " + name)
    for name in COPIED:
        require((build / name).read_bytes() == (source / name).read_bytes(), "copied input differs: " + name)
    return hash_artifacts(build, GENERATED + COPIED)


def verify_output(text, cell):
    if cell["engine"] == "simx":
        header = "MPM transport: XLEN=" + str(cell["xlen"]) + " PERF=" + cell["perf"]
        require(text.splitlines().count(header) == 1, "SimX configuration banner missing or repeated")
        matches = re.findall(r"^PASSED: ([1-9][0-9]*) MPM transport checks$", text, re.MULTILINE)
        require(len(matches) == 1, "SimX completion marker missing or repeated")
        return {"checks": int(matches[0])}
    pattern = (r"^PASSED mpm_transport RV" + str(cell["xlen"]) + r" PERF="
               + str(int(cell["perf"] == "on")) + r" TCU=([01]) read_count=([1-9][0-9]*) "
               r"assertion_count=([1-9][0-9]*) ignored=([1-9][0-9]*) response_edges=2 counter_bits=44$")
    matches = re.findall(pattern, text, re.MULTILINE)
    require(len(matches) == 1, "RTL completion/configuration marker missing or repeated")
    return dict(zip(("tcu_enabled", "read_count", "assertion_count", "ignored"), map(int, matches[0])))


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    widths = (32, 64) if args.xlen == "both" else (int(args.xlen),)
    engines = ("rtl", "simx") if args.engines == "both" else (args.engines,)
    cells = [{"id": f"rv{xlen}-perf-{perf}-{engine}", "xlen": xlen, "perf": perf,
              "engine": engine, "selected": xlen in widths and engine in engines,
              "outcome": "not_run", "run_outcome": "not_run", "reason": "not selected"}
             for xlen in (32, 64) for perf in ("off", "on") for engine in ("rtl", "simx")]
    report = {"schema_version": 1, "contract_id": "host-mpm-transport-v1", "started_at": now(),
              "state": "running", "outcome": "blocked", "development": args.development,
              "acceptance_claimed": False, "qualified": False, "absolute_no_wrap_bound": "not_established",
              "formal_qualification_eligible": False, "selected_matrix_complete": False,
              "full_matrix_completed": False, "full_matrix_outcome": "not_run", "cells": cells,
              "paths": {key: str(value) for key, value in paths.items()}, "commands": [], "variants": [],
              "budget": dict(BUDGET, jobs=2, threads=1, timeouts_seconds=TIMEOUTS), "limitations": LIMITATIONS}
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    initial_source = initial_tools = None
    env = clean_environment(work)

    def checkpoint():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")

    def command(name, argv, cwd, environment, timeout):
        entry = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "environment": environment,
                 "timeout_seconds": timeout, "log": "logs/" + name + ".log", "outcome": "not_run"}
        report["commands"].append(entry)
        checkpoint()
        entry.update(run_bounded(entry["argv"], cwd, environment, output / entry["log"],
                                 timeout_seconds=timeout, resource_paths=tuple(paths.values()), **BUDGET))
        checkpoint()
        return entry

    def check_budget(entry):
        require(entry["cleanup_complete"] and entry["reason"] not in
                {"disk_reserve", "memory_limit", "log_limit", "resource_inventory_unavailable", "monitor_failed"}
                and not str(entry["reason"]).startswith("interrupted"), "execution stopped: " + str(entry["reason"]))

    def stable():
        require(source_snapshot(source) == initial_source, "source changed during execution")
        require(tools_snapshot(paths, env, engines) == initial_tools, "tools or dependency libraries changed")

    def retain(build, identities, prefix):
        names = []
        for item in identities:
            destination = output / "artifacts" / prefix / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(build / item["path"], destination)
            names.append(destination.relative_to(output).as_posix())
        copied = hash_artifacts(output, names)
        require([(item["sha256"], item["size_bytes"]) for item in copied] ==
                [(item["sha256"], item["size_bytes"]) for item in identities], "retained configuration changed")
        return copied

    try:
        checkpoint()
        work.mkdir(mode=0o700)
        for name in ("home", "tmp"):
            (work / name).mkdir()
        report["environment"] = env
        report["available_memory_bytes"] = available_memory_bytes()
        report["free_disk_bytes"] = {name: shutil.disk_usage(path).free for name, path in paths.items()}
        require(all(value >= BUDGET["min_free_bytes"] for value in report["free_disk_bytes"].values()),
                "disk reserve is below 15 GiB")
        require(report["available_memory_bytes"] is not None and report["available_memory_bytes"] >= 4 * GIB,
                "at least 4 GiB available memory is required")
        require(hash_artifacts(source, HELPERS) == LOADED_HELPERS, "executing helper bytes changed after import")
        initial_source = report["source_before"] = source_snapshot(source)
        check_source(initial_source, args.development)
        initial_tools = report["tools_before"] = tools_snapshot(paths, env, engines)
        require(not initial_tools["missing"], "missing installed prerequisites: " + ", ".join(initial_tools["missing"]))
        for name in ("make", "g++", "python3", *(("verilator",) if "rtl" in engines else ())):
            result = command("version-" + name.replace("+", "p"),
                             [initial_tools["tools"][name]["path"], "--version"], work, env, 30)
            check_budget(result)
            require(result["outcome"] == "pass", "tool version command failed: " + name)
        for xlen in widths:
            for perf in ("off", "on"):
                name = f"rv{xlen}-perf-{perf}"
                build = work / name
                build.mkdir()
                variant = {"id": name, "build_dir": str(build)}
                report["variants"].append(variant)
                active = [cell for cell in cells if cell["selected"] and cell["xlen"] == xlen and cell["perf"] == perf]
                environment = dict(env, PERF="1") if perf == "on" else dict(env)
                configure = [source / "configure", "--xlen=" + str(xlen), "--profile=",
                             "--tooldir=" + str(paths["tools"])]
                if args.osversion:
                    configure.append("--osversion=" + args.osversion)
                stable()
                configured = command(name + "-configure", configure, build, environment, TIMEOUTS["configure"])
                variant["configure"] = configured["id"]
                check_budget(configured)
                if configured["outcome"] != "pass":
                    for cell in active:
                        cell.update(outcome="blocked", reason="configure failed: " + str(configured["reason"]))
                    continue
                variant["generated_before"] = generated_identity(build, source, paths["tools"], xlen, args.osversion)
                variant["retained_configuration"] = retain(build, variant["generated_before"], name)
                for cell in active:
                    unit = build / UNITS[cell["engine"]]
                    binary = unit / BINARIES[cell["engine"]]
                    cell.update(reason=None, build_dir=str(unit), binary_path=str(binary))
                    target = "all" if cell["engine"] == "rtl" else str(binary)
                    build_result = command(cell["id"] + "-build", [initial_tools["tools"]["make"]["path"],
                        "--no-print-directory", "-j2", "THREADS=1", "CONFIGS=", "PROFILE=",
                        "PERF=" + ("1" if perf == "on" else ""),
                        *(["-f", "mpm_transport.mk"] if cell["engine"] == "simx" else []), target], unit, environment, TIMEOUTS["build"])
                    cell["build_command"] = build_result["id"]
                    cell["build_outcome"] = build_result["outcome"]
                    check_budget(build_result)
                    if build_result["outcome"] != "pass":
                        cell.update(outcome=build_result["outcome"], reason="build failed: " + str(build_result["reason"]))
                        continue
                    require(binary.is_file() and os.access(binary, os.X_OK), "native binary missing or not executable")
                    cell["binary_before"] = file_identity(binary)
                    if cell["engine"] == "simx":
                        cell["compiler_stamp"] = retain(build, hash_artifacts(build, ["sim/simx/simx_config.stamp"]), name)
                    stable()
                    run = command(cell["id"] + "-run", [binary], unit, environment, TIMEOUTS["run"])
                    cell.update(run_command=run["id"], run_outcome=run["outcome"], outcome=run["outcome"],
                                run_process_started=run["process_started"], reason=run["reason"])
                    cell["binary_after"] = file_identity(binary)
                    check_budget(run)
                    require(cell["binary_before"] == cell["binary_after"], "native binary changed during execution")
                    if run["outcome"] == "pass":
                        try:
                            cell["observations"] = verify_output((output / run["log"]).read_text(encoding="utf-8"), cell)
                        except (UnicodeError, ValueError) as error:
                            cell.update(outcome="fail", reason=str(error))
                    checkpoint()
                variant["generated_after"] = generated_identity(build, source, paths["tools"], xlen, args.osversion)
                require(variant["generated_before"] == variant["generated_after"], "generated configuration changed")
                stable()
        selected = [cell for cell in cells if cell["selected"]]
        report["outcome"] = ("pass" if all(cell["outcome"] == "pass" for cell in selected)
                             else "fail" if any(cell["outcome"] == "fail" for cell in selected) else "blocked")
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report.update(outcome="fail" if any(item.get("process_started") for item in report["commands"]) else "blocked",
                      reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="runner interrupted")
    finally:
        for variant in report["variants"]:
            if "generated_before" in variant:
                try:
                    variant["generated_after"] = hash_artifacts(Path(variant["build_dir"]), GENERATED + COPIED)
                    require(variant["generated_before"] == variant["generated_after"], "generated configuration changed")
                except (OSError, ValueError, RuntimeError) as error:
                    report.update(outcome="fail", reason=str(error))
        for cell in cells:
            if "binary_before" in cell:
                try:
                    cell["binary_after"] = file_identity(cell["binary_path"])
                    require(cell["binary_before"] == cell["binary_after"], "native binary changed during execution")
                except (OSError, ValueError, RuntimeError) as error:
                    report.update(outcome="fail", reason=str(error))
        for key, original, observe in (("source", initial_source, lambda: source_snapshot(source)),
                                       ("tools", initial_tools, lambda: tools_snapshot(paths, env, engines))):
            if original is not None:
                try:
                    report[key + "_after"] = observe()
                    report[key + "_stable"] = report[key + "_after"] == original
                    require(report[key + "_stable"], key + " changed during execution")
                except (OSError, ValueError, RuntimeError, UnicodeError) as error:
                    report.update(outcome="fail", reason=str(error))
        for cell in cells:
            if cell["selected"] and cell["outcome"] == "not_run":
                cell.update(outcome="blocked", reason=report.get("reason", "required earlier stage did not finish"))
        report["selected_matrix_complete"] = report["outcome"] == "pass"
        report["full_matrix_completed"] = all(cell.get("run_process_started", False) for cell in cells)
        report["full_matrix_outcome"] = (report["outcome"] if report["full_matrix_completed"] else "not_run")
        report["formal_qualification_eligible"] = (report["outcome"] == "pass" and report["full_matrix_completed"]
                                                   and not args.development)
        report.update(state="finished", finished_at=now())
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--xlen", choices=("32", "64", "both"), default="both")
    parser.add_argument("--engines", choices=("rtl", "simx", "both"), default="both")
    parser.add_argument("--osversion", help="Explicit configure OS bundle (otherwise configure detects it)")
    parser.add_argument("--development", action="store_true", help="Permit incomplete source tracking/submodules; never qualifies")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        require(args.osversion is None or re.fullmatch(r"[A-Za-z0-9_/-]+", args.osversion), "invalid OS bundle")
        paths = resolve_paths(args)
        report = execute(args, paths)
    except (OSError, ValueError, RuntimeError) as error:
        print("MPM transport runner blocked: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "selected_matrix_complete": report["selected_matrix_complete"],
                      "full_matrix_completed": report["full_matrix_completed"], "report": str(paths["output"] / "report.json")}))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
