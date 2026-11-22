#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute bounded real-model public counter diagnostics in a fresh checked build.

This diagnostic uses the production runtime and model with identified test-only
link wrappers. It never qualifies a warm measurement or grants phase acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _git, collect_source, hash_artifacts
from baseline_process import GIB, run_bounded
import p06_checked_execute as checked
import p06_counter_public_build as public_build
import p06_counter_public_records as public_records
import p06_mpm_execute as native
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
BUDGET = dict(checked.BUDGET)
TIMEOUTS = dict(checked.TIMEOUTS)
CONTRACT_ID = "simx-counter-public-native-v1"
MODES = ("normal", "immediate-overflow", "delayed-overflow", "cache-overflow", "coherent-terminal")
PUBLIC_MAKEFILE = "tests/unittest/checked_counters/public.mk"
PUBLIC_DIR = "sim/simx/checked-public"
PUBLIC_BINARY = PUBLIC_DIR + "/checked_public_test"
COPIED = (*checked.COPIED, PUBLIC_MAKEFILE)
HELPERS = tuple(sorted(set(checked.HELPERS) | {
    path.relative_to(ROOT).as_posix() for path in (ROOT / "ci/project").glob("*.py")
    if not path.name.startswith("test_")
} | {"ci/project/" + name for name in (
    "p06_counter_public_execute.py", "p06_counter_public_build.py", "p06_counter_public_records.py")}))
CRITICAL = tuple(dict.fromkeys((*checked.CRITICAL, *HELPERS, PUBLIC_MAKEFILE,
    ".github/workflows/p06-checked-counters.yml",
    "tests/unittest/checked_counters/public_hooks.h", "tests/unittest/checked_counters/public_hooks.cpp",
    "tests/unittest/checked_counters/public_main.cpp", "tests/regression/ai_bench_common/counters.h")))
SOURCE_ROOTS = ("ci/project", "sim", "sw/common", "sw/include", "sw/runtime", "sw/kernel/include",
                "tests/unittest/checked_counters", "tests/regression/ai_bench_common",
                "third_party/ramulator_ext")
LOADED_HELPERS = hash_artifacts(ROOT, HELPERS)
LIMITATIONS = [
    "Success covers only these directed real-model public-runtime diagnostics, not warm readiness or phase acceptance.",
    "The scalar control and seeded counter reads do not execute GEMM, workspace reuse, the full warm caller or a performance experiment.",
    "Test-only linker wrappers observe the actual Processor; the diagnostic libraries are not seed-free measurement binaries.",
    "Coherence and terminal observations apply only to an exclusive serial submitter with the exact VM-off, direct-RAM CP route.",
    "Native observations do not replace independent source/dependency review of the complete counter-lifetime theorem.",
    "SimX evidence is software simulation, not processor RTL, vendor full-AFU emulation or physical hardware evidence.",
    "Tools and dependency identities do not inventory every host header, compiler support file or loaded system library.",
    "Binary and object bytes remain in the work tree; retained identities do not independently authenticate arbitrary producer claims.",
    "Before/after hashes do not defend against malicious concurrent filesystem writers.",
    *native.PROCESS_LIMITATIONS,
]
require = native.require


def source_snapshot(source):
    tracked = set(filter(None, _git(source, "ls-files", "-z", "--", *SOURCE_ROOTS,
                                    *CRITICAL).decode("utf-8").split("\0")))
    return {"checkout": collect_source(source), "untracked_critical": sorted(set(CRITICAL) - tracked),
            "files": hash_artifacts(source, sorted(tracked | set(CRITICAL)))}


def generated_identity(build, source, tools, osversion):
    checked.generated_identity(build, source, tools, osversion)
    require((build / PUBLIC_MAKEFILE).read_bytes() == (source / PUBLIC_MAKEFILE).read_bytes(),
            "copied public diagnostic Makefile differs")
    return hash_artifacts(build, (*checked.GENERATED, *COPIED))


def file_identities(paths):
    result = []
    seen = set()
    for name in paths:
        path = Path(name)
        require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file(),
                "execution input is not a regular file at its exact path")
        require(str(path) not in seen, "execution input path is repeated")
        seen.add(str(path))
        identity = native.file_identity(path)
        require(identity["size_bytes"] > 0, "execution input is empty")
        result.append(identity)
    return result


def interpreter_identity(snapshot):
    observation = {"version": list(sys.version_info[:3]), "implementation": platform.python_implementation(),
                   "platform": sys.platform}
    require(observation == {"version": [3, 12, 14], "implementation": "CPython", "platform": "linux"},
            "executing interpreter differs from pinned CPython 3.12.14 on Linux")
    first = snapshot["tools"]["python3"]
    second = snapshot["tools"]["executing_python"]
    require(all(first[key] == second[key] for key in ("resolved_path", "sha256", "size_bytes")),
            "PATH python3 differs from the executing interpreter")
    return observation


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    cells = [{"id": "public-" + mode, "mode": mode, "outcome": "not_run"} for mode in MODES]
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "started_at": native.now(),
        "state": "running", "outcome": "blocked", "qualified": False, "ready_for_warm": False,
        "acceptance_claimed": False, "phase_acceptance": False, "performance_acceptance": False,
        "full_warm_coverage": False, "warm_execution": False, "native_public_diagnostics_passed": False,
        "all_available_selector_transport": False, "expected_revision": args.expected_revision,
        "paths": {key: str(value) for key, value in paths.items()}, "commands": [], "cells": cells,
        "model_control": {"id": "checked-boundaries", "outcome": "not_run"}, "model": {}, "public": {},
        "bindings": {}, "stability_checks": [], "errors": [], "limitations": LIMITATIONS,
        "budget": dict(BUDGET, jobs=2, threads=1, timeouts_seconds=TIMEOUTS)}
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    environment = native.clean_environment(work)
    before_source = before_tools = None
    active_cell = None
    retained = []

    def checkpoint():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")

    def error(stage, failure):
        report["errors"].append({"stage": stage, "reason": str(failure)})
        report["outcome"] = "fail" if any(item.get("process_started") for item in report["commands"]) else "blocked"

    def retain(root, identities, prefix):
        names = []
        for item in identities:
            name = Path(item["path"])
            if name.is_absolute():
                name = name.relative_to(root)
            destination = output / "artifacts" / prefix / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, destination)
            names.append(destination.relative_to(output).as_posix())
        copied = hash_artifacts(output, names)
        require([(item["sha256"], item["size_bytes"]) for item in copied] ==
                [(item["sha256"], item["size_bytes"]) for item in identities], "retained evidence bytes differ")
        retained.extend(copied)
        return copied

    def bind(name, inputs, expected=None):
        require(name not in report["bindings"], "execution binding is repeated")
        identities = file_identities(inputs)
        require(expected is None or identities == expected, "validated execution input changed: " + name)
        report["bindings"][name] = {"before": identities}

    def bindings_stable():
        for name, group in report["bindings"].items():
            require(file_identities(item["path"] for item in group["before"]) == group["before"],
                    "execution input changed: " + name)

    def stable(stage):
        require(hash_artifacts(source, HELPERS) == LOADED_HELPERS, "executing helper bytes changed after import")
        require(source_snapshot(source) == before_source, "source changed during execution")
        require(native.tools_snapshot(paths, environment, ("simx",)) == before_tools,
                "tools or dependency libraries changed")
        bindings_stable()
        report["stability_checks"].append({"stage": stage, "bindings": list(report["bindings"])})

    def command(name, argv, cwd, timeout, public=False):
        stable("before-" + name)
        env = dict(environment, VORTEX_DRIVER="simx") if public else dict(environment)
        entry = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "environment": env,
                 "timeout_seconds": timeout, "log": "logs/" + name + ".log", "outcome": "not_run"}
        report["commands"].append(entry)
        checkpoint()
        entry.update(run_bounded(entry["argv"], cwd, env, output / entry["log"], timeout_seconds=timeout,
                                 resource_paths=tuple(paths.values()), **BUDGET))
        if active_cell is not None and active_cell["id"] == name:
            active_cell.update(run_command=name, run_outcome=entry["outcome"], exit_code=entry.get("exit_code"),
                               run_process_started=entry.get("process_started", False))
        checkpoint()
        require(entry.get("cleanup_complete") is True, name + " did not complete process cleanup")
        require(entry.get("process_started") is True and entry["outcome"] == "pass"
                and type(entry.get("exit_code")) is int and entry["exit_code"] == 0 and entry.get("reason") is None,
                name + " failed: " + str(entry.get("reason")))
        stable("after-" + name)
        return entry

    try:
        checkpoint()
        work.mkdir(mode=0o700)
        for name in ("home", "tmp"):
            (work / name).mkdir()
        report["environment"] = environment
        report["available_memory_bytes"] = available_memory_bytes()
        report["free_disk_bytes"] = {name: shutil.disk_usage(path).free for name, path in paths.items()}
        require(all(value >= BUDGET["min_free_bytes"] for value in report["free_disk_bytes"].values()),
                "disk reserve is below 15 GiB")
        require(report["available_memory_bytes"] is not None and report["available_memory_bytes"] >= 4 * GIB,
                "at least 4 GiB available memory is required")
        require(tuple(public_records.MODES) == MODES, "public diagnostic scenario inventory differs")
        require(hash_artifacts(source, HELPERS) == LOADED_HELPERS, "executing helper bytes changed after import")
        before_source = report["source_before"] = source_snapshot(source)
        native.check_source(before_source, False)
        require(args.expected_revision is None or before_source["checkout"]["revision"] == args.expected_revision,
                "source revision differs from the requested revision")
        before_tools = report["tools_before"] = native.tools_snapshot(paths, environment, ("simx",))
        require(not before_tools["missing"], "missing installed prerequisites: " + ", ".join(before_tools["missing"]))
        report["interpreter"] = interpreter_identity(before_tools)
        report["retained_sources"] = retain(source, before_source["files"], "source")
        selected = before_tools["tools"]
        for name in ("make", "g++", "python3", "executing_python"):
            command("version-" + name.replace("+", "p"), [selected[name]["path"], "--version"], work, 30)
        build = work / "checked"
        build.mkdir()
        unit, binary = build / "sim/simx", build / "sim/simx/checked_counters_test"
        report["build_dir"] = str(build)
        configure = [source / "configure", "--xlen=64", "--profile=p02-tfr", "--tooldir=" + str(paths["tools"])]
        if args.osversion:
            configure.append("--osversion=" + args.osversion)
        report["configure_command"] = command("checked-configure", configure, build, TIMEOUTS["configure"])["id"]
        generated = generated_identity(build, source, paths["tools"], args.osversion)
        report["retained_configuration"] = retain(build, generated, "checked")
        bind("configuration", [build / item["path"] for item in generated])
        require(not binary.exists() and not (unit / "obj").exists() and not (build / PUBLIC_DIR).exists(),
                "native build is not fresh")
        make = [selected["make"]["path"], "--no-print-directory", "-j2", "THREADS=1", "PROFILE=p02-tfr",
                "CONFIGS=-D" + checked.GUARD + "=1", "PERF=1", "CXX=" + selected["g++"]["path"]]
        built = command("checked-build", [*make, "-f", "checked_counters.mk", binary], unit, TIMEOUTS["build"])
        model = report["model"]
        model["build_command"] = built["id"]
        bind("model-stamp", [build / checked.STAMP])
        bind("generated-diagnostic-source", [build / checked.GENERATED_TCU])
        model["retained_compiler_stamp"] = retain(build, hash_artifacts(build, [checked.STAMP]), "checked")
        model["retained_diagnostic_source"] = retain(build, hash_artifacts(build, [checked.GENERATED_TCU]), "checked")
        words = checked.compile_flags((build / checked.STAMP).read_text(encoding="utf-8"),
                                      checked=True, source=source, build=build)
        source_files = {item["path"] for item in before_source["files"]}
        model["compiler_records"] = checked.validate_build((output / built["log"]).read_text(encoding="utf-8"),
            words, source=source, build=build, binary=binary, compiler=selected["g++"]["path"], source_files=source_files)
        bind("model-objects", [item["path"] for item in model["compiler_records"]["object_identities"]],
             model["compiler_records"]["object_identities"])
        require(os.access(binary, os.X_OK), "native boundary executable is missing or not executable")
        bind("model-binary", [binary])
        probe = build / "checked-header-probe.cpp"
        probe.write_text("#include <VX_config.h>\n#include <perf_counter.h>\n", encoding="utf-8")
        bind("header-probe", [probe])
        model["retained_probe"] = retain(build, hash_artifacts(build, [probe.name]), "checked")
        flags = [word for word in checked.dependency_flags(words, build / checked.STAMP) if word not in ("-MMD", "-MP")]
        header = command("checked-header", [selected["g++"]["path"], *flags, "-E", "-dM", "-x", "c++", probe],
                         unit, TIMEOUTS["configure"])
        model["effective_configuration"] = checked.verify_header((output / header["log"]).read_text(encoding="utf-8"), True)
        active_cell = report["model_control"]
        control = command(active_cell["id"], [selected["executing_python"]["path"], "-I", "-c",
            checked.NO_CORE_WRAPPER, binary, "boundaries"], unit, TIMEOUTS["run"])
        active_cell["observations"] = checked.verify_output((output / control["log"]).read_text(encoding="utf-8"), True)
        active_cell["outcome"] = "pass"
        active_cell = None
        public = report["public"]
        built = command("public-build", [*make, "-f", "../../" + PUBLIC_MAKEFILE, "checked-public"],
                        unit, TIMEOUTS["build"])
        public["build_command"] = built["id"]
        bind("public-stamps", [build / name for name in public_build.STAMPS])
        public["retained_compiler_stamps"] = retain(build, hash_artifacts(build, public_build.STAMPS), "checked")
        stamps = {Path(name).name.removesuffix("_config.stamp"): (build / name).read_text(encoding="utf-8")
                  for name in public_build.STAMPS}
        public["compiler_records"] = public_build.validate_build((output / built["log"]).read_text(encoding="utf-8"),
            words, stamps, source=source, build=build, compiler=selected["g++"]["path"],
            source_files=source_files, model_records=model["compiler_records"])
        bind("public-objects", [item["path"] for item in public["compiler_records"]["object_identities"]],
             public["compiler_records"]["object_identities"])
        bind("public-artifacts", [build / name for name in public_build.ARTIFACTS])
        application = build / PUBLIC_BINARY
        require(os.access(application, os.X_OK), "native public executable is missing or not executable")
        for cell in cells:
            active_cell = cell
            executed = command(cell["id"], [selected["executing_python"]["path"], "-I", "-c",
                checked.NO_CORE_WRAPPER, application, cell["mode"]], build / PUBLIC_DIR, TIMEOUTS["run"], public=True)
            cell["observations"] = public_records.verify_output((output / executed["log"]).read_text(encoding="utf-8"), cell["mode"])
            cell["outcome"] = "pass"
            active_cell = None
            checkpoint()
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, UnicodeError) as failure:
        if active_cell is not None:
            active_cell.update(outcome="fail" if active_cell.get("run_process_started") else "blocked", reason=str(failure))
        error("execution", failure)
    except KeyboardInterrupt:
        if active_cell is not None:
            active_cell.update(outcome="fail", reason="runner interrupted")
        error("execution", "runner interrupted")
    finally:
        for name, group in report["bindings"].items():
            try:
                group["after"] = file_identities(item["path"] for item in group["before"])
                require(group["after"] == group["before"], "execution input changed: " + name)
            except (OSError, ValueError, RuntimeError) as failure:
                error("final-" + name, failure)
        for name, before, observe in (("source", before_source, lambda: source_snapshot(source)),
                ("tools", before_tools, lambda: native.tools_snapshot(paths, environment, ("simx",)))):
            if before is not None:
                try:
                    report[name + "_after"] = observe()
                    report[name + "_stable"] = report[name + "_after"] == before
                    require(report[name + "_stable"], name + " changed during execution")
                except (OSError, ValueError, RuntimeError, UnicodeError) as failure:
                    error("final-" + name, failure)
        try:
            require(hash_artifacts(output, [item["path"] for item in retained]) == retained,
                    "retained evidence changed during execution")
            for entry in report["commands"]:
                if "log_sha256" in entry:
                    identity = native.file_identity(output / entry["log"])
                    require(identity["sha256"] == entry["log_sha256"] and identity["size_bytes"] == entry["log_size_bytes"],
                            "command log changed after execution")
        except (OSError, ValueError, RuntimeError) as failure:
            error("final-retained-evidence", failure)
        for cell in [report["model_control"], *cells]:
            if cell["outcome"] == "not_run":
                cell.update(outcome="blocked", reason="required execution or validation did not finish")
        report["all_available_selector_transport"] = report["outcome"] == "pass" and report["model_control"]["outcome"] == "pass"
        report["native_public_diagnostics_passed"] = report["outcome"] == "pass" and all(
            cell["outcome"] == "pass" for cell in [report["model_control"], *cells])
        report.update(state="finished", finished_at=native.now())
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-revision", help="Require this exact 40-character checkout commit")
    parser.add_argument("--osversion", help="Explicit configure OS bundle (otherwise configure detects it)")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        require(args.expected_revision is None or re.fullmatch(r"[0-9a-f]{40}", args.expected_revision), "invalid expected revision")
        require(args.osversion is None or re.fullmatch(r"[A-Za-z0-9_/-]+", args.osversion), "invalid OS bundle")
        paths = native.resolve_paths(args)
        report = execute(args, paths)
    except (OSError, ValueError, RuntimeError) as failure:
        print("Public counter runner blocked: " + str(failure), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "native_public_diagnostics_passed": report["native_public_diagnostics_passed"],
        "qualified": False, "ready_for_warm": False, "report": str(paths["output"] / "report.json")}))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
