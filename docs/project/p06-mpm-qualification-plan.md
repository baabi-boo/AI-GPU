# P06 counter qualification plan

## Decision and current boundary

Resolve exceptional channel cleanup and complete native verification and
independent review of the [simulator completion prerequisite](p06-simulator-completion-audit.md).
Then implement a separately versioned qualification layer, independently review its
enforcement and collect one fresh complete matched warm attempt. This remains a
prospective counter plan: its qualification layer and evidence format are not
implemented by this document.

The [transport audit](p06-mpm-transport-audit.md) identifies the original RV64
high-half defect and paired SimX/RTL repair. The
[reviewed native packet](evidence/p06-mpm-transport/reviews/native-review.md)
passes all eight directed candidate executions and establishes both same-harness
parent numeric failures at `18c8880`. Its immutable governance suite passes
2,910 tests. The [alternative comparison](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the specific cost-review finding and selects the direct decoder, with
raw area failures preserved. Broader CI and publication remain separately
tracked in the [handoff](p06-mpm-transport-handoff.md). A native transport pass is distinct from a proved
counter lifetime, a warm experiment or P06 acceptance.

The [warm v1 contract](../designs/warm_workspace_benchmark_v1.md), its
[analyzer](../../ci/project/p06_warm_analyze.py) and
[replay](../../ci/project/p06_warm_replay.py) retain the unconditional
`P06-WARM-RV64-MPM-HIGH-HALF` block, `qualified=false` and
`absolute_no_wrap_bound="not_established"`. Preserve their historical rejection
behavior, original cold execution pins and accepted archives. Missing historical
high bits cannot be recovered from low words.

## Completion prerequisite

The [completion contract](../designs/simulator_completion_v1.md) addresses
exceptions lost by the old SimX run entry and both asynchronous backend wrappers,
plus tasks that completed before their first busy poll. A prospective counter
guard must reach public waits as a persistent error instead of apparent success.
The checked entry preserves legitimate `gp` values, including `-1`; `AsyncRun`
consumes futures, retains failure, preserves the launch edge and joins pending
execution before teardown. The existing public error mapping remains unchanged.

Host backend/public fixtures, deterministic helper checks and compiled-parent
behavioral failures supply development evidence. A separate host probe using the
actual SimObject/SimChannel implementation found `inflight_count=1` surviving
exceptional teardown and a fresh context remaining non-idle. Repair and verify
that accounting before claiming successful cleanup or context recreation.
Native checked-model and public-success tests, a bounded runner and a hosted
workflow are implemented, but actual
native execution is still `not_run` pending hosted CI. Complete that verification
and reconcile the final source-bound packet under independent review before
using this mechanism to enforce counter qualification. Host fault injection is
not a native processor or RTL fault result. Preserve the 15 GiB native disk reserve.

## Qualification work to implement and review

1. **Specify the supported route.** Name the exact RV64 `p02-tfr` SimX timing
   configuration, enabled tensor/performance features, topology and available
   counter selectors used by the warm experiment. The directed transport tests
   use stable injected counters and TCU-disabled configurations; extend evidence
   to the actual warm configuration and each required available selector before
   claiming that coverage. Preserve architectural CSR semantics and public ABI.
2. **Bind evidence to execution.** Define a new versioned qualification record
   that binds reviewed transport evidence and its scope to the complete source
   revision/tree, relevant source bodies, generated configuration, original
   compiler/linker records, tools/dependencies and actual host/runtime/kernel
   binary identities. Resolve the [standalone interpreter finding](evidence/p06-mpm-transport/reviews/enforcement-review.md)
   by recording the actual executing interpreter separately from PATH `python3`;
   the current hosted workflow already requires their equality. Require identical
   binaries for both policies within each format, with before/after stability
   checks. A revision label, caller flag or
   self-asserted qualification ID is insufficient.
3. **Prove counter meaning and read coherence.** Document each counter's width,
   reset/lifetime, accumulation semantics and availability. Establish whether
   every snapshot is taken while the model is quiescent and prove that its two
   32-bit reads observe one stable value. If a counter can advance during the
   read, require a separately reviewed coherent-read contract and adversarial
   rollover evidence. The transport repair itself introduces no atomic snapshot
   or concurrency guarantee.
4. **Establish the absolute no-wrap bound.** Supply an independently reviewed
   bound for every required true cumulative counter over the complete interval,
   including initialization, primes, measured calls and teardown observations.
   Bind its assumptions to the executed configuration and reject violations.
   Observed monotonicity, small reported values, a process timeout or guessed
   event rates cannot substitute for that proof. Missing bounds remain blocked.
5. **Review rejection and replay behavior.** Keep the frozen v1 path blocked and
   introduce the new qualification path explicitly. Reject old, absent,
   unsupported, truncated, source/configuration/binary-mismatched or unreviewed
   evidence. Exercise both favorable and unfavorable statistics with invalid
   qualification data. Offline replay treats retained code as data and checks
   original archives, commands, resource observations and bindings independently.
   Require review by an agent that did not author the enforcement change under
   the [review policy](../review/code-review-policy.md).

Freeze the new qualification contract and review its tests before inspecting
fresh performance results. Do not widen a statistical threshold, change a
fixture, alter a golden or remove a failed attempt to obtain qualification.

## Fresh matched attempt

After the qualification prerequisites pass, use the unchanged warm workload,
timing interval, allocation observer, poison schedule, policy order and sample
populations. Run FP16 then BF16, six ordered policy pairs per format, one prime
plus 32 serial operations per process: **24 processes, 792 launches and 25,344
exact FP32 output words**, including excluded primes and warm-ups. Retain the
excluded data. Both policies use the same clean source and executable per format.

Keep the five measured batch means per format/policy and all three original
predicates: candidate median at most 95% of reference in each format, no slower
measured host pair, and no increased measured paired active-cycle delta. Use
exact comparisons. No replacement samples, optional stopping, outlier removal
or observer-overhead subtraction is permitted. An incomplete attempt is invalid;
a fully qualified valid failure to improve remains a retained negative result.

Preserve the existing two-job, 4 GiB polled RSS, 15 GiB free-disk, 16 MiB log,
1,800-second build, 180-second invocation and 90-minute hosted-job limits.
Report instrumented host time and scoped modeled counters; this experiment
does not establish physical speed, energy or whole-GPU fit.

P06-A02/A03 require their own reviewed acceptance. Vendor P01-A03, P05-A02/A03,
the inherited 267 → 283 DSP finding, physical FPGA and silicon obligations remain
separate. Preserve all original acceptance records and unavailable evidence.
