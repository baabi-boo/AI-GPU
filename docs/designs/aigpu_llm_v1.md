# End-to-End Native Llama Decoder Engine (`aigpu_llm`)

## Overview

[`tests/regression/aigpu_llm/`](../../tests/regression/aigpu_llm/main.cpp) is a
self-contained C++17 Llama-architecture decoder inference engine targeting
Vortex (`vortex2.h`, `XLEN=64`, default `p02-tfr` STD/TFR + LMEM configuration)
and executing all device operators on the unified
[`sw/kernel/ai/llm_ops_v3.cpp`](../../sw/kernel/ai/llm_ops_v3.cpp) kernel ABI
([`sw/common/ai_llm_ops_v3_args.h`](../../sw/common/ai_llm_ops_v3_args.h)).

Source presence does not constitute execution qualification; SimX and native
processor RTL (`rtlsim`) verification remain separate execution evidence.

## Architecture and Model Geometry

Default deterministic micro-Llama configuration:

| Parameter | Default | Constraint / Notes |
|---|---:|---|
| `vocab_size` | 32 | Byte tokenizer maps ASCII prompt bytes modulo `vocab_size` |
| `n_layers` | 2 | Decoder layers (`layers.0`, `layers.1`) |
| `d_model` | 16 | `n_q_heads * d_head` |
| `n_q_heads` | 2 | Query heads |
| `n_kv_heads` | 1 | Key/value heads (`2:1` GQA, `n_q_heads % n_kv_heads == 0`) |
| `d_head` | 8 | Even, `<= kLlmV3FlashMaxHeadDim` (`64`) |
| `d_ff` | 16 | SwiGLU feed-forward inner width |
| `max_seq` | 16 | Resident KV-cache sequence capacity per layer |
| `prompt_len` | 4 | Default prefill prompt tokens (`P = 4`, positions `0..3`) |
| `decode_steps` | 4 | Default autoregressive decode steps (`T = 4`, positions `4..7`) |

## Binary `.safetensors` Reader and Deterministic Serializer

[`tests/regression/aigpu_llm/safetensors_reader.h`](../../tests/regression/aigpu_llm/safetensors_reader.h)
implements:

- `SafetensorsFile::load(path, ...)` / `SafetensorsFile::parse_bytes(...)`:
  strictly validates the 8-byte little-endian `uint64_t` JSON header length
  (`0 < header_len <= 100 MiB`), UTF-8 JSON object metadata, unique tensor keys,
  supported dtypes (`F32`, `F16`, `BF16`, `I8`, `U8`, `BOOL`, `F64`, `I64`,
  `U64`, `I32`, `U32`, `I16`, `U16`, `F8_E4M3`, `F8_E5M2`), checked shape byte
  counts, monotonic non-overlapping `data_offsets`, and contiguous payload span.
  Decodes `F32`, `F16`, and `BF16` weights into host `float` arrays.
- `write_micro_llama_safetensors(path, cfg)`: generates deterministic SplitMix64
  FP32 weights in standard `.safetensors` binary format when `--weights` is not
  provided, and parses them back through `SafetensorsFile::load(...)` so the
  binary `.safetensors` path is always exercised.
- Supports both Llama-style names (`tok_embeddings.weight`,
  `layers.{l}.attention_norm.weight`, `layers.{l}.wq.weight`, `wk.weight`,
  `wv.weight`, `wo.weight`, `ffn_norm.weight`, `w_gate.weight`, `w_up.weight`,
  `w_down.weight`, `norm.weight`, `lm_head.weight`) and HuggingFace Llama
  aliases (`model.embed_tokens.weight`, `model.layers.{l}.*`).

## Device-Resident Prefill and Autoregressive Decode Dataflow

All weights and KV-cache buffers are allocated and uploaded once before prefill.
Between layers and operators, all activations stay resident in device memory
(`intermediate_h2d_bytes = 0`, `intermediate_d2h_bytes = 0`), with only the final
step logits `[vocab_size]` read back to host after each forward pass:

1. **Embedding Lookup**: `vx_enqueue_copy` slices token rows from resident
   `tok_embeddings` on-device into the active hidden buffer.
2. **Per-Layer Attention Block (`l = 0, 1`)**:
   - `OP_RMSNORM_FP32` (`attention_norm`)
   - `OP_GEMV_FP32` (`wq`, `wk`, `wv`)
   - `OP_ROPE_FP32` on `Q` and `K` (`pos_offset = 0` for prefill, `pos` for decode)
   - `OP_KV_CACHE_APPEND_FP32` appending `K, V` into resident `k_cache`, `v_cache`
   - `OP_FLASH_ATTN_TILED_FP32` with `kLlmFlagCausal` and LMEM tiling during
     prefill (`seq_len > 1`), or `OP_GQA_DECODE_ATTN_FP32` over `[0..pos]` during
     single-token decode (`seq_len == 1`)
   - `OP_GEMV_FP32` (`wo`) followed by `OP_ADD_FP32` (residual connection)
3. **Per-Layer SwiGLU FFN Block (`l = 0, 1`)**:
   - `OP_RMSNORM_FP32` (`ffn_norm`)
   - `OP_GEMV_FP32` (`w_gate`, `w_up`) -> `OP_SWIGLU_FP32` -> `OP_GEMV_FP32` (`w_down`)
   - `OP_ADD_FP32` (residual connection)
4. **Output Head & Greedy Sampling**:
   - Final `OP_RMSNORM_FP32` (`norm`) -> `OP_GEMV_FP32` (`lm_head`)
   - D2H read of the final token's `[vocab_size]` logits and greedy `argmax`.

Each forward pass executes `2 * 13 + 2 = 28` kernel launches (`140` total device
kernel launches across 1 prefill pass at positions `0..3` plus 4 autoregressive
decode passes at positions `4..7`).

## Verification Contract

[`tests/regression/aigpu_llm/main.cpp`](../../tests/regression/aigpu_llm/main.cpp)
evaluates the identical 2-layer Llama prefill and 4-step autoregressive decode
sequence in IEEE-754 `double` on CPU and asserts at prefill and every decode step:

1. Exact greedy token-for-token match across prefill and all `T` decode steps
   (`exact_token_matches == T`).
2. Finite logits with `max_abs_err <= 5e-4` across all `vocab_size` logits at
   every step.
