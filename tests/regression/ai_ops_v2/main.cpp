// SPDX-License-Identifier: Apache-2.0

#include <ai_ops_v2_args.h>
#include <vortex2.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <unistd.h>
#include <vector>

namespace va = vortex::ai;

namespace {

constexpr uint32_t kDefaultIterations = 1;
constexpr uint32_t kMaxPrintedErrors = 32;
constexpr double kApproxMaxAbsErr = 1e-4;

struct Options {
  const char* kernel_path = "kernel.vxbin";
  std::string op_filter;
  uint32_t iterations = kDefaultIterations;
  bool show_help = false;
};

void show_usage(const char* argv0) {
  std::cout << "Usage: " << argv0
            << " [-k kernel.vxbin] [-o op_name] [-n iterations] [-h]\n"
            << "  -k path   Path to kernel.vxbin (default: kernel.vxbin)\n"
            << "  -o name   Run a single matching operator case name\n"
            << "  -n count  Repetitions per case (default: 1)\n"
            << "  -h        Show this help\n";
}

bool parse_args(int argc, char** argv, Options* out) {
  int opt;
  opterr = 0;
  while ((opt = getopt(argc, argv, "k:o:n:h")) != -1) {
    switch (opt) {
      case 'k':
        out->kernel_path = optarg;
        break;
      case 'o':
        out->op_filter = optarg;
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
      case 'h':
        out->show_help = true;
        return true;
      default:
        return false;
    }
  }
  return optind == argc;
}

uint32_t float_to_bits(float v) noexcept {
  uint32_t bits = 0;
  std::memcpy(&bits, &v, sizeof(bits));
  return bits;
}

float bits_to_float(uint32_t bits) noexcept {
  float v = 0.0f;
  std::memcpy(&v, &bits, sizeof(v));
  return v;
}

void write_u32_le(uint8_t* dst, uint32_t w) noexcept {
  dst[0] = static_cast<uint8_t>(w & 0xffu);
  dst[1] = static_cast<uint8_t>((w >> 8) & 0xffu);
  dst[2] = static_cast<uint8_t>((w >> 16) & 0xffu);
  dst[3] = static_cast<uint8_t>((w >> 24) & 0xffu);
}

void write_u16_le(uint8_t* dst, uint16_t h) noexcept {
  dst[0] = static_cast<uint8_t>(h & 0xffu);
  dst[1] = static_cast<uint8_t>((h >> 8) & 0xffu);
}

uint32_t read_u32_le(const uint8_t* src) noexcept {
  return uint32_t{src[0]} | (uint32_t{src[1]} << 8)
       | (uint32_t{src[2]} << 16) | (uint32_t{src[3]} << 24);
}

uint16_t read_u16_le(const uint8_t* src) noexcept {
  return static_cast<uint16_t>(uint16_t{src[0]} | (uint16_t{src[1]} << 8));
}

std::vector<uint8_t> pack_f32_words(const std::vector<uint32_t>& words) {
  std::vector<uint8_t> bytes(words.size() * 4);
  for (size_t i = 0; i < words.size(); ++i) {
    write_u32_le(bytes.data() + i * 4, words[i]);
  }
  return bytes;
}

std::vector<uint8_t> pack_f32_floats(const std::vector<float>& vals) {
  std::vector<uint8_t> bytes(vals.size() * 4);
  for (size_t i = 0; i < vals.size(); ++i) {
    write_u32_le(bytes.data() + i * 4, float_to_bits(vals[i]));
  }
  return bytes;
}

std::vector<uint8_t> pack_u16_words(const std::vector<uint16_t>& words) {
  std::vector<uint8_t> bytes(words.size() * 2);
  for (size_t i = 0; i < words.size(); ++i) {
    write_u16_le(bytes.data() + i * 2, words[i]);
  }
  return bytes;
}

uint32_t ref_relu_bits(uint32_t bits) noexcept {
  const uint32_t abs_bits = bits & 0x7fffffffu;
  if (abs_bits > 0x7f800000u) {
    return bits;
  }
  if ((bits & 0x80000000u) != 0 || abs_bits == 0) {
    return 0u;
  }
  return bits;
}

uint16_t ref_f32_to_fp16(uint32_t bits) noexcept {
  const uint32_t sign = (bits >> 16) & 0x8000u;
  const uint32_t exp = (bits >> 23) & 0xffu;
  const uint32_t frac = bits & 0x7fffffu;

  if (exp == 0xffu) {
    if (frac == 0) {
      return static_cast<uint16_t>(sign | 0x7c00u);
    }
    const uint32_t nan_frac = (frac >> 13) | 0x0200u;
    return static_cast<uint16_t>(sign | 0x7c00u | nan_frac);
  }
  const int32_t unbiased = static_cast<int32_t>(exp) - 127;
  if (unbiased > 15) {
    return static_cast<uint16_t>(sign | 0x7c00u);
  }
  if (unbiased < -25) {
    return static_cast<uint16_t>(sign);
  }
  if (unbiased < -14) {
    const uint32_t sig = 0x800000u | frac;
    const uint32_t shift = static_cast<uint32_t>(-14 - unbiased) + 13u;
    const uint32_t half_frac = sig >> shift;
    const uint32_t rem = sig & ((1u << shift) - 1u);
    const uint32_t mid = 1u << (shift - 1u);
    const uint32_t round_up = (rem > mid || (rem == mid && (half_frac & 1u) != 0)) ? 1u : 0u;
    return static_cast<uint16_t>(sign | (half_frac + round_up));
  }
  const uint32_t half_exp = static_cast<uint32_t>(unbiased + 15);
  const uint32_t half_frac = frac >> 13;
  const uint32_t rem = frac & 0x1fffu;
  const uint32_t round_up = (rem > 0x1000u || (rem == 0x1000u && (half_frac & 1u) != 0)) ? 1u : 0u;
  uint32_t out = sign | (half_exp << 10) | half_frac;
  out += round_up;
  return static_cast<uint16_t>(out);
}

uint32_t ref_fp16_to_f32(uint16_t h) noexcept {
  const uint32_t sign = (static_cast<uint32_t>(h) & 0x8000u) << 16;
  const uint32_t exp = (static_cast<uint32_t>(h) >> 10) & 0x1fu;
  uint32_t frac = static_cast<uint32_t>(h) & 0x03ffu;
  if (exp == 0) {
    if (frac == 0) {
      return sign;
    }
    int32_t shift = -1;
    while ((frac & 0x0400u) == 0) {
      frac <<= 1;
      ++shift;
    }
    frac &= 0x03ffu;
    const uint32_t f32_exp = static_cast<uint32_t>(127 - 15 - shift);
    return sign | (f32_exp << 23) | (frac << 13);
  }
  if (exp == 0x1fu) {
    if (frac == 0) {
      return sign | 0x7f800000u;
    }
    return sign | 0x7fc00000u | (frac << 13);
  }
  const uint32_t f32_exp = exp + (127u - 15u);
  return sign | (f32_exp << 23) | (frac << 13);
}

uint16_t ref_f32_to_bf16(uint32_t bits) noexcept {
  const uint32_t abs_bits = bits & 0x7fffffffu;
  if (abs_bits > 0x7f800000u) {
    return static_cast<uint16_t>((bits >> 16) | 0x0040u);
  }
  const uint32_t lsb = (bits >> 16) & 1u;
  const uint32_t rounding_bias = 0x7fffu + lsb;
  return static_cast<uint16_t>((bits + rounding_bias) >> 16);
}

uint32_t ref_bf16_to_f32(uint16_t b) noexcept {
  const uint32_t abs_bits = static_cast<uint32_t>(b) & 0x7fffu;
  if (abs_bits > 0x7f80u) {
    return (static_cast<uint32_t>(b) << 16) | 0x00400000u;
  }
  return static_cast<uint32_t>(b) << 16;
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
    if (device) {
      vx_device_release(device);
      device = nullptr;
    }
  }
};

struct BufferHandle {
  vx_buffer_h h = nullptr;

  BufferHandle() = default;
  BufferHandle(const BufferHandle&) = delete;
  BufferHandle& operator=(const BufferHandle&) = delete;

  ~BufferHandle() {
    release();
  }

  void release() noexcept {
    if (h) {
      vx_buffer_release(h);
      h = nullptr;
    }
  }
};

#define VX_CHECK(expr)                                                          \
  do {                                                                          \
    vx_result_t _rc = (expr);                                                   \
    if (_rc != VX_SUCCESS) {                                                    \
      std::cerr << "FAILED " << #expr << ": " << vx_result_string(_rc) << '\n'; \
      return false;                                                             \
    }                                                                           \
  } while (0)

bool check_device_profile(vx_device_h device) {
  uint64_t isa = 0;
  uint64_t threads = 0, warps = 0, cores = 0, clusters = 0, issue_width = 0;
  if (vx_device_query(device, VX_CAPS_ISA_FLAGS, &isa) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_THREADS, &threads) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_WARPS, &warps) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CORES, &cores) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CLUSTERS, &clusters) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_ISSUE_WIDTH, &issue_width) != VX_SUCCESS) {
    std::cerr << "FAILED device capability query\n";
    return false;
  }
  if (VX_ISA_ARCH(isa) != 64 || threads == 0 || warps == 0 || cores == 0 || clusters == 0) {
    std::cerr << "FAILED device capabilities do not match RV64 execution profile\n";
    return false;
  }
  return true;
}

enum class CheckMode {
  BitExact32,
  BitExact16,
  MaxAbsErrF32,
};

struct OperatorCase {
  std::string name;
  uint32_t op_code = 0;
  uint32_t rows = 0;
  uint32_t cols = 0;
  uint32_t eps_bits = 0x3727c5acU;
  uint32_t block_x = 16;
  uint32_t grid_x = 1;
  CheckMode check_mode = CheckMode::BitExact32;
  double max_abs_tol = 0.0;
  std::vector<uint8_t> src0_bytes;
  std::vector<uint8_t> src1_bytes;
  std::vector<uint8_t> src2_bytes;
  std::vector<uint32_t> expected_u32;
  std::vector<uint16_t> expected_u16;
  std::vector<double> expected_f64;
};

std::vector<OperatorCase> build_cases() {
  std::vector<OperatorCase> cases;

  // 1. relu_fp32: positives, negatives, +0.0f, -0.0f, subnormals, cancellation, large values
  {
    OperatorCase c;
    c.name = "relu_fp32";
    c.op_code = va::kOpsV2OpReluFp32;
    c.rows = 4;
    c.cols = 8;
    c.check_mode = CheckMode::BitExact32;
    std::vector<uint32_t> in_words = {
        0x00000000u, 0x80000000u, 0x3f800000u, 0xbf800000u,
        0x00000001u, 0x80000001u, 0x42c80000u, 0xc2c80000u,
        0x3e800000u, 0xbe800000u, 0x00800000u, 0x80800000u,
        0x7f7fffffu, 0xff7fffffu, 0x7f800000u, 0xff800000u,
        0x7fc00000u, 0x358637bdu, 0xb58637bdu, 0x40490fdbu,
        0xc0490fdbu, 0x00400000u, 0x80400000u, 0x41200000u,
        0xc1200000u, 0x3f000000u, 0xbf000000u, 0x80000000u,
        0x3dcccccdu, 0xbdcccccdu, 0x447a0000u, 0xc47a0000u,
    };
    c.src0_bytes = pack_f32_words(in_words);
    c.expected_u32.resize(in_words.size());
    for (size_t i = 0; i < in_words.size(); ++i) {
      c.expected_u32[i] = ref_relu_bits(in_words[i]);
    }
    cases.push_back(std::move(c));
  }

  // 2. gelu_fp32: tanh approximation across [-12, +12], zero, -0.0f, small values
  {
    OperatorCase c;
    c.name = "gelu_fp32";
    c.op_code = va::kOpsV2OpGeluFp32;
    c.rows = 4;
    c.cols = 8;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    std::vector<float> vals = {
        0.0f, -0.0f, 1.0f, -1.0f, 0.5f, -0.5f, 2.0f, -2.0f,
        3.0f, -3.0f, 5.0f, -5.0f, 12.0f, -12.0f, 0.125f, -0.125f,
        0.01f, -0.01f, 1e-4f, -1e-4f, 0.25f, -0.25f, 0.75f, -0.75f,
        1.5f, -1.5f, 2.5f, -2.5f, 4.0f, -4.0f, 8.0f, -8.0f,
    };
    c.src0_bytes = pack_f32_floats(vals);
    c.expected_f64.resize(vals.size());
    const double kSqrt2OverPi = std::sqrt(2.0 / 3.14159265358979323846);
    for (size_t i = 0; i < vals.size(); ++i) {
      const double x = static_cast<double>(vals[i]);
      const double u = kSqrt2OverPi * (x + 0.044715 * x * x * x);
      c.expected_f64[i] = 0.5 * x * (1.0 + std::tanh(u));
    }
    cases.push_back(std::move(c));
  }

  // 3a. cast_fp32_to_fp16: RNE ties, -0.0f, subnormal -25 boundary, overflow, NaN/Inf
  {
    OperatorCase c;
    c.name = "cast_fp32_to_fp16";
    c.op_code = va::kOpsV2OpCastFp32ToFp16;
    c.rows = 4;
    c.cols = 8;
    c.check_mode = CheckMode::BitExact16;
    std::vector<uint32_t> in_words = {
        0x00000000u, 0x80000000u, 0x3f800000u, 0xbf800000u,
        0x3f802000u, 0x3f801000u, 0x3f803000u, 0x3f801001u,
        0x38800000u, 0x387fe000u, 0x33800000u, 0x33000000u,
        0x33000001u, 0x32ffffffu, 0xb3000001u, 0xb2ffffffu,
        0x477fe000u, 0x477ff000u, 0x47800000u, 0xc7800000u,
        0x7f800000u, 0xff800000u, 0x7fc00000u, 0x7fa00001u,
        0x40490fdbu, 0xc0490fdbu, 0x3c000000u, 0xbc000000u,
        0x00000001u, 0x80000001u, 0x42800000u, 0xc2800000u,
    };
    c.src0_bytes = pack_f32_words(in_words);
    c.expected_u16.resize(in_words.size());
    for (size_t i = 0; i < in_words.size(); ++i) {
      c.expected_u16[i] = ref_f32_to_fp16(in_words[i]);
    }
    cases.push_back(std::move(c));
  }

  // 3b. cast_fp16_to_fp32: zeros, signed subnormals, normals, Inf, NaN
  {
    OperatorCase c;
    c.name = "cast_fp16_to_fp32";
    c.op_code = va::kOpsV2OpCastFp16ToFp32;
    c.rows = 2;
    c.cols = 8;
    c.check_mode = CheckMode::BitExact32;
    std::vector<uint16_t> in_words = {
        0x0000u, 0x8000u, 0x0001u, 0x8001u,
        0x03ffu, 0x83ffu, 0x0400u, 0x8400u,
        0x3c00u, 0xbc00u, 0x7bffu, 0xfbffu,
        0x7c00u, 0xfc00u, 0x7e00u, 0x7c01u,
    };
    c.src0_bytes = pack_u16_words(in_words);
    c.expected_u32.resize(in_words.size());
    for (size_t i = 0; i < in_words.size(); ++i) {
      c.expected_u32[i] = ref_fp16_to_f32(in_words[i]);
    }
    cases.push_back(std::move(c));
  }

  // 3c. cast_fp32_to_bf16: RNE ties, signed zeros, subnormals, overflow, NaN/Inf
  {
    OperatorCase c;
    c.name = "cast_fp32_to_bf16";
    c.op_code = va::kOpsV2OpCastFp32ToBf16;
    c.rows = 2;
    c.cols = 8;
    c.check_mode = CheckMode::BitExact16;
    std::vector<uint32_t> in_words = {
        0x00000000u, 0x80000000u, 0x3f800000u, 0xbf800000u,
        0x3f808000u, 0x3f818000u, 0x3f807fffu, 0x3f808001u,
        0x00000001u, 0x80000001u, 0x7f7fffffu, 0xff7fffffu,
        0x7f800000u, 0xff800000u, 0x7fc00000u, 0x7f800001u,
    };
    c.src0_bytes = pack_f32_words(in_words);
    c.expected_u16.resize(in_words.size());
    for (size_t i = 0; i < in_words.size(); ++i) {
      c.expected_u16[i] = ref_f32_to_bf16(in_words[i]);
    }
    cases.push_back(std::move(c));
  }

  // 3d. cast_bf16_to_fp32: signed zeros, subnormals, normals, Inf, NaN
  {
    OperatorCase c;
    c.name = "cast_bf16_to_fp32";
    c.op_code = va::kOpsV2OpCastBf16ToFp32;
    c.rows = 2;
    c.cols = 8;
    c.check_mode = CheckMode::BitExact32;
    std::vector<uint16_t> in_words = {
        0x0000u, 0x8000u, 0x0001u, 0x8001u,
        0x0080u, 0x8080u, 0x3f80u, 0xbf80u,
        0x4049u, 0xc049u, 0x7f7fu, 0xff7fu,
        0x7f80u, 0xff80u, 0x7fc0u, 0x7f81u,
    };
    c.src0_bytes = pack_u16_words(in_words);
    c.expected_u32.resize(in_words.size());
    for (size_t i = 0; i < in_words.size(); ++i) {
      c.expected_u32[i] = ref_bf16_to_f32(in_words[i]);
    }
    cases.push_back(std::move(c));
  }

  // 4. softmax_fp32: all-zeros, negative/large shift stability, mixed signs, constant row
  {
    OperatorCase c;
    c.name = "softmax_fp32";
    c.op_code = va::kOpsV2OpSoftmaxFp32;
    c.rows = 4;
    c.cols = 8;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    std::vector<float> vals = {
        // Row 0: zeros and -0.0f
        0.0f, -0.0f, 0.0f, 0.0f, 0.0f, -0.0f, 0.0f, 0.0f,
        // Row 1: large positive shift (tests max subtraction stability)
        100.0f, 101.0f, 99.0f, 102.0f, 98.0f, 100.5f, 97.0f, 101.5f,
        // Row 2: large negative values
        -50.0f, -49.0f, -51.0f, -48.5f, -52.0f, -50.5f, -49.5f, -48.0f,
        // Row 3: mixed signs & cancellation spread
        -2.5f, -1.0f, 0.0f, 0.5f, 1.25f, -0.75f, 2.0f, -3.0f,
    };
    c.src0_bytes = pack_f32_floats(vals);
    c.expected_f64.resize(vals.size());
    for (uint32_t r = 0; r < c.rows; ++r) {
      double m = static_cast<double>(vals[r * c.cols]);
      for (uint32_t col = 1; col < c.cols; ++col) {
        m = std::max(m, static_cast<double>(vals[r * c.cols + col]));
      }
      double sum = 0.0;
      for (uint32_t col = 0; col < c.cols; ++col) {
        const double e = std::exp(static_cast<double>(vals[r * c.cols + col]) - m);
        c.expected_f64[r * c.cols + col] = e;
        sum += e;
      }
      for (uint32_t col = 0; col < c.cols; ++col) {
        c.expected_f64[r * c.cols + col] /= sum;
      }
    }
    cases.push_back(std::move(c));
  }

  // 5. rmsnorm_fp32: zero row (tests +eps stability), mixed signs, scaled weights
  {
    OperatorCase c;
    c.name = "rmsnorm_fp32";
    c.op_code = va::kOpsV2OpRmsNormFp32;
    c.rows = 4;
    c.cols = 8;
    c.eps_bits = float_to_bits(1e-5f);
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    std::vector<float> vals = {
        0.0f, -0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
        1.0f, -1.0f, 2.0f, -2.0f, 0.5f, -0.5f, 1.5f, -1.5f,
        -3.0f, -1.0f, 0.25f, 4.0f, -0.75f, 2.5f, -1.25f, 0.5f,
        10.0f, 10.0f, 10.0f, 10.0f, -10.0f, -10.0f, -10.0f, -10.0f,
    };
    std::vector<float> weights = {1.0f, 0.5f, -1.25f, 2.0f, 0.75f, -0.5f, 1.5f, 1.0f};
    c.src0_bytes = pack_f32_floats(vals);
    c.src1_bytes = pack_f32_floats(weights);
    c.expected_f64.resize(vals.size());
    const double eps = static_cast<double>(bits_to_float(c.eps_bits));
    for (uint32_t r = 0; r < c.rows; ++r) {
      double sq = 0.0;
      for (uint32_t col = 0; col < c.cols; ++col) {
        const double v = static_cast<double>(vals[r * c.cols + col]);
        sq += v * v;
      }
      const double inv_rms = 1.0 / std::sqrt(sq / static_cast<double>(c.cols) + eps);
      for (uint32_t col = 0; col < c.cols; ++col) {
        c.expected_f64[r * c.cols + col] =
            static_cast<double>(vals[r * c.cols + col]) * inv_rms * static_cast<double>(weights[col]);
      }
    }
    cases.push_back(std::move(c));
  }

  // 6. layernorm_fp32: constant row (var=0 -> beta), symmetric zero-mean, shifted mean
  {
    OperatorCase c;
    c.name = "layernorm_fp32";
    c.op_code = va::kOpsV2OpLayerNormFp32;
    c.rows = 4;
    c.cols = 8;
    c.eps_bits = float_to_bits(1e-5f);
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    std::vector<float> vals = {
        3.5f, 3.5f, 3.5f, 3.5f, 3.5f, 3.5f, 3.5f, 3.5f,
        -1.0f, 1.0f, -2.0f, 2.0f, -0.5f, 0.5f, -1.5f, 1.5f,
        10.0f, 11.0f, 12.0f, 13.0f, 9.0f, 8.0f, 10.5f, 11.5f,
        -4.0f, -2.5f, 0.0f, 1.25f, 2.5f, -1.75f, 3.0f, -0.5f,
    };
    std::vector<float> gamma = {1.0f, 1.5f, -0.5f, 2.0f, 0.75f, 1.25f, -1.0f, 0.5f};
    std::vector<float> beta = {0.1f, -0.2f, 0.3f, 0.0f, -0.5f, 0.25f, 0.75f, -0.125f};
    c.src0_bytes = pack_f32_floats(vals);
    c.src1_bytes = pack_f32_floats(gamma);
    c.src2_bytes = pack_f32_floats(beta);
    c.expected_f64.resize(vals.size());
    const double eps = static_cast<double>(bits_to_float(c.eps_bits));
    for (uint32_t r = 0; r < c.rows; ++r) {
      double sum = 0.0;
      for (uint32_t col = 0; col < c.cols; ++col) {
        sum += static_cast<double>(vals[r * c.cols + col]);
      }
      const double mean = sum / static_cast<double>(c.cols);
      double var = 0.0;
      for (uint32_t col = 0; col < c.cols; ++col) {
        const double d = static_cast<double>(vals[r * c.cols + col]) - mean;
        var += d * d;
      }
      const double inv_std = 1.0 / std::sqrt(var / static_cast<double>(c.cols) + eps);
      for (uint32_t col = 0; col < c.cols; ++col) {
        c.expected_f64[r * c.cols + col] =
            (static_cast<double>(vals[r * c.cols + col]) - mean) * inv_std
                * static_cast<double>(gamma[col])
            + static_cast<double>(beta[col]);
      }
    }
    cases.push_back(std::move(c));
  }

  // 7. attention_fp32: scaled dot-product attention [seq_len=8, d_k=16]
  {
    OperatorCase c;
    c.name = "attention_fp32";
    c.op_code = va::kOpsV2OpAttentionFp32;
    c.rows = 8;
    c.cols = 16;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    const uint32_t seq_len = c.rows;
    const uint32_t d_k = c.cols;
    std::vector<float> q(seq_len * d_k);
    std::vector<float> k(seq_len * d_k);
    std::vector<float> v(seq_len * d_k);
    for (uint32_t i = 0; i < seq_len; ++i) {
      for (uint32_t d = 0; d < d_k; ++d) {
        const int32_t s0 = static_cast<int32_t>((i * 7 + d * 3) % 11) - 5;
        const int32_t s1 = static_cast<int32_t>((i * 5 + d * 11) % 13) - 6;
        const int32_t s2 = static_cast<int32_t>((i * 3 + d * 5) % 9) - 4;
        q[i * d_k + d] = static_cast<float>(s0) * 0.25f;
        k[i * d_k + d] = static_cast<float>(s1) * 0.25f;
        v[i * d_k + d] = static_cast<float>(s2) * 0.5f;
      }
    }
    // Force row 0 cancellation and negative-zero inputs.
    for (uint32_t d = 0; d < d_k; ++d) {
      q[d] = (d % 2 == 0) ? 0.5f : -0.5f;
      k[d] = 1.0f;
    }
    q[1 * d_k + 0] = -0.0f;

    c.src0_bytes = pack_f32_floats(q);
    c.src1_bytes = pack_f32_floats(k);
    c.src2_bytes = pack_f32_floats(v);
    c.expected_f64.resize(seq_len * d_k);

    const double scale = 1.0 / std::sqrt(static_cast<double>(d_k));
    std::vector<double> scores(seq_len);
    for (uint32_t i = 0; i < seq_len; ++i) {
      double max_s = 0.0;
      for (uint32_t j = 0; j < seq_len; ++j) {
        double dot = 0.0;
        for (uint32_t d = 0; d < d_k; ++d) {
          dot += static_cast<double>(q[i * d_k + d]) * static_cast<double>(k[j * d_k + d]);
        }
        scores[j] = dot * scale;
        if (j == 0 || scores[j] > max_s) {
          max_s = scores[j];
        }
      }
      double exp_sum = 0.0;
      for (uint32_t j = 0; j < seq_len; ++j) {
        scores[j] = std::exp(scores[j] - max_s);
        exp_sum += scores[j];
      }
      for (uint32_t j = 0; j < seq_len; ++j) {
        scores[j] /= exp_sum;
      }
      for (uint32_t d = 0; d < d_k; ++d) {
        double acc = 0.0;
        for (uint32_t j = 0; j < seq_len; ++j) {
          acc += scores[j] * static_cast<double>(v[j * d_k + d]);
        }
        c.expected_f64[i * d_k + d] = acc;
      }
    }
    cases.push_back(std::move(c));
  }

  return cases;
}

bool run_case(const DeviceSession& session, const OperatorCase& op_case,
              uint32_t iterations, uint32_t* total_mismatches) {
  const uint64_t count = uint64_t{op_case.rows} * uint64_t{op_case.cols};
  const uint64_t dst_bytes_size =
      (op_case.check_mode == CheckMode::BitExact16) ? (count * 2) : (count * 4);

  BufferHandle src0_buf;
  BufferHandle src1_buf;
  BufferHandle src2_buf;
  BufferHandle dst_buf;

  VX_CHECK(vx_buffer_create(session.device, op_case.src0_bytes.size(), VX_MEM_READ, &src0_buf.h));
  if (!op_case.src1_bytes.empty()) {
    VX_CHECK(vx_buffer_create(session.device, op_case.src1_bytes.size(), VX_MEM_READ, &src1_buf.h));
  }
  if (!op_case.src2_bytes.empty()) {
    VX_CHECK(vx_buffer_create(session.device, op_case.src2_bytes.size(), VX_MEM_READ, &src2_buf.h));
  }
  VX_CHECK(vx_buffer_create(session.device, dst_bytes_size, VX_MEM_READ_WRITE, &dst_buf.h));

  va::OpsV2Arguments arg{};
  arg.op_code = op_case.op_code;
  arg.flags = 0;
  arg.rows = op_case.rows;
  arg.cols = op_case.cols;
  arg.eps_bits = op_case.eps_bits;
  VX_CHECK(vx_buffer_address(src0_buf.h, &arg.src0_addr));
  if (src1_buf.h) {
    VX_CHECK(vx_buffer_address(src1_buf.h, &arg.src1_addr));
  }
  if (src2_buf.h) {
    VX_CHECK(vx_buffer_address(src2_buf.h, &arg.src2_addr));
  }
  VX_CHECK(vx_buffer_address(dst_buf.h, &arg.dst_addr));

  std::vector<uint8_t> poison_dst(dst_bytes_size);
  std::vector<uint8_t> dst_bytes(dst_bytes_size);

  for (uint32_t iter = 0; iter < iterations; ++iter) {
    const uint8_t poison_byte = (iter & 1u) == 0 ? 0xa5u : 0x5au;
    std::fill(poison_dst.begin(), poison_dst.end(), poison_byte);
    std::fill(dst_bytes.begin(), dst_bytes.end(), static_cast<uint8_t>(0x3cu));

    EventHandle ev_w0;
    EventHandle ev_w1;
    EventHandle ev_w2;
    EventHandle ev_poison;
    EventHandle ev_launch;
    EventHandle ev_read;

    VX_CHECK(vx_enqueue_write(session.queue, src0_buf.h, 0, op_case.src0_bytes.data(),
                              op_case.src0_bytes.size(), 0, nullptr, &ev_w0.h));
    vx_event_h dep = ev_w0.h;
    if (src1_buf.h) {
      VX_CHECK(vx_enqueue_write(session.queue, src1_buf.h, 0, op_case.src1_bytes.data(),
                                op_case.src1_bytes.size(), 1, &dep, &ev_w1.h));
      dep = ev_w1.h;
    }
    if (src2_buf.h) {
      VX_CHECK(vx_enqueue_write(session.queue, src2_buf.h, 0, op_case.src2_bytes.data(),
                                op_case.src2_bytes.size(), 1, &dep, &ev_w2.h));
      dep = ev_w2.h;
    }
    VX_CHECK(vx_enqueue_write(session.queue, dst_buf.h, 0, poison_dst.data(),
                              poison_dst.size(), 1, &dep, &ev_poison.h));

    vx_launch_info_t li{};
    li.struct_size = sizeof(li);
    li.kernel = session.kernel;
    li.args_host = &arg;
    li.args_size = sizeof(arg);
    li.ndim = 1;
    li.grid_dim[0] = op_case.grid_x;
    li.grid_dim[1] = 1;
    li.grid_dim[2] = 1;
    li.block_dim[0] = op_case.block_x;
    li.block_dim[1] = 1;
    li.block_dim[2] = 1;
    li.lmem_size = 0;
    li.cluster_dim[0] = 1;
    li.cluster_dim[1] = 1;
    li.cluster_dim[2] = 1;

    VX_CHECK(vx_enqueue_launch(session.queue, &li, 1, &ev_poison.h, &ev_launch.h));
    VX_CHECK(vx_enqueue_read(session.queue, dst_bytes.data(), dst_buf.h, 0,
                             dst_bytes.size(), 1, &ev_launch.h, &ev_read.h));
    VX_CHECK(vx_event_wait_value(ev_read.h, 1, VX_TIMEOUT_INFINITE));

    ev_w0.release();
    ev_w1.release();
    ev_w2.release();
    ev_poison.release();
    ev_launch.release();
    ev_read.release();

    uint32_t case_mismatches = 0;
    double observed_max_abs_err = 0.0;

    if (op_case.check_mode == CheckMode::BitExact32) {
      for (size_t i = 0; i < count; ++i) {
        const uint32_t actual = read_u32_le(dst_bytes.data() + i * 4);
        const uint32_t expected = op_case.expected_u32[i];
        if (actual != expected) {
          if (*total_mismatches + case_mismatches < kMaxPrintedErrors) {
            std::printf("*** mismatch [%s iter=%u idx=%zu] expected=0x%08x actual=0x%08x\n",
                        op_case.name.c_str(), iter, i, expected, actual);
          }
          ++case_mismatches;
        }
      }
    } else if (op_case.check_mode == CheckMode::BitExact16) {
      for (size_t i = 0; i < count; ++i) {
        const uint16_t actual = read_u16_le(dst_bytes.data() + i * 2);
        const uint16_t expected = op_case.expected_u16[i];
        if (actual != expected) {
          if (*total_mismatches + case_mismatches < kMaxPrintedErrors) {
            std::printf("*** mismatch [%s iter=%u idx=%zu] expected=0x%04x actual=0x%04x\n",
                        op_case.name.c_str(), iter, i, expected, actual);
          }
          ++case_mismatches;
        }
      }
    } else {
      for (size_t i = 0; i < count; ++i) {
        const uint32_t actual_bits = read_u32_le(dst_bytes.data() + i * 4);
        const float actual_f32 = bits_to_float(actual_bits);
        const double expected = op_case.expected_f64[i];
        const double err = std::fabs(static_cast<double>(actual_f32) - expected);
        if (!std::isfinite(actual_f32) || err > observed_max_abs_err) {
          if (!std::isfinite(actual_f32)) {
            observed_max_abs_err = INFINITY;
          } else {
            observed_max_abs_err = err;
          }
        }
        if (!std::isfinite(actual_f32) || err > op_case.max_abs_tol) {
          if (*total_mismatches + case_mismatches < kMaxPrintedErrors) {
            std::printf("*** mismatch [%s iter=%u idx=%zu] expected=%.8g actual=%.8g err=%.3e\n",
                        op_case.name.c_str(), iter, i, expected,
                        static_cast<double>(actual_f32), err);
          }
          ++case_mismatches;
        }
      }
    }

    *total_mismatches += case_mismatches;
    std::printf("OP_V2_CASE name=%s op_code=%u iter=%u rows=%u cols=%u count=%llu "
                "max_abs_err=%.6e tol=%.6e mismatches=%u\n",
                op_case.name.c_str(), op_case.op_code, iter, op_case.rows, op_case.cols,
                static_cast<unsigned long long>(count),
                observed_max_abs_err, op_case.max_abs_tol, case_mismatches);
  }

  return true;
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

  const std::vector<OperatorCase> all_cases = build_cases();
  std::vector<const OperatorCase*> selected;
  for (const auto& c : all_cases) {
    if (opts.op_filter.empty() || opts.op_filter == c.name) {
      selected.push_back(&c);
    }
  }
  if (selected.empty()) {
    std::cerr << "FAILED no matching operator case for '" << opts.op_filter << "'\n";
    return 2;
  }

  DeviceSession session;
  if (vx_device_open(0, &session.device) != VX_SUCCESS) {
    std::cerr << "FAILED vx_device_open\n";
    return 1;
  }
  if (!check_device_profile(session.device)) {
    return 1;
  }

  vx_queue_info_t qi{};
  qi.struct_size = sizeof(qi);
  qi.priority = VX_QUEUE_PRIORITY_NORMAL;
  qi.flags = VX_QUEUE_PROFILING_ENABLE;
  if (vx_queue_create(session.device, &qi, &session.queue) != VX_SUCCESS) {
    std::cerr << "FAILED vx_queue_create\n";
    return 1;
  }
  if (vx_module_load_file(session.device, opts.kernel_path, &session.module) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_load_file\n";
    return 1;
  }
  if (vx_module_get_kernel(session.module, "main", &session.kernel) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_get_kernel\n";
    return 1;
  }

  uint32_t total_mismatches = 0;
  uint64_t total_elements = 0;
  for (const OperatorCase* c : selected) {
    if (!run_case(session, *c, opts.iterations, &total_mismatches)) {
      return 1;
    }
    total_elements += uint64_t{c->rows} * uint64_t{c->cols} * opts.iterations;
  }

  std::printf("OP_V2_SUMMARY cases=%zu iterations=%u total_elements=%llu total_mismatches=%u\n",
              selected.size(), opts.iterations,
              static_cast<unsigned long long>(total_elements), total_mismatches);

  vx_device_dump_perf(session.device, stdout);
  session.release();

  if (total_mismatches != 0) {
    std::cout << "FAILED!\n";
    return 1;
  }
  std::cout << "PASSED!\n";
  return 0;
}
