// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace counter_test::public_hooks {

constexpr size_t kSelectorCount = 33;
constexpr size_t kComponentCount = 40;

struct SelectorInfo {
  const char* name;
  uint32_t perf_class;
  uint32_t csr;
  size_t component_count;
};

struct Observation {
  uint64_t constructed = 0;
  uint64_t destroyed = 0;
  uint64_t constructor_entries = 0;
  uint64_t destructor_entries = 0;
  uint64_t run_entries = 0;
  uint64_t run_completed = 0;
  uint64_t run_errors = 0;
  uint64_t dcr_read_entries = 0;
  uint64_t dcr_read_completed = 0;
  uint64_t dcr_read_errors = 0;
  uint64_t dcr_write_entries = 0;
  uint64_t dcr_write_completed = 0;
  uint64_t dcr_write_errors = 0;
  uint64_t overflow_errors = 0;
  uint64_t underflow_errors = 0;
  uint64_t negative_operand_errors = 0;
  uint64_t unexpected_errors = 0;
  uint64_t violations = 0;
  uint64_t generation = 0;
  bool live = false;
};

struct ModelState {
  bool live = false;
  bool inventory_ready = false;
  bool idle = false;
  bool any_running = false;
  uint64_t generation = 0;
  uint64_t ticks = 0;
  uint64_t reset_generation = 0;
  uint64_t pending_reads = 0;
  uint64_t core_cycles = 0;
  uint64_t core_instructions = 0;
  int exitcode = 0;
  std::array<uint64_t, kComponentCount> components{};
};

struct DcrRead {
  uint64_t sequence = 0;
  uint64_t generation = 0;
  uint32_t addr = 0;
  uint32_t tag = 0;
  uint32_t value = 0;
  int status = -1;
  bool completed = false;
  bool overflow = false;
  uint64_t ticks_before = 0;
  uint64_t ticks_after = 0;
  uint64_t reset_before = 0;
  uint64_t reset_after = 0;
  uint32_t class_before = 0;
  uint32_t class_after = 0;
};

struct Destruction {
  ModelState before;
  bool completed = false;
  uint64_t ticks_after = 0;
  uint64_t reset_after = 0;
  bool idle_after = false;
};

Observation observation();
ModelState model_state();
std::array<uint32_t, 3> read_program_words(uint64_t address);
std::array<SelectorInfo, kSelectorCount> selector_info();
void seed_component(size_t selector, size_t component, uint64_t value);
void clear_components();
std::vector<DcrRead> read_trace();
void clear_read_trace();
std::vector<Destruction> destruction_trace();

} // namespace counter_test::public_hooks
