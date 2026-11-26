// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_OPS_V2_ARGS_H
#define VORTEX_AI_OPS_V2_ARGS_H

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace vortex::ai {

constexpr uint32_t kOpsV2AbiVersion = 2;
constexpr uint32_t kOpsV2ArgumentBytes = 72;

enum OpsV2OpCode : uint32_t {
  kOpsV2OpReluFp32 = 1,
  kOpsV2OpGeluFp32 = 2,
  kOpsV2OpCastFp32ToFp16 = 3,
  kOpsV2OpCastFp16ToFp32 = 4,
  kOpsV2OpCastFp32ToBf16 = 5,
  kOpsV2OpCastBf16ToFp32 = 6,
  kOpsV2OpSoftmaxFp32 = 7,
  kOpsV2OpRmsNormFp32 = 8,
  kOpsV2OpLayerNormFp32 = 9,
  kOpsV2OpAttentionFp32 = 10,
};

constexpr uint32_t kOpsV2MaxElements = 65536;
constexpr uint32_t kOpsV2MaxAttentionSeq = 64;
constexpr uint32_t kOpsV2MaxAttentionDim = 64;

// Plain POD little-endian kernel argument block for unified v2 operator dispatch.
// Tensor layouts by op_code:
//   relu_fp32:         src0[rows*cols] f32 -> dst[rows*cols] f32 (flags == 0)
//   gelu_fp32:         src0[rows*cols] f32 -> dst[rows*cols] f32 (flags == 0)
//   cast_fp32_to_fp16: src0[rows*cols] f32 -> dst[rows*cols] u16 (flags == 0)
//   cast_fp16_to_fp32: src0[rows*cols] u16 -> dst[rows*cols] f32 (flags == 0)
//   cast_fp32_to_bf16: src0[rows*cols] f32 -> dst[rows*cols] u16 (flags == 0)
//   cast_bf16_to_fp32: src0[rows*cols] u16 -> dst[rows*cols] f32 (flags == 0)
//   softmax_fp32:      src0[rows, cols] f32 -> dst[rows, cols] f32 (row-wise)
//   rmsnorm_fp32:      src0[rows, cols] f32, src1[cols] f32 -> dst[rows, cols] f32
//   layernorm_fp32:    src0[rows, cols] f32, src1[cols] f32, src2[cols] f32 -> dst[rows, cols] f32
//   attention_fp32:    src0=Q[rows, cols] f32, src1=K[rows, cols] f32, src2=V[rows, cols] f32
//                      -> dst[rows, cols] f32 (rows=seq_len, cols=d_k)
struct alignas(8) OpsV2Arguments {
  uint32_t abi_version = kOpsV2AbiVersion;
  uint32_t byte_size = kOpsV2ArgumentBytes;
  uint32_t op_code = 0;
  uint32_t flags = 0;
  uint32_t rows = 0;
  uint32_t cols = 0;
  uint32_t eps_bits = 0x3727c5acU; // IEEE-754 float32 1e-5f
  uint32_t reserved = 0;
  uint64_t src0_addr = 0;
  uint64_t src1_addr = 0;
  uint64_t src2_addr = 0;
  uint64_t dst_addr = 0;
  uint64_t reserved64 = 0;
};

static_assert(std::is_standard_layout<OpsV2Arguments>::value);
static_assert(std::is_trivially_copyable<OpsV2Arguments>::value);
static_assert(sizeof(OpsV2Arguments) == kOpsV2ArgumentBytes);
static_assert(alignof(OpsV2Arguments) == 8);
static_assert(offsetof(OpsV2Arguments, abi_version) == 0);
static_assert(offsetof(OpsV2Arguments, byte_size) == 4);
static_assert(offsetof(OpsV2Arguments, op_code) == 8);
static_assert(offsetof(OpsV2Arguments, flags) == 12);
static_assert(offsetof(OpsV2Arguments, rows) == 16);
static_assert(offsetof(OpsV2Arguments, cols) == 20);
static_assert(offsetof(OpsV2Arguments, eps_bits) == 24);
static_assert(offsetof(OpsV2Arguments, reserved) == 28);
static_assert(offsetof(OpsV2Arguments, src0_addr) == 32);
static_assert(offsetof(OpsV2Arguments, src1_addr) == 40);
static_assert(offsetof(OpsV2Arguments, src2_addr) == 48);
static_assert(offsetof(OpsV2Arguments, dst_addr) == 56);
static_assert(offsetof(OpsV2Arguments, reserved64) == 64);

namespace ops_v2_detail {

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

inline bool is_finite_nonnegative_f32_bits(uint32_t bits) noexcept {
  const uint32_t exp = (bits >> 23) & 0xffu;
  return (bits & 0x80000000u) == 0 && exp != 0xffu;
}

} // namespace ops_v2_detail

inline bool decode_ops_v2_arguments(const uint8_t* bytes, size_t size,
                                    OpsV2Arguments* out) noexcept {
  if (bytes == nullptr || out == nullptr || size != kOpsV2ArgumentBytes) {
    return false;
  }

  OpsV2Arguments decoded;
  decoded.abi_version = ops_v2_detail::read32(bytes + 0);
  decoded.byte_size = ops_v2_detail::read32(bytes + 4);
  decoded.op_code = ops_v2_detail::read32(bytes + 8);
  decoded.flags = ops_v2_detail::read32(bytes + 12);
  decoded.rows = ops_v2_detail::read32(bytes + 16);
  decoded.cols = ops_v2_detail::read32(bytes + 20);
  decoded.eps_bits = ops_v2_detail::read32(bytes + 24);
  decoded.reserved = ops_v2_detail::read32(bytes + 28);
  decoded.src0_addr = ops_v2_detail::read64(bytes + 32);
  decoded.src1_addr = ops_v2_detail::read64(bytes + 40);
  decoded.src2_addr = ops_v2_detail::read64(bytes + 48);
  decoded.dst_addr = ops_v2_detail::read64(bytes + 56);
  decoded.reserved64 = ops_v2_detail::read64(bytes + 64);

  if (decoded.abi_version != kOpsV2AbiVersion
      || decoded.byte_size != kOpsV2ArgumentBytes
      || decoded.flags != 0
      || decoded.reserved != 0
      || decoded.reserved64 != 0
      || decoded.rows == 0
      || decoded.cols == 0) {
    return false;
  }

  if (uint64_t{decoded.rows} * uint64_t{decoded.cols} > kOpsV2MaxElements) {
    return false;
  }

  const uint64_t count = uint64_t{decoded.rows} * uint64_t{decoded.cols};
  uint64_t addrs[4] = {0, 0, 0, 0};
  uint64_t sizes[4] = {0, 0, 0, 0};
  size_t active_count = 0;

  switch (decoded.op_code) {
    case kOpsV2OpReluFp32:
    case kOpsV2OpGeluFp32:
    case kOpsV2OpSoftmaxFp32: {
      if (decoded.src1_addr != 0 || decoded.src2_addr != 0) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.dst_addr;
      sizes[1] = count * 4;
      active_count = 2;
      break;
    }
    case kOpsV2OpCastFp32ToFp16:
    case kOpsV2OpCastFp32ToBf16: {
      if (decoded.src1_addr != 0 || decoded.src2_addr != 0) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.dst_addr;
      sizes[1] = count * 2;
      active_count = 2;
      break;
    }
    case kOpsV2OpCastFp16ToFp32:
    case kOpsV2OpCastBf16ToFp32: {
      if (decoded.src1_addr != 0 || decoded.src2_addr != 0) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 2;
      addrs[1] = decoded.dst_addr;
      sizes[1] = count * 4;
      active_count = 2;
      break;
    }
    case kOpsV2OpRmsNormFp32: {
      if (decoded.src2_addr != 0
          || !ops_v2_detail::is_finite_nonnegative_f32_bits(decoded.eps_bits)) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = uint64_t{decoded.cols} * 4;
      addrs[2] = decoded.dst_addr;
      sizes[2] = count * 4;
      active_count = 3;
      break;
    }
    case kOpsV2OpLayerNormFp32: {
      if (!ops_v2_detail::is_finite_nonnegative_f32_bits(decoded.eps_bits)) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = uint64_t{decoded.cols} * 4;
      addrs[2] = decoded.src2_addr;
      sizes[2] = uint64_t{decoded.cols} * 4;
      addrs[3] = decoded.dst_addr;
      sizes[3] = count * 4;
      active_count = 4;
      break;
    }
    case kOpsV2OpAttentionFp32: {
      if (decoded.rows > kOpsV2MaxAttentionSeq || decoded.cols > kOpsV2MaxAttentionDim) {
        return false;
      }
      addrs[0] = decoded.src0_addr;
      sizes[0] = count * 4;
      addrs[1] = decoded.src1_addr;
      sizes[1] = count * 4;
      addrs[2] = decoded.src2_addr;
      sizes[2] = count * 4;
      addrs[3] = decoded.dst_addr;
      sizes[3] = count * 4;
      active_count = 4;
      break;
    }
    default:
      return false;
  }

  for (size_t i = 0; i < active_count; ++i) {
    if (!ops_v2_detail::range_valid(addrs[i], sizes[i])) {
      return false;
    }
    for (size_t j = i + 1; j < active_count; ++j) {
      if (ops_v2_detail::ranges_overlap(addrs[i], sizes[i], addrs[j], sizes[j])) {
        return false;
      }
    }
  }

  *out = decoded;
  return true;
}

} // namespace vortex::ai

#endif // VORTEX_AI_OPS_V2_ARGS_H
