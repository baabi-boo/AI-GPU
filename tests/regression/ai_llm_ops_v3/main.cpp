// SPDX-License-Identifier: Apache-2.0

#include <ai_llm_ops_v3_args.h>
#include <vortex2.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
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
      case 'k': {
        out->kernel_path = optarg;
        break;
      }
      case 'o': {
        out->op_filter = optarg;
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

uint32_t read_u32_le(const uint8_t* src) noexcept {
  return uint32_t{src[0]} | (uint32_t{src[1]} << 8)
       | (uint32_t{src[2]} << 16) | (uint32_t{src[3]} << 24);
}

std::vector<uint8_t> pack_f32_floats(const std::vector<float>& vals) {
  std::vector<uint8_t> bytes(vals.size() * 4);
  for (size_t i = 0; i < vals.size(); ++i) {
    write_u32_le(bytes.data() + i * 4, float_to_bits(vals[i]));
  }
  return bytes;
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
  uint64_t threads = 0, warps = 0, cores = 0, clusters = 0, lmem_size = 0;
  if (vx_device_query(device, VX_CAPS_ISA_FLAGS, &isa) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_THREADS, &threads) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_WARPS, &warps) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CORES, &cores) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_NUM_CLUSTERS, &clusters) != VX_SUCCESS
      || vx_device_query(device, VX_CAPS_LOCAL_MEM_SIZE, &lmem_size) != VX_SUCCESS) {
    std::cerr << "FAILED device capability query\n";
    return false;
  }
  if (VX_ISA_ARCH(isa) != 64 || threads == 0 || warps == 0 || cores == 0 || clusters == 0) {
    std::cerr << "FAILED device capabilities do not match RV64 execution profile\n";
    return false;
  }
  if ((isa & VX_ISA_EXT_LMEM) == 0 || lmem_size < va::kLlmV3FlashLmemBytes) {
    std::cerr << "FAILED device local memory insufficient for tiled FlashAttention\n";
    return false;
  }
  return true;
}

enum class CheckMode {
  BitExact32,
  MaxAbsErrF32,
};

struct OperatorCase {
  std::string name;
  uint32_t op_code = 0;
  uint32_t flags = 0;
  uint32_t dim0 = 0;
  uint32_t dim1 = 0;
  uint32_t dim2 = 0;
  uint32_t dim3 = 0;
  uint32_t pos_offset = 0;
  uint32_t eps_or_theta_bits = va::kLlmV3DefaultEpsBits;
  uint32_t block_x = 16;
  uint32_t grid_x = 1;
  uint32_t lmem_size = 0;
  CheckMode check_mode = CheckMode::MaxAbsErrF32;
  double max_abs_tol = kApproxMaxAbsErr;
  std::vector<uint8_t> src0_bytes;
  std::vector<uint8_t> src1_bytes;
  std::vector<uint8_t> src2_bytes;
  std::vector<uint8_t> dst_init_bytes;
  std::vector<uint8_t> dst2_init_bytes;
  std::vector<uint32_t> expected_dst_u32;
  std::vector<uint32_t> expected_dst2_u32;
  std::vector<double> expected_dst_f64;
};

void compute_rope_ref(const std::vector<float>& x, uint32_t seq_len, uint32_t n_heads,
                      uint32_t d_head, uint32_t pos_offset, double theta,
                      std::vector<double>* out) {
  out->resize(x.size());
  const uint32_t half_dim = d_head / 2;
  for (uint32_t s = 0; s < seq_len; ++s) {
    const double pos = static_cast<double>(pos_offset + s);
    for (uint32_t h = 0; h < n_heads; ++h) {
      const uint32_t base = (s * n_heads + h) * d_head;
      for (uint32_t j = 0; j < half_dim; ++j) {
        const double freq = std::pow(theta, -static_cast<double>(2u * j) / static_cast<double>(d_head));
        const double angle = pos * freq;
        const double cs = std::cos(angle);
        const double sn = std::sin(angle);
        const double x0 = static_cast<double>(x[base + j]);
        const double x1 = static_cast<double>(x[base + j + half_dim]);
        (*out)[base + j] = x0 * cs - x1 * sn;
        (*out)[base + j + half_dim] = x0 * sn + x1 * cs;
      }
    }
  }
}

void compute_attention_ref(const std::vector<float>& q, const std::vector<float>& k,
                           const std::vector<float>& v, uint32_t q_len, uint32_t kv_len,
                           uint32_t n_q_heads, uint32_t n_kv_heads, uint32_t d_head,
                           bool causal, uint32_t pos_offset, std::vector<double>* out) {
  out->resize(size_t{q_len} * n_q_heads * d_head);
  const uint32_t group_size = n_q_heads / n_kv_heads;
  const uint32_t q_stride = n_q_heads * d_head;
  const uint32_t kv_stride = n_kv_heads * d_head;
  const double scale = 1.0 / std::sqrt(static_cast<double>(d_head));
  std::vector<double> scores(kv_len);

  for (uint32_t i = 0; i < q_len; ++i) {
    for (uint32_t qh = 0; qh < n_q_heads; ++qh) {
      const uint32_t kvh = qh / group_size;
      const uint32_t q_off = i * q_stride + qh * d_head;

      double max_s = -std::numeric_limits<double>::infinity();
      for (uint32_t j = 0; j < kv_len; ++j) {
        if (causal && j > i + pos_offset) {
          scores[j] = -std::numeric_limits<double>::infinity();
          continue;
        }
        const uint32_t k_off = j * kv_stride + kvh * d_head;
        double dot = 0.0;
        for (uint32_t d = 0; d < d_head; ++d) {
          dot += static_cast<double>(q[q_off + d]) * static_cast<double>(k[k_off + d]);
        }
        scores[j] = dot * scale;
        if (scores[j] > max_s) {
          max_s = scores[j];
        }
      }

      double exp_sum = 0.0;
      for (uint32_t j = 0; j < kv_len; ++j) {
        if (causal && j > i + pos_offset) {
          scores[j] = 0.0;
        } else {
          scores[j] = std::exp(scores[j] - max_s);
          exp_sum += scores[j];
        }
      }
      for (uint32_t d = 0; d < d_head; ++d) {
        double acc = 0.0;
        for (uint32_t j = 0; j < kv_len; ++j) {
          const uint32_t v_off = j * kv_stride + kvh * d_head;
          acc += scores[j] * static_cast<double>(v[v_off + d]);
        }
        (*out)[q_off + d] = acc / exp_sum;
      }
    }
  }
}

std::vector<OperatorCase> build_cases() {
  std::vector<OperatorCase> cases;

  // 1a. rope_prefill_fp32: seq_len=8, n_heads=2, d_head=16, pos_offset=0
  {
    OperatorCase c;
    c.name = "rope_prefill_fp32";
    c.op_code = va::kLlmOpRopeFp32;
    c.dim0 = 8;
    c.dim1 = 2;
    c.dim2 = 16;
    c.pos_offset = 0;
    c.eps_or_theta_bits = va::kLlmV3DefaultThetaBits;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    const size_t total = size_t{c.dim0} * c.dim1 * c.dim2;
    std::vector<float> x(total);
    for (size_t i = 0; i < total; ++i) {
      const int32_t v = static_cast<int32_t>((i * 7 + 3) % 17) - 8;
      x[i] = static_cast<float>(v) * 0.25f;
    }
    c.src0_bytes = pack_f32_floats(x);
    compute_rope_ref(x, c.dim0, c.dim1, c.dim2, c.pos_offset, 10000.0, &c.expected_dst_f64);
    cases.push_back(std::move(c));
  }

  // 1b. rope_decode_fp32: single token seq_len=1, n_heads=4, d_head=16, pos_offset=13
  {
    OperatorCase c;
    c.name = "rope_decode_fp32";
    c.op_code = va::kLlmOpRopeFp32;
    c.dim0 = 1;
    c.dim1 = 4;
    c.dim2 = 16;
    c.pos_offset = 13;
    c.eps_or_theta_bits = va::kLlmV3DefaultThetaBits;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    const size_t total = size_t{c.dim0} * c.dim1 * c.dim2;
    std::vector<float> x(total);
    for (size_t i = 0; i < total; ++i) {
      const int32_t v = static_cast<int32_t>((i * 11 + 5) % 19) - 9;
      x[i] = static_cast<float>(v) * 0.25f;
    }
    x[0] = -0.0f;
    c.src0_bytes = pack_f32_floats(x);
    compute_rope_ref(x, c.dim0, c.dim1, c.dim2, c.pos_offset, 10000.0, &c.expected_dst_f64);
    cases.push_back(std::move(c));
  }

  // 2. swiglu_fp32: large +/- regimes, -0.0f, fractional and cancellation inputs
  {
    OperatorCase c;
    c.name = "swiglu_fp32";
    c.op_code = va::kLlmOpSwigluFp32;
    c.dim0 = 4;
    c.dim1 = 8;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;
    std::vector<float> gate = {
        0.0f, -0.0f, 1.0f, -1.0f, 0.5f, -0.5f, 2.0f, -2.0f,
        5.0f, -5.0f, 20.0f, -20.0f, 90.0f, -90.0f, 0.125f, -0.125f,
        0.01f, -0.01f, 3.5f, -3.5f, 8.0f, -8.0f, 15.0f, -15.0f,
        -88.0f, 88.0f, 0.25f, -0.25f, 1.75f, -1.75f, 4.0f, -4.0f,
    };
    std::vector<float> up = {
        1.0f, 2.0f, 0.5f, -0.5f, -1.5f, 1.5f, 0.25f, -0.25f,
        0.1f, -1.0f, 0.05f, 2.0f, 0.01f, 3.0f, -2.0f, 2.0f,
        4.0f, -4.0f, 0.5f, 0.5f, -0.25f, 1.25f, 0.125f, -2.5f,
        1.0f, 0.5f, -3.0f, 3.0f, 0.75f, -0.75f, -0.5f, 0.5f,
    };
    c.src0_bytes = pack_f32_floats(gate);
    c.src1_bytes = pack_f32_floats(up);
    c.expected_dst_f64.resize(gate.size());
    for (size_t i = 0; i < gate.size(); ++i) {
      const double g = static_cast<double>(gate[i]);
      const double u = static_cast<double>(up[i]);
      const double sig = (g >= 0.0) ? (1.0 / (1.0 + std::exp(-g)))
                                    : (std::exp(g) / (1.0 + std::exp(g)));
      c.expected_dst_f64[i] = (g * sig) * u;
    }
    cases.push_back(std::move(c));
  }

  // 3. kv_cache_append_fp32: append n_new=3 into max_seq=16 at pos_offset=5 (bit-exact)
  {
    OperatorCase c;
    c.name = "kv_cache_append_fp32";
    c.op_code = va::kLlmOpKvCacheAppendFp32;
    c.dim0 = 3;  // n_new
    c.dim1 = 2;  // n_kv_heads
    c.dim2 = 16; // d_head
    c.dim3 = 16; // max_seq
    c.pos_offset = 5;
    c.check_mode = CheckMode::BitExact32;
    c.max_abs_tol = 0.0;

    const size_t row_elems = size_t{c.dim1} * c.dim2;
    const size_t new_elems = size_t{c.dim0} * row_elems;
    const size_t cache_elems = size_t{c.dim3} * row_elems;
    std::vector<float> k_new(new_elems);
    std::vector<float> v_new(new_elems);
    std::vector<float> k_init(cache_elems);
    std::vector<float> v_init(cache_elems);

    for (size_t i = 0; i < cache_elems; ++i) {
      k_init[i] = static_cast<float>(i) * 0.03125f - 2.0f;
      v_init[i] = static_cast<float>(i) * -0.0625f + 3.0f;
    }
    for (size_t i = 0; i < new_elems; ++i) {
      k_new[i] = static_cast<float>((i % 23) - 11) * 0.5f;
      v_new[i] = static_cast<float>((i % 19) - 9) * 0.75f;
    }
    k_new[0] = -0.0f;

    c.src0_bytes = pack_f32_floats(k_new);
    c.src1_bytes = pack_f32_floats(v_new);
    c.dst_init_bytes = pack_f32_floats(k_init);
    c.dst2_init_bytes = pack_f32_floats(v_init);

    std::vector<float> k_exp = k_init;
    std::vector<float> v_exp = v_init;
    const size_t base = size_t{c.pos_offset} * row_elems;
    for (size_t i = 0; i < new_elems; ++i) {
      k_exp[base + i] = k_new[i];
      v_exp[base + i] = v_new[i];
    }
    c.expected_dst_u32.resize(cache_elems);
    c.expected_dst2_u32.resize(cache_elems);
    for (size_t i = 0; i < cache_elems; ++i) {
      c.expected_dst_u32[i] = float_to_bits(k_exp[i]);
      c.expected_dst2_u32[i] = float_to_bits(v_exp[i]);
    }
    cases.push_back(std::move(c));
  }

  // 4. gqa_decode_attn_fp32: [1, n_q_heads=4, d_head=16] attending over [kv_len=16, n_kv_heads=2, d_head=16]
  {
    OperatorCase c;
    c.name = "gqa_decode_attn_fp32";
    c.op_code = va::kLlmOpGqaDecodeAttnFp32;
    c.dim0 = 16; // kv_len
    c.dim1 = 4;  // n_q_heads
    c.dim2 = 16; // d_head
    c.dim3 = 2;  // n_kv_heads
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    const size_t q_elems = size_t{c.dim1} * c.dim2;
    const size_t kv_elems = size_t{c.dim0} * c.dim3 * c.dim2;
    std::vector<float> q(q_elems);
    std::vector<float> k(kv_elems);
    std::vector<float> v(kv_elems);
    for (size_t i = 0; i < q_elems; ++i) {
      q[i] = static_cast<float>(static_cast<int32_t>((i * 5 + 1) % 13) - 6) * 0.25f;
    }
    for (size_t i = 0; i < kv_elems; ++i) {
      k[i] = static_cast<float>(static_cast<int32_t>((i * 7 + 3) % 15) - 7) * 0.25f;
      v[i] = static_cast<float>(static_cast<int32_t>((i * 3 + 2) % 11) - 5) * 0.5f;
    }
    c.src0_bytes = pack_f32_floats(q);
    c.src1_bytes = pack_f32_floats(k);
    c.src2_bytes = pack_f32_floats(v);
    compute_attention_ref(q, k, v, 1, c.dim0, c.dim1, c.dim3, c.dim2, false, 0, &c.expected_dst_f64);
    cases.push_back(std::move(c));
  }

  // 5a. flash_attn_tiled_noncausal_fp32: LMEM tiled [seq=16, n_q=2, d_head=16], n_kv=2
  {
    OperatorCase c;
    c.name = "flash_attn_tiled_noncausal_fp32";
    c.op_code = va::kLlmOpFlashAttnTiledFp32;
    c.flags = 0;
    c.dim0 = 16; // seq_len
    c.dim1 = 2;  // n_q_heads
    c.dim2 = 16; // d_head
    c.dim3 = 2;  // n_kv_heads
    c.block_x = 16;
    c.grid_x = ((c.dim0 + va::kLlmV3FlashTileBr - 1u) / va::kLlmV3FlashTileBr) * c.dim1;
    c.lmem_size = va::llm_ops_v3_detail::flash_lmem_bytes_required(c.dim2);
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    const size_t q_elems = size_t{c.dim0} * c.dim1 * c.dim2;
    const size_t kv_elems = size_t{c.dim0} * c.dim3 * c.dim2;
    std::vector<float> q(q_elems);
    std::vector<float> k(kv_elems);
    std::vector<float> v(kv_elems);
    for (size_t i = 0; i < q_elems; ++i) {
      q[i] = static_cast<float>(static_cast<int32_t>((i * 7 + 2) % 13) - 6) * 0.25f;
    }
    for (size_t i = 0; i < kv_elems; ++i) {
      k[i] = static_cast<float>(static_cast<int32_t>((i * 5 + 4) % 11) - 5) * 0.25f;
      v[i] = static_cast<float>(static_cast<int32_t>((i * 9 + 1) % 15) - 7) * 0.375f;
    }
    c.src0_bytes = pack_f32_floats(q);
    c.src1_bytes = pack_f32_floats(k);
    c.src2_bytes = pack_f32_floats(v);
    compute_attention_ref(q, k, v, c.dim0, c.dim0, c.dim1, c.dim3, c.dim2, false, 0, &c.expected_dst_f64);
    cases.push_back(std::move(c));
  }

  // 5b. flash_attn_tiled_causal_fp32: causal LMEM tiled [seq=16, n_q=4, d_head=16], n_kv=2
  {
    OperatorCase c;
    c.name = "flash_attn_tiled_causal_fp32";
    c.op_code = va::kLlmOpFlashAttnTiledFp32;
    c.flags = va::kLlmFlagCausal;
    c.dim0 = 16; // seq_len
    c.dim1 = 4;  // n_q_heads
    c.dim2 = 16; // d_head
    c.dim3 = 2;  // n_kv_heads
    c.block_x = 16;
    c.grid_x = ((c.dim0 + va::kLlmV3FlashTileBr - 1u) / va::kLlmV3FlashTileBr) * c.dim1;
    c.lmem_size = va::llm_ops_v3_detail::flash_lmem_bytes_required(c.dim2);
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    const size_t q_elems = size_t{c.dim0} * c.dim1 * c.dim2;
    const size_t kv_elems = size_t{c.dim0} * c.dim3 * c.dim2;
    std::vector<float> q(q_elems);
    std::vector<float> k(kv_elems);
    std::vector<float> v(kv_elems);
    for (size_t i = 0; i < q_elems; ++i) {
      q[i] = static_cast<float>(static_cast<int32_t>((i * 11 + 3) % 15) - 7) * 0.25f;
    }
    for (size_t i = 0; i < kv_elems; ++i) {
      k[i] = static_cast<float>(static_cast<int32_t>((i * 3 + 5) % 13) - 6) * 0.25f;
      v[i] = static_cast<float>(static_cast<int32_t>((i * 7 + 6) % 9) - 4) * 0.5f;
    }
    c.src0_bytes = pack_f32_floats(q);
    c.src1_bytes = pack_f32_floats(k);
    c.src2_bytes = pack_f32_floats(v);
    compute_attention_ref(q, k, v, c.dim0, c.dim0, c.dim1, c.dim3, c.dim2, true, 0, &c.expected_dst_f64);
    cases.push_back(std::move(c));
  }

  // 6. rmsnorm_fp32: rows=4, cols=16
  {
    OperatorCase c;
    c.name = "rmsnorm_fp32";
    c.op_code = va::kLlmOpRmsNormFp32;
    c.dim0 = 4;
    c.dim1 = 16;
    c.eps_or_theta_bits = va::kLlmV3DefaultEpsBits;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    std::vector<float> x(size_t{c.dim0} * c.dim1);
    std::vector<float> w(c.dim1);
    for (size_t i = 0; i < x.size(); ++i) {
      x[i] = (i < c.dim1) ? 0.0f : static_cast<float>(static_cast<int32_t>((i * 5 + 1) % 13) - 6) * 0.5f;
    }
    x[1] = -0.0f;
    for (size_t i = 0; i < w.size(); ++i) {
      w[i] = 0.75f + static_cast<float>(static_cast<int32_t>(i % 5) - 2) * 0.25f;
    }
    c.src0_bytes = pack_f32_floats(x);
    c.src1_bytes = pack_f32_floats(w);
    c.expected_dst_f64.resize(x.size());
    const double eps = static_cast<double>(bits_to_float(c.eps_or_theta_bits));
    for (uint32_t r = 0; r < c.dim0; ++r) {
      double sq = 0.0;
      for (uint32_t col = 0; col < c.dim1; ++col) {
        const double val = static_cast<double>(x[r * c.dim1 + col]);
        sq += val * val;
      }
      const double inv_rms = 1.0 / std::sqrt(sq / static_cast<double>(c.dim1) + eps);
      for (uint32_t col = 0; col < c.dim1; ++col) {
        c.expected_dst_f64[r * c.dim1 + col] =
            static_cast<double>(x[r * c.dim1 + col]) * inv_rms * static_cast<double>(w[col]);
      }
    }
    cases.push_back(std::move(c));
  }

  // 7. add_fp32: residual vector/matrix add [4, 16]
  {
    OperatorCase c;
    c.name = "add_fp32";
    c.op_code = va::kLlmOpAddFp32;
    c.dim0 = 4;
    c.dim1 = 16;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    const size_t total = size_t{c.dim0} * c.dim1;
    std::vector<float> a(total);
    std::vector<float> b(total);
    c.expected_dst_f64.resize(total);
    for (size_t i = 0; i < total; ++i) {
      a[i] = static_cast<float>(static_cast<int32_t>((i * 7) % 17) - 8) * 0.25f;
      b[i] = static_cast<float>(static_cast<int32_t>((i * 5 + 3) % 15) - 7) * 0.5f;
      c.expected_dst_f64[i] = static_cast<double>(a[i]) + static_cast<double>(b[i]);
    }
    c.src0_bytes = pack_f32_floats(a);
    c.src1_bytes = pack_f32_floats(b);
    cases.push_back(std::move(c));
  }

  // 8a. gemv_decode_fp32: single-token linear projection A[1, 32] @ B[16, 32]^T
  {
    OperatorCase c;
    c.name = "gemv_decode_fp32";
    c.op_code = va::kLlmOpGemvFp32;
    c.dim0 = 1;  // M
    c.dim1 = 32; // K
    c.dim2 = 16; // N
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    std::vector<float> a(size_t{c.dim0} * c.dim1);
    std::vector<float> b(size_t{c.dim2} * c.dim1);
    for (size_t i = 0; i < a.size(); ++i) {
      a[i] = static_cast<float>(static_cast<int32_t>((i * 3 + 1) % 11) - 5) * 0.25f;
    }
    for (size_t i = 0; i < b.size(); ++i) {
      b[i] = static_cast<float>(static_cast<int32_t>((i * 7 + 2) % 13) - 6) * 0.125f;
    }
    c.src0_bytes = pack_f32_floats(a);
    c.src1_bytes = pack_f32_floats(b);
    c.expected_dst_f64.resize(size_t{c.dim0} * c.dim2);
    for (uint32_t m = 0; m < c.dim0; ++m) {
      for (uint32_t n = 0; n < c.dim2; ++n) {
        double dot = 0.0;
        for (uint32_t k = 0; k < c.dim1; ++k) {
          dot += static_cast<double>(a[m * c.dim1 + k]) * static_cast<double>(b[n * c.dim1 + k]);
        }
        c.expected_dst_f64[m * c.dim2 + n] = dot;
      }
    }
    cases.push_back(std::move(c));
  }

  // 8b. gemm_prefill_fp32: multi-row prefill linear projection A[8, 16] @ B[24, 16]^T
  {
    OperatorCase c;
    c.name = "gemm_prefill_fp32";
    c.op_code = va::kLlmOpGemvFp32;
    c.dim0 = 8;  // M
    c.dim1 = 16; // K
    c.dim2 = 24; // N
    c.grid_x = 4;
    c.block_x = 16;
    c.check_mode = CheckMode::MaxAbsErrF32;
    c.max_abs_tol = kApproxMaxAbsErr;

    std::vector<float> a(size_t{c.dim0} * c.dim1);
    std::vector<float> b(size_t{c.dim2} * c.dim1);
    for (size_t i = 0; i < a.size(); ++i) {
      a[i] = static_cast<float>(static_cast<int32_t>((i * 5 + 4) % 13) - 6) * 0.25f;
    }
    for (size_t i = 0; i < b.size(); ++i) {
      b[i] = static_cast<float>(static_cast<int32_t>((i * 9 + 1) % 15) - 7) * 0.125f;
    }
    c.src0_bytes = pack_f32_floats(a);
    c.src1_bytes = pack_f32_floats(b);
    c.expected_dst_f64.resize(size_t{c.dim0} * c.dim2);
    for (uint32_t m = 0; m < c.dim0; ++m) {
      for (uint32_t n = 0; n < c.dim2; ++n) {
        double dot = 0.0;
        for (uint32_t k = 0; k < c.dim1; ++k) {
          dot += static_cast<double>(a[m * c.dim1 + k]) * static_cast<double>(b[n * c.dim1 + k]);
        }
        c.expected_dst_f64[m * c.dim2 + n] = dot;
      }
    }
    cases.push_back(std::move(c));
  }

  return cases;
}

bool check_f32_buffer(const OperatorCase& op_case, const char* buf_label, uint32_t iter,
                      const std::vector<uint8_t>& actual_bytes,
                      const std::vector<uint32_t>& expected_u32,
                      const std::vector<double>& expected_f64,
                      uint32_t* total_mismatches, uint32_t* case_mismatches,
                      double* observed_max_abs_err) {
  const size_t count = actual_bytes.size() / 4;
  if (op_case.check_mode == CheckMode::BitExact32) {
    for (size_t i = 0; i < count; ++i) {
      const uint32_t actual = read_u32_le(actual_bytes.data() + i * 4);
      const uint32_t expected = expected_u32[i];
      if (actual != expected) {
        if (*total_mismatches + *case_mismatches < kMaxPrintedErrors) {
          std::printf("*** mismatch [%s:%s iter=%u idx=%zu] expected=0x%08x actual=0x%08x\n",
                      op_case.name.c_str(), buf_label, iter, i, expected, actual);
        }
        ++(*case_mismatches);
      }
    }
    return true;
  }

  for (size_t i = 0; i < count; ++i) {
    const uint32_t actual_bits = read_u32_le(actual_bytes.data() + i * 4);
    const float actual_f32 = bits_to_float(actual_bits);
    const double expected = expected_f64[i];
    const double err = std::fabs(static_cast<double>(actual_f32) - expected);
    if (!std::isfinite(actual_f32) || err > *observed_max_abs_err) {
      *observed_max_abs_err = std::isfinite(actual_f32) ? err : INFINITY;
    }
    if (!std::isfinite(actual_f32) || err > op_case.max_abs_tol) {
      if (*total_mismatches + *case_mismatches < kMaxPrintedErrors) {
        std::printf("*** mismatch [%s:%s iter=%u idx=%zu] expected=%.8g actual=%.8g err=%.3e\n",
                    op_case.name.c_str(), buf_label, iter, i, expected,
                    static_cast<double>(actual_f32), err);
      }
      ++(*case_mismatches);
    }
  }
  return true;
}

bool run_case(const DeviceSession& session, const OperatorCase& op_case,
              uint32_t iterations, uint32_t* total_mismatches, uint64_t* checked_elems) {
  const uint64_t dst_bytes_size =
      (op_case.check_mode == CheckMode::BitExact32)
          ? (uint64_t{op_case.expected_dst_u32.size()} * 4)
          : (uint64_t{op_case.expected_dst_f64.size()} * 4);
  const uint64_t dst2_bytes_size = uint64_t{op_case.expected_dst2_u32.size()} * 4;

  BufferHandle src0_buf;
  BufferHandle src1_buf;
  BufferHandle src2_buf;
  BufferHandle dst_buf;
  BufferHandle dst2_buf;

  VX_CHECK(vx_buffer_create(session.device, op_case.src0_bytes.size(), VX_MEM_READ, &src0_buf.h));
  if (!op_case.src1_bytes.empty()) {
    VX_CHECK(vx_buffer_create(session.device, op_case.src1_bytes.size(), VX_MEM_READ, &src1_buf.h));
  }
  if (!op_case.src2_bytes.empty()) {
    VX_CHECK(vx_buffer_create(session.device, op_case.src2_bytes.size(), VX_MEM_READ, &src2_buf.h));
  }
  VX_CHECK(vx_buffer_create(session.device, dst_bytes_size, VX_MEM_READ_WRITE, &dst_buf.h));
  if (dst2_bytes_size > 0) {
    VX_CHECK(vx_buffer_create(session.device, dst2_bytes_size, VX_MEM_READ_WRITE, &dst2_buf.h));
  }

  va::LlmOpsV3Arguments arg{};
  arg.op_code = op_case.op_code;
  arg.flags = op_case.flags;
  arg.dim0 = op_case.dim0;
  arg.dim1 = op_case.dim1;
  arg.dim2 = op_case.dim2;
  arg.dim3 = op_case.dim3;
  arg.pos_offset = op_case.pos_offset;
  arg.eps_or_theta_bits = op_case.eps_or_theta_bits;
  VX_CHECK(vx_buffer_address(src0_buf.h, &arg.src0_addr));
  if (src1_buf.h) {
    VX_CHECK(vx_buffer_address(src1_buf.h, &arg.src1_addr));
  }
  if (src2_buf.h) {
    VX_CHECK(vx_buffer_address(src2_buf.h, &arg.src2_addr));
  }
  VX_CHECK(vx_buffer_address(dst_buf.h, &arg.dst_addr));
  if (dst2_buf.h) {
    VX_CHECK(vx_buffer_address(dst2_buf.h, &arg.dst2_addr));
  }

  std::vector<uint8_t> init_dst(dst_bytes_size);
  std::vector<uint8_t> dst_bytes(dst_bytes_size);
  std::vector<uint8_t> dst2_bytes(dst2_bytes_size);

  for (uint32_t iter = 0; iter < iterations; ++iter) {
    if (!op_case.dst_init_bytes.empty()) {
      init_dst = op_case.dst_init_bytes;
    } else {
      const uint8_t poison_byte = (iter & 1u) == 0 ? 0xa5u : 0x5au;
      std::fill(init_dst.begin(), init_dst.end(), poison_byte);
    }
    std::fill(dst_bytes.begin(), dst_bytes.end(), static_cast<uint8_t>(0x3cu));
    std::fill(dst2_bytes.begin(), dst2_bytes.end(), static_cast<uint8_t>(0x3cu));

    EventHandle ev_w0;
    EventHandle ev_w1;
    EventHandle ev_w2;
    EventHandle ev_dst;
    EventHandle ev_dst2;
    EventHandle ev_launch;
    EventHandle ev_read;
    EventHandle ev_read2;

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
    VX_CHECK(vx_enqueue_write(session.queue, dst_buf.h, 0, init_dst.data(),
                              init_dst.size(), 1, &dep, &ev_dst.h));
    dep = ev_dst.h;
    if (dst2_buf.h) {
      VX_CHECK(vx_enqueue_write(session.queue, dst2_buf.h, 0, op_case.dst2_init_bytes.data(),
                                op_case.dst2_init_bytes.size(), 1, &dep, &ev_dst2.h));
      dep = ev_dst2.h;
    }

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
    li.lmem_size = op_case.lmem_size;
    li.cluster_dim[0] = 1;
    li.cluster_dim[1] = 1;
    li.cluster_dim[2] = 1;

    VX_CHECK(vx_enqueue_launch(session.queue, &li, 1, &dep, &ev_launch.h));
    VX_CHECK(vx_enqueue_read(session.queue, dst_bytes.data(), dst_buf.h, 0,
                             dst_bytes.size(), 1, &ev_launch.h, &ev_read.h));
    vx_event_h wait_ev = ev_read.h;
    if (dst2_buf.h) {
      VX_CHECK(vx_enqueue_read(session.queue, dst2_bytes.data(), dst2_buf.h, 0,
                               dst2_bytes.size(), 1, &ev_read.h, &ev_read2.h));
      wait_ev = ev_read2.h;
    }
    VX_CHECK(vx_event_wait_value(wait_ev, 1, VX_TIMEOUT_INFINITE));

    ev_w0.release();
    ev_w1.release();
    ev_w2.release();
    ev_dst.release();
    ev_dst2.release();
    ev_launch.release();
    ev_read.release();
    ev_read2.release();

    uint32_t case_mismatches = 0;
    double observed_max_abs_err = 0.0;
    check_f32_buffer(op_case, "dst", iter, dst_bytes, op_case.expected_dst_u32,
                     op_case.expected_dst_f64, total_mismatches, &case_mismatches,
                     &observed_max_abs_err);
    if (dst2_buf.h) {
      check_f32_buffer(op_case, "dst2", iter, dst2_bytes, op_case.expected_dst2_u32,
                       op_case.expected_dst_f64, total_mismatches, &case_mismatches,
                       &observed_max_abs_err);
    }

    const uint64_t count = (dst_bytes_size + dst2_bytes_size) / 4;
    *checked_elems += count;
    *total_mismatches += case_mismatches;
    std::printf("LLM_V3_CASE name=%s op_code=%u iter=%u dims=[%u,%u,%u,%u] count=%llu "
                "lmem=%u max_abs_err=%.6e tol=%.6e mismatches=%u\n",
                op_case.name.c_str(), op_case.op_code, iter,
                op_case.dim0, op_case.dim1, op_case.dim2, op_case.dim3,
                static_cast<unsigned long long>(count), op_case.lmem_size,
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
    if (!run_case(session, *c, opts.iterations, &total_mismatches, &total_elements)) {
      return 1;
    }
  }

  std::printf("LLM_V3_SUMMARY cases=%zu iterations=%u total_elements=%llu total_mismatches=%u\n",
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
