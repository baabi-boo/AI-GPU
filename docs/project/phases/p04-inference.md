# P04 — Tiny-model inference

**Accountable role:** Model runtime lead. The primary coding agent (`/root`)
owns this fixture implementation and qualification continuation. Assign the
actual execution owner and resource budget before the native model run.
Live status, dependencies and exit criteria are in [roadmap.json](../roadmap.json).
This is a development plan, not evidence that model inference already works.

## Current work: fixture implemented, acceptance pending

P04 is `in_progress`. P04-T01's [fixed tiny MLP contract](../../designs/tiny_mlp_fixture_v1.md),
[model manifest](../../../ci/project/p04_model_manifest.json), independent
[fixture producer](../../../ci/project/p04_reference.py), checked host bridge
and source regression tests are implemented and under qualification. P04-A01
remains pending until exact-source validation and independent review are retained
and attached to the roadmap. This work targets `source_present` evidence only.
P04-A02 and P04-A03 remain unearned: no composed model executor, native model
launch or model-level dispatch/latency result is supplied by this continuation.

The selected model is a synthetic, bias-free 16→8→4 ReLU MLP with a fixed batch
of 16, 160 original deterministic weights and ten cases covering five input
families in both FP16 and BF16. It has no tokenizer, trained-model quality claim
or softmax. Every boundary uses exact raw-bit equality; its bounded integer
domain derives from the accepted P02 numerical contract.

The graph declares three native matmuls per case: `(16,8,16)` for the hidden
layer and two `(8,4,8)` calls for the output row blocks. ReLU, exact conversion
of actual FP32 hidden outputs to the selected input format, and output row
copies are explicit host work. This placement uses the existing P03 signatures;
it neither introduces native activation/cast support nor allows a CPU matmul
fallback. The 30 native launches across the ten cases are planned workload
counts, not executed results.

The immediate task is to qualify and review this source contract. After
P04-A01 acceptance, **P04-T02 — compose and qualify the native model executor**
is the next implementation step; the [executor plan](../p04-executor-plan.md)
defines actual-output lineage, completion/ownership rules and trace obligations.

## Goal and boundaries

Execute one fixed, redistributable tiny transformer or equivalently specified
network end-to-end through the accepted native operator library. A matrix-multiply
demo alone is not this milestone. Python and PyTorch integration come later.
Synthetic, deterministic weights may establish execution correctness; they do not
establish useful language-model quality or a trained-model accuracy claim.

Non-goals are arbitrary model loading, a replacement HIP compiler, training,
CUDA compatibility and physical throughput claims. See [software](../software.md).

## Entry conditions

- P03 is accepted, including operator correctness and runtime lifetime tests.
- The selected model fits the supported operator, shape, dtype and layout matrix.
- Its numerical policy derives from P02; model-level bounds are frozen before
  evaluation, with an independent CPU reference and deterministic inputs.
- The owner approves a bounded simulator resource budget and permitted host work.

## Ordered work packages

1. **Freeze the fixture.** Record architecture, dimensions, weights or generator,
   seeds, inputs, optional tokenizer, licenses and content hashes. Keep reproduction
   independent of large proprietary downloads and mutable remote model versions.
2. **Map execution.** Map every layer to supported native operators. Explicitly
   identify allowed host work, copies and synchronization; reject unsupported
   accelerated operations by default instead of silently executing them on a CPU.
3. **Compose the native executor.** Reuse the operator wrappers over
   [`vortex2.h`](../../../sw/runtime/include/vortex2.h). Handle buffer ownership,
   intermediate storage, queues/events, errors and repeat-run cleanup explicitly.
4. **Compare layer by layer.** Capture named intermediates and final outputs;
   compare with the frozen reference. For a decoder model, specify and test
   prefill/decode state and cache reuse rather than accepting one isolated layer.
5. **Record placement and cost.** Emit operator/kernel/backend dispatch records
   and transfer accounting. Separate host time, transfers and native execution;
   simulation cycles or simulator wall time are not measured physical GPU speed.

## Deliverables and acceptance

The model/fixture manifest, independent reference, checked host bridge and
source/negative tests are implemented for P04-T01, with acceptance pending.
P04-T02 must still deliver the native executor, model integration tests, catalog
registration and source-bound execution/trace evidence.

| Gate | Required proof | Evidence level |
|---|---|---|
| `P04-A01` | Fixed model, optional tokenizer, weights/generator, seeds, shapes, hashes and redistribution provenance | `source_present` |
| `P04-A02` | End-to-end native execution matches frozen layer and final-output references under predeclared tolerances | `simulated` |
| `P04-A03` | Dispatch traces prove declared accelerated operations used Vortex; transfers and permitted host work are separately reported | `simulated` |

Record the exact source/tool/configuration identities, backend, arithmetic path,
commands, exit results, raw outputs and artifact hashes under the
[acceptance policy](../acceptance.md). Existing tensor and attention tests are
building blocks, not a substitute for model-level evidence.

## Stop conditions and handoff

Block acceptance for unresolved fixture licensing, unsupported model signatures,
unexplained reference differences, hidden CPU execution, missing traces or resource
overruns. A test not run stays not run; do not relax tolerances to close the phase.

On acceptance, hand the exact fixture, operator contract and native results to
[P05](p05-framework.md) for Python integration and [P06](p06-performance.md) for
performance work. Neither a simulator model nor this document closes the later
physical FPGA gate. Vendor XRT `hw_emu` remains the blocked P01-A03 obligation;
full P01 completion is still required before P07 can close.
