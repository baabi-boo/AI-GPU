#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate independent, exact-integer sgemm_tcu memory-layout fixtures.

The inputs are small exactly representable integers. Every product and every
partial sum is exact in FP32, including each four-product FEDP boundary. This
producer uses integer arithmetic only; it never imports a production tensor
model or the separate fixed-window numerical oracle. These are source fixtures,
not a record of GPU execution or a fixture-input interface for sgemm_tcu.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "ci/project/fixtures/p02_layout_v1.json"
CONTRACT_ID = "p02-wmma-layout-v1"
FORMATS = {"fp16": (5, 10, 15), "bf16": (8, 7, 127), "fp32": (8, 23, 127)}
GEOMETRY = {
    "wmma_template": {"NT": 4, "NR": 8, "DK": 0, "DP": 0, "XB": 4},
    "tc_words": {"m": 2, "n": 2, "k": 2},
    "tile_words": {"m": 8, "n": 4, "k": 4},
    "tile_elements": {"m": 8, "n": 4, "k": 8},
    "steps": {"m": 4, "n": 2, "k": 2},
    "fragment_registers": {"a": 8, "b": 4, "c": 8},
    "input_elements_per_word": 2,
    "products_per_fedp": 4,
}


def encode_integer(value: int, format_name: str) -> int:
    """Encode an exactly representable integer; never round an input silently."""
    if type(value) is not int or format_name not in FORMATS:
        raise ValueError("an integer and a supported binary format are required")
    ebits, fbits, bias = FORMATS[format_name]
    if value == 0:
        return 0
    magnitude = abs(value)
    exponent = magnitude.bit_length() - 1
    if exponent + bias >= (1 << ebits) - 1:
        raise ValueError("integer overflows the selected format")
    shift = fbits - exponent
    if shift >= 0:
        significand = magnitude << shift
    else:
        significand, discarded = divmod(magnitude, 1 << -shift)
        if discarded:
            raise ValueError("integer is not exactly representable")
    sign = int(value < 0) << (ebits + fbits)
    return sign | ((exponent + bias) << fbits) | (significand - (1 << fbits))


def pack_memory(values: list[int], format_name: str) -> list[str]:
    """Pair consecutive 16-bit memory elements, earlier address in low half."""
    if format_name not in ("fp16", "bf16") or len(values) % 2:
        raise ValueError("an even number of FP16 or BF16 memory elements is required")
    elements = [encode_integer(value, format_name) for value in values]
    return [f"{elements[i] | (elements[i + 1] << 16):08x}"
            for i in range(0, len(elements), 2)]


def logical_inputs(kind: str, m: int, n: int, k: int,
                   hot_k: int | None = None) -> tuple[list[list[int]], list[list[int]]]:
    """Return logical A[M,K] and B[K,N], before the distinct memory layouts."""
    if any(type(value) is not int or value <= 0 or value % tile
           for value, tile in ((m, 8), (n, 4), (k, 8))):
        raise ValueError("positive multiples of the 8x4x8 tile are required")
    if kind == "k_onehot":
        if type(hot_k) is not int or not 0 <= hot_k < k:
            raise ValueError("onehot K index must lie inside the matrix")
        a = [[((-1 if row % 2 else 1) * (row + 1)) if inner == hot_k else 0
              for inner in range(k)] for row in range(m)]
        b = [[((-1 if col % 2 else 1) * (col + 1)) if inner == hot_k else 0
              for col in range(n)] for inner in range(k)]
    elif kind == "dense_boundaries":
        a = [[row + 1 + inner % 4 - 2 for inner in range(k)] for row in range(m)]
        b = [[col + 1 - (inner % 5 - 2) for col in range(n)] for inner in range(k)]
    elif kind == "cancellation":
        a = [[row + 1 for _ in range(k)] for row in range(m)]
        b = [[(1 if inner < k // 2 else -1) * (col + 1)
              for col in range(n)] for inner in range(k)]
        # Even rows cancel to +0; odd rows retain one positive column value.
        for row in range(1, m, 2):
            a[row][-1] -= 1
    else:
        raise ValueError("unknown fixture family")
    return a, b


def make_case(format_name: str, kind: str, m: int, n: int, k: int,
              hot_k: int | None = None) -> dict:
    if format_name not in ("fp16", "bf16"):
        raise ValueError("layout inputs must be FP16 or BF16")
    a, b = logical_inputs(kind, m, n, k, hot_k)
    output = []
    for row in range(m):
        for col in range(n):
            total = 0
            for inner in range(k):
                product = a[row][inner] * b[inner][col]
                total += product
                # This bound leaves all integer alignment and FP32 sums exact.
                if abs(product) >= 4096 or abs(total) >= 4096:
                    raise ValueError("fixture exceeds the exact-integer proof bound")
            output.append(f"{encode_integer(total, 'fp32'):08x}")
    shape = "single" if (m, n, k) == (8, 4, 8) else "multi"
    suffix = f"k{hot_k:02d}" if kind == "k_onehot" else kind
    case = {
        "id": f"{format_name}-{shape}-{suffix}",
        "format": format_name,
        "family": kind,
        "dimensions": {"m": m, "n": n, "k": k},
        "leading_dimensions": {"lda": k, "ldb": k, "ldc": n},
        "tile_iterations": {"m": m // 8, "n": n // 4, "k": k // 8},
        "fedp_steps_per_output": k // 4,
        "a_words": pack_memory([value for row in a for value in row], format_name),
        "b_words": pack_memory([b[inner][col] for col in range(n)
                                for inner in range(k)], format_name),
        "expected": output,
    }
    if hot_k is not None:
        case["onehot_k"] = hot_k
    return case


def fixture_document() -> dict:
    cases = []
    for format_name in ("fp16", "bf16"):
        for hot_k in (0, 3, 4, 7):
            cases.append(make_case(format_name, "k_onehot", 8, 4, 8, hot_k))
        for hot_k in (8, 15):
            cases.append(make_case(format_name, "k_onehot", 16, 8, 16, hot_k))
        for kind in ("dense_boundaries", "cancellation"):
            for m, n, k in ((8, 4, 8), (16, 8, 16)):
                cases.append(make_case(format_name, kind, m, n, k))
    return {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "contract_version": 1,
        "claim_scope": "Source application memory layout and independent exact-integer matrix products only.",
        "gpu_execution_claimed": False,
        "case_count": len(cases),
        "case_count_by_format": {"fp16": 10, "bf16": 10},
        "producer": {
            "path": "ci/project/p02_layout_fixture_oracle.py",
            "version": 1,
            "method": "integer encodings and direct integer matrix multiplication",
            "production_model_used": False,
        },
        "application": {
            "name": "sgemm_tcu",
            "source": "tests/regression/sgemm_tcu",
            "hardware_profile": "p02-tfr",
            "hardware_profile_path": "profiles/p02-tfr.json",
            "application_profile_id": "p02-tfr-rv64-t4-wmma-v1",
            "configuration_ids": {
                "fp16": "p02-tfr-rv64-t4-wmma-v1/fp16-fp32-kunroll1",
                "bf16": "p02-tfr-rv64-t4-wmma-v1/bf16-fp32-kunroll1",
            },
            "hardware_profile_shared_by_application_and_backend": True,
            "application_defines": {
                "fp16": ["-DITYPE=fp16", "-DOTYPE=fp32", "-DKUNROLL=1"],
                "bf16": ["-DITYPE=bf16", "-DOTYPE=fp32", "-DKUNROLL=1"],
            },
            "a_layout": "row_major",
            "b_layout": "col_major",
            "output_layout": "row_major",
            "element_addresses": {"a": "row*lda+k", "b": "col*ldb+k", "output": "row*ldc+col"},
            "leading_dimensions": {"lda": "K", "ldb": "K", "ldc": "N"},
            "initial_accumulator_bits": "00000000",
            "kunroll": 1,
            "dimension_rule": "Positive multiples of M=8, N=4, K=8; no tails, padding or arbitrary strides.",
            "fixture_input_adapter": "pending; existing sgemm_tcu generates its inputs and does not read this JSON",
        },
        "geometry": GEOMETRY,
        "packing": {
            "input_element_bits": 16,
            "input_word_bits": 32,
            "elements_per_word": 2,
            "memory_byte_order": "little_endian",
            "input_order": "Consecutive memory elements occupy low then high 16 bits of each word.",
            "a_words": "Complete row-major M*K input memory; lda=K elements.",
            "b_words": "Complete column-major K*N input memory; ldb=K elements.",
            "expected": "Complete row-major M*N FP32 output bits; ldc=N elements.",
            "hex_encoding": "Eight lowercase hexadecimal digits per 32-bit word, without a prefix.",
        },
        "exactness": {
            "input_values": "Small integers exactly representable in both FP16 and BF16.",
            "product_and_prefix_sum_abs_strict_max": 4096,
            "reason": "Every product and prefix sum is integral and below 2^12 in magnitude; each four-product fixed-window quantum divides every term exactly, and FP32 represents each sum exactly.",
            "comparison": "uint32_bit_equality",
            "zero_result_bits": "00000000",
            "whole_gemm_single_rounding_claimed": False,
        },
        "coverage": {
            "shapes_mnk": [[8, 4, 8], [16, 8, 16]],
            "onehot_k_indices": [0, 3, 4, 7, 8, 15],
            "boundaries": "First/last rows and columns, adjacent packed halves, four-product groups, and M=8/N=4/K=8 tile boundaries.",
            "cancellation": "Nonzero first-half sums cancel across FEDP boundaries and, for K=16, across K tiles; even rows produce +0 and odd rows retain a nonzero residual.",
        },
        "cases": cases,
    }


def render_json(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="generate the versioned source fixtures")
    mode.add_argument("--check", action="store_true", help="check frozen fixture bytes without changing them")
    args = parser.parse_args(argv)
    data = render_json(fixture_document())
    if args.write:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_bytes(data)
        print("Wrote 20 source layout fixtures (10 per format); no GPU execution.")
        return 0
    if not FIXTURE_PATH.is_file() or FIXTURE_PATH.read_bytes() != data:
        print("P02 layout fixture is missing or differs byte-for-byte", file=sys.stderr)
        return 1
    print("Verified 20 source layout fixtures byte-for-byte; no GPU execution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
