// SPDX-License-Identifier: Apache-2.0

#include "runtime.h"
#include <ai_matmul_profile.h>
#include "../sgemm_tcu/p02_fixtures.h"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>

namespace ai = vortex::ai;

namespace {

std::vector<uint8_t> pack(const uint32_t* words, size_t count) {
  std::vector<uint8_t> bytes(count * 4);
  for (size_t i = 0; i < count; ++i) {
    for (size_t byte = 0; byte < 4; ++byte) {
      bytes[i * 4 + byte] = static_cast<uint8_t>(words[i] >> (8 * byte));
    }
  }
  return bytes;
}

bool check(const ai::ExecutionResult& result, const char* action) {
  if (result.ok()) return true;
  std::fprintf(stderr, "FAILED %s: validation=%s primary=%s cleanup=%s complete=%d\n",
      action, ai::status_string(result.validation), vx_result_string(result.primary),
      vx_result_string(result.cleanup), result.complete);
  return false;
}

int run(int argc, char** argv) {
  std::string case_id, module_path, binding_id;
  uint32_t iterations = 2;
  for (int i = 1; i < argc; i += 2) {
    if (i + 1 == argc) return 2;
    const std::string option = argv[i];
    if (option == "--case") case_id = argv[i + 1];
    else if (option == "--module") module_path = argv[i + 1];
    else if (option == "--qualification-id") binding_id = argv[i + 1];
    else if (option == "--iterations" && (std::strcmp(argv[i + 1], "1") == 0
                                        || std::strcmp(argv[i + 1], "2") == 0)) {
      iterations = static_cast<uint32_t>(argv[i + 1][0] - '0');
    } else return 2;
  }
  const p02::Fixture* fixture = nullptr;
  for (const auto& item : p02::kFixtures) {
    if (case_id == item.id) fixture = &item;
  }
  const char* format = ai::kMatmulInputDType == 1 ? "fp16" : "bf16";
  if (fixture == nullptr || std::strcmp(fixture->format, format) != 0 || module_path.empty()) return 2;
  std::ifstream stream(module_path, std::ios::binary | std::ios::ate);
  if (!stream) return 2;
  const auto size = stream.tellg();
  if (size <= 0 || size > 16 * 1024 * 1024) return 2;
  std::vector<uint8_t> image(static_cast<size_t>(size));
  stream.seekg(0);
  if (!stream.read(reinterpret_cast<char*>(image.data()), size)) return 2;
  ai::ExecutionBinding binding;
  binding.profile = {ai::Profile::p02_tfr_wmma_v1, true, true};
  binding.input_dtype = static_cast<ai::DType>(ai::kMatmulInputDType);
  binding.module_bytes = image.data();
  binding.module_size = image.size();
  binding.qualification_id = binding_id;
  std::unique_ptr<ai::ManagedMatmul> runtime;
  if (!check(ai::ManagedMatmul::create(binding, &runtime), "create")) return 1;
  auto a = pack(fixture->a_words, fixture->a_count);
  auto b = pack(fixture->b_words, fixture->b_count);
  std::unique_ptr<ai::MatmulOperation> rejected;
  auto invalid = runtime->submit(7, 4, 8, a.data(), a.size(), b.data(), b.size(), 0, &rejected);
  if (invalid.validation != ai::Status::unsupported_shape || rejected) return 1;
  invalid = runtime->submit(fixture->m, fixture->n, fixture->k, a.data(), a.size() - 1,
                            b.data(), b.size(), 0, &rejected);
  if (invalid.ok() || rejected) return 1;
  std::printf("P03_REJECTIONS checked=2\n");
  for (uint32_t iteration = 0; iteration < iterations; ++iteration) {
    uint64_t free_before = 0, used_before = 0, free_after = 0, used_after = 0;
    if (runtime->memory_info(&free_before, &used_before) != VX_SUCCESS) return 1;
    std::unique_ptr<ai::MatmulOperation> operation;
    const uint32_t poison = iteration == 0 ? 0x7fc0deadu : 0xdeadbeefu;
    if (!check(runtime->submit(fixture->m, fixture->n, fixture->k,
          a.data(), a.size(), b.data(), b.size(), poison, &operation), "submit")) return 1;
    auto result = operation->wait(120000000000ull);
    if (!check(result, "wait") || !result.complete) return 1;
    const auto trace = operation->trace();
    const auto actual = operation->output_words();
    result = operation->close(120000000000ull);
    if (!check(result, "close") || !result.complete) return 1;
    operation.reset();
    if (runtime->memory_info(&free_after, &used_after) != VX_SUCCESS) return 1;
    size_t mismatches = 0;
    if (actual.size() != fixture->output_count) return 1;
    for (size_t i = 0; i < actual.size(); ++i) {
      if (actual[i] != fixture->expected[i]) ++mismatches;
    }
    std::printf("P03_RESULT {\"case_id\":\"%s\",\"format\":\"%s\",\"m\":%u,\"n\":%u,"
        "\"k\":%u,\"iteration\":%u,\"checked\":%zu,\"mismatches\":%zu,\"actual_bits\":[",
        fixture->id, format, fixture->m, fixture->n, fixture->k, iteration, actual.size(), mismatches);
    for (size_t i = 0; i < actual.size(); ++i) {
      std::printf("%s\"%08x\"", i == 0 ? "" : ",", actual[i]);
    }
    std::printf("],\"qualification_id\":\"%s\",\"dispatch\":{\"a_address\":%llu,\"b_address\":%llu,"
        "\"d_address\":%llu,\"a_bytes\":%llu,\"b_bytes\":%llu,\"d_bytes\":%llu,"
        "\"writes\":%u,\"reads\":%u,\"launches\":%u,\"waits\":%llu,\"poison\":%u,\"argument_bytes\":\"",
        trace.qualification_id.c_str(), static_cast<unsigned long long>(trace.a_address),
        static_cast<unsigned long long>(trace.b_address), static_cast<unsigned long long>(trace.d_address),
        static_cast<unsigned long long>(trace.a_bytes), static_cast<unsigned long long>(trace.b_bytes),
        static_cast<unsigned long long>(trace.d_bytes), trace.writes_enqueued, trace.reads_enqueued,
        trace.launches_enqueued, static_cast<unsigned long long>(trace.wait_calls), trace.poison);
    for (const auto byte : trace.argument_bytes) std::printf("%02x", byte);
    std::printf("\"},\"resources\":{\"used_before\":%llu,\"used_after\":%llu,\"free_before\":%llu,"
        "\"free_after\":%llu,\"primary\":%u,\"cleanup\":%u}}\n",
        static_cast<unsigned long long>(used_before), static_cast<unsigned long long>(used_after),
        static_cast<unsigned long long>(free_before), static_cast<unsigned long long>(free_after),
        static_cast<unsigned>(result.primary), static_cast<unsigned>(result.cleanup));
    if (mismatches || used_before != used_after || free_before != free_after) return 1;
  }
  if (!check(runtime->close(), "runtime close")) return 1;
  runtime.reset();
  std::puts("PASSED!");
  return 0;
}

} // namespace

int main(int argc, char** argv) {
  try {
    const int result = run(argc, argv);
    if (result) std::fprintf(stderr, "FAILED managed matmul, exit=%d\n", result);
    return result;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED managed matmul: %s\n", error.what());
    return 1;
  }
}
