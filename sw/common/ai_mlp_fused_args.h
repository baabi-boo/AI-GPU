// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_MLP_FUSED_ARGS_H
#define VORTEX_AI_MLP_FUSED_ARGS_H

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace vortex::ai {

constexpr uint32_t kMlpFusedAbiVersion = 1;
constexpr uint32_t kMlpFusedArgumentBytes = 64;

constexpr uint32_t kMlpFusedDTypeFp16 = 1;
constexpr uint32_t kMlpFusedDTypeBf16 = 2;

constexpr uint32_t kMlpFusedFlagWriteHiddenFp32 = 1u << 0;

constexpr uint32_t kMlpFusedM1 = 16;
constexpr uint32_t kMlpFusedK1 = 16;
constexpr uint32_t kMlpFusedN1 = 8;
constexpr uint32_t kMlpFusedN2 = 4;

constexpr uint64_t kMlpFusedXBytes = uint64_t{kMlpFusedM1} * kMlpFusedK1 * 2;
constexpr uint64_t kMlpFusedW1Bytes = uint64_t{kMlpFusedK1} * kMlpFusedN1 * 2;
constexpr uint64_t kMlpFusedW2Bytes = uint64_t{kMlpFusedN1} * kMlpFusedN2 * 2;
constexpr uint64_t kMlpFusedHScratchFp32Bytes = uint64_t{kMlpFusedM1} * kMlpFusedN1 * 4;
constexpr uint64_t kMlpFusedHScratchQ16Bytes = uint64_t{kMlpFusedM1} * kMlpFusedN1 * 2;
constexpr uint64_t kMlpFusedHScratchBytes = kMlpFusedHScratchFp32Bytes + kMlpFusedHScratchQ16Bytes;
constexpr uint64_t kMlpFusedYBytes = uint64_t{kMlpFusedM1} * kMlpFusedN2 * 4;

// Plain POD little-endian kernel argument block for single-launch fused Tiny-MLP:
//   X[16,16] row-major @ W1[16,8] col-major -> H_fp32[16,8] (optional scratch write)
//   -> ReLU + FP32->FP16/BF16 -> H_q16[16,8] row-major in on-core LMEM
//      (and optionally mirrored to h_scratch_addr)
//   -> H_q16[16,8] @ W2[8,4] col-major -> Y[16,4] row-major FP32 logits.
// When (flags & kMlpFusedFlagWriteHiddenFp32) != 0, h_scratch_addr must point to a
// 4-byte-aligned, non-overlapping 768-byte scratch buffer laid out as:
//   [0, 512)   = H_fp32[16,8] (128 x uint32_t),
//   [512, 768) = H_q16[16,8]  (128 x uint16_t).
// When flags == 0, h_scratch_addr may be 0 (unused); if nonzero, it must still be
// 4-byte aligned, non-wrapping, and disjoint from the other device buffers.
struct alignas(8) MlpFusedArguments {
  uint32_t abi_version = kMlpFusedAbiVersion;
  uint32_t byte_size = kMlpFusedArgumentBytes;
  uint32_t input_dtype = 0; // 1 = fp16, 2 = bf16
  uint32_t flags = 0;       // bit 0: materialize H_fp32 and H_q16 in h_scratch_addr
  uint64_t x_addr = 0;
  uint64_t w1_addr = 0;
  uint64_t w2_addr = 0;
  uint64_t h_scratch_addr = 0;
  uint64_t y_addr = 0;
  uint64_t reserved = 0;
};

static_assert(std::is_standard_layout<MlpFusedArguments>::value);
static_assert(std::is_trivially_copyable<MlpFusedArguments>::value);
static_assert(sizeof(MlpFusedArguments) == kMlpFusedArgumentBytes);
static_assert(alignof(MlpFusedArguments) == 8);
static_assert(offsetof(MlpFusedArguments, abi_version) == 0);
static_assert(offsetof(MlpFusedArguments, byte_size) == 4);
static_assert(offsetof(MlpFusedArguments, input_dtype) == 8);
static_assert(offsetof(MlpFusedArguments, flags) == 12);
static_assert(offsetof(MlpFusedArguments, x_addr) == 16);
static_assert(offsetof(MlpFusedArguments, w1_addr) == 24);
static_assert(offsetof(MlpFusedArguments, w2_addr) == 32);
static_assert(offsetof(MlpFusedArguments, h_scratch_addr) == 40);
static_assert(offsetof(MlpFusedArguments, y_addr) == 48);
static_assert(offsetof(MlpFusedArguments, reserved) == 56);

namespace mlp_fused_detail {

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

} // namespace mlp_fused_detail

inline bool decode_mlp_fused_arguments(const uint8_t* bytes, size_t size,
                                       uint32_t expected_dtype,
                                       MlpFusedArguments* out) noexcept {
  if (bytes == nullptr || out == nullptr || size != kMlpFusedArgumentBytes
      || (expected_dtype != kMlpFusedDTypeFp16 && expected_dtype != kMlpFusedDTypeBf16)) {
    return false;
  }
  MlpFusedArguments decoded;
  decoded.abi_version = mlp_fused_detail::read32(bytes + 0);
  decoded.byte_size = mlp_fused_detail::read32(bytes + 4);
  decoded.input_dtype = mlp_fused_detail::read32(bytes + 8);
  decoded.flags = mlp_fused_detail::read32(bytes + 12);
  decoded.x_addr = mlp_fused_detail::read64(bytes + 16);
  decoded.w1_addr = mlp_fused_detail::read64(bytes + 24);
  decoded.w2_addr = mlp_fused_detail::read64(bytes + 32);
  decoded.h_scratch_addr = mlp_fused_detail::read64(bytes + 40);
  decoded.y_addr = mlp_fused_detail::read64(bytes + 48);
  decoded.reserved = mlp_fused_detail::read64(bytes + 56);

  if (decoded.abi_version != kMlpFusedAbiVersion
      || decoded.byte_size != kMlpFusedArgumentBytes
      || decoded.input_dtype != expected_dtype
      || (decoded.flags & ~kMlpFusedFlagWriteHiddenFp32) != 0
      || decoded.reserved != 0) {
    return false;
  }

  const uint64_t addrs[4] = {
      decoded.x_addr, decoded.w1_addr, decoded.w2_addr, decoded.y_addr};
  const uint64_t sizes[4] = {
      kMlpFusedXBytes, kMlpFusedW1Bytes, kMlpFusedW2Bytes, kMlpFusedYBytes};
  for (size_t i = 0; i < 4; ++i) {
    if (!mlp_fused_detail::range_valid(addrs[i], sizes[i])) {
      return false;
    }
    for (size_t j = i + 1; j < 4; ++j) {
      if (mlp_fused_detail::ranges_overlap(addrs[i], sizes[i], addrs[j], sizes[j])) {
        return false;
      }
    }
  }

  const bool need_scratch = (decoded.flags & kMlpFusedFlagWriteHiddenFp32) != 0;
  if (need_scratch || decoded.h_scratch_addr != 0) {
    if (!mlp_fused_detail::range_valid(decoded.h_scratch_addr, kMlpFusedHScratchBytes)) {
      return false;
    }
    for (size_t i = 0; i < 4; ++i) {
      if (mlp_fused_detail::ranges_overlap(addrs[i], sizes[i],
                                           decoded.h_scratch_addr,
                                           kMlpFusedHScratchBytes)) {
        return false;
      }
    }
  }

  *out = decoded;
  return true;
}

} // namespace vortex::ai

#endif // VORTEX_AI_MLP_FUSED_ARGS_H
