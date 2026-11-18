// SPDX-License-Identifier: Apache-2.0

#include "contract.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>

namespace ai = vortex::ai;

static_assert(ai::kContractVersion == 1 && ai::kArgumentBytes == 56);
static_assert(static_cast<uint32_t>(ai::Operator::matmul) == 1);
static_assert(static_cast<uint32_t>(ai::Operator::gemv) == 2);
static_assert(static_cast<uint32_t>(ai::Operator::reduction) == 3);
static_assert(static_cast<uint32_t>(ai::Operator::softmax) == 4);
static_assert(static_cast<uint32_t>(ai::Operator::normalization) == 5);
static_assert(static_cast<uint32_t>(ai::Operator::activation) == 6);
static_assert(static_cast<uint32_t>(ai::Operator::layout_cast) == 7);
static_assert(static_cast<uint32_t>(ai::Operator::attention) == 8);
static_assert(static_cast<uint32_t>(ai::DType::fp16) == 1);
static_assert(static_cast<uint32_t>(ai::DType::bf16) == 2);
static_assert(static_cast<uint32_t>(ai::DType::fp32) == 3);
static_assert(static_cast<uint32_t>(ai::Layout::row_major) == 1);
static_assert(static_cast<uint32_t>(ai::Layout::column_major) == 2);
static_assert(static_cast<uint32_t>(ai::Profile::unqualified) == 0);
static_assert(static_cast<uint32_t>(ai::Profile::p02_tfr_wmma_v1) == 1);

namespace {

unsigned checks = 0;

bool check(bool passed, const char* label) {
  ++checks;
  if (!passed) {
    std::fprintf(stderr, "FAIL: %s\n", label);
  }
  return passed;
}

struct Scenario {
  ai::MatmulRequest request;
  ai::DeviceCapabilities device;
  ai::ProfileBinding binding;
};

Scenario scenario(uint64_t m = 8, uint64_t n = 4, uint64_t k = 8,
                  ai::DType dtype = ai::DType::fp16) {
  Scenario s{};
  s.device = {1, 17, 64, 4, 4, 1, 1, 1, 16384, true, true};
  s.binding = {ai::Profile::p02_tfr_wmma_v1, true, true};
  s.request.a.dtype = dtype;
  s.request.a.dimensions = {m, k};
  s.request.a.strides_bytes = {2 * k, 2};
  s.request.a.allocation = {17, 11, 0x1000, 2 * m * k, true, false};
  s.request.b.dtype = dtype;
  s.request.b.layout = ai::Layout::column_major;
  s.request.b.dimensions = {k, n};
  s.request.b.strides_bytes = {2, 2 * k};
  s.request.b.allocation = {17, 12, 0x2000, 2 * k * n, true, false};
  s.request.d.dtype = ai::DType::fp32;
  s.request.d.dimensions = {m, n};
  s.request.d.strides_bytes = {4 * n, 4};
  s.request.d.allocation = {17, 13, 0x3000, 4 * m * n, false, true};
  return s;
}

bool rejects(const Scenario& s, const char* label,
             ai::Status expected = ai::Status::success) {
  ai::MatmulPlan out{};
  out.a_bytes = 0x1122334455667788ull;
  out.grid = {19, 23, 29};
  out.argument_bytes.fill(0x5a);
  out.execution_available = true;
  std::array<unsigned char, sizeof(out)> before{};
  std::memcpy(before.data(), &out, sizeof(out));
  const auto status = ai::plan_matmul(s.request, s.device, s.binding, &out);
  return check(status != ai::Status::success, label)
      && check(expected == ai::Status::success || status == expected, "rejection status")
      && check(std::memcmp(before.data(), &out, sizeof(out)) == 0, "failed plan is atomic");
}

bool positive_shapes() {
  constexpr uint64_t shapes[][3] = {{8, 4, 8}, {8, 4, 16}, {16, 8, 16}};
  for (const auto dtype : {ai::DType::fp16, ai::DType::bf16}) {
    for (const auto& shape : shapes) {
      auto s = scenario(shape[0], shape[1], shape[2], dtype);
      ai::MatmulPlan out{};
      if (!check(ai::plan_matmul(s.request, s.device, s.binding, &out) == ai::Status::success,
                 "qualified shape plans")) {
        return false;
      }
      if (!check(out.arguments.m == shape[0] && out.arguments.n == shape[1]
                 && out.arguments.k == shape[2], "dimensions are preserved")
          || !check(out.arguments.input_dtype == static_cast<uint32_t>(dtype), "input format is preserved")
          || !check(out.arguments.a_address == 0x1000 && out.arguments.b_address == 0x2000
                    && out.arguments.d_address == 0x3000, "device addresses are preserved")
          || !check(out.a_bytes == shape[0] * shape[2] * 2
                    && out.b_bytes == shape[2] * shape[1] * 2
                    && out.d_bytes == shape[0] * shape[1] * 4, "touched byte spans")
          || !check(out.grid == std::array<uint32_t, 3>{uint32_t(shape[1] / 4), uint32_t(shape[0] / 8), 1}
                    && out.block == std::array<uint32_t, 3>{4, 1, 1}, "native tile launch geometry")
          || !check(out.local_mem_bytes == 0 && !out.execution_available, "planning does not claim execution")) {
        return false;
      }
    }
  }
  return true;
}

bool invalid_fields() {
  auto s = scenario();
  s.request.version = 0;
  if (!rejects(s, "request version", ai::Status::invalid_version)) {
    return false;
  }
  for (unsigned index = 0; index < 3; ++index) {
    s = scenario();
    auto* tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
    tensor->version = 2;
    if (!rejects(s, "tensor version", ai::Status::invalid_version)) {
      return false;
    }
    for (const uint32_t rank : {0u, 1u, 3u, UINT32_MAX}) {
      s = scenario();
      tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
      tensor->rank = rank;
      if (!rejects(s, "rank is exactly two", ai::Status::invalid_rank)) {
        return false;
      }
    }
    s = scenario();
    tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
    tensor->dtype = static_cast<ai::DType>(UINT32_MAX);
    if (!rejects(s, "unknown dtype", ai::Status::unsupported_dtype)) {
      return false;
    }
    s = scenario();
    tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
    tensor->layout = static_cast<ai::Layout>(0);
    if (!rejects(s, "unknown layout", ai::Status::unsupported_layout)) {
      return false;
    }
  }
  for (uint32_t operation = 2; operation <= 8; ++operation) {
    s = scenario();
    s.request.operation = static_cast<ai::Operator>(operation);
    if (!rejects(s, "unimplemented named operator", ai::Status::unsupported_operator)) {
      return false;
    }
  }
  for (const uint32_t operation : {0u, 9u, UINT32_MAX}) {
    s = scenario();
    s.request.operation = static_cast<ai::Operator>(operation);
    if (!rejects(s, "unknown operator", ai::Status::unsupported_operator)) {
      return false;
    }
  }
  s = scenario();
  s.request.b.dtype = ai::DType::bf16;
  if (!rejects(s, "mixed input formats", ai::Status::unsupported_dtype)) {
    return false;
  }
  s = scenario();
  s.request.d.dtype = ai::DType::fp16;
  if (!rejects(s, "non-FP32 output", ai::Status::unsupported_dtype)) {
    return false;
  }
  s = scenario();
  return check(ai::plan_matmul(s.request, s.device, s.binding, nullptr)
               == ai::Status::invalid_argument, "null plan destination");
}

bool shape_and_layout() {
  for (const uint64_t m : {8u, 16u}) {
    for (const uint64_t n : {4u, 8u}) {
      for (const uint64_t k : {8u, 16u}) {
        if ((m == 8 && n == 4 && (k == 8 || k == 16)) || (m == 16 && n == 8 && k == 16)) {
          continue;
        }
        if (!rejects(scenario(m, n, k), "unsupported shape cross-product", ai::Status::unsupported_shape)) {
          return false;
        }
      }
    }
  }
  auto s = scenario();
  for (unsigned index = 0; index < 3; ++index) {
    for (unsigned axis = 0; axis < 2; ++axis) {
      s = scenario();
      auto* tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
      tensor->dimensions[axis] = 0;
      if (!rejects(s, "empty tensor", ai::Status::empty_tensor)) {
        return false;
      }
      for (const uint64_t stride : {uint64_t(0), uint64_t(1), UINT64_MAX}) {
        s = scenario();
        tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
        tensor->strides_bytes[axis] = stride;
        if (!rejects(s, "noncompact or invalid byte stride")) {
          return false;
        }
      }
    }
    s = scenario();
    auto* tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
    tensor->layout = index == 1 ? ai::Layout::row_major : ai::Layout::column_major;
    if (!rejects(s, "operand layout mismatch", ai::Status::unsupported_layout)) {
      return false;
    }
  }
  s = scenario();
  s.request.b.dimensions[0] = 16;
  s.request.b.strides_bytes[1] = 32;
  s.request.b.allocation.size_bytes = 128;
  if (!rejects(s, "inner dimensions differ", ai::Status::unsupported_shape)) {
    return false;
  }
  s = scenario();
  s.request.d.dimensions[1] = 8;
  s.request.d.strides_bytes[0] = 32;
  s.request.d.allocation.size_bytes = 256;
  if (!rejects(s, "output dimensions differ", ai::Status::unsupported_shape)) {
    return false;
  }
  for (const uint32_t batch : {0u, 2u, UINT32_MAX}) {
    s = scenario();
    s.request.batch_count = batch;
    if (!rejects(s, "batch count must be one", ai::Status::unsupported_shape)) {
      return false;
    }
  }
  for (unsigned option = 0; option < 4; ++option) {
    s = scenario();
    if (option == 0) {
      s.request.transpose_a = true;
    } else if (option == 1) {
      s.request.transpose_b = true;
    } else if (option == 2) {
      s.request.initial_c_bits = 0x80000000;
    } else {
      s.request.flags = 1;
    }
    const auto expected = option < 2 ? ai::Status::unsupported_layout : ai::Status::invalid_argument;
    if (!rejects(s, "unsupported transpose, initial C, or flag", expected)) {
      return false;
    }
  }
  return true;
}

bool allocation_ranges() {
  auto s = scenario();
  for (auto* tensor : {&s.request.a, &s.request.b, &s.request.d}) {
    tensor->offset_bytes = 32;
    tensor->allocation.size_bytes += 32;
  }
  ai::MatmulPlan out{};
  const ai::ArgumentBytes expected_plan_bytes = {
    0x01, 0, 0, 0, 0x38, 0, 0, 0, 0x01, 0, 0, 0, 0, 0, 0, 0,
    0x08, 0, 0, 0, 0x04, 0, 0, 0, 0x08, 0, 0, 0, 0, 0, 0, 0,
    0x20, 0x10, 0, 0, 0, 0, 0, 0,
    0x20, 0x20, 0, 0, 0, 0, 0, 0,
    0x20, 0x30, 0, 0, 0, 0, 0, 0
  };
  if (!check(ai::plan_matmul(s.request, s.device, s.binding, &out) == ai::Status::success,
             "exactly fitting suballocations")
      || !check(out.arguments.a_address == 0x1020 && out.arguments.b_address == 0x2020
                && out.arguments.d_address == 0x3020, "offsets are added to device addresses")
      || !check(out.argument_bytes == expected_plan_bytes,
                "planner returns independently specified bytes with subview offsets")) {
    return false;
  }
  for (unsigned index = 0; index < 3; ++index) {
    for (unsigned failure = 0; failure < 5; ++failure) {
      s = scenario();
      auto* tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
      if (failure == 0) {
        --tensor->allocation.size_bytes;
      } else if (failure == 1) {
        tensor->offset_bytes = tensor->allocation.size_bytes;
      } else if (failure == 2) {
        tensor->offset_bytes = UINT64_MAX - 3;
      } else if (failure == 3) {
        tensor->allocation.address = UINT64_MAX - 3;
      } else {
        tensor->allocation.size_bytes = UINT64_MAX;
      }
      if (!rejects(s, "allocation range does not fit")) {
        return false;
      }
    }
    for (unsigned field = 0; field < 2; ++field) {
      s = scenario();
      auto* tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
      if (field == 0) {
        ++tensor->allocation.address;
      } else {
        tensor->offset_bytes = 1;
        ++tensor->allocation.size_bytes;
      }
      if (!rejects(s, "unaligned allocation or subview", ai::Status::misaligned_address)) {
        return false;
      }
    }
  }
  s = scenario();
  s.request.a.allocation.address = UINT64_MAX - 127;
  if (!check(ai::plan_matmul(s.request, s.device, s.binding, &out) == ai::Status::success,
             "last representable address is valid")) {
    return false;
  }
  s.request.a.allocation.address += 4;
  if (!rejects(s, "last addressed byte exceeds RV64", ai::Status::address_out_of_range)) {
    return false;
  }
  s = scenario();
  s.request.a.dimensions = {UINT64_MAX, UINT64_MAX};
  s.request.b.dimensions[0] = UINT64_MAX;
  s.request.d.dimensions[0] = UINT64_MAX;
  if (!rejects(s, "overflowing element count", ai::Status::arithmetic_overflow)) {
    return false;
  }
  s = scenario();
  s.request.a.dimensions = {UINT64_MAX / 2 + 1, 1};
  if (!rejects(s, "overflowing byte count", ai::Status::arithmetic_overflow)) {
    return false;
  }
  s = scenario();
  s.request.a.allocation.size_bytes = UINT64_MAX;
  s.request.a.offset_bytes = UINT64_MAX - 255;
  return rejects(s, "overflowing allocation base plus offset", ai::Status::arithmetic_overflow);
}

bool ownership_and_aliasing() {
  auto s = scenario();
  for (unsigned index = 0; index < 3; ++index) {
    for (unsigned failure = 0; failure < 4; ++failure) {
      s = scenario();
      auto* tensor = index == 0 ? &s.request.a : index == 1 ? &s.request.b : &s.request.d;
      if (failure == 0) {
        tensor->allocation.device_id = 18;
      } else if (failure == 1) {
        tensor->allocation.device_id = 0;
      } else if (failure == 2) {
        tensor->allocation.allocation_id = 0;
      } else if (index == 2) {
        tensor->allocation.writable = false;
      } else {
        tensor->allocation.readable = false;
      }
      const auto expected = failure == 0 ? ai::Status::device_mismatch
          : failure == 3 ? ai::Status::invalid_access : ai::Status::invalid_argument;
      if (!rejects(s, "ownership or access is invalid", expected)) {
        return false;
      }
    }
  }
  for (unsigned pair = 0; pair < 3; ++pair) {
    s = scenario();
    if (pair == 0) {
      s.request.b.allocation.address = s.request.a.allocation.address + 4;
    } else if (pair == 1) {
      s.request.d.allocation.address = s.request.a.allocation.address + 124;
    } else {
      s.request.d.allocation.address = s.request.b.allocation.address + 60;
    }
    if (!rejects(s, "partial alias across distinct allocation IDs", ai::Status::aliasing)) {
      return false;
    }
  }
  s = scenario();
  const ai::AllocationView common{17, 11, 0x1000, 320, true, true};
  s.request.a.allocation = s.request.b.allocation = s.request.d.allocation = common;
  s.request.b.offset_bytes = 128;
  s.request.d.offset_bytes = 192;
  ai::MatmulPlan out{};
  if (!check(ai::plan_matmul(s.request, s.device, s.binding, &out) == ai::Status::success,
             "adjacent disjoint views of one allocation")) {
    return false;
  }
  ++s.request.b.allocation.size_bytes;
  if (!rejects(s, "one allocation ID cannot change capacity", ai::Status::invalid_argument)) {
    return false;
  }
  s.request.b.allocation = common;
  s.request.b.allocation.writable = false;
  return rejects(s, "one allocation ID cannot change permissions", ai::Status::invalid_argument);
}

bool capabilities() {
  auto s = scenario();
  s.device.version = 2;
  if (!rejects(s, "capability version", ai::Status::invalid_version)) {
    return false;
  }
  for (unsigned field = 0; field < 12; ++field) {
    s = scenario();
    switch (field) {
    case 0: s.device.device_id = 0; break;
    case 1: s.device.address_bits = 32; break;
    case 2: s.device.address_bits = 63; break;
    case 3: s.device.threads_per_warp = 8; break;
    case 4: s.device.warps_per_core = 8; break;
    case 5: s.device.cores = 2; break;
    case 6: s.device.clusters = 2; break;
    case 7: s.device.issue_width = 4; break;
    case 8: s.device.local_mem_bytes = 16380; break;
    case 9: s.device.local_mem_bytes = 32768; break;
    case 10: s.device.tensor_extension = false; break;
    case 11: s.device.local_memory = false; break;
    }
    const auto expected = field == 0 ? ai::Status::invalid_argument : ai::Status::unsupported_profile;
    if (!rejects(s, "unqualified device capability", expected)) {
      return false;
    }
  }
  for (unsigned field = 0; field < 4; ++field) {
    s = scenario();
    if (field == 0) {
      s.binding.profile = ai::Profile::unqualified;
    } else if (field == 1) {
      s.binding.profile = static_cast<ai::Profile>(UINT32_MAX);
    } else if (field == 2) {
      s.binding.verified_kernel_profile = false;
    } else {
      s.binding.verified_device_profile = false;
    }
    if (!rejects(s, "unverified profile binding", ai::Status::unsupported_profile)) {
      return false;
    }
  }
  return true;
}

ai::MatmulArguments wire_arguments() {
  ai::MatmulArguments a{};
  a.input_dtype = 2;
  a.m = 16;
  a.n = 8;
  a.k = 16;
  a.a_address = 0x0102030405060708ull;
  a.b_address = 0x1112131415161718ull;
  a.d_address = 0x2122232425262728ull;
  return a;
}

bool wire_bytes() {
  const ai::ArgumentBytes expected = {
    0x01, 0, 0, 0, 0x38, 0, 0, 0, 0x02, 0, 0, 0, 0, 0, 0, 0,
    0x10, 0, 0, 0, 0x08, 0, 0, 0, 0x10, 0, 0, 0, 0, 0, 0, 0,
    0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01,
    0x18, 0x17, 0x16, 0x15, 0x14, 0x13, 0x12, 0x11,
    0x28, 0x27, 0x26, 0x25, 0x24, 0x23, 0x22, 0x21
  };
  ai::ArgumentBytes out{};
  auto a = wire_arguments();
  if (!check(ai::encode_matmul_arguments(a, 64, &out) == ai::Status::success, "RV64 wire encode")
      || !check(out == expected, "independent literal RV64 little-endian bytes")) {
    return false;
  }
  const ai::ArgumentBytes expected32 = {
    0x01, 0, 0, 0, 0x38, 0, 0, 0, 0x02, 0, 0, 0, 0, 0, 0, 0,
    0x10, 0, 0, 0, 0x08, 0, 0, 0, 0x10, 0, 0, 0, 0, 0, 0, 0,
    0x04, 0x03, 0x02, 0x01, 0, 0, 0, 0,
    0x14, 0x13, 0x12, 0x11, 0, 0, 0, 0,
    0x24, 0x23, 0x22, 0x21, 0, 0, 0, 0
  };
  a.a_address = 0x01020304;
  a.b_address = 0x11121314;
  a.d_address = 0x21222324;
  if (!check(ai::encode_matmul_arguments(a, 32, &out) == ai::Status::success, "RV32 representation encode")
      || !check(out == expected32, "independent literal RV32 little-endian bytes")) {
    return false;
  }
  a.input_dtype = 1;
  a.m = 8;
  a.n = 4;
  a.k = 8;
  a.a_address = 0xffffff80ull;
  if (!check(ai::encode_matmul_arguments(a, 32, &out) == ai::Status::success,
             "RV32 last operand byte is representable")) {
    return false;
  }
  a.a_address += 4;
  const auto before = out;
  return check(ai::encode_matmul_arguments(a, 32, &out) == ai::Status::address_out_of_range,
               "RV32 whole operand range must fit")
      && check(out == before, "failed wire encode is atomic");
}

bool invalid_wire() {
  for (unsigned field = 0; field < 13; ++field) {
    auto a = wire_arguments();
    uint32_t width = 64;
    switch (field) {
    case 0: a.abi_version = 0; break;
    case 1: a.byte_size = 55; break;
    case 2: a.input_dtype = 0; break;
    case 3: a.input_dtype = 3; break;
    case 4: a.flags = 1; break;
    case 5: a.reserved = 1; break;
    case 6: a.m = 0; break;
    case 7: a.k = 8; break;
    case 8: ++a.a_address; break;
    case 9: ++a.b_address; break;
    case 10: ++a.d_address; break;
    case 11: width = 32; break;
    case 12: width = 63; break;
    }
    ai::ArgumentBytes out{};
    out.fill(0xa5);
    const auto before = out;
    if (!check(ai::encode_matmul_arguments(a, width, &out) != ai::Status::success, "invalid wire request")
        || !check(out == before, "wire rejection leaves bytes unchanged")) {
      return false;
    }
  }
  const auto a = wire_arguments();
  if (!check(ai::encode_matmul_arguments(a, 64, nullptr) == ai::Status::invalid_argument,
             "null byte destination")) {
    return false;
  }
  for (uint32_t value = 0; value <= static_cast<uint32_t>(ai::Status::aliasing); ++value) {
    const auto* name = ai::status_string(static_cast<ai::Status>(value));
    if (!check(name != nullptr && std::strlen(name) > 0, "all statuses have diagnostics")) {
      return false;
    }
    for (uint32_t prior = 0; prior < value; ++prior) {
      if (!check(std::strcmp(name, ai::status_string(static_cast<ai::Status>(prior))) != 0,
                 "status diagnostics are distinct")) {
        return false;
      }
    }
  }
  return check(std::strcmp(ai::status_string(static_cast<ai::Status>(UINT32_MAX)), "unknown_status") == 0,
               "unknown status has a diagnostic");
}

} // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  struct Group {
    const char* name;
    bool (*run)();
  };
  const Group groups[] = {
    {"positive_shapes", positive_shapes}, {"invalid_fields", invalid_fields},
    {"shape_and_layout", shape_and_layout}, {"allocation_ranges", allocation_ranges},
    {"ownership_and_aliasing", ownership_and_aliasing}, {"capabilities", capabilities},
    {"wire_bytes", wire_bytes}, {"invalid_wire", invalid_wire}
  };
  for (const auto& group : groups) {
    if (std::strcmp(argv[1], group.name) == 0) {
      if (!group.run()) {
        return 1;
      }
      std::printf("PASS %s checks=%u\n", group.name, checks);
      return 0;
    }
  }
  return 2;
}
