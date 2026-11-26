# SPDX-License-Identifier: Apache-2.0
"""Offline unit tests for ci/project/aigpu_ppa_model.py (ADR-006 PPA model)."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import aigpu_ppa_model as ppa_mod
import b1_roofline_compare as roofline_cmp


ROOT = Path(__file__).resolve().parents[2]


class AigpuPpaModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measured = ppa_mod.load_measured_presilicon_inputs()
        cls.reports = {
            node: ppa_mod.build_ppa_report(node_id=node)
            for node in ppa_mod.VALID_NODES
        }
        cls.roofline_report = roofline_cmp.build_comparison_report()

    def test_loads_real_repo_inputs_cleanly(self):
        sram_prof = self.measured["sram_manifest_profiles"]
        self.assertEqual(sram_prof["aigpu-b1-tile"]["total_bits"], 4328896)
        self.assertEqual(sram_prof["aigpu-b1"]["total_bits"], 841673728)
        self.assertEqual(
            sram_prof["aigpu-b1-tile"]["bits_1rw"] + sram_prof["aigpu-b1-tile"]["bits_1r1w"],
            sram_prof["aigpu-b1-tile"]["total_bits"],
        )
        self.assertEqual(
            sram_prof["aigpu-b1"]["bits_1rw"] + sram_prof["aigpu-b1"]["bits_1r1w"],
            sram_prof["aigpu-b1"]["total_bits"],
        )

        macros = self.measured["measured_asap7_macros"]
        self.assertAlmostEqual(
            macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_fmax_mhz"], 1079.53, places=2
        )
        self.assertAlmostEqual(
            macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_design_area_um2"], 348.0, places=2
        )
        self.assertAlmostEqual(
            macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_stdcell_area_um2"],
            793.5165,
            places=4,
        )
        self.assertAlmostEqual(
            macros["vx_asic_dft_top_asap7"]["synth_stdcell_area_um2"], 68.86134, places=5
        )
        self.assertAlmostEqual(
            macros["vx_asic_soc_top_asap7_fakeram7"]["synth_stdcell_area_um2"],
            1327.61106,
            places=4,
        )

    def test_honesty_contract_and_tamper_guards(self):
        for node, report in self.reports.items():
            with self.subTest(node=node):
                self.assertEqual(report["evidence_level"], "simulated")
                self.assertIs(report["silicon_measured"], False)
                self.assertIs(report["foundry_signoff"], False)
                self.assertEqual(report["model_type"], "parametric_presilicon_estimate")

                for target in report["aigpu_targets"].values():
                    self.assertEqual(target["evidence_level"], "simulated")
                    self.assertIs(target["silicon_measured"], False)
                    self.assertIs(target["foundry_signoff"], False)
                    self.assertEqual(
                        target["model_type"], "parametric_presilicon_estimate"
                    )
                    self.assertIs(target["is_published_reference"], False)

                for ref in report["published_reference_baselines"].values():
                    self.assertEqual(ref["evidence_level"], "simulated")
                    self.assertIs(ref["silicon_measured"], False)
                    self.assertIs(ref["foundry_signoff"], False)
                    self.assertEqual(
                        ref["model_type"], "parametric_presilicon_estimate"
                    )
                    self.assertIs(ref["is_published_reference"], True)
                    self.assertIs(ref["locally_measured"], False)

        # Verify tampering with honesty fields fails validation
        bad_silicon = copy.deepcopy(self.reports["n4p_est"])
        bad_silicon["silicon_measured"] = True
        with self.assertRaisesRegex(ValueError, "silicon_measured=False"):
            ppa_mod.validate_honesty_record(bad_silicon)

        bad_signoff = copy.deepcopy(self.reports["n4p_est"])
        bad_signoff["foundry_signoff"] = True
        with self.assertRaisesRegex(ValueError, "foundry_signoff=False"):
            ppa_mod.validate_honesty_record(bad_signoff)

        for bad_level in ("silicon_measured", "fpga_measured", "rtl_verified"):
            bad_ev = copy.deepcopy(self.reports["n4p_est"])
            bad_ev["evidence_level"] = bad_level
            with self.assertRaisesRegex(ValueError, "evidence_level"):
                ppa_mod.validate_honesty_record(bad_ev)

        bad_model = copy.deepcopy(self.reports["n4p_est"])
        bad_model["model_type"] = "foundry_signoff_tapeout"
        with self.assertRaisesRegex(ValueError, "model_type"):
            ppa_mod.validate_honesty_record(bad_model)

    def test_area_monotonicity_and_reticle_limits(self):
        for node, report in self.reports.items():
            with self.subTest(node=node):
                b1_area = report["aigpu_targets"]["aigpu-b1"]["area_breakdown"][
                    "total_die_area_mm2"
                ]
                tile_area = report["aigpu_targets"]["aigpu-b1-tile"]["area_breakdown"][
                    "total_die_area_mm2"
                ]
                self.assertGreater(b1_area, tile_area)
                self.assertGreater(tile_area, 0.0)

        b1_asap7 = self.reports["asap7"]["aigpu_targets"]["aigpu-b1"]["area_breakdown"][
            "total_die_area_mm2"
        ]
        b1_n4p = self.reports["n4p_est"]["aigpu_targets"]["aigpu-b1"]["area_breakdown"][
            "total_die_area_mm2"
        ]
        b1_n3e = self.reports["n3e_est"]["aigpu_targets"]["aigpu-b1"]["area_breakdown"][
            "total_die_area_mm2"
        ]
        self.assertLess(b1_n3e, b1_n4p)
        self.assertLess(b1_n4p, b1_asap7)
        self.assertLess(b1_n4p, ppa_mod.RETICLE_LIMIT_MM2)
        self.assertLess(b1_n3e, ppa_mod.RETICLE_LIMIT_MM2)
        self.assertTrue(
            self.reports["n4p_est"]["aigpu_targets"]["aigpu-b1"]["area_breakdown"][
                "within_reticle_limit"
            ]
        )
        self.assertTrue(
            self.reports["n3e_est"]["aigpu_targets"]["aigpu-b1"]["area_breakdown"][
                "within_reticle_limit"
            ]
        )

        tile_asap7 = self.reports["asap7"]["aigpu_targets"]["aigpu-b1-tile"][
            "area_breakdown"
        ]["total_die_area_mm2"]
        tile_n4p = self.reports["n4p_est"]["aigpu_targets"]["aigpu-b1-tile"][
            "area_breakdown"
        ]["total_die_area_mm2"]
        tile_n3e = self.reports["n3e_est"]["aigpu_targets"]["aigpu-b1-tile"][
            "area_breakdown"
        ]["total_die_area_mm2"]
        self.assertLess(tile_n3e, tile_n4p)
        self.assertLess(tile_n4p, tile_asap7)

    def test_consistency_with_b1_roofline_compare_and_ridge_physics(self):
        report = self.reports["n4p_est"]
        for pname in ("aigpu-b1", "aigpu-b1-tile"):
            with self.subTest(profile=pname):
                ppa_entry = report["aigpu_targets"][pname]
                rf_entry = self.roofline_report["profiles"][pname]
                bw_tbps = rf_entry["memory"]["bandwidth_gbs"] / 1000.0
                self.assertAlmostEqual(
                    ppa_entry["memory_subsystem"]["bandwidth_tbps"], bw_tbps, places=9
                )

                tc = ppa_entry["tensor_compute"]
                for fmt_key in ("fp16_bf16", "fp8", "mxfp4", "nvfp4"):
                    rf_fmt = rf_entry["tensor_formats"][fmt_key]
                    ppa_fmt = tc[fmt_key]
                    self.assertEqual(ppa_fmt["supported"], rf_fmt["supported"])
                    self.assertAlmostEqual(
                        ppa_fmt["dense_peak"], rf_fmt["dense_peak"], places=9
                    )
                    self.assertAlmostEqual(
                        ppa_fmt["sparse_2_4_peak"], rf_fmt["sparse_2_4_peak"], places=9
                    )
                    self.assertAlmostEqual(
                        ppa_fmt["sparse_2_4_peak"],
                        2.0 * ppa_fmt["dense_peak"],
                        places=9,
                    )
                    expected_ridge = (ppa_fmt["dense_peak"] * 1e12) / (bw_tbps * 1e12)
                    self.assertAlmostEqual(
                        ppa_fmt["dense_ridge_ops_per_byte"], expected_ridge, places=9
                    )
                    self.assertAlmostEqual(
                        ppa_fmt["dense_ridge_ops_per_byte"],
                        rf_fmt["dense_ridge_flop_per_byte"],
                        places=9,
                    )
                    self.assertAlmostEqual(
                        ppa_fmt["sparse_2_4_ridge_ops_per_byte"],
                        2.0 * expected_ridge,
                        places=9,
                    )

                # Format throughput monotonicity: FP4 > FP8 > FP16
                self.assertGreater(
                    tc["nvfp4"]["dense_peak"], tc["fp8"]["dense_peak"]
                )
                self.assertGreater(
                    tc["mxfp4"]["dense_peak"], tc["fp8"]["dense_peak"]
                )
                self.assertGreater(
                    tc["fp8"]["dense_peak"], tc["fp16_bf16"]["dense_peak"]
                )

    def test_power_breakdown_sums_exactly_to_total_tdp(self):
        for node, report in self.reports.items():
            for pname, entry in report["aigpu_targets"].items():
                with self.subTest(node=node, profile=pname):
                    pb = entry["power_breakdown"]
                    self.assertAlmostEqual(
                        pb["dynamic_compute_tcu_w"] + pb["dynamic_compute_core_uncore_w"],
                        pb["dynamic_compute_total_w"],
                        places=9,
                    )
                    component_sum = (
                        pb["dynamic_compute_total_w"]
                        + pb["dynamic_sram_w"]
                        + pb["memory_io_and_phy_w"]
                        + pb["uncore_hard_ip_serdes_pll_w"]
                        + pb["static_leakage_w"]
                    )
                    self.assertAlmostEqual(component_sum, pb["total_tdp_w"], places=9)

                    area = entry["area_breakdown"]["total_die_area_mm2"]
                    self.assertAlmostEqual(
                        pb["power_density_w_per_mm2"], pb["total_tdp_w"] / area, places=9
                    )

                    # Also verify precision-specific breakdowns sum exactly
                    for fmt_key, fpb in pb["by_precision"].items():
                        fsum = (
                            fpb["dynamic_compute_tcu_w"]
                            + fpb["dynamic_compute_core_uncore_w"]
                            + fpb["dynamic_sram_w"]
                            + fpb["memory_io_and_phy_w"]
                            + fpb["uncore_hard_ip_serdes_pll_w"]
                            + fpb["static_leakage_w"]
                        )
                        self.assertAlmostEqual(fsum, fpb["total_tdp_w"], places=9)
                        tc_fmt = entry["tensor_compute"][fmt_key]
                        self.assertAlmostEqual(
                            tc_fmt["dense_per_mm2"],
                            tc_fmt["dense_peak"] / area,
                            places=9,
                        )
                        self.assertAlmostEqual(
                            tc_fmt["dense_per_watt"],
                            tc_fmt["dense_peak"] / fpb["total_tdp_w"],
                            places=9,
                        )

    def test_published_reference_baselines_present_and_tagged(self):
        refs = self.reports["n4p_est"]["published_reference_baselines"]
        expected_ids = {
            "nvidia-h100-sxm5",
            "nvidia-rtx5080",
            "nvidia-b200-single-die",
            "nvidia-b200-dual-die",
        }
        self.assertEqual(set(refs.keys()), expected_ids)
        b200_1d = refs["nvidia-b200-single-die"]
        b200_2d = refs["nvidia-b200-dual-die"]
        self.assertEqual(b200_1d["die_count"], 1)
        self.assertEqual(b200_2d["die_count"], 2)
        self.assertAlmostEqual(
            b200_2d["total_silicon_area_mm2"],
            2.0 * b200_1d["total_silicon_area_mm2"],
            places=6,
        )
        self.assertAlmostEqual(
            b200_2d["tensor_compute"]["nvfp4"]["dense_peak"],
            2.0 * b200_1d["tensor_compute"]["nvfp4"]["dense_peak"],
            places=6,
        )
        self.assertFalse(refs["nvidia-h100-sxm5"]["tensor_compute"]["nvfp4"]["supported"])
        self.assertTrue(refs["nvidia-rtx5080"]["tensor_compute"]["nvfp4"]["supported"])

    def test_cli_json_and_markdown_modes_across_nodes(self):
        for node in ppa_mod.VALID_NODES:
            with self.subTest(node=node):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = ppa_mod.main(["--node", node, "--markdown"])
                self.assertEqual(rc, 0)
                md = stdout.getvalue()
                self.assertIn("`evidence_level`: `simulated`", md)
                self.assertIn("`silicon_measured`: `false`", md)
                self.assertIn("`foundry_signoff`: `false`", md)
                self.assertIn("`aigpu-b1`", md)
                self.assertIn("`aigpu-b1-tile`", md)
                self.assertIn("Published Ref", md)

        with tempfile.TemporaryDirectory(prefix="aigpu-ppa-cli-") as tmp_dir:
            out_json = Path(tmp_dir) / "ppa.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "ci/project/aigpu_ppa_model.py"),
                    "--node",
                    "n3e_est",
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
            ppa_mod.validate_honesty_record(parsed)
            self.assertEqual(parsed["selected_node"], "n3e_est")
            self.assertEqual(
                set(parsed["aigpu_targets"].keys()), {"aigpu-b1", "aigpu-b1-tile"}
            )


if __name__ == "__main__":
    unittest.main()
