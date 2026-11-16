// Copyright © 2026
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once

#include "common.h"
#include "p02_fixtures.h"
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <tensor_cfg.h>
#include <vector>

namespace p02 {

inline const Fixture* find_fixture(const char* id) {
  const Fixture* found = nullptr;
  for (const auto& fixture : kFixtures) {
    if (std::strcmp(fixture.id, id) == 0) {
      if (found != nullptr) {
        return nullptr;
      }
      found = &fixture;
    }
  }
  return found;
}

inline const char* configuration_error() {
#if !defined(VX_CFG_XLEN_64) || defined(VX_CFG_XLEN_32) || VX_CFG_XLEN != 64
  return "fixture mode requires RV64";
#elif !defined(VX_CFG_EXT_TCU_ENABLE) || defined(VX_CFG_EXT_TCU_DISABLE) \
    || !defined(VX_CFG_TCU_TYPE_TFR) || !defined(VX_CFG_FPU_TYPE_STD) \
    || defined(VX_CFG_TCU_TYPE_DPI) || defined(VX_CFG_TCU_TYPE_DSP) \
    || defined(VX_CFG_TCU_TYPE_BHF) || defined(VX_CFG_TCU_TYPE_FPNEW) \
    || defined(VX_CFG_FPU_TYPE_DPI) || defined(VX_CFG_FPU_TYPE_DSP) \
    || defined(VX_CFG_FPU_TYPE_FPNEW)
  return "fixture mode requires native TFR tensor and STD scalar arithmetic";
#elif VX_CFG_NUM_CLUSTERS != 1 || VX_CFG_NUM_CORES != 1 \
    || VX_CFG_NUM_WARPS != 4 || VX_CFG_NUM_THREADS != 4 || VX_CFG_ISSUE_WIDTH != 1
  return "fixture mode requires one cluster, one core, four warps, four threads and issue width one";
#elif VX_CFG_NUM_ALU_BLOCKS != 1 || VX_CFG_NUM_LSU_BLOCKS != 1 \
    || VX_CFG_NUM_FPU_BLOCKS != 1 || VX_CFG_NUM_TCU_BLOCKS != 1 \
    || VX_CFG_NUM_TCU_LANES != 4 || VX_CFG_TCU_PE_RATIO != 1 \
    || VX_CFG_TCU_LATENCY != 4 || !defined(VX_CFG_TCU_USE_DSP) \
    || VX_CFG_TCU_USE_DSP != 0
  return "fixture mode requires the p02-tfr unit geometry, latency and DSP settings";
#elif !defined(VX_CFG_TCU_FP16_ENABLE) || defined(VX_CFG_TCU_FP16_DISABLE) \
    || !defined(VX_CFG_LMEM_ENABLE) || defined(VX_CFG_LMEM_DISABLE)
  return "fixture mode requires the FP16/BF16 bank and local memory";
#elif defined(VX_CFG_TCU_TF32_ENABLE) || defined(VX_CFG_TCU_FP8_ENABLE) \
    || defined(VX_CFG_TCU_FP4_ENABLE) || defined(VX_CFG_TCU_INT8_ENABLE) \
    || defined(VX_CFG_TCU_INT4_ENABLE) || defined(VX_CFG_TCU_MX_ENABLE) \
    || defined(VX_CFG_TCU_MXFP4_ENABLE) || defined(VX_CFG_TCU_NVFP4_ENABLE) \
    || defined(VX_CFG_TCU_SPARSE_ENABLE) || defined(VX_CFG_TCU_DSM_ENABLE) \
    || defined(VX_CFG_TCU_WGMMA_ENABLE) || defined(VX_CFG_TCU_FEDP2K) \
    || defined(VX_CFG_EXT_LDST_MATRIX_ENABLE) || defined(WGMMA_RS) || defined(WGMMA_SS)
  return "fixture mode requires ordinary dense, unscaled FP16/BF16 WMMA with scalar fragment loads/stores";
#elif KUNROLL != 1
  return "fixture mode requires KUNROLL=1";
#elif defined(__FAST_MATH__)
  return "fixture mode requires a build without fast-math";
#else
  using Input = vortex::tensor::ITYPE;
  using Output = vortex::tensor::OTYPE;
  using Config = vortex::tensor::wmma_config_t<VX_CFG_NUM_THREADS, Input, Output>;
  if ((!std::is_same<Input, vortex::tensor::fp16>::value
       && !std::is_same<Input, vortex::tensor::bf16>::value)
      || !std::is_same<Output, vortex::tensor::fp32>::value) {
    return "fixture mode requires FP16 or BF16 inputs and FP32 outputs";
  }
  if (Config::tcM != 2 || Config::tcN != 2 || Config::tcK != 2
      || Config::tileM != 8 || Config::tileN != 4 || Config::tileK != 8) {
    return "fixture mode requires the 8x4x8 WMMA tile and 2x2x2 packed micro-tile";
  }
  return nullptr;
#endif
}

inline const char* fixture_error(const Fixture& fixture) {
  if (const char* error = configuration_error()) {
    return error;
  }
  if (std::strcmp(fixture.format, vortex::tensor::ITYPE::name) != 0) {
    return "fixture format does not match the compiled ITYPE";
  }
  if (fixture.m == 0 || fixture.n == 0 || fixture.k == 0
      || fixture.m % 8 != 0 || fixture.n % 4 != 0 || fixture.k % 8 != 0) {
    return "fixture dimensions must contain positive complete 8x4x8 tiles";
  }
  const uint64_t a_elements = uint64_t(fixture.m) * fixture.k;
  const uint64_t b_elements = uint64_t(fixture.k) * fixture.n;
  const uint64_t outputs = uint64_t(fixture.m) * fixture.n;
  if (fixture.a_count != a_elements / 2 || fixture.b_count != b_elements / 2
      || fixture.output_count != outputs || fixture.a_words == nullptr
      || fixture.b_words == nullptr || fixture.expected == nullptr) {
    return "fixture input or output word count does not match its dimensions";
  }
  const size_t max_words = std::numeric_limits<size_t>::max() / sizeof(uint32_t);
  if (fixture.a_count > max_words || fixture.b_count > max_words
      || fixture.output_count > max_words) {
    return "fixture byte count exceeds the host address space";
  }
  return nullptr;
}

inline std::vector<uint8_t> packed_bytes(const uint32_t* words, size_t count) {
  std::vector<uint8_t> bytes(count * sizeof(uint32_t));
  for (size_t i = 0; i < count; ++i) {
    // Device memory stores the low 16-bit lane before the high lane.
    for (size_t byte = 0; byte < sizeof(uint32_t); ++byte) {
      bytes[i * sizeof(uint32_t) + byte] = uint8_t(words[i] >> (8 * byte));
    }
  }
  return bytes;
}

inline size_t report_result(const Fixture& fixture,
                           const std::vector<uint32_t>& actual,
                           uint32_t iteration, size_t max_errors) {
  size_t mismatches = 0;
  for (size_t i = 0; i < fixture.output_count; ++i) {
    if (actual[i] != fixture.expected[i]) {
      if (mismatches < max_errors) {
        std::printf("*** error: [%zu] expected=0x%08x, actual=0x%08x\n",
                    i, fixture.expected[i], actual[i]);
      }
      ++mismatches;
    }
  }
  std::printf("P02_RESULT {\"case_id\":\"%s\",\"format\":\"%s\","
              "\"m\":%u,\"n\":%u,\"k\":%u,\"iteration\":%u,"
              "\"checked\":%zu,\"mismatches\":%zu,\"actual_bits\":[",
              fixture.id, fixture.format, fixture.m, fixture.n, fixture.k,
              iteration, fixture.output_count, mismatches);
  for (size_t i = 0; i < fixture.output_count; ++i) {
    std::printf("%s\"%08x\"", i == 0 ? "" : ",", actual[i]);
  }
  std::printf("]}\n");
  return mismatches;
}

} // namespace p02
