# Warm workspace benchmark v1

## 1. Experiment identity and scope

`p06-warm-workspace-v1` freezes a new paired experiment for P06-T01 before its
performance evaluation. Its machine definition is
[p06_warm_contract.json](../../ci/project/p06_warm_contract.json); the independent
[contract reader](../../ci/project/p06_warm_contract.py) requires its exact
fields, values, types and immutable numerical/configuration inputs. This is a
measurement contract, not evidence of execution, improvement or phase acceptance.

The hypothesis is that retaining A/B/D allocations for serial `(8,4,8)` matmuls
reduces **instrumented host time per validated operation** without a correctness,
cleanup or modeled-cycle regression. The reference is `per_operation`; the
candidate is `reusable_single_tile`. Both are already present in the same
managed runtime. Each format uses one clean source revision and the **same host
executable, runtime libraries and kernel bytes for both policies**. Only policy,
paired sample identity and their bound qualification ID differ between arms.
The runner binds exact source revision/tree, contract, fixtures, generated
configuration, original compiler/linker records, tool/dependency identities and
binary hashes before either arm executes, and checks stability afterward.

This replaces the unfrozen proposal's separate-source-arm idea with a more
tightly matched comparison. It does not revise the accepted cold baseline,
its original source pins or any recorded measurement. Cold fresh-process
durations cannot be compared directly with the new in-process interval.

The only backend is RV64 `p02-tfr` **SimX timing mode**, with native TFR tensor
and STD scalar arithmetic, one core, four warps and four threads. The SimX
backend is built with `PERF=1` and exactly one enabled `PERF_ENABLE` selector;
runtime/kernel/host compilation does not acquire that backend selector.
Functional-only or multithreaded SimX, debug tracing and alternate profiles are
outside this experiment. Runtime event profiling stays disabled in both arms.

## 2. Frozen workload and treatment

The two cases are `fp16-single-dense_boundaries` and
`bf16-single-dense_boundaries` from the unchanged independent P02 layout
fixture. Their compact A/B bytes, layouts and all 32 expected FP32 words are
reproduced through the trusted fixture producers. Every operation uses the
unchanged native matmul kernel and versioned 56-byte arguments.

| Quantity per operation | Frozen value |
|---|---:|
| Shape `(M,N,K)` | `(8,4,8)` |
| A/B/D requested bytes | 128 / 64 / 128 |
| Input H2D bytes | 192 |
| Destination poison H2D bytes | 128 |
| Output D2H bytes | 128 |
| Native launches | 1 |
| Exact FP32 output words | 32 |
| Useful dense FLOPs | 512 |

Argument/control/module traffic is separate from those tensor payload totals.
Each arm creates and releases fresh operation queues/events, rewrites all input
and poison bytes, dispatches the same kernel, downloads the complete result,
compares all output words and explicitly closes the operation before the next
submission. There is no CPU matmul fallback or overlapping operation.

The prime has operation index zero and poison `0xDEADBEEF`. Indices one through
32 alternate `0x7FC0DEAD`, `0xDEADBEEF`, continuing by index parity. The exact
same poison schedule applies to both arms and every batch. Timing data cannot
select a different fixture, poison, repeat count or threshold.

## 3. Process order and populations

Run FP16, then BF16. For each format, process pair indices zero through five in
ascending order. Pair zero is the excluded warm-up pair; pairs one through five
are measured pairs. Even pair indices run reference then candidate; odd indices
run candidate then reference. Both arms run serially in the same host job using
the same frozen build. Do not parallelize arms or formats within this experiment.

Each policy batch starts a fresh process and one managed device context, creates
the owner, performs one fully validated excluded prime, then performs exactly
32 validated serial operations. The context remains live across those calls.
The owner closes after the final batch observations. A prime is excluded from
the primary mean in every process, including the excluded warm-up processes.

| Complete two-format experiment | Count |
|---|---:|
| Policy processes | 24 |
| Excluded warm-up processes | 4 |
| Measured processes | 20 |
| Native launches, including all primes and warm-ups | 792 |
| Exact FP32 words, including all primes and warm-ups | 25,344 |
| Operations in the primary measured population | 640 |
| Exact words in the primary measured population | 20,480 |
| Useful FLOPs in the primary measured population | 327,680 |

The helper may describe a format subset for validation tools; such a subset is
never a complete experiment. Formal execution requires the full ordered matrix.
No failed sample is replaced, retried within the attempt, omitted or classified
as an outlier. A new explicitly identified attempt retains the previous failure.

## 4. Primary timing and instrumentation

Use integer nanoseconds from `std::chrono::steady_clock`. Capture `begin_ns`
immediately before `submit`. Include submission, bounded wait, comparison of
the actual 32 output words, completed explicit operation close and their success
checks. Capture `end_ns` immediately afterward. Require a strictly positive
interval. Submission succeeds with `validation=0`, `primary=0`, `cleanup=0`,
`complete=false` and a returned operation. Wait and explicit close require the
same zero status fields and `complete=true`. A timeout invalidates this attempt;
it does not authorize early resource release or replacement timing.

Prepare fixture bytes and fixed record storage before timing. After a successful
explicit close and the end timestamp, copy the detached output and trace into
retention storage, then reset the closed operation. Copying does not supply the
in-interval numerical comparison: that comparison must use the actual output
before close. Serialize all retained operation records after the timed batch,
so output formatting and flushing cannot perturb later operation intervals.

The minimal allocation observer wraps the real device-open/release and
buffer-create/release functions. It uses three bounded live-buffer slots and
scalar accounting. It validates the A128/B64/D128 requests and native statuses,
tracks actual returned handles and releases, and detects overflow, unknown
releases, incorrect phase and retained resources. Timed wrappers perform no
additional native memory/address/counter query, dynamic allocation, formatting
or scan whose length grows with the sample index. Their fixed bookkeeping is
included in the primary metric; report **instrumented host time**, without
claiming uninstrumented runtime or physical-device latency.

The richer correctness observer remains separate. It establishes per-buffer
allocator-delta and ownership behavior; reusing its extra queries in the timed
caller would add policy-dependent observation cost. Do not subtract an estimate
of wrapper overhead. Context creation, priming, owner teardown and supervisor
process duration remain separate observations. Nested/overlapping intervals
are never added as exclusive costs or corrected using a guessed process-exit
delay.

The owner-create-begin through owner-close-end span must fit within the
supervised process duration, allowing the same explicit 1,000 ns observation
allowance used by the retained timing checks. This is containment validation;
it does not correct either observation or subtract supervisor overhead.

## 5. Native record schema

Successful raw output has exactly 33 `P06_WARM_OPERATION` JSON records in
operation-index order, followed by one `P06_WARM_SUMMARY`, then exactly one final
`PASSED!` line. A `P06_WARM_FAILURE`, malformed/unknown reserved marker, duplicate
record, failure token, incomplete sequence or extra success marker invalidates
the output. Other ordinary native diagnostics may be retained without changing
this record order. Readers enforce byte/nesting bounds, exact key sets, integer
ranges and types; booleans cannot substitute for integers. Duplicate JSON keys,
floating/nonfinite native record numbers, invalid Unicode and ambiguous control
separators are rejected.

Every operation and summary has these common identity fields:
`schema_version`, `contract_id`, `qualification_id`, `sample_id`, `format`,
`policy`, `pair_index`, `phase`. Version is one; the qualification ID is the
lowercase 64-hex SHA-256 of the runner's complete binding. The sample ID is
`warm-simx-FORMAT-pairINDEX-POLICY`. Process phase is `warmup` for index zero,
otherwise `measured`. All values must match the exact supervised command and
binding, not merely agree with another line in the same log.

An operation additionally contains:

- `operation_index` (zero through 32), `role` (`prime` at zero, otherwise
  `sample`), `case_id`, `m`, `n`, `k`, `poison`, `begin_ns`, `end_ns`.
- `checked=32`, `mismatches=0`, all 32 lowercase eight-hex `actual_bits`, and
  `passed=true`. Readers recompute comparisons against independent fixtures.
- `dispatch`: actual `a_address`, `b_address`, `d_address`, `a_bytes`,
  `b_bytes`, `d_bytes`, `writes`, `launches`, `reads`, `waits`,
  `timed_out_waits`, all encoded `argument_bytes`, five `event_results`, and
  `profiling_enabled`. Required counts are 3/1/1/1/0 respectively, all events
  succeed, profiling is false, extents are aligned/disjoint without overflow,
  and decoded arguments must exactly match the case and addresses. Resident
  addresses stay fixed across all 33 calls; default address reuse is permitted.
- `results` with `submit`, `wait`, `close`, each containing exactly
  `validation`, `primary`, `cleanup`, `complete` with the success semantics above.
- `counts_before` and `counts_after`, captured outside the timer, using exactly
  `device_open_calls`, `device_release_calls`, `buffer_create_calls`,
  `buffer_release_calls`, `live_buffers`, `live_requested_bytes`,
  `peak_requested_payload_bytes`, `premature_releases`, `errors`.

The summary additionally contains `operations=33`, `checked=1056`,
`mismatches=0`, `passed=true`, final `counts`, `snapshots`, `memory`, `results`,
`host_intervals_ns`, and `device_release`. Owner `results` has only `create`
and `close`, both complete successes. `host_intervals_ns` has `create` and
`close`, each with integer `begin_ns` and `end_ns`. `device_release` has exactly
`schema_version=1`, `sample_id`, `context_id=1`, `status=0`, recording the actual
wrapped native release result. Summary success or counts never replace raw
operation, query or release validation.

The exact field inventories are also machine-readable under `observation` in
the manifest and constants in the contract reader.

## 6. Counters, timing chronology and resource reconciliation

`snapshots` has `after_open`, `after_prime`, `after_batch`, `before_release`.
Each retains the existing P06 snapshot shape: `schema_version`, `sample_id`,
`context_id`, `device_index`, `compiled_memory_block_bytes`, `query_begin_ns`,
`query_end_ns`, `capabilities`, `counters`. The immutable inventory contains
45 counter rows, with 33 available and 12 unavailable L2/L3 rows. Each row
retains its name, class/CSR/core, scope, unit, required ISA, availability,
native status and value. Unavailable status/value remain null. Actual
capabilities must match the frozen topology, including their scope as configured
apertures rather than physically measured capacities.

Capture after-open and before-release snapshots in the wrappers while the native
device is live. Capture after-prime only after the prime explicitly closes, and
after-batch only after operation 32 explicitly closes. No snapshot or memory
query overlaps a primary operation interval. Preserve ordering:

1. Owner-create begin ≤ after-open query begin ≤ query end ≤ owner-create end.
2. Owner-create end ≤ prime begin < prime end ≤ after-prime query begin ≤ end.
3. After-prime query end ≤ operation-one begin; operation intervals are ordered
   and non-overlapping through operation 32.
4. Operation-32 end ≤ after-batch query begin ≤ end ≤ owner-close begin.
5. Owner-close begin ≤ before-release query begin ≤ end ≤ owner-close end.

Available cumulative counters cannot decrease or wrap across any snapshot.
The measured batch delta is **after-batch minus after-prime**, spanning the
32 sample operations and their data movement. Cycles and retired
macroinstructions must have positive batch deltas. Divide cycles by 16,384
useful FLOPs only under that valid batch scope. No per-kernel attribution,
physical latency/bandwidth, power or energy follows from these observations.

`memory` has five entries: `after_open`, `after_create`, `after_prime`,
`after_batch`, `before_release`. Each has exactly `queried=true`, `status=0`,
`free_bytes` and `used_bytes`. Queries occur outside operation timers, before
the native device releases; missing/failed observations are unavailable evidence,
never zero. The sum of free/used remains valid and consistent. The two idle
post-operation snapshots equal the after-create snapshot. Before-release
memory returns to the after-open baseline after all managed allocations are
released. These are simulator accounting observations, not physical reclamation.

| Completed 33-operation process | Per operation | Resident |
|---|---:|---:|
| Tensor creates/releases | 99 / 99 | 3 / 3 |
| Tensor creates during owner setup | 0 | 3 |
| New tensor creates/releases per operation | 3 / 3 | 0 / 0 |
| Idle requested tensor payload | 0 | 320 |
| Peak requested tensor payload | 320 | 320 |
| Final requested tensor payload | 0 | 0 |

Every process records one successful device open and release, zero observer
errors/premature releases and no live tracked handles at teardown. Before each
default operation `i`, create/release counts are `3*i`; afterward they are
`3*(i+1)`. Resident counts stay at three creates and zero releases until final
owner close. The prime's initial default peak is zero; every later peak and
the resident peak are 320. Native allocation calls from separately compiled
runtime internals are not implied to be tensor calls observed by these wrappers.

## 7. Analysis and predetermined decision

Compute one arithmetic mean of the 32 primary intervals for each process.
Exclude every prime and both format warm-up pairs from the decision. For each
format/policy report count, minimum, maximum, median and population standard
deviation across its **five measured batch means**. Retain all
operation durations, paired ratios, excluded warm-ups and raw counters as
diagnostics. Process separation does not establish statistical independence;
the 640 serial calls are not 640 independent batches.

The hypothesis is supported only when all validity requirements pass and:

- Candidate median batch mean is at most 95% of the reference median in
  **each** format.
- No measured candidate batch mean exceeds its paired reference mean.
- No measured candidate batch's active-cycle delta exceeds its paired
  reference delta.

Use exact integer/rational comparisons for these decision boundaries. Floating
summaries do not choose a different outcome at the threshold. No hidden retries,
outlier removal, optional stopping or threshold adjustment follows a rejection.
An attempt with incomplete/failed correctness, cleanup, provenance, timing or
resource observations is invalid, rather than a successful negative experiment.
A valid failure to improve rejects the treatment under this contract and is
retained as such. Five pairs support descriptive findings, not a confidence,
tail-latency or production-performance guarantee.

## 8. Provenance, budgets and remaining gates

Verify raw command exit status, full log size/hash, actual argv/environment,
binding identity and every retained source/configuration/compiler artifact.
Retained code is data, never imported or executed by offline readers. Bind both
policies to identical source and binary inventories per format and retain all
failed attempts. Numerical/profile/kernel/counter source pins are immutable;
current runtime and new harness code are bound by the clean execution snapshot,
not incorrectly claimed as the original cold-baseline source.

Preserve two build jobs, 4 GiB polled process-group RSS, 15 GiB free-disk reserve,
16 MiB per-command logs, 1,800-second build-command and 180-second invocation
deadlines, and the 90-minute hosted-job deadline. Observed preparation and
execution resource checks remain required. No optional CLI changes the workload,
sample counts, policy set, thresholds or allows dirty source.

Independent correctness and enforcement review must precede performance
qualification. This experiment alone cannot close P06-A02/A03 or imply native
RTL/applicable inherited-gate qualification, synthesis fit, physical FPGA or
silicon performance. Vendor P01-A03 and the inherited 267-to-283 DSP finding
remain separate obligations. A new successful result does not rewrite any
historical acceptance record or turn an unavailable measurement into a pass.
