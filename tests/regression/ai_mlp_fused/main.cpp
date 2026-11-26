// SPDX-License-Identifier: Apache-2.0

#include "../ai_mlp/p04_fixtures.h"
#include <ai_matmul_profile.h>
#include <ai_mlp_fused_args.h>
#include <vortex2.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
#include <unistd.h>
#include <vector>

namespace va = vortex::ai;

namespace {

constexpr uint32_t kHiddenWords = 128;
constexpr uint32_t kBridgeWords = 64;
constexpr uint32_t kOutputWords = 64;
constexpr uint32_t kSharedLmemBytes = 256; // 16x8 x 16-bit ReLU-cast hidden activations
constexpr uint32_t kDefaultIterations = 1;
constexpr uint32_t kMaxPrintedErrors = 32;

struct Options {
  const char* kernel_path = "kernel.vxbin";
  std::string case_filter;
  uint32_t iterations = kDefaultIterations;
  bool verify_hidden = false;
  bool show_help = false;
};

void show_usage(const char* argv0) {
  std::cout << "Usage: " << argv0
            << " [-k kernel.vxbin] [-c case_id] [-n iterations] [-v] [-h]\n"
            << "  -k path   Path to kernel.vxbin (default: kernel.vxbin)\n"
            << "  -c id     Run a single matching case ID (default: all 5 cases for compiled ITYPE)\n"
            << "  -n count  Repetitions per case (default: 1)\n"
            << "  -v        Materialize and bit-exact verify H_fp32 and H_q16 scratch\n"
            << "  -h        Show this help\n";
}

bool parse_args(int argc, char** argv, Options* out) {
  int opt;
  opterr = 0;
  while ((opt = getopt(argc, argv, "k:c:n:vh")) != -1) {
    switch (opt) {
      case 'k':
        out->kernel_path = optarg;
        break;
      case 'c':
        out->case_filter = optarg;
        break;
      case 'n': {
        char* end = nullptr;
        unsigned long val = std::strtoul(optarg, &end, 10);
        if (optarg[0] == '\0' || (end && *end != '\0') || val == 0 || val > 1000) {
          std::cerr << "Error: invalid iteration count '" << optarg << "'\n";
          return false;
        }
        out->iterations = static_cast<uint32_t>(val);
        break;
      }
      case 'v':
        out->verify_hidden = true;
        break;
      case 'h':
        out->show_help = true;
        return true;
      default:
        return false;
    }
  }
  return optind == argc;
}

template <size_t N>
void serialize_words_le(const std::array<uint32_t, N>& words, std::vector<uint8_t>* out) {
  out->resize(N * 4);
  for (size_t i = 0; i < N; ++i) {
    const uint32_t w = words[i];
    (*out)[i * 4 + 0] = static_cast<uint8_t>(w & 0xffu);
    (*out)[i * 4 + 1] = static_cast<uint8_t>((w >> 8) & 0xffu);
    (*out)[i * 4 + 2] = static_cast<uint8_t>((w >> 16) & 0xffu);
    (*out)[i * 4 + 3] = static_cast<uint8_t>((w >> 24) & 0xffu);
  }
}

uint32_t read_word_le(const uint8_t* bytes) noexcept {
  return uint32_t{bytes[0]} | (uint32_t{bytes[1]} << 8)
       | (uint32_t{bytes[2]} << 16) | (uint32_t{bytes[3]} << 24);
}

const char* compiled_format_name() noexcept {
  return va::kMatmulInputDType == va::kMlpFusedDTypeFp16 ? "fp16" : "bf16";
}

struct EventHandle {
  vx_event_h h = nullptr;

  EventHandle() = default;
  EventHandle(const EventHandle&) = delete;
  EventHandle& operator=(const EventHandle&) = delete;

  ~EventHandle() {
    release();
  }

  void release() noexcept {
    if (h) {
      vx_event_release(h);
      h = nullptr;
    }
  }
};

struct DeviceSession {
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  vx_buffer_h x_buf = nullptr;
  vx_buffer_h w1_buf = nullptr;
  vx_buffer_h w2_buf = nullptr;
  vx_buffer_h h_scratch_buf = nullptr;
  vx_buffer_h y_buf = nullptr;

  ~DeviceSession() {
    release();
  }

  void release() noexcept {
    if (queue) {
      vx_queue_release(queue);
      queue = nullptr;
    }
    if (kernel) {
      vx_kernel_release(kernel);
      kernel = nullptr;
    }
    if (module) {
      vx_module_release(module);
      module = nullptr;
    }
    if (y_buf) {
      vx_buffer_release(y_buf);
      y_buf = nullptr;
    }
    if (h_scratch_buf) {
      vx_buffer_release(h_scratch_buf);
      h_scratch_buf = nullptr;
    }
    if (w2_buf) {
      vx_buffer_release(w2_buf);
      w2_buf = nullptr;
    }
    if (w1_buf) {
      vx_buffer_release(w1_buf);
      w1_buf = nullptr;
    }
    if (x_buf) {
      vx_buffer_release(x_buf);
      x_buf = nullptr;
    }
    if (device) {
      vx_device_release(device);
      device = nullptr;
    }
  }
};

#define VX_CHECK(expr)                                                          \
  do {                                                                          \
    vx_result_t _rc = (expr);                                                   \
    if (_rc != VX_SUCCESS) {                                                    \
      std::cerr << "FAILED " << #expr << ": " << vx_result_string(_rc) << '\n'; \
      return 1;                                                                 \
    }                                                                           \
  } while (0)

bool check_device_profile(vx_device_h device) {
  uint64_t isa = 0;
  uint64_t threads = 0, warps = 0, cores = 0, clusters = 0, issue_width = 0, lmem = 0;
  if (vx_device_query(device, VX_CAPS_ISA_FLAGS, &isa) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_THREADS, &threads) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_WARPS, &warps) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CORES, &cores) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CLUSTERS, &clusters) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_ISSUE_WIDTH, &issue_width) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_LOCAL_MEM_SIZE, &lmem) != VX_SUCCESS) {
    std::cerr << "FAILED device capability query\n";
    return false;
  }
  if (VX_ISA_ARCH(isa) != 64 || (isa & VX_ISA_EXT_TCU) == 0 || (isa & VX_ISA_EXT_LMEM) == 0
      || threads != 4 || warps != 4 || cores != 1 || clusters != 1
      || issue_width != 1 || lmem < kSharedLmemBytes) {
    std::cerr << "FAILED device capabilities do not match p02-tfr profile\n";
    return false;
  }
  return true;
}

uint64_t read_mpm_safe(vx_device_h device, uint32_t mpm_class, uint32_t addr) {
  uint64_t val = 0;
  if (vx_device_mpm_query(device, mpm_class, addr, 0xffffffffu, &val) != VX_SUCCESS) {
    return 0;
  }
  return val;
}

uint64_t event_duration_ns(vx_event_h ev) {
  if (!ev) {
    return 0;
  }
  vx_profile_info_t info{};
  if (vx_event_get_profiling(ev, &info) != VX_SUCCESS || info.end_ns < info.start_ns) {
    return 0;
  }
  return info.end_ns - info.start_ns;
}

} // namespace

int main(int argc, char** argv) {
  Options opts;
  if (!parse_args(argc, argv, &opts)) {
    show_usage(argv[0]);
    return 2;
  }
  if (opts.show_help) {
    show_usage(argv[0]);
    return 0;
  }

  const std::string_view fmt = compiled_format_name();
  std::vector<const p04::Fixture*> cases;
  for (size_t i = 0; i < p04::kCaseCount; ++i) {
    const auto& fx = p04::kFixtures[i];
    if (std::string_view(fx.format) == fmt) {
      if (opts.case_filter.empty() || opts.case_filter == fx.id) {
        cases.push_back(&fx);
      }
    }
  }
  if (cases.empty()) {
    std::cerr << "FAILED no matching P04 cases for format '" << fmt << "'\n";
    return 2;
  }

  std::vector<uint8_t> h_x;
  std::vector<uint8_t> h_w1;
  std::vector<uint8_t> h_w2;
  std::vector<uint8_t> h_poison_y(va::kMlpFusedYBytes);
  std::vector<uint8_t> h_poison_scratch(va::kMlpFusedHScratchBytes);
  std::vector<uint8_t> h_y_bytes(va::kMlpFusedYBytes);
  std::vector<uint8_t> h_scratch_bytes(va::kMlpFusedHScratchBytes);

  DeviceSession session;
  VX_CHECK(vx_device_open(0, &session.device));
  if (!check_device_profile(session.device)) {
    return 1;
  }

  vx_queue_info_t qi{};
  qi.struct_size = sizeof(qi);
  qi.priority = VX_QUEUE_PRIORITY_NORMAL;
  qi.flags = VX_QUEUE_PROFILING_ENABLE;
  VX_CHECK(vx_queue_create(session.device, &qi, &session.queue));

  VX_CHECK(vx_module_load_file(session.device, opts.kernel_path, &session.module));
  VX_CHECK(vx_module_get_kernel(session.module, "main", &session.kernel));

  VX_CHECK(vx_buffer_create(session.device, va::kMlpFusedXBytes, VX_MEM_READ, &session.x_buf));
  VX_CHECK(vx_buffer_create(session.device, va::kMlpFusedW1Bytes, VX_MEM_READ, &session.w1_buf));
  VX_CHECK(vx_buffer_create(session.device, va::kMlpFusedW2Bytes, VX_MEM_READ, &session.w2_buf));
  VX_CHECK(vx_buffer_create(session.device, va::kMlpFusedHScratchBytes, VX_MEM_READ_WRITE, &session.h_scratch_buf));
  VX_CHECK(vx_buffer_create(session.device, va::kMlpFusedYBytes, VX_MEM_READ_WRITE, &session.y_buf));

  va::MlpFusedArguments base_args{};
  base_args.input_dtype = va::kMatmulInputDType;
  base_args.flags = opts.verify_hidden ? va::kMlpFusedFlagWriteHiddenFp32 : 0u;
  VX_CHECK(vx_buffer_address(session.x_buf, &base_args.x_addr));
  VX_CHECK(vx_buffer_address(session.w1_buf, &base_args.w1_addr));
  VX_CHECK(vx_buffer_address(session.w2_buf, &base_args.w2_addr));
  VX_CHECK(vx_buffer_address(session.h_scratch_buf, &base_args.h_scratch_addr));
  VX_CHECK(vx_buffer_address(session.y_buf, &base_args.y_addr));

  uint32_t total_output_words_checked = 0;
  uint32_t total_output_mismatches = 0;
  uint32_t total_hidden_words_checked = 0;
  uint32_t total_hidden_mismatches = 0;
  uint32_t total_bridge_words_checked = 0;
  uint32_t total_bridge_mismatches = 0;
  uint64_t total_launches = 0;
  uint64_t total_h2d_bytes = 0;
  uint64_t total_d2h_bytes = 0;
  uint64_t total_launch_ns = 0;
  uint64_t total_wall_ns = 0;

  for (const p04::Fixture* fx : cases) {
    serialize_words_le(fx->inputs.input_words, &h_x);
    serialize_words_le(fx->inputs.w1_words, &h_w1);
    serialize_words_le(fx->inputs.w2_words, &h_w2);

    for (uint32_t iter = 0; iter < opts.iterations; ++iter) {
      std::fill(h_y_bytes.begin(), h_y_bytes.end(), static_cast<uint8_t>(0x5au));
      std::fill(h_scratch_bytes.begin(), h_scratch_bytes.end(), static_cast<uint8_t>(0x5au));

      const uint32_t poison = (iter & 1u) == 0 ? 0x7fc0deadu : 0xdeadbeefu;
      for (size_t i = 0; i < kOutputWords; ++i) {
        const uint32_t p = poison ^ static_cast<uint32_t>(i);
        h_poison_y[i * 4 + 0] = static_cast<uint8_t>(p & 0xffu);
        h_poison_y[i * 4 + 1] = static_cast<uint8_t>((p >> 8) & 0xffu);
        h_poison_y[i * 4 + 2] = static_cast<uint8_t>((p >> 16) & 0xffu);
        h_poison_y[i * 4 + 3] = static_cast<uint8_t>((p >> 24) & 0xffu);
      }
      if (opts.verify_hidden) {
        for (size_t i = 0; i < va::kMlpFusedHScratchBytes / 4; ++i) {
          const uint32_t p = poison ^ static_cast<uint32_t>(i);
          h_poison_scratch[i * 4 + 0] = static_cast<uint8_t>(p & 0xffu);
          h_poison_scratch[i * 4 + 1] = static_cast<uint8_t>((p >> 8) & 0xffu);
          h_poison_scratch[i * 4 + 2] = static_cast<uint8_t>((p >> 16) & 0xffu);
          h_poison_scratch[i * 4 + 3] = static_cast<uint8_t>((p >> 24) & 0xffu);
        }
      }

      const uint64_t cycles_before = read_mpm_safe(session.device, 1, 0xB00 /* MCYCLE */);
      const uint64_t instret_before = read_mpm_safe(session.device, 1, 0xB02 /* MINSTRET */);
      const auto t_start = std::chrono::steady_clock::now();

      EventHandle ev_x;
      EventHandle ev_w1;
      EventHandle ev_w2;
      EventHandle ev_poison_y;
      EventHandle ev_poison_h;
      EventHandle ev_launch;
      EventHandle ev_read_y;
      EventHandle ev_read_h;

      VX_CHECK(vx_enqueue_write(session.queue, session.x_buf, 0, h_x.data(), h_x.size(), 0, nullptr, &ev_x.h));
      VX_CHECK(vx_enqueue_write(session.queue, session.w1_buf, 0, h_w1.data(), h_w1.size(), 1, &ev_x.h, &ev_w1.h));
      VX_CHECK(vx_enqueue_write(session.queue, session.w2_buf, 0, h_w2.data(), h_w2.size(), 1, &ev_w1.h, &ev_w2.h));
      VX_CHECK(vx_enqueue_write(session.queue, session.y_buf, 0, h_poison_y.data(), h_poison_y.size(), 1, &ev_w2.h, &ev_poison_y.h));
      vx_event_h launch_dep = ev_poison_y.h;
      if (opts.verify_hidden) {
        VX_CHECK(vx_enqueue_write(session.queue, session.h_scratch_buf, 0, h_poison_scratch.data(),
                                  h_poison_scratch.size(), 1, &ev_poison_y.h, &ev_poison_h.h));
        launch_dep = ev_poison_h.h;
      }

      vx_launch_info_t li{};
      li.struct_size = sizeof(li);
      li.kernel = session.kernel;
      li.args_host = &base_args;
      li.args_size = sizeof(base_args);
      li.ndim = 2;
      li.grid_dim[0] = 1;
      li.grid_dim[1] = 1;
      li.grid_dim[2] = 1;
      li.block_dim[0] = 16;
      li.block_dim[1] = 1;
      li.block_dim[2] = 1;
      li.lmem_size = kSharedLmemBytes;
      li.cluster_dim[0] = 1;
      li.cluster_dim[1] = 1;
      li.cluster_dim[2] = 1;

      VX_CHECK(vx_enqueue_launch(session.queue, &li, 1, &launch_dep, &ev_launch.h));
      VX_CHECK(vx_enqueue_read(session.queue, h_y_bytes.data(), session.y_buf, 0,
                               h_y_bytes.size(), 1, &ev_launch.h, &ev_read_y.h));
      vx_event_h final_ev = ev_read_y.h;
      if (opts.verify_hidden) {
        VX_CHECK(vx_enqueue_read(session.queue, h_scratch_bytes.data(), session.h_scratch_buf, 0,
                                 h_scratch_bytes.size(), 1, &ev_read_y.h, &ev_read_h.h));
        final_ev = ev_read_h.h;
      }
      VX_CHECK(vx_event_wait_value(final_ev, 1, VX_TIMEOUT_INFINITE));

      const auto t_end = std::chrono::steady_clock::now();
      const uint64_t wall_ns = static_cast<uint64_t>(
          std::chrono::duration_cast<std::chrono::nanoseconds>(t_end - t_start).count());
      const uint64_t launch_ns = event_duration_ns(ev_launch.h);
      const uint64_t cycles_after = read_mpm_safe(session.device, 1, 0xB00);
      const uint64_t instret_after = read_mpm_safe(session.device, 1, 0xB02);
      const uint64_t delta_cycles = cycles_after >= cycles_before ? (cycles_after - cycles_before) : 0;
      const uint64_t delta_instret = instret_after >= instret_before ? (instret_after - instret_before) : 0;

      ev_x.release();
      ev_w1.release();
      ev_w2.release();
      ev_poison_y.release();
      ev_poison_h.release();
      ev_launch.release();
      ev_read_y.release();
      ev_read_h.release();

      uint32_t case_out_err = 0;
      for (size_t i = 0; i < kOutputWords; ++i) {
        const uint32_t actual = read_word_le(h_y_bytes.data() + i * 4);
        const uint32_t expected = fx->expected.output_words[i];
        ++total_output_words_checked;
        if (actual != expected) {
          if (total_output_mismatches + case_out_err < kMaxPrintedErrors) {
            std::printf("*** Y mismatch [%s iter=%u idx=%zu] expected=0x%08x actual=0x%08x\n",
                        fx->id, iter, i, expected, actual);
          }
          ++case_out_err;
        }
      }
      total_output_mismatches += case_out_err;

      uint32_t case_hidden_err = 0;
      uint32_t case_bridge_err = 0;
      if (opts.verify_hidden) {
        for (size_t i = 0; i < kHiddenWords; ++i) {
          const uint32_t actual = read_word_le(h_scratch_bytes.data() + i * 4);
          const uint32_t expected = fx->expected.hidden_words[i];
          ++total_hidden_words_checked;
          if (actual != expected) {
            if (total_hidden_mismatches + case_hidden_err < kMaxPrintedErrors) {
              std::printf("*** H_fp32 mismatch [%s iter=%u idx=%zu] expected=0x%08x actual=0x%08x\n",
                          fx->id, iter, i, expected, actual);
            }
            ++case_hidden_err;
          }
        }
        total_hidden_mismatches += case_hidden_err;

        const uint8_t* q16_base = h_scratch_bytes.data() + va::kMlpFusedHScratchFp32Bytes;
        for (size_t i = 0; i < kBridgeWords; ++i) {
          const uint32_t actual = read_word_le(q16_base + i * 4);
          const uint32_t expected = fx->expected.bridge_words[i];
          ++total_bridge_words_checked;
          if (actual != expected) {
            if (total_bridge_mismatches + case_bridge_err < kMaxPrintedErrors) {
              std::printf("*** H_q16 mismatch [%s iter=%u idx=%zu] expected=0x%08x actual=0x%08x\n",
                          fx->id, iter, i, expected, actual);
            }
            ++case_bridge_err;
          }
        }
        total_bridge_mismatches += case_bridge_err;
      }

      const uint64_t h2d_bytes = va::kMlpFusedXBytes + va::kMlpFusedW1Bytes + va::kMlpFusedW2Bytes
                               + va::kMlpFusedYBytes
                               + (opts.verify_hidden ? va::kMlpFusedHScratchBytes : 0);
      const uint64_t d2h_bytes = va::kMlpFusedYBytes
                               + (opts.verify_hidden ? va::kMlpFusedHScratchBytes : 0);
      total_launches += 1;
      total_h2d_bytes += h2d_bytes;
      total_d2h_bytes += d2h_bytes;
      total_launch_ns += launch_ns;
      total_wall_ns += wall_ns;

      std::printf("FUSED_CASE id=%s iter=%u launches=1 h2d_bytes=%llu d2h_bytes=%llu "
                  "mpm_cycles=%llu mpm_instret=%llu launch_ns=%llu wall_ns=%llu "
                  "y_mismatches=%u h_mismatches=%u q_mismatches=%u\n",
                  fx->id, iter,
                  static_cast<unsigned long long>(h2d_bytes),
                  static_cast<unsigned long long>(d2h_bytes),
                  static_cast<unsigned long long>(delta_cycles),
                  static_cast<unsigned long long>(delta_instret),
                  static_cast<unsigned long long>(launch_ns),
                  static_cast<unsigned long long>(wall_ns),
                  case_out_err, case_hidden_err, case_bridge_err);
    }
  }

  std::printf("FUSED_SUMMARY format=%s cases=%zu iterations=%u total_launches=%llu "
              "total_h2d_bytes=%llu total_d2h_bytes=%llu total_launch_ns=%llu total_wall_ns=%llu "
              "output_checked=%u output_mismatches=%u hidden_checked=%u hidden_mismatches=%u "
              "bridge_checked=%u bridge_mismatches=%u\n",
              compiled_format_name(), cases.size(), opts.iterations,
              static_cast<unsigned long long>(total_launches),
              static_cast<unsigned long long>(total_h2d_bytes),
              static_cast<unsigned long long>(total_d2h_bytes),
              static_cast<unsigned long long>(total_launch_ns),
              static_cast<unsigned long long>(total_wall_ns),
              total_output_words_checked, total_output_mismatches,
              total_hidden_words_checked, total_hidden_mismatches,
              total_bridge_words_checked, total_bridge_mismatches);

  vx_device_dump_perf(session.device, stdout);
  session.release();

  if (total_output_mismatches != 0 || total_hidden_mismatches != 0 || total_bridge_mismatches != 0) {
    std::cout << "FAILED!\n";
    return 1;
  }
  std::cout << "PASSED!\n";
  return 0;
}
