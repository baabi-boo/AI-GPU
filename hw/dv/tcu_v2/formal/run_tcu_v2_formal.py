#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sequential formal proof & Yosys synthesis runner for TCU v2 and TMEM RTL.

Runs:
  1. Six formal proof harnesses via Yosys (`read_slang -DFORMAL -DSYNTHESIS ...;
     prep -top ...`) and `yosys sat` (`-seq 2` or `-tempinduct-baseonly
     -maxsteps 6/8` for assertion proofs, plus per-`$cover` `yosys sat`
     reachability checks) sequentially (`-j1`) with all build artifacts
     written out-of-tree under `/home/antigravity/vortex_builds/w14_formal/`.
  2. Yosys synthesis smoke check (`synth -top ...; check -assert`) on key leaf RTL
     modules (`VX_tcu_v2_fp4_unpack`, `VX_tcu_v2_fp8_e4m3_unpack`,
     `VX_tcu_v2_int8_dot_acc`, `VX_tcu_v2_sparse_validator`,
     `VX_tcu_v2_wgmma_desc_q`, `VX_tmem_allocator`).
  3. Structured JSON report summarizing per-harness proof depth, cover reachability,
     synthesis cell/wire counts, elapsed runtime, and overall verdict.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from typing import Any


DEFAULT_YOSYS = "/home/antigravity/tools/yosys/bin/yosys"
DEFAULT_SMTBMC = "/home/antigravity/tools/yosys/bin/yosys-smtbmc"
DEFAULT_SOLVER = "z3"
DEFAULT_BUILD_DIR = Path("/home/antigravity/vortex_builds/w14_formal")
DEFAULT_TIMEOUT_SEC = 120


@dataclass(frozen=True)
class FormalHarnessSpec:
    harness_id: str
    top_module: str
    bmc_depth: int
    sources: tuple[str, ...]
    proof_mode: str = "yosys_sat"  # "yosys_sat" or "smtbmc_unroll"
    cover_mode: str = "yosys_sat_cover"  # "yosys_sat_cover" or "smtbmc_unroll"
    cover_depth: str = "2"
    sat_cross_check: bool = False
    include_dirs: tuple[str, ...] = ("hw/rtl", "hw/rtl/tcu/v2", "hw/rtl/tmem")
    defines: tuple[str, ...] = ("FORMAL", "SYNTHESIS")
    chparams: tuple[tuple[str, str], ...] = ()
    run_cover: bool = True
    properties: tuple[str, ...] = field(default_factory=tuple)
    rtl_fixes_applied: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SynthSmokeSpec:
    module_name: str
    sources: tuple[str, ...]
    include_dirs: tuple[str, ...] = ("hw/rtl", "hw/rtl/libs", "hw/rtl/tcu/v2", "hw/rtl/tmem")
    defines: tuple[str, ...] = ("SYNTHESIS",)
    chparams: tuple[tuple[str, str], ...] = ()


FORMAL_HARNESS_SPECS: tuple[FormalHarnessSpec, ...] = (
    FormalHarnessSpec(
        harness_id="formal_fp4_fp6_equiv",
        top_module="VX_tcu_v2_formal_fp4_fp6_equiv",
        bmc_depth=2,
        proof_mode="yosys_sat",
        cover_mode="yosys_sat_cover",
        cover_depth="2",
        chparams=(("LANES", "8"),),
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv",
            "hw/rtl/tcu/v2/arith/VX_tcu_v2_fp6_e2m3_unpack.sv",
            "hw/rtl/tcu/v2/arith/VX_tcu_v2_fp6_e3m2_unpack.sv",
            "hw/rtl/tcu/v2/arith/VX_tcu_v2_mx_scale_decode.sv",
            "hw/rtl/tcu/v2/arith/VX_tcu_v2_mx_block_align.sv",
            "hw/dv/tcu_v2/formal/formal_fp4_fp6_equiv.sv",
        ),
        properties=(
            "FP4/FP6 sign-bit negation symmetry across active lanes",
            "Zero detection iff lane masked or magnitude bits are zero",
            "No Inf/NaN emitted for FP4 or FP6 element unpackers",
            "UE8M0 0xFF -> is_nan; E4M3 0x7F/0xFF -> is_nan",
            "Scale NaN dominates combined MX block scale and subnormal normalization invariants",
        ),
        rtl_fixes_applied=(
            "VX_tcu_v2_fp4_unpack.sv: wrapped 2D packed signed exponent comparisons in $signed(...)",
            "VX_tcu_v2_fp6_e2m3_unpack.sv: wrapped 2D packed signed exponent comparisons in $signed(...)",
            "VX_tcu_v2_fp6_e3m2_unpack.sv: wrapped 2D packed signed exponent comparisons in $signed(...)",
        ),
    ),
    FormalHarnessSpec(
        harness_id="formal_fp8_bf16_props",
        top_module="VX_tcu_v2_formal_fp8_bf16_props",
        bmc_depth=2,
        proof_mode="yosys_sat",
        cover_mode="yosys_sat_cover",
        cover_depth="2",
        chparams=(("LANES", "1"),),
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e5m2_unpack.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_bf16_fp16_unpack.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_fp_exception_unit.sv",
            "hw/dv/tcu_v2/formal/formal_fp8_bf16_props.sv",
        ),
        properties=(
            "FP8 E4M3FN never produces is_inf; 0x7F/0xFF always produce is_nan",
            "FP8 E5M2 Inf/NaN mutual exclusion and canonical FP32 upcast",
            "FP exception unit NaN dominance, 0*Inf -> NaN + NV (EXC_ZERO_X_INF=4'd3), (+Inf)+(-Inf) -> NaN + NV (EXC_INF_CANCEL=4'd8)",
            "INT8 dot-acc 36-bit exactness and saturation clamp bounds [INT32_MIN, INT32_MAX]",
        ),
        rtl_fixes_applied=(
            "VX_tcu_v2_fp_exception_unit.sv: sets canonical qNaN + NV on 0*Inf (EXC_ZERO_X_INF=4'd3) and (+Inf)+(-Inf) (EXC_INF_CANCEL=4'd8) ahead of qNaN causes, and preserves +0.0 sign on positive tiny underflow in RM_RDN",
        ),
    ),
    FormalHarnessSpec(
        harness_id="formal_tmem_swizzle_ecc",
        top_module="VX_tmem_formal_swizzle_ecc",
        bmc_depth=2,
        proof_mode="yosys_sat",
        cover_mode="yosys_sat_cover",
        cover_depth="2",
        sources=(
            "hw/rtl/tmem/VX_tmem_pkg.sv",
            "hw/rtl/tmem/banks/VX_tmem_swizzle_addr.sv",
            "hw/rtl/tmem/banks/VX_tmem_ecc_enc.sv",
            "hw/rtl/tmem/banks/VX_tmem_ecc_dec.sv",
            "hw/dv/tcu_v2/formal/formal_tmem_swizzle_ecc.sv",
        ),
        properties=(
            "Swizzle bijection: distinct col_a[4:0] != col_b[4:0] map to distinct banks for any row/mode",
            "Full (row, col) -> (bank_id, word_addr, half_sel) physical coordinate bijection",
            "SECDED(72,64): 0-bit flip -> ce=0, ue=0, data_out==data_in",
            "SECDED(72,64): any 1-bit flip in [0..71] -> ce=1, ue=0, data_out==data_in",
            "SECDED(72,64): any distinct 2-bit flip (b1 != b2) in [0..71] -> ue=1, ce=0",
        ),
    ),
    FormalHarnessSpec(
        harness_id="formal_sparse_legality",
        top_module="VX_tcu_v2_formal_sparse_legality",
        bmc_depth=8,
        proof_mode="yosys_sat",
        cover_mode="yosys_sat_cover",
        cover_depth="6",
        chparams=(("ARRAY_M", "1"), ("ARRAY_K", "2")),
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_sparse_validator.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_sparse_selector.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_sparse_compressor.sv",
            "hw/dv/tcu_v2/formal/formal_sparse_legality.sv",
        ),
        properties=(
            "Validator accepts iff idx0 < idx1 across every active group and format is sparse-legal",
            "Compressor always produces metadata accepted by validator",
            "For any 4-element FP16 or FP4 8-nibble group with <= 2 non-zeros, compressor -> selector recovers non-zeros in ascending order",
        ),
    ),
    FormalHarnessSpec(
        harness_id="formal_wgmma_handshake",
        top_module="VX_tcu_v2_formal_wgmma_handshake",
        bmc_depth=6,
        proof_mode="yosys_sat",
        cover_mode="yosys_sat_cover",
        cover_depth="6",
        chparams=(("DESC_DEPTH", "2"), ("NUM_BARRIERS", "2")),
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_wgmma_desc_q.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_barrier_unit.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_cta_pair_sync.sv",
            "hw/dv/tcu_v2/formal/formal_wgmma_handshake.sv",
        ),
        properties=(
            "FIFO count conservation (0 <= occupancy <= DEPTH) and exact empty/full flags",
            "Illegal descriptors rejected cleanly without corrupting queue state",
            "Barrier phase toggles iff arrivals and expected tx counts reach zero; OOB barrier_id safely rejected",
            "2-CTA peer sync never deadlocks or corrupts phase on paired arrival",
        ),
    ),
    FormalHarnessSpec(
        harness_id="formal_tmem_arb_alloc",
        top_module="VX_tmem_formal_arb_alloc",
        bmc_depth=6,
        proof_mode="yosys_sat",
        cover_mode="yosys_sat_cover",
        cover_depth="6",
        chparams=(("LANES", "2"), ("MAX_REGIONS", "4"), ("TRACK_DEPTH", "4")),
        sources=(
            "hw/rtl/tmem/VX_tmem_pkg.sv",
            "hw/rtl/tmem/ctrl/VX_tmem_allocator.sv",
            "hw/rtl/tmem/ctrl/VX_tmem_arbiter.sv",
            "hw/rtl/tmem/ctrl/VX_tmem_hazard_unit.sv",
            "hw/dv/tcu_v2/formal/formal_tmem_arb_alloc.sv",
        ),
        properties=(
            "Allocator never issues overlapping column granules; total granules <= 16",
            "Granted allocations satisfy col_offset % 32 == 0 and power-of-two num_columns >= 32",
            "Out-of-range region_id, misaligned, bad-size, or OOM requests rejected without corrupting state",
            "Arbiter grants at most one client per shared port ($onehot0)",
            "Hazard unit blocks conflicting RAW/WAR/WAW operations and fences",
        ),
        rtl_fixes_applied=(
            "VX_tmem_allocator.sv: added req_id_in_range and target_id_in_range (< MAX_REGIONS) bounds checks so out-of-range region IDs never mutate granule_bitmap without updating region_table",
        ),
    ),
)


SYNTH_SMOKE_SPECS: tuple[SynthSmokeSpec, ...] = (
    SynthSmokeSpec(
        module_name="VX_tcu_v2_fp4_unpack",
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv",
        ),
    ),
    SynthSmokeSpec(
        module_name="VX_tcu_v2_fp8_e4m3_unpack",
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv",
        ),
    ),
    SynthSmokeSpec(
        module_name="VX_tcu_v2_int8_dot_acc",
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv",
        ),
    ),
    SynthSmokeSpec(
        module_name="VX_tcu_v2_sparse_validator",
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_sparse_validator.sv",
        ),
        chparams=(("ARRAY_M", "2"), ("ARRAY_K", "4")),
    ),
    SynthSmokeSpec(
        module_name="VX_tcu_v2_wgmma_desc_q",
        sources=(
            "hw/rtl/tcu/v2/VX_tcu_v2_pkg.sv",
            "hw/rtl/tcu/v2/ctrl/VX_tcu_v2_wgmma_desc_q.sv",
        ),
        chparams=(("DEPTH", "4"),),
    ),
    SynthSmokeSpec(
        module_name="VX_tmem_allocator",
        sources=(
            "hw/rtl/tmem/VX_tmem_pkg.sv",
            "hw/rtl/tmem/ctrl/VX_tmem_allocator.sv",
        ),
        chparams=(("MAX_REGIONS", "4"),),
    ),
)


def run_subprocess(
    cmd: list[str],
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        elapsed = round(time.monotonic() - t0, 3)
        return {
            "command": " ".join(shlex.quote(c) for c in cmd),
            "returncode": proc.returncode,
            "elapsed_sec": elapsed,
            "timed_out": False,
            "stdout": stdout or "",
            "stderr": stderr or "",
        }
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
        stdout, stderr = proc.communicate()
        elapsed = round(time.monotonic() - t0, 3)
        return {
            "command": " ".join(shlex.quote(c) for c in cmd),
            "returncode": -1,
            "elapsed_sec": elapsed,
            "timed_out": True,
            "stdout": stdout or "",
            "stderr": stderr or "",
        }


def build_read_slang_cmd(
    sources: tuple[str, ...],
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    top_module: str,
    chparams: tuple[tuple[str, str], ...] = (),
) -> str:
    inc_flags = " ".join(f"-I {shlex.quote(d)}" for d in include_dirs)
    def_flags = " ".join(f"-D {shlex.quote(d)}" for d in defines)
    gp_flags = " ".join(f"-G {shlex.quote(f'{k}={v}')}" for k, v in chparams)
    src_flags = " ".join(shlex.quote(s) for s in sources)
    return f"read_slang {def_flags} {inc_flags} {gp_flags} --top {shlex.quote(top_module)} {src_flags}"


def parse_smtbmc_status(output: str) -> str:
    if "Status: PASSED" in output:
        return "PASS"
    if "Status: FAILED" in output:
        return "FAIL"
    return "UNKNOWN"


def parse_synth_stats(stdout: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    patterns = {
        "wires": (r"Number of wires:\s+(\d+)", r"^\s*(\d+)\s+wires\b"),
        "wire_bits": (r"Number of wire bits:\s+(\d+)", r"^\s*(\d+)\s+wire bits\b"),
        "cells": (r"Number of cells:\s+(\d+)", r"^\s*(\d+)\s+cells\b"),
        "memories": (r"Number of memories:\s+(\d+)", r"^\s*(\d+)\s+memories\b"),
    }
    for key, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, stdout, flags=re.M)
            if m:
                stats[key] = int(m.group(1))
                break
    return stats


def run_formal_harness(
    spec: FormalHarnessSpec,
    repo_root: Path,
    build_dir: Path,
    yosys_bin: str,
    smtbmc_bin: str,
    solver: str,
    timeout_sec: int,
    elab_only: bool,
    env: dict[str, str],
) -> dict[str, Any]:
    if spec.bmc_depth < 2:
        raise ValueError(f"Non-vacuous formal requires bmc_depth >= 2 (got {spec.bmc_depth} for {spec.harness_id})")

    harness_dir = build_dir / spec.harness_id
    harness_dir.mkdir(parents=True, exist_ok=True)
    smt2_assert_path = harness_dir / f"{spec.harness_id}.smt2"
    smt2_cover_path = harness_dir / f"{spec.harness_id}_cover.smt2"
    rtlil_cover_path = harness_dir / f"{spec.harness_id}_cover.il"

    read_cmd = build_read_slang_cmd(
        sources=spec.sources,
        include_dirs=spec.include_dirs,
        defines=spec.defines,
        top_module=spec.top_module,
        chparams=spec.chparams,
    )

    result: dict[str, Any] = {
        "harness_id": spec.harness_id,
        "top_module": spec.top_module,
        "bmc_depth": spec.bmc_depth,
        "params": {k: int(v) if v.isdigit() else v for k, v in spec.chparams},
        "properties": list(spec.properties),
        "rtl_fixes_applied": list(spec.rtl_fixes_applied),
    }

    if elab_only:
        yosys_script = f"{read_cmd}; hierarchy -top {shlex.quote(spec.top_module)}"
        y_res = run_subprocess([yosys_bin, "-q", "-p", yosys_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
        result["yosys_returncode"] = y_res["returncode"]
        result["yosys_elapsed_sec"] = y_res["elapsed_sec"]
        result["verdict"] = "PASS_ELAB_ONLY" if y_res["returncode"] == 0 else "FAIL"
        return result

    if spec.proof_mode == "smtbmc_unroll":
        # Assertions SMT2 (stdt + flatten + chformal -lower + dffunmap after opt -fast)
        yosys_script = (
            f"{read_cmd}; "
            f"prep -top {shlex.quote(spec.top_module)}; "
            f"flatten; memory_map; async2sync; chformal -cover -remove; chformal -lower; opt -fast; dffunmap; "
            f"write_smt2 -stdt {shlex.quote(str(smt2_assert_path))}"
        )
        y_res = run_subprocess([yosys_bin, "-q", "-p", yosys_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
        result["yosys_returncode"] = y_res["returncode"]
        result["yosys_elapsed_sec"] = y_res["elapsed_sec"]
        result["smt2_path"] = str(smt2_assert_path)
        if y_res["returncode"] != 0:
            result["verdict"] = "FAIL"
            result["stage_failed"] = "yosys_elaboration"
            result["yosys_stderr_tail"] = y_res["stderr"].strip().splitlines()[-15:]
            return result

        bmc_cmd = [
            smtbmc_bin,
            "-s", solver,
            "--unroll",
            "--noincr",
            "-t", str(spec.bmc_depth),
            "--noprogress",
            "--dump-vcd", str(harness_dir / f"{spec.harness_id}_cex.vcd"),
            str(smt2_assert_path),
        ]
        bmc_res = run_subprocess(bmc_cmd, cwd=repo_root, timeout_sec=timeout_sec, env=env)
        bmc_status = parse_smtbmc_status(bmc_res["stdout"])
        steps_checked = len(re.findall(r"Checking assertions in step", bmc_res["stdout"]))
        bmc_ok = (bmc_res["returncode"] == 0) and (bmc_status == "PASS")
        result["assertion_solver"] = f"yosys-smtbmc -s {solver} --unroll --noincr -t {spec.bmc_depth}"
        result["assertion_verdict"] = "PASS" if bmc_ok else "FAIL"
        result["assertion_elapsed_sec"] = bmc_res["elapsed_sec"]
        result["bmc"] = {
            "command": bmc_res["command"],
            "returncode": bmc_res["returncode"],
            "elapsed_sec": bmc_res["elapsed_sec"],
            "timed_out": bmc_res["timed_out"],
            "steps_checked": steps_checked,
            "status": bmc_status,
            "log_tail": bmc_res["stdout"].strip().splitlines()[-10:],
        }

        if spec.sat_cross_check and bmc_ok:
            sat_script = (
                f"{read_cmd}; "
                f"prep -top {shlex.quote(spec.top_module)}; "
                f"flatten; memory_map; async2sync; dffunmap; chformal -cover -remove; "
                f"sat -set-assumes -prove-asserts -verify -seq {spec.bmc_depth}"
            )
            sat_res = run_subprocess([yosys_bin, "-q", "-p", sat_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
            sat_ok = (sat_res["returncode"] == 0) and not sat_res["timed_out"]
            result["sat_cross_check"] = f"yosys sat -prove-asserts -verify -seq {spec.bmc_depth} ({'PASS' if sat_ok else 'FAIL'}, {sat_res['elapsed_sec']}s)"
            if not sat_ok:
                bmc_ok = False
    else:
        # Bounded Yosys SAT proof (unrolled -seq N for depth<=2, -tempinduct-baseonly -maxsteps N for sequential)
        if spec.bmc_depth <= 2:
            sat_flag = f"-set-assumes -prove-asserts -verify -seq {spec.bmc_depth}"
        else:
            sat_flag = f"-tempinduct-baseonly -maxsteps {spec.bmc_depth} -set-assumes -prove-asserts -verify"
        sat_script = (
            f"{read_cmd}; "
            f"prep -top {shlex.quote(spec.top_module)}; "
            f"flatten; memory_map; async2sync; dffunmap; chformal -cover -remove; "
            f"sat {sat_flag}"
        )
        sat_res = run_subprocess([yosys_bin, "-p", sat_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
        sat_proved = (
            "SAT proof finished - no model found: SUCCESS!" in sat_res["stdout"]
            or f"proved base case for {spec.bmc_depth} steps: SUCCESS!" in sat_res["stdout"]
        )
        bmc_ok = (sat_res["returncode"] == 0) and (not sat_res["timed_out"]) and sat_proved
        result["yosys_returncode"] = sat_res["returncode"]
        result["yosys_elapsed_sec"] = sat_res["elapsed_sec"]
        result["maxsteps"] = spec.bmc_depth
        result["assertion_solver"] = f"yosys sat {sat_flag}"
        result["assertion_verdict"] = "PASS" if bmc_ok else "FAIL"
        result["assertion_elapsed_sec"] = sat_res["elapsed_sec"]
        result["bmc"] = {
            "command": sat_res["command"],
            "returncode": sat_res["returncode"],
            "elapsed_sec": sat_res["elapsed_sec"],
            "timed_out": sat_res["timed_out"],
            "status": "PASS" if bmc_ok else "FAIL",
            "log_tail": sat_res["stdout"].strip().splitlines()[-10:],
        }

    cover_ok = True
    if spec.run_cover:
        if spec.cover_mode == "smtbmc_unroll":
            cov_y_script = (
                f"{read_cmd}; "
                f"prep -top {shlex.quote(spec.top_module)}; "
                f"flatten; memory_map; async2sync; chformal -assert -remove; chformal -lower; opt -fast; dffunmap; "
                f"write_smt2 -stdt {shlex.quote(str(smt2_cover_path))}"
            )
            cy_res = run_subprocess([yosys_bin, "-q", "-p", cov_y_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
            if cy_res["returncode"] != 0:
                cover_ok = False
                cov_elapsed = cy_res["elapsed_sec"]
                cov_status = "FAIL"
                covers_reached = 0
                cov_res_cmd = cy_res["command"]
                cov_rc = cy_res["returncode"]
                cov_to = cy_res["timed_out"]
                cov_tail = cy_res["stderr"].strip().splitlines()[-10:]
            else:
                cov_cmd = [
                    smtbmc_bin,
                    "-s", solver,
                    "--unroll",
                    "--noincr",
                    "-c",
                    "-t", spec.cover_depth,
                    "--noprogress",
                    str(smt2_cover_path),
                ]
                cov_res = run_subprocess(cov_cmd, cwd=repo_root, timeout_sec=timeout_sec, env=env)
                cov_status = parse_smtbmc_status(cov_res["stdout"])
                covers_reached = len(re.findall(r"Reached cover statement", cov_res["stdout"]))
                cover_ok = (cov_res["returncode"] == 0) and (cov_status == "PASS")
                cov_elapsed = round(cy_res["elapsed_sec"] + cov_res["elapsed_sec"], 3)
                cov_res_cmd = cov_res["command"]
                cov_rc = cov_res["returncode"]
                cov_to = cov_res["timed_out"]
                cov_tail = cov_res["stdout"].strip().splitlines()[-10:]
            result["cover_solver"] = f"yosys-smtbmc -s {solver} --unroll --noincr -c -t {spec.cover_depth} (after chformal -assert -remove)"
            result["cover_verdict"] = "PASS" if cover_ok else "FAIL"
            result["cover_elapsed_sec"] = cov_elapsed
            result["cover"] = {
                "command": cov_res_cmd,
                "returncode": cov_rc,
                "elapsed_sec": cov_elapsed,
                "timed_out": cov_to,
                "covers_reached": covers_reached,
                "status": cov_status,
                "log_tail": cov_tail,
            }
        else:
            # Verify reachability of every $cover cell via Yosys SAT at step cov_seq
            cov_seq = int(spec.cover_depth)
            dump_script = (
                f"{read_cmd}; "
                f"prep -top {shlex.quote(spec.top_module)}; "
                f"flatten; memory_map; async2sync; dffunmap; chformal -assert -remove; "
                f"dump -o {shlex.quote(str(rtlil_cover_path))}"
            )
            dump_res = run_subprocess([yosys_bin, "-q", "-p", dump_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
            covers: list[tuple[str, str, str]] = []
            if dump_res["returncode"] == 0 and rtlil_cover_path.exists():
                il_text = rtlil_cover_path.read_text(encoding="utf-8")
                covers = re.findall(r"cell \$cover (\S+)\s+connect \\A (\S+)\s+connect \\EN (\S+)", il_text)

            if not covers:
                cover_ok = False
                cov_elapsed = dump_res["elapsed_sec"]
                cov_status = "FAIL"
                covers_reached = 0
                cov_res_cmd = dump_res["command"]
                cov_rc = dump_res["returncode"] if dump_res["returncode"] != 0 else 1
                cov_to = dump_res["timed_out"]
                cov_tail = dump_res["stderr"].strip().splitlines()[-10:]
            else:
                sat_cmds = [
                    f"sat -set-assumes -set-at {cov_seq} {en} 1 -set-at {cov_seq} {a} 1 -seq {cov_seq}"
                    for _, a, en in covers
                ]
                cov_script = (
                    f"{read_cmd}; "
                    f"prep -top {shlex.quote(spec.top_module)}; "
                    f"flatten; memory_map; async2sync; dffunmap; chformal -assert -remove; chformal -cover -remove; "
                    + "; ".join(sat_cmds)
                )
                cov_res = run_subprocess([yosys_bin, "-p", cov_script], cwd=repo_root, timeout_sec=timeout_sec, env=env)
                solved_cnt = cov_res["stdout"].count("Solving problem")
                no_model_cnt = cov_res["stdout"].count("NO MODEL FOUND")
                covers_reached = max(0, solved_cnt - no_model_cnt)
                cover_ok = (
                    (cov_res["returncode"] == 0)
                    and (not cov_res["timed_out"])
                    and (solved_cnt == len(covers))
                    and (no_model_cnt == 0)
                )
                cov_status = "PASS" if cover_ok else "FAIL"
                cov_elapsed = round(dump_res["elapsed_sec"] + cov_res["elapsed_sec"], 3)
                cov_res_cmd = cov_res["command"]
                cov_rc = cov_res["returncode"]
                cov_to = cov_res["timed_out"]
                cov_tail = cov_res["stdout"].strip().splitlines()[-10:]

            result["cover_solver"] = f"yosys sat -set-assumes -set-at {cov_seq} EN=1,A=1 -seq {cov_seq} ({len(covers)} covers)"
            result["cover_verdict"] = "PASS" if cover_ok else "FAIL"
            result["cover_elapsed_sec"] = cov_elapsed
            result["cover"] = {
                "command": cov_res_cmd,
                "returncode": cov_rc,
                "elapsed_sec": cov_elapsed,
                "timed_out": cov_to,
                "covers_total": len(covers),
                "covers_reached": covers_reached,
                "status": cov_status,
                "log_tail": cov_tail,
            }

    result["verdict"] = "PASS" if (bmc_ok and cover_ok) else "FAIL"
    return result


def run_synth_smoke(
    spec: SynthSmokeSpec,
    repo_root: Path,
    yosys_bin: str,
    timeout_sec: int,
    env: dict[str, str],
) -> dict[str, Any]:
    read_cmd = build_read_slang_cmd(
        sources=spec.sources,
        include_dirs=spec.include_dirs,
        defines=spec.defines,
        top_module=spec.module_name,
        chparams=spec.chparams,
    )
    yosys_script = (
        f"{read_cmd}; "
        f"synth -top {shlex.quote(spec.module_name)}; "
        f"check -assert; "
        f"stat"
    )
    s_res = run_subprocess(
        [yosys_bin, "-p", yosys_script],
        cwd=repo_root,
        timeout_sec=timeout_sec,
        env=env,
    )
    stats = parse_synth_stats(s_res["stdout"])
    verdict = "PASS" if (s_res["returncode"] == 0 and not s_res["timed_out"]) else "FAIL"
    entry: dict[str, Any] = {
        "module": spec.module_name,
        "params": {k: int(v) if v.isdigit() else v for k, v in spec.chparams},
        "command": yosys_script,
        "verdict": verdict,
        "returncode": s_res["returncode"],
        "elapsed_sec": s_res["elapsed_sec"],
        "stats": stats,
    }
    if verdict != "PASS":
        entry["stderr_tail"] = s_res["stderr"].strip().splitlines()[-15:]
    return entry


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yosys", default=os.environ.get("YOSYS_BIN", DEFAULT_YOSYS))
    parser.add_argument("--smtbmc", default=os.environ.get("YOSYS_SMTBMC_BIN", DEFAULT_SMTBMC))
    parser.add_argument("--solver", default=DEFAULT_SOLVER)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--elab-only", action="store_true", help="Only run Yosys read_slang elaboration check")
    parser.add_argument("--skip-synth", action="store_true", help="Skip Yosys synth -top smoke checks")
    parser.add_argument("--harness", action="append", default=[], help="Filter specific harness_id(s)")
    parser.add_argument("--out-json", type=Path, default=None)
    return parser.parse_args(argv)


def resolve_tool_env(yosys_bin: str) -> dict[str, str]:
    env = os.environ.copy()
    yosys_dir = str(Path(yosys_bin).resolve().parent)
    if yosys_dir not in env.get("PATH", ""):
        env["PATH"] = f"{yosys_dir}:{env.get('PATH', '')}"
    return env


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = Path(__file__).resolve().parents[4]
    args.build_dir.mkdir(parents=True, exist_ok=True)
    env = resolve_tool_env(args.yosys)

    yosys_ver_res = run_subprocess([args.yosys, "-V"], cwd=repo_root, timeout_sec=30, env=env)
    z3_ver_res = run_subprocess([args.solver, "--version"], cwd=repo_root, timeout_sec=30, env=env)

    selected_harnesses = list(FORMAL_HARNESS_SPECS)
    if args.harness:
        wanted = set(args.harness)
        selected_harnesses = [h for h in FORMAL_HARNESS_SPECS if h.harness_id in wanted]
        if not selected_harnesses:
            print(f"No formal harnesses matched {sorted(wanted)}", file=sys.stderr)
            return 2

    formal_results: list[dict[str, Any]] = []
    overall_pass = True

    for spec in selected_harnesses:
        print(f"[RUN ] {spec.harness_id} (top={spec.top_module}, depth={spec.bmc_depth})")
        res = run_formal_harness(
            spec=spec,
            repo_root=repo_root,
            build_dir=args.build_dir,
            yosys_bin=args.yosys,
            smtbmc_bin=args.smtbmc,
            solver=args.solver,
            timeout_sec=args.timeout,
            elab_only=args.elab_only,
            env=env,
        )
        formal_results.append(res)
        if res["verdict"] not in ("PASS", "PASS_ELAB_ONLY"):
            overall_pass = False
        print(f"[{res['verdict']}] {spec.harness_id} ({res['yosys_elapsed_sec']}s elab)")

    synth_results: list[dict[str, Any]] = []
    if not args.skip_synth and not args.elab_only:
        for s_spec in SYNTH_SMOKE_SPECS:
            print(f"[SYNTH] {s_spec.module_name}")
            s_entry = run_synth_smoke(
                spec=s_spec,
                repo_root=repo_root,
                yosys_bin=args.yosys,
                timeout_sec=args.timeout,
                env=env,
            )
            synth_results.append(s_entry)
            if s_entry["verdict"] != "PASS":
                overall_pass = False
            print(f"[{s_entry['verdict']}] synth {s_spec.module_name} ({s_entry['elapsed_sec']}s)")

    summary = {
        "schema_version": 1,
        "wave_id": "W14",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "yosys_version": yosys_ver_res["stdout"].strip(),
        "solver": args.solver,
        "solver_version": z3_ver_res["stdout"].strip(),
        "build_dir": str(args.build_dir),
        "elab_only": args.elab_only,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
        "formal_harnesses": formal_results,
        "synth_smoke": synth_results,
    }

    out_json = args.out_json or (args.build_dir / "tcu_v2_formal_summary.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Summary written to {out_json}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
