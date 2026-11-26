// SPDX-License-Identifier: Apache-2.0

#include <ai_llm_ops_v3_args.h>
#include <vx_intrinsics.h>
#include <vx_spawn2.h>

static_assert(sizeof(uintptr_t) == 8);

namespace va = vortex::ai;

namespace {

__attribute__((always_inline)) inline uint32_t f32_to_bits(float value) {
  uint32_t bits = 0;
  __builtin_memcpy(&bits, &value, sizeof(bits));
  return bits;
}

__attribute__((always_inline)) inline float bits_to_f32(uint32_t bits) {
  float value = 0.0f;
  __builtin_memcpy(&value, &bits, sizeof(value));
  return value;
}

__attribute__((always_inline)) inline float device_sqrtf(float x) {
  float out = 0.0f;
  __asm__ ("fsqrt.s %0, %1" : "=f"(out) : "f"(x));
  return out;
}

// Self-contained device expf using Cody-Waite range reduction and degree-6 Horner polynomial.
__attribute__((always_inline)) inline float fast_expf(float x) {
  const uint32_t bits = f32_to_bits(x);
  if ((bits & 0x7fffffffu) > 0x7f800000u) {
    return x;
  }
  if (x <= -88.0f) {
    return 0.0f;
  }
  if (x >= 88.0f) {
    return bits_to_f32(0x7f800000u);
  }

  constexpr float kInvLn2 = 1.44269504088896341f;
  constexpr float kLn2Hi = 0.693145751953125f;
  constexpr float kLn2Lo = 1.4286068203094172e-6f;

  const float scaled = x * kInvLn2;
  const int32_t k = (scaled >= 0.0f)
      ? static_cast<int32_t>(scaled + 0.5f)
      : static_cast<int32_t>(scaled - 0.5f);
  if (k <= -127) {
    return 0.0f;
  }
  const float kf = static_cast<float>(k);

  const float r = (x - kf * kLn2Hi) - kf * kLn2Lo;
  const float p = 1.0f + r * (1.0f + r * (0.5f + r * (0.16666667f
      + r * (0.041666668f + r * (0.008333334f + r * 0.0013888889f)))));

  const uint32_t pow2_bits = static_cast<uint32_t>(k + 127) << 23;
  return p * bits_to_f32(pow2_bits);
}

// Self-contained device logf for arbitrary positive finite RoPE base theta.
__attribute__((always_inline)) inline float fast_logf(float x) {
  const uint32_t bits = f32_to_bits(x);
  if ((bits & 0x7fffffffu) > 0x7f800000u || x < 0.0f) {
    return bits_to_f32(0x7fc00000u);
  }
  if (x == 0.0f) {
    return bits_to_f32(0xff800000u);
  }
  if (bits == 0x7f800000u) {
    return x;
  }

  int32_t exp_val = static_cast<int32_t>((bits >> 23) & 0xffu) - 127;
  uint32_t mant_bits = bits & 0x007fffffu;
  if (exp_val == -127) {
    while ((mant_bits & 0x00800000u) == 0u) {
      mant_bits <<= 1;
      --exp_val;
    }
    mant_bits &= 0x007fffffu;
  }
  float m = bits_to_f32(mant_bits | (127u << 23));
  if (m > 1.41421356237f) {
    m *= 0.5f;
    ++exp_val;
  }

  const float y = (m - 1.0f) / (m + 1.0f);
  const float y2 = y * y;
  const float poly = 1.0f + y2 * (0.33333334f + y2 * (0.2f
      + y2 * (0.14285715f + y2 * 0.11111111f)));
  const float ln_m = 2.0f * y * poly;

  constexpr float kLn2Hi = 0.693145751953125f;
  constexpr float kLn2Lo = 1.4286068203094172e-6f;
  const float ef = static_cast<float>(exp_val);
  return (ef * kLn2Hi) + (ef * kLn2Lo + ln_m);
}

// Cody-Waite quadrant reduction modulo pi/2 and minimax degree-9/8 polynomials.
__attribute__((always_inline)) inline void fast_sincosf(float x, float* out_sin, float* out_cos) {
  const uint32_t bits = f32_to_bits(x);
  if ((bits & 0x7fffffffu) >= 0x7f800000u) {
    const float nan_val = bits_to_f32(0x7fc00000u);
    *out_sin = nan_val;
    *out_cos = nan_val;
    return;
  }

  constexpr float kInvPiOver2 = 0.63661977236758138243f;
  constexpr float kPiOver2_1 = 1.57079625129699707031e+00f;
  constexpr float kPiOver2_2 = 7.54978941586159635335e-08f;
  constexpr float kPiOver2_3 = 5.39030252995776476554e-15f;

  const float scaled = x * kInvPiOver2;
  const int32_t q = (scaled >= 0.0f)
      ? static_cast<int32_t>(scaled + 0.5f)
      : static_cast<int32_t>(scaled - 0.5f);
  const float qf = static_cast<float>(q);

  const float r = ((x - qf * kPiOver2_1) - qf * kPiOver2_2) - qf * kPiOver2_3;
  const float r2 = r * r;

  const float s_r = r * (1.0f + r2 * (-0.1666666716337204f
      + r2 * (0.008333333767950535f
      + r2 * (-0.00019841270113829523f + r2 * 2.7557319223985893e-6f))));
  const float c_r = 1.0f + r2 * (-0.5f
      + r2 * (0.0416666679084301f
      + r2 * (-0.0013888889225199819f + r2 * 2.480158728947673e-5f)));

  const uint32_t quad = static_cast<uint32_t>(q) & 3u;
  if (quad == 0u) {
    *out_sin = s_r;
    *out_cos = c_r;
  } else if (quad == 1u) {
    *out_sin = c_r;
    *out_cos = -s_r;
  } else if (quad == 2u) {
    *out_sin = -s_r;
    *out_cos = -c_r;
  } else {
    *out_sin = -c_r;
    *out_cos = s_r;
  }
}

__attribute__((always_inline)) inline float fast_sinf(float x) {
  float s = 0.0f;
  float c = 0.0f;
  fast_sincosf(x, &s, &c);
  return s;
}

__attribute__((always_inline)) inline float fast_cosf(float x) {
  float s = 0.0f;
  float c = 0.0f;
  fast_sincosf(x, &s, &c);
  return c;
}

__attribute__((always_inline)) inline float stable_silu(float x) {
  const uint32_t bits = f32_to_bits(x);
  if ((bits & 0x7fffffffu) > 0x7f800000u) {
    return x;
  }
  if (x >= 0.0f) {
    return x / (1.0f + fast_expf(-x));
  }
  const float e = fast_expf(x);
  return (x * e) / (1.0f + e);
}

void run_rope(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const float*>(arg.src0_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);

  const uint32_t seq_len = arg.dim0;
  const uint32_t n_heads = arg.dim1;
  const uint32_t d_head = arg.dim2;
  const uint32_t half_dim = d_head >> 1;
  const uint32_t total_pairs = seq_len * n_heads * half_dim;

  constexpr float kLn10000 = 9.210340371976184f;
  const float log_theta = (arg.eps_or_theta_bits == va::kLlmV3DefaultThetaBits)
      ? kLn10000
      : fast_logf(bits_to_f32(arg.eps_or_theta_bits));
  const float inv_d_head = 1.0f / static_cast<float>(d_head);

  for (uint32_t idx = tid; idx < total_pairs; idx += stride) {
    const uint32_t pair = idx % half_dim;
    const uint32_t head_seq = idx / half_dim;
    const uint32_t head = head_seq % n_heads;
    const uint32_t seq = head_seq / n_heads;

    const float pos = static_cast<float>(arg.pos_offset + seq);
    const float inv_freq = fast_expf(-static_cast<float>(2u * pair) * inv_d_head * log_theta);
    const float angle = pos * inv_freq;
    const float s = fast_sinf(angle);
    const float c = fast_cosf(angle);

    const uint32_t base = (seq * n_heads + head) * d_head;
    const float x0 = src[base + pair];
    const float x1 = src[base + pair + half_dim];
    dst[base + pair] = x0 * c - x1 * s;
    dst[base + pair + half_dim] = x0 * s + x1 * c;
  }
}

void run_swiglu(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto gate = reinterpret_cast<const float*>(arg.src0_addr);
  auto up = reinterpret_cast<const float*>(arg.src1_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t total = arg.dim0 * arg.dim1;

  for (uint32_t idx = tid; idx < total; idx += stride) {
    dst[idx] = stable_silu(gate[idx]) * up[idx];
  }
}

void run_kv_cache_append(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto k_new = reinterpret_cast<const uint32_t*>(arg.src0_addr);
  auto v_new = reinterpret_cast<const uint32_t*>(arg.src1_addr);
  auto k_cache = reinterpret_cast<uint32_t*>(arg.dst_addr);
  auto v_cache = reinterpret_cast<uint32_t*>(arg.dst2_addr);

  const uint32_t n_new = arg.dim0;
  const uint32_t n_kv_heads = arg.dim1;
  const uint32_t d_head = arg.dim2;
  const uint32_t row_elems = n_kv_heads * d_head;
  const uint32_t total_elems = n_new * row_elems;
  const uint32_t cache_base = arg.pos_offset * row_elems;

  for (uint32_t idx = tid; idx < total_elems; idx += stride) {
    k_cache[cache_base + idx] = k_new[idx];
    v_cache[cache_base + idx] = v_new[idx];
  }
}

void run_gqa_decode_attn(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto q = reinterpret_cast<const float*>(arg.src0_addr);
  auto k_cache = reinterpret_cast<const float*>(arg.src1_addr);
  auto v_cache = reinterpret_cast<const float*>(arg.src2_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);

  const uint32_t kv_len = arg.dim0;
  const uint32_t n_q_heads = arg.dim1;
  const uint32_t d_head = arg.dim2;
  const uint32_t n_kv_heads = arg.dim3;
  const uint32_t group_size = n_q_heads / n_kv_heads;
  const uint32_t kv_row_stride = n_kv_heads * d_head;
  const float inv_sqrt_d = 1.0f / device_sqrtf(static_cast<float>(d_head));

  for (uint32_t qh = tid; qh < n_q_heads; qh += stride) {
    const uint32_t kvh = qh / group_size;
    const float* q_ptr = q + qh * d_head;
    float* out_ptr = dst + qh * d_head;

    for (uint32_t d = 0; d < d_head; ++d) {
      out_ptr[d] = 0.0f;
    }

    float m_i = -bits_to_f32(0x7f7fffffu);
    float l_i = 0.0f;

    for (uint32_t t = 0; t < kv_len; ++t) {
      const float* k_ptr = k_cache + t * kv_row_stride + kvh * d_head;
      const float* v_ptr = v_cache + t * kv_row_stride + kvh * d_head;

      float dot = 0.0f;
      for (uint32_t d = 0; d < d_head; ++d) {
        dot += q_ptr[d] * k_ptr[d];
      }
      const float s = dot * inv_sqrt_d;
      const float m_new = (s > m_i) ? s : m_i;
      const float alpha = fast_expf(m_i - m_new);
      const float p = fast_expf(s - m_new);
      l_i = l_i * alpha + p;

      for (uint32_t d = 0; d < d_head; ++d) {
        out_ptr[d] = out_ptr[d] * alpha + p * v_ptr[d];
      }
      m_i = m_new;
    }

    const float inv_l = 1.0f / l_i;
    for (uint32_t d = 0; d < d_head; ++d) {
      out_ptr[d] *= inv_l;
    }
  }
}

void run_flash_attn_tiled(const va::LlmOpsV3Arguments& arg) {
  auto q = reinterpret_cast<const float*>(arg.src0_addr);
  auto k = reinterpret_cast<const float*>(arg.src1_addr);
  auto v = reinterpret_cast<const float*>(arg.src2_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);

  const uint32_t seq_len = arg.dim0;
  const uint32_t n_q_heads = arg.dim1;
  const uint32_t d_head = arg.dim2;
  const uint32_t n_kv_heads = arg.dim3;
  const uint32_t group_size = n_q_heads / n_kv_heads;
  const uint32_t q_row_stride = n_q_heads * d_head;
  const uint32_t kv_row_stride = n_kv_heads * d_head;
  const bool causal = (arg.flags & va::kLlmFlagCausal) != 0u;
  const float inv_sqrt_d = 1.0f / device_sqrtf(static_cast<float>(d_head));

  constexpr uint32_t kBr = va::kLlmV3FlashTileBr;
  constexpr uint32_t kBc = va::kLlmV3FlashTileBc;
  const uint32_t num_row_tiles = (seq_len + kBr - 1u) / kBr;
  const uint32_t total_blocks = num_row_tiles * n_q_heads;
  if (blockIdx.x >= total_blocks) {
    return;
  }

  const uint32_t qh = blockIdx.x % n_q_heads;
  const uint32_t row_tile = blockIdx.x / n_q_heads;
  const uint32_t row_base = row_tile * kBr;
  const uint32_t kvh = qh / group_size;

  const uint32_t local_tid = threadIdx.x;
  const uint32_t block_threads = blockDim.x;
  const uint32_t br_elems = kBr * d_head;
  const uint32_t bc_elems = kBc * d_head;

  auto lmem = reinterpret_cast<float*>(__local_mem());
  float* s_q = lmem;
  float* s_o = s_q + br_elems;
  float* s_k = s_o + br_elems;
  float* s_v = s_k + bc_elems;
  float* s_p = s_v + bc_elems;

  for (uint32_t idx = local_tid; idx < br_elems; idx += block_threads) {
    const uint32_t r = idx / d_head;
    const uint32_t d = idx % d_head;
    const uint32_t g_row = row_base + r;
    s_q[idx] = (g_row < seq_len) ? q[g_row * q_row_stride + qh * d_head + d] : 0.0f;
    s_o[idx] = 0.0f;
  }
  __syncthreads();

  // Keep per-row running max/sum in lane registers when block_threads >= kBr;
  // lanes beyond kBr participate in parallel K/V staging and S/O tile updates.
  float m_i = -bits_to_f32(0x7f7fffffu);
  float l_i = 0.0f;
  const uint32_t r_lane = local_tid;
  const bool row_owner = (r_lane < kBr) && ((row_base + r_lane) < seq_len);

  for (uint32_t col_base = 0; col_base < seq_len; col_base += kBc) {
    for (uint32_t idx = local_tid; idx < bc_elems; idx += block_threads) {
      const uint32_t c = idx / d_head;
      const uint32_t d = idx % d_head;
      const uint32_t g_col = col_base + c;
      if (g_col < seq_len) {
        const uint32_t g_off = g_col * kv_row_stride + kvh * d_head + d;
        s_k[idx] = k[g_off];
        s_v[idx] = v[g_off];
      } else {
        s_k[idx] = 0.0f;
        s_v[idx] = 0.0f;
      }
    }
    __syncthreads();

    for (uint32_t rc = local_tid; rc < kBr * kBc; rc += block_threads) {
      const uint32_t r = rc / kBc;
      const uint32_t c = rc % kBc;
      const uint32_t g_row = row_base + r;
      const uint32_t g_col = col_base + c;
      if (g_row >= seq_len || g_col >= seq_len
          || (causal && g_col > (g_row + arg.pos_offset))) {
        s_p[rc] = -bits_to_f32(0x7f7fffffu);
      } else {
        const float* q_row = s_q + r * d_head;
        const float* k_row = s_k + c * d_head;
        float dot = 0.0f;
        for (uint32_t d = 0; d < d_head; ++d) {
          dot += q_row[d] * k_row[d];
        }
        s_p[rc] = dot * inv_sqrt_d;
      }
    }
    __syncthreads();

    if (row_owner) {
      float* p_row = s_p + r_lane * kBc;
      float* o_row = s_o + r_lane * d_head;

      float tile_max = p_row[0];
      for (uint32_t c = 1; c < kBc; ++c) {
        if (p_row[c] > tile_max) {
          tile_max = p_row[c];
        }
      }

      if (tile_max > -1e30f) {
        const float m_new = (tile_max > m_i) ? tile_max : m_i;
        const float alpha = (l_i == 0.0f) ? 0.0f : fast_expf(m_i - m_new);

        float tile_sum = 0.0f;
        for (uint32_t c = 0; c < kBc; ++c) {
          const uint32_t g_col = col_base + c;
          if (g_col < seq_len && (!causal || g_col <= (row_base + r_lane + arg.pos_offset))) {
            const float p_val = fast_expf(p_row[c] - m_new);
            p_row[c] = p_val;
            tile_sum += p_val;
          } else {
            p_row[c] = 0.0f;
          }
        }

        const float l_new = l_i * alpha + tile_sum;
        for (uint32_t d = 0; d < d_head; ++d) {
          float pv = 0.0f;
          for (uint32_t c = 0; c < kBc; ++c) {
            pv += p_row[c] * s_v[c * d_head + d];
          }
          o_row[d] = o_row[d] * alpha + pv;
        }
        m_i = m_new;
        l_i = l_new;
      }
    }
    __syncthreads();
  }

  if (row_owner) {
    const float inv_l = (l_i > 0.0f) ? (1.0f / l_i) : 0.0f;
    const uint32_t g_row = row_base + r_lane;
    const float* o_row = s_o + r_lane * d_head;
    float* dst_row = dst + g_row * q_row_stride + qh * d_head;
    for (uint32_t d = 0; d < d_head; ++d) {
      dst_row[d] = o_row[d] * inv_l;
    }
  }
}

void run_rmsnorm(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const float*>(arg.src0_addr);
  auto weight = reinterpret_cast<const float*>(arg.src1_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t rows = arg.dim0;
  const uint32_t cols = arg.dim1;
  const float eps = bits_to_f32(arg.eps_or_theta_bits);
  const float inv_cols = 1.0f / static_cast<float>(cols);

  for (uint32_t row = tid; row < rows; row += stride) {
    const float* x_row = src + row * cols;
    float* y_row = dst + row * cols;

    float sq_sum = 0.0f;
    for (uint32_t c = 0; c < cols; ++c) {
      const float v = x_row[c];
      sq_sum += v * v;
    }
    const float inv_rms = 1.0f / device_sqrtf(sq_sum * inv_cols + eps);
    for (uint32_t c = 0; c < cols; ++c) {
      y_row[c] = x_row[c] * inv_rms * weight[c];
    }
  }
}

void run_add(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto a = reinterpret_cast<const float*>(arg.src0_addr);
  auto b = reinterpret_cast<const float*>(arg.src1_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t total = arg.dim0 * arg.dim1;

  for (uint32_t idx = tid; idx < total; idx += stride) {
    dst[idx] = a[idx] + b[idx];
  }
}

void run_gemv(const va::LlmOpsV3Arguments& arg, uint32_t tid, uint32_t stride) {
  auto a = reinterpret_cast<const float*>(arg.src0_addr);
  auto b = reinterpret_cast<const float*>(arg.src1_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);

  const uint32_t m = arg.dim0;
  const uint32_t k = arg.dim1;
  const uint32_t n = arg.dim2;
  const uint32_t total = m * n;

  for (uint32_t idx = tid; idx < total; idx += stride) {
    const uint32_t col = idx % n;
    const uint32_t row = idx / n;
    const float* a_row = a + row * k;
    const float* b_row = b + col * k;

    float dot = 0.0f;
    for (uint32_t kk = 0; kk < k; ++kk) {
      dot += a_row[kk] * b_row[kk];
    }
    dst[row * n + col] = dot;
  }
}

} // namespace

__kernel void kernel_main(const uint8_t* __UNIFORM__ bytes) {
  alignas(va::LlmOpsV3Arguments) uint8_t arg_storage[sizeof(va::LlmOpsV3Arguments)];
  auto* arg_ptr = reinterpret_cast<va::LlmOpsV3Arguments*>(arg_storage);
  if (!va::decode_llm_ops_v3_arguments(bytes, va::kLlmOpsV3ArgumentBytes, arg_ptr)
      || blockDim.y != 1 || blockDim.z != 1
      || gridDim.y != 1 || gridDim.z != 1
      || blockIdx.y != 0 || blockIdx.z != 0) {
    return;
  }
  const va::LlmOpsV3Arguments& arg = *arg_ptr;

  if (arg.op_code == va::kLlmOpFlashAttnTiledFp32) {
    if (blockDim.x < va::kLlmV3FlashTileBr) {
      return;
    }
    run_flash_attn_tiled(arg);
    return;
  }

  const uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
  const uint32_t stride = gridDim.x * blockDim.x;
  if (stride == 0) {
    return;
  }

  switch (arg.op_code) {
    case va::kLlmOpRopeFp32:
      run_rope(arg, tid, stride);
      break;
    case va::kLlmOpSwigluFp32:
      run_swiglu(arg, tid, stride);
      break;
    case va::kLlmOpKvCacheAppendFp32:
      run_kv_cache_append(arg, tid, stride);
      break;
    case va::kLlmOpGqaDecodeAttnFp32:
      run_gqa_decode_attn(arg, tid, stride);
      break;
    case va::kLlmOpRmsNormFp32:
      run_rmsnorm(arg, tid, stride);
      break;
    case va::kLlmOpAddFp32:
      run_add(arg, tid, stride);
      break;
    case va::kLlmOpGemvFp32:
      run_gemv(arg, tid, stride);
      break;
    default:
      break;
  }
}
