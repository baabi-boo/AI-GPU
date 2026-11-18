// SPDX-License-Identifier: Apache-2.0

#include "runtime.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <limits>
#include <new>
#include <thread>

namespace vortex::ai {
namespace {

void remember(vx_result_t result, vx_result_t* first) noexcept {
  if (*first == VX_SUCCESS && result != VX_SUCCESS) {
    *first = result;
  }
}

ExecutionResult rejected(Status status) noexcept {
  ExecutionResult result;
  result.validation = status;
  return result;
}

bool qualified_id(const std::string& value) noexcept {
  return value.size() == 64 && std::all_of(value.begin(), value.end(), [](char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
  });
}

bool supported_shape(uint32_t m, uint32_t n, uint32_t k) noexcept {
  return (m == 8 && n == 4 && (k == 8 || k == 16)) || (m == 16 && n == 8 && k == 16);
}

void put_word(uint8_t* destination, uint32_t value) noexcept {
  for (unsigned i = 0; i != 4; ++i) {
    destination[i] = static_cast<uint8_t>(value >> (8 * i));
  }
}

uint32_t get_word(const uint8_t* source) noexcept {
  uint32_t value = 0;
  for (unsigned i = 0; i != 4; ++i) {
    value |= uint32_t{source[i]} << (8 * i);
  }
  return value;
}

} // namespace

namespace detail {

struct RuntimeContext {
  vx_device_h device = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  DeviceCapabilities capabilities{};
  ProfileBinding profile{};
  DType dtype = DType::fp16;
  std::string qualification_id;
  std::vector<uint8_t> image;

  void release(vx_result_t* cleanup) noexcept {
    if (kernel) {
      remember(vx_kernel_release(kernel), cleanup);
      kernel = nullptr;
    }
    if (module) {
      remember(vx_module_release(module), cleanup);
      module = nullptr;
    }
    if (device) {
      remember(vx_device_release(device), cleanup);
      device = nullptr;
    }
  }

  ~RuntimeContext() {
    vx_result_t ignored = VX_SUCCESS;
    release(&ignored);
  }
};

struct OperationState {
  std::shared_ptr<RuntimeContext> context;
  vx_queue_h queue = nullptr;
  std::array<vx_buffer_h, 3> buffers{};
  std::array<vx_event_h, 5> events{};
  size_t event_count = 0;
  std::vector<uint8_t> a;
  std::vector<uint8_t> b;
  std::vector<uint8_t> download;
  std::vector<uint32_t> output;
  MatmulPlan plan{};
  MatmulTrace trace{};
  ExecutionResult result{};
  bool submitted_all = false;
  bool output_valid = false;
  bool closed = false;

  void release() noexcept {
    for (auto& event : events) {
      if (event) {
        remember(vx_event_release(event), &result.cleanup);
        event = nullptr;
      }
    }
    if (queue) {
      remember(vx_queue_release(queue), &result.cleanup);
      queue = nullptr;
    }
    for (auto& buffer : buffers) {
      if (buffer) {
        remember(vx_buffer_release(buffer), &result.cleanup);
        buffer = nullptr;
      }
    }
    if (context && context.use_count() == 1) {
      context->release(&result.cleanup);
    }
    context.reset();
    closed = true;
  }
};

} // namespace detail

namespace {

vx_result_t capabilities(detail::RuntimeContext* context) noexcept {
  static std::atomic<uint64_t> next_device_id{1};
  auto& caps = context->capabilities;
  caps.device_id = next_device_id.fetch_add(1, std::memory_order_relaxed);
  if (caps.device_id == 0) {
    return VX_ERR_INTERNAL;
  }
  const auto query32 = [&](uint32_t id, uint32_t* out) {
    uint64_t value = 0;
    auto result = vx_device_query(context->device, id, &value);
    if (result == VX_SUCCESS) {
      if (value > std::numeric_limits<uint32_t>::max()) {
        return VX_ERR_NOT_SUPPORTED;
      }
      *out = static_cast<uint32_t>(value);
    }
    return result;
  };
  vx_result_t result = query32(VX_CAPS_NUM_THREADS, &caps.threads_per_warp);
  if (result != VX_SUCCESS) return result;
  result = query32(VX_CAPS_NUM_WARPS, &caps.warps_per_core);
  if (result != VX_SUCCESS) return result;
  result = query32(VX_CAPS_NUM_CORES, &caps.cores);
  if (result != VX_SUCCESS) return result;
  result = query32(VX_CAPS_NUM_CLUSTERS, &caps.clusters);
  if (result != VX_SUCCESS) return result;
  result = query32(VX_CAPS_ISSUE_WIDTH, &caps.issue_width);
  if (result != VX_SUCCESS) return result;
  result = vx_device_query(context->device, VX_CAPS_LOCAL_MEM_SIZE, &caps.local_mem_bytes);
  if (result != VX_SUCCESS) return result;
  uint64_t isa = 0;
  result = vx_device_query(context->device, VX_CAPS_ISA_FLAGS, &isa);
  if (result != VX_SUCCESS) return result;
  caps.address_bits = static_cast<uint32_t>(VX_ISA_ARCH(isa));
  caps.tensor_extension = (isa & VX_ISA_EXT_TCU) != 0;
  caps.local_memory = (isa & VX_ISA_EXT_LMEM) != 0;
  return VX_SUCCESS;
}

bool supported_capabilities(const DeviceCapabilities& caps) noexcept {
  return caps.address_bits == 64 && caps.threads_per_warp == 4
      && caps.warps_per_core == 4 && caps.cores == 1 && caps.clusters == 1
      && caps.issue_width == 1 && caps.local_mem_bytes == 16384
      && caps.tensor_extension && caps.local_memory;
}

MatmulRequest request_for(detail::OperationState* state, uint32_t m, uint32_t n, uint32_t k,
                         const std::array<uint64_t, 3>& addresses) noexcept {
  MatmulRequest request;
  request.a.dtype = state->context->dtype;
  request.a.dimensions = {m, k};
  request.a.strides_bytes = {uint64_t{k} * 2, 2};
  request.b.dtype = state->context->dtype;
  request.b.layout = Layout::column_major;
  request.b.dimensions = {k, n};
  request.b.strides_bytes = {2, uint64_t{k} * 2};
  request.d.dtype = DType::fp32;
  request.d.dimensions = {m, n};
  request.d.strides_bytes = {uint64_t{n} * 4, 4};
  const uint64_t device_id = state->context->capabilities.device_id;
  request.a.allocation = {device_id, 1, addresses[0], state->a.size(), true, false};
  request.b.allocation = {device_id, 2, addresses[1], state->b.size(), true, false};
  request.d.allocation = {device_id, 3, addresses[2], state->download.size(), false, true};
  return request;
}

vx_result_t write(detail::OperationState* state, vx_buffer_h buffer,
                  const std::vector<uint8_t>& data) noexcept {
  const uint32_t count = state->event_count == 0 ? 0 : 1;
  const auto* dependency = count == 0 ? nullptr : &state->events[state->event_count - 1];
  auto result = vx_enqueue_write(state->queue, buffer, 0, data.data(), data.size(), count,
                                 dependency, &state->events[state->event_count]);
  if (result == VX_SUCCESS) {
    ++state->event_count;
    ++state->trace.writes_enqueued;
    state->result.complete = false;
  }
  return result;
}

vx_result_t submit(detail::OperationState* state, uint32_t m, uint32_t n, uint32_t k) noexcept {
  auto result = vx_queue_create(state->context->device, nullptr, &state->queue);
  if (result != VX_SUCCESS) return result;
  const std::array<size_t, 3> sizes{state->a.size(), state->b.size(), state->download.size()};
  std::array<uint64_t, 3> addresses{};
  for (size_t i = 0; i != state->buffers.size(); ++i) {
    const uint32_t access = i == 2 ? VX_MEM_WRITE : VX_MEM_READ;
    result = vx_buffer_create(state->context->device, sizes[i], access, &state->buffers[i]);
    if (result != VX_SUCCESS) return result;
    result = vx_buffer_address(state->buffers[i], &addresses[i]);
    if (result != VX_SUCCESS) return result;
  }
  state->result.validation = plan_matmul(request_for(state, m, n, k, addresses),
                                       state->context->capabilities,
                                       state->context->profile, &state->plan);
  if (state->result.validation != Status::success) return VX_SUCCESS;
  state->trace.a_address = addresses[0];
  state->trace.b_address = addresses[1];
  state->trace.d_address = addresses[2];
  state->trace.argument_bytes = state->plan.argument_bytes;
  result = write(state, state->buffers[0], state->a);
  if (result != VX_SUCCESS) return result;
  result = write(state, state->buffers[1], state->b);
  if (result != VX_SUCCESS) return result;
  result = write(state, state->buffers[2], state->download);
  if (result != VX_SUCCESS) return result;
  vx_launch_info_t launch{};
  launch.struct_size = sizeof(launch);
  launch.kernel = state->context->kernel;
  launch.args_host = state->plan.argument_bytes.data();
  launch.args_size = state->plan.argument_bytes.size();
  launch.ndim = 2;
  std::copy(state->plan.grid.begin(), state->plan.grid.end(), launch.grid_dim);
  std::copy(state->plan.block.begin(), state->plan.block.end(), launch.block_dim);
  launch.lmem_size = state->plan.local_mem_bytes;
  std::fill(std::begin(launch.cluster_dim), std::end(launch.cluster_dim), 1);
  result = vx_enqueue_launch(state->queue, &launch, 1, &state->events[state->event_count - 1],
                             &state->events[state->event_count]);
  if (result != VX_SUCCESS) return result;
  ++state->event_count;
  ++state->trace.launches_enqueued;
  result = vx_enqueue_read(state->queue, state->download.data(), state->buffers[2], 0,
                           state->download.size(), 1, &state->events[state->event_count - 1],
                           &state->events[state->event_count]);
  if (result != VX_SUCCESS) return result;
  ++state->event_count;
  ++state->trace.reads_enqueued;
  state->submitted_all = true;
  return VX_SUCCESS;
}

} // namespace

ManagedMatmul::ManagedMatmul(std::shared_ptr<detail::RuntimeContext> context)
    : context_(std::move(context)) {}

ManagedMatmul::~ManagedMatmul() = default;

ExecutionResult ManagedMatmul::create(const ExecutionBinding& binding,
                                     std::unique_ptr<ManagedMatmul>* out) noexcept {
  if (!out || *out || !binding.module_bytes || binding.module_size < 16
      || !qualified_id(binding.qualification_id)) {
    return rejected(Status::invalid_argument);
  }
  if (binding.profile.profile != Profile::p02_tfr_wmma_v1
      || !binding.profile.verified_device_profile || !binding.profile.verified_kernel_profile) {
    return rejected(Status::unsupported_profile);
  }
  if (binding.input_dtype != DType::fp16 && binding.input_dtype != DType::bf16) {
    return rejected(Status::unsupported_dtype);
  }
  ExecutionResult result;
  std::shared_ptr<detail::RuntimeContext> context;
  try {
    context = std::make_shared<detail::RuntimeContext>();
    context->profile = binding.profile;
    context->dtype = binding.input_dtype;
    context->qualification_id = binding.qualification_id;
    const auto* first = static_cast<const uint8_t*>(binding.module_bytes);
    context->image.assign(first, first + binding.module_size);
    result.primary = vx_device_open(0, &context->device);
    if (result.ok()) result.primary = capabilities(context.get());
    if (result.ok() && !supported_capabilities(context->capabilities)) {
      result.validation = Status::unsupported_profile;
    }
    if (result.ok()) {
      result.primary = vx_module_load_bytes(context->device, context->image.data(),
                                            context->image.size(), &context->module);
    }
    if (result.ok()) {
      result.primary = vx_module_get_kernel(context->module, "main", &context->kernel);
    }
    if (result.ok()) {
      std::unique_ptr<ManagedMatmul> owner(new ManagedMatmul(context));
      *out = std::move(owner);
      return result;
    }
  } catch (const std::bad_alloc&) {
    result.primary = VX_ERR_OUT_OF_HOST_MEMORY;
  } catch (...) {
    result.primary = VX_ERR_INTERNAL;
  }
  if (context) context->release(&result.cleanup);
  return result;
}

ExecutionResult ManagedMatmul::submit(uint32_t m, uint32_t n, uint32_t k,
                                     const void* a, size_t a_bytes,
                                     const void* b, size_t b_bytes, uint32_t poison,
                                     std::unique_ptr<MatmulOperation>* out) noexcept {
  if (!context_ || !context_->device || !out || *out || !a || !b) {
    return rejected(Status::invalid_argument);
  }
  if (!supported_shape(m, n, k)) return rejected(Status::unsupported_shape);
  if (a_bytes != uint64_t{m} * k * 2 || b_bytes != uint64_t{k} * n * 2) {
    return rejected(Status::insufficient_buffer);
  }
  ExecutionResult result;
  std::unique_ptr<MatmulOperation> operation;
  try {
    operation.reset(new MatmulOperation(context_));
    auto& state = *operation->state_;
    state.trace.qualification_id = context_->qualification_id;
    state.trace.input_dtype = context_->dtype;
    state.trace.m = m;
    state.trace.n = n;
    state.trace.k = k;
    state.trace.poison = poison;
    state.trace.a_bytes = a_bytes;
    state.trace.b_bytes = b_bytes;
    state.trace.d_bytes = uint64_t{m} * n * 4;
    state.a.assign(static_cast<const uint8_t*>(a), static_cast<const uint8_t*>(a) + a_bytes);
    state.b.assign(static_cast<const uint8_t*>(b), static_cast<const uint8_t*>(b) + b_bytes);
    state.download.resize(state.trace.d_bytes);
    state.output.resize(uint64_t{m} * n);
    for (size_t i = 0; i != state.output.size(); ++i) {
      put_word(state.download.data() + i * 4, poison);
    }
    state.result.primary = vortex::ai::submit(&state, m, n, k);
    result = state.result;
    if (state.result.complete) result = operation->close(0);
    *out = std::move(operation);
    return result;
  } catch (const std::bad_alloc&) {
    result.primary = VX_ERR_OUT_OF_HOST_MEMORY;
  } catch (...) {
    result.primary = VX_ERR_INTERNAL;
  }
  if (operation) {
    operation->state_->result = result;
    result = operation->close(0);
  }
  return result;
}

vx_result_t ManagedMatmul::memory_info(uint64_t* free_bytes, uint64_t* used_bytes) const noexcept {
  if (!context_ || !context_->device) return VX_ERR_INVALID_HANDLE;
  return vx_device_memory_info(context_->device, free_bytes, used_bytes);
}

ExecutionResult ManagedMatmul::close() noexcept {
  ExecutionResult result;
  if (!context_) return result;
  if (context_.use_count() != 1) {
    result.primary = VX_ERR_TIMEOUT;
    result.complete = false;
    return result;
  }
  context_->release(&result.cleanup);
  context_.reset();
  return result;
}

MatmulOperation::MatmulOperation(std::shared_ptr<detail::RuntimeContext> context)
    : state_(new detail::OperationState) {
  state_->context = std::move(context);
}

MatmulOperation::~MatmulOperation() {
  while (!close(VX_TIMEOUT_INFINITE).complete) {
    // An unestablished device timeout cannot authorize freeing active buffers.
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
}

ExecutionResult MatmulOperation::wait(uint64_t timeout_ns) noexcept {
  auto& state = *state_;
  if (state.closed || state.result.complete) return state.result;
  ++state.trace.wait_calls;
  const auto event = state.events[state.event_count - 1];
  const auto wait_result = vx_event_wait_value(event, 1, timeout_ns);
  if (wait_result == VX_ERR_TIMEOUT) {
    ++state.trace.timed_out_waits;
    auto result = state.result;
    if (result.primary == VX_SUCCESS) result.primary = VX_ERR_TIMEOUT;
    return result;
  }
  uint64_t value = 0;
  const auto value_result = vx_event_get_value(event, &value);
  if (value_result != VX_SUCCESS || value < 1) {
    auto result = state.result;
    if (result.primary == VX_SUCCESS) {
      result.primary = value_result != VX_SUCCESS ? value_result : VX_ERR_INTERNAL;
    }
    return result;
  }
  remember(wait_result, &state.result.primary);
  state.result.complete = true;
  for (size_t i = 0; i != state.event_count; ++i) {
    state.trace.event_results[i] = vx_event_wait_value(state.events[i], 1, 0);
    remember(state.trace.event_results[i], &state.result.primary);
  }
  if (state.submitted_all && state.result.ok()) {
    for (size_t i = 0; i != state.output.size(); ++i) {
      state.output[i] = get_word(state.download.data() + i * 4);
    }
    state.output_valid = true;
  }
  return state.result;
}

ExecutionResult MatmulOperation::close(uint64_t timeout_ns) noexcept {
  auto& state = *state_;
  auto result = wait(timeout_ns);
  if (result.complete && !state.closed) {
    state.release();
    result = state.result;
  }
  return result;
}

const std::vector<uint32_t>& MatmulOperation::output_words() const noexcept {
  static const std::vector<uint32_t> empty;
  return state_->output_valid ? state_->output : empty;
}

const MatmulTrace& MatmulOperation::trace() const noexcept {
  return state_->trace;
}

} // namespace vortex::ai
