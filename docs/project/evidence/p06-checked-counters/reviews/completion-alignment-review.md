# Independent completion alignment review

Reviewer: `/root/w03_a06_completion_alignment`, wave 3 assignment 6.
This is the root coordinator's retained transcription of that agent's
read-only review. The reviewer performed no edits, builds, tests or publication.

## Reviewed state and verdict

The source checkout had incorporated upstream
`89aa43236038fcfff5d36a7cdb95646b038fe2fb`. The reviewed counter candidate still
used fatal process abort. It was not committed or published.

**R3; land only after failure-path correction, updated evidence and fresh
independent review.** The checked arithmetic remains a useful bounded
prerequisite. The abort candidate cannot satisfy the updated qualification
plan's persistent processor failure and cleanup obligations.

## Findings

### F2: fatal abort bypasses the supported completion route

`PerfCounter::fail()` called `std::abort()` instead of using the
processor-origin terminal failure boundary. Overflow during a tick or a DCR
aggregate would bypass asynchronous exception collection, repeated public
wait/query errors, explicit close, destruction and full-platform cleanup.
The supervisor could reject the process, but this was insufficient for the
selected qualification route.

The smallest correction is a dedicated typed exception thrown before the
affected counter changes. `Processor::run_checked()` carries asynchronous
exceptions to `AsyncRun`; guarded synchronous processor hooks use its
`invoke()` path. Both retain terminal failure and suppress later work.
Replace expected-abort tests with typed-error and containment checks. Keep
actual native public wait/query evidence open until it executes.

### F1: asynchronous-failure rationale became stale after upstream integration

The header, design contract and development audit described wait-only futures
as current behavior. That observation applied to the initial `42809ff` source.
The integrated completion code consumes futures with `get()` and retains
synchronous processor-origin errors too. Record the original observation as
historical and test the replacement independently; earlier abort probes cannot
be relabeled as exception-path evidence.

## Exception boundary inspection

The reviewer inspected Core, LSU, cache, local-memory, coalescer, Processor
memory callbacks/latency, crossbar and tensor-buffer update paths. In the
supported serial timing route, these operations and the inspected serial
dispatch wrappers permit exception propagation. No inspected model destructor
performed guarded arithmetic. Full-platform cleanup discards abandoned events
and ownership without replaying counter mutations.

The exception can hold an enum or static literal and avoid constructing a
dynamic diagnostic string. This does not prove allocation-free C++ exception
runtime machinery.

Partial ticks and aggregates remain invalid after a fault; a successful join
or cleanup cannot rehabilitate a failed completion owner. Same-thread direct
tick reuse, multiple model workers and the legacy catch-and-return processor
entry remain outside the qualification route.

## Required replacement evidence

- Exact typed reasons, unchanged rejected primitive values and retained
  release/carry/maximum/ordinary-alias tests.
- Actual `AsyncRun` asynchronous and synchronous sticky failure, suppressed
  later work, safe join and fresh independent owner success.
- A linked native fault from an actual updater through `run_checked()`, full
  failed-context disposal and a separately created normal context.
- Separate scopes for helper transport, linked native failure and actual
  public runtime error integration; no all-33 transport or warm-readiness
  claim from nineteen directly seeded selectors.

## Historical source identities

| File | SHA-256 |
|---|---|
| `sim/common/perf_counter.h` | `4baebbb566bbc628ecdd48ef5c6987b6c154fce68e202c14ba03e60d81386488` |
| `docs/designs/simx_checked_counters_v1.md` | `e7dacbfd316764f63b91cde710e06534387db20a152e6bd27bcbecadbb2bd13c` |
| `docs/project/p06-checked-counters-audit.md` | `c1e1aea039596c969cb24f0675ea392cebd1b88f1ad63016bbfde4ad70952ebd` |
| `sim/simx/processor.cpp` | `569cf629d1e25ec9a295b20bfadfabbe21cd0989127f2b825fceee99a8062b78` |
| `sw/runtime/common/async_run.h` | `a9f63b2a896c5e512f7c592c758618ea88b774c9dac4bca29e847e2e3719a24e` |
| `sw/runtime/simx/vortex.cpp` | `0d890c95fecb67da26d23ea4a0af10ac328dddf110cd2575baff3aa5d4c905cb` |

These identify the rejected candidate and its upstream completion boundary.
They are not approval hashes for the later replacement.
