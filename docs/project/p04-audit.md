# P04 development-entry audit

Audited `master` revision:
[`4a5df5afef1826b70a2addee5029aae9dada2da1`](https://github.com/baabi-boo/AI-GPU/commit/4a5df5afef1826b70a2addee5029aae9dada2da1).
This records the source/history and existing hosted-CI findings used to choose
P04-T01. It is not a new GPU execution report or an acceptance decision. Live
phase state and accepted evidence remain in [roadmap.json](roadmap.json).

## 1. The next development step

At the audited revision, P03 is complete for six ordinary native matmul
signatures: FP16 or BF16 inputs, FP32 accumulation/output, and `(M,N,K)` equal
to `(8,4,8)`, `(8,4,16)` or `(16,8,16)`. A is compact row-major, B compact
column-major and D compact row-major, with initial C = +0. The
[operator manifest](../../ci/project/p03_operator_manifest.json) and
[P03 handoff](p03-operators-handoff.md) define that accepted boundary.

The managed wrapper and matching kernel have retained numerical and lifecycle
evidence. Native activation, layout/cast, normalization, softmax and attention
remain unavailable in this operator library. Its FP32 matmul outputs cannot
directly become FP16/BF16 inputs to another accepted matmul. Source presence in
inherited examples does not expand the accepted reusable API.

The roadmap therefore identifies **P04-T01: freeze the model, deterministic
reference and placement contract**. The selected model is a synthetic,
bias-free `16 → 8 → 4` ReLU MLP evaluated on 16 samples:

| Step | Planned placement | Supported shape or explicit host work |
|---|---|---|
| Hidden projection | Native matmul | `(16,8,16)` |
| Hidden activation/conversion | Host | ReLU and exact FP32-to-FP16/BF16 conversion of 128 actual output elements |
| Output projection, rows 0–7 | Native matmul | `(8,4,8)` |
| Output projection, rows 8–15 | Native matmul | `(8,4,8)` |
| Output assembly | Host | Copy the two actual row blocks into their fixed positions |

The [software contract](software.md#3-operator-and-runtime-contracts) expressly
permits predetermined host work when it is manifest-listed, dispatch-visible
and accounted separately. This is a hybrid placement contract. It does not
qualify native activation/cast, permit CPU matmul after a native failure, or
describe a wholly native network. Expected hidden values are comparison data;
a later executor must feed actual first-layer results through the host bridge.

Inputs and weights are integers in `[-2,2]`. First-layer partial sums are
bounded by ±64, activated values by `[0,64]`, and final partial sums by ±1,024.
The bounded values permit independent integer reference calculation and exact
word comparisons under the accepted P02 arithmetic contract. Five input
families in each format exercise signs, zero, basis features, nonlinearity and
the output-row split. The [fixture specification](../designs/tiny_mlp_fixture_v1.md)
defines the generator, original Apache-2.0 data, identities and rejection rules.

P04-T01 can support **P04-A01 at `source_present` scope only after qualification
and independent review**. P04-A02/A03 still require composed native execution,
intermediate/final comparisons, dispatch evidence, transfers and separate host
accounting. The next bounded implementation after the fixture is **P04-T02**,
using the accepted managed runtime's ownership, timeout and cleanup rules.

## 2. Existing CI failure is a separate unresolved issue

The audited revision's [CI run 44271136872](https://github.com/baabi-boo/AI-GPU/actions/runs/44271136872)
has 127 jobs: 125 passed, the
[`logic_gate` job](https://github.com/baabi-boo/AI-GPU/actions/runs/44271136872/job/134700081401)
failed, and the final aggregate gate failed. The tensor DUT reports DSP usage
**267 → 283 (+6.0%)**, exceeding the unchanged 5% threshold. This is an area
gate failure, not evidence that the P03 numerical tests failed.

The same DSP result appears in two earlier full runs:

| Source | Existing run and failing job | Recorded result |
|---|---|---|
| `fd803750198eb9f6ec11071abfdad211d8858100` | [43831931973 / 133185321661](https://github.com/baabi-boo/AI-GPU/actions/runs/43831931973/job/133185321661) | 267 → 283 DSP, 2026-11-16 |
| `9006939aa123452b198bc0987e34aae8fab45fdd` | [44006819632 / 133788898496](https://github.com/baabi-boo/AI-GPU/actions/runs/44006819632/job/133788898496) | 267 → 283 DSP, 2026-11-17 |

The successful predecessor [run 44258576211](https://github.com/baabi-boo/AI-GPU/actions/runs/44258576211)
at `20e026f` had 42 jobs and did not run `logic_gate`. Its green result does not
establish that the area regression was repaired. Repeated identical failures
provide no basis for dismissing this as transient tool noise.

An independent local comparison of `20e026f..4a5df5a` found no changes under
`hw/`, or in the configuration, toolchain pin, Beacon/gate code, logic-gate
catalog and Beacon baselines. Both commits have the same `hw` tree:
`426cd3e3ddbd304d20b882fb8e54488df61b37aa`. The failure predates P03's managed
matmul work; no hardware regression is attributed to that work by this audit.

The strongest static candidate is
[`1a898f7fb292e2b554ddd5c2065710a6cb5faba5`](https://github.com/baabi-boo/AI-GPU/commit/1a898f7fb292e2b554ddd5c2065710a6cb5faba5),
which correctly widened the MX scale index for WGMMA after the tensor baseline
was recorded. That also widens the dynamic `mn_idx * scale_blocks_k` expression
in `VX_tcu_core.sv`. Additional DSP inference is plausible, but **the causal
attribution is not a measured bisect and no correction has been qualified**.

A separate correction must retain the wider index, establish parent/candidate
Beacon measurements and per-unit attribution, prove any addressing rewrite
equivalent, and run the existing MX WGMMA NRC=16 RTL case with applicable
SimX/RTL parity. Narrowing the index would reintroduce a known correctness bug.
The fixture work does not change this datapath, its golden baseline or its gate
tolerance. A later reduced green run must not be reported as resolving it.

## 3. Resource and hardware boundaries

The initial workspace inventory showed approximately 57 GiB free disk and no
prepared native GPU toolchain. T01 is bounded to source/reference and host C++
qualification: no GPU toolchain downloads, a 15 GiB free-disk reserve and a
3 GiB process-group RSS budget for the formal host checks. These are execution
budgets, not measurements of accelerator memory or performance.

P01-A01/A02 remain accepted, while P01-A03 remains blocked on qualified vendor
XRT `hw_emu` tools and platform. That integration proof is still required before
P07 can close; processor-only native RTL does not replace the full AFU/vendor
obligation. Physical FPGA, usable board memory, measured throughput and custom
silicon remain unqualified. Neither the accepted matmul scope nor this tiny
synthetic fixture establishes modern NVIDIA-equivalent performance, CUDA
compatibility, a trained useful model or a production hardware product.
