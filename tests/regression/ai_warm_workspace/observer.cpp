// SPDX-License-Identifier: Apache-2.0
#include "observer.h"
#include <VX_config.h>
#include <algorithm>
#include <chrono>
#include <cinttypes>
#include <cstdio>

extern "C" vx_result_t __real_vx_device_open(uint32_t, vx_device_h*);
extern "C" vx_result_t __real_vx_device_release(vx_device_h);
extern "C" vx_result_t __real_vx_buffer_create(vx_device_h, uint64_t, uint32_t, vx_buffer_h*);
extern "C" vx_result_t __real_vx_buffer_release(vx_buffer_h);

namespace p06_warm {
namespace {

struct Slot {
  vx_buffer_h handle = nullptr;
  uint64_t bytes = 0;
};

struct State {
  Counts counts;
  std::array<Slot, 3> live{};
  vx_device_h device = nullptr;
  Phase phase = Phase::context_create;
  Memory opened_memory;
  Memory releasing_memory;
  Snapshot opened_snapshot;
  Snapshot releasing_snapshot;
  vx_result_t released = VX_ERR_INVALID_HANDLE;
};

State state;

void print_reading(const Reading& value) noexcept {
  std::fputs(",\"status\":", stdout);
  if (value.returned) {
    std::printf("%u", static_cast<unsigned>(value.status));
  } else {
    std::fputs("null", stdout);
  }
  std::fputs(",\"value\":", stdout);
  if (value.returned && value.status == VX_SUCCESS) {
    std::printf("%" PRIu64, value.value);
  } else {
    std::fputs("null", stdout);
  }
}

} // namespace

uint64_t now_ns() noexcept {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count());
}

void set_phase(Phase phase) noexcept {
  state.phase = phase;
}

Counts counts() noexcept {
  return state.counts;
}

const Memory& after_open_memory() noexcept {
  return state.opened_memory;
}

const Memory& before_release_memory() noexcept {
  return state.releasing_memory;
}

const Snapshot& after_open_snapshot() noexcept {
  return state.opened_snapshot;
}

const Snapshot& before_release_snapshot() noexcept {
  return state.releasing_snapshot;
}

vx_result_t release_status() noexcept {
  return state.released;
}

Memory memory() noexcept {
  Memory value;
  value.queried = true;
  try {
    value.status = vx_device_memory_info(state.device, &value.free_bytes, &value.used_bytes);
  } catch (...) {
    value.status = VX_ERR_INTERNAL;
  }
  if (value.status != VX_SUCCESS) {
    ++state.counts.errors;
  }
  return value;
}

Snapshot snapshot() noexcept {
  Snapshot value;
  value.begin_ns = now_ns();
  uint64_t isa = 0;
  bool valid = state.device != nullptr;
  for (size_t i = 0; i != value.capabilities.size(); ++i) {
    auto& reading = value.capabilities[i];
    try {
      reading.status = vx_device_query(state.device, p06::kCapabilities[i].id, &reading.value);
      reading.returned = true;
    } catch (...) {
      reading.status = VX_ERR_INTERNAL;
    }
    if (!reading.returned || reading.status != VX_SUCCESS) {
      ++state.counts.errors;
      valid = false;
    }
    if (p06::kCapabilities[i].id == VX_CAPS_ISA_FLAGS) {
      isa = reading.value;
    }
  }
  for (size_t i = 0; valid && i != value.counters.size(); ++i) {
    const auto& descriptor = p06::kCounters[i];
    value.enabled[i] = descriptor.required_isa == 0
        || (isa & descriptor.required_isa) == descriptor.required_isa;
    if (!value.enabled[i]) {
      continue;
    }
    auto& reading = value.counters[i];
    try {
      reading.status = vx_device_mpm_query(state.device, descriptor.mpm_class,
          descriptor.csr, descriptor.core_id, &reading.value);
      reading.returned = true;
    } catch (...) {
      reading.status = VX_ERR_INTERNAL;
    }
    if (!reading.returned || reading.status != VX_SUCCESS) {
      ++state.counts.errors;
    }
  }
  value.end_ns = now_ns();
  return value;
}

void print_counts(const Counts& value) noexcept {
  std::printf("{\"device_open_calls\":%" PRIu64 ",\"device_release_calls\":%" PRIu64
      ",\"buffer_create_calls\":%" PRIu64 ",\"buffer_release_calls\":%" PRIu64
      ",\"live_buffers\":%" PRIu64 ",\"live_requested_bytes\":%" PRIu64
      ",\"peak_requested_payload_bytes\":%" PRIu64 ",\"premature_releases\":%" PRIu64
      ",\"errors\":%" PRIu64 "}", value.device_open_calls, value.device_release_calls,
      value.buffer_create_calls, value.buffer_release_calls, value.live_buffers,
      value.live_requested_bytes, value.peak_requested_payload_bytes,
      value.premature_releases, value.errors);
}

void print_memory(const Memory& value) noexcept {
  std::printf("{\"queried\":%s,\"status\":%u,\"free_bytes\":%" PRIu64
      ",\"used_bytes\":%" PRIu64 "}", value.queried ? "true" : "false",
      static_cast<unsigned>(value.status), value.free_bytes, value.used_bytes);
}

void print_snapshot(const Snapshot& value, const char* sample_id) noexcept {
  std::printf("{\"schema_version\":1,\"sample_id\":\"%s\",\"context_id\":1,"
      "\"device_index\":0,\"compiled_memory_block_bytes\":%u,"
      "\"query_begin_ns\":%" PRIu64 ",\"query_end_ns\":%" PRIu64 ",\"capabilities\":[",
      sample_id, static_cast<unsigned>(VX_CFG_MEM_BLOCK_SIZE), value.begin_ns, value.end_ns);
  for (size_t i = 0; i != value.capabilities.size(); ++i) {
    const auto& descriptor = p06::kCapabilities[i];
    std::printf("%s{\"name\":\"%s\",\"id\":%u", i ? "," : "", descriptor.name, descriptor.id);
    print_reading(value.capabilities[i]);
    std::fputc('}', stdout);
  }
  std::fputs("],\"counters\":[", stdout);
  for (size_t i = 0; i != value.counters.size(); ++i) {
    const auto& descriptor = p06::kCounters[i];
    std::printf("%s{\"name\":\"%s\",\"mpm_class\":%u,\"csr\":%u,\"core_id\":%u,"
        "\"scope\":\"%s\",\"unit\":\"%s\",\"required_isa\":%" PRIu64 ",\"enabled\":%s",
        i ? "," : "", descriptor.name, descriptor.mpm_class, descriptor.csr,
        descriptor.core_id, descriptor.scope, descriptor.unit, descriptor.required_isa,
        value.enabled[i] ? "true" : "false");
    print_reading(value.counters[i]);
    std::fputc('}', stdout);
  }
  std::fputs("]}", stdout);
}

} // namespace p06_warm

extern "C" vx_result_t __wrap_vx_device_open(uint32_t index, vx_device_h* out) noexcept {
  using namespace p06_warm;
  ++state.counts.device_open_calls;
  if (index != 0 || state.counts.device_open_calls != 1
      || state.phase != Phase::context_create) {
    ++state.counts.errors;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_device_open(index, out);
  } catch (...) {
    ++state.counts.errors;
  }
  if (result == VX_SUCCESS && out && *out && !state.device) {
    state.device = *out;
    state.opened_memory = memory();
    state.opened_snapshot = snapshot();
  } else {
    ++state.counts.errors;
  }
  return result;
}

extern "C" vx_result_t __wrap_vx_device_release(vx_device_h device) noexcept {
  using namespace p06_warm;
  ++state.counts.device_release_calls;
  if (device && device == state.device && state.counts.device_release_calls == 1) {
    if (state.phase != Phase::owner_close || state.counts.live_buffers != 0) {
      ++state.counts.premature_releases;
    }
    state.releasing_snapshot = snapshot();
    state.releasing_memory = memory();
  } else {
    ++state.counts.errors;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_device_release(device);
  } catch (...) {
    ++state.counts.errors;
  }
  state.released = result;
  if (result != VX_SUCCESS) {
    ++state.counts.errors;
  }
  if (device == state.device) {
    state.device = nullptr;
  }
  return result;
}

extern "C" vx_result_t __wrap_vx_buffer_create(vx_device_h device, uint64_t bytes,
                                               uint32_t flags, vx_buffer_h* out) noexcept {
  using namespace p06_warm;
  ++state.counts.buffer_create_calls;
  if (device != state.device || !device || state.counts.buffer_create_calls > 99
      || (state.phase != Phase::context_create && state.phase != Phase::submit)
      || !((bytes == 128 && (flags == VX_MEM_READ || flags == VX_MEM_WRITE))
           || (bytes == 64 && flags == VX_MEM_READ))) {
    ++state.counts.errors;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_buffer_create(device, bytes, flags, out);
  } catch (...) {
    ++state.counts.errors;
  }
  if (result != VX_SUCCESS || !out || !*out) {
    ++state.counts.errors;
    return result;
  }
  Slot* empty = nullptr;
  for (auto& slot : state.live) {
    if (slot.handle == *out) {
      ++state.counts.errors;
    }
    if (!slot.handle && !empty) {
      empty = &slot;
    }
  }
  if (!empty || bytes > UINT64_MAX - state.counts.live_requested_bytes) {
    ++state.counts.errors;
    return result;
  }
  *empty = {*out, bytes};
  ++state.counts.live_buffers;
  state.counts.live_requested_bytes += bytes;
  state.counts.peak_requested_payload_bytes = std::max(
      state.counts.peak_requested_payload_bytes, state.counts.live_requested_bytes);
  return result;
}

extern "C" vx_result_t __wrap_vx_buffer_release(vx_buffer_h buffer) noexcept {
  using namespace p06_warm;
  ++state.counts.buffer_release_calls;
  Slot* matched = nullptr;
  for (auto& slot : state.live) {
    if (buffer && slot.handle == buffer) {
      matched = &slot;
    }
  }
  if (!matched) {
    ++state.counts.errors;
  }
  if (!state.device || (state.phase != Phase::operation_close && state.phase != Phase::owner_close)) {
    ++state.counts.premature_releases;
  }
  vx_result_t result = VX_ERR_INTERNAL;
  try {
    result = __real_vx_buffer_release(buffer);
  } catch (...) {
    ++state.counts.errors;
  }
  if (result != VX_SUCCESS) {
    ++state.counts.errors;
  }
  if (matched) {
    --state.counts.live_buffers;
    state.counts.live_requested_bytes -= matched->bytes;
    *matched = {};
  }
  return result;
}
