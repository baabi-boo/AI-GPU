// SPDX-License-Identifier: Apache-2.0

#include "runtime.h"
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <map>
#include <string>
#include <vector>

using namespace vortex::ai;

namespace {
int checks = 0;
void check(bool condition) {
  ++checks;
  if (!condition) {
    std::cerr << "failed check " << checks << '\n';
    std::exit(1);
  }
}
struct Buffer { std::vector<uint8_t> bytes; uint64_t address; };
struct State {
  int devices = 0;
  int modules = 0;
  int kernels = 0;
  int queues = 0;
  int events = 0;
  int premature = 0;
  int writes_observed = 0;
  uint32_t threads = 4;
  int timeout_budget = 0;
  int async_failure = 0;
  int bad_address = 0;
  bool cleanup_failure = false;
  std::string fail_call;
  int fail_at = 0;
  std::map<std::string, int> calls;
  std::vector<Buffer*> buffers;
  std::vector<uint8_t> image;
  uint64_t next_address = 0x100000;
} state;
bool fail(const std::string& name) {
  const int call = ++state.calls[name];
  return state.fail_call == name && call == state.fail_at;
}
vx_result_t release_result() {
  if (state.cleanup_failure) {
    state.cleanup_failure = false;
    return VX_ERR_INTERNAL;
  }
  return VX_SUCCESS;
}
void no_resources() {
  check(state.devices == 0 && state.modules == 0 && state.kernels == 0
        && state.queues == 0 && state.events == 0 && state.buffers.empty()
        && state.premature == 0);
}
void reset() {
  no_resources();
  state = State{};
}
}

struct vx_event {
  int refs = 2;
  bool done = false;
  vx_result_t result = VX_SUCCESS;
  vx_queue_h queue = nullptr;
  std::function<void()> work;
};
struct vx_queue { std::vector<vx_event_h> events; };
struct vx_module {};
struct vx_kernel {};

namespace {
void drop(vx_event_h event) {
  if (--event->refs == 0) {
    --state.events;
    delete event;
  }
}
vx_result_t enqueue(vx_queue_h queue, uint32_t n, const vx_event_h* waits,
                    vx_event_h* out, std::function<void()> work) {
  if (fail("enqueue")) {
    return VX_ERR_OUT_OF_HOST_MEMORY;
  }
  check((queue->events.empty() && n == 0) || (n == 1 && waits[0] == queue->events.back()));
  auto* event = new vx_event;
  event->queue = queue;
  event->work = std::move(work);
  queue->events.push_back(event);
  ++state.events;
  *out = event;
  return VX_SUCCESS;
}
void drain(vx_queue_h queue) {
  vx_result_t error = VX_SUCCESS;
  for (size_t i = 0; i != queue->events.size(); ++i) {
    auto* event = queue->events[i];
    if (!event->done) {
      if (state.async_failure == int(i + 1)) {
        error = VX_ERR_DEVICE_LOST;
      }
      if (error == VX_SUCCESS) {
        event->work();
      }
      event->result = error;
      event->done = true;
    } else if (event->result != VX_SUCCESS) {
      error = event->result;
    }
  }
}
ExecutionBinding binding(DType dtype = DType::fp16) {
  static const std::vector<uint8_t> bytes(64, 0x5a);
  ExecutionBinding result;
  result.profile = {Profile::p02_tfr_wmma_v1, true, true};
  result.input_dtype = dtype;
  result.module_bytes = bytes.data();
  result.module_size = bytes.size();
  result.qualification_id = std::string(64, 'a');
  return result;
}
std::unique_ptr<ManagedMatmul> create(DType dtype = DType::fp16) {
  std::unique_ptr<ManagedMatmul> runtime;
  check(ManagedMatmul::create(binding(dtype), &runtime).ok());
  check(runtime != nullptr && state.image == std::vector<uint8_t>(64, 0x5a));
  return runtime;
}
ExecutionResult launch(ManagedMatmul* runtime, std::unique_ptr<MatmulOperation>* operation,
                       uint32_t m = 8, uint32_t n = 4, uint32_t k = 8) {
  std::vector<uint8_t> a(m * k * 2, 0x12);
  std::vector<uint8_t> b(k * n * 2, 0x34);
  auto result = runtime->submit(m, n, k, a.data(), a.size(), b.data(), b.size(),
                                 0xdeadbeef, operation);
  std::fill(a.begin(), a.end(), 0);
  std::fill(b.begin(), b.end(), 0);
  return result;
}
}

extern "C" {
vx_result_t vx_device_open(uint32_t index, vx_device_h* out) {
  check(index == 0);
  if (fail("device_open")) {
    return VX_ERR_DEVICE_LOST;
  }
  *out = new int(1);
  ++state.devices;
  return VX_SUCCESS;
}
vx_result_t vx_device_release(vx_device_h device) {
  check(state.modules == 0 && state.kernels == 0 && state.queues == 0 && state.buffers.empty());
  delete static_cast<int*>(device);
  --state.devices;
  return release_result();
}
vx_result_t vx_device_query(vx_device_h, uint32_t id, uint64_t* out) {
  if (fail("query")) {
    return VX_ERR_DEVICE_LOST;
  }
  switch (id) {
    case VX_CAPS_NUM_THREADS: *out = state.threads; break;
    case VX_CAPS_NUM_WARPS: *out = 4; break;
    case VX_CAPS_NUM_CORES: case VX_CAPS_NUM_CLUSTERS: case VX_CAPS_ISSUE_WIDTH: *out = 1; break;
    case VX_CAPS_LOCAL_MEM_SIZE: *out = 16384; break;
    case VX_CAPS_ISA_FLAGS: *out = (2ull << 30) | VX_ISA_EXT_TCU | VX_ISA_EXT_LMEM; break;
    default: return VX_ERR_INVALID_VALUE;
  }
  return VX_SUCCESS;
}
vx_result_t vx_device_memory_info(vx_device_h, uint64_t* free_bytes, uint64_t* used_bytes) {
  *used_bytes = 0;
  for (auto* buffer : state.buffers) {
    *used_bytes += buffer->bytes.size();
  }
  *free_bytes = 100000 - *used_bytes;
  return VX_SUCCESS;
}
vx_result_t vx_module_load_bytes(vx_device_h, const void* bytes, size_t size, vx_module_h* out) {
  if (fail("module_load")) {
    return VX_ERR_OUT_OF_DEVICE_MEMORY;
  }
  auto* first = static_cast<const uint8_t*>(bytes);
  state.image.assign(first, first + size);
  *out = new vx_module;
  ++state.modules;
  return VX_SUCCESS;
}
vx_result_t vx_module_release(vx_module_h module) {
  check(state.kernels == 0 && state.queues == 0);
  delete module;
  --state.modules;
  return release_result();
}
vx_result_t vx_module_get_kernel(vx_module_h, const char* name, vx_kernel_h* out) {
  check(std::string(name) == "main");
  if (fail("get_kernel")) {
    return VX_ERR_NOT_SUPPORTED;
  }
  *out = new vx_kernel;
  ++state.kernels;
  return VX_SUCCESS;
}
vx_result_t vx_kernel_release(vx_kernel_h kernel) {
  check(state.queues == 0);
  delete kernel;
  --state.kernels;
  return release_result();
}
vx_result_t vx_queue_create(vx_device_h, const vx_queue_info_t*, vx_queue_h* out) {
  if (fail("queue_create")) {
    return VX_ERR_OUT_OF_HOST_MEMORY;
  }
  *out = new vx_queue;
  ++state.queues;
  return VX_SUCCESS;
}
vx_result_t vx_queue_release(vx_queue_h queue) {
  for (auto* event : queue->events) {
    if (!event->done) {
      ++state.premature;
    }
    drop(event);
  }
  delete queue;
  --state.queues;
  return release_result();
}
vx_result_t vx_buffer_create(vx_device_h, uint64_t size, uint32_t flags, vx_buffer_h* out) {
  if (fail("buffer_create")) {
    return VX_ERR_OUT_OF_DEVICE_MEMORY;
  }
  check(flags == VX_MEM_READ || flags == VX_MEM_WRITE);
  auto* buffer = new Buffer{std::vector<uint8_t>(size), state.next_address};
  state.next_address += 0x1000;
  state.buffers.push_back(buffer);
  *out = buffer;
  return VX_SUCCESS;
}
vx_result_t vx_buffer_address(vx_buffer_h handle, uint64_t* out) {
  if (fail("buffer_address")) {
    return VX_ERR_DEVICE_LOST;
  }
  *out = static_cast<Buffer*>(handle)->address;
  if (state.bad_address == 1) {
    ++*out;
  }
  if (state.bad_address == 2) {
    *out = 0x100000;
  }
  if (state.bad_address == 3) {
    *out = UINT64_MAX - 3;
  }
  return VX_SUCCESS;
}
vx_result_t vx_buffer_release(vx_buffer_h handle) {
  auto* buffer = static_cast<Buffer*>(handle);
  state.buffers.erase(std::find(state.buffers.begin(), state.buffers.end(), buffer));
  delete buffer;
  return release_result();
}
vx_result_t vx_enqueue_write(vx_queue_h queue, vx_buffer_h handle, uint64_t offset,
                             const void* source, uint64_t size, uint32_t n,
                             const vx_event_h* waits, vx_event_h* out) {
  auto* buffer = static_cast<Buffer*>(handle);
  check(offset == 0 && size == buffer->bytes.size());
  const int ordinal = int(queue->events.size());
  return enqueue(queue, n, waits, out, [buffer, source, size, ordinal] {
    auto* first = static_cast<const uint8_t*>(source);
    if (ordinal < 2) {
      check(std::all_of(first, first + size, [ordinal](uint8_t byte) {
        return byte == (ordinal == 0 ? 0x12 : 0x34);
      }));
    }
    std::memcpy(buffer->bytes.data(), source, size);
    ++state.writes_observed;
  });
}
vx_result_t vx_enqueue_launch(vx_queue_h queue, const vx_launch_info_t* info,
                              uint32_t n, const vx_event_h* waits, vx_event_h* out) {
  check(info->struct_size == sizeof(*info) && info->args_size == 56 && info->ndim == 2
        && info->block_dim[0] == 4 && info->block_dim[1] == 1 && info->block_dim[2] == 1);
  std::vector<uint8_t> args(static_cast<const uint8_t*>(info->args_host),
                            static_cast<const uint8_t*>(info->args_host) + info->args_size);
  return enqueue(queue, n, waits, out, [args] {
    uint64_t address = 0;
    for (unsigned i = 0; i != 8; ++i) {
      address |= uint64_t{args[48 + i]} << (8 * i);
    }
    auto found = std::find_if(state.buffers.begin(), state.buffers.end(), [address](Buffer* buffer) {
      return buffer->address == address;
    });
    check(found != state.buffers.end());
    auto* buffer = *found;
    for (size_t i = 0; i != buffer->bytes.size() / 4; ++i) {
      const uint32_t value = 0x3f800000 + static_cast<uint32_t>(i);
      for (unsigned j = 0; j != 4; ++j) {
        buffer->bytes[i * 4 + j] = uint8_t(value >> (8 * j));
      }
    }
  });
}
vx_result_t vx_enqueue_read(vx_queue_h queue, void* destination, vx_buffer_h handle,
                            uint64_t offset, uint64_t size, uint32_t n,
                            const vx_event_h* waits, vx_event_h* out) {
  auto* buffer = static_cast<Buffer*>(handle);
  check(offset == 0 && size == buffer->bytes.size());
  return enqueue(queue, n, waits, out, [buffer, destination, size] {
    std::memcpy(destination, buffer->bytes.data(), size);
  });
}
vx_result_t vx_event_wait_value(vx_event_h event, uint64_t value, uint64_t) {
  check(value == 1);
  if (state.timeout_budget > 0) {
    --state.timeout_budget;
    return VX_ERR_TIMEOUT;
  }
  drain(event->queue);
  return event->result;
}
vx_result_t vx_event_get_value(vx_event_h event, uint64_t* out) {
  *out = event->done ? 1 : 0;
  return VX_SUCCESS;
}
vx_result_t vx_event_release(vx_event_h event) {
  drop(event);
  return release_result();
}
}

namespace {
void positive_shapes() {
  for (auto dtype : {DType::fp16, DType::bf16}) {
    auto runtime = create(dtype);
    for (const auto shape : {std::array<uint32_t, 3>{8,4,8}, {8,4,16}, {16,8,16}}) {
      uint64_t free_before = 0, used_before = 0;
      check(runtime->memory_info(&free_before, &used_before) == VX_SUCCESS);
      std::unique_ptr<MatmulOperation> operation;
      auto result = launch(runtime.get(), &operation, shape[0], shape[1], shape[2]);
      check(result.ok() && !result.complete && operation->output_words().empty());
      result = operation->wait(VX_TIMEOUT_INFINITE);
      check(result.ok() && result.complete);
      check(operation->output_words().size() == shape[0] * shape[1]);
      for (size_t i = 0; i != operation->output_words().size(); ++i) {
        check(operation->output_words()[i] == 0x3f800000 + i);
      }
      const auto& trace = operation->trace();
      check(trace.writes_enqueued == 3 && trace.launches_enqueued == 1 && trace.reads_enqueued == 1);
      check(trace.argument_bytes[0] == 1 && trace.argument_bytes[4] == 56
            && trace.argument_bytes[16] == shape[0] && trace.argument_bytes[20] == shape[1]);
      check(trace.qualification_id == std::string(64, 'a') && trace.input_dtype == dtype);
      check(operation->close(0).ok() && operation->close(0).ok());
      uint64_t free_after = 0, used_after = 0;
      check(runtime->memory_info(&free_after, &used_after) == VX_SUCCESS);
      check(free_after == free_before && used_after == used_before);
    }
    check(runtime->close().ok() && runtime->close().ok());
    no_resources();
  }
}
void invalid_binding() {
  for (int kind = 0; kind != 8; ++kind) {
    auto value = binding();
    if (kind == 0) {
      value.qualification_id = "";
    }
    if (kind == 1) {
      value.qualification_id[2] = 'g';
    }
    if (kind == 2) {
      value.profile.verified_device_profile = false;
    }
    if (kind == 3) {
      value.profile.verified_kernel_profile = false;
    }
    if (kind == 4) {
      value.input_dtype = DType::fp32;
    }
    if (kind == 5) {
      value.module_size = 15;
    }
    if (kind == 6) {
      value.module_bytes = nullptr;
    }
    if (kind == 7) {
      state.threads = 8;
    }
    std::unique_ptr<ManagedMatmul> runtime;
    check(!ManagedMatmul::create(value, &runtime).ok() && !runtime);
    reset();
  }
}
void invalid_inputs() {
  auto runtime = create();
  std::vector<uint8_t> a(128, 0x12), b(64, 0x34);
  for (int kind = 0; kind != 4; ++kind) {
    std::unique_ptr<MatmulOperation> operation;
    const auto result = runtime->submit(kind == 0 ? 9 : 8, 4, 8,
      kind == 1 ? nullptr : a.data(), kind == 2 ? 127 : a.size(), b.data(),
      kind == 3 ? 65 : b.size(), 0, &operation);
    check(!result.ok() && !operation && state.queues == 0 && state.buffers.empty());
  }
  check(runtime->close().ok());
  no_resources();
}
void create_failures() {
  for (const std::string call : {"device_open", "query", "module_load", "get_kernel"}) {
    state.fail_call = call;
    state.fail_at = 1;
    std::unique_ptr<ManagedMatmul> runtime;
    check(!ManagedMatmul::create(binding(), &runtime).ok() && !runtime);
    reset();
  }
}
void partial_failures() {
  for (const std::string call : {"queue_create", "buffer_create", "buffer_address", "enqueue"}) {
    const int maximum = call == "enqueue" ? 5 : call == "queue_create" ? 1 : 3;
    for (int at = 1; at <= maximum; ++at) {
      auto runtime = create();
      state.fail_call = call;
      state.fail_at = at;
      std::unique_ptr<MatmulOperation> operation;
      const auto submitted = launch(runtime.get(), &operation);
      check(!submitted.ok() && operation && submitted.primary != VX_SUCCESS);
      const auto result = operation->close(VX_TIMEOUT_INFINITE);
      check(result.complete && result.primary == submitted.primary && result.cleanup == VX_SUCCESS);
      check(operation->output_words().empty() && state.buffers.empty() && state.queues == 0);
      check(runtime->close().ok());
      reset();
    }
  }
}
void timeout_ownership() {
  auto runtime = create();
  std::unique_ptr<MatmulOperation> operation;
  check(launch(runtime.get(), &operation).ok());
  state.timeout_budget = 1;
  const auto result = operation->close(0);
  check(result.primary == VX_ERR_TIMEOUT && !result.complete && state.buffers.size() == 3
        && state.queues == 1 && operation->output_words().empty());
  check(!runtime->close().complete);
  runtime.reset();
  check(state.devices == 1 && state.modules == 1 && state.kernels == 1);
  check(operation->close(VX_TIMEOUT_INFINITE).ok());
  check(operation->trace().timed_out_waits == 1 && !operation->output_words().empty());
  no_resources();
}
void asynchronous_errors() {
  for (int at = 1; at <= 5; ++at) {
    auto runtime = create();
    std::unique_ptr<MatmulOperation> operation;
    state.async_failure = at;
    check(launch(runtime.get(), &operation).ok());
    state.cleanup_failure = true;
    auto result = operation->close(VX_TIMEOUT_INFINITE);
    check(result.primary == VX_ERR_DEVICE_LOST && result.cleanup == VX_ERR_INTERNAL && result.complete);
    check(operation->output_words().empty() && state.queues == 0 && state.buffers.empty());
    result = operation->close(0);
    check(result.primary == VX_ERR_DEVICE_LOST && result.cleanup == VX_ERR_INTERNAL);
    check(runtime->close().ok());
    reset();
  }
}
void allocation_validation() {
  for (int mode = 1; mode <= 3; ++mode) {
    auto runtime = create();
    state.bad_address = mode;
    std::unique_ptr<MatmulOperation> operation;
    const auto result = launch(runtime.get(), &operation);
    const Status expected = mode == 1 ? Status::misaligned_address
                          : mode == 2 ? Status::aliasing : Status::address_out_of_range;
    check(result.validation == expected && result.complete && state.calls["enqueue"] == 0);
    check(operation && operation->output_words().empty() && state.buffers.empty());
    check(runtime->close().ok());
    reset();
  }
}
void destructor_drain() {
  auto runtime = create();
  for (int i = 0; i != 32; ++i) {
    std::unique_ptr<MatmulOperation> operation;
    check(launch(runtime.get(), &operation).ok());
    operation.reset();
    check(state.buffers.empty() && state.queues == 0 && state.events == 0);
  }
  check(runtime->close().ok());
  no_resources();
}
}

int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  const std::string group = argv[1];
  if (group == "positive_shapes") {
    positive_shapes();
  } else if (group == "invalid_binding") {
    invalid_binding();
  } else if (group == "invalid_inputs") {
    invalid_inputs();
  } else if (group == "create_failures") {
    create_failures();
  } else if (group == "partial_failures") {
    partial_failures();
  } else if (group == "timeout_ownership") {
    timeout_ownership();
  } else if (group == "asynchronous_errors") {
    asynchronous_errors();
  } else if (group == "allocation_validation") {
    allocation_validation();
  } else if (group == "destructor_drain") {
    destructor_drain();
  } else {
    return 2;
  }
  no_resources();
  std::cout << "PASS " << group << " checks=" << checks << '\n';
}
