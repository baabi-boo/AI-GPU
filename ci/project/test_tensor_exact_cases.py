# SPDX-License-Identifier: Apache-2.0
"""Check packed tensor fixtures with independent exact rational arithmetic."""

from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


SOURCE = Path(__file__).resolve().parents[2]
SHAPES = ((1, 1), (2, 1), (2, 2), (4, 2), (4, 4), (8, 4), (8, 8))
DUMP_SOURCE = r'''
#include "tensor_exact_cases.h"
#include <iomanip>
#include <iostream>

static void words(const std::vector<uint32_t>& values) {
  std::cout << '[';
  const char* separator = "";
  for (auto value : values) {
    std::cout << separator << value;
    separator = ",";
  }
  std::cout << ']';
}

int main() {
  for (uint32_t fmt : {2u, 3u}) {
    for (const auto& shape : {std::pair<int, int>{1, 1}, {2, 1}, {2, 2},
                             {4, 2}, {4, 4}, {8, 4}, {8, 8}}) {
      for (const auto& item : tensor_test::exact_cases(fmt, shape.first,
                                                     shape.second, shape.second)) {
        std::cout << "{\"fmt\":" << fmt << ",\"m\":" << shape.first
                  << ",\"n\":" << shape.second << ",\"k\":" << shape.second
                  << ",\"name\":" << std::quoted(item.name) << ",\"a\":";
        words(item.rs1);
        std::cout << ",\"b\":";
        words(item.rs2);
        std::cout << ",\"c\":";
        words(item.rs3);
        std::cout << ",\"expected\":";
        words(item.expected);
        std::cout << "}\n";
      }
    }
  }
}
'''


def decode(bits, exponent_bits, fraction_bits):
    sign = -1 if bits >> (exponent_bits + fraction_bits) else 1
    exponent_mask = (1 << exponent_bits) - 1
    exponent = (bits >> fraction_bits) & exponent_mask
    fraction = bits & ((1 << fraction_bits) - 1)
    if exponent == exponent_mask:
        return ("nan", None) if fraction else ("inf", sign)
    bias = (1 << (exponent_bits - 1)) - 1
    significand = fraction if exponent == 0 else (1 << fraction_bits) + fraction
    power = (1 if exponent == 0 else exponent) - bias - fraction_bits
    scale = Fraction(1 << power) if power >= 0 else Fraction(1, 1 << -power)
    return "finite", sign * significand * scale


def multiply(left, right):
    if left[0] == "nan" or right[0] == "nan":
        return "nan", None
    if left[0] == right[0] == "finite":
        return "finite", left[1] * right[1]
    if any(item[0] == "finite" and item[1] == 0 for item in (left, right)):
        return "nan", None
    signs = [item[1] if item[0] == "inf" else (-1 if item[1] < 0 else 1)
             for item in (left, right)]
    return "inf", signs[0] * signs[1]


def add(left, right):
    if left[0] == "nan" or right[0] == "nan":
        return "nan", None
    if left[0] == right[0] == "finite":
        return "finite", left[1] + right[1]
    if left[0] == right[0] == "inf" and left[1] != right[1]:
        return "nan", None
    return left if left[0] == "inf" else right


class TensorExactFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("A C++17 host compiler is required for tensor fixture tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-tensor-fixtures-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build)}
        common = SOURCE / "hw/unittest/common"
        dump_source = cls.build / "dump.cpp"
        dump_source.write_text(DUMP_SOURCE, encoding="utf-8")
        cls.host_test = cls.build / "tensor_exact_cases_test"
        cls.dump = cls.build / "dump"
        for source, binary in ((common / "tests/tensor_exact_cases_test.cpp", cls.host_test),
                               (dump_source, cls.dump)):
            run_host_command(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2", "-DNDEBUG",
                 "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                 "-I", str(common), str(source), "-o", str(binary)],
                cwd=cls.build, env=cls.environment, timeout=30,
            )
        output = cls.run_binary(cls.dump)
        cls.cases = [json.loads(line) for line in output.splitlines()]
        expected_count = 2 * sum(2 * n + 16 for _, n in SHAPES)
        if len(cls.cases) != expected_count:
            raise AssertionError("Fixture dump omitted or duplicated cases")

    @classmethod
    def run_binary(cls, binary):
        return run_host_command(
            [str(binary)], cwd=cls.build, env=cls.environment, timeout=5,
        )

    def check_format(self, fmt):
        checked = 0
        exponent_bits, fraction_bits = (5, 10) if fmt == 2 else (8, 7)
        for case in (item for item in self.cases if item["fmt"] == fmt):
            m, n, k = (case[key] for key in ("m", "n", "k"))
            self.assertIn((m, n), SHAPES)
            for field in ("a", "b", "c", "expected"):
                self.assertEqual(len(case[field]), m * n)
            for row in range(m):
                for column in range(n):
                    lane = row * n + column
                    total = decode(case["c"][lane], 8, 23)
                    for element in range(2 * k):
                        shift = 16 * (element % 2)
                        a = (case["a"][row * k + element // 2] >> shift) & 0xffff
                        b = (case["b"][column * k + element // 2] >> shift) & 0xffff
                        total = add(total, multiply(decode(a, exponent_bits, fraction_bits),
                                                    decode(b, exponent_bits, fraction_bits)))
                    self.assertEqual(decode(case["expected"][lane], 8, 23), total,
                                     (fmt, m, n, case["name"], row, column))
                    checked += 1
        self.assertEqual(checked, sum(m * n * (2 * n + 16) for m, n in SHAPES))

    def test_fp16_fixture_outputs_match_exact_fraction_reference(self):
        self.check_format(2)

    def test_bf16_fixture_outputs_match_exact_fraction_reference(self):
        self.check_format(3)

    def test_each_packed_halfword_has_active_row_and_column_coverage(self):
        for fmt in (2, 3):
            for m, n in SHAPES:
                selected = [case for case in self.cases
                            if (case["fmt"], case["m"], case["n"]) == (fmt, m, n)]
                names = {case["name"] for case in selected}
                self.assertEqual(len(names), len(selected))
                self.assertEqual(len(selected), 2 * n + 16)
                for position in range(2 * n):
                    case, = [item for item in selected if item["name"] == f"packed element {position}"]
                    for field, rows in (("a", m), ("b", n)):
                        for row in range(rows):
                            active = [index for index in range(2 * n)
                                      if (case[field][row * n + index // 2]
                                          >> (16 * (index % 2))) & 0xffff]
                            self.assertEqual(active, [position], (fmt, m, n, field, row))

    def test_special_values_and_normal_output_boundaries_are_present(self):
        for fmt in (2, 3):
            for m, n in SHAPES:
                selected = {case["name"]: case for case in self.cases
                            if (case["fmt"], case["m"], case["n"]) == (fmt, m, n)}
                for name, expected in (
                    ("positive infinity product", ("inf", 1)),
                    ("negative infinity product", ("inf", -1)),
                    ("infinity times zero", ("nan", None)),
                    ("opposing infinities", ("nan", None)),
                    ("NaN input", ("nan", None)),
                    ("positive infinity accumulator", ("inf", 1)),
                    ("negative infinity accumulator", ("inf", -1)),
                    ("NaN accumulator", ("nan", None)),
                    ("signed zero inputs", ("finite", Fraction(0))),
                ):
                    self.assertTrue(all(decode(bits, 8, 23) == expected
                                        for bits in selected[name]["expected"]))
                boundary = ("smallest FP16 subnormal to normal FP32" if fmt == 2
                            else "smallest normal BF16 input")
                expected = 0x33800000 if fmt == 2 else 0x00800000
                self.assertEqual(selected[boundary]["expected"], [expected] * (m * n))

    def test_cpp_fixture_bounds_and_independent_host_decoder(self):
        output = self.run_binary(self.host_test)
        checked = 2 * sum(m * n * (2 * n + 16) for m, n in SHAPES)
        self.assertEqual(output, f"{checked} independently decoded fixture outputs verified\n")


if __name__ == "__main__":
    unittest.main()
