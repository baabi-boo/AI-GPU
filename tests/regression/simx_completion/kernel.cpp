// SPDX-License-Identifier: Apache-2.0
#include <vx_spawn2.h>
#include "common.h"

volatile uint32_t completion_global = kCompletionGlobal;

__kernel void kernel_main(CompletionArgs* __UNIFORM__ args) {
  auto* output = reinterpret_cast<CompletionOutput*>(args->output_address);
  uintptr_t gp;
  __asm__ volatile("mv %0, gp" : "=r"(gp));
  const uint32_t value = completion_global;
  output->global_pointer = gp;
  output->global_value = value;
  output->value = value ^ args->input;
  output->sequence = args->sequence;
  output->reserved = 0;
}
