# Native AI operator contract v2

## Scope and separation from v1

`p03-native-operators-v2` is an additive v2 native operator library implemented in
[`sw/kernel/ai/ops_v2.cpp`](../../sw/kernel/ai/ops_v2.cpp), sharing its 72-byte
little-endian ABI through [`sw/common/ai_ops_v2_args.h`](../../sw/common/ai_ops_v2_args.h),
with a machine-readable manifest at
[`ci/project/p03_operator_manifest_v2.json`](../../ci/project/p03_operator_manifest_v2.json)
and native regression coverage in
[`tests/regression/ai_ops_v2/main.cpp`](../../tests/regression/ai_ops_v2/main.cpp).

This contract is strictly separate from the accepted v1 matmul contract
(`p03-native-operators-v1` in [`ai_operator_contract_v1.md`](ai_operator_contract_v1.md)
and [`p03_operator_manifest.json`](../../ci/project/p03_operator_manifest.json)):

- No v1 files (`contract.h`, `contract.cpp`, `runtime.h`, `runtime.cpp`,
  `ai_matmul_args.h`, `matmul.cpp`, `p03_operator_manifest.json`, or
  `ai_operator_contract_v1.md`) are modified.
- `OpsV2Arguments` uses `abi_version = 2` and `byte_size = 80`, distinct from
  v1 `MatmulArguments` (`abi_version = 1`, `byte_size = 56`) and from inherited
  `kernel_arg_t`.
- `p03-native-operators-v2` has no CPU fallback and is not an installed SDK API.
- Source availability does not constitute execution qualification; SimX and
  native processor RTL verification remain separate execution evidence.

## Implemented operator families

All seven operator families (ten opcodes) dispatch from the single unified
device binary [`sw/kernel/ai/ops_v2.cpp`](../../sw/kernel/ai/ops_v2.cpp) by
switching on `arg.op_code`:

| Operator | `op_code` | Shapes | Input dtypes | Output dtype | Pre-frozen tolerance |
|---|---:|---|---|---|---|
| `relu_fp32` | 1 | `[rows, cols]`, `rows * cols <= 65536` | `fp32` (`src0`) | `fp32` (`dst`) | `0` ULP / bit-exact (`-0.0f -> +0.0f`) |
| `gelu_fp32` | 2 | `[rows, cols]`, `rows * cols <= 65536` | `fp32` (`src0`) | `fp32` (`dst`) | `max_abs_err <= 1e-4` |
| `cast_fp32_to_fp16` | 3 | `[rows, cols]`, `rows * cols <= 65536` | `fp32` (`src0`) | `fp16` (`dst`) | `0` ULP / bit-exact (IEEE-754 RNE, `-25` subnormal bound) |
| `cast_fp16_to_fp32` | 4 | `[rows, cols]`, `rows * cols <= 65536` | `fp16` (`src0`) | `fp32` (`dst`) | `0` ULP / bit-exact |
| `cast_fp32_to_bf16` | 5 | `[rows, cols]`, `rows * cols <= 65536` | `fp32` (`src0`) | `bf16` (`dst`) | `0` ULP / bit-exact (IEEE-754 RNE) |
| `cast_bf16_to_fp32` | 6 | `[rows, cols]`, `rows * cols <= 65536` | `bf16` (`src0`) | `fp32` (`dst`) | `0` ULP / bit-exact |
| `softmax_fp32` | 7 | `[rows, cols]` row-wise, `rows * cols <= 65536` | `fp32` (`src0`) | `fp32` (`dst`) | `max_abs_err <= 1e-4` |
| `rmsnorm_fp32` | 8 | `[rows, cols]` row-wise + `weight[cols]` | `fp32` (`src0`, `src1`) | `fp32` (`dst`) | `max_abs_err <= 1e-4` |
| `layernorm_fp32` | 9 | `[rows, cols]` row-wise + `gamma[cols]`, `beta[cols]` | `fp32` (`src0`, `src1`, `src2`) | `fp32` (`dst`) | `max_abs_err <= 1e-4` |
| `attention_fp32` | 10 | `Q,K,V[seq_len, d_k]`, `seq_len <= 64`, `d_k <= 64` | `fp32` (`src0`, `src1`, `src2`) | `fp32` (`dst`) | `max_abs_err <= 1e-4` |

### Numerical behavior

- **`relu_fp32`**: Clamps negative finite values, `-inf`, and `-0.0f` to canonical
  `+0.0f` (`0x00000000`). Preserves NaN payloads and positive finite/`+inf` bits.
- **`gelu_fp32`**: Tanh-approximation GELU
  `0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))` evaluated using
  self-contained device FP32 range-reduced `exp` and cancellation-safe `tanh`
  polynomials without external `libm` symbol dependencies.
- **`cast_*`**: Exact IEEE-754 round-to-nearest-even bit conversions between
  `fp32` and `fp16`/`bf16`, including the FP16 subnormal `-25` exponent bound,
  signed zeros, infinities, and quiet NaN canonicalization.
- **`softmax_fp32`**: Row-wise `exp(x - row_max) / sum(exp(x - row_max))`
  using the self-contained device `exp` helper.
- **`rmsnorm_fp32`**: Row-wise `x / sqrt(mean(x^2) + eps) * weight` using
  hardware RISC-V `fsqrt.s`.
- **`layernorm_fp32`**: Row-wise `(x - mean) / sqrt(var + eps) * gamma + beta`
  using hardware RISC-V `fsqrt.s`.
- **`attention_fp32`**: Scaled dot-product attention
  `softmax((Q @ K^T) / sqrt(d_k)) @ V` for `[seq_len, d_k]` (`seq_len <= 64`,
  `d_k <= 64`), verified on `seq_len = 8, d_k = 16`.

## Argument ABI (`OpsV2Arguments`)

`OpsV2Arguments` is a 72-byte, 8-byte-aligned, trivially copyable little-endian
struct defined in [`sw/common/ai_ops_v2_args.h`](../../sw/common/ai_ops_v2_args.h):

| Offset | Field | Type | Required value / semantics |
|---:|---|---|---|
| 0 | `abi_version` | `u32` | `2` |
| 4 | `byte_size` | `u32` | `72` |
| 8 | `op_code` | `u32` | `1..10` (`OpsV2OpCode`) |
| 12 | `flags` | `u32` | `0` |
| 16 | `rows` | `u32` | Nonzero; `rows * cols <= 65536`; for attention `<= 64` |
| 20 | `cols` | `u32` | Nonzero; `rows * cols <= 65536`; for attention `<= 64` |
| 24 | `eps_bits` | `u32` | IEEE-754 `fp32` finite non-negative epsilon (default `1e-5f` = `0x3727c5ac`) |
| 28 | `reserved` | `u32` | `0` |
| 32 | `src0_addr` | `u64` | 4-byte-aligned nonzero device address |
| 40 | `src1_addr` | `u64` | 4-byte-aligned nonzero device address if required by `op_code`, else `0` |
| 48 | `src2_addr` | `u64` | 4-byte-aligned nonzero device address if required by `op_code`, else `0` |
| 56 | `dst_addr` | `u64` | 4-byte-aligned nonzero device address |
| 64 | `reserved64` | `u64` | `0` |

`decode_ops_v2_arguments` validates version, size, zero flags/reserved fields,
valid opcode, nonzero bounded shapes, `eps_bits` finiteness and sign for
normalization ops, 4-byte alignment, non-wrapping address ranges, unused address
fields being zero, and pairwise non-overlapping active device buffers.

## Launch and runtime model

- 1D launch geometry: `gridDim = [grid_x, 1, 1]`, `blockDim = [block_x, 1, 1]`,
  `lmem_size = 0`.
- Host regression runner uses `vortex2.h` with RAII `EventHandle` /
  `BufferHandle` / `DeviceSession` cleanup (releasing `queue` before `kernel`,
  `module`, buffers, and `device`), staged host buffers, poisoned output buffers,
  and independent double-precision / bit-exact CPU reference checks.
- Target profile: RV64 (`XLEN=64`), default `p02-tfr` STD/TFR configuration.
