# P02 — Tensor numerical contract

**Goal:** define and prove the arithmetic behavior of the first supported AI
configuration. This phase is `in_progress` through accepted baseline evidence;
no P02 exit gate is accepted yet.
The live status, dependencies and authoritative gate text are in
[roadmap.json](../roadmap.json); the accountable role is Compute architecture lead.

## Entry and boundaries

- P00 must be complete and P01-A01 (reproducible build) plus P01-A02 (native
  numerical baseline) must each have passing, reviewed evidence. The canonical
  [roadmap](../roadmap.json) records these as machine-checked
  `entry_acceptances`. P01's vendor integration gate P01-A03 is **not an entry
  prerequisite**; it remains blocked and must pass before P01/P07 closure.
- Use the [P02 staged-entry handoff](../p02-entry-handoff.md) for accepted inputs,
  remaining contract decisions and the first bounded deliverable.
- Start with the declared FP16/BF16 inputs and FP32 accumulation. Other formats,
  sparsity and block scaling require their own support decisions and evidence.
- Reuse the [tensor design](../../designs/tensor_core_wgmma_engine.md),
  [tensor RTL](../../../hw/rtl/tcu/), [SimX model](../../../sim/simx/tcu/) and
  [native tensor API](../../../sw/kernel/include/vx_tensor.h).
- This phase does not establish physical throughput, framework compatibility or
  universal IEEE behavior. A DPI C-arithmetic run is not native RTL proof.

## Ordered work packages

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

Hand P03 the supported configuration, immutable numerical contracts, fixture
manifest and evidence references. Record unresolved combinations in
[status](../status.md) and [backlog](../backlog.md); the next bounded action is to
map the accepted tensor signatures into a versioned native operator interface.
