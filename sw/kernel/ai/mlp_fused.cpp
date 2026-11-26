// SPDX-License-Identifier: Apache-2.0

#include <ai_matmul_profile.h>
#include <ai_mlp_fused_args.h>
#include <vx_intrinsics.h>
#include <vx_spawn2.h>
#include <vx_tensor.h>

namespace va = vortex::ai;
namespace vt = vortex::tensor;
using ctx = vt::wmma_context<VX_CFG_NUM_THREADS, vt::ITYPE, vt::OTYPE, false, 8, 0, false>;

static_assert(ctx::tileM == 8 && ctx::tileN == 4 && ctx::tileK == 8);
static_assert(sizeof(uintptr_t) == 8);
static_assert(sizeof(ctx::input_t) == 2);
static_assert(sizeof(ctx::output_t) == 4);

namespace {

// Exact IEEE-754 binary32 -> binary16 round-to-nearest-even bit conversion.
// Preserves exact representation for integers in [0, 64]
// and follows IEEE-754 RNE for normal/subnormal/overflow/NaN/Inf inputs.
[[maybe_unused]] __attribute__((always_inline)) inline uint16_t f32_bits_to_fp16(uint32_t bits) {
  const uint32_t sign = (bits >> 16) & 0x8000u;
  const uint32_t exp = (bits >> 23) & 0xffu;
  const uint32_t frac = bits & 0x7fffffu;

  if (exp == 0xffu) {
    if (frac == 0) {
      return static_cast<uint16_t>(sign | 0x7c00u);
    }
    const uint32_t nan_frac = (frac >> 13) | 0x0200u;
    return static_cast<uint16_t>(sign | 0x7c00u | nan_frac);
  }

  const int32_t unbiased = static_cast<int32_t>(exp) - 127;
  if (unbiased > 15) {
    return static_cast<uint16_t>(sign | 0x7c00u);
  }
  if (unbiased < -25) {
    return static_cast<uint16_t>(sign);
  }
  if (unbiased < -14) {
    // Subnormal half: implicit leading 1 at bit 23 shifted right by (1 - unbiased - 14 + 13)
    const uint32_t sig = 0x800000u | frac;
    const uint32_t shift = static_cast<uint32_t>(-14 - unbiased) + 13u;
    const uint32_t half_frac = sig >> shift;
    const uint32_t rem = sig & ((1u << shift) - 1u);
    const uint32_t mid = 1u << (shift - 1u);
    const uint32_t round_up = (rem > mid || (rem == mid && (half_frac & 1u) != 0)) ? 1u : 0u;
    return static_cast<uint16_t>(sign | (half_frac + round_up));
  }

  const uint32_t half_exp = static_cast<uint32_t>(unbiased + 15);
  const uint32_t half_frac = frac >> 13;
  const uint32_t rem = frac & 0x1fffu;
  const uint32_t round_up = (rem > 0x1000u || (rem == 0x1000u && (half_frac & 1u) != 0)) ? 1u : 0u;
  uint32_t out = sign | (half_exp << 10) | half_frac;
  out += round_up;
  return static_cast<uint16_t>(out);
}

// Exact IEEE-754 binary32 -> bfloat16 round-to-nearest-even bit conversion.
[[maybe_unused]] __attribute__((always_inline)) inline uint16_t f32_bits_to_bf16(uint32_t bits) {
  const uint32_t abs_bits = bits & 0x7fffffffu;
  if (abs_bits > 0x7f800000u) {
    return static_cast<uint16_t>((bits >> 16) | 0x0040u);
  }
  const uint32_t lsb = (bits >> 16) & 1u;
  const uint32_t rounding_bias = 0x7fffu + lsb;
  return static_cast<uint16_t>((bits + rounding_bias) >> 16);
}

__attribute__((always_inline)) inline uint16_t relu_and_cast(float value) {
  uint32_t bits = 0;
  __builtin_memcpy(&bits, &value, sizeof(bits));
  // ReLU: clamp negative values and -0.0f to canonical +0.0f (0x0000).
  if ((bits & 0x80000000u) != 0 || (bits & 0x7fffffffu) == 0) {
    return 0;
  }
  if constexpr (va::kMatmulInputDType == va::kMlpFusedDTypeFp16) {
    return f32_bits_to_fp16(bits);
  } else {
    return f32_bits_to_bf16(bits);
  }
}

} // namespace

__kernel void kernel_main(const uint8_t* __UNIFORM__ bytes) {
  va::MlpFusedArguments arg;
  if (!va::decode_mlp_fused_arguments(bytes, va::kMlpFusedArgumentBytes,
                                      va::kMatmulInputDType, &arg)
      || blockDim.x != 16 || blockDim.y != 1 || blockDim.z != 1
      || gridDim.x != 1 || gridDim.y != 1 || gridDim.z != 1
      || blockIdx.x != 0 || blockIdx.y != 0 || blockIdx.z != 0) {
    return;
  }

  auto x = reinterpret_cast<const ctx::input_t*>(arg.x_addr);
  auto w1 = reinterpret_cast<const ctx::input_t*>(arg.w1_addr);
  auto w2 = reinterpret_cast<const ctx::input_t*>(arg.w2_addr);
  auto h_fp32 = reinterpret_cast<float*>(arg.h_scratch_addr);
  auto h_q16 = reinterpret_cast<ctx::input_t*>(
      arg.h_scratch_addr + va::kMlpFusedHScratchFp32Bytes);
  auto y = reinterpret_cast<ctx::output_t*>(arg.y_addr);

  auto lmem_h_q16 = reinterpret_cast<ctx::input_t*>(__local_mem());
  const bool dump_hidden = (arg.flags & va::kMlpFusedFlagWriteHiddenFp32) != 0;

  // 4 warps x 4 threads = 16 threads (100% occupancy on p02-tfr 1-core GPU).
  const uint32_t warp_id = threadIdx.x >> 2; // 0..3
  const uint32_t lane = threadIdx.x & 3u;    // 0..3
  const uint32_t tm = warp_id >> 1;          // 0 or 1
  const uint32_t tn = warp_id & 1u;          // 0 or 1

  constexpr uint32_t kHiddenCols = va::kMlpFusedN1; // 8
  constexpr uint32_t kInputCols = va::kMlpFusedK1;  // 16
  constexpr uint32_t kOutputCols = va::kMlpFusedN2; // 4

  const uint32_t lane_row0 = lane >> 1; // 0 or 1
  const uint32_t lane_col0 = lane & 1u; // 0 or 1

  // Hidden layer + ReLU/cast (fused in registers, 4 warps in parallel):
  //   Each warp computes one (8,4,8) tile of H = X[16,16] @ W1[16,8], applies
  //   ReLU + exact FP32->FP16/BF16 conversion directly from accumulator
  //   registers, and writes H_q16[16,8] row-major into on-core LMEM.
  {
    const uint32_t tile_row = tm * ctx::tileM; // 0 or 8
    const uint32_t tile_col = tn * ctx::tileN; // 0 or 4

    ctx::fragment_a frag_a;
    ctx::fragment_b frag_b;
    ctx::fragment_acc frag_h;
    ctx::fill_fragment(frag_h, 0);

    for (uint32_t k = 0; k < kInputCols; k += ctx::tileK) {
      ctx::load_matrix_sync(frag_a, x + tile_row * kInputCols + k, kInputCols);
      ctx::load_matrix_sync<vt::col_major>(frag_b, w1 + tile_col * kInputCols + k, kInputCols);
      ctx::mma_sync(frag_h, frag_a, frag_b, frag_h);
    }

    if (dump_hidden) {
      ctx::store_matrix_sync(h_fp32 + tile_row * kHiddenCols + tile_col, frag_h, kHiddenCols);
    }

    for (uint32_t r = 0; r < 8; ++r) {
      const uint32_t row = tile_row + lane_row0 + (r >> 1) * 2u;
      const uint32_t col = tile_col + lane_col0 + (r & 1u) * 2u;
      const uint16_t q16 = relu_and_cast(frag_h.data[r]);
      const uint32_t idx = row * kHiddenCols + col;
      lmem_h_q16[idx] = q16;
      if (dump_hidden) {
        h_q16[idx] = q16;
      }
    }
  }

  // Cross-warp fence + CTA barrier: ensure all 4 warps' LMEM writes to
  // lmem_h_q16 are visible before output-layer WMMA loads.
  vx_fence();
  __syncthreads();

  // Output layer (2 warps in parallel): Y[16,4] = H_q16[16,8] @ W2[8,4]
  if (warp_id < 2) {
    const uint32_t tile_row = warp_id * ctx::tileM; // 0 or 8
    ctx::fragment_a frag_a;
    ctx::fragment_b frag_b;
    ctx::fragment_acc frag_y;
    ctx::fill_fragment(frag_y, 0);

    ctx::load_matrix_sync(frag_a, lmem_h_q16 + tile_row * kHiddenCols, kHiddenCols);
    ctx::load_matrix_sync<vt::col_major>(frag_b, w2, kHiddenCols);
    ctx::mma_sync(frag_y, frag_a, frag_b, frag_y);

    ctx::store_matrix_sync(y + tile_row * kOutputCols, frag_y, kOutputCols);
  }
}
