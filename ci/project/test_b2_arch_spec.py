#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Comprehensive unit tests for aigpu-b2 profiles, profile_check extension, and b2_arch_spec."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b2_arch_spec as spec
import b2_program_tracker as tracker


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "VX_config.toml"
PROFILES_DIR = ROOT / "profiles"


def _load_module(name: str, path: Path):
    spec_obj = importlib.util.spec_from_file_location(name, path)
    if spec_obj is None or spec_obj.loader is None:
        raise RuntimeError(f"Could not import {path}")
    mod = importlib.util.module_from_spec(spec_obj)
    sys.modules[name] = mod
    spec_obj.loader.exec_module(mod)
    return mod


gen_config = _load_module("test_b2_gen_config", ROOT / "ci/gen_config.py")
profile_check = _load_module("test_b2_profile_check", ROOT / "ci/profile_check.py")


class TestB2ProfilesAndGenConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.toml = gen_config._load_toml(str(CONFIG_PATH))
        cls.defaults, _ = gen_config._flatten_with_layout(cls.toml)
        cls.enums = gen_config._load_enums(cls.toml)
        cls.builtins = gen_config._load_var_table(cls.toml, "builtin")
        cls.params = gen_config._load_var_table(cls.toml, "param")
        cls.read_only = set(cls.builtins) | set(cls.params)

    def _run_gen_config_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(ROOT / "ci/gen_config.py"), "--config", str(CONFIG_PATH), *args]
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)

    def test_all_three_b2_profiles_pass_gen_config_cli(self):
        for profile_name in ("aigpu-b2", "aigpu-b2-dual", "aigpu-b2-tile"):
            with self.subTest(profile=profile_name):
                proc = self._run_gen_config_cli(
                    "--profile", profile_name,
                    "--xlen", "64",
                    "-f", "cflags",
                    "--cflags", "-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64",
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                toks = shlex.split(proc.stdout)
                self.assertIn("-DVX_CFG_XLEN=64", toks)
                self.assertIn("-DVX_CFG_TCU_TYPE=TFR", toks)
                self.assertIn("-DVX_CFG_FPU_TYPE=STD", toks)
                self.assertIn("-DVX_CFG_EXT_TCU_ENABLE", toks)
                self.assertIn("-DVX_CFG_TCU_WGMMA_ENABLE", toks)
                self.assertIn("-DVX_CFG_EXT_DXA_ENABLE", toks)
                self.assertIn("-DVX_CFG_EXT_MUFU_ENABLE", toks)
                self.assertIn("-DVX_CFG_EXT_A_ENABLE", toks)
                self.assertIn("-DVX_CFG_EXT_TEX_ENABLED=0", toks)
                self.assertIn("-DVX_CFG_EXT_RASTER_ENABLED=0", toks)
                self.assertIn("-DVX_CFG_EXT_OM_ENABLED=0", toks)
                self.assertIn("-DVX_CFG_EXT_RTU_ENABLED=0", toks)

    def test_b2_profiles_reject_xlen_32_and_emit_cpp_and_verilog_headers(self):
        for profile_name in ("aigpu-b2", "aigpu-b2-dual", "aigpu-b2-tile"):
            with self.subTest(profile=profile_name):
                bad = self._run_gen_config_cli(
                    "--profile", profile_name, "--xlen", "32", "--merge-configs"
                )
                self.assertNotEqual(bad.returncode, 0)
                for fmt in ("cpp", "verilog"):
                    proc = self._run_gen_config_cli(
                        "--profile", profile_name,
                        "--xlen", "64",
                        "-f", fmt,
                        "--resolved",
                        "--cflags", "-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64",
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertTrue(proc.stdout.strip())

    def test_b2_profiles_schema_top_keys_and_sources_present(self):
        allowed_top = {
            "name", "extends", "description", "xlen",
            "core", "chip", "platform", "reference", "sources",
        }
        for profile_name in ("aigpu-b2", "aigpu-b2-dual", "aigpu-b2-tile"):
            with self.subTest(profile=profile_name):
                raw = json.loads((PROFILES_DIR / f"{profile_name}.json").read_text(encoding="utf-8"))
                self.assertTrue(set(raw.keys()).issubset(allowed_top))
                self.assertIn("sources", raw)
                self.assertTrue(raw["sources"])
                self.assertIn("not measured physical silicon", raw["sources"]["evidence_status"].lower())
                prof = gen_config.load_profile(profile_name, str(PROFILES_DIR))
                gen_config.validate_profile(prof, self.defaults, self.enums, self.read_only)

    def test_aigpu_b2_and_dual_knobs_and_tile_rtl_safety(self):
        resolved = spec.validate_b2_profiles_against_gen_config()
        b2 = resolved["aigpu-b2"]
        dual = resolved["aigpu-b2-dual"]
        tile = resolved["aigpu-b2-tile"]

        self.assertEqual(b2["VX_CFG_NUM_CLUSTERS"], 8)
        self.assertEqual(b2["VX_CFG_NUM_CORES"], 16)
        self.assertEqual(b2["VX_CFG_NUM_CLUSTERS"] * b2["VX_CFG_NUM_CORES"], 128)
        self.assertEqual(b2["VX_CFG_TCU_PE_RATIO"], 1)
        self.assertEqual(b2["VX_CFG_TCU_FEDP2K"], 1)
        self.assertEqual(b2["VX_CFG_L2_SIZE"], 134217728)
        self.assertEqual(b2["VX_CFG_PLATFORM_MEMORY_TYPE"], "HBM3")
        self.assertEqual(b2["VX_CFG_PLATFORM_MEMORY_PEAK_BW"], 4000000)

        self.assertEqual(dual["VX_CFG_NUM_CLUSTERS"], 16)
        self.assertEqual(dual["VX_CFG_NUM_CORES"], 16)
        self.assertEqual(dual["VX_CFG_NUM_CLUSTERS"] * dual["VX_CFG_NUM_CORES"], 256)
        self.assertEqual(dual["VX_CFG_L2_SIZE"], 268435456)
        self.assertEqual(dual["VX_CFG_L2_NUM_BANKS"], 128)
        self.assertEqual(dual["VX_CFG_PLATFORM_MEMORY_PEAK_BW"], 8000000)
        self.assertEqual(dual["VX_CFG_PLATFORM_MEMORY_NUM_BANKS"], 128)

        self.assertEqual(tile["VX_CFG_NUM_CLUSTERS"], 1)
        self.assertEqual(tile["VX_CFG_NUM_CORES"], 4)
        self.assertEqual(tile["VX_CFG_SOCKET_SIZE"], 4)
        self.assertEqual(tile["VX_CFG_NUM_WARPS"], 8)
        self.assertEqual(tile["VX_CFG_NUM_THREADS"], 8)
        self.assertEqual(tile["VX_CFG_ISSUE_WIDTH"], 2)
        self.assertEqual(tile["VX_CFG_L2_SIZE"], 262144)
        # Tile leaves FEDP2K off so stock rtlsim demo/sgemm_tcu remain clean
        self.assertIs(tile["VX_CFG_TCU_FEDP2K"], False)
        self.assertLessEqual(tile["VX_CFG_LMEM_LOG_SIZE"], 18)


class TestProfileCheckExtension(unittest.TestCase):
    def test_profile_check_zero_error_on_b2_and_b1_profiles(self):
        for profile_name in ("aigpu-b2", "aigpu-b2-dual", "aigpu-b2-tile", "aigpu-b1", "aigpu-b1-tile"):
            with self.subTest(profile=profile_name):
                data, reference = profile_check.load_profile(profile_name)
                cfg = profile_check.resolved_config(profile_name, data["xlen"])
                measured = profile_check.peak_metrics(cfg, reference)
                self.assertEqual(set(measured), set(reference))
                for key, model_val in measured.items():
                    self.assertAlmostEqual(float(model_val), float(reference[key]), places=6)

    def test_profile_check_backward_compatible_across_all_repo_profiles(self):
        for path in sorted(PROFILES_DIR.glob("*.json")):
            name = path.stem
            with self.subTest(profile=name):
                data, ref = profile_check.load_profile(name)
                xlen = data.get("xlen") or 64
                cfg = profile_check.resolved_config(name, xlen)
                measured = profile_check.peak_metrics(cfg, ref)
                for key, model_val in measured.items():
                    ref_val = ref[key]
                    rel_err = abs(float(model_val) - float(ref_val)) / float(ref_val)
                    self.assertLessEqual(rel_err, 0.05, f"{name}.{key}: {model_val} vs {ref_val}")

    def test_profile_check_optional_keys_only_emitted_when_requested(self):
        cfg = profile_check.resolved_config("aigpu-b1", 64)
        measured = profile_check.peak_metrics(cfg, {"fp32_lanes": 8192})
        self.assertEqual(set(measured.keys()), {"fp32_lanes"})
        self.assertNotIn("num_cores", measured)
        self.assertNotIn("l2_size_mib", measured)
        self.assertNotIn("tcu_blocks_total", measured)


class TestThroughputReconciliationAndFormats(unittest.TestCase):
    def test_vortex_base_vs_tfrv2_reconciliation_all_skus(self):
        b2_rec = spec.build_throughput_reconciliation("aigpu-b2")
        self.assertAlmostEqual(b2_rec["vortex_base_tfr_fp16_tflops"], 1048.576, places=3)
        self.assertAlmostEqual(b2_rec["tfrv2_dense_fp16_tflops"], 1152.0, places=3)
        self.assertAlmostEqual(b2_rec["tfrv2_dense_fp8_tflops"], 2304.0, places=3)
        self.assertAlmostEqual(b2_rec["tfrv2_dense_fp4_tops"], 4608.0, places=3)
        self.assertAlmostEqual(b2_rec["tfrv2_sparse_2_4_fp4_tops"], 9216.0, places=3)

        dual_rec = spec.build_throughput_reconciliation("aigpu-b2-dual")
        self.assertAlmostEqual(dual_rec["vortex_base_tfr_fp16_tflops"], 2097.152, places=3)
        self.assertAlmostEqual(dual_rec["tfrv2_dense_fp16_tflops"], 2304.0, places=3)
        self.assertAlmostEqual(dual_rec["tfrv2_dense_fp8_tflops"], 4608.0, places=3)
        self.assertAlmostEqual(dual_rec["tfrv2_dense_fp4_tops"], 9216.0, places=3)
        self.assertAlmostEqual(dual_rec["tfrv2_sparse_2_4_fp4_tops"], 18432.0, places=3)

        tile_rec = spec.build_throughput_reconciliation("aigpu-b2-tile")
        self.assertAlmostEqual(tile_rec["vortex_base_tfr_fp16_tflops"], 0.2048, places=4)
        self.assertAlmostEqual(tile_rec["tfrv2_dense_fp16_tflops"], 18.0, places=3)
        self.assertAlmostEqual(tile_rec["tfrv2_dense_fp8_tflops"], 36.0, places=3)
        self.assertAlmostEqual(tile_rec["tfrv2_dense_fp4_tops"], 72.0, places=3)

    def test_tfrv2_numeric_formats_complete_and_valid(self):
        expected = {
            "FP16", "BF16", "TF32", "FP8_E4M3", "FP8_E5M2",
            "MXFP8", "MXFP6_E2M3", "MXFP6_E3M2", "MXFP4_E2M1", "NVFP4_E2M1", "INT8",
        }
        self.assertEqual(set(spec.NUMERIC_FORMATS.keys()), expected)
        self.assertEqual(spec.validate_numeric_formats(), [])
        self.assertEqual(spec.NUMERIC_FORMATS["NVFP4_E2M1"].scale_factor_type, "E4M3")
        self.assertEqual(spec.NUMERIC_FORMATS["NVFP4_E2M1"].scale_block_size, 16)
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP4_E2M1"].scale_factor_type, "UE8M0")
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP4_E2M1"].scale_block_size, 32)
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP6_E2M3"].bitwidth, 6)
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP6_E3M2"].exponent_bias, 3)


class TestTmemNocCoherenceAndDxa(unittest.TestCase):
    def test_tmem_geometry_and_swizzle_conflict_elimination(self):
        self.assertEqual(spec.TMEM_SPEC.capacity_bytes_per_core, 262144)
        self.assertEqual(
            spec.TMEM_SPEC.lanes_rows * spec.TMEM_SPEC.columns * spec.TMEM_SPEC.cell_width_bytes,
            spec.TMEM_SPEC.capacity_bytes_per_core,
        )
        # Same-column read across 32 rows conflicts 32-way with NONE, 0 conflicts with SWIZZLE_128B
        coords = [(r, 7) for r in range(32)]
        res_none = spec.analyze_tmem_bank_conflicts(coords, swizzle_mode="NONE")
        self.assertFalse(res_none["conflict_free"])
        self.assertEqual(res_none["conflict_ways"], 32)
        res_128 = spec.analyze_tmem_bank_conflicts(coords, swizzle_mode="SWIZZLE_128B")
        self.assertTrue(res_128["conflict_free"])
        self.assertEqual(res_128["distinct_banks"], 32)

        # Row-major read across 32 columns is always conflict-free
        row_coords = [(5, c) for c in range(32)]
        for mode in spec.TMEM_SPEC.supported_swizzle_modes:
            res_row = spec.analyze_tmem_bank_conflicts(row_coords, swizzle_mode=mode)
            self.assertTrue(res_row["conflict_free"], mode)

    def test_tmem_allocation_bounds_and_alignment(self):
        alloc = spec.validate_tmem_allocation(0, 128, num_rows=128)
        self.assertEqual(alloc["allocated_bytes"], 65536)
        self.assertTrue(alloc["double_buffer_feasible"])
        with self.assertRaises(ValueError):
            spec.validate_tmem_allocation(16, 64)  # unaligned to 32 columns
        with self.assertRaises(ValueError):
            spec.validate_tmem_allocation(0, 48)  # non-power-of-two
        with self.assertRaises(ValueError):
            spec.validate_tmem_allocation(384, 256)  # overflows 512 columns

    def test_noc_xy_routing_deadlock_free_and_home_node_hash(self):
        for sku_id, noc in spec.NOC_SPECS.items():
            with self.subTest(sku=sku_id):
                res = spec.verify_xy_routing_deadlock_free(noc.rows, noc.cols)
                self.assertTrue(res["deadlock_free"])
                self.assertEqual(res["pairs_checked"], (noc.rows * noc.cols) ** 2)

        # Verify uniform slice & dual-die distribution across consecutive 256B-aligned blocks
        dies = {spec.compute_home_node(i * 256, num_dies=2)["die_id"] for i in range(64)}
        slices = {spec.compute_home_node(i * 256, num_dies=1)["slice_id"] for i in range(64)}
        self.assertEqual(dies, {0, 1})
        self.assertEqual(slices, set(range(8)))

    def test_dxa_5d_descriptor_and_hbm3e_decomp_specs(self):
        ok = spec.validate_dxa_5d_descriptor(
            global_dims=(128, 256, 64, 4, 2),
            box_dims=(64, 32, 16, 1, 1),
            element_strides=(1, 128, 128 * 256, 128 * 256 * 64, 128 * 256 * 64 * 4),
            element_bytes=2.0,
            swizzle_mode="SWIZZLE_128B",
            multicast_clusters=4,
        )
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["box_bytes"], 64 * 32 * 16 * 2)
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1, 1),
                box_dims=(5, 16, 1, 1, 1),  # 5 * 1.0 = 5 bytes, not 16B-aligned for swizzle
                element_strides=(1, 64, 4096, 4096, 4096),
                element_bytes=1.0,
                swizzle_mode="SWIZZLE_64B",
            )
        self.assertEqual(spec.HBM3E_SPEC.pseudo_channels_per_stack, 8)
        self.assertEqual(set(spec.DECOMP_CODECS.keys()), {"LZ4", "SNAPPY", "DEFLATE", "BITCOMP"})


class TestMmioMigPcieIommuRasAndHonesty(unittest.TestCase):
    def test_mmio_map_non_overlapping_and_doorbells(self):
        self.assertEqual(spec.validate_mmio_map(), [])
        self.assertEqual(spec.gigathread_doorbell_address(0), 0x0005_0000)
        self.assertEqual(spec.gigathread_doorbell_address(63), 0x0005_0000 + 63 * 4096)
        with self.assertRaises(ValueError):
            spec.gigathread_doorbell_address(64)

    def test_mig_partition_validator_catches_overlaps(self):
        good = [
            spec.MigAllocation(0, "4g.48gb", 0x0F, 0x00FF, 0x0F, 0x0000_0000_FFFF_FFFF),
            spec.MigAllocation(1, "4g.48gb", 0xF0, 0xFF00, 0xF0, 0xFFFF_FFFF_0000_0000),
        ]
        self.assertEqual(spec.validate_mig_partition_plan(good, num_dies=1), [])

        overlap = [
            spec.MigAllocation(0, "4g.48gb", 0x0F, 0x00FF, 0x0F, 0x0000_0000_FFFF_FFFF),
            spec.MigAllocation(1, "4g.48gb", 0xF1, 0xFF00, 0xF0, 0xFFFF_FFFF_0000_0000),  # cluster 0 overlaps
        ]
        errs = spec.validate_mig_partition_plan(overlap, num_dies=1)
        self.assertTrue(any("overlapping cluster_mask" in e for e in errs))

    def test_sv48_pte_roundtrip_and_out_of_range(self):
        pte = spec.encode_sv48_pte(0xABCDE1234, read=True, write=False, exec_perm=True, user=True, encrypted=True)
        dec = spec.decode_sv48_pte(pte)
        self.assertTrue(dec["valid"])
        self.assertTrue(dec["read"])
        self.assertFalse(dec["write"])
        self.assertTrue(dec["exec"])
        self.assertTrue(dec["encrypted"])
        self.assertEqual(dec["ppn"], 0xABCDE1234)
        with self.assertRaises(ValueError):
            spec.encode_sv48_pte(1 << 44)

    def test_honesty_invariants_and_cli_outputs(self):
        report = spec.validate_all_contracts()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["evidence_level"], "source_present")
        self.assertIs(report["silicon_measured"], False)
        self.assertIs(report["foundry_signoff"], False)
        self.assertIs(report["fpga_measured"], False)

        for bad_key in ("silicon_measured", "foundry_signoff", "fpga_measured"):
            forged = copy.deepcopy(report)
            forged[bad_key] = True
            with self.assertRaises(ValueError):
                spec.validate_honesty_metadata(forged)

        buf_json = io.StringIO()
        with redirect_stdout(buf_json):
            rc = spec.main(["--sku", "aigpu-b2", "--json", "--validate-profiles"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf_json.getvalue())
        self.assertIn("aigpu-b2", parsed["skus"])
        self.assertTrue(parsed["contract_validation"]["ok"])

        buf_md = io.StringIO()
        with redirect_stdout(buf_md):
            rc_md = spec.main([])
        self.assertEqual(rc_md, 0)
        self.assertIn("AI-GPU B2 Architecture Specification Summary", buf_md.getvalue())
        self.assertIn("silicon_measured=False", buf_md.getvalue())

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "spec.json"
            rc_out = spec.main(["--check-contracts", "--output", str(out_path)])
            self.assertEqual(rc_out, 0)
            self.assertTrue(json.loads(out_path.read_text(encoding="utf-8"))["ok"])

    def test_anti_bloat_and_zero_task_wave_comments(self):
        prod_file = ROOT / "ci/project/b2_arch_spec.py"
        self.assertEqual(tracker.check_file_anti_bloat(prod_file), [])
        lines = prod_file.read_text(encoding="utf-8").splitlines()
        substantive = [ln for ln in lines if tracker.is_substantive_line(ln, ".py")]
        self.assertGreaterEqual(len(substantive), 1300)


class TestExtendedCrossPillarContracts(unittest.TestCase):
    def test_tmem_swizzle_bijectivity_across_all_rows_and_modes(self):
        # For every swizzle mode and every row, 32 consecutive columns must map bijectively to 32 banks
        for mode in spec.TMEM_SPEC.supported_swizzle_modes:
            for row in range(0, spec.TMEM_SPEC.lanes_rows, 7):
                banks = {spec.tmem_swizzled_bank(row, col, mode) for col in range(32)}
                self.assertEqual(banks, set(range(32)), f"Non-bijective row={row} mode={mode}")

        # Bounds checking on row/col/mode
        with self.assertRaises(ValueError):
            spec.tmem_swizzled_bank(-1, 0, "NONE")
        with self.assertRaises(ValueError):
            spec.tmem_swizzled_bank(128, 0, "NONE")
        with self.assertRaises(ValueError):
            spec.tmem_swizzled_bank(0, 512, "NONE")
        with self.assertRaises(ValueError):
            spec.tmem_swizzled_bank(0, 0, "SWIZZLE_256B")

    def test_tmem_bank_conflict_analyzer_strided_patterns(self):
        # Stride-2 across 32 columns in same row hits 16 distinct banks => 2-way conflict
        stride2 = [(0, (c * 2) % 64) for c in range(32)]
        res = spec.analyze_tmem_bank_conflicts(stride2, swizzle_mode="NONE")
        self.assertEqual(res["distinct_banks"], 16)
        self.assertEqual(res["conflict_ways"], 2)
        self.assertFalse(res["conflict_free"])

        # SWIZZLE_32B eliminates conflicts across 8 rows of same column, but 16 rows still 2-way
        col_8 = [(r, 0) for r in range(8)]
        self.assertTrue(spec.analyze_tmem_bank_conflicts(col_8, swizzle_mode="SWIZZLE_32B")["conflict_free"])
        col_16 = [(r, 0) for r in range(16)]
        self.assertFalse(spec.analyze_tmem_bank_conflicts(col_16, swizzle_mode="SWIZZLE_32B")["conflict_free"])
        self.assertTrue(spec.analyze_tmem_bank_conflicts(col_16, swizzle_mode="SWIZZLE_64B")["conflict_free"])
        with self.assertRaises(ValueError):
            spec.analyze_tmem_bank_conflicts([])

    def test_noc_xy_routing_paths_and_boundaries(self):
        path = spec.compute_xy_route((0, 0), (1, 3), rows=4, cols=2)
        self.assertEqual(path, [(0, 0), (1, 0), (1, 1), (1, 2), (1, 3)])
        rev = spec.compute_xy_route((1, 3), (0, 0), rows=4, cols=2)
        self.assertEqual(rev, [(1, 3), (0, 3), (0, 2), (0, 1), (0, 0)])
        same = spec.compute_xy_route((1, 2), (1, 2), rows=4, cols=2)
        self.assertEqual(same, [(1, 2)])
        with self.assertRaises(ValueError):
            spec.compute_xy_route((2, 0), (0, 0), rows=4, cols=2)
        with self.assertRaises(ValueError):
            spec.compute_xy_route((0, 0), (0, 4), rows=4, cols=2)

    def test_moesi_directory_and_ucie_d2d_consistency(self):
        self.assertEqual(spec.MOESI_SPEC.states, ("M", "O", "E", "S", "I"))
        self.assertEqual(
            spec.MOESI_SPEC.slices_per_die * spec.MOESI_SPEC.slice_capacity_bytes,
            spec.SKU_SPECS["aigpu-b2"].l2_total_bytes,
        )
        self.assertEqual(
            spec.MOESI_SPEC.slices_per_die * spec.MOESI_SPEC.banks_per_slice,
            spec.SKU_SPECS["aigpu-b2"].l2_banks_total,
        )
        # Dual-die home node global_slice_id spans 0..15 across 2 dies
        seen_global = {
            spec.compute_home_node(i * 256, num_dies=2, slices_per_die=8)["global_slice_id"]
            for i in range(256)
        }
        self.assertEqual(seen_global, set(range(16)))
        with self.assertRaises(ValueError):
            spec.compute_home_node(-1)
        with self.assertRaises(ValueError):
            spec.compute_home_node(0, num_dies=4)
        with self.assertRaises(ValueError):
            spec.compute_home_node(0, slices_per_die=6)

        # UCIe bandwidth & protocol efficiency math
        raw_calc = (
            spec.UCIE_SPEC.total_lanes_bidirectional
            * spec.UCIE_SPEC.data_rate_gt_per_pin
            / 8.0
        )
        self.assertAlmostEqual(raw_calc, spec.UCIE_SPEC.raw_bandwidth_gbs_total, places=3)
        self.assertAlmostEqual(
            spec.UCIE_SPEC.raw_bandwidth_gbs_total * spec.UCIE_SPEC.protocol_efficiency,
            spec.UCIE_SPEC.effective_bandwidth_gbs_total,
            places=2,
        )

    def test_hbm3e_jedec_timing_and_bandwidth_math(self):
        hbm = spec.HBM3E_SPEC
        self.assertEqual(hbm.t_rc_ck, hbm.t_ras_ck + hbm.t_rp_ck)
        self.assertLessEqual(hbm.t_rrd_s_ck, hbm.t_rrd_l_ck)
        self.assertGreaterEqual(hbm.t_faw_ck, 4 * hbm.t_rrd_s_ck)
        # Per-stack bandwidth: 1024 pins * 3.90625 Gbps / 8 = 500 GB/s/stack -> 8 stacks = 4,000 GB/s
        self.assertAlmostEqual(hbm.pin_rate_gbps, 3.90625, places=6)
        self.assertEqual(hbm.burst_length, 4)
        self.assertEqual(hbm.burst_length * hbm.pc_width_bits // 8, hbm.atom_bytes)
        per_stack_gbs = (hbm.stack_width_bits * hbm.pin_rate_gbps) / 8.0
        self.assertAlmostEqual(per_stack_gbs, 500.0, places=6)
        self.assertAlmostEqual(per_stack_gbs * spec.SKU_SPECS["aigpu-b2"].hbm_stacks, spec.SKU_SPECS["aigpu-b2"].hbm_bandwidth_gbs, places=6)
        self.assertAlmostEqual(per_stack_gbs * spec.SKU_SPECS["aigpu-b2-dual"].hbm_stacks, spec.SKU_SPECS["aigpu-b2-dual"].hbm_bandwidth_gbs, places=6)

    def test_decompression_descriptor_bit_layout_contiguous(self):
        expected_lsb = 0
        seen_ids = set()
        for name, lsb, msb, _ in spec.DECOMP_DESCRIPTOR_FIELDS:
            self.assertEqual(lsb, expected_lsb, f"Gap/overlap before {name}")
            self.assertGreaterEqual(msb, lsb)
            expected_lsb = msb + 1
        self.assertEqual(expected_lsb, 256)
        for codec in spec.DECOMP_CODECS.values():
            self.assertNotIn(codec.codec_id, seen_ids)
            seen_ids.add(codec.codec_id)
            self.assertTrue(codec.crc32c_verified)

    def test_dxa_5d_descriptor_validation_edge_cases(self):
        # Sub-byte FP4 descriptor (0.5 B/elem)
        fp4_ok = spec.validate_dxa_5d_descriptor(
            global_dims=(128, 64, 1, 1, 1),
            box_dims=(64, 32, 1, 1, 1),
            element_strides=(1, 128, 8192, 8192, 8192),
            element_bytes=0.5,
            swizzle_mode="SWIZZLE_32B",
            multicast_clusters=8,
        )
        self.assertEqual(fp4_ok["box_bytes"], 64 * 32 // 2)
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1),  # type: ignore[arg-type]
                box_dims=(32, 32, 1, 1, 1),
                element_strides=(1, 64, 4096, 4096, 4096),
                element_bytes=2.0,
            )
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1, 1),
                box_dims=(128, 32, 1, 1, 1),  # box > global
                element_strides=(1, 64, 4096, 4096, 4096),
                element_bytes=2.0,
            )
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1, 1),
                box_dims=(32, 32, 1, 1, 1),
                element_strides=(1, 64, 4096, 4096, 4096),
                element_bytes=8.0,
            )
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1, 1),
                box_dims=(32, 32, 1, 1, 1),
                element_strides=(1, 64, 4096, 4096, 4096),
                element_bytes=2.0,
                multicast_clusters=32,
            )

    def test_mig_profiles_scale_linearly_and_catch_invalid_masks(self):
        full = spec.MIG_PROFILES["8g.96gb"]
        for pid, prof in spec.MIG_PROFILES.items():
            with self.subTest(profile=pid):
                self.assertEqual(prof.clusters_per_instance * prof.max_instances, full.clusters_per_instance)
                self.assertEqual(prof.cores_per_instance * prof.max_instances, full.cores_per_instance)
                self.assertEqual(prof.l2_ways_per_instance * prof.max_instances, full.l2_ways_per_instance)
                self.assertEqual(prof.hbm_stacks_per_instance * prof.max_instances, full.hbm_stacks_per_instance)
                self.assertEqual(prof.cp_queues_per_instance * prof.max_instances, full.cp_queues_per_instance)

        # Wrong popcount & out-of-range masks caught
        bad_pop = [spec.MigAllocation(0, "2g.24gb", 0x01, 0x0F, 0x03, 0xFFFF)]
        self.assertTrue(any("cluster_mask popcount" in e for e in spec.validate_mig_partition_plan(bad_pop)))
        bad_range = [spec.MigAllocation(0, "1g.12gb", 1 << 9, 0x3, 0x1, 0xFF)]
        self.assertTrue(any("exceeds die clusters" in e for e in spec.validate_mig_partition_plan(bad_range)))
        bad_prof = [spec.MigAllocation(0, "3g.36gb", 0x7, 0x3F, 0x7, 0xFFFFFF)]
        self.assertTrue(any("Unknown MIG profile" in e for e in spec.validate_mig_partition_plan(bad_prof)))

    def test_pcie_bars_sv48_bits_ras_pmu_and_conf_comp(self):
        bar_names = {b["bar"] for b in spec.PCIE_BAR_LAYOUT}
        self.assertEqual(bar_names, {"BAR0", "BAR2", "BAR4"})
        # SV48 PTE bit ranges must not overlap
        occupied: set[int] = set()
        for fname, (lo, hi, _) in spec.SV48_PTE_BITS.items():
            for bit in range(lo, hi + 1):
                self.assertNotIn(bit, occupied, f"Overlap on SV48 bit {bit} ({fname})")
                occupied.add(bit)

        # RAS MCA bank IDs contiguous 0..7
        self.assertEqual([b["bank_id"] for b in spec.RAS_MCA_BANKS], list(range(8)))
        # PMU event IDs and names strictly unique
        ev_ids = [e["event_id"] for e in spec.PMU_EVENT_CATALOG]
        ev_names = [e["name"] for e in spec.PMU_EVENT_CATALOG]
        self.assertEqual(len(ev_ids), len(set(ev_ids)))
        self.assertEqual(len(ev_names), len(set(ev_names)))
        # Confidential computing cipher invariants
        self.assertEqual(spec.CONF_COMP_SPEC["memory_encryption_cipher"], "AES-256-GCM")
        self.assertEqual(spec.CONF_COMP_SPEC["key_slots"], 64)
        self.assertTrue(spec.CONF_COMP_SPEC["per_mig_key_isolation"])

    def test_throughput_math_validation_and_die_reticle_bounds(self):
        # Single-die aigpu-b2 upper bound <= 858 mm^2 EUV reticle limit
        lo, hi = spec.DIE_ESTIMATE_MM2["aigpu-b2"]
        self.assertLessEqual(hi, spec.RETICLE_LIMIT_MM2)
        self.assertGreater(lo, 0.0)
        with self.assertRaises(ValueError):
            spec.compute_vortex_base_tfr_tflops(
                total_cores=4, tcu_blocks_per_core=2, num_threads=6,
                pe_ratio=1, fedp2k=False, wgmma_enabled=True,
                clock_mhz=400.0, elements_per_word32=2,
            )
        with self.assertRaises(ValueError):
            spec.export_architecture_spec("aigpu-b99")


class TestB2CrossSkuAndCliContracts(unittest.TestCase):
    def test_sku_scaling_invariants_tile_to_single_to_dual(self):
        tile = spec.SKU_SPECS["aigpu-b2-tile"]
        single = spec.SKU_SPECS["aigpu-b2"]
        dual = spec.SKU_SPECS["aigpu-b2-dual"]

        self.assertEqual(single.total_cores, tile.total_cores * 32)
        self.assertEqual(dual.total_cores, single.total_cores * 2)
        self.assertEqual(dual.tmem_total_bytes, single.tmem_total_bytes * 2)
        self.assertEqual(dual.l2_total_bytes, single.l2_total_bytes * 2)
        self.assertEqual(dual.l2_slices, single.l2_slices * 2)
        self.assertEqual(dual.hbm_stacks, single.hbm_stacks * 2)
        self.assertEqual(dual.hbm_pseudo_channels, single.hbm_pseudo_channels * 2)
        self.assertEqual(dual.hbm_bandwidth_gbs, single.hbm_bandwidth_gbs * 2.0)
        self.assertEqual(dual.tfrv2_fp16_tflops_dense, single.tfrv2_fp16_tflops_dense * 2.0)
        self.assertEqual(dual.tfrv2_fp8_tflops_dense, single.tfrv2_fp8_tflops_dense * 2.0)
        self.assertEqual(dual.tfrv2_fp4_tops_dense, single.tfrv2_fp4_tops_dense * 2.0)
        self.assertEqual(single.tfrv2_fp16_tflops_dense, tile.tfrv2_fp16_tflops_dense * 64.0)

    def test_exported_spec_contains_all_required_sections_and_validates(self):
        full = spec.export_architecture_spec(validate_profiles=True)
        expected_keys = {
            "schema_version", "evidence_level", "silicon_measured",
            "foundry_signoff", "fpga_measured", "program", "skus",
            "tfrv2_numeric_formats", "tmem", "moesi_directory", "ucie_d2d",
            "hbm3e", "decompression_engine", "soc_mmio_map",
            "gigathread_doorbells", "mig_profiles", "pcie_gen6",
            "ras_mca_banks", "pmu_events", "confidential_computing",
            "contract_validation",
        }
        self.assertTrue(expected_keys.issubset(set(full.keys())))
        self.assertEqual(set(full["skus"].keys()), {"aigpu-b2-tile", "aigpu-b2", "aigpu-b2-dual"})
        self.assertTrue(full["contract_validation"]["ok"])
        self.assertEqual(len(full["soc_mmio_map"]), len(spec.MMIO_REGION_MAP))

    def test_markdown_summary_renders_all_skus_and_formats(self):
        full = spec.export_architecture_spec()
        md = spec.format_markdown_summary(full)
        for sku_id in spec.B2_SKUS:
            self.assertIn(f"`{sku_id}`", md)
        for fmt_id in spec.NUMERIC_FORMATS:
            self.assertIn(f"`{fmt_id}`", md)
        self.assertIn("evidence level", md.lower())
        self.assertIn("source_present", md)
        self.assertIn("foundry_signoff=False", md)
        self.assertIn("fpga_measured=False", md)

    def test_full_chip_8way_mig_partition_and_dual_die_16way(self):
        plan_8 = [
            spec.MigAllocation(
                instance_id=i,
                profile_id="1g.12gb",
                cluster_mask=1 << i,
                l2_way_mask=0x3 << (2 * i),
                hbm_stack_mask=1 << i,
                queue_mask=0xFF << (8 * i),
            )
            for i in range(8)
        ]
        self.assertEqual(spec.validate_mig_partition_plan(plan_8, num_dies=1), [])

        # Detect overlapping L2 ways, HBM stacks, and queues independently
        bad_l2 = list(plan_8)
        bad_l2[1] = spec.MigAllocation(1, "1g.12gb", 1 << 1, 0x3, 1 << 1, 0xFF << 8)
        self.assertTrue(any("overlapping l2_way_mask" in e for e in spec.validate_mig_partition_plan(bad_l2)))

        bad_hbm = list(plan_8)
        bad_hbm[1] = spec.MigAllocation(1, "1g.12gb", 1 << 1, 0x3 << 2, 0x1, 0xFF << 8)
        self.assertTrue(any("overlapping hbm_stack_mask" in e for e in spec.validate_mig_partition_plan(bad_hbm)))

        bad_q = list(plan_8)
        bad_q[1] = spec.MigAllocation(1, "1g.12gb", 1 << 1, 0x3 << 2, 1 << 1, 0xFF)
        self.assertTrue(any("overlapping queue_mask" in e for e in spec.validate_mig_partition_plan(bad_q)))

    def test_tmem_swizzle_modes_preserve_address_uniqueness_across_full_array(self):
        # Every (row, col_in_32_group) maps uniquely within a 32-bank row-group
        for mode in spec.TMEM_SPEC.supported_swizzle_modes:
            for col_base in (0, 32, 64, 128, 256, 480):
                seen_pairs = set()
                for row in range(32):
                    for c_off in range(32):
                        bank = spec.tmem_swizzled_bank(row, col_base + c_off, mode)
                        self.assertNotIn((row, bank), seen_pairs)
                        seen_pairs.add((row, bank))

    def test_cli_subprocess_invocation_validate_profiles_and_check_contracts(self):
        proc_chk = subprocess.run(
            [sys.executable, str(ROOT / "ci/project/b2_arch_spec.py"), "--check-contracts"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc_chk.returncode, 0, proc_chk.stderr)
        chk_json = json.loads(proc_chk.stdout)
        self.assertTrue(chk_json["ok"])
        self.assertEqual(chk_json["skus_validated"], ["aigpu-b2-tile", "aigpu-b2", "aigpu-b2-dual"])

        proc_exp = subprocess.run(
            [sys.executable, str(ROOT / "ci/project/b2_arch_spec.py"), "--sku", "aigpu-b2-dual", "--json"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc_exp.returncode, 0, proc_exp.stderr)
        exp_json = json.loads(proc_exp.stdout)
        self.assertEqual(list(exp_json["skus"].keys()), ["aigpu-b2-dual"])
        self.assertFalse(exp_json["silicon_measured"])

    def test_preserved_b1_profiles_and_no_task_wave_comments_in_owned_files(self):
        for b1_name in ("aigpu-b1", "aigpu-b1-tile"):
            proc = subprocess.run(
                [
                    sys.executable, str(ROOT / "ci/gen_config.py"),
                    "--config", str(CONFIG_PATH), "--profile", b1_name,
                    "--xlen", "64", "-f", "cflags", "--cflags", "-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64",
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

        for rel in (
            "ci/project/b2_arch_spec.py",
            "ci/project/test_b2_arch_spec.py",
            "ci/profile_check.py",
        ):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for idx, line in enumerate(text.splitlines(), 1):
                if "#" in line:
                    comment = line.split("#", 1)[1]
                    self.assertNotRegex(
                        comment.lower(),
                        r"\b(?:wave\s*\d+|pr\s*#?\d+|task[\s_-]*\d+)\b",
                        f"{rel}:{idx} references task/PR/wave number in comment",
                    )

    def test_dxa_stride_and_tmem_row_variants_and_honesty_validation(self):
        for rows in (32, 64, 128):
            info = spec.validate_tmem_allocation(0, 64, num_rows=rows)
            self.assertEqual(info["allocated_bytes"], rows * 64 * 4)
        with self.assertRaises(ValueError):
            spec.validate_tmem_allocation(0, 64, num_rows=16)
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1, 1),
                box_dims=(32, 32, 1, 1, 1),
                element_strides=(0, 64, 4096, 4096, 4096),
                element_bytes=2.0,
            )
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 1, 1, 1),
                box_dims=(32, 32, 1, 1, 1),
                element_strides=(1, 64, 4096, 4096, 4096),
                element_bytes=2.0,
                swizzle_mode="INVALID_SWZ",
            )
        with self.assertRaises(ValueError):
            spec.validate_honesty_metadata({"evidence_level": "silicon_measured", "silicon_measured": False, "foundry_signoff": False, "fpga_measured": False})
        with self.assertRaises(ValueError):
            spec.validate_honesty_metadata("not_a_dict")  # type: ignore[arg-type]

    def test_cli_markdown_output_file_and_doorbell_stride(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "spec.md"
            rc = spec.main(["--sku", "aigpu-b2", "--validate-profiles", "--output", str(md_path)])
            self.assertEqual(rc, 0)
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("`aigpu-b2`", content)
            self.assertIn("1152 / 2304 / 4608", content)

        # Verify all 64 GigaThread doorbells map inside BAR0_DOORBELL_PAGE [0x50000, 0x90000)
        region = next(r for r in spec.MMIO_REGION_MAP if r.name == "BAR0_DOORBELL_PAGE")
        for qid in range(spec.GIGATHREAD_NUM_QUEUES):
            addr = spec.gigathread_doorbell_address(qid)
            self.assertGreaterEqual(addr, region.base_addr)
            self.assertLess(addr + spec.GIGATHREAD_DOORBELL_STRIDE_BYTES - 1, region.end_addr)
        with self.assertRaises(ValueError):
            spec.gigathread_doorbell_address(-1)

        # Verify HBM3E, UCIe, and RAS invariants
        self.assertEqual(spec.HBM3E_SPEC.pseudo_channels_per_stack * spec.HBM3E_SPEC.pc_width_bits, spec.HBM3E_SPEC.stack_width_bits)
        self.assertEqual(spec.HBM3E_SPEC.bank_groups_per_pc * spec.HBM3E_SPEC.banks_per_group, 16)
        self.assertEqual(spec.UCIE_SPEC.flit_bits, 512)
        self.assertEqual(spec.UCIE_SPEC.retry_buffer_entries, 128)
        self.assertEqual(spec.UCIE_SPEC.credit_vcs, 4)
        self.assertTrue(all(b["poison_prop"] for b in spec.RAS_MCA_BANKS))
        self.assertEqual(spec.CONF_COMP_SPEC["iv_bits"], 96)
        self.assertEqual(spec.CONF_COMP_SPEC["auth_tag_bits"], 128)
        self.assertEqual(spec.CONF_COMP_SPEC["granule_bytes"], 64)

    def test_custom_profiles_dir_corruption_detection(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir)
            for sku_id in spec.B2_SKUS:
                shutil.copy(PROFILES_DIR / f"{sku_id}.json", custom_dir / f"{sku_id}.json")
            # Sanity: clean custom copy passes
            resolved = spec.validate_b2_profiles_against_gen_config(profiles_dir=custom_dir)
            self.assertEqual(set(resolved.keys()), set(spec.B2_SKUS))

            # Corrupt reference block in custom_dir only; must fail rather than reading repo profiles/
            b2_path = custom_dir / "aigpu-b2.json"
            data = json.loads(b2_path.read_text(encoding="utf-8"))
            data["reference"]["fp32_lanes"] = 99999
            b2_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                spec.validate_b2_profiles_against_gen_config(profiles_dir=custom_dir)
            self.assertIn("fp32_lanes", str(ctx.exception))

            # Also verify inherited reference corruption is caught via extends inside custom_dir
            b2_path.write_text((PROFILES_DIR / "aigpu-b2.json").read_text(encoding="utf-8"), encoding="utf-8")
            dual_path = custom_dir / "aigpu-b2-dual.json"
            dual_data = json.loads(dual_path.read_text(encoding="utf-8"))
            dual_data["reference"]["dram_bandwidth_gbs"] = 1234
            dual_path.write_text(json.dumps(dual_data, indent=2), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx2:
                spec.validate_b2_profiles_against_gen_config(profiles_dir=custom_dir)
            self.assertIn("dram_bandwidth_gbs", str(ctx2.exception))

    def test_mig_duplicate_and_negative_instance_id_rejection(self):
        dup_plan = [
            spec.MigAllocation(0, "1g.12gb", 0x01, 0x0003, 0x01, 0x0000_0000_0000_00FF),
            spec.MigAllocation(0, "1g.12gb", 0x02, 0x000C, 0x02, 0x0000_0000_0000_FF00),
        ]
        dup_errs = spec.validate_mig_partition_plan(dup_plan, num_dies=1)
        self.assertTrue(any("Duplicate MIG instance_id 0" in e for e in dup_errs), dup_errs)

        neg_plan = [
            spec.MigAllocation(-1, "1g.12gb", 0x01, 0x0003, 0x01, 0x0000_0000_0000_00FF),
        ]
        neg_errs = spec.validate_mig_partition_plan(neg_plan, num_dies=1)
        self.assertTrue(any("non-negative" in e for e in neg_errs), neg_errs)

    def test_dxa_5d_aliased_stride_rejection(self):
        # Aliased unit strides (1,1,1,1,1) on multi-dimensional tensor must be rejected
        with self.assertRaises(ValueError) as ctx:
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 4, 4, 4),
                box_dims=(16, 16, 2, 2, 2),
                element_strides=(1, 1, 1, 1, 1),
                element_bytes=2.0,
            )
        self.assertIn("aliases prior axis", str(ctx.exception))

        # Partially aliased axis 2 must also be rejected
        with self.assertRaises(ValueError):
            spec.validate_dxa_5d_descriptor(
                global_dims=(64, 64, 4, 1, 1),
                box_dims=(16, 16, 2, 1, 1),
                element_strides=(1, 64, 128, 16384, 16384),
                element_bytes=2.0,
            )

        # Valid non-aliasing strided 5D descriptor succeeds
        valid = spec.validate_dxa_5d_descriptor(
            global_dims=(64, 64, 4, 4, 4),
            box_dims=(16, 16, 2, 2, 2),
            element_strides=(1, 64, 4096, 16384, 65536),
            element_bytes=2.0,
        )
        self.assertTrue(valid["valid"])

    def test_cross_module_authoritative_constants_and_comment_hygiene(self):
        # MXFP6 standardization
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP6_E2M3"].elements_per_word32, 4)
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP6_E3M2"].elements_per_word32, 4)
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP6_E2M3"].fp16_throughput_multiplier, 2.0)
        self.assertEqual(spec.NUMERIC_FORMATS["MXFP6_E3M2"].fp16_throughput_multiplier, 2.0)

        # Authoritative SKU & TMEM/NoC/UCIe constants
        tile = spec.SKU_SPECS["aigpu-b2-tile"]
        self.assertEqual(tile.hbm_capacity_gib, 4)
        self.assertEqual(tile.pcie_gen, 6)
        self.assertEqual(tile.pcie_lanes, 4)
        self.assertEqual(tile.ucie_d2d_bandwidth_gbs, 0.0)

        b2 = spec.SKU_SPECS["aigpu-b2"]
        self.assertEqual((b2.noc_mesh_rows, b2.noc_mesh_cols), (4, 2))
        self.assertEqual(spec.UCIE_SPEC.nominal_roundtrip_ns, 12.0)
        self.assertEqual(spec.TMEM_SPEC.num_banks, 32)

        # Zero wave/PR/task/ADR references in comments across owned files
        for rel in ("ci/project/b2_arch_spec.py", "ci/project/test_b2_arch_spec.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for idx, line in enumerate(text.splitlines(), 1):
                if "#" in line:
                    comment = line.split("#", 1)[1]
                    self.assertNotRegex(
                        comment.lower(),
                        r"\b(?:wave\s*\d+|pr\s*#?\d+|task[\s_-]*\d+|adr[-\s]*\d+)\b",
                        f"{rel}:{idx} references task/PR/wave/ADR number in comment",
                    )


if __name__ == "__main__":
    unittest.main()
