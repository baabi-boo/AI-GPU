# SPDX-License-Identifier: Apache-2.0
"""Strict configuration and result checks for the fixed WGMMA processor matrix."""

import hashlib
import json
from pathlib import Path
import re

from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from compiler_records import _compiler_arguments, _records, _syntax
from p02_matrix_records import _rtl_arguments


HEX_WORD = re.compile(r"[0-9a-f]{8}\Z")
VALUES = {
    "VX_CFG_XLEN": "64", "VX_CFG_NUM_CLUSTERS": "1", "VX_CFG_NUM_CORES": "1",
    "VX_CFG_NUM_THREADS": "8", "VX_CFG_NUM_WARPS": "8", "VX_CFG_ISSUE_WIDTH": "4",
    "VX_CFG_FETCH_WIDTH": "2", "VX_CFG_NUM_ALU_BLOCKS": "1", "VX_CFG_NUM_LSU_BLOCKS": "1",
    "VX_CFG_NUM_FPU_BLOCKS": "1", "VX_CFG_NUM_TCU_BLOCKS": "4", "VX_CFG_NUM_TCU_LANES": "8",
    "VX_CFG_TCU_PE_RATIO": "1", "VX_CFG_TCU_LATENCY": "4", "VX_CFG_TCU_USE_DSP": "0",
    "VX_CFG_LMEM_LOG_SIZE": "14", "VX_CFG_LMEM_NUM_BANKS": "8",
}
ENABLED = ("VX_CFG_EXT_TCU", "VX_CFG_LMEM", "VX_CFG_TCU_FP16", "VX_CFG_TCU_WGMMA")
DISABLED = tuple("VX_CFG_TCU_" + name for name in
                 ("TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4", "NVFP4", "DSM")) + (
                     "VX_CFG_EXT_LDST_MATRIX",)
IDENTITY_KEYS = {"case_id", "format", "sparse", "mode", "a_layout", "iteration"}
BEGIN_KEYS = IDENTITY_KEYS | {"m", "n", "k", "words"}
RESULT_KEYS = IDENTITY_KEYS | {"checked", "mismatches", "actual_bits", "expected_bits"}
PASS_KEYS = {"case_id", "iterations", "checked"}
PERF = re.compile(r"PERF: instrs=([0-9]+), cycles=([0-9]+), IPC=([0-9]+(?:\.[0-9]+)?)\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def configuration(defines, variant, label, *, selectors=True):
    for name, value in VALUES.items():
        require(defines.get(name) == value, label + " has missing/conflicting " + name)
    require(defines.get("VX_CFG_XLEN_64") == "1", label + " lacks the RV64 selector")
    require(not any(name.startswith("VX_CFG_XLEN_") and name != "VX_CFG_XLEN_64"
                    for name in defines), label + " has another XLEN selector")
    for prefix, selected in (("VX_CFG_TCU_TYPE", "TFR"), ("VX_CFG_FPU_TYPE", "STD")):
        require(defines.get(prefix) == selected, label + " lacks native arithmetic enum")
        require(not any(name.startswith(prefix + "_") and name != prefix + "_" + selected
                        for name in defines), label + " selects nonnative arithmetic")
        if selectors:
            require(defines.get(prefix + "_" + selected) == "1", label + " lacks native selector")
    enabled = ENABLED + (("VX_CFG_TCU_SPARSE",) if variant["sparse"] else ())
    disabled = DISABLED + (() if variant["sparse"] else ("VX_CFG_TCU_SPARSE",))
    for name in enabled:
        require(defines.get(name + "_ENABLE") == "1" and name + "_DISABLE" not in defines
                and defines.get(name + "_ENABLED", "1") == "1", label + " disables " + name)
    for name in disabled:
        require(name + "_ENABLE" not in defines and defines.get(name + "_DISABLE") == "1"
                and defines.get(name + "_ENABLED", "0") == "0", label + " enables " + name)
    expected = {"ITYPE": variant["format"], "OTYPE": "fp32", "KUNROLL": "1", "WGMMA_NRC": "8",
                "PERF_ENABLE": "1", "WGMMA_" + variant["mode"].upper(): "1"}
    if variant["sparse"]:
        expected["P02_WGMMA_SPARSE"] = "1"
    if variant["a_layout"] == "row-major":
        expected["WGMMA_RMAJOR_A"] = "1"
    for name, value in expected.items():
        require(defines.get(name) == value, label + " has missing/conflicting " + name)
    conditional = {"WGMMA_RS", "WGMMA_SS", "WGMMA_RMAJOR_A", "P02_WGMMA_SPARSE"}
    require(not any(name in defines for name in conditional - expected.keys()),
            label + " selects another operand mode or layout")
    require("__FAST_MATH__" not in defines and defines.get("__FINITE_MATH_ONLY__", "0") == "0",
            label + " enables fast math")
    require(not any(name.startswith(("VX_CFG_TCU_FEDP2K", "DBG_TRACE_")) or name in {
                "DEBUG", "VCD_OUTPUT", "SAIF_OUTPUT", "XRTSIM"} for name in defines),
            label + " enables an excluded datapath or tracing")


def validate_header_macros(text, variant):
    defines = {}
    for line in text.splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
        if match:
            require(match[1] not in defines, "preprocessor output repeats a macro")
            defines[match[1]] = match[2] or "1"
    configuration(defines, variant, "effective compiler configuration")
    return {name: value for name, value in defines.items()
            if name.startswith(("VX_CFG_", "WGMMA_", "P02_"))
            or name in ("ITYPE", "OTYPE", "KUNROLL", "PERF_ENABLE")}


def validate_records(runtime, backend, application, *, driver, variant, source, build, jobs, witness=False):
    source, build = Path(source), Path(build)
    require(driver in ("simx", "rtlsim"), "unsupported processor driver")
    runtime_lines, backend_lines, app_lines = (_records(text, label) for text, label in (
        (runtime, "runtime stamp"), (backend, "backend stamp"), (application, "application stamp")))
    require(len(runtime_lines) == 1 and len(app_lines) == 3
            and len(backend_lines) == (2 if driver == "rtlsim" else 1), "unexpected compiler-record count")
    rows = [(runtime_lines[0], "runtime")]
    rows += list(zip(backend_lines, ("verilator", "backend_cpp") if driver == "rtlsim" else ("backend_cpp",)))
    rows += [(app_lines[0], "kernel"), (app_lines[1], "host")]
    output = []
    for text, role in rows:
        _syntax(text, role)
        words = _stamp_words(text, role)
        if role == "verilator":
            require(words.count("--assert") == 1, "Verilator record requires exactly one --assert")
            monitor = str(source / "sim/rtlsim/p02_wgmma_scoreboard_monitor.sv")
            require(words.count(monitor) == int(witness), "unexpected or missing witness source")
            _rtl_arguments([word for word in words if word != monitor], role, source, jobs)
        else:
            _compiler_arguments(words, role, kernel=role == "kernel")
        flags = _stamp_flags(text, role)
        require(not any(flag.startswith("-U") for flag in flags), role + " contains undefinitions")
        require(not any(word == "-Ofast" or (word.startswith("-Wp,") and "-Ofast" in word[4:].split(","))
                        for word in words), role + " enables fast math")
        defines = _stamp_defines(text, role)
        require(defines.get("NDEBUG") == "1", role + " is not the declared release build")
        require(defines.get("P02_WGMMA_WITNESS") == ("1" if witness else None),
                role + " has inconsistent witness selection")
        configuration(defines, variant, role, selectors=not (driver == "rtlsim" and role == "backend_cpp"))
        output.append({"role": role, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                       "macro_flags": flags, "configuration": {key: value for key, value in defines.items()
                       if key.startswith(("VX_CFG_", "WGMMA_", "P02_"))
                       or key in ("ITYPE", "OTYPE", "KUNROLL", "PERF_ENABLE")}})
    _syntax(app_lines[2], "host linker")
    require(_stamp_words(app_lines[2], "host linker") == ["-L" + str(build / "sw/runtime"), "-lvortex"],
            "host linker differs from the selected generated runtime")
    return output


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _json(text):
    return json.loads(text, object_pairs_hook=unique_json,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))


def verify_output(text, case, variant, *, witness=False):
    require(not any(ord(char) < 32 and char not in "\t\r\n" for char in text), "invalid output control byte")
    require(not re.search(r"(?:^|\n).*?(?:error:|fatal:|Assertion .*failed|Segmentation fault|core dumped|"
                          r"runtime error:|WGMMA verification failed)", text, re.IGNORECASE),
            "processor output contains a failure diagnostic")
    observations, current, passed = [], None, False
    cleanup_perf_duplicates = 0
    metadata_records = 0
    for line in text.splitlines():
        if line.startswith("P02_WGMMA_META "):
            require(witness and current is not None and not passed,
                    "metadata witness record outside a selected launch")
            require(type(_json(line[len("P02_WGMMA_META "):])) is dict, "invalid witness JSON")
            metadata_records += 1
            continue
        if line.startswith("P02_WGMMA_"):
            prefix, separator, payload = line.partition(" ")
            require(separator and prefix in ("P02_WGMMA_BEGIN", "P02_WGMMA_RESULT", "P02_WGMMA_PASS"),
                    "unknown or malformed WGMMA marker")
            require(not passed, "WGMMA record after final pass")
            record = _json(payload)
            require(type(record) is dict, "WGMMA marker must contain an object")
            if prefix == "P02_WGMMA_PASS":
                require(set(record) == PASS_KEYS and type(record["iterations"]) is int
                        and type(record["checked"]) is int and record == {
                            "case_id": case["id"], "iterations": 2, "checked": 1024}, "invalid final pass record")
                require(len(observations) == 2 and current is None
                        and all("performance" in item for item in observations), "pass precedes complete launches")
                passed = True
                continue
            expected_identity = {"case_id": case["id"], "format": case["format"], "sparse": case["sparse"],
                                 "mode": variant["mode"], "a_layout": variant["a_layout"],
                                 "iteration": len(observations)}
            require(type(record.get("sparse")) is bool and type(record.get("iteration")) is int,
                    "invalid identity value types")
            require(all(record.get(key) == value for key, value in expected_identity.items()),
                    "wrong fixture, configuration, or iteration")
            if prefix == "P02_WGMMA_BEGIN":
                require(set(record) == BEGIN_KEYS and current is None and len(observations) < 2
                        and all("performance" in item for item in observations), "duplicate or out-of-order begin")
                require(all(type(record[key]) is int and record[key] == value
                            for key, value in {"m": 64, "n": 8, "k": 16, "words": 512}.items()),
                        "begin dimensions do not match the frozen fixture")
                current = expected_identity
            else:
                require(set(record) == RESULT_KEYS and current == expected_identity, "result lacks matching begin")
                require(type(record["checked"]) is int and record["checked"] == 512
                        and type(record["mismatches"]) is int and record["mismatches"] == 0,
                        "incomplete or mismatching output")
                for key in ("actual_bits", "expected_bits"):
                    bits = record[key]
                    require(type(bits) is list and len(bits) == 512 and all(
                        type(word) is str and HEX_WORD.fullmatch(word) for word in bits), "invalid raw output bits")
                    require(bits == case["expected"], key + " differs from the independent frozen oracle")
                observations.append({**expected_identity, "checked": 512, "mismatches": 0,
                                     "actual_bits_sha256": hashlib.sha256(bytes.fromhex("".join(
                                         word[6:8] + word[4:6] + word[2:4] + word[0:2]
                                         for word in record["actual_bits"]))).hexdigest()})
                current = None
        elif "P02_WGMMA_" in line:
            raise ValueError("malformed WGMMA marker")
        elif match := PERF.fullmatch(line):
            require(not passed and current is None and observations, "unbound performance sample")
            perf = {"instructions": int(match[1]), "cycles": int(match[2]), "ipc": match[3]}
            require(perf["instructions"] > 0 and perf["cycles"] > 0, "empty performance sample")
            if "performance" not in observations[-1]:
                previous = observations[-2]["cumulative_performance"] if len(observations) > 1 else {
                    "instructions": 0, "cycles": 0}
                delta = {key: perf[key] - previous[key] for key in ("instructions", "cycles")}
                require(all(value > 0 for value in delta.values()), "nonincreasing cumulative counters")
                observations[-1]["cumulative_performance"] = perf
                observations[-1]["performance"] = dict(delta, derivation="cumulative_delta")
            else:
                require(len(observations) == 2 and cleanup_perf_duplicates == 0
                        and perf == observations[-1]["cumulative_performance"], "unexpected duplicate performance sample")
                cleanup_perf_duplicates += 1
        elif line.startswith("PERF: instrs="):
            raise ValueError("malformed total performance sample")
        elif passed and line.strip():
            require(re.fullmatch(r"make(?:\[[0-9]+\])?: Leaving directory .+", line) is not None,
                    "unexpected output after final pass")
    require(passed and len(observations) == 2 and current is None, "missing complete processor results")
    return {"launches": observations, "launch_count": 2, "checked_output_words": 1024,
            "cleanup_perf_duplicates": cleanup_perf_duplicates, "metadata_records": metadata_records}


def compare_pair(simx, rtl):
    require(len(simx) == len(rtl) == 2, "paired comparison requires two launches")
    comparisons = []
    for software, hardware in zip(simx, rtl):
        require(software["iteration"] == hardware["iteration"], "paired launch order differs")
        left, right = software["performance"], hardware["performance"]
        instruction_match = left["instructions"] == right["instructions"]
        delta = abs(left["cycles"] - right["cycles"])
        cycle_match = delta * 100 <= right["cycles"] * 5
        comparisons.append({"iteration": software["iteration"], "simx": left, "rtlsim": right,
                            "instructions_equal": instruction_match, "cycle_tolerance_percent": 5,
                            "cycle_delta": delta, "cycle_relative_denominator": "rtlsim_cycles",
                            "cycle_within_tolerance": cycle_match,
                            "outcome": "pass" if instruction_match and cycle_match else "fail"})
    return {"outcome": "pass" if all(item["outcome"] == "pass" for item in comparisons) else "fail",
            "launches": comparisons}
