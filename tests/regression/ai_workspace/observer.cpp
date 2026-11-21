// SPDX-License-Identifier: Apache-2.0

#include "observer.h"
#include <algorithm>
#include <cinttypes>
#include <cstdio>

extern "C" vx_result_t __real_vx_device_open(uint32_t index, vx_device_h* out);
extern "C" vx_result_t __real_vx_device_release(vx_device_h device);
extern "C" vx_result_t __real_vx_buffer_create(vx_device_h device, uint64_t size,
                                              uint32_t flags, vx_buffer_h* out);
extern "C" vx_result_t __real_vx_buffer_release(vx_buffer_h buffer);

namespace p06_workspace {
namespace {

Observation state;
Phase phase = Phase::idle;
int32_t sequence = -1;

Device* live_device(vx_device_h handle) noexcept {
  for (size_t i = 0; i != state.device_count; ++i) {
    auto& device = state.devices[i];
    if (device.live && device.handle == handle) {
      return &device;
    }
  }
  return nullptr;
}

Memory memory(Device* device) noexcept {
  Memory result;
  if (!device || !device->live) {
    ++state.counts.errors;
    return result;
  }
  result.queried = true;
  try {
    result.status = vx_device_memory_info(device->handle, &result.free_bytes,
                                          &result.used_bytes);
  } catch (...) {
    result.status = VX_ERR_INTERNAL;
  }
  if (result.status != VX_SUCCESS) {
    ++state.counts.errors;
  }
  return result;
}

bool valid(const Memory& value) noexcept {
  return value.queried && value.status == VX_SUCCESS;
}

void print_status(bool called, vx_result_t status) noexcept {
  if (called) {
    std::printf("%u", static_cast<unsigned>(status));
  } else {
    std::fputs("null", stdout);
  }
}

} // namespace

void set_phase(Phase value, int32_t index) noexcept {
  phase = value;
  sequence = index;
}

const char* phase_name(Phase value) noexcept {
  switch (value) {
  case Phase::context_create: return "context_create";
  case Phase::idle: return "idle";
  case Phase::submit: return "submit";
  case Phase::live: return "live";
  case Phase::wait: return "wait";
  case Phase::operation_close: return "operation_close";
  case Phase::owner_close: return "owner_close";
  case Phase::competing_context: return "competing_context";
  case Phase::competing_operation: return "competing_operation";
  case Phase::owner_close_live: return "owner_close_live";
  }
  return "invalid";
}

const Observation& observation() noexcept {
  return state;
}

Counts counts() noexcept {
  return state.counts;
}

bool same_counts(const Counts& left, const Counts& right) noexcept {
  return left.device_open_calls == right.device_open_calls
      && left.device_release_calls == right.device_release_calls
      && left.buffer_create_calls == right.buffer_create_calls
      && left.buffer_release_calls == right.buffer_release_calls
      && left.live_buffers == right.live_buffers
      && left.live_requested_bytes == right.live_requested_bytes
      && left.peak_requested_payload_bytes == right.peak_requested_payload_bytes
      && left.premature_releases == right.premature_releases
      && left.errors == right.errors;
}

bool matches_live_buffer(uint64_t address, uint64_t bytes, uint32_t flags) noexcept {
  size_t matches = 0;
  for (size_t i = 0; i != state.buffer_count; ++i) {
    const auto& buffer = state.buffers[i];
    if (buffer.live && buffer.address_status == VX_SUCCESS
        && buffer.address == address && buffer.requested_bytes == bytes
        && buffer.flags == flags) {
      ++matches;
    }
  }
  return matches == 1;
}

bool reconciled(const Buffer& buffer) noexcept {
  if (buffer.live || buffer.create_status != VX_SUCCESS
      || buffer.address_status != VX_SUCCESS || !buffer.release_called
      || buffer.release_status != VX_SUCCESS || !buffer.release_device_live
      || !valid(buffer.create_before) || !valid(buffer.create_after)
      || !valid(buffer.release_before) || !valid(buffer.release_after)) {
    return false;
  }
  const auto& cb = buffer.create_before;
  const auto& ca = buffer.create_after;
  const auto& rb = buffer.release_before;
  const auto& ra = buffer.release_after;
  if (ca.used_bytes < cb.used_bytes || cb.free_bytes < ca.free_bytes
      || rb.used_bytes < ra.used_bytes || ra.free_bytes < rb.free_bytes) {
    return false;
  }
  const uint64_t allocated = ca.used_bytes - cb.used_bytes;
  return allocated >= buffer.requested_bytes && allocated > 0
      && cb.free_bytes - ca.free_bytes == allocated
      && rb.used_bytes - ra.used_bytes == allocated
      && ra.free_bytes - rb.free_bytes == allocated;
}

void print_memory(const Memory& value) noexcept {
  if (!value.queried) {
    std::fputs("null", stdout);
    return;
  }
  std::printf("{\"status\":%u,\"free_bytes\":%" PRIu64 ",\"used_bytes\":%" PRIu64 "}",
      static_cast<unsigned>(value.status), value.free_bytes, value.used_bytes);
}

void print_counts(const Counts& value) noexcept {
  std::printf("{\"device_open_calls\":%" PRIu64 ",\"device_release_calls\":%" PRIu64
      ",\"buffer_create_calls\":%" PRIu64 ",\"buffer_release_calls\":%" PRIu64
      ",\"live_buffers\":%" PRIu64 ",\"live_requested_bytes\":%" PRIu64
      ",\"peak_requested_payload_bytes\":%" PRIu64
      ",\"premature_releases\":%" PRIu64 ",\"errors\":%" PRIu64 "}",
      value.device_open_calls, value.device_release_calls, value.buffer_create_calls,
      value.buffer_release_calls, value.live_buffers, value.live_requested_bytes,
      value.peak_requested_payload_bytes, value.premature_releases, value.errors);
}

void print_devices() noexcept {
  std::fputc('[', stdout);
  for (size_t i = 0; i != state.device_count; ++i) {
    const auto& device = state.devices[i];
    std::printf("%s{\"device_id\":%" PRIu64 ",\"index\":%u,\"open_status\":%u,\"after_open\":",
        i ? "," : "", device.device_id, device.index,
        static_cast<unsigned>(device.open_status));
    print_memory(device.after_open);
    std::fputs(",\"release_status\":", stdout);
    print_status(device.release_called, device.release_status);
    std::fputs(",\"before_release\":", stdout);
    print_memory(device.before_release);
    std::fputc('}', stdout);
  }
  std::fputc(']', stdout);
}

void print_buffers() noexcept {
  std::fputc('[', stdout);
  for (size_t i = 0; i != state.buffer_count; ++i) {
    const auto& buffer = state.buffers[i];
    std::printf("%s{\"buffer_id\":%" PRIu64 ",\"device_id\":%" PRIu64
        ",\"requested_bytes\":%" PRIu64 ",\"flags\":%u,\"address\":%" PRIu64
        ",\"address_status\":%u,\"create_status\":%u,\"create_phase\":\"%s\""
        ",\"create_sequence\":%" PRId32 ",\"create_before\":",
        i ? "," : "", buffer.buffer_id, buffer.device_id, buffer.requested_bytes,
        buffer.flags, buffer.address, static_cast<unsigned>(buffer.address_status),
        static_cast<unsigned>(buffer.create_status), phase_name(buffer.create_phase),
        buffer.create_sequence);
    print_memory(buffer.create_before);
    std::fputs(",\"create_after\":", stdout);
    print_memory(buffer.create_after);
    std::fputs(",\"release_status\":", stdout);
    print_status(buffer.release_called, buffer.release_status);
    std::printf(",\"release_phase\":\"%s\",\"release_sequence\":%" PRId32
        ",\"release_device_live\":%s,\"release_before\":",
        phase_name(buffer.release_phase), buffer.release_sequence,
        buffer.release_device_live ? "true" : "false");
    print_memory(buffer.release_before);
    std::fputs(",\"release_after\":", stdout);
    print_memory(buffer.release_after);
    std::fputc('}', stdout);
  }
  std::fputc(']', stdout);
}

} // namespace p06_workspace

extern "C" vx_result_t __wrap_vx_device_open(uint32_t index, vx_device_h* out) noexcept {
  using namespace p06_workspace;
  ++state.counts.device_open_calls;
  Device* record = nullptr;
  if (state.device_count < state.devices.size()) {
    record = &state.devices[state.device_count++];
    record->device_id = state.counts.device_open_calls;
    record->index = index;
  } else {
    ++state.counts.errors;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_device_open(index, out);
  } catch (...) {
    ++state.counts.errors;
  }
  if (record) {
    record->open_status = result;
    if (result == VX_SUCCESS && out && *out) {
      record->handle = *out;
      record->live = true;
      record->after_open = memory(record);
    } else if (result == VX_SUCCESS) {
      ++state.counts.errors;
    }
  }
  return result;
}

extern "C" vx_result_t __wrap_vx_device_release(vx_device_h device) noexcept {
  using namespace p06_workspace;
  ++state.counts.device_release_calls;
  auto* record = live_device(device);
  if (record) {
    record->release_called = true;
    record->before_release = memory(record);
  } else {
    ++state.counts.errors;
  }
  if (phase != Phase::owner_close && phase != Phase::context_create) {
    ++state.counts.premature_releases;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_device_release(device);
  } catch (...) {
    ++state.counts.errors;
  }
  if (record) {
    record->release_status = result;
    record->live = false;
  }
  return result;
}

extern "C" vx_result_t __wrap_vx_buffer_create(vx_device_h device, uint64_t size,
                                              uint32_t flags, vx_buffer_h* out) noexcept {
  using namespace p06_workspace;
  ++state.counts.buffer_create_calls;
  auto* owner = live_device(device);
  Buffer* record = nullptr;
  if (state.buffer_count < state.buffers.size()) {
    record = &state.buffers[state.buffer_count++];
    record->buffer_id = state.counts.buffer_create_calls;
    record->device_id = owner ? owner->device_id : 0;
    record->requested_bytes = size;
    record->flags = flags;
    record->create_phase = phase;
    record->create_sequence = sequence;
    record->create_before = memory(owner);
  } else {
    ++state.counts.errors;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_buffer_create(device, size, flags, out);
  } catch (...) {
    ++state.counts.errors;
  }
  if (record) {
    record->create_status = result;
    record->create_after = memory(owner);
    if (result == VX_SUCCESS && out && *out) {
      record->handle = *out;
      record->live = true;
      ++state.counts.live_buffers;
      state.counts.live_requested_bytes += size;
      state.counts.peak_requested_payload_bytes = std::max(
          state.counts.peak_requested_payload_bytes, state.counts.live_requested_bytes);
      try {
        record->address_status = vx_buffer_address(*out, &record->address);
      } catch (...) {
        record->address_status = VX_ERR_INTERNAL;
      }
      if (record->address_status != VX_SUCCESS) {
        ++state.counts.errors;
      }
    } else if (result == VX_SUCCESS) {
      ++state.counts.errors;
    }
  }
  return result;
}

extern "C" vx_result_t __wrap_vx_buffer_release(vx_buffer_h buffer) noexcept {
  using namespace p06_workspace;
  ++state.counts.buffer_release_calls;
  Buffer* record = nullptr;
  Device* owner = nullptr;
  for (size_t i = 0; i != state.buffer_count; ++i) {
    auto& candidate = state.buffers[i];
    if (candidate.live && candidate.handle == buffer) {
      record = &candidate;
      break;
    }
  }
  if (record) {
    for (size_t i = 0; i != state.device_count; ++i) {
      auto& candidate = state.devices[i];
      if (candidate.live && candidate.device_id == record->device_id) {
        owner = &candidate;
        break;
      }
    }
    record->release_called = true;
    record->release_phase = phase;
    record->release_sequence = sequence;
    record->release_device_live = owner != nullptr;
    record->release_before = memory(owner);
  } else {
    ++state.counts.errors;
  }
  if (phase != Phase::operation_close && phase != Phase::owner_close
      && phase != Phase::context_create) {
    ++state.counts.premature_releases;
  }
  // Observation never suppresses the actual owner's release.
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_buffer_release(buffer);
  } catch (...) {
    ++state.counts.errors;
  }
  if (record) {
    record->release_status = result;
    record->release_after = memory(owner);
    if (result == VX_SUCCESS) {
      record->live = false;
      --state.counts.live_buffers;
      state.counts.live_requested_bytes -= record->requested_bytes;
    }
  }
  return result;
}
