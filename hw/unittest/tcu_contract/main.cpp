// Copyright © 2026
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "VX_config.h"
#include "p02_tfr_vectors.h"

#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <iomanip>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef P02_MODEL_ONLY
#include "fedp.h"
#else
#include "VVX_tcu_fedp_tfr.h"
#include <verilated.h>
#endif

#if !defined(VX_CFG_XLEN_64) || VX_CFG_XLEN != 64
#error "The frozen tensor contract requires an RV64 generated build"
#endif
#if !defined(VX_CFG_EXT_TCU_ENABLE) || !defined(VX_CFG_TCU_TYPE_TFR)
#error "The frozen tensor contract requires the native TFR configuration"
#endif
#if !defined(VX_CFG_TCU_FP16_ENABLE) || defined(VX_CFG_TCU_FP16_DISABLE)
#error "The frozen tensor contract requires FP16 and BF16 support"
#endif
#if VX_CFG_TCU_LATENCY != 4 || VX_CFG_TCU_USE_DSP != 0
#error "The frozen tensor contract requires latency=4 and USE_DSP=0"
#endif
#if VX_CFG_NUM_THREADS != 4
#error "The frozen tensor contract requires NUM_THREADS=4"
#endif
#if defined(VX_CFG_TCU_TYPE_DPI) || defined(VX_CFG_TCU_TYPE_DSP) \
    || defined(VX_CFG_TCU_TYPE_BHF) || defined(VX_CFG_TCU_TYPE_FPNEW)
#error "Only the native TFR backend belongs to this contract"
#endif
#if defined(VX_CFG_TCU_TF32_ENABLE) || defined(VX_CFG_TCU_FP8_ENABLE) \
    || defined(VX_CFG_TCU_FP4_ENABLE) || defined(VX_CFG_TCU_INT8_ENABLE) \
    || defined(VX_CFG_TCU_INT4_ENABLE) || defined(VX_CFG_TCU_MX_ENABLE) \
    || defined(VX_CFG_TCU_MXFP4_ENABLE) || defined(VX_CFG_TCU_NVFP4_ENABLE) \
    || defined(VX_CFG_TCU_SPARSE_ENABLE) || defined(VX_CFG_TCU_DSM_ENABLE) \
    || defined(VX_CFG_TCU_WGMMA_ENABLE) || defined(VX_CFG_TCU_FEDP2K)
#error "The frozen tensor contract is limited to dense FP16/BF16"
#endif
#if !defined(P02_NUM_REGS) || P02_NUM_REGS != 2 \
    || !defined(P02_WINDOW) || P02_WINDOW != 25 \
    || !defined(P02_LATENCY) || P02_LATENCY != 4 \
    || !defined(P02_USE_DSP) || P02_USE_DSP != 0 \
    || !defined(P02_LANE_MASK) || P02_LANE_MASK != 1
#error "The testbench and DUT require N=2, W=25, LATENCY=4, USE_DSP=0, LANE_MASK=1"
#endif
#if defined(__FAST_MATH__) || defined(SV_DPI)
#error "Raw-bit fixtures require ordinary host floating-point semantics and no DPI"
#endif

static_assert(p02_tensor::contract_version == 1, "Unsupported fixture contract");
static_assert(p02_tensor::packed_words == 2, "Fixtures must contain two packed words");
static_assert(p02_tensor::vectors.size() > 0, "An empty fixture suite cannot pass");

namespace {

using Vector = p02_tensor::Vector;
constexpr uint32_t kFp16 = 2;
constexpr uint32_t kBf16 = 3;

#ifdef P02_MODEL_ONLY
constexpr const char* kBackend = "tfr_model";
#else
constexpr const char* kBackend = "native_tfr";
constexpr size_t kLatency = P02_LATENCY;
#endif

struct Options {
  std::string format = "all";
  std::string case_id;
  bool stalls = false;
  bool help = false;
};

struct Counts {
  size_t executed = 0;
  size_t failed = 0;
  size_t enabled_cycles = 0;
  size_t stall_cycles = 0;
  size_t hold_failures = 0;
};

std::string hex32(uint32_t value) {
  std::ostringstream out;
  out << "0x" << std::hex << std::setfill('0') << std::setw(8) << value;
  return out.str();
}

const char* format_name(uint32_t format) {
  return format == kFp16 ? "fp16" : "bf16";
}

Options parse_options(int argc, char** argv) {
  Options options;
  bool format_seen = false;
  bool case_seen = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg.rfind("--format=", 0) == 0) {
      if (format_seen) {
        throw std::invalid_argument("Duplicate --format option");
      }
      format_seen = true;
      options.format = arg.substr(9);
      if (options.format != "fp16" && options.format != "bf16" && options.format != "all") {
        throw std::invalid_argument("--format must be fp16, bf16 or all");
      }
    } else if (arg.rfind("--case=", 0) == 0) {
      if (case_seen || arg.size() == 7) {
        throw std::invalid_argument("--case requires one nonempty exact fixture ID");
      }
      case_seen = true;
      options.case_id = arg.substr(7);
    } else if (arg == "--stalls") {
      if (options.stalls) {
        throw std::invalid_argument("Duplicate --stalls option");
      }
      options.stalls = true;
    } else if (arg == "--help") {
      if (argc != 2) {
        throw std::invalid_argument("--help must be used alone");
      }
      options.help = true;
    } else {
      throw std::invalid_argument("Unknown option: " + arg);
    }
  }
#ifdef P02_MODEL_ONLY
  if (options.stalls) {
    throw std::invalid_argument("--stalls requires native_tfr; tfr_model has no clocked pipeline");
  }
#endif
  return options;
}

std::vector<const Vector*> select_vectors(const Options& options) {
  std::set<std::string> ids;
  std::vector<const Vector*> selected;
  bool found_case = options.case_id.empty();
  size_t fp16_count = 0;
  size_t bf16_count = 0;
  for (const auto& vector : p02_tensor::vectors) {
    if (vector.id == nullptr || vector.id[0] == '\0' || !ids.insert(vector.id).second) {
      throw std::runtime_error("Fixture IDs must be nonempty and unique");
    }
    if (vector.fmt != kFp16 && vector.fmt != kBf16) {
      throw std::runtime_error("Fixture format is outside the FP16/BF16 contract");
    }
    fp16_count += vector.fmt == kFp16;
    bf16_count += vector.fmt == kBf16;
    const bool case_match = options.case_id.empty() || options.case_id == vector.id;
    found_case = found_case || options.case_id == vector.id;
    if (case_match && (options.format == "all" || options.format == format_name(vector.fmt))) {
      selected.push_back(&vector);
    }
  }
  if (fp16_count == 0 || bf16_count == 0) {
    throw std::runtime_error("The frozen suite must include both FP16 and BF16");
  }
  if (!found_case) {
    throw std::invalid_argument("Unknown fixture ID: " + options.case_id);
  }
  if (selected.empty()) {
    throw std::invalid_argument("The format/case selection contains no fixtures");
  }
  return selected;
}

void check_case(const Vector& vector, uint32_t actual, const char* mode, Counts* counts) {
  const bool pass = actual == vector.expected;
  ++counts->executed;
  counts->failed += !pass;
  std::cout << "case backend=" << kBackend << " mode=" << mode
            << " id=" << vector.id << " format=" << format_name(vector.fmt)
            << " actual=" << hex32(actual) << " expected=" << hex32(vector.expected)
            << " status=" << (pass ? "pass" : "fail") << '\n';
}

bool report_counts(const char* mode, size_t selected, const Counts& counts) {
  const bool pass = counts.executed == selected && counts.executed != 0
                 && counts.failed == 0 && counts.hold_failures == 0;
  std::cout << "count backend=" << kBackend << " mode=" << mode
            << " selected=" << selected << " executed=" << counts.executed
            << " passed=" << counts.executed - counts.failed << " failed=" << counts.failed
            << " enabled_cycles=" << counts.enabled_cycles
            << " stall_cycles=" << counts.stall_cycles
            << " hold_checks=" << counts.stall_cycles * 2
            << " hold_failures=" << counts.hold_failures
            << " status=" << (pass ? "pass" : "fail") << '\n';
  return pass;
}

#ifdef P02_MODEL_ONLY

bool run_model(const std::vector<const Vector*>& selected) {
  static_assert(sizeof(float) == sizeof(uint32_t) && std::numeric_limits<float>::is_iec559,
                "The production model requires IEEE binary32 host floats");
  TfrFedp fp16(5, 10, 0, P02_WINDOW, false, false);
  TfrFedp bf16(8, 7, 0, P02_WINDOW, false, false);
  Counts counts;
  for (const Vector* vector : selected) {
    float c;
    std::memcpy(&c, &vector->c, sizeof(c));
    TfrFedp& model = vector->fmt == kFp16 ? fp16 : bf16;
    const float result = model(vector->a.data(), vector->b.data(), c, P02_NUM_REGS);
    uint32_t actual;
    std::memcpy(&actual, &result, sizeof(actual));
    check_case(*vector, actual, "model_dense", &counts);
  }
  return report_counts("model_dense", selected.size(), counts);
}

#else

class NativeDut {
public:
  NativeDut() : dut_(&context_) {
    dut_.clk = 0;
    dut_.reset = 1;
    drive(nullptr);
    tick(false);
    dut_.reset = 0;
    dut_.eval();
  }

  ~NativeDut() {
    dut_.final();
  }

  void drive(const Vector* vector) {
    dut_.fmt_s = vector ? vector->fmt : kFp16;
    dut_.fmt_d = 0;
    dut_.vld_mask = vector ? 0x1111 : 0;
    dut_.a_row = vector ? pack(vector->a) : 0;
    dut_.b_col = vector ? pack(vector->b) : 0;
    dut_.c_val = vector ? vector->c : 0;
  }

  uint32_t tick(bool enable) {
    dut_.enable = enable;
    dut_.clk = 0;
    dut_.eval();
    context_.timeInc(1);
    dut_.clk = 1;
    dut_.eval();
    context_.timeInc(1);
    if (context_.gotFinish()) {
      throw std::runtime_error("The native DUT stopped before the fixture run completed");
    }
    return dut_.d_val;
  }

  void check_hold(size_t pattern, Counts* counts) {
    const uint32_t held = dut_.d_val;
    dut_.enable = 0;
    dut_.fmt_s = (pattern & 1) ? kBf16 : kFp16;
    dut_.vld_mask = (pattern & 1) ? 0 : 0x1111;
    dut_.a_row = (pattern & 1) ? 0x7f807f807f807f80ull : 0x3c003c003c003c00ull;
    dut_.b_col = (pattern & 1) ? 0x0000000000000000ull : 0xbc00bc00bc00bc00ull;
    dut_.c_val = (pattern & 1) ? 0x7fc00000u : 0x80000000u;
    dut_.eval();
    const uint32_t after_drive = dut_.d_val;
    const uint32_t after_edge = tick(false);
    ++counts->stall_cycles;
    if (after_drive != held || after_edge != held) {
      ++counts->hold_failures;
      std::cout << "hold backend=native_tfr mode=unit_stall cycle=" << counts->stall_cycles
                << " expected=" << hex32(held) << " after_drive=" << hex32(after_drive)
                << " after_edge=" << hex32(after_edge) << " status=fail\n";
    }
  }

private:
  static uint64_t pack(const std::array<uint32_t, 2>& words) {
    return static_cast<uint64_t>(words[0]) | (static_cast<uint64_t>(words[1]) << 32);
  }

  VerilatedContext context_;
  VVX_tcu_fedp_tfr dut_;
};

bool run_native(const std::vector<const Vector*>& selected, bool stalls) {
  NativeDut dut;
  Counts counts;
  const char* mode = stalls ? "unit_stall" : "unit_dense";
  std::deque<const Vector*> pending(kLatency - 1, nullptr);
  const size_t enabled_limit = selected.size() + kLatency - 1;
  for (size_t cycle = 0; cycle < enabled_limit; ++cycle) {
    if (stalls) {
      for (size_t pause = 0; pause < 1 + (cycle % 2); ++pause) {
        dut.check_hold(counts.stall_cycles, &counts);
      }
    }
    const Vector* input = cycle < selected.size() ? selected[cycle] : nullptr;
    dut.drive(input);
    const uint32_t actual = dut.tick(true);
    ++counts.enabled_cycles;
    pending.push_back(input);
    const Vector* ready = pending.front();
    pending.pop_front();
    if (ready != nullptr) {
      check_case(*ready, actual, mode, &counts);
    }
  }
  if (stalls) {
    dut.check_hold(counts.stall_cycles, &counts);
    dut.check_hold(counts.stall_cycles, &counts);
  }
  return report_counts(mode, selected.size(), counts);
}

#endif

} // namespace

int main(int argc, char** argv) {
  try {
    const Options options = parse_options(argc, argv);
    if (options.help) {
      std::cout << "Usage: " << argv[0]
                << " [--format=fp16|bf16|all] [--case=<exact-id>] [--stalls]\n"
                << "Default: --format=all. --stalls checks only the native leaf pipeline.\n";
      return 0;
    }
    const auto selected = select_vectors(options);
    std::cout << "boundary backend=" << kBackend
#ifdef P02_MODEL_ONLY
              << " scope=tfr_model_function"
#else
              << " scope=leaf_fedp_unit"
#endif
              << " contract_version=" << p02_tensor::contract_version
              << " n=2 packed_products=4 window=25 xlen=64 threads=4 latency=4 use_dsp=0 lane_mask=1"
              << " destination=fp32 rounding=rne compare=raw_bits full_simx=false wgmma=false"
              << " fixture_count=" << p02_tensor::vectors.size() << " selected=" << selected.size()
              << " format=" << options.format << " stalls=" << (options.stalls ? "true" : "false")
              << '\n';
#ifdef P02_MODEL_ONLY
    const bool pass = run_model(selected);
#else
    Verilated::commandArgs(argc, argv);
    bool pass = run_native(selected, false);
    if (options.stalls) {
      pass = run_native(selected, true) && pass;
    }
#endif
    std::cout << "result backend=" << kBackend << " status=" << (pass ? "pass" : "fail") << '\n';
    return pass ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << "error backend=" << kBackend << " message=" << error.what() << '\n';
    return 2;
  }
}
