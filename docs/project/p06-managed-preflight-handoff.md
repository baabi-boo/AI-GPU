# P06 managed preflight: next native handoff

## Next bounded action and present scope

**Add a read-only pending-read observation and a separately versioned native
lifetime witness covering every managed launch/reset boundary.** Apply it to the
existing four-process seed-free preflight, with exact reset accounting and zero
pending balance before resets, after successful runs and flushes, at the terminal
counter vector, and immediately before actual processor destruction. This is
planned native work; the replay continuation has not implemented or executed it.

The completed development step is the
[complete inert archive reader](../designs/managed_counter_preflight_replay_v1.md).
The [development audit](evidence/p06-managed-preflight-replay/development-audit.md)
explains why that reader was needed and distinguishes its consistency checks
from missing lifetime and dependency evidence. Start from the
[replay evidence packet](evidence/p06-managed-preflight-replay/README.md), the
[original preflight contract](../designs/managed_counter_preflight_v1.md), and
the broader [qualification plan](p06-mpm-qualification-plan.md).

The successful original at
`57248e73dfce4ae2d21d2cbdb82c3953eef2e3db`,
[run 45085300171, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171),
contains four managed processes, 132 launches and 4,224 exact output checks.
It does not contain the proposed pending-read and per-run witness. Its records
must retain their original version and scope; no replay result can reconstruct
observations that were never recorded.

The current reader requires seven explicit inputs: `--archive`, `--sha256`,
`--source-revision`, `--source-inventory`, `--source-inventory-sha256`,
`--source-derivation`, and `--source-derivation-sha256`. Select their identities
independently of the packet. The archive path must be absolute and canonical.
The [contract's CLI example](../designs/managed_counter_preflight_replay_v1.md)
provides the original pins. Source export establishes the selected Git-object
membership; archive replay remains an inert retained-data consistency check.

## Exact missing observations

| Existing source boundary | What it currently supplies | Required addition |
| --- | --- | --- |
| [`ProcessorImpl::perf_mem_pending_reads_`](../../sim/simx/processor_impl.h) and [request/reply callbacks](../../sim/simx/processor.cpp) | Checked transient balance, incremented for read requests and decremented for responses | A read-only value observation through the owned processor; no seeding, clearing or mutation API |
| `ProcessorImpl::run`, `launch_reset`, and `reset` in [processor.cpp](../../sim/simx/processor.cpp) | Direct-RAM launches reset platform state and clear pending balance; cumulative selected counters survive | Observe zero balance before every permitted reset and record exactly one launch reset per successful run |
| [`ModelState` and `Observation`](../../tests/regression/ai_counter_preflight/hooks.h) | Processor identity, idle/running state, clock/reset generation, two core counters and aggregate entry/completion counts | A versioned pending-balance field and a bounded ordered trace for all 33 run boundary pairs |
| [`model_locked` and wrapped `Processor::run_checked`](../../tests/regression/ai_counter_preflight/hooks.cpp) | Observed live processor, count of completed runs, typed errors and actual construction/destruction hooks | Capture the before/after state of each owned real run, including failures without turning them into successes |
| [`check_cache_flush`, `query`, `print_model`, and `print_witness`](../../tests/regression/ai_counter_preflight/main.cpp) | 33 flush replies, four coherent counter snapshots, ownership/CP state and loaded-library paths | Carry the new observations into the original emitted witness and reconcile them with operation order |
| [`_snapshots` and `_cache_flushes`](../../ci/project/p06_managed_preflight_records.py) | Exact snapshot/read inventory and bounded nondecreasing reset generations | A separately versioned validator that requires the complete run trace, exact reset deltas and pending-balance obligations |

`ProcessorImpl::reset()` sets `perf_mem_pending_reads_` to zero. A later zero
therefore cannot prove that the preceding run had no outstanding reads. The
current four snapshots and complete flush inventory do not observe every
pre-reset balance. A successful wait, `idle()`, and a small terminal counter
value each leave that missing premise unresolved.

## Implementation sequence

### 1. Freeze the new witness and its source route

Give the added native witness a distinct reviewed contract/version and explicit
reader selection. Preserve the original v1 archive, contract and reader outcome;
reject v1 evidence as incomplete input to the new lifetime requirement instead
of synthesizing missing zero fields. Freeze field names, bounds, ordering,
failure behavior and source expectations before inspecting new native outcomes.

Bind the exact route in the
[conditional lifetime argument](../designs/simx_counter_lifetime_v1.md): RV64
timing SimX, `p02-tfr`/STD, checked counters, the selected one-core topology,
one simulation worker, `PERF=1`, direct-RAM CP traffic, exclusive host submission,
VM/L2/L3/WGMMA disabled, and the selected Ramulator/HBM2 graph. Generated headers
and full build records must establish the route; a profile name is insufficient.

Expose only a const value observation through `Processor` and `ProcessorImpl`,
keeping ownership within the existing processor API. The proposed accessor must
not tick, reset, flush, allocate a new simulator object, alter counter storage,
or route a request. It is distinct from the diagnostic seed/accessor machinery
under `tests/unittest/checked_counters`, which must remain excluded from the
measurement build. Preserve ordinary and checked counter behavior, the existing
error path, and the [SimObject ownership rule](../designs/simobject.md#the-cardinal-rule).

### 2. Record all run/reset and flush boundaries

At the existing wrapped `run_checked` boundary, record a contiguous ordinal,
processor generation, state before the real call, outcome and state after the
real call. Require exactly 33 successful pairs per admitted process: the prime
and all 32 serial operations. Any exception, nonzero execution result, trace
overflow, missing pair or ownership change invalidates the lifetime.

For each pair, require zero pending reads and a quiescent owned processor before
the reset-bearing run, then successful completion, idle state, no running core
and zero pending reads afterward. For this direct-RAM route,
`run()` calls `launch_reset()`, which calls `reset()` once. Require each run's
reset generation to advance by exactly one, and a total advance of exactly 33
from the construction/opening baseline to the final run. No reset may occur
between a completed run, its flush, the next run entry, the terminal vector and
destructor entry except the next explicitly admitted launch reset.

Do not require one global monotonically increasing platform clock:
[`SimPlatform::reset`](../../sim/common/simobject.h) resets its clock to zero and
increments `reset_gen_`. Compare clocks only within the same reset generation.
The original's observed snapshot generations `1, 2, 34, 34` illustrate the
expected progression, but do not provide the missing intermediate observations.
Derive the new exact progression from bound source and the observed construction
baseline, rather than copying those historical numbers into an unrelated route.

Extend the flush observations to retain pending balance before and after each
of the 33 required output-download flushes. Require zero on both sides, no reset,
successful completion, stable ownership and the existing exact global DCR read
sequence. Flushes may legitimately tick and update selected counters, so retain
their before/after clock values and keep all flushes before the terminal vector.

### 3. Retain terminal ownership and completed destruction

Preserve the current exact 33 available/12 unavailable selector inventory and
both raw reply halves. Require a zero pending balance throughout all four
coherent snapshots, especially the terminal vector after the complete operation
and owner cleanup. The existing terminal observation has one device reference,
no queues or buffers, both CP enables set, successful retirement and no concurrent
submission. Bind those observations to the actual queue destruction/worker join
and final-reference source paths, not merely successful release return codes.
Relevant sources are [queue.cpp](../../sw/runtime/common/queue.cpp),
[AI runtime.cpp](../../sw/runtime/ai/runtime.cpp),
[device.cpp](../../sw/runtime/common/device.cpp), and
[reference counting](../../sw/runtime/common/vortex2_internal.h).

Require the state immediately before the real processor destructor to match
the terminal state, including zero pending balance. After destruction, record
completed disposal and platform cleanup through the existing wrapper; never read
destroyed processor storage. Platform cleanup can reset its clock, so its final
zero clock is a disposal observation, not a terminal counter equality. The
source argument must still exclude later ticks, submitted work, storage changes
and counter-updating finalizers through actual destruction. A later cleanup that
discards unfinished work cannot repair an earlier invalid lifetime.

### 4. Apply the 33-selector/40-component argument

The [source-bound theorem](../designs/simx_counter_lifetime_v1.md#terminal-theorem)
uses 26 single-component and seven two-component aggregates. All 40 selected
components must start at zero, receive only the audited nonnegative checked
updates, survive permitted resets, and remain stable from terminal readout until
their storage is destroyed. Every terminal aggregate must complete its checked
sum successfully through the production path, with both public halves verified.
These premises bound every earlier aggregate by its terminal value and
`2^64 - 1`.

A new public 40-field inspector is not required merely to repeat that theorem.
The necessary addition is evidence for its missing premises and source/binary
binding. The pending-read balance is separate: it decreases on responses and
is cleared on reset, so it is not one of the 40 monotone components. Neither
individual component checks nor terminal endpoint subtraction can replace the
checked aggregate and complete lifetime premises.

## Required tests and independent review

These are proposed controls; this handoff has not executed them.

| Control | Required discriminating result |
| --- | --- |
| Actual accessor against the live model | Reads the true transient balance without changing clock, reset generation, counters or state; controlled test-only request/reply transitions prove it does not always return zero |
| Nonzero balance before a reset | Reject before reset can erase it; retain the actual failure and forbid a later fresh context from rehabilitating that lifetime |
| Missing, duplicate or reordered run pair; skipped/extra reset | Reject even if all outer digests, derived bindings and favorable numerical/statistical records are coherently repaired |
| Nonzero balance after run, flush, terminal readout or at destructor entry | Reject at the specific boundary, independently of aggregate run counts and successful API statuses |
| Failure, trace overflow, extra owner or unfinished queue | Preserve the original error and incomplete lifetime; no successful witness may be emitted |
| Post-terminal launch, tick, reset or flush | Reject a changed suffix rather than accepting a favorable earlier vector |
| Frozen current v1 original | Existing replay retains its current result; the new lifetime validator rejects the absent versioned observations for the intended reason |
| Source/configuration/binary substitution | Reject ordinary or seeded measurement builds, diagnostic objects, tiny guard limits and mismatched loaded products |

Use separate controlled test targets for fault injection. Do not add seeding or
mutation symbols to the admitted managed measurement binary. Retain explicit
parent/fixed source identities and a control that demonstrates the old evidence
cannot establish the new property; a compiler failure caused only by an absent
new method is not sufficient behavioral sensitivity. Preserve exact numerical
fixtures and compare ordinary/checked behavior. If a proposed observation changes
model timing, follow the inherited SimX/RTL parity obligations instead of treating
it as harmless instrumentation. An independent agent must review the changed
contract/enforcement and the parent-failure controls before qualification.

## Separate prerequisite: dependency source to loaded products

The new pending witness does not resolve dependency compilation provenance.
Fresh receipts must bind the complete selected dependency source and build-input
closure, configure/compile/link commands, tool identities, produced objects and
libraries, and the bytes used by the actual process. Preserve source revision,
tree and immutable dependency commits rather than trusting a cached artifact's
filename or SHA-256 alone.

| Product chain | Required connection |
| --- | --- |
| SoftFloat static archive | Bound source/options → fresh object/archive membership → the actual model static link → final model bytes |
| Ramulator core and extension libraries | Bound Ramulator and fetched dependency sources/configuration → fresh compile/link products → exact `libramulator.so` and `libramulator-vortex.so` loaded bytes |
| Generated runtime/model libraries | Complete application/backend build records and products → actual `libvortex.so`, `libvortex-simx.so` and `libsimx.so` loader observations |

The [current dependency Makefile](../../third_party/Makefile) runs nested
`make -j4` for Ramulator. Before the fresh-build task, reconcile that nested
parallelism with the declared resource budget; limiting only the outer process
does not bound its children. The current native preflight contract requires
15 GiB free disk, a 4 GiB RSS limit, two build jobs and one simulation worker.
Inspect resources first and use separate freshly configured build trees. This
handoff does not authorize a weaker budget or certify the local host for native
execution. The original replay's selected header inventory also does not supply
the full transitive dependency compilation closure or absent model object bodies.

## Completion boundary and subsequent development

Retain a new original archive only after the separately versioned witness and
reader, source/build closure, negative controls and independent review are ready
for their declared scope. The four-process FP16/BF16 × allocation-policy matrix
still comprises 132 launches and 4,224 checked words, with 16 snapshots, 528
available queries, 1,056 half replies, 132 flush replies and 192 unavailable
rows receiving no query. The pending-balance extension must not silently change
those numerical and process populations.

Complete qualification additionally needs the dependency receipts and an
independently reviewed admission/final-validation path for the exact later
measurement binaries. Only that separately established route can admit a fresh
full warm attempt under the unchanged rules: **24 processes, 792 launches and
25,344 exact output words**, including excluded primes and warm-ups. Preserve
all failed attempts and valid negative performance results.

The current preflight and replay retain all seven fields as false:
`qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `phase_acceptance`, and `performance_acceptance`.
Their three obligations remain
`all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance`, and
`independent_complete_counter_qualification`. A future version may discharge
only the obligation supported by its actual reviewed evidence; this document
discharges none.

Warm v1 remains unconditionally rejected by `P06-WARM-RV64-MPM-HIGH-HALF`, with
`absolute_no_wrap_bound="not_established"`. P06 and P06-T01 stay `in_progress`,
P06-A02/A03 remain open, and existing P06-A01 simulated acceptance retains its
historical scope. Vendor XRT hardware emulation, physical hardware, the separate
RV64 area finding and P05 framework acceptance remain separate work. No test,
native execution, full-suite result, publication or approval is claimed by this
handoff.
