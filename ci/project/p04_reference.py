#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze an integer-reference tiny MLP; no accelerator execution occurs.

The finite integer domain makes each P02 four-product reduction exact. The
reference uses direct integer matrix multiplication, never production tensor
arithmetic. Host ReLU and exact conversion are fixed placement, not fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from p02_layout_fixture_oracle import encode_integer, pack_memory


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json"
MODEL_ID = "p04-tiny-mlp-v1"
FIXTURE_ID = "p04-tiny-mlp-fixture-v1"
GENERATOR_VERSION = 1
FORMATS = ("fp16", "bf16")
FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
SEEDS = {"w1": 0x50403401, "w2": 0x50403402, "seeded_dense": 0x50403410}
MAX_FIXTURE_BYTES = 256 * 1024
WORD = re.compile(r"[0-9a-f]{8}\Z")


def xorshift_values(seed: int, count: int) -> list[int]:
    if (type(seed) is not int or not 0 < seed < 1 << 32
            or type(count) is not int or not 0 <= count <= 256):
        raise ValueError("a nonzero uint32 seed and bounded integer count are required")
    result = []
    state = seed
    for _ in range(count):
        state = (state ^ (state << 13)) & 0xFFFFFFFF
        state = (state ^ (state >> 17)) & 0xFFFFFFFF
        state = (state ^ (state << 5)) & 0xFFFFFFFF
        result.append(state % 5 - 2)
    return result


def _rows(values: list[int], width: int) -> list[list[int]]:
    return [values[start:start + width] for start in range(0, len(values), width)]


def logical_weights() -> tuple[list[list[int]], list[list[int]]]:
    return (_rows(xorshift_values(SEEDS["w1"], 128), 8),
            _rows(xorshift_values(SEEDS["w2"], 32), 4))


def logical_inputs(family: str) -> list[list[int]]:
    if family == "seeded_dense":
        return _rows(xorshift_values(SEEDS["seeded_dense"], 256), 16)
    if family == "negated_dense":
        return [[-value for value in row] for row in logical_inputs("seeded_dense")]
    if family == "zero":
        return [[0] * 16 for _ in range(16)]
    if family == "signed_basis":
        return [[(2 if row % 2 == 0 else -2) if column == row else 0
                 for column in range(16)] for row in range(16)]
    if family == "split_boundary":
        return [[(3 * row + 2 * column + 3 * (row // 8)) % 5 - 2
                 for column in range(16)] for row in range(16)]
    raise ValueError("unknown frozen input family")


def _check_matrix(matrix: list[list[int]], rows: int, columns: int,
                  minimum: int, maximum: int) -> None:
    if (type(matrix) is not list or len(matrix) != rows
            or any(type(row) is not list or len(row) != columns
                   or any(type(value) is not int or not minimum <= value <= maximum
                          for value in row) for row in matrix)):
        raise ValueError("matrix violates the fixed shape or exact integer domain")


def _multiply(a: list[list[int]], b: list[list[int]], bound: int) -> list[list[int]]:
    result = []
    for row in a:
        output = []
        for column in range(len(b[0])):
            total = 0
            for inner, left in enumerate(row):
                total += left * b[inner][column]
                if abs(total) > bound:
                    raise ValueError("an integer prefix exceeds the numerical proof bound")
            output.append(total)
        result.append(output)
    return result


def evaluate_network(inputs: list[list[int]], w1: list[list[int]] | None = None,
                     w2: list[list[int]] | None = None) -> dict:
    if w1 is None and w2 is None:
        w1, w2 = logical_weights()
    _check_matrix(inputs, 16, 16, -2, 2)
    _check_matrix(w1, 16, 8, -2, 2)
    _check_matrix(w2, 8, 4, -2, 2)
    hidden = _multiply(inputs, w1, 64)
    bridge = [[max(0, value) for value in row] for row in hidden]
    _check_matrix(bridge, 16, 8, 0, 64)
    output = _multiply(bridge, w2, 1024)
    return {"hidden": hidden, "bridge": bridge, "output": output}


def raw_words_sha256(words: list[str]) -> str:
    if (type(words) is not list or not words or len(words) > 256
            or any(type(word) is not str or WORD.fullmatch(word) is None for word in words)):
        raise ValueError("a bounded nonempty list of canonical uint32 words is required")
    return hashlib.sha256(b"".join(int(word, 16).to_bytes(4, "little")
                                   for word in words)).hexdigest()


def _flatten(matrix: list[list[int]]) -> list[int]:
    return [value for row in matrix for value in row]


def _column_major(matrix: list[list[int]]) -> list[int]:
    return [row[column] for column in range(len(matrix[0])) for row in matrix]


def _fp32_words(matrix: list[list[int]]) -> list[str]:
    return [f"{encode_integer(value, 'fp32'):08x}" for value in _flatten(matrix)]


def _check_properties(networks: dict, w2: list[list[int]]) -> None:
    dense = networks["seeded_dense"]
    hidden = _flatten(dense["hidden"])
    output = _flatten(dense["output"])
    if not min(hidden) < 0 < max(hidden) or len(set(output)) < 2:
        raise ValueError("dense fixture must exercise both activation branches and varied logits")
    linear = _multiply(dense["hidden"], w2, 1024)
    if linear == dense["output"]:
        raise ValueError("omitting ReLU must change the dense result")
    negated = _flatten(networks["negated_dense"]["output"])
    if not any(left + right != 0 for left, right in zip(output, negated)):
        raise ValueError("the paired dense fixtures must demonstrate nonlinearity")
    if any(value for stage in networks["zero"].values() for value in _flatten(stage)):
        raise ValueError("zero input must produce canonical zero intermediates and logits")
    split = networks["split_boundary"]["output"]
    if split[:8] == split[8:] or split[7] == split[8]:
        raise ValueError("row-split fixtures must distinguish the two output launches")


def fixture_document() -> dict:
    w1, w2 = logical_weights()
    networks = {family: evaluate_network(logical_inputs(family), w1, w2)
                for family in FAMILIES}
    _check_properties(networks, w2)
    encoded_weights = {}
    cases = []
    for format_name in FORMATS:
        weights = {"w1_words": pack_memory(_column_major(w1), format_name),
                   "w2_words": pack_memory(_column_major(w2), format_name)}
        weights["sha256"] = {name: raw_words_sha256(weights[name + "_words"])
                             for name in ("w1", "w2")}
        encoded_weights[format_name] = weights
        for family in FAMILIES:
            network = networks[family]
            case = {
                "id": format_name + "-" + family,
                "family": family,
                "format": format_name,
                "input_words": pack_memory(_flatten(logical_inputs(family)), format_name),
                "hidden_words": _fp32_words(network["hidden"]),
                "bridge_words": pack_memory(_flatten(network["bridge"]), format_name),
                "output_words": _fp32_words(network["output"]),
            }
            case["sha256"] = {name: raw_words_sha256(case[name + "_words"])
                              for name in ("input", "hidden", "bridge", "output")}
            cases.append(case)
    return {
        "schema_version": 1,
        "fixture_id": FIXTURE_ID,
        "model_id": MODEL_ID,
        "generator_version": GENERATOR_VERSION,
        "provenance": {
            "license": "Apache-2.0",
            "license_path": "LICENSE",
            "origin": "Repository-original deterministic synthetic weights and inputs.",
            "external_downloads": False,
            "pretrained_weights": False,
            "trained_accuracy_claimed": False,
            "gpu_execution_claimed": False,
        },
        "generator": {
            "path": "ci/project/p04_reference.py",
            "integer_encoding_helper": "ci/project/p02_layout_fixture_oracle.py",
            "algorithm": "xorshift32",
            "steps": ["s = (s ^ (s << 13)) & 0xffffffff",
                      "s = (s ^ (s >> 17)) & 0xffffffff",
                      "s = (s ^ (s << 5)) & 0xffffffff"],
            "emitted_value": "s % 5 - 2 after all three steps",
            "seeds": dict(SEEDS),
            "generation_order": "Separate streams for W1, W2 and dense X; each logical matrix is filled row-major.",
            "family_order": list(FAMILIES),
            "signed_basis": "X[r,k] = (2 if r is even else -2) if k == r else 0",
            "split_boundary": "X[r,k] = ((3*r + 2*k + 3*(r//8)) % 5) - 2",
            "production_model_used": False,
        },
        "model": {
            "equation": "Y = ReLU(X W1) W2",
            "batch_size": 16,
            "input_features": 16,
            "hidden_features": 8,
            "output_features": 4,
            "weight_count": 160,
            "bias": False,
            "softmax": False,
            "tokenizer": None,
            "formats": list(FORMATS),
            "output_dtype": "fp32",
            "input_layout": "row_major",
            "weight_layout": "column_major",
            "intermediate_and_output_layout": "row_major",
            "memory_byte_order": "little_endian",
            "packed_element_order": "Earlier memory element occupies the low 16 bits of each uint32 word.",
            "comparison": "uint32_bit_equality",
            "zero_result_bits": "00000000",
            "input_and_weight_integer_range": [-2, 2],
            "hidden_prefix_abs_max": 64,
            "bridge_integer_range": [0, 64],
            "output_prefix_abs_max": 1024,
            "initial_accumulator_bits": "00000000",
            "planned_native_mnk": [[16, 8, 16], [8, 4, 8], [8, 4, 8]],
            "host_work": ["relu_and_exact_cast", "row_partition", "copy_row_blocks"],
            "cpu_matmul_fallback": False,
            "execution_available": False,
            "reference_scope": "Independent integer source references only; native execution and dispatch evidence remain unearned.",
        },
        "weights": {"logical": {"w1": w1, "w2": w2}, "formats": encoded_weights},
        "cases": cases,
    }


def rendered_fixture() -> str:
    return json.dumps(fixture_document(), indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify frozen bytes without writing (default)")
    mode.add_argument("--write", action="store_true", help="deliberately regenerate the versioned source fixture")
    args = parser.parse_args(argv)
    try:
        data = rendered_fixture().encode("utf-8")
        if len(data) > MAX_FIXTURE_BYTES:
            raise ValueError("generated fixture exceeds its bounded size")
        if FIXTURE_PATH.is_symlink():
            raise ValueError("the fixed fixture path must not be a symlink")
        if args.write:
            FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE_PATH.write_bytes(data)
            print("Wrote 10 source-only tiny-MLP cases; no GPU execution.")
            return 0
        if (not FIXTURE_PATH.is_file() or FIXTURE_PATH.stat().st_size > MAX_FIXTURE_BYTES
                or FIXTURE_PATH.read_bytes() != data):
            raise ValueError("P04 fixture is missing or differs byte-for-byte")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Verified 10 source-only tiny-MLP cases byte-for-byte; no GPU execution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
