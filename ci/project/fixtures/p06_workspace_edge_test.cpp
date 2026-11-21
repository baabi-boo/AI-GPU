// SPDX-License-Identifier: Apache-2.0

#include "runtime.h"
#include <array>
#include <atomic>
#include <cstdlib>
#include <new>
#include <thread>

namespace allocation_probe {
struct OtherFailure {};
thread_local bool armed = false;
thread_local bool other_failure = false;
thread_local unsigned ordinal = 0;
thread_local unsigned fail_at = 0;
thread_local unsigned failures = 0;
thread_local unsigned excluded_allocations = 0;
thread_local unsigned native_depth = 0;
thread_local std::array<void*, 32> live{};

struct NativeScope {
  bool previous = armed;
  NativeScope() noexcept { armed = false; ++native_depth; }
  ~NativeScope() { --native_depth; armed = previous; }
};

void forget(void* value) noexcept {
  for (auto& slot : live) {
    if (slot == value) {
      slot = nullptr;
    }
  }
}

unsigned live_count() noexcept {
  unsigned count = 0;
  for (const auto slot : live) {
    count += slot != nullptr;
  }
  return count;
}
} // namespace allocation_probe

// This observes only wrapper-owned ordinary new allocations. Every fake C API
// entry disables injection, so fake-library containers cannot throw across C.
[[gnu::noinline]] void* operator new(size_t size) {
  using namespace allocation_probe;
  if (native_depth != 0) {
    ++excluded_allocations;
  }
  if (armed && ++ordinal == fail_at) {
    ++failures;
    if (other_failure) {
      throw OtherFailure{};
    }
    throw std::bad_alloc();
  }
  void* value = std::malloc(size == 0 ? 1 : size);
  if (!value) {
    throw std::bad_alloc();
  }
  if (armed) {
    bool stored = false;
    for (auto& slot : live) {
      if (!slot) {
        slot = value;
        stored = true;
        break;
      }
    }
    if (!stored) {
      std::abort();
    }
  }
  return value;
}
[[gnu::noinline]] void* operator new[](size_t size) { return ::operator new(size); }
[[gnu::noinline]] void operator delete(void* value) noexcept {
  allocation_probe::forget(value);
  std::free(value);
}
[[gnu::noinline]] void operator delete(void* value, size_t) noexcept { ::operator delete(value); }
[[gnu::noinline]] void operator delete[](void* value) noexcept { ::operator delete(value); }
[[gnu::noinline]] void operator delete[](void* value, size_t) noexcept { ::operator delete(value); }

#define main p03_edge_fixture_main
#define vx_device_open edge_fake_vx_device_open
#define vx_device_release edge_fake_vx_device_release
#define vx_device_query edge_fake_vx_device_query
#define vx_device_memory_info edge_fake_vx_device_memory_info
#define vx_module_load_bytes edge_fake_vx_module_load_bytes
#define vx_module_release edge_fake_vx_module_release
#define vx_module_get_kernel edge_fake_vx_module_get_kernel
#define vx_kernel_release edge_fake_vx_kernel_release
#define vx_queue_create edge_fake_vx_queue_create
#define vx_queue_release edge_fake_vx_queue_release
#define vx_buffer_create edge_fake_vx_buffer_create
#define vx_buffer_address edge_fake_vx_buffer_address
#define vx_buffer_release edge_fake_vx_buffer_release
#define vx_enqueue_write edge_fake_vx_enqueue_write
#define vx_enqueue_launch edge_fake_vx_enqueue_launch
#define vx_enqueue_read edge_fake_vx_enqueue_read
#define vx_event_wait_value edge_fake_vx_event_wait_value
#define vx_event_get_value edge_fake_vx_event_get_value
#define vx_event_get_profiling edge_fake_vx_event_get_profiling
#define vx_event_release edge_fake_vx_event_release
#include "p03_managed_runtime_test.cpp"
#undef main
#undef vx_device_open
#undef vx_device_release
#undef vx_device_query
#undef vx_device_memory_info
#undef vx_module_load_bytes
#undef vx_module_release
#undef vx_module_get_kernel
#undef vx_kernel_release
#undef vx_queue_create
#undef vx_queue_release
#undef vx_buffer_create
#undef vx_buffer_address
#undef vx_buffer_release
#undef vx_enqueue_write
#undef vx_enqueue_launch
#undef vx_enqueue_read
#undef vx_event_wait_value
#undef vx_event_get_value
#undef vx_event_get_profiling
#undef vx_event_release

namespace {
unsigned scenarios = 0;
std::atomic<unsigned> open_entries{0};
std::atomic<unsigned> race_returned{0};
bool race_active = false;
struct Polls {
  unsigned waits = 0;
  unsigned wait_timeout_at = 0;
  unsigned wait_error_at = 0;
  unsigned queries = 0;
  unsigned query_timeouts = 0;
  unsigned query_error_at = 0;
} polls;
} // namespace

#define FORWARD(name, signature, arguments) \
  extern "C" vx_result_t name signature { \
    allocation_probe::NativeScope excluded; \
    return edge_fake_##name arguments; \
  }

extern "C" vx_result_t vx_device_open(uint32_t index, vx_device_h* out) {
  allocation_probe::NativeScope excluded;
  const unsigned entries = open_entries.fetch_add(1, std::memory_order_relaxed) + 1;
  if (race_active) {
    // If the production reservation breaks, fail without racing the fake's
    // ordinary containers. The expected open-entry count still exposes it.
    if (entries != 1) {
      return VX_ERR_INTERNAL;
    }
    while (race_returned.load(std::memory_order_acquire) == 0) {
      std::this_thread::yield();
    }
  }
  return edge_fake_vx_device_open(index, out);
}
FORWARD(vx_device_release, (vx_device_h device), (device))
FORWARD(vx_device_query, (vx_device_h device, uint32_t id, uint64_t* out), (device, id, out))
FORWARD(vx_device_memory_info, (vx_device_h device, uint64_t* free_bytes, uint64_t* used_bytes),
        (device, free_bytes, used_bytes))
FORWARD(vx_module_load_bytes, (vx_device_h device, const void* bytes, size_t size, vx_module_h* out),
        (device, bytes, size, out))
FORWARD(vx_module_release, (vx_module_h module), (module))
FORWARD(vx_module_get_kernel, (vx_module_h module, const char* name, vx_kernel_h* out),
        (module, name, out))
FORWARD(vx_kernel_release, (vx_kernel_h kernel), (kernel))
FORWARD(vx_queue_create, (vx_device_h device, const vx_queue_info_t* info, vx_queue_h* out),
        (device, info, out))
FORWARD(vx_queue_release, (vx_queue_h queue), (queue))
FORWARD(vx_buffer_create, (vx_device_h device, uint64_t size, uint32_t flags, vx_buffer_h* out),
        (device, size, flags, out))
FORWARD(vx_buffer_address, (vx_buffer_h buffer, uint64_t* out), (buffer, out))
FORWARD(vx_buffer_release, (vx_buffer_h buffer), (buffer))
FORWARD(vx_enqueue_write, (vx_queue_h queue, vx_buffer_h buffer, uint64_t offset,
        const void* source, uint64_t size, uint32_t n, const vx_event_h* waits, vx_event_h* out),
        (queue, buffer, offset, source, size, n, waits, out))
FORWARD(vx_enqueue_launch, (vx_queue_h queue, const vx_launch_info_t* info, uint32_t n,
        const vx_event_h* waits, vx_event_h* out), (queue, info, n, waits, out))
FORWARD(vx_enqueue_read, (vx_queue_h queue, void* destination, vx_buffer_h buffer,
        uint64_t offset, uint64_t size, uint32_t n, const vx_event_h* waits, vx_event_h* out),
        (queue, destination, buffer, offset, size, n, waits, out))
FORWARD(vx_event_get_profiling, (vx_event_h event, vx_profile_info_t* out), (event, out))
FORWARD(vx_event_release, (vx_event_h event), (event))
#undef FORWARD

extern "C" vx_result_t vx_event_wait_value(vx_event_h event, uint64_t value, uint64_t timeout) {
  allocation_probe::NativeScope excluded;
  const unsigned call = ++polls.waits;
  if (call == polls.wait_timeout_at) {
    return VX_ERR_TIMEOUT;
  }
  const auto result = edge_fake_vx_event_wait_value(event, value, timeout);
  return call == polls.wait_error_at ? VX_ERR_DEVICE_LOST : result;
}

extern "C" vx_result_t vx_event_get_value(vx_event_h event, uint64_t* out) {
  allocation_probe::NativeScope excluded;
  ++polls.queries;
  if (polls.query_timeouts != 0) {
    --polls.query_timeouts;
    return VX_ERR_TIMEOUT;
  }
  if (polls.queries == polls.query_error_at) {
    return VX_ERR_INVALID_VALUE;
  }
  return edge_fake_vx_event_get_value(event, out);
}

namespace {

ExecutionBinding edge_binding(WorkspacePolicy policy, DType dtype, bool profiling = false) {
  auto value = binding(dtype);
  value.workspace_policy = policy;
  value.enable_profiling = profiling;
  return value;
}

std::unique_ptr<ManagedMatmul> edge_owner(const ExecutionBinding& value) {
  std::unique_ptr<ManagedMatmul> owner;
  auto result = ManagedMatmul::create(value, &owner);
  check(result.ok() && result.complete && owner != nullptr);
  return owner;
}

ExecutionResult edge_submit(ManagedMatmul* owner, std::unique_ptr<MatmulOperation>* out) {
  std::array<uint8_t, 128> a;
  std::array<uint8_t, 64> b;
  a.fill(0x12);
  b.fill(0x34);
  return owner->submit(8, 4, 8, a.data(), a.size(), b.data(), b.size(), 0xdeadbeef, out);
}

void finish(std::unique_ptr<ManagedMatmul>& owner) {
  check(owner->close().ok());
  owner.reset();
  no_resources();
  polls = {};
}

void healthy_operation(ManagedMatmul* owner) {
  std::unique_ptr<MatmulOperation> operation;
  const auto submitted = edge_submit(owner, &operation);
  check(submitted.ok() && !submitted.complete && operation != nullptr);
  const auto completed = operation->wait(0);
  check(completed.ok() && completed.complete && operation->output_words().size() == 32);
  check(operation->close(0).ok());
}

void begin_allocations(unsigned target, bool other) {
  using namespace allocation_probe;
  check(!armed && live_count() == 0 && native_depth == 0);
  ordinal = failures = excluded_allocations = 0;
  fail_at = target;
  other_failure = other;
  armed = true;
}

unsigned end_allocations() {
  allocation_probe::armed = false;
  check(allocation_probe::native_depth == 0);
  return allocation_probe::ordinal;
}

void create_race(WorkspacePolicy policy, DType dtype) {
  const auto value = edge_binding(policy, dtype);
  for (unsigned attempt = 0; attempt != 32; ++attempt) {
    reset();
    open_entries = 0;
    race_returned = 0;
    race_active = true;
    std::atomic<unsigned> ready{0};
    std::atomic<bool> go{false};
    std::array<ExecutionResult, 2> results;
    std::array<std::unique_ptr<ManagedMatmul>, 2> owners;
    auto compete = [&](unsigned index) {
      ready.fetch_add(1, std::memory_order_release);
      while (!go.load(std::memory_order_acquire)) {
        std::this_thread::yield();
      }
      results[index] = ManagedMatmul::create(value, &owners[index]);
      race_returned.fetch_add(1, std::memory_order_release);
    };
    std::thread left(compete, 0);
    std::thread right(compete, 1);
    while (ready.load(std::memory_order_acquire) != 2) {
      std::this_thread::yield();
    }
    go.store(true, std::memory_order_release);
    left.join();
    right.join();
    race_active = false;
    check(race_returned == 2 && open_entries == 1 && state.calls["device_open"] == 1);
    check(bool(owners[0]) != bool(owners[1]));
    const unsigned winner = owners[0] ? 0 : 1;
    const auto& busy = results[1 - winner];
    check(results[winner].ok() && results[winner].complete);
    check(busy.validation == Status::success && busy.primary == VX_ERR_TIMEOUT
          && busy.cleanup == VX_SUCCESS && busy.complete);
    finish(owners[winner]);
    auto retry = edge_owner(value);
    check(open_entries == 2 && state.calls["device_open"] == 2);
    healthy_operation(retry.get());
    finish(retry);
    ++scenarios;
  }
}

unsigned count_create_allocations(const ExecutionBinding& value) {
  std::unique_ptr<ManagedMatmul> owner;
  begin_allocations(100, false);
  const auto result = ManagedMatmul::create(value, &owner);
  const unsigned count = end_allocations();
  check(result.ok() && owner != nullptr && count == 4 && allocation_probe::failures == 0);
  check(allocation_probe::excluded_allocations > 0);
  finish(owner);
  check(allocation_probe::live_count() == 0);
  return count;
}

void create_allocations(WorkspacePolicy policy, DType dtype, bool other) {
  const auto value = edge_binding(policy, dtype);
  const unsigned count = count_create_allocations(value);
  for (unsigned target = 1; target <= count; ++target) {
    reset();
    std::unique_ptr<ManagedMatmul> owner;
    begin_allocations(target, other);
    const auto result = ManagedMatmul::create(value, &owner);
    check(end_allocations() == target);
    check(allocation_probe::failures == 1 && allocation_probe::live_count() == 0);
    check(!owner && result.validation == Status::success && result.complete
          && result.primary == (other ? VX_ERR_INTERNAL : VX_ERR_OUT_OF_HOST_MEMORY)
          && result.cleanup == VX_SUCCESS);
    check(state.calls["device_open"] == (target == count ? 1 : 0));
    no_resources();
    owner = edge_owner(value);
    healthy_operation(owner.get());
    finish(owner);
    ++scenarios;
  }
}

void submit_allocations(WorkspacePolicy policy, DType dtype, bool other) {
  const auto value = edge_binding(policy, dtype);
  auto owner = edge_owner(value);
  std::unique_ptr<MatmulOperation> operation;
  begin_allocations(100, false);
  const auto submitted = edge_submit(owner.get(), &operation);
  const unsigned count = end_allocations();
  check(submitted.ok() && !submitted.complete && count == 7 && allocation_probe::failures == 0);
  check(allocation_probe::excluded_allocations > 0);
  check(operation->close(0).ok());
  operation.reset();
  check(allocation_probe::live_count() == 0);
  for (unsigned target = 1; target <= count; ++target) {
    const int queue_calls = state.calls["queue_create"];
    begin_allocations(target, other);
    const auto result = edge_submit(owner.get(), &operation);
    check(end_allocations() == target);
    check(allocation_probe::failures == 1 && allocation_probe::live_count() == 0);
    check(result.validation == Status::success && result.complete
          && result.primary == (other ? VX_ERR_INTERNAL : VX_ERR_OUT_OF_HOST_MEMORY)
          && result.cleanup == VX_SUCCESS && !operation);
    check(state.calls["queue_create"] == queue_calls && state.events == 0 && state.queues == 0);
    healthy_operation(owner.get());
    ++scenarios;
  }
  finish(owner);
}

void create_allocation_cleanup(WorkspacePolicy policy, DType dtype, bool other) {
  const auto value = edge_binding(policy, dtype);
  const unsigned count = count_create_allocations(value);
  reset();
  state.cleanup_failure = true;
  std::unique_ptr<ManagedMatmul> owner;
  begin_allocations(count, other);
  const auto result = ManagedMatmul::create(value, &owner);
  check(end_allocations() == count);
  check(allocation_probe::failures == 1 && allocation_probe::live_count() == 0);
  check(!owner && result.complete && result.validation == Status::success
        && result.primary == (other ? VX_ERR_INTERNAL : VX_ERR_OUT_OF_HOST_MEMORY)
        && result.cleanup == VX_ERR_INTERNAL);
  no_resources();
  const unsigned calls = open_entries;
  const auto poisoned = ManagedMatmul::create(value, &owner);
  check(!owner && poisoned.complete && poisoned.validation == Status::success
        && poisoned.primary == VX_ERR_INTERNAL && poisoned.cleanup == VX_ERR_INTERNAL);
  check(open_entries == calls);
  ++scenarios;
}

void retained(ManagedMatmul* owner, MatmulOperation* operation, const ExecutionBinding& value) {
  check(operation->output_words().empty());
  const auto before = state.calls;
  const unsigned entries = open_entries;
  std::unique_ptr<ManagedMatmul> extra_owner;
  const auto create_result = ManagedMatmul::create(value, &extra_owner);
  check(create_result.primary == VX_ERR_TIMEOUT && create_result.complete && !extra_owner);
  std::unique_ptr<MatmulOperation> extra_operation;
  const auto submit_result = edge_submit(owner, &extra_operation);
  check(submit_result.primary == VX_ERR_TIMEOUT && submit_result.complete && !extra_operation);
  const auto owner_result = owner->close();
  check(owner_result.primary == VX_ERR_TIMEOUT && !owner_result.complete);
  check(state.calls == before && open_entries == entries
        && state.queues == 1 && state.events > 0 && state.buffers.size() == 3);
}

void complete_retry(std::unique_ptr<ManagedMatmul>& owner, std::unique_ptr<MatmulOperation>& operation,
                    vx_result_t primary, uint64_t waits, uint64_t timeouts) {
  const auto done = operation->wait(0);
  check(done.complete && done.validation == Status::success
        && done.primary == primary && done.cleanup == VX_SUCCESS);
  check(operation->output_words().size() == (primary == VX_SUCCESS ? 32 : 0));
  check(operation->trace().wait_calls == waits && operation->trace().timed_out_waits == timeouts);
  std::unique_ptr<MatmulOperation> busy;
  check(edge_submit(owner.get(), &busy).primary == VX_ERR_TIMEOUT && !busy);
  const auto closed = operation->close(0);
  check(closed.complete && closed.primary == primary && closed.cleanup == VX_SUCCESS);
  operation.reset();
  polls = {};
  state.fail_call.clear();
  healthy_operation(owner.get());
  finish(owner);
}

void prefix_timeouts(WorkspacePolicy policy, DType dtype) {
  const auto value = edge_binding(policy, dtype);
  for (unsigned event = 0; event != 5; ++event) {
    reset();
    auto owner = edge_owner(value);
    std::unique_ptr<MatmulOperation> operation;
    check(edge_submit(owner.get(), &operation).ok());
    polls.wait_timeout_at = event + 2; // Tail wait, then each zero-time prefix poll.
    const auto first = operation->wait(0);
    check(!first.complete && first.primary == VX_ERR_TIMEOUT && first.cleanup == VX_SUCCESS);
    check(operation->trace().event_results[event] == VX_ERR_TIMEOUT);
    retained(owner.get(), operation.get(), value);
    complete_retry(owner, operation, VX_SUCCESS, 2, 1);
    ++scenarios;
  }
}

void query_timeouts(WorkspacePolicy policy, DType dtype) {
  const auto value = edge_binding(policy, dtype);
  for (bool sticky : {false, true}) {
    reset();
    auto owner = edge_owner(value);
    std::unique_ptr<MatmulOperation> operation;
    check(edge_submit(owner.get(), &operation).ok());
    polls.wait_error_at = sticky ? 1 : 0;
    polls.query_timeouts = 2;
    for (unsigned retry = 0; retry != 2; ++retry) {
      const auto result = operation->wait(0);
      check(!result.complete && result.cleanup == VX_SUCCESS
            && result.primary == (sticky ? VX_ERR_DEVICE_LOST : VX_ERR_TIMEOUT));
      retained(owner.get(), operation.get(), value);
    }
    complete_retry(owner, operation, sticky ? VX_ERR_DEVICE_LOST : VX_SUCCESS, 3, 2);
    ++scenarios;
  }
}

void query_error_then_prefix_timeout(WorkspacePolicy policy, DType dtype) {
  const auto value = edge_binding(policy, dtype);
  auto owner = edge_owner(value);
  std::unique_ptr<MatmulOperation> operation;
  check(edge_submit(owner.get(), &operation).ok());
  polls.query_error_at = 1;
  const auto first = operation->wait(0);
  check(!first.complete && first.primary == VX_ERR_INVALID_VALUE);
  retained(owner.get(), operation.get(), value);
  polls.wait_timeout_at = 3; // Second tail wait followed by first prefix poll.
  const auto second = operation->wait(0);
  check(!second.complete && second.primary == VX_ERR_INVALID_VALUE);
  retained(owner.get(), operation.get(), value);
  complete_retry(owner, operation, VX_ERR_INVALID_VALUE, 3, 1);
  ++scenarios;
}

void partial_prefix_timeouts(WorkspacePolicy policy, DType dtype) {
  const auto value = edge_binding(policy, dtype);
  for (unsigned accepted = 1; accepted != 5; ++accepted) {
    for (unsigned event = 0; event != accepted; ++event) {
      reset();
      auto owner = edge_owner(value);
      state.fail_call = "enqueue";
      state.fail_at = accepted + 1;
      std::unique_ptr<MatmulOperation> operation;
      const auto submitted = edge_submit(owner.get(), &operation);
      check(!submitted.complete && submitted.primary == VX_ERR_OUT_OF_HOST_MEMORY && operation);
      check(state.events == int(accepted));
      polls.wait_timeout_at = event + 2;
      const auto first = operation->close(0);
      check(!first.complete && first.primary == VX_ERR_OUT_OF_HOST_MEMORY
            && first.cleanup == VX_SUCCESS);
      retained(owner.get(), operation.get(), value);
      complete_retry(owner, operation, VX_ERR_OUT_OF_HOST_MEMORY, 2, 1);
      ++scenarios;
    }
  }
}

void profiling_after_retry(WorkspacePolicy policy, DType dtype) {
  const auto value = edge_binding(policy, dtype, true);
  for (unsigned event = 0; event != 5; ++event) {
    reset();
    auto owner = edge_owner(value);
    std::unique_ptr<MatmulOperation> operation;
    check(edge_submit(owner.get(), &operation).ok());
    polls.wait_timeout_at = 2;
    check(operation->wait(0).primary == VX_ERR_TIMEOUT);
    retained(owner.get(), operation.get(), value);
    state.fail_call = "profiling";
    state.fail_at = event + 1;
    const auto result = operation->wait(0);
    check(result.ok() && result.complete && operation->output_words().size() == 32);
    const auto& trace = operation->trace();
    check(trace.wait_calls == 2 && trace.timed_out_waits == 1);
    for (unsigned index = 0; index != 5; ++index) {
      check(trace.event_profile_queried[index] && trace.event_results[index] == VX_SUCCESS);
      check(trace.event_profile_results[index] == (event == index ? VX_ERR_NOT_SUPPORTED : VX_SUCCESS));
    }
    check(trace.event_profiles[event].start_ns == 0 && trace.event_profiles[event].end_ns == 0);
    check(operation->close(0).ok());
    operation.reset();
    finish(owner);
    ++scenarios;
  }
}
} // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
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
  if (group == "create_race") {
    create_race(policy, dtype);
  } else if (group == "create_bad_alloc" || group == "create_other_exception") {
    create_allocations(policy, dtype, group == "create_other_exception");
  } else if (group == "submit_bad_alloc" || group == "submit_other_exception") {
    submit_allocations(policy, dtype, group == "submit_other_exception");
  } else if (group == "create_cleanup_bad_alloc" || group == "create_cleanup_other_exception") {
    create_allocation_cleanup(policy, dtype, group == "create_cleanup_other_exception");
  } else if (group == "prefix_timeouts") {
    prefix_timeouts(policy, dtype);
  } else if (group == "query_timeouts") {
    query_timeouts(policy, dtype);
  } else if (group == "query_error_prefix_timeout") {
    query_error_then_prefix_timeout(policy, dtype);
  } else if (group == "partial_prefix_timeouts") {
    partial_prefix_timeouts(policy, dtype);
  } else if (group == "profiling_after_retry") {
    profiling_after_retry(policy, dtype);
  } else {
    return 2;
  }
  check(!allocation_probe::armed && allocation_probe::native_depth == 0
        && allocation_probe::live_count() == 0);
  no_resources();
  std::cout << "PASS " << group << " checks=" << checks << " scenarios=" << scenarios << '\n';
  return 0;
}
