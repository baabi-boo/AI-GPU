// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_MLP_HOST_H
#define VORTEX_AI_MLP_HOST_H

#include <array>
#include <cstddef>
#include <cstdint>
#include "contract.h"

namespace vortex::ai {

constexpr size_t kMlpHiddenElements = 128;
constexpr size_t kMlpHiddenBytes = kMlpHiddenElements * 2;

enum class BridgeStatus : uint32_t {
  success, invalid_argument, unsupported_dtype, invalid_value
};

struct BridgeResult {
  BridgeStatus status = BridgeStatus::invalid_argument;
  std::array<uint8_t, kMlpHiddenBytes> bytes{};
};

// Failed conversion returns no usable prefix; all returned bytes remain zero.
BridgeResult prepare_mlp_hidden(const uint32_t* input, size_t count,
                               DType dtype) noexcept;

} // namespace vortex::ai

#endif
