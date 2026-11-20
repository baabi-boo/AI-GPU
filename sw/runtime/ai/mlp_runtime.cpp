// SPDX-License-Identifier: Apache-2.0

#include "mlp_runtime.h"
#include <algorithm>
#include <chrono>
#include <limits>
#include <new>
#include <thread>

namespace vortex::ai {
namespace {

uint64_t now_ns() noexcept {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count());
}

void add_elapsed(uint64_t* total, uint64_t begin) noexcept {
  const uint64_t end = now_ns();
  const uint64_t elapsed = end >= begin ? end - begin : 0;
  const uint64_t maximum = std::numeric_limits<uint64_t>::max();
  *total = elapsed > maximum - *total ? maximum : *total + elapsed;
}

class Duration {
 public:
  explicit Duration(uint64_t* total) noexcept : total_(total), begin_(now_ns()) {}
  ~Duration() { add_elapsed(total_, begin_); }

 private:
  uint64_t* total_;
  uint64_t begin_;
};

void merge(ExecutionResult* target, const ExecutionResult& source) noexcept {
  if (target->validation == Status::success) {
    target->validation = source.validation;
  }
  if (target->primary == VX_SUCCESS) {
    target->primary = source.primary;
  }
  if (target->cleanup == VX_SUCCESS) {
    target->cleanup = source.cleanup;
  }
}

ExecutionResult runtime_error(vx_result_t error) noexcept {
  ExecutionResult result;
  result.primary = error;
  return result;
}

bool valid_case_id(const std::string& id) noexcept {
  return !id.empty() && id.size() <= 128
      && std::all_of(id.begin(), id.end(), [](char value) {
           return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z')
               || (value >= '0' && value <= '9') || value == '_' || value == '-';
         });
}

template <size_t N>
void serialize(const std::array<uint32_t, N>& words, uint8_t* bytes) noexcept {
  for (size_t i = 0; i != N; ++i) {
    for (unsigned byte = 0; byte != 4; ++byte) {
      bytes[i * 4 + byte] = static_cast<uint8_t>(words[i] >> (byte * 8));
    }
  }
}

uint32_t read_word(const uint8_t* bytes) noexcept {
  uint32_t value = 0;
  for (unsigned byte = 0; byte != 4; ++byte) {
    value |= uint32_t{bytes[byte]} << (byte * 8);
  }
  return value;
}

} // namespace

ManagedMlp::ManagedMlp(const MlpCase& input) : input_(input) {
  trace_.case_id = input.case_id;
  trace_.input_dtype = input.input_dtype;
  trace_.poison = input.poison;
  const std::array<const char*, 3> ids{
      "hidden_matmul", "output_rows_0_7", "output_rows_8_15"};
  const std::array<uint32_t, 3> sequences{0, 1, 2};
  for (size_t i = 0; i != trace_.native.size(); ++i) {
    auto& record = trace_.native[i];
    record.operation_id = ids[i];
    record.sequence = sequences[i];
    record.row_begin = i == 2 ? 8 : 0;
    record.row_end = i == 1 ? 8 : 16;
  }
}

ManagedMlp::~ManagedMlp() {
  while (!close(VX_TIMEOUT_INFINITE).complete) {
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
}

ExecutionResult ManagedMlp::create(const ExecutionBinding& binding, const MlpCase& input,
                                  std::unique_ptr<ManagedMlp>* out) noexcept {
  const uint64_t begin = now_ns();
  ExecutionResult result;
  if (!out || *out || !valid_case_id(input.case_id)) {
    result.validation = Status::invalid_argument;
    return result;
  }
  if ((input.input_dtype != DType::fp16 && input.input_dtype != DType::bf16)
      || input.input_dtype != binding.input_dtype) {
    result.validation = Status::unsupported_dtype;
    return result;
  }
  std::unique_ptr<ManagedMlp> model;
  try {
    model.reset(new ManagedMlp(input));
    model->trace_.create_begin_ns = begin;
    for (auto& record : model->trace_.native) {
      record.dispatch.qualification_id = binding.qualification_id;
    }
    result = ManagedMatmul::create(binding, &model->owner_);
    if (result.ok() && result.complete) {
      auto& resources = model->trace_.resources;
      resources.before_status = model->owner_->memory_info(
          &resources.free_before, &resources.used_before);
      resources.before_valid = resources.before_status == VX_SUCCESS;
      result.primary = resources.before_status;
    }
    if (result.ok() && result.complete) {
      model->trace_.create_end_ns = now_ns();
      *out = std::move(model);
      return result;
    }
  } catch (const std::bad_alloc&) {
    result.primary = VX_ERR_OUT_OF_HOST_MEMORY;
  } catch (...) {
    result.primary = VX_ERR_INTERNAL;
  }
  if (model && model->owner_) {
    merge(&result, model->owner_->close());
  }
  return result;
}

void ManagedMlp::fail(MlpStatus status, const ExecutionResult& execution) noexcept {
  if (!result_.terminal || result_.status == MlpStatus::success) {
    result_.status = status;
  }
  result_.terminal = true;
  merge(&result_.execution, execution);
}

MlpResult ManagedMlp::result(const ExecutionResult* transient) noexcept {
  result_.execution.complete = (!operation_ || operation_complete_) && owner_close_complete_;
  auto current = result_;
  if (transient) {
    merge(&current.execution, *transient);
  }
  trace_.result = current;
  return current;
}

bool ManagedMlp::save_trace() noexcept {
  if (!operation_) {
    return true;
  }
  auto& record = trace_.native[stage_];
  record.trace_valid = false;
  try {
    record.dispatch = operation_->trace();
    record.trace_valid = true;
    return true;
  } catch (const std::bad_alloc&) {
    fail(MlpStatus::runtime_error, runtime_error(VX_ERR_OUT_OF_HOST_MEMORY));
  } catch (...) {
    fail(MlpStatus::runtime_error, runtime_error(VX_ERR_INTERNAL));
  }
  return false;
}

void ManagedMlp::submit_stage() noexcept {
  auto& record = trace_.native[stage_];
  if (stage_ == 0) {
    serialize(input_.inputs.input_words, record.a_bytes.data());
    serialize(input_.inputs.w1_words, record.b_bytes.data());
    record.a_size = 512;
    record.b_size = 256;
  } else {
    const size_t offset = (stage_ - 1) * 128;
    std::copy_n(trace_.bridge_bytes.begin() + offset, 128, record.a_bytes.begin());
    serialize(input_.inputs.w2_words, record.b_bytes.data());
    record.a_size = 128;
    record.b_size = 64;
  }
  record.submitted = true;
  record.submit_begin_ns = now_ns();
  record.submission = owner_->submit(stage_ == 0 ? 16 : 8, stage_ == 0 ? 8 : 4,
      stage_ == 0 ? 16 : 8, record.a_bytes.data(), record.a_size,
      record.b_bytes.data(), record.b_size, input_.poison, &operation_);
  record.submit_end_ns = now_ns();
  operation_complete_ = record.submission.complete;
  if (!record.submission.ok()) {
    fail(MlpStatus::runtime_error, record.submission);
  } else if (!operation_) {
    fail(MlpStatus::runtime_error, runtime_error(VX_ERR_INTERNAL));
  }
  save_trace();
}

void ManagedMlp::compare_stage() noexcept {
  auto& record = trace_.native[stage_];
  const auto& actual = operation_->output_words();
  const size_t count = stage_ == 0 ? 128 : 32;
  record.output_count = actual.size();
  if (actual.size() != count) {
    fail(MlpStatus::runtime_error, runtime_error(VX_ERR_INTERNAL));
    return;
  }
  std::copy(actual.begin(), actual.end(), record.output_words.begin());
  record.output_valid = true;
  if (stage_ == 0) {
    std::copy(actual.begin(), actual.end(), trace_.hidden_words.begin());
    trace_.hidden_valid = true;
  }
  const uint32_t* expected = stage_ == 0 ? input_.expected.hidden_words.data()
      : input_.expected.output_words.data() + (stage_ - 1) * 32;
  {
    Duration duration(&record.compare_ns);
    for (size_t i = 0; i != count; ++i) {
      ++record.checked_words;
      if (record.output_words[i] != expected[i]) {
        ++record.mismatches;
      }
    }
  }
  record.compared = true;
  if (record.mismatches != 0) {
    fail(stage_ == 0 ? MlpStatus::hidden_mismatch : MlpStatus::output_mismatch, {});
  }
}

bool ManagedMlp::release_operation(uint64_t timeout_ns) noexcept {
  if (!operation_) {
    return true;
  }
  auto& record = trace_.native[stage_];
  {
    Duration duration(&record.close_ns);
    record.cleanup = operation_->close(timeout_ns);
  }
  operation_complete_ = record.cleanup.complete;
  save_trace();
  if (!record.cleanup.complete) {
    if (record.cleanup.primary != VX_ERR_TIMEOUT && !record.cleanup.ok()) {
      fail(MlpStatus::runtime_error, record.cleanup);
    }
    return false;
  }
  if (!record.cleanup.ok()) {
    fail(MlpStatus::runtime_error, record.cleanup);
  }
  record.closed = true;
  operation_.reset();
  return true;
}

void ManagedMlp::bridge() noexcept {
  trace_.bridge_attempted = true;
  BridgeResult converted;
  {
    Duration duration(&trace_.bridge_ns);
    converted = prepare_mlp_hidden(trace_.hidden_words.data(), trace_.hidden_words.size(),
                                   input_.input_dtype);
  }
  trace_.bridge_status = converted.status;
  if (converted.status != BridgeStatus::success) {
    fail(MlpStatus::bridge_error, {});
    return;
  }
  trace_.bridge_bytes = converted.bytes;
  trace_.bridge_valid = true;
  {
    Duration duration(&trace_.bridge_compare_ns);
    for (size_t i = 0; i != trace_.bridge_words.size(); ++i) {
      trace_.bridge_words[i] = read_word(trace_.bridge_bytes.data() + i * 4);
      ++trace_.bridge_checked_words;
      if (trace_.bridge_words[i] != input_.expected.bridge_words[i]) {
        ++trace_.bridge_mismatches;
      }
    }
  }
  trace_.bridge_compared = true;
  if (trace_.bridge_mismatches != 0) {
    fail(MlpStatus::bridge_mismatch, {});
  }
}

void ManagedMlp::assemble() noexcept {
  {
    Duration duration(&trace_.assembly_ns);
    std::copy_n(trace_.native[1].output_words.begin(), 32, trace_.output_words.begin());
    std::copy_n(trace_.native[2].output_words.begin(), 32, trace_.output_words.begin() + 32);
  }
  trace_.assembled = true;
  trace_.logits_valid = true;
  {
    Duration duration(&trace_.output_compare_ns);
    for (size_t i = 0; i != trace_.output_words.size(); ++i) {
      ++trace_.output_checked_words;
      if (trace_.output_words[i] != input_.expected.output_words[i]) {
        ++trace_.output_mismatches;
      }
    }
  }
  trace_.logits_compared = true;
  if (trace_.output_mismatches != 0) {
    fail(MlpStatus::output_mismatch, {});
  } else {
    result_.status = MlpStatus::success;
    result_.terminal = true;
  }
}

void ManagedMlp::check_resources() noexcept {
  if (resources_checked_ || operation_ || !owner_) {
    return;
  }
  resources_checked_ = true;
  auto& resources = trace_.resources;
  resources.after_status = owner_->memory_info(&resources.free_after, &resources.used_after);
  resources.after_valid = resources.after_status == VX_SUCCESS;
  if (!resources.after_valid) {
    fail(MlpStatus::runtime_error, runtime_error(resources.after_status));
  } else if (!resources.before_valid || resources.free_before != resources.free_after
             || resources.used_before != resources.used_after) {
    fail(MlpStatus::resource_mismatch, {});
  }
}

MlpResult ManagedMlp::advance(uint64_t timeout_ns) noexcept {
  Duration duration(&trace_.advance_ns);
  if (result_.terminal || closing_) {
    return result();
  }
  while (stage_ != trace_.native.size()) {
    if (!operation_) {
      submit_stage();
      if (result_.terminal) {
        return result();
      }
    }
    auto& record = trace_.native[stage_];
    if (!record.compared) {
      record.waited = true;
      {
        Duration wait_duration(&record.wait_ns);
        record.completion = operation_->wait(timeout_ns);
      }
      operation_complete_ = record.completion.complete;
      save_trace();
      if (!record.completion.complete) {
        if (record.completion.primary != VX_ERR_TIMEOUT && !record.completion.ok()) {
          fail(MlpStatus::runtime_error, record.completion);
        }
        return result(&record.completion);
      }
      if (!record.completion.ok()) {
        fail(MlpStatus::runtime_error, record.completion);
      }
      if (!result_.terminal) {
        compare_stage();
      }
    }
    if (!release_operation(timeout_ns)) {
      return result(&record.cleanup);
    }
    if (result_.terminal) {
      check_resources();
      return result();
    }
    if (stage_ == 0) {
      bridge();
      if (result_.terminal) {
        check_resources();
        return result();
      }
    }
    ++stage_;
  }
  assemble();
  check_resources();
  return result();
}

ExecutionResult ManagedMlp::close(uint64_t timeout_ns) noexcept {
  Duration duration(&trace_.close_ns);
  closing_ = true;
  if (!result_.terminal) {
    result_.status = MlpStatus::closed;
    result_.terminal = true;
  }
  if (!release_operation(timeout_ns)) {
    return result(&trace_.native[stage_].cleanup).execution;
  }
  check_resources();
  if (owner_ && !trace_.owner_closed) {
    trace_.owner_cleanup = owner_->close();
    owner_close_complete_ = trace_.owner_cleanup.complete;
    if (!trace_.owner_cleanup.ok()) {
      if (trace_.owner_cleanup.complete || trace_.owner_cleanup.primary != VX_ERR_TIMEOUT) {
        fail(MlpStatus::runtime_error, trace_.owner_cleanup);
      }
    }
    if (!trace_.owner_cleanup.complete) {
      return result(&trace_.owner_cleanup).execution;
    }
    trace_.owner_closed = true;
    owner_.reset();
  }
  return result().execution;
}

const MlpTrace& ManagedMlp::trace() const noexcept {
  return trace_;
}

const char* mlp_status_string(MlpStatus status) noexcept {
  switch (status) {
    case MlpStatus::in_progress: return "in_progress";
    case MlpStatus::success: return "success";
    case MlpStatus::runtime_error: return "runtime_error";
    case MlpStatus::hidden_mismatch: return "hidden_mismatch";
    case MlpStatus::bridge_error: return "bridge_error";
    case MlpStatus::bridge_mismatch: return "bridge_mismatch";
    case MlpStatus::output_mismatch: return "output_mismatch";
    case MlpStatus::resource_mismatch: return "resource_mismatch";
    case MlpStatus::closed: return "closed";
  }
  return "unknown";
}

} // namespace vortex::ai
