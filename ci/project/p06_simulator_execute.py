#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the fixed SimX completion unit and public-runtime controls in a fresh tree.

The two native cells have distinct scopes: an actual processor/bounded-RAM
exception check and successful public-runtime launches with nonzero gp. Host
fault-injected backend checks and pinned-parent sensitivity are separate.
No download, phase acceptance or counter qualification is performed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _digest, hash_artifacts
from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from baseline_process import run_bounded
import compiler_records as compiler
import p02_matrix as base
import p06_compiler_records as timed_compiler
from p06_compiler_records import validate_header_macros


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "simulator-completion-native-v1"
APP = "tests/regression/simx_completion"
UNIT = "sim/simx/simx_completion_test"
OS_BUNDLE = "ubuntu/focal"
BUDGET = dict(base.BUDGET, max_rss_bytes=4 * 1024**3)
TIMEOUTS = {"configure": 120, "build": 1800, "run": 180, "probe": 30}
SOURCE_FILES = (
    "ci/project/p06_simulator_execute.py", "ci/project/p04_ci_prepare.py",
    ".github/workflows/p06-simulator-completion.yml",
    "docs/designs/simulator_completion_v1.md",
    "sim/simx/completion.mk", "tests/unittest/simx_completion/main.cpp",
    *(APP + "/" + name for name in ("Makefile", "main.cpp", "kernel.cpp", "common.h")),
)
GENERATED = tuple(sorted(set(base.GENERATED + base.COPIED + (
    "sim/simx/completion.mk", APP + "/Makefile",
))))
STAMPS = ("sim/simx/simx_config.stamp", "sw/runtime/simx_config.stamp",
          "sw/runtime/simx_rt_config.stamp", APP + "/config.stamp")
BINARIES = (UNIT, APP + "/simx_completion", APP + "/kernel.elf",
            APP + "/kernel.vxbin", "sw/kernel/libvortex2.a",
            "sw/runtime/libvortex.so", "sw/runtime/libvortex-simx.so",
            "sw/runtime/libsimx.so")
LIMITATIONS = [
    "This runner covers only RV64 p02-tfr timing SimX with performance counters enabled.",
    "The processor unit establishes native checked-run exception and legacy-gp semantics; it is not a public-runtime injected-failure test.",
    "The public-runtime cell checks six successful launches and nonzero gp; it does not inject a fault into the native backend.",
    "Host fault-injection, deterministic first-poll scheduling, and independently pinned parent sensitivity are separate evidence.",
    "No counter lifetime/no-wrap qualification, warm speedup, phase acceptance, RTL datapath, vendor, FPGA or silicon result is claimed.",
    "Tool and dependency hashes do not inventory every host header, compiler support file or dynamic library.",
    "Before/after hashes detect observed drift, not malicious concurrent replacement restored between checks.",
    "Retained source, generated inputs and raw logs permit review; native binaries are identified but not archived.",
    *base.PROCESS_LIMITATIONS,
]
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_snapshot(source):
    snapshot = base.source_snapshot(source)
    names = {row["path"] for row in snapshot["files"]} | set(SOURCE_FILES)
    names.update(row["path"] for row in LOADED_HELPERS)
    snapshot["files"] = hash_artifacts(source, sorted(names))
    return snapshot


def tool_snapshot(paths, environment):
    tools = base.tool_inventory(paths, environment, ("simx",))
    tools["executing_python"] = base._file_identity(sys.executable)
    return tools


def generated_identity(build, source, tools):
    base._generated_identity(build, source, tools)
    # Bind every configured compiler/search-path selection, not just XLEN and
    # the profile. The kernel driver's LLVM_PATH and RISCV_SYSROOT are outside
    # VX_CFLAGS, so a changed generated assignment would otherwise evade its
    # original stamp while the probe used the selected tool directory.
    versions = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=([A-Za-z0-9_.+-]+)$",
                               (source / "VERSION").read_text(encoding="utf-8"), re.MULTILINE))
    substitutions = dict(versions, XLEN="64", PROFILE="p02-tfr", VORTEX_HOME=str(source),
                         TOOLDIR=str(tools), OSVERSION=OS_BUNDLE, INSTALLDIR=str(build / "install"),
                         BUILDDIR=str(build))
    expected = (source / "config.mk.in").read_text(encoding="utf-8")
    require(set(re.findall(r"@([A-Z][A-Z0-9_]*)@", expected)) <= substitutions.keys(),
            "config.mk.in contains an unsupported configure substitution")
    for name, value in substitutions.items():
        expected = expected.replace("@" + name + "@", value)
    require((build / "config.mk").read_text(encoding="utf-8") == expected,
            "generated config.mk differs from the retained configured template")
    for name in ("sim/simx/completion.mk", APP + "/Makefile"):
        require((build / name).read_bytes() == (source / name).read_bytes(),
                "copied completion build input differs: " + name)
    return hash_artifacts(build, GENERATED)


def _compiler_options(words, role, source, build):
    """Bind every non-macro option to the generated completion build rules.

    The shared timed benchmark supplies the strict release option sets. Its
    application includes an AI helper directory, while this completion caller
    does not; the unit model also writes its own independent dependency stamp.
    Neither difference permits arbitrary search paths or driver options.
    """
    model = role in ("unit_model", "runtime_model")
    option_role = "backend_cpp" if model else role
    selected, includes, dependencies, probe_flags = [], [], [], []

    def scan(arguments, *, forwarded=False):
        pending = iter(arguments)
        preprocessor = []

        def operand():
            value = next(pending, None)
            require(value is not None, role + " has an option without an operand")
            return value

        for word in pending:
            option, separator, _ = word.partition("=")
            current = [word]
            if word.startswith(("-D", "-U")):
                if len(word) == 2:
                    current.append(operand())
            elif option in ("--define-macro", "--undefine-macro"):
                if not separator:
                    current.append(operand())
            elif not forwarded and word.startswith("-Wp,"):
                preprocessor.extend(word[4:].split(","))
            elif not forwarded and word == "-Xpreprocessor":
                current.append(operand())
                preprocessor.append(current[-1])
            elif not forwarded and word.startswith("-I"):
                if word == "-I":
                    current.append(operand())
                includes.append(current[-1] if word == "-I" else word[2:])
            elif not forwarded and model and word == "-MF":
                dependencies.append(operand())
                continue
            else:
                require(not forwarded and word in timed_compiler.OPTIONS[option_role],
                        role + " has an unexpected compiler option: " + word)
                selected.append(word)
                if model and word in ("-MMD", "-MP"):
                    continue
            if not forwarded:
                probe_flags.extend(current)
        if preprocessor:
            scan(preprocessor, forwarded=True)

    scan(words)
    require(Counter(selected) == Counter(timed_compiler.OPTIONS[option_role]),
            role + " has missing, repeated, or changed compiler options")
    dependency = build / ("sim/simx" if role == "unit_model" else "sw/runtime") / "simx_config.stamp"
    require(dependencies == ([str(dependency)] if model else []),
            role + " changes its dependency-record target")
    model_includes = [source / "sim/simx",
                      *(source / "sim/simx" / name for name in
                        ("dxa", "tex", "om", "raster", "rtu", "kmu", "mem", "dtm")),
                      source / "sw/common", source / "sim/common", build / "sw", build / "hw",
                      source / "third_party", source / "third_party/softfloat/source/include",
                      source / "third_party/ramulator/ext/spdlog/include",
                      source / "third_party/ramulator/ext/yaml-cpp/include",
                      source / "third_party/ramulator/src", source / "sim/simx/tcu"]
    expected_includes = {
        "unit_model": model_includes, "runtime_model": model_includes,
        "runtime": [source / "sw/runtime/include", "../common", build / "sw", build / "hw",
                    source / "sim/simx", source / "sim/common", source / "sw/common",
                    source / "sw/runtime/common"],
        "kernel": [source / "sw/kernel/include", build / "sw", build / "hw", source / "sw/common"],
        "host": [source / "sw/runtime/include", source / "sw/kernel/include",
                 build / "sw", build / "hw", source / "sw/common"],
    }
    require(includes == [str(path) for path in expected_includes[role]],
            role + " changes the completion include search order")
    # Only dependency-output bookkeeping is omitted: replaying -MF would
    # overwrite the original compiler stamp. All preprocessing-affecting
    # options, macro transports and include order remain exactly as recorded.
    return includes, probe_flags


def validate_compiler_records(build, configs, *, source=ROOT):
    source, build = Path(source), Path(build)
    require(source.is_absolute() and build.is_absolute()
            and ".." not in source.parts and ".." not in build.parts,
            "completion compiler bindings require absolute source and build paths")
    records = {name: (build / name).read_text(encoding="utf-8") for name in STAMPS}
    original_lines = {name: timed_compiler._bounded_records(text, name) for name, text in records.items()}
    compiler.validate_records(records["sw/runtime/simx_rt_config.stamp"],
                              records[APP + "/config.stamp"], str(build), configs)
    rows = []
    for name, roles in ((STAMPS[0], ("unit_model",)),
                        (STAMPS[1], ("runtime_model",)),
                        (STAMPS[2], ("runtime",)),
                        (STAMPS[3], ("kernel", "host", "linker"))):
        lines = original_lines[name]
        require(len(lines) == len(roles), "compiler record count differs: " + name)
        for text, role in zip(lines, roles):
            if role == "linker":
                continue
            compiler._compile_flags(text, role, configs, kernel=role == "kernel")
            words = _stamp_words(text, role)
            flags = _stamp_flags(text, role)
            require(not any(flag.startswith("-U") for flag in flags), role + " contains undefinitions")
            defines = _stamp_defines(text, role)
            performance = role in ("unit_model", "runtime_model")
            timed_compiler._configuration(defines, role, performance=performance,
                                          raw=True, expanded=not performance)
            expected = {"VX_PROFILE": "p02-tfr", "NDEBUG": "1"}
            allowed = {"VX_PROFILE", "NDEBUG", "VX_DBG_STALL_TIMEOUT", "VX_DBG_DEBUG_LEVEL"}
            if performance:
                allowed.add("PERF_ENABLE")
                require(sum(flag[2:].partition("=")[0] == "PERF_ENABLE" for flag in flags) == 1,
                        role + " repeats the performance-counter selector")
            if role == "kernel":
                allowed.add("__VORTEX__")
                expected["__VORTEX__"] = "1"
            if role == "host":
                allowed.update(("OMPI_SKIP_MPICXX", "MPICH_SKIP_MPICXX"))
                expected.update(OMPI_SKIP_MPICXX="1", MPICH_SKIP_MPICXX="1")
            for diagnostic, value in (("VX_DBG_STALL_TIMEOUT", "100000"), ("VX_DBG_DEBUG_LEVEL", "3")):
                if performance:
                    require(diagnostic not in defines or defines[diagnostic] == value,
                            role + " changes a diagnostic default")
                else:
                    expected[diagnostic] = value
            require(all(name.startswith("VX_CFG_") or name in allowed for name in defines),
                    role + " defines an unsupported completion macro")
            require(all(defines.get(name) == value for name, value in expected.items()),
                    role + " has missing/conflicting completion or release-build selectors")
            includes, probe_flags = _compiler_options(words, role, source, build)
            rows.append({"role": role, "path": name,
                         "sha256": hashlib.sha256(text.encode()).hexdigest(),
                         "macro_flags": flags, "compiler_flags": words,
                         "include_paths": includes, "probe_flags": probe_flags})
    return rows


def effective_header_command(tools, build, tool_directory, record):
    """Replay one supported original compile record without writing build outputs."""
    role = record["role"]
    directory = {"unit_model": build / "sim/simx", "runtime_model": build / "sim/simx",
                 "runtime": build / "sw/runtime/simx", "kernel": build / APP,
                 "host": build / APP}[role]
    compiler_name = "clang++" if role == "kernel" else "g++"
    prefix = []
    if role == "kernel":
        # VX_CFLAGS is the original application stamp. VX_CXX additionally
        # supplies this fixed LLVM driver prefix in the retained common.mk.
        toolchain = tool_directory / "riscv64-gnu-toolchain"
        prefix = ["--target=riscv64-unknown-elf",
                  "--sysroot=" + str(toolchain / "riscv64-unknown-elf"),
                  "--gcc-toolchain=" + str(toolchain),
                  "-Xclang", "-target-feature", "-Xclang", "+xvortex",
                  "-Xclang", "-target-feature", "-Xclang", "+zicond",
                  "-mllvm", "-disable-loop-idiom-all", "-Wno-unused-command-line-argument"]
    return ([tools[compiler_name]["path"], *prefix, *record["probe_flags"],
             "-E", "-dM", "-x", "c++", build / "completion-header.cpp"], directory)


def verify_output(text, cell):
    require(type(text) is str, "native output must be text")
    lines = text.splitlines()
    require(not any(line.startswith("FAILED simx_completion") for line in lines),
            "native output includes a failure")
    if cell == "unit":
        expected = [
            "native_x3 gp=7 checked_launches=3 legacy_launches=1",
            "native_x3 gp=-1 checked_launches=3 legacy_launches=1",
            "native_legacy_exception result=-1",
            "native_exception type=OutOfRange consumed=1",
            "native_x3 gp=7 checked_launches=3 legacy_launches=1",
            "PASSED simx_completion native_unit contexts=5 checked_success=9 legacy_success=3 checked_exceptions=1 legacy_errors=1",
        ]
        observed = [line for line in lines if line.startswith(("native_", "PASSED simx_completion"))]
        require(observed == expected, "native unit observations differ from the complete ordered contract")
        return {"contexts": 5, "checked_success": 9, "legacy_success": 3,
                "checked_exceptions": 1, "legacy_errors": 1}
    require(cell == "public", "unsupported native cell")
    banner = "PASSED simx_completion native_success contexts=2 launches=6 gp_nonzero=6"
    observed = [line for line in lines if line.startswith(("native_", "PASSED simx_completion"))]
    require(len(observed) == 7 and observed[-1] == banner, "native public observation inventory differs")
    witnesses = []
    for index, line in enumerate(observed[:-1]):
        match = re.fullmatch(r"native_success context=([01]) launch=([0-2]) gp=([0-9a-f]{16}) value=([0-9a-f]{8})", line)
        require(match is not None, "malformed native public witness")
        context, launch, gp, value = (int(match[1]), int(match[2]), int(match[3], 16), int(match[4], 16))
        require((context, launch) == divmod(index, 3), "native launches missing or out of order")
        require(gp & 0xffffffff != 0, "native gp witness has a zero low word")
        require(value == (0x13579bdf ^ (0x2468ace0 + 17 * launch + context)),
                "native output witness differs from the fixed inputs")
        witnesses.append({"context": context, "launch": launch, "gp": gp, "value": value})
    return {"contexts": 2, "launches": 6, "gp_nonzero": 6, "witnesses": witnesses}


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "started_at": base._now(),
              "state": "running", "outcome": "blocked", "reason": None,
              "acceptance_claimed": False, "qualified": False, "full_matrix_completed": False,
              "source_scope": "rv64-p02-tfr-timing-simx-perf-on",
              "paths": {name: str(path) if path else None for name, path in paths.items()},
              "budget": dict(BUDGET, jobs=2, threads=1, timeouts_seconds=TIMEOUTS),
              "commands": [], "cells": [{"id": name, "outcome": "not_run"} for name in ("unit", "public")],
              "stability_checks": [], "limitations": LIMITATIONS}
    output.mkdir(mode=0o700)
    for name in ("logs", "artifacts"):
        (output / name).mkdir()
    initial_source = initial_tools = initial_dependencies = configuration = artifacts = None
    build = work / "rv64-p02-tfr"
    environment = base.clean_environment(paths, 2)
    environment.pop("HOME", None)
    environment.update(THREADS="1")
    native_environment = dict(environment, PERF="1")

    def checkpoint():
        base._write_json(output / "report.json", report)

    def command(name, argv, cwd, env, timeout):
        require(not any(row["id"] == name for row in report["commands"]), "duplicate command identity")
        row = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "environment": dict(env),
               "timeout_seconds": timeout, "log": "logs/" + name + ".log", "outcome": "running"}
        report["commands"].append(row)
        checkpoint()
        row.update(run_bounded(row["argv"], cwd, env, output / row["log"],
                               timeout_seconds=timeout, resource_paths=(source, paths["tools"], work, output), **BUDGET))
        checkpoint()
        require(row.get("process_started") is True and row["outcome"] == "pass"
                and row.get("exit_code") == 0 and row.get("cleanup_complete") is True,
                "command failed: " + name + ": " + str(row.get("reason")))
        digest, size = _digest(output / row["log"])
        require((digest, size) == (row.get("log_sha256"), row.get("log_size_bytes")),
                "command log differs from its process receipt")
        return (output / row["log"]).read_text(encoding="utf-8")

    def retain(root, identities, prefix):
        copied = []
        for item in identities:
            name = "artifacts/" + prefix + "/" + item["path"]
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write((root / item["path"]).read_bytes())
            identity = hash_artifacts(output, [name])[0]
            require((identity["sha256"], identity["size_bytes"]) == (item["sha256"], item["size_bytes"]),
                    "retained input changed: " + item["path"])
            copied.append(identity)
        return copied

    def stable(label):
        require(source_snapshot(source) == initial_source, "source changed during native execution")
        require(tool_snapshot(paths, environment) == initial_tools, "tool or interpreter changed during native execution")
        require(hash_artifacts(source, base.DEPENDENCIES) == initial_dependencies,
                "dependency libraries changed during native execution")
        if configuration is not None:
            require(generated_identity(build, source, paths["tools"]) == configuration,
                    "generated configuration changed during native execution")
        if artifacts is not None:
            require(hash_artifacts(build, BINARIES + STAMPS) == artifacts,
                    "binary or compiler record changed during native execution")
        report["stability_checks"].append({"label": label, "at": base._now()})
        checkpoint()

    try:
        checkpoint()
        work.mkdir(mode=0o700)
        (work / "tmp").mkdir()
        report["resources_before"] = base._resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in report["resources_before"]["free_disk_bytes"].values()),
                "disk reserve is below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "at least 4 GiB available RAM is required")
        require(hash_artifacts(source, [row["path"] for row in LOADED_HELPERS]) == LOADED_HELPERS,
                "executing helper bytes changed after import")
        initial_source = report["source_before"] = source_snapshot(source)
        base._source_ok(initial_source, False)
        require(_digest(source / "profiles/p02-tfr.json")[0] == base.PROFILE_SHA256, "frozen profile changed")
        initial_tools = report["tools_before"] = tool_snapshot(paths, environment)
        initial_dependencies = report["dependencies_before"] = hash_artifacts(source, base.DEPENDENCIES)
        report["retained_source"] = retain(source, initial_source["files"], "source")
        for name in ("make", "g++", "clang", "clang++", "python3", "executing_python"):
            command("version-" + name.replace("+", "p"), [initial_tools[name]["path"], "--version"],
                    work, environment, TIMEOUTS["probe"])
        build.mkdir()
        report["build_dir"] = str(build)
        stable("before-configure")
        command("configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                "--osversion=" + OS_BUNDLE, "--tooldir=" + str(paths["tools"])],
                build, environment, TIMEOUTS["configure"])
        configuration = report["generated_before"] = generated_identity(build, source, paths["tools"])
        report["retained_configuration"] = retain(build, configuration, "build")
        flags_text = command("profile-flags", [initial_tools["python3"]["path"], source / "ci/gen_config.py",
                "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64",
                "--merge-configs", "--cflags=-DVX_CFG_XLEN=64"], build, environment, TIMEOUTS["probe"])
        configs = _stamp_flags(flags_text, "resolved native profile flags")
        require(configs and all(flag.startswith("-D") for flag in configs), "profile flags contain non-definitions")
        make = [initial_tools["make"]["path"], "--no-print-directory", "-j2", "THREADS=1"]
        command("unit-build", make + ["-f", "completion.mk", str(build / UNIT)],
                build / "sim/simx", native_environment, TIMEOUTS["build"])
        command("runtime-build", make + ["runtime-simx"], build / APP, native_environment, TIMEOUTS["build"])
        command("application-build", make + ["all"], build / APP, native_environment, TIMEOUTS["build"])
        artifacts = report["artifacts_before"] = hash_artifacts(build, BINARIES + STAMPS)
        for name in (UNIT, APP + "/simx_completion"):
            require(os.access(build / name, os.X_OK), "native binary is not executable: " + name)
        report["retained_compiler_records"] = retain(build, hash_artifacts(build, STAMPS), "compiler")
        report["compiler_records"] = validate_compiler_records(build, configs, source=source)
        probe = build / "completion-header.cpp"
        probe.write_text("#include <VX_config.h>\n", encoding="utf-8")
        report["header_probe"] = hash_artifacts(build, [probe.name])[0]
        report["retained_header_probe"] = retain(build, [report["header_probe"]], "probe")
        report["effective_headers"] = {}
        for record in report["compiler_records"]:
            role = record["role"]
            argv, directory = effective_header_command(initial_tools, build, paths["tools"], record)
            text = command("header-" + role, argv, directory, environment, TIMEOUTS["probe"])
            report["effective_headers"][role] = validate_header_macros(text, performance=role.endswith("_model"))
        for cell in report["cells"]:
            name = cell["id"]
            stable("before-" + name)
            cell.update(outcome="running", command=name + "-run")
            checkpoint()
            argv = ([build / UNIT] if name == "unit" else
                    [build / APP / "simx_completion", "-k", build / APP / "kernel.vxbin"])
            run_environment = dict(environment, LD_LIBRARY_PATH=str(build / "sw/runtime"), VORTEX_DRIVER="simx")
            text = command(name + "-run", argv, build / ("sim/simx" if name == "unit" else APP),
                           run_environment, TIMEOUTS["run"])
            cell["observations"] = verify_output(text, name)
            cell["outcome"] = "pass"
            stable("after-" + name)
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report.update(outcome="fail" if any(row.get("process_started") for row in report["commands"]) else "blocked",
                      reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="runner interrupted")
    finally:
        observations = (("source", initial_source, lambda: source_snapshot(source)),
                        ("tools", initial_tools, lambda: tool_snapshot(paths, environment)),
                        ("dependencies", initial_dependencies, lambda: hash_artifacts(source, base.DEPENDENCIES)),
                        ("generated", configuration, lambda: generated_identity(build, source, paths["tools"])),
                        ("artifacts", artifacts, lambda: hash_artifacts(build, BINARIES + STAMPS)))
        for name, before, observe in observations:
            if before is not None:
                try:
                    report[name + "_after"] = observe()
                    require(report[name + "_after"] == before, name + " changed during execution")
                except (OSError, ValueError, RuntimeError, UnicodeError) as error:
                    report.update(outcome="fail", reason=str(error))
        try:
            for name in ("retained_source", "retained_configuration", "retained_compiler_records", "retained_header_probe"):
                if name in report:
                    require(hash_artifacts(output, [row["path"] for row in report[name]]) == report[name],
                            "retained evidence changed: " + name)
            for row in report["commands"]:
                if row.get("log_sha256") is not None:
                    require(_digest(output / row["log"]) == (row["log_sha256"], row["log_size_bytes"]),
                            "retained command log changed: " + row["id"])
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            report.update(outcome="fail", reason=str(error))
        try:
            report["resources_after"] = base._resources(paths)
            require(all(value >= BUDGET["min_free_bytes"] for value in report["resources_after"]["free_disk_bytes"].values()),
                    "final disk reserve is below 15 GiB")
        except (OSError, ValueError, RuntimeError) as error:
            if report["outcome"] == "pass":
                report.update(outcome="fail", reason=str(error))
        for cell in report["cells"]:
            if cell["outcome"] in ("not_run", "running"):
                cell.update(outcome="fail" if cell["outcome"] == "running" else "blocked", reason=report["reason"])
        report["full_matrix_completed"] = report["outcome"] == "pass" and all(cell["outcome"] == "pass" for cell in report["cells"])
        report.update(state="finished", finished_at=base._now())
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path, help="Optional pinned host compiler directory")
    parser.set_defaults(verilator=None)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        paths = base.resolve_paths(args)
        report = execute(args, paths)
    except (OSError, ValueError, RuntimeError) as error:
        print("Simulator completion runner blocked: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "full_matrix_completed": report["full_matrix_completed"],
                      "report": str(paths["output"] / "report.json")}))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
