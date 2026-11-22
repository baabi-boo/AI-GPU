// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <stdint.h>

struct CompletionArgs {
  uint64_t output_address;
  uint32_t input;
  uint32_t sequence;
};

struct CompletionOutput {
  uint64_t global_pointer;
  uint32_t global_value;
  uint32_t value;
  uint32_t sequence;
  uint32_t reserved;
};

constexpr uint32_t kCompletionGlobal = 0x13579bdfu;

static_assert(sizeof(CompletionArgs) == 16);
static_assert(sizeof(CompletionOutput) == 24);
