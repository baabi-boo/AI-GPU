# Native AI LLM Operator Contract v3

## Scope and Additive Separation

`ai_llm_ops_v3` is an additive v3 native LLM inference operator kernel implemented
in [`sw/kernel/ai/llm_ops_v3.cpp`](../../sw/kernel/ai/llm_ops_v3.cpp), sharing a
128-byte little-endian POD ABI through
[`sw/common/ai_llm_ops_v3_args.h`](../../sw/common/ai_llm_ops_v3_args.h), and
exercised by [`tests/regression/ai_llm_ops_v3/main.cpp`](../../tests/regression/ai_llm_ops_v3/main.cpp).

This contract is strictly additive and leaves v1 (`ai_matmul_args.h`,
`matmul.cpp`) and v2 (`ai_ops_v2_args.h`, `ops_v2.cpp`) files untouched:

- `LlmOpsV3Arguments` uses `abi_version = 3` and `byte_size = 128`.
- All device transcendental and sqrt operations are self-contained bare-metal
  FP32 routines (`fast_expf`, `fast_logf`, `fast_sinf`, `fast_cosf`, and
  RISC-V `fsqrt.s`) with zero external `libm` symbol dependencies.
- Source availability does not constitute execution qualification; SimX and
  native processor RTL verification remain separate execution evidence.

## Implemented Operators

All eight opcodes dispatch from [`sw/kernel/ai/llm_ops_v3.cpp`](../../sw/kernel/ai/llm_ops_v3.cpp)
via `arg.op_code`:

| Operator | `op_code` | Logical Shapes | Inputs | Outputs | Pre-frozen Tolerance |
|---|---:|---|---|---|---|
| `rope_fp32` | 1 | `[seq_len, n_heads, d_head]`, even `d_head` | `src0` (`fp32`) | `dst` (`fp32`) | `max_abs_err <= 1e-4` |
| `swiglu_fp32` | 2 | `[rows, cols]` | `src0=gate`, `src1=up` (`fp32`) | `dst` (`fp32`) | `max_abs_err <= 1e-4` |
| `kv_cache_append_fp32` | 3 | `new[n_new, n_kv_heads, d_head] -> cache[max_seq, n_kv_heads, d_head]` | `src0=k_new`, `src1=v_new` (`fp32`) | `dst=k_cache`, `dst2=v_cache` (`fp32`) | `0.0` (bit-exact `0` ULP) |
| `gqa_decode_attn_fp32` | 4 | `q[1, n_q_heads, d_head]`, `kv[kv_len, n_kv_heads, d_head]` | `src0=q`, `src1=k_cache`, `src2=v_cache` (`fp32`) | `dst` (`fp32`) | `max_abs_err <= 1e-4` |
| `flash_attn_tiled_fp32` | 5 | `q[seq_len, n_q_heads, d_head]`, `kv[seq_len, n_kv_heads, d_head]` | `src0=q`, `src1=k`, `src2=v` (`fp32`) | `dst` (`fp32`) | `max_abs_err <= 1e-4` |
| `rmsnorm_fp32` | 6 | `[rows, cols]`, `weight[cols]` | `src0=x`, `src1=weight` (`fp32`) | `dst` (`fp32`) | `max_abs_err <= 1e-4` |
| `add_fp32` | 7 | `[rows, cols]` | `src0=a`, `src1=b` (`fp32`) | `dst` (`fp32`) | `max_abs_err <= 1e-4` |
| `gemv_fp32` | 8 | `A[M, K] @ B[N, K]^T` -> `C[M, N]` | `src0=A`, `src1=B` (`fp32`) | `dst=C` (`fp32`) | `max_abs_err <= 1e-4` |

### Operator Semantics

- **`rope_fp32` (`op_code = 1`)**: Half-split Llama rotary position embedding over
  `x[seq, head, j]` and `x[seq, head, j + d_head / 2]` for `0 <= j < d_head / 2`,
  with angle `(pos_offset + seq) * theta^(-2j / d_head)` where
  `theta = bits_to_f32(eps_or_theta_bits)` (default `10000.0f` = `0x461c4000`).
  Supports both multi-token prefill (`pos_offset = 0`) and single-token
  autoregressive decode (`pos_offset = t`).
- **`swiglu_fp32` (`op_code = 2`)**: Computes `(gate / (1 + exp(-gate))) * up`
  using the branch-stabilized SiLU evaluation (`x / (1 + exp(-x))` for `x >= 0`,
  `(x * exp(x)) / (1 + exp(x))` for `x < 0`).
- **`kv_cache_append_fp32` (`op_code = 3`)**: Copies `n_new * n_kv_heads * d_head`
  32-bit words from `k_new` and `v_new` into `k_cache` and `v_cache` starting at
  token index `pos_offset` (`pos_offset + n_new <= max_seq`), preserving all
  other cache slots untouched and copying bit-exact IEEE-754 patterns.
- **`gqa_decode_attn_fp32` (`op_code = 4`)**: Grouped-query autoregressive decode
  attention for `[1, n_q_heads, d_head]` over `[kv_len, n_kv_heads, d_head]`
  with `group_size = n_q_heads / n_kv_heads` (`n_q_heads % n_kv_heads == 0`),
  computing single-pass online-rescaled `softmax((q @ K^T) / sqrt(d_head)) @ V`
  without materializing an attention score buffer.
- **`flash_attn_tiled_fp32` (`op_code = 5`)**: Tiled FlashAttention using
  on-core local memory (`__local_mem()`), tiling `Q` and `O` by `Br = 4` rows
  and streaming `K` and `V` tiles of `Bc = 4` tokens into LMEM while keeping a
  `Br * Bc` tile score scratchpad in LMEM. Maintains per-row online running max
  `m_i`, running normalizer `l_i`, and rescaled output `O_i` (zero global
  `N x N` score matrix). Supports GQA head mapping (`n_q_heads % n_kv_heads == 0`)
  and causal masking (`flags & kLlmFlagCausal`, masking `j > i + pos_offset`).
  Requires `blockDim.x >= 4` and `d_head <= 64`, with dynamic LMEM allocation
  `4 * (2 * Br * d_head + 2 * Bc * d_head + Br * Bc)` bytes.
- **`rmsnorm_fp32` (`op_code = 6`)**: Row-wise `x / sqrt(mean(x^2) + eps) * weight`
  using `fsqrt.s` and `eps = bits_to_f32(eps_or_theta_bits)` (default `1e-5f` = `0x3727c5ac`).
- **`add_fp32` (`op_code = 7`)**: Elementwise residual addition `dst = src0 + src1`.
- **`gemv_fp32` (`op_code = 8`)**: Row-major linear projection `dst = A @ B^T`
  for `A[M, K]` and `B[N, K]`, supporting both single-token decode (`M = 1`) and
  multi-token prefill (`M > 1`).

## Argument ABI (`LlmOpsV3Arguments`)

`LlmOpsV3Arguments` is a 128-byte, 8-byte-aligned, trivially copyable
little-endian struct defined in [`sw/common/ai_llm_ops_v3_args.h`](../../sw/common/ai_llm_ops_v3_args.h):

| Offset | Field | Type | Semantics |
|---:|---|---|---|
| 0 | `abi_version` | `u32` | `3` |
| 4 | `byte_size` | `u32` | `128` |
| 8 | `op_code` | `u32` | `1..8` (`LlmOpsV3OpCode`) |
| 12 | `flags` | `u32` | Bit 0 (`0x1`): causal mask for `flash_attn_tiled_fp32`; `0` for all other ops |
| 16 | `dim0` | `u32` | `seq_len` / `rows` / `n_new` / `kv_len` / `M` |
| 20 | `dim1` | `u32` | `n_heads` / `cols` / `n_kv_heads` / `n_q_heads` / `K` |
| 24 | `dim2` | `u32` | `d_head` (ops 1, 3, 4, 5) / `N` (op 8) / `0` otherwise |
| 28 | `dim3` | `u32` | `max_seq` (op 3) / `n_kv_heads` (ops 4, 5) / `0` otherwise |
| 32 | `pos_offset` | `u32` | Token position offset (ops 1, 3, 5) / `0` otherwise |
| 36 | `eps_or_theta_bits` | `u32` | IEEE-754 `fp32` `theta` (op 1) or `eps` (op 6) |
| 40 | `reserved0` | `u32` | `0` |
| 44 | `reserved1` | `u32` | `0` |
| 48 | `src0_addr` | `u64` | 4-byte-aligned nonzero device address |
| 56 | `src1_addr` | `u64` | 4-byte-aligned device address or `0` if unused |
| 64 | `src2_addr` | `u64` | 4-byte-aligned device address or `0` if unused |
| 72 | `dst_addr` | `u64` | 4-byte-aligned nonzero device address |
| 80 | `dst2_addr` | `u64` | 4-byte-aligned second output address (op 3) or `0` |
| 88..120 | `reserved64_0..4` | `u64[5]` | `0` |

`decode_llm_ops_v3_arguments` validates ABI version, byte size, allowed flag
bits, zero reserved fields, opcode-specific dimension constraints and integer
overflow bounds, floating-point parameter validity, 4-byte alignment,
non-wrapping address spans, zeroed unused pointers, and pairwise non-overlapping
active device buffers.

## Launch and Runtime Contract

- Target architecture: RV64 (`XLEN=64`), default `p02-tfr` STD/TFR configuration
  with `__local_mem()` enabled (`VX_CFG_LMEM_ENABLE`).
- Non-tiled operators launch with 1D geometry `gridDim = [grid_x, 1, 1]`,
  `blockDim = [block_x, 1, 1]`, `lmem_size = 0`.
- `flash_attn_tiled_fp32` launches with `grid_x = ceil(seq_len / 4) * n_q_heads`,
  `block_x >= 4` (e.g., `16`), and
  `lmem_size = 4 * (2 * 4 * d_head + 2 * 4 * d_head + 16)` bytes (for `d_head = 16`,
  `1088` bytes <= 16 KiB LMEM capacity).
