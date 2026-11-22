#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute native checked-counter prerequisites in two fresh serial SimX builds.

This is a directed source/transport prerequisite, not a warm qualification packet.
Installed dependencies and clean, fully tracked source are mandatory. Resource
limits, topology, tests and qualification exclusions cannot be relaxed by CLI.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _git, collect_source, hash_artifacts
from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from baseline_process import GIB, run_bounded
from compiler_records import _compiler_arguments, _records, _syntax
import p06_compiler_records as records
import p06_mpm_execute as native
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
BUDGET = dict(native.BUDGET)
TIMEOUTS = dict(native.TIMEOUTS)
GUARD = "SIMX_CHECKED_COUNTERS"
RESULT_PREFIX = "CHECKED_COUNTERS_RESULT "
FAILURE_PREFIX = "CHECKED_COUNTERS_FAILURE_RESULT "
STAMP = "sim/simx/simx_config.stamp"
GENERATED = native.GENERATED
COPIED = ("ci/gen_config.py", "sim/common.mk", "sim/simx/Makefile",
          "sim/simx/checked_counters.mk")
HELPERS = tuple("ci/project/" + name for name in (
    "p06_checked_execute.py", "p06_mpm_execute.py", "baseline_inventory.py", "baseline_process.py",
    "preflight.py", "baseline_packet_contract.py", "baseline_packet_io.py", "baseline_matrix.py",
    "compiler_records.py", "p06_compiler_records.py", "p02_matrix_records.py"))
CRITICAL = HELPERS + ("configure", "config.mk.in", "VERSION", ".gitmodules",
    "VX_config.toml", "VX_types.toml", "vortex_opae.toml", "ci/gen_config.py",
    "ci/blackbox.sh", "profiles/p02-tfr.json", "tests/unittest/checked_counters/main.cpp",
    "sim/common/perf_counter.h", "sim/simx/checked_counters.mk", "sw/runtime/common/async_run.h")
LOADED_HELPERS = hash_artifacts(ROOT, HELPERS)
SELECTORS = (
    "cycles", "instructions", "core_sched_idle", "core_active_warps", "core_stalled_warps",
    "core_issued_warps", "core_issued_threads", "core_stall_scrb", "core_stall_lsu",
    "core_stall_tcu", "core_instr_tcu", "core_loads", "core_stores", "lmem_reads",
    "lmem_writes", "lmem_bank_st", "coalescer_miss", "tcu_tbuf_stalls", "tcu_tbuf_cache_hits")
UNSEEDED = (
    "icache_reads", "icache_miss_r", "icache_mshr_st", "dcache_reads", "dcache_writes",
    "dcache_miss_r", "dcache_miss_w", "dcache_evicts", "dcache_mshr_st", "memory_reads",
    "memory_writes", "memory_lt", "memory_bank_st", "tcu_lmem_reads")
NEGATIVE = {"core-overflow": "overflow", "cache-aggregate-overflow": "overflow",
            "pending-underflow": "underflow"}
NO_CORE_WRAPPER = ("import os,resource,sys; resource.setrlimit(resource.RLIMIT_CORE,(0,0)); "
                   "os.execv(sys.argv[1],sys.argv[1:])")
LIMITATIONS = [
    "Success establishes only these directed native source/transport prerequisites, never warm qualification or phase acceptance.",
    "Only 19 available selectors receive transport boundary seeds; 14 available selectors remain explicitly unseeded and 12 are unavailable in this topology.",
    "No warm GEMM fixture, workspace reuse, cumulative launch lifetime, numerical acceptance or performance hypothesis is executed.",
    "The native updater failure uses the production AsyncRun owner directly; native public-runtime wait/query failure integration remains unqualified.",
    "The pending-underflow scenario exercises the PerfCounter primitive used by pending counters, not a private model pending-count injection.",
    "A checked build guards instrumented accumulator operations; this runner does not independently prove every counter update is instrumented.",
    "Native SimX evidence is software simulation, not processor RTL, full-AFU emulation or physical hardware evidence.",
    "Tool/dependency hashes do not inventory every host header, compiler support file or loaded system library; binaries remain identified in the work tree.",
    "Before/after hashes and retained records do not defend against malicious concurrent filesystem writers.",
    *native.PROCESS_LIMITATIONS,
]
require = native.require


def source_snapshot(source):
    tracked = set(filter(None, _git(source, "ls-files", "-z", "--", "sim", "sw/common",
                                    "third_party/ramulator_ext", *CRITICAL).decode("utf-8").split("\0")))
    return {"checkout": collect_source(source), "untracked_critical": sorted(set(CRITICAL) - tracked),
            "files": hash_artifacts(source, sorted(tracked | set(CRITICAL)))}


def generated_identity(build, source, tools, osversion):
    text = (build / "config.mk").read_text(encoding="utf-8")
    expected = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(source), "TOOLDIR": str(tools)}
    if osversion:
        expected["OSVERSION"] = osversion
    for name, value in expected.items():
        require(re.findall(r"^" + name + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE) == [value],
                "generated configuration differs: " + name)
    for name in COPIED:
        require((build / name).read_bytes() == (source / name).read_bytes(), "copied input differs: " + name)
    return hash_artifacts(build, GENERATED + COPIED)


def compile_flags(text, *, checked, source, build):
    """Validate the original stamp, admitting only the new guard to the P06 profile."""
    require(len(text.encode("utf-8")) <= records.MAX_RECORD_BYTES and len(_records(text, "compiler stamp")) == 1,
            "compiler stamp must contain one bounded record")
    _syntax(text, "compiler stamp")
    words = _stamp_words(text, "compiler stamp")
    _compiler_arguments(words, "compiler stamp")
    flags = _stamp_flags(text, "compiler stamp")
    require(not any(flag.startswith("-U") for flag in flags), "compiler stamp contains undefinitions")
    defines = _stamp_defines(text, "compiler stamp")
    require((defines.get(GUARD) == "1") if checked else GUARD not in defines,
            "compiler stamp checked-counter selection differs")
    require(sum(flag[2:].partition("=")[0] == GUARD for flag in flags) == int(checked),
            "compiler stamp repeats the checked-counter selector")
    hardware = {name: value for name, value in defines.items() if name != GUARD}
    records._configuration(hardware, "compiler stamp", performance=True, raw=True, expanded=False)
    allowed = {"VX_PROFILE", "NDEBUG", "PERF_ENABLE", GUARD}
    require(all(name.startswith("VX_CFG_") or name in allowed for name in defines),
            "compiler stamp defines an unsupported macro")
    require(defines.get("VX_PROFILE") == "p02-tfr" and defines.get("NDEBUG") == "1",
            "compiler stamp lacks the release profile")
    includes, options, dependency = [], [], []
    pending = iter(words)
    for word in pending:
        if word.startswith("-D") and len(word) > 2:
            continue
        if word.startswith("-I") and len(word) > 2:
            includes.append(word[2:])
        elif word == "-MF":
            dependency.append(next(pending, None))
        else:
            options.append(word)
    require(Counter(options) == Counter(records.OPTIONS["backend_cpp"]),
            "compiler stamp changes release, optimization or dependency options")
    require(dependency == [str(build / STAMP)], "compiler stamp changes its dependency target")
    expected_includes = [source / "sim/simx", *(source / "sim/simx" / name for name in
        ("dxa", "tex", "om", "raster", "rtu", "kmu", "mem", "dtm")), source / "sw/common",
        source / "sim/common", build / "sw", build / "hw", source / "third_party",
        source / "third_party/softfloat/source/include", source / "third_party/ramulator/ext/spdlog/include",
        source / "third_party/ramulator/ext/yaml-cpp/include", source / "third_party/ramulator/src",
        source / "sim/simx/tcu"]
    require(includes == list(map(str, expected_includes)), "compiler stamp changes the include search order")
    return words


def dependency_flags(words, target):
    """Keep every original flag except the make target-dependent -MF operand."""
    require(words.count("-MF") == 1, "compiler record must have exactly one dependency target")
    index = words.index("-MF")
    require(index + 1 < len(words) and words[index + 1] == str(target),
            "compiler record has an unexpected dependency target")
    return words[:index] + words[index + 2:]


def validate_build(text, stamp_words, *, source, build, binary, compiler, source_files):
    """Bind actual fresh translation units and the one link to the validated stamp."""
    expected_flags = dependency_flags(stamp_words, build / STAMP)
    objects, inputs, links = [], [], []
    for line in _records(text, "native build log"):
        words = _stamp_words(line, "native build command")
        if not words or words[0] != compiler:
            # A successful fresh build must account for every object it links.
            require(not any(word.endswith((".o", ".cpp")) for word in words),
                    "build log contains an unrecognized source/object command")
            continue
        _syntax(line, "native build command")
        arguments = words[1:]
        require(arguments.count("-o") == 1 and arguments[-2] == "-o", "native build output is ambiguous")
        target = Path(arguments[-1])
        body = arguments[:-2]
        if "-c" in body:
            require(body.count("-c") == 1 and body[-2] == "-c", "native compile source is ambiguous")
            original = Path(body[-1])
            require(original.is_relative_to(source) and original.relative_to(source).as_posix() in source_files,
                    "compiled source is absent from the source snapshot")
            require(target.is_relative_to(build / "sim/simx/obj") and target.suffix == ".o"
                    and target.resolve() == target and target not in objects,
                    "compiled object is repeated or outside the fresh tree")
            require(dependency_flags(body[:-2], target.with_suffix(".d")) == expected_flags,
                    "translation-unit flags differ from the compiler stamp")
            objects.append(target)
            inputs.append(original.relative_to(source).as_posix())
        else:
            require(target == binary, "unexpected native link target")
            prefix = list(stamp_words)
            prefix[prefix.index("-MF") + 1] = str(binary)
            require(body[:len(prefix)] == prefix, "link flags differ from the compiler stamp")
            links.append(body[len(prefix):])
    require(len(links) == 1 and len(objects) >= 40 and len(inputs) == len(set(inputs)),
            "native build lacks a unique fresh compile/link inventory")
    required = {"sim/simx/core.cpp", "sim/simx/csr_unit.cpp", "sim/simx/processor.cpp",
                "sim/simx/mem/cache.cpp", "sim/simx/tcu/tcu_unit.cpp", "sim/simx/tcu/tcu_tbuf.cpp",
                "tests/unittest/checked_counters/main.cpp"}
    require(required <= set(inputs), "native build omits required real SimX or TCU sources")
    third_party = source / "third_party"
    libraries = [str(third_party / "softfloat/build/Linux-x86_64-GCC/softfloat.a"),
        "-Wl,-rpath," + str(third_party / "ramulator"), "-L" + str(third_party / "ramulator"), "-lramulator",
        "-Wl,-rpath," + str(third_party / "ramulator_ext"), "-L" + str(third_party / "ramulator_ext"),
        "-Wl,--push-state,--no-as-needed", "-lramulator-vortex", "-Wl,--pop-state"]
    require(links[0][-len(libraries):] == libraries
            and Counter(links[0][:-len(libraries)]) == Counter(map(str, objects)),
            "native link does not bind exactly the fresh objects and identified dependencies")
    return {"compiled_sources": sorted(inputs), "object_identities": [native.file_identity(path) for path in objects],
            "compiler": compiler, "translation_units": len(objects), "link_count": len(links)}


def verify_header(text, checked):
    selection = re.findall(r"^#define SIMX_CHECKED_COUNTERS(?:[ \t]+(.*))?$", text, re.MULTILINE)
    require(selection == (["1"] if checked else []), "effective checked-counter macro differs")
    ordinary = "\n".join(line for line in text.splitlines() if not line.startswith("#define " + GUARD + " "))
    return records.validate_header_macros(ordinary, performance=True)


def verify_output(text, checked):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "boundary result repeats a key")
            result[key] = value
        return result

    lines = [line for line in _records(text, "boundary output") if line.startswith(RESULT_PREFIX)]
    require(len(lines) == 1 and not re.search(r"FAILED|SIMX_CHECKED_COUNTER_FAILURE", text),
            "boundary result missing, repeated or accompanied by failure")
    value = json.loads(lines[0][len(RESULT_PREFIX):], object_pairs_hook=unique,
                       parse_constant=lambda _: require(False, "boundary result is not finite JSON"))
    expected = {"schema_version": 1, "mode": "boundaries", "xlen": 64, "perf": True,
        "tcu": True, "checked": checked, "transport_selectors": list(SELECTORS), "vectors_per_selector": 10,
        "transport_reads": 760, "checks": 2749, "failures": 0, "unseeded_available_selectors": list(UNSEEDED),
        "unavailable_selectors": 12, "full_warm_coverage": False, "warm_execution": False}
    require(type(value) is dict and value == expected
            and all(type(value[key]) is type(item) for key, item in expected.items()),
            "boundary result differs from the directed native contract")
    return value


def verify_negative(text, result, mode):
    require(mode in NEGATIVE, "unknown negative diagnostic")
    require(result.get("process_started") is True and result.get("cleanup_complete") is True
            and result.get("outcome") == "pass" and result.get("reason") is None
            and type(result.get("exit_code")) is int and result["exit_code"] == 0,
            "negative diagnostic did not complete successfully")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "failure result repeats a key")
            value[key] = item
        return value

    lines = [line for line in _records(text, "negative output") if line.startswith(FAILURE_PREFIX)]
    require(len(lines) == 1 and text.count(FAILURE_PREFIX) == 1
            and not re.search(r"FAILED|SIMX_CHECKED_COUNTER_FAILURE", text)
            and RESULT_PREFIX not in text, "negative scenario lacks its unique failure result")
    value = json.loads(lines[0][len(FAILURE_PREFIX):], object_pairs_hook=unique,
                       parse_constant=lambda _: require(False, "failure result is not finite JSON"))
    expected = {"schema_version": 1, "mode": mode, "reason": NEGATIVE[mode], "checked": True,
        "exception_type": "PerfCounterError", "protected_value_unchanged": True,
        "public_runtime": False, "warm_execution": False}
    if mode == "core-overflow":
        expected.update(actual_model_updater=True, terminal_failure=True, sticky_failure_checks=8,
                        later_work_suppressed=True, suppressed_tasks=2, joined=True, fresh_context_success=True)
    elif mode == "cache-aggregate-overflow":
        expected.update(source_unchanged=True, scope="production-cache-aggregate")
    else:
        expected.update(scope="pending-counter-primitive")
    require(type(value) is dict and value == expected
            and all(type(value[key]) is type(item) for key, item in expected.items()),
            "failure result differs from the directed native contract")
    return value


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    cells = [{"id": variant + "-" + mode, "variant": variant, "mode": mode, "outcome": "not_run"}
             for variant in ("ordinary", "checked")
             for mode in (("boundaries",) if variant == "ordinary" else ("boundaries", *NEGATIVE))]
    report = {"schema_version": 1, "contract_id": "simx-checked-counters-native-v1", "started_at": native.now(),
        "state": "running", "outcome": "blocked", "qualified": False, "ready_for_warm": False,
        "acceptance_claimed": False, "full_warm_coverage": False, "warm_execution": False,
        "native_prerequisites_passed": False, "expected_revision": args.expected_revision,
        "paths": {key: str(value) for key, value in paths.items()}, "commands": [], "variants": [],
        "cells": cells, "errors": [], "limitations": LIMITATIONS,
        "budget": dict(BUDGET, jobs=2, threads=1, timeouts_seconds=TIMEOUTS)}
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    env = native.clean_environment(work)
    before_source = before_tools = None
    active_cell = None

    def checkpoint():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")

    def error(stage, failure):
        report["errors"].append({"stage": stage, "reason": str(failure)})
        report.update(outcome="fail" if any(item.get("process_started") for item in report["commands"]) else "blocked")

    def stable():
        require(hash_artifacts(source, HELPERS) == LOADED_HELPERS, "executing helper bytes changed after import")
        require(source_snapshot(source) == before_source, "source changed during execution")
        require(native.tools_snapshot(paths, env, ("simx",)) == before_tools, "tools or dependency libraries changed")

    def retain(root, identities, prefix):
        names = []
        for item in identities:
            destination = output / "artifacts" / prefix / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / item["path"], destination)
            names.append(destination.relative_to(output).as_posix())
        copied = hash_artifacts(output, names)
        require([(item["sha256"], item["size_bytes"]) for item in copied] ==
                [(item["sha256"], item["size_bytes"]) for item in identities], "retained bytes differ")
        return copied

    def command(name, argv, cwd, timeout):
        stable()
        entry = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "environment": dict(env),
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
        require(entry["outcome"] == "pass",
                name + " failed: " + str(entry["reason"]))
        return entry

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
        before_source = report["source_before"] = source_snapshot(source)
        native.check_source(before_source, False)
        require(args.expected_revision is None or before_source["checkout"]["revision"] == args.expected_revision,
                "source revision differs from the requested revision")
        before_tools = report["tools_before"] = native.tools_snapshot(paths, env, ("simx",))
        require(not before_tools["missing"], "missing installed prerequisites: " + ", ".join(before_tools["missing"]))
        report["retained_sources"] = retain(source, before_source["files"], "source")
        selected = before_tools["tools"]
        for name in ("make", "g++", "python3", "executing_python"):
            command("version-" + name.replace("+", "p"), [selected[name]["path"], "--version"], work, 30)
        for name in ("ordinary", "checked"):
            checked = name == "checked"
            build = work / name
            build.mkdir()
            unit, binary = build / "sim/simx", build / "sim/simx/checked_counters_test"
            variant = {"id": name, "checked": checked, "build_dir": str(build), "binary_path": str(binary)}
            report["variants"].append(variant)
            configure = [source / "configure", "--xlen=64", "--profile=p02-tfr", "--tooldir=" + str(paths["tools"])]
            if args.osversion:
                configure.append("--osversion=" + args.osversion)
            variant["configure_command"] = command(name + "-configure", configure, build, TIMEOUTS["configure"])["id"]
            variant["generated_before"] = generated_identity(build, source, paths["tools"], args.osversion)
            variant["retained_configuration"] = retain(build, variant["generated_before"], name)
            require(not binary.exists() and not (unit / "obj").exists(), "native build is not fresh")
            built = command(name + "-build", [selected["make"]["path"], "--no-print-directory", "-j2", "THREADS=1",
                "PROFILE=p02-tfr", "CONFIGS=" + ("-D" + GUARD + "=1" if checked else ""), "PERF=1",
                "CXX=" + selected["g++"]["path"], "-f", "checked_counters.mk", binary], unit, TIMEOUTS["build"])
            variant["build_command"] = built["id"]
            variant["compiler_stamp_before"] = hash_artifacts(build, [STAMP])
            variant["retained_compiler_stamp"] = retain(build, variant["compiler_stamp_before"], name)
            words = compile_flags((build / STAMP).read_text(encoding="utf-8"), checked=checked, source=source, build=build)
            variant["compiler_records"] = validate_build((output / built["log"]).read_text(encoding="utf-8"), words,
                source=source, build=build, binary=binary, compiler=selected["g++"]["path"],
                source_files={item["path"] for item in before_source["files"]})
            require(binary.is_file() and os.access(binary, os.X_OK), "native binary missing or not executable")
            variant["binary_before"] = native.file_identity(binary)
            probe = build / "checked-header-probe.cpp"
            probe.write_text("#include <VX_config.h>\n#include <perf_counter.h>\n", encoding="utf-8")
            variant["retained_probe"] = retain(build, hash_artifacts(build, [probe.name]), name)
            probe_flags = [word for word in dependency_flags(words, build / STAMP) if word not in ("-MMD", "-MP")]
            preprocessed = command(name + "-header", [selected["g++"]["path"], *probe_flags, "-E", "-dM", "-x", "c++", probe],
                                   unit, TIMEOUTS["configure"])
            variant["effective_configuration"] = verify_header((output / preprocessed["log"]).read_text(encoding="utf-8"), checked)
            for cell in (cell for cell in cells if cell["variant"] == name):
                active_cell = cell
                require(generated_identity(build, source, paths["tools"], args.osversion) == variant["generated_before"],
                        "generated configuration changed before native execution")
                require(hash_artifacts(build, [STAMP]) == variant["compiler_stamp_before"],
                        "compiler stamp changed before native execution")
                require(native.file_identity(binary) == variant["binary_before"], "native binary changed before execution")
                negative = cell["mode"] in NEGATIVE
                result = command(cell["id"], [selected["executing_python"]["path"], "-I", "-c", NO_CORE_WRAPPER,
                    binary, cell["mode"]], unit, TIMEOUTS["run"])
                cell.update(run_command=result["id"], run_outcome=result["outcome"], exit_code=result["exit_code"],
                            run_process_started=result["process_started"])
                text = (output / result["log"]).read_text(encoding="utf-8")
                if negative:
                    cell["observations"] = verify_negative(text, result, cell["mode"])
                else:
                    cell["observations"] = verify_output(text, checked)
                cell["outcome"] = "pass"
                require(native.file_identity(binary) == variant["binary_before"], "native binary changed during execution")
                checkpoint()
                active_cell = None
        boundaries = [{key: value for key, value in cell["observations"].items() if key != "checked"}
                      for cell in cells if cell["mode"] == "boundaries"]
        require(boundaries[0] == boundaries[1], "ordinary and checked boundary observations differ")
        report.update(outcome="pass", ordinary_checked_observations_equal=True)
    except (OSError, ValueError, RuntimeError, UnicodeError) as failure:
        if active_cell is not None:
            active_cell.update(outcome="fail" if active_cell.get("run_process_started") else "blocked", reason=str(failure))
        error("execution", failure)
    except KeyboardInterrupt:
        if active_cell is not None:
            active_cell.update(outcome="fail", reason="runner interrupted")
        error("execution", "runner interrupted")
    finally:
        for variant in report["variants"]:
            build = Path(variant["build_dir"])
            for key, observe in (
                ("generated", lambda: generated_identity(build, source, paths["tools"], args.osversion)),
                ("compiler_stamp", lambda: hash_artifacts(build, [STAMP])),
                ("binary", lambda: native.file_identity(variant["binary_path"]))):
                if key + "_before" in variant:
                    try:
                        variant[key + "_after"] = observe()
                        require(variant[key + "_after"] == variant[key + "_before"], key + " changed during execution")
                    except (OSError, ValueError, RuntimeError, UnicodeError) as failure:
                        error(variant["id"] + "-" + key, failure)
            if "compiler_records" in variant:
                try:
                    before = variant["compiler_records"]["object_identities"]
                    variant["objects_after"] = [native.file_identity(item["path"]) for item in before]
                    require(variant["objects_after"] == before, "compiled objects changed during execution")
                except (OSError, ValueError, RuntimeError) as failure:
                    error(variant["id"] + "-objects", failure)
        for key, before, observe in (("source", before_source, lambda: source_snapshot(source)),
                ("tools", before_tools, lambda: native.tools_snapshot(paths, env, ("simx",)))):
            if before is not None:
                try:
                    report[key + "_after"] = observe()
                    report[key + "_stable"] = before == report[key + "_after"]
                    require(report[key + "_stable"], key + " changed during execution")
                except (OSError, ValueError, RuntimeError, UnicodeError) as failure:
                    error("final-" + key, failure)
        try:
            identities = list(report.get("retained_sources", []))
            for variant in report["variants"]:
                for key in ("retained_configuration", "retained_compiler_stamp", "retained_probe"):
                    identities.extend(variant.get(key, []))
            require(hash_artifacts(output, [item["path"] for item in identities]) == identities,
                    "retained evidence changed during execution")
            for entry in report["commands"]:
                if "log_sha256" in entry:
                    identity = native.file_identity(output / entry["log"])
                    require(identity["sha256"] == entry["log_sha256"] and identity["size_bytes"] == entry["log_size_bytes"],
                            "command log changed after execution")
        except (OSError, ValueError, RuntimeError) as failure:
            error("final-retained-evidence", failure)
        for cell in cells:
            if cell["outcome"] == "not_run":
                cell.update(outcome="blocked", reason="required execution or validation did not finish")
        report["native_prerequisites_passed"] = report["outcome"] == "pass" and all(cell["outcome"] == "pass" for cell in cells)
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
        print("Checked-counter runner blocked: " + str(failure), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "native_prerequisites_passed": report["native_prerequisites_passed"],
        "qualified": False, "ready_for_warm": False, "report": str(paths["output"] / "report.json")}))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
