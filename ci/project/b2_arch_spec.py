#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Authoritative pre-silicon machine-readable specification for the aigpu-b2 architecture.

This module serves as the single cross-pillar architectural contract registry for the
AI-GPU B2 commercial pre-silicon program across:
  - SKU topology & live profile validation (`aigpu-b2-tile`, `aigpu-b2`, `aigpu-b2-dual`)
  - Compute throughput reconciliation: Vortex base TFR (`1,048.576 TFLOPS` FP16) vs.
    `TFRv2` / `tcgen05` `16x8x8` systolic/FEDP pillar (`1,152 / 2,304 / 4,608` dense)
  - Complete `TFRv2` numeric format table (`FP16`, `BF16`, `TF32`, `FP8_E4M3`, `FP8_E5M2`,
    `MXFP8`, `MXFP6_E2M3`, `MXFP6_E3M2`, `MXFP4_E2M1`, `NVFP4_E2M1`, `INT8`) with IEEE/OCP
    exponent/mantissa/bias/scale-factor encodings, packing densities, and 2:4 sparsity
  - Banked Tensor Memory (`TMEM`) geometry, swizzle modes (`NONE`/`32B`/`64B`/`128B`),
    bank-conflict analyzer, and allocation/alignment validator
  - Coherent 2D Mesh NoC topology (`4x2` cluster grid + boundary nodes), deterministic XY
    dimension-order routing, hop & bisection-bandwidth calculator, MOESI directory slice
    hash/interleave map, and UCIe 2.0 coherent D2D dual-die address interleave & credit budget
  - HBM3E 8-stack/16-stack pseudo-channel geometry & JEDEC timing model, Hardware
    Decompression Engine (`LZ4`, `Snappy`, `Deflate`, `Bitcomp`) descriptor ABI, and
    5D DXA/TMA tensor descriptor validator
  - Full SoC MMIO address map, GigaThread 64-queue doorbell layout, MIG partition profile
    table & non-overlapping validator, PCIe Gen6 x16 BAR & IOMMU SV48 PTE bitfields,
    RAS MCA bank registry, PMU counter event catalog, and Confidential Computing
    SPDM/AES-256-GCM keyslot specification

Strict Pre-Silicon Honesty Invariants:
  Every generated payload carries:
    evidence_level   = "source_present"
    silicon_measured = False
    foundry_signoff  = False
    fpga_measured    = False
  Nothing in this file implies physical FPGA verification, foundry sign-off, or silicon.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


SCHEMA_VERSION = 1
ALLOWED_EVIDENCE_LEVEL = "source_present"
FORBIDDEN_EVIDENCE_LEVELS = frozenset({"fpga_measured", "silicon_measured"})

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "VX_config.toml"
DEFAULT_PROFILES_DIR = REPO_ROOT / "profiles"

B2_SKUS: tuple[str, ...] = ("aigpu-b2-tile", "aigpu-b2", "aigpu-b2-dual")

RETICLE_LIMIT_MM2 = 858.0
DIE_ESTIMATE_MM2: dict[str, tuple[float, float]] = {
    "aigpu-b2-tile": (12.0, 18.0),
    "aigpu-b2": (740.0, 810.0),
    "aigpu-b2-dual": (1520.0, 1620.0),
}


def stamp_honesty_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach mandatory pre-silicon honesty flags to an exported specification dict."""
    payload["schema_version"] = SCHEMA_VERSION
    payload["evidence_level"] = ALLOWED_EVIDENCE_LEVEL
    payload["silicon_measured"] = False
    payload["foundry_signoff"] = False
    payload["fpga_measured"] = False
    return payload


def validate_honesty_metadata(payload: dict[str, Any]) -> None:
    """Reject any specification payload that weakens pre-silicon evidence boundaries."""
    if not isinstance(payload, dict):
        raise ValueError("Specification payload must be a dict")
    if payload.get("evidence_level") != ALLOWED_EVIDENCE_LEVEL:
        raise ValueError(
            f"evidence_level must be {ALLOWED_EVIDENCE_LEVEL!r}, got {payload.get('evidence_level')!r}"
        )
    if payload.get("silicon_measured") is not False:
        raise ValueError("silicon_measured must remain False")
    if payload.get("foundry_signoff") is not False:
        raise ValueError("foundry_signoff must remain False")
    if payload.get("fpga_measured") is not False:
        raise ValueError("fpga_measured must remain False")


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _is_power_of_two(val: int) -> bool:
    return val > 0 and (val & (val - 1)) == 0


def _align_up(val: int, align: int) -> int:
    if align <= 0:
        raise ValueError(f"Alignment must be positive, got {align}")
    return ((val + align - 1) // align) * align


def _bitmask(bits: int) -> int:
    return (1 << bits) - 1 if bits > 0 else 0


# =============================================================================
# 1. SKU Topology & Compute Throughput Reconciliation (Vortex Base vs TFRv2)
# =============================================================================

@dataclass(frozen=True)
class SkuSpec:
    sku_id: str
    role: str
    num_dies: int
    clusters_per_die: int
    total_clusters: int
    cores_per_cluster: int
    total_cores: int
    socket_size: int
    warps_per_core: int
    threads_per_warp: int
    issue_width: int
    fetch_width: int
    alu_lanes_per_block: int
    fpu_lanes_per_block: int
    lsu_lanes_per_block: int
    tcu_blocks_per_core: int
    tcu_pe_ratio: int
    tcu_fedp2k: bool
    clock_mhz: float
    l1_dcache_bytes_per_core: int
    lmem_bytes_per_core: int
    tmem_bytes_per_core: int
    tmem_total_bytes: int
    l2_total_bytes: int
    l2_slices: int
    l2_ways: int
    l2_banks_total: int
    hbm_stacks: int
    hbm_pseudo_channels: int
    hbm_capacity_gib: int
    hbm_bandwidth_gbs: float
    ucie_d2d_bandwidth_gbs: float
    pcie_gen: int
    pcie_lanes: int
    pcie_bw_gbs_per_dir: float
    noc_mesh_rows: int
    noc_mesh_cols: int
    mig_max_slices: int
    vortex_base_fp16_tflops: float
    tfrv2_fp16_tflops_dense: float
    tfrv2_fp8_tflops_dense: float
    tfrv2_fp4_tops_dense: float
    tfrv2_sparse_multiplier: float
    tfrv2_array_shape: tuple[int, int, int]
    notes: str


SKU_SPECS: dict[str, SkuSpec] = {
    "aigpu-b2-tile": SkuSpec(
        sku_id="aigpu-b2-tile",
        role="RTL-verifiable 4-core compute tile & MPW slice",
        num_dies=1,
        clusters_per_die=1,
        total_clusters=1,
        cores_per_cluster=4,
        total_cores=4,
        socket_size=4,
        warps_per_core=8,
        threads_per_warp=8,
        issue_width=2,
        fetch_width=2,
        alu_lanes_per_block=8,
        fpu_lanes_per_block=8,
        lsu_lanes_per_block=8,
        tcu_blocks_per_core=2,
        tcu_pe_ratio=1,
        tcu_fedp2k=False,
        clock_mhz=400.0,
        l1_dcache_bytes_per_core=16384,
        lmem_bytes_per_core=16384,
        tmem_bytes_per_core=262144,
        tmem_total_bytes=1048576,
        l2_total_bytes=262144,
        l2_slices=1,
        l2_ways=8,
        l2_banks_total=1,
        hbm_stacks=0,
        hbm_pseudo_channels=2,
        hbm_capacity_gib=4,
        hbm_bandwidth_gbs=460.0,
        ucie_d2d_bandwidth_gbs=0.0,
        pcie_gen=6,
        pcie_lanes=4,
        pcie_bw_gbs_per_dir=32.0,
        noc_mesh_rows=1,
        noc_mesh_cols=1,
        mig_max_slices=1,
        vortex_base_fp16_tflops=0.2048,
        tfrv2_fp16_tflops_dense=18.0,
        tfrv2_fp8_tflops_dense=36.0,
        tfrv2_fp4_tops_dense=72.0,
        tfrv2_sparse_multiplier=2.0,
        tfrv2_array_shape=(16, 8, 8),
        notes=(
            "RTL verification slice uses 400 MHz platform ref and FEDP2K=false for stock rtlsim "
            "compatibility; scaled 2.0 GHz B2 architectural tile target yields 18/36/72 TFLOPS "
            "(FP16/FP8/FP4 dense) with 1 MiB TMEM and 1.5 MiB target L1/L2."
        ),
    ),
    "aigpu-b2": SkuSpec(
        sku_id="aigpu-b2",
        role="Full-reticle single-die datacenter AI GPU",
        num_dies=1,
        clusters_per_die=8,
        total_clusters=8,
        cores_per_cluster=16,
        total_cores=128,
        socket_size=1,
        warps_per_core=32,
        threads_per_warp=32,
        issue_width=4,
        fetch_width=4,
        alu_lanes_per_block=32,
        fpu_lanes_per_block=32,
        lsu_lanes_per_block=8,
        tcu_blocks_per_core=4,
        tcu_pe_ratio=1,
        tcu_fedp2k=True,
        clock_mhz=2000.0,
        l1_dcache_bytes_per_core=131072,
        lmem_bytes_per_core=131072,
        tmem_bytes_per_core=262144,
        tmem_total_bytes=33554432,
        l2_total_bytes=134217728,
        l2_slices=8,
        l2_ways=16,
        l2_banks_total=64,
        hbm_stacks=8,
        hbm_pseudo_channels=64,
        hbm_capacity_gib=96,
        hbm_bandwidth_gbs=4000.0,
        ucie_d2d_bandwidth_gbs=10000.0,
        pcie_gen=6,
        pcie_lanes=16,
        pcie_bw_gbs_per_dir=128.0,
        noc_mesh_rows=4,
        noc_mesh_cols=2,
        mig_max_slices=8,
        vortex_base_fp16_tflops=1048.576,
        tfrv2_fp16_tflops_dense=1152.0,
        tfrv2_fp8_tflops_dense=2304.0,
        tfrv2_fp4_tops_dense=4608.0,
        tfrv2_sparse_multiplier=2.0,
        tfrv2_array_shape=(16, 8, 8),
        notes=(
            "128 cores (8x16) on a 4x2 NoC mesh, 32 MiB TMEM, 128 MiB distributed L2/SLC across 8 "
            "MOESI directory slices, 4.0 TB/s 8-stack HBM3E, 10 TB/s UCIe 2.0 D2D, PCIe Gen6 x16."
        ),
    ),
    "aigpu-b2-dual": SkuSpec(
        sku_id="aigpu-b2-dual",
        role="Dual-die CoWoS-L / UCIe 2.0 unified coherent GPU",
        num_dies=2,
        clusters_per_die=8,
        total_clusters=16,
        cores_per_cluster=16,
        total_cores=256,
        socket_size=1,
        warps_per_core=32,
        threads_per_warp=32,
        issue_width=4,
        fetch_width=4,
        alu_lanes_per_block=32,
        fpu_lanes_per_block=32,
        lsu_lanes_per_block=8,
        tcu_blocks_per_core=4,
        tcu_pe_ratio=1,
        tcu_fedp2k=True,
        clock_mhz=2000.0,
        l1_dcache_bytes_per_core=131072,
        lmem_bytes_per_core=131072,
        tmem_bytes_per_core=262144,
        tmem_total_bytes=67108864,
        l2_total_bytes=268435456,
        l2_slices=16,
        l2_ways=16,
        l2_banks_total=128,
        hbm_stacks=16,
        hbm_pseudo_channels=128,
        hbm_capacity_gib=192,
        hbm_bandwidth_gbs=8000.0,
        ucie_d2d_bandwidth_gbs=10000.0,
        pcie_gen=6,
        pcie_lanes=16,
        pcie_bw_gbs_per_dir=128.0,
        noc_mesh_rows=4,
        noc_mesh_cols=4,
        mig_max_slices=16,
        vortex_base_fp16_tflops=2097.152,
        tfrv2_fp16_tflops_dense=2304.0,
        tfrv2_fp8_tflops_dense=4608.0,
        tfrv2_fp4_tops_dense=9216.0,
        tfrv2_sparse_multiplier=2.0,
        tfrv2_array_shape=(16, 8, 8),
        notes=(
            "2x aigpu-b2 dies unified via 10 TB/s coherent UCIe 2.0 D2D directory: 256 cores, "
            "64 MiB TMEM, 256 MiB unified L2/SLC, 8.0 TB/s across 16 HBM3E stacks."
        ),
    ),
}


def compute_vortex_base_tfr_tflops(
    *,
    total_cores: int,
    tcu_blocks_per_core: int,
    num_threads: int,
    pe_ratio: int,
    fedp2k: bool,
    wgmma_enabled: bool,
    clock_mhz: float,
    elements_per_word32: int,
) -> float:
    """Compute exact Vortex VX_config.toml TFR formula throughput in TFLOPS/TOPS."""
    if not _is_power_of_two(num_threads):
        raise ValueError(f"num_threads must be power of two, got {num_threads}")
    lg_cap = num_threads.bit_length() - 1
    block_en = lg_cap // 2
    block_em = lg_cap - block_en
    tc_m = 1 << block_em
    tc_n = 1 << block_en
    tc_k = num_threads // max(tc_m, tc_n)
    fedp_k = (2 * tc_k) if (fedp2k and wgmma_enabled) else tc_k
    pes_per_block = (tc_m * tc_n) / float(pe_ratio)
    word32_fmas_per_cycle = float(total_cores) * float(tcu_blocks_per_core) * pes_per_block * float(fedp_k)
    clock_ghz = clock_mhz / 1000.0
    return (word32_fmas_per_cycle * float(elements_per_word32) * 2.0 * clock_ghz) / 1000.0


def compute_tfrv2_systolic_tflops(
    *,
    total_cores: int,
    tcu_blocks_per_core: int,
    clock_mhz: float,
    elements_per_fp16_lane: float,
    sparse_2_4: bool = False,
) -> float:
    """Compute B2 TFRv2 / tcgen05 wide systolic target throughput (2.25 TFLOPS/block @ 2.0 GHz FP16).

    Reconciliation with Vortex base TFR:
      - Vortex base TFR (aigpu-b2: 128 cores x 4 blocks, NT=32 -> 8x4x4, FEDP2K=8 words,
        PE_RATIO=1, 2.0 GHz): 512 * 32 * 8 * 2 * 2 * 2.0 / 1000 = 1,048.576 TFLOPS FP16.
      - B2 TFRv2 / tcgen05 16x8x8 wide systolic pillar achieves 562.5 FP16 FMAs/block/cycle
        (1,125 FP16 FLOPs/block/cycle -> 2.25 TFLOPS/block @ 2.0 GHz), an exact ratio of
        1,125 / 1,024 = 1.098633x (+9.86%) over Vortex base TFR (2.048 TFLOPS/block @ 2.0 GHz):
          * aigpu-b2-tile (8 blocks @ 2.0 GHz):   18 /   36 /   72 TFLOPS (FP16/FP8/FP4 dense)
          * aigpu-b2      (512 blocks @ 2.0 GHz): 1,152 / 2,304 / 4,608 TFLOPS
          * aigpu-b2-dual (1024 blocks @ 2.0 GHz): 2,304 / 4,608 / 9,216 TFLOPS
    """
    base_fp16_per_block_at_2ghz = 2.25
    total_blocks = total_cores * tcu_blocks_per_core
    dense_tflops = (
        float(total_blocks)
        * base_fp16_per_block_at_2ghz
        * (clock_mhz / 2000.0)
        * float(elements_per_fp16_lane)
    )
    return dense_tflops * (2.0 if sparse_2_4 else 1.0)


def build_throughput_reconciliation(sku_id: str) -> dict[str, Any]:
    """Return explicit reconciliation between Vortex base TFR and TFRv2 architectural peaks."""
    sku = SKU_SPECS[sku_id]
    base_fp16 = compute_vortex_base_tfr_tflops(
        total_cores=sku.total_cores,
        tcu_blocks_per_core=sku.tcu_blocks_per_core,
        num_threads=sku.threads_per_warp,
        pe_ratio=sku.tcu_pe_ratio,
        fedp2k=sku.tcu_fedp2k,
        wgmma_enabled=True,
        clock_mhz=sku.clock_mhz,
        elements_per_word32=2,
    )
    arch_clock_mhz = 2000.0 if sku_id == "aigpu-b2-tile" else sku.clock_mhz
    tfrv2_fp16 = compute_tfrv2_systolic_tflops(
        total_cores=sku.total_cores,
        tcu_blocks_per_core=sku.tcu_blocks_per_core,
        clock_mhz=arch_clock_mhz,
        elements_per_fp16_lane=1.0,
    )
    tfrv2_fp8 = compute_tfrv2_systolic_tflops(
        total_cores=sku.total_cores,
        tcu_blocks_per_core=sku.tcu_blocks_per_core,
        clock_mhz=arch_clock_mhz,
        elements_per_fp16_lane=2.0,
    )
    tfrv2_fp4 = compute_tfrv2_systolic_tflops(
        total_cores=sku.total_cores,
        tcu_blocks_per_core=sku.tcu_blocks_per_core,
        clock_mhz=arch_clock_mhz,
        elements_per_fp16_lane=4.0,
    )
    return {
        "sku_id": sku_id,
        "vortex_base_clock_mhz": sku.clock_mhz,
        "vortex_base_tfr_fp16_tflops": round(base_fp16, 6),
        "vortex_base_tfr_fp8_tflops": round(base_fp16 * 2.0, 6),
        "vortex_base_tfr_fp4_tops": round(base_fp16 * 4.0, 6),
        "tfrv2_target_clock_mhz": arch_clock_mhz,
        "tfrv2_array_shape": list(sku.tfrv2_array_shape),
        "tfrv2_dense_fp16_tflops": round(tfrv2_fp16, 3),
        "tfrv2_dense_fp8_tflops": round(tfrv2_fp8, 3),
        "tfrv2_dense_fp4_tops": round(tfrv2_fp4, 3),
        "tfrv2_sparse_2_4_fp16_tflops": round(tfrv2_fp16 * 2.0, 3),
        "tfrv2_sparse_2_4_fp8_tflops": round(tfrv2_fp8 * 2.0, 3),
        "tfrv2_sparse_2_4_fp4_tops": round(tfrv2_fp4 * 2.0, 3),
        "reconciliation_ratio_tfrv2_to_vortex_base_at_equal_clock": round(
            (tfrv2_fp16 / (base_fp16 * (arch_clock_mhz / sku.clock_mhz))), 6
        ),
    }


# =============================================================================
# 2. TFRv2 Numeric Format Table (IEEE / OCP MX / NVFP4 / INT8)
# =============================================================================

@dataclass(frozen=True)
class NumericFormatSpec:
    format_id: str
    tcu_fmt_id: int
    bitwidth: int
    sign_bits: int
    exponent_bits: int
    mantissa_bits: int
    exponent_bias: int
    has_inf: bool
    has_nan: bool
    is_integer: bool
    is_signed: bool
    scale_factor_type: str | None
    scale_block_size: int
    scale_bits_per_block: int
    elements_per_word32: int
    fp16_throughput_multiplier: float
    effective_bits_per_element_with_scale: float
    sparse_2_4_metadata_bits_per_4elems: int
    accumulator_type: str
    standard_ref: str


NUMERIC_FORMATS: dict[str, NumericFormatSpec] = {
    "FP16": NumericFormatSpec(
        format_id="FP16",
        tcu_fmt_id=2,
        bitwidth=16,
        sign_bits=1,
        exponent_bits=5,
        mantissa_bits=10,
        exponent_bias=15,
        has_inf=True,
        has_nan=True,
        is_integer=False,
        is_signed=True,
        scale_factor_type=None,
        scale_block_size=1,
        scale_bits_per_block=0,
        elements_per_word32=2,
        fp16_throughput_multiplier=1.0,
        effective_bits_per_element_with_scale=16.0,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="IEEE 754 binary16",
    ),
    "BF16": NumericFormatSpec(
        format_id="BF16",
        tcu_fmt_id=3,
        bitwidth=16,
        sign_bits=1,
        exponent_bits=8,
        mantissa_bits=7,
        exponent_bias=127,
        has_inf=True,
        has_nan=True,
        is_integer=False,
        is_signed=True,
        scale_factor_type=None,
        scale_block_size=1,
        scale_bits_per_block=0,
        elements_per_word32=2,
        fp16_throughput_multiplier=1.0,
        effective_bits_per_element_with_scale=16.0,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="bfloat16",
    ),
    "TF32": NumericFormatSpec(
        format_id="TF32",
        tcu_fmt_id=1,
        bitwidth=32,
        sign_bits=1,
        exponent_bits=8,
        mantissa_bits=10,
        exponent_bias=127,
        has_inf=True,
        has_nan=True,
        is_integer=False,
        is_signed=True,
        scale_factor_type=None,
        scale_block_size=1,
        scale_bits_per_block=0,
        elements_per_word32=1,
        fp16_throughput_multiplier=0.5,
        effective_bits_per_element_with_scale=32.0,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="TensorFloat-32 (19 significant bits in 32-bit container)",
    ),
    "FP8_E4M3": NumericFormatSpec(
        format_id="FP8_E4M3",
        tcu_fmt_id=4,
        bitwidth=8,
        sign_bits=1,
        exponent_bits=4,
        mantissa_bits=3,
        exponent_bias=7,
        has_inf=False,
        has_nan=True,
        is_integer=False,
        is_signed=True,
        scale_factor_type=None,
        scale_block_size=1,
        scale_bits_per_block=0,
        elements_per_word32=4,
        fp16_throughput_multiplier=2.0,
        effective_bits_per_element_with_scale=8.0,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="OFG FP8 E4M3FN (NaN at S.1111.111)",
    ),
    "FP8_E5M2": NumericFormatSpec(
        format_id="FP8_E5M2",
        tcu_fmt_id=5,
        bitwidth=8,
        sign_bits=1,
        exponent_bits=5,
        mantissa_bits=2,
        exponent_bias=15,
        has_inf=True,
        has_nan=True,
        is_integer=False,
        is_signed=True,
        scale_factor_type=None,
        scale_block_size=1,
        scale_bits_per_block=0,
        elements_per_word32=4,
        fp16_throughput_multiplier=2.0,
        effective_bits_per_element_with_scale=8.0,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="OFG FP8 E5M2",
    ),
    "MXFP8": NumericFormatSpec(
        format_id="MXFP8",
        tcu_fmt_id=8,
        bitwidth=8,
        sign_bits=1,
        exponent_bits=4,
        mantissa_bits=3,
        exponent_bias=7,
        has_inf=False,
        has_nan=True,
        is_integer=False,
        is_signed=True,
        scale_factor_type="UE8M0",
        scale_block_size=32,
        scale_bits_per_block=8,
        elements_per_word32=4,
        fp16_throughput_multiplier=2.0,
        effective_bits_per_element_with_scale=8.25,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="OCP Microscaling v1.0 MXFP8 (E4M3/E5M2 + UE8M0 k=32)",
    ),
    "MXFP6_E2M3": NumericFormatSpec(
        format_id="MXFP6_E2M3",
        tcu_fmt_id=12,
        bitwidth=6,
        sign_bits=1,
        exponent_bits=2,
        mantissa_bits=3,
        exponent_bias=1,
        has_inf=False,
        has_nan=False,
        is_integer=False,
        is_signed=True,
        scale_factor_type="UE8M0",
        scale_block_size=32,
        scale_bits_per_block=8,
        elements_per_word32=4,
        fp16_throughput_multiplier=2.0,
        effective_bits_per_element_with_scale=6.25,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="OCP Microscaling v1.0 MXFP6 E2M3 + UE8M0 k=32",
    ),
    "MXFP6_E3M2": NumericFormatSpec(
        format_id="MXFP6_E3M2",
        tcu_fmt_id=13,
        bitwidth=6,
        sign_bits=1,
        exponent_bits=3,
        mantissa_bits=2,
        exponent_bias=3,
        has_inf=False,
        has_nan=False,
        is_integer=False,
        is_signed=True,
        scale_factor_type="UE8M0",
        scale_block_size=32,
        scale_bits_per_block=8,
        elements_per_word32=4,
        fp16_throughput_multiplier=2.0,
        effective_bits_per_element_with_scale=6.25,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="OCP Microscaling v1.0 MXFP6 E3M2 + UE8M0 k=32",
    ),
    "MXFP4_E2M1": NumericFormatSpec(
        format_id="MXFP4_E2M1",
        tcu_fmt_id=10,
        bitwidth=4,
        sign_bits=1,
        exponent_bits=2,
        mantissa_bits=1,
        exponent_bias=1,
        has_inf=False,
        has_nan=False,
        is_integer=False,
        is_signed=True,
        scale_factor_type="UE8M0",
        scale_block_size=32,
        scale_bits_per_block=8,
        elements_per_word32=8,
        fp16_throughput_multiplier=4.0,
        effective_bits_per_element_with_scale=4.25,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="OCP Microscaling v1.0 MXFP4 E2M1 + UE8M0 k=32",
    ),
    "NVFP4_E2M1": NumericFormatSpec(
        format_id="NVFP4_E2M1",
        tcu_fmt_id=11,
        bitwidth=4,
        sign_bits=1,
        exponent_bits=2,
        mantissa_bits=1,
        exponent_bias=1,
        has_inf=False,
        has_nan=False,
        is_integer=False,
        is_signed=True,
        scale_factor_type="E4M3",
        scale_block_size=16,
        scale_bits_per_block=8,
        elements_per_word32=8,
        fp16_throughput_multiplier=4.0,
        effective_bits_per_element_with_scale=4.5,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="FP32",
        standard_ref="Blackwell NVFP4 E2M1 + UE4M3 k=16",
    ),
    "INT8": NumericFormatSpec(
        format_id="INT8",
        tcu_fmt_id=17,
        bitwidth=8,
        sign_bits=1,
        exponent_bits=0,
        mantissa_bits=7,
        exponent_bias=0,
        has_inf=False,
        has_nan=False,
        is_integer=True,
        is_signed=True,
        scale_factor_type=None,
        scale_block_size=1,
        scale_bits_per_block=0,
        elements_per_word32=4,
        fp16_throughput_multiplier=2.0,
        effective_bits_per_element_with_scale=8.0,
        sparse_2_4_metadata_bits_per_4elems=4,
        accumulator_type="INT32",
        standard_ref="Two's-complement signed 8-bit integer",
    ),
}


def validate_numeric_formats() -> list[str]:
    """Validate structural invariants of all TFRv2 numeric formats."""
    errors: list[str] = []
    seen_ids: set[int] = set()
    for name, spec in NUMERIC_FORMATS.items():
        if spec.tcu_fmt_id in seen_ids:
            errors.append(f"Duplicate tcu_fmt_id {spec.tcu_fmt_id} on {name}")
        seen_ids.add(spec.tcu_fmt_id)
        if spec.format_id != name:
            errors.append(f"Format key mismatch: {name} != {spec.format_id}")
        if spec.is_integer:
            if spec.exponent_bits != 0 or spec.exponent_bias != 0:
                errors.append(f"{name}: integer format must have exponent_bits=0 and bias=0")
            if spec.accumulator_type != "INT32":
                errors.append(f"{name}: integer format must accumulate into INT32")
        else:
            if name != "TF32" and (spec.sign_bits + spec.exponent_bits + spec.mantissa_bits != spec.bitwidth):
                errors.append(
                    f"{name}: sign+exp+man ({spec.sign_bits}+{spec.exponent_bits}+{spec.mantissa_bits}) != {spec.bitwidth}"
                )
            if spec.accumulator_type != "FP32":
                errors.append(f"{name}: floating format must accumulate into FP32")
            expected_bias = (1 << (spec.exponent_bits - 1)) - 1
            if spec.exponent_bias != expected_bias:
                errors.append(f"{name}: bias {spec.exponent_bias} != expected {expected_bias}")
        expected_eff = float(spec.bitwidth) + (
            float(spec.scale_bits_per_block) / float(spec.scale_block_size)
            if spec.scale_factor_type is not None
            else 0.0
        )
        if abs(spec.effective_bits_per_element_with_scale - expected_eff) > 1e-9:
            errors.append(
                f"{name}: effective bits {spec.effective_bits_per_element_with_scale} != {expected_eff}"
            )
    return errors


# =============================================================================
# 3. Dedicated Tensor Memory (TMEM) Geometry, Swizzle & Bank-Conflict Model
# =============================================================================

@dataclass(frozen=True)
class TmemGeometrySpec:
    capacity_bytes_per_core: int
    lanes_rows: int
    columns: int
    cell_width_bytes: int
    num_banks: int
    bank_width_bytes: int
    alloc_granule_columns: int
    min_alloc_columns: int
    supported_swizzle_modes: tuple[str, ...]
    read_ports_per_core: int
    write_ports_per_core: int
    supports_double_buffering: bool
    ecc_scheme: str


TMEM_SPEC = TmemGeometrySpec(
    capacity_bytes_per_core=262144,  # 256 KiB/core = 128 lanes * 512 cols * 4 B
    lanes_rows=128,
    columns=512,
    cell_width_bytes=4,
    num_banks=32,
    bank_width_bytes=4,
    alloc_granule_columns=32,
    min_alloc_columns=32,
    supported_swizzle_modes=("NONE", "SWIZZLE_32B", "SWIZZLE_64B", "SWIZZLE_128B"),
    read_ports_per_core=2,
    write_ports_per_core=1,
    supports_double_buffering=True,
    ecc_scheme="SECDED_64_72",
)

TMEM_SWIZZLE_BYTES: dict[str, int] = {
    "NONE": 0,
    "SWIZZLE_32B": 32,
    "SWIZZLE_64B": 64,
    "SWIZZLE_128B": 128,
}


def tmem_swizzled_bank(row: int, col: int, swizzle_mode: str = "NONE") -> int:
    """Compute physical TMEM bank index [0..31] for logical (row, col) and swizzle mode."""
    if swizzle_mode not in TMEM_SWIZZLE_BYTES:
        raise ValueError(f"Unsupported TMEM swizzle mode {swizzle_mode!r}")
    if row < 0 or row >= TMEM_SPEC.lanes_rows:
        raise ValueError(f"TMEM row {row} out of bounds [0, {TMEM_SPEC.lanes_rows})")
    if col < 0 or col >= TMEM_SPEC.columns:
        raise ValueError(f"TMEM col {col} out of bounds [0, {TMEM_SPEC.columns})")
    base_bank = col & (TMEM_SPEC.num_banks - 1)
    if swizzle_mode == "NONE":
        return base_bank
    if swizzle_mode == "SWIZZLE_32B":
        # XOR bits [2:0] of bank with row[2:0] (8-bank = 32 B swizzle atom)
        return base_bank ^ (row & 0x7)
    if swizzle_mode == "SWIZZLE_64B":
        # XOR bits [3:0] of bank with row[3:0] (16-bank = 64 B swizzle atom)
        return base_bank ^ (row & 0xF)
    # SWIZZLE_128B: XOR all 5 bank bits with row[4:0] (32-bank = 128 B full row)
    return base_bank ^ (row & 0x1F)


def analyze_tmem_bank_conflicts(
    coords: list[tuple[int, int]],
    *,
    swizzle_mode: str = "NONE",
) -> dict[str, Any]:
    """Analyze bank conflicts across a simultaneous warp/subwarp TMEM access vector."""
    if not coords:
        raise ValueError("coords must be non-empty")
    bank_hits: dict[int, list[tuple[int, int]]] = {}
    for row, col in coords:
        bank = tmem_swizzled_bank(row, col, swizzle_mode)
        bank_hits.setdefault(bank, []).append((row, col))
    max_ways = max(len(v) for v in bank_hits.values())
    return {
        "swizzle_mode": swizzle_mode,
        "access_count": len(coords),
        "distinct_banks": len(bank_hits),
        "conflict_ways": max_ways,
        "conflict_free": max_ways == 1,
        "serialization_cycles": max_ways,
    }


def validate_tmem_allocation(col_offset: int, num_columns: int, *, num_rows: int = 128) -> dict[str, Any]:
    """Validate TMEM tile allocation alignment, capacity, and double-buffering headroom."""
    if num_rows not in (32, 64, 128):
        raise ValueError(f"TMEM allocation num_rows must be 32, 64, or 128, got {num_rows}")
    if col_offset < 0 or (col_offset % TMEM_SPEC.alloc_granule_columns) != 0:
        raise ValueError(
            f"col_offset={col_offset} must be non-negative multiple of {TMEM_SPEC.alloc_granule_columns}"
        )
    if num_columns < TMEM_SPEC.min_alloc_columns or not _is_power_of_two(num_columns):
        raise ValueError(
            f"num_columns={num_columns} must be power-of-two >= {TMEM_SPEC.min_alloc_columns}"
        )
    if col_offset + num_columns > TMEM_SPEC.columns:
        raise ValueError(
            f"TMEM allocation [{col_offset}, {col_offset + num_columns}) exceeds {TMEM_SPEC.columns} columns"
        )
    allocated_bytes = num_rows * num_columns * TMEM_SPEC.cell_width_bytes
    return {
        "col_offset": col_offset,
        "num_columns": num_columns,
        "num_rows": num_rows,
        "allocated_bytes": allocated_bytes,
        "utilization_pct": round(100.0 * allocated_bytes / TMEM_SPEC.capacity_bytes_per_core, 2),
        "double_buffer_feasible": (col_offset + 2 * num_columns) <= TMEM_SPEC.columns,
    }


# =============================================================================
# 4. 2D Mesh NoC, MOESI Directory & UCIe 2.0 Coherent D2D Specification
# =============================================================================

@dataclass(frozen=True)
class NocMeshSpec:
    rows: int
    cols: int
    flit_bytes: int
    link_freq_mhz: float
    virtual_channels: int
    vc_names: tuple[str, ...]
    routing_algorithm: str
    credit_depth_flits: int
    router_pipeline_stages: int
    unidirectional_link_bw_gbs: float
    bisection_bw_gbs: float


NOC_SPECS: dict[str, NocMeshSpec] = {
    "aigpu-b2-tile": NocMeshSpec(
        rows=1,
        cols=1,
        flit_bytes=64,
        link_freq_mhz=2000.0,
        virtual_channels=4,
        vc_names=("VC0_REQ", "VC1_RSP", "VC2_SNP", "VC3_WB"),
        routing_algorithm="XY_DIMENSION_ORDER",
        credit_depth_flits=8,
        router_pipeline_stages=2,
        unidirectional_link_bw_gbs=128.0,
        bisection_bw_gbs=256.0,
    ),
    "aigpu-b2": NocMeshSpec(
        rows=4,
        cols=2,
        flit_bytes=64,
        link_freq_mhz=2000.0,
        virtual_channels=4,
        vc_names=("VC0_REQ", "VC1_RSP", "VC2_SNP", "VC3_WB"),
        routing_algorithm="XY_DIMENSION_ORDER",
        credit_depth_flits=16,
        router_pipeline_stages=2,
        unidirectional_link_bw_gbs=128.0,
        # 4 rows x 2 cols with doubled 2x64B dual-ring/mesh trunk (256 GB/s/dir):
        # 4-row horizontal cut = 4 links * 2 dirs * 256 GB/s = 2,048 GB/s bisection;
        # 2-column vertical cut = 2 links * 2 dirs * 256 GB/s = 1,024 GB/s.
        bisection_bw_gbs=2048.0,
    ),
    "aigpu-b2-dual": NocMeshSpec(
        rows=4,
        cols=4,
        flit_bytes=64,
        link_freq_mhz=2000.0,
        virtual_channels=4,
        vc_names=("VC0_REQ", "VC1_RSP", "VC2_SNP", "VC3_WB"),
        routing_algorithm="XY_DIMENSION_ORDER",
        credit_depth_flits=16,
        router_pipeline_stages=2,
        unidirectional_link_bw_gbs=128.0,
        bisection_bw_gbs=10000.0,
    ),
}


def compute_xy_route(
    src: tuple[int, int],
    dst: tuple[int, int],
    *,
    rows: int = 4,
    cols: int = 2,
) -> list[tuple[int, int]]:
    """Deterministic deadlock-free XY dimension-order path from src (x,y) to dst (x,y)."""
    sx, sy = src
    dx, dy = dst
    if not (0 <= sx < cols and 0 <= sy < rows):
        raise ValueError(f"src {src} outside {cols}x{rows} mesh")
    if not (0 <= dx < cols and 0 <= dy < rows):
        raise ValueError(f"dst {dst} outside {cols}x{rows} mesh")
    path = [(sx, sy)]
    cx, cy = sx, sy
    while cx != dx:
        cx += 1 if dx > cx else -1
        path.append((cx, cy))
    while cy != dy:
        cy += 1 if dy > cy else -1
        path.append((cx, cy))
    return path


def verify_xy_routing_deadlock_free(rows: int, cols: int) -> dict[str, Any]:
    """Verify turn-model deadlock freedom (West-First / XY forbids Y->X turns) over all pairs."""
    pairs_checked = 0
    max_hops = 0
    total_hops = 0
    for sy in range(rows):
        for sx in range(cols):
            for dy in range(rows):
                for dx in range(cols):
                    path = compute_xy_route((sx, sy), (dx, dy), rows=rows, cols=cols)
                    hops = len(path) - 1
                    if hops != abs(dx - sx) + abs(dy - sy):
                        raise AssertionError("XY route is not minimal Manhattan distance")
                    # Ensure no Y-axis step precedes an X-axis step (West-First / XY turn invariant)
                    seen_y_step = False
                    for idx in range(len(path) - 1):
                        px, py = path[idx]
                        nx, ny = path[idx + 1]
                        if ny != py:
                            seen_y_step = True
                        if nx != px and seen_y_step:
                            raise AssertionError(f"Illegal Y->X turn in XY route {path}")
                    pairs_checked += 1
                    max_hops = max(max_hops, hops)
                    total_hops += hops
    return {
        "rows": rows,
        "cols": cols,
        "nodes": rows * cols,
        "pairs_checked": pairs_checked,
        "max_manhattan_hops": max_hops,
        "avg_hops": round(total_hops / max(1, pairs_checked), 3),
        "deadlock_free": True,
    }


@dataclass(frozen=True)
class MoesiDirectorySpec:
    protocol: str
    states: tuple[str, ...]
    cache_line_bytes: int
    sector_bytes: int
    interleave_granule_bytes: int
    slices_per_die: int
    slice_capacity_bytes: int
    ways: int
    banks_per_slice: int
    snoop_filter_entries_per_slice: int
    snoop_filter_ways: int


MOESI_SPEC = MoesiDirectorySpec(
    protocol="MOESI_DIRECTORY_INCLUSIVE_SF",
    states=("M", "O", "E", "S", "I"),
    cache_line_bytes=128,
    sector_bytes=64,
    interleave_granule_bytes=256,
    slices_per_die=8,
    slice_capacity_bytes=16 * 1024 * 1024,
    ways=16,
    banks_per_slice=8,
    snoop_filter_entries_per_slice=65536,
    snoop_filter_ways=16,
)


def compute_home_node(phys_addr: int, *, num_dies: int = 1, slices_per_die: int = 8) -> dict[str, int]:
    """Compute coherent home die and L2/SLC MOESI directory slice via XOR-folded PA hash."""
    if phys_addr < 0:
        raise ValueError(f"phys_addr must be non-negative, got {phys_addr}")
    if num_dies not in (1, 2):
        raise ValueError(f"num_dies must be 1 or 2, got {num_dies}")
    if not _is_power_of_two(slices_per_die):
        raise ValueError(f"slices_per_die must be power of two, got {slices_per_die}")
    # 256 B interleave granule => line/granule index starts at PA[8]
    granule = phys_addr >> 8
    die_id = (granule ^ (granule >> 6) ^ (granule >> 12)) & (num_dies - 1) if num_dies == 2 else 0
    slice_shift = 1 if num_dies == 2 else 0
    s_idx_raw = (granule >> slice_shift) ^ (granule >> (slice_shift + 4)) ^ (granule >> (slice_shift + 9))
    slice_id = s_idx_raw & (slices_per_die - 1)
    hbm_channel = (slice_id * 8) + ((phys_addr >> 11) & 0x7)
    return {
        "die_id": die_id,
        "slice_id": slice_id,
        "global_slice_id": die_id * slices_per_die + slice_id,
        "hbm_pseudo_channel": hbm_channel,
    }


@dataclass(frozen=True)
class UcieD2dSpec:
    standard: str
    packaging: str
    data_rate_gt_per_pin: float
    lanes_per_module: int
    modules_per_die_edge: int
    total_lanes_bidirectional: int
    raw_bandwidth_gbs_total: float
    protocol_efficiency: float
    effective_bandwidth_gbs_total: float
    flit_bits: int
    crc_bits: int
    retry_buffer_entries: int
    credit_vcs: int
    d2d_interleave_bytes: int
    nominal_roundtrip_ns: float


UCIE_SPEC = UcieD2dSpec(
    standard="UCIe_2.0_Coherent_Streaming",
    packaging="CoWoS-L_Silicon_Bridge",
    data_rate_gt_per_pin=32.0,
    lanes_per_module=64,
    modules_per_die_edge=40,
    total_lanes_bidirectional=2560,
    raw_bandwidth_gbs_total=10240.0,
    protocol_efficiency=0.9765625,
    effective_bandwidth_gbs_total=10000.0,
    flit_bits=512,
    crc_bits=16,
    retry_buffer_entries=128,
    credit_vcs=4,
    d2d_interleave_bytes=256,
    nominal_roundtrip_ns=12.0,
)


# =============================================================================
# 5. HBM3E Timing, Hardware Decompression ABI & 5D DXA/TMA Descriptor Spec
# =============================================================================

@dataclass(frozen=True)
class Hbm3eSpec:
    jedec_generation: str
    pin_rate_gbps: float
    stack_width_bits: int
    pseudo_channels_per_stack: int
    pc_width_bits: int
    bank_groups_per_pc: int
    banks_per_group: int
    row_size_bytes: int
    burst_length: int
    atom_bytes: int
    clock_ck_mhz: float
    t_rcd_ck: int
    t_rp_ck: int
    t_ras_ck: int
    t_rc_ck: int
    t_rrd_s_ck: int
    t_rrd_l_ck: int
    t_faw_ck: int
    t_refi_ns: int
    t_rfc_ns: int
    ecc_scheme: str
    ecc_overhead_bits_per_256b: int


HBM3E_SPEC = Hbm3eSpec(
    jedec_generation="JESD238A_HBM3E",
    pin_rate_gbps=3.90625,
    stack_width_bits=1024,
    pseudo_channels_per_stack=8,
    pc_width_bits=128,
    bank_groups_per_pc=4,
    banks_per_group=4,
    row_size_bytes=2048,
    burst_length=4,
    atom_bytes=64,
    clock_ck_mhz=1953.0,
    t_rcd_ck=28,
    t_rp_ck=28,
    t_ras_ck=64,
    t_rc_ck=92,
    t_rrd_s_ck=4,
    t_rrd_l_ck=6,
    t_faw_ck=16,
    t_refi_ns=3900,
    t_rfc_ns=350,
    ecc_scheme="SECDED_PLUS_ON_DIE_CHIPKILL",
    ecc_overhead_bits_per_256b=32,
)


@dataclass(frozen=True)
class DecompCodecSpec:
    codec_id: int
    name: str
    max_block_bytes: int
    window_bytes: int
    target_throughput_gbs_per_engine: float
    supports_fp4_weight_unpack: bool
    crc32c_verified: bool


DECOMP_CODECS: dict[str, DecompCodecSpec] = {
    "LZ4": DecompCodecSpec(0, "LZ4", 65536, 65536, 64.0, False, True),
    "SNAPPY": DecompCodecSpec(1, "SNAPPY", 65536, 65536, 64.0, False, True),
    "DEFLATE": DecompCodecSpec(2, "DEFLATE", 65536, 32768, 32.0, False, True),
    "BITCOMP": DecompCodecSpec(3, "BITCOMP", 131072, 0, 128.0, True, True),
}

DECOMP_DESCRIPTOR_FIELDS: tuple[tuple[str, int, int, str], ...] = (
    ("src_addr_lo", 0, 31, "Source compressed buffer PA/VA[31:0]"),
    ("src_addr_hi", 32, 63, "Source compressed buffer PA/VA[63:32]"),
    ("dst_addr_lo", 64, 95, "Destination L2/LMEM/TMEM buffer address[31:0]"),
    ("dst_addr_hi", 96, 127, "Destination L2/LMEM/TMEM buffer address[63:32]"),
    ("src_bytes", 128, 159, "Compressed payload size in bytes"),
    ("dst_bytes", 160, 191, "Expected uncompressed size in bytes"),
    ("codec_id", 192, 195, "0=LZ4, 1=SNAPPY, 2=DEFLATE, 3=BITCOMP"),
    ("dst_space", 196, 197, "0=GMEM/L2, 1=LMEM, 2=TMEM"),
    ("crc_enable", 198, 198, "Verify CRC32C trailer"),
    ("mcast_mask", 199, 214, "Cluster/CTA multicast destination mask"),
    ("barrier_id", 215, 222, "Hardware mbarrier ID for expect-tx completion"),
    ("reserved", 223, 255, "Zero-reserved for future codec flags"),
)


def validate_dxa_5d_descriptor(
    *,
    global_dims: tuple[int, int, int, int, int],
    box_dims: tuple[int, int, int, int, int],
    element_strides: tuple[int, int, int, int, int],
    element_bytes: float,
    swizzle_mode: str = "NONE",
    multicast_clusters: int = 1,
) -> dict[str, Any]:
    """Validate a 5D DXA/TMA async tensor copy/multicast descriptor."""
    if len(global_dims) != 5 or len(box_dims) != 5 or len(element_strides) != 5:
        raise ValueError("5D DXA descriptor requires 5-element tuples")
    if swizzle_mode not in TMEM_SWIZZLE_BYTES:
        raise ValueError(f"Unsupported swizzle_mode {swizzle_mode!r}")
    if multicast_clusters < 1 or multicast_clusters > 16:
        raise ValueError(f"multicast_clusters={multicast_clusters} out of range [1, 16]")
    if element_bytes not in (0.5, 1.0, 2.0, 4.0):
        raise ValueError(f"Unsupported element_bytes={element_bytes}")
    total_elems = 1
    for axis in range(5):
        g = global_dims[axis]
        b = box_dims[axis]
        s = element_strides[axis]
        if g <= 0 or b <= 0 or b > 256:
            raise ValueError(f"Axis {axis}: invalid global={g} or box={b} (box in [1,256])")
        if b > g:
            raise ValueError(f"Axis {axis}: box_dim {b} exceeds global_dim {g}")
        if s < 1:
            raise ValueError(f"Axis {axis}: element_stride {s} must be >= 1")
        if axis > 0 and g > 1:
            min_stride = element_strides[axis - 1] * global_dims[axis - 1]
            if s < min_stride:
                raise ValueError(
                    f"Axis {axis}: element_stride {s} aliases prior axis "
                    f"(expected >= {min_stride})"
                )
        total_elems *= b
    box_bytes = int(math.ceil(total_elems * element_bytes))
    swizzle_atom = TMEM_SWIZZLE_BYTES[swizzle_mode]
    if swizzle_atom > 0:
        inner_bytes = int(math.ceil(box_dims[0] * element_bytes))
        if (inner_bytes % 16) != 0:
            raise ValueError(f"Swizzled inner dimension bytes ({inner_bytes}) must be 16B-aligned")
    return {
        "valid": True,
        "box_elements": total_elems,
        "box_bytes": box_bytes,
        "aligned_tx_bytes": _align_up(box_bytes, 16),
        "swizzle_mode": swizzle_mode,
        "multicast_clusters": multicast_clusters,
    }


# =============================================================================
# 6. SoC MMIO Map, GigaThread Doorbells, MIG Profiles, PCIe/IOMMU, RAS/PMU/CC
# =============================================================================

@dataclass(frozen=True)
class MmioRegion:
    name: str
    base_addr: int
    size_bytes: int
    access: str
    owner: str
    description: str

    @property
    def end_addr(self) -> int:
        return self.base_addr + self.size_bytes


MMIO_REGION_MAP: tuple[MmioRegion, ...] = (
    MmioRegion("BAR0_DEVICE_ID_REV", 0x0000_0000, 0x0001_0000, "RO", "SOC_TOP", "PCIe vendor/device ID, SKU fuses, capabilities"),
    MmioRegion("BAR0_GIGATHREAD_CP", 0x0001_0000, 0x0004_0000, "RW", "CP_B2", "GigaThread Command Processor global CSRs & preemption"),
    MmioRegion("BAR0_DOORBELL_PAGE", 0x0005_0000, 0x0004_0000, "WO", "CP_B2", "64 hardware work queues x 4 KiB isolated doorbell pages"),
    MmioRegion("BAR0_MIG_PARTITIONER", 0x0009_0000, 0x0001_0000, "RW", "MIG", "MIG cluster/L2-way/HBM-channel/NoC-QoS partition table"),
    MmioRegion("BAR0_IOMMU_SV48", 0x000A_0000, 0x0002_0000, "RW", "PCIE_IOMMU", "SV48 root directory, PASID table, ATS/PRI fault ring"),
    MmioRegion("BAR0_PCIE_DMA_MSIX", 0x000C_0000, 0x0004_0000, "RW", "PCIE_DMA", "PCIe Gen6 x16 8-channel scatter-gather DMA & MSI-X table"),
    MmioRegion("BAR0_HBM3E_CTRL", 0x0010_0000, 0x0008_0000, "RW", "HBM3E", "8-stack/16-stack HBM3E MC registers & refresh telemetry"),
    MmioRegion("BAR0_NOC_L2_DIR", 0x0018_0000, 0x0004_0000, "RW", "NOC_COH", "2D Mesh NoC QoS weights & MOESI directory slice registers"),
    MmioRegion("BAR0_UCIE_D2D", 0x001C_0000, 0x0002_0000, "RW", "UCIE", "UCIe 2.0 link-training FSM, CRC/retry, credit counters"),
    MmioRegion("BAR0_DECOMP_ENGINE", 0x001E_0000, 0x0002_0000, "RW", "DE", "Hardware Decompression Engine queue & perf counters"),
    MmioRegion("BAR0_RAS_MCA_ECC", 0x0020_0000, 0x0004_0000, "RW", "RAS", "Machine-Check banks, ECC scrubbers & error-injection ports"),
    MmioRegion("BAR0_PMU_DVFS_THERM", 0x0024_0000, 0x0004_0000, "RW", "PMU", "Cluster DVFS PLLs, power-proxy, thermal governor & PMU events"),
    MmioRegion("BAR0_CONF_COMP_SEC", 0x0028_0000, 0x0004_0000, "RW", "SEC", "Secure-boot RoT, SPDM measurements & AES-256-GCM keyslots"),
    MmioRegion("BAR0_DEBUG_JTAG_DFT", 0x002C_0000, 0x0004_0000, "RW", "DFT", "RISC-V Debug Module, trace funnel & MBIST controller"),
)


def validate_mmio_map() -> list[str]:
    """Ensure every MMIO aperture is page-aligned and strictly non-overlapping."""
    errors: list[str] = []
    ordered = sorted(MMIO_REGION_MAP, key=lambda r: r.base_addr)
    for idx, region in enumerate(ordered):
        if region.size_bytes <= 0 or (region.base_addr % 4096) != 0 or (region.size_bytes % 4096) != 0:
            errors.append(f"{region.name}: base/size must be 4 KiB aligned and positive")
        if idx > 0:
            prev = ordered[idx - 1]
            if prev.end_addr > region.base_addr:
                errors.append(
                    f"MMIO overlap: {prev.name} ends at 0x{prev.end_addr:x} > "
                    f"{region.name} base 0x{region.base_addr:x}"
                )
    return errors


GIGATHREAD_NUM_QUEUES = 64
GIGATHREAD_DOORBELL_STRIDE_BYTES = 4096
GIGATHREAD_DOORBELL_BASE = 0x0005_0000


def gigathread_doorbell_address(queue_id: int) -> int:
    """Return isolated 4 KiB MMIO doorbell address for hardware queue_id [0..63]."""
    if not (0 <= queue_id < GIGATHREAD_NUM_QUEUES):
        raise ValueError(f"queue_id={queue_id} out of range [0, {GIGATHREAD_NUM_QUEUES})")
    return GIGATHREAD_DOORBELL_BASE + queue_id * GIGATHREAD_DOORBELL_STRIDE_BYTES


@dataclass(frozen=True)
class MigProfileSpec:
    profile_id: str
    max_instances: int
    clusters_per_instance: int
    cores_per_instance: int
    l2_ways_per_instance: int
    l2_size_mib_per_instance: int
    hbm_stacks_per_instance: int
    hbm_bw_gbs_per_instance: float
    tmem_mib_per_instance: float
    cp_queues_per_instance: int


MIG_PROFILES: dict[str, MigProfileSpec] = {
    "1g.12gb": MigProfileSpec("1g.12gb", 8, 1, 16, 2, 16, 1, 500.0, 4.0, 8),
    "2g.24gb": MigProfileSpec("2g.24gb", 4, 2, 32, 4, 32, 2, 1000.0, 8.0, 16),
    "4g.48gb": MigProfileSpec("4g.48gb", 2, 4, 64, 8, 64, 4, 2000.0, 16.0, 32),
    "8g.96gb": MigProfileSpec("8g.96gb", 1, 8, 128, 16, 128, 8, 4000.0, 32.0, 64),
}


@dataclass(frozen=True)
class MigAllocation:
    instance_id: int
    profile_id: str
    cluster_mask: int
    l2_way_mask: int
    hbm_stack_mask: int
    queue_mask: int


def validate_mig_partition_plan(allocations: list[MigAllocation], *, num_dies: int = 1) -> list[str]:
    """Verify a set of MIG instances has disjoint clusters, L2 ways, HBM stacks, and queues."""
    errors: list[str] = []
    used_clusters = 0
    used_l2_ways = 0
    used_hbm = 0
    used_queues = 0
    seen_instance_ids: set[int] = set()
    max_clusters = 8 * num_dies
    max_l2_ways = 16
    max_hbm = 8 * num_dies
    max_queues = GIGATHREAD_NUM_QUEUES * num_dies

    for alloc in allocations:
        if alloc.instance_id < 0:
            errors.append(f"Instance {alloc.instance_id}: instance_id must be non-negative")
        elif alloc.instance_id in seen_instance_ids:
            errors.append(f"Duplicate MIG instance_id {alloc.instance_id}")
        else:
            seen_instance_ids.add(alloc.instance_id)
        if alloc.profile_id not in MIG_PROFILES:
            errors.append(f"Unknown MIG profile {alloc.profile_id!r}")
            continue
        prof = MIG_PROFILES[alloc.profile_id]
        if bin(alloc.cluster_mask).count("1") != prof.clusters_per_instance:
            errors.append(f"Instance {alloc.instance_id}: cluster_mask popcount != {prof.clusters_per_instance}")
        if bin(alloc.l2_way_mask).count("1") != prof.l2_ways_per_instance:
            errors.append(f"Instance {alloc.instance_id}: l2_way_mask popcount != {prof.l2_ways_per_instance}")
        if bin(alloc.hbm_stack_mask).count("1") != prof.hbm_stacks_per_instance:
            errors.append(f"Instance {alloc.instance_id}: hbm_stack_mask popcount != {prof.hbm_stacks_per_instance}")
        if bin(alloc.queue_mask).count("1") != prof.cp_queues_per_instance:
            errors.append(f"Instance {alloc.instance_id}: queue_mask popcount != {prof.cp_queues_per_instance}")
        if alloc.cluster_mask & ~_bitmask(max_clusters):
            errors.append(f"Instance {alloc.instance_id}: cluster_mask exceeds die clusters")
        if alloc.l2_way_mask & ~_bitmask(max_l2_ways):
            errors.append(f"Instance {alloc.instance_id}: l2_way_mask exceeds 16 ways")
        if alloc.hbm_stack_mask & ~_bitmask(max_hbm):
            errors.append(f"Instance {alloc.instance_id}: hbm_stack_mask exceeds {max_hbm} stacks")
        if alloc.queue_mask & ~_bitmask(max_queues):
            errors.append(f"Instance {alloc.instance_id}: queue_mask exceeds {max_queues} queues")

        if used_clusters & alloc.cluster_mask:
            errors.append(f"Instance {alloc.instance_id}: overlapping cluster_mask")
        if used_l2_ways & alloc.l2_way_mask:
            errors.append(f"Instance {alloc.instance_id}: overlapping l2_way_mask")
        if used_hbm & alloc.hbm_stack_mask:
            errors.append(f"Instance {alloc.instance_id}: overlapping hbm_stack_mask")
        if used_queues & alloc.queue_mask:
            errors.append(f"Instance {alloc.instance_id}: overlapping queue_mask")

        used_clusters |= alloc.cluster_mask
        used_l2_ways |= alloc.l2_way_mask
        used_hbm |= alloc.hbm_stack_mask
        used_queues |= alloc.queue_mask

    return errors


# PCIe Gen6 x16 BARs & SV48 IOMMU PTE bitfields
PCIE_BAR_LAYOUT: tuple[dict[str, Any], ...] = (
    {"bar": "BAR0", "size_mib": 16, "type": "MEM32_NP", "purpose": "SoC MMIO registers & isolated queue doorbells"},
    {"bar": "BAR2", "size_mib": 262144, "type": "MEM64_PREFETCH", "purpose": "Resolvable HBM3E VRAM aperture (up to 256 GiB)"},
    {"bar": "BAR4", "size_mib": 64, "type": "MEM64_PREFETCH", "purpose": "MSI-X PBA/vector table & SR-IOV VF doorbell mirror"},
)

SV48_PTE_BITS: dict[str, tuple[int, int, str]] = {
    "V": (0, 0, "Valid translation entry"),
    "R": (1, 1, "Readable page"),
    "W": (2, 2, "Writable page"),
    "X": (3, 3, "Executable kernel instruction page"),
    "U": (4, 4, "User-mode accessible"),
    "G": (5, 5, "Global mapping across PASIDs"),
    "A": (6, 6, "Accessed hardware bit"),
    "D": (7, 7, "Dirty hardware bit"),
    "RSW": (8, 9, "Software-reserved bits"),
    "PPN": (10, 53, "44-bit physical page number (56-bit PA)"),
    "ENC": (54, 54, "Confidential Computing AES-256-GCM memory encryption bit"),
    "PBMT": (61, 62, "Page-based memory type (0=PMA, 1=NC, 2=IO)"),
    "N": (63, 63, "NAPOT 64 KiB contiguous hint"),
}


def encode_sv48_pte(
    ppn: int,
    *,
    read: bool = True,
    write: bool = True,
    exec_perm: bool = False,
    user: bool = True,
    encrypted: bool = False,
) -> int:
    """Encode a 64-bit SV48 IOMMU/MMU page-table entry."""
    if ppn < 0 or ppn >= (1 << 44):
        raise ValueError(f"PPN {ppn:#x} out of 44-bit SV48 range")
    pte = 1  # V=1
    if read:
        pte |= 1 << 1
    if write:
        pte |= 1 << 2
    if exec_perm:
        pte |= 1 << 3
    if user:
        pte |= 1 << 4
    pte |= (ppn & _bitmask(44)) << 10
    if encrypted:
        pte |= 1 << 54
    return pte


def decode_sv48_pte(pte: int) -> dict[str, Any]:
    """Decode a 64-bit SV48 IOMMU/MMU page-table entry into named fields."""
    return {
        "valid": bool(pte & (1 << 0)),
        "read": bool(pte & (1 << 1)),
        "write": bool(pte & (1 << 2)),
        "exec": bool(pte & (1 << 3)),
        "user": bool(pte & (1 << 4)),
        "global": bool(pte & (1 << 5)),
        "accessed": bool(pte & (1 << 6)),
        "dirty": bool(pte & (1 << 7)),
        "ppn": (pte >> 10) & _bitmask(44),
        "encrypted": bool(pte & (1 << 54)),
        "pbmt": (pte >> 61) & 0x3,
        "napot": bool(pte & (1 << 63)),
    }


# RAS Machine-Check Architecture (MCA) Banks, PMU Events, Confidential Computing
RAS_MCA_BANKS: tuple[dict[str, Any], ...] = (
    {"bank_id": 0, "subsystem": "CORE_RF_IC_DC", "ecc": "SECDED", "scrub": True, "poison_prop": True},
    {"bank_id": 1, "subsystem": "TMEM", "ecc": "SECDED_64_72", "scrub": True, "poison_prop": True},
    {"bank_id": 2, "subsystem": "L2_SLC_DATA_TAG", "ecc": "SECDED", "scrub": True, "poison_prop": True},
    {"bank_id": 3, "subsystem": "NOC_MESH_FLIT", "ecc": "SECDED_CRC16", "scrub": False, "poison_prop": True},
    {"bank_id": 4, "subsystem": "HBM3E_DRAM", "ecc": "SECDED_CHIPKILL", "scrub": True, "poison_prop": True},
    {"bank_id": 5, "subsystem": "UCIE_D2D", "ecc": "CRC16_RETRY", "scrub": False, "poison_prop": True},
    {"bank_id": 6, "subsystem": "PCIE_GEN6_DMA", "ecc": "ECRC_SECDED", "scrub": False, "poison_prop": True},
    {"bank_id": 7, "subsystem": "CP_IOMMU_SEC", "ecc": "SECDED", "scrub": True, "poison_prop": True},
)

PMU_EVENT_CATALOG: tuple[dict[str, Any], ...] = (
    {"event_id": 0x0001, "name": "CYCLES_ACTIVE", "domain": "CORE"},
    {"event_id": 0x0002, "name": "INST_RETIRED", "domain": "CORE"},
    {"event_id": 0x0100, "name": "TFRV2_MMA_CYCLES", "domain": "TCU"},
    {"event_id": 0x0101, "name": "TFRV2_SPARSE_MMA_CYCLES", "domain": "TCU"},
    {"event_id": 0x0102, "name": "TMEM_BANK_CONFLICTS", "domain": "TMEM"},
    {"event_id": 0x0200, "name": "NOC_FLITS_SENT", "domain": "NOC"},
    {"event_id": 0x0201, "name": "NOC_CREDIT_STALLS", "domain": "NOC"},
    {"event_id": 0x0202, "name": "MOESI_SNOOP_HITS", "domain": "COHERENCE"},
    {"event_id": 0x0203, "name": "UCIE_D2D_FLITS", "domain": "UCIE"},
    {"event_id": 0x0300, "name": "HBM3E_ROW_HITS", "domain": "HBM3E"},
    {"event_id": 0x0301, "name": "HBM3E_ROW_MISSES", "domain": "HBM3E"},
    {"event_id": 0x0302, "name": "DECOMP_BYTES_IN", "domain": "DE"},
    {"event_id": 0x0303, "name": "DECOMP_BYTES_OUT", "domain": "DE"},
    {"event_id": 0x0400, "name": "CP_QUEUE_DISPATCHES", "domain": "CP"},
    {"event_id": 0x0401, "name": "IOMMU_TLB_MISSES", "domain": "PCIE_IOMMU"},
    {"event_id": 0x0500, "name": "THERMAL_THROTTLE_CYCLES", "domain": "PMU"},
)

CONF_COMP_SPEC: dict[str, Any] = {
    "attestation_protocol": "DMTF_SPDM_1_2",
    "root_of_trust": "ROM_ECDSA_P384_MEASURED_BOOT",
    "memory_encryption_cipher": "AES-256-GCM",
    "pcie_ide_cipher": "AES-256-GCM-96b-TAG",
    "key_slots": 64,
    "iv_bits": 96,
    "auth_tag_bits": 128,
    "granule_bytes": 64,
    "per_mig_key_isolation": True,
}


# =============================================================================
# 7. Live Profile Validation & Cross-Pillar Consistency Checks
# =============================================================================

def _load_profile_reference(sku_id: str, profiles_dir: Path, _seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Load and merge a profile's reference dictionary strictly from profiles_dir."""
    if sku_id in _seen:
        raise ValueError(f"Profile inheritance cycle: {' -> '.join(_seen + (sku_id,))}")
    profile_path = Path(profiles_dir) / f"{sku_id}.json"
    if not profile_path.is_file():
        raise FileNotFoundError(f"Profile not found in {profiles_dir}: {profile_path}")
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    ref: dict[str, Any] = {}
    if "extends" in data:
        ref.update(_load_profile_reference(str(data["extends"]), profiles_dir, _seen + (sku_id,)))
    ref.update(data.get("reference", {}))
    return ref


def validate_b2_profiles_against_gen_config(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, dict[str, Any]]:
    """Resolve and verify all three B2 profiles through ci/gen_config.py + ci/profile_check.py."""
    gen_config = _load_module("b2_spec_gen_config", REPO_ROOT / "ci/gen_config.py")
    profile_check = _load_module("b2_spec_profile_check", REPO_ROOT / "ci/profile_check.py")

    toml_data = gen_config._load_toml(str(config_path))
    defaults, layout = gen_config._flatten_with_layout(toml_data)
    enums = gen_config._load_enums(toml_data)
    builtins = gen_config._load_var_table(toml_data, "builtin")
    params = gen_config._load_var_table(toml_data, "param")
    ro = set(builtins) | set(params)

    resolved_by_sku: dict[str, dict[str, Any]] = {}
    for sku_id in B2_SKUS:
        prof = gen_config.load_profile(sku_id, str(profiles_dir))
        gen_config.validate_profile(prof, defaults, enums, ro)
        if prof.xlen != 64:
            raise ValueError(f"{sku_id}: expected xlen=64, got {prof.xlen}")

        overrides = dict(prof.values)
        overrides["VX_CFG_XLEN"] = 64
        overrides["VX_CFG_XLEN_64"] = True
        resolver = gen_config.Resolver(
            base=defaults,
            overrides=overrides,
            enums=enums,
            builtins=builtins,
            params=params,
        )
        cfg = {k: resolver.resolve(k) for k in layout.ordered_keys}
        for k in enums:
            if k not in cfg:
                cfg[k] = resolver.resolve(k)

        sku = SKU_SPECS[sku_id]
        if cfg["VX_CFG_NUM_CLUSTERS"] * cfg["VX_CFG_NUM_CORES"] != sku.total_cores:
            raise ValueError(f"{sku_id}: resolved total_cores mismatch")
        if cfg["VX_CFG_NUM_WARPS"] != sku.warps_per_core or cfg["VX_CFG_NUM_THREADS"] != sku.threads_per_warp:
            raise ValueError(f"{sku_id}: resolved warp/thread geometry mismatch")
        if cfg["VX_CFG_NUM_TCU_BLOCKS"] != sku.tcu_blocks_per_core:
            raise ValueError(f"{sku_id}: resolved TCU block count mismatch")
        if cfg["VX_CFG_L2_SIZE"] != sku.l2_total_bytes:
            raise ValueError(f"{sku_id}: resolved L2 size mismatch")
        if float(cfg["VX_CFG_PLATFORM_CLOCK_RATE"]) != sku.clock_mhz:
            raise ValueError(f"{sku_id}: resolved clock_mhz mismatch")
        if float(cfg["VX_CFG_PLATFORM_MEMORY_PEAK_BW"]) / 1000.0 != sku.hbm_bandwidth_gbs:
            raise ValueError(f"{sku_id}: resolved HBM/DRAM bandwidth mismatch")

        # Verify ci/profile_check.py peak metrics match the reference inside profiles_dir
        ref = _load_profile_reference(sku_id, Path(profiles_dir))
        cfg_for_check = dict(cfg)
        if cfg.get("VX_CFG_L2_ENABLE"):
            cfg_for_check["VX_CFG_L2_ENABLED"] = 1
        if cfg.get("VX_CFG_EXT_TCU_ENABLE"):
            cfg_for_check["VX_CFG_EXT_TCU_ENABLED"] = 1
        measured = profile_check.peak_metrics(cfg_for_check, ref)
        for key, val in measured.items():
            if abs(float(val) - float(ref[key])) > 1e-6:
                raise ValueError(f"{sku_id}: profile_check {key}={val} != ref={ref[key]}")

        resolved_by_sku[sku_id] = cfg

    return resolved_by_sku


def validate_all_contracts(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Run every cross-pillar contract validator and return a structured report."""
    errors: list[str] = []
    errors.extend(validate_numeric_formats())
    errors.extend(validate_mmio_map())

    # Validate TMEM bank-conflict elimination under SWIZZLE_128B for column reads across 32 rows
    col_coords = [(r, 0) for r in range(32)]
    none_res = analyze_tmem_bank_conflicts(col_coords, swizzle_mode="NONE")
    swz_res = analyze_tmem_bank_conflicts(col_coords, swizzle_mode="SWIZZLE_128B")
    if none_res["conflict_free"]:
        errors.append("Expected column read across 32 rows to conflict without swizzle")
    if not swz_res["conflict_free"]:
        errors.append("SWIZZLE_128B failed to eliminate 32-row column bank conflicts")
    validate_tmem_allocation(0, 128, num_rows=128)

    # Validate NoC XY deadlock freedom
    for sku_id, noc in NOC_SPECS.items():
        res = verify_xy_routing_deadlock_free(noc.rows, noc.cols)
        if not res["deadlock_free"]:
            errors.append(f"{sku_id}: XY routing deadlock check failed")

    # Validate MIG full-chip 8x 1g.12gb partition plan
    eight_way = [
        MigAllocation(
            instance_id=i,
            profile_id="1g.12gb",
            cluster_mask=1 << i,
            l2_way_mask=0x3 << (2 * i),
            hbm_stack_mask=1 << i,
            queue_mask=0xFF << (8 * i),
        )
        for i in range(8)
    ]
    errors.extend(validate_mig_partition_plan(eight_way, num_dies=1))

    # Validate SV48 round-trip
    pte = encode_sv48_pte(0x12345, read=True, write=True, exec_perm=False, user=True, encrypted=True)
    dec = decode_sv48_pte(pte)
    if dec["ppn"] != 0x12345 or not dec["encrypted"] or not dec["valid"]:
        errors.append("SV48 PTE round-trip failed")

    # Validate live B2 profiles
    resolved = validate_b2_profiles_against_gen_config(
        config_path=config_path, profiles_dir=profiles_dir
    )

    # Validate throughput reconciliation math
    for sku_id in B2_SKUS:
        rec = build_throughput_reconciliation(sku_id)
        sku = SKU_SPECS[sku_id]
        if abs(rec["vortex_base_tfr_fp16_tflops"] - sku.vortex_base_fp16_tflops) > 1e-4:
            errors.append(f"{sku_id}: Vortex base FP16 mismatch")
        if abs(rec["tfrv2_dense_fp16_tflops"] - sku.tfrv2_fp16_tflops_dense) > 1e-3:
            errors.append(f"{sku_id}: TFRv2 dense FP16 mismatch")

    # Validate HBM3E bandwidth & burst-atom invariants
    if HBM3E_SPEC.burst_length * HBM3E_SPEC.pc_width_bits // 8 != HBM3E_SPEC.atom_bytes:
        errors.append(
            f"HBM3E burst_length*pc_width_bits/8 ({HBM3E_SPEC.burst_length * HBM3E_SPEC.pc_width_bits // 8}) "
            f"!= atom_bytes ({HBM3E_SPEC.atom_bytes})"
        )
    for hbm_sku_id in ("aigpu-b2", "aigpu-b2-dual"):
        sku = SKU_SPECS[hbm_sku_id]
        calc_bw = sku.hbm_stacks * HBM3E_SPEC.stack_width_bits * HBM3E_SPEC.pin_rate_gbps / 8.0
        if abs(calc_bw - sku.hbm_bandwidth_gbs) >= 1e-6:
            errors.append(
                f"{hbm_sku_id}: HBM3E bandwidth invariant mismatch ({calc_bw} != {sku.hbm_bandwidth_gbs})"
            )

    payload = {
        "ok": len(errors) == 0,
        "errors": errors,
        "skus_validated": list(resolved.keys()),
        "numeric_format_count": len(NUMERIC_FORMATS),
        "mmio_region_count": len(MMIO_REGION_MAP),
        "mig_profile_count": len(MIG_PROFILES),
        "mca_bank_count": len(RAS_MCA_BANKS),
        "pmu_event_count": len(PMU_EVENT_CATALOG),
    }
    return stamp_honesty_metadata(payload)


def export_architecture_spec(
    sku_id: str | None = None,
    *,
    validate_profiles: bool = False,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Build the complete machine-readable B2 architecture specification JSON payload."""
    skus = (sku_id,) if sku_id is not None else B2_SKUS
    for s in skus:
        if s not in SKU_SPECS:
            raise ValueError(f"Unknown SKU {s!r}; expected one of {B2_SKUS}")

    sku_payload = {}
    for s in skus:
        sku_payload[s] = {
            "topology": asdict(SKU_SPECS[s]),
            "throughput_reconciliation": build_throughput_reconciliation(s),
            "noc_mesh": asdict(NOC_SPECS[s]),
            "die_area_target_mm2_n4p_est": list(DIE_ESTIMATE_MM2[s]),
            "reticle_limit_mm2": RETICLE_LIMIT_MM2,
        }

    payload: dict[str, Any] = {
        "program": "ADR-007 aigpu-b2 Commercial Pre-Silicon Architecture Specification",
        "skus": sku_payload,
        "tfrv2_numeric_formats": {k: asdict(v) for k, v in NUMERIC_FORMATS.items()},
        "tmem": asdict(TMEM_SPEC),
        "moesi_directory": asdict(MOESI_SPEC),
        "ucie_d2d": asdict(UCIE_SPEC),
        "hbm3e": asdict(HBM3E_SPEC),
        "decompression_engine": {
            "codecs": {k: asdict(v) for k, v in DECOMP_CODECS.items()},
            "descriptor_bits": 256,
            "descriptor_layout": [
                {"field": f, "lsb": lsb, "msb": msb, "description": desc}
                for f, lsb, msb, desc in DECOMP_DESCRIPTOR_FIELDS
            ],
        },
        "soc_mmio_map": [
            {
                "name": r.name,
                "base_hex": f"0x{r.base_addr:08x}",
                "end_hex": f"0x{r.end_addr:08x}",
                "size_bytes": r.size_bytes,
                "access": r.access,
                "owner": r.owner,
                "description": r.description,
            }
            for r in MMIO_REGION_MAP
        ],
        "gigathread_doorbells": {
            "num_queues": GIGATHREAD_NUM_QUEUES,
            "base_hex": f"0x{GIGATHREAD_DOORBELL_BASE:08x}",
            "stride_bytes": GIGATHREAD_DOORBELL_STRIDE_BYTES,
        },
        "mig_profiles": {k: asdict(v) for k, v in MIG_PROFILES.items()},
        "pcie_gen6": {"bars": list(PCIE_BAR_LAYOUT), "iommu_sv48_pte_bits": SV48_PTE_BITS},
        "ras_mca_banks": list(RAS_MCA_BANKS),
        "pmu_events": list(PMU_EVENT_CATALOG),
        "confidential_computing": dict(CONF_COMP_SPEC),
    }

    if validate_profiles:
        payload["contract_validation"] = validate_all_contracts(
            config_path=config_path, profiles_dir=profiles_dir
        )

    return stamp_honesty_metadata(payload)


def format_markdown_summary(spec: dict[str, Any]) -> str:
    """Render a concise Markdown engineering summary from an exported spec dict."""
    validate_honesty_metadata(spec)
    lines = [
        "# AI-GPU B2 Architecture Specification Summary",
        "",
        f"- **Evidence Level:** `{spec['evidence_level']}` "
        f"(`silicon_measured={spec['silicon_measured']}`, "
        f"`foundry_signoff={spec['foundry_signoff']}`, "
        f"`fpga_measured={spec['fpga_measured']}`)",
        "",
        "## 1. SKU Topology & Throughput Reconciliation",
        "",
        "| SKU | Cores | L2 | TMEM | HBM3E BW | Vortex Base FP16 | TFRv2 Dense FP16 / FP8 / FP4 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for sku_id, entry in spec["skus"].items():
        topo = entry["topology"]
        rec = entry["throughput_reconciliation"]
        l2_str = f"{topo['l2_total_bytes'] // (1024 * 1024)} MiB" if topo["l2_total_bytes"] >= 1048576 else f"{topo['l2_total_bytes'] // 1024} KiB"
        tmem_str = f"{topo['tmem_total_bytes'] // (1024 * 1024)} MiB"
        lines.append(
            f"| `{sku_id}` | {topo['total_cores']} | {l2_str} | {tmem_str} | "
            f"{topo['hbm_bandwidth_gbs']:.0f} GB/s | {rec['vortex_base_tfr_fp16_tflops']:.3f} TFLOPS | "
            f"{rec['tfrv2_dense_fp16_tflops']:.0f} / {rec['tfrv2_dense_fp8_tflops']:.0f} / "
            f"{rec['tfrv2_dense_fp4_tops']:.0f} |"
        )
    lines.extend([
        "",
        "## 2. TFRv2 Numeric Formats",
        "",
        "| Format | Bits | Scale Factor | Block Size | Elements/Word32 | Accumulator |",
        "|---|---:|---|---:|---:|---|",
    ])
    for fmt_id, fmt in spec["tfrv2_numeric_formats"].items():
        sf = fmt["scale_factor_type"] or "none"
        lines.append(
            f"| `{fmt_id}` | {fmt['bitwidth']} | {sf} | {fmt['scale_block_size']} | "
            f"{fmt['elements_per_word32']} | {fmt['accumulator_type']} |"
        )
    lines.extend([
        "",
        "## 3. SoC Subsystems Summary",
        f"- **TMEM:** {spec['tmem']['capacity_bytes_per_core'] // 1024} KiB/core, "
        f"{spec['tmem']['lanes_rows']} rows x {spec['tmem']['columns']} cols, "
        f"{spec['tmem']['num_banks']} banks, swizzles {spec['tmem']['supported_swizzle_modes']}",
        f"- **Coherent L2/MOESI:** {spec['moesi_directory']['slices_per_die']} slices/die, "
        f"{spec['moesi_directory']['interleave_granule_bytes']} B interleave, "
        f"UCIe 2.0 effective D2D {spec['ucie_d2d']['effective_bandwidth_gbs_total']:.0f} GB/s",
        f"- **MMIO / MIG / RAS / PMU:** {len(spec['soc_mmio_map'])} BAR0 apertures, "
        f"{len(spec['mig_profiles'])} MIG profiles, {len(spec['ras_mca_banks'])} MCA banks, "
        f"{len(spec['pmu_events'])} PMU events",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sku", choices=B2_SKUS, default=None, help="Filter export to one SKU")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload")
    parser.add_argument(
        "--validate-profiles",
        action="store_true",
        help="Validate B2 profiles via ci/gen_config.py and ci/profile_check.py",
    )
    parser.add_argument(
        "--check-contracts",
        action="store_true",
        help="Run all cross-pillar architectural contract assertions and exit non-zero on failure",
    )
    parser.add_argument("--output", type=Path, default=None, help="Write output to file")
    args = parser.parse_args(argv)

    if args.check_contracts:
        res = validate_all_contracts()
        text = json.dumps(res, indent=2) + "\n"
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0 if res["ok"] else 1

    spec = export_architecture_spec(args.sku, validate_profiles=args.validate_profiles)
    text = (json.dumps(spec, indent=2) + "\n") if args.json else format_markdown_summary(spec)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
