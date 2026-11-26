#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Analytical roofline comparator for pre-silicon AI-GPU B1 targets vs baselines.

This pure-Python standard-library tool reads `profiles/aigpu-b1.json`,
`profiles/aigpu-b1-tile.json`, `profiles/rtx5080.json`, and `profiles/h100.json`,
resolves each hardware profile against `VX_config.toml` using `ci/gen_config.py`,
and computes Vortex-modeled analytical peak throughput, memory bandwidth,
ridge points (FLOP/byte), and expected arithmetic intensity for representative
Llama prefill vs decode operating regimes.

Evidence boundary:
  Every output record carries `evidence_level = "modeled_analytical"` and
  `silicon_measured = False`. These numbers are analytical hardware-configuration
  calculations derived from profile parameters and Vortex TCU/FPU formulas —
  NEVER measured silicon performance, NEVER FPGA measurements, and NEVER
  cycle-accurate RTL/SimX execution results.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


SCHEMA_VERSION = 1
ALLOWED_EVIDENCE_LEVEL = "modeled_analytical"
FORBIDDEN_PHYSICAL_LEVELS = frozenset({
    "fpga_measured",
    "silicon_measured",
    "rtl_verified",
    "simulated",
})

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "VX_config.toml"
DEFAULT_PROFILES_DIR = ROOT / "profiles"
TARGET_PROFILES = ("aigpu-b1", "aigpu-b1-tile", "rtx5080", "h100")

# Analytical TCU sub-word elements per 32-bit FEDP input word in Vortex:
#   - tf32:       1 element / 32-bit word  ->  2 FLOPs / 32-bit FMA word pair
#   - fp16_bf16:  2 elements / 32-bit word ->  4 FLOPs / 32-bit FMA word pair
#   - fp8:        4 elements / 32-bit word ->  8 FLOPs / 32-bit FMA word pair
#   - int8:       4 elements / 32-bit word ->  8 OPs   / 32-bit FMA word pair
#   - mxfp4:      8 elements / 32-bit word -> 16 FLOPs / 32-bit FMA word pair
#   - nvfp4:      8 elements / 32-bit word -> 16 FLOPs / 32-bit FMA word pair
FORMAT_SPECS: dict[str, dict[str, Any]] = {
    "fp16_bf16": {
        "label": "FP16 / BF16",
        "enable_key": "VX_CFG_TCU_FP16_ENABLE",
        "elements_per_word32": 2,
        "bytes_per_element": 2.0,
        "unit": "TFLOPS",
        "requires_mx": False,
    },
    "fp8": {
        "label": "FP8 (E4M3/E5M2)",
        "enable_key": "VX_CFG_TCU_FP8_ENABLE",
        "elements_per_word32": 4,
        "bytes_per_element": 1.0,
        "unit": "TFLOPS",
        "requires_mx": False,
    },
    "mxfp4": {
        "label": "MXFP4 (OCP 4-bit)",
        "enable_key": "VX_CFG_TCU_MXFP4_ENABLE",
        "elements_per_word32": 8,
        "bytes_per_element": 0.5,
        "unit": "TOPS",
        "requires_mx": True,
        "requires_fp4": True,
    },
    "nvfp4": {
        "label": "NVFP4 (4-bit)",
        "enable_key": "VX_CFG_TCU_NVFP4_ENABLE",
        "elements_per_word32": 8,
        "bytes_per_element": 0.5,
        "unit": "TOPS",
        "requires_mx": True,
        "requires_fp4": True,
    },
    "tf32": {
        "label": "TF32",
        "enable_key": "VX_CFG_TCU_TF32_ENABLE",
        "elements_per_word32": 1,
        "bytes_per_element": 4.0,
        "unit": "TFLOPS",
        "requires_mx": False,
    },
    "int8": {
        "label": "INT8",
        "enable_key": "VX_CFG_TCU_INT8_ENABLE",
        "elements_per_word32": 4,
        "bytes_per_element": 1.0,
        "unit": "TOPS",
        "requires_mx": False,
    },
}


@dataclass(frozen=True)
class LlamaWorkpoint:
    """Representative analytical Llama linear-layer / GEMM workpoint.

    Uses standard transformer linear-projection GEMM shapes (batch * seq_len
    tokens = M, projection dimensions N, K) to compute idealized analytical
    arithmetic intensity (2*M*N*K / ((M*K + K*N + M*N) * bytes_per_elem))
    ignoring cache-blocking amplification and KV-cache reads beyond the GEMM.
    """

    name: str
    phase: str
    tokens_m: int
    n_dim: int
    k_dim: int
    precision: str
    weight_bytes_per_element: float
    activation_bytes_per_element: float
    output_bytes_per_element: float
    notes: str

    def arithmetic_intensity(self) -> float:
        flops = 2.0 * float(self.tokens_m) * float(self.n_dim) * float(self.k_dim)
        bytes_moved = (
            float(self.tokens_m) * float(self.k_dim) * self.activation_bytes_per_element
            + float(self.k_dim) * float(self.n_dim) * self.weight_bytes_per_element
            + float(self.tokens_m) * float(self.n_dim) * self.output_bytes_per_element
        )
        return flops / bytes_moved


# Representative Llama-3-8B / datacenter FFN & projection workpoints:
# - Prefill (M = 4096 tokens, K = 4096, N = 14336): high batch/sequence reuse -> compute-bound.
# - Decode (M = 1 token, K = 4096, N = 14336): GEMV weight-streaming -> strictly memory-bound.
LLAMA_WORKPOINTS: tuple[LlamaWorkpoint, ...] = (
    LlamaWorkpoint(
        name="llama_prefill_fp16_bf16",
        phase="prefill",
        tokens_m=4096,
        n_dim=14336,
        k_dim=4096,
        precision="fp16_bf16",
        weight_bytes_per_element=2.0,
        activation_bytes_per_element=2.0,
        output_bytes_per_element=2.0,
        notes="M=4096 batched prefill projection GEMM (K=4096, N=14336), FP16/BF16 dense.",
    ),
    LlamaWorkpoint(
        name="llama_prefill_fp8",
        phase="prefill",
        tokens_m=4096,
        n_dim=14336,
        k_dim=4096,
        precision="fp8",
        weight_bytes_per_element=1.0,
        activation_bytes_per_element=1.0,
        output_bytes_per_element=2.0,
        notes="M=4096 batched prefill projection GEMM (K=4096, N=14336), FP8 weights/acts, BF16 output.",
    ),
    LlamaWorkpoint(
        name="llama_prefill_nvfp4",
        phase="prefill",
        tokens_m=4096,
        n_dim=14336,
        k_dim=4096,
        precision="nvfp4",
        weight_bytes_per_element=0.5 + (1.0 / 16.0),
        activation_bytes_per_element=0.5 + (1.0 / 16.0),
        output_bytes_per_element=2.0,
        notes="M=4096 batched prefill projection GEMM (K=4096, N=14336), NVFP4 + 1B/16 scale factor, BF16 output.",
    ),
    LlamaWorkpoint(
        name="llama_decode_fp16_bf16",
        phase="decode",
        tokens_m=1,
        n_dim=14336,
        k_dim=4096,
        precision="fp16_bf16",
        weight_bytes_per_element=2.0,
        activation_bytes_per_element=2.0,
        output_bytes_per_element=2.0,
        notes="M=1 autoregressive decode GEMV (K=4096, N=14336), FP16/BF16 weight-bandwidth limited.",
    ),
    LlamaWorkpoint(
        name="llama_decode_fp8",
        phase="decode",
        tokens_m=1,
        n_dim=14336,
        k_dim=4096,
        precision="fp8",
        weight_bytes_per_element=1.0,
        activation_bytes_per_element=1.0,
        output_bytes_per_element=2.0,
        notes="M=1 autoregressive decode GEMV (K=4096, N=14336), FP8 weight-bandwidth limited.",
    ),
    LlamaWorkpoint(
        name="llama_decode_nvfp4",
        phase="decode",
        tokens_m=1,
        n_dim=14336,
        k_dim=4096,
        precision="nvfp4",
        weight_bytes_per_element=0.5 + (1.0 / 16.0),
        activation_bytes_per_element=0.5 + (1.0 / 16.0),
        output_bytes_per_element=2.0,
        notes="M=1 autoregressive decode GEMV (K=4096, N=14336), NVFP4 + 1B/16 scale factor weight-streaming.",
    ),
)


def _load_gen_config() -> Any:
    spec = importlib.util.spec_from_file_location(
        "aigpu_b1_gen_config", ROOT / "ci/gen_config.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load gen_config module from {ROOT / 'ci/gen_config.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_honesty_record(record: dict[str, Any]) -> None:
    """Enforce that analytical comparison outputs never masquerade as silicon."""
    if not isinstance(record, dict):
        raise ValueError("Roofline record must be a JSON object")
    if record.get("evidence_level") != ALLOWED_EVIDENCE_LEVEL:
        raise ValueError(
            f"Roofline comparator only permits evidence_level={ALLOWED_EVIDENCE_LEVEL!r}, "
            f"got {record.get('evidence_level')!r}"
        )
    if record.get("silicon_measured") is not False:
        raise ValueError(
            "Roofline comparator must enforce silicon_measured=False; physical silicon is not measured"
        )


def resolve_profile_config(
    profile_name: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Load, validate, and resolve a hardware profile via ci/gen_config.py."""
    gen_config = _load_gen_config()
    raw_path = profiles_dir / f"{profile_name}.json"
    raw_profile = json.loads(raw_path.read_text(encoding="utf-8"))

    toml_data = gen_config._load_toml(str(config_path))
    defaults, layout = gen_config._flatten_with_layout(toml_data)
    enums = gen_config._load_enums(toml_data)
    builtins = gen_config._load_var_table(toml_data, "builtin")
    params = gen_config._load_var_table(toml_data, "param")

    prof = gen_config.load_profile(profile_name, str(profiles_dir))
    gen_config.validate_profile(
        prof, defaults, enums, set(params.keys()) | set(builtins.keys())
    )

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


def _format_supported(cfg: dict[str, Any], fmt_key: str) -> bool:
    if not bool(cfg.get("VX_CFG_EXT_TCU_ENABLE", False)):
        return False
    spec = FORMAT_SPECS[fmt_key]
    if not bool(cfg.get(spec["enable_key"], False)):
        return False
    if spec.get("requires_mx", False) and not bool(cfg.get("VX_CFG_TCU_MX_ENABLE", False)):
        return False
    if spec.get("requires_fp4", False) and not bool(cfg.get("VX_CFG_TCU_FP4_ENABLE", False)):
        return False
    return True


def _assert_positive_finite(value: float, label: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be positive and finite, got {value!r}")


def analyze_profile(
    profile_name: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Compute Vortex-modeled analytical roofline metrics for one profile."""
    raw_profile, prof, cfg = resolve_profile_config(
        profile_name, config_path=config_path, profiles_dir=profiles_dir
    )

    num_clusters = int(cfg["VX_CFG_NUM_CLUSTERS"])
    num_cores_per_cluster = int(cfg["VX_CFG_NUM_CORES"])
    total_cores = num_clusters * num_cores_per_cluster
    num_threads = int(cfg["VX_CFG_NUM_THREADS"])
    num_warps = int(cfg["VX_CFG_NUM_WARPS"])
    issue_width = int(cfg["VX_CFG_ISSUE_WIDTH"])
    clock_mhz = float(cfg["VX_CFG_PLATFORM_CLOCK_RATE"])
    clock_ghz = clock_mhz / 1000.0
    bw_mbs = float(cfg["VX_CFG_PLATFORM_MEMORY_PEAK_BW"])
    bw_gbs = bw_mbs / 1000.0

    _assert_positive_finite(total_cores, f"{profile_name}.total_cores")
    _assert_positive_finite(clock_mhz, f"{profile_name}.clock_mhz")
    _assert_positive_finite(bw_gbs, f"{profile_name}.bandwidth_gbs")

    fpu_blocks = int(cfg["VX_CFG_NUM_FPU_BLOCKS"])
    fpu_lanes = int(cfg["VX_CFG_NUM_FPU_LANES"])
    fma_pe_ratio = int(cfg["VX_CFG_FMA_PE_RATIO"])
    fp32_lanes_total = total_cores * fpu_blocks * fpu_lanes
    fp32_fma_pes_total = fp32_lanes_total / float(fma_pe_ratio)
    fp32_tflops = (fp32_fma_pes_total * 2.0 * clock_ghz) / 1000.0
    fp32_ridge = (fp32_tflops * 1000.0) / bw_gbs

    tcu_enabled = bool(cfg.get("VX_CFG_EXT_TCU_ENABLE", False))
    tcu_blocks = int(cfg["VX_CFG_NUM_TCU_BLOCKS"])
    tcu_pe_ratio = int(cfg["VX_CFG_TCU_PE_RATIO"])
    fedp_2k = bool(cfg.get("VX_CFG_TCU_FEDP2K", False))
    sparse_enabled = bool(cfg.get("VX_CFG_TCU_SPARSE_ENABLE", False))
    wgmma_enabled = bool(cfg.get("VX_CFG_TCU_WGMMA_ENABLE", False))
    tc_m, tc_n, tc_k = _vortex_tcu_block_shape(num_threads)

    # Vortex TCU core math (hw/rtl/tcu/VX_tcu_core.sv):
    #   Array size = (TC_M * TC_N / PE_RATIO) FEDP PEs per TCU block.
    #   Each FEDP computes FEDP_K 32-bit FMA word-dot terms per cycle (FEDP_K = TC_K, or 2*TC_K with FEDP2K).
    #   A packed format has `elements_per_word32` elements per 32-bit word (1 FMA = 2 FLOPs or OPs).
    fedp_k = (2 * tc_k) if (fedp_2k and wgmma_enabled) else tc_k
    pes_per_block = (tc_m * tc_n) / float(tcu_pe_ratio)
    word32_fmas_per_chip_cycle = (
        float(total_cores) * float(tcu_blocks) * pes_per_block * float(fedp_k)
        if tcu_enabled
        else 0.0
    )

    formats: dict[str, Any] = {}
    for fmt_key, spec in FORMAT_SPECS.items():
        supported = _format_supported(cfg, fmt_key)
        epw = spec["elements_per_word32"]
        if supported:
            dense_peak = (word32_fmas_per_chip_cycle * float(epw) * 2.0 * clock_ghz) / 1000.0
            dense_ridge = (dense_peak * 1000.0) / bw_gbs
            if sparse_enabled:
                sparse_peak: float | None = 2.0 * dense_peak
                sparse_ridge: float | None = 2.0 * dense_ridge
            else:
                sparse_peak = None
                sparse_ridge = None
        else:
            dense_peak = None
            dense_ridge = None
            sparse_peak = None
            sparse_ridge = None

        formats[fmt_key] = {
            "label": spec["label"],
            "unit": spec["unit"],
            "supported": supported,
            "sparse_2_4_supported": bool(supported and sparse_enabled),
            "dense_peak": dense_peak,
            "dense_ridge_flop_per_byte": dense_ridge,
            "sparse_2_4_peak": sparse_peak,
            "sparse_2_4_ridge_flop_per_byte": sparse_ridge,
        }

    workpoints: dict[str, Any] = {}
    for wp in LLAMA_WORKPOINTS:
        ai = wp.arithmetic_intensity()
        fmt_entry = formats[wp.precision]
        dense_peak = fmt_entry["dense_peak"]
        dense_ridge = fmt_entry["dense_ridge_flop_per_byte"]
        bw_bound_tflops = (ai * bw_gbs) / 1000.0
        if dense_peak is not None and dense_ridge is not None:
            attained_dense: float | None = min(dense_peak, bw_bound_tflops)
            regime = "compute-bound" if ai >= dense_ridge else "memory-bound"
        else:
            attained_dense = None
            regime = "unsupported"

        sp_peak = fmt_entry["sparse_2_4_peak"]
        sp_ridge = fmt_entry["sparse_2_4_ridge_flop_per_byte"]
        if sp_peak is not None and sp_ridge is not None:
            attained_sparse: float | None = min(sp_peak, bw_bound_tflops)
            sparse_regime = "compute-bound" if ai >= sp_ridge else "memory-bound"
        else:
            attained_sparse = None
            sparse_regime = "unsupported"

        workpoints[wp.name] = {
            "phase": wp.phase,
            "precision": wp.precision,
            "tokens_m": wp.tokens_m,
            "n_dim": wp.n_dim,
            "k_dim": wp.k_dim,
            "arithmetic_intensity_flop_per_byte": ai,
            "bandwidth_ceiling_tflops_or_tops": bw_bound_tflops,
            "dense_attained_tflops_or_tops": attained_dense,
            "dense_regime": regime,
            "sparse_2_4_attained_tflops_or_tops": attained_sparse,
            "sparse_2_4_regime": sparse_regime,
            "notes": wp.notes,
        }

    graphics_disabled = (
        not bool(cfg.get("VX_CFG_EXT_TEX_ENABLE", False))
        and not bool(cfg.get("VX_CFG_EXT_RASTER_ENABLE", False))
        and not bool(cfg.get("VX_CFG_EXT_OM_ENABLE", False))
        and not bool(cfg.get("VX_CFG_EXT_RTU_ENABLE", False))
    )

    result = {
        "profile": profile_name,
        "xlen": prof.xlen,
        "description": raw_profile.get("description", ""),
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "phase_status_effect": "none",
        "topology": {
            "num_clusters": num_clusters,
            "cores_per_cluster": num_cores_per_cluster,
            "total_cores": total_cores,
            "socket_size": int(cfg["VX_CFG_SOCKET_SIZE"]),
            "warps_per_core": num_warps,
            "threads_per_warp": num_threads,
            "issue_width": issue_width,
            "fetch_width": int(cfg["VX_CFG_FETCH_WIDTH"]),
            "l2_enabled": bool(cfg.get("VX_CFG_L2_ENABLE", False)),
            "l2_bytes": int(cfg["VX_CFG_L2_SIZE"]) if cfg.get("VX_CFG_L2_ENABLE", False) else 0,
            "lmem_bytes_per_core": int(cfg["VX_CFG_LMEM_SIZE"]) if cfg.get("VX_CFG_LMEM_ENABLE", False) else 0,
            "graphics_disabled": graphics_disabled,
        },
        "tcu_architecture": {
            "enabled": tcu_enabled,
            "tcu_type": cfg["VX_CFG_TCU_TYPE"],
            "fpu_type": cfg["VX_CFG_FPU_TYPE"],
            "blocks_per_core": tcu_blocks,
            "pe_ratio": tcu_pe_ratio,
            "tc_m": tc_m,
            "tc_n": tc_n,
            "tc_k": tc_k,
            "fedp_k_words": fedp_k,
            "wgmma_enabled": wgmma_enabled,
            "sparse_enabled": sparse_enabled,
            "mx_enabled": bool(cfg.get("VX_CFG_TCU_MX_ENABLE", False)),
            "fp4_enabled": bool(cfg.get("VX_CFG_TCU_FP4_ENABLE", False)),
            "dxa_enabled": bool(cfg.get("VX_CFG_EXT_DXA_ENABLE", False)),
        },
        "memory": {
            "clock_mhz": clock_mhz,
            "memory_type": cfg["VX_CFG_PLATFORM_MEMORY_TYPE"],
            "memory_banks": int(cfg["VX_CFG_PLATFORM_MEMORY_NUM_BANKS"]),
            "data_rate_mts": int(cfg["VX_CFG_PLATFORM_MEMORY_DATA_RATE"]),
            "bandwidth_gbs": bw_gbs,
            "bytes_per_clock": (bw_mbs / clock_mhz),
        },
        "scalar_fp32": {
            "fp32_lanes_total": fp32_lanes_total,
            "dense_tflops": fp32_tflops,
            "ridge_flop_per_byte": fp32_ridge,
        },
        "tensor_formats": formats,
        "llama_workpoints": workpoints,
    }
    validate_honesty_record(result)
    return result


def build_comparison_report(
    profiles: tuple[str, ...] = TARGET_PROFILES,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    """Analyze all requested profiles and assemble a unified analytical report."""
    analyzed = {
        name: analyze_profile(
            name, config_path=config_path, profiles_dir=profiles_dir
        )
        for name in profiles
    }

    b1 = analyzed.get("aigpu-b1")
    tile = analyzed.get("aigpu-b1-tile")
    scaling_checks: dict[str, Any] = {}
    if b1 is not None and tile is not None:
        b1_fp16 = b1["tensor_formats"]["fp16_bf16"]["dense_peak"]
        tile_fp16 = tile["tensor_formats"]["fp16_bf16"]["dense_peak"]
        scaling_checks = {
            "full_to_tile_core_ratio": b1["topology"]["total_cores"] / float(tile["topology"]["total_cores"]),
            "full_to_tile_clock_ratio": b1["memory"]["clock_mhz"] / tile["memory"]["clock_mhz"],
            "full_to_tile_bandwidth_ratio": b1["memory"]["bandwidth_gbs"] / tile["memory"]["bandwidth_gbs"],
            "full_to_tile_fp16_dense_tflops_ratio": b1_fp16 / tile_fp16,
        }

    report = {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "silicon_measured": False,
        "phase_status_effect": "none",
        "disclaimer": (
            "MODELED ANALYTICAL ROOFLINE ONLY (Vortex parameterized formulas over "
            "profile hardware knobs). NOT measured physical silicon, NOT physical FPGA "
            "measurements, and NOT SimX/RTL cycle simulations."
        ),
        "profiles_order": list(profiles),
        "profiles": analyzed,
        "b1_vs_tile_scaling": scaling_checks,
        "llama_workpoint_intensities": {
            wp.name: {
                "phase": wp.phase,
                "precision": wp.precision,
                "arithmetic_intensity_flop_per_byte": wp.arithmetic_intensity(),
            }
            for wp in LLAMA_WORKPOINTS
        },
    }
    validate_honesty_record(report)
    return report


def _fmt_num(val: float | None, width: int = 9) -> str:
    if val is None:
        return f"{'N/A':>{width}}"
    return f"{val:{width}.2f}"


def format_report_text(report: dict[str, Any]) -> str:
    validate_honesty_record(report)
    lines = [
        "AI-GPU Wave 8B Analytical Roofline Comparison",
        f"Evidence Level : {report['evidence_level']} (silicon_measured={report['silicon_measured']})",
        f"Disclaimer     : {report['disclaimer']}",
        "",
        f"{'Profile':<15} {'Cores':>5} {'Clk':>6} {'MemBW':>8} {'FP32':>8} "
        f"{'FP16 D/S':>17} {'FP8 D/S':>17} {'MXFP4 D/S':>17} {'NVFP4 D/S':>17}",
        f"{'':<15} {'':>5} {'MHz':>6} {'GB/s':>8} {'TFLOPS':>8} "
        f"{'TFLOPS':>17} {'TFLOPS':>17} {'TOPS':>17} {'TOPS':>17}",
        "-" * 112,
    ]
    for pname in report["profiles_order"]:
        p = report["profiles"][pname]
        topo = p["topology"]
        mem = p["memory"]
        fp32 = p["scalar_fp32"]["dense_tflops"]
        fmts = p["tensor_formats"]

        def pair_str(fkey: str) -> str:
            d = fmts[fkey]["dense_peak"]
            s = fmts[fkey]["sparse_2_4_peak"]
            ds = f"{d:7.1f}" if d is not None else "    N/A"
            ss = f"{s:7.1f}" if s is not None else "    N/A"
            return f"{ds} / {ss}"

        lines.append(
            f"{pname:<15} {topo['total_cores']:>5d} {mem['clock_mhz']:>6.0f} {mem['bandwidth_gbs']:>8.1f} "
            f"{fp32:>8.2f} {pair_str('fp16_bf16'):>17} {pair_str('fp8'):>17} "
            f"{pair_str('mxfp4'):>17} {pair_str('nvfp4'):>17}"
        )

    lines.extend([
        "",
        "Ridge Points (FLOP/byte or OP/byte — dense / 2:4 sparse):",
        f"{'Profile':<15} {'FP16 Ridge':>17} {'FP8 Ridge':>17} {'MXFP4 Ridge':>17} {'NVFP4 Ridge':>17}",
        "-" * 88,
    ])
    for pname in report["profiles_order"]:
        fmts = report["profiles"][pname]["tensor_formats"]

        def ridge_str(fkey: str) -> str:
            d = fmts[fkey]["dense_ridge_flop_per_byte"]
            s = fmts[fkey]["sparse_2_4_ridge_flop_per_byte"]
            ds = f"{d:7.2f}" if d is not None else "    N/A"
            ss = f"{s:7.2f}" if s is not None else "    N/A"
            return f"{ds} / {ss}"

        lines.append(
            f"{pname:<15} {ridge_str('fp16_bf16'):>17} {ridge_str('fp8'):>17} "
            f"{ridge_str('mxfp4'):>17} {ridge_str('nvfp4'):>17}"
        )

    lines.extend([
        "",
        "Representative Llama Prefill vs Decode Workpoints (Modeled Analytical):",
        f"{'Workpoint':<26} {'AI(Op/B)':>9} | {'b1 Attain':>10} {'b1 Regime':<13} | {'tile Attain':>11} {'tile Regime':<12} | {'h100 Regime':<12}",
        "-" * 108,
    ])
    p_b1 = report["profiles"].get("aigpu-b1")
    p_tile = report["profiles"].get("aigpu-b1-tile")
    p_h100 = report["profiles"].get("h100")
    for wp_name, wp_meta in report["llama_workpoint_intensities"].items():
        ai = wp_meta["arithmetic_intensity_flop_per_byte"]
        b1_wp = p_b1["llama_workpoints"][wp_name] if p_b1 else {}
        tl_wp = p_tile["llama_workpoints"][wp_name] if p_tile else {}
        h1_wp = p_h100["llama_workpoints"][wp_name] if p_h100 else {}
        lines.append(
            f"{wp_name:<26} {ai:>9.2f} | "
            f"{_fmt_num(b1_wp.get('dense_attained_tflops_or_tops'), 10)} {b1_wp.get('dense_regime', 'N/A'):<13} | "
            f"{_fmt_num(tl_wp.get('dense_attained_tflops_or_tops'), 11)} {tl_wp.get('dense_regime', 'N/A'):<12} | "
            f"{h1_wp.get('dense_regime', 'N/A'):<12}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles",
        default=",".join(TARGET_PROFILES),
        help="Comma-separated list of profile names to compare",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON report instead of summary table",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write output to",
    )
    args = parser.parse_args(argv)
    names = tuple(p.strip() for p in args.profiles.split(",") if p.strip())
    if not names:
        parser.error("at least one profile name is required")

    report = build_comparison_report(names)
    text = (json.dumps(report, indent=2) + "\n") if args.json else format_report_text(report)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
