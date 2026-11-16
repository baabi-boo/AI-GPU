// SPDX-License-Identifier: Apache-2.0

#include "int_dot_reference.h"

#include <initializer_list>
#include <iostream>
#include <string>
#include <vector>

namespace {

unsigned checks = 0;
unsigned failures = 0;

void expect(const char* name, const std::vector<uint32_t>& a,
            const std::vector<uint32_t>& b, uint32_t c, uint32_t expected) {
  ++checks;
  if (a.size() != b.size()) {
    std::cerr << name << ": invalid fixture dimensions\n";
    ++failures;
    return;
  }
  const auto actual = test_integer::dot_product_bits(a.data(), b.data(), c, a.size());
  if (actual != expected) {
    std::cerr << name << ": actual=0x" << std::hex << actual
              << " expected=0x" << expected << std::dec << '\n';
    ++failures;
  }
}

void boundaries() {
  expect("maximum signed accumulator plus one", {1}, {1}, 0x7fffffffu, 0x80000000u);
  expect("minimum signed accumulator minus one", {0xffffffffu}, {1},
         0x80000000u, 0x7fffffffu);
  expect("unsigned accumulator wraps", {1}, {1}, 0xffffffffu, 0u);
  expect("minimum signed product negation", {0x80000000u}, {0xffffffffu},
         0u, 0x80000000u);
  expect("maximum signed product doubles", {0x7fffffffu}, {2}, 0u, 0xfffffffeu);
  expect("maximum unsigned product", {0xffffffffu}, {0xffffffffu}, 0u, 1u);
  expect("minimum signed squared", {0x80000000u}, {0x80000000u}, 0u, 0u);
  expect("two full products and accumulator", {0xffffffffu, 0xffffffffu},
         {0xffffffffu, 0xffffffffu}, 0xffffffffu, 1u);
  expect("opposite signed products cancel", {0x80000000u, 0x80000000u},
         {1u, 0xffffffffu}, 17u, 17u);
  expect("zero products preserve negative accumulator", {0u, 0u}, {9u, 0xffffffffu},
         0x80000001u, 0x80000001u);
  expect("empty mathematical dot preserves accumulator", {}, {}, 0xdeadbeefu, 0xdeadbeefu);
  expect("multiple byte products cross signed boundary", std::vector<uint32_t>(8, 255u),
         std::vector<uint32_t>(8, 255u), 0x7fffffffu, 0x8007f007u);
}

void packed_operands() {
  expect("signed byte operands", {0xffffff80u, 0xffffffffu, 127u},
         {0xffffff80u, 255u, 0xffffff80u}, 0u, 0xffffff81u);
  expect("unsigned byte operands", {255u, 255u, 0u, 1u},
         {255u, 1u, 255u, 255u}, 0u, 65535u);
  expect("signed nibble operands", {0xfffffff8u, 0xffffffffu, 7u, 0u},
         {7u, 0xfffffff8u, 7u, 1u}, 0u, 1u);
  expect("unsigned nibble operands", {15u, 15u, 15u, 15u},
         {15u, 15u, 15u, 15u}, 0u, 900u);
  expect("signed byte accumulation below minimum", {0xffffff80u}, {127u},
         0x80000000u, 0x7fffc080u);
}

int64_t signed_value(uint32_t bits) {
  constexpr int64_t modulus = int64_t{1} << 32;
  return bits < 0x80000000u ? int64_t{bits} : int64_t{bits} - modulus;
}

uint32_t signed_reference(const std::vector<uint32_t>& a,
                          const std::vector<uint32_t>& b, uint32_t c) {
  constexpr int64_t modulus = int64_t{1} << 32;
  int64_t residue = signed_value(c);
  for (std::size_t i = 0; i < a.size(); ++i) {
    residue = (residue + signed_value(a[i]) * signed_value(b[i])) % modulus;
  }
  if (residue < 0) {
    residue += modulus;
  }
  return static_cast<uint32_t>(residue);
}

void independent_reference() {
  constexpr uint32_t values[] = {
    0u, 1u, 2u, 7u, 15u, 127u, 128u, 255u, 65535u,
    0x7ffffffeu, 0x7fffffffu, 0x80000000u, 0x80000001u,
    0xffffff80u, 0xfffffff8u, 0xfffffffeu, 0xffffffffu,
  };
  for (uint32_t a : values) {
    for (uint32_t b : values) {
      for (uint32_t c : values) {
        const std::vector<uint32_t> left{a, b, 0x80000000u, 255u, 0xfffffff8u};
        const std::vector<uint32_t> right{b, a, c, 0xffffff80u, 15u};
        expect("signed wide modular reference", left, right, c,
               signed_reference(left, right, c));
      }
    }
  }
}

}

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "Expected one group: boundary, packed, reference\n";
    return 2;
  }
  const std::string group = argv[1];
  if (group == "boundary") {
    boundaries();
  } else if (group == "packed") {
    packed_operands();
  } else if (group == "reference") {
    independent_reference();
  } else {
    std::cerr << "Unknown integer reference test group\n";
    return 2;
  }
  std::cout << "Integer reference " << group << ": " << checks << " checks, "
            << failures << " failures\n";
  return failures == 0 ? 0 : 1;
}
