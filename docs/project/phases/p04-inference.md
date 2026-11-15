# P04 — Tiny-model inference

**Accountable role:** Model runtime lead. Assign an actual owner before work.
Live status, dependencies and exit criteria are in [roadmap.json](../roadmap.json).
This is a development plan, not evidence that model inference already works.

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

Deliver a model/fixture manifest, native executor, independent reference,
deterministic integration and negative tests, catalog registration, and a
reproduction/evidence bundle. These are future deliverables, not setup artifacts.

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
physical FPGA gate.
