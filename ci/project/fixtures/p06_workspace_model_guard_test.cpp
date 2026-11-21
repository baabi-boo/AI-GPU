// SPDX-License-Identifier: Apache-2.0

#include "mlp_runtime.h"
#include <tuple>

// Real managed operators share the deferred C API; scripted zeros are control evidence only.
#define main p03_managed_runtime_fixture_main
#define vx_enqueue_write p03_fixture_enqueue_write
#define vx_enqueue_launch p03_fixture_enqueue_launch
#define vx_device_memory_info p03_fixture_device_memory_info
#include "p03_managed_runtime_test.cpp"
#undef main
#undef vx_enqueue_write
#undef vx_enqueue_launch
#undef vx_device_memory_info

namespace {

int scripted_launches = 0;

void guard_check(bool value, const char* expression, int line) {
  ++checks;
  if (!value) {
    std::cerr << "model guard line " << line << ": " << expression << '\n';
    std::exit(1);
  }
}
#define CHECK(value) guard_check(bool(value), #value, __LINE__)

auto resource_snapshot() {
  return std::make_tuple(state.devices, state.modules, state.kernels, state.queues,
      state.events, state.buffers.size(), state.premature, state.writes_observed,
      state.profiled_queues, state.default_queues, scripted_launches);
}

MlpCase model_case(DType dtype) {
  MlpCase result;
  result.case_id = dtype == DType::fp16 ? "host-zero-fp16" : "host-zero-bf16";
  result.input_dtype = dtype;
  return result;
}

std::unique_ptr<ManagedMatmul> direct_owner(DType dtype, WorkspacePolicy policy) {
  std::unique_ptr<ManagedMatmul> owner;
  auto value = binding(dtype);
  value.workspace_policy = policy;
  const auto result = ManagedMatmul::create(value, &owner);
  CHECK(result.ok() && result.complete && owner);
  return owner;
}

std::unique_ptr<ManagedMlp> model_owner(DType dtype) {
  std::unique_ptr<ManagedMlp> owner;
  const auto result = ManagedMlp::create(binding(dtype), model_case(dtype), &owner);
  CHECK(result.ok() && result.complete && owner);
  return owner;
}

void expect_rejected_contexts(DType dtype, vx_result_t primary, vx_result_t cleanup) {
  const auto before = resource_snapshot();
  const auto calls = state.calls;
  for (auto policy : {WorkspacePolicy::per_operation, WorkspacePolicy::reusable_single_tile}) {
    std::unique_ptr<ManagedMatmul> owner;
    auto value = binding(dtype);
    value.workspace_policy = policy;
    const auto result = ManagedMatmul::create(value, &owner);
    CHECK(result.validation == Status::success && result.primary == primary
          && result.cleanup == cleanup && result.complete && !owner);
    CHECK(state.calls == calls && resource_snapshot() == before);
  }
  std::unique_ptr<ManagedMlp> model;
  const auto result = ManagedMlp::create(binding(dtype), model_case(dtype), &model);
  CHECK(result.validation == Status::success && result.primary == primary
        && result.cleanup == cleanup && result.complete && !model);
  CHECK(state.calls == calls && resource_snapshot() == before);
}

void expect_busy_contexts(DType dtype) {
  expect_rejected_contexts(dtype, VX_ERR_TIMEOUT, VX_SUCCESS);
}

void healthy_handoff(DType dtype) {
  no_resources();
  auto direct = direct_owner(dtype, WorkspacePolicy::per_operation);
  CHECK(direct->close().ok());
  auto model = model_owner(dtype);
  CHECK(model->close(0).ok());
  no_resources();
}

void verify_model_graph(const ManagedMlp& model, int initial_launches) {
  const auto& trace = model.trace();
  CHECK(trace.result.terminal && trace.result.status == MlpStatus::success);
  CHECK(trace.result.execution.complete && !trace.owner_closed);
  CHECK(trace.result.execution.ok() && trace.hidden_valid && trace.bridge_valid
        && trace.assembled && trace.logits_valid && trace.logits_compared);
  CHECK(scripted_launches == initial_launches + 3);
  CHECK(state.devices == 1 && state.modules == 1 && state.kernels == 1
        && state.queues == 0 && state.events == 0 && state.buffers.empty());
  for (size_t stage = 0; stage != trace.native.size(); ++stage) {
    const auto& native = trace.native[stage];
    CHECK(native.submitted && native.waited && native.trace_valid && native.output_valid
          && native.compared && native.closed && native.cleanup.ok());
    CHECK(native.dispatch.m == (stage == 0 ? 16u : 8u)
          && native.dispatch.n == (stage == 0 ? 8u : 4u)
          && native.dispatch.k == (stage == 0 ? 16u : 8u));
    CHECK(native.dispatch.writes_enqueued == 3 && native.dispatch.launches_enqueued == 1
          && native.dispatch.reads_enqueued == 1);
    CHECK(native.output_count == (stage == 0 ? 128u : 32u) && native.mismatches == 0);
    CHECK(std::all_of(native.output_words.begin(), native.output_words.end(),
                      [](uint32_t value) { return value == 0; }));
  }
}

void matmul_excludes_model(DType dtype, WorkspacePolicy policy) {
  auto owner = direct_owner(dtype, policy);
  expect_busy_contexts(dtype);
  std::unique_ptr<MatmulOperation> operation;
  auto result = launch(owner.get(), &operation);
  CHECK(result.ok() && !result.complete && operation);
  expect_busy_contexts(dtype);
  const auto resources = resource_snapshot();
  result = owner->close();
  CHECK(result.primary == VX_ERR_TIMEOUT && !result.complete);
  CHECK(resource_snapshot() == resources);
  result = operation->wait(0);
  CHECK(result.ok() && result.complete);
  expect_busy_contexts(dtype);
  result = operation->close(0);
  CHECK(result.ok() && result.complete);
  expect_busy_contexts(dtype);
  CHECK(owner->close().ok());
  CHECK(operation->output_words().size() == 32);
  healthy_handoff(dtype);
}

void retained_operation_excludes_model(DType dtype, WorkspacePolicy policy) {
  for (bool completed_wait : {false, true}) {
    auto owner = direct_owner(dtype, policy);
    std::unique_ptr<MatmulOperation> operation;
    CHECK(launch(owner.get(), &operation).ok());
    if (completed_wait) {
      CHECK(operation->wait(0).ok());
    }
    owner.reset();
    expect_busy_contexts(dtype);
    if (!completed_wait) {
      state.timeout_budget = 1;
      const auto result = operation->close(0);
      CHECK(result.primary == VX_ERR_TIMEOUT && !result.complete);
      expect_busy_contexts(dtype);
    }
    const auto result = operation->close(0);
    CHECK(result.ok() && result.complete);
    healthy_handoff(dtype);
  }
}

void model_excludes_contexts(DType dtype) {
  auto model = model_owner(dtype);
  const int first_launch = scripted_launches;
  expect_busy_contexts(dtype);
  state.timeout_budget = 1;
  auto result = model->advance(0);
  CHECK(!result.terminal && !result.execution.complete
        && result.execution.primary == VX_ERR_TIMEOUT);
  CHECK(state.queues == 1 && state.events == 5 && state.buffers.size() == 3);
  expect_busy_contexts(dtype);
  result = model->advance(0);
  CHECK(result.terminal && result.status == MlpStatus::success && result.ok());
  verify_model_graph(*model, first_launch);
  expect_busy_contexts(dtype);
  const auto before = resource_snapshot();
  CHECK(model->advance(0).status == MlpStatus::success);
  CHECK(resource_snapshot() == before);
  auto closed = model->close(0);
  CHECK(closed.ok() && closed.complete && model->trace().owner_closed
        && model->trace().result.ok());
  closed = model->close(0);
  CHECK(closed.ok() && closed.complete);
  healthy_handoff(dtype);
}

void terminal_model_failures(DType dtype) {
  for (bool asynchronous : {false, true}) {
    auto input = model_case(dtype);
    if (!asynchronous) {
      input.expected.hidden_words[0] = 0x3f800000;
    }
    std::unique_ptr<ManagedMlp> model;
    CHECK(ManagedMlp::create(binding(dtype), input, &model).ok());
    if (asynchronous) {
      state.async_failure = 4;
    }
    const int launches = scripted_launches;
    const auto result = model->advance(0);
    CHECK(result.terminal && !result.ok() && result.execution.complete);
    CHECK(result.status == (asynchronous ? MlpStatus::runtime_error : MlpStatus::hidden_mismatch));
    CHECK(result.execution.primary == (asynchronous ? VX_ERR_DEVICE_LOST : VX_SUCCESS));
    CHECK(scripted_launches == launches + 1);
    CHECK(state.queues == 0 && state.events == 0 && state.buffers.empty());
    CHECK(!model->trace().native[1].submitted && !model->trace().owner_closed);
    expect_busy_contexts(dtype);
    const auto closed = model->close(0);
    CHECK(closed.complete && closed.cleanup == VX_SUCCESS
          && closed.primary == (asynchronous ? VX_ERR_DEVICE_LOST : VX_SUCCESS));
    model.reset();
    state.async_failure = 0;
    healthy_handoff(dtype);
  }
}

void partial_model_submission(DType dtype) {
  for (int ordinal = 2; ordinal <= 5; ++ordinal) {
    reset();
    auto model = model_owner(dtype);
    state.fail_call = "enqueue";
    state.fail_at = ordinal;
    auto result = model->advance(0);
    CHECK(result.terminal && result.status == MlpStatus::runtime_error
          && result.execution.primary == VX_ERR_OUT_OF_HOST_MEMORY
          && !result.execution.complete);
    CHECK(state.events == ordinal - 1 && state.queues == 1);
    expect_busy_contexts(dtype);
    state.timeout_budget = 1;
    auto closed = model->close(0);
    CHECK(!closed.complete && closed.primary == VX_ERR_OUT_OF_HOST_MEMORY);
    expect_busy_contexts(dtype);
    state.fail_call.clear();
    closed = model->close(0);
    CHECK(closed.complete && closed.primary == VX_ERR_OUT_OF_HOST_MEMORY
          && closed.cleanup == VX_SUCCESS);
    CHECK(model->trace().owner_closed);
    model.reset();
    healthy_handoff(dtype);
  }
}

void invalid_model_policy(DType dtype) {
  for (uint32_t raw : {uint32_t{1}, uint32_t{2}, UINT32_MAX}) {
    for (bool existing_context : {false, true}) {
      std::unique_ptr<ManagedMatmul> direct;
      if (existing_context) {
        direct = direct_owner(dtype, WorkspacePolicy::per_operation);
      }
      const auto calls = state.calls;
      const auto before = resource_snapshot();
      auto value = binding(dtype);
      value.workspace_policy = static_cast<WorkspacePolicy>(raw);
      std::unique_ptr<ManagedMlp> model;
      const auto result = ManagedMlp::create(value, model_case(dtype), &model);
      CHECK(result.validation == Status::invalid_argument && result.primary == VX_SUCCESS
            && result.cleanup == VX_SUCCESS && result.complete && !model);
      CHECK(state.calls == calls && resource_snapshot() == before);
      if (direct) {
        expect_busy_contexts(dtype);
        CHECK(direct->close().ok());
      }
      healthy_handoff(dtype);
    }
  }
}

void model_setup_rollback(DType dtype) {
  const std::array<std::pair<const char*, int>, 11> faults{{
      {"device_open", 1}, {"query", 1}, {"query", 2}, {"query", 3}, {"query", 4},
      {"query", 5}, {"query", 6}, {"query", 7}, {"module_load", 1},
      {"get_kernel", 1}, {"memory_info", 1}}};
  for (const auto& fault : faults) {
    reset();
    state.fail_call = fault.first;
    state.fail_at = fault.second;
    std::unique_ptr<ManagedMlp> model;
    const auto result = ManagedMlp::create(binding(dtype), model_case(dtype), &model);
    CHECK(!result.ok() && result.complete && !model && result.cleanup == VX_SUCCESS);
    CHECK(state.calls[fault.first] == fault.second);
    const auto expected = std::string(fault.first) == "module_load" ? VX_ERR_OUT_OF_DEVICE_MEMORY
        : std::string(fault.first) == "get_kernel" ? VX_ERR_NOT_SUPPORTED : VX_ERR_DEVICE_LOST;
    CHECK(result.primary == expected);
    no_resources();
    state.fail_call.clear();
    healthy_handoff(dtype);
  }
}

void direct_cleanup_poison(DType dtype, WorkspacePolicy policy, const std::string& phase) {
  auto owner = direct_owner(dtype, policy);
  if (phase == "operation") {
    std::unique_ptr<MatmulOperation> operation;
    CHECK(launch(owner.get(), &operation).ok());
    CHECK(operation->wait(0).ok());
    CHECK(operation->output_words().size() == 32);
    state.cleanup_failure = true;
    const auto closed = operation->close(0);
    CHECK(closed.complete && closed.primary == VX_SUCCESS && closed.cleanup == VX_ERR_INTERNAL);
    CHECK(operation->output_words().empty());
    expect_rejected_contexts(dtype, VX_ERR_INTERNAL, VX_ERR_INTERNAL);
  } else {
    CHECK(phase == "owner");
    state.cleanup_failure = true;
  }
  const auto closed = owner->close();
  CHECK(closed.complete && closed.cleanup == VX_ERR_INTERNAL);
  CHECK(owner->close().cleanup == VX_ERR_INTERNAL);
  no_resources();
  expect_rejected_contexts(dtype, VX_ERR_INTERNAL, VX_ERR_INTERNAL);
}

void model_cleanup_poison(DType dtype, const std::string& phase) {
  if (phase == "rollback") {
    state.fail_call = "memory_info";
    state.fail_at = 1;
    state.cleanup_failure = true;
    std::unique_ptr<ManagedMlp> model;
    const auto result = ManagedMlp::create(binding(dtype), model_case(dtype), &model);
    CHECK(!model && result.complete && result.primary == VX_ERR_DEVICE_LOST
          && result.cleanup == VX_ERR_INTERNAL);
    state.fail_call.clear();
  } else {
    auto model = model_owner(dtype);
    if (phase == "operation" || phase == "destructor") {
      state.timeout_budget = 1;
      const auto result = model->advance(0);
      CHECK(!result.terminal && !result.execution.complete);
    } else {
      CHECK(phase == "owner");
    }
    state.cleanup_failure = true;
    if (phase == "operation") {
      const int launches = scripted_launches;
      const auto result = model->advance(0);
      CHECK(result.terminal && result.status == MlpStatus::runtime_error
            && result.execution.primary == VX_SUCCESS && result.execution.cleanup == VX_ERR_INTERNAL);
      CHECK(scripted_launches == launches && !model->trace().native[1].submitted);
      expect_rejected_contexts(dtype, VX_ERR_INTERNAL, VX_ERR_INTERNAL);
    }
    if (phase == "destructor") {
      model.reset();
    } else {
      const auto closed = model->close(0);
      CHECK(closed.complete && closed.primary == VX_SUCCESS && closed.cleanup == VX_ERR_INTERNAL);
      CHECK(model->close(0).cleanup == VX_ERR_INTERNAL);
    }
  }
  no_resources();
  expect_rejected_contexts(dtype, VX_ERR_INTERNAL, VX_ERR_INTERNAL);
}

void default_shape_handoff(DType dtype) {
  for (const auto shape : {std::array<uint32_t, 3>{8, 4, 8}, {8, 4, 16}, {16, 8, 16}}) {
    auto owner = direct_owner(dtype, WorkspacePolicy::per_operation);
    std::unique_ptr<MatmulOperation> operation;
    CHECK(launch(owner.get(), &operation, shape[0], shape[1], shape[2]).ok());
    CHECK(operation->close(0).ok());
    CHECK(operation->output_words().size() == shape[0] * shape[1]);
    CHECK(owner->close().ok());
    auto model = model_owner(dtype);
    const int launches = scripted_launches;
    CHECK(model->advance(0).status == MlpStatus::success);
    verify_model_graph(*model, launches);
    CHECK(model->close(0).ok());
    no_resources();
  }
}

void model_destructor_handoff(DType dtype) {
  for (int stage = 0; stage != 3; ++stage) {
    auto model = model_owner(dtype);
    if (stage == 1) {
      state.timeout_budget = 1;
      CHECK(!model->advance(0).terminal);
    } else if (stage == 2) {
      CHECK(model->advance(0).status == MlpStatus::success);
    }
    expect_busy_contexts(dtype);
    model.reset();
    healthy_handoff(dtype);
  }
}

} // namespace

extern "C" {

vx_result_t vx_device_memory_info(vx_device_h device, uint64_t* free_bytes,
                                  uint64_t* used_bytes) {
  if (fail("memory_info")) {
    return VX_ERR_DEVICE_LOST;
  }
  return p03_fixture_device_memory_info(device, free_bytes, used_bytes);
}

vx_result_t vx_enqueue_write(vx_queue_h queue, vx_buffer_h handle, uint64_t offset,
                             const void* source, uint64_t size, uint32_t n,
                             const vx_event_h* waits, vx_event_h* out) {
  auto* buffer = static_cast<Buffer*>(handle);
  CHECK(offset == 0 && size == buffer->bytes.size());
  return enqueue(queue, n, waits, out, [buffer, source, size] {
    std::memcpy(buffer->bytes.data(), source, size);
    ++state.writes_observed;
  });
}

vx_result_t vx_enqueue_launch(vx_queue_h queue, const vx_launch_info_t* info,
                              uint32_t n, const vx_event_h* waits, vx_event_h* out) {
  CHECK(info->struct_size == sizeof(*info) && info->args_size == 56 && info->ndim == 2
        && info->block_dim[0] == 4 && info->block_dim[1] == 1 && info->block_dim[2] == 1);
  const auto* bytes = static_cast<const uint8_t*>(info->args_host);
  uint64_t address = 0;
  for (unsigned byte = 0; byte != 8; ++byte) {
    address |= uint64_t{bytes[48 + byte]} << (8 * byte);
  }
  const auto result = enqueue(queue, n, waits, out, [address] {
    const auto found = std::find_if(state.buffers.begin(), state.buffers.end(),
        [address](Buffer* buffer) { return buffer->address == address; });
    CHECK(found != state.buffers.end());
    std::fill((*found)->bytes.begin(), (*found)->bytes.end(), uint8_t{0});
  });
  if (result == VX_SUCCESS) {
    ++scripted_launches;
  }
  return result;
}

} // extern "C"

int main(int argc, char** argv) {
  if (argc < 4 || argc > 5) {
    return 2;
  }
  const std::string group = argv[1];
  const std::string policy_name = argv[2];
  const std::string dtype_name = argv[3];
  if ((policy_name != "per_operation" && policy_name != "reusable_single_tile")
      || (dtype_name != "fp16" && dtype_name != "bf16")) {
    return 2;
  }
  const auto policy = policy_name == "per_operation"
      ? WorkspacePolicy::per_operation : WorkspacePolicy::reusable_single_tile;
  const auto dtype = dtype_name == "fp16" ? DType::fp16 : DType::bf16;
  if (group == "matmul_excludes_model" && argc == 4) {
    matmul_excludes_model(dtype, policy);
  } else if (group == "retained_operation" && argc == 4) {
    retained_operation_excludes_model(dtype, policy);
  } else if (group == "model_excludes_contexts" && argc == 4) {
    model_excludes_contexts(dtype);
  } else if (group == "terminal_failures" && argc == 4) {
    terminal_model_failures(dtype);
  } else if (group == "partial_submission" && argc == 4) {
    partial_model_submission(dtype);
  } else if (group == "invalid_policy" && argc == 4) {
    invalid_model_policy(dtype);
  } else if (group == "setup_rollback" && argc == 4) {
    model_setup_rollback(dtype);
  } else if (group == "direct_cleanup_poison" && argc == 5) {
    direct_cleanup_poison(dtype, policy, argv[4]);
  } else if (group == "model_cleanup_poison" && argc == 5) {
    model_cleanup_poison(dtype, argv[4]);
  } else if (group == "default_shapes" && argc == 4) {
    default_shape_handoff(dtype);
  } else if (group == "model_destructor" && argc == 4) {
    model_destructor_handoff(dtype);
  } else {
    return 2;
  }
  no_resources();
  CHECK(!state.cleanup_failure && state.timeout_budget == 0);
  std::cout << "PASS " << group << " checks=" << checks << '\n';
  return 0;
}
