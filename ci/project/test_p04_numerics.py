# SPDX-License-Identifier: Apache-2.0
"""Cross-check the tiny MLP against the independent P02 ordered FEDP oracle."""

from fractions import Fraction
import json
from pathlib import Path
import struct
import unittest

import p02_fixture_oracle as leaf
from p02_wmma_numerical_fixture_oracle import sequential_fedp


ROOT = Path(__file__).resolve().parents[2]
FORMATS = ("fp16", "bf16")


def elements(words):
    return [int(word, 16) >> shift & 0xFFFF for word in words for shift in (0, 16)]


def integer_value(bits, format_name):
    ebits, fbits, bias, _ = leaf.FORMATS[format_name]
    value = leaf.decode(bits, ebits, fbits, bias)
    if value.kind != "finite" or value.value.denominator != 1:
        raise AssertionError("the bounded model requires finite integer operands")
    return int(value.value)


def binary32_word(value):
    # All integers in this proof fit exactly in both host double and binary32.
    if type(value) is not int or abs(value) > 1024:
        raise AssertionError("integer escaped the frozen numerical proof domain")
    return struct.pack(">f", value).hex()


class TinyMlpP02NumericsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json")
                                 .read_text(encoding="utf-8"))

    def check_dot(self, format_name, a, b, expected, bound):
        trace = sequential_fedp(format_name, a, b)
        self.assertEqual(len(trace), len(a) // 4)
        values_a = [integer_value(bits, format_name) for bits in a]
        values_b = [integer_value(bits, format_name) for bits in b]
        total, previous = 0, "00000000"
        for index, step in enumerate(trace):
            self.assertEqual(step["k_begin"], index * 4)
            self.assertEqual(step["input_c"], previous)
            for left, right in zip(values_a[index * 4:index * 4 + 4],
                                   values_b[index * 4:index * 4 + 4]):
                total += left * right
                self.assertLessEqual(abs(total), bound)
            mathematical_word = binary32_word(total)
            self.assertEqual(step["exact_rational"],
                             {"numerator": str(total), "denominator": "1"})
            self.assertIs(step["window"]["discarded_nonzero"], False)
            self.assertEqual(step["exact_fp32"], mathematical_word)
            self.assertEqual(step["expected"], mathematical_word)
            previous = step["expected"]
        self.assertEqual(previous, expected)
        return len(trace)

    def test_every_hidden_output_matches_all_four_ordered_quartets(self):
        outputs, quartets = 0, 0
        for case in self.fixture["cases"]:
            format_name = case["format"]
            inputs = elements(case["input_words"])
            weights = elements(self.fixture["weights"]["formats"][format_name]["w1_words"])
            self.assertEqual(len(inputs), 256)
            self.assertEqual(len(weights), 128)
            for row in range(16):
                for column in range(8):
                    with self.subTest(case=case["id"], row=row, column=column):
                        quartets += self.check_dot(
                            format_name, inputs[row * 16:(row + 1) * 16],
                            weights[column * 16:(column + 1) * 16],
                            case["hidden_words"][row * 8 + column], 64)
                        outputs += 1
        self.assertEqual((outputs, quartets), (1280, 5120))

    def test_every_output_in_both_row_blocks_matches_two_ordered_quartets(self):
        outputs, quartets = 0, 0
        for case in self.fixture["cases"]:
            format_name = case["format"]
            inputs = elements(case["bridge_words"])
            weights = elements(self.fixture["weights"]["formats"][format_name]["w2_words"])
            self.assertEqual(len(inputs), 128)
            self.assertEqual(len(weights), 32)
            for batch_start in (0, 8):
                for local_row in range(8):
                    row = batch_start + local_row
                    for column in range(4):
                        with self.subTest(case=case["id"], row=row, column=column):
                            quartets += self.check_dot(
                                format_name, inputs[row * 8:(row + 1) * 8],
                                weights[column * 8:(column + 1) * 8],
                                case["output_words"][row * 4 + column], 1024)
                            outputs += 1
        self.assertEqual((outputs, quartets), (640, 1280))

    def test_full_integer_domain_fits_encodings_and_alignment_window(self):
        first_product_bound = max(abs(a * b) for a in range(-2, 3) for b in range(-2, 3))
        hidden_bound = 16 * first_product_bound
        second_product_bound = max(abs(a * b) for a in range(hidden_bound + 1)
                                   for b in range(-2, 3))
        output_bound = 8 * second_product_bound
        self.assertEqual((first_product_bound, hidden_bound, second_product_bound, output_bound),
                         (4, 64, 128, 1024))
        for format_name in FORMATS:
            ebits, fbits, bias, _ = leaf.FORMATS[format_name]
            exponents = {}
            for value in range(-hidden_bound, hidden_bound + 1):
                bits = leaf.small_exact(value, format_name)
                number = leaf.decode(bits, ebits, fbits, bias)
                self.assertEqual(number.value, Fraction(value))
                if value:
                    exponents[value] = number.exponent
            product_scale_max = max(exponents[a] + exponents[b]
                                    for a in range(1, hidden_bound + 1)
                                    for b in (-2, -1, 1, 2))
            accumulator_scale_max = output_bound.bit_length() - 1
            quantum_exponent_max = max(product_scale_max, accumulator_scale_max) - 24
            self.assertEqual((product_scale_max, accumulator_scale_max, quantum_exponent_max),
                             (7, 10, -14))
            self.assertLessEqual(quantum_exponent_max, 0)
            self.assertLess(output_bound, 1 << 24)
            # Every product and C is integral, hence a multiple of every such quantum.
            for value in (-output_bound, -1, 0, 1, output_bound):
                scaled = Fraction(value) / leaf.power_of_two(quantum_exponent_max)
                self.assertEqual(scaled.denominator, 1)

    def test_extreme_prefixes_and_cross_quartet_cancellation_stay_exact(self):
        vectors = (
            ([2] * 16, [2] * 16, 64, 64),
            ([-2] * 16, [2] * 16, -64, 64),
            ([2] * 16, [2] * 8 + [-2] * 8, 0, 64),
            ([2] * 16, [2, -2] * 8, 0, 64),
            ([64] * 8, [2] * 8, 1024, 1024),
            ([64] * 8, [-2] * 8, -1024, 1024),
            ([64] * 8, [-2] * 4 + [2] * 4, 0, 1024),
            ([0] * 8, [-2] * 8, 0, 1024),
        )
        quartets = 0
        for format_name in FORMATS:
            for index, (a, b, expected, bound) in enumerate(vectors):
                with self.subTest(format=format_name, vector=index):
                    quartets += self.check_dot(
                        format_name, [leaf.small_exact(value, format_name) for value in a],
                        [leaf.small_exact(value, format_name) for value in b],
                        binary32_word(expected), bound)
        self.assertEqual(quartets, 48)

    def test_negative_preactivation_error_cannot_be_detected_after_relu_alone(self):
        manifest = json.loads((ROOT / "ci/project/p04_model_manifest.json")
                              .read_text(encoding="utf-8"))
        bridge = next(operation for operation in manifest["graph"]
                      if operation["id"] == "hidden_relu_cast")
        self.assertIs(bridge["compare_preactivation_first"], True)
        for format_name in FORMATS:
            case = next(case for case in self.fixture["cases"]
                        if case["id"] == format_name + "-seeded_dense")
            index = next(index for index, word in enumerate(case["hidden_words"])
                         if int(word, 16) & 0x80000000)
            expected_bits = int(case["hidden_words"][index], 16)
            expected = int(leaf.decode(expected_bits, 8, 23, 127).value)
            wrong = -2 if expected == -1 else -1
            self.assertNotEqual(binary32_word(wrong), case["hidden_words"][index])
            self.assertEqual(max(0, wrong), max(0, expected))
            self.assertEqual(elements(case["bridge_words"])[index], 0)


if __name__ == "__main__":
    unittest.main()
