# P06 next experiment proposal: serial workspace amortization

**Warm performance draft for review; not a frozen sampling contract or an
optimization result.** The ownership prerequisite and a separate correctness
smoke are now implemented under the
[frozen serial workspace contract](../designs/serial_matmul_workspace_v1.md).
The [workspace handoff](p06-workspace-handoff.md) and
[evidence packet](evidence/p06-serial-workspace/README.md) record their current
verification scope; full checkpoint integration and fresh native correctness
execution remain pending. The proposed timing, repetitions and decision criteria
below are still unfrozen and have not been evaluated. P06-A01 retains its accepted
simulated scope at `84b6ca0ca75fba248ba330642bbf8764db3d459c`; P06-A02/A03 remain open.

## Evidence and one hypothesis

The [audit](p06-qualification-audit.md) and [analysis](evidence/p06-baseline/reviews/analysis.json) report 5,952 active cycles
for 512 useful FLOPs at `(8,4,8)`, versus 6,405 cycles for 4,096 FLOPs at
`(16,8,16)`, identically in both formats. These whole-context SimX counts motivate
investigation; they do not identify allocation cost or another causal bottleneck.

**Hypothesis:** for serial `(8,4,8)` matmuls, retaining one fixed A/B/D buffer
workspace reduces host time per validated operation versus per-operation buffer
allocation, under the same warm context, without numerical or modeled-cycle regression.
The sole treatment is buffer lifetime. Both arms retain context/module/kernel, create
and release operation queues/events, rewrite inputs and poison, launch the unchanged
kernel, download, compare and explicitly close.

## Equal reference and candidate

Use `fp16-single-dense_boundaries` and `bf16-single-dense_boundaries` from the
[frozen manifest](../../ci/project/p06_benchmark_contract.json), with its exact
fixture bytes, layout, FP32 expected words, poison policy and 512 FLOPs per call.
Each call retains 192 input H2D bytes, 128 poison H2D bytes and 128 tensor D2H bytes.
Argument/control and module traffic remain separately identified, outside those totals.

The new reference must be a reviewed clean descendant of `9036b379e3dbdf2b68d1590ca37a47cbf099b7b4`
with the common ownership prerequisite and measurement harness, retaining current
per-operation A/B/D allocation. Its candidate adds only the resident buffer policy.
The exact performance reference/candidate commits are not yet pinned: identify
both, their reviewed diff, source inventories and artifact hashes before
evaluation. Match tools, dependencies,
independent compiler records, generated headers, native kernel, RV64 `p02-tfr`
SimX timing profile, topology, observer and host conditions. Record actual buffer
addresses/extents independently; allocation policy need not preserve address values.

Keep the accepted [cold benchmark](../designs/native_benchmark_v1.md) and its raw
samples intact. It uses one fresh process/context per invocation; its retained
warm-up establishes no warm-cache state. Neither new warm arm is a replacement
baseline or directly comparable to the original process-duration measurements.

## Ownership prerequisite before reuse

The [serial workspace contract](../designs/serial_matmul_workspace_v1.md) now
implements the prerequisite identified by this proposal: one managed context
reservation per linked runtime instance and one operation lease per context,
including after successful `wait()`. Completed explicit close drains accepted
work and releases operation resources before permitting another submission.
A live operation retains its context and any resident buffers; owner close
remains incomplete while that operation is live. Timeout and partial submission
retain required ownership; observed cleanup failure prevents new managed work.
Non-timeout execution errors survive later successful drain.

Targeted host tests cover direct and real-model composition, allocation failure,
simultaneous creates and cleanup poisoning. Complete checkpoint integration and
the separate native correctness matrix remain pending in the
[workspace packet](evidence/p06-serial-workspace/README.md). The native guard
does not police raw runtime clients, separately linked copies or concurrent
methods on one owner; the [Python restrictions](../designs/python_binding_v1.md#process-and-concurrency-restrictions)
remain separately scoped. No overlap or general native concurrency is proposed.

## Proposed samples and measurement boundary

Freeze a separate schema/manifest before execution. Per format and arm, retain
one excluded warm-up batch and five measured batches, each in a fresh process.
Each batch opens one context, primes with one excluded fully validated operation,
then performs 32 serial operations, closing each before the next. Proposed total:
24 processes and 792 launches; 20 measured batches contain 640 measured launches.
Run FP16 then BF16; alternate reference/candidate order by paired batch index,
starting reference-first. Retain every operation, warm-up, raw log and failed attempt.
Any failed prime, incomplete batch or sample replacement invalidates that attempt.
Time each operation in-process from immediately before submit through exact output
comparison and completed explicit close, identically in both arms. Report creation,
priming, workspace initialization, owner teardown and complete process time separately.
Keep original open/release snapshots; add validated cumulative snapshots after priming
and after operation 32 for the new batch boundary. Do not attribute context totals
to individual kernels or silently feed this schema into the cold-baseline analyzer.
Report each batch mean, then count/min/max/median/population standard deviation over
the five independent measured batches; keep individual operation values as diagnostics.
No outlier removal, optional stopping, hidden retries or post-run threshold changes.

## Correctness, metrics and rejection

Before performance evaluation, cover existing supported-shape/format correctness,
unchanged output poison cases, changed inputs across reuse, exact output words and
native dispatch. Exercise rejection of second live operations/contexts, completed
wait without close, wait/close timeout then drain, partial allocation/enqueue failure,
dependency-skipped work, owner destruction with retained operation, repeated close,
cleanup errors and recovery in a fresh process. Verify no stale output or cross-call
writes, no early buffer release, bounded resident allocation and full final release;
retain validation, primary, cleanup and completion results separately.

Primary metric is observed in-process host time per validated operation, not device
latency. Also report modeled batch active cycles/FLOP, macroinstructions, explicit
payload bytes, allocation counts and resident/peak bytes with their measurement scope.
The existing 33 available counters and 12 unavailable L2/L3 rows retain their meanings;
unavailable stays null. New metrics remain unavailable until actually instrumented.
Physical latency/bandwidth, power, energy and per-kernel counter attribution remain
unavailable. Never subtract the suspected supervisor delay or overlapping intervals.

Proposed go/no-go, subject to review before freezing: at least 5% lower median batch
mean host time in each format, no slower paired batch, and no increase in modeled
batch active cycles. Reject any correctness, ownership, cleanup, provenance, resource
or inherited-gate failure; absent improvement rejects this treatment. Five batches
support descriptive results only. Preserve failures rather than adjust the protocol.

Next performance deliverable: an independently reviewed sampling manifest and
measurement schema, with exact matched source identities and rejection criteria,
after the workspace correctness checkpoint has been qualified. The implemented
[correctness manifest](../../ci/project/p06_workspace_contract.json) specifies
no timing or speedup acceptance and does not freeze this performance proposal.
P06-A02 needs matched correctness, native RTL and applicable parity/performance evidence;
A03 needs reviewed target budgets and resource/timing reports.
Keep two jobs, 4 GiB polled RSS, 15 GiB disk reserve, bounded logs/deadlines, the inherited
267 -> 283 DSP finding and P01-A03 vendor `hw_emu` blocker. No hardware/budget waiver,
golden-data change, poison tuning, tolerance relaxation or physical-speed claim follows.
