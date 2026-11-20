// SPDX-License-Identifier: Apache-2.0

#include "mlp_host.h"

namespace vortex::ai {
namespace {

bool bounded_integer_magnitude(uint32_t bits, uint32_t* magnitude) noexcept {
  if ((bits & 0x7fffffffu) == 0) {
    *magnitude = 0;
    return true;
  }
  const uint32_t exponent = (bits >> 23) & 0xffu;
  if (exponent < 127 || exponent > 133) {
    return false;
  }
  const uint32_t significand = 0x800000u | (bits & 0x7fffffu);
  const uint32_t shift = 150 - exponent;
  if ((significand & ((1u << shift) - 1)) != 0) {
    return false;
  }
  const uint32_t value = significand >> shift;
  if (value > 64) {
    return false;
  }
  *magnitude = value;
  return true;
}

uint16_t encode_positive_integer(uint32_t value, DType dtype) noexcept {
  if (value == 0) {
    return 0;
  }
  uint32_t exponent = 0;
  for (uint32_t remaining = value; remaining > 1; remaining >>= 1) {
    ++exponent;
  }
  const uint32_t fraction_bits = dtype == DType::fp16 ? 10 : 7;
  const uint32_t bias = dtype == DType::fp16 ? 15 : 127;
  const uint32_t fraction = (value << (fraction_bits - exponent))
      - (1u << fraction_bits);
  return static_cast<uint16_t>(((exponent + bias) << fraction_bits) | fraction);
}

} // namespace

BridgeResult prepare_mlp_hidden(const uint32_t* input, size_t count,
                               DType dtype) noexcept {
  if (input == nullptr || count != kMlpHiddenElements) {
    return {};
  }
  if (dtype != DType::fp16 && dtype != DType::bf16) {
    return {BridgeStatus::unsupported_dtype, {}};
  }
  BridgeResult staged{};
  for (size_t index = 0; index < count; ++index) {
    const uint32_t bits = input[index];
    uint32_t magnitude = 0;
    // ReLU must not hide invalid negative results from the preceding operator.
    if (!bounded_integer_magnitude(bits, &magnitude)) {
      return {BridgeStatus::invalid_value, {}};
    }
    const uint32_t activated = (bits & 0x80000000u) != 0 ? 0 : magnitude;
    const uint16_t encoded = encode_positive_integer(activated, dtype);
    staged.bytes[index * 2] = static_cast<uint8_t>(encoded);
    staged.bytes[index * 2 + 1] = static_cast<uint8_t>(encoded >> 8);
  }
  staged.status = BridgeStatus::success;
  return staged;
}

} // namespace vortex::ai
