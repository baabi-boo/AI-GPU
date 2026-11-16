#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Produce independent numerical matrices for the ordinary P02 WMMA profile.

Every matrix starts with FP32 C=+0 and accumulates in ascending four-product
FEDP groups. Expected bits come only from the frozen integer/Fraction oracle;
no production arithmetic model or host floating-point arithmetic is used.
Repeated A rows and B columns make each ordered scalar derivation apply to
all 32 outputs. These source fixtures do not claim GPU execution, arbitrary
initial-C coverage, or one correctly rounded operation for the whole GEMM.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

import p02_fixture_oracle as leaf
import p02_layout_fixture_oracle as layout


ROOT = Path(__file__).resolve().parents[2]
PRODUCER_PATH = "ci/project/p02_wmma_numerical_fixture_oracle.py"
PRODUCER_VERSION = 1
CONTRACT_ID = "p02-wmma-numerical-v1"
JSON_PATH = Path("ci/project/fixtures/p02_wmma_numerical_v1.json")
FIXTURE_PATH = ROOT / JSON_PATH
FORMATS = ("fp16", "bf16")
SHAPE = {"m": 8, "n": 4, "k": 8}
ROUNDING_ANCHORS = {
    "tie_even": ("3f800000", "3f800000"),
    "tie_odd": ("3f800001", "3f800002"),
    "tie_negative_even": ("bf800000", "bf800000"),
    "tie_negative_odd": ("bf800001", "bf800002"),
    "tie_carry": ("3fffffff", "40000000"),
    "sticky_negative_tail": ("3f800000", "3f800001"),
}


def packed_memory(elements: list[int]) -> list[str]:
    """Pack complete four-element groups, earlier addresses in low halves."""
    if not elements or len(elements) % 4:
        raise ValueError("a nonempty multiple of four input elements is required")
    return [f"{word:08x}" for start in range(0, len(elements), 4)
            for word in leaf.pack(elements[start:start + 4])]


def sequential_fedp(format_name: str, a: list[int], b: list[int]) -> list[dict]:
    """Evaluate ordered K quartets, retaining the exact accumulator handoffs."""
    if (format_name not in FORMATS or len(a) not in (8, 16) or len(b) != len(a)
            or any(type(value) is not int or not 0 <= value < 1 << 16
                   for value in a + b)):
        raise ValueError("one or two K8 tiles of raw FP16/BF16 inputs are required")
    accumulator = 0
    trace = []
    for start in range(0, len(a), 4):
        a_words = leaf.pack(a[start:start + 4])
        b_words = leaf.pack(b[start:start + 4])
        result = leaf.evaluate(format_name, a_words, b_words, accumulator)
        trace.append({
            "k_begin": start,
            "input_c": f"{accumulator:08x}",
            "a": [f"{word:08x}" for word in a_words],
            "b": [f"{word:08x}" for word in b_words],
            **result,
        })
        accumulator = int(result["expected"], 16)
    return trace


def make_case(format_name: str, name: str, family: str, category: str,
              a: list[int], b: list[int], source_leaf_ids: list[str],
              derivation: str) -> dict:
    trace = sequential_fedp(format_name, a, b)
    m, n, k = SHAPE["m"], SHAPE["n"], len(a)
    return {
        "id": f"{format_name}-numerical-{name}",
        "format": format_name,
        "family": family,
        "category": category,
        "dimensions": {"m": m, "n": n, "k": k},
        "leading_dimensions": {"lda": k, "ldb": k, "ldc": n},
        "tile_iterations": {"m": 1, "n": 1, "k": k // 8},
        "fedp_steps_per_output": k // 4,
        "a_words": packed_memory(a) * m,
        "b_words": packed_memory(b) * n,
        "expected": [trace[-1]["expected"]] * (m * n),
        "source_leaf_ids": source_leaf_ids,
        "intermediate_expected": [step["expected"] for step in trace],
        "fedp_trace": trace,
        "derivation": derivation,
    }


def format_cases(format_name: str, leaf_cases: list[dict] | None = None) -> list[dict]:
    if format_name not in FORMATS:
        raise ValueError("only FP16 and BF16 belong to the WMMA numerical contract")
    if leaf_cases is None:
        leaf_cases = leaf.fixture_document()["cases"]
    selected = [case for case in leaf_cases if case["format"] == format_name]
    by_id = {case["id"]: case for case in selected}
    zero_c = [case for case in selected if case["c"] == "00000000"]
    if len(zero_c) != 24 or len(by_id) != 49:
        raise ValueError("the frozen leaf inventory must have 24 zero-C cases per format")
    cases = []

    def unpack_source(source: dict, operand: str) -> list[int]:
        return list(leaf.unpack(tuple(int(word, 16) for word in source[operand])))

    for source in zero_c:
        name = source["id"][len(format_name) + 1:]
        case = make_case(
            format_name, name, "leaf_zero_c", source["category"],
            [0] * 4 + unpack_source(source, "a"),
            [0] * 4 + unpack_source(source, "b"), [source["id"]],
            "K=0..3 contributes zero; K=4..7 repeats the frozen zero-C leaf "
            "products. Keeping the leaf quartet last preserves signed output "
            "FTZ bits. " + source["derivation"],
        )
        if case["intermediate_expected"] != ["00000000", source["expected"]]:
            raise ValueError("zero-C leaf lifting changed its frozen expected bits")
        cases.append(case)

    one = leaf.small_exact(1, format_name)
    two = leaf.small_exact(2, format_name)
    ulp = leaf.small_exact(leaf.power_of_two(-23), format_name)
    for name, (initial, final) in ROUNDING_ANCHORS.items():
        source = by_id[f"{format_name}_{name}"]
        negative = name in ("tie_negative_even", "tie_negative_odd")
        sign = 0x8000 if negative else 0
        first_a = [one | sign, 0, 0, 0]
        first_b = [one, 0, 0, 0]
        if name in ("tie_odd", "tie_negative_odd"):
            first_a[1], first_b[1] = ulp | sign, one
        elif name == "tie_carry":
            first_a[:2], first_b[:2] = [two, ulp | 0x8000], [one, one]
        case = make_case(
            format_name, name, "two_fedp_rounding", source["category"],
            first_a + unpack_source(source, "a"),
            first_b + unpack_source(source, "b"), [source["id"]],
            f"K=0..3 constructs FP32 accumulator {initial} from low-precision "
            "products and C=+0. K=4..7 applies the frozen leaf products to "
            "that returned accumulator. " + source["derivation"],
        )
        if source["c"] != initial or case["intermediate_expected"] != [initial, final]:
            raise ValueError("two-FEDP rounding anchor failed: " + case["id"])
        cases.append(case)

    exponent_bits, fraction_bits, _, _ = leaf.FORMATS[format_name]
    maximum = (((1 << exponent_bits) - 1) << fraction_bits) - 1
    for negative in (False, True):
        sign_name = "negative" if negative else "positive"
        sign = 0x8000 if negative else 0
        case = make_case(
            format_name, f"four_maxfinite_{sign_name}", "four_maxfinite_products",
            "finite_extreme", [0] * 4 + [maximum | sign] * 4,
            [0] * 4 + [maximum] * 4,
            [f"{format_name}_finite_upper_bound_{sign_name}"],
            "K=0..3 contributes zero. K=4..7 reuses the four same-sign "
            "maxfinite products from the named leaf, with C=+0 instead of "
            "maximum finite FP32 C. FP16 remains finite; BF16 overflows "
            "to the corresponding signed infinity.",
        )
        expected = (("d07fc004" if negative else "507fc004")
                    if format_name == "fp16"
                    else ("ff800000" if negative else "7f800000"))
        if case["intermediate_expected"] != ["00000000", expected]:
            raise ValueError("four-maxfinite-product anchor failed: " + case["id"])
        cases.append(case)
    return cases


def cross_tile_cases(format_name: str) -> list[dict]:
    one = leaf.small_exact(1, format_name)
    half_ulp = leaf.small_exact(leaf.power_of_two(-24), format_name)
    cases = []
    for negative in (False, True):
        sign = 0x8000 if negative else 0
        sign_name = "negative" if negative else "positive"
        a, b = [0] * 16, [0] * 16
        a[0], a[4], a[8] = one | sign, half_ulp | sign, one | (sign ^ 0x8000)
        b[0] = b[4] = b[8] = one
        initial = "bf800000" if negative else "3f800000"
        reverse_final = "b3800000" if negative else "33800000"
        case = make_case(
            format_name, f"cross_tile_rounding_{sign_name}", "cross_tile_order",
            "tile_accumulation_order", a, b,
            [f"{format_name}_tie_negative_even" if negative else f"{format_name}_tie_even"],
            f"K=0..3 constructs FP32 accumulator {initial}. K=4..7 adds the "
            "same-sign 2^-24 half ULP and ties to even, retaining that "
            "accumulator. K=8..11 cancels it exactly; K=12..15 contributes "
            "zero. Reversing the two complete K8 tiles preserves each tile's "
            f"quartet order but returns {reverse_final} instead of +0. "
            "Independently rounded tile sums also return +0; this case "
            "distinguishes tile order, not independent tile rounding.",
        )
        if case["intermediate_expected"] != [initial, initial, "00000000", "00000000"]:
            raise ValueError("cross-tile forward anchor failed: " + case["id"])
        reverse = sequential_fedp(format_name, a[8:] + a[:8], b[8:] + b[:8])
        if reverse[-1]["expected"] != reverse_final:
            raise ValueError("cross-tile reversal anchor failed: " + case["id"])
        cases.append(case)
    return cases


def self_check(cases: list[dict]) -> None:
    if len(cases) != 68 or len({case["id"] for case in cases}) != 68:
        raise ValueError("the numerical inventory must contain 68 distinct cases")
    for format_name in FORMATS:
        selected = [case for case in cases if case["format"] == format_name]
        counts = {family: sum(case["family"] == family for case in selected)
                  for family in ("leaf_zero_c", "two_fedp_rounding", "four_maxfinite_products", "cross_tile_order")}
        if len(selected) != 34 or counts != {
                "leaf_zero_c": 24, "two_fedp_rounding": 6, "four_maxfinite_products": 2,
                "cross_tile_order": 2}:
            raise ValueError("each format requires 24 lifted, six chained, two extreme, and two tile-order cases")
        for case in selected:
            k = 16 if case["family"] == "cross_tile_order" else 8
            if (case["dimensions"] != {**SHAPE, "k": k}
                    or len(case["a_words"]) != 4 * k or len(case["b_words"]) != 2 * k
                    or case["tile_iterations"] != {"m": 1, "n": 1, "k": k // 8}
                    or case["fedp_steps_per_output"] != k // 4
                    or len(case["fedp_trace"]) != k // 4
                    or len(case["intermediate_expected"]) != k // 4
                    or len(case["expected"]) != 32
                    or case["expected"] != [case["intermediate_expected"][-1]] * 32):
                raise ValueError("numerical matrix packing or output replication differs")
    by_id = {case["id"]: case for case in cases}
    if by_id["bf16-numerical-half_min_normal_negative"]["expected"] != ["80000000"] * 32:
        raise ValueError("the lifted BF16 signed-FTZ anchor must retain negative zero")


def fixture_document() -> dict:
    leaf_cases = leaf.fixture_document()["cases"]
    cases = [case for format_name in FORMATS for case in format_cases(format_name, leaf_cases)]
    cases.extend(case for format_name in FORMATS for case in cross_tile_cases(format_name))
    self_check(cases)
    layout_document = layout.fixture_document()
    application = deepcopy(layout_document["application"])
    application["fixture_input_adapter"] = (
        "Named cases exported by ci/project/p02_wmma_fixtures.py to "
        "tests/regression/sgemm_tcu/p02_fixtures.h."
    )
    return {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "contract_version": 1,
        "claim_scope": "Independent sequential-FEDP numerical source matrices for ordinary WMMA; no GPU execution claimed.",
        "gpu_execution_claimed": False,
        "case_count": len(cases),
        "case_count_by_format": {"fp16": 34, "bf16": 34},
        "producer": {
            "path": PRODUCER_PATH,
            "version": PRODUCER_VERSION,
            "method": "Sequential four-product integer/Fraction evaluations with exact raw-bit accumulator handoffs.",
            "production_model_used": False,
            "leaf_oracle": leaf.PRODUCER_PATH,
            "leaf_contract_id": leaf.CONTRACT_ID,
            "leaf_fixture_path": leaf.JSON_PATH.as_posix(),
        },
        "application": application,
        "geometry": deepcopy(layout.GEOMETRY),
        "packing": deepcopy(layout_document["packing"]),
        "arithmetic": {
            "initial_accumulator_bits": "00000000",
            "fedp_order": "Ascending K in groups of four; each returned FP32 bit pattern becomes the next C.",
            "comparison": "uint32_bit_equality",
            "intermediate_expected": "K/4 FP32 results shared by every output, after each ascending four-product group.",
            "fedp_trace": "Representative output's packed operands, incoming C, and full independent leaf derivation at each step.",
            "whole_gemm_single_rounding_claimed": False,
            "arbitrary_initial_c_coverage": "Leaf-only; all WMMA cases here initialize C to positive zero.",
        },
        "coverage": {
            "shapes_mnk": [[8, 4, 8], [8, 4, 16]],
            "identical_rows_and_columns": True,
            "per_format": {"zero_c_leaf_lifts": 24, "two_fedp_rounding": 6, "four_maxfinite_products": 2,
                           "cross_tile_order": 2},
            "cross_tile_order": "Four K16 cases detect reversal of complete K8 tiles while preserving quartet order within each tile.",
            "independent_tile_rounding_distinguished": False,
            "signed_ftz": "The lifted quartet is last so a following zero FEDP cannot canonicalize a negative FTZ zero.",
            "layout_companion": "ci/project/fixtures/p02_layout_v1.json supplies distinct rows, columns and multiple tiles.",
        },
        "cases": cases,
    }


def render_json(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def generated_files(root: Path = ROOT) -> dict[Path, bytes]:
    return {Path(root) / JSON_PATH: render_json(fixture_document())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="generate the new numerical source fixtures")
    mode.add_argument("--check", action="store_true", help="check the numerical fixture bytes without changing them")
    args = parser.parse_args(argv)
    try:
        for path, data in generated_files().items():
            if args.write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            elif not path.is_file() or path.read_bytes() != data:
                raise ValueError("P02 WMMA numerical fixture is missing or differs byte-for-byte")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(("Wrote" if args.write else "Verified")
          + " 68 numerical source fixtures (34 per format); no GPU execution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
