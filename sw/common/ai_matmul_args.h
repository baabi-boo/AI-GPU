// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_MATMUL_ARGS_H
#define VORTEX_AI_MATMUL_ARGS_H

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace vortex::ai {

constexpr uint32_t kContractVersion = 1;
constexpr uint32_t kArgumentBytes = 56;

struct alignas(8) MatmulArguments {
  uint32_t abi_version = kContractVersion;
  uint32_t byte_size = kArgumentBytes;
  uint32_t input_dtype = 0;
  uint32_t flags = 0;
  uint32_t m = 0;
  uint32_t n = 0;
  uint32_t k = 0;
  uint32_t reserved = 0;
  uint64_t a_address = 0;
  uint64_t b_address = 0;
  uint64_t d_address = 0;
};

static_assert(std::is_standard_layout<MatmulArguments>::value);
static_assert(std::is_trivially_copyable<MatmulArguments>::value);
static_assert(sizeof(MatmulArguments) == kArgumentBytes);
static_assert(alignof(MatmulArguments) == 8);
static_assert(offsetof(MatmulArguments, abi_version) == 0);
static_assert(offsetof(MatmulArguments, byte_size) == 4);
static_assert(offsetof(MatmulArguments, input_dtype) == 8);
static_assert(offsetof(MatmulArguments, flags) == 12);
static_assert(offsetof(MatmulArguments, m) == 16);
static_assert(offsetof(MatmulArguments, n) == 20);
static_assert(offsetof(MatmulArguments, k) == 24);
static_assert(offsetof(MatmulArguments, reserved) == 28);
static_assert(offsetof(MatmulArguments, a_address) == 32);
static_assert(offsetof(MatmulArguments, b_address) == 40);
static_assert(offsetof(MatmulArguments, d_address) == 48);

namespace argument_detail {

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
  return address % 4 == 0 && size - 1 <= UINT64_MAX - address;
}

inline bool ranges_overlap(uint64_t a, uint64_t a_size,
                           uint64_t b, uint64_t b_size) noexcept {
  return a <= b + (b_size - 1) && b <= a + (a_size - 1);
}

} // namespace argument_detail

inline bool decode_matmul_arguments(const uint8_t* bytes, size_t size,
                                    uint32_t expected_dtype,
                                    MatmulArguments* out) noexcept {
  if (bytes == nullptr || out == nullptr || size != kArgumentBytes
      || (expected_dtype != 1 && expected_dtype != 2)) {
    return false;
  }
  MatmulArguments decoded;
  decoded.abi_version = argument_detail::read32(bytes);
  decoded.byte_size = argument_detail::read32(bytes + 4);
  decoded.input_dtype = argument_detail::read32(bytes + 8);
  decoded.flags = argument_detail::read32(bytes + 12);
  decoded.m = argument_detail::read32(bytes + 16);
  decoded.n = argument_detail::read32(bytes + 20);
  decoded.k = argument_detail::read32(bytes + 24);
  decoded.reserved = argument_detail::read32(bytes + 28);
  decoded.a_address = argument_detail::read64(bytes + 32);
  decoded.b_address = argument_detail::read64(bytes + 40);
  decoded.d_address = argument_detail::read64(bytes + 48);

  if (decoded.abi_version != kContractVersion || decoded.byte_size != kArgumentBytes
      || decoded.flags != 0 || decoded.reserved != 0
      || decoded.input_dtype != expected_dtype) {
    return false;
  }
  if (!((decoded.m == 8 && decoded.n == 4 && (decoded.k == 8 || decoded.k == 16))
        || (decoded.m == 16 && decoded.n == 8 && decoded.k == 16))) {
    return false;
  }

  const uint64_t a_size = uint64_t{decoded.m} * decoded.k * 2;
  const uint64_t b_size = uint64_t{decoded.k} * decoded.n * 2;
  const uint64_t d_size = uint64_t{decoded.m} * decoded.n * 4;
  if (!argument_detail::range_valid(decoded.a_address, a_size)
      || !argument_detail::range_valid(decoded.b_address, b_size)
      || !argument_detail::range_valid(decoded.d_address, d_size)
      || argument_detail::ranges_overlap(decoded.a_address, a_size, decoded.b_address, b_size)
      || argument_detail::ranges_overlap(decoded.a_address, a_size, decoded.d_address, d_size)
      || argument_detail::ranges_overlap(decoded.b_address, b_size, decoded.d_address, d_size)) {
    return false;
  }
  *out = decoded;
  return true;
}

} // namespace vortex::ai

#endif
