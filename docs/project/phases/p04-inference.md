# P04 — Tiny-model inference

**Accountable role:** Model runtime lead. The primary coding agent (`/root`)
owns this executor implementation and qualification continuation. The
[executor packet](../evidence/p04-executor/README.md) records the native-run budget.
Live status, dependencies and exit criteria are in [roadmap.json](../roadmap.json).
The linked acceptance records define the demonstrated model and configuration;
the ordered work packages below remain the reproduction contract.

## Accepted scope: fixed model on SimX and native processor RTL

P04 is `complete`. **P04-T01 is complete and P04-A01 is
[accepted at `source_present` scope](../evidence/p04-fixture/acceptance.json).**
The [fixed tiny MLP contract](../../designs/tiny_mlp_fixture_v1.md),
[model manifest](../../../ci/project/p04_model_manifest.json), independent
[fixture producer](../../../ci/project/p04_reference.py), checked host bridge
and source regression tests are retained in the
[qualification packet](../evidence/p04-fixture/README.md). All five formal
commands passed at clean source `10ace66193686e3862c3c218760b66c044f1d4ae`,
tree `775aa7d5f96cfc5f7346e591ca151f36c485d2cf`; the complete source suite passed
1,733 tests in 752.879 seconds, including 64 P04 tests, without failures, errors
or skips. The source remained unchanged throughout qualification.

Those historical results cover the fixture, independent reference and compiled
host helper. The subsequent P04-T02 implementation supplies the managed executor,
native application, strict records, trusted runner and CI/catalog integration.
Its [execution packet](../evidence/p04-executor/README.md) retains fresh
qualification at `c9d139cc9f84839b6a56b6228dd304460cbfe45c`, original artifacts,
source/build identities and independent numerical, dispatch and provenance
reviews. [P04-A02](../evidence/p04-executor/acceptance-numerics.json) and
[P04-A03](../evidence/p04-executor/acceptance-dispatch.json) are accepted at
`rtl_verified` evidence level, explicitly limited to the native processor
datapath. The complete host suite passed 1,816 tests in 366.568 seconds.

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
fallback. Full qualification passed four variants: SimX/native processor RTL ×
FP16/BF16, with two distinct output poisons per case. The resulting 20 case/backend
pairs, 40 model runs and 120 native launches are actual fresh results, with
600 event/profile pairs. Exact comparisons cover 5,120 hidden, 2,560 packed
bridge, 2,560 output-block and 2,560 assembled-output words. Explicit tensor
traffic is 76,800 H2D and 30,720 D2H bytes; host row assembly copies 10,240 bytes.
Argument/control, module and setup traffic remain outside those totals.

**P04-T02 is complete. P05-T01 continues as the parallel framework track**, using
the [Python binding handoff](../p05-entry-handoff.md). Current measured-optimization
work follows the [P06 qualification handoff](../p06-qualification-handoff.md). The
[executor plan](../p04-executor-plan.md) retains actual-output lineage,
completion/ownership rules, resource limits and trace obligations for reproduction.

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
source/negative tests complete P04-T01 under the accepted P04-A01 source contract.
P04-T02 supplies the native executor, host integration tests, record validation,
catalog registration and hosted qualification path. Its compatible clean-source
native execution/trace evidence and independent review are retained in the
accepted executor packet; earlier failed preparation and incomplete uploads are
preserved separately and are not included in the accepted run totals.

| Gate | Required proof | Minimum evidence level |
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

The exact fixture, operator contract and accepted native results now supply
the [P05 handoff](../p05-entry-handoff.md) for Python integration and
[P06](p06-performance.md) for a separately frozen performance workload/counter
policy. P05 and P06 are `in_progress`; [roadmap.json](../roadmap.json) records
their live state and accepted evidence. Neither the simulator model nor this
document closes the later
physical FPGA gate. Vendor XRT `hw_emu` remains the blocked P01-A03 obligation;
full P01 completion is still required before P07 can close. The inherited
267 → 283 DSP area-gate failure also remains unresolved. Host steady-clock
profiles establish runtime observations, not physical GPU latency or throughput.
