// SPDX-License-Identifier: Apache-2.0

#ifdef P02_WGMMA_SPARSE
#include "../sgemm_tcu_wg_sp/common.h"
#else
#include "../sgemm_tcu_wg/common.h"
#endif
#include "fixtures.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <tensor_cfg.h>
#include <type_traits>
#include <vector>
#include <vortex2.h>

namespace vt = vortex::tensor;

namespace {

constexpr uint32_t kIterations = 2;
constexpr size_t kOutputWords = 512;
constexpr uint32_t kLocalBytes = 640;

#ifdef P02_WGMMA_SPARSE
constexpr bool kSparse = true;
#else
constexpr bool kSparse = false;
#endif
#ifdef WGMMA_RS
constexpr const char* kMode = "rs";
#else
constexpr const char* kMode = "ss";
#endif
#ifdef P02_WGMMA_SPARSE
constexpr const char* kLayout = "row-major-compressed";
#elif defined(WGMMA_RMAJOR_A)
constexpr const char* kLayout = "row-major";
#else
constexpr const char* kLayout = "block-major";
#endif

const char* configuration_error() {
#if !defined(VX_CFG_XLEN_64) || defined(VX_CFG_XLEN_32) || VX_CFG_XLEN != 64
  return "requires RV64";
#elif !defined(VX_CFG_EXT_TCU_ENABLE) || defined(VX_CFG_EXT_TCU_DISABLE) \
    || !defined(VX_CFG_TCU_TYPE_TFR) || !defined(VX_CFG_FPU_TYPE_STD) \
    || defined(VX_CFG_TCU_TYPE_DPI) || defined(VX_CFG_TCU_TYPE_DSP) \
    || defined(VX_CFG_TCU_TYPE_BHF) || defined(VX_CFG_TCU_TYPE_FPNEW) \
    || defined(VX_CFG_FPU_TYPE_DPI) || defined(VX_CFG_FPU_TYPE_DSP) \
    || defined(VX_CFG_FPU_TYPE_FPNEW)
  return "requires native TFR tensor and STD scalar arithmetic";
#elif VX_CFG_NUM_CLUSTERS != 1 || VX_CFG_NUM_CORES != 1 \
    || VX_CFG_NUM_THREADS != 8 || VX_CFG_NUM_WARPS != 8 \
    || VX_CFG_ISSUE_WIDTH != 4 || VX_CFG_FETCH_WIDTH != 2
  return "requires one cluster/core, eight threads/warps, issue width four and fetch width two";
#elif VX_CFG_NUM_ALU_BLOCKS != 1 || VX_CFG_NUM_LSU_BLOCKS != 1 \
    || VX_CFG_NUM_FPU_BLOCKS != 1 || VX_CFG_NUM_TCU_BLOCKS != 4 \
    || VX_CFG_NUM_TCU_LANES != 8 || VX_CFG_TCU_PE_RATIO != 1 \
    || VX_CFG_TCU_LATENCY != 4 || VX_CFG_TCU_USE_DSP != 0
  return "requires the frozen execution-block geometry and native TFR latency";
#elif !defined(VX_CFG_LMEM_ENABLE) || defined(VX_CFG_LMEM_DISABLE) \
    || VX_CFG_LMEM_LOG_SIZE != 14 || VX_CFG_LMEM_NUM_BANKS != 8
  return "requires 16 KiB local memory with eight banks";
#elif !defined(VX_CFG_TCU_FP16_ENABLE) || defined(VX_CFG_TCU_FP16_DISABLE) \
    || !defined(VX_CFG_TCU_WGMMA_ENABLE) || defined(VX_CFG_TCU_WGMMA_DISABLE)
  return "requires the FP16/BF16 bank and WGMMA";
#elif defined(VX_CFG_TCU_TF32_ENABLE) || defined(VX_CFG_TCU_FP8_ENABLE) \
    || defined(VX_CFG_TCU_FP4_ENABLE) || defined(VX_CFG_TCU_INT8_ENABLE) \
    || defined(VX_CFG_TCU_INT4_ENABLE) || defined(VX_CFG_TCU_MX_ENABLE) \
    || defined(VX_CFG_TCU_MXFP4_ENABLE) || defined(VX_CFG_TCU_NVFP4_ENABLE) \
    || defined(VX_CFG_TCU_DSM_ENABLE) || defined(VX_CFG_TCU_FEDP2K) \
    || defined(VX_CFG_EXT_LDST_MATRIX_ENABLE)
  return "requires unscaled FP16/BF16 WGMMA with scalar fragment loads/stores";
#elif WGMMA_NRC != 8 || KUNROLL != 1
  return "requires WGMMA_NRC=8 and KUNROLL=1";
#elif defined(WGMMA_RS) == defined(WGMMA_SS)
  return "requires exactly one explicit WGMMA_RS or WGMMA_SS mode";
#elif defined(P02_WGMMA_SPARSE) && (P02_WGMMA_SPARSE != 1 \
    || !defined(VX_CFG_TCU_SPARSE_ENABLE) || defined(VX_CFG_TCU_SPARSE_DISABLE) \
    || defined(WGMMA_RS) || defined(WGMMA_RMAJOR_A))
  return "sparse mode requires P02_WGMMA_SPARSE=1, sparse hardware and SS";
#elif !defined(P02_WGMMA_SPARSE) && defined(VX_CFG_TCU_SPARSE_ENABLE)
  return "dense mode requires sparse hardware disabled";
#elif defined(WGMMA_RMAJOR_A) && defined(WGMMA_RS)
  return "row-major A requires dense SS";
#elif defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__ != 0)
  return "requires a build without fast-math";
#else
  using Input = vt::ITYPE;
  using Output = vt::OTYPE;
  using Geometry = vt::wgmma_config_t<VX_CFG_NUM_THREADS, Input, Output, WGMMA_NRC>;
  if ((!std::is_same<Input, vt::fp16>::value && !std::is_same<Input, vt::bf16>::value)
      || !std::is_same<Output, vt::fp32>::value) {
    return "requires FP16 or BF16 inputs and FP32 output";
  }
  if ((kSparse || std::strcmp(kLayout, "row-major") == 0)
      && !std::is_same<Input, vt::fp16>::value) {
    return "sparse and row-major A configurations require FP16";
  }
  if (Geometry::tcM != 4 || Geometry::tcN != 2 || Geometry::tcK != 2
      || Geometry::xtileM != 8 || Geometry::xtileN != 8 || Geometry::tileK != 8) {
    return "requires the frozen 8x8x8 per-warp tile";
  }
  return nullptr;
#endif
}

const p02_wgmma::Case* parse_args(int argc, char** argv) {
  const char* id = nullptr;
  bool iterations_seen = false;
  for (int i = 1; i < argc; ++i) {
    if (std::strncmp(argv[i], "--case=", 7) == 0 && id == nullptr && argv[i][7] != '\0') {
      id = argv[i] + 7;
    } else if (std::strcmp(argv[i], "--iterations=2") == 0 && !iterations_seen) {
      iterations_seen = true;
    } else {
      std::fprintf(stderr, "invalid or duplicate argument: %s\n", argv[i]);
      return nullptr;
    }
  }
  if (id == nullptr || !iterations_seen) {
    std::fprintf(stderr, "usage: p02_wgmma --case=<fixture-id> --iterations=2\n");
    return nullptr;
  }
  const p02_wgmma::Case* selected = nullptr;
  for (const auto& fixture : p02_wgmma::cases) {
    if (std::strcmp(id, fixture.id) == 0) {
      if (selected != nullptr) {
        std::fprintf(stderr, "duplicate fixture ID: %s\n", id);
        return nullptr;
      }
      selected = &fixture;
    }
  }
  if (selected == nullptr) {
    std::fprintf(stderr, "unknown fixture: %s\n", id);
  }
  return selected;
}

const char* fixture_error(const p02_wgmma::Case& fixture) {
  if (fixture.sparse != kSparse || std::strcmp(fixture.format, vt::ITYPE::name) != 0) {
    return "fixture does not match the compiled format and sparse mode";
  }
  if (fixture.m != 64 || fixture.n != 8 || fixture.k != 16
      || fixture.a_word_count != (kSparse ? 256 : 512)
      || fixture.b_word_count != 64 || fixture.expected_count != kOutputWords
      || fixture.metadata_word_count != (kSparse ? 128 : 0)
      || fixture.a_words == nullptr || fixture.b_words == nullptr || fixture.expected == nullptr
      || (kSparse && fixture.metadata_words == nullptr)) {
    return "fixture shape or storage does not match the frozen 64x8x16 contract";
  }
  return nullptr;
}

std::vector<uint8_t> little_endian_bytes(const uint32_t* words, size_t count) {
  std::vector<uint8_t> bytes(count * 4);
  for (size_t i = 0; i < count; ++i) {
    for (size_t byte = 0; byte < 4; ++byte) {
      bytes[4 * i + byte] = uint8_t(words[i] >> (8 * byte));
    }
  }
  return bytes;
}

class Resources {
public:
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  vx_buffer_h a = nullptr;
  vx_buffer_h b = nullptr;
  vx_buffer_h c = nullptr;
  vx_buffer_h metadata = nullptr;
  std::array<vx_event_h, 3> input_events = {};
  vx_event_h poison_event = nullptr;
  vx_event_h launch_event = nullptr;
  vx_event_h read_event = nullptr;

  ~Resources() {
    close();
  }

  int close() {
    int errors = 0;
    if (queue != nullptr) {
      errors += check(vx_queue_finish(queue, VX_TIMEOUT_INFINITE), "vx_queue_finish");
    }
    errors += release(read_event, vx_event_release, "vx_event_release(read)");
    errors += release(launch_event, vx_event_release, "vx_event_release(launch)");
    errors += release(poison_event, vx_event_release, "vx_event_release(poison)");
    for (auto& event : input_events) {
      errors += release(event, vx_event_release, "vx_event_release(input)");
    }
    errors += release(kernel, vx_kernel_release, "vx_kernel_release");
    errors += release(module, vx_module_release, "vx_module_release");
    errors += release(metadata, vx_buffer_release, "vx_buffer_release(metadata)");
    errors += release(c, vx_buffer_release, "vx_buffer_release(C)");
    errors += release(b, vx_buffer_release, "vx_buffer_release(B)");
    errors += release(a, vx_buffer_release, "vx_buffer_release(A)");
    errors += release(queue, vx_queue_release, "vx_queue_release");
    errors += release(device, vx_device_release, "vx_device_release");
    return errors;
  }

  static int check(vx_result_t result, const char* operation) {
    if (result == VX_SUCCESS) {
      return 0;
    }
    std::fprintf(stderr, "%s failed with result %d\n", operation, int(result));
    return 1;
  }

  template <typename T, typename F>
  static int release(T& handle, F function, const char* operation) {
    if (handle == nullptr) {
      return 0;
    }
    const int error = check(function(handle), operation);
    handle = nullptr;
    return error;
  }
};

#define RT_CHECK(expression) \
  do { \
    if (Resources::check((expression), #expression) != 0) { \
      return 1; \
    } \
  } while (false)

int run(const p02_wgmma::Case& fixture) {
  const auto a_bytes = little_endian_bytes(fixture.a_words, fixture.a_word_count);
  const auto b_bytes = little_endian_bytes(fixture.b_words, fixture.b_word_count);
  const auto metadata_bytes = little_endian_bytes(fixture.metadata_words, fixture.metadata_word_count);
  std::vector<uint8_t> poison(kOutputWords * 4);
  std::vector<uint8_t> output(kOutputWords * 4);
  kernel_arg_t arguments = {};
  arguments.M = fixture.m;
  arguments.N = fixture.n;
  arguments.K = fixture.k;
  Resources resources;

  RT_CHECK(vx_device_open(0, &resources.device));
  uint64_t value = 0;
  for (const auto& capability : std::array<std::array<uint64_t, 2>, 6>{{
           {VX_CAPS_NUM_THREADS, 8}, {VX_CAPS_NUM_WARPS, 8},
           {VX_CAPS_ISSUE_WIDTH, 4}, {VX_CAPS_NUM_CORES, 1},
           {VX_CAPS_NUM_CLUSTERS, 1}, {VX_CAPS_LOCAL_MEM_SIZE, 16384}}}) {
    RT_CHECK(vx_device_query(resources.device, uint32_t(capability[0]), &value));
    if (value != capability[1]) {
      std::fprintf(stderr, "device capability %u differs: actual=%llu expected=%llu\n",
                   unsigned(capability[0]), static_cast<unsigned long long>(value),
                   static_cast<unsigned long long>(capability[1]));
      return 1;
    }
  }
  RT_CHECK(vx_device_query(resources.device, VX_CAPS_ISA_FLAGS, &value));
  if (VX_ISA_ARCH(value) != 64 || (value & VX_ISA_EXT_TCU) == 0
      || (value & VX_ISA_EXT_LMEM) == 0 || (value & VX_ISA_EXT_LDST_MATRIX) != 0) {
    std::fprintf(stderr, "device ISA differs from RV64 TCU/LMEM scalar fragment configuration\n");
    return 1;
  }
  vx_queue_info_t queue_info = {sizeof(queue_info), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
  RT_CHECK(vx_queue_create(resources.device, &queue_info, &resources.queue));
  RT_CHECK(vx_buffer_create(resources.device, a_bytes.size(), VX_MEM_READ, &resources.a));
  RT_CHECK(vx_buffer_create(resources.device, b_bytes.size(), VX_MEM_READ, &resources.b));
  RT_CHECK(vx_buffer_create(resources.device, output.size(), VX_MEM_READ_WRITE, &resources.c));
  RT_CHECK(vx_buffer_address(resources.a, &arguments.A_addr));
  RT_CHECK(vx_buffer_address(resources.b, &arguments.B_addr));
  RT_CHECK(vx_buffer_address(resources.c, &arguments.C_addr));
  RT_CHECK(vx_enqueue_write(resources.queue, resources.a, 0, a_bytes.data(), a_bytes.size(),
                            0, nullptr, &resources.input_events[0]));
  RT_CHECK(vx_enqueue_write(resources.queue, resources.b, 0, b_bytes.data(), b_bytes.size(),
                            0, nullptr, &resources.input_events[1]));
#ifdef P02_WGMMA_SPARSE
  RT_CHECK(vx_buffer_create(resources.device, metadata_bytes.size(), VX_MEM_READ, &resources.metadata));
  RT_CHECK(vx_buffer_address(resources.metadata, &arguments.meta_sp_addr));
  RT_CHECK(vx_enqueue_write(resources.queue, resources.metadata, 0, metadata_bytes.data(),
                            metadata_bytes.size(), 0, nullptr, &resources.input_events[2]));
#endif
  RT_CHECK(vx_module_load_file(resources.device, "kernel.vxbin", &resources.module));
  RT_CHECK(vx_module_get_kernel(resources.module, "main", &resources.kernel));

  size_t total_mismatches = 0;
  for (uint32_t iteration = 0; iteration < kIterations; ++iteration) {
    for (size_t i = 0; i < kOutputWords; ++i) {
      const uint32_t word = (iteration == 0 ? 0x7fc10000u : 0xffc20000u) | uint32_t(i);
      for (size_t byte = 0; byte < 4; ++byte) {
        poison[i * 4 + byte] = uint8_t(word >> (8 * byte));
        output[i * 4 + byte] = poison[i * 4 + byte];
      }
    }
    std::printf("P02_WGMMA_BEGIN {\"case_id\":\"%s\",\"format\":\"%s\",\"sparse\":%s,"
                "\"mode\":\"%s\",\"a_layout\":\"%s\",\"iteration\":%u,"
                "\"m\":64,\"n\":8,\"k\":16,\"words\":512}\n",
                fixture.id, fixture.format, kSparse ? "true" : "false", kMode, kLayout, iteration);
    if (std::fflush(stdout) != 0) {
      std::fprintf(stderr, "WGMMA begin output flush failed\n");
      return 1;
    }
    RT_CHECK(vx_enqueue_write(resources.queue, resources.c, 0, poison.data(), poison.size(),
                              0, nullptr, &resources.poison_event));
    std::array<vx_event_h, 4> waits = {resources.input_events[0], resources.input_events[1],
                                     resources.poison_event, resources.input_events[2]};
    vx_launch_info_t launch = {};
    launch.struct_size = sizeof(launch);
    launch.kernel = resources.kernel;
    launch.args_host = &arguments;
    launch.args_size = sizeof(arguments);
    launch.ndim = 2;
    launch.grid_dim[0] = 1;
    launch.grid_dim[1] = 2;
    launch.block_dim[0] = 32;
    launch.block_dim[1] = 1;
    launch.lmem_size = kLocalBytes;
    RT_CHECK(vx_enqueue_launch(resources.queue, &launch, kSparse ? 4 : 3, waits.data(),
                               &resources.launch_event));
    RT_CHECK(vx_enqueue_read(resources.queue, output.data(), resources.c, 0, output.size(),
                             1, &resources.launch_event, &resources.read_event));
    RT_CHECK(vx_event_wait_value(resources.read_event, 1, VX_TIMEOUT_INFINITE));

    std::array<uint32_t, kOutputWords> actual = {};
    size_t mismatches = 0;
    for (size_t i = 0; i < kOutputWords; ++i) {
      for (size_t byte = 0; byte < 4; ++byte) {
        actual[i] |= uint32_t(output[i * 4 + byte]) << (8 * byte);
      }
      mismatches += actual[i] != fixture.expected[i];
    }
    std::printf("P02_WGMMA_RESULT {\"case_id\":\"%s\",\"format\":\"%s\",\"sparse\":%s,"
                "\"mode\":\"%s\",\"a_layout\":\"%s\",\"iteration\":%u,"
                "\"checked\":512,\"mismatches\":%zu,\"actual_bits\":[",
                fixture.id, fixture.format, kSparse ? "true" : "false", kMode, kLayout, iteration, mismatches);
    for (size_t i = 0; i < kOutputWords; ++i) {
      std::printf("%s\"%08x\"", i == 0 ? "" : ",", actual[i]);
    }
    std::printf("],\"expected_bits\":[");
    for (size_t i = 0; i < kOutputWords; ++i) {
      std::printf("%s\"%08x\"", i == 0 ? "" : ",", fixture.expected[i]);
    }
    std::printf("]}\n");
    if (std::fflush(stdout) != 0) {
      std::fprintf(stderr, "WGMMA result output flush failed\n");
      return 1;
    }
    total_mismatches += mismatches;
    RT_CHECK(vx_device_dump_perf(resources.device, stdout));
    if (Resources::release(resources.read_event, vx_event_release, "vx_event_release(read)")
        + Resources::release(resources.launch_event, vx_event_release, "vx_event_release(launch)")
        + Resources::release(resources.poison_event, vx_event_release, "vx_event_release(poison)") != 0) {
      return 1;
    }
  }
  const int cleanup_errors = resources.close();
  if (total_mismatches != 0 || cleanup_errors != 0) {
    std::fprintf(stderr, "WGMMA verification failed: %zu mismatches, %d cleanup errors\n",
                 total_mismatches, cleanup_errors);
    return 1;
  }
  std::printf("P02_WGMMA_PASS {\"case_id\":\"%s\",\"iterations\":2,\"checked\":1024}\n", fixture.id);
  return std::fflush(stdout) == 0 ? 0 : 1;
}

} // namespace

int main(int argc, char** argv) {
  const auto* fixture = parse_args(argc, argv);
  if (fixture == nullptr) {
    return 2;
  }
  if (const char* error = configuration_error()) {
    std::fprintf(stderr, "invalid WGMMA configuration: %s\n", error);
    return 2;
  }
  if (const char* error = fixture_error(*fixture)) {
    std::fprintf(stderr, "invalid WGMMA fixture: %s\n", error);
    return 2;
  }
  return run(*fixture);
}
