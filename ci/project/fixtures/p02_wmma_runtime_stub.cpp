// SPDX-License-Identifier: Apache-2.0
// Replay independently supplied bytes; this stub performs no tensor arithmetic.

#include "common.h"
#include <rvfloats.h>
#include <vortex2.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

struct vx_queue {};
struct vx_module {};
struct vx_kernel {};
struct vx_event {
  const char* kind;
  uint32_t iteration;
  void* destination = nullptr;
  bool waited = false;
};

namespace {

[[noreturn]] void fail(const char* message) {
  std::fprintf(stderr, "P02_STUB_ERROR: %s\n", message);
  std::fflush(nullptr);
  std::_Exit(86);
}

void require(bool condition, const char* message) {
  if (!condition) {
    fail(message);
  }
}

void record(const std::string& message) {
  const char* path = std::getenv("P02_STUB_TRACE");
  require(path != nullptr, "trace path is absent");
  FILE* stream = std::fopen(path, "a");
  require(stream != nullptr, "cannot open trace");
  require(std::fprintf(stream, "%s\n", message.c_str()) > 0, "cannot write trace");
  require(std::fclose(stream) == 0, "cannot close trace");
}

uint32_t word_at(const uint8_t* bytes) {
  return uint32_t(bytes[0]) | (uint32_t(bytes[1]) << 8)
      | (uint32_t(bytes[2]) << 16) | (uint32_t(bytes[3]) << 24);
}

void put_word(uint8_t* bytes, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) {
    bytes[i] = uint8_t(value >> (8 * i));
  }
}

struct Scenario {
  uint32_t m = 0, n = 0, k = 0, repeats = 0;
  std::vector<uint8_t> a, b, expected, poison;
};

struct Buffer {
  bool live = false;
  char role = '?';
  uint64_t address = 0;
  std::vector<uint8_t> data;
  const uint8_t* pending = nullptr;
};

Scenario scenario;
std::array<Buffer, 3> buffers;
std::vector<vx_event_h> events;
vx_queue queue;
vx_module module;
vx_kernel kernel;
bool opened = false, queue_live = false, module_live = false, kernel_live = false;
size_t allocations = 0;
uint32_t launches = 0, reads = 0, waits = 0, poison_writes = 0;

void load_scenario() {
  const char* path = std::getenv("P02_STUB_SCENARIO");
  require(path != nullptr, "scenario path is absent");
  std::ifstream stream(path, std::ios::binary);
  require(stream.good(), "cannot open scenario");
  stream.seekg(0, std::ios::end);
  const auto length = stream.tellg();
  require(length >= 36 && length <= 1024 * 1024, "scenario size is outside the bound");
  stream.seekg(0);
  std::vector<uint8_t> bytes(static_cast<size_t>(length));
  stream.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
  require(stream.good(), "scenario read was incomplete");
  const uint8_t magic[] = {'P', '0', '2', 'W', 'M', 'M', 'A', 1};
  require(std::memcmp(bytes.data(), magic, sizeof(magic)) == 0, "invalid scenario magic");
  scenario.m = word_at(bytes.data() + 8);
  scenario.n = word_at(bytes.data() + 12);
  scenario.k = word_at(bytes.data() + 16);
  const uint32_t a_size = word_at(bytes.data() + 20);
  const uint32_t b_size = word_at(bytes.data() + 24);
  const uint32_t c_size = word_at(bytes.data() + 28);
  scenario.repeats = word_at(bytes.data() + 32);
  require(scenario.m > 0 && scenario.m <= 64 && scenario.m % 8 == 0
          && scenario.n > 0 && scenario.n <= 64 && scenario.n % 4 == 0
          && scenario.k > 0 && scenario.k <= 64 && scenario.k % 8 == 0
          && scenario.repeats > 0 && scenario.repeats <= 4,
          "invalid scenario dimensions or repeat count");
  require(a_size == scenario.m * scenario.k * 2
          && b_size == scenario.k * scenario.n * 2
          && c_size == scenario.m * scenario.n * 4
          && bytes.size() == size_t(36) + a_size + b_size + c_size,
          "scenario byte counts disagree with dimensions");
  auto begin = bytes.begin() + 36;
  scenario.a.assign(begin, begin + a_size);
  begin += a_size;
  scenario.b.assign(begin, begin + b_size);
  begin += b_size;
  scenario.expected.assign(begin, bytes.end());
  scenario.poison = scenario.expected;
  for (size_t i = 0; i < scenario.poison.size(); i += 4) {
    scenario.poison[i] ^= 1;
  }
}

Buffer& checked_buffer(vx_buffer_h handle) {
  for (auto& buffer : buffers) {
    if (handle == &buffer && buffer.live) {
      return buffer;
    }
  }
  fail("invalid or released buffer");
}

vx_event_h new_event(const char* kind, uint32_t iteration) {
  auto event = new vx_event{kind, iteration};
  events.push_back(event);
  return event;
}

void checked_event(vx_event_h event, const char* kind, uint32_t iteration) {
  require(std::find(events.begin(), events.end(), event) != events.end(),
          "invalid or released event");
  require(std::strcmp(event->kind, kind) == 0 && event->iteration == iteration,
          "incorrect event dependency");
}

bool fault(const char* name) {
  const char* selected = std::getenv("P02_STUB_FAULT");
  return selected != nullptr && std::strcmp(selected, name) == 0;
}

size_t fault_index() {
  const char* text = std::getenv("P02_STUB_INDEX");
  if (text == nullptr) {
    return scenario.expected.size() / 4 - 1;
  }
  char* end = nullptr;
  unsigned long value = std::strtoul(text, &end, 10);
  require(*text != '\0' && *end == '\0' && value < scenario.expected.size() / 4,
          "invalid corruption index");
  return value;
}

void consume_upload(Buffer& buffer, const std::vector<uint8_t>& expected,
                    const char* message) {
  require(buffer.pending != nullptr, "launch has no pending upload");
  require(std::memcmp(buffer.pending, expected.data(), expected.size()) == 0, message);
  std::memcpy(buffer.data.data(), buffer.pending, expected.size());
  buffer.pending = nullptr;
}

[[noreturn]] void conversion_called(const char* name) {
  std::fprintf(stderr, "P02_STUB_CPU_CONVERSION: %s\n", name);
  std::fflush(nullptr);
  std::abort();
}

} // namespace

extern "C" {

vx_result_t vx_device_open(uint32_t index, vx_device_h* out) {
  record("device_open");
  require(!opened && index == 0 && out != nullptr, "invalid device open");
  load_scenario();
  opened = true;
  *out = &scenario;
  return VX_SUCCESS;
}

vx_result_t vx_device_query(vx_device_h device, uint32_t cap, uint64_t* value) {
  require(opened && device == &scenario && value != nullptr, "invalid capability query");
  const char* mismatch = std::getenv("P02_STUB_CAP");
  const auto changed = [mismatch](const char* name) {
    return mismatch != nullptr && std::strcmp(mismatch, name) == 0;
  };
  switch (cap) {
  case VX_CAPS_ISA_FLAGS:
    *value = (changed("xlen") ? 1ull : 2ull) << 30;
    if (!changed("tcu")) {
      *value |= VX_ISA_EXT_TCU;
    }
    if (!changed("lmem")) {
      *value |= VX_ISA_EXT_LMEM;
    }
    if (changed("matrix")) {
      *value |= VX_ISA_EXT_LDST_MATRIX;
    }
    break;
  case VX_CAPS_NUM_THREADS: *value = changed("threads") ? 8 : 4; break;
  case VX_CAPS_NUM_WARPS: *value = changed("warps") ? 8 : 4; break;
  case VX_CAPS_NUM_CORES: *value = changed("cores") ? 2 : 1; break;
  case VX_CAPS_NUM_CLUSTERS: *value = changed("clusters") ? 2 : 1; break;
  case VX_CAPS_ISSUE_WIDTH: *value = changed("issue") ? 2 : 1; break;
  default: fail("unexpected capability query");
  }
  record("query:" + std::to_string(cap));
  return VX_SUCCESS;
}

vx_result_t vx_queue_create(vx_device_h device, const vx_queue_info_t* info,
                            vx_queue_h* out) {
  require(device == &scenario && opened && !queue_live && out != nullptr
          && info != nullptr && info->struct_size == sizeof(*info)
          && info->next == nullptr && info->priority == VX_QUEUE_PRIORITY_NORMAL
          && info->flags == 0, "incorrect queue descriptor");
  queue_live = true;
  *out = &queue;
  record("queue_create");
  return VX_SUCCESS;
}

vx_result_t vx_buffer_create(vx_device_h device, uint64_t size, uint32_t flags,
                             vx_buffer_h* out) {
  require(opened && device == &scenario && allocations < 3 && out != nullptr,
          "unexpected buffer allocation");
  const size_t expected_sizes[] = {scenario.a.size(), scenario.b.size(), scenario.expected.size()};
  require(size == expected_sizes[allocations]
          && flags == (allocations == 2 ? VX_MEM_WRITE : VX_MEM_READ),
          "allocation dimensions or access flags differ from the JSON scenario");
  auto& buffer = buffers[allocations];
  buffer.live = true;
  buffer.role = "ABC"[allocations];
  buffer.address = 0x10000ull * (allocations + 1);
  buffer.data.assign(size, 0xcc);
  *out = &buffer;
  ++allocations;
  record(std::string("allocate:") + buffer.role + ":" + std::to_string(size));
  return VX_SUCCESS;
}

vx_result_t vx_buffer_address(vx_buffer_h handle, uint64_t* address) {
  require(address != nullptr, "missing buffer address destination");
  *address = checked_buffer(handle).address;
  return VX_SUCCESS;
}

vx_result_t vx_enqueue_write(vx_queue_h q, vx_buffer_h handle, uint64_t offset,
                             const void* source, uint64_t size, uint32_t nwait,
                             const vx_event_h* waitlist, vx_event_h* out) {
  auto& buffer = checked_buffer(handle);
  require(q == &queue && queue_live && offset == 0 && size == buffer.data.size()
          && source != nullptr && nwait == 0 && waitlist == nullptr
          && buffer.pending == nullptr, "incorrect write descriptor");
  buffer.pending = static_cast<const uint8_t*>(source);
  if (buffer.role == 'C') {
    require(out != nullptr && poison_writes == launches, "missing per-launch poison event");
    require(std::memcmp(source, scenario.poison.data(), scenario.poison.size()) == 0,
            "device poison is not expected XOR one for every output");
    *out = new_event("poison", launches);
    record("poison:" + std::to_string(poison_writes++));
  } else {
    require(launches == 0 && out == nullptr, "unexpected input upload");
    record(std::string("upload:") + buffer.role);
  }
  return VX_SUCCESS;
}

vx_result_t vx_module_load_file(vx_device_h device, const char* path, vx_module_h* out) {
  require(device == &scenario && opened && !module_live && out != nullptr
          && path != nullptr && std::strcmp(path, "kernel.vxbin") == 0,
          "incorrect module load");
  module_live = true;
  *out = &module;
  record("module_load");
  return VX_SUCCESS;
}

vx_result_t vx_module_get_kernel(vx_module_h mod, const char* name, vx_kernel_h* out) {
  require(mod == &module && module_live && !kernel_live && out != nullptr
          && name != nullptr && std::strcmp(name, "main") == 0, "incorrect kernel selection");
  kernel_live = true;
  *out = &kernel;
  record("kernel_get");
  return VX_SUCCESS;
}

vx_result_t vx_enqueue_launch(vx_queue_h q, const vx_launch_info_t* info,
                              uint32_t nwait, const vx_event_h* waitlist,
                              vx_event_h* out) {
  require(q == &queue && queue_live && info != nullptr && out != nullptr
          && info->struct_size == sizeof(*info) && info->next == nullptr
          && info->kernel == &kernel && kernel_live && info->args_host != nullptr
          && info->args_size == sizeof(kernel_arg_t) && launches < scenario.repeats,
          "incorrect launch descriptor or repeat count");
  require(nwait == 1 && waitlist != nullptr && poison_writes == launches + 1,
          "launch does not depend on fresh output poison");
  checked_event(waitlist[0], "poison", launches);
  kernel_arg_t args;
  std::memcpy(&args, info->args_host, sizeof(args));
  require(args.M == scenario.m && args.N == scenario.n && args.K == scenario.k
          && args.A_addr == buffers[0].address && args.B_addr == buffers[1].address
          && args.C_addr == buffers[2].address && args.cycles_addr == 0
          && info->ndim == 2 && info->grid_dim[0] == scenario.n / 4
          && info->grid_dim[1] == scenario.m / 8 && info->grid_dim[2] == 0
          && info->block_dim[0] == 4 && info->block_dim[1] == 1
          && info->block_dim[2] == 0 && info->lmem_size == 0,
          "kernel arguments or tile grid differ from independent JSON dimensions");
  if (launches == 0) {
    consume_upload(buffers[0], scenario.a, "A upload differs from independent JSON bytes");
    consume_upload(buffers[1], scenario.b, "B upload differs from independent JSON bytes");
  }
  consume_upload(buffers[2], scenario.poison, "device output was not freshly poisoned");
  auto& output = buffers[2].data;
  if (!fault("missing_all") && !(launches == 0 && fault("missing_all_first"))
      && !(launches == 1 && fault("missing_all_second"))) {
    size_t count = output.size();
    if (launches == 1 && fault("missing_last_second")) {
      count -= 4;
    }
    std::memcpy(output.data(), scenario.expected.data(), count);
    if (launches == 1 && (fault("one_bit_second") || fault("zero_sign_second"))) {
      uint8_t* target = output.data() + 4 * fault_index();
      uint32_t value = word_at(target);
      if (fault("zero_sign_second")) {
        require((value & 0x7fffffffu) == 0, "signed-zero control requires a zero output");
        value ^= 0x80000000u;
      } else {
        value ^= 1;
      }
      put_word(target, value);
    }
  }
  *out = new_event("launch", launches);
  record("launch:" + std::to_string(launches++));
  return VX_SUCCESS;
}

vx_result_t vx_enqueue_read(vx_queue_h q, void* destination, vx_buffer_h handle,
                            uint64_t offset, uint64_t size, uint32_t nwait,
                            const vx_event_h* waitlist, vx_event_h* out) {
  auto& buffer = checked_buffer(handle);
  require(q == &queue && queue_live && &buffer == &buffers[2] && destination != nullptr
          && offset == 0 && size == scenario.expected.size() && nwait == 1
          && waitlist != nullptr && out != nullptr && launches == reads + 1,
          "incorrect output read descriptor");
  checked_event(waitlist[0], "launch", reads);
  require(std::memcmp(destination, scenario.poison.data(), scenario.poison.size()) == 0,
          "host output was not freshly poisoned before the read");
  auto event = new_event("read", reads);
  event->destination = destination;
  *out = event;
  record("read:" + std::to_string(reads++));
  return VX_SUCCESS;
}

vx_result_t vx_event_wait_value(vx_event_h event, uint64_t value, uint64_t timeout) {
  checked_event(event, "read", waits);
  require(!event->waited && value == 1 && timeout == VX_TIMEOUT_INFINITE,
          "incorrect read completion wait");
  if (!(waits == 1 && fault("missing_read_second"))) {
    std::memcpy(event->destination, buffers[2].data.data(), buffers[2].data.size());
  }
  event->waited = true;
  record("wait:" + std::to_string(waits++));
  return VX_SUCCESS;
}

vx_result_t vx_event_release(vx_event_h event) {
  auto position = std::find(events.begin(), events.end(), event);
  require(position != events.end(), "invalid event release");
  require(event->iteration < waits, "event released before output completion");
  record(std::string("release:") + event->kind + ":" + std::to_string(event->iteration));
  events.erase(position);
  delete event;
  return VX_SUCCESS;
}

vx_result_t vx_buffer_release(vx_buffer_h handle) {
  auto& buffer = checked_buffer(handle);
  buffer.live = false;
  record(std::string("release:") + buffer.role);
  return VX_SUCCESS;
}

vx_result_t vx_kernel_release(vx_kernel_h handle) {
  require(handle == &kernel && kernel_live, "invalid kernel release");
  kernel_live = false;
  record("release:kernel");
  return VX_SUCCESS;
}

vx_result_t vx_module_release(vx_module_h handle) {
  require(handle == &module && module_live && !kernel_live, "invalid module release");
  module_live = false;
  record("release:module");
  return VX_SUCCESS;
}

vx_result_t vx_queue_release(vx_queue_h handle) {
  require(handle == &queue && queue_live, "invalid queue release");
  queue_live = false;
  record("release:queue");
  return VX_SUCCESS;
}

vx_result_t vx_device_dump_perf(vx_device_h device, FILE*) {
  require(opened && device == &scenario, "invalid performance query");
  return VX_SUCCESS;
}

vx_result_t vx_device_release(vx_device_h device) {
  require(opened && device == &scenario && !queue_live && !kernel_live && !module_live
          && events.empty(), "device released with live runtime objects");
  for (const auto& buffer : buffers) {
    require(!buffer.live, "device released with live buffers");
  }
  if (launches != 0) {
    require(launches == scenario.repeats && reads == launches && waits == launches
            && poison_writes == launches, "incomplete repeat execution");
  }
  opened = false;
  record("device_close");
  return VX_SUCCESS;
}

uint16_t rv_ftoh_s(uint32_t, uint32_t, uint32_t*) { conversion_called("rv_ftoh_s"); }
uint32_t rv_htof_s(uint16_t, uint32_t, uint32_t*) { conversion_called("rv_htof_s"); }
uint16_t rv_ftob_s(uint32_t, uint32_t, uint32_t*) { conversion_called("rv_ftob_s"); }
uint32_t rv_btof_s(uint16_t, uint32_t, uint32_t*) { conversion_called("rv_btof_s"); }
uint32_t rv_ftotf32_s(uint32_t, uint32_t, uint32_t*) { conversion_called("rv_ftotf32_s"); }
uint32_t rv_tf32tof_s(uint32_t, uint32_t, uint32_t*) { conversion_called("rv_tf32tof_s"); }

} // extern "C"
