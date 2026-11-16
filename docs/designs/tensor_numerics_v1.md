# Tensor numerical contract v1 — native TFR FP16/BF16 to FP32

**Contract:** `p02-tfr-fp16-bf16-v1`, version 1. **Work package:** P02-T01.
The companion machine manifest is
[`ci/project/p02_tensor_contract.json`](../../ci/project/p02_tensor_contract.json).
This specification defines a bounded FEDP arithmetic profile, the separate
four-thread WMMA application profile, and independent source layout fixtures;
it is not a declaration that P02, P02-A01, P02-A02 or P02-A03 has passed. Acceptance and
execution results belong to separately reviewed evidence under
[`docs/project/`](../project/phases/p02-tensor.md).

The implementation inspected for this contract is source revision
`49ec3060f4787c9b650acdc26f12dab6acfcbcb9`. Future evidence must identify its
actual tested revision, generated configuration, tools and fixture hashes.
The application profile and layout fixtures are source records. Independent
review and acceptance are recorded separately; hashes alone are not a result.
Historical P01 results retain their original revisions and tolerances.

## 1. Bounded profile and support matrix

### 1.1 FEDP leaf diagnostic profile

The profile `p02-tfr-rv64-n2-v1` is a **single dense FEDP unit operation** with
two packed 32-bit words in each input and one raw FP32 accumulator. It defines
both FP16 and BF16 source formats on the same four-product unit geometry.

| Property | Contract value |
|---|---|
| Architecture/configuration context | RV64, native TFR tensor arithmetic; unit harness `VX_CFG_NUM_THREADS=4` |
| A/B source formats | FP16 (`fmt_s=2`) or BF16 (`fmt_s=3`) |
| C/D format | FP32 (`fmt_d=0`); C bits preserved on entry |
| Packing | Two 16-bit elements per 32-bit word, low half first |
| FEDP width | `N=2` words, `TCK=2*N=4` products plus C |
| Raw significand width | `W=25`: sign plus 24-bit magnitude |
| Alignment width | 26-bit unsigned magnitude (`W+1`) |
| Accumulator width | `W+2+ceil(log2(TCK+1))=30` bits including sign |
| Internal exponent width | 10 bits |
| Rounding | Fixed round to nearest, ties to even (RNE) at the final window |
| Pipeline | `VX_CFG_TCU_LATENCY=4`, `USE_DSP=0`; four enabled pipeline advances |
| Features | Dense, unscaled; FP16/BF16 bank enabled by `VX_CFG_TCU_FP16_ENABLE` |
| Excluded feature paths | WGMMA, sparse metadata, block scales, DSM, FEDP2K |
| Memory/layout scope | Direct packed operands; no local-memory or matrix-loader qualification |

`enable=0` holds the unit pipeline. Pipeline latency is a unit configuration
property; it is not a whole-GPU instruction latency or a measured throughput.
All four product positions are part of the dense operation. Arbitrary external
lane masking is outside this profile; zero-valued inputs remain subject to
the exceptional-value rules in section 4.

Native TFR RTL and the production `TfrFedp` software model are separate
consumers of independent fixtures. A host invocation of that C++ model is
`tfr_model` evidence, not a full SimX processor run. DPI, DSP, BHF and FPNEW
arithmetic backends are outside this contract. The existence of additional
format implementations does not advertise their support under version 1.

### 1.2 Four-thread WMMA application profile

[`profiles/p02-tfr.json`](../../profiles/p02-tfr.json) freezes the separate
application configuration `p02-tfr-rv64-t4-wmma-v1`. Here `t4` means four
threads per warp. The profile applies to the existing dense
[`sgemm_tcu`](../../tests/regression/sgemm_tcu/kernel.cpp) WMMA path. Its source
presence and the layout fixtures below do not establish a full SimX or native
processor-RTL application result.

| Property | Frozen application value |
|---|---|
| Architecture and scheduling | RV64; one cluster, one core, four warps, four threads per warp, issue width one |
| Arithmetic | Native TFR tensor arithmetic, STD scalar FPU; FP16 or BF16 inputs, FP32 C/D; TFR latency four, `USE_DSP=0` |
| WMMA context | Dense `wmma_context<4, It, fp32, false, 8, 0, false>`; no explicit K-dimension override |
| Micro-tile geometry | `tcM x tcN x tcK = 2 x 2 x 2` in packed 32-bit words; four products per FEDP |
| WMMA tile | `tileM x tileN x tileK = 8 x 4 x 8` in matrix elements for either input format |
| Fragment registers per lane | `NRA=8`, `NRB=4`, `NRC=8`; input ratio two 16-bit elements per word |
| Reduction geometry | `m_steps=4`, `n_steps=2`, `k_steps=2`; each output has two four-product FEDP reductions per WMMA K tile |
| Memory | Local memory enabled; ordinary scalar fragment loads/stores, `VX_CFG_EXT_LDST_MATRIX_ENABLE` disabled |
| Disabled tensor features | WGMMA, DSM, sparsity, FEDP2K, block scaling and all tensor format banks other than FP16/BF16 |
| Application specialization | `ITYPE=fp16` or `bf16`, `OTYPE=fp32`, `KUNROLL=1`; initial accumulator zero |
| Application shape | Positive `M,N,K`; `M % 8 = 0`, `N % 4 = 0`, `K % 8 = 0`; complete tiles only |
| Application storage | Compact row-major A with `lda=K`, compact column-major B with `ldb=K`, row-major output with `ldc=N` |

The profile bytes and each format's flags jointly identify a configuration.
The manifest records one `configuration_id` per format and repeats that same
identity for the application and backend. Both must consume the same resolved
profile plus `-DITYPE=<format> -DOTYPE=fp32 -DKUNROLL=1`; no application/backend
substitution or ambient feature override belongs to this profile. Retain the
actual compiler records and generated configuration with future execution
evidence. A profile identity is a source contract, not proof that a build used it.

| Input | Shared application/backend configuration ID |
|---|---|
| FP16 | `p02-tfr-rv64-t4-wmma-v1/fp16-fp32-kunroll1` |
| BF16 | `p02-tfr-rv64-t4-wmma-v1/bf16-fp32-kunroll1` |

Boolean disables must use the profile's false values and the resolver's
`VX_CFG_*_DISABLE` output; defining an `*_ENABLE` macro to zero does not disable
an `ifdef`-selected path. `VX_CFG_TCU_FEDP2K` is a non-`_ENABLE` exception:
the profile schema cannot explicitly pin it false. This contract requires the
checked false default in `VX_config.toml`, no FEDP2K override, and absence of
its generated macro; defining it to zero would enable `ifdef` paths. Other
source defaults remain revision-bound and must be retained in the generated
configuration. Enabling local memory supplies no
claim about WGMMA descriptors or shared-memory matrix execution.

### 1.3 Preserved P01 application configurations

The accepted application profiles in
[`p01_baseline.json`](../../ci/project/p01_baseline.json) remain separate from
the four-product fixture profile. Both GEMMs use RV64, one cluster, one core,
four warps, TFR tensor arithmetic, STD scalar arithmetic, seed 50 and
`M=N=K=64`, with explicit SimX and processor-RTL cases.

| P01 input | Threads/warp | Issue width | `tcM x tcN x tcK` in words | Dense products/FEDP | Default WMMA tile in elements |
|---|---:|---:|---|---:|---|
| FP16 | 8 | 2 | `4 x 2 x 2` | 4 | `8 x 8 x 16` |
| BF16 | 16 | 1 | `4 x 4 x 4` | 8 | `16 x 8 x 16` |

These derived geometries use eight registers per accumulator fragment and the
ordinary dense path in `sgemm_tcu`. The BF16 P01 application has `N=4` and a
31-bit internal accumulator; its geometry must not be relabelled as this
`N=2` unit test. This version's BF16 four-product fixtures establish a distinct
bounded configuration. Full application qualification must identify each
actual reduction width and generated configuration.

## 2. Operand representation and packing

A and B are arrays of two unsigned 32-bit bit patterns. For lane `i` from 0
through 3, the 16-bit encoding is extracted from word `i//2` at bit offset
`16*(i%2)`. Lane `i` multiplies A lane `i` by B lane `i`. There is no cross-lane
multiply, transposition, byte swapping or conversion in this packing rule.
For example, `[a1:a0, a3:a2]` describes the two words with high half before low
half; the arithmetic sequence of product positions is 0, 1, 2, 3.

| Format | Sign | Exponent field | Fraction field | Bias |
|---|---:|---|---|---:|
| FP16 | bit 15 | bits 14:10 (5 bits) | bits 9:0 (10 bits) | 15 |
| BF16 | bit 15 | bits 14:7 (8 bits) | bits 6:0 (7 bits) | 127 |
| FP32 C/D | bit 31 | bits 30:23 (8 bits) | bits 22:0 (23 bits) | 127 |

Fixtures supply **raw input encodings**. There is no implicit FP32-to-FP16 or
FP32-to-BF16 quantization step. A caller that starts with another numeric type
must choose and perform that conversion before this operation; its conversion
rounding is a separate contract. In particular, C is never quantized to the
source format. Bit comparisons include C values that contain FP32 precision
not representable in A/B's format.

## 3. Exact finite algorithm for the fixed window

The reference calculation is an integer algorithm. It must not substitute
host floating-point addition, a sequence of scalar FP32 FMAs or a single
correctly rounded exact real dot product for the stages below.

### 3.1 Decode and multiply

For a finite source encoding with sign `s`, exponent field `e`, fraction `f`,
fraction width `p` and bias `b`, set `e'=max(e,1)` and
`M=f + (2^p if e!=0 else 0)`. Its exact value is
`(-1)^s * M * 2^(e'-b-p)`. This preserves input subnormals; the hidden bit is
absent when `e=0`. Do not normalize a subnormal before exponent selection.

For each nonzero product define:

```text
product_sign = sign_a XOR sign_b
U_product = e'_a + e'_b - 2*b
P_product = (M_a * M_b) << (24 - 2*p)
E_product = U_product + 260
```

FP16's exact 11-by-11-bit significand multiplication is widened with four
low zero bits in `P_product`. BF16's exact 8-by-8-bit multiplication is widened
with ten low zero bits. The RTL first embeds BF16 mantissas into the 11-bit
multiplier, appends two low bits to its product, and appends two more at
alignment; these shifts yield the same expression. Product multiplication
does not first round to FP32 or to the source format.

For finite nonzero C, use its FP32 fraction width 23 and bias 127:

```text
M_c = fraction_c + (2^23 if exponent_c!=0 else 0)
U_c = max(exponent_c, 1) - 127
P_c = M_c << 1
E_c = max(exponent_c, 1) + 133
```

A zero product and zero C have magnitude zero and RTL exponent zero; they
cannot raise the maximum exponent. Both signs of zero C become a zero raw
significand. If every term is zero, the result is positive zero after the
exceptional classification described below.

### 3.2 Alignment, accumulation quantum and sticky information

Let `L` be the maximum `E` over the four products and C. For a nonzero finite
operation, the common accumulation quantum is exactly

```text
q = 2^(L - 284) = 2^(max(U_product_0, ..., U_product_3, U_c) - 24)
```

The maximum uses the effective exponent fields above, including unnormalized
subnormals; it does not select by the true normalized magnitude of each term.
The RTL uses the lowest lane index on an exponent tie, which leaves `L`
unchanged. Zero terms have no effect on the finite quantum.

For each term form `delta=L-E` and `A=floor(P/2^delta)`. `P` fits in 26 bits.
At `delta>=26`, the aligned magnitude is zero. Each lane independently records
`lost=(P != A*2^delta)`, including a nonzero magnitude shifted completely out
of the window. Zero magnitudes record no loss. The signed contribution is
`-A` for a negative term and `A` otherwise: alignment truncates the magnitude
before applying the sign, so it truncates each signed term toward zero.

Add the five signed contributions exactly in a 30-bit signed accumulator to
obtain `S`; the profile's headroom prevents signed overflow at this stage.
The RTL compressor tree, one's-complement negation and negative-lane popcount
implement this same signed integer sum. They do not insert intermediate FP32
roundings. Combine all lane losses into a single Boolean
`sticky = OR(lost_0, ..., lost_4)`.

**The discarded tails are not retained as a signed residual sum.** Positive
and negative discarded parts cannot cancel in the global OR sticky bit. The
rounder receives the exact integer `S` and this Boolean only. In particular,
catastrophic cancellation can expose alignment loss, and sticky information
can influence a later rounding tie. There is no general guarantee that the
result equals correctly rounded exact `C + sum(A_i*B_i)` or falls within a
fixed ULP distance of it.

### 3.3 Normalize and round

When `S=0`, return `0x00000000`, even if discarded tails set sticky. Otherwise
the output sign is the sign of `S`. Count leading zeros `lz` in the 30-bit
unsigned magnitude `abs(S)` and shift it left by `lz`. The normalized leading
one is now in bit 29. The provisional biased FP32 exponent is
`L - 128 - lz`.

Keep bits 29:6 as the 24-bit significand, take bit 5 as guard, bit 4 as round,
and combine bits 3:0 with the global alignment sticky. Increment the retained
significand exactly when:

```text
guard && (round || sticky || least_significant_retained_bit)
```

A carry out renormalizes the significand and increments the exponent. This
is RNE applied to the retained window and its sticky information. RNE is
fixed for this native datapath; dynamic scalar `frm` settings and the C++
model's other constructor rounding modes are outside this contract.

Packing then applies section 4. In particular, the exponent check occurs
**after** rounding, so a value rounded up to the minimum normal is retained.
The FP32 accumulator input and output storage widths do not imply an exact
FP32 summation at every product or a full-precision real dot product.

## 4. Exceptional values, zeros and range

Classification takes precedence over the finite result. FP16/BF16 and FP32 C
use all-ones exponent with zero fraction for infinity and nonzero fraction
for NaN. The NaN quiet/signaling bit, payload and sign do not survive into D.

| Input/result condition | Required output bits/behavior |
|---|---|
| Any NaN input, including C | Canonical quiet NaN `0x7fc00000` |
| Infinity multiplied by either signed zero | Canonical quiet NaN `0x7fc00000` |
| Both positive and negative infinite terms, including C | Canonical quiet NaN `0x7fc00000` |
| Infinite terms of only one sign, with no NaN condition | Infinity with that sign (`0x7f800000` or `0xff800000`) |
| All finite signed zeros, or aligned integer sum exactly zero | Positive zero `0x00000000` |
| Nonzero finite sum with rounded biased exponent at least 255 | Infinity with the sign of the integer sum |
| Nonzero finite sum with rounded biased exponent at most zero | Signed zero with the sign of the integer sum (output FTZ) |
| Rounded biased exponent from 1 through 254 | Packed normal FP32 with RNE significand |

Input subnormals in A, B and C enter the finite algorithm; they are not
unconditionally flushed on input. They may disappear through finite-window
alignment or final output FTZ. Output subnormal encodings are never produced.
Negative finite underflow produces `0x80000000`; this differs from exact
cancellation and from an operation containing only negative zeros, both of
which produce positive zero.

Exceptional classification includes `NaN*0` and `Inf*0` even when a zero
operand would suppress a product's ordinary magnitude. A zero-product mask
must not turn either operation into an ordinary zero.

This contract specifies returned bits. The FEDP interface has no architectural
exception-flag output, and this work makes no claim about `fflags`, traps,
signaling-NaN exceptions, underflow/inexact flags or scalar floating-point
environment side effects. It does not establish universal IEEE-754 or
vendor tensor-instruction equivalence.

## 5. Layouts and reduction boundaries

### 5.1 Leaf packing and application addresses

The leaf packing in section 2 distinguishes both halves of both words and
preserves nonzero C, so exchanging packed positions or dropping the last word
is visible. These leaf fixtures check FEDP operands. Their direct-input
harness does not execute matrix-load/store address logic.

The native fragment API in
[`vx_tensor.h`](../../sw/kernel/include/vx_tensor.h) exposes row-major and
column-major loads/stores. For the application in section 1.2, an element's
offset from its matrix base, in elements, is `A[m,k] = m*K+k`,
`B[k,n] = n*K+k` and `D[m,n] = m*N+n`. A/B elements occupy two bytes and D
elements four bytes. The kernel initializes its accumulator fragment to
positive zero; it does not load a matrix C or implement arbitrary alpha/beta.
Tile origins are `(8*blockIdx.y, 4*blockIdx.x)` in output coordinates; the K
loop visits `0,8,...,K-8` with `KUNROLL=1` and stores the completed tile once.
The compact application contract excludes padding, transposed application
operands, partial-tile masking and nonzero initial matrix C.

### 5.2 Independent source layout fixtures

[`p02_layout_fixture_oracle.py`](../../ci/project/p02_layout_fixture_oracle.py)
produces the separately versioned
[`p02_layout_v1.json`](../../ci/project/fixtures/p02_layout_v1.json) from explicit
integer matrix inputs, memory-address rules and matrix multiplication. The
producer is independent of
production `vx_tensor.h`, `tensor_cfg.h`, SimX and RTL execution; production
gather/scatter or arithmetic must not generate its expected mapping or bits.
The manifest binds the layout artifact, its producer and the application
profile to concrete SHA-256 identities. The exact fixture inventory and
supported storage variants are recorded in that artifact.

The fixture profile is the four-thread, `2 x 2 x 2`-word micro-tile and
`8 x 4 x 8`-element WMMA geometry above. Its **20 source-only cases**, ten for
each format, use compact A/B/D storage and zero initial C. Each case records
dimensions, leading dimensions, tile counts, four-product reduction count,
packed full-matrix A/B input words and row-major expected FP32 output words.
Each word is eight lowercase hexadecimal digits, with the lower-address
16-bit input in the low half under little-endian memory byte order.

| Family | Cases per format | Dimensions and boundary purpose |
|---|---:|---|
| K one-hot | 6 | `8 x 4 x 8` at K indices `0,3,4,7`; `16 x 8 x 16` at K indices `8,15` |
| Dense boundaries | 2 | One `8 x 4 x 8` tile and `16 x 8 x 16` across M, N and K tile boundaries |
| Cancellation | 2 | The same shapes; nonzero partial sums cross FEDP/K-tile boundaries before exact zero or a nonzero residual |

Inputs are small integers exactly representable in both source formats.
Every product and prefix sum has magnitude below 4096; for these cases all
terms fit the retained FEDP window exactly and every intermediate FP32 sum is
exact. Independent integer matrix multiplication therefore supplies expected
bits without pretending to model a general whole-GEMM single rounding.
Comparison is unsigned 32-bit equality, including positive-zero output bits.

These are complete matrix-memory fixtures, not direct lane/register mapping
vectors. The existing `sgemm_tcu` host generates its own inputs and has no
reader for this JSON; its fixture-input adapter remains pending. A deterministic
producer check verifies source data without exercising the compiled fragment
API, matrix instructions, memory system or GPU. Actual matrix-layout
qualification requires retained execution of fragment gather/scatter, leading
dimensions, tile boundaries and K traversal on the frozen application/backend
configuration. Padded strides, nonzero initial matrix C and tail handling are
outside this fixture and application profile.

### 5.3 Reduction order

A FEDP reduction rounds once after its fixed-width signed sum. A WMMA or
WGMMA operation can issue multiple such reductions, feeding each FP32 result
back as C. A complete GEMM repeats that process across K tiles. Consequently,
four-product unit rounding, instruction-level micro-operation rounding and
whole-GEMM rounding are distinct boundaries. Repartitioning or reordering K
terms can change results. Full GEMM reproduction must retain its actual
instruction/micro-operation order and geometry; the unit fixture is not an
oracle for a differently partitioned whole GEMM.

## 6. Unsupported combinations and response boundaries

Only the two source formats, FP32 destination and bounded TFR profile in
section 1 are advertised here. FP32/TF32 A/B, FP8/BF8, integer tensor inputs,
MX/NV block scaling, sparsity, alternate rounding modes, other backend types,
other accumulator widths and other FEDP widths are excluded from v1.
The retained P01 TF32 attention evidence remains valid at its original scope;
its existence does not add TF32 to this contract.

The fixture producer and strict harness must reject unknown format names,
unknown case IDs, malformed operands and configuration substitutions
explicitly rather than silently narrowing or falling back. This is a tooling
selection rule. The inspected native API at the source revision above checks
output compatibility but has no general enabled-format guard. The new
`detail::tfr_input_enabled` guard and static assertions at the TFR WMMA/WGMMA
API boundary reject disabled source formats at template instantiation. Their
presence is a source fact; the positive/negative compile matrix requires its
own retained execution evidence. These guards apply when TFR is selected.

**Raw instruction encodings bypass that front-end boundary.** This contract
does not promise an illegal-instruction trap, a runtime error or any numerical
value for an excluded raw encoding or disabled-format raw instruction. The
unit's `fmt_d` is not a destination-format rejection mechanism. Tooling or
compile-time API rejection is not evidence of raw decoder rejection. P02-A02
must retain the exact boundary of every unsupported-format failure it tests.

## 7. Independent fixtures, comparison and preserved tolerances

[`p02_fixture_oracle.py`](../../ci/project/p02_fixture_oracle.py) is the
version-1 deterministic producer for
[`p02_tfr_v1.json`](../../ci/project/fixtures/p02_tfr_v1.json) and
[`p02_tfr_vectors.h`](../../hw/unittest/common/p02_tfr_vectors.h).
The producer uses integer/rational calculations of this algorithm. It must
not call, import, compile or derive expected outputs by executing production
`TfrFedp`, SimX, RTL, DPI or another backend. Production arithmetic is a
consumer to be checked against the fixtures, not their producer.

Every fixture retains its ID, format, raw A/B/C, expected FP32 bits, category
and derivation. Finite cases can additionally retain an exact rational sum
and its correctly rounded FP32 result as a diagnostic; that mathematical
answer is not substituted for the fixed-window expected output.

**Comparison is unsigned 32-bit equality.** No absolute, relative or ULP
tolerance is permitted for these unit fixtures. Positive and negative zero
are distinct, and a different NaN payload fails even when both outputs are
NaNs. Expected outputs are versioned data and cannot be updated merely to
make a production mismatch pass. A semantic change requires a new reviewed
contract version and independently regenerated fixtures before evaluation.

The initial leaf fixture set had 96 cases, 48 for each source format. The
current corpus has **98 cases, 49 per format**: it preserves every original
case record and appends `fp16_zero_times_max_exponent` and
`bf16_zero_times_max_exponent`. These cases require a zero product with a
maximum encoded operand exponent not to displace the nonzero finite term's
alignment exponent. Any previously retained 96-case leaf diagnostic retains
its original scope and does not establish execution of the added pair.
Coverage includes ordinary products and C, packed positions, signed zeros,
input subnormals, output FTZ, rounding ties and carries, exponent gaps,
alignment losses, cancellation, finite extremes, overflow, NaN and infinity.
The machine manifest records the concrete fixture categories and counts.
The separately frozen layout corpus adds source expectations; matrix-layout
execution, long instruction chains and WGMMA concurrency remain separate
pending obligations. Neither fixture inventory establishes their completion.

FP16's four finite products cannot overflow finite FP32 C in this profile;
its extreme cases check that maximal finite C remains finite. BF16 cases
exercise actual positive and negative overflow. A shared `overflow` category
does not assert that every format reaches overflow from finite inputs.

The manifest records SHA-256 identities computed from the current 98-case
leaf JSON, generated header and producer, and independently from the layout
JSON, layout producer and application profile. Independent review of these
identities is recorded separately. Freeze these bytes in the manifest/evidence
**before acceptance evaluation**.
Regeneration must verify the bytes rather than adopting new expected outputs
from a test run. No placeholder digest constitutes a frozen fixture identity.

P01 reference tolerances are preserved without reinterpretation:

| Historical case family | Preserved reference/comparison |
|---|---|
| FP16/BF16 `sgemm_tcu`, both drivers | CPU double accumulation of converted products; `abs((actual-reference)/reference) < 0.01`, with exact zero pairs accepted |
| TF32 attention, both drivers | CPU double softmax reference using quantized inputs/intermediate P; `abs(actual-reference) <= 0.001 + 0.001*abs(reference)` |

These application rules do not relax the new bit-exact unit comparator, and
the unit comparator does not retroactively change the accepted P01 runs.
Preserve the P01 manifest and its evidence unchanged.

## 8. Reproduction and evidence levels

From the source root, check deterministic fixture bytes and focused tooling:

```sh
python3 ci/project/p02_fixture_oracle.py --check
python3 ci/project/p02_layout_fixture_oracle.py --check
python3 -m unittest discover -s ci/project -p 'test_p02_tensor_contract.py' -v
python3 ci/project/check_project.py
```

From a freshly configured **RV64 generated build directory**, the focused
unit harness provides native RTL and a separate production-model consumer:

```sh
make -C hw/unittest/tcu_contract THREADS=2
make -C hw/unittest/tcu_contract run OPTS='--format=all'
make -C hw/unittest/tcu_contract run OPTS='--format=all --stalls'
make -C hw/unittest/tcu_contract model
make -C hw/unittest/tcu_contract run-model OPTS='--format=all'
```

Use `--format=fp16` or `--format=bf16` and `--case=<fixture-id>` for a retained
single-case replay; `--stalls` belongs to the native consumer only. The native
scope is `backend=native_tfr` with `mode=unit_dense` or `mode=unit_stall`.
The host consumer is `backend=tfr_model`, `mode=model_dense`. Preserve the
actual build flags that enforce the fixed profile, every selected fixture,
raw mismatches and the exit status. Review source identities and generated
configuration again before reusing a build.

These are reproduction commands, not a record that the commands ran. The
producer check establishes deterministic source artifacts. Python/host checks
establish tooling/model behavior. A successful native unit run establishes
the tested unit arithmetic only. Full SimX application execution, processor
RTL, full-AFU `xrtsim`, vendor `hw_emu` and physical hardware are different
evidence levels. P01-A03 remains a separate vendor integration obligation.

P02-A01 requires reviewed source contracts and the finalized fixture manifest.
P02-A02 additionally requires its normal, edge, cancellation, layout and
explicit unsupported-format execution evidence. P02-A03 additionally requires
its WGMMA synchronization, metadata, multi-warp and backpressure evidence or
the phase's reviewed applicability limits. No unit pass closes those broader
obligations automatically.

## 9. Source map

| Contract mechanism | Primary source |
|---|---|
| Widths, stages and enable behavior | [`VX_tcu_fedp_tfr.sv`](../../hw/rtl/tcu/tfr/VX_tcu_fedp_tfr.sv) |
| FP16/BF16 decode and exact product | [`VX_tcu_tfr_mul_f16.sv`](../../hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f16.sv) |
| FP32 C decomposition | [`VX_tcu_tfr_mul_join.sv`](../../hw/rtl/tcu/tfr/VX_tcu_tfr_mul_join.sv) |
| Magnitude alignment and per-lane sticky | [`VX_tcu_tfr_align.sv`](../../hw/rtl/tcu/tfr/VX_tcu_tfr_align.sv) |
| Signed sum and global OR sticky | [`VX_tcu_tfr_acc.sv`](../../hw/rtl/tcu/tfr/VX_tcu_tfr_acc.sv) |
| Normalization, RNE, overflow and FTZ | [`VX_tcu_tfr_norm_round.sv`](../../hw/rtl/tcu/tfr/VX_tcu_tfr_norm_round.sv) |
| NaN/Inf reduction | [`VX_tcu_tfr_exc_reduce.sv`](../../hw/rtl/tcu/tfr/VX_tcu_tfr_exc_reduce.sv) |
| Production software arithmetic consumer | [`sw/common/fedp.h`](../../sw/common/fedp.h) |
| SimX integration of production arithmetic | [`tcu_unit.cpp`](../../sim/simx/tcu/tcu_unit.cpp) |
| Fragment geometry | [`tensor_cfg.h`](../../sw/common/tensor_cfg.h) |
| Frozen application settings | [`profiles/p02-tfr.json`](../../profiles/p02-tfr.json) |
| Fragment gather/scatter and register mapping | [`vx_tensor.h`](../../sw/kernel/include/vx_tensor.h) |
| GEMM layout, initial C and K traversal | [`sgemm_tcu/kernel.cpp`](../../tests/regression/sgemm_tcu/kernel.cpp) |
| Independent layout expectations | [`p02_layout_fixture_oracle.py`](../../ci/project/p02_layout_fixture_oracle.py) |
