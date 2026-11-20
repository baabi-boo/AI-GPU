# P04-T02 — Native tiny-model executor plan

This is future implementation and qualification work. No model executor or
device execution result is supplied by this plan. The
[fixture contract](../designs/tiny_mlp_fixture_v1.md) defines the source workload;
[roadmap.json](roadmap.json) and accepted evidence determine phase state.
The accountable role is model runtime lead; assign the actual execution owner
and resource budget before beginning the run.

## 1. Freeze inputs and execution identity

Validate the model manifest and fixture with the reviewed checkout's
[contract checker](../../ci/project/p04_model_contract.py). Preserve their hashes
and the exact clean source revision. Use all ten frozen cases, covering five
families in FP16 and BF16; define backend, repetitions, resource bounds and
failure rules before evaluation. Source-reference tests perform no dispatch.

Reuse the [managed operator API](../../sw/runtime/ai/runtime.h) and accepted
[P03 execution requirements](p03-operators-handoff.md). A trusted runner must
separately validate runtime, backend, kernel and host compiler records, current
generated configuration, dependency identities and actual binary hashes before
supplying `ExecutionBinding`. Match the ordinary `p02-tfr` RV64 profile,
selected input dtype, FP32 output and K-unroll setting on both application and
backend. A plausible qualification ID or capability bit is not provenance proof.

Use separate generated build trees for incompatible variants. Start with one
bounded SimX case, then execute the frozen inventory and declared native
processor-RTL coverage; retain each backend's result separately. Do not promote
processor RTL to full-AFU, vendor-emulation or physical-board evidence.

## 2. Compose three managed matmuls per case

Create the matching managed owner and capture initial resource counters. The
fixed graph requires the following calls; all blocks are `(4,1,1)` and every
runtime request has `batch_count=1`.

| Operation | `(M,N,K)` / grid | Actual input and output boundary |
|---|---|---|
| `hidden_matmul` | `(16,8,16)` / `(2,2,1)` | X and column-major W1 → 128 H FP32 words |
| `output_rows_0_7` | `(8,4,8)` / `(1,1,1)` | Bridge bytes `[0,128)` and W2 → 32 Y words |
| `output_rows_8_15` | `(8,4,8)` / `(1,1,1)` | Bridge bytes `[128,256)` and W2 → 32 Y words |

For each submission, retain any returned operation even when submission reports
an error. Wait for completion and require **`result.ok() && result.complete`**;
`ok()` alone does not check completion. Copy operation-owned outputs and traces
while their owner is alive. Preserve primary, validation and cleanup statuses
separately and stop dependent work on any failed or incomplete operation.

After the hidden call, compare all actual H words with the frozen preactivation
before ReLU. Pass those actual words to
[`prepare_mlp_hidden`](../../sw/runtime/ai/mlp_host.h), require bridge success,
and compare its actual bytes with the bridge reference. Expected H and bridge
arrays are comparison inputs only; they must never feed subsequent native work.

Sequential output calls are sufficient. Compare each actual output block with
its own row range, then use `copy_row_blocks` to assemble logits at byte offsets
0 and 128. Compare all 64 assembled FP32 words exactly. Native failure never
selects a CPU matmul implementation. The host bridge and copies have fixed,
manifest-declared placement; they are not native activation/cast support.

## 3. Retain ownership through failures

Close and drain operations explicitly and inspect cleanup results before
release. A bounded wait or close timeout retains its operation for another
drain attempt. Its destructor waits indefinitely and is not bounded cancellation.
The managed owner may also remain incomplete while operations retain its shared
context. Close the owner only after operation ownership has been resolved and
check completion as well as errors. Record resource restoration after release.

Exercise partial submission, failed dependency, timeout retention and late-stage
failure paths. A failed case keeps its raw outcomes; retrying must not overwrite
the failed evidence or reuse stale outputs as a successful result.

## 4. Add model-level execution records

Existing `MatmulTrace` covers a single call; it does not supply model operation
IDs, graph dependencies or elapsed timings. Add executor-level records binding
case, format, backend, fixture/source identity, operation ID, row slice,
dependency order and actual bridge lineage to each native trace. Preserve the
qualification binding, shape, dtype, poison, A/B/D addresses and extents,
56-byte arguments, enqueue counts, waits/timeouts, event results and statuses.

Record the host bridge and row copies explicitly. Measure host orchestration,
bridge, reference comparisons, transfers and native work separately, stating the
clock/method and any overlap. Simulator cycles or wall time are not physical GPU
latency. Never synthesize dispatch evidence from the reference or static graph.

Per case, the current three submissions plan nine tensor-buffer writes, three
launches and three reads: **1,920 H2D bytes including output poison, and 768 D2H
bytes**. Report these as explicit tensor-buffer traffic. Exclude and separately
identify per-launch argument/control, module and setup traffic; the tensor
totals are not physical DMA transaction counts or bandwidth measurements.

## 5. Qualify and hand off

Register the executor in the native test catalog with deterministic numerical,
placement and failure checks. Retain raw intermediates/final outputs, actual
dispatch and host records, source/tool/configuration identities, bounded command
receipts and artifact hashes. Have independent review reconcile graph coverage,
all comparisons, trace lineage, resource ownership and failed attempts.

P04-A02 requires actual composed execution matching the frozen references;
P04-A03 requires actual native placement and separate host/transfer accounting.
Only their compatible passing evidence can close those gates under the
[acceptance policy](acceptance.md). This plan grants neither acceptance nor a
P04 completion claim, and leaves P01-A03 and later physical-hardware obligations
unchanged.
