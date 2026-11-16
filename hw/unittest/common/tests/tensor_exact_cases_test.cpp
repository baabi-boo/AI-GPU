// SPDX-License-Identifier: Apache-2.0

#include "tensor_exact_cases.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <set>

static long double unpack16(uint16_t bits, uint32_t fmt) {
  const int fraction_bits = fmt == 2 ? 10 : 7;
  const int exponent_bits = fmt == 2 ? 5 : 8;
  const int bias = (1 << (exponent_bits - 1)) - 1;
  const int all_exponents = (1 << exponent_bits) - 1;
  const int exponent = (bits >> fraction_bits) & all_exponents;
  const int fraction = bits & ((1 << fraction_bits) - 1);
  long double value;
  if (exponent == all_exponents) {
    value = fraction ? std::numeric_limits<long double>::quiet_NaN()
                     : std::numeric_limits<long double>::infinity();
  } else if (exponent == 0) {
    value = std::ldexp(static_cast<long double>(fraction), 1 - bias - fraction_bits);
  } else {
    value = std::ldexp(static_cast<long double>((1 << fraction_bits) + fraction),
                       exponent - bias - fraction_bits);
  }
  return bits & 0x8000u ? -value : value;
}

static float unpack32(uint32_t bits) {
  float value;
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

static void require(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << message << '\n';
    std::exit(1);
  }
}

int main() {
  size_t checked = 0;
  for (uint32_t fmt : {2u, 3u}) {
    for (const auto& shape : {std::pair<int, int>{1, 1}, {2, 1}, {2, 2}, {4, 2}, {4, 4}, {8, 4}, {8, 8}}) {
      const int m = shape.first;
      const int n = shape.second;
      const int k = n;
      const auto cases = tensor_test::exact_cases(fmt, m, n, k);
      require(cases.size() == size_t(2 * k + 16), "wrong exact case count");
      std::set<std::string> names;
      for (const auto& test : cases) {
        require(names.insert(test.name).second, "duplicate exact case name");
        require(test.rs1.size() == size_t(m * n) && test.rs2.size() == size_t(m * n)
                && test.rs3.size() == size_t(m * n) && test.expected.size() == size_t(m * n),
                "wrong fixture lane count");
        for (int i = 0; i < m; ++i) {
          for (int j = 0; j < n; ++j) {
            long double value = unpack32(test.rs3[i * n + j]);
            for (int p = 0; p < 2 * k; ++p) {
              const auto a = uint16_t(test.rs1[i * k + p / 2] >> (16 * (p % 2)));
              const auto b = uint16_t(test.rs2[j * k + p / 2] >> (16 * (p % 2)));
              value += unpack16(a, fmt) * unpack16(b, fmt);
            }
            const float expected = unpack32(test.expected[i * n + j]);
            const float actual = static_cast<float>(value);
            require((std::isnan(expected) && std::isnan(actual)) || expected == actual,
                    test.name + ": independently decoded reference mismatch");
            ++checked;
          }
        }
      }
    }
  }
  for (const auto& shape : {std::pair<int, int>{0, 2}, {-1, 2}, {3, 2}, {2, 4}, {16, 8}}) {
    bool rejected = false;
    try {
      tensor_test::exact_cases(2, shape.first, shape.second, shape.second);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    require(rejected, "invalid shape accepted");
  }
  bool rejected = false;
  try {
    tensor_test::exact_cases(1, 2, 2, 2);
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  require(rejected, "invalid format accepted");
  rejected = false;
  try {
    tensor_test::exact_cases(2, 2, 2, 1);
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  require(rejected, "invalid K shape accepted");
  std::cout << checked << " independently decoded fixture outputs verified\n";
  return 0;
}
