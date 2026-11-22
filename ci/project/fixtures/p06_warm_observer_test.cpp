// SPDX-License-Identifier: Apache-2.0
#include "observer.h"
#include <array>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>

extern "C" vx_result_t __wrap_vx_device_open(uint32_t, vx_device_h*) noexcept;
extern "C" vx_result_t __wrap_vx_device_release(vx_device_h) noexcept;
extern "C" vx_result_t __wrap_vx_buffer_create(vx_device_h, uint64_t, uint32_t, vx_buffer_h*) noexcept;
extern "C" vx_result_t __wrap_vx_buffer_release(vx_buffer_h) noexcept;

namespace observed = p06_warm;

namespace {

uint64_t allocations = 0;
const char* fault = "none";
int device_token = 0;
int other_token = 0;

struct Buffer {
  bool live = false;
  uint64_t bytes = 0;
};

struct Native {
  uint64_t opens = 0, releases = 0, creates = 0, frees = 0;
  uint64_t memory = 0, capabilities = 0, counters = 0, addresses = 0;
  uint64_t used = 0, live = 0;
  std::array<uint64_t, std::size(p06::kCounters)> counter_queries{};
  std::array<uint64_t, std::size(p06::kCapabilities)> capability_queries{};
  std::array<Buffer, 128> buffers{};
  vx_device_h last_device = nullptr;
  vx_buffer_h last_buffer = nullptr;
  vx_buffer_h* last_out = nullptr;
  uint64_t last_bytes = 0;
  uint32_t last_flags = 0, last_index = 0;
} native;

bool is(const char* name) {
  return std::strcmp(fault, name) == 0;
}

void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "observer test failure: %s\n", message);
    std::exit(2);
  }
}

uint64_t isa_flags() {
  return VX_ISA_EXT_ICACHE | VX_ISA_EXT_DCACHE | VX_ISA_EXT_LMEM | VX_ISA_EXT_TCU;
}

std::array<uint64_t, 5> measurements() {
  return {native.memory, native.capabilities, native.counters, native.addresses, allocations};
}

uint64_t errors() {
  const auto counts = observed::counts();
  return counts.errors + counts.premature_releases;
}

vx_result_t create(vx_device_h device, uint64_t bytes, uint32_t flags, vx_buffer_h* out) {
  const auto before = measurements();
  const uint64_t calls = native.creates;
  const vx_result_t result = __wrap_vx_buffer_create(device, bytes, flags, out);
  check(native.creates == calls + 1, "allocation was not forwarded exactly once");
  check(native.last_device == device && native.last_bytes == bytes
      && native.last_flags == flags && native.last_out == out, "allocation arguments changed");
  check(measurements() == before, "allocation wrapper queried native state or allocated storage");
  return result;
}

vx_result_t release(vx_buffer_h buffer) {
  const auto before = measurements();
  const uint64_t calls = native.frees;
  const vx_result_t result = __wrap_vx_buffer_release(buffer);
  check(native.frees == calls + 1 && native.last_buffer == buffer,
      "buffer cleanup was skipped, repeated or changed");
  check(measurements() == before, "release wrapper queried native state or allocated storage");
  return result;
}

vx_device_h open(uint32_t index = 0) {
  vx_device_h device = nullptr;
  const uint64_t calls = native.opens;
  const vx_result_t result = __wrap_vx_device_open(index, &device);
  check(native.opens == calls + 1 && native.last_index == index, "device open was not forwarded");
  if (!is("open_failed") && !is("open_throw")) {
    check(result == VX_SUCCESS, "unexpected open result");
  } else {
    check(result != VX_SUCCESS, "failed open returned success");
  }
  return device;
}

vx_result_t close(vx_device_h device) {
  const uint64_t calls = native.releases;
  const vx_result_t result = __wrap_vx_device_release(device);
  check(native.releases == calls + 1 && native.last_device == device,
      "device cleanup was skipped, repeated or changed");
  check(observed::release_status() == result, "device release status was not retained");
  return result;
}

std::array<vx_buffer_h, 3> buffers(vx_device_h device) {
  std::array<vx_buffer_h, 3> result{};
  check(create(device, 128, VX_MEM_READ, &result[0]) == VX_SUCCESS, "A create failed");
  check(create(device, 64, VX_MEM_READ, &result[1]) == VX_SUCCESS, "B create failed");
  check(create(device, 128, VX_MEM_WRITE, &result[2]) == VX_SUCCESS, "D create failed");
  return result;
}

void free_buffers(const std::array<vx_buffer_h, 3>& values) {
  for (vx_buffer_h value : values) {
    check(release(value) == VX_SUCCESS, "buffer release failed");
  }
}

void success(bool resident) {
  const vx_device_h device = open();
  std::array<vx_buffer_h, 3> values{};
  if (resident) {
    values = buffers(device);
  }
  observed::set_phase(observed::Phase::idle);
  check(observed::memory().status == VX_SUCCESS, "idle memory failed");
  for (size_t index = 0; index != 33; ++index) {
    if (!resident) {
      observed::set_phase(observed::Phase::submit);
      values = buffers(device);
    }
    check(observed::counts().live_buffers == 3 && observed::counts().live_requested_bytes == 320,
        "live triple accounting differs");
    if (!resident) {
      observed::set_phase(observed::Phase::operation_close);
      free_buffers(values);
      check(observed::counts().live_buffers == 0 && observed::counts().live_requested_bytes == 0,
          "closed operation retains tensor payload");
    }
    observed::set_phase(observed::Phase::idle);
    if (index == 0 || index == 32) {
      const auto snapshot = observed::snapshot();
      check(snapshot.begin_ns <= snapshot.end_ns, "snapshot interval reversed");
      check(observed::memory().status == VX_SUCCESS, "batch memory failed");
    }
  }
  observed::set_phase(observed::Phase::owner_close);
  if (resident) {
    free_buffers(values);
  }
  check(close(device) == VX_SUCCESS, "owner release failed");
  const auto counts = observed::counts();
  check(counts.errors == 0 && counts.premature_releases == 0 && counts.live_buffers == 0
      && counts.live_requested_bytes == 0 && counts.peak_requested_payload_bytes == 320,
      "successful resource accounting differs");
  check(native.creates == (resident ? 3u : 99u) && native.frees == native.creates
      && native.live == 0 && native.used == 0 && native.opens == 1 && native.releases == 1,
      "successful native lifetimes differ");
  check(native.memory == 5 && native.capabilities == 52 && native.counters == 132
      && native.addresses == 0, "unexpected observation queries");
  const auto& snapshot = observed::before_release_snapshot();
  for (size_t index = 0; index != std::size(p06::kCounters); ++index) {
    const bool enabled = p06::kCounters[index].required_isa == 0
        || (isa_flags() & p06::kCounters[index].required_isa) == p06::kCounters[index].required_isa;
    check(snapshot.enabled[index] == enabled && snapshot.counters[index].returned == enabled,
        "counter availability differs");
    check(native.counter_queries[index] == (enabled ? 4u : 0u), "counter query inventory differs");
  }
  for (uint64_t calls : native.capability_queries) {
    check(calls == 4, "capability query inventory differs");
  }
}

void rejected(const char* scenario) {
  if (std::strncmp(scenario, "open_", 5) == 0) {
    fault = scenario;
    if (is("open_phase")) {
      observed::set_phase(observed::Phase::idle);
    }
    if (is("open_null_out")) {
      check(__wrap_vx_device_open(0, nullptr) == VX_SUCCESS && native.opens == 1,
          "null-output open was not forwarded");
    } else {
      const vx_device_h device = open(is("open_index") ? 1u : 0u);
      if (is("open_duplicate")) {
        open();
      }
      check(errors() != 0, "invalid open did not report an error");
      if (device) {
        observed::set_phase(observed::Phase::owner_close);
        close(device);
      }
    }
  } else if (std::strncmp(scenario, "query_", 6) == 0) {
    const vx_device_h device = open();
    fault = scenario;
    const uint64_t errors_before = errors();
    const uint64_t counter_before = native.counters;
    if (is("query_memory_failed") || is("query_memory_throw")) {
      check(observed::memory().status != VX_SUCCESS, "memory error became success");
    } else {
      const auto result = observed::snapshot();
      if (is("query_capability_failed") || is("query_capability_throw")) {
        check(native.counters == counter_before, "counter query followed invalid capabilities");
        check(result.capabilities[0].status != VX_SUCCESS, "capability error disappeared");
      } else {
        check(native.counters == counter_before + 33 && result.counters[0].status != VX_SUCCESS,
            "counter failure inventory differs");
      }
    }
    check(errors() > errors_before, "failed query did not report an observer error");
    fault = "none";
    observed::set_phase(observed::Phase::owner_close);
    close(device);
  } else {
    vx_device_h device = nullptr;
    if (std::strcmp(scenario, "create_no_device") != 0) {
      device = open();
    }
    std::array<vx_buffer_h, 3> values{};
    vx_buffer_h extra = nullptr;
    if (std::strncmp(scenario, "create_", 7) == 0) {
      observed::set_phase(observed::Phase::submit);
      if (std::strcmp(scenario, "create_limit") == 0) {
        for (size_t index = 0; index != 33; ++index) {
          values = buffers(device);
          observed::set_phase(observed::Phase::operation_close);
          free_buffers(values);
          observed::set_phase(observed::Phase::submit);
        }
        values = {};
      } else if (std::strcmp(scenario, "create_slots") == 0) {
        values = buffers(device);
      } else if (std::strcmp(scenario, "create_duplicate") == 0) {
        create(device, 128, VX_MEM_READ, &values[0]);
      }
      fault = scenario;
      if (is("create_idle")) {
        observed::set_phase(observed::Phase::idle);
      } else if (is("create_closing")) {
        observed::set_phase(observed::Phase::operation_close);
      } else if (is("create_owner_close")) {
        observed::set_phase(observed::Phase::owner_close);
      }
      const uint64_t errors_before = errors();
      const vx_result_t result = create(is("create_wrong_device") ? &other_token : device,
          is("create_size") ? 32u : 128u, is("create_flags") ? 0u : VX_MEM_READ,
          is("create_null_out") ? nullptr : &extra);
      if (is("create_failed") || is("create_throw")) {
        check(result != VX_SUCCESS, "allocation failure became success");
      }
      if (is("create_slots")) {
        check(observed::counts().live_buffers == 3 && native.live == 4,
            "observer did not preserve the three-slot boundary");
      }
      check(errors() > errors_before, "invalid allocation did not report an observer error");
      fault = "none";
      observed::set_phase(observed::Phase::operation_close);
      if (extra) {
        release(extra);
      }
      for (vx_buffer_h value : values) {
        if (value) {
          release(value);
        }
      }
    } else if (std::strncmp(scenario, "buffer_", 7) == 0) {
      values = buffers(device);
      observed::set_phase(observed::Phase::operation_close);
      fault = scenario;
      if (is("buffer_idle")) {
        observed::set_phase(observed::Phase::idle);
      } else if (is("buffer_submit")) {
        observed::set_phase(observed::Phase::submit);
      } else if (is("buffer_create")) {
        observed::set_phase(observed::Phase::context_create);
      } else if (is("buffer_no_device")) {
        observed::set_phase(observed::Phase::owner_close);
        close(device);
        device = nullptr;
      }
      const uint64_t errors_before = errors();
      const vx_result_t result = release(is("buffer_unknown") ? &other_token
          : is("buffer_null") ? nullptr : values[0]);
      if (is("buffer_failed") || is("buffer_throw")) {
        check(result != VX_SUCCESS && native.live == 3, "native failed-release retention was hidden");
      }
      check(errors() > errors_before, "invalid buffer cleanup did not report an observer error");
      fault = "none";
      observed::set_phase(observed::Phase::operation_close);
      for (vx_buffer_h value : values) {
        const auto* stored = static_cast<Buffer*>(value);
        if (stored->live) {
          release(value);
        }
      }
    } else if (std::strncmp(scenario, "device_", 7) == 0) {
      if (std::strcmp(scenario, "device_live") == 0) {
        values = buffers(device);
      }
      observed::set_phase(observed::Phase::owner_close);
      fault = scenario;
      if (is("device_idle")) {
        observed::set_phase(observed::Phase::idle);
      }
      const uint64_t errors_before = errors();
      const vx_result_t result = close(is("device_unknown") ? &other_token
          : is("device_null") ? nullptr : device);
      if (is("device_failed") || is("device_throw")) {
        check(result != VX_SUCCESS, "device failure became success");
      }
      check(errors() > errors_before, "invalid device cleanup did not report an observer error");
      device = nullptr;
    } else {
      check(false, "unknown scenario");
    }
    fault = "none";
    if (device) {
      observed::set_phase(observed::Phase::owner_close);
      close(device);
    }
  }
  check(observed::counts().errors != 0 || observed::counts().premature_releases != 0,
      "invalid behavior has successful observer counts");
}

} // namespace

void* operator new(std::size_t bytes) {
  ++allocations;
  void* result = std::malloc(bytes ? bytes : 1);
  if (!result) {
    throw std::bad_alloc();
  }
  return result;
}

void* operator new[](std::size_t bytes) {
  return ::operator new(bytes);
}

void operator delete(void* value) noexcept { std::free(value); }
void operator delete[](void* value) noexcept { std::free(value); }
void operator delete(void* value, std::size_t) noexcept { std::free(value); }
void operator delete[](void* value, std::size_t) noexcept { std::free(value); }

extern "C" vx_result_t __real_vx_device_open(uint32_t index, vx_device_h* out) {
  ++native.opens;
  native.last_index = index;
  if (is("open_throw")) {
    throw 1;
  }
  if (is("open_failed")) {
    return VX_ERR_DEVICE_LOST;
  }
  if (out) {
    *out = is("open_null_handle") ? nullptr : &device_token;
  }
  return VX_SUCCESS;
}

extern "C" vx_result_t __real_vx_device_release(vx_device_h device) {
  ++native.releases;
  native.last_device = device;
  if (is("device_throw")) {
    throw 1;
  }
  return is("device_failed") ? VX_ERR_DEVICE_LOST : VX_SUCCESS;
}

extern "C" vx_result_t __real_vx_buffer_create(vx_device_h device, uint64_t bytes,
                                              uint32_t flags, vx_buffer_h* out) {
  ++native.creates;
  native.last_device = device;
  native.last_bytes = bytes;
  native.last_flags = flags;
  native.last_out = out;
  if (is("create_throw")) {
    throw 1;
  }
  if (is("create_failed")) {
    return VX_ERR_OUT_OF_DEVICE_MEMORY;
  }
  if (out) {
    if (is("create_null_handle")) {
      *out = nullptr;
    } else if (is("create_duplicate")) {
      *out = &native.buffers[0];
    } else {
      check(native.creates <= native.buffers.size(), "fake native allocation bound exceeded");
      auto& slot = native.buffers[native.creates - 1];
      slot = {true, bytes};
      ++native.live;
      native.used += bytes;
      *out = &slot;
    }
  }
  return VX_SUCCESS;
}

extern "C" vx_result_t __real_vx_buffer_release(vx_buffer_h buffer) {
  ++native.frees;
  native.last_buffer = buffer;
  if (is("buffer_throw")) {
    throw 1;
  }
  if (is("buffer_failed")) {
    return VX_ERR_DEVICE_LOST;
  }
  for (auto& slot : native.buffers) {
    if (buffer == &slot && slot.live) {
      --native.live;
      native.used -= slot.bytes;
      slot.live = false;
      return VX_SUCCESS;
    }
  }
  return VX_ERR_INVALID_HANDLE;
}

extern "C" vx_result_t vx_device_memory_info(vx_device_h, uint64_t* free, uint64_t* used) {
  ++native.memory;
  if (is("query_memory_throw")) {
    throw 1;
  }
  if (is("query_memory_failed")) {
    return VX_ERR_DEVICE_LOST;
  }
  *free = 1048576 - native.used;
  *used = native.used;
  return VX_SUCCESS;
}

extern "C" vx_result_t vx_device_query(vx_device_h, uint32_t id, uint64_t* value) {
  ++native.capabilities;
  for (size_t index = 0; index != std::size(p06::kCapabilities); ++index) {
    if (id == p06::kCapabilities[index].id) {
      ++native.capability_queries[index];
      if (index == 0 && is("query_capability_throw")) {
        throw 1;
      }
      if (index == 0 && is("query_capability_failed")) {
        return VX_ERR_DEVICE_LOST;
      }
      *value = id == VX_CAPS_ISA_FLAGS ? isa_flags() : 1;
      return VX_SUCCESS;
    }
  }
  check(false, "unexpected capability query");
  return VX_ERR_INVALID_INFO;
}

extern "C" vx_result_t vx_device_mpm_query(vx_device_h, uint32_t mpm_class,
                                           uint32_t csr, uint32_t core_id, uint64_t* value) {
  ++native.counters;
  for (size_t index = 0; index != std::size(p06::kCounters); ++index) {
    const auto& row = p06::kCounters[index];
    if (row.mpm_class == mpm_class && row.csr == csr && row.core_id == core_id) {
      check(row.required_isa == 0 || (isa_flags() & row.required_isa) == row.required_isa,
          "unavailable counter was queried");
      ++native.counter_queries[index];
      if (index == 0 && is("query_counter_throw")) {
        throw 1;
      }
      if (index == 0 && is("query_counter_failed")) {
        return VX_ERR_DEVICE_LOST;
      }
      *value = native.counter_queries[index];
      return VX_SUCCESS;
    }
  }
  check(false, "unexpected counter query");
  return VX_ERR_INVALID_INFO;
}

extern "C" vx_result_t vx_buffer_address(vx_buffer_h, uint64_t* value) {
  ++native.addresses;
  *value = 64;
  return VX_SUCCESS;
}

int main(int argc, char** argv) {
  check(argc == 2, "exactly one scenario is required");
  const bool resident = std::strcmp(argv[1], "resident") == 0;
  const bool valid = resident || std::strcmp(argv[1], "default") == 0;
  if (valid) {
    success(resident);
  } else {
    rejected(argv[1]);
  }
  std::printf("{\"scenario\":\"%s\",\"counts\":", argv[1]);
  observed::print_counts(observed::counts());
  std::printf(",\"native\":{\"opens\":%" PRIu64 ",\"releases\":%" PRIu64
      ",\"creates\":%" PRIu64 ",\"frees\":%" PRIu64 ",\"memory_queries\":%" PRIu64
      ",\"capability_queries\":%" PRIu64 ",\"counter_queries\":%" PRIu64
      ",\"address_queries\":%" PRIu64 "},\"passed\":true}\n",
      native.opens, native.releases, native.creates, native.frees,
      native.memory, native.capabilities, native.counters, native.addresses);
  return 0;
}
