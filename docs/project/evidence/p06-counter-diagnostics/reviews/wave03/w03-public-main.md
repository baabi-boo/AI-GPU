# Wave 3 native public counter harness

Owned and changed only `tests/unittest/checked_counters/public_main.cpp`.
Final source SHA-256: `b5285920e318bb8ea1752f57b675ba3fef356b52075f3e5950d2f7e3665eb825`.

## Implemented diagnostic cells

- `normal`: two separate real public-runtime contexts execute the three-instruction scalar program. Each context uploads and reads back exactly the original three code words through public DMA, executes through the public queue and real checked model, observes architectural gp=7 and positive actual counters, then performs the terminal diagnostic.
- `coherent-terminal`: the same actual scalar witness precedes test-only seeds of all 40 real backing components. The first terminal observation validates all 33 public 64-bit queries against those values; the second context is fresh and unseeded.
- `immediate-overflow`: actual core cycles seeded to UINT64_MAX, then an actual queued native run must reach the real checked updater, retain the saturated destination, retire no instruction, and surface a typed error through the unchanged runtime.
- `delayed-overflow`: actual cycles seeded to UINT64_MAX-2. Real ticks and two successful counter increments must precede the typed overflow; no retired-instruction progress is claimed.
- `cache-overflow`: an actual successful scalar run precedes seeding the two actual D-cache read components to UINT64_MAX and 1. A public low-half query must reach the actual cache aggregation, retain its output sentinel and both component values, then poison the backend.

Every negative cell verifies repeated timeline waits, higher-value waits, multi-event waits, queue-local error consumption, suppressed public DCR and DMA operations, suppressed queries, and a rejected native launch from a newly created queue. Five later requests must leave actual model entry counts unchanged. The JSON retains query return codes and destination values as well as the model entry counts before and after those attempts.

## Terminal and lifetime observations

The test releases and joins its queues, releases every event and program buffer, requires the internal real Device reference count to be exactly one, and checks its actual registered queue and buffer sets are empty. A deliberately added Device retain makes the same ownership predicate reject terminality; releasing that retain restores exclusive ownership.

Before and after all 33 public queries, the CP remains enabled, has neither busy nor error status, has retired the runtime's exact expected sequence, and has head equal to tail. Thus disabling the CP cannot create a false drain certificate. The 66 actual model DCR calls must be exactly the low/high tag sequence for the frozen `ai_bench_common/counters.h` inventory. All 12 L2/L3 entries must be capability-disabled and receive no query. Each half must preserve the model tick/reset generation and counter class, return the expected word, and reconstruct the actual component sum. All 40 backing values must remain unchanged through the terminal snapshot and the actual pre-destructor observation.

The wrapper's actual Processor destruction must finish, clear platform ticks and leave it idle before any fresh context opens. Failed-context state is also compared to its actual pre-destructor observation. The test introduces no production API, class-definition change, access-control flag, model replacement, or warm qualification authority.

## Result schema

One success line begins `COUNTER_PUBLIC_RESULT ` with schema_version 1. Five exact mode names above. All modes require two actual constructors, two actual destructors and two run entries; async modes have one run completion and one run error, other modes have two run completions. Cache overflow has one DCR-read error. Every negative mode has exactly one typed overflow. Unexpected errors, ownership violations and underflow/negative-operand errors are forbidden.

The JSON contains terminal snapshots (two for normal/coherent, one fresh snapshot for negative cells), actual model before/after state, all 40 components, all 33 public rows with both raw half traces, before/after CP states, and actual destruction traces. Negative records retain the triggering model states, the cache query's raw failure result (null for async), suppressed-request model-entry counts, and both repeated failed query destinations. `program_words_verified=6` counts three code words read back in each of two contexts; it is host-transfer evidence, while gp=7 is the native execution witness. It is not GEMM or matrix numerical evidence.

`qualified`, `ready_for_warm`, `warm_execution` and `acceptance_claimed` remain false.

## Validation and scope

The build author ran the public main's actual emitted compiler flags from a fresh configured RV64 p02-tfr checked tree, replacing only compilation/output and dependency side effects with `-fsyntax-only`; the first complete implementation passed. A final repeat after the raw-query evidence and DMA lifetime amendments was requested. The exact receipt is `w03-public-main-build-syntax.log`.

`git diff --check` passed. No full native link or execution was attempted locally, preserving the 15 GiB reserve. Hosted native execution and independent review remain required. No commit or push was made by this agent.

The source-bound diagnostic proves only its own scalar caller, serial ownership, direct-RAM route and checked backend. It does not prove the full warm workspace caller, a seed-free measurement artifact, arbitrary concurrency, LLC/VM operation, high-half failure injection, RTL parity, GEMM correctness, or lifetime qualification for other callers.
