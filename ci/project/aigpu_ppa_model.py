#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Parametric pre-silicon PPA, area, power, and compute-density model for AI-GPU.

Pure Python standard-library tool (CLI + importable API) that grounds pre-silicon
die-area, power, thermal-density, HBM3E/memory-bandwidth, and compute-density
(TFLOPS/mm^2, TFLOPS/W, ridge-point ops/byte) projections for:
  - `aigpu-b1-tile`: 4-core RTL-verifiable MPW compute tile (256 KiB L2)
  - `aigpu-b1`:      64-core datacenter AI-only SoC (4 clusters x 16 cores,
                     64 MiB L2, 4.0 TB/s HBM3E-class @ 2.0 GHz)

and compares them side-by-side against published reference baselines:
  - NVIDIA `H100` SXM5 (`profiles/h100.json` + NVIDIA GH100 published datasheet)
  - NVIDIA `RTX 5080` (`profiles/rtx5080.json` + NVIDIA GB203 published datasheet)
  - NVIDIA `B200` (single-die & dual-die Blackwell published datasheet specs;
    explicitly tagged as published reference specs, NOT locally measured)

Measured pre-silicon repository inputs read directly on disk:
  1. `profiles/aigpu-b1.json`, `profiles/aigpu-b1-tile.json`,
     `profiles/h100.json`, `profiles/rtx5080.json` (and resolved via
     `ci/project/b1_roofline_compare.py` so peak TFLOPS and ridge points match
     bit-for-bit with zero drift).
  2. `hw/asic/sram/sram_macro_manifest.json` for exact logical SRAM arrays and
     bit counts partitioned by port type (`1rw` vs `1r1w`).
  3. `hw/asic/phys/phys_results.json` for real Yosys 0.69 / OpenSTA 3.1.0 /
     OpenROAD ORFS ASAP7 measured areas, post-route Fmax (`1079.53 MHz` on
     `VX_tcu_tfr_mul_f16`), post-route cell/power inflation ratios, and shell
     metrics (`VX_asic_dft_top`, `VX_tcu_tfr_mul_f16`, `VX_tcu_fedp_tfr`,
     `VX_asic_soc_top`).
  4. `ci/baselines/synthesis/yosys/*.json` and `ci/baselines/synthesis/beacon/*.json`
     for real Yosys ASAP7 macro-unit standard-cell areas (`yosys/tensor.json`
     records `tcu` at `xlen=32` with `catalog.mk` `tcu_CFG` 16T/16W `configs=""`,
     and `tensor` at 8T/8W) and Beacon LUT/FF/DSP reference context.

Strict Honesty Contract (ADR-006):
  - Every output payload carries:
      `evidence_level = "simulated"`
      `silicon_measured = False`
      `foundry_signoff = False`
      `model_type = "parametric_presilicon_estimate"`
  - Measured pre-silicon inputs, parametric scaling assumptions, and published
    vendor reference baselines are strictly separated in both JSON and Markdown.
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

import b1_roofline_compare as roofline_cmp


SCHEMA_VERSION = 1
ALLOWED_EVIDENCE_LEVEL = "simulated"
ALLOWED_MODEL_TYPE = "parametric_presilicon_estimate"
RETICLE_LIMIT_MM2 = 858.0  # Standard EUV/DUV full-field lithography reticle ceiling (26 mm x 33 mm)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_DIR = ROOT / "profiles"
DEFAULT_CONFIG_PATH = ROOT / "VX_config.toml"
DEFAULT_SRAM_MANIFEST_PATH = ROOT / "hw/asic/sram/sram_macro_manifest.json"
DEFAULT_PHYS_RESULTS_PATH = ROOT / "hw/asic/phys/phys_results.json"
DEFAULT_YOSYS_DIR = ROOT / "ci/baselines/synthesis/yosys"
DEFAULT_BEACON_DIR = ROOT / "ci/baselines/synthesis/beacon"

VALID_NODES = ("asap7", "n4p_est", "n3e_est")


@dataclass(frozen=True)
class NodeScalingSpec:
    """Explicit technology-node scaling assumptions anchored to ASAP7 measurements."""

    node_id: str
    display_name: str
    process_class: str
    is_predictive_academic_pdk: bool
    logic_area_scale_vs_asap7: float
    sram_1rw_bitcell_um2: float
    sram_1r1w_area_multiplier: float
    sram_array_efficiency: float
    pnr_macro_utilization: float
    phy_area_scale_vs_n4p: float
    logic_dyn_energy_scale_vs_asap7: float
    sram_energy_pj_per_byte: float
    hbm_io_energy_pj_per_bit: float
    mpw_tile_io_power_w: float
    leakage_fraction_of_die_power: float
    fmax_scale_vs_asap7_rvt: float
    notes: str


NODE_SPECS: dict[str, NodeScalingSpec] = {
    "asap7": NodeScalingSpec(
        node_id="asap7",
        display_name="ASAP7 (Predictive 7nm RVT Academic PDK)",
        process_class="Predictive academic 7nm FinFET (7.5-track RVT, Vdd=0.70V tt)",
        is_predictive_academic_pdk=True,
        logic_area_scale_vs_asap7=1.00,
        sram_1rw_bitcell_um2=0.0320,
        sram_1r1w_area_multiplier=1.45,
        sram_array_efficiency=0.55,
        pnr_macro_utilization=0.62,
        phy_area_scale_vs_n4p=1.25,
        logic_dyn_energy_scale_vs_asap7=1.00,
        sram_energy_pj_per_byte=1.65,
        hbm_io_energy_pj_per_bit=2.80,
        mpw_tile_io_power_w=1.60,
        leakage_fraction_of_die_power=0.16,
        fmax_scale_vs_asap7_rvt=1.00,
        notes=(
            "Direct ASAP7 RVT baseline anchored to Yosys/OpenSTA/OpenROAD runs in "
            "hw/asic/phys/phys_results.json; SRAM macro density is an academic 7nm "
            "estimate (no real ASAP7 foundry SRAM compiler)."
        ),
    ),
    "n4p_est": NodeScalingSpec(
        node_id="n4p_est",
        display_name="N4P-class (Parametric Commercial 4nm Estimate)",
        process_class="Parametric 4nm-class HPC FinFET estimate (Vdd~0.75-0.80V)",
        is_predictive_academic_pdk=False,
        logic_area_scale_vs_asap7=0.56,
        sram_1rw_bitcell_um2=0.0210,
        sram_1r1w_area_multiplier=1.45,
        sram_array_efficiency=0.62,
        pnr_macro_utilization=0.62,
        phy_area_scale_vs_n4p=1.00,
        logic_dyn_energy_scale_vs_asap7=0.68,
        sram_energy_pj_per_byte=1.10,
        hbm_io_energy_pj_per_bit=2.50,
        mpw_tile_io_power_w=1.20,
        leakage_fraction_of_die_power=0.14,
        fmax_scale_vs_asap7_rvt=1.87,
        notes=(
            "Parametric commercial 4nm-class projection derived from ASAP7 measured "
            "logic cells (0.56x shrink, 0.0210 um^2 6T HD SRAM bitcell with 62% "
            "array efficiency, 0.68x dynamic switching energy vs ASAP7 RVT)."
        ),
    ),
    "n3e_est": NodeScalingSpec(
        node_id="n3e_est",
        display_name="N3E-class (Parametric Commercial 3nm Estimate)",
        process_class="Parametric 3nm-class FinFET estimate (Vdd~0.70-0.75V)",
        is_predictive_academic_pdk=False,
        logic_area_scale_vs_asap7=0.42,
        sram_1rw_bitcell_um2=0.0199,
        sram_1r1w_area_multiplier=1.45,
        sram_array_efficiency=0.63,
        pnr_macro_utilization=0.62,
        phy_area_scale_vs_n4p=0.90,
        logic_dyn_energy_scale_vs_asap7=0.52,
        sram_energy_pj_per_byte=0.90,
        hbm_io_energy_pj_per_bit=2.30,
        mpw_tile_io_power_w=1.00,
        leakage_fraction_of_die_power=0.12,
        fmax_scale_vs_asap7_rvt=2.10,
        notes=(
            "Parametric commercial 3nm-class projection derived from ASAP7 measured "
            "logic cells (0.42x shrink, 0.0199 um^2 6T HD SRAM bitcell per published "
            "3nm SRAM scaling limits, 0.52x dynamic energy vs ASAP7 RVT)."
        ),
    ),
}

# Parametric workload & hardware-scaling constants (kept explicit for ADR-006 transparency)
PARAMETRIC_MODEL_CONSTANTS: dict[str, Any] = {
    "reticle_limit_mm2": RETICLE_LIMIT_MM2,
    "gemm_tcu_effective_toggle_factor": 0.35,
    "opensta_default_input_activity": 0.10,
    "fedp_multiformat_area_overhead": 1.35,
    "fedp_multiformat_dynamic_power_overhead": 1.25,
    "non_fedp_logic_active_duty_factor": 0.45,
    "sram_internal_bandwidth_duty_factor": 0.45,
    "rv64_lane_width_area_scale_vs_rv32": 1.40,
    "rv64_ctrl_width_area_scale_vs_rv32": 1.30,
    "core_scalar_lane_area_fraction": 0.45,
    "core_scalar_ctrl_area_fraction": 0.55,
    "l2_bank_ctrl_asap7_um2_full": 180000.0,
    "l2_bank_ctrl_asap7_um2_tile": 45000.0,
    "noc_cp_fabric_asap7_um2_full": 6500000.0,
    "noc_cp_fabric_asap7_um2_tile": 25000.0,
    "vm_mmu_tlb_asap7_um2_per_core": 45000.0,
    "hard_ip_n4p_mm2_full": {
        "hbm3e_8stack_phys_and_ctrl": 44.0,
        "pcie_gen5_x16_ucie_serdes": 18.0,
        "plls_padring_power_bump_keepout": 10.0,
    },
    "hard_ip_n4p_mm2_tile": {
        "mpw_axi_serdes_and_debug_io": 0.55,
        "pll_reset_and_wirebond_padring": 0.85,
    },
    "hard_ip_base_power_asap7_w_full": 18.0,
    "hard_ip_base_power_asap7_w_tile": 0.80,
    "on_die_hbm_phy_leakage_share": 0.50,
    "precision_dynamic_power_multipliers": {
        "fp16_bf16": 1.00,
        "fp8": 0.96,
        "mxfp4": 0.94,
        "nvfp4": 0.94,
    },
}


def validate_honesty_record(record: dict[str, Any]) -> None:
    """Enforce ADR-006 pre-silicon honesty invariants on every PPA record."""
    if not isinstance(record, dict):
        raise ValueError("PPA record must be a JSON object")
    if record.get("evidence_level") != ALLOWED_EVIDENCE_LEVEL:
        raise ValueError(
            f"PPA model requires evidence_level={ALLOWED_EVIDENCE_LEVEL!r}, "
            f"got {record.get('evidence_level')!r}"
        )
    if record.get("silicon_measured") is not False:
        raise ValueError(
            "PPA model must enforce silicon_measured=False; no silicon exists"
        )
    if record.get("foundry_signoff") is not False:
        raise ValueError(
            "PPA model must enforce foundry_signoff=False; no foundry sign-off exists"
        )
    if record.get("model_type") != ALLOWED_MODEL_TYPE:
        raise ValueError(
            f"PPA model requires model_type={ALLOWED_MODEL_TYPE!r}, "
            f"got {record.get('model_type')!r}"
        )


def _assert_positive_finite(value: float, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{label} must be positive and finite, got {value!r}")
    return float(value)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required repo input file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def load_measured_presilicon_inputs(
    *,
    phys_results_path: Path = DEFAULT_PHYS_RESULTS_PATH,
    sram_manifest_path: Path = DEFAULT_SRAM_MANIFEST_PATH,
    yosys_dir: Path = DEFAULT_YOSYS_DIR,
    beacon_dir: Path = DEFAULT_BEACON_DIR,
) -> dict[str, Any]:
    """Load real OpenROAD/Yosys/OpenSTA/SRAM/Beacon measurements from the repo."""
    phys = _read_json(phys_results_path)
    sram_manifest = _read_json(sram_manifest_path)

    synth = phys["synthesis_and_sta"]
    pnr = phys["openroad_pnr_and_gds"]

    fedp_lat4 = synth["vx_tcu_fedp_tfr_asap7_lat4"]
    fedp_lat5 = synth["vx_tcu_fedp_tfr_asap7_lat5"]
    mul_f16_synth = synth["vx_tcu_tfr_mul_f16_asap7"]
    mul_f16_pnr = pnr["vx_tcu_tfr_mul_f16_asap7"]
    dft_synth = synth["vx_asic_dft_top_asap7"]
    dft_pnr = pnr["vx_asic_dft_top_asap7"]
    soc_fakeram7 = synth["vx_asic_soc_top_asap7_fakeram7"]

    y_core_json = _read_json(yosys_dir / "core.json")
    y_tensor_json = _read_json(yosys_dir / "tensor.json")
    y_dxa_json = _read_json(yosys_dir / "dxa.json")
    y_mufu_json = _read_json(yosys_dir / "mufu.json")

    b_core_json = _read_json(beacon_dir / "core.json")
    b_tensor_json = _read_json(beacon_dir / "tensor.json")

    # Verify SRAM manifest arithmetic consistency across every array and subsystem
    sram_profiles: dict[str, Any] = {}
    for pname in ("aigpu-b1-tile", "aigpu-b1"):
        p_entry = sram_manifest["profiles"][pname]
        arrays = p_entry["sram_arrays"]
        bits_sum = sum(int(a["total_bits"]) for a in arrays)
        declared_bits = int(p_entry["totals"]["total_bits"])
        if bits_sum != declared_bits:
            raise ValueError(
                f"SRAM manifest bit mismatch for {pname}: sum(arrays)={bits_sum} != {declared_bits}"
            )
        bits_1rw = sum(int(a["total_bits"]) for a in arrays if a["port_type"] == "1rw")
        bits_1r1w = sum(int(a["total_bits"]) for a in arrays if a["port_type"] == "1r1w")
        if bits_1rw + bits_1r1w != bits_sum:
            raise ValueError(f"Unsupported SRAM port types in {pname}")
        sram_profiles[pname] = {
            "total_logical_arrays": int(p_entry["totals"]["total_logical_arrays"]),
            "total_bits": bits_sum,
            "total_bytes": int(p_entry["totals"]["total_bytes"]),
            "total_kib": float(p_entry["totals"]["total_kib"]),
            "total_mib": float(p_entry["totals"]["total_mib"]),
            "bits_1rw": bits_1rw,
            "bits_1r1w": bits_1r1w,
            "subsystem_bits": {
                k: int(v["total_bits"]) for k, v in p_entry["subsystem_totals"].items()
            },
        }

    mul_synth_area = _assert_positive_finite(
        mul_f16_synth["yosys"]["standard_cell_area_um2"], "mul_f16_synth_area"
    )
    mul_pnr_design_area = _assert_positive_finite(
        mul_f16_pnr["design_area_um2"], "mul_f16_pnr_design_area"
    )
    mul_synth_dyn_mw = _assert_positive_finite(
        mul_f16_synth["opensta_post_synth"]["power_mw"]["internal"]
        + mul_f16_synth["opensta_post_synth"]["power_mw"]["switching"],
        "mul_f16_synth_dyn_mw",
    )
    mul_pnr_dyn_mw = _assert_positive_finite(
        mul_f16_pnr["power_mw"]["internal"] + mul_f16_pnr["power_mw"]["switching"],
        "mul_f16_pnr_dyn_mw",
    )
    fedp_lat4_area = _assert_positive_finite(
        fedp_lat4["yosys"]["standard_cell_area_um2"], "fedp_lat4_area"
    )
    fedp_lat4_dyn_mw = _assert_positive_finite(
        fedp_lat4["opensta_post_synth"]["power_mw"]["internal"]
        + fedp_lat4["opensta_post_synth"]["power_mw"]["switching"],
        "fedp_lat4_dyn_mw",
    )
    post_route_fmax_mhz = _assert_positive_finite(
        mul_f16_pnr["clocks_min_period"]["clk"]["fmax_mhz"],
        "mul_f16_post_route_fmax_mhz",
    )

    return {
        "phys_results_metadata": {
            "artifact_id": phys.get("artifact_id"),
            "evidence_level": phys.get("evidence_level"),
            "foundry_signoff": bool(phys.get("foundry_signoff", False)),
            "git_head": phys.get("tools", {}).get("git_head"),
        },
        "sram_manifest_metadata": {
            "manifest_id": sram_manifest.get("manifest_id"),
            "evidence_level": sram_manifest.get("evidence_level"),
        },
        "measured_asap7_macros": {
            "vx_asic_dft_top_asap7": {
                "synth_cell_count": int(dft_synth["yosys"]["cell_count"]),
                "synth_stdcell_area_um2": float(dft_synth["yosys"]["standard_cell_area_um2"]),
                "pnr_design_area_um2": float(dft_pnr["design_area_um2"]),
                "pnr_core_area_um2": float(dft_pnr["core_area_um2"]),
                "pnr_utilization_pct": float(dft_pnr["utilization_pct"]),
                "pnr_klayout_die_area_um2": float(dft_pnr["artifacts"]["klayout"]["die_area_um2"]),
                "pnr_tck_fmax_mhz": float(dft_pnr["clocks_min_period"]["tck"]["fmax_mhz"]),
            },
            "vx_tcu_tfr_mul_f16_asap7": {
                "synth_cell_count": int(mul_f16_synth["yosys"]["cell_count"]),
                "synth_stdcell_area_um2": mul_synth_area,
                "synth_fmax_mhz": float(mul_f16_synth["achieved_fmax_mhz"]),
                "synth_dyn_power_mw_at_1ghz_0p1_act": mul_synth_dyn_mw,
                "pnr_design_area_um2": mul_pnr_design_area,
                "pnr_core_area_um2": float(mul_f16_pnr["core_area_um2"]),
                "pnr_utilization_pct": float(mul_f16_pnr["utilization_pct"]),
                "pnr_klayout_die_area_um2": float(mul_f16_pnr["artifacts"]["klayout"]["die_area_um2"]),
                "pnr_fmax_mhz": post_route_fmax_mhz,
                "pnr_dyn_power_mw_at_1ghz_0p1_act": mul_pnr_dyn_mw,
                "pnr_to_synth_area_ratio": mul_pnr_design_area / mul_synth_area,
                "pnr_to_synth_dyn_power_ratio": mul_pnr_dyn_mw / mul_synth_dyn_mw,
                "pnr_dyn_power_density_w_per_mm2_at_1ghz_0p1_act": (
                    (mul_pnr_dyn_mw * 1000.0) / mul_pnr_design_area
                ),
            },
            "vx_tcu_fedp_tfr_asap7_lat4": {
                "synth_cell_count": int(fedp_lat4["yosys"]["cell_count"]),
                "synth_stdcell_area_um2": fedp_lat4_area,
                "synth_fmax_mhz": float(fedp_lat4["achieved_fmax_mhz"]),
                "synth_dyn_power_mw_at_1ghz_0p1_act": fedp_lat4_dyn_mw,
                "synth_leakage_power_mw": float(
                    fedp_lat4["opensta_post_synth"]["power_mw"]["leakage"]
                ),
            },
            "vx_tcu_fedp_tfr_asap7_lat5": {
                "synth_cell_count": int(fedp_lat5["yosys"]["cell_count"]),
                "synth_stdcell_area_um2": float(fedp_lat5["yosys"]["standard_cell_area_um2"]),
                "synth_fmax_mhz": float(fedp_lat5["achieved_fmax_mhz"]),
            },
            "vx_asic_soc_top_asap7_fakeram7": {
                "synth_cell_count": int(soc_fakeram7["yosys"]["cell_count"]),
                "synth_stdcell_area_um2": float(soc_fakeram7["yosys"]["standard_cell_area_um2"]),
                "synth_total_chip_area_um2": float(soc_fakeram7["yosys"]["total_chip_area_um2"]),
                "fakeram7_256x32_area_um2": float(
                    soc_fakeram7["yosys"]["total_chip_area_um2"]
                    - soc_fakeram7["yosys"]["standard_cell_area_um2"]
                ),
                "datapath_excl_reset_clk_core_fmax_mhz": float(
                    soc_fakeram7["opensta_post_synth_datapath_excl_async_reset_tree"][
                        "clocks_min_period"
                    ]["clk_core"]["fmax_mhz"]
                ),
            },
        },
        "yosys_asap7_unit_baselines": {
            "core_8t_8w_rv32_um2": float(y_core_json["core"]["result"]["cell_area_um2"]),
            "cache_ctrl_um2": float(y_core_json["cache"]["result"]["cell_area_um2"]),
            "lmem_ctrl_um2": float(y_core_json["lmem"]["result"]["cell_area_um2"]),
            "tcu_16t_16w_tfr_um2": float(y_tensor_json["tcu"]["result"]["cell_area_um2"]),
            "tensor_2core_um2": float(y_tensor_json["tensor"]["result"]["cell_area_um2"]),
            "dxa_16t_um2": float(y_dxa_json["dxa"]["result"]["cell_area_um2"]),
            "mufu_16t_um2": float(y_mufu_json["mufu"]["result"]["cell_area_um2"]),
        },
        "beacon_fpga_baselines": {
            "core_16t_16w": {
                "lut": int(b_core_json["core"]["result"]["lut"]),
                "ff": int(b_core_json["core"]["result"]["ff"]),
                "dsp": int(b_core_json["core"]["result"]["dsp"]),
                "bram": float(b_core_json["core"]["result"]["bram"]),
            },
            "tcu_16t_16w": {
                "lut": int(b_tensor_json["tcu"]["result"]["lut"]),
                "ff": int(b_tensor_json["tcu"]["result"]["ff"]),
                "dsp": int(b_tensor_json["tcu"]["result"]["dsp"]),
            },
        },
        "sram_manifest_profiles": sram_profiles,
    }


def _compute_sram_area_mm2(
    sram_info: dict[str, Any],
    node: NodeScalingSpec,
) -> dict[str, float]:
    """Convert exact SRAM manifest bit counts (1RW + 1R1W) into macro area (mm^2)."""
    bits_1rw = float(sram_info["bits_1rw"])
    bits_1r1w = float(sram_info["bits_1r1w"])
    area_1rw_mm2 = ((bits_1rw * node.sram_1rw_bitcell_um2) / node.sram_array_efficiency) / 1e6
    area_1r1w_mm2 = (
        (bits_1r1w * node.sram_1rw_bitcell_um2 * node.sram_1r1w_area_multiplier)
        / node.sram_array_efficiency
    ) / 1e6
    total_sram_mm2 = area_1rw_mm2 + area_1r1w_mm2
    return {
        "sram_1rw_mm2": area_1rw_mm2,
        "sram_1r1w_mm2": area_1r1w_mm2,
        "sram_total_mm2": total_sram_mm2,
        "effective_mbit_per_mm2": (float(sram_info["total_bits"]) / 1e6) / total_sram_mm2,
    }


def _compute_aigpu_format_metrics(
    roofline_entry: dict[str, Any],
    *,
    die_area_mm2: float,
    power_by_precision: dict[str, float],
) -> dict[str, Any]:
    """Compute dense & 2:4 sparse TFLOPS, ridge points, TFLOPS/mm^2, and TFLOPS/W."""
    bw_tbps = float(roofline_entry["memory"]["bandwidth_gbs"]) / 1000.0
    formats_out: dict[str, Any] = {}
    for fmt_key in ("fp16_bf16", "fp8", "mxfp4", "nvfp4"):
        rf_fmt = roofline_entry["tensor_formats"][fmt_key]
        supported = bool(rf_fmt["supported"])
        if not supported:
            formats_out[fmt_key] = {
                "label": rf_fmt["label"],
                "unit": rf_fmt["unit"],
                "supported": False,
                "sparse_2_4_supported": False,
                "dense_peak": None,
                "sparse_2_4_peak": None,
                "dense_ridge_ops_per_byte": None,
                "sparse_2_4_ridge_ops_per_byte": None,
                "dense_per_mm2": None,
                "sparse_2_4_per_mm2": None,
                "dense_per_watt": None,
                "sparse_2_4_per_watt": None,
            }
            continue

        dense_peak = float(rf_fmt["dense_peak"])
        sparse_peak = (
            float(rf_fmt["sparse_2_4_peak"])
            if rf_fmt["sparse_2_4_peak"] is not None
            else None
        )
        # Exact definition: peak_tflops * 1e12 / (bw_tbps * 1e12) == peak_tflops / bw_tbps
        dense_ridge = (dense_peak * 1e12) / (bw_tbps * 1e12)
        sparse_ridge = (
            (sparse_peak * 1e12) / (bw_tbps * 1e12) if sparse_peak is not None else None
        )
        tdp_w = power_by_precision[fmt_key]
        formats_out[fmt_key] = {
            "label": rf_fmt["label"],
            "unit": rf_fmt["unit"],
            "supported": True,
            "sparse_2_4_supported": bool(rf_fmt["sparse_2_4_supported"]),
            "dense_peak": dense_peak,
            "sparse_2_4_peak": sparse_peak,
            "dense_ridge_ops_per_byte": dense_ridge,
            "sparse_2_4_ridge_ops_per_byte": sparse_ridge,
            "dense_per_mm2": dense_peak / die_area_mm2,
            "sparse_2_4_per_mm2": (
                sparse_peak / die_area_mm2 if sparse_peak is not None else None
            ),
            "dense_per_watt": dense_peak / tdp_w,
            "sparse_2_4_per_watt": (
                sparse_peak / tdp_w if sparse_peak is not None else None
            ),
            "modeled_tdp_w_at_format": tdp_w,
        }
    return formats_out


def model_aigpu_target(
    profile_name: str,
    *,
    node_id: str = "n4p_est",
    measured: dict[str, Any] | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Model die area, power breakdown, thermal density, and TFLOPS/mm^2/W for aigpu-b1(-tile)."""
    if profile_name not in ("aigpu-b1", "aigpu-b1-tile"):
        raise ValueError(f"Unsupported AI-GPU target profile: {profile_name!r}")
    if node_id not in NODE_SPECS:
        raise ValueError(f"Unknown node {node_id!r}; expected one of {VALID_NODES}")

    if measured is None:
        measured = load_measured_presilicon_inputs()

    node = NODE_SPECS[node_id]
    rf = roofline_cmp.analyze_profile(
        profile_name, config_path=config_path, profiles_dir=profiles_dir
    )
    _, _, cfg = roofline_cmp.resolve_profile_config(
        profile_name, config_path=config_path, profiles_dir=profiles_dir
    )
    sram_info = measured["sram_manifest_profiles"][profile_name]

    is_full = profile_name == "aigpu-b1"
    cores = int(rf["topology"]["total_cores"])
    threads = int(rf["topology"]["threads_per_warp"])
    warps = int(rf["topology"]["warps_per_core"])
    issue_width = int(rf["topology"]["issue_width"])
    tcu_blocks = int(rf["tcu_architecture"]["blocks_per_core"])
    pe_ratio = int(rf["tcu_architecture"]["pe_ratio"])
    tck = int(rf["tcu_architecture"]["tc_k"])
    clock_mhz = float(rf["memory"]["clock_mhz"])
    clock_ghz = clock_mhz / 1000.0
    bw_gbs = float(rf["memory"]["bandwidth_gbs"])
    bw_tbps = bw_gbs / 1000.0
    vm_enabled = bool(cfg.get("VX_CFG_VM_ENABLE", False))
    dcache_banks = int(cfg.get("VX_CFG_DCACHE_NUM_BANKS", 1))
    l2_banks = int(cfg.get("VX_CFG_L2_NUM_BANKS", 1))

    # 1. Logic Area (anchored strictly to measured ASAP7 Yosys + OpenROAD metrics)
    macros = measured["measured_asap7_macros"]
    yosys_units = measured["yosys_asap7_unit_baselines"]

    fedp_n2_area = macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_stdcell_area_um2"]
    mul_f16_synth_area = macros["vx_tcu_tfr_mul_f16_asap7"]["synth_stdcell_area_um2"]
    pnr_area_mult = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_to_synth_area_ratio"]
    pnr_dyn_mult = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_to_synth_dyn_power_ratio"]
    dft_synth_area = macros["vx_asic_dft_top_asap7"]["synth_stdcell_area_um2"]
    soc_synth_area = macros["vx_asic_soc_top_asap7_fakeram7"]["synth_stdcell_area_um2"]

    fedps_per_core = (threads // pe_ratio) * tcu_blocks
    mul_frac = mul_f16_synth_area / fedp_n2_area
    n_scale = mul_frac * (tck / 2.0) + (1.0 - mul_frac) * (1.0 + 0.35 * (tck / 2.0 - 1.0))
    fedp_core_asap7_um2 = (
        fedps_per_core
        * fedp_n2_area
        * n_scale
        * PARAMETRIC_MODEL_CONSTANTS["fedp_multiformat_area_overhead"]
    )

    tcu_ctrl_per_blk_16t = max(
        10000.0,
        yosys_units["tcu_16t_16w_tfr_um2"]
        - 16.0
        * fedp_n2_area
        * n_scale
        * PARAMETRIC_MODEL_CONSTANTS["fedp_multiformat_area_overhead"],
    )
    wgmma_core_asap7_um2 = (
        tcu_blocks
        * tcu_ctrl_per_blk_16t
        * (threads / 16.0)
        * (1.15 if warps >= 32 else 1.0)
    )

    lane_scale = (
        (threads / 8.0)
        * issue_width
        * PARAMETRIC_MODEL_CONSTANTS["rv64_lane_width_area_scale_vs_rv32"]
    )
    ctrl_scale = (
        (warps / 8.0)
        * (0.5 + 0.5 * issue_width)
        * PARAMETRIC_MODEL_CONSTANTS["rv64_ctrl_width_area_scale_vs_rv32"]
    )
    scalar_core_asap7_um2 = yosys_units["core_8t_8w_rv32_um2"] * (
        PARAMETRIC_MODEL_CONSTANTS["core_scalar_lane_area_fraction"] * lane_scale
        + PARAMETRIC_MODEL_CONSTANTS["core_scalar_ctrl_area_fraction"] * ctrl_scale
    )

    mufu_core_asap7_um2 = yosys_units["mufu_16t_um2"] * (threads / 16.0)
    l1_ctrl_core_asap7_um2 = (
        yosys_units["cache_ctrl_um2"]
        * (1.0 if is_full else 0.5)
        * (0.6 + 0.25 * dcache_banks)
    )
    vm_core_asap7_um2 = (
        PARAMETRIC_MODEL_CONSTANTS["vm_mmu_tlb_asap7_um2_per_core"] if vm_enabled else 0.0
    )
    dxa_core_asap7_um2 = yosys_units["dxa_16t_um2"] * (1.0 if is_full else 0.25)

    core_synth_asap7_um2 = (
        fedp_core_asap7_um2
        + wgmma_core_asap7_um2
        + scalar_core_asap7_um2
        + mufu_core_asap7_um2
        + l1_ctrl_core_asap7_um2
        + vm_core_asap7_um2
        + dxa_core_asap7_um2
    )
    l2_ctrl_asap7_um2 = l2_banks * (
        PARAMETRIC_MODEL_CONSTANTS["l2_bank_ctrl_asap7_um2_full"]
        if is_full
        else PARAMETRIC_MODEL_CONSTANTS["l2_bank_ctrl_asap7_um2_tile"]
    )
    noc_soc_asap7_um2 = (
        (
            PARAMETRIC_MODEL_CONSTANTS["noc_cp_fabric_asap7_um2_full"]
            if is_full
            else PARAMETRIC_MODEL_CONSTANTS["noc_cp_fabric_asap7_um2_tile"]
        )
        + soc_synth_area
        + dft_synth_area
    )

    total_synth_asap7_mm2 = (cores * core_synth_asap7_um2 + l2_ctrl_asap7_um2 + noc_soc_asap7_um2) / 1e6
    pnr_expansion = pnr_area_mult / node.pnr_macro_utilization
    logic_stdcell_scaled_mm2 = total_synth_asap7_mm2 * node.logic_area_scale_vs_asap7
    logic_routed_mm2 = logic_stdcell_scaled_mm2 * pnr_expansion
    routing_halo_overhead_mm2 = logic_routed_mm2 - logic_stdcell_scaled_mm2

    # 2. SRAM Area (exact bit count from sram_macro_manifest.json)
    sram_area = _compute_sram_area_mm2(sram_info, node)

    # 3. Hard-IP Area (PHYs, PCIe/UCIe SerDes, PLL, Padring)
    ip_dict = (
        PARAMETRIC_MODEL_CONSTANTS["hard_ip_n4p_mm2_full"]
        if is_full
        else PARAMETRIC_MODEL_CONSTANTS["hard_ip_n4p_mm2_tile"]
    )
    hard_ip_breakdown_mm2 = {
        k: float(v) * node.phy_area_scale_vs_n4p for k, v in ip_dict.items()
    }
    hard_ip_total_mm2 = sum(hard_ip_breakdown_mm2.values())

    die_area_mm2 = logic_routed_mm2 + sram_area["sram_total_mm2"] + hard_ip_total_mm2
    within_reticle_limit = die_area_mm2 <= RETICLE_LIMIT_MM2
    reticle_utilization_pct = (die_area_mm2 / RETICLE_LIMIT_MM2) * 100.0

    # 4. Power Breakdown (anchored to measured OpenSTA ASAP7 power)
    fedp_e01_pj = macros["vx_tcu_fedp_tfr_asap7_lat4"]["synth_dyn_power_mw_at_1ghz_0p1_act"]
    tcu_activity_mult = (
        PARAMETRIC_MODEL_CONSTANTS["gemm_tcu_effective_toggle_factor"]
        / PARAMETRIC_MODEL_CONSTANTS["opensta_default_input_activity"]
    )
    tcu_dyn_asap7_w = (
        cores
        * fedps_per_core
        * (
            fedp_e01_pj
            * tcu_activity_mult
            * pnr_dyn_mult
            * n_scale
            * PARAMETRIC_MODEL_CONSTANTS["fedp_multiformat_dynamic_power_overhead"]
        )
        * (clock_ghz * 1e9)
        * 1e-12
    )
    non_fedp_synth_asap7_mm2 = total_synth_asap7_mm2 - (cores * fedp_core_asap7_um2 / 1e6)
    mul_pnr_dyn_density = macros["vx_tcu_tfr_mul_f16_asap7"][
        "pnr_dyn_power_density_w_per_mm2_at_1ghz_0p1_act"
    ]
    core_uncore_dyn_asap7_w = (
        non_fedp_synth_asap7_mm2
        * pnr_area_mult
        * mul_pnr_dyn_density
        * PARAMETRIC_MODEL_CONSTANTS["non_fedp_logic_active_duty_factor"]
        * clock_ghz
    )

    tcu_dyn_base_w = tcu_dyn_asap7_w * node.logic_dyn_energy_scale_vs_asap7
    core_uncore_dyn_w = core_uncore_dyn_asap7_w * node.logic_dyn_energy_scale_vs_asap7

    internal_sram_tbps = (
        (cores * issue_width * (threads * 4) * clock_ghz) / 1000.0
    ) * PARAMETRIC_MODEL_CONSTANTS["sram_internal_bandwidth_duty_factor"]
    sram_dyn_w = internal_sram_tbps * node.sram_energy_pj_per_byte

    if is_full:
        mem_io_w = (bw_tbps * 8.0) * node.hbm_io_energy_pj_per_bit
        hard_ip_w = (
            PARAMETRIC_MODEL_CONSTANTS["hard_ip_base_power_asap7_w_full"]
            * node.logic_dyn_energy_scale_vs_asap7
        )
    else:
        mem_io_w = node.mpw_tile_io_power_w
        hard_ip_w = (
            PARAMETRIC_MODEL_CONSTANTS["hard_ip_base_power_asap7_w_tile"]
            * node.logic_dyn_energy_scale_vs_asap7
        )

    def _power_for_tcu_scale(tcu_mult: float) -> dict[str, float]:
        tcu_w = tcu_dyn_base_w * tcu_mult
        dyn_compute_w = tcu_w + core_uncore_dyn_w
        active_die_w = (
            dyn_compute_w
            + sram_dyn_w
            + PARAMETRIC_MODEL_CONSTANTS["on_die_hbm_phy_leakage_share"] * mem_io_w
            + hard_ip_w
        )
        leak_w = active_die_w * (
            node.leakage_fraction_of_die_power / (1.0 - node.leakage_fraction_of_die_power)
        )
        total_w = dyn_compute_w + sram_dyn_w + mem_io_w + hard_ip_w + leak_w
        return {
            "dynamic_compute_tcu_w": tcu_w,
            "dynamic_compute_core_uncore_w": core_uncore_dyn_w,
            "dynamic_compute_total_w": dyn_compute_w,
            "dynamic_sram_w": sram_dyn_w,
            "memory_io_and_phy_w": mem_io_w,
            "uncore_hard_ip_serdes_pll_w": hard_ip_w,
            "static_leakage_w": leak_w,
            "total_tdp_w": total_w,
        }

    power_by_fmt: dict[str, dict[str, float]] = {
        fmt_key: _power_for_tcu_scale(mult)
        for fmt_key, mult in PARAMETRIC_MODEL_CONSTANTS[
            "precision_dynamic_power_multipliers"
        ].items()
    }
    nominal_power = power_by_fmt["fp16_bf16"]
    nominal_tdp_w = nominal_power["total_tdp_w"]
    thermal_density_w_per_mm2 = nominal_tdp_w / die_area_mm2

    measured_mul_fmax = macros["vx_tcu_tfr_mul_f16_asap7"]["pnr_fmax_mhz"]
    projected_node_fmax_mhz = measured_mul_fmax * node.fmax_scale_vs_asap7_rvt

    fmt_metrics = _compute_aigpu_format_metrics(
        rf,
        die_area_mm2=die_area_mm2,
        power_by_precision={k: v["total_tdp_w"] for k, v in power_by_fmt.items()},
    )

    result = {
        "id": profile_name,
        "category": "aigpu_presilicon_model",
        "description": rf["description"],
        "node_id": node.node_id,
        "node_display_name": node.display_name,
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "foundry_signoff": False,
        "model_type": ALLOWED_MODEL_TYPE,
        "is_published_reference": False,
        "topology": rf["topology"],
        "clock_and_frequency": {
            "modeled_target_clock_mhz": clock_mhz,
            "measured_asap7_mul_f16_post_route_fmax_mhz": measured_mul_fmax,
            "projected_node_fmax_ceiling_mhz": projected_node_fmax_mhz,
            "meets_target_clock_at_projected_node": projected_node_fmax_mhz >= clock_mhz,
        },
        "memory_subsystem": {
            "memory_type": "HBM3E-class" if is_full else "MPW AXI4/SerDes (460 GB/s sim ceiling)",
            "bandwidth_gbs": bw_gbs,
            "bandwidth_tbps": bw_tbps,
            "sram_total_bits": sram_info["total_bits"],
            "sram_total_mib": sram_info["total_mib"],
            "sram_1rw_bits": sram_info["bits_1rw"],
            "sram_1r1w_bits": sram_info["bits_1r1w"],
            "sram_logical_arrays": sram_info["total_logical_arrays"],
        },
        "area_breakdown": {
            "core_synth_asap7_um2": core_synth_asap7_um2,
            "total_synth_asap7_mm2": total_synth_asap7_mm2,
            "logic_stdcell_scaled_mm2": logic_stdcell_scaled_mm2,
            "routing_and_utilization_overhead_mm2": routing_halo_overhead_mm2,
            "logic_routed_mm2": logic_routed_mm2,
            "sram_1rw_mm2": sram_area["sram_1rw_mm2"],
            "sram_1r1w_mm2": sram_area["sram_1r1w_mm2"],
            "sram_total_mm2": sram_area["sram_total_mm2"],
            "sram_effective_mbit_per_mm2": sram_area["effective_mbit_per_mm2"],
            "hard_ip_breakdown_mm2": hard_ip_breakdown_mm2,
            "hard_ip_total_mm2": hard_ip_total_mm2,
            "total_die_area_mm2": die_area_mm2,
            "reticle_limit_mm2": RETICLE_LIMIT_MM2,
            "reticle_utilization_pct": reticle_utilization_pct,
            "within_reticle_limit": within_reticle_limit,
        },
        "power_breakdown": {
            **nominal_power,
            "power_density_w_per_mm2": thermal_density_w_per_mm2,
            "by_precision": power_by_fmt,
        },
        "tensor_compute": fmt_metrics,
        "notes": (
            f"{node.notes} "
            + (
                "Full 64-core datacenter SoC target (4 TB/s HBM3E @ 2.0 GHz)."
                if is_full
                else "4-core MPW test-chip verification slice; profile retains VX_config.toml "
                "460 GB/s simulator placeholder for roofline ridge calculation while physical "
                "MPW I/O power models a bounded AXI4/SerDes test link."
            )
        ),
    }
    validate_honesty_record(result)
    return result


def build_published_reference_baselines(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, dict[str, Any]]:
    """Build clearly tagged published NVIDIA baselines for comparison only.

    For `h100` and `rtx5080`, profile topology/bandwidth are cross-checked against
    `profiles/h100.json` and `profiles/rtx5080.json`, while published vendor peak
    TFLOPS, die area (mm^2), and TDP (W) come explicitly from NVIDIA public
    datasheets/whitepapers (and Vortex-modeled `b1_roofline_compare` numbers are
    also retained separately where applicable). For `b200` (single-die and
    dual-die), all numbers are explicitly tagged as published reference specs,
    NEVER locally measured.
    """
    rf_h100 = roofline_cmp.analyze_profile(
        "h100", config_path=config_path, profiles_dir=profiles_dir
    )
    rf_rtx5080 = roofline_cmp.analyze_profile(
        "rtx5080", config_path=config_path, profiles_dir=profiles_dir
    )

    specs: list[dict[str, Any]] = [
        {
            "id": "nvidia-h100-sxm5",
            "display_name": "NVIDIA H100 SXM5 (Published Ref)",
            "architecture": "Hopper GH100 (TSMC 4N, monolithic)",
            "process_node": "TSMC 4N (4nm-class)",
            "profile_link": "profiles/h100.json",
            "die_count": 1,
            "die_area_mm2": 814.0,
            "tdp_w": 700.0,
            "bandwidth_tbps": float(rf_h100["memory"]["bandwidth_gbs"]) / 1000.0,  # 3.35 TB/s
            "memory_type": "HBM3 (80 GB)",
            "clock_mhz": float(rf_h100["memory"]["clock_mhz"]),
            "vortex_modeled_fp16_dense_tflops": float(
                rf_h100["tensor_formats"]["fp16_bf16"]["dense_peak"]
            ),
            "published_peaks": {
                "fp16_bf16": (989.5, 1979.0),
                "fp8": (1979.0, 3958.0),
                "mxfp4": (None, None),
                "nvfp4": (None, None),
            },
            "source_citation": (
                "Published NVIDIA H100 SXM5 Datasheet & GH100 Whitepaper "
                "(814 mm^2 die, 700 W TDP, 3.35 TB/s HBM3, 989.5 FP16 / 1979 FP8 dense TFLOPS; "
                "Vortex profile in profiles/h100.json)."
            ),
        },
        {
            "id": "nvidia-rtx5080",
            "display_name": "NVIDIA RTX 5080 (Published Ref)",
            "architecture": "Blackwell GB203 (TSMC 4N, client/workstation)",
            "process_node": "TSMC 4N (4nm-class)",
            "profile_link": "profiles/rtx5080.json",
            "die_count": 1,
            "die_area_mm2": 378.0,
            "tdp_w": 360.0,
            "bandwidth_tbps": float(rf_rtx5080["memory"]["bandwidth_gbs"]) / 1000.0,  # 0.96 TB/s
            "memory_type": "GDDR7 (16 GB)",
            "clock_mhz": float(rf_rtx5080["memory"]["clock_mhz"]),
            "vortex_modeled_fp16_dense_tflops": float(
                rf_rtx5080["tensor_formats"]["fp16_bf16"]["dense_peak"]
            ),
            "published_peaks": {
                # RTX Blackwell Whitepaper App. B @ 2617 MHz boost:
                # FP16 w/ FP32 accum: 112.6 dense / 225.1 sparse (FP16 accum: 225.1 / 450.2)
                "fp16_bf16": (112.6, 225.1),
                "fp8": (450.2, 900.4),
                "mxfp4": (900.4, 1800.8),
                "nvfp4": (900.4, 1800.8),
            },
            "source_citation": (
                "Published NVIDIA RTX Blackwell GB203 Whitepaper (App. B) & RTX 5080 Specs "
                "(378 mm^2 die, 360 W TGP, 960 GB/s GDDR7, 112.6 FP16 [FP32-acc] / 450.2 FP8 / "
                "900.4 FP4 dense, 1801 AI TOPS sparse; Vortex profile in profiles/rtx5080.json)."
            ),
        },
        {
            "id": "nvidia-b200-single-die",
            "display_name": "NVIDIA B200 Single-Die (Published Ref)",
            "architecture": "Blackwell GB100 half-package die (TSMC 4NP)",
            "process_node": "TSMC 4NP (4nm-class)",
            "profile_link": None,
            "die_count": 1,
            "die_area_mm2": 800.0,  # Single-die reticle-scale half of dual-die B200 (~800 mm^2/die)
            "tdp_w": 500.0,
            "bandwidth_tbps": 4.00,
            "memory_type": "HBM3e (4 stacks/die, half of 8 TB/s B200)",
            "clock_mhz": None,
            "vortex_modeled_fp16_dense_tflops": None,
            "published_peaks": {
                "fp16_bf16": (1125.0, 2250.0),
                "fp8": (2250.0, 4500.0),
                "mxfp4": (4500.0, 9000.0),
                "nvfp4": (4500.0, 9000.0),
            },
            "source_citation": (
                "Published Reference Spec ONLY (NOT locally measured): 1/2 of NVIDIA Blackwell B200 "
                "dual-die package (~800 mm^2 reticle-class die, 500 W half-TDP, 4.0 TB/s HBM3e, "
                "1125 FP16 / 2250 FP8 / 4500 FP4 dense TFLOPS)."
            ),
        },
        {
            "id": "nvidia-b200-dual-die",
            "display_name": "NVIDIA B200 Dual-Die SXM (Published Ref)",
            "architecture": "Blackwell GB100 dual-die CoWoS-L package (TSMC 4NP)",
            "process_node": "TSMC 4NP (4nm-class, 2x reticle dies)",
            "profile_link": None,
            "die_count": 2,
            "die_area_mm2": 1600.0,
            "tdp_w": 1000.0,
            "bandwidth_tbps": 8.00,
            "memory_type": "HBM3e (192 GB / 8 stacks, up to 8.0 TB/s)",
            "clock_mhz": None,
            "vortex_modeled_fp16_dense_tflops": None,
            "published_peaks": {
                "fp16_bf16": (2250.0, 4500.0),
                "fp8": (4500.0, 9000.0),
                "mxfp4": (9000.0, 18000.0),
                "nvfp4": (9000.0, 18000.0),
            },
            "source_citation": (
                "Published Reference Spec ONLY (NOT locally measured): NVIDIA B200 SXM datasheet "
                "(2x ~800 mm^2 dies = ~1600 mm^2 silicon, 1000 W TDP, up to 8.0 TB/s HBM3e, "
                "2250 FP16 / 4500 FP8 / 9000 FP4 dense TFLOPS; 4500/9000/18000 sparse)."
            ),
        },
    ]

    baselines: dict[str, dict[str, Any]] = {}
    for spec in specs:
        area = float(spec["die_area_mm2"])
        tdp = float(spec["tdp_w"])
        bw_tbps = float(spec["bandwidth_tbps"])
        per_die_area = area / float(spec["die_count"])
        tensor_compute: dict[str, Any] = {}
        for fmt_key, (dense_val, sparse_val) in spec["published_peaks"].items():
            supported = dense_val is not None
            dense_ridge = (dense_val * 1e12) / (bw_tbps * 1e12) if dense_val is not None else None
            sparse_ridge = (
                (sparse_val * 1e12) / (bw_tbps * 1e12) if sparse_val is not None else None
            )
            tensor_compute[fmt_key] = {
                "supported": supported,
                "sparse_2_4_supported": sparse_val is not None,
                "dense_peak": dense_val,
                "sparse_2_4_peak": sparse_val,
                "dense_ridge_ops_per_byte": dense_ridge,
                "sparse_2_4_ridge_ops_per_byte": sparse_ridge,
                "dense_per_mm2": (dense_val / area) if dense_val is not None else None,
                "sparse_2_4_per_mm2": (sparse_val / area) if sparse_val is not None else None,
                "dense_per_watt": (dense_val / tdp) if dense_val is not None else None,
                "sparse_2_4_per_watt": (sparse_val / tdp) if sparse_val is not None else None,
            }

        entry = {
            "id": spec["id"],
            "category": "published_vendor_reference_baseline",
            "display_name": spec["display_name"],
            "architecture": spec["architecture"],
            "process_node": spec["process_node"],
            "profile_link": spec["profile_link"],
            "evidence_level": ALLOWED_EVIDENCE_LEVEL,
            "silicon_measured": False,
            "foundry_signoff": False,
            "model_type": ALLOWED_MODEL_TYPE,
            "is_published_reference": True,
            "locally_measured": False,
            "die_count": spec["die_count"],
            "total_silicon_area_mm2": area,
            "per_die_area_mm2": per_die_area,
            "within_reticle_limit_per_die": per_die_area <= RETICLE_LIMIT_MM2,
            "tdp_w": tdp,
            "power_density_w_per_mm2": tdp / area,
            "bandwidth_tbps": bw_tbps,
            "bandwidth_gbs": bw_tbps * 1000.0,
            "memory_type": spec["memory_type"],
            "vortex_modeled_fp16_dense_tflops": spec["vortex_modeled_fp16_dense_tflops"],
            "tensor_compute": tensor_compute,
            "source_citation": spec["source_citation"],
        }
        validate_honesty_record(entry)
        baselines[spec["id"]] = entry
    return baselines


def build_ppa_report(
    *,
    node_id: str = "n4p_est",
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    phys_results_path: Path = DEFAULT_PHYS_RESULTS_PATH,
    sram_manifest_path: Path = DEFAULT_SRAM_MANIFEST_PATH,
    yosys_dir: Path = DEFAULT_YOSYS_DIR,
    beacon_dir: Path = DEFAULT_BEACON_DIR,
) -> dict[str, Any]:
    """Build complete parametric PPA report across AI-GPU targets and published references."""
    if node_id not in NODE_SPECS:
        raise ValueError(f"Unknown node {node_id!r}; expected one of {VALID_NODES}")

    measured = load_measured_presilicon_inputs(
        phys_results_path=phys_results_path,
        sram_manifest_path=sram_manifest_path,
        yosys_dir=yosys_dir,
        beacon_dir=beacon_dir,
    )
    aigpu_targets = {
        name: model_aigpu_target(
            name,
            node_id=node_id,
            measured=measured,
            config_path=config_path,
            profiles_dir=profiles_dir,
        )
        for name in ("aigpu-b1-tile", "aigpu-b1")
    }
    node_sweep_aigpu_b1 = {
        nid: model_aigpu_target(
            "aigpu-b1",
            node_id=nid,
            measured=measured,
            config_path=config_path,
            profiles_dir=profiles_dir,
        )
        for nid in VALID_NODES
    }
    node_sweep_tile = {
        nid: model_aigpu_target(
            "aigpu-b1-tile",
            node_id=nid,
            measured=measured,
            config_path=config_path,
            profiles_dir=profiles_dir,
        )
        for nid in VALID_NODES
    }
    published_refs = build_published_reference_baselines(
        config_path=config_path, profiles_dir=profiles_dir
    )

    node = NODE_SPECS[node_id]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "foundry_signoff": False,
        "model_type": ALLOWED_MODEL_TYPE,
        "selected_node": node_id,
        "disclaimer": (
            "PARAMETRIC PRE-SILICON PPA ESTIMATE ONLY (ADR-006): anchored to real "
            "open-source Yosys/OpenSTA/OpenROAD ASAP7 measurements and exact SRAM "
            "manifest bit counts, extrapolated via explicit commercial node scaling "
            "assumptions. NOT manufactured silicon (silicon_measured=false), NOT "
            "foundry sign-off (foundry_signoff=false), and NOT physical FPGA results."
        ),
        "measured_presilicon_inputs": measured,
        "parametric_scaling_assumptions": {
            "selected_node": {
                "node_id": node.node_id,
                "display_name": node.display_name,
                "process_class": node.process_class,
                "is_predictive_academic_pdk": node.is_predictive_academic_pdk,
                "logic_area_scale_vs_asap7": node.logic_area_scale_vs_asap7,
                "sram_1rw_bitcell_um2": node.sram_1rw_bitcell_um2,
                "sram_1r1w_area_multiplier": node.sram_1r1w_area_multiplier,
                "sram_array_efficiency": node.sram_array_efficiency,
                "pnr_macro_utilization": node.pnr_macro_utilization,
                "phy_area_scale_vs_n4p": node.phy_area_scale_vs_n4p,
                "logic_dyn_energy_scale_vs_asap7": node.logic_dyn_energy_scale_vs_asap7,
                "sram_energy_pj_per_byte": node.sram_energy_pj_per_byte,
                "hbm_io_energy_pj_per_bit": node.hbm_io_energy_pj_per_bit,
                "mpw_tile_io_power_w": node.mpw_tile_io_power_w,
                "leakage_fraction_of_die_power": node.leakage_fraction_of_die_power,
                "fmax_scale_vs_asap7_rvt": node.fmax_scale_vs_asap7_rvt,
                "notes": node.notes,
            },
            "all_nodes": {
                nid: {
                    "logic_area_scale_vs_asap7": ns.logic_area_scale_vs_asap7,
                    "sram_1rw_bitcell_um2": ns.sram_1rw_bitcell_um2,
                    "sram_array_efficiency": ns.sram_array_efficiency,
                    "logic_dyn_energy_scale_vs_asap7": ns.logic_dyn_energy_scale_vs_asap7,
                    "sram_energy_pj_per_byte": ns.sram_energy_pj_per_byte,
                    "hbm_io_energy_pj_per_bit": ns.hbm_io_energy_pj_per_bit,
                    "leakage_fraction_of_die_power": ns.leakage_fraction_of_die_power,
                    "fmax_scale_vs_asap7_rvt": ns.fmax_scale_vs_asap7_rvt,
                }
                for nid, ns in NODE_SPECS.items()
            },
            "model_constants": PARAMETRIC_MODEL_CONSTANTS,
        },
        "aigpu_targets": aigpu_targets,
        "node_sensitivity_sweep": {
            "aigpu-b1": node_sweep_aigpu_b1,
            "aigpu-b1-tile": node_sweep_tile,
        },
        "published_reference_baselines": published_refs,
    }
    validate_honesty_record(report)
    return report


def _fmt_opt(val: float | None, precision: int = 2) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{precision}f}"


def format_report_markdown(report: dict[str, Any]) -> str:
    """Render deterministic Markdown tables suitable for Track F1/F4 collateral."""
    validate_honesty_record(report)
    node_id = report["selected_node"]
    assump = report["parametric_scaling_assumptions"]["selected_node"]
    measured = report["measured_presilicon_inputs"]
    macros = measured["measured_asap7_macros"]
    sram_prof = measured["sram_manifest_profiles"]

    lines: list[str] = [
        f"# AI-GPU Parametric Pre-Silicon PPA Report (`node={node_id}`)",
        "",
        f"- **Evidence Level**: `{report['evidence_level']}` | "
        f"**Model Type**: `{report['model_type']}` | "
        f"**`silicon_measured`**: `{str(report['silicon_measured']).lower()}` | "
        f"**`foundry_signoff`**: `{str(report['foundry_signoff']).lower()}`",
        f"- **Selected Technology Node**: `{assump['display_name']}` ({assump['process_class']})",
        f"- **Boundary**: {report['disclaimer']}",
        "",
        "## 1. Measured Pre-Silicon Inputs (ASAP7 EDA & SRAM Manifest)",
        "",
        "| Measured Artifact / Module | Scope | Key Measured Value | Source |",
        "|---|---|---:|---|",
        f"| `VX_tcu_tfr_mul_f16` (OpenROAD PnR) | ASAP7 7nm P&R + GDS | "
        f"`{macros['vx_tcu_tfr_mul_f16_asap7']['pnr_fmax_mhz']:.2f} MHz` Fmax, "
        f"`{macros['vx_tcu_tfr_mul_f16_asap7']['pnr_design_area_um2']:.1f} um^2` design "
        f"(`{macros['vx_tcu_tfr_mul_f16_asap7']['pnr_to_synth_area_ratio']:.3f}x` synth) | `hw/asic/phys/phys_results.json` |",
        f"| `VX_tcu_fedp_tfr` LAT4 (Yosys + OpenSTA) | ASAP7 N=2 TCK=4 | "
        f"`{macros['vx_tcu_fedp_tfr_asap7_lat4']['synth_stdcell_area_um2']:.2f} um^2`, "
        f"`{macros['vx_tcu_fedp_tfr_asap7_lat4']['synth_dyn_power_mw_at_1ghz_0p1_act']:.4f} mW` dyn@1GHz | `hw/asic/phys/phys_results.json` |",
        f"| `VX_asic_dft_top` (OpenROAD PnR) | ASAP7 JTAG/MBIST | "
        f"`{macros['vx_asic_dft_top_asap7']['pnr_design_area_um2']:.1f} um^2`, "
        f"`{macros['vx_asic_dft_top_asap7']['pnr_utilization_pct']:.1f}%` util | `hw/asic/phys/phys_results.json` |",
        f"| `VX_asic_soc_top` w/ FakeRAM7 (Yosys) | ASAP7 CDC AXI4 shell | "
        f"`{macros['vx_asic_soc_top_asap7_fakeram7']['synth_stdcell_area_um2']:.2f} um^2` logic, "
        f"`{macros['vx_asic_soc_top_asap7_fakeram7']['datapath_excl_reset_clk_core_fmax_mhz']:.2f} MHz` datapath | `hw/asic/phys/phys_results.json` |",
        f"| `aigpu-b1-tile` SRAM Manifest | 4 cores, 131 arrays | "
        f"`{sram_prof['aigpu-b1-tile']['total_bits']:,}` bits (`{sram_prof['aigpu-b1-tile']['total_mib']:.4f} MiB`) | `hw/asic/sram/sram_macro_manifest.json` |",
        f"| `aigpu-b1` SRAM Manifest | 64 cores, 8,256 arrays | "
        f"`{sram_prof['aigpu-b1']['total_bits']:,}` bits (`{sram_prof['aigpu-b1']['total_mib']:.4f} MiB`) | `hw/asic/sram/sram_macro_manifest.json` |",
        "",
        f"## 2. AI-GPU Die Area, Power & Compute Density (`{node_id}`)",
        "",
        "| Metric | `aigpu-b1-tile` (4C MPW Slice) | `aigpu-b1` (64C AI-Only SoC) |",
        "|---|---:|---:|",
    ]
    tile = report["aigpu_targets"]["aigpu-b1-tile"]
    b1 = report["aigpu_targets"]["aigpu-b1"]
    t_area = tile["area_breakdown"]
    b_area = b1["area_breakdown"]
    t_pwr = tile["power_breakdown"]
    b_pwr = b1["power_breakdown"]

    area_rows = [
        ("Logic Stdcell Scaled (mm^2)", f"{t_area['logic_stdcell_scaled_mm2']:.3f}", f"{b_area['logic_stdcell_scaled_mm2']:.2f}"),
        ("Routing & Floorplan Overhead (mm^2)", f"{t_area['routing_and_utilization_overhead_mm2']:.3f}", f"{b_area['routing_and_utilization_overhead_mm2']:.2f}"),
        ("SRAM Macro Total (mm^2)", f"{t_area['sram_total_mm2']:.3f}", f"{b_area['sram_total_mm2']:.2f}"),
        ("Hard IP / PHY / Padring (mm^2)", f"{t_area['hard_ip_total_mm2']:.3f}", f"{b_area['hard_ip_total_mm2']:.2f}"),
        ("**Total Die Area (mm^2)**", f"**{t_area['total_die_area_mm2']:.2f}**", f"**{b_area['total_die_area_mm2']:.2f}**"),
        ("Reticle Limit (`<= 858 mm^2`)", f"PASS ({t_area['reticle_utilization_pct']:.2f}%)", f"PASS ({b_area['reticle_utilization_pct']:.2f}%)" if b_area["within_reticle_limit"] else f"FAIL ({b_area['reticle_utilization_pct']:.2f}%)"),
        ("Compute Dynamic Power (W)", f"{t_pwr['dynamic_compute_total_w']:.2f}", f"{b_pwr['dynamic_compute_total_w']:.1f}"),
        ("SRAM Dynamic Power (W)", f"{t_pwr['dynamic_sram_w']:.2f}", f"{b_pwr['dynamic_sram_w']:.1f}"),
        ("Memory I/O & PHY Power (W)", f"{t_pwr['memory_io_and_phy_w']:.2f}", f"{b_pwr['memory_io_and_phy_w']:.1f}"),
        ("Hard IP / SerDes / PLL Power (W)", f"{t_pwr['uncore_hard_ip_serdes_pll_w']:.2f}", f"{b_pwr['uncore_hard_ip_serdes_pll_w']:.1f}"),
        ("Static Leakage Power (W)", f"{t_pwr['static_leakage_w']:.2f}", f"{b_pwr['static_leakage_w']:.1f}"),
        ("**Total Modeled TDP (W)**", f"**{t_pwr['total_tdp_w']:.2f}**", f"**{b_pwr['total_tdp_w']:.1f}**"),
        ("Power / Thermal Density (W/mm^2)", f"{t_pwr['power_density_w_per_mm2']:.3f}", f"{b_pwr['power_density_w_per_mm2']:.3f}"),
        ("Target Clock / Projected Fmax (MHz)", f"{tile['clock_and_frequency']['modeled_target_clock_mhz']:.0f} / {tile['clock_and_frequency']['projected_node_fmax_ceiling_mhz']:.0f}", f"{b1['clock_and_frequency']['modeled_target_clock_mhz']:.0f} / {b1['clock_and_frequency']['projected_node_fmax_ceiling_mhz']:.0f}"),
    ]
    for label, v_tile, v_b1 in area_rows:
        lines.append(f"| {label} | {v_tile} | {v_b1} |")

    lines.extend([
        "",
        f"## 3. Cross-Accelerator PPA & Compute-Density Comparison (`{node_id}` vs Published Reference Specs)",
        "",
        "| Device (Tag) | Silicon Area (mm^2) | TDP (W) | W/mm^2 | Mem BW (TB/s) | FP16 D/S (TFLOPS) | FP8 D/S (TFLOPS) | FP4 D/S (TOPS) | FP16 Ridge (Op/B) | FP16 D / mm^2 | FP16 D / W | FP4 D / W |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    def _pair(tc: dict[str, Any], key: str) -> str:
        ent = tc[key]
        if not ent["supported"]:
            return "N/A"
        return f"{_fmt_opt(ent['dense_peak'], 1)} / {_fmt_opt(ent['sparse_2_4_peak'], 1)}"

    for label, entry, is_ref in [
        (f"`aigpu-b1-tile` ({node_id} est)", tile, False),
        (f"`aigpu-b1` ({node_id} est)", b1, False),
        ("NVIDIA `RTX 5080` (Published Ref)", report["published_reference_baselines"]["nvidia-rtx5080"], True),
        ("NVIDIA `H100 SXM5` (Published Ref)", report["published_reference_baselines"]["nvidia-h100-sxm5"], True),
        ("NVIDIA `B200 1-Die` (Published Ref)", report["published_reference_baselines"]["nvidia-b200-single-die"], True),
        ("NVIDIA `B200 2-Die` (Published Ref)", report["published_reference_baselines"]["nvidia-b200-dual-die"], True),
    ]:
        area = entry["total_silicon_area_mm2"] if is_ref else entry["area_breakdown"]["total_die_area_mm2"]
        tdp = entry["tdp_w"] if is_ref else entry["power_breakdown"]["total_tdp_w"]
        w_per_mm2 = entry["power_density_w_per_mm2"] if is_ref else entry["power_breakdown"]["power_density_w_per_mm2"]
        bw = entry["bandwidth_tbps"] if is_ref else entry["memory_subsystem"]["bandwidth_tbps"]
        tc = entry["tensor_compute"]
        fp4_key = "nvfp4"
        lines.append(
            f"| {label} | {area:.2f} | {tdp:.1f} | {w_per_mm2:.3f} | {bw:.2f} | "
            f"{_pair(tc, 'fp16_bf16')} | {_pair(tc, 'fp8')} | {_pair(tc, fp4_key)} | "
            f"{_fmt_opt(tc['fp16_bf16']['dense_ridge_ops_per_byte'], 2)} | "
            f"{_fmt_opt(tc['fp16_bf16']['dense_per_mm2'], 3)} | "
            f"{_fmt_opt(tc['fp16_bf16']['dense_per_watt'], 3)} | "
            f"{_fmt_opt(tc[fp4_key]['dense_per_watt'], 3)} |"
        )

    lines.extend([
        "",
        "## 4. Node Scaling Sensitivity (`aigpu-b1` 64-Core SoC)",
        "",
        "| Node | Logic Routed (mm^2) | SRAM (mm^2) | Hard IP (mm^2) | Total Die (mm^2) | Reticle `<=858` | TDP (W) | W/mm^2 | FP16/W | FP4/W |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for nid in VALID_NODES:
        sw = report["node_sensitivity_sweep"]["aigpu-b1"][nid]
        ab = sw["area_breakdown"]
        pb = sw["power_breakdown"]
        tc = sw["tensor_compute"]
        lines.append(
            f"| `{nid}` | {ab['logic_routed_mm2']:.2f} | {ab['sram_total_mm2']:.2f} | "
            f"{ab['hard_ip_total_mm2']:.2f} | {ab['total_die_area_mm2']:.2f} | "
            f"{'PASS' if ab['within_reticle_limit'] else 'FAIL'} | {pb['total_tdp_w']:.1f} | "
            f"{pb['power_density_w_per_mm2']:.3f} | {tc['fp16_bf16']['dense_per_watt']:.3f} | "
            f"{tc['nvfp4']['dense_per_watt']:.3f} |"
        )

    lines.extend([
        "",
        "## 5. Honesty & Scope Disclaimers",
        "",
        "- `evidence_level`: `simulated` | `model_type`: `parametric_presilicon_estimate` | "
        "`silicon_measured`: `false` | `foundry_signoff`: `false`.",
        "- `NVIDIA H100`, `RTX 5080`, and `B200` (single-die and dual-die) entries are **published reference specifications only** — NOT locally measured silicon.",
        "- `aigpu-b1` commercial node projections (`n4p_est`, `n3e_est`) are pre-PDK parametric scaling estimates awaiting commercial foundry PDK, memory compilers, and HBM3E/PCIe IP (`ODR-007`/`ODR-008`).",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--node",
        choices=VALID_NODES,
        default="n4p_est",
        help="Target technology node parameterization (default: n4p_est)",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON report",
    )
    output_group.add_argument(
        "--markdown",
        action="store_true",
        help="Emit Markdown datasheet/dashboard report (default output mode)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path",
    )
    args = parser.parse_args(argv)

    report = build_ppa_report(node_id=args.node)
    if args.json:
        text = json.dumps(report, indent=2) + "\n"
    else:
        text = format_report_markdown(report)

    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
