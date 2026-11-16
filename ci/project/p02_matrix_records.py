# SPDX-License-Identifier: Apache-2.0
"""P02-specific checks for separate compiler records and fixture output.

The P01 packet parsers are reused as parsers only. Their frozen application and
XRT validation contracts are deliberately unchanged.
"""

import hashlib
import json
from pathlib import Path
import re

from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from compiler_records import _compiler_arguments, _records, _syntax


PROFILE_SHA256 = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
DISABLED = tuple("VX_CFG_TCU_" + name for name in (
    "TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4", "NVFP4",
    "SPARSE", "DSM", "WGMMA")) + ("VX_CFG_EXT_LDST_MATRIX",)
ENABLED = ("VX_CFG_EXT_TCU", "VX_CFG_TCU_FP16", "VX_CFG_LMEM")
VALUES = {
    "VX_CFG_XLEN": "64", "VX_CFG_NUM_CLUSTERS": "1", "VX_CFG_NUM_CORES": "1",
    "VX_CFG_NUM_WARPS": "4", "VX_CFG_NUM_THREADS": "4", "VX_CFG_ISSUE_WIDTH": "1",
    "VX_CFG_NUM_ALU_BLOCKS": "1", "VX_CFG_NUM_LSU_BLOCKS": "1",
    "VX_CFG_NUM_FPU_BLOCKS": "1", "VX_CFG_TCU_PE_RATIO": "1",
    "VX_CFG_TCU_LATENCY": "4", "VX_CFG_TCU_USE_DSP": "0",
}
RESULT_KEYS = {"case_id", "format", "m", "n", "k", "iteration", "checked",
               "mismatches", "actual_bits"}
HEX_WORD = re.compile(r"[0-9a-f]{8}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _configuration(defines, label, *, raw=False, selectors=False):
    require("__FAST_MATH__" not in defines and defines.get("__FINITE_MATH_ONLY__", "0") == "0",
            label + " enables fast math")
    for name, value in VALUES.items():
        require(defines.get(name) == value, label + " has missing/conflicting " + name)
    require(defines.get("VX_CFG_XLEN_64") == "1", label + " lacks RV64 selector")
    require(not any(name.startswith("VX_CFG_XLEN_") and name != "VX_CFG_XLEN_64"
                    for name in defines), label + " contains another XLEN selector")
    for prefix, native in (("VX_CFG_TCU_TYPE", "TFR"), ("VX_CFG_FPU_TYPE", "STD")):
        require(not any(name.startswith(prefix + "_") and name != prefix + "_" + native
                        for name in defines), label + " selects nonnative arithmetic")
        if raw:
            require(defines.get(prefix) == native, label + " lacks native profile enum")
        if selectors:
            require(defines.get(prefix + "_" + native) == "1",
                    label + " lacks resolved native arithmetic selector")
    for name in ENABLED:
        require(defines.get(name + "_ENABLE") == "1" and name + "_DISABLE" not in defines,
                label + " disables a required feature: " + name)
        require(defines.get(name + "_ENABLED", "1") == "1",
                label + " has a conflicting feature mirror: " + name)
    for name in DISABLED:
        require(name + "_ENABLE" not in defines, label + " enables an excluded feature: " + name)
        require(defines.get(name + "_ENABLED", "0") == "0",
                label + " has a conflicting feature mirror: " + name)
        if raw:
            require(defines.get(name + "_DISABLE") == "1",
                    label + " lacks explicit feature disable: " + name)
    require(not any(name.startswith(("VX_CFG_TCU_FEDP2K", "WGMMA_", "DBG_TRACE_"))
                    or name in {"DEBUG", "PERF_ENABLE", "VCD_OUTPUT", "SAIF_OUTPUT", "XRTSIM"}
                    for name in defines),
            label + " enables unsupported arithmetic, concurrency, or tracing")


def validate_header_macros(text):
    """Check the effective configuration reported by the C++ preprocessor."""
    defines = {}
    for line in text.splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
        if match:
            require(match[1] not in defines, "preprocessed header repeats a macro")
            defines[match[1]] = match[2] or "1"
    _configuration(defines, "generated header", selectors=True)
    return {name: value for name, value in defines.items() if name.startswith("VX_CFG_")}


def _rtl_arguments(words, label, source, jobs):
    """Check only the generated processor Verilator record's known syntax."""
    operands = {
        "--language": "1800-2012", "--replication-limit": "65536",
        "--x-initial": "unique", "--x-assign": "unique",
        "--cc": "rtlsim_shim", "--top-module": "rtlsim_shim", "-j": str(jobs),
    }
    seen = {}
    packages = {str(source / "hw/rtl" / name) for name in (
        "VX_gpu_pkg.sv", "fpu/VX_fpu_pkg.sv", "tcu/VX_tcu_pkg.sv", "VX_trace_pkg.sv")}
    found = set()
    pending = iter(words)
    for word in pending:
        if word in operands:
            require(word not in seen, label + " repeats a Verilator option")
            seen[word] = next(pending, None)
            require(seen[word] == operands[word], label + " has conflicting Verilator selection")
        elif word == "-MAKEFLAGS":
            require(next(pending, None) in ("OPT_FAST=-O2", "OPT_GLOBAL=-O2"),
                    label + " has unsupported nested make flags")
        elif word.startswith("-D"):
            require(len(word) > 2, label + " has an empty define")
        elif word.startswith("-I"):
            require(len(word) > 2 and not word[2:].startswith("-"), label + " has an invalid include")
        elif word in packages:
            require(word not in found, label + " repeats an RTL package")
            found.add(word)
        else:
            require(word in {"--exe", "--assert", "-Wall", "-Wpedantic", "-Wno-DECLFILENAME",
                             "-Wno-REDEFMACRO", "verilator.vlt"},
                    label + " contains unsupported Verilator flags or source operands")
    require(seen == operands and found == packages, label + " lacks processor RTL selections")


def _record(text, label, fmt, *, role, source, jobs, selectors=True):
    _syntax(text, label)
    words = _stamp_words(text, label)
    if role == "verilator":
        _rtl_arguments(words, label, source, jobs)
    else:
        _compiler_arguments(words, label, kernel=role == "kernel")
    require(not any(word == "-Ofast" or (word.startswith("-Wp,")
                    and "-Ofast" in word[4:].split(",")) for word in words),
            label + " enables fast math")
    require(not any(flag.startswith("-U") for flag in _stamp_flags(text, label)),
            label + " contains undefinitions")
    defines = _stamp_defines(text, label)
    _configuration(defines, label, raw=True, selectors=selectors)
    for name, value in (("ITYPE", fmt), ("OTYPE", "fp32"), ("KUNROLL", "1"), ("NDEBUG", "1")):
        require(defines.get(name) == value, label + " has missing/conflicting " + name)
    return {"role": role, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "macro_flags": _stamp_flags(text, label),
            "configuration": {key: value for key, value in defines.items()
                              if key.startswith("VX_CFG_") or key in ("ITYPE", "OTYPE", "KUNROLL")}}


def validate_records(runtime, backend, application, *, driver, fmt, source, build, jobs):
    """Validate every record independently; no configuration pooling is allowed."""
    require(driver in ("simx", "rtlsim") and fmt in ("fp16", "bf16"), "unsupported variant")
    source, build = Path(source), Path(build)
    runtime_lines = _records(runtime, "runtime stamp")
    backend_lines = _records(backend, "backend stamp")
    app_lines = _records(application, "application stamp")
    require(len(runtime_lines) == 1, "runtime stamp must contain one C++ record")
    require(len(backend_lines) == (2 if driver == "rtlsim" else 1),
            "backend stamp has the wrong number of independent records")
    require(len(app_lines) == 3, "application stamp must contain kernel, host and linker records")
    records = [(runtime_lines[0], "runtime")]
    records += list(zip(backend_lines, ("verilator", "backend_cpp") if driver == "rtlsim"
                        else ("backend_cpp",)))
    records += [(app_lines[0], "kernel"), (app_lines[1], "host")]
    # RTL arithmetic is selected by Verilator, not the host C++ shim.
    result = [_record(text, role + " stamp", fmt, role=role, source=source, jobs=jobs,
                      selectors=not (driver == "rtlsim" and role == "backend_cpp"))
              for text, role in records]
    _syntax(app_lines[2], "host linker stamp")
    require(_stamp_words(app_lines[2], "host linker stamp") == [
        str(source / "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a"),
        "-L" + str(build / "sw/runtime"), "-lvortex"],
        "host linker stamp differs from the generated runtime/dependency binding")
    return result


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate P02_RESULT JSON field")
        result[key] = value
    return result


def verify_output(text, case, iterations):
    """Require every returned bit and exactly the selected repeated launches."""
    require(iterations in (1, 2), "iterations must be one or two")
    require(not any(ord(char) < 32 and char not in "\t\n\r" for char in text),
            "host output contains invalid control bytes")
    lines = text.splitlines()
    require(sum(line.strip() == "PASSED!" for line in lines) == 1
            and len(re.findall(r"\bPASSED\b", text)) == 1,
            "host output must contain exactly one final PASSED! marker")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|Assertion .*failed|"
                          r"(?:Segmentation fault|core dumped|runtime error:)", text, re.IGNORECASE),
            "host output contains a failure marker")
    results = []
    marker_line = -1
    for index, line in enumerate(lines):
        if "P02_RESULT" not in line:
            continue
        require(line.startswith("P02_RESULT "), "malformed P02_RESULT marker")
        try:
            result = json.loads(line[len("P02_RESULT "):], object_pairs_hook=_unique_json,
                                parse_constant=lambda value: (_ for _ in ()).throw(
                                    ValueError("nonfinite P02_RESULT JSON value")))
        except json.JSONDecodeError as error:
            raise ValueError("malformed P02_RESULT JSON") from error
        require(isinstance(result, dict) and set(result) == RESULT_KEYS,
                "P02_RESULT has missing or unexpected fields")
        for key in ("m", "n", "k", "iteration", "checked", "mismatches"):
            require(type(result[key]) is int, "P02_RESULT integers must not be booleans or floats")
        require(result["case_id"] == case["id"] and result["format"] == case["format"],
                "P02_RESULT identifies another fixture")
        require(all(result[key] == case[key] for key in ("m", "n", "k")),
                "P02_RESULT dimensions differ from the fixture")
        require(result["iteration"] == len(results), "P02_RESULT iteration missing, repeated or reordered")
        require(result["checked"] == case["m"] * case["n"] and result["mismatches"] == 0,
                "P02_RESULT does not report all elements checked with zero mismatches")
        bits = result["actual_bits"]
        require(isinstance(bits, list) and all(isinstance(word, str) and HEX_WORD.fullmatch(word)
                                             for word in bits), "P02_RESULT bits are not hex8 strings")
        require(bits == case["expected"], "P02_RESULT bits differ from independent expected output")
        results.append({"iteration": result["iteration"], "checked": result["checked"],
                        "mismatches": 0, "actual_bits_sha256": hashlib.sha256(
                            b"".join(int(word, 16).to_bytes(4, "little") for word in bits)).hexdigest()})
        marker_line = index
    require(len(results) == iterations, "host output has the wrong number of P02_RESULT records")
    passed_line = next(index for index, line in enumerate(lines) if line.strip() == "PASSED!")
    require(passed_line > marker_line, "PASSED! precedes complete fixture results")
    require(not any(line.strip() and not re.fullmatch(r"make(?:\[[0-9]+\])?: Leaving directory .+", line)
                    for line in lines[passed_line + 1:]), "unexpected output after final PASSED!")
    return results
