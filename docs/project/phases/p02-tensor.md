# P02 — Tensor numerical contract

**Goal:** define and prove the arithmetic behavior of the first supported AI
configuration. This phase is `complete`. P02-T01 is complete with
[P02-A01 source-level evidence](../evidence/p02-numerics/acceptance.json).
[P02-A02 ordinary WMMA evidence](../evidence/p02-wmma/acceptance.json) is
accepted. The independently reviewed
[P02-A03 WGMMA evidence](../evidence/p02-wgmma/processor/acceptance.json)
completes P02-T02 and the phase's three acceptance gates.
The live status, dependencies and authoritative gate text are in
[roadmap.json](../roadmap.json); the accountable role is Compute architecture lead.

## Entry and boundaries

- P00 must be complete and P01-A01 (reproducible build) plus P01-A02 (native
  numerical baseline) must each have passing, reviewed evidence. The canonical
  [roadmap](../roadmap.json) records these as machine-checked
  `entry_acceptances`. P01's vendor integration gate P01-A03 is **not an entry
  prerequisite**; it remains blocked and must pass before P01/P07 closure.
- Use the [P02 numerical handoff](../p02-numerics-handoff.md) for the implemented
  contract, actual results and remaining work. The
  [staged-entry handoff](../p02-entry-handoff.md) preserves the entry decision.
- Start with the declared FP16/BF16 inputs and FP32 accumulation. Other formats,
  sparsity and block scaling require their own support decisions and evidence.
- Reuse the [tensor design](../../designs/tensor_core_wgmma_engine.md),
  [tensor RTL](../../../hw/rtl/tcu/), [SimX model](../../../sim/simx/tcu/) and
  [native tensor API](../../../sw/kernel/include/vx_tensor.h).
- This phase does not establish physical throughput, framework compatibility or
  universal IEEE behavior. A DPI C-arithmetic run is not native RTL proof.

## Ordered work packages

Items 1–3 are implemented in the [v1 numerical contract](../../designs/tensor_numerics_v1.md),
[manifest](../../../ci/project/p02_tensor_contract.json) and
[p02-tfr profile](../../../profiles/p02-tfr.json). The
[evidence packet](../evidence/p02-numerics/README.md) binds reviewed source to
98 native leaf cases, the same 98 stalled cases with 306 hold checks, 98 host
model-function cases, 47 compiler cases and 1,343 offline tests at the original
A01 checkpoint. The later [ordinary WMMA packet](../evidence/p02-wmma/README.md)
adds the application adapter and matched processor execution for the 20 unchanged
layout cases plus 68 independent numerical cases, satisfying A02's ordinary WMMA
scope. Item 5 now has accepted native-unit and processor evidence, described
below, with completed engineering and publication-integrity review.

1. Freeze one baseline configuration: XLEN, native arithmetic backend, enabled
   formats, tensor/WGMMA switches, warp geometry, local memory and tile layouts.
   Record generated configuration and identical application/backend settings.
2. Write a versioned numerical contract for each advertised combination. Specify
   input quantization, rounding, accumulation order/precision, signed zero,
   subnormals, NaN/Inf, overflow, underflow and unsupported-input behavior.
3. Select independent reference calculations and deterministic fixtures. Freeze
   absolute/relative or bit-exact comparison rules **before acceptance runs**;
   distinguish arithmetic requirements from an observed backend approximation.
4. Extend focused tests for ordinary values, extremes, cancellation, long sums,
   tile/layout boundaries and explicit rejection of unsupported combinations.
   Reuse the [tensor catalog](../../../ci/testcases/tensor.yaml).
5. Exercise WGMMA descriptor/layout rules, synchronization, multiple warps,
   metadata dependencies and backpressure using the
   [warpgroup catalog](../../../ci/testcases/tensor_wg.yaml). Include sparse or
   scaled cases only when that combination is explicitly advertised.
6. Compare SimX and native RTL; localize the first unexplained divergence.
   Keep timing-model changes paired with RTL changes and use applicable inherited
   parity/logic gates without widening their tolerances or editing golden data.

## Accepted ordinary WMMA scope

Clean source `58faf6d68879e1db92122df493172eab59c02458`, tree
`cd35869ee89cb42685e9bac367667a7dffbe1b1d`, passed all **176 case/backend
executions, 352 launches and 14,336 exact FP32 output-word checks**. There are
88 source cases, 44 per format, each run twice on both full SimX and native
processor `rtlsim`. Independent integer/rational expected words cover ordinary,
edge, cancellation, tile-layout and K-traversal cases. The separate actual
RISC-V API matrix met 47 expectations in 94 WMMA/WGMMA contexts: 17 successful
compilations and 30 intended rejections. These rejections prove the public C++
boundary; they do not establish traps for unsupported raw instructions.

The unchanged RV64 `p02-tfr` application profile limits this result to dense
ordinary WMMA with FP16/BF16 inputs, FP32 accumulation/output, initial C = +0,
K = 8 or 16, `KUNROLL=1` and the `8 x 4 x 8` tile. A is row-major, B is
column-major and C/D are row-major. Native RTL uses TFR tensor and STD scalar
floating-point arithmetic; integer DPI helpers remain. Processor `rtlsim`
bypasses the AFU, so this record adds no vendor `hw_emu`, physical-device,
WGMMA concurrency or timing-model parity qualification.

The [handoff](../p02-wmma-handoff.md) preserves the initial SimX selector failure
and the first full offline run's one source-contract failure in 1,448 tests.
The reporting-only child `c9cf9ba0730f236e110a1d48a54d8f47a9faf9af` has focused
source-contract and 15-test adapter passes on its exact patch; its full-suite
rerun passed all 1,448 tests, and the rebuilt hosts repeated all 352 launches
and 14,336 exact comparisons successfully; see [status](../status.md).
Those child checks preserve the formal processor result's original source identity.

## Accepted bounded WGMMA scope

The [WGMMA handoff](../p02-wgmma-handoff.md) and
[processor packet](../evidence/p02-wgmma/processor/README.md) retain the finished
formal run at clean source `4af2307e57202c1269e20f893267a5583ad3cba0`: 113
commands, 12 backend/configuration builds, 24 case executions, 48 launches and
24,576 exact output-word comparisons passed. Six configurations cover dense
FP16/BF16 SS/RS, FP16 SS row-major A and bounded sparse FP16 SS. The two sparse
RTL cases contain 64 completed metadata transactions, all with observed waits.
All 12 performance pairs preserve exact retired-instruction equality and the
unchanged 5% cycle bound; the largest difference is 1.356484%.

The [historical native unit](../evidence/p02-wgmma/unit/README.md) remains a
separate execution at `9006939aa123452b198bc0987e34aae8fab45fdd`: eight groups,
392 accepted/committed transactions and 3,072 exact arithmetic words. Its 417-file
RTL/harness bridge is unchanged at the processor source. Directed dense NRC16
RS pressure supplies the blocked compute-path observation; forced sparse-compute
pressure is unclaimed. Processor metadata ordering and unit pressure are
complementary evidence. Integer DPI helpers remain in the processor; full-AFU,
vendor `hw_emu`, physical FPGA, PPA and silicon qualification remain separate.

The corrected original-packet verifier checked 1,103 files with the independently
supplied report digest. Independent engineering and publication-integrity reviews
support [P02-A03 acceptance](../evidence/p02-wgmma/processor/acceptance.json),
record `p02-a03-wgmma-4af2307-359a8c0`. The original verifier's automatic
acceptance flags remain false; the reviewed acceptance record closes the gate.

## Deliverables and acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P02-A01` | Reviewed format/backend contracts, support matrix and deterministic fixture manifest, with comparison rules frozen before evaluation | `source_present` |
| `P02-A02` | Reference-comparison reports for native FP16/BF16-to-FP32 normal, edge, cancellation and layout tests; explicit unsupported-format failures | `rtl_verified` |
| `P02-A03` | WGMMA concurrency/metadata/backpressure reports and applicable model-parity evidence, or a justified applicability limit | `rtl_verified` |

For every run retain source/tool identities, configuration, arithmetic backend,
case/seed, exact command, reference version, tolerances, raw output and result.
Separate SimX, native processor RTL and full-shell XRT evidence. A justified
parity applicability limit does not waive numerical correctness or concurrency
tests. Follow the [verification](../verification.md) and
[acceptance](../acceptance.md) policies.

## Stop conditions and handoff

Stop acceptance for an undefined arithmetic rule, unexplained mismatch, missing
native test, stale configuration or unreviewed tolerance change. In particular,
resolve NVFP4 subnormal-scale semantics before advertising that mode; exclusion
must be explicit, not a hidden fallback. Do not convert a missing run to a pass.

P02-T02 is complete. The accepted record reconciles the finished processor packet,
historical native-unit source bridge, sparse witness, declared instruction/cycle
checks and independent engineering/publication reviews. Preserve failed attempts
and the original execution identities when using this evidence downstream.

All P02 exit gates are accepted. P03 receives the supported configuration,
immutable numerical contracts, fixture manifest and evidence references for
the native operator interface. P03-T01 now implements that separate source-level
contract, planner and argument encoder. Continue with matching device dispatch
and lifecycle qualification in the [P03 handoff](../p03-operators-handoff.md).
P03 is `in_progress`; its full execution and lifetime gates remain open. Record
unresolved combinations in [status](../status.md) and [backlog](../backlog.md).
