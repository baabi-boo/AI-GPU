// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstddef>
#include <cstdint>

namespace p06_preflight {

constexpr size_t kMaxReads = 512;

struct ModelState {
  bool live = false;
  bool idle = false;
  bool any_running = false;
  uint64_t generation = 0;
  uint64_t ticks = 0;
  uint64_t reset_generation = 0;
  uint64_t core_cycles = 0;
  uint64_t core_instructions = 0;
  int exitcode = 0;
};

struct DcrRead {
  // Global DCR ordinal across MPM and cache-flush traces.
  uint64_t sequence = 0;
  uint64_t generation = 0;
  uint64_t completed_runs = 0;
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
  bool idle_before = false;
  bool idle_after = false;
  bool any_running_before = false;
  bool any_running_after = false;
};

struct Destruction {
  ModelState before;
  bool completed = false;
  uint64_t ticks_after = 0;
  uint64_t reset_after = 0;
  bool idle_after = false;
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
  // MPM replies and cache-flush replies have separate bounded traces.
  uint64_t read_count = 0;
  uint64_t cache_flush_count = 0;
  bool live = false;
  ModelState constructed_state;
  Destruction destruction;
};

} // namespace p06_preflight

extern "C" int p06_preflight_get_observation(p06_preflight::Observation*) noexcept;
extern "C" int p06_preflight_get_model_state(p06_preflight::ModelState*) noexcept;
extern "C" int p06_preflight_get_read(size_t, p06_preflight::DcrRead*) noexcept;
extern "C" int p06_preflight_get_cache_flush_read(size_t, p06_preflight::DcrRead*) noexcept;
