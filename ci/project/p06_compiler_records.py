# SPDX-License-Identifier: Apache-2.0
"""Validate original compiler records for the frozen timed SimX benchmark."""

from collections import Counter
import hashlib
from pathlib import Path
import re

from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from compiler_records import _compiler_arguments, _records, _syntax
from p02_matrix_records import DISABLED, ENABLED, VALUES, require


MAX_RECORD_BYTES = 1024 * 1024
WRAP_FLAGS = ("-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release")
MEMORY_VALUES = {
    "VX_CFG_SOCKET_SIZE": "1",
    "VX_CFG_MEM_BLOCK_SIZE": "64",
    "VX_CFG_ICACHE_SIZE": "16384",
    "VX_CFG_DCACHE_SIZE": "16384",
    "VX_CFG_SIMD_WIDTH": "4",
    "VX_CFG_NUM_LSU_LANES": "4",
    "VX_CFG_LMEM_NUM_BANKS": "4",
    "VX_CFG_LMEM_LOG_SIZE": "14",
    "VX_CFG_LMEM_SIZE": "16384",
}
HEADER_EXPRESSIONS = {
    "VX_CFG_SIMD_WIDTH": "VX_CFG_NUM_THREADS",
    "VX_CFG_NUM_LSU_LANES": "VX_CFG_SIMD_WIDTH",
    "VX_CFG_LMEM_NUM_BANKS": "VX_CFG_NUM_LSU_LANES",
    "VX_CFG_LMEM_LOG_SIZE": "__CLOG2(__MAX(16384, ((VX_CFG_LMEM_NUM_BANKS) * (2048))))",
    "VX_CFG_LMEM_SIZE": "__POW(2, VX_CFG_LMEM_LOG_SIZE)",
}
MEMORY_ENABLED = ("VX_CFG_ICACHE", "VX_CFG_DCACHE")
MEMORY_DISABLED = ("VX_CFG_L2", "VX_CFG_L3", "VX_CFG_VM")
COMMON_OPTIONS = {"-Wall", "-Wextra", "-Wfatal-errors", "-Werror"}
OPTIONS = {
    "runtime": COMMON_OPTIONS | {"-std=c++17", "-fPIC", "-O2"},
    "backend_cpp": COMMON_OPTIONS | {"-std=c++17", "-fPIC", "-O2", "-MMD", "-MP"},
    "kernel": COMMON_OPTIONS | {
        "-march=rv64imafd", "-mabi=lp64d", "-Wno-unused-command-line-argument",
        "-O3", "-mcmodel=medany", "-fno-rtti", "-fno-exceptions", "-nostartfiles",
        "-nostdlib", "-fdata-sections", "-ffunction-sections",
    },
    "host": COMMON_OPTIONS | {"-std=c++17", "-pedantic", "-O2"},
}
NONHARDWARE_MACROS = {
    "VX_PROFILE", "ITYPE", "OTYPE", "KUNROLL", "NDEBUG",
    "VX_DBG_STALL_TIMEOUT", "VX_DBG_DEBUG_LEVEL",
}


def _bounded_records(text, label):
    require(type(text) is str and len(text.encode("utf-8")) <= MAX_RECORD_BYTES,
            label + " is not bounded compiler-record text")
    return _records(text, label)


def _configuration(defines, label, *, performance, raw=False, expanded=True):
    require("__FAST_MATH__" not in defines and defines.get("__FINITE_MATH_ONLY__", "0") == "0",
            label + " enables fast math")
    require(not any(name.startswith(("SIMX_", "WGMMA_", "DBG_TRACE_", "TRACING_",
                                    "VX_CFG_TCU_FEDP2K"))
                    or name in {"DEBUG", "VCD_OUTPUT", "SAIF_OUTPUT", "XRTSIM",
                                "USE_SST", "USE_GEM5"} for name in defines),
            label + " changes timing mode, concurrency, arithmetic, or tracing")
    if performance:
        require(defines.get("PERF_ENABLE") == "1", label + " lacks enabled performance counters")
    else:
        require("PERF_ENABLE" not in defines, label + " unexpectedly defines PERF_ENABLE")
    for name, value in VALUES.items():
        require(defines.get(name) == value, label + " has missing/conflicting " + name)
    require(defines.get("VX_CFG_XLEN_64") == "1", label + " lacks RV64 selector")
    require(not any(name.startswith("VX_CFG_XLEN_") and name != "VX_CFG_XLEN_64"
                    for name in defines), label + " contains another XLEN selector")
    for prefix, native in (("VX_CFG_TCU_TYPE", "TFR"), ("VX_CFG_FPU_TYPE", "STD")):
        require(defines.get(prefix) == native, label + " lacks native profile enum")
        require(defines.get(prefix + "_" + native) == "1",
                label + " lacks resolved native arithmetic selector")
        require(not any(name.startswith(prefix + "_") and name != prefix + "_" + native
                        for name in defines), label + " selects nonnative arithmetic")
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
    for name, value in MEMORY_VALUES.items():
        choices = {value}
        if not raw and name in HEADER_EXPRESSIONS:
            choices.add(HEADER_EXPRESSIONS[name])
        require((not expanded and name not in defines) or defines.get(name) in choices,
                label + " has missing/conflicting " + name)
    for name in MEMORY_ENABLED:
        require(name + "_DISABLE" not in defines
                and defines.get(name + "_ENABLE", None if expanded else "1") == "1"
                and defines.get(name + "_ENABLED", None if expanded else "1") == "1",
                label + " changes the frozen cache configuration: " + name)
    for name in MEMORY_DISABLED:
        require(name + "_ENABLE" not in defines
                and defines.get(name + "_ENABLED", None if expanded else "0") == "0"
                and defines.get(name + "_DISABLE", "1") == "1",
                label + " enables an excluded memory feature: " + name)


def _options(words, label, *, role, source, build):
    """Check recorded driver options without executing or rewriting the record."""
    selected = []
    dependency_paths = []
    includes = []

    def scan(arguments, *, forwarded=False):
        pending = iter(arguments)
        preprocessor = []

        def operand():
            value = next(pending, None)
            require(value is not None, label + " has an option without an operand")
            return value

        for word in pending:
            option, separator, _ = word.partition("=")
            if word.startswith(("-D", "-U")):
                if len(word) == 2:
                    operand()
            elif option in ("--define-macro", "--undefine-macro"):
                if not separator:
                    operand()
            elif not forwarded and word.startswith("-Wp,"):
                preprocessor.extend(word[4:].split(","))
            elif not forwarded and word == "-Xpreprocessor":
                preprocessor.append(operand())
            elif word.startswith("-I"):
                require(not forwarded, label + " forwards an include search option")
                value = operand() if word == "-I" else word[2:]
                includes.append(value)
            elif word == "-MF" and not forwarded and role == "backend_cpp":
                dependency_paths.append(operand())
            else:
                require(not forwarded and word in OPTIONS[role],
                        label + " has an unexpected compiler option")
                selected.append(word)
        if preprocessor:
            scan(preprocessor, forwarded=True)

    scan(words)
    require(Counter(selected) == Counter(OPTIONS[role]),
            label + " has missing, repeated, or changed compiler options")
    expected = [str(build / "sw/runtime/simx_config.stamp")] if role == "backend_cpp" else []
    require(dependency_paths == expected, label + " changes the backend dependency-record target")
    expected_includes = {
        "runtime": [source / "sw/runtime/include", "../common", build / "sw", build / "hw",
                    source / "sim/simx", source / "sim/common", source / "sw/common",
                    source / "sw/runtime/common"],
        "backend_cpp": [source / "sim/simx",
                        *(source / "sim/simx" / name for name in
                          ("dxa", "tex", "om", "raster", "rtu", "kmu", "mem", "dtm")),
                        source / "sw/common", source / "sim/common", build / "sw", build / "hw",
                        source / "third_party", source / "third_party/softfloat/source/include",
                        source / "third_party/ramulator/ext/spdlog/include",
                        source / "third_party/ramulator/ext/yaml-cpp/include",
                        source / "third_party/ramulator/src", source / "sim/simx/tcu"],
        "kernel": [source / "sw/kernel/include", build / "sw", build / "hw", source / "sw/common"],
        "host": [source / "sw/runtime/ai", source / "sw/runtime/include",
                 source / "sw/kernel/include", build / "sw", build / "hw", source / "sw/common"],
    }
    require(includes == [str(path) for path in expected_includes[role]],
            label + " changes the frozen include search order")
    return includes


def _record(text, label, fmt, *, role, source, build):
    _syntax(text, label)
    words = _stamp_words(text, label)
    _compiler_arguments(words, label, kernel=role == "kernel")
    flags = _stamp_flags(text, label)
    require(not any(flag.startswith("-U") for flag in flags), label + " contains undefinitions")
    defines = _stamp_defines(text, label)
    performance = role == "backend_cpp"
    _configuration(defines, label, performance=performance, raw=True,
                   expanded=not performance)
    includes = _options(words, label, role=role, source=source, build=build)
    expected = {"VX_PROFILE": "p02-tfr", "ITYPE": fmt, "OTYPE": "fp32",
                "KUNROLL": "1", "NDEBUG": "1"}
    allowed = set(NONHARDWARE_MACROS)
    if performance:
        allowed.add("PERF_ENABLE")
        require(sum(flag[2:].partition("=")[0] == "PERF_ENABLE" for flag in flags) == 1,
                label + " repeats the performance-counter selector")
    if role == "kernel":
        allowed.add("__VORTEX__")
        expected["__VORTEX__"] = "1"
    if role == "host":
        allowed.update(("OMPI_SKIP_MPICXX", "MPICH_SKIP_MPICXX"))
        expected.update(OMPI_SKIP_MPICXX="1", MPICH_SKIP_MPICXX="1")
    if not performance:
        expected.update(VX_DBG_STALL_TIMEOUT="100000", VX_DBG_DEBUG_LEVEL="3")
    else:
        for name, value in (("VX_DBG_STALL_TIMEOUT", "100000"), ("VX_DBG_DEBUG_LEVEL", "3")):
            require(name not in defines or defines[name] == value,
                    label + " changes a frozen diagnostic default")
    require(all(name.startswith("VX_CFG_") or name in allowed for name in defines),
            label + " defines an unsupported compiler macro")
    require(all(defines.get(name) == value for name, value in expected.items()),
            label + " has missing/conflicting application or release-build selectors")
    return {"role": role, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "macro_flags": flags, "include_paths": includes,
            "configuration": {name: value for name, value in defines.items()
                              if name.startswith("VX_CFG_")
                              or name in ("ITYPE", "OTYPE", "KUNROLL", "PERF_ENABLE")}}


def validate_records(runtime, backend, application, *, fmt, source, build, jobs):
    """Validate each original runtime/backend/kernel/host record independently."""
    require(fmt in ("fp16", "bf16"), "unsupported benchmark format")
    require(type(jobs) is int and jobs in (1, 2), "unsupported benchmark job budget")
    source, build = Path(source), Path(build)
    require(source.is_absolute() and build.is_absolute()
            and ".." not in source.parts and ".." not in build.parts,
            "compiler bindings need absolute source and build paths")
    runtime_lines = _bounded_records(runtime, "benchmark runtime stamp")
    backend_lines = _bounded_records(backend, "benchmark backend stamp")
    app_lines = _bounded_records(application, "benchmark application stamp")
    require(len(runtime_lines) == len(backend_lines) == 1,
            "expected one independent runtime and one SimX backend record")
    require(len(app_lines) == 3, "expected separate kernel, host, and linker records")
    result = [_record(text, role + " benchmark stamp", fmt, role=role,
                      source=source, build=build) for text, role in (
        (runtime_lines[0], "runtime"), (backend_lines[0], "backend_cpp"),
        (app_lines[0], "kernel"), (app_lines[1], "host"))]
    _syntax(app_lines[2], "benchmark linker stamp")
    require(_stamp_words(app_lines[2], "benchmark linker stamp")
            == [*WRAP_FLAGS, "-L" + str(build / "sw/runtime"), "-lvortex"],
            "benchmark linker differs from the observed runtime binding")
    return result


def validate_header_macros(text, *, performance=False):
    """Check the original effective preprocessor output, including timing mode."""
    require(type(performance) is bool, "performance selection must be boolean")
    lines = _bounded_records(text, "benchmark preprocessor output")
    require(len(lines) <= 8192, "benchmark preprocessor output contains too many macros")
    defines = {}
    for line in lines:
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?(?:[ \t]+(.*))?", line)
        require(match is not None, "benchmark preprocessor output contains a non-macro record")
        require(match[1] not in defines, "benchmark preprocessor output repeats a macro")
        defines[match[1]] = "function-like" if match[2] else (match[3] or "1")
    _configuration(defines, "benchmark generated header", performance=performance)
    return {name: value for name, value in defines.items()
            if name.startswith("VX_CFG_") or name == "PERF_ENABLE"}
