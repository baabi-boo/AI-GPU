// SPDX-License-Identifier: Apache-2.0

#include "contract.h"
#include <limits>

namespace vortex::ai {
namespace {

constexpr uint64_t kMaximum = std::numeric_limits<uint64_t>::max();

bool multiply(uint64_t a, uint64_t b, uint64_t* out) noexcept {
  if (b != 0 && a > kMaximum / b) {
    return false;
  }
  *out = a * b;
  return true;
}

bool add(uint64_t a, uint64_t b, uint64_t* out) noexcept {
  if (a > kMaximum - b) {
    return false;
  }
  *out = a + b;
  return true;
}

bool supported_shape(uint64_t m, uint64_t n, uint64_t k) noexcept {
  return (m == 8 && n == 4 && (k == 8 || k == 16))
      || (m == 16 && n == 8 && k == 16);
}

bool input_dtype(uint32_t dtype) noexcept {
  return dtype == static_cast<uint32_t>(DType::fp16)
      || dtype == static_cast<uint32_t>(DType::bf16);
}

bool range_fits(uint64_t address, uint64_t bytes, uint32_t bits) noexcept {
  const uint64_t maximum = bits == 32 ? UINT32_MAX : kMaximum;
  return bytes != 0 && address <= maximum && bytes - 1 <= maximum - address;
}

bool overlaps(uint64_t first, uint64_t first_bytes,
              uint64_t second, uint64_t second_bytes) noexcept {
  return first <= second + (second_bytes - 1)
      && second <= first + (first_bytes - 1);
}

Status tensor_size(const TensorView& tensor, DType dtype, Layout layout,
                   uint64_t* bytes) noexcept {
  if (tensor.version != kContractVersion) {
    return Status::invalid_version;
  }
  if (tensor.rank != 2) {
    return Status::invalid_rank;
  }
  if (tensor.dtype != dtype) {
    return Status::unsupported_dtype;
  }
  if (tensor.layout != layout) {
    return Status::unsupported_layout;
  }
  if (tensor.dimensions[0] == 0 || tensor.dimensions[1] == 0) {
    return Status::empty_tensor;
  }
  const uint64_t element_bytes = dtype == DType::fp32 ? 4 : 2;
  uint64_t elements = 0;
  uint64_t major_stride = 0;
  const uint64_t major_elements = layout == Layout::row_major
      ? tensor.dimensions[1] : tensor.dimensions[0];
  if (!multiply(tensor.dimensions[0], tensor.dimensions[1], &elements)
      || !multiply(elements, element_bytes, bytes)
      || !multiply(major_elements, element_bytes, &major_stride)) {
    return Status::arithmetic_overflow;
  }
  const std::array<uint64_t, 2> expected = layout == Layout::row_major
      ? std::array<uint64_t, 2>{major_stride, element_bytes}
      : std::array<uint64_t, 2>{element_bytes, major_stride};
  if (tensor.strides_bytes != expected) {
    return Status::unsupported_layout;
  }
  return Status::success;
}

Status tensor_address(const TensorView& tensor, const DeviceCapabilities& device,
                      uint64_t bytes, bool output, uint64_t* address) noexcept {
  const auto& allocation = tensor.allocation;
  if (allocation.allocation_id == 0 || allocation.device_id == 0) {
    return Status::invalid_argument;
  }
  if (allocation.device_id != device.device_id) {
    return Status::device_mismatch;
  }
  if (output ? !allocation.writable : !allocation.readable) {
    return Status::invalid_access;
  }
  if (tensor.offset_bytes > allocation.size_bytes
      || bytes > allocation.size_bytes - tensor.offset_bytes) {
    return Status::insufficient_buffer;
  }
  if (!add(allocation.address, tensor.offset_bytes, address)) {
    return Status::arithmetic_overflow;
  }
  if (allocation.address % 4 != 0 || tensor.offset_bytes % 4 != 0) {
    return Status::misaligned_address;
  }
  if (!range_fits(allocation.address, allocation.size_bytes, device.address_bits)
      || !range_fits(*address, bytes, device.address_bits)) {
    return Status::address_out_of_range;
  }
  return Status::success;
}

bool same_allocation(const AllocationView& a, const AllocationView& b) noexcept {
  return a.allocation_id != b.allocation_id
      || (a.device_id == b.device_id && a.address == b.address
          && a.size_bytes == b.size_bytes && a.readable == b.readable
          && a.writable == b.writable);
}

void put32(ArgumentBytes* bytes, size_t offset, uint32_t value) noexcept {
  for (size_t i = 0; i < 4; ++i) {
    (*bytes)[offset + i] = static_cast<uint8_t>(value >> (8 * i));
  }
}

void put64(ArgumentBytes* bytes, size_t offset, uint64_t value) noexcept {
  for (size_t i = 0; i < 8; ++i) {
    (*bytes)[offset + i] = static_cast<uint8_t>(value >> (8 * i));
  }
}

} // namespace

Status encode_matmul_arguments(const MatmulArguments& arguments,
                              uint32_t address_bits,
                              ArgumentBytes* out) noexcept {
  if (out == nullptr || (address_bits != 32 && address_bits != 64)) {
    return Status::invalid_argument;
  }
  if (arguments.abi_version != kContractVersion) {
    return Status::invalid_version;
  }
  if (arguments.byte_size != kArgumentBytes || arguments.flags != 0
      || arguments.reserved != 0) {
    return Status::invalid_argument;
  }
  if (!input_dtype(arguments.input_dtype)) {
    return Status::unsupported_dtype;
  }
  if (!supported_shape(arguments.m, arguments.n, arguments.k)) {
    return Status::unsupported_shape;
  }
  const uint64_t a_bytes = uint64_t{arguments.m} * arguments.k * 2;
  const uint64_t b_bytes = uint64_t{arguments.k} * arguments.n * 2;
  const uint64_t d_bytes = uint64_t{arguments.m} * arguments.n * 4;
  if (arguments.a_address % 4 != 0 || arguments.b_address % 4 != 0
      || arguments.d_address % 4 != 0) {
    return Status::misaligned_address;
  }
  if (!range_fits(arguments.a_address, a_bytes, address_bits)
      || !range_fits(arguments.b_address, b_bytes, address_bits)
      || !range_fits(arguments.d_address, d_bytes, address_bits)) {
    return Status::address_out_of_range;
  }
  if (overlaps(arguments.a_address, a_bytes, arguments.b_address, b_bytes)
      || overlaps(arguments.a_address, a_bytes, arguments.d_address, d_bytes)
      || overlaps(arguments.b_address, b_bytes, arguments.d_address, d_bytes)) {
    return Status::aliasing;
  }
  ArgumentBytes bytes{};
  put32(&bytes, 0, arguments.abi_version);
  put32(&bytes, 4, arguments.byte_size);
  put32(&bytes, 8, arguments.input_dtype);
  put32(&bytes, 12, arguments.flags);
  put32(&bytes, 16, arguments.m);
  put32(&bytes, 20, arguments.n);
  put32(&bytes, 24, arguments.k);
  put32(&bytes, 28, arguments.reserved);
  put64(&bytes, 32, arguments.a_address);
  put64(&bytes, 40, arguments.b_address);
  put64(&bytes, 48, arguments.d_address);
  *out = bytes;
  return Status::success;
}

Status plan_matmul(const MatmulRequest& request,
                   const DeviceCapabilities& device,
                   const ProfileBinding& binding,
                   MatmulPlan* out) noexcept {
  if (out == nullptr || device.device_id == 0) {
    return Status::invalid_argument;
  }
  if (request.version != kContractVersion || device.version != kContractVersion) {
    return Status::invalid_version;
  }
  if (request.operation != Operator::matmul) {
    return Status::unsupported_operator;
  }
  if (request.flags != 0 || request.initial_c_bits != 0) {
    return Status::invalid_argument;
  }
  if (request.transpose_a || request.transpose_b) {
    return Status::unsupported_layout;
  }
  if (request.batch_count != 1) {
    return Status::unsupported_shape;
  }
  if (binding.profile != Profile::p02_tfr_wmma_v1
      || !binding.verified_kernel_profile || !binding.verified_device_profile
      || device.address_bits != 64 || device.threads_per_warp != 4
      || device.warps_per_core != 4 || device.cores != 1 || device.clusters != 1
      || device.issue_width != 1 || device.local_mem_bytes != 16384
      || !device.tensor_extension || !device.local_memory) {
    return Status::unsupported_profile;
  }
  if (!input_dtype(static_cast<uint32_t>(request.a.dtype))) {
    return Status::unsupported_dtype;
  }
  MatmulPlan plan{};
  Status status = tensor_size(request.a, request.a.dtype, Layout::row_major, &plan.a_bytes);
  if (status != Status::success) {
    return status;
  }
  status = tensor_size(request.b, request.a.dtype, Layout::column_major, &plan.b_bytes);
  if (status != Status::success) {
    return status;
  }
  status = tensor_size(request.d, DType::fp32, Layout::row_major, &plan.d_bytes);
  if (status != Status::success) {
    return status;
  }
  const uint64_t m = request.a.dimensions[0];
  const uint64_t n = request.b.dimensions[1];
  const uint64_t k = request.a.dimensions[1];
  if (request.b.dimensions[0] != k || request.d.dimensions[0] != m
      || request.d.dimensions[1] != n || !supported_shape(m, n, k)) {
    return Status::unsupported_shape;
  }
  if (!same_allocation(request.a.allocation, request.b.allocation)
      || !same_allocation(request.a.allocation, request.d.allocation)
      || !same_allocation(request.b.allocation, request.d.allocation)) {
    return Status::invalid_argument;
  }
  auto& arguments = plan.arguments;
  status = tensor_address(request.a, device, plan.a_bytes, false, &arguments.a_address);
  if (status != Status::success) {
    return status;
  }
  status = tensor_address(request.b, device, plan.b_bytes, false, &arguments.b_address);
  if (status != Status::success) {
    return status;
  }
  status = tensor_address(request.d, device, plan.d_bytes, true, &arguments.d_address);
  if (status != Status::success) {
    return status;
  }
  arguments.input_dtype = static_cast<uint32_t>(request.a.dtype);
  arguments.m = static_cast<uint32_t>(m);
  arguments.n = static_cast<uint32_t>(n);
  arguments.k = static_cast<uint32_t>(k);
  status = encode_matmul_arguments(arguments, device.address_bits, &plan.argument_bytes);
  if (status != Status::success) {
    return status;
  }
  plan.grid = {arguments.n / 4, arguments.m / 8, 1};
  plan.block = {4, 1, 1};
  *out = plan;
  return Status::success;
}

const char* status_string(Status status) noexcept {
  switch (status) {
  case Status::success: return "success";
  case Status::invalid_argument: return "invalid_argument";
  case Status::invalid_version: return "invalid_version";
  case Status::unsupported_operator: return "unsupported_operator";
  case Status::unsupported_dtype: return "unsupported_dtype";
  case Status::unsupported_shape: return "unsupported_shape";
  case Status::unsupported_layout: return "unsupported_layout";
  case Status::unsupported_profile: return "unsupported_profile";
  case Status::invalid_rank: return "invalid_rank";
  case Status::empty_tensor: return "empty_tensor";
  case Status::device_mismatch: return "device_mismatch";
  case Status::invalid_access: return "invalid_access";
  case Status::misaligned_address: return "misaligned_address";
  case Status::insufficient_buffer: return "insufficient_buffer";
  case Status::arithmetic_overflow: return "arithmetic_overflow";
  case Status::address_out_of_range: return "address_out_of_range";
  case Status::aliasing: return "aliasing";
  }
  return "unknown_status";
}

} // namespace vortex::ai
