// SPDX-License-Identifier: Apache-2.0
// Independent byte replay validates the host protocol without executing a kernel.

#include <vortex2.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <vector>

struct vx_queue {};
struct vx_module {};
struct vx_kernel {};
struct vx_event {
  std::string kind;
  unsigned iteration;
  void *destination = nullptr;
  bool complete = false;
};

namespace {

[[noreturn]] void fail(const char *message) {
  std::fprintf(stderr, "WGMMA_STUB_ERROR: %s\n", message);
  std::fflush(nullptr);
  std::_Exit(86);
}

void require(bool condition, const char *message) {
  if (!condition) {
    fail(message);
  }
}

void record(const std::string &message) {
  const char *path = std::getenv("WGMMA_STUB_TRACE");
  require(path != nullptr, "missing trace path");
  FILE *stream = std::fopen(path, "a");
  require(stream != nullptr, "cannot open trace");
  require(std::fprintf(stream, "%s\n", message.c_str()) > 0, "cannot write trace");
  require(std::fclose(stream) == 0, "cannot close trace");
}

bool selected(const char *variable, const std::string &name) {
  const char *value = std::getenv(variable);
  return value != nullptr && value == name;
}

bool fault(const char *name) {
  return selected("WGMMA_STUB_FAULT", name);
}

std::map<std::string, unsigned> calls;
bool injected(const std::string &operation) {
  const unsigned occurrence = ++calls[operation];
  const char *count = std::getenv("WGMMA_STUB_OCCURRENCE");
  const unsigned target = count == nullptr ? 1 : unsigned(std::strtoul(count, nullptr, 10));
  if (selected("WGMMA_STUB_FAIL", operation) && occurrence == target) {
    record("injected:" + operation + ":" + std::to_string(occurrence));
    return true;
  }
  return false;
}

uint32_t word(const uint8_t *bytes) {
  return uint32_t(bytes[0]) | uint32_t(bytes[1]) << 8 | uint32_t(bytes[2]) << 16 | uint32_t(bytes[3]) << 24;
}

struct Scenario {
  bool sparse = false;
  std::array<std::vector<uint8_t>, 4> payload;
};
struct Buffer {
  bool live = false;
  unsigned role = 0;
  uint64_t address = 0;
  std::vector<uint8_t> bytes;
  const uint8_t *pending = nullptr;
};
struct DenseArgs {
  uint32_t m, n, k;
  uint64_t a, b, c;
};
struct SparseArgs {
  uint32_t m, n, k;
  uint64_t a, b, c, metadata;
};
static_assert(sizeof(DenseArgs) == 40 && sizeof(SparseArgs) == 48, "fixed runtime ABI");

Scenario scenario;
std::array<Buffer, 4> buffers;
std::vector<vx_event_h> events;
std::array<std::vector<uint8_t>, 2> poisons;
vx_queue queue;
vx_module module;
vx_kernel kernel;
bool opened = false, queue_live = false, module_live = false, kernel_live = false;
bool finished = false;
unsigned allocations = 0, launches = 0, reads = 0, waits = 0, poison_writes = 0;
const char *roles[] = {"A", "B", "C", "metadata"};

void require_no_leaks() {
  require(!opened && !queue_live && !module_live && !kernel_live && events.empty(),
          "runtime handle leaked at exit");
  for (const auto &buffer : buffers) {
    require(!buffer.live, "buffer leaked at exit");
  }
}

void load_scenario() {
  const char *path = std::getenv("WGMMA_STUB_SCENARIO");
  require(path != nullptr, "missing scenario");
  std::ifstream stream(path, std::ios::binary | std::ios::ate);
  require(stream.good(), "cannot read scenario");
  const auto size = stream.tellg();
  require(size >= 28 && size <= 16384, "scenario size out of bounds");
  std::vector<uint8_t> bytes(static_cast<size_t>(size));
  stream.seekg(0);
  stream.read(reinterpret_cast<char *>(bytes.data()), bytes.size());
  require(stream.good() && std::memcmp(bytes.data(), "WGMMA01!", 8) == 0,
          "invalid scenario header");
  scenario.sparse = word(bytes.data() + 8) != 0;
  size_t offset = 28;
  const size_t expected_sizes[] = {scenario.sparse ? 1024u : 2048u, 256u, 2048u,
                                   scenario.sparse ? 512u : 0u};
  for (unsigned i = 0; i < 4; ++i) {
    const size_t length = word(bytes.data() + 12 + 4 * i);
    require(length == expected_sizes[i] && length <= bytes.size() - offset,
            "invalid scenario payload size");
    scenario.payload[i].assign(bytes.begin() + offset, bytes.begin() + offset + length);
    offset += length;
  }
  require(offset == bytes.size(), "trailing scenario bytes");
}

Buffer &buffer_for(vx_buffer_h handle) {
  for (auto &buffer : buffers) {
    if (handle == &buffer && buffer.live) {
      return buffer;
    }
  }
  fail("invalid buffer handle");
}

vx_event_h event_for(const char *kind, unsigned iteration) {
  auto event = new vx_event{kind, iteration};
  events.push_back(event);
  return event;
}

void event_is(vx_event_h event, const char *kind, unsigned iteration) {
  require(std::find(events.begin(), events.end(), event) != events.end(), "invalid event");
  require(event->kind == kind && event->iteration == iteration, "wrong event dependency");
}

void complete_upload(Buffer &buffer) {
  if (buffer.pending == nullptr) {
    return;
  }
  const auto &expected = buffer.role == 2 ? poisons[poison_writes - 1]
                                          : scenario.payload[buffer.role];
  require(expected.size() == buffer.bytes.size() && std::memcmp(buffer.pending, expected.data(), expected.size()) == 0,
          "upload differs from independent scenario bytes or changed before completion");
  std::memcpy(buffer.bytes.data(), buffer.pending, expected.size());
  buffer.pending = nullptr;
}

void complete_read(vx_event_h event) {
  if (event->kind == "read" && !event->complete) {
    if (!(event->iteration == 1 && fault("missing_read_second"))) {
      std::memcpy(event->destination, buffers[2].bytes.data(), buffers[2].bytes.size());
    }
    event->complete = true;
  }
}

} // namespace

extern "C" {

vx_result_t vx_device_open(uint32_t index, vx_device_h *out) {
  record("device_open");
  require(!opened && index == 0 && out != nullptr, "invalid device open");
  if (injected("device_open")) {
    return VX_ERR_INTERNAL;
  }
  load_scenario();
  std::atexit(require_no_leaks);
  opened = true;
  *out = &scenario;
  return VX_SUCCESS;
}

vx_result_t vx_device_query(vx_device_h device, uint32_t cap, uint64_t *value) {
  require(opened && device == &scenario && value != nullptr, "invalid capability query");
  record("query:" + std::to_string(cap));
  if (injected("device_query")) {
    return VX_ERR_INTERNAL;
  }
  switch (cap) {
  case VX_CAPS_NUM_THREADS:
    *value = selected("WGMMA_STUB_CAP", "threads") ? 4 : 8;
    break;
  case VX_CAPS_NUM_WARPS:
    *value = selected("WGMMA_STUB_CAP", "warps") ? 4 : 8;
    break;
  case VX_CAPS_ISSUE_WIDTH:
    *value = selected("WGMMA_STUB_CAP", "issue") ? 2 : 4;
    break;
  case VX_CAPS_NUM_CORES:
    *value = selected("WGMMA_STUB_CAP", "cores") ? 2 : 1;
    break;
  case VX_CAPS_NUM_CLUSTERS:
    *value = selected("WGMMA_STUB_CAP", "clusters") ? 2 : 1;
    break;
  case VX_CAPS_LOCAL_MEM_SIZE:
    *value = selected("WGMMA_STUB_CAP", "lmem_size") ? 8192 : 16384;
    break;
  case VX_CAPS_ISA_FLAGS:
    *value = (selected("WGMMA_STUB_CAP", "xlen") ? 1ull : 2ull) << 30;
    if (!selected("WGMMA_STUB_CAP", "tcu")) {
      *value |= VX_ISA_EXT_TCU;
    }
    if (!selected("WGMMA_STUB_CAP", "lmem")) {
      *value |= VX_ISA_EXT_LMEM;
    }
    if (selected("WGMMA_STUB_CAP", "matrix")) {
      *value |= VX_ISA_EXT_LDST_MATRIX;
    }
    break;
  default:
    fail("unexpected capability query");
  }
  return VX_SUCCESS;
}

vx_result_t vx_queue_create(vx_device_h device, const vx_queue_info_t *info, vx_queue_h *out) {
  require(opened && device == &scenario && !queue_live && info != nullptr && out != nullptr && info->struct_size == sizeof(*info) && info->next == nullptr && info->priority == VX_QUEUE_PRIORITY_NORMAL && info->flags == 0,
          "invalid queue descriptor");
  if (injected("queue_create")) {
    return VX_ERR_INTERNAL;
  }
  queue_live = true;
  *out = &queue;
  record("create:queue");
  return VX_SUCCESS;
}

vx_result_t vx_buffer_create(vx_device_h device, uint64_t size, uint32_t flags, vx_buffer_h *out) {
  require(opened && device == &scenario && out != nullptr && allocations < (scenario.sparse ? 4u : 3u), "unexpected buffer allocation");
  const std::string name = "buffer_create:" + std::string(roles[allocations]);
  if (injected(name)) {
    return VX_ERR_INTERNAL;
  }
  require(size == scenario.payload[allocations].size() && flags == (allocations == 2 ? VX_MEM_READ_WRITE : VX_MEM_READ),
          "incorrect buffer size or access flags");
  auto &buffer = buffers[allocations];
  buffer.live = true;
  buffer.role = allocations;
  buffer.address = (allocations + 1) * 0x10000ull;
  buffer.bytes.assign(size, 0xcc);
  *out = &buffer;
  record("create:" + std::string(roles[allocations++]));
  return VX_SUCCESS;
}

vx_result_t vx_buffer_address(vx_buffer_h handle, uint64_t *out) {
  auto &buffer = buffer_for(handle);
  require(out != nullptr, "missing address destination");
  if (injected("buffer_address:" + std::string(roles[buffer.role]))) {
    return VX_ERR_INTERNAL;
  }
  *out = buffer.address;
  return VX_SUCCESS;
}

vx_result_t vx_enqueue_write(vx_queue_h q, vx_buffer_h handle, uint64_t offset,
                             const void *source, uint64_t size, uint32_t nwait,
                             const vx_event_h *waitlist, vx_event_h *out) {
  auto &buffer = buffer_for(handle);
  require(queue_live && q == &queue && offset == 0 && size == buffer.bytes.size() && source != nullptr && nwait == 0 && waitlist == nullptr && out != nullptr && buffer.pending == nullptr, "invalid write descriptor");
  if (injected("write:" + std::string(roles[buffer.role]))) {
    return VX_ERR_INTERNAL;
  }
  finished = false;
  buffer.pending = static_cast<const uint8_t *>(source);
  if (buffer.role == 2) {
    require(poison_writes == launches && launches < 2, "poison must precede each launch");
    auto &current = poisons[launches];
    current.assign(buffer.pending, buffer.pending + size);
    for (size_t i = 0; i < current.size(); i += 4) {
      const uint32_t bits = word(current.data() + i);
      require((bits & 0x7fc00000u) == 0x7fc00000u, "poison must be a quiet NaN");
      require((bits & 0xffffu) == i / 4, "every poison index must be distinct");
    }
    require(launches == 0 || current != poisons[0], "second poison must differ from first");
    *out = event_for("poison", launches);
    record("poison:" + std::to_string(poison_writes++));
  } else {
    require(launches == 0, "input was uploaded after execution began");
    *out = event_for(roles[buffer.role], 0);
    record("upload:" + std::string(roles[buffer.role]));
  }
  return VX_SUCCESS;
}

vx_result_t vx_module_load_file(vx_device_h device, const char *path, vx_module_h *out) {
  require(opened && device == &scenario && !module_live && out != nullptr && path != nullptr && std::strcmp(path, "kernel.vxbin") == 0, "invalid module load");
  if (injected("module_load")) {
    return VX_ERR_INTERNAL;
  }
  module_live = true;
  *out = &module;
  record("create:module");
  return VX_SUCCESS;
}

vx_result_t vx_module_get_kernel(vx_module_h mod, const char *name, vx_kernel_h *out) {
  require(module_live && mod == &module && !kernel_live && out != nullptr && name != nullptr && std::strcmp(name, "main") == 0, "invalid kernel lookup");
  if (injected("kernel_get")) {
    return VX_ERR_INTERNAL;
  }
  kernel_live = true;
  *out = &kernel;
  record("create:kernel");
  return VX_SUCCESS;
}

vx_result_t vx_enqueue_launch(vx_queue_h q, const vx_launch_info_t *info,
                              uint32_t nwait, const vx_event_h *waitlist, vx_event_h *out) {
  require(queue_live && q == &queue && info != nullptr && out != nullptr && info->struct_size == sizeof(*info) && info->next == nullptr && kernel_live && info->kernel == &kernel && info->args_host != nullptr && launches < 2,
          "invalid launch descriptor");
  require(nwait == (scenario.sparse ? 4u : 3u) && waitlist != nullptr && poison_writes == launches + 1, "missing launch dependency");
  event_is(waitlist[0], "A", 0);
  event_is(waitlist[1], "B", 0);
  event_is(waitlist[2], "poison", launches);
  if (scenario.sparse) {
    event_is(waitlist[3], "metadata", 0);
  }
  require(info->args_size == (scenario.sparse ? sizeof(SparseArgs) : sizeof(DenseArgs)),
          "kernel ABI size mismatch");
  SparseArgs args = {};
  std::memcpy(&args, info->args_host, info->args_size);
  require(args.m == 64 && args.n == 8 && args.k == 16 && args.a == buffers[0].address && args.b == buffers[1].address && args.c == buffers[2].address && (!scenario.sparse || args.metadata == buffers[3].address) && info->ndim == 2 && info->grid_dim[0] == 1 && info->grid_dim[1] == 2 && info->grid_dim[2] == 0 && info->block_dim[0] == 32 && info->block_dim[1] == 1 && info->block_dim[2] == 0 && info->lmem_size == 640,
          "kernel arguments or launch geometry mismatch");
  if (injected("launch")) {
    return VX_ERR_INTERNAL;
  }
  for (auto &buffer : buffers) {
    if (buffer.live) {
      complete_upload(buffer);
    }
  }
  auto &output = buffers[2].bytes;
  if (!fault("missing_all") && !(launches == 0 && fault("missing_first")) && !(launches == 1 && fault("missing_second"))) {
    size_t count = output.size();
    if (launches == 1 && fault("missing_last_second")) {
      count -= 4;
    }
    std::memcpy(output.data(), scenario.payload[2].data(), count);
    if (launches == 1 && fault("one_bit_second")) {
      const char *value = std::getenv("WGMMA_STUB_INDEX");
      const size_t index = value == nullptr ? 511 : std::strtoul(value, nullptr, 10);
      require(index < 512, "invalid corruption index");
      output[index * 4] ^= 1;
    }
  }
  finished = false;
  *out = event_for("launch", launches);
  record("launch:" + std::to_string(launches++));
  return VX_SUCCESS;
}

vx_result_t vx_enqueue_read(vx_queue_h q, void *destination, vx_buffer_h handle,
                            uint64_t offset, uint64_t size, uint32_t nwait,
                            const vx_event_h *waitlist, vx_event_h *out) {
  auto &buffer = buffer_for(handle);
  require(queue_live && q == &queue && &buffer == &buffers[2] && destination != nullptr && offset == 0 && size == buffer.bytes.size() && nwait == 1 && waitlist != nullptr && out != nullptr && launches == reads + 1, "invalid read descriptor");
  event_is(waitlist[0], "launch", reads);
  require(std::memcmp(destination, poisons[reads].data(), size) == 0,
          "host result storage must be freshly poisoned before read");
  if (injected("read")) {
    return VX_ERR_INTERNAL;
  }
  auto event = event_for("read", reads);
  event->destination = destination;
  *out = event;
  record("read:" + std::to_string(reads++));
  return VX_SUCCESS;
}

vx_result_t vx_event_wait_value(vx_event_h event, uint64_t value, uint64_t timeout) {
  event_is(event, "read", waits);
  require(value == 1 && timeout == VX_TIMEOUT_INFINITE && !event->complete,
          "invalid event wait");
  if (injected("wait")) {
    return VX_ERR_INTERNAL;
  }
  complete_read(event);
  record("wait:" + std::to_string(waits++));
  return VX_SUCCESS;
}

vx_result_t vx_device_dump_perf(vx_device_h device, FILE *stream) {
  require(opened && device == &scenario && stream == stdout, "invalid performance dump");
  record("perf:" + std::to_string(waits));
  return injected("dump_perf") ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_queue_finish(vx_queue_h q, uint64_t timeout) {
  require(queue_live && q == &queue && timeout == VX_TIMEOUT_INFINITE, "invalid queue finish");
  for (auto &buffer : buffers) {
    if (buffer.live) {
      complete_upload(buffer);
    }
  }
  for (auto event : events) {
    complete_read(event);
  }
  finished = true;
  record("finish");
  return injected("queue_finish") ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_event_release(vx_event_h event) {
  auto position = std::find(events.begin(), events.end(), event);
  require(position != events.end(), "event released twice");
  require(finished || (event->iteration < waits && (event->kind == "read" || event->kind == "launch" || event->kind == "poison")), "event released before completion");
  const bool error = injected("event_release:" + event->kind);
  record("release_event:" + event->kind + ":" + std::to_string(event->iteration));
  events.erase(position);
  delete event;
  return error ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_buffer_release(vx_buffer_h handle) {
  auto &buffer = buffer_for(handle);
  require(finished && buffer.pending == nullptr, "buffer released before queue drained");
  const std::string name = roles[buffer.role];
  const bool error = injected("release:" + name);
  buffer.live = false;
  record("release:" + name);
  return error ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_kernel_release(vx_kernel_h handle) {
  require(kernel_live && handle == &kernel && finished, "invalid kernel release");
  const bool error = injected("release:kernel");
  kernel_live = false;
  record("release:kernel");
  return error ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_module_release(vx_module_h handle) {
  require(module_live && handle == &module && !kernel_live && finished, "invalid module release");
  const bool error = injected("release:module");
  module_live = false;
  record("release:module");
  return error ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_queue_release(vx_queue_h handle) {
  require(queue_live && handle == &queue && finished && events.empty(), "invalid queue release");
  const bool error = injected("release:queue");
  queue_live = false;
  record("release:queue");
  return error ? VX_ERR_INTERNAL : VX_SUCCESS;
}

vx_result_t vx_device_release(vx_device_h device) {
  require(opened && device == &scenario && !queue_live && !kernel_live && !module_live && events.empty(), "device released with live children");
  for (const auto &buffer : buffers) {
    require(!buffer.live, "device released with live buffer");
  }
  const bool error = injected("release:device");
  opened = false;
  record("device_close");
  return error ? VX_ERR_INTERNAL : VX_SUCCESS;
}

} // extern "C"
