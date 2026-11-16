# SPDX-License-Identifier: Apache-2.0
"""Offline integrity, independent arithmetic anchors and TFR model checks.

The C++ checks exercise the production software FEDP function, not a SimX
processor or native RTL. They use fresh generated headers, a host C++17
compiler and UBSan; no RISC-V compiler, Verilator or downloads are required.
"""

from collections import Counter
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

import p02_fixture_oracle as oracle
from tensor_host_tools import run_host_command


SOURCE = Path(__file__).resolve().parents[2]
MANIFEST = SOURCE / "ci/project/p02_tensor_contract.json"
FIXTURES = SOURCE / "ci/project/fixtures/p02_tfr_v1.json"
HEADER = SOURCE / "hw/unittest/common/p02_tfr_vectors.h"
PRODUCER = SOURCE / "ci/project/p02_fixture_oracle.py"


def pow2(exponent):
    """Construct an exact mathematical test input, without oracle helpers."""
    return Fraction(2) ** exponent


# These constants follow the stated arithmetic identities, not producer output.
# Both formats represent the small integers/fractions used by these cases.
COMMON_ANCHORS = {
    "zero": (0x00000000, 0x00000000),
    "negative_zeros": (0x00000000, 0x00000000),
    "c_passthrough": (0x3EAAAAAB, 0x3EAAAAAB),
    "dense_positive": (0x428D0000, 0x428D0000),  # 5+12+21+32+1/2 = 70.5
    "dense_mixed_sign": (0xBE800000, 0xBE800000),  # 4-6+6-4-1/4 = -1/4
    "dense_fractional": (0x3F400000, 0x3F400000),  # 3/8+3/4-3/2+1+1/8
    "packed_onehot_0": (0x3F800000, 0x3F800000),  # 1
    "packed_onehot_1": (0x40000000, 0x40000000),  # 2
    "packed_onehot_2": (0x40800000, 0x40800000),  # 4
    "packed_onehot_3": (0x41000000, 0x41000000),  # 8
    "c_low_bit": (0x3F800001, 0x3F800001),
    "tie_even": (0x3F800000, 0x3F800000),  # 1 + half an ULP
    "tie_odd": (0x3F800002, 0x3F800002),  # 1 + 1.5 ULPs
    "tie_negative_even": (0xBF800000, 0xBF800000),
    "tie_negative_odd": (0xBF800002, 0xBF800002),
    "tie_carry": (0x40000000, 0x40000000),  # Midpoint below 2 rounds to 2.
    "above_half": (0x3F800001, 0x3F800001),
    "cancel_products": (0x00000000, 0x00000000),
    "cancel_c": (0x00000000, 0x00000000),
    "sticky_negative_tail": (0x3F800001, 0x3F800000),  # Unsigned tail OR.
    "tiny_positive": (0x3F800000, 0x3F800000),
    "tiny_negative": (0x3F800000, 0x3F800000),
    "opposed_c_infinity": (0x7FC00000, 0x7FC00000),
    "c_subnormal_positive": (0x00000000, 0x00000001),
    "c_subnormal_negative": (0x80000000, 0x80000001),
    "cancel_extreme_products": (0x00000000, 0x3F800000),
    "positive_infinity": (0x7F800000, 0x7F800000),
    "negative_infinity": (0xFF800000, 0xFF800000),
    "same_sign_infinities": (0xFF800000, 0xFF800000),
    "opposed_product_infinities": (0x7FC00000, 0x7FC00000),
    "infinity_times_zero": (0x7FC00000, 0x7FC00000),
    "input_quiet_nan": (0x7FC00000, 0x7FC00000),
    "input_signaling_nan": (0x7FC00000, 0x7FC00000),
    "c_quiet_nan": (0x7FC00000, 0x7FC00000),
    "c_signaling_nan": (0x7FC00000, 0x7FC00000),
    "c_negative_infinity": (0xFF800000, 0xFF800000),
}

FORMAT_ANCHORS = {
    "fp16": {
        "cancel_with_residual": (0x33800000, 0x33800000),  # 2^-24 fits the window.
        "cancel_large_with_tiny": (0x00000000, 0x33800000),
        "input_min_subnormal": (0x33800000, 0x33800000),  # 2^-24
        "input_max_subnormal": (0x387FC000, 0x387FC000),  # 1023 * 2^-24
        "scaled_min_subnormal": (0x3B7FE000, 0x3B7FE000),  # 2047 / 2^19
        "scaled_negative_subnormal": (0xBB7FE000, 0xBB7FE000),
        "squared_min_subnormal": (0x27800000, 0x27800000),  # 2^-48
        "input_min_normal": (0x38800000, 0x38800000),  # 2^-14
        "half_min_normal_positive": (0x38000000, 0x38000000),  # 2^-15
        "half_min_normal_negative": (0xB8000000, 0xB8000000),
        "finite_upper_bound_positive": (0x7F7FFFFF, 0x7F7FFFFF),
        "finite_upper_bound_negative": (0xFF7FFFFF, 0xFF7FFFFF),
        "zero_times_max_exponent": (0x33800000, 0x33800000),  # 2^-24 + 0*maxfinite
    },
    "bf16": {
        "cancel_with_residual": (0x00000000, 0x00010000),  # 2^-133 is discarded.
        "cancel_large_with_tiny": (0x00000000, 0x00010000),
        "input_min_subnormal": (0x00000000, 0x00010000),  # 2^-133
        "input_max_subnormal": (0x00000000, 0x007F0000),  # 127 * 2^-133
        "scaled_min_subnormal": (0x3CFF0000, 0x3CFF0000),  # 255 / 2^13
        "scaled_negative_subnormal": (0xBCFF0000, 0xBCFF0000),
        "squared_min_subnormal": (0x00000000, 0x00000000),  # 2^-266
        "input_min_normal": (0x00800000, 0x00800000),  # 2^-126
        "half_min_normal_positive": (0x00000000, 0x00400000),  # Signed FTZ.
        "half_min_normal_negative": (0x80000000, 0x80400000),
        "finite_upper_bound_positive": (0x7F800000, 0x7F800000),
        "finite_upper_bound_negative": (0xFF800000, 0xFF800000),
        "zero_times_max_exponent": (0x00800000, 0x00800000),  # 2^-126 + 0*maxfinite
    },
}


class ContractIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.document = json.loads(FIXTURES.read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case for case in cls.document["cases"]}

    def test_generated_json_and_header_reproduce_exact_bytes(self):
        generated = oracle.generated_files(SOURCE)
        self.assertEqual(set(generated), {FIXTURES, HEADER})
        for path, content in generated.items():
            with self.subTest(path=path.relative_to(SOURCE)):
                self.assertEqual(path.read_bytes(), content)

    def test_manifest_paths_and_producer_version_bind_actual_artifacts(self):
        fixtures = self.manifest["fixtures"]
        self.assertEqual(fixtures["path"], FIXTURES.relative_to(SOURCE).as_posix())
        self.assertEqual(fixtures["generated_header"], HEADER.relative_to(SOURCE).as_posix())
        producer_path = PRODUCER.relative_to(SOURCE).as_posix()
        self.assertEqual(fixtures["producer"]["path"], producer_path)
        self.assertEqual(self.document["producer"]["path"], producer_path)
        self.assertEqual(oracle.PRODUCER_PATH, producer_path)
        self.assertEqual(Path(oracle.__file__).resolve(), PRODUCER)
        self.assertEqual(fixtures["producer"]["version"], oracle.PRODUCER_VERSION)
        self.assertEqual(fixtures["producer"]["version"], self.document["producer"]["version"])

    def test_all_recorded_manifest_sha256_identities_match(self):
        fixtures = self.manifest["fixtures"]
        identities = {
            "sha256": FIXTURES,
            "generated_header_sha256": HEADER,
            "producer_sha256": PRODUCER,
        }
        self.assertEqual({key for key in fixtures if "sha256" in key}, set(identities))
        for field, path in identities.items():
            with self.subTest(field=field):
                self.assertRegex(fixtures[field], r"^[0-9a-f]{64}$")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 fixtures[field])

    def test_inventory_has_98_unique_cases_and_49_per_format(self):
        cases = self.document["cases"]
        self.assertEqual(len(cases), 98)
        self.assertEqual(len(self.cases), 98)
        counts = dict(Counter(case["format"] for case in cases))
        self.assertEqual(counts, {"fp16": 49, "bf16": 49})
        self.assertEqual(self.manifest["fixtures"]["case_count"], 98)
        self.assertEqual(self.manifest["fixtures"]["case_count_by_format"], counts)
        self.assertEqual(set(self.manifest["coverage"]["fixture_categories"]),
                         {case["category"] for case in cases})
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["id"].startswith(case["format"] + "_"))
                self.assertTrue(case["derivation"])
                self.assertEqual(len(case["a"]), 2)
                self.assertEqual(len(case["b"]), 2)
                for word in case["a"] + case["b"] + [case["c"], case["expected"],
                                                       case["exact_fp32"]]:
                    self.assertRegex(word, r"^[0-9a-f]{8}$")

    def test_frozen_configuration_and_supported_formats(self):
        self.assertEqual(self.document["contract_id"], "p02-tfr-fp16-bf16-v1")
        self.assertEqual(self.manifest["contract_id"], self.document["contract_id"])
        self.assertEqual(self.document["schema_version"], 1)
        self.assertEqual(self.manifest["contract_version"], 1)
        self.assertEqual(self.document["producer"], {"path": "ci/project/p02_fixture_oracle.py",
                                                    "version": 1})
        self.assertEqual(self.document["configuration"], {
            "packed_words": 2, "products": 4, "window_bits": 25,
            "accumulator_bits": 30, "rounding": "RNE", "formats": {"fp16": 2, "bf16": 3},
        })
        profile = self.manifest["profile"]
        expected = {
            "xlen": 64, "threads": 4, "arithmetic_backend": "TFR", "packed_words": 2,
            "word_bits": 32, "elements_per_word": 2, "products": 4, "window_bits": 25,
            "aligned_magnitude_bits": 26, "accumulator_bits": 30,
            "internal_exponent_bits": 10, "latency": 4, "use_dsp": 0, "rounding": "RNE",
            "dense": True, "scaled": False, "wgmma": False, "sparse": False,
            "dsm": False, "fedp2k": False,
        }
        self.assertEqual({key: profile[key] for key in expected}, expected)
        self.assertEqual(self.manifest["supported_formats"], [
            {"input": "fp16", "input_format_id": 2, "output": "fp32", "output_format_id": 0,
             "exponent_bits": 5, "fraction_bits": 10, "exponent_bias": 15,
             "enable_macro": "VX_CFG_TCU_FP16_ENABLE"},
            {"input": "bf16", "input_format_id": 3, "output": "fp32", "output_format_id": 0,
             "exponent_bits": 8, "fraction_bits": 7, "exponent_bias": 127,
             "enable_macro": "VX_CFG_TCU_FP16_ENABLE"},
        ])
        self.assertEqual(self.manifest["backends"]["excluded"], ["DPI", "DSP", "BHF", "FPNEW"])
        self.assertTrue((SOURCE / self.manifest["specification"]).is_file())

    def test_comparison_is_bit_exact_including_nan_and_signed_zero(self):
        self.assertEqual(self.manifest["comparison"], {
            "method": "uint32_bit_equality", "expected_field": "expected", "bit_width": 32,
            "absolute_tolerance": 0, "relative_tolerance": 0, "ulp_tolerance": 0,
            "signed_zero_equal": False, "nan_payloads_equal": False,
            "expected_nan_bits": "7fc00000",
        })
        self.assertFalse(self.manifest["arithmetic"]["exact_real_dot_equivalence"])
        self.assertFalse(self.manifest["arithmetic"]["whole_gemm_single_rounding"])

    def test_preserved_p01_tolerances_and_geometry(self):
        preserved = self.manifest["preserved_p01"]
        p01 = json.loads((SOURCE / preserved["manifest"]).read_text(encoding="utf-8"))
        cases = {case["id"]: case for case in p01["cases"]}
        self.assertEqual(len(cases), 6)
        gemm_tolerance = {"relative_error_strict_max": 0.01, "zero_pair_equal": True}
        attention_tolerance = {"atol": 0.001, "rtol": 0.001}
        self.assertEqual(preserved["gemm_common"]["tolerances"], gemm_tolerance)
        self.assertEqual(preserved["attention"]["tolerances"], attention_tolerance)
        for fmt, threads, width in (("fp16", 8, 2), ("bf16", 16, 1)):
            for driver in ("simx", "rtlsim"):
                case = cases[f"gemm-{fmt}-{driver}"]
                self.assertEqual(case["reference"]["tolerances"], gemm_tolerance)
                self.assertEqual(case["reference"]["seed"], 50)
                self.assertIn(f"-DVX_CFG_NUM_THREADS={threads}", case["configs"])
                self.assertIn(f"-DVX_CFG_ISSUE_WIDTH={width}", case["configs"])
                self.assertEqual(case["args"], ["-m", "64", "-n", "64", "-k", "64"])
        for driver in ("simx", "rtlsim"):
            self.assertEqual(cases[f"attention-tf32-{driver}"]["reference"]["tolerances"],
                             attention_tolerance)

    def check_anchors(self, fmt):
        anchors = {**COMMON_ANCHORS, **FORMAT_ANCHORS[fmt]}
        self.assertEqual(len(anchors), 49)
        self.assertEqual({f"{fmt}_{suffix}" for suffix in anchors},
                         {key for key in self.cases if key.startswith(fmt + "_")})
        for suffix, (expected, exact) in anchors.items():
            case = self.cases[f"{fmt}_{suffix}"]
            with self.subTest(case=case["id"]):
                self.assertEqual(int(case["expected"], 16), expected)
                self.assertEqual(int(case["exact_fp32"], 16), exact)
                result = oracle.evaluate(fmt, tuple(int(word, 16) for word in case["a"]),
                                         tuple(int(word, 16) for word in case["b"]),
                                         int(case["c"], 16))
                self.assertEqual(int(result["expected"], 16), expected)
                self.assertEqual(int(result["exact_fp32"], 16), exact)

    def test_fp16_cases_match_independently_anchored_bits(self):
        self.check_anchors("fp16")

    def test_bf16_cases_match_independently_anchored_bits(self):
        self.check_anchors("bf16")

    def test_zero_products_with_maximum_exponents_preserve_the_finite_term(self):
        for fmt, a, b, expected, quantum_exponent, units in (
                ("fp16", [0x00000001, 0], [0x7BFF3C00, 0], 0x33800000, -38, 1 << 14),
                ("bf16", [0x00000080, 0], [0x7F7F3F80, 0], 0x00800000, -150, 1 << 24)):
            with self.subTest(format=fmt):
                case = self.cases[f"{fmt}_zero_times_max_exponent"]
                self.assertEqual([int(word, 16) for word in case["a"]], a)
                self.assertEqual([int(word, 16) for word in case["b"]], b)
                self.assertEqual(case["c"], "00000000")
                self.assertEqual(int(case["expected"], 16), expected)
                self.assertEqual(int(case["exact_fp32"], 16), expected)
                self.assertEqual(case["window"], {
                    "quantum_exponent": quantum_exponent, "signed_units": units,
                    "discarded_nonzero": False,
                })

    def test_exact_rational_counterexamples_retain_lost_information(self):
        expected = {
            "fp16_dense_positive": Fraction(141, 2),
            "bf16_dense_mixed_sign": Fraction(-1, 4),
            "fp16_scaled_min_subnormal": Fraction(2047, 1 << 19),
            "bf16_scaled_min_subnormal": Fraction(255, 1 << 13),
            "fp16_sticky_negative_tail": 1 + pow2(-24) - pow2(-48),
            "bf16_sticky_negative_tail": 1 + pow2(-24) - pow2(-266),
            "fp16_cancel_large_with_tiny": pow2(-24),
            "bf16_cancel_large_with_tiny": pow2(-133),
            "fp16_cancel_extreme_products": Fraction(1),
            "bf16_cancel_extreme_products": Fraction(1),
        }
        for case_id, value in expected.items():
            with self.subTest(case=case_id):
                recorded = self.cases[case_id]["exact_rational"]
                self.assertEqual(Fraction(int(recorded["numerator"]),
                                          int(recorded["denominator"])), value)
        for fmt in ("fp16", "bf16"):
            self.assertEqual(self.cases[f"{fmt}_sticky_negative_tail"]["window"], {
                "quantum_exponent": -24, "signed_units": (1 << 24) + 1,
                "discarded_nonzero": True,
            })
            self.assertEqual(self.cases[f"{fmt}_cancel_extreme_products"]["window"]["signed_units"], 0)

    def test_one_hot_fixture_packing_has_literal_lane_order(self):
        # Explicit encodings avoid deriving the expected arrangement with pack().
        for fmt, a, one in (("fp16", [0x40003C00, 0x48004400], 0x3C00),
                            ("bf16", [0x40003F80, 0x41004080], 0x3F80)):
            for lane in range(4):
                case = self.cases[f"{fmt}_packed_onehot_{lane}"]
                expected_b = [0, 0]
                expected_b[lane // 2] = one << (16 * (lane % 2))
                self.assertEqual([int(word, 16) for word in case["a"]], a)
                self.assertEqual([int(word, 16) for word in case["b"]], expected_b)


class RationalRoundingTests(unittest.TestCase):
    def assert_rounds(self, cases, **options):
        for value, expected in cases:
            with self.subTest(value=value, options=options):
                self.assertEqual(oracle.round_binary32(value, **options), expected)

    def test_exact_values_and_signed_normal_results(self):
        self.assert_rounds([(Fraction(0), 0), (Fraction(1), 0x3F800000),
                           (Fraction(-1, 4), 0xBE800000), (Fraction(141, 2), 0x428D0000),
                           (pow2(-126), 0x00800000), (pow2(127), 0x7F000000)])

    def test_halfway_ties_choose_even_for_both_signs(self):
        self.assert_rounds([(1 + pow2(-24), 0x3F800000),
                           (1 + 3 * pow2(-24), 0x3F800002),
                           (-1 - pow2(-24), 0xBF800000),
                           (-1 - 3 * pow2(-24), 0xBF800002),
                           (1 - pow2(-25), 0x3F800000)])

    def test_rational_values_on_either_side_of_halfway(self):
        midpoint = 1 + pow2(-24)
        self.assert_rounds([(midpoint - pow2(-100), 0x3F800000),
                           (midpoint + pow2(-100), 0x3F800001),
                           (-midpoint + pow2(-100), 0xBF800000),
                           (-midpoint - pow2(-100), 0xBF800001)])

    def test_rounding_carry_into_next_exponent(self):
        midpoint = 2 - pow2(-24)
        self.assert_rounds([(midpoint, 0x40000000),
                           (midpoint - pow2(-100), 0x3FFFFFFF),
                           (-midpoint, 0xC0000000)])

    def test_sticky_breaks_ties_but_cannot_create_a_guard_bit(self):
        self.assert_rounds([(1 + pow2(-24), 0x3F800001),
                           (-1 - pow2(-24), 0xBF800001),
                           (Fraction(1), 0x3F800000),
                           (1 + pow2(-25), 0x3F800000),
                           (Fraction(0), 0)], sticky=True)

    def test_gradual_underflow_and_zero_ties(self):
        self.assert_rounds([(pow2(-149), 0x00000001),
                           (pow2(-150), 0x00000000),
                           (-pow2(-150), 0x80000000),
                           (3 * pow2(-150), 0x00000002),
                           (pow2(-150) + pow2(-200), 0x00000001),
                           (pow2(-126) - pow2(-149), 0x007FFFFF),
                           (pow2(-126) - pow2(-150), 0x00800000)])

    def test_ftz_preserves_negative_sign_and_smallest_normal(self):
        self.assert_rounds([(pow2(-149), 0), (-pow2(-149), 0x80000000),
                           (pow2(-127), 0), (-pow2(-127), 0x80000000),
                           (pow2(-126), 0x00800000),
                           (-pow2(-126), 0x80800000)], flush_subnormal=True)

    def test_window_rounding_carry_precedes_ftz(self):
        # Normalized 24-bit rounding carries at 2^-126 - 2^-151. Gradual
        # binary32 rounds at a different midpoint; this contract uses FTZ.
        midpoint = pow2(-126) - pow2(-151)
        self.assert_rounds([(midpoint, 0x00800000),
                           (midpoint - pow2(-200), 0),
                           (-midpoint, 0x80800000),
                           (-midpoint + pow2(-200), 0x80000000)], flush_subnormal=True)

    def test_finite_to_infinity_midpoint_for_both_signs(self):
        maximum = pow2(128) - pow2(104)
        midpoint = pow2(128) - pow2(103)
        self.assert_rounds([(maximum, 0x7F7FFFFF), (-maximum, 0xFF7FFFFF),
                           (midpoint - 1, 0x7F7FFFFF), (midpoint, 0x7F800000),
                           (-midpoint + 1, 0xFF7FFFFF), (-midpoint, 0xFF800000)])


class OracleInputTests(unittest.TestCase):
    def test_pack_and_unpack_use_low_halfword_first(self):
        self.assertEqual(oracle.pack([0x1234, 0x5678, 0x9ABC, 0xDEF0]),
                         (0x56781234, 0xDEF09ABC))
        self.assertEqual(oracle.unpack((0x56781234, 0xDEF09ABC)),
                         (0x1234, 0x5678, 0x9ABC, 0xDEF0))

    def test_operand_counts_and_unsigned_ranges_are_enforced(self):
        for elements in ([], [0] * 3, [0] * 5, [-1, 0, 0, 0], [0x10000, 0, 0, 0]):
            with self.subTest(elements=elements), self.assertRaises(ValueError):
                oracle.pack(elements)
        for words in ((), (0,), (0, 0, 0), (-1, 0), (1 << 32, 0)):
            with self.subTest(words=words), self.assertRaises(ValueError):
                oracle.unpack(words)
        for bits in (-1, 1 << 16):
            with self.subTest(bits=bits), self.assertRaises(ValueError):
                oracle.decode(bits, 5, 10, 15)
        for c in (-1, 1 << 32):
            with self.subTest(c=c), self.assertRaises(ValueError):
                oracle.evaluate("fp16", (0, 0), (0, 0), c)

    def test_evaluate_rejects_malformed_a_and_b(self):
        for words in ((), (0,), (0, 0, 0), (-1, 0), (0, 1 << 32)):
            for side in ("a", "b"):
                operands = {"a": (0, 0), "b": (0, 0)}
                operands[side] = words
                with self.subTest(side=side, words=words), self.assertRaises(ValueError):
                    oracle.evaluate("bf16", **operands, c=0)

    def test_unsupported_formats_are_not_coerced(self):
        for fmt in ("", "FP16", "fp32", "tf32", "fp8", "i8", None):
            with self.subTest(format=fmt), self.assertRaises(ValueError):
                oracle.evaluate(fmt, (0, 0), (0, 0), 0)

    def test_subnormal_decode_preserves_value_and_effective_exponent(self):
        for bits, ebits, fbits, bias, expected, exponent in (
                (0x0001, 5, 10, 15, pow2(-24), -14),
                (0x8001, 5, 10, 15, -pow2(-24), -14),
                (0x0001, 8, 7, 127, pow2(-133), -126),
                (0x007F, 8, 7, 127, 127 * pow2(-133), -126)):
            with self.subTest(bits=bits, fraction_bits=fbits):
                decoded = oracle.decode(bits, ebits, fbits, bias)
                self.assertEqual(decoded.kind, "finite")
                self.assertEqual(decoded.value, expected)
                self.assertEqual(decoded.exponent, exponent)


CAPTURE_EXIT = """
import json, subprocess, sys
result = subprocess.run(sys.argv[1:], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, check=False)
print(json.dumps({"returncode": result.returncode, "output": result.stdout}))
"""


class ProductionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise AssertionError("A C++17 host compiler with UBSan is required for P02 tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-p02-contract-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build), "XLEN": "64"}
        # Regenerate from the canonical TOML on every run. No stale build tree
        # or hand-written stand-in header is permitted in these offline tests.
        flags = "-DVX_CFG_XLEN=64 -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_TYPE_TFR"
        for name in ("VX_config", "VX_types"):
            argv = [sys.executable, str(SOURCE / "ci/gen_config.py"),
                    "--config", str(SOURCE / f"{name}.toml"), "--format", "cpp",
                    "--resolved", "--output", str(cls.build / f"{name}.h")]
            if name == "VX_config":
                argv += ["--cflags", flags]
            run_host_command(argv, cwd=cls.build, env=cls.environment, timeout=10)
        cls.binary = cls.build / "tfr_model"
        cls.compile_model(cls.binary, HEADER.parent)
        cls.output = cls.run_model([])["output"]

    @classmethod
    def compile_model(cls, binary, fixture_directory):
        run_host_command(
            [cls.compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-DNDEBUG",
             "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-DP02_MODEL_ONLY",
             "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
             "-DP02_NUM_REGS=2", "-DP02_WINDOW=25", "-DP02_LATENCY=4",
             "-DP02_USE_DSP=0", "-DP02_LANE_MASK=1", "-I", str(fixture_directory),
             "-I", str(cls.build), "-I", str(SOURCE / "sw/common"),
             str(SOURCE / "hw/unittest/tcu_contract/main.cpp"), "-o", str(binary)],
            cwd=cls.build, env=cls.environment, timeout=30,
        )

    @classmethod
    def run_model(cls, args, *, binary=None, expected_exit=0):
        # The wrapper records expected failures while the shared bounded runner
        # still enforces process cleanup, runtime, memory and output limits.
        output = run_host_command(
            [sys.executable, "-c", CAPTURE_EXIT, str(binary or cls.binary), *args],
            cwd=cls.build, env=cls.environment, timeout=5,
        )
        result = json.loads(output)
        if result["returncode"] != expected_exit:
            raise AssertionError(f"Expected exit {expected_exit}, got {result['returncode']}:\n"
                                 + result["output"])
        return result

    def test_production_model_matches_all_98_frozen_vectors_under_ubsan(self):
        cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
        rows = [line for line in self.output.splitlines() if line.startswith("case ")]
        self.assertEqual(len(rows), 98)
        observed = {}
        for line in rows:
            fields = dict(field.split("=", 1) for field in line.split()[1:])
            self.assertNotIn(fields["id"], observed)
            self.assertEqual(fields["backend"], "tfr_model")
            self.assertEqual(fields["mode"], "model_dense")
            self.assertEqual(fields["status"], "pass")
            observed[fields["id"]] = fields
        self.assertEqual(set(observed), {case["id"] for case in cases})
        for case in cases:
            self.assertEqual(observed[case["id"]]["actual"], "0x" + case["expected"])
            self.assertEqual(observed[case["id"]]["expected"], "0x" + case["expected"])
        self.assertIn("scope=tfr_model_function", self.output)
        self.assertIn("compare=raw_bits full_simx=false", self.output)
        self.assertIn("selected=98 executed=98 passed=98 failed=0", self.output)
        self.assertTrue(self.output.endswith("result backend=tfr_model status=pass\n"))

    def test_format_and_exact_case_selection_report_actual_counts(self):
        for fmt in ("fp16", "bf16"):
            with self.subTest(format=fmt):
                output = self.run_model([f"--format={fmt}"])["output"]
                rows = [line for line in output.splitlines() if line.startswith("case ")]
                self.assertEqual(len(rows), 49)
                self.assertTrue(all(f"format={fmt} " in line for line in rows))
                self.assertIn("selected=49 executed=49 passed=49 failed=0", output)
        output = self.run_model(["--format=fp16", "--case=fp16_dense_positive"])["output"]
        self.assertIn("selected=1 executed=1 passed=1 failed=0", output)

    def test_malformed_unknown_duplicate_and_empty_cli_selections_fail(self):
        cases = [
            (["--format=tf32"], "--format must be"),
            (["--format="], "--format must be"),
            (["--format=all", "--format=fp16"], "Duplicate --format"),
            (["--case="], "nonempty exact fixture ID"),
            (["--case=missing"], "Unknown fixture ID"),
            (["--case=fp16_zero", "--case=fp16_zero"], "nonempty exact fixture ID"),
            (["--format=bf16", "--case=fp16_zero"], "contains no fixtures"),
            (["--unknown"], "Unknown option"),
            (["--format", "fp16"], "Unknown option"),
            (["--stalls"], "no clocked pipeline"),
            (["--help", "--format=all"], "--help must be used alone"),
        ]
        for args, diagnostic in cases:
            with self.subTest(args=args):
                output = self.run_model(args, expected_exit=2)["output"]
                self.assertIn(diagnostic, output)
                self.assertIn("error backend=tfr_model", output)
                self.assertNotIn("status=pass", output)
                self.assertNotIn("case backend=", output)

    def check_expected_bit_mutation(self, case_id, actual, expected):
        original = HEADER.read_bytes()
        text = original.decode("utf-8")
        self.assertEqual((actual ^ expected).bit_count(), 1)
        pattern = (rf'("{re.escape(case_id)}"[^\n]*\n\s*0x[0-9a-f]{{8}}u, )'
                   rf'0x{actual:08x}u')
        mutated, count = re.subn(pattern, rf"\g<1>0x{expected:08x}u", text)
        self.assertEqual(count, 1, "The mutation must affect exactly one expected result bit")
        mutant_directory = self.build / f"{case_id}-one-bit-mutant"
        mutant_directory.mkdir()
        (mutant_directory / HEADER.name).write_text(mutated, encoding="utf-8")
        binary = mutant_directory / "tfr_model_mutant"
        self.compile_model(binary, mutant_directory)
        output = self.run_model([f"--case={case_id}"], binary=binary,
                                expected_exit=1)["output"]
        self.assertEqual([line for line in output.splitlines() if line.startswith("case ")], [
            f"case backend=tfr_model mode=model_dense id={case_id} format={case_id.split('_')[0]} "
            f"actual=0x{actual:08x} expected=0x{expected:08x} status=fail",
        ])
        self.assertEqual([line for line in output.splitlines() if line.startswith("count ")], [
            "count backend=tfr_model mode=model_dense selected=1 executed=1 passed=0 failed=1 "
            "enabled_cycles=0 stall_cycles=0 hold_checks=0 hold_failures=0 status=fail",
        ])
        self.assertTrue(output.endswith("result backend=tfr_model status=fail\n"))
        self.assertEqual(HEADER.read_bytes(), original)

    def test_one_expected_bit_mutation_is_detected_without_changing_production(self):
        self.check_expected_bit_mutation("fp16_dense_positive", 0x428D0000, 0x428D0001)

    def test_signed_zero_sign_bit_mutation_is_detected_without_changing_production(self):
        self.check_expected_bit_mutation("fp16_c_subnormal_negative", 0x80000000, 0x00000000)

    def test_nan_payload_bit_mutation_is_detected_without_changing_production(self):
        self.check_expected_bit_mutation("fp16_input_quiet_nan", 0x7FC00000, 0x7FC00001)


if __name__ == "__main__":
    unittest.main()
