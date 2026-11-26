// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_LLM_OPS_V3_ARGS_H
#define VORTEX_AI_LLM_OPS_V3_ARGS_H

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace vortex::ai {

constexpr uint32_t kLlmOpsV3AbiVersion = 3;
constexpr uint32_t kLlmOpsV3ArgumentBytes = 128;

enum LlmOpsV3OpCode : uint32_t {
  kLlmOpRopeFp32 = 1,
  kLlmOpSwigluFp32 = 2,
  kLlmOpKvCacheAppendFp32 = 3,
  kLlmOpGqaDecodeAttnFp32 = 4,
  kLlmOpFlashAttnTiledFp32 = 5,
  kLlmOpRmsNormFp32 = 6,
  kLlmOpAddFp32 = 7,
  kLlmOpGemvFp32 = 8,
};

constexpr uint32_t kLlmFlagCausal = 1u << 0;
constexpr uint32_t kLlmFlagAll = kLlmFlagCausal;

constexpr uint32_t kLlmV3MaxElements = 262144;
constexpr uint32_t kLlmV3FlashTileBr = 4;
constexpr uint32_t kLlmV3FlashTileBc = 4;
constexpr uint32_t kLlmV3FlashMaxHeadDim = 64;
constexpr uint32_t kLlmV3FlashLmemBytes =
    4u * ((kLlmV3FlashTileBr * kLlmV3FlashMaxHeadDim) * 2u
          + (kLlmV3FlashTileBc * kLlmV3FlashMaxHeadDim) * 2u
          + (kLlmV3FlashTileBr * kLlmV3FlashTileBc));

constexpr uint32_t kLlmV3DefaultEpsBits = 0x3727c5acU;   // 1e-5f
constexpr uint32_t kLlmV3DefaultThetaBits = 0x461c4000U; // 10000.0f

// Plain POD little-endian kernel argument block for unified v3 LLM operator dispatch.
// Tensor layouts by op_code (compact row-major FP32):
//   kLlmOpRopeFp32:
//     src0[dim0=seq_len, dim1=n_heads, dim2=d_head] -> dst[seq_len, n_heads, d_head]
//     (d_head even, pos_offset >= 0, eps_or_theta_bits = theta > 0).
//   kLlmOpSwigluFp32:
//     src0=gate[dim0=rows, dim1=cols], src1=up[rows, cols] -> dst[rows, cols].
//   kLlmOpKvCacheAppendFp32:
//     src0=k_new[dim0=n_new, dim1=n_kv_heads, dim2=d_head],
//     src1=v_new[n_new, n_kv_heads, d_head]
//     -> dst=k_cache[dim3=max_seq, n_kv_heads, d_head],
//        dst2=v_cache[max_seq, n_kv_heads, d_head] at [pos_offset, pos_offset + n_new).
//   kLlmOpGqaDecodeAttnFp32:
//     src0=q[1, dim1=n_q_heads, dim2=d_head],
//     src1=k_cache[dim0=kv_len, dim3=n_kv_heads, d_head],
//     src2=v_cache[kv_len, n_kv_heads, d_head]
//     -> dst[1, n_q_heads, d_head] (n_q_heads % n_kv_heads == 0).
//   kLlmOpFlashAttnTiledFp32:
//     src0=q[dim0=seq_len, dim1=n_q_heads, dim2=d_head],
//     src1=k[dim0=seq_len, dim3=n_kv_heads, d_head],
//     src2=v[seq_len, n_kv_heads, d_head]
//     -> dst[seq_len, n_q_heads, d_head]; flags bit 0 selects causal mask j <= i + pos_offset.
//   kLlmOpRmsNormFp32:
//     src0[dim0=rows, dim1=cols], src1=weight[cols] -> dst[rows, cols], eps_or_theta_bits=eps.
//   kLlmOpAddFp32:
//     src0[dim0=rows, dim1=cols], src1[rows, cols] -> dst[rows, cols].
//   kLlmOpGemvFp32:
//     src0=A[dim0=M, dim1=K], src1=B[dim2=N, dim1=K] (row-major weights) -> dst[M, N].
struct alignas(8) LlmOpsV3Arguments {
  uint32_t abi_version = kLlmOpsV3AbiVersion;
  uint32_t byte_size = kLlmOpsV3ArgumentBytes;
  uint32_t op_code = 0;
  uint32_t flags = 0;
  uint32_t dim0 = 0;
  uint32_t dim1 = 0;
  uint32_t dim2 = 0;
  uint32_t dim3 = 0;
  uint32_t pos_offset = 0;
  uint32_t eps_or_theta_bits = kLlmV3DefaultEpsBits;
  uint32_t reserved0 = 0;
  uint32_t reserved1 = 0;
  uint64_t src0_addr = 0;
  uint64_t src1_addr = 0;
  uint64_t src2_addr = 0;
  uint64_t dst_addr = 0;
  uint64_t dst2_addr = 0;
  uint64_t reserved64_0 = 0;
  uint64_t reserved64_1 = 0;
  uint64_t reserved64_2 = 0;
  uint64_t reserved64_3 = 0;
  uint64_t reserved64_4 = 0;
};

static_assert(std::is_standard_layout<LlmOpsV3Arguments>::value);
static_assert(std::is_trivially_copyable<LlmOpsV3Arguments>::value);
static_assert(sizeof(LlmOpsV3Arguments) == kLlmOpsV3ArgumentBytes);
static_assert(alignof(LlmOpsV3Arguments) == 8);
static_assert(offsetof(LlmOpsV3Arguments, abi_version) == 0);
static_assert(offsetof(LlmOpsV3Arguments, byte_size) == 4);
static_assert(offsetof(LlmOpsV3Arguments, op_code) == 8);
static_assert(offsetof(LlmOpsV3Arguments, flags) == 12);
static_assert(offsetof(LlmOpsV3Arguments, dim0) == 16);
static_assert(offsetof(LlmOpsV3Arguments, dim1) == 20);
static_assert(offsetof(LlmOpsV3Arguments, dim2) == 24);
static_assert(offsetof(LlmOpsV3Arguments, dim3) == 28);
static_assert(offsetof(LlmOpsV3Arguments, pos_offset) == 32);
static_assert(offsetof(LlmOpsV3Arguments, eps_or_theta_bits) == 36);
static_assert(offsetof(LlmOpsV3Arguments, reserved0) == 40);
static_assert(offsetof(LlmOpsV3Arguments, reserved1) == 44);
static_assert(offsetof(LlmOpsV3Arguments, src0_addr) == 48);
static_assert(offsetof(LlmOpsV3Arguments, src1_addr) == 56);
static_assert(offsetof(LlmOpsV3Arguments, src2_addr) == 64);
static_assert(offsetof(LlmOpsV3Arguments, dst_addr) == 72);
static_assert(offsetof(LlmOpsV3Arguments, dst2_addr) == 80);
static_assert(offsetof(LlmOpsV3Arguments, reserved64_0) == 88);
static_assert(offsetof(LlmOpsV3Arguments, reserved64_1) == 96);
static_assert(offsetof(LlmOpsV3Arguments, reserved64_2) == 104);
static_assert(offsetof(LlmOpsV3Arguments, reserved64_3) == 112);
static_assert(offsetof(LlmOpsV3Arguments, reserved64_4) == 120);

namespace llm_ops_v3_detail {

inline uint32_t read32(const uint8_t* bytes) noexcept {
  uint32_t value = 0;
  for (uint32_t i = 0; i < 4; ++i) {
    value |= uint32_t{bytes[i]} << (8 * i);
  }
  return value;
}

inline uint64_t read64(const uint8_t* bytes) noexcept {
  uint64_t value = 0;
  for (uint32_t i = 0; i < 8; ++i) {
    value |= uint64_t{bytes[i]} << (8 * i);
  }
  return value;
}

inline bool range_valid(uint64_t address, uint64_t size) noexcept {
  return address != 0 && (address % 4 == 0) && size > 0 && (size - 1 <= UINT64_MAX - address);
}

inline bool ranges_overlap(uint64_t a, uint64_t a_size,
                           uint64_t b, uint64_t b_size) noexcept {
  return a <= b + (b_size - 1) && b <= a + (a_size - 1);
}

inline bool mul_u64_checked(uint64_t a, uint64_t b, uint64_t* out) noexcept {
  if (a != 0 && b > UINT64_MAX / a) {
    return false;
  }
  *out = a * b;
  return true;
}

inline bool mul3_u64_checked(uint64_t a, uint64_t b, uint64_t c, uint64_t* out) noexcept {
  uint64_t ab = 0;
  if (!mul_u64_checked(a, b, &ab)) {
    return false;
  }
  return mul_u64_checked(ab, c, out);
}

inline bool is_finite_nonnegative_f32_bits(uint32_t bits) noexcept {
  const uint32_t exp = (bits >> 23) & 0xffu;
  return (bits & 0x80000000u) == 0 && exp != 0xffu;
}

inline bool is_finite_positive_normal_f32_bits(uint32_t bits) noexcept {
  const uint32_t exp = (bits >> 23) & 0xffu;
  return (bits & 0x80000000u) == 0 && exp > 0 && exp < 0xffu;
}

inline uint32_t flash_lmem_bytes_required(uint32_t d_head) noexcept {
  return 4u * ((kLlmV3FlashTileBr * d_head) * 2u
               + (kLlmV3FlashTileBc * d_head) * 2u
               + (kLlmV3FlashTileBr * kLlmV3FlashTileBc));
}

} // namespace llm_ops_v3_detail

inline bool decode_llm_ops_v3_arguments(const uint8_t* bytes, size_t size,
                                        LlmOpsV3Arguments* out) noexcept {
  if (bytes == nullptr || out == nullptr || size != kLlmOpsV3ArgumentBytes) {
    return false;
  }

  LlmOpsV3Arguments decoded;
  decoded.abi_version = llm_ops_v3_detail::read32(bytes + 0);
  decoded.byte_size = llm_ops_v3_detail::read32(bytes + 4);
  decoded.op_code = llm_ops_v3_detail::read32(bytes + 8);
  decoded.flags = llm_ops_v3_detail::read32(bytes + 12);
  decoded.dim0 = llm_ops_v3_detail::read32(bytes + 16);
  decoded.dim1 = llm_ops_v3_detail::read32(bytes + 20);
  decoded.dim2 = llm_ops_v3_detail::read32(bytes + 24);
  decoded.dim3 = llm_ops_v3_detail::read32(bytes + 28);
  decoded.pos_offset = llm_ops_v3_detail::read32(bytes + 32);
  decoded.eps_or_theta_bits = llm_ops_v3_detail::read32(bytes + 36);
  decoded.reserved0 = llm_ops_v3_detail::read32(bytes + 40);
  decoded.reserved1 = llm_ops_v3_detail::read32(bytes + 44);
  decoded.src0_addr = llm_ops_v3_detail::read64(bytes + 48);
  decoded.src1_addr = llm_ops_v3_detail::read64(bytes + 56);
  decoded.src2_addr = llm_ops_v3_detail::read64(bytes + 64);
  decoded.dst_addr = llm_ops_v3_detail::read64(bytes + 72);
  decoded.dst2_addr = llm_ops_v3_detail::read64(bytes + 80);
  decoded.reserved64_0 = llm_ops_v3_detail::read64(bytes + 88);
  decoded.reserved64_1 = llm_ops_v3_detail::read64(bytes + 96);
  decoded.reserved64_2 = llm_ops_v3_detail::read64(bytes + 104);
  decoded.reserved64_3 = llm_ops_v3_detail::read64(bytes + 112);
  decoded.reserved64_4 = llm_ops_v3_detail::read64(bytes + 120);

  if (decoded.abi_version != kLlmOpsV3AbiVersion
      || decoded.byte_size != kLlmOpsV3ArgumentBytes
      || (decoded.flags & ~kLlmFlagAll) != 0
      || decoded.reserved0 != 0
      || decoded.reserved1 != 0
      || decoded.reserved64_0 != 0
      || decoded.reserved64_1 != 0
      || decoded.reserved64_2 != 0
      || decoded.reserved64_3 != 0
      || decoded.reserved64_4 != 0) {
    return false;
  }

  uint64_t addrs[5] = {0, 0, 0, 0, 0};
  uint64_t sizes[5] = {0, 0, 0, 0, 0};
  size_t active_count = 0;

  switch (decoded.op_code) {
    case kLlmOpRopeFp32: {
      if (decoded.flags != 0 || decoded.dim0 == 0 || decoded.dim1 == 0
          || decoded.dim2 == 0 || (decoded.dim2 & 1u) != 0 || decoded.dim3 != 0
          || decoded.src1_addr != 0 || decoded.src2_addr != 0 || decoded.dst2_addr != 0
          || !llm_ops_v3_detail::is_finite_positive_normal_f32_bits(decoded.eps_or_theta_bits)) {
        return false;
      }
      uint64_t count = 0;
      if (!llm_ops_v3_detail::mul3_u64_checked(decoded.dim0, decoded.dim1, decoded.dim2, &count)
          || count > kLlmV3MaxElements) {
        return false;
      }
      if (uint64_t{decoded.pos_offset} + uint64_t{decoded.dim0} > UINT32_MAX) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.dst_addr;
      sizes[1] = count * 4;
      active_count = 2;
      break;
    }
    case kLlmOpSwigluFp32:
    case kLlmOpAddFp32: {
      if (decoded.flags != 0 || decoded.dim0 == 0 || decoded.dim1 == 0
          || decoded.dim2 != 0 || decoded.dim3 != 0 || decoded.pos_offset != 0
          || decoded.src2_addr != 0 || decoded.dst2_addr != 0) {
        return false;
      }
      uint64_t count = 0;
      if (!llm_ops_v3_detail::mul_u64_checked(decoded.dim0, decoded.dim1, &count)
          || count > kLlmV3MaxElements) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = count * 4;
      addrs[2] = decoded.dst_addr;
      sizes[2] = count * 4;
      active_count = 3;
      break;
    }
    case kLlmOpKvCacheAppendFp32: {
      if (decoded.flags != 0 || decoded.dim0 == 0 || decoded.dim1 == 0
          || decoded.dim2 == 0 || decoded.dim3 == 0 || decoded.src2_addr != 0) {
        return false;
      }
      if (uint64_t{decoded.pos_offset} + uint64_t{decoded.dim0} > uint64_t{decoded.dim3}) {
        return false;
      }
      uint64_t new_count = 0;
      uint64_t cache_count = 0;
      if (!llm_ops_v3_detail::mul3_u64_checked(decoded.dim0, decoded.dim1, decoded.dim2, &new_count)
          || !llm_ops_v3_detail::mul3_u64_checked(decoded.dim3, decoded.dim1, decoded.dim2, &cache_count)
          || new_count > kLlmV3MaxElements
          || cache_count > kLlmV3MaxElements) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = new_count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = new_count * 4;
      addrs[2] = decoded.dst_addr;
      sizes[2] = cache_count * 4;
      addrs[3] = decoded.dst2_addr;
      sizes[3] = cache_count * 4;
      active_count = 4;
      break;
    }
    case kLlmOpGqaDecodeAttnFp32: {
      if (decoded.flags != 0 || decoded.dim0 == 0 || decoded.dim1 == 0
          || decoded.dim2 == 0 || decoded.dim3 == 0 || decoded.pos_offset != 0
          || decoded.dst2_addr != 0
          || (decoded.dim1 % decoded.dim3) != 0) {
        return false;
      }
      uint64_t q_count = 0;
      uint64_t kv_count = 0;
      if (!llm_ops_v3_detail::mul_u64_checked(decoded.dim1, decoded.dim2, &q_count)
          || !llm_ops_v3_detail::mul3_u64_checked(decoded.dim0, decoded.dim3, decoded.dim2, &kv_count)
          || q_count > kLlmV3MaxElements
          || kv_count > kLlmV3MaxElements) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = q_count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = kv_count * 4;
      addrs[2] = decoded.src2_addr;
      sizes[2] = kv_count * 4;
      addrs[3] = decoded.dst_addr;
      sizes[3] = q_count * 4;
      active_count = 4;
      break;
    }
    case kLlmOpFlashAttnTiledFp32: {
      if (decoded.dim0 == 0 || decoded.dim1 == 0 || decoded.dim2 == 0
          || decoded.dim3 == 0 || decoded.dim2 > kLlmV3FlashMaxHeadDim
          || decoded.dst2_addr != 0 || (decoded.dim1 % decoded.dim3) != 0) {
        return false;
      }
      uint64_t q_count = 0;
      uint64_t kv_count = 0;
      if (!llm_ops_v3_detail::mul3_u64_checked(decoded.dim0, decoded.dim1, decoded.dim2, &q_count)
          || !llm_ops_v3_detail::mul3_u64_checked(decoded.dim0, decoded.dim3, decoded.dim2, &kv_count)
          || q_count > kLlmV3MaxElements
          || kv_count > kLlmV3MaxElements) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = q_count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = kv_count * 4;
      addrs[2] = decoded.src2_addr;
      sizes[2] = kv_count * 4;
      addrs[3] = decoded.dst_addr;
      sizes[3] = q_count * 4;
      active_count = 4;
      break;
    }
    case kLlmOpRmsNormFp32: {
      if (decoded.flags != 0 || decoded.dim0 == 0 || decoded.dim1 == 0
          || decoded.dim2 != 0 || decoded.dim3 != 0 || decoded.pos_offset != 0
          || decoded.src2_addr != 0 || decoded.dst2_addr != 0
          || !llm_ops_v3_detail::is_finite_nonnegative_f32_bits(decoded.eps_or_theta_bits)) {
        return false;
      }
      uint64_t count = 0;
      if (!llm_ops_v3_detail::mul_u64_checked(decoded.dim0, decoded.dim1, &count)
          || count > kLlmV3MaxElements) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = uint64_t{decoded.dim1} * 4;
      addrs[2] = decoded.dst_addr;
      sizes[2] = count * 4;
      active_count = 3;
      break;
    }
    case kLlmOpGemvFp32: {
      if (decoded.flags != 0 || decoded.dim0 == 0 || decoded.dim1 == 0
          || decoded.dim2 == 0 || decoded.dim3 != 0 || decoded.pos_offset != 0
          || decoded.src2_addr != 0 || decoded.dst2_addr != 0) {
        return false;
      }
      uint64_t a_count = 0;
      uint64_t b_count = 0;
      uint64_t c_count = 0;
      if (!llm_ops_v3_detail::mul_u64_checked(decoded.dim0, decoded.dim1, &a_count)
          || !llm_ops_v3_detail::mul_u64_checked(decoded.dim2, decoded.dim1, &b_count)
          || !llm_ops_v3_detail::mul_u64_checked(decoded.dim0, decoded.dim2, &c_count)
          || a_count > kLlmV3MaxElements
          || b_count > kLlmV3MaxElements
          || c_count > kLlmV3MaxElements) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = a_count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = b_count * 4;
      addrs[2] = decoded.dst_addr;
      sizes[2] = c_count * 4;
      active_count = 3;
      break;
    }
    default:
      return false;
  }

  for (size_t i = 0; i < active_count; ++i) {
    if (!llm_ops_v3_detail::range_valid(addrs[i], sizes[i])) {
      return false;
    }
    for (size_t j = i + 1; j < active_count; ++j) {
      if (llm_ops_v3_detail::ranges_overlap(addrs[i], sizes[i], addrs[j], sizes[j])) {
        return false;
      }
    }
  }

  *out = decoded;
  return true;
}

} // namespace vortex::ai

#endif // VORTEX_AI_LLM_OPS_V3_ARGS_H
