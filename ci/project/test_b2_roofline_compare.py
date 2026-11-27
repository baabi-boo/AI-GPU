# SPDX-License-Identifier: Apache-2.0
"""Unit tests for hierarchical AI-GPU B2 analytical roofline comparator."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b2_roofline_compare as cmp_mod
import b2_program_tracker as tracker


ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "profiles"


def _write_temp_profiles_dir(tmp_path: Path, include_b1: bool = True) -> None:
    """Populate a temporary profiles directory with B2 and optional B1 JSONs."""
    for name in cmp_mod.AIGPU_B2_TARGETS:
        payload = cmp_mod._b2_authoritative_profile_payload(name)
        (tmp_path / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if include_b1:
        for name in cmp_mod.AIGPU_B1_TARGETS:
            src = PROFILES_DIR / f"{name}.json"
            (tmp_path / f"{name}.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


class B2ProfileResolutionAndPeaksTests(unittest.TestCase):
    def test_authoritative_temp_profiles_dir_and_real_b1_profiles_resolve(self):
        with tempfile.TemporaryDirectory(prefix="b2-profiles-test-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            _write_temp_profiles_dir(tmp_path, include_b1=True)

            report = cmp_mod.build_b2_comparison_report(
                profiles_dir=tmp_path,
                allow_builtin_fallback=False,
                selected_workloads=("llama3-70b", "deepseek-v3"),
                selected_formats=("fp16", "fp8_e4m3", "nvfp4"),
            )
            cmp_mod.validate_honesty_record(report)

            for pname in cmp_mod.ALL_AIGPU_TARGETS:
                self.assertEqual(report["targets"][pname]["profile_source"], "profiles_dir")

            b2 = report["targets"]["aigpu-b2"]
            self.assertEqual(b2["topology"]["total_cores"], 128)
            self.assertEqual(b2["topology"]["die_count"], 1)
            self.assertEqual(b2["topology"]["tmem_bytes_total"], 32 * 1024 * 1024)
            self.assertEqual(b2["memory"]["bandwidth_gbs"], 4000.0)
            self.assertTrue(b2["topology"]["graphics_disabled"])

            # TFRv2 reconciliation: 1,152 / 2,304 / 4,608 dense and 2x sparse
            self.assertAlmostEqual(b2["tensor_formats"]["fp16"]["dense_peak"], 1152.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["bf16"]["dense_peak"], 1152.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["tf32"]["dense_peak"], 576.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["fp8_e4m3"]["dense_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["fp8_e5m2"]["dense_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["mxfp8"]["dense_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["mxfp6_e2m3"]["dense_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["mxfp6_e3m2"]["dense_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["mxfp4"]["dense_peak"], 4608.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["nvfp4"]["dense_peak"], 4608.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["int8"]["dense_peak"], 2304.0, places=6)

            # 2:4 structured sparsity = 2x dense
            self.assertAlmostEqual(b2["tensor_formats"]["fp16"]["sparse_2_4_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["fp8_e4m3"]["sparse_2_4_peak"], 4608.0, places=6)
            self.assertAlmostEqual(b2["tensor_formats"]["nvfp4"]["sparse_2_4_peak"], 9216.0, places=6)

            # Vortex base resolved TFR preserved alongside TFRv2 architectural target
            self.assertAlmostEqual(
                b2["tensor_formats"]["fp16"]["tfr_base_resolved_dense_peak"], 1048.576, places=6
            )
            self.assertIsNone(b2["tensor_formats"]["mxfp6_e2m3"]["tfr_base_resolved_dense_peak"])

            # Dual-die CoWoS-L target: 256 cores, 2,304 / 4,608 / 9,216 dense @ 2.0 GHz, 8 TB/s HBM3E
            b2_dual = report["targets"]["aigpu-b2-dual"]
            self.assertEqual(b2_dual["topology"]["total_cores"], 256)
            self.assertEqual(b2_dual["topology"]["die_count"], 2)
            self.assertEqual(b2_dual["topology"]["tmem_bytes_total"], 64 * 1024 * 1024)
            self.assertEqual(b2_dual["memory"]["bandwidth_gbs"], 8000.0)
            self.assertAlmostEqual(b2_dual["tensor_formats"]["fp16"]["dense_peak"], 2304.0, places=6)
            self.assertAlmostEqual(b2_dual["tensor_formats"]["fp8_e4m3"]["dense_peak"], 4608.0, places=6)
            self.assertAlmostEqual(b2_dual["tensor_formats"]["nvfp4"]["dense_peak"], 9216.0, places=6)
            self.assertAlmostEqual(b2_dual["tensor_formats"]["nvfp4"]["sparse_2_4_peak"], 18432.0, places=6)

            # Tile target: 4 cores, 400 MHz RTL ref -> 3.6/7.2/14.4 @ 400 MHz and 18/36/72 scaled @ 2.0 GHz
            b2_tile = report["targets"]["aigpu-b2-tile"]
            self.assertEqual(b2_tile["topology"]["total_cores"], 4)
            self.assertEqual(b2_tile["memory"]["clock_mhz"], 400.0)
            self.assertAlmostEqual(b2_tile["tensor_formats"]["fp16"]["dense_peak"], 3.6, places=6)
            self.assertAlmostEqual(b2_tile["tensor_formats"]["fp8_e4m3"]["dense_peak"], 7.2, places=6)
            self.assertAlmostEqual(b2_tile["tensor_formats"]["nvfp4"]["dense_peak"], 14.4, places=6)
            self.assertAlmostEqual(
                b2_tile["tensor_formats"]["fp16"]["tfrv2_scaled_2ghz_dense_peak"], 18.0, places=6
            )
            self.assertAlmostEqual(
                b2_tile["tensor_formats"]["fp8_e4m3"]["tfrv2_scaled_2ghz_dense_peak"], 36.0, places=6
            )
            self.assertAlmostEqual(
                b2_tile["tensor_formats"]["nvfp4"]["tfrv2_scaled_2ghz_dense_peak"], 72.0, places=6
            )

            # Preserved legacy B1 targets remain intact
            b1 = report["targets"]["aigpu-b1"]
            self.assertEqual(b1["topology"]["total_cores"], 64)
            self.assertAlmostEqual(b1["tensor_formats"]["fp16"]["dense_peak"], 131.072, places=6)
            self.assertFalse(b1["tensor_formats"]["mxfp6_e2m3"]["supported"])

    def test_live_repo_profiles_dir_works_with_or_without_b2_json_files(self):
        # Handles concurrent creation of profiles/aigpu-b2*.json by sibling workers cleanly.
        for name in cmp_mod.AIGPU_B2_TARGETS:
            analyzed = cmp_mod.analyze_aigpu_profile(name, profiles_dir=PROFILES_DIR)
            cmp_mod.validate_honesty_record(analyzed)
            if (PROFILES_DIR / f"{name}.json").is_file():
                self.assertEqual(analyzed["profile_source"], "profiles_dir")
            else:
                self.assertEqual(analyzed["profile_source"], "authoritative_spec_fallback")

        # Strict mode rejects missing profile JSON when using an empty dir
        with tempfile.TemporaryDirectory(prefix="b2-empty-profiles-") as empty_dir:
            with self.assertRaises(FileNotFoundError):
                cmp_mod.analyze_aigpu_profile(
                    "aigpu-b2", profiles_dir=Path(empty_dir), allow_builtin_fallback=False
                )


class HierarchicalRooflineCeilingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        cls.b2_dual = cmp_mod.analyze_aigpu_profile("aigpu-b2-dual")
        cls.b1 = cmp_mod.analyze_aigpu_profile("aigpu-b1")

    def test_six_level_hierarchy_bottleneck_attribution(self):
        # 1. Pure compute-bound high-AI traffic -> compute ceiling
        t_compute = cmp_mod.HierarchicalTraffic(
            flops=1e15, tmem_bytes=1e12, l1_lmem_bytes=1e11, l2_slc_bytes=1e10, hbm_bytes=1e9
        )
        r_comp = cmp_mod.evaluate_hierarchical_roofline(self.b2, "fp8_e4m3", t_compute)
        self.assertEqual(r_comp["limiting_level"], "compute")
        self.assertAlmostEqual(r_comp["attained_tflops_or_tops"], 2304.0, places=4)

        # 2. Level 1 TMEM-bound when accumulator drain dominates
        t_tmem = cmp_mod.HierarchicalTraffic(
            flops=1e13, tmem_bytes=1e12, l1_lmem_bytes=1e9, l2_slc_bytes=1e9, hbm_bytes=1e8
        )
        r_tmem = cmp_mod.evaluate_hierarchical_roofline(self.b2, "fp8_e4m3", t_tmem)
        self.assertEqual(r_tmem["limiting_level"], "level1_tmem")

        # 3. Level 2 L1/LMEM-bound
        t_l1 = cmp_mod.HierarchicalTraffic(
            flops=1e13, tmem_bytes=1e9, l1_lmem_bytes=1e12, l2_slc_bytes=1e9, hbm_bytes=1e8
        )
        r_l1 = cmp_mod.evaluate_hierarchical_roofline(self.b2, "fp8_e4m3", t_l1)
        self.assertEqual(r_l1["limiting_level"], "level2_l1_lmem")

        # 4. Level 3 L2/SLC-bound
        t_l2 = cmp_mod.HierarchicalTraffic(
            flops=1e13, tmem_bytes=1e9, l1_lmem_bytes=1e9, l2_slc_bytes=1e12, hbm_bytes=1e8
        )
        r_l2 = cmp_mod.evaluate_hierarchical_roofline(self.b2, "fp8_e4m3", t_l2)
        self.assertEqual(r_l2["limiting_level"], "level3_l2_slc")

        # 5. Level 4 HBM-bound + Hardware Decompression Engine bandwidth amplification
        t_hbm = cmp_mod.HierarchicalTraffic(
            flops=1e13,
            tmem_bytes=1e9,
            l1_lmem_bytes=1e9,
            l2_slc_bytes=1e9,
            hbm_bytes=1e12,
            compressed_weight_bytes=1e12,
            de_amplification=1.45,
        )
        r_hbm_no_de = cmp_mod.evaluate_hierarchical_roofline(
            self.b2, "fp8_e4m3", t_hbm, use_de_compression=False
        )
        r_hbm_with_de = cmp_mod.evaluate_hierarchical_roofline(
            self.b2, "fp8_e4m3", t_hbm, use_de_compression=True
        )
        self.assertEqual(r_hbm_no_de["limiting_level"], "level4_hbm")
        self.assertEqual(r_hbm_with_de["limiting_level"], "level4_hbm")
        self.assertGreater(
            r_hbm_with_de["attained_tflops_or_tops"],
            1.40 * r_hbm_no_de["attained_tflops_or_tops"],
        )

        # 6. Level 5 UCIe D2D-bound on dual-die when cross-die traffic spikes
        t_ucie = cmp_mod.HierarchicalTraffic(
            flops=1e13, tmem_bytes=1e9, l1_lmem_bytes=1e9, l2_slc_bytes=1e9, hbm_bytes=1e9, ucie_d2d_bytes=5e12
        )
        r_ucie = cmp_mod.evaluate_hierarchical_roofline(self.b2_dual, "fp8_e4m3", t_ucie)
        self.assertEqual(r_ucie["limiting_level"], "level5_ucie_d2d")
        # Single-die b1 has no UCIe D2D fabric -> zero D2D ceiling if ucie traffic demanded
        r_b1_ucie = cmp_mod.evaluate_hierarchical_roofline(self.b1, "fp8_e4m3", t_ucie)
        self.assertEqual(r_b1_ucie["attained_tflops_or_tops"], 0.0)

        # 7. Level 6 PCIe Gen6 host offload bottleneck
        t_pcie = cmp_mod.HierarchicalTraffic(
            flops=1e13, tmem_bytes=1e9, l1_lmem_bytes=1e9, l2_slc_bytes=1e9, hbm_bytes=1e9, pcie_host_bytes=1e12
        )
        r_pcie = cmp_mod.evaluate_hierarchical_roofline(self.b2, "fp8_e4m3", t_pcie)
        self.assertEqual(r_pcie["limiting_level"], "level6_pcie_host")


class WorkloadAndWaveQuantizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        cls.b2_dual = cmp_mod.analyze_aigpu_profile("aigpu-b2-dual")
        cls.b1 = cmp_mod.analyze_aigpu_profile("aigpu-b1")
        cls.h200 = cmp_mod.analyze_competitor_baseline("nvidia-h200-sxm")
        cls.b200_2d = cmp_mod.analyze_competitor_baseline("nvidia-b200-2die")

    def test_llama3_prefill_vs_decode_regime_transition(self):
        for model_id in ("llama3-8b", "llama3-70b", "llama3-405b"):
            with self.subTest(model=model_id):
                prefill = cmp_mod.evaluate_workload_on_target(
                    self.b2, model_id, regime="prefill", tokens_or_batch=4096, fmt_key="fp8_e4m3"
                )
                decode_b1 = cmp_mod.evaluate_workload_on_target(
                    self.b2, model_id, regime="decode", tokens_or_batch=1, fmt_key="fp8_e4m3"
                )
                decode_b128 = cmp_mod.evaluate_workload_on_target(
                    self.b2, model_id, regime="decode", tokens_or_batch=128, fmt_key="fp8_e4m3"
                )
                self.assertEqual(prefill["limiting_level"], "compute")
                self.assertEqual(decode_b1["limiting_level"], "level4_hbm")
                self.assertGreater(prefill["effective_hbm_ai"], decode_b1["effective_hbm_ai"] * 100.0)
                self.assertGreater(decode_b128["tokens_per_sec"], decode_b1["tokens_per_sec"] * 10.0)

    def test_deepseek_v3_moe_mla_and_dual_die_alltoall_overhead(self):
        ds_single = cmp_mod.evaluate_workload_on_target(
            self.b2, "deepseek-v3", regime="decode", tokens_or_batch=32, fmt_key="fp8_e4m3"
        )
        ds_dual_low_split = cmp_mod.evaluate_workload_on_target(
            self.b2_dual,
            "deepseek-v3",
            regime="decode",
            tokens_or_batch=32,
            fmt_key="fp8_e4m3",
            remote_die_split_ratio=0.0,
        )
        ds_dual_high_split = cmp_mod.evaluate_workload_on_target(
            self.b2_dual,
            "deepseek-v3",
            regime="decode",
            tokens_or_batch=32,
            fmt_key="fp8_e4m3",
            remote_die_split_ratio=1.0,
        )
        # Dual-die includes AllReduce + MoE AllToAll + remote split traffic over UCIe D2D
        self.assertEqual(ds_single["ucie_d2d_bytes"], 0.0)
        self.assertGreater(ds_dual_low_split["ucie_d2d_bytes"], 0.0)
        self.assertGreater(ds_dual_high_split["ucie_d2d_bytes"], ds_dual_low_split["ucie_d2d_bytes"])
        # MLA compressed KV cache at batch=32, ctx=4096 is tiny (< 5 GiB) compared to standard GQA
        self.assertLess(ds_single["kv_cache_gib"], 5.0)
        # Dual-die outperforms single-die on decode throughput
        self.assertGreater(ds_dual_low_split["tokens_per_sec"], ds_single["tokens_per_sec"] * 1.5)

    def test_gemm_wave_quantization_edge_cases_and_tmem_overlap(self):
        # Perfectly divisible large GEMM achieves much higher wave efficiency than tiny tail-wave GEMM
        tile = cmp_mod.GemmTileSpec(tile_m=128, tile_n=128, tile_k=64, stages=3)
        full_wave = cmp_mod.evaluate_gemm_wave_quantization(
            self.b2, m_dim=4096, n_dim=4096, k_dim=4096, fmt_key="fp8_e4m3", tile=tile
        )
        # 128 cores * 1 CTA/core (or multiple) -> add +1 CTA tail wave penalty
        tail_wave = cmp_mod.evaluate_gemm_wave_quantization(
            self.b2, m_dim=129, n_dim=128, k_dim=4096, fmt_key="fp8_e4m3", tile=tile
        )
        self.assertGreater(full_wave["wave_quantization_efficiency"], tail_wave["wave_quantization_efficiency"])
        self.assertGreater(full_wave["tile_padding_efficiency"], tail_wave["tile_padding_efficiency"])
        self.assertGreater(full_wave["attained_tflops_or_tops"], tail_wave["attained_tflops_or_tops"])
        # TMEM improves overlap efficiency vs no-TMEM baseline
        b1_tile_eval = cmp_mod.evaluate_gemm_wave_quantization(
            self.b1, m_dim=2048, n_dim=2048, k_dim=512, fmt_key="fp8_e4m3", tile=tile
        )
        b2_tile_eval = cmp_mod.evaluate_gemm_wave_quantization(
            self.b2, m_dim=2048, n_dim=2048, k_dim=512, fmt_key="fp8_e4m3", tile=tile
        )
        self.assertGreater(b2_tile_eval["tmem_overlap_efficiency"], b1_tile_eval["tmem_overlap_efficiency"])

    def test_sensitivity_sweeps_monotonicity(self):
        sweeps = cmp_mod.run_sensitivity_sweeps()

        clk_pts = [row["prefill_tokens_per_sec"] for row in sweeps["clock_frequency_sweep"]]
        self.assertEqual(clk_pts, sorted(clk_pts))
        self.assertGreater(clk_pts[-1], clk_pts[0])

        hbm_pts = [row["decode_tokens_per_sec"] for row in sweeps["hbm_bandwidth_sweep"]]
        self.assertEqual(hbm_pts, sorted(hbm_pts))
        self.assertGreater(hbm_pts[-1], hbm_pts[0])

        ucie_bytes = [row["ucie_d2d_gb"] for row in sweeps["ucie_split_ratio_sweep"]]
        ucie_tps = [row["tokens_per_sec"] for row in sweeps["ucie_split_ratio_sweep"]]
        ucie_lat = [row["step_latency_ms"] for row in sweeps["ucie_split_ratio_sweep"]]
        self.assertEqual(ucie_bytes, sorted(ucie_bytes))
        self.assertGreater(ucie_bytes[-1], ucie_bytes[0])
        for idx in range(1, len(ucie_tps)):
            self.assertLess(ucie_tps[idx], ucie_tps[idx - 1])
            self.assertGreater(ucie_lat[idx], ucie_lat[idx - 1])

        sp_peaks = [row["effective_peak_tflops"] for row in sweeps["sparsity_utilization_sweep"]]
        sp_pts = [row["prefill_attained_tflops"] for row in sweeps["sparsity_utilization_sweep"]]
        self.assertEqual(sp_peaks, sorted(sp_peaks))
        self.assertEqual(sp_pts, sorted(sp_pts))
        self.assertAlmostEqual(sp_peaks[-1] / sp_peaks[0], 2.0, places=4)
        self.assertGreater(sp_pts[-1], sp_pts[0])

        kv_mem = [row["kv_cache_gib"] for row in sweeps["kv_quantization_sweep"]]
        kv_tps = [row["decode_tokens_per_sec"] for row in sweeps["kv_quantization_sweep"]]
        self.assertGreater(kv_mem[0], kv_mem[1])
        self.assertGreater(kv_mem[1], kv_mem[2])
        self.assertGreater(kv_tps[2], kv_tps[0])

    def test_dual_die_speedup_strictly_below_2x_across_llm_and_gemm(self):
        for wl_id in ("llama3-8b", "llama3-70b", "deepseek-v3"):
            for regime, val in (("prefill", 4096), ("decode", 1), ("decode", 32), ("decode", 128)):
                with self.subTest(workload=wl_id, regime=regime, val=val):
                    r1 = cmp_mod.evaluate_workload_on_target(
                        self.b2, wl_id, regime=regime, tokens_or_batch=val, fmt_key="fp8_e4m3"
                    )
                    r2 = cmp_mod.evaluate_workload_on_target(
                        self.b2_dual, wl_id, regime=regime, tokens_or_batch=val, fmt_key="fp8_e4m3"
                    )
                    speedup = r2["tokens_per_sec"] / r1["tokens_per_sec"]
                    self.assertGreater(speedup, 1.70)
                    self.assertLess(speedup, 2.0)

        for fmt_key in ("fp16", "fp8_e4m3", "nvfp4"):
            with self.subTest(gemm_fmt=fmt_key):
                g1 = cmp_mod.evaluate_gemm_wave_quantization(
                    self.b2, m_dim=4096, n_dim=4096, k_dim=4096, fmt_key=fmt_key
                )
                g2 = cmp_mod.evaluate_gemm_wave_quantization(
                    self.b2_dual, m_dim=4096, n_dim=4096, k_dim=4096, fmt_key=fmt_key
                )
                gemm_speedup = g2["attained_tflops_or_tops"] / g1["attained_tflops_or_tops"]
                self.assertGreater(gemm_speedup, 1.70)
                self.assertLess(gemm_speedup, 2.0)


class FormatAndWorkloadCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        cls.b2_dual = cmp_mod.analyze_aigpu_profile("aigpu-b2-dual")
        cls.b2_tile = cmp_mod.analyze_aigpu_profile("aigpu-b2-tile")
        cls.b1 = cmp_mod.analyze_aigpu_profile("aigpu-b1")
        cls.b1_tile = cmp_mod.analyze_aigpu_profile("aigpu-b1-tile")
        cls.b200_1d = cmp_mod.analyze_competitor_baseline("nvidia-b200-1die")
        cls.b200_2d = cmp_mod.analyze_competitor_baseline("nvidia-b200-2die")
        cls.h200 = cmp_mod.analyze_competitor_baseline("nvidia-h200-sxm")
        cls.h100 = cmp_mod.analyze_competitor_baseline("nvidia-h100-sxm5")
        cls.mi300x = cmp_mod.analyze_competitor_baseline("amd-mi300x")
        cls.rtx5080 = cmp_mod.analyze_competitor_baseline("nvidia-rtx5080")

    def test_all_eleven_formats_and_aliases(self):
        expected_aliases = {
            "fp16_bf16": "fp16",
            "fp8": "fp8_e4m3",
            "mxfp6": "mxfp6_e2m3",
            "fp4": "nvfp4",
        }
        for alias, canon in expected_aliases.items():
            self.assertEqual(cmp_mod.canonical_format_key(alias), canon)

        with self.assertRaises(ValueError):
            cmp_mod.canonical_format_key("fp2_invalid")

        expected_b2_dense = {
            "tf32": 576.0,
            "fp16": 1152.0,
            "bf16": 1152.0,
            "fp8_e4m3": 2304.0,
            "fp8_e5m2": 2304.0,
            "mxfp8": 2304.0,
            "mxfp6_e2m3": 2304.0,
            "mxfp6_e3m2": 2304.0,
            "mxfp4": 4608.0,
            "nvfp4": 4608.0,
            "int8": 2304.0,
        }
        for fkey, exp_dense in expected_b2_dense.items():
            with self.subTest(fmt=fkey):
                b2_fmt = self.b2["tensor_formats"][fkey]
                dual_fmt = self.b2_dual["tensor_formats"][fkey]
                tile_fmt = self.b2_tile["tensor_formats"][fkey]
                self.assertTrue(b2_fmt["supported"])
                self.assertTrue(b2_fmt["sparse_2_4_supported"])
                self.assertAlmostEqual(b2_fmt["dense_peak"], exp_dense, places=6)
                self.assertAlmostEqual(b2_fmt["sparse_2_4_peak"], 2.0 * exp_dense, places=6)
                self.assertAlmostEqual(dual_fmt["dense_peak"], 2.0 * exp_dense, places=6)
                self.assertAlmostEqual(
                    tile_fmt["tfrv2_scaled_2ghz_dense_peak"], exp_dense / 64.0, places=6
                )
                # Ridge invariants across HBM, L2, and TMEM
                self.assertGreater(
                    b2_fmt["dense_ridge_hbm_flop_per_byte"],
                    b2_fmt["dense_ridge_l2_flop_per_byte"],
                )
                self.assertGreater(
                    b2_fmt["dense_ridge_l2_flop_per_byte"],
                    b2_fmt["dense_ridge_tmem_flop_per_byte"],
                )

    def test_effective_bytes_per_element_accounts_for_microscaling_metadata(self):
        self.assertAlmostEqual(cmp_mod.FORMAT_SPECS["fp16"].effective_bytes_per_element, 2.0, places=6)
        self.assertAlmostEqual(cmp_mod.FORMAT_SPECS["fp8_e4m3"].effective_bytes_per_element, 1.0, places=6)
        self.assertAlmostEqual(
            cmp_mod.FORMAT_SPECS["mxfp8"].effective_bytes_per_element, 1.0 + (1.0 / 32.0), places=6
        )
        self.assertAlmostEqual(
            cmp_mod.FORMAT_SPECS["mxfp6_e2m3"].effective_bytes_per_element, 0.75 + (1.0 / 32.0), places=6
        )
        self.assertAlmostEqual(
            cmp_mod.FORMAT_SPECS["mxfp4"].effective_bytes_per_element, 0.5 + (1.0 / 32.0), places=6
        )
        self.assertAlmostEqual(
            cmp_mod.FORMAT_SPECS["nvfp4"].effective_bytes_per_element, 0.5 + (1.0 / 16.0), places=6
        )

    def test_competitor_format_support_boundaries(self):
        # Hopper H100/H200 & CDNA3 MI300X do not support FP4 or MXFP6
        for legacy_comp in (self.h100, self.h200, self.mi300x):
            self.assertTrue(legacy_comp["tensor_formats"]["fp16"]["supported"])
            self.assertTrue(legacy_comp["tensor_formats"]["fp8_e4m3"]["supported"])
            self.assertFalse(legacy_comp["tensor_formats"]["nvfp4"]["supported"])
            self.assertFalse(legacy_comp["tensor_formats"]["mxfp4"]["supported"])
            self.assertFalse(legacy_comp["tensor_formats"]["mxfp6_e2m3"]["supported"])

        # Blackwell B200 & RTX 5080 support MXFP6, MXFP4, NVFP4
        for bw_comp in (self.b200_1d, self.b200_2d, self.rtx5080):
            self.assertTrue(bw_comp["tensor_formats"]["nvfp4"]["supported"])
            self.assertTrue(bw_comp["tensor_formats"]["mxfp4"]["supported"])
            self.assertTrue(bw_comp["tensor_formats"]["mxfp6_e2m3"]["supported"])

        # MI300X carries 256 MiB L3 Infinity Cache
        l3_info = self.mi300x["hierarchy"]["levels"]["level3_l2_slc"]
        self.assertEqual(l3_info["l3_capacity_bytes"], 256 * 1024 * 1024)
        self.assertEqual(l3_info["effective_llc_bytes"], 256 * 1024 * 1024)

        # Unsupported format workload evaluation degrades cleanly without crashing
        res = cmp_mod.evaluate_workload_on_target(
            self.h100, "llama3-70b", regime="decode", tokens_or_batch=32, fmt_key="nvfp4"
        )
        self.assertFalse(res["supported"])
        self.assertEqual(res["limiting_level"], "unsupported")
        self.assertIsNone(res["attained_tflops_or_tops"])
        self.assertIsNone(res["tokens_per_sec"])

    def test_workload_parameter_counts_and_hbm_capacity_fit(self):
        self.assertGreater(cmp_mod.LLM_WORKLOADS["llama3-8b"].total_params_billions, 7.0)
        self.assertLess(cmp_mod.LLM_WORKLOADS["llama3-8b"].total_params_billions, 9.0)
        self.assertGreater(cmp_mod.LLM_WORKLOADS["llama3-70b"].total_params_billions, 65.0)
        self.assertLess(cmp_mod.LLM_WORKLOADS["llama3-70b"].total_params_billions, 75.0)
        self.assertGreater(cmp_mod.LLM_WORKLOADS["llama3-405b"].total_params_billions, 390.0)
        self.assertGreater(cmp_mod.LLM_WORKLOADS["deepseek-v3"].total_params_billions, 600.0)

        # Llama-3 70B FP8 fits in 96 GiB single-die aigpu-b2 HBM, whereas 405B FP16 needs dual-die/multi-GPU
        ev_70b_fp8 = cmp_mod.evaluate_workload_on_target(
            self.b2, "llama3-70b", regime="decode", tokens_or_batch=16, fmt_key="fp8_e4m3"
        )
        ev_405b_fp16 = cmp_mod.evaluate_workload_on_target(
            self.b2, "llama3-405b", regime="decode", tokens_or_batch=16, fmt_key="fp16"
        )
        self.assertTrue(ev_70b_fp8["fits_single_device_hbm"])
        self.assertFalse(ev_405b_fp16["fits_single_device_hbm"])

    def test_all_prefill_lengths_and_decode_batches_monotone(self):
        for wl_id in ("llama3-8b", "llama3-70b", "deepseek-v3"):
            prefill_lat = []
            for seq_len in cmp_mod.PREFILL_SEQ_LENGTHS:
                ev = cmp_mod.evaluate_workload_on_target(
                    self.b2, wl_id, regime="prefill", tokens_or_batch=seq_len, fmt_key="fp8_e4m3"
                )
                self.assertGreater(ev["tokens_per_sec"], 0.0)
                prefill_lat.append(ev["step_latency_ms"])
            self.assertEqual(prefill_lat, sorted(prefill_lat))

            decode_tps = []
            for batch in cmp_mod.DECODE_BATCH_SIZES:
                ev = cmp_mod.evaluate_workload_on_target(
                    self.b2, wl_id, regime="decode", tokens_or_batch=batch, fmt_key="fp8_e4m3"
                )
                self.assertGreater(ev["tokens_per_sec"], 0.0)
                decode_tps.append(ev["tokens_per_sec"])
            self.assertEqual(decode_tps, sorted(decode_tps))
            self.assertGreater(decode_tps[-1], decode_tps[0])

    def test_deepseek_moe_active_experts_scale_with_batch(self):
        ds = cmp_mod.LLM_WORKLOADS["deepseek-v3"]
        t_b1 = cmp_mod.compute_workload_traffic(ds, regime="decode", tokens_or_batch=1, fmt_key="fp8_e4m3")
        t_b32 = cmp_mod.compute_workload_traffic(ds, regime="decode", tokens_or_batch=32, fmt_key="fp8_e4m3")
        t_b256 = cmp_mod.compute_workload_traffic(ds, regime="decode", tokens_or_batch=256, fmt_key="fp8_e4m3")

        # At batch=1, active experts = top_k (8) + shared (1) = 9
        self.assertAlmostEqual(t_b1["active_experts_per_layer"], 9.0, places=2)
        self.assertGreater(t_b32["active_experts_per_layer"], t_b1["active_experts_per_layer"])
        self.assertGreater(t_b256["active_experts_per_layer"], t_b32["active_experts_per_layer"])
        self.assertLessEqual(t_b256["active_experts_per_layer"], 257.0)

    def test_input_validation_errors(self):
        with self.assertRaises(ValueError):
            cmp_mod.analyze_aigpu_profile("aigpu-b2", sparsity_utilization=1.5)
        with self.assertRaises(ValueError):
            cmp_mod.analyze_aigpu_profile("aigpu-b2", clock_override_mhz=-100.0)
        with self.assertRaises(ValueError):
            cmp_mod.analyze_aigpu_profile("aigpu-b2", hbm_bw_override_gbs=0.0)
        with self.assertRaises(ValueError):
            cmp_mod.analyze_competitor_baseline("unknown-gpu")
        with self.assertRaises(ValueError):
            cmp_mod.analyze_competitor_baseline("nvidia-b200-1die", sparsity_utilization=-0.1)
        with self.assertRaises(ValueError):
            cmp_mod.compute_workload_traffic(
                cmp_mod.LLM_WORKLOADS["llama3-8b"], regime="train", tokens_or_batch=32, fmt_key="fp16"
            )
        with self.assertRaises(ValueError):
            cmp_mod.compute_workload_traffic(
                cmp_mod.LLM_WORKLOADS["llama3-8b"], regime="decode", tokens_or_batch=0, fmt_key="fp16"
            )
        with self.assertRaises(ValueError):
            cmp_mod.evaluate_workload_on_target(
                self.b2, "nonexistent-model", regime="decode", tokens_or_batch=1, fmt_key="fp16"
            )
        with self.assertRaises(ValueError):
            cmp_mod.build_b2_comparison_report(selected_workloads=("bad-model",))
        with self.assertRaises(ValueError):
            cmp_mod.build_b2_comparison_report(selected_regimes=("training",))

        # GEMM invalid dimensions & tile parameters raise ValueError (no ZeroDivisionError)
        for bad_kwargs in (
            {"m_dim": 0, "n_dim": 128, "k_dim": 128},
            {"m_dim": -128, "n_dim": 128, "k_dim": 128},
            {"m_dim": 128, "n_dim": 0, "k_dim": 128},
            {"m_dim": 128, "n_dim": -64, "k_dim": 128},
            {"m_dim": 128, "n_dim": 128, "k_dim": 0},
            {"m_dim": 128, "n_dim": 128, "k_dim": -64},
            {"m_dim": True, "n_dim": 128, "k_dim": 128},
        ):
            with self.assertRaises(ValueError):
                cmp_mod.evaluate_gemm_wave_quantization(self.b2, fmt_key="fp8_e4m3", **bad_kwargs)

        with self.assertRaises(ValueError):
            cmp_mod.evaluate_gemm_wave_quantization(
                self.b2,
                m_dim=128,
                n_dim=128,
                k_dim=128,
                fmt_key="fp8_e4m3",
                tile=cmp_mod.GemmTileSpec(tile_m=0, tile_n=64, tile_k=32),
            )

        # Workload traffic parameter validation
        wl = cmp_mod.LLM_WORKLOADS["llama3-70b"]
        for bad_wt in (
            {"tokens_or_batch": -1},
            {"decode_context_len": 0},
            {"decode_context_len": -128},
            {"die_count": 0},
            {"die_count": -2},
            {"remote_die_split_ratio": -0.1},
            {"remote_die_split_ratio": 1.1},
            {"remote_die_split_ratio": float("nan")},
            {"remote_die_split_ratio": float("inf")},
            {"l2_capacity_bytes": -1},
        ):
            with self.assertRaises(ValueError):
                cmp_mod.compute_workload_traffic(
                    wl, regime="decode", fmt_key="fp8_e4m3", **{"tokens_or_batch": 1, **bad_wt}
                )

        # HierarchicalTraffic numeric validation
        for bad_tr in (
            cmp_mod.HierarchicalTraffic(flops=0.0, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=-1e9, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=float("nan"), tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=float("inf"), tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=-1.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=0.0, l1_lmem_bytes=float("nan"), l2_slc_bytes=0.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=-10.0, hbm_bytes=1024.0),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=-1024.0),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0, ucie_d2d_bytes=-1.0),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0, pcie_host_bytes=float("inf")),
            cmp_mod.HierarchicalTraffic(flops=1e12, tmem_bytes=0.0, l1_lmem_bytes=0.0, l2_slc_bytes=0.0, hbm_bytes=1024.0, compressed_weight_bytes=-5.0),
        ):
            with self.assertRaises(ValueError):
                cmp_mod.evaluate_hierarchical_roofline(self.b2, "fp8_e4m3", bad_tr)

    def test_speedup_tables_and_b2_vs_b1_scaling(self):
        report = cmp_mod.build_b2_comparison_report(
            selected_workloads=("llama3-70b", "deepseek-v3"),
            selected_formats=("fp16", "fp8_e4m3", "nvfp4"),
            include_sweeps=False,
        )
        rows = {
            (r["target"], r["baseline"]): r
            for r in report["comparative_speedups"]["pairwise_speedups"]
        }
        b2_vs_b1 = rows[("aigpu-b2", "aigpu-b1")]
        self.assertAlmostEqual(b2_vs_b1["fp16_dense_peak_ratio"], 1152.0 / 131.072, places=3)
        self.assertAlmostEqual(b2_vs_b1["hbm_bandwidth_ratio"], 1.0, places=3)
        self.assertGreater(b2_vs_b1["llama3_70b_prefill_4k_fp8_speedup"], 3.0)

        b2_vs_b200 = rows[("aigpu-b2", "nvidia-b200-1die")]
        self.assertGreater(b2_vs_b200["fp16_dense_peak_ratio"], 1.0)
        self.assertAlmostEqual(b2_vs_b200["hbm_bandwidth_ratio"], 1.0, places=3)

        dual_vs_h200 = rows[("aigpu-b2-dual", "nvidia-h200-sxm")]
        self.assertGreater(dual_vs_h200["fp8_dense_peak_ratio"], 2.0)
        self.assertGreater(dual_vs_h200["llama3_70b_decode_b32_fp8_speedup"], 2.0)


class CompetitorHonestyAndCliTests(unittest.TestCase):
    def test_competitor_baselines_strict_separation_and_honesty_guard(self):
        for cid in cmp_mod.COMPETITOR_IDS:
            rec = cmp_mod.analyze_competitor_baseline(cid)
            cmp_mod.validate_honesty_record(rec)
            self.assertEqual(rec["source"], "published_vendor_datasheet")
            self.assertTrue(rec["is_published_reference"])
            self.assertFalse(rec["locally_measured"])

        # Honesty guard must reject any forbidden physical or foundry signoff claim
        valid = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        for bad_level in ("silicon_measured", "fpga_measured", "rtl_verified", "simulated", "foundry_signoff"):
            forged = copy.deepcopy(valid)
            forged["evidence_level"] = bad_level
            with self.assertRaises(ValueError):
                cmp_mod.validate_honesty_record(forged)

        for flag in ("silicon_measured", "fpga_measured", "foundry_signoff"):
            forged_flag = copy.deepcopy(valid)
            forged_flag[flag] = True
            with self.assertRaises(ValueError):
                cmp_mod.validate_honesty_record(forged_flag)

        forged_schema = copy.deepcopy(cmp_mod.build_b2_comparison_report(
            selected_workloads=("llama3-8b",), selected_formats=("fp16",), include_sweeps=False
        ))
        forged_schema["schema_version"] = 99
        with self.assertRaises(ValueError):
            cmp_mod.validate_honesty_record(forged_schema)

    def test_cli_json_and_markdown_modes_and_anti_bloat(self):
        # Verify production module clears b2_program_tracker anti-bloat check cleanly
        bloat = tracker.check_file_anti_bloat(ROOT / "ci/project/b2_roofline_compare.py")
        self.assertEqual(bloat, [])

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = cmp_mod.main(["--markdown", "--workload", "llama3-70b", "--regime", "decode"])
        self.assertEqual(rc, 0)
        md = stdout.getvalue()
        self.assertIn("aigpu-b2-dual", md)
        self.assertIn("nvidia-b200-2die", md)
        self.assertIn("silicon_measured=False", md)
        self.assertIn("Six-Level Hierarchical Memory & Fabric Bandwidths", md)
        self.assertIn("Comparative Speedup Summary", md)

        with tempfile.TemporaryDirectory(prefix="b2-roofline-cli-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            _write_temp_profiles_dir(tmp_path, include_b1=True)
            out_json = tmp_path / "b2_roofline.json"
            out_md = tmp_path / "b2_roofline.md"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "ci/project/b2_roofline_compare.py"),
                    "--profiles-dir",
                    str(tmp_path),
                    "--format",
                    "fp16,fp8_e4m3,nvfp4",
                    "--workload",
                    "llama3-70b,deepseek-v3",
                    "--regime",
                    "both",
                    "--sweep",
                    "--json",
                    "--output",
                    str(out_json),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.stdout, "")
            parsed = json.loads(out_json.read_text(encoding="utf-8"))
            cmp_mod.validate_honesty_record(parsed)
            self.assertEqual(set(parsed["targets"]), set(cmp_mod.ALL_AIGPU_TARGETS) | set(cmp_mod.COMPETITOR_IDS))
            self.assertIn("sensitivity_sweeps", parsed)
            self.assertIn("comparative_speedups", parsed)
            self.assertIn("gemm_wave_quantization", parsed)

            proc_md = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "ci/project/b2_roofline_compare.py"),
                    "--profiles-dir",
                    str(tmp_path),
                    "--strict-profiles",
                    "--format",
                    "fp8_e4m3",
                    "--workload",
                    "llama3-70b",
                    "--regime",
                    "prefill",
                    "--markdown",
                    "--output",
                    str(out_md),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_md.stdout, "")
            md_text = out_md.read_text(encoding="utf-8")
            self.assertIn("Modeled (profiles_dir)", md_text)
            self.assertIn("Published Ref", md_text)

    def test_live_profiles_strict_resolution_and_gemm_wave_matrix(self):
        # Verify live profiles/*.json resolve cleanly in strict mode when present
        live_b2_present = all((PROFILES_DIR / f"{p}.json").is_file() for p in cmp_mod.AIGPU_B2_TARGETS)
        if live_b2_present:
            report_live = cmp_mod.build_b2_comparison_report(
                profiles_dir=PROFILES_DIR,
                allow_builtin_fallback=False,
                selected_workloads=("llama3-8b", "llama3-70b", "deepseek-v3"),
                selected_formats=("fp16", "fp8_e4m3", "mxfp6_e2m3", "nvfp4"),
                include_sweeps=False,
            )
            cmp_mod.validate_honesty_record(report_live)
            for pname in cmp_mod.ALL_AIGPU_TARGETS:
                self.assertEqual(report_live["targets"][pname]["profile_source"], "profiles_dir")

            b2_live = report_live["targets"]["aigpu-b2"]
            b2_dual_live = report_live["targets"]["aigpu-b2-dual"]
            b2_tile_live = report_live["targets"]["aigpu-b2-tile"]
            self.assertEqual(b2_live["topology"]["l2_bytes_config"], 134217728)
            self.assertEqual(b2_dual_live["topology"]["l2_bytes_config"], 268435456)
            self.assertEqual(b2_tile_live["topology"]["l2_bytes_config"], 262144)
            self.assertEqual(
                b2_dual_live["hierarchy"]["levels"]["level3_l2_slc"]["effective_llc_bytes"],
                268435456,
            )

        # Verify GEMM wave quantization matrix across small/medium/large shapes and formats
        b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        b2_dual = cmp_mod.analyze_aigpu_profile("aigpu-b2-dual")
        shapes = (
            (256, 28672, 8192),
            (1024, 14336, 4096),
            (4096, 4096, 4096),
            (8192, 8192, 8192),
        )
        for fkey in ("fp16", "fp8_e4m3", "nvfp4"):
            prev_b2_att = 0.0
            for m_dim, n_dim, k_dim in shapes:
                res_b2 = cmp_mod.evaluate_gemm_wave_quantization(
                    b2, m_dim=m_dim, n_dim=n_dim, k_dim=k_dim, fmt_key=fkey
                )
                res_dual = cmp_mod.evaluate_gemm_wave_quantization(
                    b2_dual, m_dim=m_dim, n_dim=n_dim, k_dim=k_dim, fmt_key=fkey
                )
                res_b2_sparse = cmp_mod.evaluate_gemm_wave_quantization(
                    b2, m_dim=m_dim, n_dim=n_dim, k_dim=k_dim, fmt_key=fkey, use_sparse=True
                )
                self.assertTrue(res_b2["supported"])
                self.assertGreater(res_b2["attained_tflops_or_tops"], 0.0)
                if res_b2["limiting_level"] == "compute":
                    self.assertGreater(res_b2_sparse["attained_tflops_or_tops"], res_b2["attained_tflops_or_tops"])
                else:
                    self.assertGreaterEqual(res_b2_sparse["attained_tflops_or_tops"], res_b2["attained_tflops_or_tops"])
                fixed_b2 = cmp_mod.evaluate_gemm_wave_quantization(
                    b2, m_dim=m_dim, n_dim=n_dim, k_dim=k_dim, fmt_key=fkey,
                    tile=cmp_mod.DEFAULT_GEMM_TILES[1],
                )
                fixed_dual = cmp_mod.evaluate_gemm_wave_quantization(
                    b2_dual, m_dim=m_dim, n_dim=n_dim, k_dim=k_dim, fmt_key=fkey,
                    tile=cmp_mod.DEFAULT_GEMM_TILES[1],
                )
                self.assertEqual(fixed_dual["concurrent_cta_slots"], 2 * fixed_b2["concurrent_cta_slots"])
                self.assertGreaterEqual(res_b2["combined_tile_efficiency"], 0.0)
                self.assertLessEqual(res_b2["combined_tile_efficiency"], 1.0)
                self.assertGreaterEqual(res_b2["wave_quantization_efficiency"], 0.0)
                self.assertLessEqual(res_b2["wave_quantization_efficiency"], 1.0)
                self.assertGreater(res_b2["attained_tflops_or_tops"], prev_b2_att * 0.5)
                prev_b2_att = res_b2["attained_tflops_or_tops"]

        # Oversized tile exceeds TMEM/LMEM capacity -> triggers fit_penalty (<1.0) vs fitted tile
        oversized_tile = cmp_mod.GemmTileSpec(tile_m=512, tile_n=512, tile_k=128, stages=4)
        fitted_tile = cmp_mod.GemmTileSpec(tile_m=128, tile_n=128, tile_k=64, stages=3)
        res_over = cmp_mod.evaluate_gemm_wave_quantization(
            b2, m_dim=4096, n_dim=4096, k_dim=4096, fmt_key="fp8_e4m3", tile=oversized_tile
        )
        res_fit = cmp_mod.evaluate_gemm_wave_quantization(
            b2, m_dim=4096, n_dim=4096, k_dim=4096, fmt_key="fp8_e4m3", tile=fitted_tile
        )
        self.assertLess(res_over["combined_tile_efficiency"], res_fit["combined_tile_efficiency"])

        # Verify unsupported GEMM evaluation returns supported=False cleanly
        h100 = cmp_mod.analyze_competitor_baseline("nvidia-h100-sxm5")
        unsup_gemm = cmp_mod.evaluate_gemm_wave_quantization(
            h100, m_dim=4096, n_dim=4096, k_dim=4096, fmt_key="nvfp4"
        )
        self.assertFalse(unsup_gemm["supported"])
        self.assertIsNone(unsup_gemm["attained_tflops_or_tops"])

        # Verify CLI format filtering and single-target output
        stdout_single = io.StringIO()
        with redirect_stdout(stdout_single):
            rc = cmp_mod.main([
                "--targets", "aigpu-b2",
                "--competitors", "nvidia-b200-1die",
                "--format", "nvfp4",
                "--workload", "deepseek-v3",
                "--regime", "decode",
                "--json",
            ])
        self.assertEqual(rc, 0)
        single_payload = json.loads(stdout_single.getvalue())
        cmp_mod.validate_honesty_record(single_payload)
        self.assertEqual(single_payload["selected_formats"], ["nvfp4"])
        self.assertEqual(single_payload["selected_workloads"], ["deepseek-v3"])
        self.assertEqual(single_payload["selected_regimes"], ["decode"])
        self.assertEqual(set(single_payload["targets"]), {"aigpu-b2", "nvidia-b200-1die"})


class HierarchicalFormulaAndScalingTests(unittest.TestCase):
    def test_de_engine_disabled_vs_enabled_for_fp4_and_fp8_decode(self):
        b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        b1 = cmp_mod.analyze_aigpu_profile("aigpu-b1")
        wl = cmp_mod.LLM_WORKLOADS["llama3-70b"]
        wt_fp4 = cmp_mod.compute_workload_traffic(
            wl, regime="decode", tokens_or_batch=8, fmt_key="nvfp4", die_count=1
        )
        wt_fp16 = cmp_mod.compute_workload_traffic(
            wl, regime="decode", tokens_or_batch=8, fmt_key="fp16", die_count=1
        )
        # NVFP4 weight footprint is >3x smaller than FP16 despite 1B/16 scale factor
        self.assertLess(wt_fp4["total_weight_bytes"] * 3.0, wt_fp16["total_weight_bytes"])

        # DE engine improves effective HBM ceiling on b2 for compressed FP4/FP8 weights, not on b1
        r_b2_de = cmp_mod.evaluate_hierarchical_roofline(
            b2, "nvfp4", wt_fp4["traffic"], use_de_compression=True
        )
        r_b2_node = cmp_mod.evaluate_hierarchical_roofline(
            b2, "nvfp4", wt_fp4["traffic"], use_de_compression=False
        )
        r_b1_de = cmp_mod.evaluate_hierarchical_roofline(
            b1, "nvfp4", wt_fp4["traffic"], use_de_compression=True
        )
        r_b1_node = cmp_mod.evaluate_hierarchical_roofline(
            b1, "nvfp4", wt_fp4["traffic"], use_de_compression=False
        )
        self.assertGreater(r_b2_de["effective_hbm_ai"], r_b2_node["effective_hbm_ai"])
        self.assertGreater(r_b2_de["attained_tflops_or_tops"], r_b2_node["attained_tflops_or_tops"])
        self.assertAlmostEqual(r_b1_de["effective_hbm_ai"], r_b1_node["effective_hbm_ai"], places=6)

    def test_sustained_vs_peak_hbm_and_pcie_unidir_invariants(self):
        b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        lv = b2["hierarchy"]["levels"]
        self.assertLess(lv["level4_hbm"]["sustained_bandwidth_gbs"], lv["level4_hbm"]["peak_bandwidth_gbs"])
        self.assertAlmostEqual(
            lv["level6_pcie_de"]["pcie_unidirectional_gbs"],
            0.5 * lv["level6_pcie_de"]["pcie_bidirectional_gbs"],
            places=6,
        )
        self.assertAlmostEqual(
            lv["level5_ucie_d2d"]["unidirectional_gbs"],
            0.5 * lv["level5_ucie_d2d"]["bidirectional_gbs"],
            places=6,
        )

        # Peak HBM ceiling >= sustained HBM ceiling on HBM-limited decode
        wl = cmp_mod.LLM_WORKLOADS["llama3-70b"]
        wt = cmp_mod.compute_workload_traffic(wl, regime="decode", tokens_or_batch=4, fmt_key="fp16")
        r_sust = cmp_mod.evaluate_hierarchical_roofline(b2, "fp16", wt["traffic"], use_sustained_hbm=True)
        r_peak = cmp_mod.evaluate_hierarchical_roofline(b2, "fp16", wt["traffic"], use_sustained_hbm=False)
        self.assertEqual(r_sust["limiting_level"], "level4_hbm")
        self.assertEqual(r_peak["limiting_level"], "level4_hbm")
        self.assertGreater(r_peak["attained_tflops_or_tops"], r_sust["attained_tflops_or_tops"])

    def test_vortex_tcu_block_shape_validation(self):
        self.assertEqual(cmp_mod._vortex_tcu_block_shape(4), (2, 2, 2))
        self.assertEqual(cmp_mod._vortex_tcu_block_shape(8), (4, 2, 2))
        self.assertEqual(cmp_mod._vortex_tcu_block_shape(32), (8, 4, 4))
        for bad in (0, -4, 3, 6, 12):
            with self.assertRaises(ValueError):
                cmp_mod._vortex_tcu_block_shape(bad)

    def test_unsupported_format_hierarchical_eval_and_sparse_fallback(self):
        h100 = cmp_mod.analyze_competitor_baseline("nvidia-h100-sxm5")
        traffic = cmp_mod.HierarchicalTraffic(
            flops=1e14, tmem_bytes=1e11, l1_lmem_bytes=1e11, l2_slc_bytes=1e10, hbm_bytes=1e10
        )
        unsup = cmp_mod.evaluate_hierarchical_roofline(h100, "nvfp4", traffic)
        self.assertFalse(unsup["supported"])
        self.assertEqual(unsup["limiting_level"], "unsupported")
        self.assertIsNone(unsup["attained_tflops_or_tops"])

        # Dense vs sparse peak check on supported format
        dense_eval = cmp_mod.evaluate_hierarchical_roofline(h100, "fp16", traffic, use_sparse=False)
        sparse_eval = cmp_mod.evaluate_hierarchical_roofline(h100, "fp16", traffic, use_sparse=True)
        self.assertGreater(sparse_eval["compute_ceiling_tflops_or_tops"], dense_eval["compute_ceiling_tflops_or_tops"])

    def test_markdown_and_text_formatting_equivalence_and_honesty_banners(self):
        report = cmp_mod.build_b2_comparison_report(
            aigpu_targets=("aigpu-b2", "aigpu-b2-dual"),
            competitor_ids=("nvidia-b200-1die", "nvidia-b200-2die"),
            selected_workloads=("llama3-70b",),
            selected_formats=("fp16", "fp8_e4m3"),
            include_sweeps=False,
        )
        md = cmp_mod.format_report_markdown(report)
        txt = cmp_mod.format_report_text(report)
        self.assertEqual(md, txt)
        self.assertIn("fpga_measured=False", md)
        self.assertIn("foundry_signoff=False", md)
        self.assertIn("silicon_measured=False", md)
        self.assertIn("aigpu-b2", md)
        self.assertIn("nvidia-b200-2die", md)

    def test_de_engine_finite_ceiling_and_bottleneck_bounding(self):
        b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        traffic = cmp_mod.HierarchicalTraffic(
            flops=1e13,
            tmem_bytes=1e9,
            l1_lmem_bytes=1e9,
            l2_slc_bytes=1e9,
            hbm_bytes=1e12,
            compressed_weight_bytes=1e12,
            de_amplification=1.45,
        )
        r_de = cmp_mod.evaluate_hierarchical_roofline(b2, "fp8_e4m3", traffic, use_de_compression=True)
        self.assertIsNotNone(r_de["de_ceiling_tflops_or_tops"])
        self.assertTrue(math.isfinite(r_de["de_ceiling_tflops_or_tops"]))
        self.assertIn("level6_de_engine", r_de["tier_ceilings_tflops_or_tops"])

        # Throttle de_engine_max_gbs so DE throughput strictly bounds execution
        b2_slow_de = copy.deepcopy(b2)
        b2_slow_de["hierarchy"]["levels"]["level6_pcie_de"]["de_engine_max_gbs"] = 400.0
        r_slow_de = cmp_mod.evaluate_hierarchical_roofline(
            b2_slow_de, "fp8_e4m3", traffic, use_de_compression=True
        )
        self.assertEqual(r_slow_de["limiting_level"], "level6_de_engine")
        self.assertLess(r_slow_de["attained_tflops_or_tops"], r_de["attained_tflops_or_tops"])

    def test_fallback_profile_parity_and_tile_parameter_alignment(self):
        # Fallback payloads match live profiles/*.json chip/platform/reference blocks
        for pname in cmp_mod.AIGPU_B2_TARGETS:
            live_path = PROFILES_DIR / f"{pname}.json"
            if live_path.is_file():
                live = json.loads(live_path.read_text(encoding="utf-8"))
                fb = cmp_mod._b2_authoritative_profile_payload(pname)
                self.assertEqual(fb["chip"], live["chip"])
                self.assertEqual(fb["reference"], live["reference"])
                if "platform" in live:
                    self.assertEqual(fb["platform"], live["platform"])

        # Cross-module alignment for aigpu-b2, aigpu-b2-dual, aigpu-b2-tile, and MXFP6
        b2 = cmp_mod.analyze_aigpu_profile("aigpu-b2")
        b2_dual = cmp_mod.analyze_aigpu_profile("aigpu-b2-dual")
        b2_tile = cmp_mod.analyze_aigpu_profile("aigpu-b2-tile")

        self.assertEqual(b2["hierarchy"]["levels"]["level5_ucie_d2d"]["latency_ns"], 12.0)
        self.assertEqual(b2_dual["hierarchy"]["levels"]["level5_ucie_d2d"]["latency_ns"], 12.0)
        self.assertEqual(b2_tile["hierarchy"]["levels"]["level4_hbm"]["capacity_bytes"], 4 * (1 << 30))
        self.assertEqual(b2_tile["hierarchy"]["levels"]["level5_ucie_d2d"]["bidirectional_gbs"], 0.0)
        self.assertEqual(b2_tile["hierarchy"]["levels"]["level6_pcie_de"]["pcie_gen"], 6)
        self.assertEqual(b2_tile["hierarchy"]["levels"]["level6_pcie_de"]["pcie_lanes"], 4)
        self.assertIn("Gen6 x4", b2_tile["hierarchy"]["levels"]["level6_pcie_de"]["name"])

        for mxfp6_key in ("mxfp6_e2m3", "mxfp6_e3m2"):
            self.assertEqual(cmp_mod.FORMAT_SPECS[mxfp6_key].elements_per_word32, 4)
            self.assertEqual(cmp_mod.FORMAT_SPECS[mxfp6_key].tfrv2_multiplier_vs_fp16, 2.0)


if __name__ == "__main__":
    unittest.main()
