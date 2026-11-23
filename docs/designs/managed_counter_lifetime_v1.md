# Managed counter lifetime observations, version 1

## Scope and explicit selection

The contract `p06-managed-counter-lifetime-v1` supplements the
[managed preflight v1 transcript](managed_counter_preflight_v1.md) with the
missing pending-read and per-run/reset observations identified in the
[native handoff](../project/p06-managed-preflight-handoff.md). Its machine-readable
descriptor is [p06_native_lifetime_contract.py](../../ci/project/p06_native_lifetime_contract.py).
This document defines validation requirements; it does not assert an executed
native result or qualify a measurement binary.

The native application accepts exactly one leading `--lifetime` selector. The
outer wrapper consumes that selector before passing the remaining arguments to
the existing option parser and unchanged warm caller. Duplicate, misplaced or
unknown selectors fail. The default mode preserves its v1 transcript and reader.

Successful lifetime mode emits the complete v1 transcript, including its final
`P06_MANAGED_COUNTER_WITNESS` line, then exactly one final
`P06_MANAGED_COUNTER_LIFETIME ` JSON line ending in a newline. The new reader
removes only that last line and passes every preceding byte to the existing v1
reader. It then validates the additional record against the verified v1 result.
The old reader continues to require its own final marker; it does not silently
accept a new protocol. A v1-only transcript fails the new reader specifically
because lifetime observations are absent.

The sidecar has schema version `1` and a distinct contract identity. The runner's
report, build binding and process binding explicitly select this contract and
retain the canonical descriptor hash. Shared process/sample IDs still identify
the same four underlying numerical processes; the contract identity and binding
digest distinguish the extension. Selected trusted helper bytes, including the
new reader, are bound before execution. A reader never imports retained code,
executes retained commands or opens paths supplied by a transcript.

## Frozen execution route and population

The existing source, generated-header and compiler-record checks continue to
establish RV64 timing SimX, `p02-tfr`/STD, 64-bit checked counters, one core and
one simulation worker, `PERF=1`, direct-RAM command-processor traffic, exclusive
host submission, VM/L2/L3/WGMMA disabled and the selected Ramulator/HBM2 graph.
Diagnostic mutation objects and nonproduction small counter limits remain
excluded. A name such as `p02-tfr` is insufficient without the checked build
records. The new const accessor observes the actual owned pending-read balance
without ticking, resetting, flushing, allocating, routing work or changing it.

The matrix remains FP16/BF16 × `per_operation`/`reusable_single_tile`. Each
fresh process performs a prime and 32 serial operations: 33 launches and 1,056
checked words. Four processes contain **132 launches and 4,224 checked words**.
Per process, the original transcript also supplies four snapshots, 132 available
counter queries, 264 raw half replies, 33 output flush replies and 48 unavailable
rows with no query. None of these populations is reduced or relabelled as warm
performance sampling. A separate native accessor probe is outside these counts.

The resource limits remain two build jobs, one simulation worker, 15 GiB free
disk, 4 GiB RSS, a 1,800-second build timeout and a 180-second process timeout.
Existing preparation and failure retention remain mandatory.

## Exact record shapes

Field sets are exact. Unknown, missing and duplicate fields fail. Booleans cannot
stand in for integers; counters and ordinals are bounded unsigned 64-bit values.
The inherited bounded UTF-8 JSON decoder rejects floating-point values,
nonfinite values, excessive depth and oversized records. The sidecar is at most
512 KiB, within a complete output bounded to 16 MiB. Its arrays have the fixed
lengths below, so accepting a favorable prefix of an overflowed trace is invalid.

| Record | Exact fields and interpretation |
| --- | --- |
| Identity | `schema_version`, `contract_id`, `process_id`, `sample_id`, `execution_binding_sha256`, `format`, `policy`; all match the selected invocation, with the new contract ID |
| Route | `backend="simx"`, `xlen=64`, `checked_counter_bits=64`, `simulation_workers=1`, `seeded=false` |
| Extended model | Every v1 model field plus `pending_reads`; removing exactly that additional field reproduces the corresponding v1 state where one exists |
| Run | `ordinal`, `before`, `after`, `real_call_entered`, `completed`, `exception`, `dcr_reads_before`, `dcr_reads_after`, `cache_flushes_before`, `cache_flushes_after`; exactly 33 ordered records |
| Read supplement | `sequence`, `pending_before`, `pending_after`; 264 `reads` and 33 `cache_flush_reads`, each bound one-to-one to the same ordered v1 DCR sequence |
| Snapshot | `name`, `before`, `after`; four ordered extended model pairs named `after_open`, `after_prime`, `after_batch`, `before_release` |
| Destruction | The v1 destruction fields `before`, `completed`, `ticks_after`, `reset_after`, `idle_after`; only `before` is an extended live-model state |
| Other top-level fields | `constructed_state`, `runs`, `snapshots`, `reads`, `cache_flush_reads`, `destruction`, `trace_overflow`, `unresolved_obligations`, and all seven false claim fields |

An extended model contains `live`, `idle`, `any_running`, `generation`, `ticks`,
`reset_generation`, `core_cycles`, `core_instructions`, `exitcode` and
`pending_reads`. An admitted live state has one owned processor generation,
`live=true`, `idle=true`, `any_running=false` and `pending_reads=0`. The accessor
must be read at the boundary; none of these values implies another.

`exitcode` is the observed legacy architectural x3/`gp` register, represented as
a native signed 32-bit integer. `run_checked()` returns **void**. A successful
run may observe `7`, `-1` or another valid signed register value. Admission uses
`real_call_entered=true`, `completed=true`, `exception=false` and the existing
successful public completion/API observations. It never invents an integer
status returned by the checked call or interprets a nonzero register as failure.

## Run, reset and read ordering

Let `R` be the observed construction/opening reset generation. It must be a
bounded integer for which `R + 33` is representable. Construction and the opening
snapshot agree exactly, including the actual pending balance.

For each ordinal `j` from 1 through 33:

1. Capture the owned, quiescent before-state and zero pending balance **before**
   invoking the real reset-bearing call. Reject a nonzero balance at this point;
   do not let the real reset clear it and then report a successful run.
2. Observe before-reset generation `R + j - 1`, then exactly `R + j` after the
   returned real call. Require zero pending balance and a quiescent owned model
   afterward. Missing, duplicate, reordered, skipped or extra resets fail even
   if aggregate counts and endpoint observations are repaired.
3. Both `dcr_reads_before` and `dcr_reads_after` equal `66` for the prime
   (`j=1`), or `131 + j` for `j>=2`. Both cache-flush counts equal `j - 1`.
   This binds the run between the already verified DCR events and proves that
   no raw host read or output flush occurred inside that recorded call.
4. The matching flush is sequence `67` for the prime or `132 + j` afterward.
   Its original completed-run count equals `j`; its reset generation is
   exactly `R + j` on both sides. Both pending observations are zero, with
   successful original response/status, stable ownership and no reset.

The platform clock resets at each launch reset. It is not globally monotone.
On this direct-RAM route, host transfers and counter queries do not tick the
model. Require the first run's before-state to equal the opening state,
run-after ticks to equal flush-before ticks, and flush-after ticks to equal
the next run's before ticks. Flush-after ticks may exceed flush-before ticks.
The core is already drained, so the other model fields remain unchanged across
that flush and between runs. Match the prime/final snapshots exactly to the
corresponding post-flush states, and require after-batch and before-release
states to agree. Core cumulative counters must not decrease during each real
run; the complete 40-component source argument remains separate.

The four snapshot reset generations are exactly `[R, R+1, R+33, R+33]`.
Each before/after pair is equal, including zero pending balance, and its model
projection equals the corresponding v1 observation. All raw MPM and flush
supplements match their original sequence and require zero pending balance on
both sides. The validated v1 records retain the exact selector/class/reset/clock,
response halves and success checks. The new sidecar does not replace them.

## Terminal ownership, destruction and failures

The existing terminal vector follows all operations and owner cleanup. Its
validated original evidence requires one device reference, no live queues or
buffers, an enabled command processor and successful retirement. The relevant
source paths still must establish queue-worker join and final-reference behavior;
an API success alone cannot substitute for that source reasoning.

The final snapshot and the state immediately before the actual processor
destructor are exactly equal, including pending balance, clock, reset generation,
owner, core counters and legacy register. New work, a tick, a flush or reset after
that terminal state invalidates the lifetime. Completed disposal is recorded
after the real destructor returns. Only the still-live platform is inspected
then: its clock may be zeroed by cleanup, its reset generation must be unchanged
and it must be idle. Never inspect destroyed processor storage. Cleanup cannot
rehabilitate an earlier nonzero pending balance or failed run.

The trace has capacity 33 and records one slot per attempted run. Exhaustion
sets a violation/overflow observation and fails before another real run.
`trace_overflow` must be false for admission. Real exceptions and unsuccessful
upstream completion/API results remain failures. Available after-state may be
retained on a failure, but a secondary observation failure must not replace the
original exception. No successful sidecar is emitted for an incomplete or failed
process, and a fresh replacement process cannot repair that process's evidence.

## Required controls and remaining qualification boundary

Compiled host controls exercise the actual wrappers with controlled real-call
implementations: a nonzero pending balance must reject before a reset-bearing
call erases it; nonzero legacy `gp` success remains valid; real exceptions,
observation failures, overflow, wrong ownership and post-terminal changes fail
without losing the original error. A separate native probe must observe actual
request/reply transitions, including a nonzero pending value and final zero,
while repeated accessor calls leave model state unchanged. An always-zero
accessor must fail that probe. Fault injection stays outside the admitted
measurement binary.

Reader controls alter every run/reset/pending/destruction boundary, including
coherently repaired surrounding records and favorable numerical results. Old v1
originals remain valid in their original reader and fail the lifetime reader for
missing observations. Independent review and a freshly emitted four-process
original are required before reporting a native lifetime-observation result.

All seven fields remain **false** in both the parent witness and sidecar:
`qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `phase_acceptance` and `performance_acceptance`. Both retain
the same three unresolved obligations, in the same order:
`all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance` and
`independent_complete_counter_qualification`.

Recorded boundary consistency alone does not discharge the full source/binary
binding needed by the [conditional 40-component argument](simx_counter_lifetime_v1.md).
Cached dependency identities and matching loader paths do not prove fresh
SoftFloat/Ramulator source-to-object/archive/library compilation. The separate
native accessor probe supplies no dependency provenance. Transcript validation
is also distinct from complete archive replay. No absolute no-wrap bound, warm
admission, performance result or new phase acceptance follows from this contract.
The unchanged warm-v1 blocker and P06-A02/A03 remain open.
