// SPDX-License-Identifier: Apache-2.0
#ifndef VORTEX_AI_WARM_WORKSPACE_OBSERVER_H
#define VORTEX_AI_WARM_WORKSPACE_OBSERVER_H

#include "../ai_bench_common/counters.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <iterator>

namespace p06_warm {

enum class Phase { context_create, idle, submit, operation_close, owner_close };

struct Counts {
  uint64_t device_open_calls = 0;
  uint64_t device_release_calls = 0;
  uint64_t buffer_create_calls = 0;
  uint64_t buffer_release_calls = 0;
  uint64_t live_buffers = 0;
  uint64_t live_requested_bytes = 0;
  uint64_t peak_requested_payload_bytes = 0;
  uint64_t premature_releases = 0;
  uint64_t errors = 0;
};

struct Memory {
  bool queried = false;
  vx_result_t status = VX_ERR_INVALID_HANDLE;
  uint64_t free_bytes = 0;
  uint64_t used_bytes = 0;
};

struct Reading {
  bool returned = false;
  vx_result_t status = VX_ERR_INTERNAL;
  uint64_t value = 0;
};

struct Snapshot {
  uint64_t begin_ns = 0;
  uint64_t end_ns = 0;
  std::array<Reading, std::size(p06::kCapabilities)> capabilities{};
  std::array<Reading, std::size(p06::kCounters)> counters{};
  std::array<bool, std::size(p06::kCounters)> enabled{};
};

uint64_t now_ns() noexcept;
void set_phase(Phase phase) noexcept;
Counts counts() noexcept;
Memory memory() noexcept;
Snapshot snapshot() noexcept;
const Memory& after_open_memory() noexcept;
const Memory& before_release_memory() noexcept;
const Snapshot& after_open_snapshot() noexcept;
const Snapshot& before_release_snapshot() noexcept;
vx_result_t release_status() noexcept;
void print_counts(const Counts& value) noexcept;
void print_memory(const Memory& value) noexcept;
void print_snapshot(const Snapshot& value, const char* sample_id) noexcept;

} // namespace p06_warm

#endif
