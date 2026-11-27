# SPDX-License-Identifier: Apache-2.0
"""Run out-of-tree Verilator DV testbenches for TCU v2 and TMEM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[4]
BUILD_ROOT = Path("/home/antigravity/vortex_builds/w14_dv_sim")
RTL_ROOT = REPO_ROOT / "hw/rtl"
DV_SIM_DIR = Path(__file__).resolve().parent
BUILD_CFG_HW = Path("/home/antigravity/vortex_builds/build64_b2/hw")
VERILATOR_VLT = REPO_ROOT / "hw/unittest/verilator.vlt.in"

COMMON_PKGS = [
    str(RTL_ROOT / "tcu/v2/VX_tcu_v2_pkg.sv"),
    str(RTL_ROOT / "tmem/VX_tmem_pkg.sv"),
]

COMMON_INC = [
    f"-I{BUILD_CFG_HW}",
    f"-I{RTL_ROOT}",
    f"-I{RTL_ROOT}/libs",
    f"-I{RTL_ROOT}/interfaces",
    f"-I{RTL_ROOT}/tcu/v2",
    f"-I{RTL_ROOT}/tcu/v2/arith",
    f"-I{RTL_ROOT}/tcu/v2/fp8_bf16",
    f"-I{RTL_ROOT}/tcu/v2/array",
    f"-I{RTL_ROOT}/tcu/v2/ctrl",
    f"-I{RTL_ROOT}/tmem",
    f"-I{RTL_ROOT}/tmem/banks",
    f"-I{RTL_ROOT}/tmem/ctrl",
    f"-I{DV_SIM_DIR}",
]

TARGETS: dict[str, dict[str, object]] = {
    "golden_selftest": {
        "top": "tcu_v2_golden_ref",
        "tb": "tb_tcu_v2_golden_selftest.cpp",
        "params": [],
        "cpp_only": True,
        "rtl": [],
    },
    "fp4_fp6_fedp": {
        "top": "VX_tcu_v2_fp4_fp6_fedp_unit",
        "tb": "tb_fp4_fp6_fedp.cpp",
        "params": ["-GLANES=8"],
        "rtl": [
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e2m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e3m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_scale_decode.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_block_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lane_select.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_csa_tree.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lza_norm.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fp32_round.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_fp6_fedp_unit.sv"),
        ],
    },
    "fp8_bf16_fedp": {
        "top": "VX_tcu_v2_fp8_bf16_fedp_unit",
        "tb": "tb_fp8_bf16_fedp.cpp",
        "params": ["-GLANES=8"],
        "rtl": [
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e5m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_bf16_fp16_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_tf32_int8_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_mul_bank.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_mx_scale_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_csa_reduce.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp32_acc_norm.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp_exception_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_fedp_unit.sv"),
        ],
    },
    "systolic_array": {
        "top": "VX_tcu_v2_systolic_top",
        "tb": "tb_systolic_array.cpp",
        "params": ["-GARRAY_M=4", "-GARRAY_N=4", "-GARRAY_K=8"],
        "rtl": [
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e2m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e3m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_scale_decode.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_block_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lane_select.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_csa_tree.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lza_norm.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fp32_round.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_fp6_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e5m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_bf16_fp16_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_tf32_int8_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_mul_bank.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_mx_scale_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_csa_reduce.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp32_acc_norm.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp_exception_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_dbuf.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_scale_broadcast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_skew.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe_row.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_acc_tile_bank.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_output_drain.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_bias.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_act.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_cast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_array_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_systolic_top.sv"),
        ],
    },
    "sparse_wgmma": {
        "top": "VX_tcu_v2_top",
        "tb": "tb_sparse_wgmma.cpp",
        "params": ["-GARRAY_M=4", "-GARRAY_N=4", "-GARRAY_K=8", "-GNUM_PIPES=2"],
        "rtl": [
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e2m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e3m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_scale_decode.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_block_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lane_select.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_csa_tree.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lza_norm.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fp32_round.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_fp6_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e5m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_bf16_fp16_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_tf32_int8_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_mul_bank.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_mx_scale_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_csa_reduce.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp32_acc_norm.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp_exception_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_dbuf.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_scale_broadcast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_skew.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe_row.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_acc_tile_bank.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_output_drain.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_bias.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_act.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_cast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_array_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_systolic_top.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_wgmma_desc_q.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_wgmma_scoreboard.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_barrier_unit.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_cta_pair_sync.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_uop_expander.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_pipe_sched.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tmem_req_gen.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_validator.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_selector.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_compressor.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_decompressor.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_desc_arbiter.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tile_prefetch_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tmem_addr_mapper.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_commit_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_perf_mon.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_ctrl_regfile.sv"),
            str(RTL_ROOT / "tcu/v2/VX_tcu_v2_top.sv"),
        ],
    },
    "tmem_subsystem": {
        "top": "VX_tmem_top",
        "tb": "tb_tmem_subsystem.cpp",
        "params": ["-GNUM_BANKS=32", "-GBANK_DEPTH=1024", "-GLANES=8"],
        "rtl": [
            str(RTL_ROOT / "tmem/banks/VX_tmem_swizzle_addr.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_enc.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_dec.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_power_ctrl.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_sram_bank.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_conflict.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_rd_xbar.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_wr_xbar.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_rw_bypass.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_scrubber.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_array.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_allocator.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_bounds_chk.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_hazard_unit.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_arbiter.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_ld_engine.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_st_engine.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_mma_feeder.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_layout_xform.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_wait_barrier.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_perf_mon.sv"),
            str(RTL_ROOT / "tmem/VX_tmem_top.sv"),
        ],
    },
    "cluster_slice": {
        "top": "VX_tcu_tmem_cluster_slice",
        "tb": "tb_cluster_slice.cpp",
        "params": ["-GNUM_TCU_PIPES=2", "-GARRAY_M=4", "-GARRAY_N=4", "-GARRAY_K=8", "-GTMEM_LANES=8"],
        "rtl": [
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e2m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e3m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_scale_decode.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_block_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lane_select.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_csa_tree.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lza_norm.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fp32_round.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_fp6_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e5m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_bf16_fp16_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_tf32_int8_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_mul_bank.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_mx_scale_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_csa_reduce.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp32_acc_norm.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp_exception_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_dbuf.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_scale_broadcast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_skew.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe_row.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_acc_tile_bank.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_output_drain.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_bias.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_act.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_cast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_array_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_systolic_top.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_wgmma_desc_q.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_wgmma_scoreboard.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_barrier_unit.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_cta_pair_sync.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_uop_expander.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_pipe_sched.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tmem_req_gen.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_validator.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_selector.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_compressor.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_decompressor.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_desc_arbiter.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tile_prefetch_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tmem_addr_mapper.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_commit_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_perf_mon.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_ctrl_regfile.sv"),
            str(RTL_ROOT / "tcu/v2/VX_tcu_v2_top.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_swizzle_addr.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_enc.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_dec.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_power_ctrl.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_sram_bank.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_conflict.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_rd_xbar.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_wr_xbar.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_rw_bypass.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_scrubber.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_array.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_allocator.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_bounds_chk.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_hazard_unit.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_arbiter.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_ld_engine.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_st_engine.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_mma_feeder.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_layout_xform.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_wait_barrier.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_perf_mon.sv"),
            str(RTL_ROOT / "tmem/VX_tmem_top.sv"),
            str(RTL_ROOT / "tcu/v2/VX_tcu_tmem_cluster_slice.sv"),
        ],
    },
    "epilogue_and_sva": {
        "top": "VX_tcu_v2_cluster_sva_wrap",
        "tb": "tb_epilogue_and_sva.cpp",
        "params": ["-GNUM_TCU_PIPES=2", "-GARRAY_M=4", "-GARRAY_N=4", "-GARRAY_K=8", "-GTMEM_LANES=8"],
        "extra_flags": ["-DASSERTIONS", "-Wno-DECLFILENAME"],
        "rtl": [
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e2m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_e3m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_scale_decode.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_block_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp6_mul_lane.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lane_select.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_csa_tree.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_lza_norm.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_mx_fp32_round.sv"),
            str(RTL_ROOT / "tcu/v2/arith/VX_tcu_v2_fp4_fp6_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e4m3_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_e5m2_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_bf16_fp16_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_tf32_int8_unpack.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_mul_bank.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_mx_scale_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_fedp_align.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_csa_reduce.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp32_acc_norm.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_int8_dot_acc.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp_exception_unit.sv"),
            str(RTL_ROOT / "tcu/v2/fp8_bf16/VX_tcu_v2_fp8_bf16_fedp_unit.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_dbuf.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_scale_broadcast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_operand_skew.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_pe_row.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_acc_tile_bank.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_output_drain.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_bias.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_act.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_epilogue_cast.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_array_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/array/VX_tcu_v2_systolic_top.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_wgmma_desc_q.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_wgmma_scoreboard.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_barrier_unit.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_cta_pair_sync.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_uop_expander.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_pipe_sched.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tmem_req_gen.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_validator.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_selector.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_compressor.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_sparse_decompressor.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_desc_arbiter.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tile_prefetch_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_tmem_addr_mapper.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_commit_ctrl.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_perf_mon.sv"),
            str(RTL_ROOT / "tcu/v2/ctrl/VX_tcu_v2_ctrl_regfile.sv"),
            str(RTL_ROOT / "tcu/v2/VX_tcu_v2_top.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_swizzle_addr.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_enc.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_dec.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_power_ctrl.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_sram_bank.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_conflict.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_rd_xbar.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_wr_xbar.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_rw_bypass.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_ecc_scrubber.sv"),
            str(RTL_ROOT / "tmem/banks/VX_tmem_bank_array.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_allocator.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_bounds_chk.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_hazard_unit.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_arbiter.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_ld_engine.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_st_engine.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_mma_feeder.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_layout_xform.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_wait_barrier.sv"),
            str(RTL_ROOT / "tmem/ctrl/VX_tmem_perf_mon.sv"),
            str(RTL_ROOT / "tmem/VX_tmem_top.sv"),
            str(RTL_ROOT / "tcu/v2/VX_tcu_tmem_cluster_slice.sv"),
            str(REPO_ROOT / "hw/dv/tcu_v2/formal/VX_tcu_v2_sva_monitors.sv"),
            str(REPO_ROOT / "hw/dv/tcu_v2/formal/VX_tmem_sva_monitors.sv"),
            str(REPO_ROOT / "hw/dv/tcu_v2/formal/VX_tcu_v2_cluster_sva_wrap.sv"),
        ],
    },
}


def _newest_src_mtime(paths: list[str]) -> float:
    newest = 0.0
    for p_str in paths:
        p = Path(p_str)
        if p.exists():
            newest = max(newest, p.stat().st_mtime)
    return newest


def run_target(name: str, verilator_bin: str, lint_only: bool, opt_fast: str, clean: bool = False) -> dict[str, object]:
    import shutil
    cfg = TARGETS[name]
    top = str(cfg["top"])
    tb_cpp = str(DV_SIM_DIR / str(cfg["tb"]))
    ref_cpp = str(DV_SIM_DIR / "tcu_v2_golden_ref.cpp")
    ref_h = str(DV_SIM_DIR / "tcu_v2_golden_ref.h")
    params = list(cfg["params"])  # type: ignore[arg-type]
    rtl_files = list(cfg["rtl"])  # type: ignore[arg-type]

    extra_flags = list(cfg.get("extra_flags", []))  # type: ignore[arg-type]

    target_dir = BUILD_ROOT / name
    obj_dir = target_dir / "obj_dir"
    exe_path = target_dir / f"sim_{name}"

    if not lint_only:
        all_sources = [*COMMON_PKGS, *rtl_files, ref_h, ref_cpp, tb_cpp, str(VERILATOR_VLT)]
        stale = (not exe_path.exists()) or (exe_path.stat().st_mtime < _newest_src_mtime(all_sources))
        if clean or stale:
            if target_dir.exists():
                shutil.rmtree(target_dir)
    obj_dir.mkdir(parents=True, exist_ok=True)

    if bool(cfg.get("cpp_only", False)):
        if lint_only:
            return {
                "target": name,
                "top": top,
                "mode": "lint",
                "returncode": 0,
                "verdict": "PASS",
                "elapsed_sec": 0.0,
            }
        t0 = time.monotonic()
        cxx = os.environ.get("CXX", "g++")
        b_cmd = [cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", f"-I{DV_SIM_DIR}", ref_cpp, tb_cpp, "-o", str(exe_path)]
        print(f"[run_dv] BUILD {name} (C++20) -> {exe_path} ...")
        b_proc = subprocess.run(b_cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        if b_proc.stdout:
            print(b_proc.stdout, end="")
        if b_proc.stderr:
            print(b_proc.stderr, file=sys.stderr, end="")
        if b_proc.returncode != 0:
            return {
                "target": name,
                "top": top,
                "mode": "build",
                "returncode": b_proc.returncode,
                "verdict": "FAIL",
                "elapsed_sec": round(time.monotonic() - t0, 3),
            }
        print(f"[run_dv] RUN {name} ...")
        r_proc = subprocess.run([str(exe_path)], cwd=target_dir, capture_output=True, text=True, check=False)
        if r_proc.stdout:
            print(r_proc.stdout, end="")
        if r_proc.stderr:
            print(r_proc.stderr, file=sys.stderr, end="")
        return {
            "target": name,
            "top": top,
            "mode": "sim",
            "assertions_enabled": False,
            "returncode": r_proc.returncode,
            "verdict": "PASS" if r_proc.returncode == 0 else "FAIL",
            "elapsed_sec": round(time.monotonic() - t0, 3),
            "stdout_lines": [ln for ln in r_proc.stdout.splitlines() if ln.strip()],
        }

    cmd = [
        verilator_bin,
        "--language", "1800-2012",
        "--assert",
        "-Wall",
        "--x-initial", "unique",
        "--x-assign", "unique",
        str(VERILATOR_VLT),
        "-DSIMULATION",
        "-DVX_CFG_XLEN=64",
        "-DVX_CFG_XLEN_64",
        *extra_flags,
        *params,
        *COMMON_INC,
        "--top-module", top,
    ]
    t0 = time.monotonic()
    if lint_only:
        cmd.extend(["--lint-only", *COMMON_PKGS, *rtl_files])
        print(f"[run_dv] LINT {name} ({top}) ...")
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr, end="")
        return {
            "target": name,
            "top": top,
            "mode": "lint",
            "returncode": proc.returncode,
            "verdict": "PASS" if proc.returncode == 0 else "FAIL",
            "elapsed_sec": round(time.monotonic() - t0, 3),
        }

    cmd.extend([
        "--cc",
        "--exe",
        "--build",
        "-j", "1",
        "--output-split", "15000",
        "--output-split-cfuncs", "1000",
        "-MAKEFLAGS", f"OPT_FAST={opt_fast} OPT_SLOW=-O0",
        "--Mdir", str(obj_dir),
        "-o", str(exe_path),
        "-CFLAGS", f"-std=c++20 -I{DV_SIM_DIR}",
        *COMMON_PKGS,
        *rtl_files,
        ref_cpp,
        tb_cpp,
    ])
    print(f"[run_dv] BUILD {name} ({top}) -> {exe_path} ...")
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)
    build_proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False, timeout=480)
    if build_proc.stdout:
        print(build_proc.stdout, end="")
    if build_proc.stderr:
        print(build_proc.stderr, file=sys.stderr, end="")
    if build_proc.returncode != 0:
        return {
            "target": name,
            "top": top,
            "mode": "build",
            "returncode": build_proc.returncode,
            "verdict": "FAIL",
            "elapsed_sec": round(time.monotonic() - t0, 3),
        }

    print(f"[run_dv] RUN {name} ...")
    run_proc = subprocess.run([str(exe_path)], cwd=BUILD_ROOT / name, capture_output=True, text=True, check=False, timeout=120)
    if run_proc.stdout:
        print(run_proc.stdout, end="")
    if run_proc.stderr:
        print(run_proc.stderr, file=sys.stderr, end="")
    return {
        "target": name,
        "top": top,
        "mode": "sim",
        "assertions_enabled": ("-DASSERTIONS" in extra_flags),
        "returncode": run_proc.returncode,
        "verdict": "PASS" if run_proc.returncode == 0 else "FAIL",
        "elapsed_sec": round(time.monotonic() - t0, 3),
        "stdout_lines": [ln for ln in run_proc.stdout.splitlines() if ln.strip()],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Out-of-tree Verilator DV runner for TCU v2 and TMEM")
    parser.add_argument("--target", choices=["all", *TARGETS.keys()], default="all")
    parser.add_argument("--lint-only", action="store_true")
    parser.add_argument("--clean", action="store_true", help="Force clean rebuild of selected targets")
    parser.add_argument("--opt-fast", default="-O0", help="C++ optimization level for Verilated fast code")
    parser.add_argument("--json", type=Path, default=None, help="Optional path to write JSON telemetry")
    args = parser.parse_args()

    verilator_bin = os.environ.get("VERILATOR_BIN", "verilator")
    if Path("/home/antigravity/tools/verilator/bin/verilator").exists():
        verilator_bin = "/home/antigravity/tools/verilator/bin/verilator"

    selected = list(TARGETS.keys()) if args.target == "all" else [args.target]
    results: list[dict[str, object]] = []
    overall_rc = 0
    for name in selected:
        entry = run_target(name, verilator_bin, args.lint_only, args.opt_fast, args.clean)
        results.append(entry)
        rc = int(entry["returncode"])  # type: ignore[arg-type]
        if rc != 0:
            overall_rc = rc
            print(f"[run_dv] FAILED target={name} rc={rc}", file=sys.stderr)
            break

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "lint_only": args.lint_only,
            "overall_verdict": "PASS" if overall_rc == 0 else "FAIL",
            "targets": results,
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if overall_rc != 0:
        return overall_rc
    print(f"[run_dv] ALL PASSED ({len(selected)} targets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
