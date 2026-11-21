// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_WORKSPACE_OBSERVER_H
#define VORTEX_AI_WORKSPACE_OBSERVER_H

#include <vortex2.h>
#include <array>
#include <cstddef>
#include <cstdint>

namespace p06_workspace {

enum class Phase {
  context_create, idle, submit, live, wait, operation_close, owner_close,
  competing_context, competing_operation, owner_close_live
};

struct Memory {
  bool queried = false;
  vx_result_t status = VX_ERR_INVALID_HANDLE;
  uint64_t free_bytes = 0;
  uint64_t used_bytes = 0;
};

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

struct Device {
  uint64_t device_id = 0;
  uint32_t index = 0;
  vx_device_h handle = nullptr;
  bool live = false;
  vx_result_t open_status = VX_ERR_INTERNAL;
  Memory after_open;
  bool release_called = false;
  vx_result_t release_status = VX_ERR_INTERNAL;
  Memory before_release;
};

struct Buffer {
  uint64_t buffer_id = 0;
  uint64_t device_id = 0;
  uint64_t requested_bytes = 0;
  uint32_t flags = 0;
  uint64_t address = 0;
  vx_buffer_h handle = nullptr;
  bool live = false;
  vx_result_t address_status = VX_ERR_INTERNAL;
  vx_result_t create_status = VX_ERR_INTERNAL;
  Phase create_phase = Phase::idle;
  int32_t create_sequence = -1;
  Memory create_before;
  Memory create_after;
  bool release_called = false;
  vx_result_t release_status = VX_ERR_INTERNAL;
  Phase release_phase = Phase::idle;
  int32_t release_sequence = -1;
  bool release_device_live = false;
  Memory release_before;
  Memory release_after;
};

struct Observation {
  Counts counts;
  std::array<Device, 4> devices{};
  size_t device_count = 0;
  std::array<Buffer, 16> buffers{};
  size_t buffer_count = 0;
};

void set_phase(Phase phase, int32_t sequence = -1) noexcept;
const char* phase_name(Phase phase) noexcept;
const Observation& observation() noexcept;
Counts counts() noexcept;
bool same_counts(const Counts& left, const Counts& right) noexcept;
bool matches_live_buffer(uint64_t address, uint64_t bytes, uint32_t flags) noexcept;
bool reconciled(const Buffer& buffer) noexcept;
void print_memory(const Memory& memory) noexcept;
void print_counts(const Counts& counts) noexcept;
void print_devices() noexcept;
void print_buffers() noexcept;

} // namespace p06_workspace

#endif
