#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify the frozen tiny-MLP source contract without executing a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import p02_layout_fixture_oracle as encoding_reference
import p04_reference as reference


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "ci/project/p04_model_manifest.json"
FIXTURE_PATH = "ci/project/fixtures/p04_tiny_mlp_v1.json"
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
ARTIFACT_PATHS = (
    FIXTURE_PATH,
    "ci/project/p04_reference.py",
    "ci/project/p04_model_contract.py",
    "ci/project/p02_layout_fixture_oracle.py",
    "ci/project/p03_operator_manifest.json",
    "profiles/p02-tfr.json",
    "VX_config.toml",
    "VX_types.toml",
    "ci/gen_config.py",
    "sw/runtime/ai/mlp_host.h",
    "sw/runtime/ai/mlp_host.cpp",
    "sw/runtime/ai/contract.h",
    "sw/common/ai_matmul_args.h",
    "sw/common/ai_matmul_profile.h",
    "docs/designs/tiny_mlp_fixture_v1.md",
    "docs/designs/tensor_numerics_v1.md",
    "LICENSE",
)
_IMPLEMENTATION_FILES = {
    "ci/project/p04_model_contract.py": Path(__file__),
    "ci/project/p04_reference.py": Path(reference.__file__),
    "ci/project/p02_layout_fixture_oracle.py": Path(encoding_reference.__file__),
}


class ContractError(ValueError):
    pass


def _plain_path(path: Path) -> Path:
    absolute = Path(path).absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ContractError(f"symlinks are not allowed: {path}")
    return absolute


def _read_file(path: Path, maximum: int) -> bytes:
    path = _plain_path(path)
    if type(maximum) is not int or maximum <= 0:
        raise ContractError("file size bound must be a positive integer")
    try:
        if not path.is_file() or path.stat().st_size > maximum:
            raise ContractError(f"missing, nonregular or oversized file: {path}")
        with path.open("rb") as source:
            data = source.read(maximum + 1)
    except OSError as error:
        raise ContractError(f"cannot read {path}: {error}") from error
    if len(data) > maximum:
        raise ContractError(f"oversized file: {path}")
    return data


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(token: str) -> None:
    raise ContractError(f"nonfinite JSON number: {token}")


def _float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ContractError(f"nonfinite JSON number: {token}")
    return value


def _parse(data: bytes, label: str) -> dict:
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_constant=_nonfinite, parse_float=_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ContractError(f"invalid JSON in {label}: {error}") from error
    if type(document) is not dict:
        raise ContractError(f"{label} must contain one JSON object")
    return document


def load_document(path: Path, max_bytes: int = MAX_DOCUMENT_BYTES) -> dict:
    return _parse(_read_file(Path(path), max_bytes), str(path))


def _same(actual: object, expected: object, path: str) -> None:
    if type(actual) is not type(expected):
        raise ContractError(f"{path}: expected {type(expected).__name__}")
    if type(expected) is dict:
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise ContractError(f"{path}: missing keys {missing}, unexpected keys {extra}")
        for key, value in expected.items():
            _same(actual[key], value, f"{path}.{key}")
    elif type(expected) is list:
        if len(actual) != len(expected):
            raise ContractError(f"{path}: expected {len(expected)} entries")
        for index, value in enumerate(expected):
            _same(actual[index], value, f"{path}[{index}]")
    elif actual != expected:
        raise ContractError(f"{path}: differs from the frozen contract")


def _required(actual: dict, expected: dict, path: str) -> None:
    if type(actual) is not dict:
        raise ContractError(f"{path}: expected dict")
    for key, value in expected.items():
        if key not in actual:
            raise ContractError(f"{path}: missing key {key}")
        _same(actual[key], value, f"{path}.{key}")


def _validate_inputs(contents: dict[str, bytes]) -> None:
    fixture = _parse(contents[FIXTURE_PATH], "fixture")
    _same(fixture, reference.fixture_document(), "fixture")
    if contents[FIXTURE_PATH] != reference.rendered_fixture().encode("utf-8"):
        raise ContractError("fixture: canonical UTF-8 file bytes differ from the producer")
    operators = _parse(contents["ci/project/p03_operator_manifest.json"], "P03 manifest")
    _required(operators, {"schema_version": 1, "contract_id": "p03-native-operators-v1",
                         "execution_available": True, "cpu_fallback": False}, "P03")
    entries = operators.get("operators")
    if type(entries) is not list or any(type(entry) is not dict for entry in entries):
        raise ContractError("P03 operators must be an object list")
    by_id = {}
    for entry in entries:
        name = entry.get("id")
        if type(name) is not str or name in by_id:
            raise ContractError("P03 operator identifiers must be unique strings")
        by_id[name] = entry
    if not {"matmul", "activation", "layout_cast"} <= set(by_id):
        raise ContractError("P03 must declare matmul, activation and layout_cast availability")
    _required(by_id["matmul"], {"state": "implemented"}, "P03.matmul")
    _required(by_id["matmul"].get("signature"), {
        "input_dtypes": ["fp16", "bf16"], "matching_input_dtypes_required": True,
        "accumulator_dtype": "fp32", "output_dtype": "fp32", "rank": 2,
        "shape_tuple_order": ["m", "n", "k"],
        "shape_tuples": [[8, 4, 8], [8, 4, 16], [16, 8, 16]],
        "a_layout": "row_major", "b_layout": "column_major", "d_layout": "row_major",
        "initial_c_bits": "00000000", "batch_count": 1,
        "transpose": False, "padding": False,
    }, "P03.matmul.signature")
    for name in ("activation", "layout_cast"):
        _required(by_id[name], {"state": "unavailable"}, f"P03.{name}")
    profile = _parse(contents["profiles/p02-tfr.json"], "P02 profile")
    # Inheritance and platform entries can override otherwise exact core/chip values.
    allowed_profile_fields = {"name", "xlen", "core", "chip", "description", "sources", "reference"}
    unexpected_fields = sorted(set(profile) - allowed_profile_fields)
    if unexpected_fields:
        raise ContractError(f"P02.profile: unexpected keys {unexpected_fields}")
    _required(profile, {"name": "p02-tfr", "xlen": 64}, "P02.profile")
    if not profile.get("sources"):
        raise ContractError("P02.profile.sources: provenance is required")
    if "reference" in profile and type(profile["reference"]) is not dict:
        raise ContractError("P02.profile.reference: expected dict")
    _same(profile.get("core"), {
        "VX_CFG_NUM_WARPS": 4, "VX_CFG_NUM_THREADS": 4, "VX_CFG_ISSUE_WIDTH": 1,
        "VX_CFG_NUM_ALU_BLOCKS": 1, "VX_CFG_NUM_LSU_BLOCKS": 1, "VX_CFG_NUM_FPU_BLOCKS": 1,
        "VX_CFG_FPU_TYPE": "STD", "VX_CFG_EXT_TCU_ENABLE": True,
        "VX_CFG_TCU_TYPE": "TFR", "VX_CFG_TCU_PE_RATIO": 1,
        "VX_CFG_TCU_LATENCY": 4, "VX_CFG_TCU_USE_DSP": 0,
        "VX_CFG_TCU_FP16_ENABLE": True, "VX_CFG_TCU_TF32_ENABLE": False,
        "VX_CFG_TCU_FP8_ENABLE": False, "VX_CFG_TCU_FP4_ENABLE": False,
        "VX_CFG_TCU_INT8_ENABLE": False, "VX_CFG_TCU_INT4_ENABLE": False,
        "VX_CFG_TCU_MX_ENABLE": False, "VX_CFG_TCU_MXFP4_ENABLE": False,
        "VX_CFG_TCU_NVFP4_ENABLE": False, "VX_CFG_TCU_SPARSE_ENABLE": False,
        "VX_CFG_TCU_DSM_ENABLE": False, "VX_CFG_TCU_WGMMA_ENABLE": False,
        "VX_CFG_LMEM_ENABLE": True, "VX_CFG_EXT_LDST_MATRIX_ENABLE": False,
    }, "P02.profile.core")
    _same(profile.get("chip"), {"VX_CFG_NUM_CLUSTERS": 1, "VX_CFG_NUM_CORES": 1},
          "P02.profile.chip")


def _inventory(root: Path) -> dict[str, bytes]:
    root = _plain_path(Path(root))
    if not root.is_dir():
        raise ContractError("source root must be an existing directory")
    contents = {path: _read_file(root / path, MAX_DOCUMENT_BYTES if path == FIXTURE_PATH
                                else MAX_ARTIFACT_BYTES) for path in ARTIFACT_PATHS}
    for path, invoking_path in _IMPLEMENTATION_FILES.items():
        if contents[path] != _read_file(invoking_path, MAX_ARTIFACT_BYTES):
            raise ContractError(
                f"{path}: target source differs from the invoking implementation; "
                "run the reviewed target's own checker for intentional source changes"
            )
    _validate_inputs(contents)
    return contents


def _graph() -> list[dict]:
    return [
        {"id": "hidden_matmul", "placement": "native", "operator": "matmul",
         "mnk": [16, 8, 16], "a": "input", "b": "w1", "output": "actual_hidden",
         "a_bytes": 512, "b_bytes": 256, "output_bytes": 512},
        {"id": "hidden_relu_cast", "placement": "host", "operator": "relu_and_exact_cast",
         "input": "actual_hidden", "output": "actual_bridge", "elements": 128,
         "input_bytes": 512, "output_bytes": 256,
         "helper": "vortex::ai::prepare_mlp_hidden", "compare_preactivation_first": True},
        {"id": "output_rows_0_7", "placement": "native", "operator": "matmul",
         "mnk": [8, 4, 8], "a": "actual_bridge", "rows": [0, 8], "a_offset_bytes": 0,
         "b": "w2", "output": "actual_output_rows_0_7",
         "a_bytes": 128, "b_bytes": 64, "output_bytes": 128},
        {"id": "output_rows_8_15", "placement": "native", "operator": "matmul",
         "mnk": [8, 4, 8], "a": "actual_bridge", "rows": [8, 16], "a_offset_bytes": 128,
         "b": "w2", "output": "actual_output_rows_8_15",
         "a_bytes": 128, "b_bytes": 64, "output_bytes": 128},
        {"id": "assemble_logits", "placement": "host", "operator": "copy_row_blocks",
         "inputs": ["actual_output_rows_0_7", "actual_output_rows_8_15"],
         "output": "actual_logits", "destination_offsets_bytes": [0, 128],
         "copy_bytes": [128, 128]},
    ]


def _manifest(contents: dict[str, bytes]) -> dict:
    return {
        "schema_version": 1,
        "model_id": "p04-tiny-mlp-v1",
        "fixture_id": "p04-tiny-mlp-fixture-v1",
        "contract_version": 1,
        "work_package": "P04-T01",
        "scope": "Frozen hybrid tiny-model source fixture; no model or device execution evidence.",
        "evidence_level": "source_present",
        "execution_available": False,
        "gpu_execution_claimed": False,
        "cpu_matmul_fallback": False,
        "execution_acceptances": {"P04-A02": "not_run", "P04-A03": "not_run"},
        "specification": "docs/designs/tiny_mlp_fixture_v1.md",
        "fixture": FIXTURE_PATH,
        "artifacts": [{"path": path, "sha256": hashlib.sha256(contents[path]).hexdigest()}
                      for path in ARTIFACT_PATHS],
        "operator_contract_id": "p03-native-operators-v1",
        "profile": "p02-tfr-rv64-t4-wmma-v1",
        "formats": ["fp16", "bf16"],
        "case_ids": [f"{format_name}-{family}" for format_name in reference.FORMATS
                     for family in reference.FAMILIES],
        "case_count": 10,
        "planned_native_launches_per_case": 3,
        "planned_native_launches_total": 30,
        "graph": _graph(),
        "host_work_allowlist": ["relu_and_exact_cast", "row_partition", "copy_row_blocks"],
        "reference_use": "Comparison only; every dependent operation consumes actual prior output.",
        "numerics": {
            "input_and_weight_integer_range": [-2, 2],
            "hidden_prefix_abs_max": 64, "bridge_integer_range": [0, 64],
            "output_prefix_abs_max": 1024, "initial_accumulator_bits": "00000000",
            "comparisons": ["hidden_words", "bridge_words", "output_words"],
            "comparison": "uint32_bit_equality", "absolute_tolerance": 0,
            "relative_tolerance": 0, "ulp_tolerance": 0,
            "bridge_rejects": ["nonfinite", "nonintegral", "outside_minus64_plus64"],
            "bridge_signed_zero": "normalize_to_positive_zero",
        },
        "representation": {
            "input_layout": "row_major", "weight_layout": "column_major",
            "intermediate_and_output_layout": "row_major", "byte_order": "little_endian",
            "word_encoding": "eight_lowercase_hex_digits", "earlier_element": "low_16_bits",
        },
        "future_execution_requirements": {
            "launches": "Three unique native operation IDs with actual runtime bindings and row ranges.",
            "host_records": "Host bridge and row copies are explicit, ordered, separately timed work.",
            "transfer_records": "Record A/B writes, output-poison writes and output reads separately.",
            "failure": "No CPU matmul fallback; preserve errors and drain retained operation resources.",
            "performance": "Report host, transfer and native work separately; no physical-speed inference.",
        },
        "resource_limits": {"fixture_bytes": MAX_DOCUMENT_BYTES,
                            "manifest_bytes": MAX_DOCUMENT_BYTES,
                            "artifact_bytes_each": MAX_ARTIFACT_BYTES},
        "provenance": {"license": "Apache-2.0", "original_synthetic_data": True,
                       "external_downloads": False, "trained_accuracy_claimed": False,
                       "tokenizer": None},
    }


def expected_manifest(root: Path = ROOT) -> dict:
    return _manifest(_inventory(Path(root)))


def validate(root: Path = ROOT) -> dict:
    root = Path(root)
    contents = _inventory(root)
    actual = load_document(root / MANIFEST_PATH)
    _same(actual, _manifest(contents), "manifest")
    return {"result": "pass", "scope": "source_present", "model_id": reference.MODEL_ID,
            "case_count": 10, "planned_native_launches": 30,
            "gpu_execution_claimed": False, "execution_available": False,
            "fixture_sha256": hashlib.sha256(contents[FIXTURE_PATH]).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify without writing (default)")
    mode.add_argument("--write-manifest", action="store_true",
                      help="deliberately pin the reviewed fixture and source artifact bytes")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="emit the source-only summary as JSON")
    args = parser.parse_args(argv)
    try:
        if args.write_manifest:
            document = expected_manifest(args.root)
            destination = _plain_path(args.root / MANIFEST_PATH)
            destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            print("Wrote the source-only tiny-MLP manifest; no execution acceptance granted.")
            return 0
        summary = validate(args.root)
    except (OSError, ValueError) as error:
        print(f"P04 contract: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print("Verified 10 tiny-MLP source cases and 30 planned launches; no GPU execution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
