// SPDX-License-Identifier: Apache-2.0
// HOST-ONLY fault-injection DSO. This is not an accelerator or a numerical oracle.
// Build only through ci/project/p05_test_runtime.py, never production setup.py.
//
// The 20 vx_* entry points exercise unchanged managed owners. Writes retain the
// caller's address until a wait; launches copy their 56-byte argument block.
// Generic launches return the synthetic words 0x3f800000 + element index.
// A named P04 case applies to the NEXT device successfully opened. Its three
// responses are immutable fixture words, emitted only after the actual uploaded
// inputs, poison and launch dimensions pass the frozen stage contract.
//
// Test control ABI (all return 0 on success unless documented otherwise):
//   int p05_test_reset();                 // refuses while any resource is live
//   int p05_test_fail(name, occurrence, code); // relative future call, code -1=default
//   int p05_test_clear_failures();        // keeps counters and live resources
//   int p05_test_timeout(budget);         // incomplete waits only; finite budget
//   int p05_test_async_failure(ordinal, code); // per queue event 1..5, 0=disabled
//   int p05_test_select_case(name);       // next owner; empty string=generic
//   int p05_test_bad_address(mode);       // 0=normal,1=unaligned,2=alias,3=overflow
//   int p05_test_threads(count);          // simulated device capability
//   int p05_test_corrupt_response(stage, word, xor_bits); // -1 disables
//   int64_t p05_test_counter(name);       // -1 for unknown; calls:<name> supported
//   int64_t p05_test_owner_counter(id, name); // historical owner resource counts
//   const char* p05_test_counters_json(); // borrowed until next call to same getter
//   const char* p05_test_captures_json(); // actual transfers/args/output as hex
// First-open injection without preloading the DSO: set the TEST-ONLY environment
// P05_TEST_INITIAL_FAILURE=name:occurrence:code before starting a fresh process.
// Invalid environment syntax fails the first device open with INVALID_VALUE.

#include "vortex2.h"
#include "ai_matmul_args.h"
#include "p04_fixtures.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <new>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#define TEST_EXPORT __attribute__((visibility("default")))

namespace {
struct Device {
  uint64_t id = 0;
  const p04::Fixture* fixture = nullptr;
  size_t stage = 0;
};
struct Buffer {
  Device* device;
  std::vector<uint8_t> bytes;
  uint64_t address;
  uint32_t flags;
  vx_queue_h queue = nullptr;
};
struct OwnerCounts {
  int64_t devices = 0, modules = 0, kernels = 0, queues = 0;
  int64_t buffers = 0, events = 0, bytes = 0;
};
struct Capture {
  uint64_t owner = 0, queue = 0;
  int64_t stage = -1;
  std::string fixture;
  std::vector<uint8_t> a, b, poison, args, output;
  std::array<uint32_t, 3> grid{}, block{}, cluster{};
  uint32_t m = 0, n = 0, k = 0, dtype = 0, lmem = 0;
  bool launched = false, inputs_validated = false;
};
struct Failure { uint64_t at; vx_result_t code; };
struct State {
  std::set<Device*> devices;
  std::set<Buffer*> buffers;
  std::set<vx_module_h> modules;
  std::set<vx_kernel_h> kernels;
  std::set<vx_queue_h> queues;
  std::set<vx_event_h> events;
  std::map<uint64_t, OwnerCounts> owners;
  std::map<std::string, uint64_t> calls;
  std::map<std::string, Failure> failures;
  std::vector<Capture> captures;
  std::vector<uint8_t> last_module;
  const p04::Fixture* next_case = nullptr;
  uint64_t next_owner = 1, next_queue = 1, next_address = 0x100000;
  uint64_t timeout_budget = 0, profile_clock = 100;
  uint64_t writes_observed = 0, reads_observed = 0, launches_observed = 0;
  uint64_t profiled_queues = 0, default_queues = 0, fixture_inputs_checked = 0;
  uint64_t input_copy_mismatches = 0, response_corruptions = 0;
  uint64_t contract_errors = 0, premature = 0, last_timeout_ns = 0;
  uint64_t max_live_devices = 0;
  unsigned async_ordinal = 0, bad_address = 0, threads = 4;
  vx_result_t async_code = VX_ERR_DEVICE_LOST;
  int corrupt_stage = -1;
  uint64_t corrupt_word = 0;
  uint32_t corrupt_xor = 0;
  bool initialized = false, invalid_initial_failure = false;
  std::string counters_json, captures_json;
} state;

std::string canonical(const char* name) {
  if (name == nullptr) return {};
  std::string value(name);
  if (value.compare(0, 3, "vx_") == 0) value.erase(0, 3);
  if (value == "device_query") return "query";
  if (value == "device_memory_info") return "memory_info";
  if (value == "module_load_bytes") return "module_load";
  if (value == "module_get_kernel") return "get_kernel";
  if (value == "event_wait_value") return "event_wait";
  if (value == "event_get_value") return "event_value";
  if (value == "event_get_profiling") return "profiling";
  return value;
}

int default_error(const std::string& name) {
  if (name == "device_open" || name == "query" || name == "memory_info"
      || name == "buffer_address" || name == "event_wait" || name == "event_value"
      || name == "work") return VX_ERR_DEVICE_LOST;
  if (name == "module_load" || name == "buffer_create") return VX_ERR_OUT_OF_DEVICE_MEMORY;
  if (name == "get_kernel" || name == "profiling") return VX_ERR_NOT_SUPPORTED;
  if (name == "queue_create" || name == "enqueue" || name == "enqueue_write"
      || name == "enqueue_launch" || name == "enqueue_read") return VX_ERR_OUT_OF_HOST_MEMORY;
  if (name == "device_release" || name == "module_release" || name == "kernel_release"
      || name == "queue_release" || name == "buffer_release" || name == "event_release"
      || name == "cleanup") return VX_ERR_INTERNAL;
  return -1;
}

bool valid_code(int code) { return code >= VX_ERR_INVALID_HANDLE && code <= VX_ERR_INTERNAL; }

vx_result_t call(const char* name) {
  const auto count = ++state.calls[name];
  const auto found = state.failures.find(name);
  if (found != state.failures.end() && found->second.at == count) return found->second.code;
  return VX_SUCCESS;
}

vx_result_t cleanup(const char* name) {
  const auto named = call(name);
  const auto any = call("cleanup");
  return named == VX_SUCCESS ? any : named;
}

bool require(bool condition) {
  if (!condition) ++state.contract_errors;
  return condition;
}

template <class Function> vx_result_t guarded(Function&& function) noexcept {
  try { return function(); }
  catch (const std::bad_alloc&) { return VX_ERR_OUT_OF_HOST_MEMORY; }
  catch (...) { ++state.contract_errors; return VX_ERR_INTERNAL; }
}

void initialize() {
  if (state.initialized) return;
  state.initialized = true;
  const char* value = std::getenv("P05_TEST_INITIAL_FAILURE");
  if (!value || !*value) return;
  const std::string text(value);
  const auto first = text.find(':');
  const auto second = first == std::string::npos ? first : text.find(':', first + 1);
  if (first == std::string::npos || second == std::string::npos) {
    state.invalid_initial_failure = true;
    return;
  }
  const auto name = canonical(text.substr(0, first).c_str());
  const auto count_text = text.substr(first + 1, second - first - 1);
  const auto code_text = text.substr(second + 1);
  char *count_end = nullptr, *code_end = nullptr;
  errno = 0;
  const auto count = std::strtoull(count_text.c_str(), &count_end, 10);
  const auto code = std::strtol(code_text.c_str(), &code_end, 10);
  if (errno || count_text.empty() || count_text[0] == '-' || !count_end || *count_end
      || code_text.empty() || !code_end || *code_end || !count || default_error(name) < 0
      || code < 1 || code > VX_ERR_INTERNAL) {
    state.invalid_initial_failure = true;
    return;
  }
  state.failures[name] = {count, static_cast<vx_result_t>(code)};
}

OwnerCounts& owner(Device* device) { return state.owners.at(device->id); }
bool live(Device* device) { return state.devices.count(device) != 0; }
bool live(Buffer* buffer) { return state.buffers.count(buffer) != 0; }

uint64_t word64(const std::vector<uint8_t>& bytes, size_t offset) {
  return vortex::ai::argument_detail::read64(bytes.data() + offset);
}
uint32_t word32(const std::vector<uint8_t>& bytes, size_t offset) {
  return vortex::ai::argument_detail::read32(bytes.data() + offset);
}
void put32(uint8_t* bytes, uint32_t word) {
  for (unsigned i = 0; i != 4; ++i) bytes[i] = static_cast<uint8_t>(word >> (i * 8));
}
std::vector<uint8_t> serialize(const uint32_t* words, size_t count) {
  std::vector<uint8_t> bytes(count * 4);
  for (size_t i = 0; i != count; ++i) put32(bytes.data() + 4 * i, words[i]);
  return bytes;
}
std::string hex(const std::vector<uint8_t>& bytes) {
  constexpr char digits[] = "0123456789abcdef";
  std::string result(bytes.size() * 2, '0');
  for (size_t i = 0; i != bytes.size(); ++i) {
    result[2 * i] = digits[bytes[i] >> 4];
    result[2 * i + 1] = digits[bytes[i] & 15];
  }
  return result;
}
void counts_json(std::ostream& out, const OwnerCounts& counts) {
  out << "{\"devices\":" << counts.devices << ",\"modules\":" << counts.modules
      << ",\"kernels\":" << counts.kernels << ",\"queues\":" << counts.queues
      << ",\"buffers\":" << counts.buffers << ",\"events\":" << counts.events
      << ",\"bytes\":" << counts.bytes << '}';
}
int64_t count_value(const OwnerCounts& counts, const std::string& name) {
  if (name == "devices") return counts.devices;
  if (name == "modules") return counts.modules;
  if (name == "kernels") return counts.kernels;
  if (name == "queues") return counts.queues;
  if (name == "buffers") return counts.buffers;
  if (name == "events") return counts.events;
  if (name == "bytes") return counts.bytes;
  return -1;
}
OwnerCounts totals() {
  OwnerCounts total;
  for (const auto& entry : state.owners) {
    const auto& counts = entry.second;
    total.devices += counts.devices; total.modules += counts.modules;
    total.kernels += counts.kernels; total.queues += counts.queues;
    total.buffers += counts.buffers; total.events += counts.events;
    total.bytes += counts.bytes;
  }
  return total;
}
} // namespace

struct vx_module { Device* device; std::vector<uint8_t> image; };
struct vx_kernel { vx_module_h module; };
struct vx_queue {
  Device* device;
  size_t capture;
  bool profiling;
  std::vector<vx_event_h> events;
  size_t write_count = 0;
};
struct vx_event {
  vx_queue_h queue;
  int refs = 2;
  bool done = false;
  vx_result_t result = VX_SUCCESS;
  vx_profile_info_t profile{};
  std::function<vx_result_t()> work;
};

namespace {
void drop(vx_event_h event) {
  if (--event->refs == 0) {
    --owner(event->queue->device).events;
    state.events.erase(event);
    delete event;
  }
}

vx_result_t enqueue(vx_queue_h queue, uint32_t count, const vx_event_h* waits,
                    vx_event_h* out, std::function<vx_result_t()> work) {
  if (!require(state.queues.count(queue) && out
      && ((queue->events.empty() && count == 0)
          || (count == 1 && waits && !queue->events.empty()
              && waits[0] == queue->events.back())))) return VX_ERR_INVALID_VALUE;
  const auto error = call("enqueue");
  if (error != VX_SUCCESS) return error;
  auto event = std::make_unique<vx_event>();
  event->queue = queue;
  event->profile.queued_ns = ++state.profile_clock;
  event->work = std::move(work);
  queue->events.reserve(queue->events.size() + 1);
  state.events.insert(event.get());
  queue->events.push_back(event.get());
  ++owner(queue->device).events;
  *out = event.release();
  return VX_SUCCESS;
}

void drain(vx_queue_h queue) {
  vx_result_t error = VX_SUCCESS;
  for (size_t i = 0; i != queue->events.size(); ++i) {
    auto* event = queue->events[i];
    if (!event->done) {
      if (error == VX_SUCCESS && state.async_ordinal == i + 1) error = state.async_code;
      if (error == VX_SUCCESS) error = call("work");
      if (error == VX_SUCCESS) error = guarded(event->work);
      event->result = error;
      event->done = true;
      state.profile_clock += 10;
      event->profile.submit_ns = state.profile_clock;
      event->profile.start_ns = state.profile_clock + (error == VX_SUCCESS ? 2 : 0);
      event->profile.end_ns = state.profile_clock + (error == VX_SUCCESS ? 8 : 0);
    } else if (event->result != VX_SUCCESS) {
      error = event->result;
    }
  }
}

Buffer* by_address(Device* device, uint64_t address) {
  for (auto* buffer : state.buffers) {
    if (buffer->device == device && buffer->address == address) return buffer;
  }
  return nullptr;
}

vx_result_t launch(vx_queue_h queue) {
  auto& capture = state.captures.at(queue->capture);
  const auto& args = capture.args;
  auto* a = by_address(queue->device, word64(args, 32));
  auto* b = by_address(queue->device, word64(args, 40));
  auto* d = by_address(queue->device, word64(args, 48));
  if (!require(a && b && d && a->bytes.size() == uint64_t(capture.m) * capture.k * 2
      && b->bytes.size() == uint64_t(capture.k) * capture.n * 2
      && d->bytes.size() == uint64_t(capture.m) * capture.n * 4
      && a->flags == VX_MEM_READ && b->flags == VX_MEM_READ && d->flags == VX_MEM_WRITE
      && capture.a == a->bytes && capture.b == b->bytes && capture.poison == d->bytes
      && !capture.poison.empty())) return VX_ERR_INVALID_VALUE;
  const auto poison = word32(capture.poison, 0);
  for (size_t i = 0; i != capture.poison.size(); i += 4) {
    if (!require(word32(capture.poison, i) == poison)) return VX_ERR_INVALID_VALUE;
  }
  const auto* fixture = queue->device->fixture;
  if (fixture) {
    const size_t stage = static_cast<size_t>(capture.stage);
    if (!require(stage < 3 && capture.dtype == (std::string(fixture->format) == "fp16" ? 1u : 2u)
        && capture.m == (stage == 0 ? 16u : 8u) && capture.n == (stage == 0 ? 8u : 4u)
        && capture.k == (stage == 0 ? 16u : 8u))) return VX_ERR_INVALID_VALUE;
    const auto expected_a = stage == 0
        ? serialize(fixture->inputs.input_words.data(), fixture->inputs.input_words.size())
        : serialize(fixture->expected.bridge_words.data() + (stage - 1) * 32, 32);
    const auto expected_b = stage == 0
        ? serialize(fixture->inputs.w1_words.data(), fixture->inputs.w1_words.size())
        : serialize(fixture->inputs.w2_words.data(), fixture->inputs.w2_words.size());
    if (!require(a->bytes == expected_a && b->bytes == expected_b)) return VX_ERR_INVALID_VALUE;
    ++state.fixture_inputs_checked;
    capture.inputs_validated = true;
    d->bytes = stage == 0
        ? serialize(fixture->expected.hidden_words.data(), fixture->expected.hidden_words.size())
        : serialize(fixture->expected.output_words.data() + (stage - 1) * 32, 32);
  } else {
    for (size_t i = 0; i != d->bytes.size() / 4; ++i) put32(d->bytes.data() + 4 * i, 0x3f800000u + i);
  }
  if (state.corrupt_stage >= 0 && capture.stage == state.corrupt_stage
      && state.corrupt_word < d->bytes.size() / 4) {
    const auto offset = static_cast<size_t>(state.corrupt_word) * 4;
    put32(d->bytes.data() + offset, word32(d->bytes, offset) ^ state.corrupt_xor);
    ++state.response_corruptions;
  }
  capture.output = d->bytes;
  capture.launched = true;
  ++state.launches_observed;
  return VX_SUCCESS;
}
} // namespace

extern "C" {
TEST_EXPORT vx_result_t vx_device_open(uint32_t index, vx_device_h* out) {
  return guarded([&]() -> vx_result_t {
    initialize();
    if (!require(index == 0 && out)) return VX_ERR_INVALID_VALUE;
    *out = nullptr;
    if (state.invalid_initial_failure) return VX_ERR_INVALID_VALUE;
    const auto error = call("device_open");
    if (error != VX_SUCCESS) return error;
    auto device = std::make_unique<Device>();
    device->id = state.next_owner++;
    device->fixture = state.next_case;
    state.owners[device->id] = OwnerCounts{};
    state.devices.insert(device.get());
    ++owner(device.get()).devices;
    state.max_live_devices = std::max<uint64_t>(state.max_live_devices, state.devices.size());
    state.next_case = nullptr;
    *out = device.release();
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_device_release(vx_device_h handle) {
  return guarded([&]() -> vx_result_t {
    auto* device = static_cast<Device*>(handle);
    if (!require(live(device))) return VX_ERR_INVALID_HANDLE;
    auto& counts = owner(device);
    if (!require(counts.modules == 0 && counts.kernels == 0 && counts.queues == 0
                 && counts.events == 0 && counts.buffers == 0)) return VX_ERR_INVALID_HANDLE;
    --counts.devices;
    state.devices.erase(device);
    delete device;
    return cleanup("device_release");
  });
}

TEST_EXPORT vx_result_t vx_device_query(vx_device_h handle, uint32_t id, uint64_t* out) {
  return guarded([&]() -> vx_result_t {
    if (!require(live(static_cast<Device*>(handle)) && out)) return VX_ERR_INVALID_HANDLE;
    const auto error = call("query");
    if (error != VX_SUCCESS) return error;
    switch (id) {
      case VX_CAPS_NUM_THREADS: *out = state.threads; break;
      case VX_CAPS_NUM_WARPS: *out = 4; break;
      case VX_CAPS_NUM_CORES: case VX_CAPS_NUM_CLUSTERS: case VX_CAPS_ISSUE_WIDTH: *out = 1; break;
      case VX_CAPS_LOCAL_MEM_SIZE: *out = 16384; break;
      case VX_CAPS_ISA_FLAGS: *out = (2ull << 30) | VX_ISA_EXT_TCU | VX_ISA_EXT_LMEM; break;
      default: return VX_ERR_INVALID_VALUE;
    }
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_device_memory_info(vx_device_h handle, uint64_t* free_bytes, uint64_t* used_bytes) {
  return guarded([&]() -> vx_result_t {
    auto* device = static_cast<Device*>(handle);
    if (!require(live(device) && free_bytes && used_bytes)) return VX_ERR_INVALID_HANDLE;
    const auto error = call("memory_info");
    if (error != VX_SUCCESS) return error;
    *used_bytes = static_cast<uint64_t>(owner(device).bytes);
    *free_bytes = (1ull << 20) - *used_bytes;
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_module_load_bytes(vx_device_h handle, const void* bytes, size_t size, vx_module_h* out) {
  return guarded([&]() -> vx_result_t {
    auto* device = static_cast<Device*>(handle);
    if (!require(live(device) && bytes && size >= 16 && out)) return VX_ERR_INVALID_VALUE;
    const auto error = call("module_load");
    if (error != VX_SUCCESS) return error;
    const auto* first = static_cast<const uint8_t*>(bytes);
    auto module = std::make_unique<vx_module>();
    module->device = device;
    module->image.assign(first, first + size);
    state.last_module = module->image;
    state.modules.insert(module.get());
    ++owner(device).modules;
    *out = module.release();
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_module_release(vx_module_h module) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.modules.count(module))) return VX_ERR_INVALID_HANDLE;
    auto& counts = owner(module->device);
    if (!require(counts.kernels == 0 && counts.queues == 0)) return VX_ERR_INVALID_HANDLE;
    --counts.modules;
    state.modules.erase(module);
    delete module;
    return cleanup("module_release");
  });
}

TEST_EXPORT vx_result_t vx_module_get_kernel(vx_module_h module, const char* name, vx_kernel_h* out) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.modules.count(module) && name && std::strcmp(name, "main") == 0 && out)) return VX_ERR_INVALID_VALUE;
    const auto error = call("get_kernel");
    if (error != VX_SUCCESS) return error;
    auto kernel = std::make_unique<vx_kernel>();
    kernel->module = module;
    state.kernels.insert(kernel.get());
    ++owner(module->device).kernels;
    *out = kernel.release();
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_kernel_release(vx_kernel_h kernel) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.kernels.count(kernel))) return VX_ERR_INVALID_HANDLE;
    auto& counts = owner(kernel->module->device);
    if (!require(counts.queues == 0)) return VX_ERR_INVALID_HANDLE;
    --counts.kernels;
    state.kernels.erase(kernel);
    delete kernel;
    return cleanup("kernel_release");
  });
}

TEST_EXPORT vx_result_t vx_queue_create(vx_device_h handle, const vx_queue_info_t* info, vx_queue_h* out) {
  return guarded([&]() -> vx_result_t {
    auto* device = static_cast<Device*>(handle);
    if (!require(live(device) && out && (!info || (info->struct_size == sizeof(*info)
        && info->next == nullptr && info->priority == VX_QUEUE_PRIORITY_NORMAL
        && info->flags == VX_QUEUE_PROFILING_ENABLE)))) return VX_ERR_INVALID_VALUE;
    const auto error = call("queue_create");
    if (error != VX_SUCCESS) return error;
    auto queue = std::make_unique<vx_queue>();
    queue->device = device; queue->profiling = info != nullptr;
    Capture capture;
    capture.owner = device->id; capture.queue = state.next_queue++;
    if (device->fixture) { capture.stage = device->stage++; capture.fixture = device->fixture->id; }
    queue->capture = state.captures.size();
    state.captures.push_back(std::move(capture));
    state.queues.insert(queue.get());
    ++owner(device).queues;
    if (info) ++state.profiled_queues; else ++state.default_queues;
    *out = queue.release();
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_queue_release(vx_queue_h queue) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.queues.count(queue))) return VX_ERR_INVALID_HANDLE;
    for (auto* event : queue->events) {
      if (!event->done) { ++state.premature; return VX_ERR_INVALID_HANDLE; }
    }
    for (auto* event : queue->events) drop(event);
    --owner(queue->device).queues;
    state.queues.erase(queue);
    delete queue;
    return cleanup("queue_release");
  });
}

TEST_EXPORT vx_result_t vx_buffer_create(vx_device_h handle, uint64_t size, uint32_t flags, vx_buffer_h* out) {
  return guarded([&]() -> vx_result_t {
    auto* device = static_cast<Device*>(handle);
    if (!require(live(device) && out && size && size <= (1ull << 20)
        && (flags == VX_MEM_READ || flags == VX_MEM_WRITE))) return VX_ERR_INVALID_VALUE;
    const auto error = call("buffer_create");
    if (error != VX_SUCCESS) return error;
    auto buffer = std::make_unique<Buffer>(Buffer{device, std::vector<uint8_t>(size), state.next_address, flags});
    state.next_address += ((size + 4095) / 4096) * 4096;
    state.buffers.insert(buffer.get());
    ++owner(device).buffers; owner(device).bytes += size;
    *out = buffer.release();
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_buffer_address(vx_buffer_h handle, uint64_t* out) {
  return guarded([&]() -> vx_result_t {
    auto* buffer = static_cast<Buffer*>(handle);
    if (!require(live(buffer) && out)) return VX_ERR_INVALID_HANDLE;
    const auto error = call("buffer_address");
    if (error != VX_SUCCESS) return error;
    *out = state.bad_address == 2 ? 0x100000 : state.bad_address == 3 ? UINT64_MAX - 3 : buffer->address;
    if (state.bad_address == 1) ++*out;
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_buffer_release(vx_buffer_h handle) {
  return guarded([&]() -> vx_result_t {
    auto* buffer = static_cast<Buffer*>(handle);
    if (!require(live(buffer))) return VX_ERR_INVALID_HANDLE;
    if (buffer->queue && state.queues.count(buffer->queue)) {
        for (auto* event : buffer->queue->events) {
          if (!event->done) { ++state.premature; return VX_ERR_INVALID_HANDLE; }
        }
    }
    --owner(buffer->device).buffers; owner(buffer->device).bytes -= buffer->bytes.size();
    state.buffers.erase(buffer);
    delete buffer;
    return cleanup("buffer_release");
  });
}

TEST_EXPORT vx_result_t vx_enqueue_write(vx_queue_h queue, vx_buffer_h handle, uint64_t offset,
    const void* source, uint64_t size, uint32_t count, const vx_event_h* waits, vx_event_h* out) {
  return guarded([&]() -> vx_result_t {
    auto* buffer = static_cast<Buffer*>(handle);
    if (!require(state.queues.count(queue) && live(buffer) && buffer->device == queue->device
        && source && offset == 0 && size == buffer->bytes.size() && queue->write_count < 3)) return VX_ERR_INVALID_VALUE;
    const auto error = call("enqueue_write");
    if (error != VX_SUCCESS) return error;
    const auto* first = static_cast<const uint8_t*>(source);
    const std::vector<uint8_t> submitted(first, first + size);
    const auto ordinal = queue->write_count;
    const auto result = enqueue(queue, count, waits, out, [queue, buffer, first, size, submitted, ordinal] {
      if (!require(live(buffer))) return VX_ERR_INVALID_HANDLE;
      if (!std::equal(submitted.begin(), submitted.end(), first)) ++state.input_copy_mismatches;
      std::memcpy(buffer->bytes.data(), first, size);
      auto& capture = state.captures.at(queue->capture);
      auto& destination = ordinal == 0 ? capture.a : ordinal == 1 ? capture.b : capture.poison;
      destination = buffer->bytes;
      ++state.writes_observed;
      return VX_SUCCESS;
    });
    if (result == VX_SUCCESS) { ++queue->write_count; buffer->queue = queue; }
    return result;
  });
}

TEST_EXPORT vx_result_t vx_enqueue_launch(vx_queue_h queue, const vx_launch_info_t* info,
    uint32_t count, const vx_event_h* waits, vx_event_h* out) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.queues.count(queue) && info && info->struct_size == sizeof(*info)
        && info->next == nullptr && state.kernels.count(info->kernel)
        && info->kernel->module->device == queue->device && info->args_host
        && info->args_size == 56 && info->ndim == 2 && queue->write_count == 3)) return VX_ERR_INVALID_VALUE;
    const auto error = call("enqueue_launch");
    if (error != VX_SUCCESS) return error;
    auto& capture = state.captures.at(queue->capture);
    const auto* first = static_cast<const uint8_t*>(info->args_host);
    capture.args.assign(first, first + info->args_size);
    capture.dtype = word32(capture.args, 8); capture.m = word32(capture.args, 16);
    capture.n = word32(capture.args, 20); capture.k = word32(capture.args, 24);
    std::copy_n(info->grid_dim, 3, capture.grid.begin());
    std::copy_n(info->block_dim, 3, capture.block.begin());
    std::copy_n(info->cluster_dim, 3, capture.cluster.begin());
    capture.lmem = info->lmem_size;
    vortex::ai::MatmulArguments decoded;
    if (!require(vortex::ai::decode_matmul_arguments(capture.args.data(), capture.args.size(), capture.dtype, &decoded)
        && capture.grid == std::array<uint32_t, 3>{capture.n / 4, capture.m / 8, 1}
        && capture.block == std::array<uint32_t, 3>{4, 1, 1}
        && capture.cluster == std::array<uint32_t, 3>{1, 1, 1} && capture.lmem == 0)) return VX_ERR_INVALID_VALUE;
    return enqueue(queue, count, waits, out, [queue] { return launch(queue); });
  });
}

TEST_EXPORT vx_result_t vx_enqueue_read(vx_queue_h queue, void* destination, vx_buffer_h handle,
    uint64_t offset, uint64_t size, uint32_t count, const vx_event_h* waits, vx_event_h* out) {
  return guarded([&]() -> vx_result_t {
    auto* buffer = static_cast<Buffer*>(handle);
    if (!require(state.queues.count(queue) && live(buffer) && buffer->device == queue->device
        && destination && offset == 0 && size == buffer->bytes.size())) return VX_ERR_INVALID_VALUE;
    const auto error = call("enqueue_read");
    if (error != VX_SUCCESS) return error;
    return enqueue(queue, count, waits, out, [buffer, destination, size] {
      if (!require(live(buffer))) return VX_ERR_INVALID_HANDLE;
      std::memcpy(destination, buffer->bytes.data(), size);
      ++state.reads_observed;
      return VX_SUCCESS;
    });
  });
}

TEST_EXPORT vx_result_t vx_event_wait_value(vx_event_h event, uint64_t value, uint64_t timeout_ns) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.events.count(event) && value == 1)) return VX_ERR_INVALID_VALUE;
    state.last_timeout_ns = timeout_ns;
    const auto error = call("event_wait");
    if (error != VX_SUCCESS) return error;
    if (!event->done && state.timeout_budget) { --state.timeout_budget; return VX_ERR_TIMEOUT; }
    drain(event->queue);
    return event->result;
  });
}

TEST_EXPORT vx_result_t vx_event_get_value(vx_event_h event, uint64_t* out) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.events.count(event) && out)) return VX_ERR_INVALID_HANDLE;
    const auto error = call("event_value");
    if (error != VX_SUCCESS) return error;
    *out = event->done ? 1 : 0;
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_event_get_profiling(vx_event_h event, vx_profile_info_t* out) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.events.count(event) && out && event->done && event->queue->profiling)) return VX_ERR_INVALID_VALUE;
    const auto error = call("profiling");
    if (error != VX_SUCCESS) { *out = {99, 98, 97, 96}; return error; }
    *out = event->profile;
    return VX_SUCCESS;
  });
}

TEST_EXPORT vx_result_t vx_event_release(vx_event_h event) {
  return guarded([&]() -> vx_result_t {
    if (!require(state.events.count(event) && event->refs == 2)) return VX_ERR_INVALID_HANDLE;
    drop(event);
    return cleanup("event_release");
  });
}

TEST_EXPORT int p05_test_reset() {
  return guarded([]() -> vx_result_t {
    if (!state.devices.empty() || !state.modules.empty() || !state.kernels.empty()
        || !state.queues.empty() || !state.events.empty() || !state.buffers.empty()) return VX_ERR_INVALID_VALUE;
    state = State{};
    // Explicit reset consumes initialization; an inherited environment injection
    // must not unexpectedly arm itself again in later cases in the same process.
    state.initialized = true;
    return VX_SUCCESS;
  });
}

TEST_EXPORT int p05_test_fail(const char* name, uint64_t occurrence, int code) {
  return guarded([&]() -> vx_result_t {
    initialize();
    const auto key = canonical(name);
    const int fallback = default_error(key);
    if (code == -1) code = fallback;
    if (fallback < 0 || !occurrence || !valid_code(code)
        || occurrence > UINT64_MAX - state.calls[key]) return VX_ERR_INVALID_VALUE;
    state.failures[key] = {state.calls[key] + occurrence, static_cast<vx_result_t>(code)};
    return VX_SUCCESS;
  });
}
TEST_EXPORT int p05_test_clear_failures() {
  state.failures.clear(); state.timeout_budget = 0; state.async_ordinal = 0;
  state.bad_address = 0; state.threads = 4; state.corrupt_stage = -1;
  state.invalid_initial_failure = false;
  return VX_SUCCESS;
}
TEST_EXPORT int p05_test_timeout(uint64_t budget) { state.timeout_budget = budget; return VX_SUCCESS; }
TEST_EXPORT int p05_test_async_failure(unsigned ordinal, int code) {
  if (ordinal > 5 || !valid_code(code)) return VX_ERR_INVALID_VALUE;
  state.async_ordinal = ordinal; state.async_code = static_cast<vx_result_t>(code); return VX_SUCCESS;
}
TEST_EXPORT int p05_test_select_case(const char* name) {
  if (!name) return VX_ERR_INVALID_VALUE;
  if (!*name) { state.next_case = nullptr; return VX_SUCCESS; }
  for (const auto& fixture : p04::kFixtures) {
    if (std::strcmp(fixture.id, name) == 0) { state.next_case = &fixture; return VX_SUCCESS; }
  }
  return VX_ERR_INVALID_VALUE;
}
TEST_EXPORT int p05_test_bad_address(unsigned mode) {
  if (mode > 3) return VX_ERR_INVALID_VALUE;
  state.bad_address = mode; return VX_SUCCESS;
}
TEST_EXPORT int p05_test_threads(unsigned count) { state.threads = count; return VX_SUCCESS; }
TEST_EXPORT int p05_test_corrupt_response(int stage, uint64_t word, uint32_t xor_bits) {
  if (stage < -1 || stage > 2) return VX_ERR_INVALID_VALUE;
  state.corrupt_stage = stage; state.corrupt_word = word; state.corrupt_xor = xor_bits; return VX_SUCCESS;
}
TEST_EXPORT int64_t p05_test_counter(const char* name) {
  try {
    if (!name) return -1;
    const std::string key(name);
    const auto resource = count_value(totals(), key);
    if (resource >= 0) return resource;
    if (key.compare(0, 6, "calls:") == 0) {
      const auto found = state.calls.find(canonical(key.c_str() + 6));
      return found == state.calls.end() ? 0 : static_cast<int64_t>(found->second);
    }
    if (key == "last_owner") return state.next_owner - 1;
    if (key == "captures") return state.captures.size();
    if (key == "module_bytes") return state.last_module.size();
#define COUNT(field) if (key == #field) return static_cast<int64_t>(state.field)
    COUNT(writes_observed); COUNT(reads_observed); COUNT(launches_observed);
    COUNT(profiled_queues); COUNT(default_queues); COUNT(fixture_inputs_checked);
    COUNT(input_copy_mismatches); COUNT(response_corruptions); COUNT(contract_errors);
    COUNT(premature); COUNT(timeout_budget); COUNT(last_timeout_ns);
    COUNT(max_live_devices);
#undef COUNT
    return -1;
  } catch (...) { return -1; }
}
TEST_EXPORT int64_t p05_test_owner_counter(uint64_t id, const char* name) {
  try {
    const auto found = state.owners.find(id);
    return found == state.owners.end() || !name ? -1 : count_value(found->second, name);
  } catch (...) { return -1; }
}
TEST_EXPORT const char* p05_test_counters_json() {
  try {
    std::ostringstream out;
    out << "{\"scope\":\"host-only-fault-injection\",\"resources\":";
    counts_json(out, totals());
    out << ",\"owners\":{";
    bool first = true;
    for (const auto& entry : state.owners) {
      if (!first) out << ',';
      first = false; out << '"' << entry.first << "\":"; counts_json(out, entry.second);
    }
    out << "},\"calls\":{"; first = true;
    for (const auto& entry : state.calls) {
      if (!first) out << ',';
      first = false; out << '"' << entry.first << "\":" << entry.second;
    }
    out << "},\"last_owner\":" << state.next_owner - 1
        << ",\"writes_observed\":" << state.writes_observed
        << ",\"reads_observed\":" << state.reads_observed
        << ",\"launches_observed\":" << state.launches_observed
        << ",\"fixture_inputs_checked\":" << state.fixture_inputs_checked
        << ",\"input_copy_mismatches\":" << state.input_copy_mismatches
        << ",\"contract_errors\":" << state.contract_errors
        << ",\"premature\":" << state.premature
        << ",\"max_live_devices\":" << state.max_live_devices
        << ",\"timeout_budget\":" << state.timeout_budget
        << ",\"last_timeout_ns\":" << state.last_timeout_ns << '}';
    state.counters_json = out.str(); return state.counters_json.c_str();
  } catch (...) { return nullptr; }
}
TEST_EXPORT const char* p05_test_captures_json() {
  try {
    std::ostringstream out; out << '[';
    bool first = true;
    for (const auto& capture : state.captures) {
      if (!first) out << ',';
      first = false;
      out << "{\"owner\":" << capture.owner << ",\"queue\":" << capture.queue
          << ",\"stage\":" << capture.stage << ",\"fixture\":\"" << capture.fixture
          << "\",\"m\":" << capture.m << ",\"n\":" << capture.n << ",\"k\":" << capture.k
          << ",\"dtype\":" << capture.dtype << ",\"lmem\":" << capture.lmem;
      const auto dims = [&](const char* name, const std::array<uint32_t, 3>& value) {
        out << ",\"" << name << "\":[" << value[0] << ',' << value[1] << ',' << value[2] << ']';
      };
      dims("grid", capture.grid); dims("block", capture.block); dims("cluster", capture.cluster);
      out << ",\"launched\":" << (capture.launched ? "true" : "false")
          << ",\"inputs_validated\":" << (capture.inputs_validated ? "true" : "false")
          << ",\"args_hex\":\"" << hex(capture.args) << "\",\"a_hex\":\"" << hex(capture.a)
          << "\",\"b_hex\":\"" << hex(capture.b) << "\",\"poison_hex\":\"" << hex(capture.poison)
          << "\",\"output_hex\":\"" << hex(capture.output) << "\"}";
    }
    out << ']'; state.captures_json = out.str(); return state.captures_json.c_str();
  } catch (...) { return nullptr; }
}
} // extern "C"
