// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <stdexcept>

namespace vortex {

class RAM {
public:
  RAM(uint64_t, uint64_t) {}
  void enable_acl(bool) {}

  void read(uint8_t* destination, uint64_t address, uint64_t bytes) {
    bounds(address, bytes);
    std::memcpy(destination, bytes_.data() + address, bytes);
  }

  void write(const uint8_t* source, uint64_t address, uint64_t bytes) {
    bounds(address, bytes);
    std::memcpy(bytes_.data() + address, source, bytes);
  }

private:
  void bounds(uint64_t address, uint64_t bytes) const {
    if (address > bytes_.size() || bytes > bytes_.size() - address) {
      throw std::out_of_range("fixture device memory");
    }
  }

  std::array<uint8_t, 65536> bytes_{};
};

}  // namespace vortex
