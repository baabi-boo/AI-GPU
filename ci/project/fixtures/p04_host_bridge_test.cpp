// SPDX-License-Identifier: Apache-2.0

#include "mlp_host.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using vortex::ai::BridgeResult;
using vortex::ai::BridgeStatus;
using vortex::ai::DType;
using vortex::ai::prepare_mlp_hidden;

namespace {

using Input = std::array<uint32_t, 128>;
constexpr std::array<DType, 2> kFormats = {DType::fp16, DType::bf16};
size_t checks = 0;

static_assert(sizeof(float) == sizeof(uint32_t));
static_assert(std::numeric_limits<float>::is_iec559);
static_assert(std::numeric_limits<float>::digits == 24);
static_assert(vortex::ai::kMlpHiddenElements == 128);
static_assert(vortex::ai::kMlpHiddenBytes == 256);

void require(bool condition, const char* message) {
  ++checks;
  if (!condition) {
    throw std::runtime_error(message);
  }
}

uint32_t float_bits(int value) {
  const float number = static_cast<float>(value);
  uint32_t bits = 0;
  std::memcpy(&bits, &number, sizeof(bits));
  return bits;
}

uint16_t expected_element(int value, DType dtype) {
  if (value <= 0) {
    return 0;
  }
  const uint32_t bits = float_bits(value);
  // All selected positive integers are normal and exact in either format.
  return static_cast<uint16_t>(dtype == DType::bf16
      ? bits >> 16 : (bits >> 13) - 0x1c000u);
}

void check_element(const BridgeResult& result, size_t index, uint16_t expected) {
  require(result.bytes[index * 2] == (expected & 0xffu), "low byte differs");
  require(result.bytes[index * 2 + 1] == (expected >> 8), "high byte differs");
}

void require_error(const BridgeResult& result, BridgeStatus status) {
  require(result.status == status, "wrong rejection status");
  require(std::all_of(result.bytes.begin(), result.bytes.end(),
                     [](uint8_t byte) { return byte == 0; }),
          "failure exposed a partial output");
}

void legal_domain() {
  for (DType dtype : kFormats) {
    for (int offset = 0; offset < 129; ++offset) {
      Input input{};
      for (size_t index = 0; index < input.size(); ++index) {
        input[index] = float_bits((offset + static_cast<int>(index)) % 129 - 64);
      }
      const Input original = input;
      const auto result = prepare_mlp_hidden(input.data(), input.size(), dtype);
      require(result.status == BridgeStatus::success, "legal integer rejected");
      require(input == original, "conversion modified input");
      for (size_t index = 0; index < input.size(); ++index) {
        const int value = (offset + static_cast<int>(index)) % 129 - 64;
        check_element(result, index, expected_element(value, dtype));
      }
    }
  }
}

void reject_at_boundaries(uint32_t bits) {
  for (DType dtype : kFormats) {
    for (size_t index : {size_t{0}, size_t{63}, size_t{64}, size_t{127}}) {
      Input input{};
      input.fill(float_bits(3));
      input[index] = bits;
      const Input original = input;
      require_error(prepare_mlp_hidden(input.data(), input.size(), dtype),
                    BridgeStatus::invalid_value);
      require(input == original, "rejection modified input");
    }
  }
}

void adjacent_fractional_words() {
  for (int value = 1; value <= 64; ++value) {
    const uint32_t bits = float_bits(value);
    for (uint32_t adjacent : {bits - 1, bits + 1}) {
      reject_at_boundaries(adjacent);
      reject_at_boundaries(adjacent | 0x80000000u);
    }
  }
}

void exceptional_words() {
  constexpr std::array<uint32_t, 18> invalid = {
    0x00000001u, 0x007fffffu, 0x00800000u, 0x3f000000u,
    0x80000001u, 0x807fffffu, 0x80800000u, 0xbf000000u,
    0x7f800000u, 0xff800000u, 0x7fc00000u, 0xffc00000u,
    0x7f800001u, 0xff800001u, 0x7f7fffffu, 0xff7fffffu,
    0x42820000u, 0xc2820000u,
  };
  for (uint32_t bits : invalid) {
    reject_at_boundaries(bits);
  }
}

void invalid_structure() {
  Input input{};
  input.fill(float_bits(3));
  const Input original = input;
  for (DType dtype : kFormats) {
    require_error(prepare_mlp_hidden(nullptr, 128, dtype), BridgeStatus::invalid_argument);
    for (size_t count : {size_t{0}, size_t{1}, size_t{127}, size_t{129},
                         std::numeric_limits<size_t>::max()}) {
      require_error(prepare_mlp_hidden(input.data(), count, dtype),
                    BridgeStatus::invalid_argument);
    }
  }
  for (DType dtype : {DType::fp32, static_cast<DType>(0),
                      static_cast<DType>(0xffffffffu)}) {
    require_error(prepare_mlp_hidden(input.data(), input.size(), dtype),
                  BridgeStatus::unsupported_dtype);
  }
  require(input == original, "structural rejection modified input");
}

void zero_and_row_order() {
  Input input{};
  input[0] = 0x80000000u;
  input[1] = 0;
  input[2] = float_bits(-64);
  input[63] = float_bits(1);
  input[64] = float_bits(64);
  input[127] = float_bits(2);
  const Input original = input;
  for (DType dtype : kFormats) {
    const auto result = prepare_mlp_hidden(input.data(), input.size(), dtype);
    require(result.status == BridgeStatus::success, "signed zero rejected");
    for (size_t index = 0; index < input.size(); ++index) {
      const uint16_t expected = index == 63 ? (dtype == DType::fp16 ? 0x3c00 : 0x3f80)
          : index == 64 ? (dtype == DType::fp16 ? 0x5400 : 0x4280)
          : index == 127 ? 0x4000 : 0;
      check_element(result, index, expected);
    }
    require(input == original, "row test modified input");
  }
}

uint32_t read_u32(const uint8_t* bytes) {
  return uint32_t{bytes[0]} | (uint32_t{bytes[1]} << 8)
      | (uint32_t{bytes[2]} << 16) | (uint32_t{bytes[3]} << 24);
}

void frozen_cases(const char* path) {
  std::ifstream file(path, std::ios::binary);
  std::array<uint8_t, 8 + 10 * (4 + 512 + 256)> packet{};
  require(static_cast<bool>(file.read(reinterpret_cast<char*>(packet.data()), packet.size())),
          "fixture packet missing or truncated");
  require(file.get() == std::char_traits<char>::eof(), "fixture packet has trailing bytes");
  require(std::memcmp(packet.data(), "MLP1", 4) == 0, "fixture packet magic differs");
  require(read_u32(packet.data() + 4) == 10, "fixture packet count differs");
  size_t offset = 8;
  for (size_t case_index = 0; case_index < 10; ++case_index) {
    const auto dtype = static_cast<DType>(read_u32(packet.data() + offset));
    require(dtype == (case_index < 5 ? DType::fp16 : DType::bf16), "fixture format differs");
    offset += 4;
    Input input{};
    for (uint32_t& value : input) {
      value = read_u32(packet.data() + offset);
      offset += 4;
    }
    const Input original = input;
    const auto result = prepare_mlp_hidden(input.data(), input.size(), dtype);
    require(result.status == BridgeStatus::success, "frozen case rejected");
    for (size_t index = 0; index < result.bytes.size(); ++index) {
      require(result.bytes[index] == packet[offset + index], "frozen bridge byte differs");
    }
    require(input == original, "fixture conversion modified input");
    offset += result.bytes.size();
    input[0] = float_bits(64);
    const auto changed = prepare_mlp_hidden(input.data(), input.size(), dtype);
    require(changed.status == BridgeStatus::success, "changed actual input rejected");
    check_element(changed, 0, dtype == DType::fp16 ? 0x5400 : 0x4280);
    require(changed.bytes != result.bytes, "conversion ignored the actual input");
    require(std::equal(changed.bytes.begin() + 2, changed.bytes.end(), result.bytes.begin() + 2),
            "one actual input changed unrelated elements");
  }
  require(offset == packet.size(), "fixture packet was not consumed exactly");
}

} // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    return 2;
  }
  const std::string group = argv[1];
  try {
    if (group == "legal_domain" && argc == 2) {
      legal_domain();
    } else if (group == "adjacent_fractional_words" && argc == 2) {
      adjacent_fractional_words();
    } else if (group == "exceptional_words" && argc == 2) {
      exceptional_words();
    } else if (group == "invalid_structure" && argc == 2) {
      invalid_structure();
    } else if (group == "zero_and_row_order" && argc == 2) {
      zero_and_row_order();
    } else if (group == "frozen_cases" && argc == 3) {
      frozen_cases(argv[2]);
    } else {
      return 2;
    }
    std::cout << "PASS " << group << " checks=" << checks << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << group << ": " << error.what() << '\n';
    return 1;
  }
}
