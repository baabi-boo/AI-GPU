// SPDX-License-Identifier: Apache-2.0

#include "mlp_runtime.h"
#include "p04_fixtures.h"
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <new>
#include <string>
#include <vector>

namespace {
bool fail_next_allocation = false;
}

[[gnu::noinline]] void* operator new(size_t count) {
  if (fail_next_allocation) {
    fail_next_allocation = false;
    throw std::bad_alloc();
  }
  if (void* value = std::malloc(count == 0 ? 1 : count)) {
    return value;
  }
  throw std::bad_alloc();
}
[[gnu::noinline]] void operator delete(void* value) noexcept { std::free(value); }
[[gnu::noinline]] void operator delete(void* value, size_t) noexcept { std::free(value); }

using namespace vortex::ai;

namespace {
int checks = 0;
const char* current_group = nullptr;
void check(bool condition, const char* expression, int line) {
  ++checks;
  if (!condition) {
    std::cerr << "FAILED " << current_group << ':' << line << ' ' << expression << '\n';
    std::exit(1);
  }
}
#define CHECK(value) check(bool(value), #value, __LINE__)

struct Capture {
  uint32_t m = 0;
  uint32_t n = 0;
  uint32_t k = 0;
  uint32_t poison = 0;
  std::vector<uint8_t> a;
  std::vector<uint8_t> b;
};
struct State {
  int contexts = 0;
  int operations = 0;
  int destructor_drains = 0;
  int submissions = 0;
  int create_calls = 0;
  int memory_calls = 0;
  uint64_t active_bytes = 0;
  int fail_create = 0;
  int fail_memory_at = 0;
  bool drift_memory = false;
  int timeout_stage = -1;
  int timeout_budget = 0;
  int fail_submit_stage = -1;
  bool partial_submit = false;
  int fail_wait_stage = -1;
  int fail_cleanup_stage = -1;
  bool fail_owner_cleanup = false;
  int owner_timeout_budget = 0;
  int fail_trace_allocation_stage = -1;
  std::array<std::vector<uint32_t>, 3> responses;
  std::array<Capture, 3> captures;
} state;

void no_resources() {
  CHECK(state.contexts == 0);
  CHECK(state.operations == 0);
  CHECK(state.active_bytes == 0);
  CHECK(!fail_next_allocation);
}

MlpCase fixture_case(const p04::Fixture& fixture, uint32_t poison = 0x7fc0deadu) {
  MlpCase result;
  result.case_id = fixture.id;
  result.input_dtype = std::string(fixture.format) == "fp16" ? DType::fp16 : DType::bf16;
  result.inputs = {fixture.inputs.input_words, fixture.inputs.w1_words, fixture.inputs.w2_words};
  result.expected = {fixture.expected.hidden_words, fixture.expected.bridge_words,
                     fixture.expected.output_words};
  result.poison = poison;
  return result;
}

void reset(const MlpCase& input) {
  no_resources();
  state = State{};
  state.responses[0].assign(input.expected.hidden_words.begin(), input.expected.hidden_words.end());
  state.responses[1].assign(input.expected.output_words.begin(), input.expected.output_words.begin() + 32);
  state.responses[2].assign(input.expected.output_words.begin() + 32, input.expected.output_words.end());
}

ExecutionBinding binding(DType dtype) {
  static const std::array<uint8_t, 16> module{};
  ExecutionBinding result;
  result.input_dtype = dtype;
  result.module_bytes = module.data();
  result.module_size = module.size();
  result.qualification_id = std::string(64, 'a');
  result.enable_profiling = true;
  return result;
}

std::unique_ptr<ManagedMlp> create(const MlpCase& input) {
  std::unique_ptr<ManagedMlp> model;
  const auto result = ManagedMlp::create(binding(input.input_dtype), input, &model);
  CHECK(result.ok() && result.complete && model != nullptr);
  CHECK(state.contexts == 1 && state.operations == 0);
  return model;
}

template <size_t N>
std::vector<uint8_t> bytes(const std::array<uint32_t, N>& words) {
  std::vector<uint8_t> result(N * 4);
  for (size_t index = 0; index != N; ++index) {
    for (unsigned byte = 0; byte != 4; ++byte) {
      result[index * 4 + byte] = static_cast<uint8_t>(words[index] >> (byte * 8));
    }
  }
  return result;
}

void finish(std::unique_ptr<ManagedMlp>* model) {
  CHECK((*model)->close(VX_TIMEOUT_INFINITE).complete);
  model->reset();
  no_resources();
}

void check_success(const ManagedMlp& model, const MlpCase& input) {
  const auto& trace = model.trace();
  CHECK(trace.result.ok());
  CHECK(state.submissions == 3);
  CHECK(state.operations == 0 && state.destructor_drains == 0);
  CHECK(trace.hidden_valid && trace.bridge_valid && trace.bridge_compared);
  CHECK(trace.assembled && trace.logits_valid && trace.logits_compared);
  CHECK(trace.hidden_words == input.expected.hidden_words);
  CHECK(trace.bridge_words == input.expected.bridge_words);
  CHECK(trace.output_words == input.expected.output_words);
  CHECK(trace.bridge_checked_words == 64 && trace.output_checked_words == 64);
  CHECK(trace.bridge_mismatches == 0 && trace.output_mismatches == 0);
  CHECK(trace.resources.before_valid && trace.resources.after_valid);
  CHECK(trace.resources.used_before == trace.resources.used_after);
  CHECK(trace.resources.free_before == trace.resources.free_after);
  const auto bridge = bytes(input.expected.bridge_words);
  CHECK(state.captures[0].a == bytes(input.inputs.input_words));
  CHECK(state.captures[0].b == bytes(input.inputs.w1_words));
  for (size_t stage = 0; stage != 3; ++stage) {
    const auto& record = trace.native[stage];
    const auto& capture = state.captures[stage];
    CHECK(record.submitted && record.waited && record.trace_valid && record.output_valid);
    CHECK(record.compared && record.closed && record.mismatches == 0);
    CHECK(record.submission.ok() && !record.submission.complete);
    CHECK(record.completion.ok() && record.completion.complete);
    CHECK(record.cleanup.ok() && record.cleanup.complete);
    CHECK(record.checked_words == (stage == 0 ? 128u : 32u));
    CHECK(record.sequence == stage);
    CHECK(capture.m == (stage == 0 ? 16u : 8u));
    CHECK(capture.n == (stage == 0 ? 8u : 4u));
    CHECK(capture.k == (stage == 0 ? 16u : 8u));
    CHECK(capture.poison == input.poison);
    CHECK(record.dispatch.profiling_enabled);
    CHECK(record.dispatch.event_profile_queried[4]);
    CHECK(record.dispatch.event_profile_results[4] == VX_SUCCESS);
    CHECK(record.dispatch.event_profiles[4].end_ns == 15);
    if (stage != 0) {
      CHECK(capture.b == bytes(input.inputs.w2_words));
      CHECK(capture.a == std::vector<uint8_t>(bridge.begin() + (stage - 1) * 128,
                                             bridge.begin() + stage * 128));
      CHECK(std::equal(capture.a.begin(), capture.a.end(), trace.bridge_bytes.begin() + (stage - 1) * 128));
      CHECK(record.row_begin == (stage == 1 ? 0u : 8u));
      CHECK(record.row_end == (stage == 1 ? 8u : 16u));
    }
  }
}
}

namespace vortex::ai::detail {
struct RuntimeContext {
  DType dtype = DType::fp16;
  std::string qualification_id;
  bool profiling = false;
  RuntimeContext() { ++state.contexts; }
  ~RuntimeContext() { --state.contexts; }
};
struct OperationState {
  std::shared_ptr<RuntimeContext> context;
  int stage = -1;
  uint64_t bytes = 0;
  bool closed = false;
  bool output_valid = false;
  ExecutionResult result{};
  MatmulTrace trace{};
  std::vector<uint32_t> output;
  OperationState() { ++state.operations; }
  ~OperationState() {
    CHECK(closed);
    --state.operations;
  }
};
}

namespace vortex::ai {
ManagedMatmul::ManagedMatmul(std::shared_ptr<detail::RuntimeContext> context)
    : context_(std::move(context)) {}
ManagedMatmul::~ManagedMatmul() = default;
ExecutionResult ManagedMatmul::create(const ExecutionBinding& input,
                                     std::unique_ptr<ManagedMatmul>* out) noexcept {
  ++state.create_calls;
  ExecutionResult result;
  if (state.fail_create) {
    result.primary = VX_ERR_DEVICE_LOST;
    return result;
  }
  auto context = std::make_shared<detail::RuntimeContext>();
  context->dtype = input.input_dtype;
  context->qualification_id = input.qualification_id;
  context->profiling = input.enable_profiling;
  out->reset(new ManagedMatmul(std::move(context)));
  return result;
}
ExecutionResult ManagedMatmul::submit(uint32_t m, uint32_t n, uint32_t k,
    const void* a, size_t a_size, const void* b, size_t b_size, uint32_t poison,
    std::unique_ptr<MatmulOperation>* out) noexcept {
  const int stage = state.submissions++;
  CHECK(stage >= 0 && stage < 3 && context_ && out && !*out);
  auto& capture = state.captures[stage];
  capture = {m, n, k, poison, std::vector<uint8_t>(static_cast<const uint8_t*>(a),
      static_cast<const uint8_t*>(a) + a_size),
      std::vector<uint8_t>(static_cast<const uint8_t*>(b), static_cast<const uint8_t*>(b) + b_size)};
  ExecutionResult result;
  if (stage == state.fail_submit_stage && !state.partial_submit) {
    result.primary = VX_ERR_OUT_OF_DEVICE_MEMORY;
    return result;
  }
  std::unique_ptr<MatmulOperation> operation(new MatmulOperation(context_));
  auto& op = *operation->state_;
  op.stage = stage;
  op.bytes = a_size + b_size + m * n * 4;
  state.active_bytes += op.bytes;
  op.output = state.responses[stage];
  op.result.complete = false;
  if (stage == state.fail_submit_stage) {
    op.result.primary = VX_ERR_OUT_OF_DEVICE_MEMORY;
  }
  auto& trace = op.trace;
  trace.qualification_id = context_->qualification_id;
  trace.input_dtype = context_->dtype;
  trace.m = m;
  trace.n = n;
  trace.k = k;
  trace.poison = poison;
  trace.a_bytes = a_size;
  trace.b_bytes = b_size;
  trace.d_bytes = m * n * 4;
  trace.a_address = 0x100000 + stage * 0x1000;
  trace.b_address = trace.a_address + a_size;
  trace.d_address = trace.b_address + b_size;
  trace.writes_enqueued = op.result.primary == VX_SUCCESS ? 3 : 1;
  trace.launches_enqueued = op.result.primary == VX_SUCCESS ? 1 : 0;
  trace.reads_enqueued = op.result.primary == VX_SUCCESS ? 1 : 0;
  trace.profiling_enabled = context_->profiling;
  result = op.result;
  if (stage == state.fail_trace_allocation_stage) {
    trace.qualification_id.assign(2048, 'b');
  }
  *out = std::move(operation);
  if (stage == state.fail_trace_allocation_stage) {
    fail_next_allocation = true;
  }
  return result;
}
vx_result_t ManagedMatmul::memory_info(uint64_t* free_bytes, uint64_t* used_bytes) const noexcept {
  ++state.memory_calls;
  if (!context_) {
    return VX_ERR_INVALID_HANDLE;
  }
  if (state.memory_calls == state.fail_memory_at) {
    return VX_ERR_INTERNAL;
  }
  *used_bytes = 4096 + state.active_bytes + (state.drift_memory && state.memory_calls > 1 ? 4 : 0);
  *free_bytes = 1048576 - *used_bytes;
  return VX_SUCCESS;
}
ExecutionResult ManagedMatmul::close() noexcept {
  ExecutionResult result;
  if (!context_) {
    return result;
  }
  if (context_.use_count() != 1 || state.owner_timeout_budget > 0) {
    if (state.owner_timeout_budget > 0) {
      --state.owner_timeout_budget;
    }
    result.primary = VX_ERR_TIMEOUT;
    result.complete = false;
    return result;
  }
  if (state.fail_owner_cleanup) {
    result.cleanup = VX_ERR_INTERNAL;
  }
  context_.reset();
  return result;
}
MatmulOperation::MatmulOperation(std::shared_ptr<detail::RuntimeContext> context)
    : state_(new detail::OperationState) {
  state_->context = std::move(context);
}
MatmulOperation::~MatmulOperation() {
  if (!state_->closed) {
    ++state.destructor_drains;
    CHECK(close(VX_TIMEOUT_INFINITE).complete);
  }
}
ExecutionResult MatmulOperation::wait(uint64_t timeout_ns) noexcept {
  auto& op = *state_;
  if (op.result.complete || op.closed) {
    return op.result;
  }
  ++op.trace.wait_calls;
  if (op.stage == state.timeout_stage && state.timeout_budget > 0 && timeout_ns != VX_TIMEOUT_INFINITE) {
    --state.timeout_budget;
    ++op.trace.timed_out_waits;
    auto transient = op.result;
    if (transient.primary == VX_SUCCESS) {
      transient.primary = VX_ERR_TIMEOUT;
    }
    return transient;
  }
  op.result.complete = true;
  if (op.stage == state.fail_wait_stage && op.result.primary == VX_SUCCESS) {
    op.result.primary = VX_ERR_EVENT_FAILED;
  }
  op.output_valid = op.result.ok();
  if (op.trace.profiling_enabled) {
    for (size_t i = 0; i != op.trace.event_profiles.size(); ++i) {
      op.trace.event_profile_queried[i] = true;
      op.trace.event_profile_results[i] = VX_SUCCESS;
      op.trace.event_profiles[i] = {1 + i, 4 + i, 8 + i, 11 + i};
      op.trace.event_results[i] = op.result.primary;
    }
  }
  return op.result;
}
ExecutionResult MatmulOperation::close(uint64_t timeout_ns) noexcept {
  auto result = wait(timeout_ns);
  if (!result.complete || state_->closed) {
    return result;
  }
  state_->closed = true;
  state.active_bytes -= state_->bytes;
  if (state_->stage == state.fail_cleanup_stage) {
    state_->result.cleanup = VX_ERR_INTERNAL;
  }
  return state_->result;
}
const std::vector<uint32_t>& MatmulOperation::output_words() const noexcept {
  static const std::vector<uint32_t> empty;
  return state_->output_valid ? state_->output : empty;
}
const MatmulTrace& MatmulOperation::trace() const noexcept { return state_->trace; }
}

namespace {
void positive_graph() {
  for (const auto& fixture : p04::kFixtures) {
    for (uint32_t poison : {0x7fc0deadu, 0xdeadbeefu}) {
      const auto input = fixture_case(fixture, poison);
      reset(input);
      auto model = create(input);
      CHECK(model->advance(100).ok());
      check_success(*model, input);
      CHECK(model->advance(0).ok() && state.submissions == 3);
      CHECK(model->close(100).ok());
      CHECK(model->trace().owner_closed && model->trace().result.ok());
      CHECK(model->close(0).ok());
      CHECK(model->advance(0).ok() && state.submissions == 3);
      finish(&model);
    }
  }
}
void copied_ownership() {
  auto input = fixture_case(p04::kFixtures[0]);
  const auto original = input;
  reset(input);
  auto model = create(input);
  input.inputs.input_words.fill(0xdeadbeefu);
  input.inputs.w1_words.fill(0);
  input.inputs.w2_words.fill(0);
  input.expected.hidden_words.fill(0);
  input.expected.bridge_words.fill(0);
  input.expected.output_words.fill(0);
  input.input_dtype = DType::bf16;
  input.case_id = "mutated";
  input.poison = 0;
  CHECK(model->advance(100).ok());
  check_success(*model, original);
  CHECK(model->trace().case_id == original.case_id);
  finish(&model);
}
void timeout_resume() {
  for (int stage = 0; stage != 3; ++stage) {
    const auto input = fixture_case(p04::kFixtures[4]);
    reset(input);
    state.timeout_stage = stage;
    state.timeout_budget = 2;
    auto model = create(input);
    for (int attempt = 0; attempt != 2; ++attempt) {
      const auto result = model->advance(0);
      CHECK(!result.terminal && !result.execution.complete);
      CHECK(result.execution.primary == VX_ERR_TIMEOUT);
      CHECK(state.submissions == stage + 1 && state.operations == 1);
      CHECK(state.destructor_drains == 0 && !model->trace().logits_valid);
      CHECK(!model->trace().native[stage].output_valid);
    }
    CHECK(model->advance(100).ok());
    CHECK(model->trace().native[stage].dispatch.timed_out_waits == 2);
    check_success(*model, input);
    finish(&model);
  }
}
void partial_submission() {
  for (int stage = 0; stage != 3; ++stage) {
    for (bool partial : {false, true}) {
      const auto input = fixture_case(p04::kFixtures[0]);
      reset(input);
      state.fail_submit_stage = stage;
      state.partial_submit = partial;
      state.timeout_stage = stage;
      state.timeout_budget = 2;
      auto model = create(input);
      const auto result = model->advance(0);
      CHECK(result.terminal && result.status == MlpStatus::runtime_error);
      CHECK(result.execution.primary == VX_ERR_OUT_OF_DEVICE_MEMORY);
      CHECK(result.execution.complete == !partial);
      CHECK(state.operations == int(partial) && state.submissions == stage + 1);
      CHECK(!model->advance(0).ok() && state.submissions == stage + 1);
      if (partial) {
        for (int attempt = 0; attempt != 2; ++attempt) {
          const auto cleanup = model->close(0);
          CHECK(!cleanup.complete && cleanup.primary == VX_ERR_OUT_OF_DEVICE_MEMORY);
          CHECK(state.operations == 1 && state.destructor_drains == 0);
        }
      }
      CHECK(model->close(100).complete);
      CHECK(model->trace().result.status == MlpStatus::runtime_error);
      CHECK(model->trace().result.execution.primary == VX_ERR_OUT_OF_DEVICE_MEMORY);
      CHECK(!model->trace().logits_valid && state.submissions == stage + 1);
      finish(&model);
    }
  }
}
void asynchronous_failures() {
  for (int stage = 0; stage != 3; ++stage) {
    const auto input = fixture_case(p04::kFixtures[0]);
    reset(input);
    state.fail_wait_stage = stage;
    auto model = create(input);
    const auto result = model->advance(100);
    CHECK(result.terminal && result.status == MlpStatus::runtime_error);
    CHECK(result.execution.primary == VX_ERR_EVENT_FAILED && result.execution.complete);
    CHECK(!model->trace().native[stage].output_valid && !model->trace().logits_valid);
    CHECK(state.submissions == stage + 1 && state.operations == 0);
    CHECK(!model->advance(0).ok() && state.submissions == stage + 1);
    finish(&model);
  }
}
void cleanup_failures() {
  for (int stage = 0; stage != 3; ++stage) {
    for (bool primary_failure : {false, true}) {
      const auto input = fixture_case(p04::kFixtures[0]);
      reset(input);
      state.fail_cleanup_stage = stage;
      state.fail_wait_stage = primary_failure ? stage : -1;
      auto model = create(input);
      const auto result = model->advance(100);
      CHECK(result.terminal && result.status == MlpStatus::runtime_error);
      CHECK(result.execution.cleanup == VX_ERR_INTERNAL);
      CHECK(result.execution.primary == (primary_failure ? VX_ERR_EVENT_FAILED : VX_SUCCESS));
      CHECK(state.submissions == stage + 1 && state.operations == 0);
      CHECK(model->trace().native[stage].closed && !model->trace().logits_valid);
      CHECK(model->close(100).cleanup == VX_ERR_INTERNAL);
      CHECK(model->trace().result.status == MlpStatus::runtime_error);
      finish(&model);
    }
  }
}
void comparison_stops() {
  for (int scenario = 0; scenario != 6; ++scenario) {
    auto input = fixture_case(p04::kFixtures[scenario == 1 ? 2 : scenario == 3 ? 4 : 0]);
    reset(input);
    int expected_submissions = 1;
    MlpStatus expected_status = MlpStatus::hidden_mismatch;
    if (scenario == 0) {
      CHECK(state.responses[0][0] == 0xbf800000u);
      state.responses[0][0] = 0xc0000000u;
    } else if (scenario == 1) {
      state.responses[0][0] = 0x80000000u;
    } else if (scenario == 2) {
      input.expected.bridge_words[0] ^= 1;
      expected_status = MlpStatus::bridge_mismatch;
    } else {
      expected_submissions = scenario == 5 ? 3 : 2;
      expected_status = MlpStatus::output_mismatch;
      if (scenario == 3) {
        std::swap(state.responses[1], state.responses[2]);
      } else {
        state.responses[scenario == 5 ? 2 : 1][31] ^= 1;
      }
    }
    auto model = create(input);
    const auto result = model->advance(100);
    CHECK(result.terminal && result.status == expected_status && !result.ok());
    CHECK(state.submissions == expected_submissions);
    CHECK(!model->trace().logits_valid && !model->trace().assembled);
    if (scenario <= 1) {
      CHECK(!model->trace().bridge_attempted);
      CHECK(model->trace().native[0].mismatches == 1);
      CHECK(model->trace().hidden_words[0] == state.responses[0][0]);
    }
    CHECK(model->close(100).complete);
    CHECK(model->trace().result.status == expected_status);
    CHECK(!model->advance(0).ok() && state.submissions == expected_submissions);
    finish(&model);
  }
}
void bridge_domain() {
  for (uint32_t bits : {0x42820000u, 0xc2820000u, 0x3f000000u, 0xbf000000u,
                        0x00000001u, 0x80000001u, 0x7f800000u, 0xff800000u, 0x7fc00000u}) {
    auto input = fixture_case(p04::kFixtures[0]);
    input.expected.hidden_words[127] = bits;
    reset(input);
    auto model = create(input);
    const auto result = model->advance(100);
    CHECK(result.terminal && result.status == MlpStatus::bridge_error);
    CHECK(model->trace().native[0].mismatches == 0 && model->trace().hidden_valid);
    CHECK(model->trace().bridge_attempted && !model->trace().bridge_valid);
    CHECK(model->trace().bridge_status == BridgeStatus::invalid_value);
    CHECK(!model->trace().bridge_compared && state.submissions == 1);
    finish(&model);
  }
}
void close_boundaries() {
  const auto input = fixture_case(p04::kFixtures[0]);
  reset(input);
  auto model = create(input);
  CHECK(model->close(0).complete);
  CHECK(model->advance(0).status == MlpStatus::closed);
  CHECK(state.submissions == 0);
  finish(&model);
  for (int stage = 0; stage != 3; ++stage) {
    reset(input);
    state.timeout_stage = stage;
    state.timeout_budget = 3;
    model = create(input);
    CHECK(!model->advance(0).execution.complete);
    CHECK(!model->close(0).complete);
    CHECK(model->advance(0).status == MlpStatus::closed);
    CHECK(state.submissions == stage + 1 && state.operations == 1);
    CHECK(!model->close(0).complete);
    CHECK(model->close(100).complete);
    CHECK(state.submissions == stage + 1 && state.destructor_drains == 0);
    CHECK(!model->trace().logits_valid);
    finish(&model);
  }
  reset(input);
  state.timeout_stage = 0;
  state.timeout_budget = 100;
  model = create(input);
  CHECK(!model->advance(0).execution.complete);
  model.reset();
  CHECK(state.submissions == 1 && state.destructor_drains == 0);
  no_resources();
}
void invalid_create() {
  auto input = fixture_case(p04::kFixtures[0]);
  reset(input);
  std::unique_ptr<ManagedMlp> model;
  CHECK(!ManagedMlp::create(binding(input.input_dtype), input, nullptr).ok());
  for (const std::string& id : {std::string{}, std::string("bad/id"), std::string(129, 'a')}) {
    auto invalid = input;
    invalid.case_id = id;
    CHECK(ManagedMlp::create(binding(invalid.input_dtype), invalid, &model).validation == Status::invalid_argument);
    CHECK(!model);
  }
  auto invalid = input;
  invalid.input_dtype = DType::fp32;
  CHECK(ManagedMlp::create(binding(DType::fp32), invalid, &model).validation == Status::unsupported_dtype);
  CHECK(ManagedMlp::create(binding(DType::bf16), input, &model).validation == Status::unsupported_dtype);
  CHECK(state.create_calls == 0);
  model = create(input);
  const auto* original = model.get();
  CHECK(!ManagedMlp::create(binding(input.input_dtype), input, &model).ok());
  CHECK(model.get() == original);
  finish(&model);
  reset(input);
  state.fail_create = 1;
  CHECK(ManagedMlp::create(binding(input.input_dtype), input, &model).primary == VX_ERR_DEVICE_LOST);
  CHECK(!model);
  no_resources();
  reset(input);
  state.fail_memory_at = 1;
  CHECK(ManagedMlp::create(binding(input.input_dtype), input, &model).primary == VX_ERR_INTERNAL);
  CHECK(!model);
  no_resources();
}
void resources_and_owner() {
  const auto input = fixture_case(p04::kFixtures[0]);
  for (bool failed_query : {false, true}) {
    reset(input);
    state.drift_memory = !failed_query;
    state.fail_memory_at = failed_query ? 2 : 0;
    auto model = create(input);
    const auto result = model->advance(100);
    CHECK(result.terminal && !result.ok());
    CHECK(result.status == (failed_query ? MlpStatus::runtime_error : MlpStatus::resource_mismatch));
    CHECK(state.submissions == 3 && state.operations == 0);
    CHECK(model->trace().resources.after_valid == !failed_query);
    finish(&model);
  }
  reset(input);
  auto model = create(input);
  CHECK(model->advance(100).ok());
  state.fail_owner_cleanup = true;
  CHECK(model->close(100).cleanup == VX_ERR_INTERNAL);
  CHECK(!model->trace().result.ok() && model->trace().result.status == MlpStatus::runtime_error);
  CHECK(model->close(0).cleanup == VX_ERR_INTERNAL);
  finish(&model);
  reset(input);
  model = create(input);
  CHECK(model->advance(100).ok());
  state.owner_timeout_budget = 2;
  CHECK(!model->close(0).complete);
  CHECK(!model->advance(0).execution.complete);
  CHECK(!model->close(0).complete);
  CHECK(model->close(100).ok());
  CHECK(model->trace().owner_closed && model->trace().result.ok());
  finish(&model);
}
void output_sizes() {
  const auto input = fixture_case(p04::kFixtures[0]);
  for (int stage = 0; stage != 3; ++stage) {
    for (int change : {-1, 1}) {
      reset(input);
      state.responses[stage].resize((stage == 0 ? 128 : 32) + change);
      auto model = create(input);
      const auto result = model->advance(100);
      CHECK(result.terminal && result.status == MlpStatus::runtime_error);
      CHECK(result.execution.primary == VX_ERR_INTERNAL);
      CHECK(!model->trace().native[stage].output_valid && !model->trace().logits_valid);
      CHECK(state.submissions == stage + 1);
      finish(&model);
    }
  }
}
void allocation_failures() {
  const auto input = fixture_case(p04::kFixtures[0]);
  reset(input);
  std::unique_ptr<ManagedMlp> model;
  auto qualified = binding(input.input_dtype);
  fail_next_allocation = true;
  CHECK(ManagedMlp::create(qualified, input, &model).primary == VX_ERR_OUT_OF_HOST_MEMORY);
  CHECK(!model && state.create_calls == 0);
  no_resources();
  for (int stage = 0; stage != 3; ++stage) {
    reset(input);
    state.fail_trace_allocation_stage = stage;
    model = create(input);
    const auto result = model->advance(100);
    CHECK(result.terminal && result.status == MlpStatus::runtime_error);
    CHECK(result.execution.primary == VX_ERR_OUT_OF_HOST_MEMORY && !result.execution.complete);
    CHECK(state.submissions == stage + 1 && state.operations == 1 && state.destructor_drains == 0);
    CHECK(!model->trace().native[stage].trace_valid);
    CHECK(model->close(100).complete);
    CHECK(!model->trace().result.ok());
    finish(&model);
  }
}
void repetitions() {
  for (size_t repetition = 0; repetition != 32; ++repetition) {
    const auto input = fixture_case(p04::kFixtures[repetition % p04::kCaseCount]);
    reset(input);
    auto model = create(input);
    CHECK(model->advance(100).ok());
    CHECK(model->trace().resources.used_before == model->trace().resources.used_after);
    finish(&model);
  }
}
}

int main(int argc, char** argv) {
  CHECK(argc == 2);
  current_group = argv[1];
  const std::string name = current_group;
  if (name == "positive_graph") {
    positive_graph();
  } else if (name == "copied_ownership") {
    copied_ownership();
  } else if (name == "timeout_resume") {
    timeout_resume();
  } else if (name == "partial_submission") {
    partial_submission();
  } else if (name == "asynchronous_failures") {
    asynchronous_failures();
  } else if (name == "cleanup_failures") {
    cleanup_failures();
  } else if (name == "comparison_stops") {
    comparison_stops();
  } else if (name == "bridge_domain") {
    bridge_domain();
  } else if (name == "close_boundaries") {
    close_boundaries();
  } else if (name == "invalid_create") {
    invalid_create();
  } else if (name == "resources_and_owner") {
    resources_and_owner();
  } else if (name == "output_sizes") {
    output_sizes();
  } else if (name == "allocation_failures") {
    allocation_failures();
  } else if (name == "repetitions") {
    repetitions();
  } else {
    CHECK(false);
  }
  no_resources();
  std::cout << "PASS " << name << " checks=" << checks << '\n';
  return 0;
}
