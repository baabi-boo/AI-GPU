#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Retain native RV64 failures from the pinned, unrepaired MPM transport.

The parent commit must already be available in the candidate's Git object store.
Only a separate reference checkout receives the identical candidate test harnesses.
An expected numerical failure is regression sensitivity evidence, not qualification.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _git, hash_artifacts
from baseline_process import GIB, run_bounded
from preflight import available_memory_bytes
import p06_mpm_execute as native


PARENT = "4df7186edbca82b21b2b8cba9b3b192248b99209"
SELF = "ci/project/p06_mpm_parent.py"
OVERLAY = (
    "hw/unittest/mpm_transport/Makefile",
    "hw/unittest/mpm_transport/VX_mpm_transport_top.sv",
    "hw/unittest/mpm_transport/main.cpp",
    "tests/unittest/mpm_transport/main.cpp",
    "sim/simx/mpm_transport.mk",
)
REFERENCE_INPUTS = tuple(name for name in native.CRITICAL
                         if name not in native.HELPERS
                         and name != "docs/designs/host_mpm_transport_v1.md")
LOADED = hash_artifacts(native.ROOT, (SELF,) + native.HELPERS)


def verify_expected_failure(text, engine, result):
    native.require(result.get("process_started") is True and result.get("cleanup_complete") is True
                   and result.get("outcome") == "fail" and result.get("exit_code") == 1
                   and result.get("reason") == "nonzero_exit", "native process did not exit with an assertion failure")
    native.require("PASSED" not in text, "parent unexpectedly reported success")
    failures = [line for line in text.splitlines() if line.startswith("FAIL")]
    if engine == "rtl":
        native.require(len(failures) == 1 and re.fullmatch(
            r"FAIL RV64 tick=[0-9]+ tag=00220001: expected=00000001 actual=00000000",
            failures[0]), "RTL did not fail on the pinned high-half assertion")
        return {"assertion": failures[0], "expected_high": "00000001", "actual_high": "00000000"}
    native.require(engine == "simx", "unknown native engine")
    native.require(text.splitlines().count("MPM transport: XLEN=64 PERF=on") == 1,
                   "SimX configuration banner differs")
    summaries = [line for line in failures if re.fullmatch(r"FAILED: [1-9][0-9]* of [1-9][0-9]* MPM transport checks", line)]
    native.require(len(summaries) == 1, "SimX failure summary missing or repeated")
    summary = re.fullmatch(r"FAILED: ([0-9]+) of ([0-9]+) MPM transport checks", summaries[0])
    assertions = [line for line in failures if line != summaries[0]]
    native.require(len(assertions) == int(summary[1]) < int(summary[2]), "SimX failure count differs")
    signature = None
    for line in assertions:
        match = re.fullmatch(
            r"FAILED: (host high reply|low-first reconstruction|high-first reconstruction) "
            r"core=([0-9]+) class=([0-9]+) index=([0-9]+) seed=0x([0-9a-f]{16}) "
            r"actual=0x([0-9a-f]{16}) expected=0x([0-9a-f]{16})", line)
        native.require(match is not None, "SimX failed outside the high-half/reconstruction assertions")
        what, core, perf_class, index, seed, actual, expected = match.groups()
        seed, actual, expected = (int(value, 16) for value in (seed, actual, expected))
        native.require(seed > 0xffffffff, "SimX failure does not require a high half")
        if what == "host high reply":
            native.require(actual == 0 and expected == seed >> 32, "SimX high-half mismatch differs")
            if (core, perf_class, index, seed, expected) == ("0", "0", "0", 0x100000000, 1):
                signature = line
        else:
            native.require(expected == seed and actual == seed & 0xffffffff,
                           "SimX reconstruction failure differs from the missing high half")
    native.require(signature is not None, "SimX lacks the pinned cycle high-half assertion")
    return {"assertion": signature, "failed_checks": int(summary[1]), "total_checks": int(summary[2]),
            "expected_high": "00000001", "actual_high": "00000000"}


def reference_checkout_argv(source, reference, git="git"):
    # A shallow clone can omit a fetched commit outside its advertised history.
    return [git, "-C", str(source), "worktree", "add", "--detach", str(reference), PARENT]


def reference_snapshot(reference):
    native.require(_git(reference, "rev-parse", "HEAD").decode().strip() == PARENT, "reference revision changed")
    changed = _git(reference, "diff", "--name-only", "--ignore-submodules=all", PARENT,
                   "--", ".", ":(exclude)third_party").decode().splitlines()
    native.require(not changed, "unexpected tracked reference source changes")
    return {"revision": PARENT, "tree": _git(reference, "rev-parse", "HEAD^{tree}").decode().strip(),
            "overlay": hash_artifacts(reference, OVERLAY),
            "critical_inputs": hash_artifacts(reference, REFERENCE_INPUTS)}


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    reference, build = work / "reference", work / "rv64-perf-on"
    report = {"schema_version": 1, "contract_id": "host-mpm-transport-v1", "parent_revision": PARENT,
              "scope": "native-parent-regression-sensitivity", "started_at": native.now(),
              "state": "running", "outcome": "blocked", "qualified": False, "acceptance_claimed": False,
              "reference_is_test_overlay": True, "absolute_no_wrap_bound": "not_established",
              "paths": {key: str(value) for key, value in paths.items()}, "commands": [],
              "budget": dict(native.BUDGET, jobs=2, threads=1, timeouts_seconds=native.TIMEOUTS),
              "cells": [{"engine": engine, "xlen": 64, "perf": "on", "outcome": "not_run"}
                        for engine in ("rtl", "simx")],
              "limitations": ["Only RV64 PERF on is examined on the pinned old implementation.",
                              "The reference reuses identical tracked dependency inputs and candidate cached libraries.",
                              "The reference has added candidate harnesses and a Make fragment; tracked source remains pinned.",
                              "An expected failure is sensitivity evidence; it does not accept a phase or qualify a packet.",
                              *native.LIMITATIONS]}
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    original_source = original_tools = original_reference = generated = None
    env = native.clean_environment(work)

    def checkpoint():
        target = output / "report.json.tmp"
        target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        target.replace(output / "report.json")

    def command(name, argv, cwd, timeout, environment=env):
        entry = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "environment": environment,
                 "timeout_seconds": timeout, "log": "logs/" + name + ".log", "outcome": "not_run"}
        report["commands"].append(entry)
        checkpoint()
        entry.update(run_bounded(entry["argv"], cwd, environment, output / entry["log"],
                                 timeout_seconds=timeout, resource_paths=tuple(paths.values()), **native.BUDGET))
        checkpoint()
        return entry

    def success(entry):
        native.require(entry["outcome"] == "pass" and entry["cleanup_complete"],
                       entry["id"] + " failed: " + str(entry["reason"]))

    def stable():
        native.require(native.source_snapshot(source) == original_source, "candidate source changed")
        native.require(native.tools_snapshot(paths, env, ("rtl", "simx")) == original_tools, "tools/dependencies changed")
        native.require(hash_artifacts(source, (SELF,) + native.HELPERS) == LOADED, "executing helpers changed")
        if original_reference is not None:
            native.require(reference_snapshot(reference) == original_reference, "reference source changed")

    def retain(identities):
        for item in identities:
            target = output / "configuration" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(build / item["path"], target)
        native.require(hash_artifacts(output / "configuration", [item["path"] for item in identities]) == identities,
                       "retained configuration differs")

    try:
        checkpoint()
        work.mkdir(mode=0o700)
        for name in ("home", "tmp"):
            (work / name).mkdir()
        report["environment"] = env
        report["free_disk_bytes"] = {name: shutil.disk_usage(path).free for name, path in paths.items()}
        report["available_memory_bytes"] = available_memory_bytes()
        native.require(all(value >= native.BUDGET["min_free_bytes"] for value in report["free_disk_bytes"].values()),
                       "disk reserve is below 15 GiB")
        native.require(report["available_memory_bytes"] is not None and report["available_memory_bytes"] >= 4 * GIB,
                       "at least 4 GiB available memory is required")
        native.require(hash_artifacts(source, (SELF,) + native.HELPERS) == LOADED, "executing helpers changed")
        _git(source, "ls-files", "--error-unmatch", "--", SELF)
        _git(source, "cat-file", "-e", PARENT + "^{commit}")
        original_source = report["source_before"] = native.source_snapshot(source)
        native.check_source(original_source, False)
        original_tools = report["tools_before"] = native.tools_snapshot(paths, env, ("rtl", "simx"))
        native.require(not original_tools["missing"], "missing installed prerequisites: " + ", ".join(original_tools["missing"]))
        git = shutil.which("git", path=env["PATH"])
        native.require(git is not None, "git unavailable")
        report["git_tool"] = native.file_identity(git)
        dependency_tree = _git(source, "rev-parse", PARENT + ":third_party").decode().strip()
        native.require(dependency_tree == _git(source, "rev-parse", "HEAD:third_party").decode().strip(),
                       "candidate dependency source/pins differ from the reference")
        report["shared_dependency_tree"] = dependency_tree
        for tool in ("make", "g++", "python3", "verilator"):
            success(command("version-" + tool.replace("+", "p"),
                            [original_tools["tools"][tool]["path"], "--version"], work, 30))
        success(command("checkout-reference", reference_checkout_argv(source, reference, git), work, 120))
        native.require(not _git(reference, "status", "--porcelain", "--ignore-submodules=all"), "reference checkout is dirty")
        report["parent_production_before_overlay"] = hash_artifacts(reference, (
            "sim/simx/core.cpp", "sim/simx/csr_unit.cpp", "hw/rtl/core/VX_csr_mpm.sv", "hw/rtl/core/VX_csr_data.sv"))
        for name in OVERLAY:
            target = reference / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        native.require(hash_artifacts(reference, OVERLAY) == hash_artifacts(source, OVERLAY), "test overlay differs")
        (reference / "third_party").rename(work / "parent-third-party-tracked")
        (reference / "third_party").symlink_to(source / "third_party", target_is_directory=True)
        original_reference = report["reference_before"] = reference_snapshot(reference)
        stable()
        build.mkdir()
        environment = dict(env, PERF="1")
        configure = [reference / "configure", "--xlen=64", "--profile=", "--tooldir=" + str(paths["tools"])]
        if args.osversion:
            configure.append("--osversion=" + args.osversion)
        success(command("configure-rv64-perf-on", configure, build, native.TIMEOUTS["configure"], environment))
        generated = report["generated_before"] = native.generated_identity(build, reference, paths["tools"], 64, args.osversion)
        retain(generated)
        for cell in report["cells"]:
            engine = cell["engine"]
            unit = build / native.UNITS[engine]
            binary = unit / native.BINARIES[engine]
            stable()
            target = "all" if engine == "rtl" else str(binary)
            makefile = ["-f", "mpm_transport.mk"] if engine == "simx" else []
            built = command(engine + "-build", [original_tools["tools"]["make"]["path"], "--no-print-directory",
                            "-j2", *makefile, "THREADS=1", "CONFIGS=", "PROFILE=", "PERF=1", target], unit, native.TIMEOUTS["build"], environment)
            cell["build_command"] = built["id"]
            success(built)
            native.require(binary.is_file() and os.access(binary, os.X_OK), "native binary missing or not executable")
            cell["binary_before"] = native.file_identity(binary)
            stable()
            result = command(engine + "-run", [binary], unit, native.TIMEOUTS["run"], environment)
            cell.update(run_command=result["id"], native_outcome=result["outcome"], native_exit_code=result["exit_code"])
            cell["binary_after"] = native.file_identity(binary)
            native.require(cell["binary_before"] == cell["binary_after"], "native binary changed")
            cell["observations"] = verify_expected_failure((output / result["log"]).read_text(encoding="utf-8"), engine, result)
            cell["outcome"] = "expected_failure"
            if engine == "simx":
                retain(hash_artifacts(build, ["sim/simx/simx_config.stamp"]))
            stable()
            checkpoint()
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report.update(outcome="fail" if any(item.get("process_started") for item in report["commands"]) else "blocked",
                      reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="runner interrupted")
    finally:
        for label, original, observe in (
                ("source", original_source, lambda: native.source_snapshot(source)),
                ("tools", original_tools, lambda: native.tools_snapshot(paths, env, ("rtl", "simx"))),
                ("reference", original_reference, lambda: reference_snapshot(reference)),
                ("generated", generated, lambda: native.generated_identity(build, reference, paths["tools"], 64, args.osversion))):
            if original is not None:
                try:
                    report[label + "_after"] = observe()
                    native.require(report[label + "_after"] == original, label + " changed during execution")
                except (OSError, ValueError, RuntimeError, UnicodeError) as error:
                    report.update(outcome="fail", reason=str(error))
        for cell in report["cells"]:
            if "binary_before" in cell:
                try:
                    cell["binary_after"] = native.file_identity(cell["binary_before"]["path"])
                    native.require(cell["binary_before"] == cell["binary_after"], "native binary changed")
                except (OSError, ValueError, RuntimeError) as error:
                    report.update(outcome="fail", reason=str(error))
            if cell["outcome"] == "not_run":
                cell.update(outcome="blocked", reason=report.get("reason", "earlier stage did not finish"))
        report.update(state="finished", finished_at=native.now())
        checkpoint()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=native.ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--osversion")
    args = parser.parse_args(argv)
    try:
        native.require(args.osversion is None or re.fullmatch(r"[A-Za-z0-9_/-]+", args.osversion), "invalid OS bundle")
        paths = native.resolve_paths(args)
        report = execute(args, paths)
    except (OSError, ValueError, RuntimeError) as error:
        print("MPM parent runner blocked: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "scope": report["scope"],
                      "report": str(paths["output"] / "report.json")}))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
