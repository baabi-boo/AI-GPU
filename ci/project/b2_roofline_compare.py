#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Hierarchical analytical roofline comparator for AI-GPU B2 vs B1 and baselines.

This pure-Python standard-library analytical engine compares pre-silicon AI-GPU
B2 targets (`aigpu-b2`, `aigpu-b2-dual`, `aigpu-b2-tile`) and preserved B1
targets (`aigpu-b1`, `aigpu-b1-tile`) against published vendor datasheet
baselines (NVIDIA B200 1-Die/2-Die SXM, NVIDIA H200 SXM, NVIDIA H100 SXM5,
AMD MI300X, NVIDIA RTX 5080).

Capabilities:
  1. Profile resolution via `ci/gen_config.py` against `VX_config.toml` (with
     validated architectural fallback when custom profile directories omit B2
     JSON files).
  2. Complete B2 precision coverage (`FP16`, `BF16`, `TF32`, `FP8` E4M3/E5M2,
     `MXFP8`, `MXFP6` E2M3/E3M2, `MXFP4`, `NVFP4`, `INT8`) across dense and
     `2:4` structured sparse modes, reconciling Vortex base resolved TFR vs the
     `TFRv2` wide `16x8x8` architectural target.
  3. Six-level hierarchical roofline ceilings:
     - Level 1: TMEM / Register File accumulator reuse
     - Level 2: Shared LMEM / L1 data cache
     - Level 3: Coherent L2 / SLC (plus L3 Infinity Cache where present)
     - Level 4: HBM3E / GDDR external memory bandwidth
     - Level 5: Dual-die CoWoS-L UCIe 2.0 coherent D2D fabric
     - Level 6: PCIe Gen6/Gen5 host offload + Hardware Decompression Engine
  4. Analytical workload models for Llama-3 (8B, 70B, 405B) with GQA + SwiGLU
     and DeepSeek-V3 MoE with MLA + routed/shared experts + AllToAll dispatch,
     spanning prefill (seq 1K/4K/16K/32K) and decode (batch 1/8/32/128/256).
  5. GEMM tile-efficiency & wave-quantization model (CTA grid occupancy,
     TMEM double-buffering overlap, tail-wave penalty).
  6. Parametric sensitivity sweeps and comparative speedup tables.

Evidence boundary:
  Every output payload carries `schema_version = 1`,
  `evidence_level = "modeled_analytical"`, `silicon_measured = False`,
  `fpga_measured = False`, and `foundry_signoff = False`. Competitor rows
  additionally carry `source = "published_vendor_datasheet"`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any


SCHEMA_VERSION = 1
ALLOWED_EVIDENCE_LEVEL = "modeled_analytical"
FORBIDDEN_PHYSICAL_LEVELS = frozenset({
    "fpga_measured",
    "silicon_measured",
    "rtl_verified",
    "simulated",
    "foundry_signoff",
})

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "VX_config.toml"
DEFAULT_PROFILES_DIR = ROOT / "profiles"

AIGPU_B2_TARGETS = ("aigpu-b2", "aigpu-b2-dual", "aigpu-b2-tile")
AIGPU_B1_TARGETS = ("aigpu-b1", "aigpu-b1-tile")
ALL_AIGPU_TARGETS = AIGPU_B2_TARGETS + AIGPU_B1_TARGETS

COMPETITOR_IDS = (
    "nvidia-b200-1die",
    "nvidia-b200-2die",
    "nvidia-h200-sxm",
    "nvidia-h100-sxm5",
    "amd-mi300x",
    "nvidia-rtx5080",
)

TFRV2_TARGET_FP16_FLOPS_PER_PIPE_CYCLE = 1125.0
TFRV2_PIPE_SCALED_CLOCK_MHZ = 2000.0
BYTES_PER_MIB = 1024 * 1024
BYTES_PER_KIB = 1024


@dataclass(frozen=True)
class FormatSpec:
    """Precision specification for compute throughput and memory traffic."""

    key: str
    label: str
    enable_key: str
    elements_per_word32: int
    storage_bytes_per_element: float
    scale_bytes_per_block: float
    block_size: int
    unit: str
    tfrv2_multiplier_vs_fp16: float
    requires_mx: bool = False
    requires_fp4: bool = False
    tfrv2_only: bool = False

    @property
    def effective_bytes_per_element(self) -> float:
        if self.block_size <= 0 or self.scale_bytes_per_block <= 0.0:
            return self.storage_bytes_per_element
        return self.storage_bytes_per_element + (self.scale_bytes_per_block / float(self.block_size))


FORMAT_SPECS: dict[str, FormatSpec] = {
    "tf32": FormatSpec(
        key="tf32",
        label="TF32",
        enable_key="VX_CFG_TCU_TF32_ENABLE",
        elements_per_word32=1,
        storage_bytes_per_element=4.0,
        scale_bytes_per_block=0.0,
        block_size=0,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=0.5,
    ),
    "fp16": FormatSpec(
        key="fp16",
        label="FP16",
        enable_key="VX_CFG_TCU_FP16_ENABLE",
        elements_per_word32=2,
        storage_bytes_per_element=2.0,
        scale_bytes_per_block=0.0,
        block_size=0,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=1.0,
    ),
    "bf16": FormatSpec(
        key="bf16",
        label="BF16",
        enable_key="VX_CFG_TCU_FP16_ENABLE",
        elements_per_word32=2,
        storage_bytes_per_element=2.0,
        scale_bytes_per_block=0.0,
        block_size=0,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=1.0,
    ),
    "fp8_e4m3": FormatSpec(
        key="fp8_e4m3",
        label="FP8 (E4M3)",
        enable_key="VX_CFG_TCU_FP8_ENABLE",
        elements_per_word32=4,
        storage_bytes_per_element=1.0,
        scale_bytes_per_block=0.0,
        block_size=0,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=2.0,
    ),
    "fp8_e5m2": FormatSpec(
        key="fp8_e5m2",
        label="FP8 (E5M2)",
        enable_key="VX_CFG_TCU_FP8_ENABLE",
        elements_per_word32=4,
        storage_bytes_per_element=1.0,
        scale_bytes_per_block=0.0,
        block_size=0,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=2.0,
    ),
    "mxfp8": FormatSpec(
        key="mxfp8",
        label="MXFP8 (UE8M0)",
        enable_key="VX_CFG_TCU_FP8_ENABLE",
        elements_per_word32=4,
        storage_bytes_per_element=1.0,
        scale_bytes_per_block=1.0,
        block_size=32,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=2.0,
        requires_mx=True,
    ),
    "mxfp6_e2m3": FormatSpec(
        key="mxfp6_e2m3",
        label="MXFP6 (E2M3)",
        enable_key="VX_CFG_TCU_FP8_ENABLE",
        elements_per_word32=4,  # 2.0x FP16 (2 elems/word32) compute-rate packing in TFRv2
        storage_bytes_per_element=0.75,
        scale_bytes_per_block=1.0,
        block_size=32,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=2.0,
        requires_mx=True,
        tfrv2_only=True,
    ),
    "mxfp6_e3m2": FormatSpec(
        key="mxfp6_e3m2",
        label="MXFP6 (E3M2)",
        enable_key="VX_CFG_TCU_FP8_ENABLE",
        elements_per_word32=4,
        storage_bytes_per_element=0.75,
        scale_bytes_per_block=1.0,
        block_size=32,
        unit="TFLOPS",
        tfrv2_multiplier_vs_fp16=2.0,
        requires_mx=True,
        tfrv2_only=True,
    ),
    "mxfp4": FormatSpec(
        key="mxfp4",
        label="MXFP4 (OCP 4-bit)",
        enable_key="VX_CFG_TCU_MXFP4_ENABLE",
        elements_per_word32=8,
        storage_bytes_per_element=0.5,
        scale_bytes_per_block=1.0,
        block_size=32,
        unit="TOPS",
        tfrv2_multiplier_vs_fp16=4.0,
        requires_mx=True,
        requires_fp4=True,
    ),
    "nvfp4": FormatSpec(
        key="nvfp4",
        label="NVFP4 (4-bit)",
        enable_key="VX_CFG_TCU_NVFP4_ENABLE",
        elements_per_word32=8,
        storage_bytes_per_element=0.5,
        scale_bytes_per_block=1.0,
        block_size=16,
        unit="TOPS",
        tfrv2_multiplier_vs_fp16=4.0,
        requires_mx=True,
        requires_fp4=True,
    ),
    "int8": FormatSpec(
        key="int8",
        label="INT8",
        enable_key="VX_CFG_TCU_INT8_ENABLE",
        elements_per_word32=4,
        storage_bytes_per_element=1.0,
        scale_bytes_per_block=0.0,
        block_size=0,
        unit="TOPS",
        tfrv2_multiplier_vs_fp16=2.0,
    ),
}

FORMAT_ALIASES: dict[str, str] = {
    "fp16_bf16": "fp16",
    "fp8": "fp8_e4m3",
    "mxfp6": "mxfp6_e2m3",
    "fp4": "nvfp4",
}


def canonical_format_key(fmt: str) -> str:
    """Resolve user or legacy format names into canonical FORMAT_SPECS keys."""
    norm = fmt.strip().lower()
    norm = FORMAT_ALIASES.get(norm, norm)
    if norm not in FORMAT_SPECS:
        raise ValueError(f"Unsupported format {fmt!r}; expected one of {sorted(FORMAT_SPECS)}")
    return norm


def _b2_authoritative_profile_payload(profile_name: str) -> dict[str, Any]:
    """Return authoritative B2 profile JSON dictionary when disk file is absent."""
    base_core: dict[str, Any] = {
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
        "VX_CFG_TCU_PE_RATIO": 1,
        "VX_CFG_TCU_WGMMA_ENABLE": True,
        "VX_CFG_TCU_FEDP2K": 1,
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
    }
    if profile_name == "aigpu-b2":
        return {
            "name": "aigpu-b2",
            "description": (
                "Pre-silicon full-reticle single-die AI-GPU B2 profile (128 cores, "
                "TFRv2, 32 MiB TMEM, 128 MiB L2, 4.0 TB/s HBM3E, 10 TB/s UCIe 2.0)."
            ),
            "xlen": 64,
            "core": dict(base_core),
            "chip": {
                "VX_CFG_NUM_CLUSTERS": 8,
                "VX_CFG_NUM_CORES": 16,
                "VX_CFG_L2_ENABLE": True,
                "VX_CFG_L2_SIZE": 134217728,
                "VX_CFG_L2_NUM_WAYS": 16,
                "VX_CFG_L2_NUM_BANKS": 64,
                "VX_CFG_L2_MSHR_SIZE": 192,
            },
            "platform": {
                "VX_CFG_PLATFORM_CLOCK_RATE": 2000,
                "VX_CFG_PLATFORM_MEMORY_PEAK_BW": 4000000,
                "VX_CFG_PLATFORM_MEMORY_TYPE": "HBM3",
                "VX_CFG_PLATFORM_MEMORY_NUM_BANKS": 64,
                "VX_CFG_PLATFORM_MEMORY_DATA_RATE": 3906,
            },
            "reference": {
                "fp32_lanes": 16384,
                "dram_bandwidth_gbs": 4000,
                "dram_peak_bytes_per_cycle": 2000,
                "clock_mhz": 2000,
                "num_cores": 128,
                "l2_size_mib": 128,
                "tcu_blocks_total": 512,
            },
            "sources": {
                "evidence_status": (
                    "PRE-SILICON TARGET ARCHITECTURE PROFILE ONLY: not measured physical silicon, "
                    "not FPGA hardware, and not foundry sign-off."
                ),
            },
        }
    if profile_name == "aigpu-b2-dual":
        return {
            "name": "aigpu-b2-dual",
            "description": (
                "Pre-silicon dual-die CoWoS-L/UCIe 2.0 unified AI-GPU B2 profile "
                "(256 cores, 64 MiB TMEM, 256 MiB unified L2, 8.0 TB/s HBM3E, 10 TB/s D2D)."
            ),
            "xlen": 64,
            "core": dict(base_core),
            "chip": {
                "VX_CFG_NUM_CLUSTERS": 16,
                "VX_CFG_NUM_CORES": 16,
                "VX_CFG_L2_ENABLE": True,
                "VX_CFG_L2_SIZE": 268435456,
                "VX_CFG_L2_NUM_WAYS": 16,
                "VX_CFG_L2_NUM_BANKS": 128,
                "VX_CFG_L2_MSHR_SIZE": 192,
            },
            "platform": {
                "VX_CFG_PLATFORM_CLOCK_RATE": 2000,
                "VX_CFG_PLATFORM_MEMORY_PEAK_BW": 8000000,
                "VX_CFG_PLATFORM_MEMORY_TYPE": "HBM3",
                "VX_CFG_PLATFORM_MEMORY_NUM_BANKS": 128,
                "VX_CFG_PLATFORM_MEMORY_DATA_RATE": 3906,
            },
            "reference": {
                "fp32_lanes": 32768,
                "dram_bandwidth_gbs": 8000,
                "dram_peak_bytes_per_cycle": 4000,
                "clock_mhz": 2000,
                "num_cores": 256,
                "l2_size_mib": 256,
                "tcu_blocks_total": 1024,
            },
            "sources": {
                "evidence_status": (
                    "PRE-SILICON TARGET ARCHITECTURE PROFILE ONLY: not measured physical silicon, "
                    "not FPGA hardware, and not foundry sign-off."
                ),
            },
        }
    if profile_name == "aigpu-b2-tile":
        return {
            "name": "aigpu-b2-tile",
            "description": (
                "Pre-silicon RTL-verifiable 4-core compute tile slice for aigpu-b2 "
                "(1 cluster x 4 RV64X cores, TFRv2/TMEM, 400 MHz RTL ref)."
            ),
            "xlen": 64,
            "core": {
                "VX_CFG_NUM_WARPS": 8,
                "VX_CFG_NUM_THREADS": 8,
                "VX_CFG_ISSUE_WIDTH": 2,
                "VX_CFG_LMEM_ENABLE": True,
                "VX_CFG_FPU_TYPE": "STD",
                "VX_CFG_EXT_TCU_ENABLE": True,
                "VX_CFG_TCU_TYPE": "TFR",
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
                "VX_CFG_EXT_MUFU_ENABLE": True,
                "VX_CFG_EXT_A_ENABLE": True,
                "VX_CFG_EXT_TEX_ENABLE": False,
                "VX_CFG_EXT_RASTER_ENABLE": False,
                "VX_CFG_EXT_OM_ENABLE": False,
                "VX_CFG_EXT_RTU_ENABLE": False,
            },
            "chip": {
                "VX_CFG_NUM_CLUSTERS": 1,
                "VX_CFG_NUM_CORES": 4,
                "VX_CFG_SOCKET_SIZE": 4,
                "VX_CFG_L2_ENABLE": True,
                "VX_CFG_L2_SIZE": 262144,
            },
            "reference": {
                "fp32_lanes": 64,
                "dram_bandwidth_gbs": 460,
                "dram_peak_bytes_per_cycle": 1150,
                "clock_mhz": 400,
                "num_cores": 4,
                "tcu_blocks_total": 8,
            },
            "sources": {
                "evidence_status": (
                    "PRE-SILICON RTL-VERIFIABLE COMPUTE TILE SLICE ONLY: not measured physical "
                    "silicon, not FPGA hardware, and not full-chip foundry sign-off."
                ),
            },
        }
    raise ValueError(f"No builtin B2 architectural fallback exists for {profile_name!r}")


@dataclass(frozen=True)
class ArchitectureOverrides:
    """Supplemental B2 architectural parameters beyond VX_config.toml defaults."""

    die_count: int
    tmem_bytes_per_core: int
    tmem_bw_bytes_per_cycle_per_core: int
    l1_lmem_bw_bytes_per_cycle_per_core: int
    l2_bw_bytes_per_cycle: int
    l3_bytes: int
    l3_bw_bytes_per_cycle: int
    ucie_d2d_bidir_gbs: float
    ucie_d2d_unidir_gbs: float
    ucie_latency_ns: float
    pcie_bidir_gbs: float
    pcie_gen: int
    pcie_lanes: int
    de_engine_max_gbs: float
    de_default_amplification: float
    has_tfrv2: bool
    has_de_engine: bool
    hbm_efficiency: float
    l2_arch_target_bytes: int | None = None


AIGPU_ARCH_SUPPLEMENTS: dict[str, ArchitectureOverrides] = {
    "aigpu-b2": ArchitectureOverrides(
        die_count=1,
        tmem_bytes_per_core=256 * BYTES_PER_KIB,
        tmem_bw_bytes_per_cycle_per_core=256,
        l1_lmem_bw_bytes_per_cycle_per_core=128,
        l2_bw_bytes_per_cycle=4096,
        l3_bytes=0,
        l3_bw_bytes_per_cycle=0,
        ucie_d2d_bidir_gbs=10000.0,
        ucie_d2d_unidir_gbs=5000.0,
        ucie_latency_ns=12.0,
        pcie_bidir_gbs=256.0,
        pcie_gen=6,
        pcie_lanes=16,
        de_engine_max_gbs=2400.0,
        de_default_amplification=1.45,
        has_tfrv2=True,
        has_de_engine=True,
        hbm_efficiency=0.88,
    ),
    "aigpu-b2-dual": ArchitectureOverrides(
        die_count=2,
        tmem_bytes_per_core=256 * BYTES_PER_KIB,
        tmem_bw_bytes_per_cycle_per_core=256,
        l1_lmem_bw_bytes_per_cycle_per_core=128,
        l2_bw_bytes_per_cycle=8192,
        l3_bytes=0,
        l3_bw_bytes_per_cycle=0,
        ucie_d2d_bidir_gbs=10000.0,
        ucie_d2d_unidir_gbs=5000.0,
        ucie_latency_ns=12.0,
        pcie_bidir_gbs=256.0,
        pcie_gen=6,
        pcie_lanes=16,
        de_engine_max_gbs=4800.0,
        de_default_amplification=1.45,
        has_tfrv2=True,
        has_de_engine=True,
        hbm_efficiency=0.88,
    ),
    "aigpu-b2-tile": ArchitectureOverrides(
        die_count=1,
        tmem_bytes_per_core=256 * BYTES_PER_KIB,
        tmem_bw_bytes_per_cycle_per_core=128,
        l1_lmem_bw_bytes_per_cycle_per_core=64,
        l2_bw_bytes_per_cycle=256,
        l3_bytes=0,
        l3_bw_bytes_per_cycle=0,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=64.0,
        pcie_gen=6,
        pcie_lanes=4,
        de_engine_max_gbs=200.0,
        de_default_amplification=1.35,
        has_tfrv2=True,
        has_de_engine=True,
        hbm_efficiency=0.85,
        l2_arch_target_bytes=int(1.5 * BYTES_PER_MIB),
    ),
    "aigpu-b1": ArchitectureOverrides(
        die_count=1,
        tmem_bytes_per_core=0,
        tmem_bw_bytes_per_cycle_per_core=128,
        l1_lmem_bw_bytes_per_cycle_per_core=128,
        l2_bw_bytes_per_cycle=4096,
        l3_bytes=0,
        l3_bw_bytes_per_cycle=0,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=128.0,
        pcie_gen=5,
        pcie_lanes=16,
        de_engine_max_gbs=0.0,
        de_default_amplification=1.0,
        has_tfrv2=False,
        has_de_engine=False,
        hbm_efficiency=0.85,
    ),
    "aigpu-b1-tile": ArchitectureOverrides(
        die_count=1,
        tmem_bytes_per_core=0,
        tmem_bw_bytes_per_cycle_per_core=64,
        l1_lmem_bw_bytes_per_cycle_per_core=64,
        l2_bw_bytes_per_cycle=256,
        l3_bytes=0,
        l3_bw_bytes_per_cycle=0,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=64.0,
        pcie_gen=5,
        pcie_lanes=16,
        de_engine_max_gbs=0.0,
        de_default_amplification=1.0,
        has_tfrv2=False,
        has_de_engine=False,
        hbm_efficiency=0.82,
    ),
}


@dataclass(frozen=True)
class CompetitorSpec:
    """Published vendor datasheet specification for competitive comparisons."""

    id: str
    display_name: str
    vendor: str
    architecture: str
    die_count: int
    cores_or_sms: int
    clock_mhz: float
    tmem_bytes: int
    tmem_bw_gbs: float
    l1_lmem_bytes: int
    l1_lmem_bw_gbs: float
    l2_bytes: int
    l2_bw_gbs: float
    l3_bytes: int
    l3_bw_gbs: float
    hbm_bytes: int
    hbm_bw_gbs: float
    hbm_efficiency: float
    ucie_d2d_bidir_gbs: float
    ucie_d2d_unidir_gbs: float
    ucie_latency_ns: float
    pcie_bidir_gbs: float
    pcie_gen: int
    has_de_engine: bool
    de_engine_max_gbs: float
    de_default_amplification: float
    dense_peaks: dict[str, float]
    sparse_2_4_peaks: dict[str, float]
    citation: str


COMPETITOR_BASELINES: dict[str, CompetitorSpec] = {
    "nvidia-b200-1die": CompetitorSpec(
        id="nvidia-b200-1die",
        display_name="NVIDIA B200 1-Die SXM (Published Ref)",
        vendor="NVIDIA",
        architecture="Blackwell GB100 (1 reticle die)",
        die_count=1,
        cores_or_sms=80,
        clock_mhz=1830.0,
        tmem_bytes=80 * 256 * BYTES_PER_KIB,
        tmem_bw_gbs=46000.0,
        l1_lmem_bytes=80 * 256 * BYTES_PER_KIB,
        l1_lmem_bw_gbs=23400.0,
        l2_bytes=63 * BYTES_PER_MIB,
        l2_bw_gbs=6500.0,
        l3_bytes=0,
        l3_bw_gbs=0.0,
        hbm_bytes=96 * 1024 * BYTES_PER_MIB,
        hbm_bw_gbs=4000.0,
        hbm_efficiency=0.88,
        ucie_d2d_bidir_gbs=10000.0,
        ucie_d2d_unidir_gbs=5000.0,
        ucie_latency_ns=15.0,
        pcie_bidir_gbs=256.0,
        pcie_gen=6,
        has_de_engine=True,
        de_engine_max_gbs=2400.0,
        de_default_amplification=1.45,
        dense_peaks={
            "tf32": 562.5,
            "fp16": 1125.0,
            "bf16": 1125.0,
            "fp8_e4m3": 2250.0,
            "fp8_e5m2": 2250.0,
            "mxfp8": 2250.0,
            "mxfp6_e2m3": 2250.0,
            "mxfp6_e3m2": 2250.0,
            "mxfp4": 4500.0,
            "nvfp4": 4500.0,
            "int8": 2250.0,
        },
        sparse_2_4_peaks={
            "tf32": 1125.0,
            "fp16": 2250.0,
            "bf16": 2250.0,
            "fp8_e4m3": 4500.0,
            "fp8_e5m2": 4500.0,
            "mxfp8": 4500.0,
            "mxfp6_e2m3": 4500.0,
            "mxfp6_e3m2": 4500.0,
            "mxfp4": 9000.0,
            "nvfp4": 9000.0,
            "int8": 4500.0,
        },
        citation=(
            "Published NVIDIA Blackwell B200 datasheet half-package baseline: "
            "1125 FP16 / 2250 FP8 / 4500 FP4 dense TFLOPS, 4.0 TB/s HBM3E, 10 TB/s NV-HBI."
        ),
    ),
    "nvidia-b200-2die": CompetitorSpec(
        id="nvidia-b200-2die",
        display_name="NVIDIA B200 2-Die SXM (Published Ref)",
        vendor="NVIDIA",
        architecture="Blackwell GB100 Dual-Die CoWoS-L",
        die_count=2,
        cores_or_sms=160,
        clock_mhz=1830.0,
        tmem_bytes=160 * 256 * BYTES_PER_KIB,
        tmem_bw_gbs=92000.0,
        l1_lmem_bytes=160 * 256 * BYTES_PER_KIB,
        l1_lmem_bw_gbs=46800.0,
        l2_bytes=126 * BYTES_PER_MIB,
        l2_bw_gbs=13000.0,
        l3_bytes=0,
        l3_bw_gbs=0.0,
        hbm_bytes=192 * 1024 * BYTES_PER_MIB,
        hbm_bw_gbs=8000.0,
        hbm_efficiency=0.88,
        ucie_d2d_bidir_gbs=10000.0,
        ucie_d2d_unidir_gbs=5000.0,
        ucie_latency_ns=18.0,
        pcie_bidir_gbs=256.0,
        pcie_gen=6,
        has_de_engine=True,
        de_engine_max_gbs=4800.0,
        de_default_amplification=1.45,
        dense_peaks={
            "tf32": 1125.0,
            "fp16": 2250.0,
            "bf16": 2250.0,
            "fp8_e4m3": 4500.0,
            "fp8_e5m2": 4500.0,
            "mxfp8": 4500.0,
            "mxfp6_e2m3": 4500.0,
            "mxfp6_e3m2": 4500.0,
            "mxfp4": 9000.0,
            "nvfp4": 9000.0,
            "int8": 4500.0,
        },
        sparse_2_4_peaks={
            "tf32": 2250.0,
            "fp16": 4500.0,
            "bf16": 4500.0,
            "fp8_e4m3": 9000.0,
            "fp8_e5m2": 9000.0,
            "mxfp8": 9000.0,
            "mxfp6_e2m3": 9000.0,
            "mxfp6_e3m2": 9000.0,
            "mxfp4": 18000.0,
            "nvfp4": 18000.0,
            "int8": 9000.0,
        },
        citation=(
            "Published NVIDIA Blackwell B200 SXM datasheet: "
            "2250 FP16 / 4500 FP8 / 9000 FP4 dense TFLOPS, 8.0 TB/s HBM3E, 10 TB/s NV-HBI."
        ),
    ),
    "nvidia-h200-sxm": CompetitorSpec(
        id="nvidia-h200-sxm",
        display_name="NVIDIA H200 SXM (Published Ref)",
        vendor="NVIDIA",
        architecture="Hopper GH100 + HBM3E",
        die_count=1,
        cores_or_sms=132,
        clock_mhz=1980.0,
        tmem_bytes=0,
        tmem_bw_gbs=33400.0,
        l1_lmem_bytes=132 * 256 * BYTES_PER_KIB,
        l1_lmem_bw_gbs=33400.0,
        l2_bytes=50 * BYTES_PER_MIB,
        l2_bw_gbs=12000.0,
        l3_bytes=0,
        l3_bw_gbs=0.0,
        hbm_bytes=141 * 1024 * BYTES_PER_MIB,
        hbm_bw_gbs=4800.0,
        hbm_efficiency=0.87,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=128.0,
        pcie_gen=5,
        has_de_engine=False,
        de_engine_max_gbs=0.0,
        de_default_amplification=1.0,
        dense_peaks={
            "tf32": 494.7,
            "fp16": 989.4,
            "bf16": 989.4,
            "fp8_e4m3": 1978.9,
            "fp8_e5m2": 1978.9,
            "int8": 1978.9,
        },
        sparse_2_4_peaks={
            "tf32": 989.4,
            "fp16": 1978.9,
            "bf16": 1978.9,
            "fp8_e4m3": 3957.8,
            "fp8_e5m2": 3957.8,
            "int8": 3957.8,
        },
        citation=(
            "Published NVIDIA H200 SXM datasheet: 132 SMs @ 1980 MHz, 4.8 TB/s HBM3E (141 GB), "
            "989.4 FP16 / 1978.9 FP8 dense TFLOPS (no FP4/MX)."
        ),
    ),
    "nvidia-h100-sxm5": CompetitorSpec(
        id="nvidia-h100-sxm5",
        display_name="NVIDIA H100 SXM5 (Published Ref)",
        vendor="NVIDIA",
        architecture="Hopper GH100 + HBM3",
        die_count=1,
        cores_or_sms=132,
        clock_mhz=1980.0,
        tmem_bytes=0,
        tmem_bw_gbs=33400.0,
        l1_lmem_bytes=132 * 256 * BYTES_PER_KIB,
        l1_lmem_bw_gbs=33400.0,
        l2_bytes=50 * BYTES_PER_MIB,
        l2_bw_gbs=12000.0,
        l3_bytes=0,
        l3_bw_gbs=0.0,
        hbm_bytes=80 * 1024 * BYTES_PER_MIB,
        hbm_bw_gbs=3350.0,
        hbm_efficiency=0.86,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=128.0,
        pcie_gen=5,
        has_de_engine=False,
        de_engine_max_gbs=0.0,
        de_default_amplification=1.0,
        dense_peaks={
            "tf32": 494.7,
            "fp16": 989.4,
            "bf16": 989.4,
            "fp8_e4m3": 1978.9,
            "fp8_e5m2": 1978.9,
            "int8": 1978.9,
        },
        sparse_2_4_peaks={
            "tf32": 989.4,
            "fp16": 1978.9,
            "bf16": 1978.9,
            "fp8_e4m3": 3957.8,
            "fp8_e5m2": 3957.8,
            "int8": 3957.8,
        },
        citation=(
            "Published NVIDIA H100 SXM5 datasheet: 132 SMs @ 1980 MHz, 3.35 TB/s HBM3 (80 GB), "
            "989.4 FP16 / 1978.9 FP8 dense TFLOPS."
        ),
    ),
    "amd-mi300x": CompetitorSpec(
        id="amd-mi300x",
        display_name="AMD Instinct MI300X (Published Ref)",
        vendor="AMD",
        architecture="CDNA 3 (8 XCDs + 4 IODs)",
        die_count=1,
        cores_or_sms=304,
        clock_mhz=2100.0,
        tmem_bytes=0,
        tmem_bw_gbs=40850.0,
        l1_lmem_bytes=304 * 96 * BYTES_PER_KIB,
        l1_lmem_bw_gbs=40850.0,
        l2_bytes=32 * BYTES_PER_MIB,
        l2_bw_gbs=17200.0,
        l3_bytes=256 * BYTES_PER_MIB,
        l3_bw_gbs=10000.0,
        hbm_bytes=192 * 1024 * BYTES_PER_MIB,
        hbm_bw_gbs=5300.0,
        hbm_efficiency=0.84,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=128.0,
        pcie_gen=5,
        has_de_engine=False,
        de_engine_max_gbs=0.0,
        de_default_amplification=1.0,
        dense_peaks={
            "tf32": 653.7,
            "fp16": 1307.4,
            "bf16": 1307.4,
            "fp8_e4m3": 2614.9,
            "fp8_e5m2": 2614.9,
            "int8": 2614.9,
        },
        sparse_2_4_peaks={
            "tf32": 1307.4,
            "fp16": 2614.9,
            "bf16": 2614.9,
            "fp8_e4m3": 5229.8,
            "fp8_e5m2": 5229.8,
            "int8": 5229.8,
        },
        citation=(
            "Published AMD MI300X CDNA3 datasheet: 304 CUs @ 2100 MHz, 256 MB Infinity Cache, "
            "5.3 TB/s HBM3 (192 GB), 1307.4 FP16 / 2614.9 FP8 dense TFLOPS."
        ),
    ),
    "nvidia-rtx5080": CompetitorSpec(
        id="nvidia-rtx5080",
        display_name="NVIDIA RTX 5080 (Published Ref)",
        vendor="NVIDIA",
        architecture="Blackwell GB203 (client)",
        die_count=1,
        cores_or_sms=84,
        clock_mhz=2617.0,
        tmem_bytes=0,
        tmem_bw_gbs=28100.0,
        l1_lmem_bytes=84 * 128 * BYTES_PER_KIB,
        l1_lmem_bw_gbs=28100.0,
        l2_bytes=64 * BYTES_PER_MIB,
        l2_bw_gbs=4400.0,
        l3_bytes=0,
        l3_bw_gbs=0.0,
        hbm_bytes=16 * 1024 * BYTES_PER_MIB,
        hbm_bw_gbs=960.0,
        hbm_efficiency=0.90,
        ucie_d2d_bidir_gbs=0.0,
        ucie_d2d_unidir_gbs=0.0,
        ucie_latency_ns=0.0,
        pcie_bidir_gbs=128.0,
        pcie_gen=5,
        has_de_engine=False,
        de_engine_max_gbs=0.0,
        de_default_amplification=1.0,
        dense_peaks={
            "tf32": 56.3,
            "fp16": 112.6,
            "bf16": 112.6,
            "fp8_e4m3": 450.2,
            "fp8_e5m2": 450.2,
            "mxfp8": 450.2,
            "mxfp6_e2m3": 450.2,
            "mxfp6_e3m2": 450.2,
            "mxfp4": 900.4,
            "nvfp4": 900.4,
            "int8": 450.2,
        },
        sparse_2_4_peaks={
            "tf32": 112.6,
            "fp16": 225.1,
            "bf16": 225.1,
            "fp8_e4m3": 900.4,
            "fp8_e5m2": 900.4,
            "mxfp8": 900.4,
            "mxfp6_e2m3": 900.4,
            "mxfp6_e3m2": 900.4,
            "mxfp4": 1800.8,
            "nvfp4": 1800.8,
            "int8": 900.4,
        },
        citation=(
            "Published NVIDIA RTX Blackwell GB203 App. B datasheet: 84 SMs @ 2617 MHz boost, "
            "960 GB/s GDDR7, 112.6 FP16 (FP32-acc) / 450.2 FP8 / 900.4 FP4 dense."
        ),
    ),
}


def validate_honesty_record(record: dict[str, Any]) -> None:
    """Reject any record that claims physical silicon, FPGA, or foundry sign-off."""
    if not isinstance(record, dict):
        raise ValueError("Roofline record must be a dictionary")
    if "schema_version" in record and record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Roofline record schema_version must be {SCHEMA_VERSION}, got {record.get('schema_version')!r}"
        )
    level = record.get("evidence_level")
    if level in FORBIDDEN_PHYSICAL_LEVELS:
        raise ValueError(
            f"Forbidden physical/non-analytical evidence_level {level!r}; "
            f"only {ALLOWED_EVIDENCE_LEVEL!r} is permitted"
        )
    if level != ALLOWED_EVIDENCE_LEVEL:
        raise ValueError(
            f"Roofline comparator only permits evidence_level={ALLOWED_EVIDENCE_LEVEL!r}, got {level!r}"
        )
    for flag in ("silicon_measured", "fpga_measured", "foundry_signoff"):
        if record.get(flag) is not False:
            raise ValueError(
                f"Roofline comparator must enforce {flag}=False; got {record.get(flag)!r}"
            )


def _assert_positive_finite(value: float, label: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{label} must be positive and finite, got {value!r}")


def _assert_non_negative_finite(value: float, label: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ValueError(f"{label} must be non-negative and finite, got {value!r}")


def _assert_positive_int(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer, got {value!r}")


def _load_gen_config() -> Any:
    spec = importlib.util.spec_from_file_location("aigpu_b2_gen_config", ROOT / "ci/gen_config.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load gen_config module from {ROOT / 'ci/gen_config.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_via_gen_config(
    profile_name: str,
    *,
    config_path: Path,
    profiles_dir: Path,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    gen_config = _load_gen_config()
    raw_path = profiles_dir / f"{profile_name}.json"
    raw_profile = json.loads(raw_path.read_text(encoding="utf-8"))

    toml_data = gen_config._load_toml(str(config_path))
    defaults, layout = gen_config._flatten_with_layout(toml_data)
    enums = gen_config._load_enums(toml_data)
    builtins = gen_config._load_var_table(toml_data, "builtin")
    params = gen_config._load_var_table(toml_data, "param")

    prof = gen_config.load_profile(profile_name, str(profiles_dir))
    gen_config.validate_profile(prof, defaults, enums, set(params.keys()) | set(builtins.keys()))

    xlen = prof.xlen if prof.xlen is not None else 64
    overrides = dict(prof.values)
    overrides["VX_CFG_XLEN"] = xlen
    overrides[f"VX_CFG_XLEN_{xlen}"] = True

    resolver = gen_config.Resolver(
        base=defaults,
        overrides=overrides,
        enums=enums,
        builtins=builtins,
        params=params,
    )
    resolved: dict[str, Any] = {}
    for key in layout.ordered_keys:
        resolved[key] = resolver.resolve(key)
    for key in enums:
        if key not in resolved:
            resolved[key] = resolver.resolve(key)
    return raw_profile, prof, resolved


def resolve_profile_config(
    profile_name: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    allow_builtin_fallback: bool = True,
) -> tuple[dict[str, Any], Any, dict[str, Any], str]:
    """Resolve an AI-GPU profile via ci/gen_config.py with optional B2 fallback."""
    profile_file = profiles_dir / f"{profile_name}.json"
    if profile_file.is_file():
        raw_profile, prof, resolved = _resolve_via_gen_config(
            profile_name, config_path=config_path, profiles_dir=profiles_dir
        )
        return raw_profile, prof, resolved, "profiles_dir"

    if allow_builtin_fallback and profile_name in AIGPU_B2_TARGETS:
        payload = _b2_authoritative_profile_payload(profile_name)
        with tempfile.TemporaryDirectory(prefix="b2-roofline-fallback-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / f"{profile_name}.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            raw_profile, prof, resolved = _resolve_via_gen_config(
                profile_name, config_path=config_path, profiles_dir=tmp_path
            )
        return raw_profile, prof, resolved, "authoritative_spec_fallback"

    raise FileNotFoundError(f"Missing profile JSON: {profile_file}")


def _vortex_tcu_block_shape(num_threads: int) -> tuple[int, int, int]:
    """Mirror hw/rtl/VX_gpu_pkg.sv MTX_TC_{M,N,K} derivation from NUM_THREADS."""
    if num_threads <= 0 or (num_threads & (num_threads - 1)) != 0:
        raise ValueError(f"VX_CFG_NUM_THREADS must be a positive power of two, got {num_threads}")
    lg_cap = num_threads.bit_length() - 1
    block_en = lg_cap // 2
    block_em = lg_cap - block_en
    tc_m = 1 << block_em
    tc_n = 1 << block_en
    tc_k = num_threads // max(tc_m, tc_n)
    return tc_m, tc_n, tc_k


def _format_supported(cfg: dict[str, Any], spec: FormatSpec, *, has_tfrv2: bool) -> bool:
    if not bool(cfg.get("VX_CFG_EXT_TCU_ENABLE", False)):
        return False
    if spec.tfrv2_only and not has_tfrv2:
        return False
    if not bool(cfg.get(spec.enable_key, False)):
        return False
    if spec.requires_mx and not bool(cfg.get("VX_CFG_TCU_MX_ENABLE", False)):
        return False
    if spec.requires_fp4 and not bool(cfg.get("VX_CFG_TCU_FP4_ENABLE", False)):
        return False
    return True


def _build_memory_hierarchy_dict(
    *,
    tmem_bytes: int,
    tmem_bw_gbs: float,
    l1_lmem_bytes: int,
    l1_lmem_bw_gbs: float,
    l2_bytes: int,
    l2_bw_gbs: float,
    l3_bytes: int,
    l3_bw_gbs: float,
    hbm_bytes: int,
    hbm_bw_gbs: float,
    hbm_efficiency: float,
    ucie_bidir_gbs: float,
    ucie_unidir_gbs: float,
    ucie_latency_ns: float,
    pcie_bidir_gbs: float,
    pcie_gen: int,
    pcie_lanes: int = 16,
    has_de_engine: bool,
    de_engine_max_gbs: float,
    de_default_amplification: float,
    die_count: int,
) -> dict[str, Any]:
    """Assemble standardized 6-level hierarchical memory/fabric description."""
    hbm_sustained_gbs = hbm_bw_gbs * hbm_efficiency
    de_effective_hbm_gbs = (
        min(hbm_bw_gbs * de_default_amplification, hbm_sustained_gbs + de_engine_max_gbs)
        if has_de_engine
        else hbm_sustained_gbs
    )
    return {
        "die_count": die_count,
        "levels": {
            "level1_tmem": {
                "name": "TMEM / Register Accumulator",
                "capacity_bytes": int(tmem_bytes),
                "capacity_mib": round(tmem_bytes / float(BYTES_PER_MIB), 4),
                "bandwidth_gbs": float(tmem_bw_gbs),
            },
            "level2_l1_lmem": {
                "name": "Shared LMEM / L1 Data Cache",
                "capacity_bytes": int(l1_lmem_bytes),
                "capacity_mib": round(l1_lmem_bytes / float(BYTES_PER_MIB), 4),
                "bandwidth_gbs": float(l1_lmem_bw_gbs),
            },
            "level3_l2_slc": {
                "name": "Coherent L2 / SLC (+ L3 if present)",
                "l2_capacity_bytes": int(l2_bytes),
                "l2_capacity_mib": round(l2_bytes / float(BYTES_PER_MIB), 4),
                "l2_bandwidth_gbs": float(l2_bw_gbs),
                "l3_capacity_bytes": int(l3_bytes),
                "l3_capacity_mib": round(l3_bytes / float(BYTES_PER_MIB), 4),
                "l3_bandwidth_gbs": float(l3_bw_gbs),
                "effective_llc_bytes": int(l3_bytes if l3_bytes > 0 else l2_bytes),
                "effective_llc_bandwidth_gbs": float(l3_bw_gbs if l3_bytes > 0 else l2_bw_gbs),
            },
            "level4_hbm": {
                "name": "HBM3E / GDDR External Memory",
                "capacity_bytes": int(hbm_bytes),
                "peak_bandwidth_gbs": float(hbm_bw_gbs),
                "sustained_efficiency": float(hbm_efficiency),
                "sustained_bandwidth_gbs": float(hbm_sustained_gbs),
            },
            "level5_ucie_d2d": {
                "name": "CoWoS-L UCIe 2.0 Coherent D2D Fabric",
                "enabled": bool(ucie_bidir_gbs > 0.0),
                "bidirectional_gbs": float(ucie_bidir_gbs),
                "unidirectional_gbs": float(ucie_unidir_gbs),
                "latency_ns": float(ucie_latency_ns),
            },
            "level6_pcie_de": {
                "name": f"PCIe Gen{pcie_gen} x{pcie_lanes} + Hardware Decompression Engine",
                "pcie_gen": int(pcie_gen),
                "pcie_lanes": int(pcie_lanes),
                "pcie_bidirectional_gbs": float(pcie_bidir_gbs),
                "pcie_unidirectional_gbs": float(pcie_bidir_gbs * 0.5),
                "has_de_engine": bool(has_de_engine),
                "de_engine_max_gbs": float(de_engine_max_gbs),
                "de_default_amplification": float(de_default_amplification),
                "de_effective_hbm_gbs": float(de_effective_hbm_gbs),
            },
        },
    }


def analyze_aigpu_profile(
    profile_name: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    allow_builtin_fallback: bool = True,
    clock_override_mhz: float | None = None,
    hbm_bw_override_gbs: float | None = None,
    sparsity_utilization: float = 1.0,
) -> dict[str, Any]:
    """Analyze an AI-GPU profile including TFR base vs TFRv2 and 6-tier hierarchy."""
    if not (0.0 <= sparsity_utilization <= 1.0):
        raise ValueError(f"sparsity_utilization must be in [0, 1], got {sparsity_utilization!r}")

    raw_profile, prof, cfg, profile_source = resolve_profile_config(
        profile_name,
        config_path=config_path,
        profiles_dir=profiles_dir,
        allow_builtin_fallback=allow_builtin_fallback,
    )
    supp = AIGPU_ARCH_SUPPLEMENTS.get(profile_name, AIGPU_ARCH_SUPPLEMENTS["aigpu-b1"])

    num_clusters = int(cfg["VX_CFG_NUM_CLUSTERS"])
    num_cores_per_cluster = int(cfg["VX_CFG_NUM_CORES"])
    total_cores = num_clusters * num_cores_per_cluster
    num_threads = int(cfg["VX_CFG_NUM_THREADS"])
    num_warps = int(cfg["VX_CFG_NUM_WARPS"])
    issue_width = int(cfg["VX_CFG_ISSUE_WIDTH"])
    clock_mhz = float(clock_override_mhz if clock_override_mhz is not None else cfg["VX_CFG_PLATFORM_CLOCK_RATE"])
    clock_ghz = clock_mhz / 1000.0
    bw_gbs = float(
        hbm_bw_override_gbs
        if hbm_bw_override_gbs is not None
        else float(cfg["VX_CFG_PLATFORM_MEMORY_PEAK_BW"]) / 1000.0
    )

    _assert_positive_finite(total_cores, f"{profile_name}.total_cores")
    _assert_positive_finite(clock_mhz, f"{profile_name}.clock_mhz")
    _assert_positive_finite(bw_gbs, f"{profile_name}.bandwidth_gbs")

    fpu_blocks = int(cfg["VX_CFG_NUM_FPU_BLOCKS"])
    fpu_lanes = int(cfg["VX_CFG_NUM_FPU_LANES"])
    fma_pe_ratio = int(cfg["VX_CFG_FMA_PE_RATIO"])
    fp32_lanes_total = total_cores * fpu_blocks * fpu_lanes
    fp32_fma_pes_total = fp32_lanes_total / float(fma_pe_ratio)
    fp32_tflops = (fp32_fma_pes_total * 2.0 * clock_ghz) / 1000.0

    tcu_enabled = bool(cfg.get("VX_CFG_EXT_TCU_ENABLE", False))
    tcu_blocks = int(cfg["VX_CFG_NUM_TCU_BLOCKS"])
    total_tcu_pipes = total_cores * tcu_blocks
    tcu_pe_ratio = int(cfg["VX_CFG_TCU_PE_RATIO"])
    fedp_2k = bool(cfg.get("VX_CFG_TCU_FEDP2K", False))
    sparse_enabled = bool(cfg.get("VX_CFG_TCU_SPARSE_ENABLE", False))
    wgmma_enabled = bool(cfg.get("VX_CFG_TCU_WGMMA_ENABLE", False))
    tc_m, tc_n, tc_k = _vortex_tcu_block_shape(num_threads)

    fedp_k = (2 * tc_k) if (fedp_2k and wgmma_enabled) else tc_k
    pes_per_block = (tc_m * tc_n) / float(tcu_pe_ratio)
    word32_fmas_per_chip_cycle = (
        float(total_tcu_pipes) * pes_per_block * float(fedp_k) if tcu_enabled else 0.0
    )

    l2_bytes = int(cfg["VX_CFG_L2_SIZE"]) if cfg.get("VX_CFG_L2_ENABLE", False) else 0
    dcache_bytes = int(cfg["VX_CFG_DCACHE_SIZE"]) if cfg.get("VX_CFG_DCACHE_ENABLE", False) else 0
    lmem_bytes = int(cfg["VX_CFG_LMEM_SIZE"]) if cfg.get("VX_CFG_LMEM_ENABLE", False) else 0
    tmem_bytes_total = total_cores * supp.tmem_bytes_per_core
    l1_lmem_bytes_total = total_cores * (dcache_bytes + lmem_bytes)

    tmem_bw_gbs = float(total_cores) * float(supp.tmem_bw_bytes_per_cycle_per_core) * clock_ghz
    l1_lmem_bw_gbs = float(total_cores) * float(supp.l1_lmem_bw_bytes_per_cycle_per_core) * clock_ghz
    l2_bw_gbs = float(supp.l2_bw_bytes_per_cycle) * clock_ghz
    l3_bw_gbs = float(supp.l3_bw_bytes_per_cycle) * clock_ghz

    hbm_bytes = (
        192 * 1024 * BYTES_PER_MIB
        if supp.die_count == 2
        else (96 * 1024 * BYTES_PER_MIB if "b2" in profile_name and "tile" not in profile_name else 64 * 1024 * BYTES_PER_MIB)
    )
    if "tile" in profile_name:
        hbm_bytes = 4 * 1024 * BYTES_PER_MIB

    hierarchy = _build_memory_hierarchy_dict(
        tmem_bytes=tmem_bytes_total,
        tmem_bw_gbs=tmem_bw_gbs,
        l1_lmem_bytes=l1_lmem_bytes_total,
        l1_lmem_bw_gbs=l1_lmem_bw_gbs,
        l2_bytes=supp.l2_arch_target_bytes if supp.l2_arch_target_bytes else l2_bytes,
        l2_bw_gbs=l2_bw_gbs,
        l3_bytes=supp.l3_bytes,
        l3_bw_gbs=l3_bw_gbs,
        hbm_bytes=hbm_bytes,
        hbm_bw_gbs=bw_gbs,
        hbm_efficiency=supp.hbm_efficiency,
        ucie_bidir_gbs=supp.ucie_d2d_bidir_gbs,
        ucie_unidir_gbs=supp.ucie_d2d_unidir_gbs,
        ucie_latency_ns=supp.ucie_latency_ns,
        pcie_bidir_gbs=supp.pcie_bidir_gbs,
        pcie_gen=supp.pcie_gen,
        pcie_lanes=supp.pcie_lanes,
        has_de_engine=supp.has_de_engine,
        de_engine_max_gbs=supp.de_engine_max_gbs,
        de_default_amplification=supp.de_default_amplification,
        die_count=supp.die_count,
    )

    formats: dict[str, Any] = {}
    for fmt_key, spec in FORMAT_SPECS.items():
        supported = _format_supported(cfg, spec, has_tfrv2=supp.has_tfrv2)
        if supported:
            base_dense = (
                (word32_fmas_per_chip_cycle * float(spec.elements_per_word32) * 2.0 * clock_ghz) / 1000.0
                if not spec.tfrv2_only
                else None
            )
            if supp.has_tfrv2:
                # TFRv2 wide 16x8x8 target: 1,125 FP16 FLOPs/cycle/pipe -> 2.25 TFLOPS/pipe @ 2.0 GHz
                tfrv2_fp16_dense = (
                    float(total_tcu_pipes) * TFRV2_TARGET_FP16_FLOPS_PER_PIPE_CYCLE * clock_ghz
                ) / 1000.0
                tfrv2_dense = tfrv2_fp16_dense * spec.tfrv2_multiplier_vs_fp16
                tfrv2_fp16_scaled_2ghz = (
                    float(total_tcu_pipes)
                    * TFRV2_TARGET_FP16_FLOPS_PER_PIPE_CYCLE
                    * (TFRV2_PIPE_SCALED_CLOCK_MHZ / 1000.0)
                ) / 1000.0
                tfrv2_scaled_2ghz_dense = tfrv2_fp16_scaled_2ghz * spec.tfrv2_multiplier_vs_fp16
                primary_dense = tfrv2_dense
            else:
                tfrv2_dense = None
                tfrv2_scaled_2ghz_dense = None
                primary_dense = base_dense

            primary_ridge_hbm = (primary_dense * 1000.0) / bw_gbs
            primary_ridge_l2 = (primary_dense * 1000.0) / l2_bw_gbs
            primary_ridge_tmem = (primary_dense * 1000.0) / tmem_bw_gbs

            if sparse_enabled:
                sparse_mult = 1.0 + sparsity_utilization
                primary_sparse = primary_dense * sparse_mult
                base_sparse = (base_dense * sparse_mult) if base_dense is not None else None
                tfrv2_sparse = (tfrv2_dense * sparse_mult) if tfrv2_dense is not None else None
                tfrv2_scaled_2ghz_sparse = (
                    tfrv2_scaled_2ghz_dense * sparse_mult
                    if tfrv2_scaled_2ghz_dense is not None
                    else None
                )
                primary_sparse_ridge_hbm = primary_ridge_hbm * sparse_mult
            else:
                primary_sparse = None
                base_sparse = None
                tfrv2_sparse = None
                tfrv2_scaled_2ghz_sparse = None
                primary_sparse_ridge_hbm = None
        else:
            base_dense = None
            base_sparse = None
            tfrv2_dense = None
            tfrv2_sparse = None
            tfrv2_scaled_2ghz_dense = None
            tfrv2_scaled_2ghz_sparse = None
            primary_dense = None
            primary_sparse = None
            primary_ridge_hbm = None
            primary_ridge_l2 = None
            primary_ridge_tmem = None
            primary_sparse_ridge_hbm = None

        formats[fmt_key] = {
            "label": spec.label,
            "unit": spec.unit,
            "supported": supported,
            "sparse_2_4_supported": bool(supported and sparse_enabled),
            "storage_bytes_per_element": spec.storage_bytes_per_element,
            "effective_bytes_per_element": spec.effective_bytes_per_element,
            "dense_peak": primary_dense,
            "sparse_2_4_peak": primary_sparse,
            "tfr_base_resolved_dense_peak": base_dense,
            "tfr_base_resolved_sparse_2_4_peak": base_sparse,
            "tfrv2_architectural_dense_peak": tfrv2_dense,
            "tfrv2_architectural_sparse_2_4_peak": tfrv2_sparse,
            "tfrv2_scaled_2ghz_dense_peak": tfrv2_scaled_2ghz_dense,
            "tfrv2_scaled_2ghz_sparse_2_4_peak": tfrv2_scaled_2ghz_sparse,
            "dense_ridge_hbm_flop_per_byte": primary_ridge_hbm,
            "dense_ridge_l2_flop_per_byte": primary_ridge_l2,
            "dense_ridge_tmem_flop_per_byte": primary_ridge_tmem,
            "sparse_2_4_ridge_hbm_flop_per_byte": primary_sparse_ridge_hbm,
        }

    graphics_disabled = (
        not bool(cfg.get("VX_CFG_EXT_TEX_ENABLE", False))
        and not bool(cfg.get("VX_CFG_EXT_RASTER_ENABLE", False))
        and not bool(cfg.get("VX_CFG_EXT_OM_ENABLE", False))
        and not bool(cfg.get("VX_CFG_EXT_RTU_ENABLE", False))
    )

    record = {
        "id": profile_name,
        "display_name": f"{profile_name} (Modeled Pre-Silicon)",
        "category": "aigpu_presilicon_target",
        "source": "vortex_profile_analytical_model",
        "profile_source": profile_source,
        "xlen": prof.xlen,
        "description": raw_profile.get("description", ""),
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "fpga_measured": False,
        "foundry_signoff": False,
        "is_published_reference": False,
        "locally_measured": False,
        "phase_status_effect": "none",
        "topology": {
            "die_count": supp.die_count,
            "num_clusters": num_clusters,
            "cores_per_cluster": num_cores_per_cluster,
            "total_cores": total_cores,
            "total_tcu_pipes": total_tcu_pipes,
            "socket_size": int(cfg["VX_CFG_SOCKET_SIZE"]),
            "warps_per_core": num_warps,
            "threads_per_warp": num_threads,
            "issue_width": issue_width,
            "l2_bytes_config": l2_bytes,
            "tmem_bytes_total": tmem_bytes_total,
            "lmem_bytes_per_core": lmem_bytes,
            "dcache_bytes_per_core": dcache_bytes,
            "graphics_disabled": graphics_disabled,
        },
        "tcu_architecture": {
            "enabled": tcu_enabled,
            "tcu_type": cfg["VX_CFG_TCU_TYPE"],
            "has_tfrv2": supp.has_tfrv2,
            "tfrv2_reconciliation_note": (
                "Reconciles Vortex base resolved TFR (power-of-two TC_M*TC_N*FEDP_K) "
                "with TFRv2 wide 16x8x8 architectural target (1,125 FP16 FLOPs/cycle/pipe)."
            ),
            "blocks_per_core": tcu_blocks,
            "pe_ratio": tcu_pe_ratio,
            "tc_m": tc_m,
            "tc_n": tc_n,
            "tc_k": tc_k,
            "fedp_k_words": fedp_k,
            "wgmma_enabled": wgmma_enabled,
            "sparse_enabled": sparse_enabled,
            "sparsity_utilization": sparsity_utilization,
            "mx_enabled": bool(cfg.get("VX_CFG_TCU_MX_ENABLE", False)),
            "fp4_enabled": bool(cfg.get("VX_CFG_TCU_FP4_ENABLE", False)),
            "dxa_enabled": bool(cfg.get("VX_CFG_EXT_DXA_ENABLE", False)),
        },
        "memory": {
            "clock_mhz": clock_mhz,
            "memory_type": cfg["VX_CFG_PLATFORM_MEMORY_TYPE"],
            "memory_banks": int(cfg["VX_CFG_PLATFORM_MEMORY_NUM_BANKS"]),
            "bandwidth_gbs": bw_gbs,
            "sustained_bandwidth_gbs": bw_gbs * supp.hbm_efficiency,
            "bytes_per_clock": (bw_gbs * 1000.0) / clock_mhz,
        },
        "hierarchy": hierarchy,
        "scalar_fp32": {
            "fp32_lanes_total": fp32_lanes_total,
            "dense_tflops": fp32_tflops,
            "ridge_hbm_flop_per_byte": (fp32_tflops * 1000.0) / bw_gbs,
        },
        "tensor_formats": formats,
    }
    validate_honesty_record(record)
    return record


def analyze_competitor_baseline(
    comp_id: str,
    *,
    sparsity_utilization: float = 1.0,
) -> dict[str, Any]:
    """Build analytical hierarchical roofline record for a published vendor baseline."""
    if comp_id not in COMPETITOR_BASELINES:
        raise ValueError(f"Unknown competitor baseline {comp_id!r}")
    if not (0.0 <= sparsity_utilization <= 1.0):
        raise ValueError(f"sparsity_utilization must be in [0, 1], got {sparsity_utilization!r}")

    spec = COMPETITOR_BASELINES[comp_id]
    hierarchy = _build_memory_hierarchy_dict(
        tmem_bytes=spec.tmem_bytes,
        tmem_bw_gbs=spec.tmem_bw_gbs,
        l1_lmem_bytes=spec.l1_lmem_bytes,
        l1_lmem_bw_gbs=spec.l1_lmem_bw_gbs,
        l2_bytes=spec.l2_bytes,
        l2_bw_gbs=spec.l2_bw_gbs,
        l3_bytes=spec.l3_bytes,
        l3_bw_gbs=spec.l3_bw_gbs,
        hbm_bytes=spec.hbm_bytes,
        hbm_bw_gbs=spec.hbm_bw_gbs,
        hbm_efficiency=spec.hbm_efficiency,
        ucie_bidir_gbs=spec.ucie_d2d_bidir_gbs,
        ucie_unidir_gbs=spec.ucie_d2d_unidir_gbs,
        ucie_latency_ns=spec.ucie_latency_ns,
        pcie_bidir_gbs=spec.pcie_bidir_gbs,
        pcie_gen=spec.pcie_gen,
        has_de_engine=spec.has_de_engine,
        de_engine_max_gbs=spec.de_engine_max_gbs,
        de_default_amplification=spec.de_default_amplification,
        die_count=spec.die_count,
    )

    formats: dict[str, Any] = {}
    for fmt_key, fspec in FORMAT_SPECS.items():
        dense = spec.dense_peaks.get(fmt_key)
        raw_sparse = spec.sparse_2_4_peaks.get(fmt_key)
        supported = dense is not None
        if supported:
            assert dense is not None
            sparse_val = (
                dense + (raw_sparse - dense) * sparsity_utilization
                if raw_sparse is not None
                else None
            )
            ridge_hbm = (dense * 1000.0) / spec.hbm_bw_gbs
            ridge_l2 = (dense * 1000.0) / spec.l2_bw_gbs
            ridge_tmem = (dense * 1000.0) / spec.tmem_bw_gbs
            sparse_ridge_hbm = ((sparse_val * 1000.0) / spec.hbm_bw_gbs) if sparse_val is not None else None
        else:
            sparse_val = None
            ridge_hbm = None
            ridge_l2 = None
            ridge_tmem = None
            sparse_ridge_hbm = None

        formats[fmt_key] = {
            "label": fspec.label,
            "unit": fspec.unit,
            "supported": supported,
            "sparse_2_4_supported": sparse_val is not None,
            "storage_bytes_per_element": fspec.storage_bytes_per_element,
            "effective_bytes_per_element": fspec.effective_bytes_per_element,
            "dense_peak": dense,
            "sparse_2_4_peak": sparse_val,
            "dense_ridge_hbm_flop_per_byte": ridge_hbm,
            "dense_ridge_l2_flop_per_byte": ridge_l2,
            "dense_ridge_tmem_flop_per_byte": ridge_tmem,
            "sparse_2_4_ridge_hbm_flop_per_byte": sparse_ridge_hbm,
        }

    record = {
        "id": spec.id,
        "display_name": spec.display_name,
        "category": "published_vendor_competitor_baseline",
        "source": "published_vendor_datasheet",
        "vendor": spec.vendor,
        "architecture": spec.architecture,
        "description": spec.citation,
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "fpga_measured": False,
        "foundry_signoff": False,
        "is_published_reference": True,
        "locally_measured": False,
        "phase_status_effect": "none",
        "topology": {
            "die_count": spec.die_count,
            "total_cores": spec.cores_or_sms,
            "tmem_bytes_total": spec.tmem_bytes,
            "l2_bytes_config": spec.l2_bytes,
            "l3_bytes_config": spec.l3_bytes,
        },
        "memory": {
            "clock_mhz": spec.clock_mhz,
            "bandwidth_gbs": spec.hbm_bw_gbs,
            "sustained_bandwidth_gbs": spec.hbm_bw_gbs * spec.hbm_efficiency,
            "bytes_per_clock": (spec.hbm_bw_gbs * 1000.0) / spec.clock_mhz,
        },
        "hierarchy": hierarchy,
        "tensor_formats": formats,
    }
    validate_honesty_record(record)
    return record


@dataclass(frozen=True)
class HierarchicalTraffic:
    """Operation and multi-tier byte traffic demand for a modeled kernel/workload."""

    flops: float
    tmem_bytes: float
    l1_lmem_bytes: float
    l2_slc_bytes: float
    hbm_bytes: float
    ucie_d2d_bytes: float = 0.0
    pcie_host_bytes: float = 0.0
    compressed_weight_bytes: float = 0.0
    de_amplification: float = 1.0
    sync_barriers: int = 2


EXPOSED_UCIE_D2D_FRACTION = 0.25


def evaluate_hierarchical_roofline(
    target: dict[str, Any],
    fmt_key: str,
    traffic: HierarchicalTraffic,
    *,
    use_sparse: bool = False,
    use_de_compression: bool = True,
    use_sustained_hbm: bool = True,
) -> dict[str, Any]:
    """Compute multi-level hierarchical roofline ceiling and bottleneck attribution."""
    _assert_positive_finite(traffic.flops, "traffic.flops")
    _assert_non_negative_finite(traffic.tmem_bytes, "traffic.tmem_bytes")
    _assert_non_negative_finite(traffic.l1_lmem_bytes, "traffic.l1_lmem_bytes")
    _assert_non_negative_finite(traffic.l2_slc_bytes, "traffic.l2_slc_bytes")
    _assert_non_negative_finite(traffic.hbm_bytes, "traffic.hbm_bytes")
    _assert_non_negative_finite(traffic.ucie_d2d_bytes, "traffic.ucie_d2d_bytes")
    _assert_non_negative_finite(traffic.pcie_host_bytes, "traffic.pcie_host_bytes")
    _assert_non_negative_finite(traffic.compressed_weight_bytes, "traffic.compressed_weight_bytes")
    _assert_positive_finite(traffic.de_amplification, "traffic.de_amplification")
    if isinstance(traffic.sync_barriers, bool) or not isinstance(traffic.sync_barriers, int) or traffic.sync_barriers < 0:
        raise ValueError(f"traffic.sync_barriers must be a non-negative integer, got {traffic.sync_barriers!r}")

    fmt_entry = target["tensor_formats"][fmt_key]
    if not fmt_entry["supported"]:
        return {
            "supported": False,
            "limiting_level": "unsupported",
            "attained_tflops_or_tops": None,
            "compute_ceiling_tflops_or_tops": None,
            "tier_ceilings_tflops_or_tops": {},
            "effective_hbm_ai": 0.0,
        }

    compute_peak = (
        fmt_entry["sparse_2_4_peak"]
        if (use_sparse and fmt_entry["sparse_2_4_supported"])
        else fmt_entry["dense_peak"]
    )
    assert compute_peak is not None

    levels = target["hierarchy"]["levels"]
    tmem_bw = levels["level1_tmem"]["bandwidth_gbs"]
    l1_bw = levels["level2_l1_lmem"]["bandwidth_gbs"]
    l2_bw = levels["level3_l2_slc"]["effective_llc_bandwidth_gbs"]
    hbm_raw_bw = (
        levels["level4_hbm"]["sustained_bandwidth_gbs"]
        if use_sustained_hbm
        else levels["level4_hbm"]["peak_bandwidth_gbs"]
    )
    de_info = levels["level6_pcie_de"]
    de_engine_max_gbs = float(de_info["de_engine_max_gbs"])
    if (
        use_de_compression
        and de_info["has_de_engine"]
        and de_engine_max_gbs > 0.0
        and traffic.compressed_weight_bytes > 0.0
    ):
        amp = min(de_info["de_default_amplification"], max(1.0, traffic.de_amplification))
        saved_bytes = traffic.compressed_weight_bytes * (1.0 - (1.0 / amp))
        # DE expands the saved virtual HBM weight bytes alongside HBM channels;
        # bound by de_engine_max_gbs on the decompressed byte stream.
        effective_hbm_bytes = max(1.0, traffic.hbm_bytes - saved_bytes)
        de_time_s = saved_bytes / (de_engine_max_gbs * 1e9)
        de_ceiling_tflops = (traffic.flops / (de_time_s * 1e12)) if de_time_s > 0.0 else float("inf")
    else:
        effective_hbm_bytes = traffic.hbm_bytes
        de_time_s = 0.0
        de_ceiling_tflops = None

    ucie_info = levels["level5_ucie_d2d"]
    ucie_bw = ucie_info["bidirectional_gbs"] if ucie_info["enabled"] else 0.0
    pcie_bw = de_info["pcie_bidirectional_gbs"]
    die_count = int(target.get("topology", {}).get("die_count", target["hierarchy"].get("die_count", 1)))

    tier_times_s = {
        "compute": (traffic.flops / (float(compute_peak) * 1e12)),
        "level1_tmem": (traffic.tmem_bytes / (tmem_bw * 1e9)) if (traffic.tmem_bytes > 0 and tmem_bw > 0) else 0.0,
        "level2_l1_lmem": (traffic.l1_lmem_bytes / (l1_bw * 1e9)) if (traffic.l1_lmem_bytes > 0 and l1_bw > 0) else 0.0,
        "level3_l2_slc": (traffic.l2_slc_bytes / (l2_bw * 1e9)) if (traffic.l2_slc_bytes > 0 and l2_bw > 0) else 0.0,
        "level4_hbm": (effective_hbm_bytes / (hbm_raw_bw * 1e9)) if (effective_hbm_bytes > 0 and hbm_raw_bw > 0) else 0.0,
        "level5_ucie_d2d": (
            (traffic.ucie_d2d_bytes / (ucie_bw * 1e9)) + (ucie_info["latency_ns"] * 1e-9)
            if (traffic.ucie_d2d_bytes > 0 and ucie_bw > 0)
            else (float("inf") if traffic.ucie_d2d_bytes > 0 else 0.0)
        ),
        "level6_pcie_host": (
            (traffic.pcie_host_bytes / (pcie_bw * 1e9))
            if (traffic.pcie_host_bytes > 0 and pcie_bw > 0)
            else (float("inf") if traffic.pcie_host_bytes > 0 else 0.0)
        ),
    }
    if de_time_s > 0.0:
        tier_times_s["level6_de_engine"] = de_time_s

    tier_ceilings: dict[str, float] = {
        k: ((traffic.flops / (t * 1e12)) if (t > 0.0 and math.isfinite(t)) else (0.0 if not math.isfinite(t) else float("inf")))
        for k, t in tier_times_s.items()
    }
    limiting_level = min(tier_ceilings, key=lambda k: tier_ceilings[k])
    max_tier_time_s = tier_times_s[limiting_level]

    # Non-overlapped cross-die UCIe D2D serialization & collective barrier overhead:
    # dual-die collectives/snoop barriers cannot be 100% hidden behind HBM/compute.
    ucie_time_s = tier_times_s["level5_ucie_d2d"]
    if traffic.ucie_d2d_bytes > 0.0 and die_count > 1 and math.isfinite(ucie_time_s):
        sync_latency_s = float(max(2, traffic.sync_barriers)) * float(ucie_info["latency_ns"]) * 1e-9
        exposed_ucie_s = (EXPOSED_UCIE_D2D_FRACTION * ucie_time_s) + sync_latency_s
        local_tiers = [t for k, t in tier_times_s.items() if k != "level5_ucie_d2d"]
        local_max_s = max(local_tiers) if local_tiers else 0.0
        total_step_time_s = max(local_max_s + exposed_ucie_s, ucie_time_s)
    else:
        exposed_ucie_s = 0.0
        total_step_time_s = max_tier_time_s

    attained = (
        (traffic.flops / (total_step_time_s * 1e12))
        if (total_step_time_s > 0.0 and math.isfinite(total_step_time_s))
        else 0.0
    )

    return {
        "supported": True,
        "limiting_level": limiting_level,
        "attained_tflops_or_tops": attained,
        "compute_ceiling_tflops_or_tops": float(compute_peak),
        "de_ceiling_tflops_or_tops": (
            round(de_ceiling_tflops, 4) if (de_ceiling_tflops is not None and math.isfinite(de_ceiling_tflops)) else None
        ),
        "exposed_ucie_overhead_ms": exposed_ucie_s * 1000.0,
        "tier_ceilings_tflops_or_tops": {
            k: (round(v, 4) if math.isfinite(v) else None) for k, v in tier_ceilings.items()
        },
        "effective_hbm_ai": traffic.flops / max(1.0, effective_hbm_bytes),
        "raw_hbm_ai": traffic.flops / max(1.0, traffic.hbm_bytes),
        "min_execution_time_ms": total_step_time_s * 1000.0,
    }


@dataclass(frozen=True)
class GemmTileSpec:
    """CTA tile geometry and double-buffering parameters for GEMM efficiency."""

    tile_m: int
    tile_n: int
    tile_k: int
    stages: int = 3
    cta_cluster_m: int = 2


DEFAULT_GEMM_TILES: tuple[GemmTileSpec, ...] = (
    GemmTileSpec(tile_m=128, tile_n=256, tile_k=64, stages=3, cta_cluster_m=2),
    GemmTileSpec(tile_m=128, tile_n=128, tile_k=64, stages=4, cta_cluster_m=2),
    GemmTileSpec(tile_m=64, tile_n=128, tile_k=64, stages=3, cta_cluster_m=1),
    GemmTileSpec(tile_m=64, tile_n=64, tile_k=32, stages=2, cta_cluster_m=1),
)


def evaluate_gemm_wave_quantization(
    target: dict[str, Any],
    *,
    m_dim: int,
    n_dim: int,
    k_dim: int,
    fmt_key: str,
    tile: GemmTileSpec | None = None,
    use_sparse: bool = False,
) -> dict[str, Any]:
    """Model CTA grid wave quantization, TMEM double-buffering overlap, and tile efficiency."""
    _assert_positive_int(m_dim, "m_dim")
    _assert_positive_int(n_dim, "n_dim")
    _assert_positive_int(k_dim, "k_dim")
    fmt_key = canonical_format_key(fmt_key)
    spec = FORMAT_SPECS[fmt_key]
    fmt_entry = target["tensor_formats"][fmt_key]
    if not fmt_entry["supported"]:
        return {"supported": False, "attained_tflops_or_tops": None}

    total_cores = int(target["topology"]["total_cores"])
    elem_bytes = spec.effective_bytes_per_element
    tmem_per_core = (
        int(target["topology"].get("tmem_bytes_total", 0)) // max(1, total_cores)
        if target["topology"].get("tmem_bytes_total", 0) > 0
        else 131072
    )
    lmem_per_core = int(target["topology"].get("lmem_bytes_per_core", 131072))

    candidates = (tile,) if tile is not None else DEFAULT_GEMM_TILES
    for cand in candidates:
        _assert_positive_int(cand.tile_m, "tile.tile_m")
        _assert_positive_int(cand.tile_n, "tile.tile_n")
        _assert_positive_int(cand.tile_k, "tile.tile_k")
        _assert_positive_int(cand.stages, "tile.stages")
        _assert_positive_int(cand.cta_cluster_m, "tile.cta_cluster_m")
    best_eval: dict[str, Any] | None = None

    for cand in candidates:
        # Check whether tile fits in TMEM (FP32 accumulators) and LMEM (staged A+B operands)
        accum_bytes = cand.tile_m * cand.tile_n * 4
        smem_bytes = int((cand.tile_m * cand.tile_k + cand.tile_k * cand.tile_n) * elem_bytes * cand.stages)
        if accum_bytes > max(65536, tmem_per_core) or smem_bytes > max(65536, lmem_per_core * 2):
            max_ctas_per_core = 1
            fit_penalty = 0.72
        else:
            max_ctas_per_core = max(
                1,
                min(4, tmem_per_core // max(1, accum_bytes), max(1, (lmem_per_core * 2) // max(1, smem_bytes))),
            )
            fit_penalty = 1.0

        grid_m = math.ceil(m_dim / cand.tile_m)
        grid_n = math.ceil(n_dim / cand.tile_n)
        total_ctas = grid_m * grid_n
        concurrent_slots = total_cores * max_ctas_per_core
        waves = math.ceil(total_ctas / concurrent_slots)
        wave_quant_eff = float(total_ctas) / float(waves * concurrent_slots)

        # Edge padding waste inside partially filled boundary tiles
        useful_elements = float(m_dim * n_dim)
        padded_elements = float(grid_m * cand.tile_m * grid_n * cand.tile_n)
        tile_padding_eff = useful_elements / padded_elements

        # TMEM/DXA double-buffering overlap across K-loop iterations
        k_iters = math.ceil(k_dim / cand.tile_k)
        # Prologue + epilogue stall is amortized across k_iters; TMEM hides accumulator drain
        has_tmem = int(target["topology"].get("tmem_bytes_total", 0)) > 0
        prologue_iters = 0.85 if has_tmem else 1.35
        tmem_overlap_eff = float(k_iters) / (float(k_iters) + prologue_iters)

        # Multicast / L2 reuse amplification across CTA cluster
        l2_reuse_factor = float(min(grid_m, cand.cta_cluster_m) * min(grid_n, 4))
        flops = 2.0 * float(m_dim) * float(n_dim) * float(k_dim)
        hbm_bytes = (
            float(m_dim) * float(k_dim) * elem_bytes
            + float(k_dim) * float(n_dim) * elem_bytes
            + float(m_dim) * float(n_dim) * 2.0
        )
        # Dual-die remote L2 / cross-die split traffic & partial-sum sync for large GEMM
        die_count = int(target["topology"].get("die_count", 1))
        ucie_bytes = hbm_bytes * (0.35 if die_count > 1 else 0.0)
        traffic = HierarchicalTraffic(
            flops=flops,
            tmem_bytes=flops * (4.0 / max(16.0, float(cand.tile_k))),
            l1_lmem_bytes=hbm_bytes * 2.5,
            l2_slc_bytes=hbm_bytes * max(1.0, 2.0 / math.sqrt(l2_reuse_factor)),
            hbm_bytes=hbm_bytes,
            ucie_d2d_bytes=ucie_bytes,
            compressed_weight_bytes=float(k_dim) * float(n_dim) * elem_bytes,
            de_amplification=1.40 if elem_bytes <= 1.0 else 1.0,
            sync_barriers=max(2, k_iters // 16) if die_count > 1 else 0,
        )
        roof = evaluate_hierarchical_roofline(target, fmt_key, traffic, use_sparse=use_sparse)
        combined_tile_eff = wave_quant_eff * tile_padding_eff * tmem_overlap_eff * fit_penalty
        attained = float(roof["attained_tflops_or_tops"]) * combined_tile_eff

        result = {
            "supported": True,
            "tile": f"{cand.tile_m}x{cand.tile_n}x{cand.tile_k}_s{cand.stages}",
            "total_ctas": total_ctas,
            "concurrent_cta_slots": concurrent_slots,
            "waves": waves,
            "wave_quantization_efficiency": round(wave_quant_eff, 6),
            "tile_padding_efficiency": round(tile_padding_eff, 6),
            "tmem_overlap_efficiency": round(tmem_overlap_eff, 6),
            "combined_tile_efficiency": round(combined_tile_eff, 6),
            "roofline_ceiling_tflops_or_tops": roof["attained_tflops_or_tops"],
            "attained_tflops_or_tops": attained,
            "limiting_level": roof["limiting_level"],
        }
        if best_eval is None or result["attained_tflops_or_tops"] > best_eval["attained_tflops_or_tops"]:
            best_eval = result

    assert best_eval is not None
    return best_eval


@dataclass(frozen=True)
class WorkloadSpec:
    """Analytical LLM model specification (Llama-3 dense or DeepSeek-V3 MoE)."""

    id: str
    family: str
    num_layers: int
    hidden_size: int
    intermediate_size: int
    num_q_heads: int
    num_kv_heads: int
    head_dim: int
    vocab_size: int
    # MoE / MLA fields (0/None for standard GQA dense transformers)
    is_moe: bool = False
    moe_layers: int = 0
    moe_intermediate_size: int = 0
    num_routed_experts: int = 0
    top_k_experts: int = 0
    num_shared_experts: int = 0
    kv_lora_rank: int = 0
    q_lora_rank: int = 0
    qk_rope_head_dim: int = 0
    qk_nope_head_dim: int = 0
    v_head_dim: int = 0

    @property
    def total_params_billions(self) -> float:
        if not self.is_moe:
            attn_p = self.num_layers * (
                2 * self.hidden_size * self.num_q_heads * self.head_dim
                + 2 * self.hidden_size * self.num_kv_heads * self.head_dim
            )
            mlp_p = self.num_layers * (3 * self.hidden_size * self.intermediate_size)
            emb_p = 2 * self.vocab_size * self.hidden_size
            return (attn_p + mlp_p + emb_p) / 1e9
        dense_layers = self.num_layers - self.moe_layers
        # Approximate MLA + dense + routed + shared params
        attn_per_layer = (
            self.hidden_size * (self.q_lora_rank + self.kv_lora_rank + self.qk_rope_head_dim)
            + self.q_lora_rank * self.num_q_heads * (self.qk_nope_head_dim + self.qk_rope_head_dim)
            + self.kv_lora_rank * self.num_q_heads * (self.qk_nope_head_dim + self.v_head_dim)
            + self.num_q_heads * self.v_head_dim * self.hidden_size
        )
        dense_mlp = dense_layers * (3 * self.hidden_size * self.intermediate_size)
        routed_mlp = (
            self.moe_layers * self.num_routed_experts * (3 * self.hidden_size * self.moe_intermediate_size)
        )
        shared_mlp = (
            self.moe_layers * self.num_shared_experts * (3 * self.hidden_size * self.moe_intermediate_size)
        )
        emb_p = 2 * self.vocab_size * self.hidden_size
        return (self.num_layers * attn_per_layer + dense_mlp + routed_mlp + shared_mlp + emb_p) / 1e9


LLM_WORKLOADS: dict[str, WorkloadSpec] = {
    "llama3-8b": WorkloadSpec(
        id="llama3-8b",
        family="llama3",
        num_layers=32,
        hidden_size=4096,
        intermediate_size=14336,
        num_q_heads=32,
        num_kv_heads=8,
        head_dim=128,
        vocab_size=128256,
    ),
    "llama3-70b": WorkloadSpec(
        id="llama3-70b",
        family="llama3",
        num_layers=80,
        hidden_size=8192,
        intermediate_size=28672,
        num_q_heads=64,
        num_kv_heads=8,
        head_dim=128,
        vocab_size=128256,
    ),
    "llama3-405b": WorkloadSpec(
        id="llama3-405b",
        family="llama3",
        num_layers=126,
        hidden_size=16384,
        intermediate_size=53248,
        num_q_heads=128,
        num_kv_heads=8,
        head_dim=128,
        vocab_size=128256,
    ),
    "deepseek-v3": WorkloadSpec(
        id="deepseek-v3",
        family="deepseek_moe",
        num_layers=61,
        hidden_size=7168,
        intermediate_size=18432,
        num_q_heads=128,
        num_kv_heads=128,
        head_dim=128,
        vocab_size=129280,
        is_moe=True,
        moe_layers=58,
        moe_intermediate_size=2048,
        num_routed_experts=256,
        top_k_experts=8,
        num_shared_experts=1,
        kv_lora_rank=512,
        q_lora_rank=1536,
        qk_rope_head_dim=64,
        qk_nope_head_dim=128,
        v_head_dim=128,
    ),
}

PREFILL_SEQ_LENGTHS: tuple[int, ...] = (1024, 4096, 16384, 32768)
DECODE_BATCH_SIZES: tuple[int, ...] = (1, 8, 32, 128, 256)
DEFAULT_DECODE_CONTEXT_LEN = 4096


def compute_workload_traffic(
    workload: WorkloadSpec,
    *,
    regime: str,
    tokens_or_batch: int,
    fmt_key: str,
    kv_format_key: str = "fp8_e4m3",
    die_count: int = 1,
    remote_die_split_ratio: float = 0.5,
    l2_capacity_bytes: int = 134217728,
    decode_context_len: int = DEFAULT_DECODE_CONTEXT_LEN,
) -> dict[str, Any]:
    """Compute analytical FLOPs, KV-cache footprint, and multi-tier byte traffic."""
    if regime not in ("prefill", "decode"):
        raise ValueError(f"regime must be 'prefill' or 'decode', got {regime!r}")
    _assert_positive_int(tokens_or_batch, "tokens_or_batch")
    _assert_positive_int(decode_context_len, "decode_context_len")
    _assert_positive_int(die_count, "die_count")
    if (
        not isinstance(remote_die_split_ratio, (int, float))
        or isinstance(remote_die_split_ratio, bool)
        or not math.isfinite(float(remote_die_split_ratio))
        or not (0.0 <= float(remote_die_split_ratio) <= 1.0)
    ):
        raise ValueError(
            f"remote_die_split_ratio must be finite and in [0.0, 1.0], got {remote_die_split_ratio!r}"
        )
    if (
        isinstance(l2_capacity_bytes, bool)
        or not isinstance(l2_capacity_bytes, int)
        or l2_capacity_bytes < 0
    ):
        raise ValueError(f"l2_capacity_bytes must be a non-negative integer, got {l2_capacity_bytes!r}")

    w_bytes = FORMAT_SPECS[canonical_format_key(fmt_key)].effective_bytes_per_element
    kv_bytes = FORMAT_SPECS[canonical_format_key(kv_format_key)].effective_bytes_per_element
    act_bytes = max(1.0, min(2.0, w_bytes)) if w_bytes >= 1.0 else w_bytes

    if regime == "prefill":
        batch_size = 1
        seq_len = tokens_or_batch
        tokens_processed = seq_len
        kv_seq_len = seq_len
    else:
        batch_size = tokens_or_batch
        seq_len = 1
        tokens_processed = batch_size
        kv_seq_len = decode_context_len

    if not workload.is_moe:
        # Standard GQA Attention + SwiGLU MLP
        q_dim = workload.num_q_heads * workload.head_dim
        kv_dim = workload.num_kv_heads * workload.head_dim

        # Projection FLOPs per layer: Q, K, V, O + gate, up, down
        proj_flops_per_layer = 2.0 * float(tokens_processed) * (
            workload.hidden_size * (2 * q_dim + 2 * kv_dim)
            + 3 * workload.hidden_size * workload.intermediate_size
        )
        # Attention score + weighted sum FLOPs: 4 * batch * q_heads * seq_q * seq_k * head_dim
        # (causal prefill averages 0.5 * seq_k)
        eff_attn_k = (0.5 * kv_seq_len) if regime == "prefill" else float(kv_seq_len)
        attn_flops_per_layer = (
            4.0 * float(batch_size) * float(workload.num_q_heads) * float(seq_len) * eff_attn_k * float(workload.head_dim)
        )
        total_flops = float(workload.num_layers) * (proj_flops_per_layer + attn_flops_per_layer)

        # Model weight bytes per layer (all layers streamed once per forward pass)
        weight_params_per_layer = (
            workload.hidden_size * (2 * q_dim + 2 * kv_dim)
            + 3 * workload.hidden_size * workload.intermediate_size
        )
        total_weight_bytes = float(workload.num_layers) * float(weight_params_per_layer) * w_bytes
        kv_cache_bytes = (
            2.0 * float(workload.num_layers) * float(batch_size) * float(kv_seq_len) * float(kv_dim) * kv_bytes
        )
        # Prefill writes KV cache once; decode reads whole KV cache per step
        kv_traffic_bytes = kv_cache_bytes if regime == "decode" else (kv_cache_bytes * 1.0)
        activation_bytes = (
            float(workload.num_layers) * float(tokens_processed) * float(workload.hidden_size) * act_bytes * 6.0
        )
        # Dual-die TP=2 requires 2 AllReduces per layer (O-proj + down-proj)
        tp_allreduce_bytes = (
            float(workload.num_layers) * 2.0 * float(tokens_processed) * float(workload.hidden_size) * 2.0
            if die_count > 1
            else 0.0
        )
        all_to_all_bytes = 0.0
        active_experts_per_layer = 0.0
    else:
        # DeepSeek-V3: MLA compressed KV-cache + dense layers + routed top-K MoE + shared experts
        dense_layers = workload.num_layers - workload.moe_layers
        # MLA Q/KV low-rank + up-projection + O-proj
        qk_head = workload.qk_nope_head_dim + workload.qk_rope_head_dim
        mla_proj_params = (
            workload.hidden_size * (workload.q_lora_rank + workload.kv_lora_rank + workload.qk_rope_head_dim)
            + workload.q_lora_rank * workload.num_q_heads * qk_head
            + workload.kv_lora_rank * workload.num_q_heads * (workload.qk_nope_head_dim + workload.v_head_dim)
            + workload.num_q_heads * workload.v_head_dim * workload.hidden_size
        )
        mla_proj_flops = 2.0 * float(tokens_processed) * float(mla_proj_params)
        eff_attn_k = (0.5 * kv_seq_len) if regime == "prefill" else float(kv_seq_len)
        mla_attn_flops = (
            2.0
            * float(batch_size)
            * float(workload.num_q_heads)
            * float(seq_len)
            * eff_attn_k
            * float(qk_head + workload.v_head_dim)
        )

        # Dense MLP FLOPs
        dense_mlp_flops = float(dense_layers) * 2.0 * float(tokens_processed) * (
            3.0 * float(workload.hidden_size) * float(workload.intermediate_size)
        )
        # MoE active FLOPs per token: (top_k + shared) experts
        active_experts_per_tok = float(workload.top_k_experts + workload.num_shared_experts)
        moe_mlp_flops = float(workload.moe_layers) * 2.0 * float(tokens_processed) * active_experts_per_tok * (
            3.0 * float(workload.hidden_size) * float(workload.moe_intermediate_size)
        )
        total_flops = (
            float(workload.num_layers) * (mla_proj_flops + mla_attn_flops) + dense_mlp_flops + moe_mlp_flops
        )

        # Coupon-collector expected unique routed experts touched per MoE layer across tokens_processed:
        # E[unique] = N * (1 - ((N - k)/N)^tokens)
        n_exp = float(workload.num_routed_experts)
        k_exp = float(workload.top_k_experts)
        p_miss = max(0.0, (n_exp - k_exp) / n_exp)
        expected_unique_routed = n_exp * (1.0 - (p_miss ** min(tokens_processed, 2048)))
        active_experts_per_layer = expected_unique_routed + float(workload.num_shared_experts)

        expert_weight_params = 3.0 * float(workload.hidden_size) * float(workload.moe_intermediate_size)
        dense_weight_bytes = (
            float(workload.num_layers) * float(mla_proj_params)
            + float(dense_layers) * 3.0 * float(workload.hidden_size) * float(workload.intermediate_size)
        ) * w_bytes
        moe_weight_bytes = float(workload.moe_layers) * active_experts_per_layer * expert_weight_params * w_bytes
        total_weight_bytes = dense_weight_bytes + moe_weight_bytes

        # MLA compressed KV-cache: only (kv_lora_rank + qk_rope_head_dim) per token per layer!
        mla_kv_dim = workload.kv_lora_rank + workload.qk_rope_head_dim
        kv_cache_bytes = (
            float(workload.num_layers) * float(batch_size) * float(kv_seq_len) * float(mla_kv_dim) * kv_bytes
        )
        kv_traffic_bytes = kv_cache_bytes
        activation_bytes = (
            float(workload.num_layers) * float(tokens_processed) * float(workload.hidden_size) * act_bytes * 8.0
        )
        tp_allreduce_bytes = (
            float(workload.num_layers) * float(tokens_processed) * float(workload.hidden_size) * 2.0
            if die_count > 1
            else 0.0
        )
        # AllToAll dispatch + combine over UCIe D2D when split across 2 dies
        all_to_all_bytes = (
            float(workload.moe_layers)
            * 2.0
            * float(tokens_processed)
            * float(workload.top_k_experts)
            * float(workload.hidden_size)
            * act_bytes
            * 0.5
            if die_count > 1
            else 0.0
        )

    # L2 hit-rate filter: activations and hot shared/KV slices hit in L2 if smaller than L2 capacity
    l2_hit_fraction_act = min(0.85, float(l2_capacity_bytes) / max(1.0, activation_bytes / float(workload.num_layers)))
    hbm_act_bytes = activation_bytes * (1.0 - l2_hit_fraction_act)
    raw_hbm_bytes = total_weight_bytes + kv_traffic_bytes + hbm_act_bytes

    # Cross-die UCIe D2D traffic: TP AllReduce + MoE AllToAll + remote L2/HBM split fraction
    remote_hbm_split_bytes = raw_hbm_bytes * remote_die_split_ratio * 0.25 if die_count > 1 else 0.0
    ucie_d2d_bytes = tp_allreduce_bytes + all_to_all_bytes + remote_hbm_split_bytes

    # TMEM holds FP32 accumulators across the full K reduction (e.g. K_tile=256..1024),
    # so external TMEM/RF drain is ~0.015 bytes/FLOP in tiled MMA rather than 0.25 bytes/FLOP.
    # Each transformer layer executes 2 collective synchronization phases (attention + MLP/MoE).
    sync_barriers = 2 * workload.num_layers if die_count > 1 else 0
    traffic = HierarchicalTraffic(
        flops=total_flops,
        tmem_bytes=total_flops * 0.015,
        l1_lmem_bytes=raw_hbm_bytes * 2.2 + activation_bytes,
        l2_slc_bytes=raw_hbm_bytes * 1.15 + activation_bytes * 0.5,
        hbm_bytes=raw_hbm_bytes,
        ucie_d2d_bytes=ucie_d2d_bytes,
        pcie_host_bytes=0.0,
        compressed_weight_bytes=total_weight_bytes if w_bytes <= 1.05 else 0.0,
        de_amplification=1.45 if w_bytes <= 1.05 else 1.0,
        sync_barriers=sync_barriers,
    )

    return {
        "workload_id": workload.id,
        "regime": regime,
        "tokens_or_batch": tokens_or_batch,
        "tokens_processed_per_step": tokens_processed,
        "kv_cache_bytes": kv_cache_bytes,
        "kv_cache_gib": kv_cache_bytes / float(1024**3),
        "total_weight_bytes": total_weight_bytes,
        "active_experts_per_layer": round(active_experts_per_layer, 2),
        "tp_allreduce_bytes": tp_allreduce_bytes,
        "moe_all_to_all_bytes": all_to_all_bytes,
        "traffic": traffic,
    }


def evaluate_workload_on_target(
    target: dict[str, Any],
    workload_id: str,
    *,
    regime: str,
    tokens_or_batch: int,
    fmt_key: str,
    kv_format_key: str = "fp8_e4m3",
    use_sparse: bool = False,
    remote_die_split_ratio: float = 0.5,
    use_de_compression: bool = True,
) -> dict[str, Any]:
    """Evaluate a Llama-3 or DeepSeek-V3 operating point on an analyzed target."""
    if workload_id not in LLM_WORKLOADS:
        raise ValueError(f"Unknown workload {workload_id!r}; expected one of {sorted(LLM_WORKLOADS)}")
    fmt_key = canonical_format_key(fmt_key)
    kv_format_key = canonical_format_key(kv_format_key)
    wl = LLM_WORKLOADS[workload_id]

    die_count = int(target["topology"].get("die_count", 1))
    l2_bytes = int(target["hierarchy"]["levels"]["level3_l2_slc"]["effective_llc_bytes"])
    wt = compute_workload_traffic(
        wl,
        regime=regime,
        tokens_or_batch=tokens_or_batch,
        fmt_key=fmt_key,
        kv_format_key=kv_format_key,
        die_count=die_count,
        remote_die_split_ratio=remote_die_split_ratio,
        l2_capacity_bytes=l2_bytes,
    )
    traffic: HierarchicalTraffic = wt["traffic"]
    roof = evaluate_hierarchical_roofline(
        target,
        fmt_key,
        traffic,
        use_sparse=use_sparse,
        use_de_compression=use_de_compression,
    )
    if not roof["supported"]:
        return {
            "workload": workload_id,
            "regime": regime,
            "tokens_or_batch": tokens_or_batch,
            "format": fmt_key,
            "supported": False,
            "limiting_level": "unsupported",
            "attained_tflops_or_tops": None,
            "tokens_per_sec": None,
            "step_latency_ms": None,
            "kv_cache_gib": wt["kv_cache_gib"],
        }

    step_ms = float(roof["min_execution_time_ms"])
    toks_per_sec = (float(wt["tokens_processed_per_step"]) / (step_ms / 1000.0)) if step_ms > 0.0 else 0.0
    hbm_cap_bytes = int(target["hierarchy"]["levels"]["level4_hbm"]["capacity_bytes"])
    fits_in_hbm = (wt["total_weight_bytes"] + wt["kv_cache_bytes"]) <= float(hbm_cap_bytes)

    return {
        "workload": workload_id,
        "regime": regime,
        "tokens_or_batch": tokens_or_batch,
        "format": fmt_key,
        "kv_format": kv_format_key,
        "supported": True,
        "limiting_level": roof["limiting_level"],
        "attained_tflops_or_tops": roof["attained_tflops_or_tops"],
        "compute_ceiling_tflops_or_tops": roof["compute_ceiling_tflops_or_tops"],
        "effective_hbm_ai": roof["effective_hbm_ai"],
        "raw_hbm_ai": roof["raw_hbm_ai"],
        "step_latency_ms": step_ms,
        "tokens_per_sec": toks_per_sec,
        "kv_cache_gib": wt["kv_cache_gib"],
        "total_weight_gib": wt["total_weight_bytes"] / float(1024**3),
        "fits_single_device_hbm": fits_in_hbm,
        "ucie_d2d_bytes": traffic.ucie_d2d_bytes,
    }


def run_sensitivity_sweeps(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    allow_builtin_fallback: bool = True,
    fmt_key: str = "fp8_e4m3",
    workload_id: str = "llama3-70b",
) -> dict[str, Any]:
    """Run parametric sensitivity sweeps on clock, HBM BW, UCIe split, 2:4 sparsity, and KV quant."""
    fmt_key = canonical_format_key(fmt_key)

    # 1. Clock frequency sweep on aigpu-b2 (prefill seq=4096 compute-bound & decode batch=32)
    clock_sweep = []
    for clk_mhz in (1500.0, 1750.0, 2000.0, 2200.0):
        prof = analyze_aigpu_profile(
            "aigpu-b2",
            config_path=config_path,
            profiles_dir=profiles_dir,
            allow_builtin_fallback=allow_builtin_fallback,
            clock_override_mhz=clk_mhz,
        )
        prefill = evaluate_workload_on_target(
            prof, workload_id, regime="prefill", tokens_or_batch=4096, fmt_key=fmt_key
        )
        decode = evaluate_workload_on_target(
            prof, workload_id, regime="decode", tokens_or_batch=32, fmt_key=fmt_key
        )
        clock_sweep.append({
            "clock_mhz": clk_mhz,
            "fp16_tfrv2_dense_tflops": prof["tensor_formats"]["fp16"]["dense_peak"],
            "fp8_tfrv2_dense_tflops": prof["tensor_formats"]["fp8_e4m3"]["dense_peak"],
            "prefill_tokens_per_sec": prefill["tokens_per_sec"],
            "decode_tokens_per_sec": decode["tokens_per_sec"],
        })

    # 2. HBM3E bandwidth sweep on aigpu-b2 (decode batch=16 memory-bound)
    hbm_sweep = []
    for bw_gbs in (3200.0, 4000.0, 4800.0, 5600.0, 8000.0):
        prof = analyze_aigpu_profile(
            "aigpu-b2",
            config_path=config_path,
            profiles_dir=profiles_dir,
            allow_builtin_fallback=allow_builtin_fallback,
            hbm_bw_override_gbs=bw_gbs,
        )
        decode = evaluate_workload_on_target(
            prof, workload_id, regime="decode", tokens_or_batch=16, fmt_key=fmt_key
        )
        hbm_sweep.append({
            "hbm_bandwidth_gbs": bw_gbs,
            "decode_attained_tflops": decode["attained_tflops_or_tops"],
            "decode_tokens_per_sec": decode["tokens_per_sec"],
            "limiting_level": decode["limiting_level"],
        })

    # 3. Dual-die UCIe D2D remote traffic split ratio sweep on aigpu-b2-dual
    b2_dual = analyze_aigpu_profile(
        "aigpu-b2-dual",
        config_path=config_path,
        profiles_dir=profiles_dir,
        allow_builtin_fallback=allow_builtin_fallback,
    )
    ucie_sweep = []
    for ratio in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
        ds_decode = evaluate_workload_on_target(
            b2_dual,
            "deepseek-v3",
            regime="decode",
            tokens_or_batch=64,
            fmt_key=fmt_key,
            remote_die_split_ratio=ratio,
        )
        ucie_sweep.append({
            "remote_die_split_ratio": ratio,
            "ucie_d2d_gb": ds_decode["ucie_d2d_bytes"] / 1e9,
            "tokens_per_sec": ds_decode["tokens_per_sec"],
            "step_latency_ms": ds_decode["step_latency_ms"],
        })

    # 4. 2:4 sparsity utilization sweep on aigpu-b2 (prefill seq=4096)
    sparsity_sweep = []
    for util in (0.0, 0.25, 0.5, 0.75, 1.0):
        prof = analyze_aigpu_profile(
            "aigpu-b2",
            config_path=config_path,
            profiles_dir=profiles_dir,
            allow_builtin_fallback=allow_builtin_fallback,
            sparsity_utilization=util,
        )
        prefill = evaluate_workload_on_target(
            prof,
            workload_id,
            regime="prefill",
            tokens_or_batch=4096,
            fmt_key=fmt_key,
            use_sparse=True,
        )
        sparsity_sweep.append({
            "sparsity_utilization": util,
            "effective_peak_tflops": prof["tensor_formats"][fmt_key]["sparse_2_4_peak"],
            "prefill_attained_tflops": prefill["attained_tflops_or_tops"],
            "prefill_tokens_per_sec": prefill["tokens_per_sec"],
        })

    # 5. KV-cache quantization sweep (FP16 vs FP8 vs NVFP4) at batch=128 decode
    b2 = analyze_aigpu_profile(
        "aigpu-b2",
        config_path=config_path,
        profiles_dir=profiles_dir,
        allow_builtin_fallback=allow_builtin_fallback,
    )
    kv_sweep = []
    for kv_fmt in ("fp16", "fp8_e4m3", "nvfp4"):
        dec = evaluate_workload_on_target(
            b2,
            workload_id,
            regime="decode",
            tokens_or_batch=128,
            fmt_key=fmt_key,
            kv_format_key=kv_fmt,
        )
        kv_sweep.append({
            "kv_format": kv_fmt,
            "kv_cache_gib": dec["kv_cache_gib"],
            "decode_tokens_per_sec": dec["tokens_per_sec"],
            "step_latency_ms": dec["step_latency_ms"],
        })

    return {
        "clock_frequency_sweep": clock_sweep,
        "hbm_bandwidth_sweep": hbm_sweep,
        "ucie_split_ratio_sweep": ucie_sweep,
        "sparsity_utilization_sweep": sparsity_sweep,
        "kv_quantization_sweep": kv_sweep,
    }


def build_speedup_comparison_tables(
    targets: dict[str, dict[str, Any]],
    workload_matrix: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute comparative speedup/gap tables for aigpu-b2 & aigpu-b2-dual vs baselines."""
    comparisons: list[dict[str, Any]] = []
    pairs = [
        ("aigpu-b2", "nvidia-b200-1die"),
        ("aigpu-b2", "nvidia-h200-sxm"),
        ("aigpu-b2", "nvidia-h100-sxm5"),
        ("aigpu-b2", "amd-mi300x"),
        ("aigpu-b2", "aigpu-b1"),
        ("aigpu-b2-dual", "nvidia-b200-2die"),
        ("aigpu-b2-dual", "nvidia-h200-sxm"),
        ("aigpu-b2-dual", "amd-mi300x"),
    ]
    for lhs_id, rhs_id in pairs:
        lhs = targets.get(lhs_id)
        rhs = targets.get(rhs_id)
        if lhs is None or rhs is None:
            continue

        def _ratio(a: float | None, b: float | None) -> float | None:
            if a is None or b is None or b == 0.0:
                return None
            return round(a / b, 4)

        lhs_fmts = lhs["tensor_formats"]
        rhs_fmts = rhs["tensor_formats"]
        lhs_wl = workload_matrix.get(lhs_id, {})
        rhs_wl = workload_matrix.get(rhs_id, {})

        comparisons.append({
            "target": lhs_id,
            "baseline": rhs_id,
            "fp16_dense_peak_ratio": _ratio(
                lhs_fmts["fp16"]["dense_peak"], rhs_fmts["fp16"]["dense_peak"]
            ),
            "fp8_dense_peak_ratio": _ratio(
                lhs_fmts["fp8_e4m3"]["dense_peak"], rhs_fmts["fp8_e4m3"]["dense_peak"]
            ),
            "nvfp4_dense_peak_ratio": _ratio(
                lhs_fmts["nvfp4"]["dense_peak"], rhs_fmts["nvfp4"]["dense_peak"]
            ),
            "hbm_bandwidth_ratio": _ratio(
                lhs["memory"]["bandwidth_gbs"], rhs["memory"]["bandwidth_gbs"]
            ),
            "llama3_70b_prefill_4k_fp8_speedup": _ratio(
                lhs_wl.get("llama3-70b_prefill_4096_fp8_e4m3", {}).get("tokens_per_sec"),
                rhs_wl.get("llama3-70b_prefill_4096_fp8_e4m3", {}).get("tokens_per_sec"),
            ),
            "llama3_70b_decode_b32_fp8_speedup": _ratio(
                lhs_wl.get("llama3-70b_decode_32_fp8_e4m3", {}).get("tokens_per_sec"),
                rhs_wl.get("llama3-70b_decode_32_fp8_e4m3", {}).get("tokens_per_sec"),
            ),
            "deepseek_v3_decode_b32_fp8_speedup": _ratio(
                lhs_wl.get("deepseek-v3_decode_32_fp8_e4m3", {}).get("tokens_per_sec"),
                rhs_wl.get("deepseek-v3_decode_32_fp8_e4m3", {}).get("tokens_per_sec"),
            ),
        })
    return {"pairwise_speedups": comparisons}


def build_b2_comparison_report(
    *,
    aigpu_targets: tuple[str, ...] = ALL_AIGPU_TARGETS,
    competitor_ids: tuple[str, ...] = COMPETITOR_IDS,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
    allow_builtin_fallback: bool = True,
    selected_formats: tuple[str, ...] | None = None,
    selected_workloads: tuple[str, ...] | None = None,
    selected_regimes: tuple[str, ...] = ("prefill", "decode"),
    include_sweeps: bool = True,
    sweep_format: str = "fp8_e4m3",
    sweep_workload: str = "llama3-70b",
) -> dict[str, Any]:
    """Assemble complete hierarchical analytical roofline report for B2 vs baselines."""
    formats_filter = (
        tuple(canonical_format_key(f) for f in selected_formats)
        if selected_formats is not None
        else tuple(FORMAT_SPECS.keys())
    )
    workloads_filter = (
        tuple(selected_workloads) if selected_workloads is not None else tuple(LLM_WORKLOADS.keys())
    )
    for wl in workloads_filter:
        if wl not in LLM_WORKLOADS:
            raise ValueError(f"Unknown workload {wl!r}; expected one of {sorted(LLM_WORKLOADS)}")
    for reg in selected_regimes:
        if reg not in ("prefill", "decode"):
            raise ValueError(f"Unknown regime {reg!r}; expected 'prefill' or 'decode'")

    targets: dict[str, dict[str, Any]] = {}
    for pname in aigpu_targets:
        targets[pname] = analyze_aigpu_profile(
            pname,
            config_path=config_path,
            profiles_dir=profiles_dir,
            allow_builtin_fallback=allow_builtin_fallback,
        )
    for cid in competitor_ids:
        targets[cid] = analyze_competitor_baseline(cid)

    # Evaluate workload suite across prefill and decode regimes
    eval_formats = tuple(f for f in ("fp16", "fp8_e4m3", "nvfp4") if f in formats_filter)
    if not eval_formats:
        eval_formats = (formats_filter[0],)

    workload_matrix: dict[str, dict[str, Any]] = {}
    for tid, tobj in targets.items():
        per_target: dict[str, Any] = {}
        for wl_id in workloads_filter:
            if "prefill" in selected_regimes:
                for seq_len in PREFILL_SEQ_LENGTHS:
                    for fkey in eval_formats:
                        key = f"{wl_id}_prefill_{seq_len}_{fkey}"
                        per_target[key] = evaluate_workload_on_target(
                            tobj, wl_id, regime="prefill", tokens_or_batch=seq_len, fmt_key=fkey
                        )
            if "decode" in selected_regimes:
                for batch in DECODE_BATCH_SIZES:
                    for fkey in eval_formats:
                        key = f"{wl_id}_decode_{batch}_{fkey}"
                        per_target[key] = evaluate_workload_on_target(
                            tobj, wl_id, regime="decode", tokens_or_batch=batch, fmt_key=fkey
                        )
        workload_matrix[tid] = per_target

    # Representative GEMM wave-quantization benchmarks
    gemm_shapes = (
        ("gemm_4096x4096x4096", 4096, 4096, 4096),
        ("gemm_8192x8192x8192", 8192, 8192, 8192),
        ("gemm_1024x14336x4096_tail", 1024, 14336, 4096),
        ("gemm_256x28672x8192_small_m", 256, 28672, 8192),
    )
    gemm_wave_analysis: dict[str, dict[str, Any]] = {}
    gemm_fmt = "fp8_e4m3" if "fp8_e4m3" in formats_filter else formats_filter[0]
    for tid, tobj in targets.items():
        gemm_wave_analysis[tid] = {
            gname: evaluate_gemm_wave_quantization(
                tobj, m_dim=m, n_dim=n, k_dim=k, fmt_key=gemm_fmt
            )
            for gname, m, n, k in gemm_shapes
        }

    sweeps = (
        run_sensitivity_sweeps(
            config_path=config_path,
            profiles_dir=profiles_dir,
            allow_builtin_fallback=allow_builtin_fallback,
            fmt_key=sweep_format,
            workload_id=sweep_workload,
        )
        if include_sweeps
        else {}
    )

    speedups = build_speedup_comparison_tables(targets, workload_matrix)

    report = {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "fpga_measured": False,
        "foundry_signoff": False,
        "phase_status_effect": "none",
        "disclaimer": (
            "MODELED ANALYTICAL ROOFLINE ONLY (Vortex profile parameters + hierarchical "
            "memory/fabric formulas + published vendor datasheets). NOT measured physical "
            "silicon, NOT FPGA hardware measurements, NOT SimX/RTL cycle simulations, and "
            "NOT foundry sign-off."
        ),
        "selected_formats": list(formats_filter),
        "selected_workloads": list(workloads_filter),
        "selected_regimes": list(selected_regimes),
        "targets_order": list(targets.keys()),
        "targets": targets,
        "workload_evaluations": workload_matrix,
        "gemm_wave_quantization": gemm_wave_analysis,
        "sensitivity_sweeps": sweeps,
        "comparative_speedups": speedups,
    }
    validate_honesty_record(report)
    return report


def _fmt_val(val: float | None, decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val:,.{decimals}f}"


def format_report_markdown(report: dict[str, Any]) -> str:
    """Format hierarchical roofline comparison report as investor/engineering Markdown."""
    validate_honesty_record(report)
    lines = [
        "# AI-GPU B2 Hierarchical Analytical Roofline Report",
        "",
        f"- **Schema Version:** `{report['schema_version']}`",
        f"- **Evidence Level:** `{report['evidence_level']}` "
        f"(`silicon_measured={report['silicon_measured']}`, "
        f"`fpga_measured={report['fpga_measured']}`, "
        f"`foundry_signoff={report['foundry_signoff']}`)",
        f"- **Disclaimer:** {report['disclaimer']}",
        "",
        "## 1. Compute Peak & TFRv2 Reconciliation (Dense / 2:4 Sparse)",
        "",
        "| Target | Source | Cores | Clk (MHz) | HBM/DRAM (TB/s) | FP16 (TFLOPS) | FP8 (TFLOPS) | MXFP6 (TFLOPS) | NVFP4 (TOPS) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tid in report["targets_order"]:
        t = report["targets"][tid]
        fmts = t["tensor_formats"]
        src_tag = "Published Ref" if t["is_published_reference"] else f"Modeled ({t['profile_source']})"

        def _pair(fk: str) -> str:
            d = fmts[fk]["dense_peak"]
            s = fmts[fk]["sparse_2_4_peak"]
            if d is None:
                return "N/A"
            return f"{_fmt_val(d)} / {_fmt_val(s)}"

        lines.append(
            f"| `{tid}` | {src_tag} | {t['topology']['total_cores']} | "
            f"{t['memory']['clock_mhz']:.0f} | {t['memory']['bandwidth_gbs'] / 1000.0:.2f} | "
            f"{_pair('fp16')} | {_pair('fp8_e4m3')} | {_pair('mxfp6_e2m3')} | {_pair('nvfp4')} |"
        )

    lines.extend([
        "",
        "## 2. Six-Level Hierarchical Memory & Fabric Bandwidths",
        "",
        "| Target | L1 TMEM (MiB / TB/s) | L2 LMEM+L1 (MiB / TB/s) | L3 L2/SLC (MiB / TB/s) | L4 HBM Peak (TB/s) | L5 UCIe D2D (TB/s) | L6 PCIe / DE Eff HBM (TB/s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for tid in report["targets_order"]:
        lv = report["targets"][tid]["hierarchy"]["levels"]
        tmem = lv["level1_tmem"]
        l1 = lv["level2_l1_lmem"]
        l2 = lv["level3_l2_slc"]
        hbm = lv["level4_hbm"]
        ucie = lv["level5_ucie_d2d"]
        de = lv["level6_pcie_de"]
        lines.append(
            f"| `{tid}` | {tmem['capacity_mib']:.1f} / {tmem['bandwidth_gbs'] / 1000.0:.1f} | "
            f"{l1['capacity_mib']:.1f} / {l1['bandwidth_gbs'] / 1000.0:.1f} | "
            f"{l2['effective_llc_bytes'] / (1024 * 1024):.1f} / {l2['effective_llc_bandwidth_gbs'] / 1000.0:.1f} | "
            f"{hbm['peak_bandwidth_gbs'] / 1000.0:.2f} | "
            f"{ucie['bidirectional_gbs'] / 1000.0:.1f} | "
            f"Gen{de['pcie_gen']} ({de['pcie_bidirectional_gbs']:.0f} GB/s) / {de['de_effective_hbm_gbs'] / 1000.0:.2f} |"
        )

    lines.extend([
        "",
        "## 3. Comparative Speedup Summary (Modeled Analytical)",
        "",
        "| Target vs Baseline | FP16 Peak | FP8 Peak | NVFP4 Peak | HBM BW | Llama-3 70B Prefill 4K | Llama-3 70B Decode B32 | DeepSeek-V3 Decode B32 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in report["comparative_speedups"]["pairwise_speedups"]:
        def _x(v: float | None) -> str:
            return f"{v:.2f}x" if v is not None else "N/A"
        lines.append(
            f"| `{row['target']}` vs `{row['baseline']}` | "
            f"{_x(row['fp16_dense_peak_ratio'])} | {_x(row['fp8_dense_peak_ratio'])} | "
            f"{_x(row['nvfp4_dense_peak_ratio'])} | {_x(row['hbm_bandwidth_ratio'])} | "
            f"{_x(row['llama3_70b_prefill_4k_fp8_speedup'])} | "
            f"{_x(row['llama3_70b_decode_b32_fp8_speedup'])} | "
            f"{_x(row['deepseek_v3_decode_b32_fp8_speedup'])} |"
        )

    return "\n".join(lines) + "\n"


def format_report_text(report: dict[str, Any]) -> str:
    """Format concise ASCII summary table for terminal inspection."""
    return format_report_markdown(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=DEFAULT_PROFILES_DIR,
        help="Directory containing hardware profile JSON files (default: profiles/)",
    )
    parser.add_argument(
        "--targets",
        default=",".join(ALL_AIGPU_TARGETS),
        help="Comma-separated AI-GPU profile names",
    )
    parser.add_argument(
        "--competitors",
        default=",".join(COMPETITOR_IDS),
        help="Comma-separated competitor baseline IDs",
    )
    parser.add_argument(
        "--format",
        dest="precision_format",
        default="all",
        help="Precision format filter (e.g. fp16, bf16, tf32, fp8_e4m3, mxfp8, mxfp6_e2m3, mxfp4, nvfp4, int8, or 'all')",
    )
    parser.add_argument(
        "--regime",
        default="both",
        choices=("prefill", "decode", "both"),
        help="Workload regime filter",
    )
    parser.add_argument(
        "--workload",
        default="all",
        help="Workload filter (llama3-8b, llama3-70b, llama3-405b, deepseek-v3, or 'all')",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Include full parametric sensitivity sweeps in output",
    )
    parser.add_argument(
        "--strict-profiles",
        action="store_true",
        help="Disable authoritative B2 fallback if profiles/aigpu-b2*.json are absent",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON report",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Emit Markdown report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path",
    )
    args = parser.parse_args(argv)

    target_list = tuple(t.strip() for t in args.targets.split(",") if t.strip())
    comp_list = tuple(c.strip() for c in args.competitors.split(",") if c.strip())
    selected_formats = (
        None
        if args.precision_format.strip().lower() == "all"
        else tuple(canonical_format_key(x) for x in args.precision_format.split(",") if x.strip())
    )
    selected_workloads = (
        None
        if args.workload.strip().lower() == "all"
        else tuple(w.strip().lower() for w in args.workload.split(",") if w.strip())
    )
    selected_regimes = ("prefill", "decode") if args.regime == "both" else (args.regime,)

    report = build_b2_comparison_report(
        aigpu_targets=target_list,
        competitor_ids=comp_list,
        profiles_dir=args.profiles_dir,
        allow_builtin_fallback=not args.strict_profiles,
        selected_formats=selected_formats,
        selected_workloads=selected_workloads,
        selected_regimes=selected_regimes,
        include_sweeps=args.sweep or args.json,
    )

    if args.json:
        text = json.dumps(report, indent=2) + "\n"
    elif args.markdown:
        text = format_report_markdown(report)
    else:
        text = format_report_text(report)

    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
