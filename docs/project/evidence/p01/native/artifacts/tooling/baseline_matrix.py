# SPDX-License-Identifier: Apache-2.0
"""Frozen native P01 case selection; no workload execution or gate acceptance."""

import json
from pathlib import Path
import re


MATRIX_ID = "p01-native-rv64-v1"
TOOLCHAIN_COMMIT = "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b"
MAX_MANIFEST_BYTES = 256 * 1024
DRIVERS = ("simx", "rtlsim")
WORKLOADS = {
    "gemm-fp16": ("sgemm_tcu", "fp16", 8, 2, "sgemm_tcu-3"),
    "gemm-bf16": ("sgemm_tcu", "bf16", 16, 1, "sgemm_tcu-4"),
    "attention-tf32": ("flash_attn_tcu_wg", "tf32", 4, 4,
                       "flash_attn_tcu_wg-rtlsim"),
}
TOP_FIELDS = {"schema_version", "id", "xlen", "toolchain_tag",
              "toolchain_commit", "os_bundle", "cases"}
CASE_FIELDS = {"id", "app", "driver", "configs", "args", "input_dtype",
               "output_dtype", "arithmetic", "catalog_source", "catalog_id",
               "derivation", "reference"}
REFERENCE_FIELDS = {"seed", "oracle", "comparison", "tolerances"}
DEFINE = re.compile(r"-D([A-Z][A-Z0-9_]*)(?:=([A-Za-z][A-Za-z0-9_]*|[0-9]+))?\Z")


def _object(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ValueError(label + " has missing or unknown fields")


def _text(value, label):
    if (type(value) is not str or not value.strip() or len(value) > 2048
            or any(ord(character) < 32 for character in value)):
        raise ValueError(label + " must be nonempty bounded text")


def _defines(tokens):
    if type(tokens) is not list or not tokens or len(tokens) > 32:
        raise ValueError("configs must be a bounded nonempty token list")
    values = {}
    for token in tokens:
        match = DEFINE.fullmatch(token) if type(token) is str else None
        if match is None:
            raise ValueError("unsafe or malformed configuration token")
        name, value = match.groups()
        if name in values:
            raise ValueError("duplicate configuration macro: " + name)
        values[name] = value
    return values


def _expected_defines(workload):
    app, dtype, threads, issue_width, _ = WORKLOADS[workload]
    result = {
        "VX_CFG_NUM_CLUSTERS": "1", "VX_CFG_NUM_CORES": "1",
        "VX_CFG_NUM_WARPS": "4", "VX_CFG_NUM_THREADS": str(threads),
        "VX_CFG_ISSUE_WIDTH": str(issue_width),
        "VX_CFG_EXT_TCU_ENABLE": None, "VX_CFG_TCU_TYPE_TFR": None,
        "VX_CFG_FPU_TYPE_STD": None, "ITYPE": dtype, "OTYPE": "fp32",
    }
    if app == "sgemm_tcu":
        result["VX_CFG_TCU_FP16_ENABLE"] = None
    else:
        result.update({
            "VX_CFG_NUM_ALU_BLOCKS": "1", "VX_CFG_NUM_LSU_BLOCKS": "1",
            "VX_CFG_NUM_FPU_BLOCKS": "1", "VX_CFG_TCU_TF32_ENABLE": None,
            "VX_CFG_TCU_WGMMA_ENABLE": None, "WGMMA_NRC": "8",
            "WGMMA_RS": None,
        })
    return result


def _validate_case(case):
    _object(case, CASE_FIELDS, "case")
    if type(case["driver"]) is not str or case["driver"] not in DRIVERS:
        raise ValueError("only simx and processor rtlsim are supported")
    if type(case["id"]) is not str:
        raise ValueError("case ID must be text")
    workload = case["id"].removesuffix("-" + case["driver"])
    if workload not in WORKLOADS or case["id"] != workload + "-" + case["driver"]:
        raise ValueError("unknown frozen case ID")
    app, dtype, _, _, catalog_id = WORKLOADS[workload]
    if case["app"] != app or case["input_dtype"] != dtype or case["output_dtype"] != "fp32":
        raise ValueError("case application/dtype disagrees with its frozen ID")
    if case["arithmetic"] != {"tensor": "TFR", "scalar": "STD"}:
        raise ValueError("native TFR tensor and STD scalar arithmetic are required")
    if _defines(case["configs"]) != _expected_defines(workload):
        raise ValueError("configuration differs from the frozen native case")
    expected_args = (["-m", "64", "-n", "64", "-k", "64"] if app == "sgemm_tcu"
                     else ["-N", "32", "-D", "16", "-c", "8", "-t", "8"])
    if type(case["args"]) is not list or case["args"] != expected_args:
        raise ValueError("unsafe arguments or dimensions differ from the frozen case")
    catalog = "ci/testcases/tensor.yaml" if app == "sgemm_tcu" else "ci/testcases/tensor_wg.yaml"
    if case["catalog_source"] != catalog or case["catalog_id"] != catalog_id:
        raise ValueError("catalog provenance differs from the frozen case")
    _text(case["derivation"], "derivation")
    reference = case["reference"]
    _object(reference, REFERENCE_FIELDS, "reference")
    if type(reference["seed"]) is not int or reference["seed"] != 50:
        raise ValueError("reference seed must remain 50")
    if reference["oracle"] != "tests/regression/" + app + "/main.cpp":
        raise ValueError("reference oracle differs from the frozen source")
    _text(reference["comparison"], "reference comparison")
    tolerance = reference["tolerances"]
    if app == "sgemm_tcu":
        _object(tolerance, {"relative_error_strict_max", "zero_pair_equal"}, "tolerances")
        if (type(tolerance["relative_error_strict_max"]) is not float
                or tolerance["relative_error_strict_max"] != 0.01
                or tolerance["zero_pair_equal"] is not True):
            raise ValueError("inherited GEMM tolerance must remain unchanged")
    else:
        _object(tolerance, {"atol", "rtol"}, "tolerances")
        if any(type(tolerance[name]) is not float or tolerance[name] != 0.001
               for name in ("atol", "rtol")):
            raise ValueError("inherited attention tolerances must remain unchanged")
    return case


def validate_matrix(matrix):
    """Reject drift from the versioned matrix and unsafe downstream shell tokens."""
    _object(matrix, TOP_FIELDS, "matrix")
    if type(matrix["schema_version"]) is not int or matrix["schema_version"] != 1:
        raise ValueError("unsupported matrix schema version")
    if matrix["id"] != MATRIX_ID or type(matrix["xlen"]) is not int or matrix["xlen"] != 64:
        raise ValueError("this matrix requires its frozen ID and RV64")
    if (matrix["toolchain_tag"] != "v3.0.2"
            or matrix["toolchain_commit"] != TOOLCHAIN_COMMIT
            or matrix["os_bundle"] != "ubuntu/focal"):
        raise ValueError("toolchain identity differs from the frozen matrix")
    cases = matrix["cases"]
    if type(cases) is not list or len(cases) != 6:
        raise ValueError("the complete matrix requires six cases")
    ids = set()
    for case in cases:
        _validate_case(case)
        if case["id"] in ids:
            raise ValueError("duplicate case ID: " + case["id"])
        ids.add(case["id"])
    if ids != {workload + "-" + driver for workload in WORKLOADS for driver in DRIVERS}:
        raise ValueError("matrix is missing required paired native coverage")
    return matrix


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field: " + key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def load_matrix(path):
    """Read a bounded UTF-8 manifest and validate it without executing commands."""
    try:
        path = Path(path)
        if not path.is_file():
            raise ValueError("matrix must be a regular file")
        with path.open("rb") as source:
            contents = source.read(MAX_MANIFEST_BYTES + 1)
        if len(contents) > MAX_MANIFEST_BYTES:
            raise ValueError("matrix exceeds the size limit")
        matrix = json.loads(contents.decode("utf-8"), object_pairs_hook=_unique_keys,
                            parse_constant=_reject_constant)
    except (OSError, UnicodeError, RecursionError) as error:
        raise ValueError("matrix is missing, unreadable or malformed") from error
    return validate_matrix(matrix)


def select_cases(matrix, case_ids=None):
    """Select a nonempty allowlist in manifest order; selection is not acceptance."""
    validate_matrix(matrix)
    if case_ids is None:
        return list(matrix["cases"])
    if (type(case_ids) not in (list, tuple) or not case_ids
            or any(type(case_id) is not str for case_id in case_ids)):
        raise ValueError("case selection must be a nonempty list of IDs")
    requested = set(case_ids)
    if len(requested) != len(case_ids):
        raise ValueError("duplicate selected case ID")
    known = {case["id"] for case in matrix["cases"]}
    if not requested <= known:
        raise ValueError("unknown selected case ID")
    return [case for case in matrix["cases"] if case["id"] in requested]


def command_for(case):
    _validate_case(case)
    return ["./ci/blackbox.sh", "--driver=" + case["driver"],
            "--app=" + case["app"], "--args=" + " ".join(case["args"])]


def config_for(case):
    _validate_case(case)
    return " ".join(case["configs"])
