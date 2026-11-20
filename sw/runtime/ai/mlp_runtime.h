// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_MLP_RUNTIME_H
#define VORTEX_AI_MLP_RUNTIME_H

#include "mlp_host.h"
#include "runtime.h"

namespace vortex::ai {

struct MlpInputs {
  std::array<uint32_t, 128> input_words{};
  std::array<uint32_t, 64> w1_words{};
  std::array<uint32_t, 16> w2_words{};
};

struct MlpReference {
  std::array<uint32_t, 128> hidden_words{};
  std::array<uint32_t, 64> bridge_words{};
  std::array<uint32_t, 64> output_words{};
};

struct MlpCase {
  std::string case_id;
  DType input_dtype = DType::fp16;
  MlpInputs inputs{};
  MlpReference expected{};
  uint32_t poison = 0x7fc0deadu;
};

enum class MlpStatus : uint32_t {
  in_progress,
  success,
  runtime_error,
  hidden_mismatch,
  bridge_error,
  bridge_mismatch,
  output_mismatch,
  resource_mismatch,
  closed
};

struct MlpResult {
  MlpStatus status = MlpStatus::in_progress;
  // A terminal inference failure can still own an incomplete native operation.
  ExecutionResult execution{};
  bool terminal = false;

  bool ok() const noexcept {
    return terminal && status == MlpStatus::success
        && execution.ok() && execution.complete;
  }
};

struct MlpNativeStage {
  const char* operation_id = nullptr;
  uint32_t sequence = 0;
  uint32_t row_begin = 0;
  uint32_t row_end = 0;
  bool submitted = false;
  bool waited = false;
  bool trace_valid = false;
  bool output_valid = false;
  bool compared = false;
  bool closed = false;
  ExecutionResult submission{};
  ExecutionResult completion{};
  ExecutionResult cleanup{};
  MatmulTrace dispatch{};
  size_t a_size = 0;
  size_t b_size = 0;
  size_t output_count = 0;
  std::array<uint8_t, 512> a_bytes{};
  std::array<uint8_t, 256> b_bytes{};
  std::array<uint32_t, 128> output_words{};
  uint32_t checked_words = 0;
  uint32_t mismatches = 0;
  uint64_t submit_begin_ns = 0;
  uint64_t submit_end_ns = 0;
  uint64_t wait_ns = 0;
  uint64_t compare_ns = 0;
  uint64_t close_ns = 0;
};

struct MlpResources {
  bool before_valid = false;
  bool after_valid = false;
  vx_result_t before_status = VX_ERR_NOT_SUPPORTED;
  vx_result_t after_status = VX_ERR_NOT_SUPPORTED;
  uint64_t free_before = 0;
  uint64_t used_before = 0;
  uint64_t free_after = 0;
  uint64_t used_after = 0;
};

struct MlpTrace {
  std::string case_id;
  DType input_dtype = DType::fp16;
  uint32_t poison = 0;
  std::array<MlpNativeStage, 3> native{};
  // Valid means observed, not numerically matched; result.ok() establishes success.
  bool hidden_valid = false;
  bool bridge_attempted = false;
  bool bridge_valid = false;
  bool bridge_compared = false;
  bool assembled = false;
  bool logits_valid = false;
  bool logits_compared = false;
  bool owner_closed = false;
  BridgeStatus bridge_status = BridgeStatus::invalid_argument;
  std::array<uint32_t, 128> hidden_words{};
  std::array<uint8_t, 256> bridge_bytes{};
  std::array<uint32_t, 64> bridge_words{};
  std::array<uint32_t, 64> output_words{};
  uint32_t bridge_checked_words = 0;
  uint32_t bridge_mismatches = 0;
  uint32_t output_checked_words = 0;
  uint32_t output_mismatches = 0;
  uint64_t create_begin_ns = 0;
  uint64_t create_end_ns = 0;
  uint64_t advance_ns = 0;
  uint64_t bridge_ns = 0;
  uint64_t bridge_compare_ns = 0;
  uint64_t assembly_ns = 0;
  uint64_t output_compare_ns = 0;
  uint64_t close_ns = 0;
  MlpResources resources{};
  ExecutionResult owner_cleanup{};
  MlpResult result{};
};

// Single-caller fixed graph; the trusted runner owns fixture/profile provenance.
class ManagedMlp {
 public:
  // Destruction drains indefinitely; retain this owner after an incomplete close.
  ~ManagedMlp();
  ManagedMlp(const ManagedMlp&) = delete;
  ManagedMlp& operator=(const ManagedMlp&) = delete;

  static ExecutionResult create(const ExecutionBinding& binding, const MlpCase& input,
                                std::unique_ptr<ManagedMlp>* out) noexcept;

  // timeout_ns applies to each wait/drain, not to the whole call or host work.
  MlpResult advance(uint64_t timeout_ns) noexcept;
  // A successful drain does not erase an earlier inference failure.
  ExecutionResult close(uint64_t timeout_ns) noexcept;
  const MlpTrace& trace() const noexcept;

 private:
  explicit ManagedMlp(const MlpCase& input);
  void fail(MlpStatus status, const ExecutionResult& execution) noexcept;
  MlpResult result(const ExecutionResult* transient = nullptr) noexcept;
  bool save_trace() noexcept;
  bool release_operation(uint64_t timeout_ns) noexcept;
  void check_resources() noexcept;
  void submit_stage() noexcept;
  void compare_stage() noexcept;
  void bridge() noexcept;
  void assemble() noexcept;

  MlpCase input_;
  MlpTrace trace_{};
  MlpResult result_{};
  std::unique_ptr<ManagedMatmul> owner_;
  std::unique_ptr<MatmulOperation> operation_;
  size_t stage_ = 0;
  bool operation_complete_ = true;
  bool owner_close_complete_ = true;
  bool closing_ = false;
  bool resources_checked_ = false;
};

const char* mlp_status_string(MlpStatus status) noexcept;

} // namespace vortex::ai

#endif
