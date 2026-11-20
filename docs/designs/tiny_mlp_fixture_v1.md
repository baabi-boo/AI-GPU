# Fixed tiny MLP fixture v1

This contract freezes the P04-T01 model, independent reference and host bridge.
It supports source-level review of P04-A01. It does not establish model execution,
P04-A02/P04-A03 acceptance or physical accelerator performance. Actual acceptance
and phase state belong to the [roadmap](../project/roadmap.json) and its evidence.

## 1. Model and placement

Model `p04-tiny-mlp-v1` is a synthetic, bias-free network with 16 input features,
eight ReLU hidden units and four output scores, evaluated on a fixed batch of
16 samples. Its equations are `H = X W1`, `R = max(H, 0)`, `Y = R W2`.
There are 160 weights: W1 has shape 16×8 and W2 has shape 8×4. The model has no
biases, softmax, tokenizer, sequence state or trained-model accuracy claim.

Placement is fixed in advance. The [software contract](../project/software.md)
permits explicitly declared host work; only the three matmuls below are
accelerated operations. Host ReLU/conversion does not extend P03's native
activation or layout/cast support. The graph cannot select CPU matmul after a
native failure, and it must not substitute frozen references for actual outputs.

| Operation | Inputs and result | Placement and accepted signature `(M,N,K)` |
|---|---|---|
| `hidden_matmul` | X[16,16] × W1[16,8] → H[16,8] | Native matmul `(16,8,16)` |
| `hidden_relu_cast` | Actual H[16,8] → R[16,8] | Host ReLU and exact conversion to the selected input format |
| `output_rows_0_7` | Actual R rows [0,8) × W2[8,4] → Y rows [0,8) | Native matmul `(8,4,8)` |
| `output_rows_8_15` | Actual R rows [8,16) × W2[8,4] → Y rows [8,16) | Native matmul `(8,4,8)` |
| `assemble_logits` | Copy the two actual output row blocks into Y[16,4] | Host byte copies preserving row order |

Each case selects either FP16 or BF16 for all matmul inputs; accumulation and
matmul output are FP32, starting from exact positive zero. Each native operation
uses the matching accepted [P03 operator contract](ai_operator_contract_v1.md)
and [P02 profile](../../profiles/p02-tfr.json). No signature expansion, implicit
padding, transpose, arbitrary stride or native FP32-input matmul is introduced.
The split is two explicit M=8 calls, not a new `(16,4,8)` signature.

## 2. Original deterministic data

Fixture `p04-tiny-mlp-fixture-v1`, generator version 1, contains original
synthetic weights and inputs distributed under the repository's
[Apache-2.0 license](../../LICENSE). It downloads no dataset, pretrained weights
or tokenizer. The data define correctness targets for later execution of the
fixed network; they do not establish an execution result, statistical quality,
learned behavior or useful accuracy.

The [producer](../../ci/project/p04_reference.py) uses independent integer
arithmetic and the exact encodings in
[`p02_layout_fixture_oracle.py`](../../ci/project/p02_layout_fixture_oracle.py).
It does not call the production simulator or tensor arithmetic implementation.

The unsigned 32-bit generator starts each stream from its specified seed. For
each emitted value, update state `s` with these steps, where `mask = 0xffffffff`:

```text
s = (s ^ ((s << 13) & mask)) & mask
s = (s ^ (s >> 17)) & mask
s = (s ^ ((s << 5) & mask)) & mask
value = (s % 5) - 2
```

The first value follows one complete update; the seed itself is not emitted.
Generate logical matrices in row-major order. FP16 and BF16 share the same
logical integers and differ only in their encoded representations.

| Stream | Seed | Values and logical shape |
|---|---|---|
| W1 | `0x50403401` | 128 values, 16×8 |
| W2 | `0x50403402` | 32 values, 8×4 |
| Dense X | `0x50403410` | 256 values, 16×16 |

There are five input families in each format, in the following order. Cases
are format-major: all FP16 cases, then all BF16 cases. Their IDs are
`<format>-<family>`. The inventory is ten cases with 30 planned native launches;
these counts describe the workload, not observed execution.

| Family | X[row,column], with zero-based indices |
|---|---|
| `seeded_dense` | The frozen dense generator stream |
| `negated_dense` | Exact elementwise negation of `seeded_dense` |
| `zero` | Canonical positive zero in every element |
| `signed_basis` | Only column=row is nonzero: +2 for even rows, −2 for odd rows |
| `split_boundary` | `((3*row + 2*column + 3*(row//8)) % 5) - 2` |

The producer checks that dense preactivations contain both signs, outputs are
nonconstant, and removing ReLU changes an output. It also checks nonlinearity
through a nonzero element of `f(X) + f(-X)` and distinguishes the two output
row blocks in `split_boundary`. These are fixture coverage properties, not
model-quality metrics.

## 3. Numerical contract and exact comparisons

Every input and weight is an integer in [-2,2]. A first-layer product has
magnitude at most four; any prefix of its 16-product sum has magnitude at most
64. ReLU therefore produces integers in [0,64], exactly representable in both
FP16 and BF16. A second-layer product has magnitude at most 128; any prefix of
its eight-product sum has magnitude at most 1,024.

These bounds keep all products and partial sums exact under the accepted
[P02 ordered four-product TFR contract](tensor_numerics_v1.md). The bounded
integers have no discarded fractional tail in its alignment window and fit
FP32 exactly. The reference computes direct integer sums and encodes their
results; independent P02 quartet checks can verify the arithmetic derivation.
This proof applies to this domain, not arbitrary floating-point inputs or a
different reduction contract.

Comparison is raw-word equality at each boundary, with no absolute, relative
or ULP allowance:

1. Compare all 128 actual H FP32 words before ReLU. Cancellation and zero
   results in the reference are exact positive zero.
2. Compare all 128 actual R input-format elements, represented by 64 packed
   words, after the host bridge.
3. Compare each actual 32-word second-layer output with its corresponding
   row range, then compare all 64 assembled Y FP32 words.

A negative numerical error must not disappear under ReLU. An execution result
containing a different negative H value fails the first comparison even if its
activated value remains zero. No failed comparison permits regenerated expected
data, a widened tolerance or continuation described as successful inference.

## 4. Representation and identities

X, H, R and Y are compact row-major arrays. W1 and W2 are compact column-major
arrays in device-input storage, after row-major generation of their logical
values. A word is exactly eight lowercase hexadecimal digits without `0x`.
Packed FP16/BF16 words place the earlier memory element in their low 16 bits.
Each word is serialized little endian for byte hashes and transfer inputs.

| Tensor | Elements | Bytes | Stored 32-bit words | Byte strides |
|---|---:|---:|---:|---|
| X[16,16] | 256 input-format | 512 | 128 | (32,2) |
| W1[16,8] | 128 input-format | 256 | 64 | (2,32) |
| H[16,8] | 128 FP32 | 512 | 128 | (32,4) |
| R[16,8] | 128 input-format | 256 | 64 | (16,2) |
| W2[8,4] | 32 input-format | 64 | 16 | (2,16) |
| Y[16,4] | 64 FP32 | 256 | 64 | (16,4) |

The [fixture JSON](../../ci/project/fixtures/p04_tiny_mlp_v1.json) has exactly
these root fields: `schema_version`, `fixture_id`, `model_id`,
`generator_version`, `provenance`, `generator`, `model`, `weights`, `cases`.
Weights retain logical `w1`/`w2` matrices and per-format `w1_words`/`w2_words`.
Each case records `id`, `family`, `format`, `input_words`, `hidden_words`,
`bridge_words`, `output_words` and `sha256`. Tensor hashes cover raw little-endian
bytes; they do not hash the JSON text describing a word array.

The separate [model manifest](../../ci/project/p04_model_manifest.json) fixes
the graph, permitted placement, source dependencies and complete fixture-file
identity. The [contract checker](../../ci/project/p04_model_contract.py)
validates that boundary and deterministic reproduction. A changed tensor with
an updated adjacent hash still fails against the reviewed fixture contract.
An identity hash does not by itself prove correct arithmetic or license rights.

Verification rejects unknown/missing fields, duplicate keys, noncanonical
words, altered case inventories, incorrect types/shapes/layouts, unsupported
formats or signatures, changed placement, reference drift and identity drift.
Boolean values are not integer schema versions or dimensions. Nonfinite JSON
numbers and uncontrolled artifact paths are invalid. Verification is read-only;
deliberate regeneration is separate and its diff requires review.

For a copied checkout, `--root` requires its checker, reference producer and
P02 encoding-helper source bytes to match the invoking implementations. The
checker therefore cannot pin one producer while using another to reproduce the
fixture. To validate intentional source changes, review them and run that
checkout's own checker. This is a source-consistency check, not authentication
of arbitrary code or a guarantee against concurrent filesystem changes.

## 5. Checked host bridge

The internal [`mlp_host.h`](../../sw/runtime/ai/mlp_host.h) and
[`mlp_host.cpp`](../../sw/runtime/ai/mlp_host.cpp) define
`prepare_mlp_hidden(input, count, dtype)`. It consumes exactly 128 live, aligned
FP32 `uint32_t` words and returns a `BridgeResult` containing status and 256
bytes. It is host code with no device dispatch, runtime allocation or installed
API extension.

Before applying ReLU, every word must represent a finite, exactly integral
value in [-64,64]. This rejects fractions, subnormals, NaNs, infinities and
out-of-domain integers of either sign. Both signed zero words are accepted by
the helper and become positive zero; the separate raw H comparison still
rejects a negative zero where the frozen reference requires positive zero.

The helper uses integer bit operations to decode FP32 and encode exact FP16
or BF16. It preserves row order and writes each output element little endian.
Bytes [0,128) feed `output_rows_0_7`; bytes [128,256) feed
`output_rows_8_15`. It performs no rounding, saturation or generic format cast.

Null input or a count other than 128 returns `invalid_argument`; an unsupported
dtype returns `unsupported_dtype`; a malformed value returns `invalid_value`.
Every failure returns an all-zero byte array, with no partially encoded prefix.
Only `success` permits submission of the returned bytes. The input is unchanged;
callers remain responsible for its lifetime and valid pointer representation.

## 6. Later executor and evidence obligations

The native executor must validate the fixture before launch, retain successful
completion and actual output ownership, and pass actual H words to the bridge.
Frozen H/R/Y are comparator data only. Each native failure fails the case;
timeout or incomplete cleanup must retain resources under the existing
[managed runtime lifetime contract](../project/p03-operators-handoff.md).

For each case, execution evidence must bind the model/fixture identities,
format, backend, actual kernel/module and compiler/profile identities; retain
three distinct native dispatch records with exact shapes and row ranges;
record waits and dependency order; and report actual H, R, output blocks and Y.
Host bridge status, host placement and row assembly must be separately visible.

For the current managed wrapper's three independent submissions, the planned
explicit tensor-buffer transfers include output-poison writes and results:

| Submission | A write | B write | D poison write | D read |
|---|---:|---:|---:|---:|
| Hidden matmul | 512 B | 256 B | 512 B | 512 B |
| Output rows 0–7 | 128 B | 64 B | 128 B | 128 B |
| Output rows 8–15 | 128 B | 64 B | 128 B | 128 B |
| Total per case | 768 B | 384 B | 768 B | 768 B |

That is 1,920 explicit tensor-buffer host-to-device bytes and 768
device-to-host bytes per case. These totals exclude per-launch argument and
control traffic as well as module/setup traffic. Host bridge processing and
the 256-byte output assembly are host work. These counts are planned API-level
bytes, not physical DMA transactions, measured bandwidth or observed execution.

Report host orchestration, bridge, reference checking, transfers and native
execution separately, with the measurement method and overlap explicit.
Simulator cycles and wall time are not physical GPU latency. Successful fixture
or host-helper tests do not supply dispatch proof. P04-A02/A03 require the
separate source-bound execution and trace evidence described by the
[P04 plan](../project/phases/p04-inference.md); this document grants neither.
The [P04-T02 executor plan](../project/p04-executor-plan.md) records the next
implementation and qualification sequence.
