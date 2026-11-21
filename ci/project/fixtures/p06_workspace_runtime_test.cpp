// SPDX-License-Identifier: Apache-2.0

#include "runtime.h"
#include <deque>
#include <tuple>

// Reuse the deferred fake C API without changing the historical fixture.
#define main p03_managed_runtime_fixture_main
#define vx_buffer_create p03_fixture_buffer_create
#define vx_buffer_release p03_fixture_buffer_release
#define vx_enqueue_write p03_fixture_enqueue_write
#define vx_enqueue_launch p03_fixture_enqueue_launch
#define vx_event_wait_value p03_fixture_event_wait_value
#define vx_event_get_value p03_fixture_event_get_value
#define vx_event_release p03_fixture_event_release
#define vx_queue_release p03_fixture_queue_release
#define vx_kernel_release p03_fixture_kernel_release
#define vx_module_release p03_fixture_module_release
#define vx_device_release p03_fixture_device_release
#include "p03_managed_runtime_test.cpp"
#undef main
#undef vx_buffer_create
#undef vx_buffer_release
#undef vx_enqueue_write
#undef vx_enqueue_launch
#undef vx_event_wait_value
#undef vx_event_get_value
#undef vx_event_release
#undef vx_queue_release
#undef vx_kernel_release
#undef vx_module_release
#undef vx_device_release

namespace {

constexpr vx_result_t kCleanupFailure = VX_ERR_INVALID_VALUE;

struct ReleaseFault {
  std::string name;
  int ordinal;
  vx_result_t result;
};

struct WaitObservation {
  vx_result_t result;
  bool drain;
};

struct ValueObservation {
  vx_result_t result;
  uint64_t value;
};

struct WorkspaceAudit {
  int buffer_creations = 0;
  int buffer_releases = 0;
  int launches_observed = 0;
  std::vector<uint64_t> allocation_sizes;
  std::vector<uint32_t> allocation_flags;
  std::map<std::string, int> releases;
  std::vector<std::string> release_order;
  std::vector<ReleaseFault> release_faults;
  std::deque<WaitObservation> waits;
  std::deque<ValueObservation> values;
} audit;

struct Payload {
  std::vector<uint8_t> a;
  std::vector<uint8_t> b;
  std::vector<uint8_t> d;
  uint32_t marker = 0;
} payload;

vx_result_t released(const std::string& name, vx_result_t result) {
  const int ordinal = ++audit.releases[name];
  audit.release_order.push_back(name);
  for (const auto& fault : audit.release_faults) {
    if (fault.name == name && fault.ordinal == ordinal) {
      return fault.result;
    }
  }
  return result;
}

Buffer* at_address(uint64_t address) {
  const auto found = std::find_if(state.buffers.begin(), state.buffers.end(),
      [address](const Buffer* buffer) { return buffer->address == address; });
  check(found != state.buffers.end());
  return *found;
}

uint64_t argument_address(const ArgumentBytes& bytes, size_t offset) {
  uint64_t value = 0;
  for (unsigned i = 0; i != 8; ++i) {
    value |= uint64_t{bytes[offset + i]} << (i * 8);
  }
  return value;
}

void write_word(uint8_t* bytes, uint32_t word) {
  for (unsigned i = 0; i != 4; ++i) {
    bytes[i] = static_cast<uint8_t>(word >> (i * 8));
  }
}

} // namespace

extern "C" {

vx_result_t vx_buffer_create(vx_device_h device, uint64_t size, uint32_t flags,
                             vx_buffer_h* out) {
  const auto result = p03_fixture_buffer_create(device, size, flags, out);
  if (result == VX_SUCCESS) {
    ++audit.buffer_creations;
    audit.allocation_sizes.push_back(size);
    audit.allocation_flags.push_back(flags);
  }
  return result;
}

vx_result_t vx_buffer_release(vx_buffer_h buffer) {
  check(state.queues == 0 && state.events == 0);
  ++audit.buffer_releases;
  return released("buffer", p03_fixture_buffer_release(buffer));
}

vx_result_t vx_event_release(vx_event_h event) {
  check(event->done);
  return released("event", p03_fixture_event_release(event));
}

vx_result_t vx_queue_release(vx_queue_h queue) {
  return released("queue", p03_fixture_queue_release(queue));
}

vx_result_t vx_kernel_release(vx_kernel_h kernel) {
  check(state.buffers.empty());
  return released("kernel", p03_fixture_kernel_release(kernel));
}

vx_result_t vx_module_release(vx_module_h module) {
  return released("module", p03_fixture_module_release(module));
}

vx_result_t vx_device_release(vx_device_h device) {
  return released("device", p03_fixture_device_release(device));
}

vx_result_t vx_enqueue_write(vx_queue_h queue, vx_buffer_h handle, uint64_t offset,
                             const void* source, uint64_t size, uint32_t count,
                             const vx_event_h* waits, vx_event_h* out) {
  auto* buffer = static_cast<Buffer*>(handle);
  const size_t ordinal = queue->events.size();
  check(offset == 0 && size == buffer->bytes.size() && ordinal < 3);
  const auto expected = ordinal == 0 ? payload.a : ordinal == 1 ? payload.b : payload.d;
  check(expected.size() == size);
  return enqueue(queue, count, waits, out, [buffer, source, size, expected] {
    const auto* first = static_cast<const uint8_t*>(source);
    check(std::equal(expected.begin(), expected.end(), first));
    std::memcpy(buffer->bytes.data(), source, size);
    ++state.writes_observed;
  });
}

vx_result_t vx_enqueue_launch(vx_queue_h queue, const vx_launch_info_t* info,
                              uint32_t count, const vx_event_h* waits, vx_event_h* out) {
  ArgumentBytes arguments{};
  check(info->args_size == arguments.size());
  std::memcpy(arguments.data(), info->args_host, arguments.size());
  const auto expected = payload;
  const auto result = p03_fixture_enqueue_launch(queue, info, count, waits, out);
  if (result == VX_SUCCESS) {
    auto original = std::move((*out)->work);
    (*out)->work = [arguments, expected, original] {
      auto* a = at_address(argument_address(arguments, 32));
      auto* b = at_address(argument_address(arguments, 40));
      auto* d = at_address(argument_address(arguments, 48));
      check(a->bytes == expected.a && b->bytes == expected.b && d->bytes == expected.d);
      original();
      // Mark data lineage only; these words do not model matrix arithmetic.
      for (size_t i = 0; i != d->bytes.size() / 4; ++i) {
        write_word(d->bytes.data() + i * 4, expected.marker + static_cast<uint32_t>(i));
      }
      ++audit.launches_observed;
    };
  }
  return result;
}

vx_result_t vx_event_wait_value(vx_event_h event, uint64_t value, uint64_t timeout) {
  if (audit.waits.empty()) {
    return p03_fixture_event_wait_value(event, value, timeout);
  }
  check(value == 1);
  const auto observation = audit.waits.front();
  audit.waits.pop_front();
  if (observation.drain) {
    drain(event->queue);
  }
  return observation.result;
}

vx_result_t vx_event_get_value(vx_event_h event, uint64_t* out) {
  if (audit.values.empty()) {
    return p03_fixture_event_get_value(event, out);
  }
  const auto observation = audit.values.front();
  audit.values.pop_front();
  *out = observation.value;
  return observation.result;
}

} // extern "C"

namespace {

bool resident(WorkspacePolicy policy) {
  return policy == WorkspacePolicy::reusable_single_tile;
}

void reset_workspace() {
  reset();
  audit = WorkspaceAudit{};
  payload = Payload{};
}

auto footprint() {
  return std::make_tuple(state.devices, state.modules, state.kernels, state.queues,
      state.events, state.buffers.size(), state.calls, audit.buffer_creations,
      audit.buffer_releases, audit.releases);
}

ExecutionBinding workspace_binding(WorkspacePolicy policy, DType dtype) {
  auto value = binding(dtype);
  value.workspace_policy = policy;
  return value;
}

std::unique_ptr<ManagedMatmul> workspace_owner(WorkspacePolicy policy, DType dtype) {
  std::unique_ptr<ManagedMatmul> owner;
  const auto result = ManagedMatmul::create(workspace_binding(policy, dtype), &owner);
  check(result.ok() && result.complete && owner);
  check(state.devices == 1 && state.modules == 1 && state.kernels == 1);
  check(state.queues == 0 && state.events == 0);
  check(state.buffers.size() == (resident(policy) ? 3u : 0u));
  return owner;
}

uint32_t output_marker(uint32_t sequence) {
  return 0x42000000u + sequence * 256;
}

ExecutionResult workspace_submit(ManagedMatmul* owner,
                                 std::unique_ptr<MatmulOperation>* operation,
                                 uint32_t sequence = 1, uint32_t m = 8,
                                 uint32_t n = 4, uint32_t k = 8) {
  std::vector<uint8_t> a(size_t{m} * k * 2);
  std::vector<uint8_t> b(size_t{k} * n * 2);
  for (size_t i = 0; i != a.size(); ++i) {
    a[i] = static_cast<uint8_t>(sequence * 13 + i * 3 + 0x12);
  }
  for (size_t i = 0; i != b.size(); ++i) {
    b[i] = static_cast<uint8_t>(sequence * 19 + i * 5 + 0x34);
  }
  const uint32_t poison = sequence % 2 ? 0x7fc0dead : 0xdeadbeef;
  payload = {a, b, std::vector<uint8_t>(size_t{m} * n * 4), output_marker(sequence)};
  for (size_t i = 0; i != payload.d.size(); i += 4) {
    write_word(payload.d.data() + i, poison);
  }
  const auto result = owner->submit(m, n, k, a.data(), a.size(), b.data(), b.size(),
                                     poison, operation);
  std::fill(a.begin(), a.end(), 0);
  std::fill(b.begin(), b.end(), 0);
  return result;
}

void check_output(const MatmulOperation& operation, uint32_t sequence, size_t words = 32) {
  check(operation.output_words().size() == words);
  for (size_t i = 0; i != words; ++i) {
    check(operation.output_words()[i] == output_marker(sequence) + i);
  }
}

void check_idle_buffers(WorkspacePolicy policy) {
  check(state.queues == 0 && state.events == 0);
  check(state.buffers.size() == (resident(policy) ? 3u : 0u));
}

void busy_create(WorkspacePolicy policy, DType dtype) {
  const auto before = footprint();
  std::unique_ptr<ManagedMatmul> competing;
  const auto result = ManagedMatmul::create(workspace_binding(policy, dtype), &competing);
  check(!competing && result.validation == Status::success && result.complete);
  check(result.primary == VX_ERR_TIMEOUT && result.cleanup == VX_SUCCESS);
  check(footprint() == before);
}

void busy_submit(ManagedMatmul* owner) {
  const auto before = footprint();
  std::unique_ptr<MatmulOperation> competing;
  const auto result = workspace_submit(owner, &competing, 99);
  check(!competing && result.validation == Status::success && result.complete);
  check(result.primary == VX_ERR_TIMEOUT && result.cleanup == VX_SUCCESS);
  check(footprint() == before);
}

void busy_owner_close(ManagedMatmul* owner) {
  const auto before = footprint();
  const auto result = owner->close();
  check(result.primary == VX_ERR_TIMEOUT && result.cleanup == VX_SUCCESS && !result.complete);
  check(footprint() == before);
}

void clean_operation(ManagedMatmul* owner, uint32_t sequence = 1) {
  std::unique_ptr<MatmulOperation> operation;
  const auto submitted = workspace_submit(owner, &operation, sequence);
  check(submitted.ok() && !submitted.complete && operation);
  const auto closed = operation->close(VX_TIMEOUT_INFINITE);
  check(closed.ok() && closed.complete);
  check_output(*operation, sequence);
}

void context_lease(WorkspacePolicy policy, DType dtype) {
  auto owner = workspace_owner(policy, dtype);
  for (const auto other_policy : {WorkspacePolicy::per_operation,
                                  WorkspacePolicy::reusable_single_tile}) {
    for (const auto other_dtype : {DType::fp16, DType::bf16}) {
      busy_create(other_policy, other_dtype);
    }
  }
  check(owner->close().ok() && owner->close().ok());
  no_resources();
  auto next = workspace_owner(policy, dtype);
  check(next->close().ok());
}

void operation_lease(WorkspacePolicy policy, DType dtype) {
  auto owner = workspace_owner(policy, dtype);
  std::unique_ptr<MatmulOperation> operation;
  check(workspace_submit(owner.get(), &operation).ok());
  busy_submit(owner.get());
  const auto before = footprint();
  std::unique_ptr<MatmulOperation> invalid;
  const auto rejected = workspace_submit(owner.get(), &invalid, 2, 9, 4, 8);
  check(rejected.validation == Status::unsupported_shape && rejected.complete && !invalid);
  check(footprint() == before);
  busy_submit(owner.get());
  const auto waited = operation->wait(VX_TIMEOUT_INFINITE);
  check(waited.ok() && waited.complete);
  check_output(*operation, 1);
  busy_submit(owner.get());
  busy_create(policy, dtype);
  busy_owner_close(owner.get());
  check(operation->close(0).ok() && operation->close(0).ok());
  check_idle_buffers(policy);
  clean_operation(owner.get(), 2);
  check_output(*operation, 1);
  check(owner->close().ok());
}

void timeout_retention(WorkspacePolicy policy, DType dtype) {
  auto owner = workspace_owner(policy, dtype);
  std::unique_ptr<MatmulOperation> operation;
  check(workspace_submit(owner.get(), &operation).ok());
  state.timeout_budget = 1;
  const auto timed_out = operation->close(0);
  check(timed_out.primary == VX_ERR_TIMEOUT && !timed_out.complete);
  check(timed_out.cleanup == VX_SUCCESS && operation->output_words().empty());
  check(state.buffers.size() == 3 && state.queues == 1 && state.events == 5);
  busy_submit(owner.get());
  busy_create(policy, dtype);
  busy_owner_close(owner.get());
  const auto drained = operation->close(VX_TIMEOUT_INFINITE);
  check(drained.ok() && drained.complete && operation->trace().timed_out_waits == 1);
  check_output(*operation, 1);
  check_idle_buffers(policy);
  clean_operation(owner.get(), 2);
  check(owner->close().ok());
}

void owner_destruction(WorkspacePolicy policy, DType dtype) {
  for (const bool waited : {false, true}) {
    auto owner = workspace_owner(policy, dtype);
    std::unique_ptr<MatmulOperation> operation;
    check(workspace_submit(owner.get(), &operation).ok());
    if (waited) {
      check(operation->wait(VX_TIMEOUT_INFINITE).ok());
    }
    owner.reset();
    check(state.devices == 1 && state.modules == 1 && state.kernels == 1);
    check(state.buffers.size() == 3 && state.queues == 1 && state.events == 5);
    busy_create(policy, dtype);
    if (!waited) {
      state.timeout_budget = 1;
      check(!operation->close(0).complete);
      busy_create(policy, dtype);
    }
    const auto drained = operation->close(VX_TIMEOUT_INFINITE);
    check(drained.ok() && drained.complete);
    check_output(*operation, 1);
    no_resources();
    auto next = workspace_owner(policy, dtype);
    check(next->close().ok());
    reset_workspace();
  }
}

void serial_reuse(WorkspacePolicy policy, DType dtype) {
  auto owner = workspace_owner(policy, dtype);
  uint64_t initial_free = 0, initial_used = 0;
  check(owner->memory_info(&initial_free, &initial_used) == VX_SUCCESS);
  check(initial_used == (resident(policy) ? 320u : 0u));
  std::array<uint64_t, 3> first_addresses{};
  std::vector<std::unique_ptr<MatmulOperation>> completed;
  for (uint32_t sequence = 1; sequence <= 32; ++sequence) {
    std::unique_ptr<MatmulOperation> operation;
    const auto submitted = workspace_submit(owner.get(), &operation, sequence);
    check(submitted.ok() && !submitted.complete && operation->output_words().empty());
    check(state.buffers.size() == 3 && state.queues == 1 && state.events == 5);
    const auto& trace = operation->trace();
    const std::array<uint64_t, 3> addresses{trace.a_address, trace.b_address, trace.d_address};
    check(trace.a_bytes == 128 && trace.b_bytes == 64 && trace.d_bytes == 128);
    check(trace.m == 8 && trace.n == 4 && trace.k == 8 && trace.input_dtype == dtype);
    check(trace.poison == (sequence % 2 ? 0x7fc0deadu : 0xdeadbeefu));
    check(trace.qualification_id == std::string(64, 'a'));
    check(trace.writes_enqueued == 3 && trace.launches_enqueued == 1 && trace.reads_enqueued == 1);
    check(addresses[0] != addresses[1] && addresses[0] != addresses[2]
          && addresses[1] != addresses[2]);
    for (size_t i = 0; i != addresses.size(); ++i) {
      check(argument_address(trace.argument_bytes, 32 + i * 8) == addresses[i]);
    }
    if (sequence == 1) {
      first_addresses = addresses;
    } else if (resident(policy)) {
      check(addresses == first_addresses);
    }
    check(operation->wait(VX_TIMEOUT_INFINITE).ok());
    check_output(*operation, sequence);
    busy_submit(owner.get());
    const auto closed = operation->close(0);
    check(closed.ok() && closed.complete);
    check_idle_buffers(policy);
    check(audit.buffer_creations == (resident(policy) ? 3 : int(sequence * 3)));
    check(audit.buffer_releases == (resident(policy) ? 0 : int(sequence * 3)));
    uint64_t current_free = 0, current_used = 0;
    check(owner->memory_info(&current_free, &current_used) == VX_SUCCESS);
    check(current_free == initial_free && current_used == initial_used);
    completed.push_back(std::move(operation));
    for (size_t i = 0; i != completed.size(); ++i) {
      check_output(*completed[i], static_cast<uint32_t>(i + 1));
      check(completed[i]->trace().poison == ((i + 1) % 2 ? 0x7fc0deadu : 0xdeadbeefu));
    }
  }
  check(state.writes_observed == 96 && audit.launches_observed == 32);
  check(state.calls["enqueue"] == 160 && state.calls["queue_create"] == 32);
  check(state.default_queues == 32 && state.profiled_queues == 0);
  for (size_t i = 0; i != audit.allocation_sizes.size(); ++i) {
    check(audit.allocation_sizes[i] == (i % 3 == 1 ? 64u : 128u));
    check(audit.allocation_flags[i] == (i % 3 == 2 ? VX_MEM_WRITE : VX_MEM_READ));
  }
  check(owner->close().ok());
  check(audit.buffer_releases == audit.buffer_creations);
}

void policy_validation(WorkspacePolicy policy, DType dtype) {
  check(binding(dtype).workspace_policy == WorkspacePolicy::per_operation);
  auto unknown = workspace_binding(static_cast<WorkspacePolicy>(99), dtype);
  std::unique_ptr<ManagedMatmul> rejected_owner;
  const auto before = footprint();
  const auto unknown_result = ManagedMatmul::create(unknown, &rejected_owner);
  check(unknown_result.validation == Status::invalid_argument && unknown_result.complete);
  check(unknown_result.primary == VX_SUCCESS && unknown_result.cleanup == VX_SUCCESS);
  check(!rejected_owner && footprint() == before);
  auto owner = workspace_owner(policy, dtype);
  for (const auto shape : {std::array<uint32_t, 3>{8,4,8}, {8,4,16}, {16,8,16}}) {
    const auto before_submit = footprint();
    std::unique_ptr<MatmulOperation> operation;
    const auto result = workspace_submit(owner.get(), &operation, 1, shape[0], shape[1], shape[2]);
    if (resident(policy) && shape[2] != 8) {
      check(result.validation == Status::unsupported_shape && result.complete && !operation);
      check(result.primary == VX_SUCCESS && result.cleanup == VX_SUCCESS);
      check(footprint() == before_submit);
    } else {
      check(result.ok() && operation && !result.complete);
      check(operation->close(VX_TIMEOUT_INFINITE).ok());
      check_output(*operation, 1, size_t{shape[0]} * shape[1]);
      check_idle_buffers(policy);
    }
  }
  std::vector<uint8_t> a(128), b(65);
  for (int fault = 0; fault != 3; ++fault) {
    const auto before_submit = footprint();
    std::unique_ptr<MatmulOperation> operation;
    const auto result = owner->submit(8, 4, 8, fault == 0 ? nullptr : a.data(),
        fault == 1 ? 127 : 128, b.data(), fault == 2 ? 65 : 64, 0, &operation);
    check(result.validation == (fault == 0 ? Status::invalid_argument : Status::insufficient_buffer));
    check(result.complete && !operation && footprint() == before_submit);
  }
  clean_operation(owner.get());
  check(owner->close().ok());
}

void setup_rollback(WorkspacePolicy policy, DType dtype) {
  const std::vector<std::pair<std::string, int>> failures{
      {"device_open", 1}, {"query", 7}, {"module_load", 1}, {"get_kernel", 1},
      {"buffer_create", resident(policy) ? 3 : 0},
      {"buffer_address", resident(policy) ? 3 : 0}};
  for (const auto& failure : failures) {
    for (int at = 1; at <= failure.second; ++at) {
      state.fail_call = failure.first;
      state.fail_at = at;
      std::unique_ptr<ManagedMatmul> owner;
      const auto result = ManagedMatmul::create(workspace_binding(policy, dtype), &owner);
      const auto expected = failure.first == "module_load" || failure.first == "buffer_create"
          ? VX_ERR_OUT_OF_DEVICE_MEMORY : failure.first == "get_kernel"
          ? VX_ERR_NOT_SUPPORTED : VX_ERR_DEVICE_LOST;
      check(!owner && result.primary == expected && result.complete && result.cleanup == VX_SUCCESS);
      no_resources();
      check(audit.buffer_creations == audit.buffer_releases);
      state.fail_call.clear();
      auto next = workspace_owner(policy, dtype);
      check(next->close().ok());
      reset_workspace();
    }
  }
}

void address_validation(WorkspacePolicy policy, DType dtype) {
  for (int mode = 1; mode <= 3; ++mode) {
    const auto expected = mode == 1 ? Status::misaligned_address
        : mode == 2 ? Status::aliasing : Status::address_out_of_range;
    if (resident(policy)) {
      state.bad_address = mode;
      std::unique_ptr<ManagedMatmul> owner;
      const auto result = ManagedMatmul::create(workspace_binding(policy, dtype), &owner);
      check(result.validation == expected && result.complete && !owner);
      check(result.cleanup == VX_SUCCESS && state.calls["enqueue"] == 0);
      no_resources();
      state.bad_address = 0;
      auto next = workspace_owner(policy, dtype);
      clean_operation(next.get());
      check(next->close().ok());
    } else {
      auto owner = workspace_owner(policy, dtype);
      state.bad_address = mode;
      std::unique_ptr<MatmulOperation> operation;
      const auto result = workspace_submit(owner.get(), &operation);
      check(result.validation == expected && result.complete && operation);
      check(result.cleanup == VX_SUCCESS && state.calls["enqueue"] == 0);
      check_idle_buffers(policy);
      state.bad_address = 0;
      clean_operation(owner.get());
      check(owner->close().ok());
    }
    reset_workspace();
  }
}

void partial_rollback(WorkspacePolicy policy, DType dtype) {
  const std::vector<std::pair<std::string, int>> failures{
      {"queue_create", 1}, {"buffer_create", resident(policy) ? 0 : 3},
      {"buffer_address", resident(policy) ? 0 : 3}, {"enqueue", 5}};
  for (const auto& failure : failures) {
    for (int at = 1; at <= failure.second; ++at) {
      auto owner = workspace_owner(policy, dtype);
      state.fail_call = failure.first;
      state.fail_at = state.calls[failure.first] + at;
      std::unique_ptr<MatmulOperation> operation;
      const auto submitted = workspace_submit(owner.get(), &operation);
      const auto expected = failure.first == "buffer_create" ? VX_ERR_OUT_OF_DEVICE_MEMORY
          : failure.first == "buffer_address" ? VX_ERR_DEVICE_LOST : VX_ERR_OUT_OF_HOST_MEMORY;
      check(operation && submitted.primary == expected && submitted.cleanup == VX_SUCCESS);
      const bool partial = failure.first == "enqueue" && at > 1;
      check(submitted.complete != partial && operation->output_words().empty());
      if (partial) {
        check(state.events == at - 1 && state.queues == 1 && state.buffers.size() == 3);
        state.timeout_budget = 1;
        const auto timeout = operation->close(0);
        check(!timeout.complete && timeout.primary == expected && timeout.cleanup == VX_SUCCESS);
        busy_submit(owner.get());
        busy_create(policy, dtype);
        busy_owner_close(owner.get());
        if (at % 2 == 0) {
          owner.reset();
          busy_create(policy, dtype);
        }
      }
      const auto result = operation->close(VX_TIMEOUT_INFINITE);
      check(result.complete && result.primary == expected && result.cleanup == VX_SUCCESS);
      check(operation->output_words().empty());
      state.fail_call.clear();
      if (owner) {
        check_idle_buffers(policy);
        clean_operation(owner.get(), 2);
        check(owner->close().ok());
      } else {
        no_resources();
        auto next = workspace_owner(policy, dtype);
        check(next->close().ok());
      }
      reset_workspace();
    }
  }
}

void completion_observation(WorkspacePolicy policy, DType dtype) {
  for (int mode = 0; mode != 4; ++mode) {
    auto owner = workspace_owner(policy, dtype);
    std::unique_ptr<MatmulOperation> operation;
    check(workspace_submit(owner.get(), &operation).ok());
    audit.waits.push_back({mode < 2 ? VX_ERR_DEVICE_LOST : VX_SUCCESS, mode >= 2});
    audit.values.push_back({mode % 2 == 0 ? VX_ERR_INVALID_VALUE : VX_SUCCESS, 0});
    const auto expected = mode < 2 ? VX_ERR_DEVICE_LOST
        : mode == 2 ? VX_ERR_INVALID_VALUE : VX_ERR_INTERNAL;
    const auto first = operation->wait(0);
    check(first.primary == expected && !first.complete && first.cleanup == VX_SUCCESS);
    check(operation->output_words().empty() && state.events == 5 && state.buffers.size() == 3);
    busy_submit(owner.get());
    audit.values.push_back({VX_ERR_NOT_SUPPORTED, 0});
    const auto second = operation->wait(0);
    check(second.primary == expected && !second.complete && operation->output_words().empty());
    busy_owner_close(owner.get());
    const auto drained = operation->close(VX_TIMEOUT_INFINITE);
    check(drained.primary == expected && drained.complete && drained.cleanup == VX_SUCCESS);
    check(operation->output_words().empty());
    check_idle_buffers(policy);
    clean_operation(owner.get(), 2);
    check(owner->close().ok());
    reset_workspace();
  }
}

void poisoned_create(WorkspacePolicy policy, DType dtype) {
  const auto before = footprint();
  std::unique_ptr<ManagedMatmul> rejected_owner;
  const auto result = ManagedMatmul::create(workspace_binding(policy, dtype), &rejected_owner);
  check(!rejected_owner && result.validation == Status::success && result.complete);
  check(result.primary == VX_ERR_INTERNAL && result.cleanup == kCleanupFailure);
  check(footprint() == before);
}

void poisoned_submit(ManagedMatmul* owner) {
  const auto before = footprint();
  std::unique_ptr<MatmulOperation> rejected_operation;
  const auto result = workspace_submit(owner, &rejected_operation, 99);
  check(!rejected_operation && result.validation == Status::success && result.complete);
  check(result.primary == VX_ERR_INTERNAL && result.cleanup == kCleanupFailure);
  check(footprint() == before);
}

void sticky_owner_close(ManagedMatmul* owner) {
  const auto closed = owner->close();
  check(closed.primary == VX_SUCCESS && closed.cleanup == kCleanupFailure && closed.complete);
  const auto before = footprint();
  const auto repeated = owner->close();
  check(repeated.primary == closed.primary && repeated.cleanup == closed.cleanup && repeated.complete);
  check(footprint() == before);
}

void cleanup_operation(WorkspacePolicy policy, DType dtype, const std::string& target,
                       int ordinal, bool primary_failure, bool multiple_failures) {
  auto owner = workspace_owner(policy, dtype);
  std::unique_ptr<MatmulOperation> operation;
  if (primary_failure) {
    state.async_failure = 3;
  }
  check(workspace_submit(owner.get(), &operation).ok());
  const auto waited = operation->wait(VX_TIMEOUT_INFINITE);
  check(waited.complete && waited.primary == (primary_failure ? VX_ERR_DEVICE_LOST : VX_SUCCESS));
  if (!primary_failure) {
    check_output(*operation, 1);
  }
  audit.release_faults.push_back({target, ordinal, kCleanupFailure});
  if (multiple_failures) {
    audit.release_faults.push_back({"queue", 1, VX_ERR_DEVICE_LOST});
    audit.release_faults.push_back({"kernel", 1, VX_ERR_OUT_OF_DEVICE_MEMORY});
  }
  const auto result = operation->close(0);
  check(result.complete && result.primary == waited.primary && result.cleanup == kCleanupFailure);
  check(operation->output_words().empty());
  check_idle_buffers(policy);
  check(audit.releases["event"] == 5 && audit.releases["queue"] == 1);
  check(audit.buffer_releases == (resident(policy) ? 0 : 3));
  const auto before = footprint();
  const auto repeated = operation->close(0);
  check(repeated.primary == result.primary && repeated.cleanup == result.cleanup && repeated.complete);
  check(footprint() == before);
  poisoned_submit(owner.get());
  poisoned_create(policy, dtype);
  sticky_owner_close(owner.get());
  no_resources();
  poisoned_create(policy, dtype);
}

void cleanup_context(WorkspacePolicy policy, DType dtype, const std::string& target,
                     int ordinal, bool retained_operation) {
  auto owner = workspace_owner(policy, dtype);
  std::unique_ptr<MatmulOperation> operation;
  if (retained_operation) {
    check(workspace_submit(owner.get(), &operation).ok());
    check(operation->wait(VX_TIMEOUT_INFINITE).ok());
    check_output(*operation, 1);
    owner.reset();
    busy_create(policy, dtype);
  }
  audit.release_faults.push_back({target, ordinal, kCleanupFailure});
  if (retained_operation) {
    const auto result = operation->close(0);
    check(result.primary == VX_SUCCESS && result.cleanup == kCleanupFailure && result.complete);
    check(operation->output_words().empty());
    const auto before = footprint();
    check(operation->close(0).cleanup == kCleanupFailure && footprint() == before);
  } else {
    sticky_owner_close(owner.get());
  }
  no_resources();
  check(audit.buffer_creations == audit.buffer_releases);
  check(audit.releases["kernel"] == 1 && audit.releases["module"] == 1
        && audit.releases["device"] == 1);
  poisoned_create(policy, dtype);
}

void cleanup_destructor(WorkspacePolicy policy, DType dtype, bool operation_destructor) {
  auto owner = workspace_owner(policy, dtype);
  if (operation_destructor) {
    std::unique_ptr<MatmulOperation> operation;
    check(workspace_submit(owner.get(), &operation).ok());
    audit.release_faults.push_back({"event", 1, kCleanupFailure});
    operation.reset();
    check_idle_buffers(policy);
    poisoned_submit(owner.get());
    sticky_owner_close(owner.get());
  } else {
    audit.release_faults.push_back({"kernel", 1, kCleanupFailure});
    owner.reset();
  }
  no_resources();
  poisoned_create(policy, dtype);
}

void cleanup_rollback(WorkspacePolicy policy, DType dtype, const std::string& phase) {
  if (phase == "context" || phase == "workspace") {
    check(phase != "workspace" || resident(policy));
    state.fail_call = phase == "workspace" ? "buffer_create" : "get_kernel";
    state.fail_at = phase == "workspace" ? 2 : 1;
    audit.release_faults.push_back({phase == "workspace" ? "buffer" : "module", 1,
                                     kCleanupFailure});
    std::unique_ptr<ManagedMatmul> owner;
    const auto result = ManagedMatmul::create(workspace_binding(policy, dtype), &owner);
    check(!owner && result.complete && result.cleanup == kCleanupFailure);
    check(result.primary == (phase == "workspace" ? VX_ERR_OUT_OF_DEVICE_MEMORY : VX_ERR_NOT_SUPPORTED));
  } else {
    auto owner = workspace_owner(policy, dtype);
    state.fail_call = "enqueue";
    state.fail_at = phase == "partial" ? 3 : 1;
    audit.release_faults.push_back({phase == "partial" ? "event" : "queue", 1,
                                     kCleanupFailure});
    std::unique_ptr<MatmulOperation> operation;
    const auto submitted = workspace_submit(owner.get(), &operation);
    check(operation && submitted.primary == VX_ERR_OUT_OF_HOST_MEMORY);
    const auto result = operation->close(VX_TIMEOUT_INFINITE);
    check(result.primary == submitted.primary && result.cleanup == kCleanupFailure && result.complete);
    check(operation->output_words().empty());
    poisoned_submit(owner.get());
    sticky_owner_close(owner.get());
  }
  no_resources();
  poisoned_create(policy, dtype);
}

} // namespace

int main(int argc, char** argv) {
  if (argc < 4 || argc > 6) {
    return 2;
  }
  const std::string group = argv[1];
  const std::string policy_name = argv[2];
  const std::string dtype_name = argv[3];
  if ((policy_name != "per_operation" && policy_name != "reusable_single_tile")
      || (dtype_name != "fp16" && dtype_name != "bf16")) {
    return 2;
  }
  const auto policy = policy_name == "per_operation" ? WorkspacePolicy::per_operation
      : WorkspacePolicy::reusable_single_tile;
  const auto dtype = dtype_name == "fp16" ? DType::fp16 : DType::bf16;
  const std::string target = argc > 4 ? argv[4] : "";
  const int ordinal = argc > 5 ? std::atoi(argv[5]) : 1;
  if (group == "context_lease") {
    context_lease(policy, dtype);
  } else if (group == "operation_lease") {
    operation_lease(policy, dtype);
  } else if (group == "timeout_retention") {
    timeout_retention(policy, dtype);
  } else if (group == "owner_destruction") {
    owner_destruction(policy, dtype);
  } else if (group == "serial_reuse") {
    serial_reuse(policy, dtype);
  } else if (group == "policy_validation") {
    policy_validation(policy, dtype);
  } else if (group == "setup_rollback") {
    setup_rollback(policy, dtype);
  } else if (group == "address_validation") {
    address_validation(policy, dtype);
  } else if (group == "partial_rollback") {
    partial_rollback(policy, dtype);
  } else if (group == "completion_observation") {
    completion_observation(policy, dtype);
  } else if (group == "cleanup_operation") {
    cleanup_operation(policy, dtype, target, ordinal, false, false);
  } else if (group == "cleanup_primary") {
    cleanup_operation(policy, dtype, "event", 1, true, false);
  } else if (group == "cleanup_first") {
    cleanup_operation(policy, dtype, "event", 1, false, true);
  } else if (group == "cleanup_context" || group == "cleanup_retained_context") {
    cleanup_context(policy, dtype, target, ordinal, group == "cleanup_retained_context");
  } else if (group == "cleanup_destructor") {
    cleanup_destructor(policy, dtype, target == "operation");
  } else if (group == "cleanup_rollback") {
    cleanup_rollback(policy, dtype, target);
  } else {
    return 2;
  }
  no_resources();
  std::cout << "PASS " << group << " checks=" << checks << '\n';
  return 0;
}
