#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Parametric pre-silicon PPA, SRAM cut, thermal, packaging, yield, and TCO model for AI-GPU B2.

Pure Python standard-library tool (CLI + importable API) extending the read-only
ASAP7 physical anchors and node scaling definitions in `ci/project/aigpu_ppa_model.py`
to model the reticle-class B2 target family:
  - `aigpu-b2-tile`: 4-core RTL-verifiable compute tile & MPW slice (~12-18 mm^2 N4P est.)
  - `aigpu-b2`:      128-core reticle-class datacenter AI GPU (~740-810 mm^2 <= 858 mm^2 N4P est.)
  - `aigpu-b2-dual`: 256-core dual-die CoWoS-L / UCIe 2.0 unified coherent GPU

All projections are anchored to measured open-source ASAP7 EDA runs in
`hw/asic/phys/phys_results.json` and `ci/baselines/synthesis/yosys/*.json` plus
`hw/asic/sram/sram_macro_manifest.json` (read-only). Every output strictly
enforces pre-silicon honesty metadata (`schema_version=1`,
`evidence_level="simulated"`, `model_type="parametric_presilicon_estimate"`,
`silicon_measured=False`, `fpga_measured=False`, `foundry_signoff=False`).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import aigpu_ppa_model as base_ppa


SCHEMA_VERSION = base_ppa.SCHEMA_VERSION
ALLOWED_EVIDENCE_LEVEL = base_ppa.ALLOWED_EVIDENCE_LEVEL
ALLOWED_MODEL_TYPE = base_ppa.ALLOWED_MODEL_TYPE
RETICLE_LIMIT_MM2 = base_ppa.RETICLE_LIMIT_MM2
RETICLE_FIELD_WIDTH_MM = 26.0
RETICLE_FIELD_HEIGHT_MM = 33.0
VALID_NODES = base_ppa.VALID_NODES
NODE_SPECS = base_ppa.NODE_SPECS
NodeScalingSpec = base_ppa.NodeScalingSpec

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_DIR = base_ppa.DEFAULT_PROFILES_DIR
DEFAULT_CONFIG_PATH = base_ppa.DEFAULT_CONFIG_PATH
DEFAULT_PHYS_RESULTS_PATH = base_ppa.DEFAULT_PHYS_RESULTS_PATH
DEFAULT_SRAM_MANIFEST_PATH = base_ppa.DEFAULT_SRAM_MANIFEST_PATH
DEFAULT_YOSYS_DIR = base_ppa.DEFAULT_YOSYS_DIR
DEFAULT_BEACON_DIR = base_ppa.DEFAULT_BEACON_DIR

VALID_SKUS = ("aigpu-b2-tile", "aigpu-b2", "aigpu-b2-dual")
VALID_WORKLOADS = (
    "idle",
    "llm_decode",
    "llm_prefill_fp8",
    "llm_prefill_fp4",
    "peak_tdp_stress",
)
VALID_TMEM_PORT_MODES = ("dual_banked_1rw", "native_1r1w")
VALID_DVFS_BINS = ("efficiency_bin", "nominal", "boost_odv")
DEFAULT_D0_SWEEP = (0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30)


@dataclass(frozen=True)
class B2SkuSpec:
    """Architectural specification for an AI-GPU B2 target SKU."""

    sku_id: str
    display_name: str
    role: str
    die_count: int
    clusters_per_die: int
    cores_per_cluster: int
    warps_per_core: int
    threads_per_warp: int
    issue_width: int
    fetch_width: int
    alu_lanes_per_block: int
    fpu_lanes_per_block: int
    lsu_lanes_per_block: int
    tcu_pipes_per_core: int
    tcu_pe_ratio: int
    vortex_fedp_2k: bool
    tfr_v2_fp16_tflops_per_pipe_at_2ghz: float
    tmem_kib_per_core: int
    tmem_banks_per_core: int
    l1_dcache_kib_per_core: int
    l1_icache_kib_per_core: int
    lmem_kib_per_core: int
    rf_kib_per_core: int
    l2_mib_per_die: float
    l2_banks_per_die: int
    l2_ways: int
    has_coherent_directory: bool
    has_snoop_filter: bool
    has_hardware_de: bool
    has_gigathread_cp: bool
    has_mig: bool
    has_ras_pmu_sec_aes: bool
    noc_mesh_rows: int
    noc_mesh_cols: int
    hbm3e_stacks_per_die: int
    hbm3e_bw_tbps_per_die: float
    ucie_bw_tbps_per_die: float
    pcie_gen6_lanes_per_die: int
    clock_mhz_target: float
    rtl_ref_clock_mhz: float
    tile_io_bw_gbs: float
    profile_json_name: str


B2_SKU_SPECS: dict[str, B2SkuSpec] = {
    "aigpu-b2-tile": B2SkuSpec(
        sku_id="aigpu-b2-tile",
        display_name="AI-GPU B2 Tile (4C MPW Slice)",
        role="RTL-verifiable compute tile and MPW silicon bring-up slice",
        die_count=1,
        clusters_per_die=1,
        cores_per_cluster=4,
        warps_per_core=8,
        threads_per_warp=8,
        issue_width=2,
        fetch_width=2,
        alu_lanes_per_block=8,
        fpu_lanes_per_block=8,
        lsu_lanes_per_block=8,
        tcu_pipes_per_core=2,
        tcu_pe_ratio=1,
        vortex_fedp_2k=False,
        tfr_v2_fp16_tflops_per_pipe_at_2ghz=2.25,
        tmem_kib_per_core=256,
        tmem_banks_per_core=32,
        l1_dcache_kib_per_core=16,
        l1_icache_kib_per_core=16,
        lmem_kib_per_core=16,
        rf_kib_per_core=32,
        l2_mib_per_die=1.25,
        l2_banks_per_die=4,
        l2_ways=8,
        has_coherent_directory=False,
        has_snoop_filter=False,
        has_hardware_de=False,
        has_gigathread_cp=False,
        has_mig=False,
        has_ras_pmu_sec_aes=False,
        noc_mesh_rows=1,
        noc_mesh_cols=1,
        hbm3e_stacks_per_die=0,
        hbm3e_bw_tbps_per_die=0.0,
        ucie_bw_tbps_per_die=0.0,
        pcie_gen6_lanes_per_die=4,
        clock_mhz_target=2000.0,
        rtl_ref_clock_mhz=400.0,
        tile_io_bw_gbs=460.0,
        profile_json_name="aigpu-b2-tile",
    ),
    "aigpu-b2": B2SkuSpec(
        sku_id="aigpu-b2",
        display_name="AI-GPU B2 (128C Reticle Single-Die)",
        role="Full-reticle single-die datacenter AI GPU",
        die_count=1,
        clusters_per_die=8,
        cores_per_cluster=16,
        warps_per_core=32,
        threads_per_warp=32,
        issue_width=4,
        fetch_width=4,
        alu_lanes_per_block=32,
        fpu_lanes_per_block=32,
        lsu_lanes_per_block=8,
        tcu_pipes_per_core=4,
        tcu_pe_ratio=1,
        vortex_fedp_2k=True,
        tfr_v2_fp16_tflops_per_pipe_at_2ghz=2.25,
        tmem_kib_per_core=256,
        tmem_banks_per_core=32,
        l1_dcache_kib_per_core=128,
        l1_icache_kib_per_core=16,
        lmem_kib_per_core=128,
        rf_kib_per_core=48,
        l2_mib_per_die=128.0,
        l2_banks_per_die=64,
        l2_ways=16,
        has_coherent_directory=True,
        has_snoop_filter=True,
        has_hardware_de=True,
        has_gigathread_cp=True,
        has_mig=True,
        has_ras_pmu_sec_aes=True,
        noc_mesh_rows=4,
        noc_mesh_cols=2,
        hbm3e_stacks_per_die=8,
        hbm3e_bw_tbps_per_die=4.0,
        ucie_bw_tbps_per_die=10.0,
        pcie_gen6_lanes_per_die=16,
        clock_mhz_target=2000.0,
        rtl_ref_clock_mhz=2000.0,
        tile_io_bw_gbs=4000.0,
        profile_json_name="aigpu-b2",
    ),
    "aigpu-b2-dual": B2SkuSpec(
        sku_id="aigpu-b2-dual",
        display_name="AI-GPU B2 Dual (256C CoWoS-L Unified)",
        role="Dual-die CoWoS-L / UCIe 2.0 unified coherent datacenter GPU",
        die_count=2,
        clusters_per_die=8,
        cores_per_cluster=16,
        warps_per_core=32,
        threads_per_warp=32,
        issue_width=4,
        fetch_width=4,
        alu_lanes_per_block=32,
        fpu_lanes_per_block=32,
        lsu_lanes_per_block=8,
        tcu_pipes_per_core=4,
        tcu_pe_ratio=1,
        vortex_fedp_2k=True,
        tfr_v2_fp16_tflops_per_pipe_at_2ghz=2.25,
        tmem_kib_per_core=256,
        tmem_banks_per_core=32,
        l1_dcache_kib_per_core=128,
        l1_icache_kib_per_core=16,
        lmem_kib_per_core=128,
        rf_kib_per_core=48,
        l2_mib_per_die=128.0,
        l2_banks_per_die=64,
        l2_ways=16,
        has_coherent_directory=True,
        has_snoop_filter=True,
        has_hardware_de=True,
        has_gigathread_cp=True,
        has_mig=True,
        has_ras_pmu_sec_aes=True,
        noc_mesh_rows=4,
        noc_mesh_cols=2,
        hbm3e_stacks_per_die=8,
        hbm3e_bw_tbps_per_die=4.0,
        ucie_bw_tbps_per_die=10.0,
        pcie_gen6_lanes_per_die=16,
        clock_mhz_target=2000.0,
        rtl_ref_clock_mhz=2000.0,
        tile_io_bw_gbs=8000.0,
        profile_json_name="aigpu-b2-dual",
    ),
}


@dataclass(frozen=True)
class WorkloadProfileSpec:
    """Dynamic activity and interface duty-cycle profile for power/thermal estimation."""

    workload_id: str
    display_name: str
    tcu_activity_duty: float
    core_uncore_duty: float
    tmem_bw_duty: float
    sram_cache_bw_duty: float
    hbm_bw_duty: float
    ucie_bw_duty: float
    pcie_duty: float
    active_precision: str
    notes: str


WORKLOAD_PROFILES: dict[str, WorkloadProfileSpec] = {
    "idle": WorkloadProfileSpec(
        workload_id="idle",
        display_name="Idle / Clock-Gated Standby",
        tcu_activity_duty=0.01,
        core_uncore_duty=0.05,
        tmem_bw_duty=0.02,
        sram_cache_bw_duty=0.03,
        hbm_bw_duty=0.08,
        ucie_bw_duty=0.05,
        pcie_duty=0.10,
        active_precision="fp16_bf16",
        notes="Clock-gated tensor pipes and caches; HBM3E self-refresh, PLLs, and static leakage dominate.",
    ),
    "llm_decode": WorkloadProfileSpec(
        workload_id="llm_decode",
        display_name="LLM Autoregressive Decode (Memory-BW Bound)",
        tcu_activity_duty=0.22,
        core_uncore_duty=0.45,
        tmem_bw_duty=0.28,
        sram_cache_bw_duty=0.42,
        hbm_bw_duty=0.92,
        ucie_bw_duty=0.65,
        pcie_duty=0.30,
        active_precision="fp8",
        notes="Weight-streaming GEMV regime dominated by HBM3E I/O and L2/SLC streaming.",
    ),
    "llm_prefill_fp8": WorkloadProfileSpec(
        workload_id="llm_prefill_fp8",
        display_name="LLM Batched Prefill (FP8 Compute-Bound)",
        tcu_activity_duty=0.85,
        core_uncore_duty=0.72,
        tmem_bw_duty=0.82,
        sram_cache_bw_duty=0.76,
        hbm_bw_duty=0.74,
        ucie_bw_duty=0.52,
        pcie_duty=0.40,
        active_precision="fp8",
        notes="High TFRv2 systolic occupancy with sustained TMEM ping-pong buffering.",
    ),
    "llm_prefill_fp4": WorkloadProfileSpec(
        workload_id="llm_prefill_fp4",
        display_name="LLM Batched Prefill (NVFP4/MXFP4 Microscaled)",
        tcu_activity_duty=0.88,
        core_uncore_duty=0.74,
        tmem_bw_duty=0.86,
        sram_cache_bw_duty=0.72,
        hbm_bw_duty=0.68,
        ucie_bw_duty=0.50,
        pcie_duty=0.40,
        active_precision="nvfp4",
        notes="Peak FP4 microscaled tensor utilization with reduced external HBM byte traffic.",
    ),
    "peak_tdp_stress": WorkloadProfileSpec(
        workload_id="peak_tdp_stress",
        display_name="Peak TDP Thermal Stress (Sustained Max Activity)",
        tcu_activity_duty=1.00,
        core_uncore_duty=1.00,
        tmem_bw_duty=1.00,
        sram_cache_bw_duty=1.00,
        hbm_bw_duty=1.00,
        ucie_bw_duty=1.00,
        pcie_duty=1.00,
        active_precision="fp16_bf16",
        notes="Worst-case sustained thermal envelope across compute, SRAM, HBM3E, and D2D.",
    ),
}


@dataclass(frozen=True)
class DvfsOperatingPoint:
    """Voltage-frequency operating bin relative to nominal node target."""

    bin_id: str
    display_name: str
    clock_scale: float
    vdd_scale: float
    notes: str


DVFS_BINS: dict[str, DvfsOperatingPoint] = {
    "efficiency_bin": DvfsOperatingPoint(
        bin_id="efficiency_bin",
        display_name="Efficiency / Max TFLOPS-per-Watt Bin",
        clock_scale=0.85,
        vdd_scale=0.90,
        notes="Reduced Vdd/Fclk operating point for optimal TFLOPS/W in dense inference clusters.",
    ),
    "nominal": DvfsOperatingPoint(
        bin_id="nominal",
        display_name="Nominal Datacenter Bin (2.0 GHz Target)",
        clock_scale=1.00,
        vdd_scale=1.00,
        notes="Baseline 2.0 GHz datacenter operating point anchored to N4P/N3E Fmax scaling.",
    ),
    "boost_odv": DvfsOperatingPoint(
        bin_id="boost_odv",
        display_name="Overdrive Boost Bin (+10% Fclk)",
        clock_scale=1.10,
        vdd_scale=1.08,
        notes="Liquid-cooled overdrive voltage/frequency bin subject to node Fmax ceiling.",
    ),
}


# Explicit parametric hardware, physical layout, packaging, yield, and TCO constants.
B2_PARAMETRIC_CONSTANTS: dict[str, Any] = {
    "reticle_limit_mm2": RETICLE_LIMIT_MM2,
    "reticle_field_width_mm": RETICLE_FIELD_WIDTH_MM,
    "reticle_field_height_mm": RETICLE_FIELD_HEIGHT_MM,
    "preferred_die_aspect_ratio": 1.12,
    "gemm_tcu_effective_toggle_factor": 0.34,
    "opensta_default_input_activity": 0.10,
    "tfr_v2_fedp_multiformat_area_overhead": 1.65,
    "tfr_v2_sparsity_microscale_area_factor": 1.26,
    "tfr_v2_dynamic_power_overhead": 1.22,
    "tfr_v2_wide_systolic_core_asap7_um2": 1320000.0,
    "tfr_v2_wide_systolic_tile_asap7_um2": 640000.0,
    "tfr_v2_tmem_arbiter_ctrl_asap7_um2_per_core": 96000.0,
    "rv64x_lane_width_area_scale_vs_rv32": 1.44,
    "rv64x_ctrl_width_area_scale_vs_rv32": 1.32,
    "core_scalar_lane_area_fraction": 0.45,
    "core_scalar_ctrl_area_fraction": 0.55,
    "sv48_mmu_tlb_asap7_um2_per_core": 92000.0,
    "dxa_5d_tma_scale_vs_b1": 1.95,
    "l2_bank_ctrl_asap7_um2": 240000.0,
    "coherent_dir_snoop_ctrl_asap7_um2_per_die": 24500000.0,
    "noc_router_2d_mesh_asap7_um2": 2650000.0,
    "noc_mesh_link_repeater_asap7_um2_per_cluster": 1550000.0,
    "gigathread_cp_asap7_um2": 11500000.0,
    "mig_partitioner_asap7_um2": 4800000.0,
    "hardware_de_engine_asap7_um2": 13500000.0,
    "ras_pmu_sec_aes256_asap7_um2": 14800000.0,
    "tile_uncore_shim_asap7_um2": 1450000.0,
    "non_fedp_logic_active_duty_factor": 0.36,
    "sram_internal_bandwidth_duty_factor": 0.38,
    "hard_ip_n4p_mm2_per_hbm3e_stack": 10.5,
    "hard_ip_n4p_mm2_ucie_10tbps": 36.0,
    "hard_ip_n4p_mm2_pcie_gen6_x16_iommu": 24.0,
    "hard_ip_n4p_mm2_plls_padring_keepout_full": 22.0,
    "hard_ip_n4p_mm2_tile_serdes_ucie_stub": 3.40,
    "hard_ip_n4p_mm2_tile_pll_padring": 3.20,
    "shoreline_mm_per_hbm3e_stack": 5.8,
    "shoreline_gbps_per_mm_ucie_2_0": 650.0,
    "shoreline_mm_pcie_gen6_x16": 9.5,
    "shoreline_mm_misc_io_and_corners_full": 14.0,
    "shoreline_mm_tile_io_and_corners": 4.2,
    "ucie_energy_pj_per_bit": {
        "asap7": 0.48,
        "n4p_est": 0.35,
        "n3e_est": 0.29,
    },
    "pcie_gen6_x16_active_power_w": {
        "asap7": 24.0,
        "n4p_est": 18.0,
        "n3e_est": 15.0,
    },
    "hard_ip_base_power_asap7_w_full": 22.0,
    "hard_ip_base_power_asap7_w_tile": 0.85,
    "on_die_hbm_phy_leakage_share": 0.50,
    "tmem_energy_scale_vs_cache_sram": 0.85,
    "precision_dynamic_power_multipliers": {
        "fp16_bf16": 1.00,
        "fp8": 0.94,
        "mxfp4": 0.91,
        "nvfp4": 0.91,
    },
    "sram_ecc_overhead_secded_64b": 8.0 / 64.0,
    "sram_ecc_overhead_secded_32b": 7.0 / 32.0,
    "sram_ecc_overhead_chipkill_128b": 16.0 / 128.0,
    "sram_redundancy_spare_fraction": 0.04,
    "sram_repair_defect_coverage": 0.78,
    "sram_dual_banked_1rw_area_multiplier": 1.18,
    "sram_dual_banked_1rw_energy_multiplier": 1.08,
    "thermal_specs": {
        "air_cooled": {
            "label": "High-Airflow Server Chassis (Air)",
            "ambient_c": 35.0,
            "r_theta_ja_c_per_w_full": 0.088,
            "r_theta_ja_c_per_w_dual": 0.085,
            "r_theta_ja_c_per_w_tile": 1.80,
            "max_tj_c": 95.0,
        },
        "liquid_cooled": {
            "label": "Direct-to-Chip Warm-Water DLC Cold Plate",
            "ambient_c": 40.0,
            "r_theta_ja_c_per_w_full": 0.036,
            "r_theta_ja_c_per_w_dual": 0.032,
            "r_theta_ja_c_per_w_tile": 0.65,
            "max_tj_c": 95.0,
        },
    },
    "nominal_vdd_v": {
        "asap7": 0.70,
        "n4p_est": 0.75,
        "n3e_est": 0.72,
    },
    "wafer_diameter_mm": 300.0,
    "wafer_edge_exclusion_mm": 3.0,
    "scribe_lane_mm": 0.10,
    "negbin_alpha": 3.0,
    "kgd_test_yield": 0.96,
    "cowos_l_assembly_yield_dual": 0.94,
    "cowos_s_assembly_yield_single": 0.97,
    "parametric_wafer_cost_usd": {
        "asap7": 9500.0,
        "n4p_est": 16500.0,
        "n3e_est": 20500.0,
    },
    "parametric_hbm3e_stack_cost_usd": 420.0,
    "parametric_cowos_l_interposer_cost_usd": 680.0,
    "parametric_cowos_s_interposer_cost_usd": 310.0,
    "tco_assumptions": {
        "amortization_years": 3.0,
        "hours_per_year": 8760.0,
        "fleet_utilization": 0.70,
        "electricity_usd_per_kwh": 0.085,
        "pue_air": 1.35,
        "pue_dlc": 1.12,
        "server_host_capex_share_per_gpu_usd": 4200.0,
        "estimated_system_price_mult_over_silicon_bom": 3.8,
    },
}


def validate_b2_honesty_record(record: dict[str, Any]) -> None:
    """Enforce strict pre-silicon honesty invariants on every B2 PPA record."""
    base_ppa.validate_honesty_record(record)
    if record.get("schema_version") is not None and record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"B2 PPA record requires schema_version={SCHEMA_VERSION}, got {record.get('schema_version')!r}"
        )
    if record.get("fpga_measured") is not False:
        raise ValueError(
            "B2 PPA model must enforce fpga_measured=False; no physical FPGA results exist"
        )


def _stamp_honesty(payload: dict[str, Any], *, is_published_ref: bool = False) -> dict[str, Any]:
    payload["schema_version"] = SCHEMA_VERSION
    payload["evidence_level"] = ALLOWED_EVIDENCE_LEVEL
    payload["model_type"] = ALLOWED_MODEL_TYPE
    payload["silicon_measured"] = False
    payload["fpga_measured"] = False
    payload["foundry_signoff"] = False
    payload["is_published_reference"] = is_published_ref
    if is_published_ref:
        payload["locally_measured"] = False
    return payload


def _assert_positive_finite(value: float, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{label} must be positive and finite, got {value!r}")
    return float(value)


def validate_sku_spec(sku: B2SkuSpec) -> None:
    """Validate internal geometric and architectural consistency of a B2SkuSpec."""
    _assert_positive_finite(sku.die_count, f"{sku.sku_id}.die_count")
    _assert_positive_finite(sku.clusters_per_die, f"{sku.sku_id}.clusters_per_die")
    _assert_positive_finite(sku.cores_per_cluster, f"{sku.sku_id}.cores_per_cluster")
    _assert_positive_finite(sku.tcu_pipes_per_core, f"{sku.sku_id}.tcu_pipes_per_core")
    _assert_positive_finite(sku.tmem_kib_per_core, f"{sku.sku_id}.tmem_kib_per_core")
    _assert_positive_finite(sku.clock_mhz_target, f"{sku.sku_id}.clock_mhz_target")
    if sku.threads_per_warp <= 0 or (sku.threads_per_warp & (sku.threads_per_warp - 1)) != 0:
        raise ValueError(f"{sku.sku_id}.threads_per_warp must be power of two")
    if sku.noc_mesh_rows * sku.noc_mesh_cols < sku.clusters_per_die:
        raise ValueError(
            f"{sku.sku_id}: NoC mesh {sku.noc_mesh_rows}x{sku.noc_mesh_cols} cannot cover "
            f"{sku.clusters_per_die} clusters"
        )
    if sku.hbm3e_stacks_per_die > 0 and sku.hbm3e_stacks_per_die % 2 != 0:
        raise ValueError(f"{sku.sku_id}: HBM3E stacks per die must be even for symmetric edges")


def _vortex_tcu_block_shape(num_threads: int) -> tuple[int, int, int]:
    """Derive base Vortex TCU tile geometry (TC_M, TC_N, TC_K) from NUM_THREADS."""
    if num_threads <= 0 or (num_threads & (num_threads - 1)) != 0:
        raise ValueError(f"threads_per_warp must be a positive power of two, got {num_threads}")
    lg_cap = num_threads.bit_length() - 1
    block_en = lg_cap // 2
    block_em = lg_cap - block_en
    tc_m = 1 << block_em
    tc_n = 1 << block_en
    tc_k = num_threads // max(tc_m, tc_n)
    return tc_m, tc_n, tc_k


def _maybe_read_profile_json(sku: B2SkuSpec, profiles_dir: Path) -> dict[str, Any] | None:
    p_path = profiles_dir / f"{sku.profile_json_name}.json"
    if not p_path.is_file():
        return None
    try:
        data = json.loads(p_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def compute_b2_compute_capability(
    sku: B2SkuSpec,
    *,
    clock_mhz: float | None = None,
) -> dict[str, Any]:
    """Compute Vortex-resolved TFR baseline and TFRv2 16x8x8 architectural peak TFLOPS/TOPS."""
    validate_sku_spec(sku)
    eff_clock_mhz = float(clock_mhz if clock_mhz is not None else sku.clock_mhz_target)
    _assert_positive_finite(eff_clock_mhz, f"{sku.sku_id}.clock_mhz")
    clock_ghz = eff_clock_mhz / 1000.0

    cores_per_die = sku.clusters_per_die * sku.cores_per_cluster
    total_cores = cores_per_die * sku.die_count
    total_tcu_pipes = total_cores * sku.tcu_pipes_per_core

    tc_m, tc_n, tc_k = _vortex_tcu_block_shape(sku.threads_per_warp)
    fedp_k = (2 * tc_k) if sku.vortex_fedp_2k else tc_k
    pes_per_pipe = (tc_m * tc_n) / float(sku.tcu_pe_ratio)
    word32_fmas_per_cycle_base = float(total_tcu_pipes) * pes_per_pipe * float(fedp_k)

    fp32_lanes_total = total_cores * sku.issue_width * sku.fpu_lanes_per_block
    scalar_fp32_tflops = (fp32_lanes_total * 2.0 * clock_ghz) / 1000.0

    bw_tbps = (
        sku.die_count * sku.hbm3e_bw_tbps_per_die
        if sku.hbm3e_stacks_per_die > 0
        else sku.tile_io_bw_gbs / 1000.0
    )

    # Base FP16 TFRv2 peak at effective clock across all pipes
    fp16_v2_total = total_tcu_pipes * sku.tfr_v2_fp16_tflops_per_pipe_at_2ghz * (clock_ghz / 2.0)

    # Precision throughput ratios relative to FP16: TF32=0.5x, FP8/INT8/MXFP6=2x, FP4=4x
    format_specs = {
        "fp16_bf16": (2, 1.0, "TFLOPS", "FP16 / BF16 -> FP32"),
        "tf32": (1, 0.5, "TFLOPS", "TF32 -> FP32"),
        "fp8": (4, 2.0, "TFLOPS", "FP8 / MXFP8 (E4M3/E5M2)"),
        "int8": (4, 2.0, "TOPS", "INT8"),
        "mxfp6": (4, 2.0, "TFLOPS", "MXFP6 (E2M3/E3M2)"),
        "mxfp4": (8, 4.0, "TOPS", "MXFP4 (OCP 4-bit)"),
        "nvfp4": (8, 4.0, "TOPS", "NVFP4 (Block-Scaled 4-bit)"),
    }

    formats: dict[str, dict[str, Any]] = {}
    for fmt_key, (epw, ratio_vs_fp16, unit, label) in format_specs.items():
        base_dense = (word32_fmas_per_cycle_base * float(epw) * 2.0 * clock_ghz) / 1000.0
        base_sparse = 2.0 * base_dense
        v2_dense = fp16_v2_total * ratio_vs_fp16
        v2_sparse = 2.0 * v2_dense
        formats[fmt_key] = {
            "label": label,
            "unit": unit,
            "supported": True,
            "sparse_2_4_supported": True,
            "vortex_base_resolved_dense": base_dense,
            "vortex_base_resolved_sparse_2_4": base_sparse,
            "tfr_v2_architectural_dense": v2_dense,
            "tfr_v2_architectural_sparse_2_4": v2_sparse,
            "dense_ridge_ops_per_byte": v2_dense / bw_tbps,
            "sparse_2_4_ridge_ops_per_byte": v2_sparse / bw_tbps,
        }

    # For tile SKU, also capture the 400 MHz RTL reference numbers explicitly
    rtl_ref_scale = sku.rtl_ref_clock_mhz / eff_clock_mhz
    rtl_ref_peaks = {
        "rtl_ref_clock_mhz": sku.rtl_ref_clock_mhz,
        "fp16_tfr_v2_dense_tflops": formats["fp16_bf16"]["tfr_v2_architectural_dense"] * rtl_ref_scale,
        "fp8_tfr_v2_dense_tflops": formats["fp8"]["tfr_v2_architectural_dense"] * rtl_ref_scale,
        "nvfp4_tfr_v2_dense_tops": formats["nvfp4"]["tfr_v2_architectural_dense"] * rtl_ref_scale,
    }

    return {
        "clock_mhz": eff_clock_mhz,
        "total_cores": total_cores,
        "cores_per_die": cores_per_die,
        "total_tcu_pipes": total_tcu_pipes,
        "vortex_tcu_shape": {"tc_m": tc_m, "tc_n": tc_n, "tc_k": tc_k, "fedp_k": fedp_k},
        "tfr_v2_systolic_shape": "16x8x8",
        "word32_fmas_per_cycle_vortex_base": word32_fmas_per_cycle_base,
        "fp32_lanes_total": fp32_lanes_total,
        "scalar_fp32_tflops": scalar_fp32_tflops,
        "bandwidth_tbps": bw_tbps,
        "rtl_ref_peaks": rtl_ref_peaks,
        "formats": formats,
    }


def compute_b2_sram_budget(
    sku: B2SkuSpec,
    node: NodeScalingSpec,
    *,
    tmem_port_mode: str = "dual_banked_1rw",
) -> dict[str, Any]:
    """Compute exact SRAM macro cut decomposition, ECC bits, redundancy, and area for a B2 SKU."""
    if tmem_port_mode not in VALID_TMEM_PORT_MODES:
        raise ValueError(f"Unsupported tmem_port_mode {tmem_port_mode!r}; expected {VALID_TMEM_PORT_MODES}")

    cores_per_die = sku.clusters_per_die * sku.cores_per_cluster
    secded_64 = B2_PARAMETRIC_CONSTANTS["sram_ecc_overhead_secded_64b"]
    secded_32 = B2_PARAMETRIC_CONSTANTS["sram_ecc_overhead_secded_32b"]
    chipkill_128 = B2_PARAMETRIC_CONSTANTS["sram_ecc_overhead_chipkill_128b"]
    redundancy = B2_PARAMETRIC_CONSTANTS["sram_redundancy_spare_fraction"]

    arrays: list[dict[str, Any]] = []

    def _add_array(
        *,
        array_id: str,
        subsystem: str,
        port_type: str,
        logical_bytes_per_die: float,
        cut_depth: int,
        cut_data_width: int,
        ecc_fraction: float,
        ecc_scheme_label: str,
        area_mult_override: float = 1.0,
        energy_mult: float = 1.0,
        notes: str,
    ) -> None:
        logical_bits = int(round(logical_bytes_per_die * 8.0))
        ecc_bits = int(round(logical_bits * ecc_fraction))
        redundancy_bits = int(round((logical_bits + ecc_bits) * redundancy))
        physical_bits = logical_bits + ecc_bits + redundancy_bits

        bits_per_cut = cut_depth * cut_data_width
        macro_cuts_per_die = max(1, int(math.ceil(logical_bits / float(bits_per_cut))))

        if port_type == "1rw":
            port_mult = 1.0
        elif port_type == "dual_banked_1rw":
            port_mult = B2_PARAMETRIC_CONSTANTS["sram_dual_banked_1rw_area_multiplier"]
        elif port_type == "1r1w":
            port_mult = node.sram_1r1w_area_multiplier
        else:
            raise ValueError(f"Unsupported port_type {port_type!r}")

        area_per_die_mm2 = (
            (physical_bits * node.sram_1rw_bitcell_um2 * port_mult * area_mult_override)
            / node.sram_array_efficiency
        ) / 1e6

        arrays.append({
            "array_id": array_id,
            "subsystem": subsystem,
            "port_type": port_type,
            "cut_geometry": f"{cut_depth}x{cut_data_width}b",
            "macro_cuts_per_die": macro_cuts_per_die,
            "logical_bits_per_die": logical_bits,
            "logical_bytes_per_die": logical_bits // 8,
            "logical_mib_per_die": logical_bits / (8.0 * 1024.0 * 1024.0),
            "ecc_scheme": ecc_scheme_label,
            "ecc_overhead_bits_per_die": ecc_bits,
            "redundancy_overhead_bits_per_die": redundancy_bits,
            "physical_bits_per_die": physical_bits,
            "area_per_die_mm2": area_per_die_mm2,
            "area_total_package_mm2": area_per_die_mm2 * sku.die_count,
            "energy_mult": energy_mult,
            "notes": notes,
        })

    # 1. Dedicated Banked TMEM (256 KiB/core = 32 MiB/die on aigpu-b2, 1 MiB on tile)
    tmem_bytes_per_die = cores_per_die * sku.tmem_kib_per_core * 1024
    tmem_energy_mult = (
        B2_PARAMETRIC_CONSTANTS["sram_dual_banked_1rw_energy_multiplier"]
        if tmem_port_mode == "dual_banked_1rw"
        else 1.25
    )
    _add_array(
        array_id="tmem_tensor_bank",
        subsystem="tmem",
        port_type="dual_banked_1rw" if tmem_port_mode == "dual_banked_1rw" else "1r1w",
        logical_bytes_per_die=float(tmem_bytes_per_die),
        cut_depth=1024,
        cut_data_width=128,
        ecc_fraction=secded_64,
        ecc_scheme_label="SECDED_72_64",
        energy_mult=tmem_energy_mult,
        notes=(
            f"{sku.tmem_kib_per_core} KiB/core x {cores_per_die} cores "
            f"({sku.tmem_banks_per_core} banks/core, mode={tmem_port_mode})"
        ),
    )

    # 2. L2/SLC Data + Tags + Coherent Directory + Snoop Filter
    l2_data_bytes_per_die = sku.l2_mib_per_die * 1024.0 * 1024.0
    _add_array(
        array_id="l2_slc_data",
        subsystem="l2_slc",
        port_type="1rw",
        logical_bytes_per_die=l2_data_bytes_per_die,
        cut_depth=2048,
        cut_data_width=128,
        ecc_fraction=chipkill_128 if sku.l2_mib_per_die >= 32.0 else secded_64,
        ecc_scheme_label="Chipkill_144_128" if sku.l2_mib_per_die >= 32.0 else "SECDED_72_64",
        notes=(
            f"{sku.l2_mib_per_die:.2f} MiB L2/SLC data across {sku.l2_banks_per_die} banks "
            f"({sku.l2_ways}-way, 128 B sectored lines)"
        ),
    )

    l2_tag_bytes_per_die = l2_data_bytes_per_die * (44.0 / 1024.0)
    _add_array(
        array_id="l2_slc_tag_and_state",
        subsystem="l2_slc",
        port_type="1r1w",
        logical_bytes_per_die=l2_tag_bytes_per_die,
        cut_depth=512,
        cut_data_width=128,
        ecc_fraction=secded_32,
        ecc_scheme_label="SECDED_39_32",
        notes="L2/SLC tag + MOESI state + replacement metadata (1R1W lookup/update)",
    )

    if sku.has_coherent_directory and sku.has_snoop_filter:
        dir_bytes_per_die = 6.0 * 1024.0 * 1024.0
        _add_array(
            array_id="coherent_dir_and_snoop_filter",
            subsystem="l2_slc",
            port_type="1r1w",
            logical_bytes_per_die=dir_bytes_per_die,
            cut_depth=1024,
            cut_data_width=64,
            ecc_fraction=secded_64,
            ecc_scheme_label="SECDED_72_64",
            notes="8-cluster inclusive directory + UCIe 2.0 remote-die snoop filter vectors",
        )

    # 3. Core LMEM, L1D, L1I, Register File, TCU Metadata, DXA, DE, and HBM ECC Reorder Buffers
    lmem_logical_bytes = cores_per_die * sku.lmem_kib_per_core * 1024
    _add_array(
        array_id="lmem_bank_mirrored",
        subsystem="lmem_l1_rf",
        port_type="1r1w",
        logical_bytes_per_die=float(lmem_logical_bytes),
        cut_depth=1024,
        cut_data_width=64,
        ecc_fraction=secded_64,
        ecc_scheme_label="SECDED_72_64",
        area_mult_override=2.0 if sku.issue_width >= 2 else 1.0,
        notes="Shared LMEM per core (2x write-mirrored 1R1W physical copies for dual-issue)",
    )

    l1d_bytes = cores_per_die * sku.l1_dcache_kib_per_core * 1024
    _add_array(
        array_id="l1_dcache_data_and_tag",
        subsystem="lmem_l1_rf",
        port_type="1rw",
        logical_bytes_per_die=float(l1d_bytes) * 1.08,
        cut_depth=512,
        cut_data_width=128,
        ecc_fraction=secded_64,
        ecc_scheme_label="SECDED_72_64",
        notes="Per-core L1 Data cache data + tag arrays",
    )

    l1i_bytes = cores_per_die * sku.l1_icache_kib_per_core * 1024
    _add_array(
        array_id="l1_icache_data_and_tag",
        subsystem="lmem_l1_rf",
        port_type="1rw",
        logical_bytes_per_die=float(l1i_bytes) * 1.08,
        cut_depth=256,
        cut_data_width=64,
        ecc_fraction=secded_32,
        ecc_scheme_label="SECDED_39_32",
        notes="Per-core L1 Instruction cache data + tag arrays",
    )

    rf_bytes = cores_per_die * sku.rf_kib_per_core * 1024
    _add_array(
        array_id="rf_gpr_and_pred_bank",
        subsystem="lmem_l1_rf",
        port_type="1r1w",
        logical_bytes_per_die=float(rf_bytes),
        cut_depth=64,
        cut_data_width=256,
        ecc_fraction=secded_64,
        ecc_scheme_label="SECDED_72_64",
        notes="Banked scalar/vector GPR register file (1R1W multi-bank cuts)",
    )

    meta_bytes = cores_per_die * 8 * 1024 + (256 * 1024 if sku.has_gigathread_cp else 16 * 1024)
    _add_array(
        array_id="tcu_meta_dxa_cp_queues",
        subsystem="lmem_l1_rf",
        port_type="1r1w",
        logical_bytes_per_die=float(meta_bytes),
        cut_depth=16,
        cut_data_width=128,
        ecc_fraction=secded_32,
        ecc_scheme_label="SECDED_39_32",
        notes="TCU 2:4/MX metadata, 5D DXA descriptor tables, and GigaThread CP queues",
    )

    if sku.has_hardware_de or sku.hbm3e_stacks_per_die > 0:
        io_sram_bytes = (
            (512 * 1024 if sku.has_hardware_de else 0)
            + (sku.hbm3e_stacks_per_die * 128 * 1024)
        )
        _add_array(
            array_id="de_history_and_hbm_reorder_sram",
            subsystem="lmem_l1_rf",
            port_type="1r1w",
            logical_bytes_per_die=float(io_sram_bytes),
            cut_depth=256,
            cut_data_width=128,
            ecc_fraction=secded_64,
            ecc_scheme_label="SECDED_72_64",
            notes="Hardware DE LZ4/Deflate ring buffers + HBM3E FR-FCFS reorder & scrub SRAM",
        )

    subsystem_summary: dict[str, dict[str, Any]] = {}
    for arr in arrays:
        sub = arr["subsystem"]
        bucket = subsystem_summary.setdefault(
            sub,
            {
                "logical_bits_per_die": 0,
                "logical_mib_per_die": 0.0,
                "ecc_overhead_bits_per_die": 0,
                "redundancy_overhead_bits_per_die": 0,
                "physical_bits_per_die": 0,
                "macro_cuts_per_die": 0,
                "area_per_die_mm2": 0.0,
            },
        )
        bucket["logical_bits_per_die"] += arr["logical_bits_per_die"]
        bucket["logical_mib_per_die"] += arr["logical_mib_per_die"]
        bucket["ecc_overhead_bits_per_die"] += arr["ecc_overhead_bits_per_die"]
        bucket["redundancy_overhead_bits_per_die"] += arr["redundancy_overhead_bits_per_die"]
        bucket["physical_bits_per_die"] += arr["physical_bits_per_die"]
        bucket["macro_cuts_per_die"] += arr["macro_cuts_per_die"]
        bucket["area_per_die_mm2"] += arr["area_per_die_mm2"]

    total_logical_bits = sum(a["logical_bits_per_die"] for a in arrays)
    total_ecc_bits = sum(a["ecc_overhead_bits_per_die"] for a in arrays)
    total_redundancy_bits = sum(a["redundancy_overhead_bits_per_die"] for a in arrays)
    total_physical_bits = sum(a["physical_bits_per_die"] for a in arrays)
    total_area_per_die_mm2 = sum(a["area_per_die_mm2"] for a in arrays)
    total_cuts_per_die = sum(a["macro_cuts_per_die"] for a in arrays)

    tmem_arr = next(a for a in arrays if a["array_id"] == "tmem_tensor_bank")
    tmem_dual_1rw_mm2 = (
        tmem_arr["physical_bits_per_die"]
        * node.sram_1rw_bitcell_um2
        * B2_PARAMETRIC_CONSTANTS["sram_dual_banked_1rw_area_multiplier"]
        / node.sram_array_efficiency
    ) / 1e6
    tmem_native_1r1w_mm2 = (
        tmem_arr["physical_bits_per_die"]
        * node.sram_1rw_bitcell_um2
        * node.sram_1r1w_area_multiplier
        / node.sram_array_efficiency
    ) / 1e6

    # Banked TMEM bandwidth calculation (64 bits/bank/cycle across 32 banks = 256 B/cycle/core)
    tmem_bytes_per_cycle_per_core = sku.tmem_banks_per_core * 8
    tmem_bw_tbps_per_die = (
        cores_per_die * tmem_bytes_per_cycle_per_core * (sku.clock_mhz_target / 1000.0)
    ) / 1000.0

    return {
        "tmem_port_mode": tmem_port_mode,
        "arrays": arrays,
        "subsystem_summary": subsystem_summary,
        "totals_per_die": {
            "logical_bits": total_logical_bits,
            "logical_mib": total_logical_bits / (8.0 * 1024.0 * 1024.0),
            "ecc_overhead_bits": total_ecc_bits,
            "redundancy_overhead_bits": total_redundancy_bits,
            "physical_bits": total_physical_bits,
            "macro_cuts": total_cuts_per_die,
            "sram_total_mm2": total_area_per_die_mm2,
            "effective_mbit_per_mm2": (total_logical_bits / 1e6) / total_area_per_die_mm2,
            "ecc_plus_redundancy_pct": 100.0 * (total_ecc_bits + total_redundancy_bits) / total_logical_bits,
        },
        "totals_package": {
            "die_count": sku.die_count,
            "logical_mib": sku.die_count * total_logical_bits / (8.0 * 1024.0 * 1024.0),
            "physical_bits": sku.die_count * total_physical_bits,
            "sram_total_mm2": sku.die_count * total_area_per_die_mm2,
        },
        "tmem_architecture": {
            "kib_per_core": sku.tmem_kib_per_core,
            "mib_per_die": (cores_per_die * sku.tmem_kib_per_core) / 1024.0,
            "mib_package": (sku.die_count * cores_per_die * sku.tmem_kib_per_core) / 1024.0,
            "banks_per_core": sku.tmem_banks_per_core,
            "aggregate_bw_tbps_per_die_at_target_clk": tmem_bw_tbps_per_die,
            "dual_banked_1rw_mm2_per_die": tmem_dual_1rw_mm2,
            "native_1r1w_mm2_per_die": tmem_native_1r1w_mm2,
            "area_savings_mm2_per_die": tmem_native_1r1w_mm2 - tmem_dual_1rw_mm2,
            "area_savings_pct": 100.0 * (tmem_native_1r1w_mm2 - tmem_dual_1rw_mm2) / tmem_native_1r1w_mm2,
        },
    }


def compute_b2_area_and_shoreline(
    sku: B2SkuSpec,
    node: NodeScalingSpec,
    measured: dict[str, Any],
    *,
    tmem_port_mode: str = "dual_banked_1rw",
) -> dict[str, Any]:
    """Compute subsystem logic, SRAM, hard-IP areas and physical shoreline feasibility."""
    macros = measured["measured_asap7_macros"]
    yosys_units = measured["yosys_asap7_unit_baselines"]

    fedp_n2_area = macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_stdcell_area_um2"]
    mul_f16_synth_area = macros["vx_tcu_tfr_mul_f16_asap7"]["synth_stdcell_area_um2"]
    pnr_area_mult = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_to_synth_area_ratio"]
    dft_synth_area = macros["vx_asic_dft_top_asap7"]["synth_stdcell_area_um2"]
    soc_synth_area = macros["vx_asic_soc_top_asap7_fakeram7"]["synth_stdcell_area_um2"]

    cores_per_die = sku.clusters_per_die * sku.cores_per_cluster
    is_full_die = cores_per_die >= 64
    _, _, tc_k = _vortex_tcu_block_shape(sku.threads_per_warp)

    # 1. Core Scalar/Vector/L1/MMU/DXA Logic (anchored to Yosys ASAP7 baselines)
    lane_scale = (
        (sku.threads_per_warp / 8.0)
        * sku.issue_width
        * B2_PARAMETRIC_CONSTANTS["rv64x_lane_width_area_scale_vs_rv32"]
    )
    ctrl_scale = (
        (sku.warps_per_core / 8.0)
        * (0.5 + 0.5 * sku.issue_width)
        * B2_PARAMETRIC_CONSTANTS["rv64x_ctrl_width_area_scale_vs_rv32"]
    )
    scalar_core_asap7_um2 = yosys_units["core_8t_8w_rv32_um2"] * (
        B2_PARAMETRIC_CONSTANTS["core_scalar_lane_area_fraction"] * lane_scale
        + B2_PARAMETRIC_CONSTANTS["core_scalar_ctrl_area_fraction"] * ctrl_scale
    )
    mufu_core_asap7_um2 = yosys_units["mufu_16t_um2"] * (sku.threads_per_warp / 16.0) * 1.5
    l1_lmem_ctrl_core_asap7_um2 = (
        yosys_units["cache_ctrl_um2"] * (1.0 if is_full_die else 0.5)
        + yosys_units["lmem_ctrl_um2"] * (1.5 if is_full_die else 0.75)
    )
    vm_core_asap7_um2 = (
        B2_PARAMETRIC_CONSTANTS["sv48_mmu_tlb_asap7_um2_per_core"]
        if is_full_die
        else 48000.0
    )
    dxa_core_asap7_um2 = (
        yosys_units["dxa_16t_um2"]
        * B2_PARAMETRIC_CONSTANTS["dxa_5d_tma_scale_vs_b1"]
        * (1.0 if is_full_die else 0.40)
    )
    core_non_tcu_asap7_um2 = (
        scalar_core_asap7_um2
        + mufu_core_asap7_um2
        + l1_lmem_ctrl_core_asap7_um2
        + vm_core_asap7_um2
        + dxa_core_asap7_um2
    )

    # 2. TFRv2 / tcgen05 16x8x8 Systolic Pipes + 2:4 Sparsity + Microscale + TMEM Arbiters
    fedps_per_core = (sku.threads_per_warp // sku.tcu_pe_ratio) * sku.tcu_pipes_per_core
    mul_frac = mul_f16_synth_area / fedp_n2_area
    n_scale = mul_frac * (tc_k / 2.0) + (1.0 - mul_frac) * (1.0 + 0.35 * (tc_k / 2.0 - 1.0))
    fedp_base_core_asap7_um2 = (
        fedps_per_core
        * fedp_n2_area
        * n_scale
        * B2_PARAMETRIC_CONSTANTS["tfr_v2_fedp_multiformat_area_overhead"]
        * B2_PARAMETRIC_CONSTANTS["tfr_v2_sparsity_microscale_area_factor"]
    )
    wide_systolic_expansion_asap7_um2 = (
        B2_PARAMETRIC_CONSTANTS["tfr_v2_wide_systolic_core_asap7_um2"]
        if is_full_die
        else B2_PARAMETRIC_CONSTANTS["tfr_v2_wide_systolic_tile_asap7_um2"]
    )
    tmem_arb_ctrl_asap7_um2 = B2_PARAMETRIC_CONSTANTS["tfr_v2_tmem_arbiter_ctrl_asap7_um2_per_core"]
    tfr_v2_core_asap7_um2 = (
        fedp_base_core_asap7_um2 + wide_systolic_expansion_asap7_um2 + tmem_arb_ctrl_asap7_um2
    )

    # 3. Uncore: L2 Controllers, Coherent Directory/Snoop, 2D Mesh NoC, CP, MIG, DE, RAS/PMU/Sec
    l2_ctrl_asap7_um2 = (
        sku.l2_banks_per_die * B2_PARAMETRIC_CONSTANTS["l2_bank_ctrl_asap7_um2"]
        + (
            B2_PARAMETRIC_CONSTANTS["coherent_dir_snoop_ctrl_asap7_um2_per_die"]
            if sku.has_coherent_directory
            else 0.0
        )
    )
    noc_routers = sku.noc_mesh_rows * sku.noc_mesh_cols
    noc_asap7_um2 = (
        noc_routers * B2_PARAMETRIC_CONSTANTS["noc_router_2d_mesh_asap7_um2"]
        + sku.clusters_per_die * B2_PARAMETRIC_CONSTANTS["noc_mesh_link_repeater_asap7_um2_per_cluster"]
        if is_full_die
        else B2_PARAMETRIC_CONSTANTS["tile_uncore_shim_asap7_um2"]
    )
    cp_mig_de_sec_asap7_um2 = (
        (B2_PARAMETRIC_CONSTANTS["gigathread_cp_asap7_um2"] if sku.has_gigathread_cp else 0.0)
        + (B2_PARAMETRIC_CONSTANTS["mig_partitioner_asap7_um2"] if sku.has_mig else 0.0)
        + (B2_PARAMETRIC_CONSTANTS["hardware_de_engine_asap7_um2"] if sku.has_hardware_de else 0.0)
        + (B2_PARAMETRIC_CONSTANTS["ras_pmu_sec_aes256_asap7_um2"] if sku.has_ras_pmu_sec_aes else 0.0)
        + soc_synth_area
        + dft_synth_area
    )

    pnr_expansion = pnr_area_mult / node.pnr_macro_utilization
    logic_scale = node.logic_area_scale_vs_asap7 * pnr_expansion

    cores_scalar_synth_asap7_mm2 = (cores_per_die * core_non_tcu_asap7_um2) / 1e6
    tfr_v2_synth_asap7_mm2 = (cores_per_die * tfr_v2_core_asap7_um2) / 1e6
    l2_dir_ctrl_synth_asap7_mm2 = l2_ctrl_asap7_um2 / 1e6
    noc_mesh_synth_asap7_mm2 = noc_asap7_um2 / 1e6
    uncore_engines_synth_asap7_mm2 = cp_mig_de_sec_asap7_um2 / 1e6

    total_synth_asap7_mm2 = (
        cores_scalar_synth_asap7_mm2
        + tfr_v2_synth_asap7_mm2
        + l2_dir_ctrl_synth_asap7_mm2
        + noc_mesh_synth_asap7_mm2
        + uncore_engines_synth_asap7_mm2
    )

    routed_subsystems_mm2 = {
        "rv64x_cores_scalar_l1_mmu_dxa": cores_scalar_synth_asap7_mm2 * logic_scale,
        "tfr_v2_systolic_sparsity_microscale_tmem_ctrl": tfr_v2_synth_asap7_mm2 * logic_scale,
        "l2_slc_ctrl_and_coherent_directory": l2_dir_ctrl_synth_asap7_mm2 * logic_scale,
        "noc_2d_mesh_routers_and_links": noc_mesh_synth_asap7_mm2 * logic_scale,
        "cp_mig_de_ras_pmu_sec_aes_shell": uncore_engines_synth_asap7_mm2 * logic_scale,
    }
    logic_stdcell_scaled_mm2 = total_synth_asap7_mm2 * node.logic_area_scale_vs_asap7
    logic_routed_mm2 = sum(routed_subsystems_mm2.values())
    routing_halo_mm2 = logic_routed_mm2 - logic_stdcell_scaled_mm2

    # 4. SRAM Macro Area (TMEM + L2/SLC/Directory + LMEM/L1/RF/DE/HBM)
    sram_budget = compute_b2_sram_budget(sku, node, tmem_port_mode=tmem_port_mode)
    sram_total_mm2 = sram_budget["totals_per_die"]["sram_total_mm2"]

    # 5. Hard IP / PHY Ring Area
    if is_full_die:
        hbm_area_n4p = sku.hbm3e_stacks_per_die * B2_PARAMETRIC_CONSTANTS["hard_ip_n4p_mm2_per_hbm3e_stack"]
        ucie_area_n4p = B2_PARAMETRIC_CONSTANTS["hard_ip_n4p_mm2_ucie_10tbps"]
        pcie_area_n4p = B2_PARAMETRIC_CONSTANTS["hard_ip_n4p_mm2_pcie_gen6_x16_iommu"]
        pll_pad_area_n4p = B2_PARAMETRIC_CONSTANTS["hard_ip_n4p_mm2_plls_padring_keepout_full"]
        hard_ip_breakdown_mm2 = {
            "hbm3e_8stack_phy_and_ctrl": hbm_area_n4p * node.phy_area_scale_vs_n4p,
            "ucie_2_0_10tbps_d2d_phy": ucie_area_n4p * node.phy_area_scale_vs_n4p,
            "pcie_gen6_x16_serdes_and_iommu": pcie_area_n4p * node.phy_area_scale_vs_n4p,
            "plls_pvt_jtag_padring_keepout": pll_pad_area_n4p * node.phy_area_scale_vs_n4p,
        }
    else:
        # MPW tile carries an explicit passive UCIe test-stub PHY macro (0.0 active D2D BW)
        hard_ip_breakdown_mm2 = {
            "mpw_axi_serdes_and_ucie_test_stub": (
                B2_PARAMETRIC_CONSTANTS["hard_ip_n4p_mm2_tile_serdes_ucie_stub"]
                * node.phy_area_scale_vs_n4p
            ),
            "pll_reset_and_wirebond_padring": (
                B2_PARAMETRIC_CONSTANTS["hard_ip_n4p_mm2_tile_pll_padring"]
                * node.phy_area_scale_vs_n4p
            ),
        }
    hard_ip_total_mm2 = sum(hard_ip_breakdown_mm2.values())

    per_die_area_mm2 = logic_routed_mm2 + sram_total_mm2 + hard_ip_total_mm2
    total_silicon_area_mm2 = per_die_area_mm2 * sku.die_count
    within_reticle_limit = per_die_area_mm2 <= RETICLE_LIMIT_MM2
    reticle_utilization_pct = (per_die_area_mm2 / RETICLE_LIMIT_MM2) * 100.0

    # 6. Die Geometry & Shoreline Feasibility Check
    if is_full_die:
        aspect = B2_PARAMETRIC_CONSTANTS["preferred_die_aspect_ratio"]
        die_width_mm = math.sqrt(per_die_area_mm2 / aspect)
        die_height_mm = per_die_area_mm2 / die_width_mm
        if die_width_mm > RETICLE_FIELD_WIDTH_MM and per_die_area_mm2 <= RETICLE_LIMIT_MM2:
            die_width_mm = RETICLE_FIELD_WIDTH_MM
            die_height_mm = per_die_area_mm2 / die_width_mm
        within_field_dims = (
            die_width_mm <= RETICLE_FIELD_WIDTH_MM and die_height_mm <= RETICLE_FIELD_HEIGHT_MM
        )
    else:
        die_width_mm = math.sqrt(per_die_area_mm2)
        die_height_mm = die_width_mm
        within_field_dims = True

    die_perimeter_mm = 2.0 * (die_width_mm + die_height_mm)

    if is_full_die:
        hbm_stacks_per_edge = sku.hbm3e_stacks_per_die // 2
        hbm_edge_required_mm = hbm_stacks_per_edge * B2_PARAMETRIC_CONSTANTS["shoreline_mm_per_hbm3e_stack"]
        hbm_total_shoreline_mm = sku.hbm3e_stacks_per_die * B2_PARAMETRIC_CONSTANTS["shoreline_mm_per_hbm3e_stack"]
        ucie_shoreline_mm = (
            sku.ucie_bw_tbps_per_die * 1000.0
        ) / B2_PARAMETRIC_CONSTANTS["shoreline_gbps_per_mm_ucie_2_0"]
        pcie_shoreline_mm = B2_PARAMETRIC_CONSTANTS["shoreline_mm_pcie_gen6_x16"]
        misc_shoreline_mm = B2_PARAMETRIC_CONSTANTS["shoreline_mm_misc_io_and_corners_full"]
        total_shoreline_required_mm = (
            hbm_total_shoreline_mm + ucie_shoreline_mm + pcie_shoreline_mm + misc_shoreline_mm
        )
        edge_fits = {
            "west_hbm3e_4stack_mm": (hbm_edge_required_mm, die_height_mm, hbm_edge_required_mm <= die_height_mm - 2.0),
            "east_hbm3e_4stack_mm": (hbm_edge_required_mm, die_height_mm, hbm_edge_required_mm <= die_height_mm - 2.0),
            "south_ucie_2_0_lsi_mm": (ucie_shoreline_mm, die_width_mm, ucie_shoreline_mm <= die_width_mm - 2.0),
            "north_pcie_gen6_misc_mm": (pcie_shoreline_mm + 4.0, die_width_mm, (pcie_shoreline_mm + 4.0) <= die_width_mm - 2.0),
        }
        shoreline_feasible = (
            total_shoreline_required_mm <= die_perimeter_mm
            and all(v[2] for v in edge_fits.values())
        )
    else:
        hbm_total_shoreline_mm = 0.0
        ucie_shoreline_mm = 1.6  # Passive MPW UCIe test-stub padring keepout (0.0 active D2D BW)
        pcie_shoreline_mm = 2.0
        misc_shoreline_mm = B2_PARAMETRIC_CONSTANTS["shoreline_mm_tile_io_and_corners"]
        total_shoreline_required_mm = ucie_shoreline_mm + pcie_shoreline_mm + misc_shoreline_mm
        edge_fits = {
            "tile_perimeter_mm": (total_shoreline_required_mm, die_perimeter_mm, total_shoreline_required_mm <= die_perimeter_mm),
        }
        shoreline_feasible = total_shoreline_required_mm <= die_perimeter_mm

    return {
        "per_die_area_breakdown_mm2": {
            "logic_stdcell_scaled_mm2": logic_stdcell_scaled_mm2,
            "routing_and_utilization_overhead_mm2": routing_halo_mm2,
            "logic_routed_mm2": logic_routed_mm2,
            "logic_subsystems_routed_mm2": routed_subsystems_mm2,
            "sram_tmem_mm2": sram_budget["subsystem_summary"]["tmem"]["area_per_die_mm2"],
            "sram_l2_slc_dir_mm2": sram_budget["subsystem_summary"]["l2_slc"]["area_per_die_mm2"],
            "sram_lmem_l1_rf_mm2": sram_budget["subsystem_summary"]["lmem_l1_rf"]["area_per_die_mm2"],
            "sram_total_mm2": sram_total_mm2,
            "hard_ip_breakdown_mm2": hard_ip_breakdown_mm2,
            "hard_ip_total_mm2": hard_ip_total_mm2,
            "total_die_area_mm2": per_die_area_mm2,
            "total_synth_asap7_mm2": total_synth_asap7_mm2,
            "tfr_v2_core_asap7_um2": tfr_v2_core_asap7_um2,
            "scalar_core_asap7_um2": core_non_tcu_asap7_um2,
        },
        "package_silicon_area_mm2": total_silicon_area_mm2,
        "reticle_and_field_check": {
            "reticle_limit_mm2": RETICLE_LIMIT_MM2,
            "reticle_utilization_pct": reticle_utilization_pct,
            "within_reticle_limit": within_reticle_limit,
            "die_width_mm": die_width_mm,
            "die_height_mm": die_height_mm,
            "within_reticle_field_26x33mm": within_field_dims,
        },
        "shoreline_budget": {
            "die_perimeter_mm": die_perimeter_mm,
            "hbm3e_shoreline_mm": hbm_total_shoreline_mm,
            "ucie_2_0_shoreline_mm": ucie_shoreline_mm,
            "pcie_gen6_shoreline_mm": pcie_shoreline_mm,
            "misc_keepout_corners_mm": misc_shoreline_mm,
            "total_shoreline_required_mm": total_shoreline_required_mm,
            "shoreline_utilization_pct": (total_shoreline_required_mm / die_perimeter_mm) * 100.0,
            "edge_checks": {
                k: {"required_mm": v[0], "available_mm": v[1], "fits": v[2]}
                for k, v in edge_fits.items()
            },
            "shoreline_feasible": shoreline_feasible,
        },
        "sram_budget": sram_budget,
    }


def compute_b2_power_thermal_packaging(
    sku: B2SkuSpec,
    node: NodeScalingSpec,
    measured: dict[str, Any],
    area_info: dict[str, Any],
    *,
    workload_id: str = "peak_tdp_stress",
    clock_mhz: float | None = None,
    dvfs_bin: str = "nominal",
) -> dict[str, Any]:
    """Compute workload-dependent power breakdown, thermal T_j, DVFS curve, and CoWoS-L budgets."""
    if workload_id not in WORKLOAD_PROFILES:
        raise ValueError(f"Unknown workload {workload_id!r}; expected {VALID_WORKLOADS}")
    if dvfs_bin not in DVFS_BINS:
        raise ValueError(f"Unknown dvfs_bin {dvfs_bin!r}; expected {VALID_DVFS_BINS}")

    wl = WORKLOAD_PROFILES[workload_id]
    dvfs = DVFS_BINS[dvfs_bin]
    base_clock_mhz = float(clock_mhz if clock_mhz is not None else sku.clock_mhz_target)
    eff_clock_mhz = base_clock_mhz * dvfs.clock_scale
    clock_ghz = eff_clock_mhz / 1000.0
    vdd_scale_sq = dvfs.vdd_scale * dvfs.vdd_scale

    macros = measured["measured_asap7_macros"]
    fedp_e01_mw = macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_dyn_power_mw_at_1ghz_0p1_act"]
    pnr_area_mult = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_to_synth_area_ratio"]
    pnr_dyn_mult = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_to_synth_dyn_power_ratio"]
    mul_pnr_dyn_density = macros["vx_tcu_tfr_mul_f16_asap7"][
        "pnr_dyn_power_density_w_per_mm2_at_1ghz_0p1_act"
    ]

    cores_per_die = sku.clusters_per_die * sku.cores_per_cluster
    is_full_die = cores_per_die >= 64
    _, _, tc_k = _vortex_tcu_block_shape(sku.threads_per_warp)
    fedps_per_core = (sku.threads_per_warp // sku.tcu_pe_ratio) * sku.tcu_pipes_per_core
    mul_f16_synth_area = macros["vx_tcu_tfr_mul_f16_asap7"]["synth_stdcell_area_um2"]
    fedp_n2_area = macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_stdcell_area_um2"]
    mul_frac = mul_f16_synth_area / fedp_n2_area
    n_scale = mul_frac * (tc_k / 2.0) + (1.0 - mul_frac) * (1.0 + 0.35 * (tc_k / 2.0 - 1.0))

    tcu_activity_mult = (
        B2_PARAMETRIC_CONSTANTS["gemm_tcu_effective_toggle_factor"]
        / B2_PARAMETRIC_CONSTANTS["opensta_default_input_activity"]
    )
    tcu_dyn_asap7_per_die_w = (
        cores_per_die
        * fedps_per_core
        * (
            fedp_e01_mw
            * tcu_activity_mult
            * pnr_dyn_mult
            * n_scale
            * B2_PARAMETRIC_CONSTANTS["tfr_v2_dynamic_power_overhead"]
        )
        * (clock_ghz * 1e9)
        * 1e-12
    )
    total_synth_mm2 = area_info["per_die_area_breakdown_mm2"]["total_synth_asap7_mm2"]
    tfr_v2_synth_mm2 = (
        cores_per_die * area_info["per_die_area_breakdown_mm2"]["tfr_v2_core_asap7_um2"]
    ) / 1e6
    non_tcu_synth_mm2 = max(0.1, total_synth_mm2 - tfr_v2_synth_mm2)
    core_uncore_dyn_asap7_per_die_w = (
        non_tcu_synth_mm2
        * pnr_area_mult
        * mul_pnr_dyn_density
        * B2_PARAMETRIC_CONSTANTS["non_fedp_logic_active_duty_factor"]
        * clock_ghz
    )

    tcu_dyn_peak_per_die_w = tcu_dyn_asap7_per_die_w * node.logic_dyn_energy_scale_vs_asap7 * vdd_scale_sq
    core_uncore_dyn_peak_per_die_w = (
        core_uncore_dyn_asap7_per_die_w * node.logic_dyn_energy_scale_vs_asap7 * vdd_scale_sq
    )

    tmem_tbps_per_die = (
        (cores_per_die * sku.tcu_pipes_per_core * 64.0 * clock_ghz) / 1000.0
    ) * B2_PARAMETRIC_CONSTANTS["sram_internal_bandwidth_duty_factor"]
    tmem_arr = next(
        a for a in area_info["sram_budget"]["arrays"] if a["array_id"] == "tmem_tensor_bank"
    )
    tmem_dyn_peak_per_die_w = (
        tmem_tbps_per_die
        * node.sram_energy_pj_per_byte
        * B2_PARAMETRIC_CONSTANTS["tmem_energy_scale_vs_cache_sram"]
        * tmem_arr["energy_mult"]
        * vdd_scale_sq
    )

    cache_sram_tbps_per_die = (
        (cores_per_die * sku.issue_width * (sku.threads_per_warp * 4) * clock_ghz) / 1000.0
    ) * B2_PARAMETRIC_CONSTANTS["sram_internal_bandwidth_duty_factor"]
    cache_sram_dyn_peak_per_die_w = cache_sram_tbps_per_die * node.sram_energy_pj_per_byte * vdd_scale_sq

    if is_full_die:
        hbm_io_peak_per_die_w = (sku.hbm3e_bw_tbps_per_die * 8.0) * node.hbm_io_energy_pj_per_bit
        ucie_energy_pj = B2_PARAMETRIC_CONSTANTS["ucie_energy_pj_per_bit"][node.node_id]
        ucie_peak_per_die_w = (
            (sku.ucie_bw_tbps_per_die * 8.0) * ucie_energy_pj * (0.60 if sku.die_count == 2 else 0.15)
        )
        pcie_peak_per_die_w = B2_PARAMETRIC_CONSTANTS["pcie_gen6_x16_active_power_w"][node.node_id]
        hard_ip_base_per_die_w = (
            B2_PARAMETRIC_CONSTANTS["hard_ip_base_power_asap7_w_full"]
            * node.logic_dyn_energy_scale_vs_asap7
        )
    else:
        hbm_io_peak_per_die_w = node.mpw_tile_io_power_w
        ucie_peak_per_die_w = 0.25 * node.logic_dyn_energy_scale_vs_asap7
        pcie_peak_per_die_w = 0.45 * node.logic_dyn_energy_scale_vs_asap7
        hard_ip_base_per_die_w = (
            B2_PARAMETRIC_CONSTANTS["hard_ip_base_power_asap7_w_tile"]
            * node.logic_dyn_energy_scale_vs_asap7
        )

    def _compute_breakdown(
        *,
        tcu_duty: float,
        uncore_duty: float,
        tmem_duty: float,
        cache_duty: float,
        hbm_duty: float,
        ucie_duty: float,
        pcie_duty: float,
        fmt_key: str,
    ) -> dict[str, float]:
        fmt_mult = B2_PARAMETRIC_CONSTANTS["precision_dynamic_power_multipliers"][fmt_key]
        tcu_w = sku.die_count * tcu_dyn_peak_per_die_w * tcu_duty * fmt_mult
        uncore_w = sku.die_count * core_uncore_dyn_peak_per_die_w * uncore_duty
        tmem_w = sku.die_count * tmem_dyn_peak_per_die_w * tmem_duty
        cache_w = sku.die_count * cache_sram_dyn_peak_per_die_w * cache_duty
        hbm_w = sku.die_count * hbm_io_peak_per_die_w * hbm_duty
        ucie_w = sku.die_count * ucie_peak_per_die_w * ucie_duty
        pcie_w = sku.die_count * pcie_peak_per_die_w * pcie_duty
        hard_base_w = sku.die_count * hard_ip_base_per_die_w

        peak_active_die_w = sku.die_count * (
            tcu_dyn_peak_per_die_w
            + core_uncore_dyn_peak_per_die_w
            + tmem_dyn_peak_per_die_w
            + cache_sram_dyn_peak_per_die_w
            + B2_PARAMETRIC_CONSTANTS["on_die_hbm_phy_leakage_share"] * hbm_io_peak_per_die_w
            + 0.5 * ucie_peak_per_die_w
            + pcie_peak_per_die_w
            + hard_ip_base_per_die_w
        )
        base_leak_w = (
            peak_active_die_w
            * (node.leakage_fraction_of_die_power / (1.0 - node.leakage_fraction_of_die_power))
            * dvfs.vdd_scale
        )
        thermal_leak_factor = 0.72 + 0.28 * (0.5 * tcu_duty + 0.5 * hbm_duty)
        leak_w = base_leak_w * thermal_leak_factor

        total_w = tcu_w + uncore_w + tmem_w + cache_w + hbm_w + ucie_w + pcie_w + hard_base_w + leak_w
        return {
            "dynamic_compute_tcu_w": tcu_w,
            "dynamic_compute_core_uncore_w": uncore_w,
            "dynamic_compute_total_w": tcu_w + uncore_w,
            "dynamic_tmem_w": tmem_w,
            "dynamic_cache_sram_w": cache_w,
            "dynamic_sram_total_w": tmem_w + cache_w,
            "hbm3e_io_and_phy_w": hbm_w,
            "ucie_d2d_phy_w": ucie_w,
            "pcie_gen6_and_hard_ip_w": pcie_w + hard_base_w,
            "static_leakage_w": leak_w,
            "total_power_w": total_w,
        }

    selected_power = _compute_breakdown(
        tcu_duty=wl.tcu_activity_duty,
        uncore_duty=wl.core_uncore_duty,
        tmem_duty=wl.tmem_bw_duty,
        cache_duty=wl.sram_cache_bw_duty,
        hbm_duty=wl.hbm_bw_duty,
        ucie_duty=wl.ucie_bw_duty,
        pcie_duty=wl.pcie_duty,
        fmt_key=wl.active_precision,
    )
    peak_tdp_by_precision = {
        fmt_key: _compute_breakdown(
            tcu_duty=1.0,
            uncore_duty=1.0,
            tmem_duty=1.0,
            cache_duty=1.0,
            hbm_duty=1.0,
            ucie_duty=1.0,
            pcie_duty=1.0,
            fmt_key=fmt_key,
        )
        for fmt_key in B2_PARAMETRIC_CONSTANTS["precision_dynamic_power_multipliers"]
    }
    all_workloads_power = {
        wid: _compute_breakdown(
            tcu_duty=wspec.tcu_activity_duty,
            uncore_duty=wspec.core_uncore_duty,
            tmem_duty=wspec.tmem_bw_duty,
            cache_duty=wspec.sram_cache_bw_duty,
            hbm_duty=wspec.hbm_bw_duty,
            ucie_duty=wspec.ucie_bw_duty,
            pcie_duty=wspec.pcie_duty,
            fmt_key=wspec.active_precision,
        )
        for wid, wspec in WORKLOAD_PROFILES.items()
    }

    pkg_area_mm2 = area_info["package_silicon_area_mm2"]
    peak_tdp_w = peak_tdp_by_precision["fp16_bf16"]["total_power_w"]
    selected_w = selected_power["total_power_w"]

    thermal_env: dict[str, Any] = {}
    for cool_mode, tspec in B2_PARAMETRIC_CONSTANTS["thermal_specs"].items():
        if sku.sku_id == "aigpu-b2-tile":
            r_theta = tspec["r_theta_ja_c_per_w_tile"]
        elif sku.die_count == 2:
            r_theta = tspec["r_theta_ja_c_per_w_dual"]
        else:
            r_theta = tspec["r_theta_ja_c_per_w_full"]
        tj_selected = tspec["ambient_c"] + selected_w * r_theta
        tj_peak_tdp = tspec["ambient_c"] + peak_tdp_w * r_theta
        thermal_env[cool_mode] = {
            "label": tspec["label"],
            "ambient_c": tspec["ambient_c"],
            "r_theta_ja_c_per_w": r_theta,
            "max_tj_c": tspec["max_tj_c"],
            "tj_at_selected_workload_c": tj_selected,
            "tj_at_peak_tdp_c": tj_peak_tdp,
            "meets_thermal_ceiling_at_peak_tdp": tj_peak_tdp <= tspec["max_tj_c"],
            "thermal_margin_c": tspec["max_tj_c"] - tj_peak_tdp,
        }

    vdd_v = B2_PARAMETRIC_CONSTANTS["nominal_vdd_v"][node.node_id] * dvfs.vdd_scale
    peak_current_a = peak_tdp_w / vdd_v
    if is_full_die:
        hbm_pkg_area_mm2 = sku.die_count * sku.hbm3e_stacks_per_die * 121.0
        interposer_area_mm2 = (pkg_area_mm2 + hbm_pkg_area_mm2) * (1.28 if sku.die_count == 2 else 1.22)
        substrate_area_mm2 = 75.0 * 75.0 if sku.die_count == 2 else 62.5 * 62.5
        packaging_tech = (
            "CoWoS-L (RDL Interposer + 3x Embedded Silicon LSI Bridges)"
            if sku.die_count == 2
            else "CoWoS-S / CoWoS-R 2.5D Interposer"
        )
        warpage_est_um = 112.0 if sku.die_count == 2 else 74.0
        warpage_limit_um = 150.0
        lsi_bridges = 3 if sku.die_count == 2 else 0
    else:
        interposer_area_mm2 = pkg_area_mm2 * 1.4
        substrate_area_mm2 = 25.0 * 25.0
        packaging_tech = "FC-BGA Organic Substrate (MPW Shuttle Package)"
        warpage_est_um = 35.0
        warpage_limit_um = 120.0
        lsi_bridges = 0

    c4_power_bump_count = int(math.ceil(peak_current_a / 0.16))
    # Ohm's-law PDN IR drop: derive effective R_pdn from nominal-bin package current so IR scales proportionally with I_pkg
    nom_dvfs = DVFS_BINS["nominal"]
    nom_vdd_sq = nom_dvfs.vdd_scale * nom_dvfs.vdd_scale
    nom_clock_ghz = base_clock_mhz / 1000.0
    nom_tcu_peak_w = (tcu_dyn_asap7_per_die_w / clock_ghz) * nom_clock_ghz * node.logic_dyn_energy_scale_vs_asap7 * nom_vdd_sq
    nom_uncore_peak_w = (core_uncore_dyn_asap7_per_die_w / clock_ghz) * nom_clock_ghz * node.logic_dyn_energy_scale_vs_asap7 * nom_vdd_sq
    nom_tmem_peak_w = (
        (((cores_per_die * sku.tcu_pipes_per_core * 64.0 * nom_clock_ghz) / 1000.0) * B2_PARAMETRIC_CONSTANTS["sram_internal_bandwidth_duty_factor"])
        * node.sram_energy_pj_per_byte
        * B2_PARAMETRIC_CONSTANTS["tmem_energy_scale_vs_cache_sram"]
        * tmem_arr["energy_mult"]
        * nom_vdd_sq
    )
    nom_cache_peak_w = (
        (((cores_per_die * sku.issue_width * (sku.threads_per_warp * 4) * nom_clock_ghz) / 1000.0) * B2_PARAMETRIC_CONSTANTS["sram_internal_bandwidth_duty_factor"])
        * node.sram_energy_pj_per_byte
        * nom_vdd_sq
    )
    nom_peak_active_die_w = sku.die_count * (
        nom_tcu_peak_w
        + nom_uncore_peak_w
        + nom_tmem_peak_w
        + nom_cache_peak_w
        + B2_PARAMETRIC_CONSTANTS["on_die_hbm_phy_leakage_share"] * hbm_io_peak_per_die_w
        + 0.5 * ucie_peak_per_die_w
        + pcie_peak_per_die_w
        + hard_ip_base_per_die_w
    )
    nom_leak_w = (
        nom_peak_active_die_w
        * (node.leakage_fraction_of_die_power / (1.0 - node.leakage_fraction_of_die_power))
        * nom_dvfs.vdd_scale
    )
    nom_peak_tdp_w = (
        sku.die_count
        * (
            nom_tcu_peak_w
            + nom_uncore_peak_w
            + nom_tmem_peak_w
            + nom_cache_peak_w
            + hbm_io_peak_per_die_w
            + ucie_peak_per_die_w
            + pcie_peak_per_die_w
            + hard_ip_base_per_die_w
        )
        + nom_leak_w
    )
    nom_vdd_v = B2_PARAMETRIC_CONSTANTS["nominal_vdd_v"][node.node_id] * nom_dvfs.vdd_scale
    nom_peak_current_a = nom_peak_tdp_w / nom_vdd_v
    r_pdn_mohm = (18.5 if is_full_die else 9.0) / nom_peak_current_a
    pdn_ir_drop_mv = peak_current_a * r_pdn_mohm
    pdn_ir_limit_mv = 25.0

    measured_mul_fmax = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_fmax_mhz"]
    measured_fedp_fmax = macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_fmax_mhz"]
    projected_fmax_mhz = measured_mul_fmax * node.fmax_scale_vs_asap7_rvt

    return {
        "dvfs_bin": dvfs_bin,
        "selected_workload": workload_id,
        "selected_workload_power": selected_power,
        "peak_tdp_w": peak_tdp_w,
        "peak_tdp_by_precision": peak_tdp_by_precision,
        "all_workloads_power": all_workloads_power,
        "thermal_density_w_per_mm2_at_peak_tdp": peak_tdp_w / pkg_area_mm2,
        "thermal_density_w_per_mm2_at_workload": selected_w / pkg_area_mm2,
        "thermal_envelopes": thermal_env,
        "clock_and_frequency": {
            "modeled_target_clock_mhz": eff_clock_mhz,
            "measured_asap7_mul_f16_post_route_fmax_mhz": measured_mul_fmax,
            "measured_asap7_fedp_post_synth_fmax_mhz": measured_fedp_fmax,
            "projected_node_fmax_ceiling_mhz": projected_fmax_mhz,
            "meets_target_clock_at_projected_node": projected_fmax_mhz >= eff_clock_mhz,
        },
        "packaging_and_pdn": {
            "packaging_technology": packaging_tech,
            "lsi_bridge_count": lsi_bridges,
            "interposer_or_rdl_area_mm2": interposer_area_mm2,
            "package_substrate_area_mm2": substrate_area_mm2,
            "estimated_warpage_um": warpage_est_um,
            "warpage_limit_um": warpage_limit_um,
            "within_warpage_budget": warpage_est_um <= warpage_limit_um,
            "nominal_vdd_v": vdd_v,
            "peak_package_current_a": peak_current_a,
            "required_power_ground_bumps": c4_power_bump_count * 2,
            "estimated_pdn_ir_drop_mv": pdn_ir_drop_mv,
            "pdn_ir_drop_limit_mv": pdn_ir_limit_mv,
            "within_pdn_budget": pdn_ir_drop_mv <= pdn_ir_limit_mv,
        },
    }


def gross_dies_per_300mm_wafer(
    die_width_mm: float,
    die_height_mm: float,
    *,
    wafer_diameter_mm: float = 300.0,
    edge_exclusion_mm: float = 3.0,
    scribe_lane_mm: float = 0.10,
) -> int:
    """Count exact rectangular stepped dies fitting inside usable 300mm wafer radius."""
    _assert_positive_finite(die_width_mm, "die_width_mm")
    _assert_positive_finite(die_height_mm, "die_height_mm")
    usable_r = (wafer_diameter_mm / 2.0) - edge_exclusion_mm
    if usable_r <= 0.0:
        return 0
    step_x = die_width_mm + scribe_lane_mm
    step_y = die_height_mm + scribe_lane_mm
    max_cols = int(math.floor((2.0 * usable_r) / step_x)) + 2
    max_rows = int(math.floor((2.0 * usable_r) / step_y)) + 2

    best_count = 0
    for ox in (0.0, 0.5 * step_x):
        for oy in (0.0, 0.5 * step_y):
            count = 0
            x_start = -((max_cols // 2) * step_x) + ox
            y_start = -((max_rows // 2) * step_y) + oy
            for r in range(max_rows + 1):
                y0 = y_start + r * step_y
                y1 = y0 + die_height_mm
                for c in range(max_cols + 1):
                    x0 = x_start + c * step_x
                    x1 = x0 + die_width_mm
                    if (
                        (x0 * x0 + y0 * y0) <= usable_r * usable_r
                        and (x1 * x1 + y0 * y0) <= usable_r * usable_r
                        and (x0 * x0 + y1 * y1) <= usable_r * usable_r
                        and (x1 * x1 + y1 * y1) <= usable_r * usable_r
                    ):
                        count += 1
            if count > best_count:
                best_count = count
    return best_count


def _murphy_yield(d0_per_cm2: float, area_cm2: float) -> float:
    x = d0_per_cm2 * area_cm2
    if x <= 1e-12:
        return 1.0
    val = (1.0 - math.exp(-x)) / x
    return val * val


def _negbin_yield(d0_per_cm2: float, area_cm2: float, alpha: float) -> float:
    x = (d0_per_cm2 * area_cm2) / alpha
    if x <= 1e-12:
        return 1.0
    return (1.0 + x) ** (-alpha)


def compute_b2_yield_and_cost(
    sku: B2SkuSpec,
    node: NodeScalingSpec,
    area_info: dict[str, Any],
    *,
    d0_sweep: tuple[float, ...] = DEFAULT_D0_SWEEP,
    nominal_d0: float = 0.07,
) -> dict[str, Any]:
    """Compute 300mm wafer gross dies, Murphy/NegBin yield, SRAM repair uplift, and KGD cost."""
    ab = area_info["per_die_area_breakdown_mm2"]
    rc = area_info["reticle_and_field_check"]
    die_area_mm2 = ab["total_die_area_mm2"]
    sram_area_mm2 = ab["sram_total_mm2"]
    non_sram_area_mm2 = max(0.0, die_area_mm2 - sram_area_mm2)

    repair_cov = B2_PARAMETRIC_CONSTANTS["sram_repair_defect_coverage"]
    effective_area_unrepaired_cm2 = die_area_mm2 / 100.0
    effective_area_repaired_cm2 = (non_sram_area_mm2 + sram_area_mm2 * (1.0 - repair_cov)) / 100.0
    alpha = B2_PARAMETRIC_CONSTANTS["negbin_alpha"]

    gross_dpw = gross_dies_per_300mm_wafer(
        rc["die_width_mm"],
        rc["die_height_mm"],
        wafer_diameter_mm=B2_PARAMETRIC_CONSTANTS["wafer_diameter_mm"],
        edge_exclusion_mm=B2_PARAMETRIC_CONSTANTS["wafer_edge_exclusion_mm"],
        scribe_lane_mm=B2_PARAMETRIC_CONSTANTS["scribe_lane_mm"],
    )

    wafer_cost_usd = B2_PARAMETRIC_CONSTANTS["parametric_wafer_cost_usd"][node.node_id]
    kgd_test_yield = B2_PARAMETRIC_CONSTANTS["kgd_test_yield"]
    pkg_yield = (
        B2_PARAMETRIC_CONSTANTS["cowos_l_assembly_yield_dual"]
        if sku.die_count == 2
        else (
            B2_PARAMETRIC_CONSTANTS["cowos_s_assembly_yield_single"]
            if sku.hbm3e_stacks_per_die > 0
            else 0.985
        )
    )
    hbm_cost_usd = (
        sku.die_count
        * sku.hbm3e_stacks_per_die
        * B2_PARAMETRIC_CONSTANTS["parametric_hbm3e_stack_cost_usd"]
    )
    interposer_cost_usd = (
        B2_PARAMETRIC_CONSTANTS["parametric_cowos_l_interposer_cost_usd"]
        if sku.die_count == 2
        else (
            B2_PARAMETRIC_CONSTANTS["parametric_cowos_s_interposer_cost_usd"]
            if sku.hbm3e_stacks_per_die > 0
            else 25.0
        )
    )

    def _eval_d0(d0: float) -> dict[str, Any]:
        if (
            not isinstance(d0, (int, float))
            or isinstance(d0, bool)
            or not math.isfinite(float(d0))
            or float(d0) < 0.0
        ):
            raise ValueError(f"Defect density D0 must be finite and non-negative, got {d0!r}")
        d0_val = float(d0)
        y_murphy_raw = _murphy_yield(d0_val, effective_area_unrepaired_cm2)
        y_murphy_rep = _murphy_yield(d0_val, effective_area_repaired_cm2)
        y_nb_raw = _negbin_yield(d0_val, effective_area_unrepaired_cm2, alpha)
        y_nb_rep = _negbin_yield(d0_val, effective_area_repaired_cm2, alpha)

        good_dies_per_wafer = gross_dpw * y_nb_rep * kgd_test_yield
        kgd_die_cost = (
            (wafer_cost_usd / good_dies_per_wafer) if good_dies_per_wafer > 0.0 else float("inf")
        )
        composite_module_yield = (y_nb_rep ** sku.die_count) * pkg_yield
        pkg_silicon_bom_usd = (
            (sku.die_count * kgd_die_cost + hbm_cost_usd + interposer_cost_usd) / pkg_yield
            if math.isfinite(kgd_die_cost)
            else float("inf")
        )
        return {
            "d0_defects_per_cm2": float(d0),
            "murphy_yield_unrepaired": y_murphy_raw,
            "murphy_yield_sram_repaired": y_murphy_rep,
            "negbin_yield_unrepaired": y_nb_raw,
            "negbin_yield_sram_repaired": y_nb_rep,
            "sram_repair_uplift_pct_pts": 100.0 * (y_nb_rep - y_nb_raw),
            "good_kgds_per_wafer": good_dies_per_wafer,
            "kgd_die_cost_usd_est": kgd_die_cost,
            "package_assembly_yield": pkg_yield,
            "composite_module_yield": composite_module_yield,
            "package_silicon_bom_usd_est": pkg_silicon_bom_usd,
        }

    sweep_points = [_eval_d0(d0) for d0 in d0_sweep]
    nom_point = next(
        (p for p in sweep_points if abs(p["d0_defects_per_cm2"] - nominal_d0) < 1e-9),
        None,
    )
    if nom_point is None:
        nom_point = _eval_d0(nominal_d0)

    return {
        "wafer_diameter_mm": B2_PARAMETRIC_CONSTANTS["wafer_diameter_mm"],
        "gross_dies_per_wafer": gross_dpw,
        "die_area_mm2": die_area_mm2,
        "effective_area_unrepaired_cm2": effective_area_unrepaired_cm2,
        "effective_area_sram_repaired_cm2": effective_area_repaired_cm2,
        "parametric_wafer_cost_usd_est": wafer_cost_usd,
        "hbm3e_and_interposer_bom_usd_est": hbm_cost_usd + interposer_cost_usd,
        "nominal_point": nom_point,
        "d0_sweep": sweep_points,
        "cost_model_disclaimer": (
            "Parametric pre-quote silicon BOM estimates ONLY; NOT foundry or OSAT vendor quotes."
        ),
    }


def build_b2_published_vendor_baselines() -> dict[str, dict[str, Any]]:
    """Build published datacenter vendor reference baselines (strictly non-measured)."""
    specs: list[dict[str, Any]] = [
        {
            "id": "nvidia-b200-1die",
            "display_name": "NVIDIA B200 1-Die (Published Ref)",
            "vendor": "NVIDIA",
            "architecture": "Blackwell GB100 half-package die (TSMC 4NP)",
            "die_count": 1,
            "silicon_area_mm2": 800.0,
            "tdp_w": 500.0,
            "bandwidth_tbps": 4.00,
            "memory_spec": "HBM3e (4 stacks/die, 96 GB)",
            "est_module_price_usd": 17500.0,
            "peaks": {
                "fp16_bf16": (1125.0, 2250.0),
                "fp8": (2250.0, 4500.0),
                "nvfp4": (4500.0, 9000.0),
            },
            "source_citation": (
                "Published Vendor Reference Spec ONLY: 1/2 of NVIDIA B200 SXM package "
                "(~800 mm^2 die, 500 W half-TDP, 4.0 TB/s HBM3e, 1125/2250/4500 dense TFLOPS)."
            ),
        },
        {
            "id": "nvidia-b200-2die",
            "display_name": "NVIDIA B200 2-Die SXM (Published Ref)",
            "vendor": "NVIDIA",
            "architecture": "Blackwell GB100 dual-die CoWoS-L (TSMC 4NP)",
            "die_count": 2,
            "silicon_area_mm2": 1600.0,
            "tdp_w": 1000.0,
            "bandwidth_tbps": 8.00,
            "memory_spec": "HBM3e (8 stacks, 192 GB)",
            "est_module_price_usd": 35000.0,
            "peaks": {
                "fp16_bf16": (2250.0, 4500.0),
                "fp8": (4500.0, 9000.0),
                "nvfp4": (9000.0, 18000.0),
            },
            "source_citation": (
                "Published Vendor Reference Spec ONLY: NVIDIA B200 SXM datasheet "
                "(2x ~800 mm^2 dies = ~1600 mm^2 silicon, 1000 W TDP, 8.0 TB/s HBM3e, "
                "2250 FP16 / 4500 FP8 / 9000 FP4 dense TFLOPS)."
            ),
        },
        {
            "id": "nvidia-h200-sxm",
            "display_name": "NVIDIA H200 SXM (Published Ref)",
            "vendor": "NVIDIA",
            "architecture": "Hopper GH100 + HBM3e (TSMC 4N)",
            "die_count": 1,
            "silicon_area_mm2": 814.0,
            "tdp_w": 700.0,
            "bandwidth_tbps": 4.80,
            "memory_spec": "HBM3e (6 stacks, 141 GB)",
            "est_module_price_usd": 32000.0,
            "peaks": {
                "fp16_bf16": (989.5, 1979.0),
                "fp8": (1979.0, 3958.0),
                "nvfp4": (None, None),
            },
            "source_citation": (
                "Published Vendor Reference Spec ONLY: NVIDIA H200 SXM datasheet "
                "(814 mm^2 GH100 die, 700 W TDP, 4.8 TB/s HBM3e, 989.5 FP16 / 1979 FP8 dense)."
            ),
        },
        {
            "id": "nvidia-h100-sxm5",
            "display_name": "NVIDIA H100 SXM5 (Published Ref)",
            "vendor": "NVIDIA",
            "architecture": "Hopper GH100 (TSMC 4N)",
            "die_count": 1,
            "silicon_area_mm2": 814.0,
            "tdp_w": 700.0,
            "bandwidth_tbps": 3.35,
            "memory_spec": "HBM3 (5 stacks, 80 GB)",
            "est_module_price_usd": 28000.0,
            "peaks": {
                "fp16_bf16": (989.5, 1979.0),
                "fp8": (1979.0, 3958.0),
                "nvfp4": (None, None),
            },
            "source_citation": (
                "Published Vendor Reference Spec ONLY: NVIDIA H100 SXM5 datasheet "
                "(814 mm^2 die, 700 W TDP, 3.35 TB/s HBM3, 989.5 FP16 / 1979 FP8 dense)."
            ),
        },
        {
            "id": "amd-mi300x",
            "display_name": "AMD Instinct MI300X (Published Ref)",
            "vendor": "AMD",
            "architecture": "CDNA 3 Multi-Chiplet (8x XCD 5nm + 4x IOD 6nm)",
            "die_count": 12,
            "silicon_area_mm2": 1017.0,
            "tdp_w": 750.0,
            "bandwidth_tbps": 5.30,
            "memory_spec": "HBM3 (8 stacks, 192 GB)",
            "est_module_price_usd": 20000.0,
            "peaks": {
                "fp16_bf16": (1307.0, 2614.0),
                "fp8": (2614.0, 5228.0),
                "nvfp4": (None, None),
            },
            "source_citation": (
                "Published Vendor Reference Spec ONLY: AMD Instinct MI300X datasheet "
                "(~1,017 mm^2 active XCD+IOD silicon, 750 W TDP, 5.3 TB/s HBM3, "
                "1307 FP16 / 2614 FP8 dense TFLOPS)."
            ),
        },
    ]

    out: dict[str, dict[str, Any]] = {}
    for spec in specs:
        area = float(spec["silicon_area_mm2"])
        tdp = float(spec["tdp_w"])
        bw = float(spec["bandwidth_tbps"])
        formats: dict[str, Any] = {}
        for fmt_key, (dense_v, sparse_v) in spec["peaks"].items():
            supported = dense_v is not None
            formats[fmt_key] = {
                "supported": supported,
                "sparse_2_4_supported": sparse_v is not None,
                "dense_peak": dense_v,
                "sparse_2_4_peak": sparse_v,
                "dense_ridge_ops_per_byte": (dense_v / bw) if dense_v is not None else None,
                "sparse_2_4_ridge_ops_per_byte": (sparse_v / bw) if sparse_v is not None else None,
                "dense_per_mm2": (dense_v / area) if dense_v is not None else None,
                "dense_per_watt": (dense_v / tdp) if dense_v is not None else None,
                "sparse_2_4_per_watt": (sparse_v / tdp) if sparse_v is not None else None,
            }

        entry: dict[str, Any] = {
            "id": spec["id"],
            "category": "published_vendor_reference_baseline",
            "display_name": spec["display_name"],
            "vendor": spec["vendor"],
            "architecture": spec["architecture"],
            "die_count": spec["die_count"],
            "total_silicon_area_mm2": area,
            "per_die_area_mm2": area / float(spec["die_count"]),
            "tdp_w": tdp,
            "power_density_w_per_mm2": tdp / area,
            "bandwidth_tbps": bw,
            "memory_spec": spec["memory_spec"],
            "est_module_price_usd": spec["est_module_price_usd"],
            "tensor_compute": formats,
            "source_citation": spec["source_citation"],
        }
        _stamp_honesty(entry, is_published_ref=True)
        validate_b2_honesty_record(entry)
        out[spec["id"]] = entry
    return out


def compute_datacenter_tco_metrics(
    *,
    fp16_dense_tflops: float,
    fp8_dense_tflops: float,
    fp4_dense_tops: float | None,
    tdp_w: float,
    est_module_price_usd: float,
    uses_liquid_cooling: bool,
) -> dict[str, Any]:
    """Compute 3-year per-GPU datacenter TCO and cost per PFLOPS-hr."""
    tco_cfg = B2_PARAMETRIC_CONSTANTS["tco_assumptions"]
    years = tco_cfg["amortization_years"]
    hours = years * tco_cfg["hours_per_year"]
    pue = tco_cfg["pue_dlc"] if uses_liquid_cooling else tco_cfg["pue_air"]
    util = tco_cfg["fleet_utilization"]

    capex_usd = est_module_price_usd + tco_cfg["server_host_capex_share_per_gpu_usd"]
    avg_power_kw = (tdp_w * 0.72 * pue) / 1000.0
    opex_power_usd = avg_power_kw * hours * util * tco_cfg["electricity_usd_per_kwh"]
    total_3yr_tco_usd = capex_usd + opex_power_usd

    active_hours = hours * util
    tco_per_fp16_pflops_hr = total_3yr_tco_usd / ((fp16_dense_tflops / 1000.0) * active_hours)
    tco_per_fp8_pflops_hr = total_3yr_tco_usd / ((fp8_dense_tflops / 1000.0) * active_hours)
    tco_per_fp4_pflops_hr = (
        total_3yr_tco_usd / ((fp4_dense_tops / 1000.0) * active_hours)
        if fp4_dense_tops is not None
        else None
    )
    return {
        "amortization_years": years,
        "pue_assumed": pue,
        "capex_usd_est": capex_usd,
        "opex_power_3yr_usd_est": opex_power_usd,
        "total_3yr_tco_usd_est": total_3yr_tco_usd,
        "usd_per_fp16_pflops_hr": tco_per_fp16_pflops_hr,
        "usd_per_fp8_pflops_hr": tco_per_fp8_pflops_hr,
        "usd_per_fp4_pflops_hr": tco_per_fp4_pflops_hr,
    }


def compute_b1_to_b2_generational_delta(
    b2_single_model: dict[str, Any],
    *,
    node_id: str,
    measured: dict[str, Any],
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Compare single-die aigpu-b2 directly against legacy aigpu-b1 via read-only aigpu_ppa_model."""
    b1_model = base_ppa.model_aigpu_target(
        "aigpu-b1",
        node_id=node_id,
        measured=measured,
        config_path=config_path,
        profiles_dir=profiles_dir,
    )
    b1_area = b1_model["area_breakdown"]["total_die_area_mm2"]
    b1_tdp = b1_model["power_breakdown"]["total_tdp_w"]
    b1_fp16 = b1_model["tensor_compute"]["fp16_bf16"]["dense_peak"]
    b1_fp8 = b1_model["tensor_compute"]["fp8"]["dense_peak"]
    b1_fp4 = b1_model["tensor_compute"]["nvfp4"]["dense_peak"]
    b1_fp16_per_mm2 = b1_model["tensor_compute"]["fp16_bf16"]["dense_per_mm2"]
    b1_fp16_per_w = b1_model["tensor_compute"]["fp16_bf16"]["dense_per_watt"]

    b2_area = b2_single_model["area_and_shoreline"]["per_die_area_breakdown_mm2"]["total_die_area_mm2"]
    b2_tdp = b2_single_model["power_and_thermal"]["peak_tdp_w"]
    b2_tc = b2_single_model["compute_and_formats"]["tensor_compute"]
    b2_fp16 = b2_tc["fp16_bf16"]["tfr_v2_architectural_dense"]
    b2_fp8 = b2_tc["fp8"]["tfr_v2_architectural_dense"]
    b2_fp4 = b2_tc["nvfp4"]["tfr_v2_architectural_dense"]
    b2_fp16_per_mm2 = b2_tc["fp16_bf16"]["dense_per_mm2"]
    b2_fp16_per_w = b2_tc["fp16_bf16"]["dense_per_watt"]

    return {
        "node_id": node_id,
        "b1_baseline": {
            "total_cores": b1_model["topology"]["total_cores"],
            "die_area_mm2": b1_area,
            "tdp_w": b1_tdp,
            "fp16_dense_tflops": b1_fp16,
            "fp8_dense_tflops": b1_fp8,
            "fp4_dense_tops": b1_fp4,
            "fp16_per_mm2": b1_fp16_per_mm2,
            "fp16_per_watt": b1_fp16_per_w,
            "sram_total_mib": b1_model["memory_subsystem"]["sram_total_mib"],
        },
        "b2_single_die": {
            "total_cores": b2_single_model["topology"]["total_cores"],
            "die_area_mm2": b2_area,
            "tdp_w": b2_tdp,
            "fp16_dense_tflops": b2_fp16,
            "fp8_dense_tflops": b2_fp8,
            "fp4_dense_tops": b2_fp4,
            "fp16_per_mm2": b2_fp16_per_mm2,
            "fp16_per_watt": b2_fp16_per_w,
            "sram_plus_tmem_mib": b2_single_model["area_and_shoreline"]["sram_budget"]["totals_per_die"]["logical_mib"],
        },
        "ratios_b2_over_b1": {
            "cores_ratio": b2_single_model["topology"]["total_cores"] / float(b1_model["topology"]["total_cores"]),
            "die_area_ratio": b2_area / b1_area,
            "tdp_ratio": b2_tdp / b1_tdp,
            "fp16_tflops_ratio": b2_fp16 / b1_fp16,
            "fp8_tflops_ratio": b2_fp8 / b1_fp8,
            "fp4_tops_ratio": b2_fp4 / b1_fp4,
            "compute_density_fp16_per_mm2_ratio": b2_fp16_per_mm2 / b1_fp16_per_mm2,
            "energy_efficiency_fp16_per_watt_ratio": b2_fp16_per_w / b1_fp16_per_w,
        },
    }


def model_b2_sku(
    sku_id: str,
    *,
    node_id: str = "n4p_est",
    workload_id: str = "peak_tdp_stress",
    tmem_port_mode: str = "dual_banked_1rw",
    dvfs_bin: str = "nominal",
    d0_sweep: tuple[float, ...] = DEFAULT_D0_SWEEP,
    measured: dict[str, Any] | None = None,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Model full B2 PPA, SRAM cuts, shoreline, power/thermal, CoWoS-L, yield, and TCO for one SKU."""
    if sku_id not in B2_SKU_SPECS:
        raise ValueError(f"Unsupported B2 SKU {sku_id!r}; expected one of {VALID_SKUS}")
    if node_id not in NODE_SPECS:
        raise ValueError(f"Unknown node {node_id!r}; expected one of {VALID_NODES}")
    if workload_id not in WORKLOAD_PROFILES:
        raise ValueError(f"Unknown workload {workload_id!r}; expected one of {VALID_WORKLOADS}")
    if dvfs_bin not in DVFS_BINS:
        raise ValueError(f"Unknown dvfs_bin {dvfs_bin!r}; expected one of {VALID_DVFS_BINS}")

    if measured is None:
        measured = base_ppa.load_measured_presilicon_inputs()

    sku = B2_SKU_SPECS[sku_id]
    node = NODE_SPECS[node_id]
    dvfs = DVFS_BINS[dvfs_bin]

    profile_json = _maybe_read_profile_json(sku, profiles_dir)
    target_clock = sku.clock_mhz_target * dvfs.clock_scale

    compute_cap = compute_b2_compute_capability(sku, clock_mhz=target_clock)
    area_info = compute_b2_area_and_shoreline(
        sku, node, measured, tmem_port_mode=tmem_port_mode
    )
    power_thermal = compute_b2_power_thermal_packaging(
        sku,
        node,
        measured,
        area_info,
        workload_id=workload_id,
        clock_mhz=sku.clock_mhz_target,
        dvfs_bin=dvfs_bin,
    )
    yield_cost = compute_b2_yield_and_cost(
        sku,
        node,
        area_info,
        d0_sweep=d0_sweep,
    )

    pkg_area_mm2 = area_info["package_silicon_area_mm2"]
    peak_tdp_w = power_thermal["peak_tdp_w"]
    by_prec = power_thermal["peak_tdp_by_precision"]

    tensor_metrics: dict[str, Any] = {}
    for fmt_key, fentry in compute_cap["formats"].items():
        pwr_key = fmt_key if fmt_key in by_prec else "fp16_bf16"
        fmt_tdp_w = by_prec[pwr_key]["total_power_w"]
        dense_v = fentry["tfr_v2_architectural_dense"]
        sparse_v = fentry["tfr_v2_architectural_sparse_2_4"]
        tensor_metrics[fmt_key] = {
            **fentry,
            "modeled_tdp_w_at_format": fmt_tdp_w,
            "dense_per_mm2": dense_v / pkg_area_mm2,
            "sparse_2_4_per_mm2": sparse_v / pkg_area_mm2,
            "dense_per_watt": dense_v / fmt_tdp_w,
            "sparse_2_4_per_watt": sparse_v / fmt_tdp_w,
        }

    # Evaluate DVFS operating bins cleanly for trade-off visibility
    dvfs_sweep: dict[str, dict[str, Any]] = {}
    for bid, bspec in DVFS_BINS.items():
        if bid == dvfs_bin:
            b_pt = power_thermal
            b_cap = compute_cap
        else:
            b_cap = compute_b2_compute_capability(sku, clock_mhz=sku.clock_mhz_target * bspec.clock_scale)
            b_pt = compute_b2_power_thermal_packaging(
                sku,
                node,
                measured,
                area_info,
                workload_id=workload_id,
                clock_mhz=sku.clock_mhz_target,
                dvfs_bin=bid,
            )
        b_fp16 = b_cap["formats"]["fp16_bf16"]["tfr_v2_architectural_dense"]
        b_tdp = b_pt["peak_tdp_w"]
        dvfs_sweep[bid] = {
            "clock_mhz": b_cap["clock_mhz"],
            "vdd_v": b_pt["packaging_and_pdn"]["nominal_vdd_v"],
            "peak_tdp_w": b_tdp,
            "fp16_dense_tflops": b_fp16,
            "fp16_dense_per_watt": b_fp16 / b_tdp,
            "meets_node_fmax_ceiling": b_pt["clock_and_frequency"]["meets_target_clock_at_projected_node"],
        }

    bom_usd = yield_cost["nominal_point"]["package_silicon_bom_usd_est"]
    est_module_price_usd = (
        bom_usd * B2_PARAMETRIC_CONSTANTS["tco_assumptions"]["estimated_system_price_mult_over_silicon_bom"]
        if math.isfinite(bom_usd)
        else float("inf")
    )
    tco_metrics = compute_datacenter_tco_metrics(
        fp16_dense_tflops=tensor_metrics["fp16_bf16"]["tfr_v2_architectural_dense"],
        fp8_dense_tflops=tensor_metrics["fp8"]["tfr_v2_architectural_dense"],
        fp4_dense_tops=tensor_metrics["nvfp4"]["tfr_v2_architectural_dense"],
        tdp_w=peak_tdp_w,
        est_module_price_usd=est_module_price_usd,
        uses_liquid_cooling=(sku.die_count == 2 or peak_tdp_w > 650.0),
    )

    result: dict[str, Any] = {
        "id": sku.sku_id,
        "category": "aigpu_b2_presilicon_model",
        "display_name": sku.display_name,
        "role": sku.role,
        "node_id": node.node_id,
        "node_display_name": node.display_name,
        "profile_json_present": profile_json is not None,
        "topology": {
            "die_count": sku.die_count,
            "clusters_per_die": sku.clusters_per_die,
            "cores_per_cluster": sku.cores_per_cluster,
            "cores_per_die": sku.clusters_per_die * sku.cores_per_cluster,
            "total_cores": compute_cap["total_cores"],
            "warps_per_core": sku.warps_per_core,
            "threads_per_warp": sku.threads_per_warp,
            "issue_width": sku.issue_width,
            "tcu_pipes_per_core": sku.tcu_pipes_per_core,
            "total_tcu_pipes": compute_cap["total_tcu_pipes"],
            "hbm3e_stacks_total": sku.die_count * sku.hbm3e_stacks_per_die,
            "bandwidth_tbps_total": compute_cap["bandwidth_tbps"],
            "ucie_2_0_d2d_tbps": sku.ucie_bw_tbps_per_die,
            "pcie_gen6_lanes_per_die": sku.pcie_gen6_lanes_per_die,
        },
        "compute_and_formats": {
            "clock_mhz": compute_cap["clock_mhz"],
            "scalar_fp32_tflops": compute_cap["scalar_fp32_tflops"],
            "vortex_tcu_shape": compute_cap["vortex_tcu_shape"],
            "tfr_v2_systolic_shape": compute_cap["tfr_v2_systolic_shape"],
            "rtl_ref_peaks": compute_cap["rtl_ref_peaks"],
            "tensor_compute": tensor_metrics,
        },
        "area_and_shoreline": area_info,
        "power_and_thermal": power_thermal,
        "dvfs_operating_sweep": dvfs_sweep,
        "yield_and_cost": yield_cost,
        "datacenter_tco_estimate": tco_metrics,
    }
    _stamp_honesty(result, is_published_ref=False)
    validate_b2_honesty_record(result)
    return result


def build_b2_ppa_report(
    *,
    node_id: str = "n4p_est",
    sku_filter: str = "all",
    workload_id: str = "peak_tdp_stress",
    tmem_port_mode: str = "dual_banked_1rw",
    dvfs_bin: str = "nominal",
    d0_sweep: tuple[float, ...] = DEFAULT_D0_SWEEP,
    phys_results_path: Path = DEFAULT_PHYS_RESULTS_PATH,
    sram_manifest_path: Path = DEFAULT_SRAM_MANIFEST_PATH,
    yosys_dir: Path = DEFAULT_YOSYS_DIR,
    beacon_dir: Path = DEFAULT_BEACON_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Build full B2 pre-silicon PPA, thermal, packaging, yield, generational delta, and TCO report."""
    if node_id not in NODE_SPECS:
        raise ValueError(f"Unknown node {node_id!r}; expected one of {VALID_NODES}")
    if sku_filter != "all" and sku_filter not in B2_SKU_SPECS:
        raise ValueError(f"Unknown SKU {sku_filter!r}; expected 'all' or {VALID_SKUS}")

    measured = base_ppa.load_measured_presilicon_inputs(
        phys_results_path=phys_results_path,
        sram_manifest_path=sram_manifest_path,
        yosys_dir=yosys_dir,
        beacon_dir=beacon_dir,
    )

    selected_skus = VALID_SKUS if sku_filter == "all" else (sku_filter,)
    sku_models = {
        sid: model_b2_sku(
            sid,
            node_id=node_id,
            workload_id=workload_id,
            tmem_port_mode=tmem_port_mode,
            dvfs_bin=dvfs_bin,
            d0_sweep=d0_sweep,
            measured=measured,
            profiles_dir=profiles_dir,
        )
        for sid in selected_skus
    }

    b2_single_ref = sku_models.get("aigpu-b2") or model_b2_sku(
        "aigpu-b2",
        node_id=node_id,
        workload_id=workload_id,
        tmem_port_mode=tmem_port_mode,
        dvfs_bin=dvfs_bin,
        d0_sweep=d0_sweep,
        measured=measured,
        profiles_dir=profiles_dir,
    )
    generational_delta = compute_b1_to_b2_generational_delta(
        b2_single_ref,
        node_id=node_id,
        measured=measured,
        config_path=config_path,
        profiles_dir=profiles_dir,
    )

    node_sweep = {
        nid: {
            sid: model_b2_sku(
                sid,
                node_id=nid,
                workload_id=workload_id,
                tmem_port_mode=tmem_port_mode,
                dvfs_bin=dvfs_bin,
                d0_sweep=d0_sweep,
                measured=measured,
                profiles_dir=profiles_dir,
            )
            for sid in ("aigpu-b2-tile", "aigpu-b2")
        }
        for nid in VALID_NODES
    }

    published_refs = build_b2_published_vendor_baselines()
    h100_ref = published_refs["nvidia-h100-sxm5"]
    h100_tco = compute_datacenter_tco_metrics(
        fp16_dense_tflops=h100_ref["tensor_compute"]["fp16_bf16"]["dense_peak"],
        fp8_dense_tflops=h100_ref["tensor_compute"]["fp8"]["dense_peak"],
        fp4_dense_tops=None,
        tdp_w=h100_ref["tdp_w"],
        est_module_price_usd=h100_ref["est_module_price_usd"],
        uses_liquid_cooling=False,
    )
    b200_2d_ref = published_refs["nvidia-b200-2die"]
    b200_2d_tco = compute_datacenter_tco_metrics(
        fp16_dense_tflops=b200_2d_ref["tensor_compute"]["fp16_bf16"]["dense_peak"],
        fp8_dense_tflops=b200_2d_ref["tensor_compute"]["fp8"]["dense_peak"],
        fp4_dense_tops=b200_2d_ref["tensor_compute"]["nvfp4"]["dense_peak"],
        tdp_w=b200_2d_ref["tdp_w"],
        est_module_price_usd=b200_2d_ref["est_module_price_usd"],
        uses_liquid_cooling=True,
    )

    tco_comparison: dict[str, Any] = {
        "baseline_h100_sxm5": h100_tco,
        "baseline_b200_2die": b200_2d_tco,
        "skus": {},
    }
    for sid, smodel in sku_models.items():
        stco = smodel["datacenter_tco_estimate"]
        fp8_perf_per_w = smodel["compute_and_formats"]["tensor_compute"]["fp8"]["dense_per_watt"]
        h100_fp8_perf_per_w = h100_ref["tensor_compute"]["fp8"]["dense_per_watt"]
        b200_fp8_perf_per_w = b200_2d_ref["tensor_compute"]["fp8"]["dense_per_watt"]
        tco_comparison["skus"][sid] = {
            **stco,
            "fp8_perf_per_watt_vs_h100": fp8_perf_per_w / h100_fp8_perf_per_w,
            "fp8_perf_per_watt_vs_b200_2die": fp8_perf_per_w / b200_fp8_perf_per_w,
            "tco_per_fp8_pflops_hr_vs_h100": stco["usd_per_fp8_pflops_hr"] / h100_tco["usd_per_fp8_pflops_hr"],
            "tco_per_fp8_pflops_hr_vs_b200_2die": stco["usd_per_fp8_pflops_hr"] / b200_2d_tco["usd_per_fp8_pflops_hr"],
        }

    node = NODE_SPECS[node_id]
    report: dict[str, Any] = {
        "selected_node": node_id,
        "selected_sku_filter": sku_filter,
        "selected_workload": workload_id,
        "tmem_port_mode": tmem_port_mode,
        "dvfs_bin": dvfs_bin,
        "disclaimer": (
            "PARAMETRIC PRE-SILICON B2 PPA ESTIMATE ONLY: anchored to open-source "
            "Yosys/OpenSTA/OpenROAD ASAP7 measurements and SRAM macro baselines, "
            "extrapolated via explicit commercial node scaling assumptions. "
            "NOT manufactured silicon (silicon_measured=false), NOT physical FPGA "
            "(fpga_measured=false), and NOT foundry sign-off (foundry_signoff=false)."
        ),
        "measured_presilicon_inputs": measured,
        "node_scaling_spec": {
            "node_id": node.node_id,
            "display_name": node.display_name,
            "process_class": node.process_class,
            "logic_area_scale_vs_asap7": node.logic_area_scale_vs_asap7,
            "sram_1rw_bitcell_um2": node.sram_1rw_bitcell_um2,
            "sram_array_efficiency": node.sram_array_efficiency,
            "phy_area_scale_vs_n4p": node.phy_area_scale_vs_n4p,
            "fmax_scale_vs_asap7_rvt": node.fmax_scale_vs_asap7_rvt,
        },
        "parametric_constants": B2_PARAMETRIC_CONSTANTS,
        "b2_skus": sku_models,
        "b1_to_b2_generational_delta": generational_delta,
        "node_sensitivity_sweep": node_sweep,
        "published_vendor_baselines": published_refs,
        "tco_and_efficiency_comparison": tco_comparison,
    }
    _stamp_honesty(report, is_published_ref=False)
    validate_b2_honesty_record(report)
    return report


def _fmt_opt(val: float | None, precision: int = 2) -> str:
    if val is None or not math.isfinite(float(val)):
        return "N/A"
    return f"{val:.{precision}f}"


def format_b2_markdown(report: dict[str, Any], *, include_yield_sweep: bool = False) -> str:
    """Render deterministic Markdown report covering area, SRAM, shoreline, thermal, yield, and TCO."""
    validate_b2_honesty_record(report)
    node_id = report["selected_node"]
    wl_id = report["selected_workload"]
    skus = report["b2_skus"]

    lines: list[str] = [
        f"# AI-GPU B2 Parametric Pre-Silicon PPA Report (`node={node_id}`, `workload={wl_id}`)",
        "",
        f"- **Schema Version**: `{report['schema_version']}` | **Evidence Level**: `{report['evidence_level']}` | "
        f"**Model Type**: `{report['model_type']}`",
        f"- **`silicon_measured`**: `{str(report['silicon_measured']).lower()}` | "
        f"**`fpga_measured`**: `{str(report['fpga_measured']).lower()}` | "
        f"**`foundry_signoff`**: `{str(report['foundry_signoff']).lower()}`",
        f"- **Boundary**: {report['disclaimer']}",
        "",
        "## 1. B2 SKU Die Area, Reticle & Shoreline Summary",
        "",
        "| SKU | Cores / Pipes | Logic Routed (mm^2) | TMEM (mm^2) | L2/SLC/Dir (mm^2) | LMEM/L1/RF (mm^2) | Hard IP (mm^2) | Per-Die Area (mm^2) | Pkg Silicon (mm^2) | Reticle <=858 | Shoreline |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for sid, sm in skus.items():
        ab = sm["area_and_shoreline"]["per_die_area_breakdown_mm2"]
        rc = sm["area_and_shoreline"]["reticle_and_field_check"]
        sb = sm["area_and_shoreline"]["shoreline_budget"]
        topo = sm["topology"]
        lines.append(
            f"| `{sid}` | {topo['total_cores']} / {topo['total_tcu_pipes']} | "
            f"{ab['logic_routed_mm2']:.2f} | {ab['sram_tmem_mm2']:.2f} | "
            f"{ab['sram_l2_slc_dir_mm2']:.2f} | {ab['sram_lmem_l1_rf_mm2']:.2f} | "
            f"{ab['hard_ip_total_mm2']:.2f} | **{ab['total_die_area_mm2']:.2f}** | "
            f"{sm['area_and_shoreline']['package_silicon_area_mm2']:.2f} | "
            f"{'PASS' if rc['within_reticle_limit'] else 'FAIL'} ({rc['reticle_utilization_pct']:.1f}%) | "
            f"{'PASS' if sb['shoreline_feasible'] else 'FAIL'} ({sb['shoreline_utilization_pct']:.1f}%) |"
        )

    lines.extend([
        "",
        "## 2. Power, Thermal & CoWoS-L Packaging Envelope",
        "",
        "| SKU | Workload Power (W) | Peak TDP (W) | W/mm^2 (Peak) | Air T_j (C) | DLC T_j (C) | Pkg Tech | Warpage (um) | Peak Current (A) |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ])
    for sid, sm in skus.items():
        pt = sm["power_and_thermal"]
        pkg = pt["packaging_and_pdn"]
        air = pt["thermal_envelopes"]["air_cooled"]
        dlc = pt["thermal_envelopes"]["liquid_cooled"]
        lines.append(
            f"| `{sid}` | {pt['selected_workload_power']['total_power_w']:.1f} | "
            f"**{pt['peak_tdp_w']:.1f}** | {pt['thermal_density_w_per_mm2_at_peak_tdp']:.3f} | "
            f"{air['tj_at_peak_tdp_c']:.1f} ({'OK' if air['meets_thermal_ceiling_at_peak_tdp'] else 'EXCEEDS'}) | "
            f"{dlc['tj_at_peak_tdp_c']:.1f} ({'OK' if dlc['meets_thermal_ceiling_at_peak_tdp'] else 'EXCEEDS'}) | "
            f"{pkg['packaging_technology']} | {pkg['estimated_warpage_um']:.1f}/{pkg['warpage_limit_um']:.0f} | "
            f"{pkg['peak_package_current_a']:.0f} |"
        )

    lines.extend([
        "",
        "## 3. Compute Density, Efficiency & Published Vendor Comparison",
        "",
        "| Device (Tag) | Silicon (mm^2) | TDP (W) | BW (TB/s) | FP16 Dense / Sparse | FP8 Dense / Sparse | FP4 Dense / Sparse | FP16/mm^2 | FP8/W | FP4/W |",
        "|---|---:|---:|---:|---|---|---|---:|---:|---:|",
    ])
    for sid, sm in skus.items():
        tc = sm["compute_and_formats"]["tensor_compute"]
        area = sm["area_and_shoreline"]["package_silicon_area_mm2"]
        tdp = sm["power_and_thermal"]["peak_tdp_w"]
        bw = sm["topology"]["bandwidth_tbps_total"]
        lines.append(
            f"| `{sid}` ({node_id} est) | {area:.1f} | {tdp:.1f} | {bw:.2f} | "
            f"{tc['fp16_bf16']['tfr_v2_architectural_dense']:.1f} / {tc['fp16_bf16']['tfr_v2_architectural_sparse_2_4']:.1f} | "
            f"{tc['fp8']['tfr_v2_architectural_dense']:.1f} / {tc['fp8']['tfr_v2_architectural_sparse_2_4']:.1f} | "
            f"{tc['nvfp4']['tfr_v2_architectural_dense']:.1f} / {tc['nvfp4']['tfr_v2_architectural_sparse_2_4']:.1f} | "
            f"{tc['fp16_bf16']['dense_per_mm2']:.3f} | {tc['fp8']['dense_per_watt']:.3f} | {tc['nvfp4']['dense_per_watt']:.3f} |"
        )

    for _, ref in report["published_vendor_baselines"].items():
        tc = ref["tensor_compute"]
        fp4 = tc["nvfp4"]
        fp4_str = (
            f"{_fmt_opt(fp4['dense_peak'], 1)} / {_fmt_opt(fp4['sparse_2_4_peak'], 1)}"
            if fp4["supported"]
            else "N/A"
        )
        lines.append(
            f"| {ref['display_name']} | {ref['total_silicon_area_mm2']:.1f} | {ref['tdp_w']:.1f} | "
            f"{ref['bandwidth_tbps']:.2f} | "
            f"{_fmt_opt(tc['fp16_bf16']['dense_peak'], 1)} / {_fmt_opt(tc['fp16_bf16']['sparse_2_4_peak'], 1)} | "
            f"{_fmt_opt(tc['fp8']['dense_peak'], 1)} / {_fmt_opt(tc['fp8']['sparse_2_4_peak'], 1)} | "
            f"{fp4_str} | {_fmt_opt(tc['fp16_bf16']['dense_per_mm2'], 3)} | "
            f"{_fmt_opt(tc['fp8']['dense_per_watt'], 3)} | {_fmt_opt(fp4['dense_per_watt'] if fp4['supported'] else None, 3)} |"
        )

    gen = report["b1_to_b2_generational_delta"]
    ratios = gen["ratios_b2_over_b1"]
    lines.extend([
        "",
        f"## 4. Generational Scaling (`aigpu-b1` -> `aigpu-b2` at `{node_id}`)",
        "",
        f"- **Cores**: `{gen['b1_baseline']['total_cores']}` -> `{gen['b2_single_die']['total_cores']}` (`{ratios['cores_ratio']:.2f}x`)",
        f"- **Die Area**: `{gen['b1_baseline']['die_area_mm2']:.2f} mm^2` -> `{gen['b2_single_die']['die_area_mm2']:.2f} mm^2` (`{ratios['die_area_ratio']:.2f}x`)",
        f"- **FP16 / FP8 / FP4 Dense**: `{ratios['fp16_tflops_ratio']:.2f}x` / `{ratios['fp8_tflops_ratio']:.2f}x` / `{ratios['fp4_tops_ratio']:.2f}x`",
        f"- **Compute Density (FP16/mm^2)** & **Energy Eff. (FP16/W)**: `{ratios['compute_density_fp16_per_mm2_ratio']:.2f}x` / `{ratios['energy_efficiency_fp16_per_watt_ratio']:.2f}x`",
    ])

    if include_yield_sweep:
        lines.extend([
            "",
            "## 5. 300mm Wafer Yield & KGD Cost Sweep",
            "",
            "| SKU | Gross DPW | D0 (def/cm^2) | Murphy Raw | NegBin Repaired | Uplift (pts) | Pkg Yield | KGD Est (USD) | Pkg BOM Est (USD) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for sid, sm in skus.items():
            yc = sm["yield_and_cost"]
            for pt in yc["d0_sweep"]:
                lines.append(
                    f"| `{sid}` | {yc['gross_dies_per_wafer']} | {pt['d0_defects_per_cm2']:.2f} | "
                    f"{pt['murphy_yield_unrepaired'] * 100.0:.2f}% | {pt['negbin_yield_sram_repaired'] * 100.0:.2f}% | "
                    f"+{pt['sram_repair_uplift_pct_pts']:.2f} | {pt['composite_module_yield'] * 100.0:.2f}% | "
                    f"${pt['kgd_die_cost_usd_est']:.0f} | ${pt['package_silicon_bom_usd_est']:.0f} |"
                )

    return "\n".join(lines) + "\n"


def _parse_d0_sweep(raw: str | None) -> tuple[float, ...]:
    if raw is None:
        return DEFAULT_D0_SWEEP
    vals = []
    for part in raw.split(","):
        s = part.strip()
        if not s:
            continue
        val = float(s)
        if not math.isfinite(val) or val < 0.0:
            raise ValueError(f"Invalid D0 value in sweep: {s!r}")
        vals.append(val)
    if not vals:
        raise ValueError("Empty D0 sweep")
    return tuple(vals)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for AI-GPU B2 parametric pre-silicon PPA modeling."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=VALID_NODES, default="n4p_est")
    parser.add_argument("--sku", choices=("all", *VALID_SKUS), default="all")
    parser.add_argument("--workload", choices=VALID_WORKLOADS, default="peak_tdp_stress")
    parser.add_argument("--tmem-port-mode", choices=VALID_TMEM_PORT_MODES, default="dual_banked_1rw")
    parser.add_argument("--dvfs-bin", choices=VALID_DVFS_BINS, default="nominal")
    parser.add_argument(
        "--yield-sweep",
        action="store_true",
        help="Include full 300mm wafer defect-density D0 yield sweep in Markdown output",
    )
    parser.add_argument(
        "--d0-values",
        type=str,
        default=None,
        help="Optional comma-separated D0 defect densities (defects/cm^2)",
    )
    out_group = parser.add_mutually_exclusive_group()
    out_group.add_argument("--json", action="store_true", help="Emit structured JSON report")
    out_group.add_argument("--markdown", action="store_true", help="Emit Markdown report")
    parser.add_argument("--output", type=Path, default=None, help="Optional output file path")
    args = parser.parse_args(argv)

    d0_sweep = _parse_d0_sweep(args.d0_values)
    report = build_b2_ppa_report(
        node_id=args.node,
        sku_filter=args.sku,
        workload_id=args.workload,
        tmem_port_mode=args.tmem_port_mode,
        dvfs_bin=args.dvfs_bin,
        d0_sweep=d0_sweep,
    )
    if args.json:
        text = json.dumps(report, indent=2) + "\n"
    else:
        text = format_b2_markdown(report, include_yield_sweep=bool(args.yield_sweep or args.d0_values))

    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
