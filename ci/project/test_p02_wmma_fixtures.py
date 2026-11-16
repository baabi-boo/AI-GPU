# SPDX-License-Identifier: Apache-2.0
"""Independent source-only checks of WMMA matrix arithmetic and strict export."""

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

import p02_wmma_fixtures as exporter
import p02_wmma_numerical_fixture_oracle as numerical


ROOT = Path(__file__).resolve().parents[2]
LEAF_PATH = Path("ci/project/fixtures/p02_tfr_v1.json")
FORMAT_FIELDS = {"fp16": (5, 10), "bf16": (8, 7), "fp32": (8, 23)}


def halfwords(words):
    memory = b"".join(bytes.fromhex(word)[::-1] for word in words)
    return tuple(int.from_bytes(memory[offset:offset + 2], "little")
                 for offset in range(0, len(memory), 2))


def fields(bits, format_name):
    exponent_width, fraction_width = FORMAT_FIELDS[format_name]
    exponent = (bits >> fraction_width) & ((1 << exponent_width) - 1)
    fraction = bits & ((1 << fraction_width) - 1)
    sign = -1 if bits >> (exponent_width + fraction_width) else 1
    if exponent == (1 << exponent_width) - 1:
        return "nan" if fraction else "infinity", sign, 0, 0
    bias = (1 << (exponent_width - 1)) - 1
    return ("finite", sign, fraction | ((1 << fraction_width) if exponent else 0),
            max(exponent, 1) - bias)


def rational(bits, format_name):
    kind, sign, mantissa, scale = fields(bits, format_name)
    if kind != "finite":
        raise AssertionError("a finite encoding is required")
    return sign * mantissa * Fraction(2) ** (scale - FORMAT_FIELDS[format_name][1])


@lru_cache(maxsize=None)
def nearest_binary32(value):
    """Choose neighboring IEEE encodings by rational distance, including ties."""
    if value == 0:
        return 0
    sign = 0x80000000 if value < 0 else 0
    magnitude = abs(value)
    maximum = rational(0x7F7FFFFF, "fp32")
    if magnitude > maximum:
        return sign | (0x7F800000 if magnitude >= (1 << 128) - (1 << 103)
                       else 0x7F7FFFFF)
    lower, upper = 0, 0x7F7FFFFF
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if rational(middle, "fp32") <= magnitude:
            lower = middle
        else:
            upper = middle - 1
    below = rational(lower, "fp32")
    if below == magnitude:
        return sign | lower
    above = rational(lower + 1, "fp32")
    distance_below, distance_above = magnitude - below, above - magnitude
    chosen = lower + (distance_above < distance_below
                      or (distance_above == distance_below and lower & 1))
    return sign | chosen


def rounded_window(units, quantum_exponent, sticky):
    if units == 0:
        return 0
    sign, magnitude = (0x80000000 if units < 0 else 0), abs(units)
    top_bit = magnitude.bit_length() - 1
    exponent = top_bit + quantum_exponent
    shift = top_bit - 23
    if shift > 0:
        retained, tail = divmod(magnitude, 1 << shift)
        halfway = 1 << (shift - 1)
        retained += tail > halfway or (tail == halfway and (sticky or retained & 1))
    else:
        retained = magnitude << -shift
    if retained == 1 << 24:
        retained >>= 1
        exponent += 1
    if exponent > 127:
        return sign | 0x7F800000
    if exponent < -126:
        return sign
    return sign | ((exponent + 127) << 23) | (retained & 0x7FFFFF)


@lru_cache(maxsize=None)
def independent_step(format_name, a, b, accumulator):
    """Reconstruct the specified 26-bit terms and 30-bit integer accumulator."""
    c_kind, c_sign, c_mantissa, c_scale = fields(accumulator, "fp32")
    invalid = c_kind == "nan"
    infinity_signs = {c_sign} if c_kind == "infinity" else set()
    terms, exact_terms = [], []
    if c_kind == "finite" and c_mantissa:
        terms.append((c_sign, c_mantissa << 1, c_scale + 260))
        exact_terms.append(rational(accumulator, "fp32"))
    fraction_width = FORMAT_FIELDS[format_name][1]
    for left, right in zip(a, b):
        l_kind, l_sign, l_mantissa, l_scale = fields(left, format_name)
        r_kind, r_sign, r_mantissa, r_scale = fields(right, format_name)
        if "nan" in (l_kind, r_kind):
            invalid = True
        elif "infinity" in (l_kind, r_kind):
            if ((l_kind == "finite" and l_mantissa == 0)
                    or (r_kind == "finite" and r_mantissa == 0)):
                invalid = True
            else:
                infinity_signs.add(l_sign * r_sign)
        elif l_mantissa and r_mantissa:
            widened = (l_mantissa * r_mantissa) << (24 - 2 * fraction_width)
            terms.append((l_sign * r_sign, widened, l_scale + r_scale + 260))
            exact_terms.append(rational(left, format_name) * rational(right, format_name))
    if invalid or len(infinity_signs) == 2:
        return {"expected": "7fc00000", "exact_fp32": "7fc00000", "exception": "canonical_nan"}
    if infinity_signs:
        result = "ff800000" if -1 in infinity_signs else "7f800000"
        return {"expected": result, "exact_fp32": result, "exception": "signed_infinity"}
    highest = max((exponent for _, _, exponent in terms), default=284)
    units, sticky = 0, False
    for sign, magnitude, exponent in terms:
        shift = highest - exponent
        aligned = magnitude >> shift
        units += sign * aligned
        sticky |= magnitude != aligned << shift
    if not -(1 << 29) <= units < 1 << 29:
        raise AssertionError("fixture exceeds the specified accumulator")
    exact = sum(exact_terms, Fraction())
    return {
        "expected": f"{rounded_window(units, highest - 284, sticky):08x}",
        "exact_fp32": f"{nearest_binary32(exact):08x}",
        "exact_rational": {"numerator": str(exact.numerator), "denominator": str(exact.denominator)},
        "window": {"quantum_exponent": highest - 284 if terms else None,
                   "signed_units": units, "discarded_nonzero": sticky},
    }


class WmmaNumericalFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / exporter.NUMERICAL_JSON).read_bytes())
        cls.layout = json.loads((ROOT / exporter.LAYOUT_JSON).read_bytes())
        cls.leaves = {case["id"]: case for case in json.loads((ROOT / LEAF_PATH).read_bytes())["cases"]}
        cls.cases = cls.document["cases"]
        cls.by_id = {case["id"]: case for case in cls.cases}

    def test_inventory_and_scope_preserve_the_separate_layout_companion(self):
        self.assertEqual(self.document["case_count"], 68)
        self.assertEqual(len(self.by_id), 68)
        self.assertEqual(Counter(case["format"] for case in self.cases), {"fp16": 34, "bf16": 34})
        self.assertEqual(len(self.layout["cases"]), 20)
        self.assertIs(self.document["gpu_execution_claimed"], False)
        self.assertIs(self.document["producer"]["production_model_used"], False)
        self.assertIs(self.document["arithmetic"]["whole_gemm_single_rounding_claimed"], False)
        self.assertIs(self.document["coverage"]["independent_tile_rounding_distinguished"], False)
        self.assertEqual(self.document["coverage"]["shapes_mnk"], [[8, 4, 8], [8, 4, 16]])
        self.assertEqual(self.document["arithmetic"]["initial_accumulator_bits"], "00000000")
        for fmt in ("fp16", "bf16"):
            selected = [case for case in self.cases if case["format"] == fmt]
            self.assertEqual(Counter(case["family"] for case in selected),
                             {"leaf_zero_c": 24, "two_fedp_rounding": 6,
                              "four_maxfinite_products": 2, "cross_tile_order": 2})
        self.assertEqual((ROOT / exporter.NUMERICAL_JSON).read_bytes(),
                         numerical.render_json(numerical.fixture_document()))

    def test_original_64_numerical_records_remain_unchanged_and_in_order(self):
        original_records = (json.dumps(self.cases[:64], indent=2, ensure_ascii=True) + "\n").encode()
        self.assertEqual(hashlib.sha256(original_records).hexdigest(),
                         "cede2e078427b5ed07a1dba473255e122eca37bd461967dc0ec8d78fb6624a24")
        self.assertEqual([case["id"] for case in self.cases[64:]], [
            f"{fmt}-numerical-cross_tile_rounding_{sign}"
            for fmt in ("fp16", "bf16") for sign in ("positive", "negative")])

    def test_every_output_and_recorded_derivation_from_independently_decoded_memory(self):
        output_count = 0
        for case in self.layout["cases"] + self.cases:
            m, n, k = (case["dimensions"][key] for key in ("m", "n", "k"))
            a, b = halfwords(case["a_words"]), halfwords(case["b_words"])
            self.assertEqual((len(a), len(b), len(case["expected"])), (m * k, n * k, m * n))
            for row in range(m):
                for col in range(n):
                    with self.subTest(case=case["id"], row=row, col=col):
                        accumulator = 0
                        for start in range(0, k, 4):
                            left = a[row * k + start:row * k + start + 4]
                            right = b[col * k + start:col * k + start + 4]
                            result = independent_step(case["format"], left, right, accumulator)
                            if "fedp_trace" in case:
                                step = case["fedp_trace"][start // 4]
                                self.assertEqual(step["k_begin"], start)
                                self.assertEqual(step["input_c"], f"{accumulator:08x}")
                                self.assertEqual(halfwords(step["a"]), left)
                                self.assertEqual(halfwords(step["b"]), right)
                                self.assertEqual({key: value for key, value in step.items()
                                                  if key not in ("a", "b", "k_begin", "input_c")}, result)
                                self.assertEqual(case["intermediate_expected"][start // 4], result["expected"])
                            accumulator = int(result["expected"], 16)
                        self.assertEqual(f"{accumulator:08x}", case["expected"][row * n + col])
                        output_count += 1
        self.assertEqual(output_count, 3584)

    def test_zero_c_lifts_place_the_frozen_quartet_last_in_every_row_and_column(self):
        for case in self.cases:
            if case["family"] != "leaf_zero_c":
                continue
            with self.subTest(case=case["id"]):
                source = self.leaves[case["source_leaf_ids"][0]]
                self.assertEqual(source["c"], "00000000")
                self.assertEqual(case["intermediate_expected"], ["00000000", source["expected"]])
                for field, leaf_field, repeats in (("a_words", "a", 8), ("b_words", "b", 4)):
                    expected = (0, 0, 0, 0) + halfwords(source[leaf_field])
                    self.assertEqual(halfwords(case[field]), expected * repeats)

    def test_signed_ftz_is_lost_if_a_zero_quartet_follows_the_underflow(self):
        case = self.by_id["bf16-numerical-half_min_normal_negative"]
        a, b = halfwords(case["a_words"])[:8], halfwords(case["b_words"])[:8]
        self.assertEqual(case["expected"], ["80000000"] * 32)
        first = independent_step("bf16", a[4:], b[4:], 0)
        self.assertEqual(first["exact_rational"], {"numerator": "-1", "denominator": str(1 << 127)})
        self.assertEqual(first["expected"], "80000000")
        second = independent_step("bf16", a[:4], b[:4], 0x80000000)
        self.assertEqual(second["expected"], "00000000")

    def test_rounding_and_extremes_have_fixed_hand_computed_anchors(self):
        anchors = {
            "tie_even": ("3f800000", "3f800000", Fraction(1) + Fraction(1, 1 << 24)),
            "tie_odd": ("3f800001", "3f800002", Fraction(1) + Fraction(3, 1 << 24)),
            "tie_negative_even": ("bf800000", "bf800000", -Fraction(1) - Fraction(1, 1 << 24)),
            "tie_negative_odd": ("bf800001", "bf800002", -Fraction(1) - Fraction(3, 1 << 24)),
            "tie_carry": ("3fffffff", "40000000", Fraction(2) - Fraction(1, 1 << 24)),
        }
        for fmt in ("fp16", "bf16"):
            for name, (initial, final, exact) in anchors.items():
                with self.subTest(format=fmt, anchor=name):
                    case = self.by_id[f"{fmt}-numerical-{name}"]
                    self.assertEqual(case["intermediate_expected"], [initial, final])
                    step = case["fedp_trace"][1]
                    self.assertEqual(step["exact_rational"],
                                     {"numerator": str(exact.numerator), "denominator": str(exact.denominator)})
                    self.assertFalse(step["window"]["discarded_nonzero"])
            for negative, sign_name in ((False, "positive"), (True, "negative")):
                case = self.by_id[f"{fmt}-numerical-four_maxfinite_{sign_name}"]
                maximum = Fraction(65504) if fmt == "fp16" else Fraction(255, 128) * (1 << 127)
                exact = (-1 if negative else 1) * 4 * maximum * maximum
                expected = (("d07fc004" if negative else "507fc004") if fmt == "fp16"
                            else ("ff800000" if negative else "7f800000"))
                self.assertEqual(case["intermediate_expected"], ["00000000", expected])
                self.assertEqual(case["fedp_trace"][1]["exact_rational"],
                                 {"numerator": str(exact.numerator), "denominator": str(exact.denominator)})

    def test_negative_sticky_tail_distinguishes_contract_from_exact_whole_gemm(self):
        for fmt, tiny_exponent in (("fp16", -48), ("bf16", -266)):
            case = self.by_id[f"{fmt}-numerical-sticky_negative_tail"]
            a, b = halfwords(case["a_words"])[:8], halfwords(case["b_words"])[:8]
            exact = sum((rational(left, fmt) * rational(right, fmt)
                         for left, right in zip(a, b)), Fraction())
            self.assertEqual(exact, 1 + Fraction(1, 1 << 24) - Fraction(2) ** tiny_exponent)
            self.assertEqual(nearest_binary32(exact), 0x3F800000)
            self.assertEqual(case["expected"], ["3f800001"] * 32)
            self.assertEqual(case["fedp_trace"][1]["window"],
                             {"quantum_exponent": -24, "signed_units": 16777217, "discarded_nonzero": True})

    def test_sequential_producer_preserves_k_order_and_each_rounding_boundary(self):
        for fmt, one, half_ulp in (("fp16", 0x3C00, 0x0001), ("bf16", 0x3F80, 0x3380)):
            a = [one, half_ulp, 0, 0, one | 0x8000, 0, 0, 0]
            b = [one] * 8
            forward = numerical.sequential_fedp(fmt, a, b)
            reverse = numerical.sequential_fedp(fmt, a[4:] + a[:4], b)
            self.assertEqual([(step["k_begin"], step["input_c"], step["expected"]) for step in forward],
                             [(0, "00000000", "3f800000"), (4, "3f800000", "00000000")])
            self.assertEqual([step["expected"] for step in reverse], ["bf800000", "33800000"])
            exact = sum((rational(left, fmt) * rational(right, fmt) for left, right in zip(a, b)), Fraction())
            self.assertEqual(exact, Fraction(1, 1 << 24))
            self.assertEqual(nearest_binary32(exact), 0x33800000)

    def test_k16_cases_preserve_sequential_quartets_across_the_tile_boundary(self):
        for fmt, one, half_ulp in (("fp16", 0x3C00, 0x0001), ("bf16", 0x3F80, 0x3380)):
            for negative, sign_name in ((False, "positive"), (True, "negative")):
                case = self.by_id[f"{fmt}-numerical-cross_tile_rounding_{sign_name}"]
                with self.subTest(case=case["id"]):
                    sign = 0x8000 if negative else 0
                    initial = "bf800000" if negative else "3f800000"
                    a, b = halfwords(case["a_words"])[:16], halfwords(case["b_words"])[:16]
                    wanted_a, wanted_b = [0] * 16, [0] * 16
                    wanted_a[0], wanted_a[4], wanted_a[8] = one | sign, half_ulp | sign, one | (sign ^ 0x8000)
                    wanted_b[0] = wanted_b[4] = wanted_b[8] = one
                    self.assertEqual((a, b), (tuple(wanted_a), tuple(wanted_b)))
                    self.assertEqual(case["dimensions"], {"m": 8, "n": 4, "k": 16})
                    self.assertEqual(case["tile_iterations"], {"m": 1, "n": 1, "k": 2})
                    self.assertEqual(case["fedp_steps_per_output"], 4)
                    self.assertEqual(case["intermediate_expected"], [initial, initial, "00000000", "00000000"])
                    accumulator, actual = 0, []
                    for start in (0, 4, 8, 12):
                        result = independent_step(fmt, a[start:start + 4], b[start:start + 4], accumulator)
                        actual.append((start, f"{accumulator:08x}", result["expected"]))
                        accumulator = int(result["expected"], 16)
                    self.assertEqual(actual, [(0, "00000000", initial), (4, initial, initial),
                                              (8, initial, "00000000"), (12, "00000000", "00000000")])
                    self.assertEqual(case["expected"], ["00000000"] * 32)
                    source = self.leaves[case["source_leaf_ids"][0]]
                    self.assertEqual(case["fedp_trace"][1]["exact_rational"], source["exact_rational"])
                    self.assertEqual(case["fedp_trace"][1]["expected"], source["expected"])

    def test_k16_cases_detect_quartet_reordering_and_complete_k8_tile_reversal(self):
        for case in self.cases:
            if case["family"] != "cross_tile_order":
                continue
            negative = case["id"].endswith("negative")
            residual = "b3800000" if negative else "33800000"
            opposite = "3f800000" if negative else "bf800000"
            a, b = halfwords(case["a_words"])[:16], halfwords(case["b_words"])[:16]
            for starts, expected_trace in (
                    ((0, 8, 4, 12), [case["intermediate_expected"][0], "00000000", residual, residual]),
                    ((8, 12, 0, 4), [opposite, opposite, "00000000", residual])):
                with self.subTest(case=case["id"], source_order=starts):
                    accumulator, trace = 0, []
                    for start in starts:
                        result = independent_step(case["format"], a[start:start + 4], b[start:start + 4], accumulator)
                        trace.append(result["expected"])
                        accumulator = int(result["expected"], 16)
                    self.assertEqual(trace, expected_trace)
                    self.assertNotEqual([trace[-1]] * 32, case["expected"])

    def test_k16_cases_do_not_distinguish_independently_rounded_tile_sums(self):
        for case in self.cases:
            if case["family"] != "cross_tile_order":
                continue
            with self.subTest(case=case["id"]):
                a, b = halfwords(case["a_words"])[:16], halfwords(case["b_words"])[:16]
                rounded_tiles = []
                for start in (0, 8):
                    exact_tile = sum((rational(a[index], case["format"]) * rational(b[index], case["format"])
                                      for index in range(start, start + 8)), Fraction())
                    rounded_tiles.append(rational(nearest_binary32(exact_tile), "fp32"))
                independent_tiles = nearest_binary32(sum(rounded_tiles, Fraction()))
                self.assertEqual([f"{independent_tiles:08x}"] * 32, case["expected"])

    def test_sequential_producer_rejects_incomplete_or_out_of_scope_tile_shapes(self):
        for size in (0, 4, 12, 24):
            with self.subTest(size=size), self.assertRaises(ValueError):
                numerical.sequential_fedp("fp16", [0] * size, [0] * size)
        with self.assertRaises(ValueError):
            numerical.sequential_fedp("bf16", [0] * 16, [0] * 8)


class WmmaFixtureInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / exporter.NUMERICAL_JSON).read_bytes())
        cls.case = cls.document["cases"][0]

    def test_json_rejects_duplicate_fields_at_every_depth(self):
        for raw in (b'{"case_count":64,"case_count":64}',
                    b'{"cases":[{"id":"a","id":"b"}]}',
                    b'{"id":"a","i\\u0064":"b"}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(exporter.FixtureError, "duplicate JSON field"):
                exporter.decode_json(raw)

    def test_json_rejects_nonfinite_floating_or_overlong_numbers(self):
        for token in ("NaN", "Infinity", "-Infinity", "1.0", "1e0", "1e999", "9" * 65):
            with self.subTest(token=token), self.assertRaises(exporter.FixtureError):
                exporter.decode_json(('{"number":' + token + '}').encode())

    def test_json_rejects_invalid_encoding_root_depth_and_size(self):
        for raw in (b'\xff', b'[]', b'null', b'{} trailing', b'{"x":' + b'[' * 33 + b']' * 33 + b'}',
                    b' ' * (exporter.MAX_JSON_BYTES + 1), '{}'):
            with self.subTest(kind=type(raw).__name__, size=len(raw)), self.assertRaises(exporter.FixtureError):
                exporter.decode_json(raw)
        self.assertEqual(exporter.decode_json(b'{"brackets":"[{}]\\\""}'), {"brackets": '[{}]"'})

    def test_case_ids_and_formats_reject_injection_ambiguity_and_unknown_formats(self):
        for field, values in (("id", ("", "UPPER", "-first", "a b", 'a"};', "a\n", "x" * 129, None)),
                              ("format", ("FP16", "fp32", "tf32", "", None, True))):
            for value in values:
                case = deepcopy(self.case)
                case[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(exporter.FixtureError):
                    exporter.validate_case(case)

    def test_dimensions_reject_boolean_noncompact_unbounded_and_conflicting_values(self):
        for key, values in (("m", (True, 0, -8, 7, 72, "8", 8.0)),
                            ("n", (True, 0, -4, 5, 68)), ("k", (True, 0, -8, 12, 72))):
            for value in values:
                case = deepcopy(self.case)
                case["dimensions"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(exporter.FixtureError):
                    exporter.validate_case(case)
        for key, value in (("m", 16), ("n", True), ("k", "8")):
            case = deepcopy(self.case)
            case[key] = value
            with self.assertRaisesRegex(exporter.FixtureError, "normalized dimensions"):
                exporter.validate_case(case)
        for field, key in (("leading_dimensions", "ldb"), ("tile_iterations", "k")):
            case = deepcopy(self.case)
            case[field][key] += 1
            with self.assertRaises(exporter.FixtureError):
                exporter.validate_case(case)

    def test_word_arrays_reject_wrong_counts_types_and_noncanonical_encodings(self):
        for field in ("a_words", "b_words", "expected"):
            for value in (self.case[field][:-1], self.case[field] + ["00000000"], None, "00000000"):
                case = deepcopy(self.case)
                case[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(exporter.FixtureError):
                    exporter.validate_case(case)
            for word in ("0000000", "000000000", "0000000G", "000000AF", "0x00000000", "-0000000", 0, True):
                case = deepcopy(self.case)
                case[field][0] = word
                with self.subTest(field=field, word=word), self.assertRaises(exporter.FixtureError):
                    exporter.validate_case(case)

    def test_document_rejects_duplicate_ids_and_broken_accumulator_handoffs(self):
        duplicate = deepcopy(self.document)
        duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]
        with self.assertRaisesRegex(exporter.FixtureError, "IDs must be unique"):
            exporter.validate_document(duplicate, self.document)
        for field, value in (("k_begin", 0), ("input_c", "80000000"), ("expected", "3f800000")):
            document = deepcopy(self.document)
            document["cases"][0]["fedp_trace"][1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(exporter.FixtureError, "trace handoff"):
                exporter.validate_document(document, self.document)

    def test_k16_document_rejects_short_traces_and_tile_boundary_handoff_drift(self):
        index = next(index for index, case in enumerate(self.document["cases"])
                     if case["family"] == "cross_tile_order")
        for field in ("fedp_trace", "intermediate_expected"):
            document = deepcopy(self.document)
            document["cases"][index][field] = document["cases"][index][field][:2]
            with self.subTest(field=field), self.assertRaises(exporter.FixtureError):
                exporter.validate_document(document, self.document)
        for field, value in (("k_begin", 4), ("input_c", "00000000"), ("expected", "33800000")):
            document = deepcopy(self.document)
            document["cases"][index]["fedp_trace"][2][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(exporter.FixtureError, "trace handoff"):
                exporter.validate_document(document, self.document)
        for field, value in (("fedp_steps_per_output", 2), ("tile_iterations", {"m": 1, "n": 1, "k": 1})):
            case = deepcopy(self.document["cases"][index])
            case[field] = value
            with self.subTest(field=field), self.assertRaises(exporter.FixtureError):
                exporter.validate_case(case)

    def test_loader_rejects_producer_metadata_data_and_whitespace_drift(self):
        changes = (("producer", "version", 2), ("producer", "production_model_used", True),
                   ("arithmetic", "whole_gemm_single_rounding_claimed", True),
                   ("coverage", "identical_rows_and_columns", False))
        with tempfile.TemporaryDirectory(prefix="p02-wmma-drift-") as temporary:
            path = Path(temporary) / "candidate.json"
            for section, field, value in changes:
                document = deepcopy(self.document)
                document[section][field] = value
                path.write_bytes(numerical.render_json(document))
                with self.subTest(section=section, field=field), self.assertRaises(exporter.FixtureError):
                    exporter.load_cases(numerical_path=path)
            document = deepcopy(self.document)
            document["cases"][0]["a_words"][0] = "3c003c00"
            path.write_bytes(numerical.render_json(document))
            with self.assertRaisesRegex(exporter.FixtureError, "byte-for-byte"):
                exporter.load_cases(numerical_path=path)
            path.write_bytes((ROOT / exporter.NUMERICAL_JSON).read_bytes() + b"\n")
            with self.assertRaisesRegex(exporter.FixtureError, "byte-for-byte"):
                exporter.load_cases(numerical_path=path)

    def test_loader_rejects_a_changed_producer_against_unchanged_frozen_data(self):
        changed = deepcopy(self.document)
        changed["cases"][0]["derivation"] += " changed"
        with patch.object(numerical, "fixture_document", return_value=changed):
            with self.assertRaisesRegex(exporter.FixtureError, "byte-for-byte"):
                exporter.load_cases()

    def test_loader_binds_the_frozen_leaf_source_and_rejects_nonregular_inputs(self):
        with tempfile.TemporaryDirectory(prefix="p02-wmma-input-") as temporary:
            root = Path(temporary)
            for relative in (LEAF_PATH, exporter.LAYOUT_JSON, exporter.NUMERICAL_JSON):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            leaf = root / LEAF_PATH
            leaf.write_bytes(leaf.read_bytes() + b"\n")
            with self.assertRaisesRegex(exporter.FixtureError, "frozen leaf fixture"):
                exporter.load_cases(root)
            symlink, fifo = root / "link.json", root / "pipe.json"
            symlink.symlink_to(ROOT / exporter.NUMERICAL_JSON)
            os.mkfifo(fifo)
            for path in (symlink, fifo, root / "missing.json"):
                with self.subTest(path=path.name), self.assertRaises(exporter.FixtureError):
                    exporter.load_cases(numerical_path=path)


class WmmaFixtureExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = exporter.load_cases()
        cls.header = exporter.render_header(cls.cases)

    def test_normalized_combined_inventory_retains_source_order(self):
        original = [case for path in (exporter.LAYOUT_JSON, exporter.NUMERICAL_JSON)
                    for case in json.loads((ROOT / path).read_bytes())["cases"]]
        self.assertEqual(len(self.cases), 88)
        self.assertEqual(Counter(case["format"] for case in self.cases), {"fp16": 44, "bf16": 44})
        for case, source in zip(self.cases, original):
            self.assertEqual(case, {**source, **source["dimensions"]})

    def test_generated_header_preserves_every_word_and_fixture_record(self):
        text = self.header.decode()
        arrays = re.findall(r"inline constexpr uint32_t k(A|B|Expected)(\d+)\[\] = \{([^}]+)\};", text)
        self.assertEqual(len(arrays), 88 * 3)
        extracted = {(kind, int(index)): re.findall(r"0x([0-9a-f]{8})u", body)
                     for kind, index, body in arrays}
        records = re.findall(
            r'\{"([^"]+)", "([^"]+)", (\d+)u, (\d+)u, (\d+)u,\s*'
            r'kA(\d+), (\d+)u, kB(\d+), (\d+)u,\s*kExpected(\d+), (\d+)u\}', text)
        self.assertEqual(len(records), 88)
        for index, case in enumerate(self.cases):
            self.assertEqual(records[index], tuple(map(str, (
                case["id"], case["format"], case["m"], case["n"], case["k"], index,
                len(case["a_words"]), index, len(case["b_words"]), index, len(case["expected"])))))
            for name, field in (("A", "a_words"), ("B", "b_words"), ("Expected", "expected")):
                self.assertEqual(extracted[(name, index)], case[field])

    def test_header_reproduction_is_deterministic_and_matches_the_frozen_export(self):
        self.assertEqual(self.header, exporter.render_header(deepcopy(self.cases)))
        self.assertEqual(self.header, (ROOT / exporter.HEADER_PATH).read_bytes())
        self.assertEqual(exporter.generated_files(), {ROOT / exporter.HEADER_PATH: self.header})

    def test_exporter_rejects_incomplete_duplicate_or_unbalanced_inventory(self):
        duplicate = deepcopy(self.cases)
        duplicate[1] = deepcopy(duplicate[0])
        wrong_format = deepcopy(self.cases)
        wrong_format[0]["format"] = "bf16"
        for cases in (self.cases[:-1], duplicate, wrong_format):
            with self.assertRaises(exporter.FixtureError):
                exporter.render_header(cases)

    def test_cli_check_detects_missing_and_changed_header_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="p02-wmma-header-") as temporary:
            path = Path(temporary) / "p02_fixtures.h"
            with patch.object(exporter, "generated_files", return_value={path: self.header}), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(exporter.main(["--check"]), 1)
                self.assertFalse(path.exists())
                self.assertEqual(exporter.main(["--write"]), 0)
                self.assertEqual(path.read_bytes(), self.header)
                self.assertEqual(exporter.main(["--check"]), 0)
                altered = self.header.replace(b"0x00000000u", b"0x00000001u", 1)
                self.assertNotEqual(altered, self.header)
                path.write_bytes(altered)
                self.assertEqual(exporter.main(["--check"]), 1)
                self.assertEqual(path.read_bytes(), altered)


if __name__ == "__main__":
    unittest.main()
