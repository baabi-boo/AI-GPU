# Wave 2 harness independent review

## Scope and identity

- Reviewer: `/root/w02_harness_review`, independent of the harness author.
- Base: `7455e008c1e001d3329e74fd55ffcd942592ec5f`.
- Reviewed every changed hunk of `tests/unittest/checked_counters/main.cpp` in the working tree.
- Reviewed main.cpp SHA-256: `a4a5ed88b75730222e8f7977f23232ac276ff5360e9c7edd7d8db4bf196580ee`.
- Read the code-review and simx-review skills, AGENTS.md, C++ and Verilog coding guidelines, bug-fix discipline, review policy, SimObject design, and SimX architecture.
- Supporting reads: current counter_access selector table/interface, frozen ai_bench_common/counters.h inventory, AsyncRun, Core DCR and CSR routing, Cache aggregation, and TcuTbuf/TcuUnit aggregation. Access-wrapper implementation and its compile/link integration are a separate review; they were still being authored during this review.

## Findings

No F1, F2, or F3 defect found in the reviewed harness diff. The following F0 observations record what static review establishes, without representing native execution as passed.

### F0 high static-proof — exact inventory and independently reconciled counts

At main.cpp:217-257 and counter_access.cpp's selector table, all 33 available `(name, performance class, CSR)` tuples match the frozen 45-row inventory in order after removing its 12 unavailable L2/L3 rows. A read-only Python comparison confirmed exact tuple equality. The backing inventory is 26 single-component selectors plus 7 two-component selectors: 40 distinct components. Six D-cache fields and TCU local-memory reads receive two independent component passes each.

Each of 40 components receives all ten boundary values while every other selected source is zero. Each two-component selector additionally receives `0xffffffff + 1` and `(UINT64_MAX / 2) + (UINT64_MAX / 2 + 1)`. Thus 400 component vectors + 14 split vectors + 33 reset transports = 447 transports. Each transport makes four half reads and 14 counted checks. Together with 40 initial-zero checks, 40 retained-storage checks, and 51 aggregate checks across 17 fields, this is exactly 1,788 half reads and 6,389 checks. The result schema's literal inventory counts agree with the executed loop structure.

### F0 high static-proof — sentinel, nonaliasing, and reset coverage

At main.cpp:181-189, every half read initializes its output to the complement of the expected value, checks DCR success, exact half value, and class restoration. Both low/high and high/low read orders are exercised. At main.cpp:221-236, component pointers must be nonnull and pairwise distinct and have the expected per-selector cardinality.

At main.cpp:260-275, each component is seeded independently, a real processor reset is invoked, all 40 retained values are checked directly, and all 33 selectors are transported again. Read-only arithmetic verified that every reset selector total is distinct and below UINT64_MAX. This supplies nonzero, nonalias sentinel coverage after reset in addition to the isolated boundary passes. The largest aggregate total cannot overflow merely from the chosen reset seed.

### F0 high static-proof — real backing overflow and terminal containment

At main.cpp:424-479, both new scenarios obtain real selected backing components, seed max plus one, and call Processor::dcr_read through AsyncRun::invoke. The D-cache path reaches Cache::perf_stats bank addition; the TCU path reaches TcuTbuf::reads checked addition through TcuUnit::perf_stats. The exception must be PerfCounterError with the exact overflow reason and diagnostic. Both backing values and the DCR output sentinel must remain unchanged.

The eight terminal observations are two waits, check, busy, wait_for, rejected start, rejected invoke, and post-join check. Both task bodies remain unexecuted. Failed AsyncRun and Processor lifetimes end before check_fresh_context constructs a replacement, launches a real three-instruction architectural witness, verifies exit code 7 and positive production counters, and joins. The reported fields retain public_runtime=false and warm_execution=false. The boundaries result retains full_warm_coverage=false. The three pre-existing negative scenarios and their schema-1 output remain unchanged.

### F0 high missing-test — linked execution remains open

Native build/link/execution was not run by this reviewer, per task scope and available resource budget. Static calculations and source review do not establish that the final diagnostic object substitutions link, that the model runs, or that the final runner accepts the real emitted schema. Before claiming linked diagnostic success, run the reconfigured final normal and checked builds, both boundary modes, the three retained negative cases, and the two new backing-fault cases. Retain their real outputs and final source identity. Final access-wrapper/build integration, runner/replay parsing, and public runtime diagnostics require their assigned independent reviews.

## Checks actually performed

- `git diff 7455e008c1e001d3329e74fd55ffcd942592ec5f -- tests/unittest/checked_counters/main.cpp`: every changed hunk reviewed.
- Read-only Python extraction/comparison of selector tuples: 45 canonical total, 33 expected available, 33 actual, exact order/classes/CSR names equal.
- Read-only Python inventory/arithmetic check: 40 sources, 7 two-source selectors, distinct nonoverflowing reset totals, 1,788 reads, 6,389 assertions.
- Native builds/tests: **not run** by this reviewer.
- No repository file edits, index mutations, commits, checkout/reset, or pushes performed. This review note is the only written artifact.

## Classification and verdict

The isolated test-file path has the policy's R1 path classification; the integrated change includes build and CI evidence-consumer changes and should be reviewed as R3 for its externally consumed diagnostic schema. This independent review applies R3 depth to the harness. The classifier accepts committed ref pairs only; the final integrated committed range must be classified by the integration owner.

**Verdict: no harness source changes requested; land after the listed final integration checks and independent companion reviews.** This is a static review approval of the scoped harness, not a claim of native execution, warm readiness, phase acceptance, or performance qualification.
