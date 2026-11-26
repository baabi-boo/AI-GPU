// SPDX-License-Identifier: Apache-2.0

#include "safetensors_reader.h"

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
#include <map>
#include <string>
#include <unistd.h>
#include <utility>
#include <vector>

namespace va = vortex::ai;

namespace {

constexpr uint32_t kDefaultPromptTokens = 4;
constexpr uint32_t kDefaultDecodeSteps = 4;
constexpr uint32_t kMaxBlockThreads = 16;
constexpr uint32_t kMaxPrintedErrors = 32;
constexpr double kLogitsMaxAbsTolerance = 5e-4;
constexpr const char* kDefaultPrompt = "AI-GPU";

struct Options {
  std::string kernel_path = "kernel.vxbin";
  std::string weights_path;
  std::string prompt = kDefaultPrompt;
  uint32_t prompt_len = kDefaultPromptTokens;
  uint32_t decode_steps = kDefaultDecodeSteps;
  bool show_help = false;
};

void show_usage(const char* argv0) {
  std::cout << "Usage: " << argv0
            << " [-k kernel.vxbin] [--weights file.safetensors] [--prompt text]"
            << " [--prompt-len N] [--decode-steps N] [-h]\n"
            << "  -k, --kernel          Path to llm_ops_v3 kernel.vxbin (default: kernel.vxbin)\n"
            << "  -w, --weights         Path to input .safetensors weights (auto-generated if omitted)\n"
            << "  -p, --prompt          ASCII prompt string (default: \"AI-GPU\")\n"
            << "      --prompt-len      Prompt token count P (default: 4)\n"
            << "  -n, --decode-steps    Autoregressive decode steps T (default: 4)\n"
            << "      --max-new-tokens  Alias for --decode-steps\n"
            << "  -h, --help            Show this help\n";
}

bool parse_u32_flag(const char* s, uint32_t min_val, uint32_t max_val, uint32_t* out) {
  if (!s || s[0] == '\0') {
    return false;
  }
  char* end = nullptr;
  const unsigned long val = std::strtoul(s, &end, 10);
  if (!end || *end != '\0' || val < min_val || val > max_val) {
    return false;
  }
  *out = static_cast<uint32_t>(val);
  return true;
}

bool parse_args(int argc, char** argv, Options* out) {
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "-h" || arg == "--help") {
      out->show_help = true;
      return true;
    }
    if ((arg == "-k" || arg == "--kernel") && i + 1 < argc) {
      out->kernel_path = argv[++i];
      continue;
    }
    if ((arg == "-w" || arg == "--weights") && i + 1 < argc) {
      out->weights_path = argv[++i];
      continue;
    }
    if ((arg == "-p" || arg == "--prompt") && i + 1 < argc) {
      out->prompt = argv[++i];
      continue;
    }
    if (arg == "--prompt-len" && i + 1 < argc) {
      if (!parse_u32_flag(argv[++i], 1u, 15u, &out->prompt_len)) {
        std::cerr << "Error: invalid --prompt-len\n";
        return false;
      }
      continue;
    }
    if ((arg == "-n" || arg == "--decode-steps" || arg == "--max-new-tokens")
        && i + 1 < argc) {
      if (!parse_u32_flag(argv[++i], 1u, 15u, &out->decode_steps)) {
        std::cerr << "Error: invalid --decode-steps\n";
        return false;
      }
      continue;
    }
    std::cerr << "Error: unknown or incomplete argument '" << arg << "'\n";
    return false;
  }
  if (out->prompt.empty()) {
    std::cerr << "Error: prompt must not be empty\n";
    return false;
  }
  return true;
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

std::vector<uint8_t> pack_f32_bytes(const std::vector<float>& vals) {
  std::vector<uint8_t> out(vals.size() * 4);
  for (size_t i = 0; i < vals.size(); ++i) {
    write_u32_le(out.data() + i * 4, float_to_bits(vals[i]));
  }
  return out;
}

std::vector<float> unpack_f32_bytes(const std::vector<uint8_t>& bytes) {
  std::vector<float> out(bytes.size() / 4);
  for (size_t i = 0; i < out.size(); ++i) {
    out[i] = bits_to_float(read_u32_le(bytes.data() + i * 4));
  }
  return out;
}

std::vector<uint32_t> tokenize_ascii(const std::string& prompt, uint32_t prompt_len,
                                     uint32_t vocab_size) {
  std::vector<uint32_t> ids;
  ids.reserve(prompt_len);
  const size_t limit = std::min<size_t>(prompt.size(), prompt_len);
  for (size_t i = 0; i < limit; ++i) {
    ids.push_back(static_cast<uint8_t>(prompt[i]) % vocab_size);
  }
  while (ids.size() < prompt_len) {
    ids.push_back(static_cast<uint8_t>(prompt[ids.size() % prompt.size()]) % vocab_size);
  }
  return ids;
}

std::string format_token_list(const std::vector<uint32_t>& ids) {
  std::string out = "[";
  for (size_t i = 0; i < ids.size(); ++i) {
    if (i > 0) {
      out += ",";
    }
    out += std::to_string(ids[i]);
  }
  out += "]";
  return out;
}

struct EventHandle {
  vx_event_h h = nullptr;

  EventHandle() = default;
  EventHandle(const EventHandle&) = delete;
  EventHandle& operator=(const EventHandle&) = delete;

  EventHandle(EventHandle&& other) noexcept : h(other.h) {
    other.h = nullptr;
  }

  EventHandle& operator=(EventHandle&& other) noexcept {
    if (this != &other) {
      release();
      h = other.h;
      other.h = nullptr;
    }
    return *this;
  }

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

  BufferHandle(BufferHandle&& other) noexcept
      : h(other.h), addr(other.addr) {
    other.h = nullptr;
    other.addr = 0;
  }

  BufferHandle& operator=(BufferHandle&& other) noexcept {
    if (this != &other) {
      release();
      h = other.h;
      addr = other.addr;
      other.h = nullptr;
      other.addr = 0;
    }
    return *this;
  }

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
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;

  DeviceSession() = default;
  DeviceSession(const DeviceSession&) = delete;
  DeviceSession& operator=(const DeviceSession&) = delete;

  ~DeviceSession() {
    release();
  }

  void release() noexcept {
    // Drain queue work before releasing the kernel, module, and device handles.
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

#define VX_CHECK(expr)                                                          \
  do {                                                                          \
    vx_result_t _rc = (expr);                                                   \
    if (_rc != VX_SUCCESS) {                                                    \
      std::cerr << "FAILED " << #expr << ": " << vx_result_string(_rc) << '\n'; \
      return false;                                                             \
    }                                                                           \
  } while (0)

struct LayerWeights {
  std::vector<float> attention_norm;
  std::vector<float> wq;
  std::vector<float> wk;
  std::vector<float> wv;
  std::vector<float> wo;
  std::vector<float> ffn_norm;
  std::vector<float> w_gate;
  std::vector<float> w_up;
  std::vector<float> w_down;
};

struct LlamaWeights {
  aigpu::llm::MicroLlamaConfig cfg;
  std::vector<float> tok_embeddings;
  std::vector<LayerWeights> layers;
  std::vector<float> norm;
  std::vector<float> lm_head;
};

bool parse_meta_u32(const std::map<std::string, std::string>& meta, const char* key,
                    uint32_t* val, bool* found) {
  const auto it = meta.find(key);
  if (it == meta.end()) {
    return true;
  }
  if (!parse_u32_flag(it->second.c_str(), 1u, 1000000u, val)) {
    return false;
  }
  if (found) {
    *found = true;
  }
  return true;
}

bool resolve_tensor_name(const aigpu::llm::SafetensorsFile& sf,
                         const std::string& primary,
                         const std::string& hf_alt,
                         std::string* resolved) {
  if (sf.has(primary)) {
    *resolved = primary;
    return true;
  }
  if (!hf_alt.empty() && sf.has(hf_alt)) {
    *resolved = hf_alt;
    return true;
  }
  return false;
}

uint32_t detect_num_layers(const aigpu::llm::SafetensorsFile& sf) {
  uint32_t count = 0;
  while (true) {
    const std::string p1 = "layers." + std::to_string(count) + ".wq.weight";
    const std::string p2 = "model.layers." + std::to_string(count) + ".self_attn.q_proj.weight";
    if (!sf.has(p1) && !sf.has(p2)) {
      break;
    }
    ++count;
  }
  return count;
}

bool load_llama_weights(const aigpu::llm::SafetensorsFile& sf, LlamaWeights* out,
                        std::string* err) {
  aigpu::llm::MicroLlamaConfig cfg{};
  const auto& meta = sf.metadata();
  bool has_layers_meta = false;
  if (!parse_meta_u32(meta, "vocab_size", &cfg.vocab_size, nullptr)
      || !parse_meta_u32(meta, "n_layers", &cfg.n_layers, &has_layers_meta)
      || !parse_meta_u32(meta, "num_hidden_layers", &cfg.n_layers, &has_layers_meta)
      || !parse_meta_u32(meta, "d_model", &cfg.d_model, nullptr)
      || !parse_meta_u32(meta, "hidden_size", &cfg.d_model, nullptr)
      || !parse_meta_u32(meta, "n_q_heads", &cfg.n_q_heads, nullptr)
      || !parse_meta_u32(meta, "num_attention_heads", &cfg.n_q_heads, nullptr)
      || !parse_meta_u32(meta, "n_kv_heads", &cfg.n_kv_heads, nullptr)
      || !parse_meta_u32(meta, "num_key_value_heads", &cfg.n_kv_heads, nullptr)
      || !parse_meta_u32(meta, "d_ff", &cfg.d_ff, nullptr)
      || !parse_meta_u32(meta, "intermediate_size", &cfg.d_ff, nullptr)
      || !parse_meta_u32(meta, "max_seq", &cfg.max_seq, nullptr)) {
    *err = "invalid integer metadata in safetensors header";
    return false;
  }

  if (!has_layers_meta) {
    const uint32_t detected_layers = detect_num_layers(sf);
    if (detected_layers == 0) {
      *err = "could not detect any decoder layers in safetensors checkpoint";
      return false;
    }
    cfg.n_layers = detected_layers;
  }

  std::string emb_name;
  if (!resolve_tensor_name(sf, "tok_embeddings.weight", "model.embed_tokens.weight", &emb_name)) {
    *err = "missing tok_embeddings.weight";
    return false;
  }
  const aigpu::llm::SafetensorsTensor* emb = sf.find(emb_name);
  if (!emb || emb->shape.size() != 2) {
    *err = "tok_embeddings.weight must be 2-D";
    return false;
  }
  cfg.vocab_size = static_cast<uint32_t>(emb->shape[0]);
  cfg.d_model = static_cast<uint32_t>(emb->shape[1]);

  std::string wk0_name;
  if (!resolve_tensor_name(sf, "layers.0.wk.weight", "model.layers.0.self_attn.k_proj.weight", &wk0_name)) {
    *err = "missing layers.0.wk.weight";
    return false;
  }
  const aigpu::llm::SafetensorsTensor* wk0 = sf.find(wk0_name);
  if (!wk0 || wk0->shape.size() != 2 || wk0->shape[1] != cfg.d_model) {
    *err = "layers.0.wk.weight shape invalid";
    return false;
  }
  const uint32_t kv_dim = static_cast<uint32_t>(wk0->shape[0]);

  std::string gate0_name;
  if (!resolve_tensor_name(sf, "layers.0.w_gate.weight", "model.layers.0.mlp.gate_proj.weight", &gate0_name)) {
    *err = "missing layers.0.w_gate.weight";
    return false;
  }
  const aigpu::llm::SafetensorsTensor* gate0 = sf.find(gate0_name);
  if (!gate0 || gate0->shape.size() != 2 || gate0->shape[1] != cfg.d_model) {
    *err = "layers.0.w_gate.weight shape invalid";
    return false;
  }
  cfg.d_ff = static_cast<uint32_t>(gate0->shape[0]);

  if (cfg.n_q_heads == 0 || (cfg.d_model % cfg.n_q_heads) != 0) {
    *err = "d_model not divisible by n_q_heads";
    return false;
  }
  cfg.d_head = cfg.d_model / cfg.n_q_heads;
  if (cfg.d_head == 0 || (cfg.d_head & 1u) != 0 || cfg.d_head > va::kLlmV3FlashMaxHeadDim) {
    *err = "d_head violates llm_ops_v3 constraints (even, <= 64)";
    return false;
  }
  if (kv_dim == 0 || (kv_dim % cfg.d_head) != 0) {
    *err = "kv_dim not divisible by d_head";
    return false;
  }
  cfg.n_kv_heads = kv_dim / cfg.d_head;
  if ((cfg.n_q_heads % cfg.n_kv_heads) != 0) {
    *err = "n_q_heads must be a multiple of n_kv_heads";
    return false;
  }

  out->cfg = cfg;
  if (!sf.read_as_f32(emb_name, {cfg.vocab_size, cfg.d_model}, &out->tok_embeddings, err)) {
    return false;
  }

  out->layers.resize(cfg.n_layers);
  for (uint32_t l = 0; l < cfg.n_layers; ++l) {
    LayerWeights& lw = out->layers[l];
    const std::string p_llama = "layers." + std::to_string(l) + ".";
    const std::string p_hf = "model.layers." + std::to_string(l) + ".";

    auto load_pair = [&](const std::string& a, const std::string& b,
                         const std::vector<uint64_t>& shape,
                         std::vector<float>* dst) -> bool {
      std::string chosen;
      if (!resolve_tensor_name(sf, a, b, &chosen)) {
        *err = "missing tensor '" + a + "'";
        return false;
      }
      return sf.read_as_f32(chosen, shape, dst, err);
    };

    if (!load_pair(p_llama + "attention_norm.weight", p_hf + "input_layernorm.weight",
                   {cfg.d_model}, &lw.attention_norm)
        || !load_pair(p_llama + "wq.weight", p_hf + "self_attn.q_proj.weight",
                      {cfg.d_model, cfg.d_model}, &lw.wq)
        || !load_pair(p_llama + "wk.weight", p_hf + "self_attn.k_proj.weight",
                      {kv_dim, cfg.d_model}, &lw.wk)
        || !load_pair(p_llama + "wv.weight", p_hf + "self_attn.v_proj.weight",
                      {kv_dim, cfg.d_model}, &lw.wv)
        || !load_pair(p_llama + "wo.weight", p_hf + "self_attn.o_proj.weight",
                      {cfg.d_model, cfg.d_model}, &lw.wo)
        || !load_pair(p_llama + "ffn_norm.weight", p_hf + "post_attention_layernorm.weight",
                      {cfg.d_model}, &lw.ffn_norm)
        || !load_pair(p_llama + "w_gate.weight", p_hf + "mlp.gate_proj.weight",
                      {cfg.d_ff, cfg.d_model}, &lw.w_gate)
        || !load_pair(p_llama + "w_up.weight", p_hf + "mlp.up_proj.weight",
                      {cfg.d_ff, cfg.d_model}, &lw.w_up)
        || !load_pair(p_llama + "w_down.weight", p_hf + "mlp.down_proj.weight",
                      {cfg.d_model, cfg.d_ff}, &lw.w_down)) {
      return false;
    }
  }

  std::string norm_name;
  if (!resolve_tensor_name(sf, "norm.weight", "model.norm.weight", &norm_name)) {
    *err = "missing norm.weight";
    return false;
  }
  if (!sf.read_as_f32(norm_name, {cfg.d_model}, &out->norm, err)) {
    return false;
  }
  if (sf.has("lm_head.weight")) {
    if (!sf.read_as_f32("lm_head.weight", {cfg.vocab_size, cfg.d_model}, &out->lm_head, err)) {
      return false;
    }
  } else {
    out->lm_head = out->tok_embeddings;
  }
  return true;
}

// ============================================================================
// Independent IEEE-754 double CPU reference
// ============================================================================

void cpu_rmsnorm_f64(const std::vector<double>& x, const std::vector<float>& w,
                     uint32_t rows, uint32_t cols, double eps,
                     std::vector<double>* out) {
  out->resize(size_t{rows} * cols);
  for (uint32_t r = 0; r < rows; ++r) {
    double sq = 0.0;
    for (uint32_t c = 0; c < cols; ++c) {
      const double v = x[r * cols + c];
      sq += v * v;
    }
    const double inv_rms = 1.0 / std::sqrt(sq / static_cast<double>(cols) + eps);
    for (uint32_t c = 0; c < cols; ++c) {
      (*out)[r * cols + c] = x[r * cols + c] * inv_rms * static_cast<double>(w[c]);
    }
  }
}

void cpu_linear_f64(const std::vector<double>& a, const std::vector<float>& b,
                    uint32_t m, uint32_t k, uint32_t n, std::vector<double>* out) {
  out->resize(size_t{m} * n);
  for (uint32_t row = 0; row < m; ++row) {
    for (uint32_t col = 0; col < n; ++col) {
      double acc = 0.0;
      for (uint32_t kk = 0; kk < k; ++kk) {
        acc += a[row * k + kk] * static_cast<double>(b[col * k + kk]);
      }
      (*out)[row * n + col] = acc;
    }
  }
}

void cpu_rope_f64(std::vector<double>* x, uint32_t seq_len, uint32_t n_heads,
                  uint32_t d_head, uint32_t pos_offset, double theta) {
  const uint32_t half_dim = d_head / 2;
  for (uint32_t s = 0; s < seq_len; ++s) {
    const double pos = static_cast<double>(pos_offset + s);
    for (uint32_t h = 0; h < n_heads; ++h) {
      const uint32_t base = (s * n_heads + h) * d_head;
      for (uint32_t j = 0; j < half_dim; ++j) {
        const double inv_freq =
            std::pow(theta, -static_cast<double>(2u * j) / static_cast<double>(d_head));
        const double angle = pos * inv_freq;
        const double cs = std::cos(angle);
        const double sn = std::sin(angle);
        const double x0 = (*x)[base + j];
        const double x1 = (*x)[base + j + half_dim];
        (*x)[base + j] = x0 * cs - x1 * sn;
        (*x)[base + j + half_dim] = x0 * sn + x1 * cs;
      }
    }
  }
}

void cpu_gqa_attention_f64(const std::vector<double>& q,
                           const std::vector<double>& k,
                           const std::vector<double>& v,
                           uint32_t q_len, uint32_t kv_len,
                           uint32_t n_q_heads, uint32_t n_kv_heads,
                           uint32_t d_head, bool causal, uint32_t pos_offset,
                           std::vector<double>* out) {
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
          dot += q[q_off + d] * k[k_off + d];
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
          acc += scores[j] * v[v_off + d];
        }
        (*out)[q_off + d] = acc / exp_sum;
      }
    }
  }
}

void cpu_swiglu_f64(const std::vector<double>& gate, const std::vector<double>& up,
                    std::vector<double>* out) {
  out->resize(gate.size());
  for (size_t i = 0; i < gate.size(); ++i) {
    const double g = gate[i];
    const double sig = (g >= 0.0)
        ? (1.0 / (1.0 + std::exp(-g)))
        : (std::exp(g) / (1.0 + std::exp(g)));
    (*out)[i] = (g * sig) * up[i];
  }
}

void cpu_add_f64(const std::vector<double>& a, const std::vector<double>& b,
                 std::vector<double>* out) {
  out->resize(a.size());
  for (size_t i = 0; i < a.size(); ++i) {
    (*out)[i] = a[i] + b[i];
  }
}

uint32_t argmax_f64(const std::vector<double>& logits, uint32_t row_offset,
                    uint32_t vocab_size) {
  uint32_t best = 0;
  double best_val = logits[row_offset];
  for (uint32_t v = 1; v < vocab_size; ++v) {
    if (logits[row_offset + v] > best_val) {
      best_val = logits[row_offset + v];
      best = v;
    }
  }
  return best;
}

uint32_t argmax_f32(const std::vector<float>& logits, uint32_t row_offset,
                    uint32_t vocab_size) {
  uint32_t best = 0;
  float best_val = logits[row_offset];
  for (uint32_t v = 1; v < vocab_size; ++v) {
    if (logits[row_offset + v] > best_val) {
      best_val = logits[row_offset + v];
      best = v;
    }
  }
  return best;
}

struct CpuRefResult {
  std::vector<double> prefill_logits;
  uint32_t prefill_token = 0;
  std::vector<std::vector<double>> decode_logits;
  std::vector<uint32_t> decode_tokens;
};

CpuRefResult run_cpu_reference_f64(const LlamaWeights& w,
                                   const std::vector<uint32_t>& prompt_ids,
                                   uint32_t decode_steps) {
  const auto& cfg = w.cfg;
  const uint32_t p_len = static_cast<uint32_t>(prompt_ids.size());
  const uint32_t kv_dim = cfg.n_kv_heads * cfg.d_head;
  const double eps = static_cast<double>(bits_to_float(va::kLlmV3DefaultEpsBits));
  const double theta = static_cast<double>(bits_to_float(va::kLlmV3DefaultThetaBits));

  std::vector<std::vector<double>> k_cache(
      cfg.n_layers, std::vector<double>(size_t{cfg.max_seq} * kv_dim, 0.0));
  std::vector<std::vector<double>> v_cache(
      cfg.n_layers, std::vector<double>(size_t{cfg.max_seq} * kv_dim, 0.0));

  auto forward_steps = [&](const std::vector<uint32_t>& tokens,
                           uint32_t pos_offset) -> std::vector<double> {
    const uint32_t seq_len = static_cast<uint32_t>(tokens.size());
    std::vector<double> x(size_t{seq_len} * cfg.d_model);
    for (uint32_t s = 0; s < seq_len; ++s) {
      const uint32_t tok = tokens[s];
      for (uint32_t d = 0; d < cfg.d_model; ++d) {
        x[s * cfg.d_model + d] = static_cast<double>(w.tok_embeddings[tok * cfg.d_model + d]);
      }
    }

    std::vector<double> norm_buf;
    std::vector<double> q;
    std::vector<double> k;
    std::vector<double> v;
    std::vector<double> attn_out;
    std::vector<double> proj;
    std::vector<double> gate;
    std::vector<double> up;
    std::vector<double> swiglu;

    for (uint32_t l = 0; l < cfg.n_layers; ++l) {
      const LayerWeights& lw = w.layers[l];
      cpu_rmsnorm_f64(x, lw.attention_norm, seq_len, cfg.d_model, eps, &norm_buf);
      cpu_linear_f64(norm_buf, lw.wq, seq_len, cfg.d_model, cfg.d_model, &q);
      cpu_linear_f64(norm_buf, lw.wk, seq_len, cfg.d_model, kv_dim, &k);
      cpu_linear_f64(norm_buf, lw.wv, seq_len, cfg.d_model, kv_dim, &v);

      cpu_rope_f64(&q, seq_len, cfg.n_q_heads, cfg.d_head, pos_offset, theta);
      cpu_rope_f64(&k, seq_len, cfg.n_kv_heads, cfg.d_head, pos_offset, theta);

      for (uint32_t s = 0; s < seq_len; ++s) {
        const size_t dst_base = size_t{pos_offset + s} * kv_dim;
        const size_t src_base = size_t{s} * kv_dim;
        for (uint32_t d = 0; d < kv_dim; ++d) {
          k_cache[l][dst_base + d] = k[src_base + d];
          v_cache[l][dst_base + d] = v[src_base + d];
        }
      }

      if (seq_len > 1) {
        cpu_gqa_attention_f64(q, k, v, seq_len, seq_len, cfg.n_q_heads,
                              cfg.n_kv_heads, cfg.d_head, true, 0, &attn_out);
      } else {
        cpu_gqa_attention_f64(q, k_cache[l], v_cache[l], 1, pos_offset + 1,
                              cfg.n_q_heads, cfg.n_kv_heads, cfg.d_head,
                              false, 0, &attn_out);
      }

      cpu_linear_f64(attn_out, lw.wo, seq_len, cfg.d_model, cfg.d_model, &proj);
      cpu_add_f64(x, proj, &x);

      cpu_rmsnorm_f64(x, lw.ffn_norm, seq_len, cfg.d_model, eps, &norm_buf);
      cpu_linear_f64(norm_buf, lw.w_gate, seq_len, cfg.d_model, cfg.d_ff, &gate);
      cpu_linear_f64(norm_buf, lw.w_up, seq_len, cfg.d_model, cfg.d_ff, &up);
      cpu_swiglu_f64(gate, up, &swiglu);
      cpu_linear_f64(swiglu, lw.w_down, seq_len, cfg.d_ff, cfg.d_model, &proj);
      cpu_add_f64(x, proj, &x);
    }

    cpu_rmsnorm_f64(x, w.norm, seq_len, cfg.d_model, eps, &norm_buf);
    std::vector<double> logits;
    cpu_linear_f64(norm_buf, w.lm_head, seq_len, cfg.d_model, cfg.vocab_size, &logits);
    return logits;
  };

  CpuRefResult res;
  const std::vector<double> prefill_all = forward_steps(prompt_ids, 0);
  const uint32_t last_row = (p_len - 1u) * cfg.vocab_size;
  res.prefill_logits.assign(
      prefill_all.begin() + static_cast<std::ptrdiff_t>(last_row),
      prefill_all.begin() + static_cast<std::ptrdiff_t>(last_row + cfg.vocab_size));
  res.prefill_token = argmax_f64(res.prefill_logits, 0, cfg.vocab_size);

  uint32_t next_tok = res.prefill_token;
  res.decode_logits.reserve(decode_steps);
  res.decode_tokens.reserve(decode_steps);
  for (uint32_t step = 0; step < decode_steps; ++step) {
    const uint32_t pos = p_len + step;
    std::vector<double> step_logits = forward_steps({next_tok}, pos);
    next_tok = argmax_f64(step_logits, 0, cfg.vocab_size);
    res.decode_logits.push_back(std::move(step_logits));
    res.decode_tokens.push_back(next_tok);
  }
  return res;
}

// ============================================================================
// Device execution helpers
// ============================================================================

bool query_device_block_threads(vx_device_h device, uint32_t d_head,
                                uint32_t* out_block_x) {
  uint64_t isa = 0;
  uint64_t threads = 0;
  uint64_t warps = 0;
  uint64_t cores = 0;
  uint64_t clusters = 0;
  uint64_t lmem_size = 0;
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
  const uint64_t max_cta_threads = threads * warps;
  if (max_cta_threads < va::kLlmV3FlashTileBr) {
    std::cerr << "FAILED device CTA thread capacity (" << max_cta_threads
              << ") below FlashAttention tile height (" << va::kLlmV3FlashTileBr << ")\n";
    return false;
  }
  const uint32_t req_lmem = va::llm_ops_v3_detail::flash_lmem_bytes_required(d_head);
  if ((isa & VX_ISA_EXT_LMEM) == 0 || lmem_size < req_lmem) {
    std::cerr << "FAILED device local memory insufficient for tiled FlashAttention\n";
    return false;
  }
  *out_block_x = static_cast<uint32_t>(std::min<uint64_t>(kMaxBlockThreads, max_cta_threads));
  return true;
}

bool create_buffer(vx_device_h device, uint64_t size, uint32_t flags, BufferHandle* out) {
  VX_CHECK(vx_buffer_create(device, size, flags, &out->h));
  VX_CHECK(vx_buffer_address(out->h, &out->addr));
  return true;
}

bool enqueue_write_bytes(vx_queue_h queue, const BufferHandle& dst, uint64_t dst_off,
                         std::vector<uint8_t> data,
                         std::vector<std::vector<uint8_t>>* staging,
                         EventHandle* chain, uint64_t* h2d_bytes) {
  staging->push_back(std::move(data));
  const std::vector<uint8_t>& held = staging->back();
  EventHandle next_ev;
  const uint32_t n_wait = chain->h ? 1u : 0u;
  const vx_event_h* wait_ptr = chain->h ? &chain->h : nullptr;
  VX_CHECK(vx_enqueue_write(queue, dst.h, dst_off, held.data(), held.size(),
                            n_wait, wait_ptr, &next_ev.h));
  std::swap(chain->h, next_ev.h);
  *h2d_bytes += held.size();
  return true;
}

bool enqueue_llm_op(vx_queue_h queue, vx_kernel_h kernel,
                    const va::LlmOpsV3Arguments& arg, uint32_t grid_x,
                    uint32_t block_x, uint32_t lmem_size, EventHandle* chain,
                    uint32_t* launch_count) {
  vx_launch_info_t li{};
  li.struct_size = sizeof(li);
  li.kernel = kernel;
  li.args_host = &arg;
  li.args_size = sizeof(arg);
  li.ndim = 1;
  li.grid_dim[0] = grid_x;
  li.grid_dim[1] = 1;
  li.grid_dim[2] = 1;
  li.block_dim[0] = block_x;
  li.block_dim[1] = 1;
  li.block_dim[2] = 1;
  li.lmem_size = lmem_size;
  li.cluster_dim[0] = 1;
  li.cluster_dim[1] = 1;
  li.cluster_dim[2] = 1;

  EventHandle next_ev;
  const uint32_t n_wait = chain->h ? 1u : 0u;
  const vx_event_h* wait_ptr = chain->h ? &chain->h : nullptr;
  VX_CHECK(vx_enqueue_launch(queue, &li, n_wait, wait_ptr, &next_ev.h));
  std::swap(chain->h, next_ev.h);
  ++(*launch_count);
  return true;
}

bool enqueue_copy_d2d(vx_queue_h queue, const BufferHandle& dst, uint64_t dst_off,
                      const BufferHandle& src, uint64_t src_off, uint64_t bytes,
                      EventHandle* chain) {
  EventHandle next_ev;
  const uint32_t n_wait = chain->h ? 1u : 0u;
  const vx_event_h* wait_ptr = chain->h ? &chain->h : nullptr;
  VX_CHECK(vx_enqueue_copy(queue, dst.h, dst_off, src.h, src_off, bytes,
                           n_wait, wait_ptr, &next_ev.h));
  std::swap(chain->h, next_ev.h);
  return true;
}

struct DeviceLayerWeights {
  BufferHandle attention_norm;
  BufferHandle wq;
  BufferHandle wk;
  BufferHandle wv;
  BufferHandle wo;
  BufferHandle ffn_norm;
  BufferHandle w_gate;
  BufferHandle w_up;
  BufferHandle w_down;
  BufferHandle k_cache;
  BufferHandle v_cache;
};

struct DeviceLlamaState {
  BufferHandle tok_embeddings;
  std::vector<DeviceLayerWeights> layers;
  BufferHandle norm;
  BufferHandle lm_head;

  // Device-resident activation scratch buffers (zero host transfers inside layers).
  BufferHandle act_a;
  BufferHandle act_b;
  BufferHandle norm_buf;
  BufferHandle q_raw;
  BufferHandle q_rope;
  BufferHandle k_raw;
  BufferHandle k_rope;
  BufferHandle v_buf;
  BufferHandle attn_out;
  BufferHandle proj_out;
  BufferHandle ffn_gate;
  BufferHandle ffn_up;
  BufferHandle ffn_swiglu;
  BufferHandle logits;
};

bool allocate_and_upload_weights(const DeviceSession& session, const LlamaWeights& w,
                                 DeviceLlamaState* dev, uint64_t* init_h2d_bytes) {
  const auto& cfg = w.cfg;
  const uint32_t kv_dim = cfg.n_kv_heads * cfg.d_head;
  const uint32_t max_seq = cfg.max_seq;

  const uint64_t emb_bytes = uint64_t{cfg.vocab_size} * cfg.d_model * 4;
  const uint64_t vec_bytes = uint64_t{cfg.d_model} * 4;
  const uint64_t qproj_bytes = uint64_t{cfg.d_model} * cfg.d_model * 4;
  const uint64_t kvproj_bytes = uint64_t{kv_dim} * cfg.d_model * 4;
  const uint64_t ffn_bytes = uint64_t{cfg.d_ff} * cfg.d_model * 4;
  const uint64_t kv_cache_bytes = uint64_t{cfg.max_seq} * kv_dim * 4;

  if (!create_buffer(session.device, emb_bytes, VX_MEM_READ, &dev->tok_embeddings)
      || !create_buffer(session.device, vec_bytes, VX_MEM_READ, &dev->norm)
      || !create_buffer(session.device, emb_bytes, VX_MEM_READ, &dev->lm_head)) {
    return false;
  }

  dev->layers.resize(cfg.n_layers);
  for (uint32_t l = 0; l < cfg.n_layers; ++l) {
    DeviceLayerWeights& dl = dev->layers[l];
    if (!create_buffer(session.device, vec_bytes, VX_MEM_READ, &dl.attention_norm)
        || !create_buffer(session.device, qproj_bytes, VX_MEM_READ, &dl.wq)
        || !create_buffer(session.device, kvproj_bytes, VX_MEM_READ, &dl.wk)
        || !create_buffer(session.device, kvproj_bytes, VX_MEM_READ, &dl.wv)
        || !create_buffer(session.device, qproj_bytes, VX_MEM_READ, &dl.wo)
        || !create_buffer(session.device, vec_bytes, VX_MEM_READ, &dl.ffn_norm)
        || !create_buffer(session.device, ffn_bytes, VX_MEM_READ, &dl.w_gate)
        || !create_buffer(session.device, ffn_bytes, VX_MEM_READ, &dl.w_up)
        || !create_buffer(session.device, ffn_bytes, VX_MEM_READ, &dl.w_down)
        || !create_buffer(session.device, kv_cache_bytes, VX_MEM_READ_WRITE, &dl.k_cache)
        || !create_buffer(session.device, kv_cache_bytes, VX_MEM_READ_WRITE, &dl.v_cache)) {
      return false;
    }
  }

  const uint64_t act_max_bytes = uint64_t{max_seq} * cfg.d_model * 4;
  const uint64_t kv_act_max_bytes = uint64_t{max_seq} * kv_dim * 4;
  const uint64_t ffn_act_max_bytes = uint64_t{max_seq} * cfg.d_ff * 4;
  const uint64_t logits_max_bytes = uint64_t{max_seq} * cfg.vocab_size * 4;

  if (!create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->act_a)
      || !create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->act_b)
      || !create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->norm_buf)
      || !create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->q_raw)
      || !create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->q_rope)
      || !create_buffer(session.device, kv_act_max_bytes, VX_MEM_READ_WRITE, &dev->k_raw)
      || !create_buffer(session.device, kv_act_max_bytes, VX_MEM_READ_WRITE, &dev->k_rope)
      || !create_buffer(session.device, kv_act_max_bytes, VX_MEM_READ_WRITE, &dev->v_buf)
      || !create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->attn_out)
      || !create_buffer(session.device, act_max_bytes, VX_MEM_READ_WRITE, &dev->proj_out)
      || !create_buffer(session.device, ffn_act_max_bytes, VX_MEM_READ_WRITE, &dev->ffn_gate)
      || !create_buffer(session.device, ffn_act_max_bytes, VX_MEM_READ_WRITE, &dev->ffn_up)
      || !create_buffer(session.device, ffn_act_max_bytes, VX_MEM_READ_WRITE, &dev->ffn_swiglu)
      || !create_buffer(session.device, logits_max_bytes, VX_MEM_READ_WRITE, &dev->logits)) {
    return false;
  }

  // Keep host-side DMA staging vectors alive until the async write chain completes.
  std::vector<std::vector<uint8_t>> staging;
  staging.reserve(3u + size_t{cfg.n_layers} * 11u);

  EventHandle chain;
  if (!enqueue_write_bytes(session.queue, dev->tok_embeddings, 0,
                           pack_f32_bytes(w.tok_embeddings), &staging, &chain, init_h2d_bytes)
      || !enqueue_write_bytes(session.queue, dev->norm, 0,
                              pack_f32_bytes(w.norm), &staging, &chain, init_h2d_bytes)
      || !enqueue_write_bytes(session.queue, dev->lm_head, 0,
                              pack_f32_bytes(w.lm_head), &staging, &chain, init_h2d_bytes)) {
    return false;
  }

  for (uint32_t l = 0; l < cfg.n_layers; ++l) {
    const LayerWeights& lw = w.layers[l];
    DeviceLayerWeights& dl = dev->layers[l];
    if (!enqueue_write_bytes(session.queue, dl.attention_norm, 0,
                             pack_f32_bytes(lw.attention_norm), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.wq, 0,
                                pack_f32_bytes(lw.wq), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.wk, 0,
                                pack_f32_bytes(lw.wk), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.wv, 0,
                                pack_f32_bytes(lw.wv), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.wo, 0,
                                pack_f32_bytes(lw.wo), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.ffn_norm, 0,
                                pack_f32_bytes(lw.ffn_norm), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.w_gate, 0,
                                pack_f32_bytes(lw.w_gate), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.w_up, 0,
                                pack_f32_bytes(lw.w_up), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.w_down, 0,
                                pack_f32_bytes(lw.w_down), &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.k_cache, 0,
                                std::vector<uint8_t>(kv_cache_bytes, 0),
                                &staging, &chain, init_h2d_bytes)
        || !enqueue_write_bytes(session.queue, dl.v_cache, 0,
                                std::vector<uint8_t>(kv_cache_bytes, 0),
                                &staging, &chain, init_h2d_bytes)) {
      return false;
    }
  }

  VX_CHECK(vx_event_wait_value(chain.h, 1, VX_TIMEOUT_INFINITE));
  chain.release();
  return true;
}

bool run_device_forward_step(const DeviceSession& session,
                             const aigpu::llm::MicroLlamaConfig& cfg,
                             const DeviceLlamaState& dev,
                             const std::vector<uint32_t>& token_ids,
                             uint32_t pos_offset,
                             uint32_t block_x,
                             uint32_t* launch_count,
                             std::vector<float>* out_last_logits,
                             uint64_t* final_d2h_bytes) {
  const uint32_t seq_len = static_cast<uint32_t>(token_ids.size());
  const uint32_t kv_dim = cfg.n_kv_heads * cfg.d_head;
  const uint64_t row_bytes = uint64_t{cfg.d_model} * 4;
  const uint32_t flash_lmem = va::llm_ops_v3_detail::flash_lmem_bytes_required(cfg.d_head);
  const uint32_t flash_grid_x =
      ((seq_len + va::kLlmV3FlashTileBr - 1u) / va::kLlmV3FlashTileBr) * cfg.n_q_heads;

  EventHandle chain;
  const BufferHandle* cur_x = &dev.act_a;
  const BufferHandle* next_x = &dev.act_b;

  // Device-to-device embedding lookup from resident tok_embeddings (zero host activation transfer).
  for (uint32_t s = 0; s < seq_len; ++s) {
    const uint64_t src_off = uint64_t{token_ids[s]} * row_bytes;
    const uint64_t dst_off = uint64_t{s} * row_bytes;
    if (!enqueue_copy_d2d(session.queue, *cur_x, dst_off, dev.tok_embeddings,
                          src_off, row_bytes, &chain)) {
      return false;
    }
  }

  for (uint32_t l = 0; l < cfg.n_layers; ++l) {
    const DeviceLayerWeights& dl = dev.layers[l];

    // 1. Attention RMSNorm
    {
      va::LlmOpsV3Arguments arg{};
      arg.op_code = va::kLlmOpRmsNormFp32;
      arg.dim0 = seq_len;
      arg.dim1 = cfg.d_model;
      arg.eps_or_theta_bits = va::kLlmV3DefaultEpsBits;
      arg.src0_addr = cur_x->addr;
      arg.src1_addr = dl.attention_norm.addr;
      arg.dst_addr = dev.norm_buf.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
    }

    // 2. Q / K / V Linear Projections
    {
      va::LlmOpsV3Arguments arg_q{};
      arg_q.op_code = va::kLlmOpGemvFp32;
      arg_q.dim0 = seq_len;
      arg_q.dim1 = cfg.d_model;
      arg_q.dim2 = cfg.d_model;
      arg_q.src0_addr = dev.norm_buf.addr;
      arg_q.src1_addr = dl.wq.addr;
      arg_q.dst_addr = dev.q_raw.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_q, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_k{};
      arg_k.op_code = va::kLlmOpGemvFp32;
      arg_k.dim0 = seq_len;
      arg_k.dim1 = cfg.d_model;
      arg_k.dim2 = kv_dim;
      arg_k.src0_addr = dev.norm_buf.addr;
      arg_k.src1_addr = dl.wk.addr;
      arg_k.dst_addr = dev.k_raw.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_k, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_v{};
      arg_v.op_code = va::kLlmOpGemvFp32;
      arg_v.dim0 = seq_len;
      arg_v.dim1 = cfg.d_model;
      arg_v.dim2 = kv_dim;
      arg_v.src0_addr = dev.norm_buf.addr;
      arg_v.src1_addr = dl.wv.addr;
      arg_v.dst_addr = dev.v_buf.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_v, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
    }

    // 3. RoPE on Q and K
    {
      va::LlmOpsV3Arguments arg_rq{};
      arg_rq.op_code = va::kLlmOpRopeFp32;
      arg_rq.dim0 = seq_len;
      arg_rq.dim1 = cfg.n_q_heads;
      arg_rq.dim2 = cfg.d_head;
      arg_rq.pos_offset = pos_offset;
      arg_rq.eps_or_theta_bits = va::kLlmV3DefaultThetaBits;
      arg_rq.src0_addr = dev.q_raw.addr;
      arg_rq.dst_addr = dev.q_rope.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_rq, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_rk{};
      arg_rk.op_code = va::kLlmOpRopeFp32;
      arg_rk.dim0 = seq_len;
      arg_rk.dim1 = cfg.n_kv_heads;
      arg_rk.dim2 = cfg.d_head;
      arg_rk.pos_offset = pos_offset;
      arg_rk.eps_or_theta_bits = va::kLlmV3DefaultThetaBits;
      arg_rk.src0_addr = dev.k_raw.addr;
      arg_rk.dst_addr = dev.k_rope.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_rk, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
    }

    // 4. KV Cache Append
    {
      va::LlmOpsV3Arguments arg_kv{};
      arg_kv.op_code = va::kLlmOpKvCacheAppendFp32;
      arg_kv.dim0 = seq_len;
      arg_kv.dim1 = cfg.n_kv_heads;
      arg_kv.dim2 = cfg.d_head;
      arg_kv.dim3 = cfg.max_seq;
      arg_kv.pos_offset = pos_offset;
      arg_kv.src0_addr = dev.k_rope.addr;
      arg_kv.src1_addr = dev.v_buf.addr;
      arg_kv.dst_addr = dl.k_cache.addr;
      arg_kv.dst2_addr = dl.v_cache.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_kv, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
    }

    // 5. Causal FlashAttention for prefill (seq_len > 1), GQA Decode over KV cache for decode
    if (seq_len > 1u) {
      va::LlmOpsV3Arguments arg_attn{};
      arg_attn.op_code = va::kLlmOpFlashAttnTiledFp32;
      arg_attn.flags = va::kLlmFlagCausal;
      arg_attn.dim0 = seq_len;
      arg_attn.dim1 = cfg.n_q_heads;
      arg_attn.dim2 = cfg.d_head;
      arg_attn.dim3 = cfg.n_kv_heads;
      arg_attn.pos_offset = 0;
      arg_attn.src0_addr = dev.q_rope.addr;
      arg_attn.src1_addr = dev.k_rope.addr;
      arg_attn.src2_addr = dev.v_buf.addr;
      arg_attn.dst_addr = dev.attn_out.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_attn, flash_grid_x,
                          block_x, flash_lmem, &chain, launch_count)) {
        return false;
      }
    } else {
      va::LlmOpsV3Arguments arg_attn{};
      arg_attn.op_code = va::kLlmOpGqaDecodeAttnFp32;
      arg_attn.dim0 = pos_offset + 1u;
      arg_attn.dim1 = cfg.n_q_heads;
      arg_attn.dim2 = cfg.d_head;
      arg_attn.dim3 = cfg.n_kv_heads;
      arg_attn.src0_addr = dev.q_rope.addr;
      arg_attn.src1_addr = dl.k_cache.addr;
      arg_attn.src2_addr = dl.v_cache.addr;
      arg_attn.dst_addr = dev.attn_out.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_attn, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
    }

    // 6. Output Projection + Residual Add
    {
      va::LlmOpsV3Arguments arg_o{};
      arg_o.op_code = va::kLlmOpGemvFp32;
      arg_o.dim0 = seq_len;
      arg_o.dim1 = cfg.d_model;
      arg_o.dim2 = cfg.d_model;
      arg_o.src0_addr = dev.attn_out.addr;
      arg_o.src1_addr = dl.wo.addr;
      arg_o.dst_addr = dev.proj_out.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_o, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_add{};
      arg_add.op_code = va::kLlmOpAddFp32;
      arg_add.dim0 = seq_len;
      arg_add.dim1 = cfg.d_model;
      arg_add.src0_addr = cur_x->addr;
      arg_add.src1_addr = dev.proj_out.addr;
      arg_add.dst_addr = next_x->addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_add, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
      std::swap(cur_x, next_x);
    }

    // 7. FFN RMSNorm + SwiGLU MLP + Residual Add
    {
      va::LlmOpsV3Arguments arg_fn{};
      arg_fn.op_code = va::kLlmOpRmsNormFp32;
      arg_fn.dim0 = seq_len;
      arg_fn.dim1 = cfg.d_model;
      arg_fn.eps_or_theta_bits = va::kLlmV3DefaultEpsBits;
      arg_fn.src0_addr = cur_x->addr;
      arg_fn.src1_addr = dl.ffn_norm.addr;
      arg_fn.dst_addr = dev.norm_buf.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_fn, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_gate{};
      arg_gate.op_code = va::kLlmOpGemvFp32;
      arg_gate.dim0 = seq_len;
      arg_gate.dim1 = cfg.d_model;
      arg_gate.dim2 = cfg.d_ff;
      arg_gate.src0_addr = dev.norm_buf.addr;
      arg_gate.src1_addr = dl.w_gate.addr;
      arg_gate.dst_addr = dev.ffn_gate.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_gate, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_up{};
      arg_up.op_code = va::kLlmOpGemvFp32;
      arg_up.dim0 = seq_len;
      arg_up.dim1 = cfg.d_model;
      arg_up.dim2 = cfg.d_ff;
      arg_up.src0_addr = dev.norm_buf.addr;
      arg_up.src1_addr = dl.w_up.addr;
      arg_up.dst_addr = dev.ffn_up.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_up, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_swi{};
      arg_swi.op_code = va::kLlmOpSwigluFp32;
      arg_swi.dim0 = seq_len;
      arg_swi.dim1 = cfg.d_ff;
      arg_swi.src0_addr = dev.ffn_gate.addr;
      arg_swi.src1_addr = dev.ffn_up.addr;
      arg_swi.dst_addr = dev.ffn_swiglu.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_swi, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_down{};
      arg_down.op_code = va::kLlmOpGemvFp32;
      arg_down.dim0 = seq_len;
      arg_down.dim1 = cfg.d_ff;
      arg_down.dim2 = cfg.d_model;
      arg_down.src0_addr = dev.ffn_swiglu.addr;
      arg_down.src1_addr = dl.w_down.addr;
      arg_down.dst_addr = dev.proj_out.addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_down, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }

      va::LlmOpsV3Arguments arg_add2{};
      arg_add2.op_code = va::kLlmOpAddFp32;
      arg_add2.dim0 = seq_len;
      arg_add2.dim1 = cfg.d_model;
      arg_add2.src0_addr = cur_x->addr;
      arg_add2.src1_addr = dev.proj_out.addr;
      arg_add2.dst_addr = next_x->addr;
      if (!enqueue_llm_op(session.queue, session.kernel, arg_add2, 1u, block_x,
                          0u, &chain, launch_count)) {
        return false;
      }
      std::swap(cur_x, next_x);
    }
  }

  // Final RMSNorm + LM head projection
  {
    va::LlmOpsV3Arguments arg_fn{};
    arg_fn.op_code = va::kLlmOpRmsNormFp32;
    arg_fn.dim0 = seq_len;
    arg_fn.dim1 = cfg.d_model;
    arg_fn.eps_or_theta_bits = va::kLlmV3DefaultEpsBits;
    arg_fn.src0_addr = cur_x->addr;
    arg_fn.src1_addr = dev.norm.addr;
    arg_fn.dst_addr = dev.norm_buf.addr;
    if (!enqueue_llm_op(session.queue, session.kernel, arg_fn, 1u, block_x,
                        0u, &chain, launch_count)) {
      return false;
    }

    va::LlmOpsV3Arguments arg_lm{};
    arg_lm.op_code = va::kLlmOpGemvFp32;
    arg_lm.dim0 = seq_len;
    arg_lm.dim1 = cfg.d_model;
    arg_lm.dim2 = cfg.vocab_size;
    arg_lm.src0_addr = dev.norm_buf.addr;
    arg_lm.src1_addr = dev.lm_head.addr;
    arg_lm.dst_addr = dev.logits.addr;
    if (!enqueue_llm_op(session.queue, session.kernel, arg_lm, 1u, block_x,
                        0u, &chain, launch_count)) {
      return false;
    }
  }

  // Read back only the final token's logits [vocab_size].
  const uint64_t logits_bytes = uint64_t{cfg.vocab_size} * 4;
  const uint64_t last_logits_off = uint64_t{seq_len - 1u} * logits_bytes;
  std::vector<uint8_t> logits_raw(logits_bytes);
  EventHandle ev_read;
  VX_CHECK(vx_enqueue_read(session.queue, logits_raw.data(), dev.logits.h,
                           last_logits_off, logits_bytes, 1, &chain.h, &ev_read.h));
  VX_CHECK(vx_event_wait_value(ev_read.h, 1, VX_TIMEOUT_INFINITE));
  ev_read.release();
  chain.release();
  *final_d2h_bytes += logits_bytes;
  *out_last_logits = unpack_f32_bytes(logits_raw);
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

  std::string weights_file = opts.weights_path;
  bool remove_temp_weights = false;
  if (weights_file.empty()) {
    char tmpl[] = "/tmp/aigpu_llm_XXXXXX.safetensors";
    const int fd = mkstemps(tmpl, 12);
    if (fd < 0) {
      std::cerr << "FAILED mkstemps for deterministic .safetensors checkpoint\n";
      return 1;
    }
    close(fd);
    weights_file = tmpl;
    remove_temp_weights = true;
    std::string ser_err;
    if (!aigpu::llm::write_micro_llama_safetensors(weights_file, aigpu::llm::MicroLlamaConfig{},
                                                  &ser_err)) {
      std::remove(weights_file.c_str());
      std::cerr << "FAILED write_micro_llama_safetensors: " << ser_err << '\n';
      return 1;
    }
  }

  aigpu::llm::SafetensorsFile sf;
  std::string load_err;
  if (!aigpu::llm::SafetensorsFile::load(weights_file, &sf, &load_err)) {
    if (remove_temp_weights) {
      std::remove(weights_file.c_str());
    }
    std::cerr << "FAILED SafetensorsFile::load(" << weights_file << "): " << load_err << '\n';
    return 1;
  }
  if (remove_temp_weights) {
    std::remove(weights_file.c_str());
  }

  LlamaWeights weights;
  if (!load_llama_weights(sf, &weights, &load_err)) {
    std::cerr << "FAILED load_llama_weights: " << load_err << '\n';
    return 1;
  }

  if (opts.prompt_len + opts.decode_steps > weights.cfg.max_seq) {
    std::cerr << "FAILED prompt_len (" << opts.prompt_len << ") + decode_steps ("
              << opts.decode_steps << ") exceeds max_seq (" << weights.cfg.max_seq << ")\n";
    return 2;
  }

  const std::vector<uint32_t> prompt_ids =
      tokenize_ascii(opts.prompt, opts.prompt_len, weights.cfg.vocab_size);
  const CpuRefResult cpu_ref =
      run_cpu_reference_f64(weights, prompt_ids, opts.decode_steps);

  DeviceSession session;
  if (vx_device_open(0, &session.device) != VX_SUCCESS) {
    std::cerr << "FAILED vx_device_open\n";
    return 1;
  }
  uint32_t block_x = kMaxBlockThreads;
  if (!query_device_block_threads(session.device, weights.cfg.d_head, &block_x)) {
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
  if (vx_module_load_file(session.device, opts.kernel_path.c_str(), &session.module) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_load_file (" << opts.kernel_path << ")\n";
    return 1;
  }
  if (vx_module_get_kernel(session.module, "main", &session.kernel) != VX_SUCCESS) {
    std::cerr << "FAILED vx_module_get_kernel\n";
    return 1;
  }

  uint32_t total_launches = 0;
  uint64_t init_h2d_bytes = 0;
  uint64_t final_d2h_bytes = 0;
  uint32_t total_mismatches = 0;
  uint32_t exact_decode_matches = 0;
  bool prefill_tok_match = false;
  double worst_max_abs_err = 0.0;
  std::vector<uint32_t> device_decode_tokens;
  device_decode_tokens.reserve(opts.decode_steps);

  {
    DeviceLlamaState dev_state;
    if (!allocate_and_upload_weights(session, weights, &dev_state, &init_h2d_bytes)) {
      return 1;
    }

    auto verify_step = [&](const char* phase, uint32_t step_idx, uint32_t pos_start,
                           uint32_t seq_len, uint32_t step_launches,
                           const std::vector<float>& dev_logits,
                           const std::vector<double>& ref_logits,
                           uint32_t ref_tok, bool* out_tok_match) -> uint32_t {
      const uint32_t dev_tok = argmax_f32(dev_logits, 0, weights.cfg.vocab_size);
      double step_max_err = 0.0;
      uint32_t step_mismatches = 0;
      for (uint32_t v = 0; v < weights.cfg.vocab_size; ++v) {
        const double err = std::fabs(static_cast<double>(dev_logits[v]) - ref_logits[v]);
        if (!std::isfinite(dev_logits[v]) || err > step_max_err) {
          step_max_err = std::isfinite(dev_logits[v]) ? err : INFINITY;
        }
        if (!std::isfinite(dev_logits[v]) || err > kLogitsMaxAbsTolerance) {
          if (total_mismatches + step_mismatches < kMaxPrintedErrors) {
            std::printf("*** logit mismatch [%s step=%u vocab=%u] expected=%.8g actual=%.8g err=%.3e\n",
                        phase, step_idx, v, ref_logits[v],
                        static_cast<double>(dev_logits[v]), err);
          }
          ++step_mismatches;
        }
      }
      const bool tok_match = (dev_tok == ref_tok);
      *out_tok_match = tok_match;
      if (!tok_match) {
        ++step_mismatches;
      }
      total_mismatches += step_mismatches;
      if (!std::isfinite(step_max_err) || step_max_err > worst_max_abs_err) {
        worst_max_abs_err = step_max_err;
      }
      std::printf("AIGPU_LLM_STEP phase=%s step=%u pos=%u seq_len=%u launches=%u "
                  "dev_tok=%u ref_tok=%u token_match=%u max_abs_err=%.6e tol=%.6e mismatches=%u\n",
                  phase, step_idx, pos_start, seq_len, step_launches, dev_tok, ref_tok,
                  tok_match ? 1u : 0u, step_max_err, kLogitsMaxAbsTolerance, step_mismatches);
      return dev_tok;
    };

    // Prefill phase: prompt tokens [0 .. P-1] -> samples first next-token seed.
    std::vector<float> prefill_logits;
    uint32_t prefill_launches = 0;
    if (!run_device_forward_step(session, weights.cfg, dev_state, prompt_ids, 0u,
                                 block_x, &prefill_launches, &prefill_logits,
                                 &final_d2h_bytes)) {
      return 1;
    }
    total_launches += prefill_launches;
    uint32_t cur_tok = verify_step("prefill", 0u, 0u, opts.prompt_len, prefill_launches,
                                   prefill_logits, cpu_ref.prefill_logits,
                                   cpu_ref.prefill_token, &prefill_tok_match);

    // Autoregressive decode phase: T steps at pos = P .. P+T-1 using growing KV cache.
    for (uint32_t step = 0; step < opts.decode_steps; ++step) {
      const uint32_t pos = opts.prompt_len + step;
      std::vector<float> step_logits;
      uint32_t step_launches = 0;
      if (!run_device_forward_step(session, weights.cfg, dev_state, {cur_tok}, pos,
                                   block_x, &step_launches, &step_logits,
                                   &final_d2h_bytes)) {
        return 1;
      }
      total_launches += step_launches;
      bool step_tok_match = false;
      cur_tok = verify_step("decode", step, pos, 1u, step_launches,
                            step_logits, cpu_ref.decode_logits[step],
                            cpu_ref.decode_tokens[step], &step_tok_match);
      if (step_tok_match) {
        ++exact_decode_matches;
      }
      device_decode_tokens.push_back(cur_tok);
    }
  }

  std::printf("AIGPU_LLM_SUMMARY layers=%u vocab=%u d_model=%u n_q_heads=%u n_kv_heads=%u "
              "d_head=%u d_ff=%u safetensors_tensors=%zu prompt_tokens=%u decode_tokens=%u "
              "total_launches=%u init_h2d_bytes=%llu intermediate_h2d_bytes=0 "
              "intermediate_d2h_bytes=0 final_d2h_bytes=%llu max_abs_err=%.6e tol=%.6e "
              "prefill_tok_match=%u exact_token_matches=%u/%u dev_tokens=%s ref_tokens=%s "
              "mismatches=%u\n",
              weights.cfg.n_layers, weights.cfg.vocab_size, weights.cfg.d_model,
              weights.cfg.n_q_heads, weights.cfg.n_kv_heads, weights.cfg.d_head,
              weights.cfg.d_ff, sf.num_tensors(), opts.prompt_len, opts.decode_steps,
              total_launches, static_cast<unsigned long long>(init_h2d_bytes),
              static_cast<unsigned long long>(final_d2h_bytes), worst_max_abs_err,
              kLogitsMaxAbsTolerance, prefill_tok_match ? 1u : 0u,
              exact_decode_matches, opts.decode_steps,
              format_token_list(device_decode_tokens).c_str(),
              format_token_list(cpu_ref.decode_tokens).c_str(), total_mismatches);

  vx_device_dump_perf(session.device, stdout);
  session.release();

  if (total_mismatches != 0 || !prefill_tok_match
      || exact_decode_matches != opts.decode_steps) {
    std::cout << "FAILED!\n";
    return 1;
  }
  std::cout << "PASSED!\n";
  return 0;
}
