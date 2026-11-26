# SPDX-License-Identifier: Apache-2.0
"""Offline unit tests for Wave 8B aigpu-b1 profiles and roofline comparator."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b1_roofline_compare as cmp_mod


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "VX_config.toml"
PROFILES_DIR = ROOT / "profiles"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen_config = _load_module("test_b1_gen_config", ROOT / "ci/gen_config.py")
profile_check = _load_module("test_b1_profile_check", ROOT / "ci/profile_check.py")


class AigpuB1ProfileSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.toml = gen_config._load_toml(str(CONFIG_PATH))
        cls.defaults, _ = gen_config._flatten_with_layout(cls.toml)
        cls.enums = gen_config._load_enums(cls.toml)
        cls.builtins = gen_config._load_var_table(cls.toml, "builtin")
        cls.params = gen_config._load_var_table(cls.toml, "param")
        cls.read_only = set(cls.builtins) | set(cls.params)

    def _invoke_gen_config(self, profile_name: str, *arguments: str) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            rc = gen_config.main([
                "--config", str(CONFIG_PATH),
                "--profile", profile_name,
                *arguments,
            ])
        self.assertEqual(rc, 0)
        return output.getvalue().strip()

    def test_both_profiles_pass_gen_config_schema_and_rv64_selection(self):
        for profile_name in ("aigpu-b1", "aigpu-b1-tile"):
            with self.subTest(profile=profile_name):
                raw = json.loads(
                    (PROFILES_DIR / f"{profile_name}.json").read_text(encoding="utf-8")
                )
                prof = gen_config.load_profile(profile_name, str(PROFILES_DIR))
                gen_config.validate_profile(prof, self.defaults, self.enums, self.read_only)
                self.assertEqual(prof.xlen, 64)
                self.assertEqual(self._invoke_gen_config(profile_name, "--profile-xlen"), "64")

                with self.assertRaisesRegex(ValueError, "XLEN=32"):
                    self._invoke_gen_config(profile_name, "--xlen", "32", "--merge-configs")

                merged = shlex.split(
                    self._invoke_gen_config(profile_name, "--xlen", "64", "--merge-configs")
                )
                self.assertIn(f"-DVX_PROFILE={profile_name}", merged)
                self.assertIn("-DVX_CFG_TCU_TYPE=TFR", merged)
                self.assertIn("-DVX_CFG_FPU_TYPE=STD", merged)
                for gfx_disable in (
                    "-DVX_CFG_EXT_TEX_DISABLE",
                    "-DVX_CFG_EXT_RASTER_DISABLE",
                    "-DVX_CFG_EXT_OM_DISABLE",
                    "-DVX_CFG_EXT_RTU_DISABLE",
                ):
                    self.assertIn(gfx_disable, merged)

                # Verify resolved C++, Verilog, and cflags outputs succeed cleanly.
                for fmt in ("cflags", "cpp", "verilog"):
                    extra = ["--cflags", "-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64"]
                    if fmt != "cflags":
                        extra.append("--resolved")
                    out = self._invoke_gen_config(
                        profile_name, "--xlen", "64", "-f", fmt, *extra
                    )
                    self.assertTrue(out)

                # Verify sources provenance explicitly disclaims physical silicon.
                evidence_note = raw["sources"].get("evidence_status", "")
                self.assertIn("not measured physical silicon", evidence_note.lower())

    def test_aigpu_b1_requested_architectural_knobs_and_resolved_invariants(self):
        _, _, cfg = cmp_mod.resolve_profile_config("aigpu-b1")
        expected = {
            "VX_CFG_XLEN": 64,
            "VX_CFG_NUM_WARPS": 32,
            "VX_CFG_NUM_THREADS": 32,
            "VX_CFG_ISSUE_WIDTH": 4,
            "VX_CFG_FETCH_WIDTH": 4,
            "VX_CFG_NUM_ALU_LANES": 32,
            "VX_CFG_NUM_FPU_LANES": 32,
            "VX_CFG_NUM_LSU_LANES": 8,
            "VX_CFG_DCACHE_SIZE": 131072,
            "VX_CFG_DCACHE_MSHR_SIZE": 24,
            "VX_CFG_DCACHE_NUM_BANKS": 4,
            "VX_CFG_LMEM_ENABLE": True,
            "VX_CFG_LMEM_LOG_SIZE": 17,
            "VX_CFG_LMEM_SIZE": 131072,
            "VX_CFG_LMEM_NUM_BANKS": 16,
            "VX_CFG_VM_ENABLE": True,
            "VX_CFG_EXT_A_ENABLE": True,
            "VX_CFG_EXT_ZACAS_ENABLE": True,
            "VX_CFG_EXT_ZFHMIN_ENABLE": True,
            "VX_CFG_EXT_MUFU_ENABLE": True,
            "VX_CFG_NUM_MUFU_LANES": 16,
            "VX_CFG_EXT_TCU_ENABLE": True,
            "VX_CFG_TCU_TYPE": "TFR",
            "VX_CFG_TCU_PE_RATIO": 2,
            "VX_CFG_TCU_WGMMA_ENABLE": True,
            "VX_CFG_TCU_FP16_ENABLE": True,
            "VX_CFG_TCU_TF32_ENABLE": True,
            "VX_CFG_TCU_FP8_ENABLE": True,
            "VX_CFG_TCU_FP4_ENABLE": True,
            "VX_CFG_TCU_MX_ENABLE": True,
            "VX_CFG_TCU_MXFP4_ENABLE": True,
            "VX_CFG_TCU_NVFP4_ENABLE": True,
            "VX_CFG_TCU_INT8_ENABLE": True,
            "VX_CFG_TCU_SPARSE_ENABLE": True,
            "VX_CFG_EXT_DXA_ENABLE": True,
            "VX_CFG_NUM_BARRIERS": 16,
            "VX_CFG_FPU_TYPE": "STD",
            "VX_CFG_EXT_TEX_ENABLE": False,
            "VX_CFG_EXT_RASTER_ENABLE": False,
            "VX_CFG_EXT_OM_ENABLE": False,
            "VX_CFG_EXT_RTU_ENABLE": False,
            "VX_CFG_NUM_CLUSTERS": 4,
            "VX_CFG_NUM_CORES": 16,
            "VX_CFG_L2_ENABLE": True,
            "VX_CFG_L2_SIZE": 67108864,
            "VX_CFG_L2_NUM_WAYS": 16,
            "VX_CFG_L2_NUM_BANKS": 64,
            "VX_CFG_L2_MSHR_SIZE": 192,
            "VX_CFG_PLATFORM_CLOCK_RATE": 2000,
            "VX_CFG_PLATFORM_MEMORY_PEAK_BW": 4000000,
            "VX_CFG_PLATFORM_MEMORY_TYPE": "HBM3",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(cfg[key], value)
        self.assertEqual(cfg["VX_CFG_NUM_CLUSTERS"] * cfg["VX_CFG_NUM_CORES"], 64)
        self.assertLessEqual(cfg["VX_CFG_LMEM_LOG_SIZE"], 18)

    def test_aigpu_b1_tile_requested_knobs_and_rtl_slice_bounds(self):
        _, _, cfg = cmp_mod.resolve_profile_config("aigpu-b1-tile")
        expected = {
            "VX_CFG_XLEN": 64,
            "VX_CFG_NUM_CLUSTERS": 1,
            "VX_CFG_NUM_CORES": 4,
            "VX_CFG_SOCKET_SIZE": 4,
            "VX_CFG_NUM_WARPS": 8,
            "VX_CFG_NUM_THREADS": 8,
            "VX_CFG_ISSUE_WIDTH": 2,
            "VX_CFG_LMEM_ENABLE": True,
            "VX_CFG_L2_ENABLE": True,
            "VX_CFG_L2_SIZE": 262144,
            "VX_CFG_FPU_TYPE": "STD",
            "VX_CFG_EXT_TCU_ENABLE": True,
            "VX_CFG_TCU_TYPE": "TFR",
            "VX_CFG_TCU_WGMMA_ENABLE": True,
            "VX_CFG_TCU_FP16_ENABLE": True,
            "VX_CFG_TCU_FP8_ENABLE": True,
            "VX_CFG_TCU_FP4_ENABLE": True,
            "VX_CFG_TCU_MX_ENABLE": True,
            "VX_CFG_TCU_MXFP4_ENABLE": True,
            "VX_CFG_TCU_NVFP4_ENABLE": True,
            "VX_CFG_TCU_INT8_ENABLE": True,
            "VX_CFG_TCU_SPARSE_ENABLE": True,
            "VX_CFG_EXT_DXA_ENABLE": True,
            "VX_CFG_EXT_MUFU_ENABLE": True,
            "VX_CFG_EXT_A_ENABLE": True,
            "VX_CFG_EXT_TEX_ENABLE": False,
            "VX_CFG_EXT_RASTER_ENABLE": False,
            "VX_CFG_EXT_OM_ENABLE": False,
            "VX_CFG_EXT_RTU_ENABLE": False,
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(cfg[key], value)
        self.assertEqual(cfg["VX_CFG_NUM_CORES"] % cfg["VX_CFG_SOCKET_SIZE"], 0)
        self.assertLessEqual(cfg["VX_CFG_LMEM_LOG_SIZE"], 18)

    def test_profile_check_peak_metrics_match_reference(self):
        for profile_name in ("aigpu-b1", "aigpu-b1-tile"):
            with self.subTest(profile=profile_name):
                data, reference = profile_check.load_profile(profile_name)
                self.assertEqual(data["xlen"], 64)
                cfg = profile_check.resolved_config(profile_name, 64)
                measured = profile_check.peak_metrics(cfg, reference)
                self.assertEqual(set(measured), set(reference))
                for key, model_val in measured.items():
                    self.assertAlmostEqual(float(model_val), float(reference[key]), places=6)


class B1RooflineComparatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = cmp_mod.build_comparison_report()

    def test_report_loads_all_four_profiles_with_strict_honesty_labels(self):
        self.assertEqual(
            self.report["profiles_order"],
            ["aigpu-b1", "aigpu-b1-tile", "rtx5080", "h100"],
        )
        self.assertEqual(self.report["evidence_level"], "modeled_analytical")
        self.assertIs(self.report["silicon_measured"], False)
        self.assertEqual(self.report["phase_status_effect"], "none")
        self.assertIn("NOT measured physical silicon", self.report["disclaimer"])

        for pname in self.report["profiles_order"]:
            entry = self.report["profiles"][pname]
            with self.subTest(profile=pname):
                self.assertEqual(entry["evidence_level"], "modeled_analytical")
                self.assertIs(entry["silicon_measured"], False)
                self.assertEqual(entry["phase_status_effect"], "none")

    def test_honesty_guard_rejects_physical_or_silicon_claims(self):
        for bad_level in ("silicon_measured", "fpga_measured", "rtl_verified", "simulated"):
            forged = copy.deepcopy(self.report)
            forged["evidence_level"] = bad_level
            with self.assertRaisesRegex(ValueError, "evidence_level"):
                cmp_mod.validate_honesty_record(forged)

        forged_flag = copy.deepcopy(self.report)
        forged_flag["silicon_measured"] = True
        with self.assertRaisesRegex(ValueError, "silicon_measured=False"):
            cmp_mod.validate_honesty_record(forged_flag)

    def test_analytical_peaks_ridges_and_llama_regimes_are_positive_and_consistent(self):
        profiles = self.report["profiles"]

        # Positive sanity across all profiles and supported formats
        for pname, entry in profiles.items():
            mem = entry["memory"]
            self.assertGreater(mem["clock_mhz"], 0.0)
            self.assertGreater(mem["bandwidth_gbs"], 0.0)
            self.assertTrue(math.isfinite(mem["bandwidth_gbs"]))
            self.assertGreater(entry["scalar_fp32"]["dense_tflops"], 0.0)
            self.assertGreater(entry["scalar_fp32"]["ridge_flop_per_byte"], 0.0)

            for fmt_name, fmt in entry["tensor_formats"].items():
                if fmt["supported"]:
                    dense = fmt["dense_peak"]
                    ridge = fmt["dense_ridge_flop_per_byte"]
                    self.assertGreater(dense, 0.0)
                    self.assertGreater(ridge, 0.0)
                    self.assertAlmostEqual(ridge, (dense * 1000.0) / mem["bandwidth_gbs"], places=9)
                    if fmt["sparse_2_4_supported"]:
                        self.assertAlmostEqual(fmt["sparse_2_4_peak"], 2.0 * dense, places=9)
                        self.assertAlmostEqual(
                            fmt["sparse_2_4_ridge_flop_per_byte"],
                            2.0 * ridge,
                            places=9,
                        )
                else:
                    self.assertIsNone(fmt["dense_peak"])
                    self.assertIsNone(fmt["sparse_2_4_peak"])
                    self.assertIsNone(fmt["dense_ridge_flop_per_byte"])

        # Exact expected analytical numbers for aigpu-b1:
        # 64 cores * 4 TCU blocks * (32 / 2) PEs * 4 FEDP_K = 16384 32b FMA terms/clk
        # At 2.0 GHz:
        #   FP32 vec = 64 * 4 * 32 * 2 * 2.0 / 1000 = 32.768 TFLOPS
        #   FP16/BF16 dense = 16384 * 2 * 2 * 2.0 / 1000 = 131.072 TFLOPS, 2:4 sparse = 262.144
        #   FP8 dense       = 262.144 TFLOPS, 2:4 sparse = 524.288
        #   MXFP4 / NVFP4   = 524.288 TOPS, 2:4 sparse = 1048.576
        b1 = profiles["aigpu-b1"]
        self.assertTrue(b1["topology"]["graphics_disabled"])
        self.assertEqual(b1["topology"]["total_cores"], 64)
        self.assertEqual(b1["memory"]["bandwidth_gbs"], 4000.0)
        self.assertAlmostEqual(b1["scalar_fp32"]["dense_tflops"], 32.768, places=6)
        self.assertAlmostEqual(b1["tensor_formats"]["fp16_bf16"]["dense_peak"], 131.072, places=6)
        self.assertAlmostEqual(b1["tensor_formats"]["fp16_bf16"]["sparse_2_4_peak"], 262.144, places=6)
        self.assertAlmostEqual(b1["tensor_formats"]["fp8"]["dense_peak"], 262.144, places=6)
        self.assertAlmostEqual(b1["tensor_formats"]["mxfp4"]["dense_peak"], 524.288, places=6)
        self.assertAlmostEqual(b1["tensor_formats"]["nvfp4"]["sparse_2_4_peak"], 1048.576, places=6)

        # Tile profile checks: 4 cores, graphics disabled, supports MXFP4/NVFP4/WGMMA
        tile = profiles["aigpu-b1-tile"]
        self.assertTrue(tile["topology"]["graphics_disabled"])
        self.assertEqual(tile["topology"]["total_cores"], 4)
        self.assertAlmostEqual(tile["tensor_formats"]["fp16_bf16"]["dense_peak"], 0.2048, places=6)
        self.assertAlmostEqual(tile["tensor_formats"]["nvfp4"]["sparse_2_4_peak"], 1.6384, places=6)
        self.assertGreater(
            b1["tensor_formats"]["fp16_bf16"]["dense_peak"],
            tile["tensor_formats"]["fp16_bf16"]["dense_peak"],
        )

        # H100 has FP8 + WGMMA enabled, FP4/MXFP4/NVFP4 disabled
        h100 = profiles["h100"]
        self.assertTrue(h100["tensor_formats"]["fp8"]["supported"])
        self.assertFalse(h100["tensor_formats"]["mxfp4"]["supported"])
        self.assertFalse(h100["tensor_formats"]["nvfp4"]["supported"])
        self.assertEqual(h100["llama_workpoints"]["llama_decode_nvfp4"]["dense_regime"], "unsupported")

        # RTX 5080 has FP4/MX/MXFP4/NVFP4 enabled
        rtx = profiles["rtx5080"]
        self.assertTrue(rtx["tensor_formats"]["mxfp4"]["supported"])
        self.assertTrue(rtx["tensor_formats"]["nvfp4"]["supported"])

        # Llama prefill AI >> decode AI, and b1 is compute-bound in prefill vs memory-bound in decode
        prefill_fp8 = b1["llama_workpoints"]["llama_prefill_fp8"]
        decode_fp8 = b1["llama_workpoints"]["llama_decode_fp8"]
        self.assertGreater(
            prefill_fp8["arithmetic_intensity_flop_per_byte"],
            100.0 * decode_fp8["arithmetic_intensity_flop_per_byte"],
        )
        self.assertEqual(prefill_fp8["dense_regime"], "compute-bound")
        self.assertEqual(decode_fp8["dense_regime"], "memory-bound")
        self.assertEqual(b1["llama_workpoints"]["llama_decode_fp16_bf16"]["dense_regime"], "memory-bound")
        self.assertEqual(b1["llama_workpoints"]["llama_decode_nvfp4"]["dense_regime"], "memory-bound")

    def test_cli_json_and_text_modes(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc_text = cmp_mod.main([])
        self.assertEqual(rc_text, 0)
        self.assertIn("modeled_analytical", stdout.getvalue())
        self.assertIn("silicon_measured=False", stdout.getvalue())
        self.assertIn("aigpu-b1-tile", stdout.getvalue())

        with tempfile.TemporaryDirectory(prefix="b1-roofline-cli-") as tmp_dir:
            out_json = Path(tmp_dir) / "report.json"
            proc = subprocess.run(
                [sys.executable, "-B", str(ROOT / "ci/project/b1_roofline_compare.py"),
                 "--json", "--output", str(out_json)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.stdout, "")
            parsed = json.loads(out_json.read_text(encoding="utf-8"))
            cmp_mod.validate_honesty_record(parsed)
            self.assertEqual(set(parsed["profiles"]), set(cmp_mod.TARGET_PROFILES))


if __name__ == "__main__":
    unittest.main()
