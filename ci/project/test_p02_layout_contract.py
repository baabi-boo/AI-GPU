# SPDX-License-Identifier: Apache-2.0
"""Source-only P02 WMMA profile, packed matrix and host geometry checks.

The independent decoder and matrix product below use exact Fractions. The
small C++ probe instantiates tensor_cfg.h on the host; it executes no Vortex
instructions and is not a SimX, native RTL or application execution result.
"""

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import p02_layout_fixture_oracle as oracle
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "profiles/p02-tfr.json"
FIXTURE = ROOT / "ci/project/fixtures/p02_layout_v1.json"
SPEC = importlib.util.spec_from_file_location("p02_layout_gen_config", ROOT / "ci/gen_config.py")
gen_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gen_config
SPEC.loader.exec_module(gen_config)
DISABLED_BANKS = ("TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4", "NVFP4",
                  "SPARSE", "DSM", "WGMMA")


def decode(bits, format_name):
    """Decode the published IEEE bit fields independently of the producer."""
    exponent_bits, fraction_bits = {"fp16": (5, 10), "bf16": (8, 7), "fp32": (8, 23)}[format_name]
    exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
    fraction = bits & ((1 << fraction_bits) - 1)
    if exponent == (1 << exponent_bits) - 1:
        raise AssertionError("layout cases must be finite")
    significand = Fraction(fraction, 1 << fraction_bits) + (exponent != 0)
    bias = (1 << (exponent_bits - 1)) - 1
    value = significand * Fraction(2) ** (max(exponent, 1) - bias)
    return -value if bits >> (exponent_bits + fraction_bits) else value


def memory_values(words, format_name):
    """Read little-endian byte memory, without using producer packing code."""
    raw = b"".join(int(word, 16).to_bytes(4, "little") for word in words)
    return [decode(int.from_bytes(raw[i:i + 2], "little"), format_name)
            for i in range(0, len(raw), 2)]


class LayoutFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.cases = cls.document["cases"]

    def test_fixture_bytes_and_case_inventory(self):
        self.assertEqual(FIXTURE.read_bytes(), oracle.render_json(oracle.fixture_document()))
        self.assertEqual(self.document["contract_id"], "p02-wmma-layout-v1")
        self.assertEqual(self.document["schema_version"], 1)
        self.assertFalse(self.document["gpu_execution_claimed"])
        self.assertFalse(self.document["producer"]["production_model_used"])
        self.assertEqual(self.document["case_count"], 20)
        self.assertEqual(Counter(case["format"] for case in self.cases), {"fp16": 10, "bf16": 10})
        self.assertEqual(len({case["id"] for case in self.cases}), 20)
        for fmt in ("fp16", "bf16"):
            selected = [case for case in self.cases if case["format"] == fmt]
            self.assertEqual(Counter(case["family"] for case in selected),
                             {"k_onehot": 6, "dense_boundaries": 2, "cancellation": 2})
            self.assertEqual({case["onehot_k"] for case in selected if "onehot_k" in case},
                             {0, 3, 4, 7, 8, 15})
            self.assertEqual({tuple(case["dimensions"].values()) for case in selected},
                             {(8, 4, 8), (16, 8, 16)})

    def test_all_packed_matrices_match_an_independent_exact_product(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                m, n, k = (case["dimensions"][key] for key in ("m", "n", "k"))
                self.assertEqual(case["leading_dimensions"], {"lda": k, "ldb": k, "ldc": n})
                self.assertEqual(case["tile_iterations"], {"m": m // 8, "n": n // 4, "k": k // 8})
                self.assertEqual(case["fedp_steps_per_output"], k // 4)
                self.assertEqual((len(case["a_words"]), len(case["b_words"]), len(case["expected"])),
                                 (m * k // 2, k * n // 2, m * n))
                for word in case["a_words"] + case["b_words"] + case["expected"]:
                    self.assertRegex(word, r"^[0-9a-f]{8}$")
                a = memory_values(case["a_words"], case["format"])
                b = memory_values(case["b_words"], case["format"])
                for row in range(m):
                    for col in range(n):
                        total = Fraction(0)
                        for inner in range(k):
                            # A row and B column have independently checked strides.
                            term = a[row * k + inner] * b[col * k + inner]
                            total += term
                            self.assertEqual(term.denominator, 1)
                            self.assertEqual(total.denominator, 1)
                            self.assertLess(abs(term), 4096)
                            self.assertLess(abs(total), 4096)
                        result = int(case["expected"][row * n + col], 16)
                        self.assertEqual(decode(result, "fp32"), total)
                        if total == 0:
                            self.assertEqual(result, 0, "exact cancellation must encode positive zero")

    def test_onehots_distinguish_packed_halves_and_row_column_boundaries(self):
        for case in self.cases:
            if case["family"] != "k_onehot":
                continue
            with self.subTest(case=case["id"]):
                m, n, k = (case["dimensions"][key] for key in ("m", "n", "k"))
                hot = case["onehot_k"]
                a = memory_values(case["a_words"], case["format"])
                b = memory_values(case["b_words"], case["format"])
                self.assertEqual({i % k for i, value in enumerate(a) if value}, {hot})
                self.assertEqual({i % k for i, value in enumerate(b) if value}, {hot})
                self.assertEqual(sum(bool(value) for value in a), m)
                self.assertEqual(sum(bool(value) for value in b), n)
                for row in range(m):
                    self.assertEqual(a[row * k + hot], (-1) ** row * (row + 1))
                for col in range(n):
                    self.assertEqual(b[col * k + hot], (-1) ** col * (col + 1))
                for row in (0, m - 1, 7, min(8, m - 1)):
                    for col in (0, n - 1, 3, min(4, n - 1)):
                        self.assertEqual(decode(int(case["expected"][row * n + col], 16), "fp32"),
                                         (-1) ** (row + col) * (row + 1) * (col + 1))

    def test_dense_patterns_distinguish_adjacent_rows_columns_and_tiles(self):
        for case in self.cases:
            if case["family"] != "dense_boundaries":
                continue
            m, n = case["dimensions"]["m"], case["dimensions"]["n"]
            result = case["expected"]
            self.assertNotEqual(result[:n], result[(m - 1) * n:])
            self.assertTrue(all(result[row * n] != result[row * n + n - 1] for row in range(m)))
            if m == 16:
                self.assertNotEqual(result[7 * n:8 * n], result[8 * n:9 * n])
                self.assertTrue(all(result[row * n + 3] != result[row * n + 4] for row in range(m)))

    def test_cancellation_has_nonzero_prefixes_and_zero_or_residual_outputs(self):
        for case in self.cases:
            if case["family"] != "cancellation":
                continue
            m, n, k = (case["dimensions"][key] for key in ("m", "n", "k"))
            a = memory_values(case["a_words"], case["format"])
            b = memory_values(case["b_words"], case["format"])
            for row in range(m):
                for col in range(n):
                    prefix = sum(a[row * k + inner] * b[col * k + inner]
                                 for inner in range(k // 2))
                    self.assertEqual(prefix, (row + 1) * (col + 1) * (k // 2))
                    expected = col + 1 if row % 2 else 0
                    self.assertEqual(decode(int(case["expected"][row * n + col], 16), "fp32"), expected)

    def test_encodings_and_halfword_packing_have_independent_bit_anchors(self):
        for fmt, expected in (("fp16", [0x0000, 0x3C00, 0xC000, 0x4C40]),
                              ("bf16", [0x0000, 0x3F80, 0xC000, 0x4188])):
            self.assertEqual([oracle.encode_integer(value, fmt) for value in (0, 1, -2, 17)], expected)
            self.assertEqual(oracle.pack_memory([0, 1, -2, 17], fmt),
                             [f"{expected[1]:04x}{expected[0]:04x}",
                              f"{expected[3]:04x}{expected[2]:04x}"])
        self.assertEqual(oracle.encode_integer(-17, "fp32"), 0xC1880000)

    def test_invalid_dimensions_formats_and_lossy_encodings_fail(self):
        for shape in ((0, 4, 8), (8, 0, 8), (8, 4, 0), (-8, 4, 8), (7, 4, 8), (8, 5, 8), (8, 4, 9)):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                oracle.make_case("fp16", "dense_boundaries", *shape)
        for fmt in ("tf32", "fp32", "FP16"):
            with self.assertRaises(ValueError):
                oracle.make_case(fmt, "dense_boundaries", 8, 4, 8)
        for hot in (-1, 8, None, True):
            with self.assertRaises(ValueError):
                oracle.make_case("bf16", "k_onehot", 8, 4, 8, hot)
        for value in (True, "1", 257):
            with self.assertRaises(ValueError):
                oracle.encode_integer(value, "bf16")
        with self.assertRaises(ValueError):
            oracle.pack_memory([1], "fp16")

    def test_check_is_read_only_and_rejects_drift(self):
        with tempfile.TemporaryDirectory(prefix="p02-layout-check-") as temporary:
            path = Path(temporary) / "fixture.json"
            with patch.object(oracle, "FIXTURE_PATH", path), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(oracle.main(["--check"]), 1)
                self.assertFalse(path.exists())
                self.assertEqual(oracle.main(["--write"]), 0)
                self.assertEqual(oracle.main(["--check"]), 0)
                altered = path.read_bytes().replace(b'"schema_version": 1', b'"schema_version": 2', 1)
                path.write_bytes(altered)
                self.assertEqual(oracle.main(["--check"]), 1)
                self.assertEqual(path.read_bytes(), altered)


class LayoutProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = gen_config.load_profile("p02-tfr", str(ROOT / "profiles"))
        toml = gen_config._load_toml(str(ROOT / "VX_config.toml"))
        cls.defaults, _ = gen_config._flatten_with_layout(toml)
        cls.enums = gen_config._load_enums(toml)
        cls.builtins = gen_config._load_var_table(toml, "builtin")
        cls.params = gen_config._load_var_table(toml, "param")

    def invoke(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            result = gen_config.main(["--config", str(ROOT / "VX_config.toml"),
                                      "--profile", "p02-tfr", *arguments])
        self.assertEqual(result, 0)
        return output.getvalue().strip()

    def test_existing_schema_rv64_and_provenance(self):
        gen_config.validate_profile(self.profile, self.defaults, self.enums,
                                    set(self.builtins) | set(self.params))
        self.assertEqual(self.profile.chain, ["p02-tfr"])
        self.assertEqual(self.invoke("--profile-xlen"), "64")
        with self.assertRaisesRegex(ValueError, "XLEN=32"):
            self.invoke("--xlen", "32", "--merge-configs")
        data = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertIn("UNQUALIFIED", data["description"])
        self.assertNotIn("reference", data)
        sources = "\n".join(data["sources"])
        for key in (*self.profile.values, "xlen", "VX_CFG_TCU_FEDP2K"):
            self.assertIn(key, sources)

    def test_resolved_geometry_native_arithmetic_and_all_feature_banks(self):
        resolver = gen_config.Resolver(self.defaults, dict(self.profile.values, SV_DPI=True),
                                       self.enums, self.builtins, self.params)
        expected = {
            "NUM_CLUSTERS": 1, "NUM_CORES": 1, "NUM_WARPS": 4, "NUM_THREADS": 4,
            "ISSUE_WIDTH": 1, "NUM_ALU_BLOCKS": 1, "NUM_LSU_BLOCKS": 1, "NUM_FPU_BLOCKS": 1,
            "NUM_TCU_BLOCKS": 1, "NUM_TCU_LANES": 4, "FPU_TYPE": "STD", "TCU_TYPE": "TFR",
            "EXT_TCU_ENABLE": True, "TCU_PE_RATIO": 1, "TCU_LATENCY": 4, "TCU_USE_DSP": 0,
            "TCU_FP16_ENABLE": True, "LMEM_ENABLE": True, "EXT_LDST_MATRIX_ENABLE": False,
            "TCU_FEDP2K": False, "TCU_TYPE_DPI": False, "FPU_TYPE_DPI": False,
        }
        expected.update({f"TCU_{bank}_ENABLE": False for bank in DISABLED_BANKS})
        for key, value in expected.items():
            with self.subTest(knob=key):
                self.assertEqual(resolver.resolve("VX_CFG_" + key), value)
        self.assertIs(self.defaults["VX_CFG_TCU_FEDP2K"], False)
        self.assertNotIn("VX_CFG_TCU_FEDP2K", self.profile.values)

    def test_application_and_backend_share_profile_and_explicit_format_defines(self):
        application = json.loads(FIXTURE.read_text(encoding="utf-8"))["application"]
        self.assertEqual(application["hardware_profile"], "p02-tfr")
        self.assertTrue(application["hardware_profile_shared_by_application_and_backend"])
        self.assertEqual(application["initial_accumulator_bits"], "00000000")
        self.assertEqual(application["leading_dimensions"], {"lda": "K", "ldb": "K", "ldc": "N"})
        for fmt in ("fp16", "bf16"):
            flags = [f"-DITYPE={fmt}", "-DOTYPE=fp32", "-DKUNROLL=1"]
            self.assertEqual(application["application_defines"][fmt], flags)
            self.assertEqual(application["configuration_ids"][fmt],
                             f"p02-tfr-rv64-t4-wmma-v1/{fmt}-fp32-kunroll1")
            tokens = shlex.split(self.invoke("--xlen", "64", "--merge-configs", "--cflags=" + " ".join(flags)))
            for token in flags + ["-DVX_CFG_LMEM_ENABLE", "-DVX_CFG_EXT_LDST_MATRIX_DISABLE",
                                  "-DVX_CFG_TCU_TYPE=TFR", "-DVX_CFG_FPU_TYPE=STD"]:
                self.assertIn(token, tokens)
            for bank in DISABLED_BANKS:
                self.assertIn(f"-DVX_CFG_TCU_{bank}_DISABLE", tokens)
            self.assertFalse(any("FEDP2K" in token for token in tokens))

    def test_source_application_uses_the_declared_ordinary_layout(self):
        kernel = (ROOT / "tests/regression/sgemm_tcu/kernel.cpp").read_text(encoding="utf-8")
        common = (ROOT / "tests/regression/sgemm_tcu/common.h").read_text(encoding="utf-8")
        self.assertIn("vt::wmma_context<VX_CFG_NUM_THREADS, vt::ITYPE, vt::OTYPE, false, 8, 0, vt::ldst_matrix_enabled>", kernel)
        for statement in ("ctx::fill_fragment(fragC, 0)", "pA + tile_row * K + i",
                          "pB + tile_col * K + i", "ctx::load_matrix_sync(fragA, pTileA, K)",
                          "ctx::load_matrix_sync<vt::col_major>(fragB, pTileB, K)",
                          "pC + tile_row * N + tile_col", "ctx::store_matrix_sync(pTileC, fragC, N)"):
            self.assertIn(statement, kernel)
        self.assertRegex(common, r"#ifndef KUNROLL\s+#define KUNROLL 1\s+#endif")

    def test_host_tensor_cfg_probe_matches_the_frozen_geometry(self):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "P02 geometry checks require a C++17 host compiler")
        with tempfile.TemporaryDirectory(prefix="p02-layout-geometry-") as temporary:
            build = Path(temporary)
            environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "TMPDIR": str(build)}
            header = self.invoke("--xlen", "64", "--format", "cpp", "--resolved",
                                 "--cflags=-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -DSV_DPI")
            (build / "VX_config.h").write_text(header + "\n", encoding="utf-8")
            self.assertNotRegex(header, r"(?m)^#define VX_CFG_TCU_FEDP2K(?:\s|$)")
            source = r'''
#include "VX_config.h"
#include "tensor_cfg.h"
#include <cstdio>
#if !defined(VX_CFG_TCU_TYPE_TFR) || !defined(VX_CFG_FPU_TYPE_STD)
#error Native arithmetic must be selected
#endif
#if !defined(VX_CFG_LMEM_ENABLE) || defined(VX_CFG_EXT_LDST_MATRIX_ENABLE) || defined(VX_CFG_TCU_FEDP2K)
#error The ordinary application feature path changed
#endif
static_assert(VX_CFG_XLEN == 64 && VX_CFG_NUM_WARPS == 4 && VX_CFG_NUM_THREADS == 4);
static_assert(VX_CFG_TCU_PE_RATIO == 1 && VX_CFG_TCU_LATENCY == 4 && VX_CFG_TCU_USE_DSP == 0);
template<class T> void show() {
  using C = vortex::tensor::wmma_config_t<VX_CFG_NUM_THREADS, T, vortex::tensor::fp32, 8, 0, 0, 4>;
  std::printf("%s %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u\n", T::name,
    C::tcM, C::tcN, C::tcK, C::xtileM, C::xtileN, C::xtileK,
    C::tileM, C::tileN, C::tileK, C::m_steps, C::n_steps, C::k_steps,
    C::NRA, C::NRB, C::NRC, C::i_ratio);
}
int main() { show<vortex::tensor::fp16>(); show<vortex::tensor::bf16>(); }
'''
            (build / "geometry.cpp").write_text(source, encoding="utf-8")
            run_host_command([compiler, "-std=c++17", "-O0", "-Wall", "-Wextra", "-Werror",
                              "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
                              "-I", str(ROOT / "sw/common"), str(build / "geometry.cpp"),
                              "-o", str(build / "geometry")], cwd=build, env=environment, timeout=30)
            output = run_host_command([str(build / "geometry")], cwd=build, env=environment, timeout=10)
            geometry = json.loads(FIXTURE.read_text(encoding="utf-8"))["geometry"]
            expected = [2, 2, 2, 8, 4, 4, 8, 4, 8, 4, 2, 2, 8, 4, 8, 2]
            recorded = []
            for key in ("tc_words", "tile_words", "tile_elements", "steps", "fragment_registers"):
                recorded.extend(geometry[key].values())
            recorded.append(geometry["input_elements_per_word"])
            self.assertEqual(recorded, expected)
            self.assertEqual(output.splitlines(), [fmt + " " + " ".join(map(str, expected))
                                                  for fmt in ("fp16", "bf16")])


if __name__ == "__main__":
    unittest.main()
