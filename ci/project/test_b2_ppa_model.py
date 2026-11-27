# SPDX-License-Identifier: Apache-2.0
"""Offline unit tests for ci/project/b2_ppa_model.py (AI-GPU B2 PPA model)."""

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

import aigpu_ppa_model as base_ppa
import b2_arch_spec
import b2_ppa_model as b2_ppa
import b2_program_tracker as tracker


ROOT = Path(__file__).resolve().parents[2]


class B2PpaModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measured = base_ppa.load_measured_presilicon_inputs()
        cls.reports = {
            node: b2_ppa.build_b2_ppa_report(node_id=node)
            for node in b2_ppa.VALID_NODES
        }

    def test_readonly_integration_with_aigpu_ppa_model(self):
        # Verify shared constants and read-only anchors match base module exactly
        self.assertEqual(b2_ppa.SCHEMA_VERSION, base_ppa.SCHEMA_VERSION)
        self.assertEqual(b2_ppa.RETICLE_LIMIT_MM2, base_ppa.RETICLE_LIMIT_MM2)
        self.assertEqual(b2_ppa.VALID_NODES, base_ppa.VALID_NODES)
        self.assertIs(b2_ppa.NODE_SPECS, base_ppa.NODE_SPECS)

        n4p = self.reports["n4p_est"]
        macros = n4p["measured_presilicon_inputs"]["measured_asap7_macros"]
        self.assertAlmostEqual(
            macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_fmax_mhz"], 1079.53, places=2
        )
        self.assertAlmostEqual(
            macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_stdcell_area_um2"],
            793.5165,
            places=4,
        )
        # Generational comparison uses base_ppa.model_aigpu_target directly
        gen = n4p["b1_to_b2_generational_delta"]
        b1_ref = base_ppa.model_aigpu_target("aigpu-b1", node_id="n4p_est", measured=self.measured)
        self.assertAlmostEqual(
            gen["b1_baseline"]["die_area_mm2"],
            b1_ref["area_breakdown"]["total_die_area_mm2"],
            places=6,
        )
        self.assertGreater(gen["ratios_b2_over_b1"]["fp16_tflops_ratio"], 8.0)
        self.assertGreater(gen["ratios_b2_over_b1"]["compute_density_fp16_per_mm2_ratio"], 2.0)
        self.assertGreater(gen["ratios_b2_over_b1"]["energy_efficiency_fp16_per_watt_ratio"], 3.0)

    def test_anti_bloat_check_passes_with_zero_warnings(self):
        model_path = ROOT / "ci/project/b2_ppa_model.py"
        warnings = tracker.check_file_anti_bloat(model_path)
        self.assertEqual(warnings, [], f"Unexpected anti-bloat warnings: {warnings}")

    def test_strict_honesty_contract_and_tamper_rejection(self):
        for node_id, report in self.reports.items():
            with self.subTest(node=node_id):
                self.assertEqual(report["schema_version"], 1)
                self.assertEqual(report["evidence_level"], "simulated")
                self.assertEqual(report["model_type"], "parametric_presilicon_estimate")
                self.assertIs(report["silicon_measured"], False)
                self.assertIs(report["fpga_measured"], False)
                self.assertIs(report["foundry_signoff"], False)
                self.assertIs(report["is_published_reference"], False)

                for sku_id, sku_entry in report["b2_skus"].items():
                    with self.subTest(sku=sku_id):
                        self.assertEqual(sku_entry["schema_version"], 1)
                        self.assertEqual(sku_entry["evidence_level"], "simulated")
                        self.assertEqual(sku_entry["model_type"], "parametric_presilicon_estimate")
                        self.assertIs(sku_entry["silicon_measured"], False)
                        self.assertIs(sku_entry["fpga_measured"], False)
                        self.assertIs(sku_entry["foundry_signoff"], False)
                        self.assertIs(sku_entry["is_published_reference"], False)

                for ref_id, ref_entry in report["published_vendor_baselines"].items():
                    with self.subTest(ref=ref_id):
                        self.assertEqual(ref_entry["schema_version"], 1)
                        self.assertEqual(ref_entry["evidence_level"], "simulated")
                        self.assertIs(ref_entry["silicon_measured"], False)
                        self.assertIs(ref_entry["fpga_measured"], False)
                        self.assertIs(ref_entry["foundry_signoff"], False)
                        self.assertIs(ref_entry["is_published_reference"], True)
                        self.assertIs(ref_entry["locally_measured"], False)

        # Tamper assertions must fail closed
        for field, bad_val, pattern in (
            ("silicon_measured", True, "silicon_measured=False"),
            ("fpga_measured", True, "fpga_measured=False"),
            ("foundry_signoff", True, "foundry_signoff=False"),
            ("evidence_level", "silicon_measured", "evidence_level"),
            ("model_type", "tapeout_signoff", "model_type"),
            ("schema_version", 99, "schema_version"),
        ):
            tampered = copy.deepcopy(self.reports["n4p_est"])
            tampered[field] = bad_val
            with self.assertRaisesRegex(ValueError, pattern):
                b2_ppa.validate_b2_honesty_record(tampered)

    def test_reticle_limit_and_sku_area_ranges(self):
        n4p_skus = self.reports["n4p_est"]["b2_skus"]
        n3e_skus = self.reports["n3e_est"]["b2_skus"]
        asap7_skus = self.reports["asap7"]["b2_skus"]

        # aigpu-b2-tile fits inside 12-18 mm^2 MPW range on N4P
        tile_n4p_area = n4p_skus["aigpu-b2-tile"]["area_and_shoreline"]["per_die_area_breakdown_mm2"][
            "total_die_area_mm2"
        ]
        self.assertGreaterEqual(tile_n4p_area, 12.0)
        self.assertLessEqual(tile_n4p_area, 18.0)

        # aigpu-b2 fits comfortably inside 740-810 mm^2 and <= 858 mm^2 reticle limit on N4P
        b2_n4p_rc = n4p_skus["aigpu-b2"]["area_and_shoreline"]["reticle_and_field_check"]
        b2_n4p_area = n4p_skus["aigpu-b2"]["area_and_shoreline"]["per_die_area_breakdown_mm2"][
            "total_die_area_mm2"
        ]
        self.assertGreaterEqual(b2_n4p_area, 740.0)
        self.assertLessEqual(b2_n4p_area, 810.0)
        self.assertLessEqual(b2_n4p_area, b2_ppa.RETICLE_LIMIT_MM2)
        self.assertTrue(b2_n4p_rc["within_reticle_limit"])
        self.assertTrue(b2_n4p_rc["within_reticle_field_26x33mm"])

        # N3E shrinks monotonically relative to N4P, which shrinks relative to ASAP7
        b2_n3e_area = n3e_skus["aigpu-b2"]["area_and_shoreline"]["per_die_area_breakdown_mm2"][
            "total_die_area_mm2"
        ]
        b2_asap7_area = asap7_skus["aigpu-b2"]["area_and_shoreline"]["per_die_area_breakdown_mm2"][
            "total_die_area_mm2"
        ]
        self.assertLess(b2_n3e_area, b2_n4p_area)
        self.assertLess(b2_n4p_area, b2_asap7_area)
        self.assertTrue(
            n3e_skus["aigpu-b2"]["area_and_shoreline"]["reticle_and_field_check"]["within_reticle_limit"]
        )

        # Dual-die package total silicon is exactly 2x single-die while per-die matches single-die
        b2_dual_area = n4p_skus["aigpu-b2-dual"]["area_and_shoreline"]
        self.assertAlmostEqual(
            b2_dual_area["per_die_area_breakdown_mm2"]["total_die_area_mm2"],
            b2_n4p_area,
            places=6,
        )
        self.assertAlmostEqual(
            b2_dual_area["package_silicon_area_mm2"],
            2.0 * b2_n4p_area,
            places=6,
        )

        # Subsystem area sum conservation on every node and SKU
        for node_id, report in self.reports.items():
            for sid, sm in report["b2_skus"].items():
                with self.subTest(node=node_id, sku=sid):
                    ab = sm["area_and_shoreline"]["per_die_area_breakdown_mm2"]
                    sub_sum = sum(ab["logic_subsystems_routed_mm2"].values())
                    self.assertAlmostEqual(sub_sum, ab["logic_routed_mm2"], places=6)
                    sram_sum = ab["sram_tmem_mm2"] + ab["sram_l2_slc_dir_mm2"] + ab["sram_lmem_l1_rf_mm2"]
                    self.assertAlmostEqual(sram_sum, ab["sram_total_mm2"], places=6)
                    self.assertAlmostEqual(
                        ab["logic_routed_mm2"] + ab["sram_total_mm2"] + ab["hard_ip_total_mm2"],
                        ab["total_die_area_mm2"],
                        places=6,
                    )

    def test_tmem_l2_sram_macro_cut_totals_and_ecc_overhead(self):
        n4p_skus = self.reports["n4p_est"]["b2_skus"]

        # Exact TMEM capacities: 1 MiB (tile), 32 MiB (b2), 64 MiB (b2-dual)
        tile_sram = n4p_skus["aigpu-b2-tile"]["area_and_shoreline"]["sram_budget"]
        b2_sram = n4p_skus["aigpu-b2"]["area_and_shoreline"]["sram_budget"]
        dual_sram = n4p_skus["aigpu-b2-dual"]["area_and_shoreline"]["sram_budget"]

        self.assertAlmostEqual(tile_sram["tmem_architecture"]["mib_package"], 1.0, places=6)
        self.assertAlmostEqual(b2_sram["tmem_architecture"]["mib_die" if "mib_die" in b2_sram["tmem_architecture"] else "mib_per_die"], 32.0, places=6)
        self.assertAlmostEqual(b2_sram["tmem_architecture"]["mib_package"], 32.0, places=6)
        self.assertAlmostEqual(dual_sram["tmem_architecture"]["mib_package"], 64.0, places=6)

        # Exact TMEM cut bit arithmetic: 32 MiB = 268,435,456 logical bits + 1/8 SECDED + 4% spare
        tmem_arr = next(a for a in b2_sram["arrays"] if a["array_id"] == "tmem_tensor_bank")
        expected_tmem_logical = 32 * 1024 * 1024 * 8
        expected_tmem_ecc = int(round(expected_tmem_logical * (8.0 / 64.0)))
        expected_tmem_red = int(round((expected_tmem_logical + expected_tmem_ecc) * 0.04))
        self.assertEqual(tmem_arr["logical_bits_per_die"], expected_tmem_logical)
        self.assertEqual(tmem_arr["ecc_overhead_bits_per_die"], expected_tmem_ecc)
        self.assertEqual(tmem_arr["redundancy_overhead_bits_per_die"], expected_tmem_red)
        self.assertEqual(
            tmem_arr["physical_bits_per_die"],
            expected_tmem_logical + expected_tmem_ecc + expected_tmem_red,
        )

        # Exact L2 data capacity: 128 MiB/die on b2, 256 MiB unified on b2-dual
        l2_arr = next(a for a in b2_sram["arrays"] if a["array_id"] == "l2_slc_data")
        expected_l2_logical = 128 * 1024 * 1024 * 8
        expected_l2_ecc = int(round(expected_l2_logical * (16.0 / 128.0)))  # Chipkill 144/128
        expected_l2_red = int(round((expected_l2_logical + expected_l2_ecc) * 0.04))
        self.assertEqual(l2_arr["logical_bits_per_die"], expected_l2_logical)
        self.assertEqual(l2_arr["ecc_overhead_bits_per_die"], expected_l2_ecc)
        self.assertEqual(l2_arr["physical_bits_per_die"], expected_l2_logical + expected_l2_ecc + expected_l2_red)
        self.assertEqual(l2_arr["ecc_scheme"], "Chipkill_144_128")

        # Dual-banked 1RW TMEM saves area compared to native 1R1W TMEM
        b2_1r1w = b2_ppa.model_b2_sku("aigpu-b2", node_id="n4p_est", tmem_port_mode="native_1r1w", measured=self.measured)
        tmem_1rw_mm2 = b2_sram["subsystem_summary"]["tmem"]["area_per_die_mm2"]
        tmem_1r1w_mm2 = b2_1r1w["area_and_shoreline"]["sram_budget"]["subsystem_summary"]["tmem"]["area_per_die_mm2"]
        self.assertLess(tmem_1rw_mm2, tmem_1r1w_mm2)
        self.assertAlmostEqual(
            tmem_1r1w_mm2 - tmem_1rw_mm2,
            b2_sram["tmem_architecture"]["area_savings_mm2_per_die"],
            places=6,
        )

    def test_hbm3e_ucie_pcie_shoreline_checks(self):
        for node_id in ("n4p_est", "n3e_est"):
            for sid in b2_ppa.VALID_SKUS:
                with self.subTest(node=node_id, sku=sid):
                    sm = self.reports[node_id]["b2_skus"][sid]
                    sb = sm["area_and_shoreline"]["shoreline_budget"]
                    self.assertTrue(sb["shoreline_feasible"])
                    self.assertLess(sb["total_shoreline_required_mm"], sb["die_perimeter_mm"])
                    for edge in sb["edge_checks"].values():
                        self.assertTrue(edge["fits"])
                        self.assertLessEqual(edge["required_mm"], edge["available_mm"])

        # Verify 8 HBM3E stacks and 10 TB/s UCIe 2.0 shoreline arithmetic on aigpu-b2
        b2_sb = self.reports["n4p_est"]["b2_skus"]["aigpu-b2"]["area_and_shoreline"]["shoreline_budget"]
        self.assertAlmostEqual(b2_sb["hbm3e_shoreline_mm"], 8.0 * 5.8, places=6)
        self.assertAlmostEqual(b2_sb["ucie_2_0_shoreline_mm"], 10000.0 / 650.0, places=6)
        self.assertAlmostEqual(b2_sb["pcie_gen6_shoreline_mm"], 9.5, places=6)

    def test_compute_peaks_and_precision_ratios(self):
        n4p = self.reports["n4p_est"]["b2_skus"]
        b2_tc = n4p["aigpu-b2"]["compute_and_formats"]["tensor_compute"]
        dual_tc = n4p["aigpu-b2-dual"]["compute_and_formats"]["tensor_compute"]
        tile_tc = n4p["aigpu-b2-tile"]["compute_and_formats"]["tensor_compute"]

        # Architectural TFRv2 targets @ 2.0 GHz
        self.assertAlmostEqual(b2_tc["fp16_bf16"]["tfr_v2_architectural_dense"], 1152.0, places=3)
        self.assertAlmostEqual(b2_tc["fp8"]["tfr_v2_architectural_dense"], 2304.0, places=3)
        self.assertAlmostEqual(b2_tc["mxfp6"]["tfr_v2_architectural_dense"], 2304.0, places=3)
        self.assertAlmostEqual(b2_tc["nvfp4"]["tfr_v2_architectural_dense"], 4608.0, places=3)
        self.assertAlmostEqual(b2_tc["fp16_bf16"]["tfr_v2_architectural_sparse_2_4"], 2304.0, places=3)
        self.assertAlmostEqual(b2_tc["fp8"]["tfr_v2_architectural_sparse_2_4"], 4608.0, places=3)
        self.assertAlmostEqual(b2_tc["mxfp6"]["tfr_v2_architectural_sparse_2_4"], 4608.0, places=3)
        self.assertAlmostEqual(b2_tc["nvfp4"]["tfr_v2_architectural_sparse_2_4"], 9216.0, places=3)

        # Vortex base resolved TFR FP16 = 1048.576 TFLOPS cleanly distinguished from 1152 TFLOPS TFRv2
        self.assertAlmostEqual(b2_tc["fp16_bf16"]["vortex_base_resolved_dense"], 1048.576, places=3)

        # Dual-die is exactly 2x single-die
        for fmt_key in ("fp16_bf16", "fp8", "mxfp6", "mxfp4", "nvfp4", "tf32", "int8"):
            self.assertAlmostEqual(
                dual_tc[fmt_key]["tfr_v2_architectural_dense"],
                2.0 * b2_tc[fmt_key]["tfr_v2_architectural_dense"],
                places=6,
            )

        # Tile @ 2 GHz = 18 / 36 / 72 TFLOPS; 400 MHz RTL ref = 3.6 / 7.2 / 14.4 TFLOPS
        self.assertAlmostEqual(tile_tc["fp16_bf16"]["tfr_v2_architectural_dense"], 18.0, places=3)
        self.assertAlmostEqual(tile_tc["fp8"]["tfr_v2_architectural_dense"], 36.0, places=3)
        self.assertAlmostEqual(tile_tc["nvfp4"]["tfr_v2_architectural_dense"], 72.0, places=3)
        rtl_ref = n4p["aigpu-b2-tile"]["compute_and_formats"]["rtl_ref_peaks"]
        self.assertAlmostEqual(rtl_ref["fp16_tfr_v2_dense_tflops"], 3.6, places=3)

    def test_power_conservation_workload_and_node_monotonicity(self):
        for node_id, report in self.reports.items():
            for sid, sm in report["b2_skus"].items():
                pt = sm["power_and_thermal"]
                with self.subTest(node=node_id, sku=sid):
                    # Component sum equality for selected workload and all workloads
                    for wname, pb in [
                        ("selected", pt["selected_workload_power"]),
                        *pt["all_workloads_power"].items(),
                        *pt["peak_tdp_by_precision"].items(),
                    ]:
                        comp_sum = (
                            pb["dynamic_compute_tcu_w"]
                            + pb["dynamic_compute_core_uncore_w"]
                            + pb["dynamic_tmem_w"]
                            + pb["dynamic_cache_sram_w"]
                            + pb["hbm3e_io_and_phy_w"]
                            + pb["ucie_d2d_phy_w"]
                            + pb["pcie_gen6_and_hard_ip_w"]
                            + pb["static_leakage_w"]
                        )
                        self.assertAlmostEqual(comp_sum, pb["total_power_w"], places=9, msg=wname)

                    # Workload monotonicity: idle < decode < prefill_fp4 < prefill_fp8 <= peak_tdp_stress
                    w_map = pt["all_workloads_power"]
                    self.assertLess(w_map["idle"]["total_power_w"], w_map["llm_decode"]["total_power_w"])
                    self.assertLess(w_map["llm_decode"]["total_power_w"], w_map["llm_prefill_fp4"]["total_power_w"])
                    self.assertLess(w_map["llm_prefill_fp8"]["total_power_w"], w_map["peak_tdp_stress"]["total_power_w"])

                    # Thermal T_j equation consistency and DLC < Air T_j
                    pkg_area = sm["area_and_shoreline"]["package_silicon_area_mm2"]
                    self.assertAlmostEqual(
                        pt["thermal_density_w_per_mm2_at_peak_tdp"],
                        pt["peak_tdp_w"] / pkg_area,
                        places=9,
                    )
                    air = pt["thermal_envelopes"]["air_cooled"]
                    dlc = pt["thermal_envelopes"]["liquid_cooled"]
                    self.assertAlmostEqual(
                        dlc["tj_at_peak_tdp_c"],
                        dlc["ambient_c"] + pt["peak_tdp_w"] * dlc["r_theta_ja_c_per_w"],
                        places=6,
                    )
                    if sid != "aigpu-b2-tile":
                        self.assertLess(dlc["tj_at_peak_tdp_c"], air["tj_at_peak_tdp_c"])
                    if node_id in ("n4p_est", "n3e_est"):
                        self.assertTrue(dlc["meets_thermal_ceiling_at_peak_tdp"])

        # Node power monotonicity: N3E < N4P < ASAP7 for same SKU
        for sid in b2_ppa.VALID_SKUS:
            p_n3e = self.reports["n3e_est"]["b2_skus"][sid]["power_and_thermal"]["peak_tdp_w"]
            p_n4p = self.reports["n4p_est"]["b2_skus"][sid]["power_and_thermal"]["peak_tdp_w"]
            p_asap7 = self.reports["asap7"]["b2_skus"][sid]["power_and_thermal"]["peak_tdp_w"]
            self.assertLess(p_n3e, p_n4p)
            self.assertLess(p_n4p, p_asap7)

        # CoWoS-L dual-die packaging verification
        dual_pkg = self.reports["n4p_est"]["b2_skus"]["aigpu-b2-dual"]["power_and_thermal"]["packaging_and_pdn"]
        self.assertIn("CoWoS-L", dual_pkg["packaging_technology"])
        self.assertEqual(dual_pkg["lsi_bridge_count"], 3)
        self.assertTrue(dual_pkg["within_warpage_budget"])
        self.assertTrue(dual_pkg["within_pdn_budget"])

    def test_dvfs_sweep_and_fmax_ceilings(self):
        b2_n4p = self.reports["n4p_est"]["b2_skus"]["aigpu-b2"]
        sweep = b2_n4p["dvfs_operating_sweep"]
        self.assertLess(sweep["efficiency_bin"]["peak_tdp_w"], sweep["nominal"]["peak_tdp_w"])
        self.assertLess(sweep["nominal"]["peak_tdp_w"], sweep["boost_odv"]["peak_tdp_w"])
        self.assertGreater(
            sweep["efficiency_bin"]["fp16_dense_per_watt"],
            sweep["boost_odv"]["fp16_dense_per_watt"],
        )
        self.assertTrue(sweep["nominal"]["meets_node_fmax_ceiling"])
        self.assertFalse(
            self.reports["asap7"]["b2_skus"]["aigpu-b2"]["dvfs_operating_sweep"]["nominal"]["meets_node_fmax_ceiling"]
        )

    def test_wafer_gross_dies_yield_monotonicity_and_cowos_l_aggregation(self):
        # Larger dies fit fewer gross dies per 300mm wafer
        n4p = self.reports["n4p_est"]["b2_skus"]
        tile_dpw = n4p["aigpu-b2-tile"]["yield_and_cost"]["gross_dies_per_wafer"]
        b2_dpw = n4p["aigpu-b2"]["yield_and_cost"]["gross_dies_per_wafer"]
        self.assertGreater(tile_dpw, 3000)
        self.assertGreater(b2_dpw, 50)
        self.assertLess(b2_dpw, 120)

        for sid in b2_ppa.VALID_SKUS:
            yc = n4p[sid]["yield_and_cost"]
            sweep = yc["d0_sweep"]
            for i in range(len(sweep) - 1):
                # Higher defect density D0 strictly reduces yield and increases KGD cost
                self.assertGreater(
                    sweep[i]["murphy_yield_sram_repaired"],
                    sweep[i + 1]["murphy_yield_sram_repaired"],
                )
                self.assertGreater(
                    sweep[i]["negbin_yield_sram_repaired"],
                    sweep[i + 1]["negbin_yield_sram_repaired"],
                )
                self.assertLess(
                    sweep[i]["kgd_die_cost_usd_est"],
                    sweep[i + 1]["kgd_die_cost_usd_est"],
                )
            for pt in sweep:
                # SRAM repair always increases yield over unrepaired
                self.assertGreater(pt["negbin_yield_sram_repaired"], pt["negbin_yield_unrepaired"])
                self.assertGreater(pt["murphy_yield_sram_repaired"], pt["murphy_yield_unrepaired"])

        # Dual-die composite yield is strictly lower than single-die due to KGD^2 * CoWoS-L yield
        b2_nom = n4p["aigpu-b2"]["yield_and_cost"]["nominal_point"]
        dual_nom = n4p["aigpu-b2-dual"]["yield_and_cost"]["nominal_point"]
        self.assertAlmostEqual(
            dual_nom["composite_module_yield"],
            (dual_nom["negbin_yield_sram_repaired"] ** 2) * dual_nom["package_assembly_yield"],
            places=9,
        )
        self.assertLess(dual_nom["composite_module_yield"], b2_nom["composite_module_yield"])
        self.assertGreater(dual_nom["package_silicon_bom_usd_est"], 2.0 * b2_nom["kgd_die_cost_usd_est"])

    def test_published_vendor_baselines_and_tco_comparator(self):
        n4p = self.reports["n4p_est"]
        refs = n4p["published_vendor_baselines"]
        self.assertEqual(
            set(refs.keys()),
            {
                "nvidia-b200-1die",
                "nvidia-b200-2die",
                "nvidia-h200-sxm",
                "nvidia-h100-sxm5",
                "amd-mi300x",
            },
        )
        self.assertFalse(refs["nvidia-h100-sxm5"]["tensor_compute"]["nvfp4"]["supported"])
        self.assertFalse(refs["nvidia-h200-sxm"]["tensor_compute"]["nvfp4"]["supported"])
        self.assertFalse(refs["amd-mi300x"]["tensor_compute"]["nvfp4"]["supported"])
        self.assertTrue(refs["nvidia-b200-2die"]["tensor_compute"]["nvfp4"]["supported"])

        tco = n4p["tco_and_efficiency_comparison"]
        self.assertIn("aigpu-b2", tco["skus"])
        self.assertIn("aigpu-b2-dual", tco["skus"])
        self.assertGreater(tco["skus"]["aigpu-b2"]["fp8_perf_per_watt_vs_h100"], 1.0)
        self.assertLess(tco["skus"]["aigpu-b2"]["tco_per_fp8_pflops_hr_vs_h100"], 1.0)

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            b2_ppa.model_b2_sku("unknown-sku")
        with self.assertRaises(ValueError):
            b2_ppa.model_b2_sku("aigpu-b2", node_id="tsmc_2nm")
        with self.assertRaises(ValueError):
            b2_ppa.model_b2_sku("aigpu-b2", workload_id="crypto_mining")
        with self.assertRaises(ValueError):
            b2_ppa.model_b2_sku("aigpu-b2", tmem_port_mode="3rw")
        with self.assertRaises(ValueError):
            b2_ppa.model_b2_sku("aigpu-b2", dvfs_bin="turbo_9ghz")
        with self.assertRaises(ValueError):
            b2_ppa.gross_dies_per_300mm_wafer(-1.0, 10.0)
        for bad_d0 in (-0.05, -0.01, float("nan"), float("inf"), -float("inf"), True):
            with self.subTest(bad_d0=bad_d0):
                with self.assertRaises(ValueError):
                    b2_ppa.compute_b2_yield_and_cost(
                        b2_ppa.B2_SKU_SPECS["aigpu-b2"],
                        b2_ppa.NODE_SPECS["n4p_est"],
                        self.reports["n4p_est"]["b2_skus"]["aigpu-b2"]["area_and_shoreline"],
                        d0_sweep=(bad_d0,),
                    )
                with self.assertRaises(ValueError):
                    b2_ppa.compute_b2_yield_and_cost(
                        b2_ppa.B2_SKU_SPECS["aigpu-b2"],
                        b2_ppa.NODE_SPECS["n4p_est"],
                        self.reports["n4p_est"]["b2_skus"]["aigpu-b2"]["area_and_shoreline"],
                        nominal_d0=bad_d0,
                    )

    def test_cli_json_markdown_and_filters(self):
        for node_id in b2_ppa.VALID_NODES:
            with self.subTest(node=node_id):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = b2_ppa.main([
                        "--node", node_id,
                        "--workload", "llm_prefill_fp8",
                        "--yield-sweep",
                        "--markdown",
                    ])
                self.assertEqual(rc, 0)
                md = buf.getvalue()
                self.assertIn("**Evidence Level**: `simulated`", md)
                self.assertIn("**`silicon_measured`**: `false`", md)
                self.assertIn("**`fpga_measured`**: `false`", md)
                self.assertIn("**`foundry_signoff`**: `false`", md)
                self.assertIn("`aigpu-b2`", md)
                self.assertIn("`aigpu-b2-dual`", md)
                self.assertIn("300mm Wafer Yield & KGD Cost Sweep", md)
                self.assertIn("NVIDIA B200 2-Die SXM (Published Ref)", md)
                self.assertIn("AMD Instinct MI300X (Published Ref)", md)

        with tempfile.TemporaryDirectory(prefix="aigpu-b2-ppa-") as tmp:
            out_path = Path(tmp) / "b2_ppa.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "ci/project/b2_ppa_model.py"),
                    "--node",
                    "n3e_est",
                    "--sku",
                    "aigpu-b2",
                    "--workload",
                    "llm_decode",
                    "--d0-values",
                    "0.05,0.10,0.20",
                    "--json",
                    "--output",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.stdout, "")
            parsed = json.loads(out_path.read_text(encoding="utf-8"))
            b2_ppa.validate_b2_honesty_record(parsed)
            self.assertEqual(parsed["selected_node"], "n3e_est")
            self.assertEqual(parsed["selected_workload"], "llm_decode")
            self.assertEqual(set(parsed["b2_skus"].keys()), {"aigpu-b2"})
            sweep = parsed["b2_skus"]["aigpu-b2"]["yield_and_cost"]["d0_sweep"]
            self.assertEqual([round(p["d0_defects_per_cm2"], 2) for p in sweep], [0.05, 0.10, 0.20])
            for p in sweep:
                self.assertTrue(math.isfinite(p["kgd_die_cost_usd_est"]))

    def test_sram_macro_cut_decomposition_and_all_subsystems(self):
        for node_id in b2_ppa.VALID_NODES:
            for sid in b2_ppa.VALID_SKUS:
                with self.subTest(node=node_id, sku=sid):
                    sm = self.reports[node_id]["b2_skus"][sid]
                    sram = sm["area_and_shoreline"]["sram_budget"]
                    arrays = {a["array_id"]: a for a in sram["arrays"]}
                    self.assertIn("tmem_tensor_bank", arrays)
                    self.assertIn("l2_slc_data", arrays)
                    self.assertIn("l2_slc_tag_and_state", arrays)
                    self.assertIn("lmem_bank_mirrored", arrays)
                    self.assertIn("l1_dcache_data_and_tag", arrays)
                    self.assertIn("l1_icache_data_and_tag", arrays)
                    self.assertIn("rf_gpr_and_pred_bank", arrays)
                    self.assertIn("tcu_meta_dxa_cp_queues", arrays)

                    if sid in ("aigpu-b2", "aigpu-b2-dual"):
                        self.assertIn("coherent_dir_and_snoop_filter", arrays)
                        self.assertIn("de_history_and_hbm_reorder_sram", arrays)
                        self.assertEqual(arrays["l2_slc_data"]["macro_cuts_per_die"], 4096)
                        self.assertEqual(arrays["tmem_tensor_bank"]["macro_cuts_per_die"], 2048)
                    else:
                        self.assertNotIn("coherent_dir_and_snoop_filter", arrays)
                        self.assertEqual(arrays["tmem_tensor_bank"]["macro_cuts_per_die"], 64)

                    total_bits = sum(a["logical_bits_per_die"] for a in arrays.values())
                    total_phys = sum(a["physical_bits_per_die"] for a in arrays.values())
                    total_cuts = sum(a["macro_cuts_per_die"] for a in arrays.values())
                    total_area = sum(a["area_per_die_mm2"] for a in arrays.values())
                    totals = sram["totals_per_die"]
                    self.assertEqual(totals["logical_bits"], total_bits)
                    self.assertEqual(totals["physical_bits"], total_phys)
                    self.assertEqual(totals["macro_cuts"], total_cuts)
                    self.assertAlmostEqual(totals["sram_total_mm2"], total_area, places=9)
                    self.assertGreater(totals["ecc_plus_redundancy_pct"], 12.0)
                    self.assertLess(totals["ecc_plus_redundancy_pct"], 25.0)

                    # Package SRAM totals scale linearly with die count
                    pkg = sram["totals_package"]
                    self.assertAlmostEqual(
                        pkg["sram_total_mm2"],
                        sm["topology"]["die_count"] * totals["sram_total_mm2"],
                        places=9,
                    )
                    self.assertEqual(
                        pkg["physical_bits"],
                        sm["topology"]["die_count"] * totals["physical_bits"],
                    )

    def test_tmem_bandwidth_and_dual_banked_1rw_energy_tradeoff(self):
        b2_1rw = b2_ppa.model_b2_sku(
            "aigpu-b2",
            node_id="n4p_est",
            tmem_port_mode="dual_banked_1rw",
            measured=self.measured,
        )
        b2_1r1w = b2_ppa.model_b2_sku(
            "aigpu-b2",
            node_id="n4p_est",
            tmem_port_mode="native_1r1w",
            measured=self.measured,
        )
        tmem_arch = b2_1rw["area_and_shoreline"]["sram_budget"]["tmem_architecture"]
        # 128 cores * 32 banks/core * 8 B/cycle * 2.0 GHz = 65.536 TB/s
        self.assertEqual(tmem_arch["banks_per_core"], 32)
        self.assertAlmostEqual(tmem_arch["aggregate_bw_tbps_per_die_at_target_clk"], 65.536, places=6)
        self.assertGreater(tmem_arch["area_savings_pct"], 15.0)
        self.assertLess(
            b2_1rw["power_and_thermal"]["selected_workload_power"]["dynamic_tmem_w"],
            b2_1r1w["power_and_thermal"]["selected_workload_power"]["dynamic_tmem_w"],
        )
        self.assertLess(
            b2_1rw["area_and_shoreline"]["per_die_area_breakdown_mm2"]["total_die_area_mm2"],
            b2_1r1w["area_and_shoreline"]["per_die_area_breakdown_mm2"]["total_die_area_mm2"],
        )

    def test_workload_profiles_power_breakdown_and_thermal_margins(self):
        # Verify all 5 workloads across all 3 SKUs on n4p_est
        for sid in b2_ppa.VALID_SKUS:
            prev_power = -1.0
            for wid in ("idle", "llm_decode", "llm_prefill_fp4", "llm_prefill_fp8", "peak_tdp_stress"):
                model = b2_ppa.model_b2_sku(
                    sid,
                    node_id="n4p_est",
                    workload_id=wid,
                    measured=self.measured,
                )
                pt = model["power_and_thermal"]
                wl_power = pt["selected_workload_power"]["total_power_w"]
                self.assertEqual(pt["selected_workload"], wid)
                self.assertAlmostEqual(
                    wl_power,
                    pt["all_workloads_power"][wid]["total_power_w"],
                    places=9,
                )
                self.assertGreater(wl_power, prev_power)
                prev_power = wl_power

                # Check liquid-cooled T_j at workload is bounded and consistent
                dlc = pt["thermal_envelopes"]["liquid_cooled"]
                self.assertAlmostEqual(
                    dlc["tj_at_selected_workload_c"],
                    dlc["ambient_c"] + wl_power * dlc["r_theta_ja_c_per_w"],
                    places=6,
                )
                self.assertTrue(dlc["tj_at_selected_workload_c"] <= dlc["max_tj_c"])

        # Decode should have higher HBM I/O power share than compute TCU share
        b2_decode = b2_ppa.model_b2_sku(
            "aigpu-b2",
            node_id="n4p_est",
            workload_id="llm_decode",
            measured=self.measured,
        )
        b2_prefill = b2_ppa.model_b2_sku(
            "aigpu-b2",
            node_id="n4p_est",
            workload_id="llm_prefill_fp8",
            measured=self.measured,
        )
        dec_pb = b2_decode["power_and_thermal"]["selected_workload_power"]
        pre_pb = b2_prefill["power_and_thermal"]["selected_workload_power"]
        self.assertGreater(dec_pb["hbm3e_io_and_phy_w"], pre_pb["hbm3e_io_and_phy_w"])
        self.assertGreater(pre_pb["dynamic_compute_tcu_w"], dec_pb["dynamic_compute_tcu_w"])

    def test_wafer_stepper_geometry_and_boundary_cases(self):
        # Monotonicity of gross dies per 300mm wafer with die size
        d_small = b2_ppa.gross_dies_per_300mm_wafer(4.0, 4.0)
        d_med = b2_ppa.gross_dies_per_300mm_wafer(15.0, 15.0)
        d_large = b2_ppa.gross_dies_per_300mm_wafer(26.0, 31.0)
        self.assertGreater(d_small, d_med)
        self.assertGreater(d_med, d_large)
        self.assertGreater(d_large, 50)

        # Die larger than usable wafer diameter fits 0 dies
        self.assertEqual(b2_ppa.gross_dies_per_300mm_wafer(305.0, 305.0), 0)
        # Zero edge exclusion or tiny wafer returns 0 when unusable
        self.assertEqual(
            b2_ppa.gross_dies_per_300mm_wafer(10.0, 10.0, wafer_diameter_mm=10.0, edge_exclusion_mm=6.0),
            0,
        )

        # Zero defect density yields 100% silicon die yield
        yc_zero = b2_ppa.compute_b2_yield_and_cost(
            b2_ppa.B2_SKU_SPECS["aigpu-b2"],
            b2_ppa.NODE_SPECS["n4p_est"],
            self.reports["n4p_est"]["b2_skus"]["aigpu-b2"]["area_and_shoreline"],
            d0_sweep=(0.0,),
        )
        pt0 = yc_zero["d0_sweep"][0]
        self.assertAlmostEqual(pt0["murphy_yield_unrepaired"], 1.0, places=9)
        self.assertAlmostEqual(pt0["negbin_yield_sram_repaired"], 1.0, places=9)

    def test_ridge_points_tco_and_sku_spec_validation(self):
        n4p = self.reports["n4p_est"]
        b2 = n4p["b2_skus"]["aigpu-b2"]
        b2_dual = n4p["b2_skus"]["aigpu-b2-dual"]
        b2_tc = b2["compute_and_formats"]["tensor_compute"]
        dual_tc = b2_dual["compute_and_formats"]["tensor_compute"]

        # Ridge point = peak_tflops / bw_tbps stays invariant between 1-die and 2-die (both scale 2x)
        for fmt in ("fp16_bf16", "fp8", "nvfp4"):
            self.assertAlmostEqual(
                b2_tc[fmt]["dense_ridge_ops_per_byte"],
                dual_tc[fmt]["dense_ridge_ops_per_byte"],
                places=6,
            )
            self.assertAlmostEqual(
                b2_tc[fmt]["sparse_2_4_ridge_ops_per_byte"],
                2.0 * b2_tc[fmt]["dense_ridge_ops_per_byte"],
                places=6,
            )

        # TCO comparison checks
        tco_cmp = n4p["tco_and_efficiency_comparison"]
        b2_tco = tco_cmp["skus"]["aigpu-b2"]
        dual_tco = tco_cmp["skus"]["aigpu-b2-dual"]
        self.assertGreater(b2_tco["total_3yr_tco_usd_est"], b2_tco["capex_usd_est"])
        self.assertGreater(dual_tco["total_3yr_tco_usd_est"], b2_tco["total_3yr_tco_usd_est"])
        self.assertLess(b2_tco["usd_per_fp8_pflops_hr"], b2_tco["usd_per_fp16_pflops_hr"])
        self.assertLess(b2_tco["usd_per_fp4_pflops_hr"], b2_tco["usd_per_fp8_pflops_hr"])

        # Synthetic bad B2SkuSpec must be caught by validate_sku_spec
        bad_mesh_sku = b2_ppa.B2SkuSpec(
            **{
                **b2_ppa.B2_SKU_SPECS["aigpu-b2"].__dict__,
                "noc_mesh_rows": 1,
                "noc_mesh_cols": 2,
            }
        )
        with self.assertRaisesRegex(ValueError, "NoC mesh"):
            b2_ppa.validate_sku_spec(bad_mesh_sku)

        bad_hbm_sku = b2_ppa.B2SkuSpec(
            **{
                **b2_ppa.B2_SKU_SPECS["aigpu-b2"].__dict__,
                "hbm3e_stacks_per_die": 7,
            }
        )
        with self.assertRaisesRegex(ValueError, "even"):
            b2_ppa.validate_sku_spec(bad_hbm_sku)

    def test_single_sku_report_and_markdown_table_consistency(self):
        rep = b2_ppa.build_b2_ppa_report(
            node_id="n4p_est",
            sku_filter="aigpu-b2-dual",
            workload_id="llm_prefill_fp4",
            dvfs_bin="efficiency_bin",
        )
        self.assertEqual(set(rep["b2_skus"].keys()), {"aigpu-b2-dual"})
        self.assertEqual(rep["dvfs_bin"], "efficiency_bin")
        md = b2_ppa.format_b2_markdown(rep, include_yield_sweep=False)
        self.assertIn("aigpu-b2-dual", md)
        self.assertNotIn("300mm Wafer Yield & KGD Cost Sweep", md)
        self.assertIn("Generational Scaling (`aigpu-b1` -> `aigpu-b2`", md)

    def test_cross_module_spec_alignment_with_arch_spec_and_profiles(self):
        profiles_dir = ROOT / "profiles"
        for sid in b2_ppa.VALID_SKUS:
            ppa_sku = b2_ppa.B2_SKU_SPECS[sid]
            arch_sku = b2_arch_spec.SKU_SPECS[sid]
            profile = json.loads((profiles_dir / f"{sid}.json").read_text(encoding="utf-8"))
            core_cfg = profile.get("core", {})
            if "extends" in profile:
                parent_profile = json.loads((profiles_dir / f"{profile['extends']}.json").read_text(encoding="utf-8"))
                merged_core = dict(parent_profile.get("core", {}))
                merged_core.update(core_cfg)
                core_cfg = merged_core

            with self.subTest(sku=sid):
                self.assertEqual(ppa_sku.l1_dcache_kib_per_core * 1024, arch_sku.l1_dcache_bytes_per_core)
                if "VX_CFG_DCACHE_SIZE" in core_cfg:
                    self.assertEqual(ppa_sku.l1_dcache_kib_per_core * 1024, core_cfg["VX_CFG_DCACHE_SIZE"])
                self.assertEqual(ppa_sku.vortex_fedp_2k, arch_sku.tcu_fedp2k)
                expected_fedp2k = bool(core_cfg.get("VX_CFG_TCU_FEDP2K", 0))
                self.assertEqual(ppa_sku.vortex_fedp_2k, expected_fedp2k)
                self.assertEqual(ppa_sku.tmem_banks_per_core, b2_arch_spec.TMEM_SPEC.num_banks)
                if sid == "aigpu-b2-tile":
                    self.assertEqual(ppa_sku.ucie_bw_tbps_per_die, 0.0)
                    self.assertEqual(arch_sku.ucie_d2d_bandwidth_gbs, 0.0)
                    self.assertEqual(ppa_sku.noc_mesh_rows, arch_sku.noc_mesh_rows)
                    self.assertEqual(ppa_sku.noc_mesh_cols, arch_sku.noc_mesh_cols)
                else:
                    self.assertEqual(ppa_sku.noc_mesh_rows, 4)
                    self.assertEqual(ppa_sku.noc_mesh_cols, 2)
                    self.assertEqual(b2_arch_spec.NOC_SPECS["aigpu-b2"].rows, ppa_sku.noc_mesh_rows)
                    self.assertEqual(b2_arch_spec.NOC_SPECS["aigpu-b2"].cols, ppa_sku.noc_mesh_cols)

                # MXFP6 dense TFLOPS uses 2.0x FP16 ratio matching b2_arch_spec
                mxfp6_ratio = b2_arch_spec.NUMERIC_FORMATS["MXFP6_E2M3"].fp16_throughput_multiplier
                self.assertEqual(mxfp6_ratio, 2.0)
                tc = self.reports["n4p_est"]["b2_skus"][sid]["compute_and_formats"]["tensor_compute"]
                self.assertAlmostEqual(
                    tc["mxfp6"]["tfr_v2_architectural_dense"],
                    tc["fp16_bf16"]["tfr_v2_architectural_dense"] * mxfp6_ratio,
                    places=6,
                )

    def test_pdn_ir_drop_monotonicity_across_dvfs_bins(self):
        for node_id in b2_ppa.VALID_NODES:
            for sid in b2_ppa.VALID_SKUS:
                with self.subTest(node=node_id, sku=sid):
                    ir_by_bin: dict[str, float] = {}
                    curr_by_bin: dict[str, float] = {}
                    for bid in ("efficiency_bin", "nominal", "boost_odv"):
                        sm = b2_ppa.model_b2_sku(
                            sid,
                            node_id=node_id,
                            dvfs_bin=bid,
                            measured=self.measured,
                        )
                        pkg = sm["power_and_thermal"]["packaging_and_pdn"]
                        ir_by_bin[bid] = pkg["estimated_pdn_ir_drop_mv"]
                        curr_by_bin[bid] = pkg["peak_package_current_a"]
                    self.assertLess(curr_by_bin["efficiency_bin"], curr_by_bin["nominal"])
                    self.assertLess(curr_by_bin["nominal"], curr_by_bin["boost_odv"])
                    self.assertLess(ir_by_bin["efficiency_bin"], ir_by_bin["nominal"])
                    self.assertLess(ir_by_bin["nominal"], ir_by_bin["boost_odv"])
                    expected_nom_ir = 9.0 if sid == "aigpu-b2-tile" else 18.5
                    self.assertAlmostEqual(ir_by_bin["nominal"], expected_nom_ir, places=6)
                    self.assertAlmostEqual(
                        ir_by_bin["boost_odv"] / ir_by_bin["nominal"],
                        curr_by_bin["boost_odv"] / curr_by_bin["nominal"],
                        places=9,
                    )


if __name__ == "__main__":
    unittest.main()

