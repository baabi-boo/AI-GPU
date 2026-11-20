# SPDX-License-Identifier: Apache-2.0
"""Independent byte decoding and integer-network checks for the frozen MLP."""

from copy import deepcopy
from fractions import Fraction
import hashlib
from itertools import accumulate
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import p04_reference as reference


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json"
FORMATS = ("fp16", "bf16")
FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")


def raw_bytes(words):
    return struct.pack("<" + "I" * len(words), *(int(word, 16) for word in words))


def finite_value(bits, exponent_bits, fraction_bits):
    exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
    if exponent == (1 << exponent_bits) - 1:
        raise AssertionError("the finite fixture contains a nonfinite value")
    mantissa = bits & ((1 << fraction_bits) - 1)
    if exponent:
        mantissa += 1 << fraction_bits
    power = max(exponent, 1) - ((1 << (exponent_bits - 1)) - 1) - fraction_bits
    magnitude = Fraction(mantissa) * (Fraction(2) ** power)
    return -magnitude if bits >> (exponent_bits + fraction_bits) else magnitude


def tensor_values(words, dtype):
    data = raw_bytes(words)
    element_code, ebits, fbits = {
        "fp16": ("H", 5, 10), "bf16": ("H", 8, 7), "fp32": ("I", 8, 23),
    }[dtype]
    elements = [item[0] for item in struct.iter_unpack("<" + element_code, data)]
    values = [finite_value(bits, ebits, fbits) for bits in elements]
    if any(value.denominator != 1 for value in values):
        raise AssertionError("the exact-integer fixture contains a fractional value")
    if any(value == 0 and bits != 0 for value, bits in zip(values, elements)):
        raise AssertionError("frozen zero results must use positive zero")
    return [int(value) for value in values]


def rows(values, width):
    return [values[start:start + width] for start in range(0, len(values), width)]


def column_major_matrix(values, height, width):
    return [[values[column * height + row] for column in range(width)]
            for row in range(height)]


class TinyMlpReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case for case in cls.fixture["cases"]}

    def case_values(self, family, stage, dtype="fp16"):
        case = self.cases[dtype + "-" + family]
        stored_dtype = dtype if stage in ("input", "bridge") else "fp32"
        return tensor_values(case[stage + "_words"], stored_dtype)

    def test_exact_case_inventory_and_source_only_scope(self):
        self.assertEqual([case["id"] for case in self.fixture["cases"]],
                         [dtype + "-" + family for dtype in FORMATS for family in FAMILIES])
        self.assertEqual(len(self.cases), 10)
        self.assertEqual(self.fixture["model"]["planned_native_mnk"],
                         [[16, 8, 16], [8, 4, 8], [8, 4, 8]])
        self.assertEqual(self.fixture["model"]["host_work"],
                         ["relu_and_exact_cast", "row_partition", "copy_row_blocks"])
        self.assertIs(self.fixture["model"]["cpu_matmul_fallback"], False)
        self.assertIs(self.fixture["model"]["execution_available"], False)
        self.assertIs(self.fixture["provenance"]["gpu_execution_claimed"], False)
        self.assertIs(self.fixture["provenance"]["trained_accuracy_claimed"], False)

    def test_host_work_tokens_match_the_model_manifest(self):
        manifest = json.loads((ROOT / "ci/project/p04_model_manifest.json").read_text(
            encoding="utf-8"))
        self.assertEqual(self.fixture["model"]["host_work"], manifest["host_work_allowlist"])

    def test_literal_generator_and_encoding_anchors(self):
        self.assertEqual(reference.xorshift_values(1, 5), [2, 2, -1, -2, 1])
        self.assertEqual(reference.xorshift_values(0x50403401, 8),
                         [0, -2, 1, -1, 1, 0, 0, 1])
        self.assertEqual(self.fixture["weights"]["logical"]["w1"][0],
                         [0, -2, 1, -1, 1, 0, 0, 1])
        self.assertEqual(self.fixture["weights"]["logical"]["w2"][0], [1, -1, -2, 0])
        for dtype, one in (("fp16", "3c00"), ("bf16", "3f80")):
            with self.subTest(dtype=dtype):
                self.assertEqual(self.fixture["weights"]["formats"][dtype]["w2_words"][0],
                                 "c000" + one)
                basis = self.cases[dtype + "-signed_basis"]
                self.assertEqual(basis["input_words"][0], "00004000")
                self.assertEqual(basis["hidden_words"][:8],
                                 ["00000000", "c0800000", "40000000", "c0000000",
                                  "40000000", "00000000", "00000000", "40000000"])
                self.assertEqual(basis["output_words"][:4],
                                 ["40800000", "40800000", "c0800000", "40c00000"])

    def test_column_major_weights_decode_to_declared_logical_matrices(self):
        for dtype in FORMATS:
            encoded = self.fixture["weights"]["formats"][dtype]
            for name, height, width, count in (("w1", 16, 8, 64), ("w2", 8, 4, 16)):
                with self.subTest(dtype=dtype, tensor=name):
                    words = encoded[name + "_words"]
                    self.assertEqual(len(words), count)
                    values = tensor_values(words, dtype)
                    matrix = column_major_matrix(values, height, width)
                    self.assertEqual(matrix, self.fixture["weights"]["logical"][name])
                    self.assertTrue(all(-2 <= value <= 2 for value in values))
                    self.assertNotEqual(rows(values, width), matrix)
                    self.assertEqual(hashlib.sha256(raw_bytes(words)).hexdigest(),
                                     encoded["sha256"][name])

    def test_every_stage_matches_math_reconstructed_from_serialized_inputs(self):
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                dtype = case["format"]
                weights = self.fixture["weights"]["formats"][dtype]
                w1 = column_major_matrix(tensor_values(weights["w1_words"], dtype), 16, 8)
                w2 = column_major_matrix(tensor_values(weights["w2_words"], dtype), 8, 4)
                inputs = rows(tensor_values(case["input_words"], dtype), 16)
                self.assertTrue(all(-2 <= value <= 2 for row in inputs for value in row))
                hidden, logits = [], []
                for row in inputs:
                    activation = []
                    for column in zip(*w1):
                        products = [left * right for left, right in zip(row, column)]
                        self.assertLessEqual(max(map(abs, accumulate(products))), 64)
                        hidden.append(sum(products))
                        activation.append(max(0, sum(products)))
                    for column in zip(*w2):
                        products = [left * right for left, right in zip(activation, column)]
                        self.assertLessEqual(max(map(abs, accumulate(products))), 1024)
                        logits.append(sum(products))
                self.assertEqual(tensor_values(case["hidden_words"], "fp32"), hidden)
                self.assertEqual(tensor_values(case["bridge_words"], dtype),
                                 [max(0, value) for value in hidden])
                self.assertEqual(tensor_values(case["output_words"], "fp32"), logits)
                for name, word_count in (("input", 128), ("hidden", 128),
                                         ("bridge", 64), ("output", 64)):
                    words = case[name + "_words"]
                    self.assertEqual(len(words), word_count)
                    self.assertTrue(all(len(word) == 8 and
                                        all(c in "0123456789abcdef" for c in word)
                                        for word in words))
                    self.assertEqual(hashlib.sha256(raw_bytes(words)).hexdigest(),
                                     case["sha256"][name])

    def test_format_variants_have_identical_mathematical_values(self):
        for family in FAMILIES:
            for stage in ("input", "hidden", "bridge", "output"):
                with self.subTest(family=family, stage=stage):
                    self.assertEqual(self.case_values(family, stage, "fp16"),
                                     self.case_values(family, stage, "bf16"))

    def test_input_families_cover_zero_basis_and_sign_reversal(self):
        dense = self.case_values("seeded_dense", "input")
        self.assertEqual(self.case_values("negated_dense", "input"), [-value for value in dense])
        for stage in ("input", "hidden", "bridge", "output"):
            self.assertTrue(all(value == 0 for value in self.case_values("zero", stage)))
        basis = rows(self.case_values("signed_basis", "input"), 16)
        for row, values in enumerate(basis):
            self.assertEqual([index for index, value in enumerate(values) if value], [row])
            self.assertEqual(values[row], 2 if row % 2 == 0 else -2)

    def test_relu_is_observable_and_the_network_is_nonlinear(self):
        hidden = self.case_values("seeded_dense", "hidden")
        self.assertLess(min(hidden), 0)
        self.assertGreater(max(hidden), 0)
        w2 = self.fixture["weights"]["logical"]["w2"]
        linear = [sum(left * right for left, right in zip(row, column))
                  for row in rows(hidden, 8) for column in zip(*w2)]
        output = self.case_values("seeded_dense", "output")
        self.assertNotEqual(output, linear)
        self.assertGreater(len(set(output)), 1)
        negated = self.case_values("negated_dense", "output")
        self.assertTrue(any(left + right != 0 for left, right in zip(output, negated)))

    def test_second_layer_row_split_cannot_repeat_or_swap_one_batch(self):
        inputs = rows(self.case_values("split_boundary", "input"), 16)
        output = rows(self.case_values("split_boundary", "output"), 4)
        self.assertNotEqual(inputs[:8], inputs[8:])
        self.assertNotEqual(output[:8], output[8:])
        self.assertNotEqual(output[7], output[8])
        self.assertNotEqual(output, output[:8] + output[:8])
        self.assertNotEqual(output, output[8:] + output[:8])

    def test_reference_accepts_inclusive_domain_extremes_without_rounding(self):
        inputs = [[2] * 16 for _ in range(16)]
        w1, w2 = [[2] * 8 for _ in range(16)], [[2] * 4 for _ in range(8)]
        result = reference.evaluate_network(inputs, w1, w2)
        self.assertEqual(result["hidden"], [[64] * 8 for _ in range(16)])
        self.assertEqual(result["bridge"], [[64] * 8 for _ in range(16)])
        self.assertEqual(result["output"], [[1024] * 4 for _ in range(16)])
        negative = reference.evaluate_network([[-2] * 16 for _ in range(16)], w1, w2)
        self.assertEqual(negative["hidden"], [[-64] * 8 for _ in range(16)])
        self.assertEqual(negative["output"], [[0] * 4 for _ in range(16)])

    def test_reference_rejects_malformed_shapes_and_noninteger_domain(self):
        valid = [[0] * 16 for _ in range(16)]
        invalid = [None, tuple(valid), [], valid[:-1], [[0] * 15 for _ in range(16)]]
        for value in (True, 0.0, "0", -3, 3):
            matrix = deepcopy(valid)
            matrix[-1][-1] = value
            invalid.append(matrix)
        for matrix in invalid:
            with self.subTest(matrix=repr(matrix)[:60]):
                with self.assertRaises(ValueError):
                    reference.evaluate_network(matrix)
        w1, w2 = reference.logical_weights()
        for first, second in ((w1[:-1], w2), (w1, w2[:-1]), (None, w2), (w1, None)):
            with self.assertRaises(ValueError):
                reference.evaluate_network(valid, first, second)
        for value in (True, 0.5, -3, 3):
            first, second = deepcopy(w1), deepcopy(w2)
            first[-1][-1] = value
            second[-1][-1] = value
            with self.assertRaises(ValueError):
                reference.evaluate_network(valid, first, w2)
            with self.assertRaises(ValueError):
                reference.evaluate_network(valid, w1, second)

    def test_generator_rejects_invalid_seeds_and_counts(self):
        for seed in (0, -1, 1 << 32, True, 1.0, "1"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                reference.xorshift_values(seed, 1)
        for count in (-1, 257, True, 1.0, "1"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                reference.xorshift_values(1, count)
        self.assertEqual(reference.xorshift_values(1, 0), [])
        self.assertEqual(len(reference.xorshift_values(1, 256)), 256)
        with self.assertRaises(ValueError):
            reference.logical_inputs("unknown")

    def test_tensor_hash_is_over_little_endian_words_and_rejects_noncanonical_text(self):
        self.assertEqual(reference.raw_words_sha256(["01234567", "89abcdef"]),
                         hashlib.sha256(bytes.fromhex("67452301efcdab89")).hexdigest())
        for words in ([], ["00000000"] * 257, ("00000000",), [True], ["FFFFFFFF"],
                      ["0x000000"], ["0000000"], ["000000000"], ["00000000\n"]):
            with self.subTest(words=repr(words)[:40]), self.assertRaises(ValueError):
                reference.raw_words_sha256(words)

    def test_reproduction_is_deterministic_and_does_not_alias_returned_objects(self):
        first = reference.fixture_document()
        first["weights"]["logical"]["w1"][0][0] = 99
        first["cases"][0]["hidden_words"][0] = "ffffffff"
        self.assertEqual(reference.fixture_document(), self.fixture)
        self.assertEqual(reference.rendered_fixture().encode("utf-8"), FIXTURE.read_bytes())


class TinyMlpReferenceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p04-reference-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        project = self.root / "ci/project"
        (project / "fixtures").mkdir(parents=True)
        for name in ("p04_reference.py", "p02_layout_fixture_oracle.py"):
            shutil.copy2(ROOT / "ci/project" / name, project / name)
        self.fixture = project / "fixtures/p04_tiny_mlp_v1.json"
        shutil.copy2(FIXTURE, self.fixture)
        self.script = project / "p04_reference.py"

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def check(self, arguments, expected_code):
        before = self.snapshot()
        result = subprocess.run([sys.executable, str(self.script), *arguments], cwd=self.root,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before, "verification must not alter any source bytes or mtime")
        return result

    def test_default_and_explicit_check_are_read_only(self):
        for arguments in ([], ["--check"]):
            with self.subTest(arguments=arguments):
                result = self.check(arguments, 0)
                self.assertIn("10 source-only", result.stdout)
                self.assertIn("no GPU execution", result.stdout)

    def test_corrupt_fixture_is_rejected_without_repair(self):
        data = self.fixture.read_bytes()
        self.fixture.write_bytes(data.replace(b'"c0800000"', b'"c0800001"', 1))
        self.assertNotEqual(self.fixture.read_bytes(), data)
        self.assertIn("differs byte-for-byte", self.check(["--check"], 1).stderr)

    def test_missing_fixture_is_not_regenerated(self):
        self.fixture.unlink()
        self.check([], 1)
        self.assertFalse(self.fixture.exists())

    def test_oversized_fixture_is_rejected_without_modification(self):
        self.fixture.write_bytes(b" " * (256 * 1024 + 1))
        self.check(["--check"], 1)

    def test_conflicting_check_and_write_flags_do_not_write(self):
        self.check(["--check", "--write"], 2)


if __name__ == "__main__":
    unittest.main()
