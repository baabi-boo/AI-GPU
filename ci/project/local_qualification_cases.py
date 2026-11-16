# SPDX-License-Identifier: Apache-2.0
"""Fixed supplemental AFU/RTL workloads and their unchanged reference checks."""

from copy import deepcopy
import re


CONTRACT_ID = "local-afu-rv64-v1"
SCALAR_CONFIGS = " ".join((
    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
    "-DVERILATOR_RESET_VALUE=1",
))
CORE_IDS = ("demo", "reopen-cold", "reopen-warm", "axi-store-order",
            "cp-llc-port", "mm-axi-arb")
TENSOR_IDS = ("gemm-fp16", "gemm-bf16")
MAX_LOG_BYTES = 16 * 1024 * 1024

_APP_SOURCES = (
    "ci/blackbox.sh", "tests/regression/common.mk",
    "sw/runtime/xrt/Makefile", "sw/runtime/xrt/vortex.cpp", "sw/runtime/xrt/xsim.tcl",
    "sim/xrtsim/Makefile", "sim/xrtsim/xrt_c.h", "sim/xrtsim/xrt_c.cpp",
    "sim/xrtsim/xrt_sim.h", "sim/xrtsim/xrt_sim.cpp",
    "sim/xrtsim/vortex_afu_shim.sv", "hw/rtl/afu/xrt/vortex_afu.v",
)
_APP_ARTIFACTS = (
    "sw/runtime/xrt_config.stamp", "sw/runtime/xrtsim_config.stamp",
    "sw/runtime/libvortex.so", "sw/runtime/libvortex-xrt.so", "sw/runtime/libxrtsim.so",
)


def _app(identifier, app, args, catalog, *, environment=None, configs=None,
         group="scalar", extra_sources=()):
    prefix = "tests/regression/" + app + "/"
    return {
        "id": identifier, "group": group, "kind": "app", "app": app,
        "configs": SCALAR_CONFIGS if configs is None else configs,
        "env": {} if environment is None else environment,
        "args": args, "catalog": catalog,
        "artifacts": [*_APP_ARTIFACTS, prefix + "config.stamp",
                      prefix + app, prefix + "kernel.vxbin"],
        "sources": [*_APP_SOURCES, prefix + "Makefile", prefix + "main.cpp",
                    prefix + "kernel.cpp", prefix + "common.h", *extra_sources],
    }


def _unit(identifier, app, rtl):
    prefix = "hw/unittest/" + app + "/"
    top = "VX_" + app + "_top"
    return {
        "id": identifier, "group": "units", "kind": "unit", "app": app,
        "configs": SCALAR_CONFIGS, "env": {}, "args": [],
        "catalog": "ci/testcases/unittest.yaml:hw-" + identifier,
        "artifacts": [prefix + app, prefix + "obj_dir/V" + top + ".mk"],
        "sources": ["ci/testcases/unittest.yaml", "hw/unittest/common.mk",
                    "hw/unittest/verilator.vlt.in", prefix + "Makefile",
                    prefix + "main.cpp", prefix + top + ".sv", rtl],
    }


def _tensor(dtype, threads, issue_width, catalog_id):
    configs = " ".join((
        "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
        "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=" + str(threads),
        "-DVX_CFG_ISSUE_WIDTH=" + str(issue_width), "-DVX_CFG_EXT_TCU_ENABLE",
        "-DVX_CFG_TCU_TYPE_TFR", "-DVX_CFG_FPU_TYPE_STD", "-DITYPE=" + dtype,
        "-DOTYPE=fp32", "-DVX_CFG_TCU_FP16_ENABLE",
    ))
    identifier = "gemm-" + dtype
    return _app(
        identifier, "sgemm_tcu", ["-m", "64", "-n", "64", "-k", "64"],
        "ci/project/p01_baseline.json:" + identifier + "-rtlsim; "
        "ci/testcases/tensor.yaml:" + catalog_id +
        "; unchanged numerical configuration, derived full-AFU xrtsim route",
        configs=configs, group=identifier,
        extra_sources=("ci/project/p01_baseline.json", "ci/testcases/tensor.yaml",
                       "sw/kernel/include/vx_tensor.h", "sw/common/tensor_cfg.h"),
    )


_CASES = {
    "demo": _app(
        "demo", "demo", ["-n1"],
        "P01 supplemental integer demo; derived RV64 native-STD reset-one configuration",
    ),
    "reopen-cold": _app(
        "reopen-cold", "reopen", ["-n1", "-i2"],
        "ci/testcases/regression.yaml:reopen-1; derived explicit one-point/two-session arguments",
        environment={"XRTSIM_WARM_OPEN": "0"},
        extra_sources=("ci/testcases/regression.yaml", "tests/regression/reopen/start.S"),
    ),
    "reopen-warm": _app(
        "reopen-warm", "reopen", ["-n1", "-i2"],
        "ci/testcases/regression.yaml:reopen-2; derived explicit one-point/two-session arguments",
        environment={"XRTSIM_WARM_OPEN": "1"},
        extra_sources=("ci/testcases/regression.yaml", "tests/regression/reopen/start.S"),
    ),
    "axi-store-order": _app(
        "axi-store-order", "stencil3d", ["-n64", "-b2"],
        "ci/testcases/stress.yaml:axi-store-order; derived explicit 64-cube/native-STD configuration",
        environment={"VX_MEM_RSP_REORDER": "1", "VX_MEM_RSP_STALL": "6"},
        extra_sources=("ci/testcases/stress.yaml",),
    ),
    "cp-llc-port": _unit("cp-llc-port", "cp_llc_port", "hw/rtl/mem/VX_cp_llc_port.sv"),
    "mm-axi-arb": _unit("mm-axi-arb", "mm_axi_arb", "hw/rtl/libs/VX_mm_axi_arb.sv"),
    "gemm-fp16": _tensor("fp16", 8, 2, "sgemm_tcu-3"),
    "gemm-bf16": _tensor("bf16", 16, 1, "sgemm_tcu-4"),
}
CASES = deepcopy(_CASES)


def select_cases(ids=None):
    """Return independent fixed records in catalog order; tensors require selection."""
    requested = list(CORE_IDS) if ids is None else ids
    if (type(requested) not in (list, tuple) or not requested
            or any(type(item) is not str or item not in _CASES for item in requested)
            or len(set(requested)) != len(requested)):
        raise ValueError("case IDs must be a nonempty unique selection from the fixed catalog")
    return [deepcopy(case) for name, case in _CASES.items() if name in requested]


def _case(case):
    if (type(case) is not dict or type(case.get("id")) is not str
            or case["id"] not in _CASES or case != _CASES[case["id"]]):
        raise ValueError("case differs from the fixed local qualification contract")
    return _CASES[case["id"]]


def command_for(case, jobs):
    """Return a fixed argv for a generated build tree."""
    case = _case(case)
    if type(jobs) is not int or jobs not in (1, 2):
        raise ValueError("local qualification requires one or two compile workers")
    if case["kind"] == "unit":
        return ["make", "-j" + str(jobs), "-C", "hw/unittest/" + case["app"], "run"]
    return ["./ci/blackbox.sh", "--driver=xrt", "--target=xrtsim",
            "--app=" + case["app"], "--args=" + " ".join(case["args"])]


_FAILURE = re.compile(
    r"\b(?:FAILED|MISMATCH)\b|\b(?:fatal\s+)?error\s*:|^\s*FAIL\b|"
    r"\*\*\*\s*FAIL\s*\*\*\*|assertion[^\n]*failed|"
    r"\b(?:Segmentation fault|Aborted|core dumped)\b|^%Error(?:-|:)|"
    r"^make(?:\[[0-9]+\])?:\s+\*\*\*|"
    r"\bFound\s+[1-9][0-9]*[^\n]*\berrors?\b",
    re.IGNORECASE | re.MULTILINE,
)
_SUCCESSES = {"PASSED!", "PASSED", "Test PASSED", "PASSED (0 failures)"}


def _ordered_once(lines, markers):
    positions = []
    for marker in markers:
        if lines.count(marker) != 1:
            raise ValueError("missing or duplicated result marker: " + marker)
        positions.append(lines.index(marker))
    if positions != sorted(positions):
        raise ValueError("result stages are out of order")
    return positions


def _arbiter(lines):
    sections = [
        "1. two masters, random traffic and back-pressure",
        "2. a slave that takes the data before the address",
        "3. single-beat writes with address and data offered together",
        "PASSED (0 failures)",
    ]
    bounds = _ordered_once(lines, sections)
    random = []
    early_data = []
    throughput = []
    for index, line in enumerate(lines):
        match = re.fullmatch(
            r"  seed ([1-8]): all writes and reads complete in order \(([1-9][0-9]*) cycles\) +PASS", line)
        if match:
            if not bounds[0] < index < bounds[1] or int(match[2]) > 200000:
                raise ValueError("AXI random-traffic result is outside its section or cycle bound")
            random.append(int(match[1]))
        match = re.fullmatch(
            r"  seed (1[1-4]): no deadlock, data still in address order +PASS", line)
        if match:
            if not bounds[1] < index < bounds[2]:
                raise ValueError("AXI data-first result is outside its section")
            early_data.append(int(match[1]))
        match = re.fullmatch(
            r"  one write per cycle \(([1-9][0-9]*) writes in ([1-9][0-9]*) cycles\) +PASS", line)
        if match:
            if not bounds[2] < index < bounds[3]:
                raise ValueError("AXI throughput result is outside its section")
            throughput.append({"writes": int(match[1]), "cycles": int(match[2])})
    if (random != list(range(1, 9)) or early_data != list(range(11, 15))
            or len(throughput) != 1 or throughput[0]["writes"] != 1000
            or throughput[0]["cycles"] > 1016
            or sum(bool(re.fullmatch(r"\s+.+\sPASS", line)) for line in lines) != 13):
        raise ValueError("AXI arbiter requires all thirteen original checks")
    return {"checks_passed": 13, "random_seeds": random,
            "data_before_address_seeds": early_data, "throughput": throughput[0]}


def verify_log(case, text):
    """Validate workload output after the caller verifies the command exit and budget."""
    case = _case(case)
    if (type(text) is not str or not text or len(text.encode("utf-8")) > MAX_LOG_BYTES
            or "\0" in text or _FAILURE.search(text)):
        raise ValueError("result log is invalid, oversized or contains failure evidence")
    lines = text.splitlines()
    identifier = case["id"]
    success = ("Test PASSED" if identifier.startswith("reopen-") else
               "PASSED" if identifier == "cp-llc-port" else
               "PASSED (0 failures)" if identifier == "mm-axi-arb" else "PASSED!")
    if [line.strip() for line in lines if line.strip() in _SUCCESSES] != [success]:
        raise ValueError("one unambiguous workload success marker is required")
    observed = {"outcome": "pass", "case_id": identifier, "success_marker": success}
    if identifier == "demo":
        _ordered_once(lines, [
            "open device connection", "data type: integer", "number of points: 16",
            "buffer size: 64 bytes", "upload source buffer0", "upload source buffer1",
            "load kernel module", "launch kernel", "download destination buffer",
            "wait for completion", "verify result", "cleanup", success,
        ])
        observed.update({"points": 16, "buffer_bytes": 64, "comparison": "exact integer"})
    elif identifier.startswith("reopen-"):
        stages = ["session " + str(i) + ": " + stage for i in range(2) for stage in (
            "open device connection", "upload + launch + readback", "close device connection")]
        _ordered_once(lines, [*stages, success])
        if [line for line in lines if line.startswith("session ")] != stages:
            raise ValueError("reopen requires exactly the two declared complete sessions")
        observed.update({"sessions": 2, "points_per_session": 1,
                         "warm_open_requested": identifier == "reopen-warm"})
    elif identifier == "axi-store-order":
        _ordered_once(lines, [
            "open device connection", "data type: float", "matrix size: 64x64x64",
            "block size: 2x2x2", "upload source buffer0", "load kernel module",
            "start device", "download destination buffer", "wait for completion",
            "verify result", "cleanup", success,
        ])
        reorder_lines = [line for line in lines if line.startswith("[xrtsim] response reordering:")]
        match = re.fullmatch(
            r"\[xrtsim\] response reordering: seed=1, ([1-9][0-9]*) responses returned ahead of an older ready one",
            reorder_lines[0] if len(reorder_lines) == 1 else "")
        if match is None:
            raise ValueError("requested memory stress requires positive observed response reordering")
        observed.update({"matrix": [64, 64, 64], "block": [2, 2, 2], "max_ulp": 6,
                         "reorder_seed": 1, "reordered_responses": int(match[1]),
                         "response_stall_requested": 6})
    elif identifier == "cp-llc-port":
        _ordered_once(lines, [success])
        observed["source_test_functions"] = 6
    elif identifier == "mm-axi-arb":
        observed.update(_arbiter(lines))
    else:
        dtype = identifier.removeprefix("gemm-")
        _ordered_once(lines, [
            "open device connection", "input data type: " + dtype +
            (" (id=2)" if dtype == "fp16" else " (id=3)"),
            "output data type: fp32 (id=0)", "matrix A: 64x64", "matrix B: 64x64",
            "matrix C: 64x64", "upload matrix A buffer", "upload matrix B buffer",
            "load kernel module", "[iter 0] launch kernel", "[iter 0] download destination buffer",
            "[iter 0] wait for completion", "[iter 0] verify result",
            "[iter 0] match (0 errors)", "cleanup", success,
        ])
        if set(re.findall(r"^\[iter ([0-9]+)\]", text, re.MULTILINE)) != {"0"}:
            raise ValueError("tensor case must execute exactly the declared iteration")
        observed.update({"input_dtype": dtype, "output_dtype": "fp32", "shape": [64, 64, 64],
                         "matched_iterations": 1, "relative_error_strict_max": 0.01,
                         "zero_pair_equal": True})
    return observed
