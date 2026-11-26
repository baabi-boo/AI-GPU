// SPDX-License-Identifier: Apache-2.0

#include <ai_ops_v2_args.h>
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

__attribute__((always_inline)) inline float device_absf(float x) {
  return bits_to_f32(f32_to_bits(x) & 0x7fffffffu);
}

// Self-contained device expf using Cody-Waite range reduction and degree-6 Horner polynomial.
__attribute__((always_inline)) inline float fast_expf(float x) {
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
  const float kf = static_cast<float>(k);

  const float r = (x - kf * kLn2Hi) - kf * kLn2Lo;
  const float p = 1.0f + r * (1.0f + r * (0.5f + r * (0.16666667f
      + r * (0.041666668f + r * (0.008333334f + r * 0.0013888889f)))));

  const uint32_t pow2_bits = static_cast<uint32_t>(k + 127) << 23;
  return p * bits_to_f32(pow2_bits);
}

// Self-contained tanh avoiding catastrophic cancellation near zero.
__attribute__((always_inline)) inline float fast_tanhf(float x) {
  if (x > 10.0f) {
    return 1.0f;
  }
  if (x < -10.0f) {
    return -1.0f;
  }
  if (device_absf(x) < 0.25f) {
    const float x2 = x * x;
    return x * (1.0f + x2 * (-0.33333334f + x2 * (0.13333334f
        + x2 * (-0.053968254f + x2 * 0.021869488f))));
  }
  const float e2x = fast_expf(2.0f * x);
  return (e2x - 1.0f) / (e2x + 1.0f);
}

// Exact IEEE-754 binary32 -> binary16 round-to-nearest-even bit conversion.
__attribute__((always_inline)) inline uint16_t f32_bits_to_fp16(uint32_t bits) {
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

// Exact IEEE-754 binary16 -> binary32 bit conversion.
__attribute__((always_inline)) inline uint32_t fp16_bits_to_f32_bits(uint16_t h) {
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

// Exact IEEE-754 binary32 -> bfloat16 round-to-nearest-even bit conversion.
__attribute__((always_inline)) inline uint16_t f32_bits_to_bf16(uint32_t bits) {
  const uint32_t abs_bits = bits & 0x7fffffffu;
  if (abs_bits > 0x7f800000u) {
    return static_cast<uint16_t>((bits >> 16) | 0x0040u);
  }
  const uint32_t lsb = (bits >> 16) & 1u;
  const uint32_t rounding_bias = 0x7fffu + lsb;
  return static_cast<uint16_t>((bits + rounding_bias) >> 16);
}

// Exact IEEE-754 bfloat16 -> binary32 bit conversion.
__attribute__((always_inline)) inline uint32_t bf16_bits_to_f32_bits(uint16_t b) {
  const uint32_t abs_bits = static_cast<uint32_t>(b) & 0x7fffu;
  if (abs_bits > 0x7f80u) {
    return (static_cast<uint32_t>(b) << 16) | 0x00400000u;
  }
  return static_cast<uint32_t>(b) << 16;
}

void run_relu(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const uint32_t*>(arg.src0_addr);
  auto dst = reinterpret_cast<uint32_t*>(arg.dst_addr);
  const uint32_t total = arg.rows * arg.cols;
  for (uint32_t idx = tid; idx < total; idx += stride) {
    const uint32_t bits = src[idx];
    const uint32_t abs_bits = bits & 0x7fffffffu;
    if (abs_bits > 0x7f800000u) {
      dst[idx] = bits;
    } else if ((bits & 0x80000000u) != 0 || abs_bits == 0) {
      dst[idx] = 0u;
    } else {
      dst[idx] = bits;
    }
  }
}

void run_gelu(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const float*>(arg.src0_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t total = arg.rows * arg.cols;
  constexpr float kSqrt2OverPi = 0.797884560802865356f;
  constexpr float kGeluCoeff = 0.044715f;
  for (uint32_t idx = tid; idx < total; idx += stride) {
    const float x = src[idx];
    const float u = kSqrt2OverPi * x * (1.0f + kGeluCoeff * x * x);
    dst[idx] = 0.5f * x * (1.0f + fast_tanhf(u));
  }
}

void run_cast_f32_to_f16(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const uint32_t*>(arg.src0_addr);
  auto dst = reinterpret_cast<uint16_t*>(arg.dst_addr);
  const uint32_t total = arg.rows * arg.cols;
  for (uint32_t idx = tid; idx < total; idx += stride) {
    dst[idx] = f32_bits_to_fp16(src[idx]);
  }
}

void run_cast_f16_to_f32(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const uint16_t*>(arg.src0_addr);
  auto dst = reinterpret_cast<uint32_t*>(arg.dst_addr);
  const uint32_t total = arg.rows * arg.cols;
  for (uint32_t idx = tid; idx < total; idx += stride) {
    dst[idx] = fp16_bits_to_f32_bits(src[idx]);
  }
}

void run_cast_f32_to_bf16(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const uint32_t*>(arg.src0_addr);
  auto dst = reinterpret_cast<uint16_t*>(arg.dst_addr);
  const uint32_t total = arg.rows * arg.cols;
  for (uint32_t idx = tid; idx < total; idx += stride) {
    dst[idx] = f32_bits_to_bf16(src[idx]);
  }
}

void run_cast_bf16_to_f32(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const uint16_t*>(arg.src0_addr);
  auto dst = reinterpret_cast<uint32_t*>(arg.dst_addr);
  const uint32_t total = arg.rows * arg.cols;
  for (uint32_t idx = tid; idx < total; idx += stride) {
    dst[idx] = bf16_bits_to_f32_bits(src[idx]);
  }
}

void run_softmax(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const float*>(arg.src0_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t rows = arg.rows;
  const uint32_t cols = arg.cols;

  for (uint32_t row = tid; row < rows; row += stride) {
    const float* x_row = src + row * cols;
    float* y_row = dst + row * cols;

    float max_val = x_row[0];
    for (uint32_t c = 1; c < cols; ++c) {
      if (x_row[c] > max_val) {
        max_val = x_row[c];
      }
    }

    float sum = 0.0f;
    for (uint32_t c = 0; c < cols; ++c) {
      const float e = fast_expf(x_row[c] - max_val);
      y_row[c] = e;
      sum += e;
    }

    const float inv_sum = 1.0f / sum;
    for (uint32_t c = 0; c < cols; ++c) {
      y_row[c] *= inv_sum;
    }
  }
}

void run_rmsnorm(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const float*>(arg.src0_addr);
  auto weight = reinterpret_cast<const float*>(arg.src1_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t rows = arg.rows;
  const uint32_t cols = arg.cols;
  const float eps = bits_to_f32(arg.eps_bits);
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

void run_layernorm(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto src = reinterpret_cast<const float*>(arg.src0_addr);
  auto gamma = reinterpret_cast<const float*>(arg.src1_addr);
  auto beta = reinterpret_cast<const float*>(arg.src2_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t rows = arg.rows;
  const uint32_t cols = arg.cols;
  const float eps = bits_to_f32(arg.eps_bits);
  const float inv_cols = 1.0f / static_cast<float>(cols);

  for (uint32_t row = tid; row < rows; row += stride) {
    const float* x_row = src + row * cols;
    float* y_row = dst + row * cols;

    float sum = 0.0f;
    for (uint32_t c = 0; c < cols; ++c) {
      sum += x_row[c];
    }
    const float mean = sum * inv_cols;

    float var_sum = 0.0f;
    for (uint32_t c = 0; c < cols; ++c) {
      const float d = x_row[c] - mean;
      var_sum += d * d;
    }
    const float inv_std = 1.0f / device_sqrtf(var_sum * inv_cols + eps);

    for (uint32_t c = 0; c < cols; ++c) {
      y_row[c] = (x_row[c] - mean) * inv_std * gamma[c] + beta[c];
    }
  }
}

void run_attention(const va::OpsV2Arguments& arg, uint32_t tid, uint32_t stride) {
  auto q = reinterpret_cast<const float*>(arg.src0_addr);
  auto k = reinterpret_cast<const float*>(arg.src1_addr);
  auto v = reinterpret_cast<const float*>(arg.src2_addr);
  auto dst = reinterpret_cast<float*>(arg.dst_addr);
  const uint32_t seq_len = arg.rows;
  const uint32_t d_k = arg.cols;
  const float inv_sqrt_dk = 1.0f / device_sqrtf(static_cast<float>(d_k));

  float scores[va::kOpsV2MaxAttentionSeq];

  for (uint32_t i = tid; i < seq_len; i += stride) {
    const float* q_row = q + i * d_k;
    float* out_row = dst + i * d_k;

    float max_score = 0.0f;
    for (uint32_t j = 0; j < seq_len; ++j) {
      const float* k_row = k + j * d_k;
      float dot = 0.0f;
      for (uint32_t d = 0; d < d_k; ++d) {
        dot += q_row[d] * k_row[d];
      }
      const float s = dot * inv_sqrt_dk;
      scores[j] = s;
      if (j == 0 || s > max_score) {
        max_score = s;
      }
    }

    float exp_sum = 0.0f;
    for (uint32_t j = 0; j < seq_len; ++j) {
      const float p = fast_expf(scores[j] - max_score);
      scores[j] = p;
      exp_sum += p;
    }
    const float inv_sum = 1.0f / exp_sum;
    for (uint32_t j = 0; j < seq_len; ++j) {
      scores[j] *= inv_sum;
    }

    for (uint32_t d = 0; d < d_k; ++d) {
      float acc = 0.0f;
      for (uint32_t j = 0; j < seq_len; ++j) {
        acc += scores[j] * v[j * d_k + d];
      }
      out_row[d] = acc;
    }
  }
}

} // namespace

__kernel void kernel_main(const uint8_t* __UNIFORM__ bytes) {
  va::OpsV2Arguments arg;
  if (!va::decode_ops_v2_arguments(bytes, va::kOpsV2ArgumentBytes, &arg)
      || blockDim.y != 1 || blockDim.z != 1
      || gridDim.y != 1 || gridDim.z != 1
      || blockIdx.y != 0 || blockIdx.z != 0) {
    return;
  }

  const uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
  const uint32_t stride = gridDim.x * blockDim.x;
  if (stride == 0) {
    return;
  }

  switch (arg.op_code) {
    case va::kOpsV2OpReluFp32:
      run_relu(arg, tid, stride);
      break;
    case va::kOpsV2OpGeluFp32:
      run_gelu(arg, tid, stride);
      break;
    case va::kOpsV2OpCastFp32ToFp16:
      run_cast_f32_to_f16(arg, tid, stride);
      break;
    case va::kOpsV2OpCastFp16ToFp32:
      run_cast_f16_to_f32(arg, tid, stride);
      break;
    case va::kOpsV2OpCastFp32ToBf16:
      run_cast_f32_to_bf16(arg, tid, stride);
      break;
    case va::kOpsV2OpCastBf16ToFp32:
      run_cast_bf16_to_f32(arg, tid, stride);
      break;
    case va::kOpsV2OpSoftmaxFp32:
      run_softmax(arg, tid, stride);
      break;
    case va::kOpsV2OpRmsNormFp32:
      run_rmsnorm(arg, tid, stride);
      break;
    case va::kOpsV2OpLayerNormFp32:
      run_layernorm(arg, tid, stride);
      break;
    case va::kOpsV2OpAttentionFp32:
      run_attention(arg, tid, stride);
      break;
    default:
      break;
  }
}
