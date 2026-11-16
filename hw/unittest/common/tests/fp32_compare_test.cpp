// SPDX-License-Identifier: Apache-2.0

#include "fp32_compare.h"

#include <iostream>
#include <limits>
#include <string>

namespace {

unsigned checks = 0;
unsigned failures = 0;

void expect(const char* name, uint32_t actual, uint32_t expected, uint32_t tolerance,
            bool equal, uint64_t distance) {
  for (unsigned order = 0; order < 2; ++order) {
    const auto result = order == 0
        ? test_fp32::compare_bits(actual, expected, tolerance)
        : test_fp32::compare_bits(expected, actual, tolerance);
    ++checks;
    if (result.equal != equal || result.ulps != distance) {
      std::cerr << name << " order=" << order << " equal=" << result.equal
                << " ulps=" << result.ulps << " expected_equal=" << equal
                << " expected_ulps=" << distance << '\n';
      ++failures;
    }
  }
}

void special_values() {
  constexpr uint64_t no_distance = std::numeric_limits<uint64_t>::max();
  constexpr uint32_t maximum = std::numeric_limits<uint32_t>::max();
  expect("positive infinity", 0x7f800000, 0x7f800000, 0, true, 0);
  expect("negative infinity", 0xff800000, 0xff800000, 0, true, 0);
  expect("opposite infinities", 0x7f800000, 0xff800000, 1, false, no_distance);
  expect("infinite tolerance cannot merge infinities", 0x7f800000, 0xff800000,
         maximum, false, no_distance);
  expect("maximum finite is not infinity", 0x7f7fffff, 0x7f800000,
         1, false, no_distance);
  expect("negative maximum finite is not infinity", 0xff7fffff, 0xff800000,
         1, false, no_distance);
  expect("finite tolerance cannot admit infinity", 0x7f7fffff, 0x7f800000,
         maximum, false, no_distance);
  expect("infinity is not adjacent NaN", 0x7f800000, 0x7f800001,
         1, false, no_distance);
  expect("negative infinity is not adjacent NaN", 0xff800000, 0xff800001,
         maximum, false, no_distance);
  expect("finite is not NaN", 0x3f800000, 0x7fc00000, maximum, false, no_distance);
  expect("zero is not NaN", 0, 0xff800001, maximum, false, no_distance);
  const uint32_t nans[] = {0x7f800001, 0x7fc00000, 0xff800001, 0xffc12345};
  for (const auto left : nans) {
    for (const auto right : nans) {
      expect("NaN classification", left, right, 0, true, 0);
    }
  }
}

void finite_values() {
  expect("positive adjacent", 0x3f800000, 0x3f800001, 1, true, 1);
  expect("positive adjacent exact rejection", 0x3f800000, 0x3f800001, 0, false, 1);
  expect("negative adjacent", 0xbf800000, 0xbf800001, 1, true, 1);
  expect("negative adjacent exact rejection", 0xbf800000, 0xbf800001, 0, false, 1);
  expect("two ULPs exceed one", 0x3f800000, 0x3f800002, 1, false, 2);
  expect("two ULPs accepted at two", 0x3f800000, 0x3f800002, 2, true, 2);
  expect("opposite ones", 0x3f800000, 0xbf800000, 1, false, 0x7f000000ull);
  expect("distance exceeds signed int", 0x40000000, 0xc0000000, 1,
         false, 0x80000000ull);
  expect("widest finite distance", 0x7f7fffff, 0xff7fffff, 1,
         false, 0xfefffffeull);
  expect("finite uint32 tolerance", 0x7f7fffff, 0xff7fffff,
         std::numeric_limits<uint32_t>::max(), true, 0xfefffffeull);
  const uint32_t adjacent[] = {
    0x00000000, 0x00000001, 0x007ffffe, 0x007fffff,
    0x00800000, 0x3f7fffff, 0x3f800000, 0x7f7ffffe,
  };
  for (const auto value : adjacent) {
    expect("positive finite boundary", value, value + 1, 1, true, 1);
    expect("negative finite boundary", value | 0x80000000u,
           (value + 1) | 0x80000000u, 1, true, 1);
  }
}

void zero_values() {
  expect("signed zeros", 0, 0x80000000, 0, true, 0);
  expect("zero and positive subnormal", 0, 1, 1, true, 1);
  expect("zero and negative subnormal", 0, 0x80000001, 1, true, 1);
  expect("negative zero and positive subnormal", 0x80000000, 1, 1, true, 1);
  expect("negative zero and negative subnormal", 0x80000000, 0x80000001, 1, true, 1);
  expect("opposite subnormals exceed one", 1, 0x80000001, 1, false, 2);
  expect("opposite subnormals accepted at two", 1, 0x80000001, 2, true, 2);
  expect("negative zero exact subnormal rejection", 0x80000000, 1, 0, false, 1);
}

void representations() {
  const struct {
    float value;
    uint32_t expected;
  } cases[] = {
    {1.0f, 0x3f800000}, {-1.0f, 0xbf800000},
    {0.0f, 0}, {-0.0f, 0x80000000},
    {std::numeric_limits<float>::infinity(), 0x7f800000},
    {-std::numeric_limits<float>::infinity(), 0xff800000},
  };
  for (const auto& item : cases) {
    ++checks;
    if (test_fp32::bits(item.value) != item.expected) {
      std::cerr << "float representation mismatch\n";
      ++failures;
    }
  }
}

}

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "Expected one group: special, finite, zero, representation\n";
    return 2;
  }
  const std::string group = argv[1];
  if (group == "special") {
    special_values();
  } else if (group == "finite") {
    finite_values();
  } else if (group == "zero") {
    zero_values();
  } else if (group == "representation") {
    representations();
  } else {
    std::cerr << "Unknown comparison test group\n";
    return 2;
  }
  std::cout << "FP32 comparator " << group << ": " << checks << " checks, "
            << failures << " failures\n";
  return failures == 0 ? 0 : 1;
}
