# Tiny Transformer v2 native model contract

Contract ID: `p04-tiny-transformer-v2` (manifest:
[`ci/project/p04_transformer_v2_manifest.json`](../../ci/project/p04_transformer_v2_manifest.json)).

This is an **additive v2 model contract**. The accepted P04 v1 tiny-MLP model
contract (`p04-tiny-mlp-v1` in [`tiny_mlp_fixture_v1.md`](tiny_mlp_fixture_v1.md),
[`p04_model_manifest.json`](../../ci/project/p04_model_manifest.json), and
[`tests/regression/ai_mlp/`](../../tests/regression/ai_mlp/)) remains untouched.
Source presence of this contract does not grant phase acceptance or physical
hardware performance; SimX and native processor RTL execution evidence remain
separate observations.

## 1. Architecture and dimensions

The workload is a deterministic, synthetic, bias-free 1-layer pre-norm
Transformer block with the following fixed geometry:

| Parameter | Value | Description |
|---|---:|---|
| `seq_len` | 8 | Sequence length |
| `d_model` | 16 | Model hidden dimension |
| `n_heads` | 2 | Attention heads |
| `d_head` | 8 | Per-head dimension (`d_model / n_heads`) |
| `d_ff` | 16 | Feed-forward inner dimension |
| `rms_eps` | `1e-5` | RMSNorm epsilon (`0x3727c5ac`) |

### Execution graph and device-resident dataflow

All intermediate activations remain device-resident between kernel launches.
Only initial inputs and weights (plus final output poison) are transferred
host-to-device (`H2D`), and only final output logits `Y[8, 16]` FP32 are read
back device-to-host (`D2H`):

1. **Pre-RMSNorm 1** (`ops_v2` `rmsnorm_fp32`, `op_code=8`, `[8, 16]`):
   `N1 = rmsnorm(X, rms1_w, eps=1e-5)` -> device-resident `d_norm_f32`.
2. **Q/K/V Linear Projections** (`ops_v2` `cast_fp32_to_fp16` `op_code=3` +
   native `matmul` 4x `(8, 4, 16)` tiles + device-to-device `vx_enqueue_copy_rect`):
   `Q = N1_fp16 @ Wq`, `K = N1_fp16 @ Wk`, `V = N1_fp16 @ Wv`, each `[8, 16]` FP32.
3. **2-Head Scaled Dot-Product Attention** (device-to-device `vx_enqueue_copy_rect`
   head slicing + `ops_v2` `attention_fp32`, `op_code=10`, `[8, 8]` per head):
   For `h in {0, 1}`: `A_h = softmax((Q_h @ K_h^T) / sqrt(8)) @ V_h`, then
   `vx_enqueue_copy_rect` concatenates `A_0`, `A_1` into `A_concat[8, 16]` FP32.
4. **Output Projection & Residual 1**:
   - `ops_v2` `cast_fp32_to_fp16` on `A_concat`, then native `matmul` 4x `(8, 4, 16)`
     tiles with `Wo` -> `A_proj[8, 16]` FP32.
   - Residual addition `X_mid = X + A_proj` executed natively on-device by casting
     `X` and `A_proj` via `ops_v2` `cast_fp32_to_fp16`, packing `[X_half | A_proj_half]`
     per 8-column slice via `vx_enqueue_copy_rect`, and multiplying by the exact
     `[I_8; I_8]` FP16 identity-add tiles `W_add` via native `matmul` (`(8, 4, 16)`).
5. **Pre-RMSNorm 2** (`ops_v2` `rmsnorm_fp32`, `op_code=8`, `[8, 16]`):
   `N2 = rmsnorm(X_mid, rms2_w, eps=1e-5)` -> device-resident `d_norm_f32`.
6. **Feed-Forward Network (`W1` + GELU + `W2`) & Residual 2**:
   - `ops_v2` `cast_fp32_to_fp16` on `N2` -> native `matmul` 4x `(8, 4, 16)` with
     `W1` -> `FFN_h[8, 16]` FP32.
   - `ops_v2` `gelu_fp32` (`op_code=2`, `[8, 16]`): `FFN_a = gelu(FFN_h)` ->
     device-resident `d_ffn_a_f32`.
   - `ops_v2` `cast_fp32_to_fp16` on `FFN_a` -> native `matmul` 4x `(8, 4, 16)`
     with `W2` -> `FFN_out[8, 16]` FP32.
   - Residual addition `Y = X_mid + FFN_out` on-device via `cast_fp32_to_fp16`,
     `vx_enqueue_copy_rect`, and native `matmul` with `W_add`.

Total native dispatches per block execution: 13 `ops_v2` launches (`2 rmsnorm_fp32`,
`2 attention_fp32`, `1 gelu_fp32`, `8 cast_fp32_to_fp16`) and 32 `(8, 4, 16)`
native `matmul` tile launches (45 launches total), with zero intermediate
host↔device transfers.

## 2. Deterministic seeded weights and inputs

All inputs and weights are generated deterministically in C++ and Python from
fixed 64-bit SplitMix64 streams (zero external downloads or proprietary assets):

```text
state = (state + 0x9E3779B97F4A7C15) mod 2^64
z = state
z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) mod 2^64
z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) mod 2^64
z = z ^ (z >> 31)
u = (ldexp(double(z >> 40), -24) * 2.0 - 1.0) * scale
```

| Tensor | Seed | Shape | Scale / range | Representation |
|---|---|---|---|---|
| `X` | `0x50405B00` | `[8, 16]` | `[-0.25, +0.25]` | Exact FP16 values in FP32 |
| `rms1_w` | `0x50405B01` | `[16]` | `0.75 + 0.25 * u`, `u in [-1, 1]` | FP32 |
| `Wq` | `0x50405B02` | `[16, 16]` | `[-0.1875, +0.1875]` | Col-major FP16 tiles `(16, 4)` |
| `Wk` | `0x50405B03` | `[16, 16]` | `[-0.1875, +0.1875]` | Col-major FP16 tiles `(16, 4)` |
| `Wv` | `0x50405B04` | `[16, 16]` | `[-0.1875, +0.1875]` | Col-major FP16 tiles `(16, 4)` |
| `Wo` | `0x50405B05` | `[16, 16]` | `[-0.1875, +0.1875]` | Col-major FP16 tiles `(16, 4)` |
| `rms2_w` | `0x50405B06` | `[16]` | `0.75 + 0.25 * u`, `u in [-1, 1]` | FP32 |
| `W1` | `0x50405B07` | `[16, 16]` | `[-0.1875, +0.1875]` | Col-major FP16 tiles `(16, 4)` |
| `W2` | `0x50405B08` | `[16, 16]` | `[-0.1875, +0.1875]` | Col-major FP16 tiles `(16, 4)` |
| `W_add` | exact `[I_8; I_8]` | `[16, 8]` | `{0.0, 1.0}` | Col-major FP16 tiles `(16, 4)` |

## 3. CPU reference and pre-frozen numerical tolerance

The CPU reference evaluates the entire 1-layer Transformer block in IEEE-754
`double` (`fp64`) using `std::sqrt`, `std::exp`, and `std::tanh` against the
exact input and weight values.

- **Pre-frozen tolerance:** every element `y[i]` (`0 <= i < 128`) of the final
  device output `Y[8, 16]` must be finite and satisfy:
  `max_abs_err = max_i |double(y_device[i]) - y_ref_f64[i]| <= 5e-4`.
- With exact FP16-representable input `X` and projection weights in the seeded
  scales above, the expected end-to-end FP16-matmul + FP32-ops_v2 rounding delta
  against the `fp64` reference is ~`1.35e-4` (~3.7x margin under `5e-4`).

## 4. Target build and resident Python/PyTorch v2 bridge

- **Native runner:** [`tests/regression/ai_transformer_v2/main.cpp`](../../tests/regression/ai_transformer_v2/main.cpp)
  with [`tests/regression/ai_transformer_v2/Makefile`](../../tests/regression/ai_transformer_v2/Makefile),
  targeting `XLEN=64` and the `p02-tfr` STD/TFR profile (`vortex2.h`).
- **Device kernels:** compiles [`sw/kernel/ai/ops_v2.cpp`](../../sw/kernel/ai/ops_v2.cpp)
  as `kernel.vxbin` (`0x180000000`) and [`sw/kernel/ai/matmul.cpp`](../../sw/kernel/ai/matmul.cpp)
  as `matmul.vxbin` (`0x180400000`).
- **Additive Python/PyTorch v2 resident bridge:**
  [`python/vortex_ai/resident_v2.py`](../../python/vortex_ai/resident_v2.py)
  provides `ResidentContext`, `ResidentTensor`, and `ResidentGraph` on top of
  the strict single-context serial ownership model (`python_binding_v1.md`),
  eliminating redundant intermediate host↔device transfers between graph
  operators while explicitly rejecting concurrent context creation, use-after-close,
  and `requires_grad` / forward-AD autograd inputs.
