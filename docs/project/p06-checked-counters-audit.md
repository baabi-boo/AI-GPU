# P06 checked counter development audit

## Starting point and selected work

This continuation starts at `42809ff0c1b81384d7c9b079e4ef786be8407600`
on `master`. The host MPM transport repair is present, while the historical
warm-v1 analyzer deliberately rejects full qualification. The
[qualification plan](p06-mpm-qualification-plan.md) identifies the next
dependency: establish the actual counter route, its arithmetic lifetime and
source/build binding before interpreting a fresh warm experiment.

Independent source audits found 33 available counters and twelve unavailable
L2/L3 rows in the frozen RV64 `p02-tfr` experiment. The available counters
retain cumulative statistics across launches. Repairing high-word transport
does not prove that those statistics, their contributing counts, or their
aggregate sums never overflow. A process timeout, small reported value or
monotonic observation cannot supply that proof.

The selected implementation is an opt-in checked accumulator used at the
actual SimX storage and aggregation sites. This is a concrete prerequisite
for the versioned qualification layer, with a distinct
[implemented contract](../designs/simx_checked_counters_v1.md). It does not
change the frozen warm-v1 decision or accept P06-A02/A03.

## Findings and decisions

| Finding | Evidence | Development decision |
|---|---|---|
| Unbounded cumulative unsigned arithmetic | Core, cache, local-memory, coalescer, memory and TCU counters use 64-bit storage across launch resets | Guard additions and increments before overflow in an explicitly instrumented build |
| Aggregate overflow can precede a public read | Cache sums, CSR coalescer sum, TCU buffer sum and memory crossbar source | Cover underlying storage and intermediate additions, not only returned values |
| Pending read underflow can corrupt latency | Request/response callbacks in `processor.cpp` increment/decrement an unsigned pending count | Check the contributing pending count, including subtraction |
| Initial asynchronous completion defect was fixed concurrently | At the starting revision some future waits lost exceptions; integrated upstream completion commits consume futures and retain processor failure | Use a typed counter exception through `run_checked()` and guarded synchronous queries; reject the initial abort design |
| Standalone interpreter identity is missing | Transport runner records PATH Python but can execute under another interpreter | Retain `sys.executable` separately in tool snapshots and drift checks |
| Directed transport scope differs from warm scope | Existing native transport matrix disables TCU; only selected CORE values are seeded | Preserve that evidence's scope; require separate warm-profile coverage |

A lifetime tick cap was considered and rejected for this slice. It would need
independent event-rate and occupancy bounds for every selector, plus a count
that survives platform resets. Checked arithmetic instead establishes the
invariant by induction at every contributing addition: a fully instrumented context whose guarded operations all complete normally
has not performed an overflowing guarded addition. Reset meaning, source coverage, coherent reads and actual execution
remain separate review obligations.

## Integrated upstream development

While this audit was active, `master` advanced through the simulator completion
repair, its CP error-origin correction and source-bound evidence to
`89aa43236038fcfff5d36a7cdb95646b038fe2fb`. These changes were fast-forwarded
into the checkout before continuing implementation. The original asynchronous
exception finding is historical; the selected route now consumes futures with
`get()` and preserves terminal processor failure.

An independent review rejected the initial fatal-abort counter candidate
because it bypassed persistent public failure and full-platform cleanup. The
replacement throws `PerfCounterError` before mutation, uses the existing
completion boundary and retains ordinary unsigned behavior when instrumentation
is disabled. Earlier abort-oriented probe results apply only to that discarded
candidate; they are not evidence for the replacement. Fresh tests and review
are required. Actual public runtime counter-fault integration remains a
separate qualification obligation.

## Preserved boundaries

Ordinary builds retain the `uint64_t` alias. The new option affects instrumented
host execution cost; it is not a hardware optimization or an uninstrumented
latency measurement. Both policies in a future matched experiment must use
the same identified instrumented binary. Historical receipts do not acquire
the new guarantees retroactively.

The frozen workloads, reference fixtures, statistical predicates, budgets,
goldens, acceptance records and warm-v1 block remain intact. The inherited
tensor 267-to-283 DSP failure, vendor XRT `hw_emu` requirement, P05 review
obligations and physical FPGA/silicon gates remain separate.

## Execution and publication record

The final evidence index records actual host tests, hosted executions,
independent reviews, completed agent assignments and the published revision.
This audit is not an execution receipt. Local formal native work is constrained
by the preserved 15 GiB disk reserve; small host tests use their separate
resource contract. A hosted result must name its actual source revision and
configuration before it supports a claim.
