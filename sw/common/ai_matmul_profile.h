// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_MATMUL_PROFILE_H
#define VORTEX_AI_MATMUL_PROFILE_H

#include <cstdint>

#if !defined(VX_CFG_EXT_TCU_ENABLE) || !defined(VX_CFG_TCU_TYPE_TFR) \
    || !defined(VX_CFG_FPU_TYPE_STD) || !defined(VX_CFG_TCU_FP16_ENABLE) \
    || !defined(VX_CFG_LMEM_ENABLE)
#error "AI matmul requires the native TFR/STD FP16 bank and local memory"
#endif

#if defined(VX_CFG_TCU_TYPE_DPI) || defined(VX_CFG_TCU_TYPE_DSP) \
    || defined(VX_CFG_TCU_TYPE_BHF) || defined(VX_CFG_TCU_TYPE_FPNEW) \
    || defined(VX_CFG_FPU_TYPE_DPI) || defined(VX_CFG_FPU_TYPE_DSP) \
    || defined(VX_CFG_FPU_TYPE_FPNEW)
#error "AI matmul requires only the native TFR/STD arithmetic selectors"
#endif

#if VX_CFG_XLEN != 64 || VX_CFG_NUM_CLUSTERS != 1 || VX_CFG_NUM_CORES != 1 \
    || VX_CFG_NUM_THREADS != 4 || VX_CFG_NUM_WARPS != 4 || VX_CFG_ISSUE_WIDTH != 1 \
    || VX_CFG_NUM_ALU_BLOCKS != 1 || VX_CFG_NUM_LSU_BLOCKS != 1 \
    || VX_CFG_NUM_FPU_BLOCKS != 1 || VX_CFG_NUM_TCU_BLOCKS != 1 \
    || VX_CFG_NUM_TCU_LANES != 4 || VX_CFG_LMEM_SIZE != 16384
#error "AI matmul requires the accepted ordinary WMMA RV64 geometry"
#endif

#if !defined(VX_CFG_TCU_USE_DSP) || VX_CFG_TCU_USE_DSP != 0 \
    || VX_CFG_TCU_PE_RATIO != 1 || VX_CFG_TCU_LATENCY != 4
#error "AI matmul requires the accepted native TFR reduction profile"
#endif

#if defined(VX_CFG_TCU_TF32_ENABLE) || defined(VX_CFG_TCU_FP8_ENABLE) \
    || defined(VX_CFG_TCU_FP4_ENABLE) || defined(VX_CFG_TCU_INT8_ENABLE) \
    || defined(VX_CFG_TCU_INT4_ENABLE) || defined(VX_CFG_TCU_MX_ENABLE) \
    || defined(VX_CFG_TCU_MXFP4_ENABLE) || defined(VX_CFG_TCU_NVFP4_ENABLE) \
    || defined(VX_CFG_TCU_SPARSE_ENABLE) || defined(VX_CFG_TCU_DSM_ENABLE) \
    || defined(VX_CFG_TCU_WGMMA_ENABLE) || defined(VX_CFG_TCU_FEDP2K) \
    || defined(VX_CFG_EXT_LDST_MATRIX_ENABLE)
#error "AI matmul requires the accepted ordinary WMMA format and feature exclusions"
#endif

#if !defined(KUNROLL) || KUNROLL != 1
#error "AI matmul requires KUNROLL=1"
#endif

#define VX_AI_DTYPE_fp16 1
#define VX_AI_DTYPE_bf16 2
#define VX_AI_DTYPE_fp32 3
#define VX_AI_DTYPE_EXPAND_(name) VX_AI_DTYPE_##name
#define VX_AI_DTYPE_EXPAND(name) VX_AI_DTYPE_EXPAND_(name)

#if VX_AI_DTYPE_EXPAND(ITYPE) != 1 && VX_AI_DTYPE_EXPAND(ITYPE) != 2
#error "AI matmul input must be FP16 or BF16"
#endif
#if VX_AI_DTYPE_EXPAND(OTYPE) != 3
#error "AI matmul output must be FP32"
#endif

namespace vortex::ai {

constexpr uint32_t kMatmulInputDType = VX_AI_DTYPE_EXPAND(ITYPE);

} // namespace vortex::ai

#undef VX_AI_DTYPE_EXPAND
#undef VX_AI_DTYPE_EXPAND_
#undef VX_AI_DTYPE_fp32
#undef VX_AI_DTYPE_bf16
#undef VX_AI_DTYPE_fp16

#endif
