#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Produce the frozen four-product FP16/BF16 TFR contract fixtures.

All values are integers or Fractions; no host floating-point operations or
production arithmetic models are used. A nonzero product's scale exponent is
the sum of its operands' effective unbiased exponents (subnormals use 1-bias).
For W=25, the common quantum is 2**(max_scale_exponent-24), including C's scale
exponent. Each signed term is truncated toward zero to this quantum. The OR of
discarded remainders breaks a subsequent halfway tie without retaining signs.
This mathematical quantization rule is deliberately separate from the exact
rational dot product, which is also recorded with correctly rounded binary32.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
PRODUCER_PATH = "ci/project/p02_fixture_oracle.py"
PRODUCER_VERSION = 1
CONTRACT_ID = "p02-tfr-fp16-bf16-v1"
JSON_PATH = Path("ci/project/fixtures/p02_tfr_v1.json")
HEADER_PATH = Path("hw/unittest/common/p02_tfr_vectors.h")
FORMATS = {"fp16": (5, 10, 15, 2), "bf16": (8, 7, 127, 3)}
CANONICAL_NAN = 0x7FC00000


def power_of_two(exponent: int) -> Fraction:
    return (Fraction(1 << exponent) if exponent >= 0
            else Fraction(1, 1 << -exponent))


@dataclass(frozen=True)
class Number:
    kind: str
    sign: int
    value: Fraction | None
    exponent: int | None


def decode(bits: int, exponent_bits: int, fraction_bits: int,
           bias: int) -> Number:
    width = 1 + exponent_bits + fraction_bits
    if not 0 <= bits < 1 << width:
        raise ValueError("operand does not fit its declared format")
    sign = -1 if bits >> (width - 1) else 1
    exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
    fraction = bits & ((1 << fraction_bits) - 1)
    if exponent == (1 << exponent_bits) - 1:
        return Number("nan" if fraction else "infinity", sign, None, None)
    scale = max(exponent, 1) - bias
    significand = fraction + ((1 << fraction_bits) if exponent else 0)
    value = sign * significand * power_of_two(scale - fraction_bits)
    return Number("finite", sign, value, scale)


def floor_log2(value: Fraction) -> int:
    if value <= 0:
        raise ValueError("logarithm requires a positive value")
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    return exponent - (value < power_of_two(exponent))


def round_binary32(value: Fraction, *, sticky: bool = False,
                   flush_subnormal: bool = False) -> int:
    """Round by rational distances to binary32 neighbors, with an optional tail."""
    if not value:
        return 0
    sign = 0x80000000 if value < 0 else 0
    magnitude = abs(value)
    unit_exponent = floor_log2(magnitude) - 23
    if not flush_subnormal:
        unit_exponent = max(unit_exponent, -149)
    scaled = magnitude / power_of_two(unit_exponent)
    significand, remainder = divmod(scaled.numerator, scaled.denominator)
    twice_remainder = 2 * remainder
    if (twice_remainder > scaled.denominator
            or (twice_remainder == scaled.denominator
                and (sticky or significand & 1))):
        significand += 1
    if significand >= 1 << 24:
        significand >>= 1
        unit_exponent += 1
    if not significand:
        return sign
    if significand < 1 << 23:
        return sign | significand
    exponent = unit_exponent + 23
    if exponent > 127:
        return sign | 0x7F800000
    if exponent < -126:
        return sign
    return sign | ((exponent + 127) << 23) | (significand - (1 << 23))


def unpack(words: tuple[int, int]) -> tuple[int, ...]:
    if len(words) != 2 or any(not 0 <= word < 1 << 32 for word in words):
        raise ValueError("exactly two unsigned 32-bit packed words are required")
    return tuple((word >> shift) & 0xFFFF for word in words for shift in (0, 16))


def pack(elements: list[int]) -> tuple[int, int]:
    if len(elements) != 4 or any(not 0 <= item < 1 << 16 for item in elements):
        raise ValueError("exactly four unsigned 16-bit elements are required")
    return elements[0] | (elements[1] << 16), elements[2] | (elements[3] << 16)


def evaluate(format_name: str, a: tuple[int, int], b: tuple[int, int],
             c: int) -> dict:
    if format_name not in FORMATS:
        raise ValueError("only fp16 and bf16 belong to this contract")
    exponent_bits, fraction_bits, bias, _ = FORMATS[format_name]
    lhs = [decode(item, exponent_bits, fraction_bits, bias) for item in unpack(a)]
    rhs = [decode(item, exponent_bits, fraction_bits, bias) for item in unpack(b)]
    accumulator = decode(c, 8, 23, 127)
    invalid = accumulator.kind == "nan"
    infinity_signs = set()
    terms = []
    if accumulator.kind == "infinity":
        infinity_signs.add(accumulator.sign)
    elif accumulator.kind == "finite" and accumulator.value:
        terms.append((accumulator.value, accumulator.exponent))
    for left, right in zip(lhs, rhs):
        if left.kind == "nan" or right.kind == "nan":
            invalid = True
        elif left.kind == "infinity" or right.kind == "infinity":
            if left.value == 0 or right.value == 0:
                invalid = True
            else:
                infinity_signs.add(left.sign * right.sign)
        else:
            product = left.value * right.value
            if product:
                terms.append((product, left.exponent + right.exponent))
    if invalid or len(infinity_signs) == 2:
        return {"expected": f"{CANONICAL_NAN:08x}", "exact_fp32": f"{CANONICAL_NAN:08x}",
                "exception": "canonical_nan"}
    if infinity_signs:
        bits = 0x7F800000 | (0x80000000 if -1 in infinity_signs else 0)
        return {"expected": f"{bits:08x}", "exact_fp32": f"{bits:08x}",
                "exception": "signed_infinity"}

    exact = sum((value for value, _ in terms), Fraction())
    quantum_exponent = max(exponent for _, exponent in terms) - 24 if terms else None
    quantum = power_of_two(quantum_exponent) if terms else Fraction(1)
    units = 0
    discarded = False
    for value, _ in terms:
        scaled = abs(value) / quantum
        magnitude, remainder = divmod(scaled.numerator, scaled.denominator)
        units += magnitude if value > 0 else -magnitude
        discarded |= remainder != 0
    return {
        "expected": f"{round_binary32(units * quantum, sticky=discarded, flush_subnormal=True):08x}",
        "exact_fp32": f"{round_binary32(exact):08x}",
        "exact_rational": {"numerator": str(exact.numerator), "denominator": str(exact.denominator)},
        "window": {"quantum_exponent": quantum_exponent, "signed_units": units,
                   "discarded_nonzero": discarded},
    }


def small_exact(value: Fraction | int, format_name: str) -> int:
    """Encode an exactly representable finite seed; reject unintended rounding."""
    value = Fraction(value)
    if not value:
        return 0
    _, fraction_bits, bias, _ = FORMATS[format_name]
    sign = 0x8000 if value < 0 else 0
    magnitude = abs(value)
    exponent = floor_log2(magnitude)
    encoded_exponent = max(exponent + bias, 0)
    scale = max(encoded_exponent, 1) - bias - fraction_bits
    significand = magnitude / power_of_two(scale)
    if (significand.denominator != 1
            or not 0 <= encoded_exponent < (1 << FORMATS[format_name][0]) - 1):
        raise ValueError("seed is not exactly representable")
    fraction = int(significand) - ((1 << fraction_bits) if encoded_exponent else 0)
    if not 0 <= fraction < 1 << fraction_bits:
        raise ValueError("seed significand is out of range")
    return sign | (encoded_exponent << fraction_bits) | fraction


def format_cases(format_name: str) -> list[dict]:
    exponent_bits, fraction_bits, _, _ = FORMATS[format_name]
    one = small_exact(1, format_name)
    half = small_exact(Fraction(1, 2), format_name)
    half_ulp = small_exact(power_of_two(-24), format_name)
    min_subnormal = 1
    max_subnormal = (1 << fraction_bits) - 1
    min_normal = 1 << fraction_bits
    infinity = ((1 << exponent_bits) - 1) << fraction_bits
    maximum = infinity - 1
    cases = []

    def add(name, category, a, b=None, c=0, derivation=""):
        a_words = pack(a)
        b_words = pack(b if b is not None else [one] * 4)
        cases.append({
            "id": f"{format_name}_{name}", "format": format_name,
            "a": [f"{word:08x}" for word in a_words],
            "b": [f"{word:08x}" for word in b_words], "c": f"{c:08x}",
            "category": category, "derivation": derivation,
            **evaluate(format_name, a_words, b_words, c),
        })

    def encoded(values):
        return [small_exact(value, format_name) for value in values]

    add("zero", "zero", [0] * 4, derivation="All five terms are zero; the integer sum emits +0.")
    add("negative_zeros", "zero", [0x8000] * 4, c=0x80000000,
        derivation="Negative input zeros and negative C zero carry no integer magnitude; output is +0.")
    add("c_passthrough", "normal", [0] * 4, c=0x3EAAAAAB,
        derivation="Only C is nonzero; its full binary32 significand is retained.")
    add("dense_positive", "normal", encoded([1, 2, 3, 4]), encoded([5, 6, 7, 8]), 0x3F000000,
        "1*5 + 2*6 + 3*7 + 4*8 + 1/2 = 141/2 exactly.")
    add("dense_mixed_sign", "normal", encoded([1, -2, 3, -4]), encoded([4, 3, 2, 1]), 0xBE800000,
        "4 - 6 + 6 - 4 - 1/4 = -1/4 exactly.")
    add("dense_fractional", "normal", encoded([Fraction(3, 2), Fraction(1, 2), Fraction(-3, 4), 2]),
        encoded([Fraction(1, 4), Fraction(3, 2), 2, Fraction(1, 2)]), 0x3E000000,
        "3/8 + 3/4 - 3/2 + 1 + 1/8 = 3/4 exactly.")
    for lane in range(4):
        b = [0] * 4
        b[lane] = one
        add(f"packed_onehot_{lane}", "packed_onehot", encoded([1, 2, 4, 8]), b,
            derivation=f"Only logical element {lane} contributes 2^{lane}; element i occupies word i//2, bits 16*(i%2).")
    add("c_low_bit", "normal", [0] * 4, c=0x3F800001,
        derivation="The least significant bit of the FP32 C significand survives unchanged.")
    for name, c, product_sign, description in (
            ("tie_even", 0x3F800000, 0, "1 + 2^-24 is halfway; the even lower endpoint wins."),
            ("tie_odd", 0x3F800001, 0, "1 + 2^-23 + 2^-24 is halfway; the even upper endpoint wins."),
            ("tie_negative_even", 0xBF800000, 0x8000, "-(1 + 2^-24) is halfway; the even magnitude rounds to -1."),
            ("tie_negative_odd", 0xBF800001, 0x8000, "-(1 + 2^-23 + 2^-24) rounds to the even larger magnitude."),
            ("tie_carry", 0x3FFFFFFF, 0, "2 - 2^-23 + 2^-24 is halfway; rounding carries into exponent 1.")):
        add(name, "rounding_tie", [half_ulp | product_sign, 0, 0, 0], c=c, derivation=description)
    add("above_half", "rounding_sticky", [half_ulp, min_subnormal, 0, 0],
        [one, min_subnormal, 0, 0], 0x3F800000,
        "1 + 2^-24 + minsub^2 is above halfway; the discarded positive tail makes rounding increment.")
    add("cancel_products", "cancellation", [one, one | 0x8000, 0, 0],
        derivation="Equal opposite products cancel to an exact integer zero, which emits +0.")
    add("cancel_c", "cancellation", [one, 0, 0, 0], c=0xBF800000,
        derivation="The product +1 cancels the FP32 accumulator -1 exactly.")
    add("cancel_with_residual", "cancellation", [one, one | 0x8000, min_subnormal, 0],
        derivation="1 - 1 + minsub leaves an exact minsub; retention depends on the common quantum 2^-24.")
    add("cancel_large_with_tiny", "cancellation", [maximum, maximum | 0x8000, min_subnormal, 0],
        [one, one, one, 0],
        derivation="maxfinite - maxfinite + minsub has exact residual minsub; the residual is lost before cancellation, so TFR emits +0.")
    add("sticky_negative_tail", "rounding_sticky", [half_ulp, min_subnormal | 0x8000, 0, 0],
        [one, min_subnormal, 0, 0], 0x3F800000,
        "1 + 2^-24 - minsub^2 is below halfway exactly; unsigned discarded-tail OR makes the TFR halfway round upward.")
    add("tiny_positive", "tiny_term", [min_subnormal, 0, 0, 0], [min_subnormal, 0, 0, 0], 0x3F800000,
        "1 + minsub^2 rounds to 1; sticky alone cannot increment when the guard bit is zero.")
    add("tiny_negative", "tiny_term", [min_subnormal | 0x8000, 0, 0, 0],
        [min_subnormal, 0, 0, 0], 0x3F800000,
        "1 - minsub^2 rounds to 1; the small negative term is truncated and cannot set a guard bit.")
    add("opposed_c_infinity", "invalid", [infinity, 0, 0, 0], c=0xFF800000,
        derivation="A positive infinite product plus negative infinite C produces canonical 7fc00000.")
    add("input_min_subnormal", "input_subnormal", [min_subnormal, 0, 0, 0],
        derivation="minsub*1 preserves the input's exact value before output rounding and signed FTZ.")
    add("input_max_subnormal", "input_subnormal", [max_subnormal, 0, 0, 0],
        derivation="maxsub*1 has no implicit leading one; input subnormals are not flushed.")
    add("scaled_min_subnormal", "input_subnormal", [min_subnormal, 0, 0, 0], [maximum, 0, 0, 0],
        derivation="minsub*maxfinite is a normal FP32 result; this distinguishes gradual input handling from input flushing.")
    add("scaled_negative_subnormal", "input_subnormal", [min_subnormal | 0x8000, 0, 0, 0],
        [maximum, 0, 0, 0],
        derivation="(-minsub)*maxfinite is the exact negative of the normal scaled-subnormal result.")
    add("squared_min_subnormal", "input_subnormal", [min_subnormal, 0, 0, 0], [min_subnormal, 0, 0, 0],
        derivation="minsub^2 is exact before FP32 conversion; FP16 yields 2^-48, while BF16 is below the FP32 range.")
    add("input_min_normal", "extreme_exponent", [min_normal, 0, 0, 0],
        derivation="minnormal*1 exercises the smallest encoded normal input exponent.")
    for negative in (False, True):
        add(f"half_min_normal_{'negative' if negative else 'positive'}",
            "output_ftz" if format_name == "bf16" else "tiny_term",
            [min_normal | (0x8000 if negative else 0), 0, 0, 0], [half, 0, 0, 0],
            derivation="minnormal*1/2 is normal in FP32 for FP16; BF16 produces a subnormal FP32 magnitude and flushes it with its sign.")
    add("c_subnormal_positive", "output_ftz", [0] * 4, c=0x00000001,
        derivation="The exact FP32 C value 2^-149 is retained internally but final output FTZ emits +0.")
    add("c_subnormal_negative", "output_ftz", [0] * 4, c=0x80000001,
        derivation="The exact FP32 C value -2^-149 is retained internally; final output FTZ preserves its negative sign.")
    for negative in (False, True):
        add(f"finite_upper_bound_{'negative' if negative else 'positive'}", "overflow",
            [maximum | (0x8000 if negative else 0)] * 4, [maximum] * 4,
            0xFF7FFFFF if negative else 0x7F7FFFFF,
            "Four maxfinite products and same-sign maximum finite C overflow for BF16; FP16 products are too small to round the maximum C upward.")
    add("cancel_extreme_products", "extreme_exponent", [maximum, maximum | 0x8000, one, 0],
        [maximum, maximum, one, 0],
        derivation="maxfinite^2 - maxfinite^2 + 1 is exactly 1; exponent selection precedes cancellation and truncates the unit residual.")
    add("positive_infinity", "infinity", [infinity, 0, 0, 0],
        derivation="A positive infinite product dominates finite terms.")
    add("negative_infinity", "infinity", [infinity, 0, 0, 0], [one | 0x8000, one, one, one],
        derivation="Product infinity sign is the XOR of operand signs.")
    add("same_sign_infinities", "infinity", [infinity | 0x8000, 0, 0, 0], c=0xFF800000,
        derivation="Negative infinite product and negative infinite C retain negative infinity.")
    add("opposed_product_infinities", "invalid", [infinity, infinity | 0x8000, 0, 0],
        derivation="Opposite infinite products produce canonical 7fc00000.")
    add("infinity_times_zero", "invalid", [infinity, 0, 0, 0], [0, one, one, one],
        derivation="Infinity times zero is invalid even when every other term is finite zero.")
    add("input_quiet_nan", "nan", [infinity | 0x8000 | (1 << (fraction_bits - 1)) | 5, 0, 0, 0],
        derivation="A negative quiet NaN payload is discarded and canonical positive 7fc00000 is emitted.")
    add("input_signaling_nan", "nan", [infinity | 0x8001, 0, 0, 0],
        derivation="A negative signaling NaN is quieted to canonical positive 7fc00000.")
    add("c_quiet_nan", "nan", [one, 0, 0, 0], c=0xFFC12345,
        derivation="C's quiet NaN sign and payload are canonicalized to 7fc00000.")
    add("c_signaling_nan", "nan", [one, 0, 0, 0], c=0xFF812345,
        derivation="C's signaling NaN sign and payload are canonicalized to 7fc00000.")
    add("c_negative_infinity", "infinity", [one, 0, 0, 0], c=0xFF800000,
        derivation="Negative infinite C dominates the finite product +1.")
    add("zero_times_max_exponent", "extreme_exponent",
        [min_subnormal if format_name == "fp16" else min_normal, 0, 0, 0],
        [one, maximum, 0, 0],
        derivation="The zero product with maxfinite contributes no exponent; minsub*1 for FP16 and minnormal*1 for BF16 retain their exact FP32 values.")
    return cases


def self_check(cases: list[dict]) -> None:
    by_id = {case["id"]: case for case in cases}
    if len(cases) != 98 or len(by_id) != len(cases):
        raise ValueError("fixture inventory must contain 98 distinct cases")
    anchors = {
        "dense_positive": (0x428D0000, 0x428D0000),
        "dense_mixed_sign": (0xBE800000, 0xBE800000),
        "dense_fractional": (0x3F400000, 0x3F400000),
        "tie_even": (0x3F800000, 0x3F800000),
        "tie_odd": (0x3F800002, 0x3F800002),
        "tie_negative_even": (0xBF800000, 0xBF800000),
        "tie_negative_odd": (0xBF800002, 0xBF800002),
        "tie_carry": (0x40000000, 0x40000000),
        "sticky_negative_tail": (0x3F800001, 0x3F800000),
        "c_subnormal_negative": (0x80000000, 0x80000001),
        "cancel_extreme_products": (0x00000000, 0x3F800000),
    }
    for format_name in FORMATS:
        if sum(case["format"] == format_name for case in cases) != 49:
            raise ValueError("each format must contain 49 cases")
        for suffix, expected in anchors.items():
            case = by_id[f"{format_name}_{suffix}"]
            if (int(case["expected"], 16), int(case["exact_fp32"], 16)) != expected:
                raise ValueError(f"independent rational anchor failed: {case['id']}")
    for case_id, expected, exact in (
            ("fp16_cancel_large_with_tiny", "00000000", "33800000"),
            ("bf16_half_min_normal_negative", "80000000", "80400000"),
            ("fp16_finite_upper_bound_positive", "7f7fffff", "7f7fffff"),
            ("bf16_finite_upper_bound_positive", "7f800000", "7f800000"),
            ("fp16_zero_times_max_exponent", "33800000", "33800000"),
            ("bf16_zero_times_max_exponent", "00800000", "00800000")):
        if (by_id[case_id]["expected"], by_id[case_id]["exact_fp32"]) != (expected, exact):
            raise ValueError(f"independent boundary anchor failed: {case_id}")


def fixture_document() -> dict:
    cases = [case for format_name in FORMATS for case in format_cases(format_name)]
    self_check(cases)
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID,
        "producer": {"path": PRODUCER_PATH, "version": PRODUCER_VERSION},
        "configuration": {"packed_words": 2, "products": 4, "window_bits": 25,
                          "accumulator_bits": 30, "rounding": "RNE",
                          "formats": {name: value[3] for name, value in FORMATS.items()}},
        "arithmetic": {
            "effective_input_exponent": "max(encoded_exponent, 1) - bias",
            "common_quantum": "2^(max(nonzero product exponent sums, nonzero C exponent) - 24)",
            "alignment": "Truncate each signed exact term toward zero to the common quantum, then sum integers.",
            "discarded_tail": "OR nonzero discarded magnitudes irrespective of sign; use only to break a present halfway tie upward in magnitude.",
            "output": "Normalize and RNE first, then flush subnormal outputs with the integer-sum sign; an exact integer-sum zero is +0.",
            "exact_reference": "Correctly rounded exact rational sum with gradual binary32 underflow; rational zero is canonical +0. Nonfinite cases use the contract exception policy.",
            "exception_policy": "Any NaN, infinity times zero, or opposite infinities yields 7fc00000; otherwise retain infinity sign.",
        },
        "cases": cases,
    }


def render_json(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def render_header(document: dict) -> bytes:
    lines = [
        "// SPDX-License-Identifier: Apache-2.0", "", "#pragma once", "",
        "#include <array>", "#include <cstdint>", "", "namespace p02_tensor {", "",
        "inline constexpr uint32_t contract_version = 1;",
        "inline constexpr uint32_t packed_words = 2;", "",
        "struct Vector {", "  const char* id;", "  uint32_t fmt;",
        "  std::array<uint32_t, 2> a, b;", "  uint32_t c, expected;", "};", "",
        f"inline constexpr std::array<Vector, {len(document['cases'])}> vectors = {{{{",
    ]
    for case in document["cases"]:
        a = ", ".join(f"0x{word}u" for word in case["a"])
        b = ", ".join(f"0x{word}u" for word in case["b"])
        fmt = FORMATS[case["format"]][3]
        lines.extend([f"  {{\"{case['id']}\", {fmt}u, {{{{{a}}}}}, {{{{{b}}}}},",
                      f"   0x{case['c']}u, 0x{case['expected']}u}},"])
    lines.extend(["}};", "", "} // namespace p02_tensor", ""])
    return "\n".join(lines).encode("utf-8")


def generated_files(root: Path = ROOT) -> dict[Path, bytes]:
    document = fixture_document()
    return {root / JSON_PATH: render_json(document), root / HEADER_PATH: render_header(document)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify both frozen artifacts byte-for-byte")
    mode.add_argument("--write", action="store_true", help="explicitly generate the versioned fixture artifacts")
    args = parser.parse_args(argv)
    files = generated_files()
    if args.write:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        print("Wrote 98 fixtures and their C++ header (49 per format).")
        return 0
    failures = []
    for path, data in files.items():
        if not path.is_file():
            failures.append(f"missing frozen artifact: {path.relative_to(ROOT)}")
        elif path.read_bytes() != data:
            failures.append(f"frozen artifact differs byte-for-byte: {path.relative_to(ROOT)}")
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("Verified 98 frozen fixtures and their C++ header byte-for-byte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
