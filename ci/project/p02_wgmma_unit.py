#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and execute the bounded native four-slot WGMMA protocol harness.

Formal execution requires a clean committed checkout. --development records a
dirty-source investigation without accepting P02-A03. Work/output roots must be
fresh; all build trees, command logs and source/configuration identities remain
available for independent review. This direct-dispatch unit does not establish
processor scoreboard behavior, SimX parity, vendor integration or hardware PPA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from baseline_inventory import collect_source, hash_artifacts
from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from baseline_process import GIB, MIB, LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from compiler_records import _compiler_arguments, _records, _syntax
from p02_matrix import (_file_identity, _now, _resources, _source_ok, _timeout,
                        _write_json, clean_environment, resolve_paths)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p02-wgmma-native-unit-v1"
UNIT = "hw/unittest/tcu_wgmma"
TOP = "VX_tcu_wgmma_top"
PREFIX = "V" + TOP
CYCLE_LIMIT = 100000
BUDGET = {"min_free_bytes": 15 * GIB, "max_rss_bytes": 6 * GIB, "max_log_bytes": 16 * MIB}
VALUES = {
    "NUM_CLUSTERS": 1, "NUM_CORES": 1, "NUM_THREADS": 8, "NUM_WARPS": 8,
    "ISSUE_WIDTH": 4, "FETCH_WIDTH": 2, "NUM_ALU_BLOCKS": 1, "NUM_LSU_BLOCKS": 1,
    "NUM_FPU_BLOCKS": 1, "NUM_TCU_BLOCKS": 4, "NUM_TCU_LANES": 8,
    "TCU_PE_RATIO": 1, "TCU_LATENCY": 4, "TCU_USE_DSP": 0,
    "LMEM_LOG_SIZE": 14, "LMEM_NUM_BANKS": 8,
}
DISABLED = tuple("TCU_" + name for name in
                 ("TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4", "NVFP4", "DSM")) + (
                     "EXT_LDST_MATRIX",)
CONFIGS = tuple("-DVX_CFG_" + name + "=" + str(value) for name, value in VALUES.items()) + (
    "-DVX_CFG_EXT_TCU_ENABLE", "-DVX_CFG_LMEM_ENABLE", "-DVX_CFG_TCU_WGMMA_ENABLE",
    "-DVX_CFG_TCU_SPARSE_ENABLE", "-DVX_CFG_TCU_FP16_ENABLE",
    "-DVX_CFG_TCU_TYPE_TFR", "-DVX_CFG_FPU_TYPE_STD",
) + tuple("-DVX_CFG_" + name + "_DISABLE" for name in DISABLED)
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh", "hw/unittest/verilator.vlt")
COPIED = ("ci/gen_config.py", "hw/unittest/common.mk", UNIT + "/Makefile")
INPUTS = ("configure", "config.mk.in", "VERSION", ".gitmodules", "VX_config.toml",
          "VX_types.toml", "hw/unittest/verilator.vlt.in")
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))
TOOLING = tuple(item["path"] for item in LOADED_HELPERS)
GROUPS = (
    ("dense_ss_initial", 64, 512),
    ("dense_ss_descriptor_reuse", 64, 512),
    ("dense_ss_row_major", 64, 512),
    ("dense_rs_bf16", 64, 512),
    ("cta_exclusion", 32, 256),
    ("sparse_metadata_initial", 36, 256),
    ("sparse_metadata_reload", 36, 256),
    ("dense_rs_commit_pressure", 32, 256),
)
COVERAGE_FIELDS = {
    "accepted", "commits", "words", "dispatch_stalls", "commit_holds", "lmem_holds",
    "lmem_requests", "lmem_responses", "delayed_lmem", "metadata_requests",
    "metadata_writes", "metadata_lanes", "delayed_metadata", "cta_conflicts",
    "cta_entries", "overlapping", "pressure_holds", "pressure_qualified", "pressure_tail",
    "descriptor_a_poisoned", "descriptor_b_poisoned", "cycles", "watchdog", "pressure_limit",
}
LIMITATIONS = [
    "A passing unit packet does not accept P02-A03 or close P02.",
    "The harness directly supplies expanded dispatch micro-operations; processor scoreboarding is separate.",
    "Integer-generated exact FP16/BF16 vectors and the finite directed schedules do not qualify other formats/geometries.",
    "No SimX timing parity, full AFU, vendor hw_emu, physical FPGA, synthesis or silicon result is claimed.",
    "Tool identities do not inventory every host system header, support file or dynamic library.",
    "Original logs and snapshots retain local paths and need publication review.",
    *PROCESS_LIMITATIONS,
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_snapshot(source):
    checkout = collect_source(source)
    names = set(TOOLING + INPUTS + COPIED)
    for directory in ("hw/rtl", UNIT):
        for path in (source / directory).rglob("*"):
            if path.is_file() and (path.suffix in {".sv", ".v", ".vh", ".vi", ".h", ".cpp"}
                                   or path.name == "Makefile"):
                names.add(path.relative_to(source).as_posix())
    for name in checkout["changed_paths"] + checkout["untracked_paths"]:
        if (source / name).is_file():
            names.add(name)
    return {"checkout": checkout, "files": hash_artifacts(source, sorted(names))}


def tool_inventory(paths, env):
    selected = {}
    for name in ("make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl"):
        selected[name] = shutil.which(name, path=env["PATH"])
        require(selected[name] is not None, "required host tool is missing: " + name)
    for name in ("verilator", "verilator_bin"):
        selected[name] = paths["verilator"] / "bin" / name
    require(all(os.access(path, os.X_OK) for path in selected.values()), "selected tool is not executable")
    return {name: _file_identity(path) for name, path in selected.items()}


def generated_identity(build, source, tools):
    text = (build / "config.mk").read_text()
    for name, expected in (("XLEN", "64"), ("PROFILE", ""), ("VORTEX_HOME", str(source)),
                           ("TOOLDIR", str(tools)), ("OSVERSION", "ubuntu/focal")):
        require(re.findall(r"^" + name + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE) == [expected],
                "generated config.mk differs: " + name)
    words = (build / ".config.stamp").read_text().strip().split()
    values = dict(word.split("=", 1) for word in words)
    require(len(values) == len(words), "configure stamp repeats settings")
    for name, expected in (("XLEN", "64"), ("PROFILE", ""), ("SOURCE_DIR", str(source)),
                           ("BUILDDIR", str(build)), ("TOOLDIR", str(tools))):
        require(values.get(name) == expected, "configure stamp differs: " + name)
    for name in COPIED:
        require((build / name).read_bytes() == (source / name).read_bytes(), "copied build input differs: " + name)
    expected = (source / "hw/unittest/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(source))
    require((build / "hw/unittest/verilator.vlt").read_text() == expected, "Verilator lint configuration differs")
    return hash_artifacts(build, GENERATED + COPIED)


def configuration(defines, label, *, effective=False):
    expected = _stamp_defines(" ".join(CONFIGS), "frozen unit configuration")
    expected.update(VX_CFG_XLEN="64", VX_CFG_XLEN_64="1")
    require(all(defines.get(key) == value for key, value in expected.items()), label + " lacks the frozen configuration")
    require(not any(name.startswith("VX_CFG_XLEN_") and name != "VX_CFG_XLEN_64" for name in defines),
            label + " selects another XLEN")
    for prefix, selected in (("VX_CFG_TCU_TYPE", "TFR"), ("VX_CFG_FPU_TYPE", "STD")):
        require(defines.get(prefix, selected) == selected and not any(
            name.startswith(prefix + "_") and name != prefix + "_" + selected for name in defines),
            label + " selects a nonnative arithmetic path")
    for name in DISABLED:
        require("VX_CFG_" + name + "_ENABLE" not in defines
                and defines.get("VX_CFG_" + name + "_ENABLED", "0") == "0", label + " enables an excluded bank")
    for name in ("EXT_TCU", "LMEM", "TCU_FP16", "TCU_WGMMA", "TCU_SPARSE"):
        require("VX_CFG_" + name + "_DISABLE" not in defines
                and defines.get("VX_CFG_" + name + "_ENABLED", "1") == "1", label + " disables a required bank")
    require(not any(name.startswith(("VX_CFG_TCU_FEDP2K", "DBG_TRACE_")) or name in {
        "SV_DPI", "DEBUG", "VCD_OUTPUT", "SAIF_OUTPUT", "XRTSIM", "__FAST_MATH__"} for name in defines),
        label + " enables an excluded datapath or trace")
    require(defines.get("__FINITE_MATH_ONLY__", "0") == "0", label + " enables finite-only arithmetic")
    if effective:
        require("NDEBUG" not in defines and defines.get("VX_CFG_NUM_LSU_LANES") == "8",
                "effective host configuration disables assertions or changes LSU lanes")


def validate_stamp(text, source, build, jobs):
    _records(text, "unit compiler stamp")
    lines = text.splitlines()
    require(len(lines) == 3 and lines[2] == "", "unit stamp must contain separate C++, RTL and empty linker records")
    source, build = Path(source), Path(build)
    results = []
    for role, line in zip(("host_cpp", "verilator"), lines[:2]):
        _syntax(line, role)
        words = _stamp_words(line, role)
        flags = _stamp_flags(line, role)
        require([flag for flag in flags if flag.startswith("-U")] == ["-UNDEBUG"], role + " has unexpected undefinitions")
        require([flag for flag in flags if flag[2:].split("=", 1)[0] == "NDEBUG"] == ["-DNDEBUG", "-UNDEBUG"],
                role + " does not enable assertions after release optimization")
        require(not any(word == "-Ofast" or word.startswith(("-Wp,", "-Xpreprocessor")) for word in words),
                role + " has opaque or fast-math flags")
        defines = _stamp_defines(line, role)
        configuration(defines, role)
        if role == "host_cpp":
            _compiler_arguments(words, role)
            allowed = {"-std=c++17", "-Wall", "-Wextra", "-Wfatal-errors", "-Werror", "-fPIC", "-O2"}
            allowed |= {"-I" + str(path) for path in (source / UNIT, build / "sw", build / "hw")}
            require(all(word.startswith(("-D", "-U")) or word in allowed for word in words),
                    "host C++ options differ from the native unit contract")
        else:
            pairs = {"--language": "1800-2012", "--x-initial": "unique", "--x-assign": "unique",
                     "--cc": TOP, "--top-module": TOP, "-j": str(jobs)}
            required = {"--exe", "--assert", "-Wall", "-Wpedantic", "-Wno-DECLFILENAME",
                        "-Wno-REDEFMACRO", "-Wno-GENUNNAMED", "../verilator.vlt"}
            operands = {str(source / "hw/rtl/VX_gpu_pkg.sv"), str(source / "hw/rtl/tcu/VX_tcu_pkg.sv")}
            includes = {"-I" + str(path) for path in (build / "sw", build / "hw", source / UNIT)}
            includes |= {"-I" + str(source / "hw/rtl" / path) for path in
                         ("", "libs", "tcu", "tcu/tfr", "interfaces", "core", "mem")}
            seen, index = set(), 0
            while index < len(words):
                word = words[index]
                if word in pairs:
                    require(word not in seen and index + 1 < len(words) and words[index + 1] == pairs[word],
                            "incorrect or repeated Verilator option: " + word)
                    seen.add(word)
                    index += 2
                    continue
                require(word.startswith(("-D", "-U")) or word in required | operands | includes,
                        "unexpected Verilator argument: " + word)
                if word in required | operands | includes:
                    require(word not in seen, "repeated Verilator argument")
                    seen.add(word)
                index += 1
            require(seen == set(pairs) | required | operands | includes, "Verilator invocation is incomplete")
            require(defines.get("SIMULATION") == "1", "Verilator does not select simulation")
        results.append({"role": role, "sha256": hashlib.sha256(line.encode()).hexdigest(),
                        "macro_flags": flags, "configuration": defines})
    return results


def validate_header(text):
    defines = {}
    for line in text.splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
        if match:
            require(match[1] not in defines, "effective header repeats a macro")
            defines[match[1]] = match[2] or "1"
    configuration(defines, "effective host header", effective=True)
    return {key: value for key, value in defines.items() if key.startswith("VX_CFG_")}


def build_artifacts(build):
    names = set(GENERATED + COPIED + (UNIT + "/config.stamp", UNIT + "/tcu_wgmma"))
    obj = build / UNIT / "obj_dir"
    for path in obj.rglob("*"):
        if path.is_file() and path.suffix in {".h", ".cpp", ".d", ".dat", ".mk"}:
            names.add(path.relative_to(build).as_posix())
    require(all(UNIT + "/obj_dir/" + PREFIX + suffix in names for suffix in
                ("__verFiles.dat", "_classes.mk", "__Syms.h")), "native hierarchy metadata is incomplete")
    hierarchy = (obj / (PREFIX + "__Syms.h")).read_text()
    dependencies = (obj / (PREFIX + "__verFiles.dat")).read_text()
    require("VX_tcu_fedp_tfr" in hierarchy and all("g_blocks__BRA__" + str(slot) + "__KET__" in hierarchy
                                                  for slot in range(4)), "four native TFR blocks are not present")
    require(all(name in dependencies for name in ("VX_tcu_unit.sv", "VX_tcu_shared.sv", "VX_tcu_fedp_tfr.sv")),
            "native unit/shared/FEDP dependencies are missing")
    require(not re.search(r"VX_tcu_dpi|/hw/dpi/|VX_dpi_", hierarchy + dependencies, re.IGNORECASE),
            "DPI appears in the native unit hierarchy")
    return tuple(sorted(names))


def _fields(line, prefix):
    require(line.startswith(prefix + " "), "malformed unit marker")
    result = {}
    for word in line[len(prefix) + 1:].split(" "):
        pair = word.split("=")
        require(len(pair) == 2 and pair[0] not in result and re.fullmatch(r"[a-z_]+", pair[0]),
                "malformed or repeated unit field")
        result[pair[0]] = pair[1]
    return result


def verify_output(text):
    require(isinstance(text, str) and len(text.encode()) <= BUDGET["max_log_bytes"], "unit log exceeds its budget")
    require(not any(ord(char) < 32 and char not in "\r\n\t" for char in text), "invalid unit log control byte")
    lines = [line for line in text.splitlines() if line.strip()]
    require(len(lines) == len(GROUPS) + 2 and lines[-1] == "WGMMA_DIRECTED_PASS",
            "unit output lacks exactly eight groups, coverage and final pass")
    groups = []
    for line, (name, accepted, words) in zip(lines[:-2], GROUPS):
        row = _fields(line, "WGMMA_GROUP")
        require(set(row) == {"name", "accepted", "commits", "words", "cycles"} and row["name"] == name,
                "missing, duplicated or reordered unit scenario")
        require(all(re.fullmatch(r"[0-9]+", row[key]) for key in row if key != "name"), "invalid group counter")
        row = {key: int(value) if key != "name" else value for key, value in row.items()}
        require((row["accepted"], row["commits"], row["words"]) == (accepted, accepted, words)
                and 0 < row["cycles"] < CYCLE_LIMIT, "unit group count or watchdog differs")
        groups.append(row)
    raw = _fields(lines[-2], "WGMMA_COVERAGE")
    require(set(raw) == COVERAGE_FIELDS and all(re.fullmatch(r"[0-9]+", value) for value in raw.values()),
            "unit coverage fields differ")
    coverage = {key: int(value) for key, value in raw.items()}
    require(coverage["accepted"] == coverage["commits"] == sum(row[1] for row in GROUPS) == 392
            and coverage["words"] == sum(row[2] for row in GROUPS) == 3072, "unit totals do not reconcile")
    require(coverage["lmem_requests"] == coverage["lmem_responses"] > 0, "unit LMEM responses are incomplete")
    require((coverage["metadata_requests"], coverage["metadata_writes"], coverage["metadata_lanes"],
             coverage["delayed_metadata"]) == (8, 16, 64, 8), "metadata reload/split response coverage differs")
    for key in ("dispatch_stalls", "commit_holds", "lmem_holds", "delayed_lmem", "cta_conflicts",
                "cta_entries", "overlapping", "pressure_qualified"):
        require(coverage[key] > 0, "zero required unit coverage: " + key)
    require(coverage["pressure_tail"] == 8 and 8 < coverage["pressure_holds"] <= 256
            and coverage["pressure_qualified"] <= coverage["pressure_holds"], "causal commit pressure coverage differs")
    require((coverage["descriptor_a_poisoned"], coverage["descriptor_b_poisoned"]) == (238, 357),
            "descriptor latching sensitivity coverage differs")
    require(coverage["cycles"] == sum(row["cycles"] for row in groups)
            and coverage["watchdog"] == CYCLE_LIMIT and coverage["pressure_limit"] == 256,
            "unit cycle accounting or watchdog differs")
    return {"group_count": len(groups), "accepted_transactions": 392, "committed_transactions": 392,
            "checked_output_words": 3072, "groups": groups, "coverage": coverage,
            "cycle_watchdog_per_group": CYCLE_LIMIT}


def execute_run(args, paths):
    output, work, source = paths["output"], paths["work"], paths["source"]
    output.mkdir(mode=0o700)
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "started_at": _now(),
              "state": "running", "outcome": "blocked", "reason": None, "development": args.development,
              "acceptance_claimed": False, "qualifies_P02_A03": False, "phase_complete": False,
              "paths": {key: str(value) if value else None for key, value in paths.items()},
              "budget": dict(BUDGET, jobs=args.jobs, build_timeout_seconds=args.timeout_seconds,
                             run_timeout_seconds=args.run_timeout_seconds, cycle_watchdog_per_group=CYCLE_LIMIT),
              "configs": list(CONFIGS), "profile": "", "commands": [], "limitations": LIMITATIONS}
    initial_source = initial_tools = None
    env = clean_environment(paths, args.jobs)

    def checkpoint():
        _write_json(output / "report.json", report)

    def snapshot(name, value):
        relative = "snapshots/" + name + ".json"
        _write_json(output / relative, value)
        return hash_artifacts(output, [relative])[0]

    def copy_files(root, names, prefix):
        saved = []
        for name in sorted(set(names)):
            destination = output / prefix / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            original = root / name
            require(shutil.disk_usage(output).free - original.stat().st_size >= BUDGET["min_free_bytes"],
                    "retained artifact would breach the disk reserve")
            with original.open("rb") as incoming, destination.open("xb") as stream:
                shutil.copyfileobj(incoming, stream, length=MIB)
            saved.append(destination.relative_to(output).as_posix())
        return hash_artifacts(output, saved)

    def command(name, argv, cwd, timeout, environment=None):
        entry = {"id": name, "argv": [str(word) for word in argv], "cwd": str(cwd),
                 "environment": dict(env if environment is None else environment),
                 "log": "logs/" + name + ".log", "outcome": "running", "timeout_seconds": timeout,
                 "resources_before": _resources(paths)}
        report["commands"].append(entry)
        checkpoint()
        entry.update(run_bounded(entry["argv"], cwd, entry["environment"], output / entry["log"], timeout_seconds=timeout,
                                 **BUDGET, resource_paths=(source, paths["tools"], work, output)))
        checkpoint()
        require(entry["outcome"] == "pass" and entry["exit_code"] == 0 and entry["process_started"]
                and entry["cleanup_complete"], "command " + name + " stopped: " + str(entry.get("reason")))
        return entry

    def stable(label):
        observed = source_snapshot(source)
        report["source_" + label] = snapshot("source-" + label, observed)
        _source_ok(observed, args.development)
        require(observed == initial_source, "source changed during unit execution")
        require(tool_inventory(paths, env) == initial_tools, "selected unit tools changed during execution")
        checkpoint()

    try:
        for directory in ("logs", "snapshots", "artifacts"):
            (output / directory).mkdir()
        checkpoint()
        work.mkdir(mode=0o700)
        (work / "home").mkdir()
        (work / "tmp").mkdir()
        report["resources_before"] = _resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in report["resources_before"]["free_disk_bytes"].values()),
                "disk reserve is below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "at least 6 GiB available memory is required")
        require(hash_artifacts(source, TOOLING) == LOADED_HELPERS, "executing unit runner/helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial_source = source_snapshot(source)
        report["source_before"] = snapshot("source-before", initial_source)
        _source_ok(initial_source, args.development)
        report.update(source_revision=initial_source["checkout"]["revision"],
                      source_dirty=initial_source["checkout"]["dirty"])
        initial_tools = tool_inventory(paths, env)
        report["tools_before"] = snapshot("tools-before", initial_tools)
        report["source_snapshots"] = copy_files(source, [row["path"] for row in initial_source["files"]], "artifacts/source")
        require([dict(row, path=row["path"].removeprefix("artifacts/source/"))
                 for row in report["source_snapshots"]] == initial_source["files"],
                "retained source bytes differ from the initial snapshot")
        for name in ("g++", "make", "verilator"):
            command("version-" + name.replace("+", "p"), [initial_tools[name]["path"], "--version"], work, 30)
        build = work / "native-unit"
        build.mkdir()
        command("configure", [source / "configure", "--xlen=64", "--profile=", "--osversion=ubuntu/focal",
                              "--tooldir=" + str(paths["tools"])], build, 120)
        report["generated_before"] = generated_identity(build, source, paths["tools"])
        check = work / "header-check"
        check.mkdir()
        for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
            destination = check / Path(relative).name
            command(language + "-header-reproduce", [initial_tools["python3"]["path"], source / "ci/gen_config.py",
                "--config=" + str(source / "VX_config.toml"), "--profile=", "--format=" + language,
                "--output=" + str(destination)], build, 30, dict(env, XLEN="64"))
            require(destination.read_bytes() == (build / relative).read_bytes(), "generated header did not reproduce")
        stable("configured")
        command("native-build", [initial_tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
            "THREADS=" + str(args.jobs), "VERILATOR_PATH=" + str(paths["verilator"]),
            "CONFIGS=" + " ".join(CONFIGS), "all"], build / UNIT, args.timeout_seconds)
        records = validate_stamp((build / UNIT / "config.stamp").read_text(), source, build, args.jobs)
        report["compiler_records"] = records
        header = command("effective-header", [initial_tools["g++"]["path"], "-E", "-dM", "-x", "c++",
            *records[0]["macro_flags"], "-include", build / "sw/VX_config.h", "/dev/null"], build, 30)
        report["effective_configuration"] = validate_header((output / header["log"]).read_text())
        baseline_artifacts = hash_artifacts(build, build_artifacts(build))
        report["artifacts_before"] = baseline_artifacts
        retained = [row["path"] for row in baseline_artifacts if not row["path"].endswith(".cpp")]
        report["retained_artifacts"] = copy_files(build, retained, "artifacts/build")
        require([dict(row, path=row["path"].removeprefix("artifacts/build/"))
                 for row in report["retained_artifacts"]] == [row for row in baseline_artifacts if row["path"] in retained],
                "retained native artifacts differ from the built identities")
        stable("built")
        run = command("native-run", [build / UNIT / "tcu_wgmma", "--all"], build / UNIT, args.run_timeout_seconds)
        report["observations"] = verify_output((output / run["log"]).read_text(encoding="utf-8", errors="strict"))
        report["artifacts_after"] = hash_artifacts(build, build_artifacts(build))
        require(report["artifacts_after"] == baseline_artifacts, "native build artifacts changed during execution")
        stable("executed")
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError) as error:
        report.update(outcome="fail" if report["commands"] else "blocked", reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="unit execution interrupted")
    finally:
        if initial_source is not None:
            try:
                final_source = source_snapshot(source)
                report["source_after"] = snapshot("source-after", final_source)
                report["source_stable"] = final_source == initial_source
                require(report["source_stable"], "source changed during unit execution")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason=str(error))
        if initial_tools is not None:
            try:
                final_tools = tool_inventory(paths, env)
                report["tools_after"] = snapshot("tools-after", final_tools)
                require(final_tools == initial_tools, "selected unit tools changed during execution")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason=str(error))
        report.update(state="finished", finished_at=_now(), resources_after=_resources(paths))
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("run",))
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    parser.add_argument("--verilator", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=_timeout, default=1800)
    parser.add_argument("--run-timeout-seconds", type=_timeout, default=120)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute_run(args, resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
                          "report": str(Path(args.output).absolute() / "report.json"), "acceptance_claimed": False}))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
