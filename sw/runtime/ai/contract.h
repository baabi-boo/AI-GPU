// SPDX-License-Identifier: Apache-2.0

#ifndef VORTEX_AI_CONTRACT_H
#define VORTEX_AI_CONTRACT_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace vortex::ai {

constexpr uint32_t kContractVersion = 1;
constexpr uint32_t kArgumentBytes = 56;

enum class Operator : uint32_t {
  matmul = 1, gemv, reduction, softmax, normalization, activation, layout_cast, attention
};

enum class DType : uint32_t { fp16 = 1, bf16 = 2, fp32 = 3 };
enum class Layout : uint32_t { row_major = 1, column_major = 2 };
enum class Profile : uint32_t { unqualified = 0, p02_tfr_wmma_v1 = 1 };

enum class Status : uint32_t {
  success = 0,
  invalid_argument,
  invalid_version,
  unsupported_operator,
  unsupported_dtype,
  unsupported_shape,
  unsupported_layout,
  unsupported_profile,
  invalid_rank,
  empty_tensor,
  device_mismatch,
  invalid_access,
  misaligned_address,
  insufficient_buffer,
  arithmetic_overflow,
  address_out_of_range,
  aliasing
};

struct AllocationView {
  uint64_t device_id = 0;
  uint64_t allocation_id = 0;
  uint64_t address = 0;
  uint64_t size_bytes = 0;
  bool readable = false;
  bool writable = false;
};

struct TensorView {
  uint32_t version = kContractVersion;
  DType dtype = DType::fp16;
  uint32_t rank = 2;
  Layout layout = Layout::row_major;
  std::array<uint64_t, 2> dimensions{};
  std::array<uint64_t, 2> strides_bytes{};
  AllocationView allocation{};
  uint64_t offset_bytes = 0;
};

struct DeviceCapabilities {
  uint32_t version = kContractVersion;
  uint64_t device_id = 0;
  // ISA representation width; the actual mapped device aperture may be smaller.
  uint32_t address_bits = 0;
  uint32_t threads_per_warp = 0;
  uint32_t warps_per_core = 0;
  uint32_t cores = 0;
  uint32_t clusters = 0;
  uint32_t issue_width = 0;
  uint64_t local_mem_bytes = 0;
  bool tensor_extension = false;
  bool local_memory = false;
};

struct ProfileBinding {
  Profile profile = Profile::unqualified;
  bool verified_kernel_profile = false;
  bool verified_device_profile = false;
};

struct MatmulRequest {
  uint32_t version = kContractVersion;
  Operator operation = Operator::matmul;
  TensorView a{};
  TensorView b{};
  TensorView d{};
  uint32_t batch_count = 1;
  bool transpose_a = false;
  bool transpose_b = false;
  uint32_t initial_c_bits = 0;
  uint32_t flags = 0;
};

struct alignas(8) MatmulArguments {
  uint32_t abi_version = kContractVersion;
  uint32_t byte_size = kArgumentBytes;
  uint32_t input_dtype = 0;
  uint32_t flags = 0;
  uint32_t m = 0;
  uint32_t n = 0;
  uint32_t k = 0;
  uint32_t reserved = 0;
  uint64_t a_address = 0;
  uint64_t b_address = 0;
  uint64_t d_address = 0;
};

static_assert(std::is_standard_layout<MatmulArguments>::value);
static_assert(std::is_trivially_copyable<MatmulArguments>::value);
static_assert(sizeof(MatmulArguments) == kArgumentBytes);
static_assert(alignof(MatmulArguments) == 8);
static_assert(offsetof(MatmulArguments, abi_version) == 0);
static_assert(offsetof(MatmulArguments, byte_size) == 4);
static_assert(offsetof(MatmulArguments, input_dtype) == 8);
static_assert(offsetof(MatmulArguments, flags) == 12);
static_assert(offsetof(MatmulArguments, m) == 16);
static_assert(offsetof(MatmulArguments, n) == 20);
static_assert(offsetof(MatmulArguments, k) == 24);
static_assert(offsetof(MatmulArguments, reserved) == 28);
static_assert(offsetof(MatmulArguments, a_address) == 32);
static_assert(offsetof(MatmulArguments, b_address) == 40);
static_assert(offsetof(MatmulArguments, d_address) == 48);

using ArgumentBytes = std::array<uint8_t, kArgumentBytes>;

struct MatmulPlan {
  MatmulArguments arguments{};
  ArgumentBytes argument_bytes{};
  std::array<uint32_t, 3> grid{};
  std::array<uint32_t, 3> block{};
  uint32_t local_mem_bytes = 0;
  uint64_t a_bytes = 0;
  uint64_t b_bytes = 0;
  uint64_t d_bytes = 0;
  bool execution_available = false;
};

/// Validate tracked views and prepare a plan; no allocation, dispatch or fallback occurs.
Status plan_matmul(const MatmulRequest& request,
                   const DeviceCapabilities& device,
                   const ProfileBinding& binding,
                   MatmulPlan* out) noexcept;

/// Encode checked addresses as little-endian bytes; failure leaves output unchanged.
Status encode_matmul_arguments(const MatmulArguments& arguments,
                              uint32_t address_bits,
                              ArgumentBytes* out) noexcept;

const char* status_string(Status status) noexcept;

} // namespace vortex::ai

#endif
