// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <cstring>
#include <limits>

namespace test_fp32 {

static_assert(sizeof(float) == sizeof(uint32_t)
              && std::numeric_limits<float>::is_iec559
              && std::numeric_limits<float>::digits == 24
              && std::numeric_limits<float>::max_exponent == 128,
              "FP32 comparisons require IEEE binary32 float");

struct Comparison {
  bool equal;
  uint64_t ulps;
};

inline uint32_t bits(float value) {
  uint32_t result;
  std::memcpy(&result, &value, sizeof(result));
  return result;
}

inline Comparison compare_bits(uint32_t actual, uint32_t expected, uint32_t max_ulps) {
  const uint32_t actual_magnitude = actual & 0x7fffffffu;
  const uint32_t expected_magnitude = expected & 0x7fffffffu;
  const bool actual_nan = actual_magnitude > 0x7f800000u;
  const bool expected_nan = expected_magnitude > 0x7f800000u;
  const uint64_t incomparable = std::numeric_limits<uint64_t>::max();

  // NaN payloads and signs are outside this numerical comparison policy.
  if (actual_nan || expected_nan) {
    const bool equal = actual_nan && expected_nan;
    return {equal, equal ? 0 : incomparable};
  }
  if (actual_magnitude == 0x7f800000u || expected_magnitude == 0x7f800000u) {
    const bool equal = actual == expected;
    return {equal, equal ? 0 : incomparable};
  }

  // Collapse signed zero and preserve finite ordering across the sign boundary.
  const uint64_t origin = uint64_t{1} << 31;
  const uint64_t actual_key = (actual & 0x80000000u)
      ? origin - actual_magnitude : origin + actual_magnitude;
  const uint64_t expected_key = (expected & 0x80000000u)
      ? origin - expected_magnitude : origin + expected_magnitude;
  const uint64_t distance = actual_key > expected_key
      ? actual_key - expected_key : expected_key - actual_key;
  return {distance <= max_ulps, distance};
}

}
