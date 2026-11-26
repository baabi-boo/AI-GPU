// SPDX-License-Identifier: Apache-2.0

#include <ai_matmul_args.h>
#include <ai_ops_v2_args.h>
#include <vortex2.h>

#include <algorithm>
#include <array>
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

constexpr uint32_t kSeqLen = 8;
constexpr uint32_t kDModel = 16;
constexpr uint32_t kNHeads = 2;
constexpr uint32_t kDHead = 8;
constexpr uint32_t kDFf = 16;
constexpr uint32_t kTileN = 4;
constexpr uint32_t kTilesPerProj = kDModel / kTileN; // 4 tiles of (8, 4, 16)
constexpr uint32_t kHalfCols = 8;
constexpr uint32_t kTilesPerHalf = kHalfCols / kTileN; // 2 tiles of (8, 4, 16)
constexpr uint32_t kRmsEpsBits = 0x3727c5acU; // 1e-5f
constexpr uint32_t kOpsBlockX = 16;
constexpr uint32_t kMatmulBlockX = 4;
constexpr uint32_t kDefaultIterations = 1;
constexpr uint32_t kMaxPrintedErrors = 32;
constexpr double kMaxAbsTolerance = 5e-4;

struct Options {
  std::string ops_kernel_path = "kernel.vxbin";
  std::string matmul_kernel_path;
  uint32_t iterations = kDefaultIterations;
  bool show_help = false;
};

void show_usage(const char* argv0) {
  std::cout << "Usage: " << argv0
            << " [-k kernel.vxbin] [-m matmul.vxbin] [-n iterations] [-h]\n"
            << "  -k path   Path to ops_v2 kernel.vxbin (default: kernel.vxbin)\n"
            << "  -m path   Path to matmul.vxbin (default: sibling matmul.vxbin)\n"
            << "  -n count  Repetitions (default: 1)\n"
            << "  -h        Show this help\n";
}

std::string default_matmul_path(const std::string& ops_path) {
  const size_t slash = ops_path.find_last_of('/');
  if (slash == std::string::npos) {
    return "matmul.vxbin";
  }
  return ops_path.substr(0, slash + 1) + "matmul.vxbin";
}

bool parse_args(int argc, char** argv, Options* out) {
  int opt;
  opterr = 0;
  while ((opt = getopt(argc, argv, "k:m:n:h")) != -1) {
    switch (opt) {
      case 'k': {
        out->ops_kernel_path = optarg;
        break;
      }
      case 'm': {
        out->matmul_kernel_path = optarg;
        break;
      }
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
      case 'h': {
        out->show_help = true;
        return true;
      }
      default: {
        return false;
      }
    }
  }
  if (out->matmul_kernel_path.empty()) {
    out->matmul_kernel_path = default_matmul_path(out->ops_kernel_path);
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

uint16_t f32_bits_to_fp16(uint32_t bits) noexcept {
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

uint32_t fp16_bits_to_f32_bits(uint16_t h) noexcept {
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

float quantize_fp16_as_f32(float v) noexcept {
  const uint16_t h = f32_bits_to_fp16(float_to_bits(v));
  return bits_to_float(fp16_bits_to_f32_bits(h));
}

uint64_t splitmix64_next(uint64_t* state) noexcept {
  *state += 0x9E3779B97F4A7C15ULL;
  uint64_t z = *state;
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}

std::vector<float> generate_stream(uint64_t seed, size_t count, double scale,
                                   double offset, bool quantize_fp16) {
  std::vector<float> out(count);
  uint64_t state = seed;
  for (size_t i = 0; i < count; ++i) {
    const uint64_t z = splitmix64_next(&state);
    const double u = std::ldexp(static_cast<double>(z >> 40), -24) * 2.0 - 1.0;
    const float raw = static_cast<float>(offset + u * scale);
    out[i] = quantize_fp16 ? quantize_fp16_as_f32(raw) : raw;
  }
  return out;
}

std::vector<uint8_t> pack_f32_bytes(const std::vector<float>& vals) {
  std::vector<uint8_t> bytes(vals.size() * 4);
  for (size_t i = 0; i < vals.size(); ++i) {
    write_u32_le(bytes.data() + i * 4, float_to_bits(vals[i]));
  }
  return bytes;
}

// Pack columns [col_begin, col_begin + kTileN) of a [rows, total_cols] matrix
// into column-major FP16 bytes for matmul(M=8, N=4, K=16).
std::vector<uint8_t> pack_weight_tile_col_major_fp16(const std::vector<float>& w,
                                                     uint32_t rows,
                                                     uint32_t total_cols,
                                                     uint32_t col_begin) {
  std::vector<uint8_t> bytes(size_t{rows} * kTileN * 2);
  for (uint32_t c = 0; c < kTileN; ++c) {
    for (uint32_t r = 0; r < rows; ++r) {
      const float val = w[r * total_cols + (col_begin + c)];
      const uint16_t h = f32_bits_to_fp16(float_to_bits(val));
      write_u16_le(bytes.data() + (c * rows + r) * 2, h);
    }
  }
  return bytes;
}

// Pack one (16, 4) column-major FP16 tile of [I_8; I_8] for residual addition.
std::vector<uint8_t> pack_identity_add_tile_fp16(uint32_t col_begin) {
  std::vector<uint8_t> bytes(size_t{kDModel} * kTileN * 2, 0);
  for (uint32_t c = 0; c < kTileN; ++c) {
    const uint32_t gcol = col_begin + c;
    write_u16_le(bytes.data() + (c * kDModel + gcol) * 2, 0x3c00u);
    write_u16_le(bytes.data() + (c * kDModel + kHalfCols + gcol) * 2, 0x3c00u);
  }
  return bytes;
}

void ref_rmsnorm_f64(const double* x, const float* weight, uint32_t rows,
                     uint32_t cols, double eps, double* out) {
  for (uint32_t r = 0; r < rows; ++r) {
    double sq = 0.0;
    for (uint32_t c = 0; c < cols; ++c) {
      const double v = x[r * cols + c];
      sq += v * v;
    }
    const double inv_rms = 1.0 / std::sqrt(sq / static_cast<double>(cols) + eps);
    for (uint32_t c = 0; c < cols; ++c) {
      out[r * cols + c] = x[r * cols + c] * inv_rms * static_cast<double>(weight[c]);
    }
  }
}

void ref_matmul_f64(const double* a, const float* b, uint32_t m, uint32_t n,
                    uint32_t k, double* out) {
  for (uint32_t i = 0; i < m; ++i) {
    for (uint32_t j = 0; j < n; ++j) {
      double acc = 0.0;
      for (uint32_t l = 0; l < k; ++l) {
        acc += a[i * k + l] * static_cast<double>(b[l * n + j]);
      }
      out[i * n + j] = acc;
    }
  }
}

void ref_attention_f64(const double* q, const double* k, const double* v,
                       uint32_t seq_len, uint32_t d_head, uint32_t total_cols,
                       uint32_t col_offset, double* out) {
  const double scale = 1.0 / std::sqrt(static_cast<double>(d_head));
  std::vector<double> scores(seq_len);
  for (uint32_t i = 0; i < seq_len; ++i) {
    double max_s = 0.0;
    for (uint32_t j = 0; j < seq_len; ++j) {
      double dot = 0.0;
      for (uint32_t d = 0; d < d_head; ++d) {
        dot += q[i * total_cols + col_offset + d] * k[j * total_cols + col_offset + d];
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
    for (uint32_t d = 0; d < d_head; ++d) {
      double acc = 0.0;
      for (uint32_t j = 0; j < seq_len; ++j) {
        acc += scores[j] * v[j * total_cols + col_offset + d];
      }
      out[i * total_cols + col_offset + d] = acc;
    }
  }
}

struct TransformerWeights {
  std::vector<float> x;
  std::vector<float> rms1_w;
  std::vector<float> wq;
  std::vector<float> wk;
  std::vector<float> wv;
  std::vector<float> wo;
  std::vector<float> rms2_w;
  std::vector<float> w1;
  std::vector<float> w2;
  std::vector<double> expected_y;
};

TransformerWeights build_workload() {
  TransformerWeights w;
  w.x = generate_stream(0x50405b00ULL, size_t{kSeqLen} * kDModel, 0.25, 0.0, true);
  w.rms1_w = generate_stream(0x50405b01ULL, kDModel, 0.25, 0.75, false);
  w.wq = generate_stream(0x50405b02ULL, size_t{kDModel} * kDModel, 0.1875, 0.0, true);
  w.wk = generate_stream(0x50405b03ULL, size_t{kDModel} * kDModel, 0.1875, 0.0, true);
  w.wv = generate_stream(0x50405b04ULL, size_t{kDModel} * kDModel, 0.1875, 0.0, true);
  w.wo = generate_stream(0x50405b05ULL, size_t{kDModel} * kDModel, 0.1875, 0.0, true);
  w.rms2_w = generate_stream(0x50405b06ULL, kDModel, 0.25, 0.75, false);
  w.w1 = generate_stream(0x50405b07ULL, size_t{kDModel} * kDFf, 0.1875, 0.0, true);
  w.w2 = generate_stream(0x50405b08ULL, size_t{kDFf} * kDModel, 0.1875, 0.0, true);

  const size_t n_act = size_t{kSeqLen} * kDModel;
  const double eps = static_cast<double>(bits_to_float(kRmsEpsBits));
  std::vector<double> x_f64(n_act);
  for (size_t i = 0; i < n_act; ++i) {
    x_f64[i] = static_cast<double>(w.x[i]);
  }

  std::vector<double> norm1(n_act);
  ref_rmsnorm_f64(x_f64.data(), w.rms1_w.data(), kSeqLen, kDModel, eps, norm1.data());

  std::vector<double> q(n_act);
  std::vector<double> k(n_act);
  std::vector<double> v(n_act);
  ref_matmul_f64(norm1.data(), w.wq.data(), kSeqLen, kDModel, kDModel, q.data());
  ref_matmul_f64(norm1.data(), w.wk.data(), kSeqLen, kDModel, kDModel, k.data());
  ref_matmul_f64(norm1.data(), w.wv.data(), kSeqLen, kDModel, kDModel, v.data());

  std::vector<double> attn_concat(n_act);
  for (uint32_t h = 0; h < kNHeads; ++h) {
    ref_attention_f64(q.data(), k.data(), v.data(), kSeqLen, kDHead, kDModel,
                      h * kDHead, attn_concat.data());
  }

  std::vector<double> attn_proj(n_act);
  ref_matmul_f64(attn_concat.data(), w.wo.data(), kSeqLen, kDModel, kDModel, attn_proj.data());

  std::vector<double> x_mid(n_act);
  for (size_t i = 0; i < n_act; ++i) {
    x_mid[i] = x_f64[i] + attn_proj[i];
  }

  std::vector<double> norm2(n_act);
  ref_rmsnorm_f64(x_mid.data(), w.rms2_w.data(), kSeqLen, kDModel, eps, norm2.data());

  std::vector<double> ffn_h(size_t{kSeqLen} * kDFf);
  ref_matmul_f64(norm2.data(), w.w1.data(), kSeqLen, kDFf, kDModel, ffn_h.data());

  const double kSqrt2OverPi = std::sqrt(2.0 / 3.14159265358979323846);
  std::vector<double> ffn_a(size_t{kSeqLen} * kDFf);
  for (size_t i = 0; i < ffn_h.size(); ++i) {
    const double xv = ffn_h[i];
    const double u = kSqrt2OverPi * (xv + 0.044715 * xv * xv * xv);
    ffn_a[i] = 0.5 * xv * (1.0 + std::tanh(u));
  }

  std::vector<double> ffn_out(n_act);
  ref_matmul_f64(ffn_a.data(), w.w2.data(), kSeqLen, kDModel, kDFf, ffn_out.data());

  w.expected_y.resize(n_act);
  for (size_t i = 0; i < n_act; ++i) {
    w.expected_y[i] = x_mid[i] + ffn_out[i];
  }
  return w;
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

struct BufferHandle {
  vx_buffer_h h = nullptr;
  uint64_t addr = 0;

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
      addr = 0;
    }
  }
};

struct DeviceSession {
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h ops_module = nullptr;
  vx_kernel_h ops_kernel = nullptr;
  vx_module_h matmul_module = nullptr;
  vx_kernel_h matmul_kernel = nullptr;

  ~DeviceSession() {
    release();
  }

  void release() noexcept {
    // Release the queue first so all queued work drains before releasing kernels/modules/device.
    if (queue) {
      vx_queue_release(queue);
      queue = nullptr;
    }
    if (matmul_kernel) {
      vx_kernel_release(matmul_kernel);
      matmul_kernel = nullptr;
    }
    if (matmul_module) {
      vx_module_release(matmul_module);
      matmul_module = nullptr;
    }
    if (ops_kernel) {
      vx_kernel_release(ops_kernel);
      ops_kernel = nullptr;
    }
    if (ops_module) {
      vx_module_release(ops_module);
      ops_module = nullptr;
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
      return false;                                                             \
    }                                                                           \
  } while (0)

bool check_device_profile(vx_device_h device) {
  uint64_t isa = 0;
  uint64_t threads = 0, warps = 0, cores = 0, clusters = 0;
  if (vx_device_query(device, VX_CAPS_ISA_FLAGS, &isa) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_THREADS, &threads) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_WARPS, &warps) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CORES, &cores) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CLUSTERS, &clusters) != VX_SUCCESS) {
    std::cerr << "FAILED device capability query\n";
    return false;
  }
  if (VX_ISA_ARCH(isa) != 64 || (isa & VX_ISA_EXT_TCU) == 0
      || threads < 4 || warps < 4 || cores == 0 || clusters == 0) {
    std::cerr << "FAILED device capabilities do not match RV64 TFR profile\n";
    return false;
  }
  return true;
}

bool create_buffer(vx_device_h device, uint64_t size, uint32_t flags, BufferHandle* out) {
  VX_CHECK(vx_buffer_create(device, size, flags, &out->h));
  VX_CHECK(vx_buffer_address(out->h, &out->addr));
  return true;
}

bool enqueue_write_bytes(vx_queue_h queue, const BufferHandle& dst,
                         const std::vector<uint8_t>& data,
                         vx_event_h dep, EventHandle* out_ev,
                         uint64_t* h2d_bytes) {
  out_ev->release();
  const uint32_t n_wait = dep ? 1u : 0u;
  const vx_event_h* wait_ptr = dep ? &dep : nullptr;
  VX_CHECK(vx_enqueue_write(queue, dst.h, 0, data.data(), data.size(),
                            n_wait, wait_ptr, &out_ev->h));
  *h2d_bytes += data.size();
  return true;
}

bool enqueue_ops_v2(vx_queue_h queue, vx_kernel_h kernel, uint32_t op_code,
                    uint32_t rows, uint32_t cols, uint64_t src0_addr,
                    uint64_t src1_addr, uint64_t src2_addr, uint64_t dst_addr,
                    vx_event_h dep, EventHandle* out_ev, uint32_t* ops_launches) {
  va::OpsV2Arguments arg{};
  arg.op_code = op_code;
  arg.flags = 0;
  arg.rows = rows;
  arg.cols = cols;
  arg.eps_bits = kRmsEpsBits;
  arg.src0_addr = src0_addr;
  arg.src1_addr = src1_addr;
  arg.src2_addr = src2_addr;
  arg.dst_addr = dst_addr;

  vx_launch_info_t li{};
  li.struct_size = sizeof(li);
  li.kernel = kernel;
  li.args_host = &arg;
  li.args_size = sizeof(arg);
  li.ndim = 1;
  li.grid_dim[0] = 1;
  li.grid_dim[1] = 1;
  li.grid_dim[2] = 1;
  li.block_dim[0] = kOpsBlockX;
  li.block_dim[1] = 1;
  li.block_dim[2] = 1;
  li.lmem_size = 0;
  li.cluster_dim[0] = 1;
  li.cluster_dim[1] = 1;
  li.cluster_dim[2] = 1;

  out_ev->release();
  const uint32_t n_wait = dep ? 1u : 0u;
  const vx_event_h* wait_ptr = dep ? &dep : nullptr;
  VX_CHECK(vx_enqueue_launch(queue, &li, n_wait, wait_ptr, &out_ev->h));
  ++(*ops_launches);
  return true;
}

bool enqueue_matmul_tile(vx_queue_h queue, vx_kernel_h kernel, uint64_t a_addr,
                         uint64_t b_addr, uint64_t d_addr, vx_event_h dep,
                         EventHandle* out_ev, uint32_t* matmul_launches) {
  va::MatmulArguments arg{};
  arg.input_dtype = 1; // fp16
  arg.flags = 0;
  arg.m = kSeqLen;
  arg.n = kTileN;
  arg.k = kDModel;
  arg.a_address = a_addr;
  arg.b_address = b_addr;
  arg.d_address = d_addr;

  vx_launch_info_t li{};
  li.struct_size = sizeof(li);
  li.kernel = kernel;
  li.args_host = &arg;
  li.args_size = sizeof(arg);
  li.ndim = 2;
  li.grid_dim[0] = 1;
  li.grid_dim[1] = 1;
  li.grid_dim[2] = 1;
  li.block_dim[0] = kMatmulBlockX;
  li.block_dim[1] = 1;
  li.block_dim[2] = 1;
  li.lmem_size = 0;
  li.cluster_dim[0] = 1;
  li.cluster_dim[1] = 1;
  li.cluster_dim[2] = 1;

  out_ev->release();
  const uint32_t n_wait = dep ? 1u : 0u;
  const vx_event_h* wait_ptr = dep ? &dep : nullptr;
  VX_CHECK(vx_enqueue_launch(queue, &li, n_wait, wait_ptr, &out_ev->h));
  ++(*matmul_launches);
  return true;
}

bool enqueue_copy_2d(vx_queue_h queue, const BufferHandle& dst,
                     uint64_t dst_x_bytes, uint64_t dst_row_pitch,
                     const BufferHandle& src, uint64_t src_x_bytes,
                     uint64_t src_row_pitch, uint64_t width_bytes,
                     uint64_t rows, vx_event_h dep, EventHandle* out_ev,
                     uint32_t* d2d_copies) {
  vx_rect_info_t rect{};
  rect.struct_size = sizeof(rect);
  rect.buffer_origin[0] = dst_x_bytes;
  rect.buffer_origin[1] = 0;
  rect.buffer_origin[2] = 0;
  rect.host_origin[0] = src_x_bytes;
  rect.host_origin[1] = 0;
  rect.host_origin[2] = 0;
  rect.region[0] = width_bytes;
  rect.region[1] = rows;
  rect.region[2] = 1;
  rect.buffer_row_pitch = dst_row_pitch;
  rect.buffer_slice_pitch = 0;
  rect.host_row_pitch = src_row_pitch;
  rect.host_slice_pitch = 0;

  out_ev->release();
  const uint32_t n_wait = dep ? 1u : 0u;
  const vx_event_h* wait_ptr = dep ? &dep : nullptr;
  VX_CHECK(vx_enqueue_copy_rect(queue, dst.h, src.h, &rect,
                                n_wait, wait_ptr, &out_ev->h));
  ++(*d2d_copies);
  return true;
}

bool enqueue_linear_proj(const DeviceSession& session, const BufferHandle& act_fp16,
                         const std::array<BufferHandle, kTilesPerProj>& w_tiles,
                         const BufferHandle& tile_f32, const BufferHandle& out_f32,
                         EventHandle* chain, uint32_t* matmul_launches,
                         uint32_t* d2d_copies) {
  for (uint32_t t = 0; t < kTilesPerProj; ++t) {
    EventHandle ev_mm;
    if (!enqueue_matmul_tile(session.queue, session.matmul_kernel,
                             act_fp16.addr, w_tiles[t].addr, tile_f32.addr,
                             chain->h, &ev_mm, matmul_launches)) {
      return false;
    }
    EventHandle ev_cp;
    if (!enqueue_copy_2d(session.queue, out_f32, uint64_t{t} * kTileN * 4,
                         uint64_t{kDModel} * 4, tile_f32, 0, uint64_t{kTileN} * 4,
                         uint64_t{kTileN} * 4, kSeqLen, ev_mm.h, &ev_cp, d2d_copies)) {
      return false;
    }
    std::swap(chain->h, ev_cp.h);
  }
  return true;
}

bool enqueue_residual_add(const DeviceSession& session,
                          const BufferHandle& a_f32, const BufferHandle& b_f32,
                          const BufferHandle& res_a_fp16, const BufferHandle& res_b_fp16,
                          const BufferHandle& res_pair_fp16,
                          const std::array<BufferHandle, kTilesPerHalf>& w_add_tiles,
                          const BufferHandle& tile_f32, const BufferHandle& out_f32,
                          EventHandle* chain, uint32_t* ops_launches,
                          uint32_t* matmul_launches, uint32_t* d2d_copies) {
  EventHandle ev_ca;
  if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpCastFp32ToFp16,
                      kSeqLen, kDModel, a_f32.addr, 0, 0, res_a_fp16.addr,
                      chain->h, &ev_ca, ops_launches)) {
    return false;
  }
  EventHandle ev_cb;
  if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpCastFp32ToFp16,
                      kSeqLen, kDModel, b_f32.addr, 0, 0, res_b_fp16.addr,
                      ev_ca.h, &ev_cb, ops_launches)) {
    return false;
  }
  std::swap(chain->h, ev_cb.h);

  const uint64_t fp16_row_pitch = uint64_t{kDModel} * 2;
  const uint64_t half_width_bytes = uint64_t{kHalfCols} * 2;
  for (uint32_t half = 0; half < kNHeads; ++half) {
    EventHandle ev_pa;
    if (!enqueue_copy_2d(session.queue, res_pair_fp16, 0, fp16_row_pitch,
                         res_a_fp16, uint64_t{half} * half_width_bytes, fp16_row_pitch,
                         half_width_bytes, kSeqLen, chain->h, &ev_pa, d2d_copies)) {
      return false;
    }
    EventHandle ev_pb;
    if (!enqueue_copy_2d(session.queue, res_pair_fp16, half_width_bytes, fp16_row_pitch,
                         res_b_fp16, uint64_t{half} * half_width_bytes, fp16_row_pitch,
                         half_width_bytes, kSeqLen, ev_pa.h, &ev_pb, d2d_copies)) {
      return false;
    }
    std::swap(chain->h, ev_pb.h);

    for (uint32_t t = 0; t < kTilesPerHalf; ++t) {
      EventHandle ev_mm;
      if (!enqueue_matmul_tile(session.queue, session.matmul_kernel,
                               res_pair_fp16.addr, w_add_tiles[t].addr, tile_f32.addr,
                               chain->h, &ev_mm, matmul_launches)) {
        return false;
      }
      EventHandle ev_cp;
      const uint64_t dst_col_bytes = (uint64_t{half} * kHalfCols + uint64_t{t} * kTileN) * 4;
      if (!enqueue_copy_2d(session.queue, out_f32, dst_col_bytes, uint64_t{kDModel} * 4,
                           tile_f32, 0, uint64_t{kTileN} * 4, uint64_t{kTileN} * 4,
                           kSeqLen, ev_mm.h, &ev_cp, d2d_copies)) {
        return false;
      }
      std::swap(chain->h, ev_cp.h);
    }
  }
  return true;
}

bool run_transformer(const DeviceSession& session, const TransformerWeights& weights,
                     uint32_t iterations, uint32_t* total_mismatches,
                     double* worst_max_abs_err) {
  const uint64_t act_f32_bytes = uint64_t{kSeqLen} * kDModel * 4;
  const uint64_t act_fp16_bytes = uint64_t{kSeqLen} * kDModel * 2;
  const uint64_t head_f32_bytes = uint64_t{kSeqLen} * kDHead * 4;
  const uint64_t tile_w_bytes = uint64_t{kDModel} * kTileN * 2;
  const uint64_t tile_f32_bytes = uint64_t{kSeqLen} * kTileN * 4;
  const uint64_t rms_w_bytes = uint64_t{kDModel} * 4;

  BufferHandle d_x_f32, d_rms1_w, d_rms2_w;
  std::array<BufferHandle, kTilesPerProj> d_wq, d_wk, d_wv, d_wo, d_w1, d_w2;
  std::array<BufferHandle, kTilesPerHalf> d_wadd;

  if (!create_buffer(session.device, act_f32_bytes, VX_MEM_READ, &d_x_f32)
      || !create_buffer(session.device, rms_w_bytes, VX_MEM_READ, &d_rms1_w)
      || !create_buffer(session.device, rms_w_bytes, VX_MEM_READ, &d_rms2_w)) {
    return false;
  }
  for (uint32_t t = 0; t < kTilesPerProj; ++t) {
    if (!create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_wq[t])
        || !create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_wk[t])
        || !create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_wv[t])
        || !create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_wo[t])
        || !create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_w1[t])
        || !create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_w2[t])) {
      return false;
    }
  }
  for (uint32_t t = 0; t < kTilesPerHalf; ++t) {
    if (!create_buffer(session.device, tile_w_bytes, VX_MEM_READ, &d_wadd[t])) {
      return false;
    }
  }

  BufferHandle d_norm_f32, d_act_fp16, d_q_f32, d_k_f32, d_v_f32;
  BufferHandle d_qh_f32, d_kh_f32, d_vh_f32, d_attnh_f32, d_attn_f32;
  BufferHandle d_proj_f32, d_x_mid_f32, d_ffn_h_f32, d_ffn_a_f32;
  BufferHandle d_res_a_fp16, d_res_b_fp16, d_res_pair_fp16, d_tile_f32, d_y_f32;

  if (!create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_norm_f32)
      || !create_buffer(session.device, act_fp16_bytes, VX_MEM_READ_WRITE, &d_act_fp16)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_q_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_k_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_v_f32)
      || !create_buffer(session.device, head_f32_bytes, VX_MEM_READ_WRITE, &d_qh_f32)
      || !create_buffer(session.device, head_f32_bytes, VX_MEM_READ_WRITE, &d_kh_f32)
      || !create_buffer(session.device, head_f32_bytes, VX_MEM_READ_WRITE, &d_vh_f32)
      || !create_buffer(session.device, head_f32_bytes, VX_MEM_READ_WRITE, &d_attnh_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_attn_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_proj_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_x_mid_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_ffn_h_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_ffn_a_f32)
      || !create_buffer(session.device, act_fp16_bytes, VX_MEM_READ_WRITE, &d_res_a_fp16)
      || !create_buffer(session.device, act_fp16_bytes, VX_MEM_READ_WRITE, &d_res_b_fp16)
      || !create_buffer(session.device, act_fp16_bytes, VX_MEM_READ_WRITE, &d_res_pair_fp16)
      || !create_buffer(session.device, tile_f32_bytes, VX_MEM_READ_WRITE, &d_tile_f32)
      || !create_buffer(session.device, act_f32_bytes, VX_MEM_READ_WRITE, &d_y_f32)) {
    return false;
  }

  const std::vector<uint8_t> h_x = pack_f32_bytes(weights.x);
  const std::vector<uint8_t> h_rms1 = pack_f32_bytes(weights.rms1_w);
  const std::vector<uint8_t> h_rms2 = pack_f32_bytes(weights.rms2_w);

  std::array<std::vector<uint8_t>, kTilesPerProj> h_wq, h_wk, h_wv, h_wo, h_w1, h_w2;
  for (uint32_t t = 0; t < kTilesPerProj; ++t) {
    h_wq[t] = pack_weight_tile_col_major_fp16(weights.wq, kDModel, kDModel, t * kTileN);
    h_wk[t] = pack_weight_tile_col_major_fp16(weights.wk, kDModel, kDModel, t * kTileN);
    h_wv[t] = pack_weight_tile_col_major_fp16(weights.wv, kDModel, kDModel, t * kTileN);
    h_wo[t] = pack_weight_tile_col_major_fp16(weights.wo, kDModel, kDModel, t * kTileN);
    h_w1[t] = pack_weight_tile_col_major_fp16(weights.w1, kDModel, kDFf, t * kTileN);
    h_w2[t] = pack_weight_tile_col_major_fp16(weights.w2, kDFf, kDModel, t * kTileN);
  }
  std::array<std::vector<uint8_t>, kTilesPerHalf> h_wadd;
  for (uint32_t t = 0; t < kTilesPerHalf; ++t) {
    h_wadd[t] = pack_identity_add_tile_fp16(t * kTileN);
  }

  std::vector<uint8_t> poison_y(act_f32_bytes);
  std::vector<uint8_t> out_y_bytes(act_f32_bytes);

  for (uint32_t iter = 0; iter < iterations; ++iter) {
    const uint32_t poison_word = (iter & 1u) == 0 ? 0x7fc0deadu : 0xdeadbeefu;
    for (size_t i = 0; i < size_t{kSeqLen} * kDModel; ++i) {
      write_u32_le(poison_y.data() + i * 4, poison_word ^ static_cast<uint32_t>(i));
    }
    std::fill(out_y_bytes.begin(), out_y_bytes.end(), static_cast<uint8_t>(0x3cu));

    uint64_t h2d_bytes = 0;
    uint64_t d2h_bytes = 0;
    uint32_t ops_launches = 0;
    uint32_t matmul_launches = 0;
    uint32_t d2d_copies = 0;

    EventHandle chain;
    auto upload = [&](const BufferHandle& buf, const std::vector<uint8_t>& bytes) -> bool {
      EventHandle ev;
      if (!enqueue_write_bytes(session.queue, buf, bytes, chain.h, &ev, &h2d_bytes)) {
        return false;
      }
      std::swap(chain.h, ev.h);
      return true;
    };

    if (!upload(d_x_f32, h_x) || !upload(d_rms1_w, h_rms1)
        || !upload(d_rms2_w, h_rms2) || !upload(d_y_f32, poison_y)) {
      return false;
    }
    for (uint32_t t = 0; t < kTilesPerProj; ++t) {
      if (!upload(d_wq[t], h_wq[t]) || !upload(d_wk[t], h_wk[t])
          || !upload(d_wv[t], h_wv[t]) || !upload(d_wo[t], h_wo[t])
          || !upload(d_w1[t], h_w1[t]) || !upload(d_w2[t], h_w2[t])) {
        return false;
      }
    }
    for (uint32_t t = 0; t < kTilesPerHalf; ++t) {
      if (!upload(d_wadd[t], h_wadd[t])) {
        return false;
      }
    }

    const uint64_t init_h2d_bytes = h2d_bytes;

    // 1. Pre-RMSNorm 1
    {
      EventHandle ev;
      if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpRmsNormFp32,
                          kSeqLen, kDModel, d_x_f32.addr, d_rms1_w.addr, 0,
                          d_norm_f32.addr, chain.h, &ev, &ops_launches)) {
        return false;
      }
      std::swap(chain.h, ev.h);
    }

    // 2. Cast norm1 -> FP16 and run Q/K/V projections on-device
    {
      EventHandle ev;
      if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpCastFp32ToFp16,
                          kSeqLen, kDModel, d_norm_f32.addr, 0, 0,
                          d_act_fp16.addr, chain.h, &ev, &ops_launches)) {
        return false;
      }
      std::swap(chain.h, ev.h);
    }
    if (!enqueue_linear_proj(session, d_act_fp16, d_wq, d_tile_f32, d_q_f32,
                             &chain, &matmul_launches, &d2d_copies)
        || !enqueue_linear_proj(session, d_act_fp16, d_wk, d_tile_f32, d_k_f32,
                                &chain, &matmul_launches, &d2d_copies)
        || !enqueue_linear_proj(session, d_act_fp16, d_wv, d_tile_f32, d_v_f32,
                                &chain, &matmul_launches, &d2d_copies)) {
      return false;
    }

    // 3. 2-head Scaled Dot-Product Attention (ops_v2 attention_fp32)
    for (uint32_t head = 0; head < kNHeads; ++head) {
      const uint64_t head_col_bytes = uint64_t{head} * kDHead * 4;
      const uint64_t model_pitch = uint64_t{kDModel} * 4;
      const uint64_t head_pitch = uint64_t{kDHead} * 4;

      EventHandle ev_sq, ev_sk, ev_sv, ev_attn, ev_cat;
      if (!enqueue_copy_2d(session.queue, d_qh_f32, 0, head_pitch, d_q_f32,
                           head_col_bytes, model_pitch, head_pitch, kSeqLen,
                           chain.h, &ev_sq, &d2d_copies)
          || !enqueue_copy_2d(session.queue, d_kh_f32, 0, head_pitch, d_k_f32,
                              head_col_bytes, model_pitch, head_pitch, kSeqLen,
                              ev_sq.h, &ev_sk, &d2d_copies)
          || !enqueue_copy_2d(session.queue, d_vh_f32, 0, head_pitch, d_v_f32,
                              head_col_bytes, model_pitch, head_pitch, kSeqLen,
                              ev_sk.h, &ev_sv, &d2d_copies)
          || !enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpAttentionFp32,
                             kSeqLen, kDHead, d_qh_f32.addr, d_kh_f32.addr, d_vh_f32.addr,
                             d_attnh_f32.addr, ev_sv.h, &ev_attn, &ops_launches)
          || !enqueue_copy_2d(session.queue, d_attn_f32, head_col_bytes, model_pitch,
                              d_attnh_f32, 0, head_pitch, head_pitch, kSeqLen,
                              ev_attn.h, &ev_cat, &d2d_copies)) {
        return false;
      }
      std::swap(chain.h, ev_cat.h);
    }

    // 4. Output projection + Residual 1
    {
      EventHandle ev;
      if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpCastFp32ToFp16,
                          kSeqLen, kDModel, d_attn_f32.addr, 0, 0,
                          d_act_fp16.addr, chain.h, &ev, &ops_launches)) {
        return false;
      }
      std::swap(chain.h, ev.h);
    }
    if (!enqueue_linear_proj(session, d_act_fp16, d_wo, d_tile_f32, d_proj_f32,
                             &chain, &matmul_launches, &d2d_copies)
        || !enqueue_residual_add(session, d_x_f32, d_proj_f32, d_res_a_fp16,
                                 d_res_b_fp16, d_res_pair_fp16, d_wadd,
                                 d_tile_f32, d_x_mid_f32, &chain,
                                 &ops_launches, &matmul_launches, &d2d_copies)) {
      return false;
    }

    // 5. Pre-RMSNorm 2 + FFN (W1 -> GELU -> W2) + Residual 2
    {
      EventHandle ev_n2, ev_c2;
      if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpRmsNormFp32,
                          kSeqLen, kDModel, d_x_mid_f32.addr, d_rms2_w.addr, 0,
                          d_norm_f32.addr, chain.h, &ev_n2, &ops_launches)
          || !enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpCastFp32ToFp16,
                             kSeqLen, kDModel, d_norm_f32.addr, 0, 0,
                             d_act_fp16.addr, ev_n2.h, &ev_c2, &ops_launches)) {
        return false;
      }
      std::swap(chain.h, ev_c2.h);
    }
    if (!enqueue_linear_proj(session, d_act_fp16, d_w1, d_tile_f32, d_ffn_h_f32,
                             &chain, &matmul_launches, &d2d_copies)) {
      return false;
    }
    {
      EventHandle ev_gelu, ev_c3;
      if (!enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpGeluFp32,
                          kSeqLen, kDFf, d_ffn_h_f32.addr, 0, 0,
                          d_ffn_a_f32.addr, chain.h, &ev_gelu, &ops_launches)
          || !enqueue_ops_v2(session.queue, session.ops_kernel, va::kOpsV2OpCastFp32ToFp16,
                             kSeqLen, kDFf, d_ffn_a_f32.addr, 0, 0,
                             d_act_fp16.addr, ev_gelu.h, &ev_c3, &ops_launches)) {
        return false;
      }
      std::swap(chain.h, ev_c3.h);
    }
    if (!enqueue_linear_proj(session, d_act_fp16, d_w2, d_tile_f32, d_proj_f32,
                             &chain, &matmul_launches, &d2d_copies)
        || !enqueue_residual_add(session, d_x_mid_f32, d_proj_f32, d_res_a_fp16,
                                 d_res_b_fp16, d_res_pair_fp16, d_wadd,
                                 d_tile_f32, d_y_f32, &chain,
                                 &ops_launches, &matmul_launches, &d2d_copies)) {
      return false;
    }

    // Only the final logits are transferred D2H; all intermediates stay on-device.
    EventHandle ev_read;
    VX_CHECK(vx_enqueue_read(session.queue, out_y_bytes.data(), d_y_f32.h, 0,
                             out_y_bytes.size(), 1, &chain.h, &ev_read.h));
    d2h_bytes += out_y_bytes.size();

    VX_CHECK(vx_event_wait_value(ev_read.h, 1, VX_TIMEOUT_INFINITE));
    ev_read.release();
    chain.release();

    uint32_t iter_mismatches = 0;
    double iter_max_abs_err = 0.0;
    for (size_t i = 0; i < weights.expected_y.size(); ++i) {
      const float actual_f32 = bits_to_float(read_u32_le(out_y_bytes.data() + i * 4));
      const double expected = weights.expected_y[i];
      const double err = std::fabs(static_cast<double>(actual_f32) - expected);
      if (!std::isfinite(actual_f32) || err > iter_max_abs_err) {
        iter_max_abs_err = std::isfinite(actual_f32) ? err : INFINITY;
      }
      if (!std::isfinite(actual_f32) || err > kMaxAbsTolerance) {
        if (*total_mismatches + iter_mismatches < kMaxPrintedErrors) {
          std::printf("*** mismatch [iter=%u idx=%zu] expected=%.8g actual=%.8g err=%.3e\n",
                      iter, i, expected, static_cast<double>(actual_f32), err);
        }
        ++iter_mismatches;
      }
    }

    *total_mismatches += iter_mismatches;
    if (!std::isfinite(iter_max_abs_err) || iter_max_abs_err > *worst_max_abs_err) {
      *worst_max_abs_err = iter_max_abs_err;
    }

    std::printf("TRANSFORMER_V2_CASE iter=%u ops_launches=%u matmul_launches=%u "
                "d2d_copies=%u init_h2d_bytes=%llu intermediate_h2d_bytes=0 "
                "intermediate_d2h_bytes=0 final_d2h_bytes=%llu "
                "max_abs_err=%.6e tol=%.6e mismatches=%u\n",
                iter, ops_launches, matmul_launches, d2d_copies,
                static_cast<unsigned long long>(init_h2d_bytes),
                static_cast<unsigned long long>(d2h_bytes),
                iter_max_abs_err, kMaxAbsTolerance, iter_mismatches);
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

  const TransformerWeights weights = build_workload();

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
  if (vx_module_load_file(session.device, opts.ops_kernel_path.c_str(),
                          &session.ops_module) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_load_file (" << opts.ops_kernel_path << ")\n";
    return 1;
  }
  if (vx_module_get_kernel(session.ops_module, "main", &session.ops_kernel) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_get_kernel (ops_v2 main)\n";
    return 1;
  }
  if (vx_module_load_file(session.device, opts.matmul_kernel_path.c_str(),
                          &session.matmul_module) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_load_file (" << opts.matmul_kernel_path << ")\n";
    return 1;
  }
  if (vx_module_get_kernel(session.matmul_module, "main", &session.matmul_kernel) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_get_kernel (matmul main)\n";
    return 1;
  }

  uint32_t total_mismatches = 0;
  double worst_max_abs_err = 0.0;
  if (!run_transformer(session, weights, opts.iterations,
                       &total_mismatches, &worst_max_abs_err)) {
    return 1;
  }

  std::printf("TRANSFORMER_V2_SUMMARY seq_len=%u d_model=%u n_heads=%u d_head=%u "
              "d_ff=%u iterations=%u elements=%u max_abs_err=%.6e tol=%.6e "
              "total_mismatches=%u\n",
              kSeqLen, kDModel, kNHeads, kDHead, kDFf, opts.iterations,
              kSeqLen * kDModel * opts.iterations,
              worst_max_abs_err, kMaxAbsTolerance, total_mismatches);

  vx_device_dump_perf(session.device, stdout);
  session.release();

  if (total_mismatches != 0) {
    std::cout << "FAILED!\n";
    return 1;
  }
  std::cout << "PASSED!\n";
  return 0;
}
