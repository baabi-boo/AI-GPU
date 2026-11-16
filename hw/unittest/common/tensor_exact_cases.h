// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace tensor_test {

struct ExactCase {
  std::string name;
  std::vector<uint32_t> rs1;
  std::vector<uint32_t> rs2;
  std::vector<uint32_t> rs3;
  std::vector<uint32_t> expected;
};

namespace detail {

inline uint32_t float_bits(float value) {
  static_assert(sizeof(float) == sizeof(uint32_t)
                && std::numeric_limits<float>::is_iec559
                && std::numeric_limits<float>::digits == 24,
                "tensor fixtures require IEEE binary32 float");
  uint32_t result;
  std::memcpy(&result, &value, sizeof(result));
  return result;
}

inline uint16_t small_integer(int value, uint32_t fmt) {
  if (value < -32 || value > 32) {
    throw std::invalid_argument("fixture integer is outside its exact range");
  }
  const uint32_t sign = value < 0 ? 0x8000u : 0u;
  const uint32_t magnitude = value < 0 ? -value : value;
  if (magnitude == 0) {
    return 0;
  }
  uint32_t exponent = 0;
  while ((uint32_t{1} << (exponent + 1)) <= magnitude) {
    ++exponent;
  }
  const uint32_t fraction_bits = fmt == 2 ? 10 : 7;
  const uint32_t bias = fmt == 2 ? 15 : 127;
  return static_cast<uint16_t>(sign | ((exponent + bias) << fraction_bits)
      | ((magnitude - (uint32_t{1} << exponent)) << (fraction_bits - exponent)));
}

inline void element(std::vector<uint32_t>& words, int row, int word_count,
                    int index, uint16_t value) {
  words[row * word_count + index / 2] |= uint32_t{value} << (16 * (index % 2));
}

}

inline std::vector<ExactCase> exact_cases(uint32_t fmt, int tc_m, int tc_n, int tc_k) {
  if (fmt != 2 && fmt != 3) {
    throw std::invalid_argument("exact packed fixtures require FP16 or BF16");
  }
  if (tc_m < 1 || tc_m > 16 || tc_n < 1 || tc_n > 8 || tc_k != tc_n
      || (tc_m != tc_n && tc_m != 2 * tc_n)
      || (tc_m & (tc_m - 1)) || (tc_n & (tc_n - 1))
      || tc_m * tc_n > 64) {
    throw std::invalid_argument("unsupported packed WMMA fixture shape");
  }
  const int lanes = tc_m * tc_n;
  const uint16_t one = detail::small_integer(1, fmt);
  const uint16_t minus_one = detail::small_integer(-1, fmt);
  const uint16_t infinity = fmt == 2 ? 0x7c00u : 0x7f80u;
  const uint16_t nan = fmt == 2 ? 0x7e00u : 0x7fc0u;
  std::vector<ExactCase> cases;
  auto blank = [&](std::string name) {
    return ExactCase{std::move(name), std::vector<uint32_t>(lanes),
        std::vector<uint32_t>(lanes), std::vector<uint32_t>(lanes),
        std::vector<uint32_t>(lanes)};
  };
  auto uniform = [&](std::string name, uint16_t a0, uint16_t b0,
                     uint32_t c, uint32_t expected,
                     uint16_t a1 = 0, uint16_t b1 = 0) {
    auto test = blank(std::move(name));
    for (int i = 0; i < tc_m; ++i) {
      detail::element(test.rs1, i, tc_k, 0, a0);
      detail::element(test.rs1, i, tc_k, 1, a1);
    }
    for (int j = 0; j < tc_n; ++j) {
      detail::element(test.rs2, j, tc_k, 0, b0);
      detail::element(test.rs2, j, tc_k, 1, b1);
    }
    for (int t = 0; t < lanes; ++t) {
      test.rs3[t] = c;
      test.expected[t] = expected;
    }
    cases.push_back(std::move(test));
  };

  // Small integer products and half-integer C values are exactly representable.
  for (int position = 0; position < 2 * tc_k; ++position) {
    auto test = blank("packed element " + std::to_string(position));
    for (int i = 0; i < tc_m; ++i) {
      detail::element(test.rs1, i, tc_k, position, detail::small_integer(i + 1, fmt));
    }
    for (int j = 0; j < tc_n; ++j) {
      detail::element(test.rs2, j, tc_k, position, detail::small_integer(2 * j + 1, fmt));
    }
    for (int i = 0; i < tc_m; ++i) {
      for (int j = 0; j < tc_n; ++j) {
        const int t = i * tc_n + j;
        test.rs3[t] = detail::float_bits(float(i - j) * 0.5f);
        test.expected[t] = detail::float_bits(float(2 * (i + 1) * (2 * j + 1) + i - j) * 0.5f);
      }
    }
    cases.push_back(std::move(test));
  }

  auto dense = blank("packed two-term layout");
  for (int i = 0; i < tc_m; ++i) {
    detail::element(dense.rs1, i, tc_k, 0, detail::small_integer(2 * i + 1, fmt));
    detail::element(dense.rs1, i, tc_k, 1, detail::small_integer(2 * i + 2, fmt));
  }
  for (int j = 0; j < tc_n; ++j) {
    detail::element(dense.rs2, j, tc_k, 0, detail::small_integer(j + 5, fmt));
    detail::element(dense.rs2, j, tc_k, 1, detail::small_integer(j + 7, fmt));
  }
  for (int i = 0; i < tc_m; ++i) {
    for (int j = 0; j < tc_n; ++j) {
      const int t = i * tc_n + j;
      dense.rs3[t] = detail::float_bits(float(i - j) * 0.5f);
      const int product = (2 * i + 1) * (j + 5) + (2 * i + 2) * (j + 7);
      dense.expected[t] = detail::float_bits(float(2 * product + i - j) * 0.5f);
    }
  }
  cases.push_back(std::move(dense));

  uniform("disjoint halfwords", one, 0, 0x3fc00000u, 0x3fc00000u, 0, one);
  uniform("exact cancellation", one, one, 0x40000000u, 0x40000000u, minus_one, one);
  uniform("negative finite result", detail::small_integer(-2, fmt),
          detail::small_integer(4, fmt), 0x3f800000u, 0xc0e00000u);
  uniform("signed zero inputs", 0x8000u, one, 0x80000000u, 0u, 0u, minus_one);
  if (fmt == 2) {
    uniform("smallest FP16 subnormal to normal FP32", 0x0001u, one, 0u, 0x33800000u);
    uniform("largest finite FP16 input", 0x7bffu, one, 0u, 0x477fe000u);
  } else {
    uniform("smallest normal BF16 input", 0x0080u, one, 0u, 0x00800000u);
    uniform("largest finite BF16 input", 0x7f7fu, one, 0u, 0x7f7f0000u);
  }
  uniform("positive infinity product", infinity, one, 0u, 0x7f800000u);
  uniform("negative infinity product", infinity, minus_one, 0u, 0xff800000u);
  uniform("infinity times zero", infinity, 0u, 0u, 0x7fc00000u);
  uniform("opposing infinities", infinity, one, 0u, 0x7fc00000u,
          infinity | 0x8000u, one);
  uniform("NaN input", nan, one, 0u, 0x7fc00000u);
  uniform("positive infinity accumulator", 0u, 0u, 0x7f800000u, 0x7f800000u);
  uniform("negative infinity accumulator", 0u, 0u, 0xff800000u, 0xff800000u);
  uniform("NaN accumulator", 0u, 0u, 0xffc12345u, 0x7fc00000u);
  uniform("negative finite accumulator", 0u, 0u, 0xbfc00000u, 0xbfc00000u);
  return cases;
}

}
