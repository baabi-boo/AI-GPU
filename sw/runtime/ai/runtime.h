// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_RUNTIME_H
#define VORTEX_AI_RUNTIME_H

#include "contract.h"
#include <vortex2.h>
#include <memory>
#include <string>
#include <vector>

namespace vortex::ai {

// A trusted runner verifies image/backend/compiler records before supplying this binding.
struct ExecutionBinding {
  ProfileBinding profile{};
  DType input_dtype = DType::fp16;
  const void* module_bytes = nullptr;
  size_t module_size = 0;
  std::string qualification_id;
};

struct ExecutionResult {
  Status validation = Status::success;
  vx_result_t primary = VX_SUCCESS;
  vx_result_t cleanup = VX_SUCCESS;
  bool complete = true;

  bool ok() const noexcept {
    return validation == Status::success && primary == VX_SUCCESS && cleanup == VX_SUCCESS;
  }
};

struct MatmulTrace {
  std::string qualification_id;
  DType input_dtype = DType::fp16;
  uint32_t m = 0;
  uint32_t n = 0;
  uint32_t k = 0;
  uint32_t poison = 0;
  uint64_t a_address = 0;
  uint64_t b_address = 0;
  uint64_t d_address = 0;
  uint64_t a_bytes = 0;
  uint64_t b_bytes = 0;
  uint64_t d_bytes = 0;
  ArgumentBytes argument_bytes{};
  uint32_t writes_enqueued = 0;
  uint32_t launches_enqueued = 0;
  uint32_t reads_enqueued = 0;
  uint64_t wait_calls = 0;
  uint64_t timed_out_waits = 0;
  std::array<vx_result_t, 5> event_results{};
};

namespace detail {
struct RuntimeContext;
struct OperationState;
}

class MatmulOperation {
 public:
  // Destruction drains indefinitely; retain ownership after a bounded close times out.
  ~MatmulOperation();
  MatmulOperation(const MatmulOperation&) = delete;
  MatmulOperation& operator=(const MatmulOperation&) = delete;

  ExecutionResult wait(uint64_t timeout_ns) noexcept;
  ExecutionResult close(uint64_t timeout_ns) noexcept;
  const std::vector<uint32_t>& output_words() const noexcept;
  const MatmulTrace& trace() const noexcept;

 private:
  friend class ManagedMatmul;
  explicit MatmulOperation(std::shared_ptr<detail::RuntimeContext> context);
  std::unique_ptr<detail::OperationState> state_;
};

// Single-caller objects; operations may outlive their ManagedMatmul owner.
class ManagedMatmul {
 public:
  ~ManagedMatmul();
  ManagedMatmul(const ManagedMatmul&) = delete;
  ManagedMatmul& operator=(const ManagedMatmul&) = delete;

  static ExecutionResult create(const ExecutionBinding& binding,
                                std::unique_ptr<ManagedMatmul>* out) noexcept;

  // A partial submission returns its owned operation even when primary is an error.
  ExecutionResult submit(uint32_t m, uint32_t n, uint32_t k,
                         const void* a, size_t a_bytes,
                         const void* b, size_t b_bytes, uint32_t poison,
                         std::unique_ptr<MatmulOperation>* out) noexcept;
  vx_result_t memory_info(uint64_t* free_bytes, uint64_t* used_bytes) const noexcept;
  ExecutionResult close() noexcept;

 private:
  explicit ManagedMatmul(std::shared_ptr<detail::RuntimeContext> context);
  std::shared_ptr<detail::RuntimeContext> context_;
};

} // namespace vortex::ai

#endif
