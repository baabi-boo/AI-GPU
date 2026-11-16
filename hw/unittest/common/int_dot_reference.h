// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>

namespace test_integer {

inline uint32_t dot_product_bits(const uint32_t* a, const uint32_t* b,
                                 uint32_t c, std::size_t count) {
  uint32_t accumulator = c;
  for (std::size_t i = 0; i < count; ++i) {
    // Low product bits are identical for signed and unsigned representations.
    accumulator = static_cast<uint32_t>(uint64_t{a[i]} * b[i] + accumulator);
  }
  return accumulator;
}

}
