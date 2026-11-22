# Wave 2 independent review: backing-counter access and build

Reviewer: `/root/w02_access_review` (did not author the reviewed code).
Base: `7455e008c1e001d3329e74fd55ffcd942592ec5f`.
Scope: six new test accessor files and the complete changed hunks of `sim/simx/checked_counters.mk`; current working-tree contents identified below.

## Verdict

**No F1, F2, or F3 findings in this scope. R2; land from the accessor/build static-review perspective.** Native linking and execution are **not run** and remain necessary before claiming these directed diagnostics passed. The complete implementation still needs its final commit classification and reviews for runner/contract changes outside this scope. This report grants no waiver and does not establish warm qualification, parity, or hardware evidence.

Read the repository `code-review` and `simx-review` skills, AGENTS, review policy, C++/Verilog coding guidelines, bug-fix discipline, and both SimObject/SimX architecture documents. The classification here is manual: this is a test seam and diagnostic build change with no installed ABI, production flag, timing behavior, gate-threshold, or golden-data edits. The commit-only classifier cannot yet classify these uncommitted/untracked changes; the coordinator should classify the final commit.

## Storage and topology

Confirmed the complete 33-selector map against `tests/regression/ai_bench_common/counters.h` and the matching branches in `sim/simx/csr_unit.cpp`. Its 40 cumulative source fields consist of 26 single-component selectors, six selectors with two data-cache banks each, and one selector with two tensor buffers. The separate pending-read balance is not counted as a cumulative selector.

- Core's 13 fields use its actual mutable `PerfStats` reference. LocalMem's three fields, MemCoalescer's misses, and TcuUnit's two direct fields use references to actual non-const backing objects; the const casts do not cast away constness of a const allocation.
- I-cache selectors reach the attached socket's instruction-cache cluster, its sole Cache, and its sole `CacheBank::perf_stats_`. D-cache selectors reach the corresponding data-cache cluster, sole Cache, and both real bank statistics. `Cache::Impl::perf_stats()` sums precisely those bank fields; the selected list excludes `dcache_bank_st`, whose source is a different arbiter.
- The three global memory totals and pending balance address the actual `ProcessorImpl` members. Memory bank stalls address `Memory::Impl::mem_xbar_->crossbar_->collisions_`, the request crossbar's actual `PerfCounter`, rather than `Memory::PerfStats`' derived snapshot.
- Tensor reads address `TcuTbuf::Impl::buf(0).reads_` and `buf(1).reads_`, which `reads()` sums. They do not seed `TcuUnit::PerfStats::lmem_reads`, which the production getter overwrites. Inventory creation calls that getter while the tensor sources are still healthy; the harness must retain inventory before poisoning, as the separately reviewed harness does.
- Compile-time checks restrict the diagnostic to RV64 serial timing, one cluster/core/socket, four warps and threads, one issue/LSU/TCU block, enabled I/D/local memory, exact one/two I/D cache banks, and no VM/L2/L3/WGMMA. Runtime checks require attached owners, one cache in each cluster, non-bypass caches with the exact bank vector sizes, two memory-crossbar outputs with an actual request crossbar, and two tensor buffers. No pointer is manufactured for a missing or bypassed component.

## Access, translation units, and flags

The C++17 explicit-instantiation seam yields typed member pointers; there are no offsets, object-layout guesses, reinterpret casts, private/public preprocessor rewrites, production friends, or production class edits. Each tag is unique to its translation unit, and the shared template has one consistent header definition. The code does not disable access checks, which would interfere with SimObject's protected-hook detection.

The socket/cache/memory wrappers include the corresponding unchanged production `.cpp`. Their four replaced object names (including TCU) are removed only from the diagnostic link list. Production `SRCS`, `OBJS`, targets, and `CXXFLAGS` remain unchanged. The diagnostic adds five accessor objects and its existing main, for 45 translation units in the supported configuration. No production model file or `sim/simx/Makefile` differs from the base in this reviewed snapshot.

TCU uses the exact unchanged production body followed by one LF and the test footer, compiled as the main source file. This avoids changing warning policy when GCC diagnoses the anonymous Buffer member in include context. The footer is appended after the complete production body; it adds no macro/class mutation. Only that generated object supplies the production TCU definitions to the diagnostic link.

## Dependency and rebuild verification

Independently ran a bounded configured-tree/preprocessor/Make probe; **PASS**. Receipt: `/workspace/scratch/98908dfa3444/w02-access-review-probe.log`.

- Configured a temporary RV64 `p02-tfr` tree with `PERF=1`, ordinary mode, and `/usr/bin/g++`; no native object compilation or link was attempted.
- Ran the actual generation recipe and verified exact `tcu_tbuf.cpp + b"\n" + access_tcu.cpp` bytes.
- Ran the compiler dependency preprocessor (`-MM`) using flags extracted from the actual Make dry run. It discovered 26 dependencies, including the intended source-tree `counter_access.h` and `tcu_tbuf.h`. The footer's relative helper include resolves through the existing `-I<source>/sim/simx` path, without any additional include flag.
- With an empty placeholder target used only for Make freshness inspection, the unchanged target was up to date. `make -n -W` for original TCU body, footer, and source makefile each regenerated the combined source and recompiled its object. `-W counter_access.h` recompiled the object without unnecessary regeneration. The force-updated configuration stamp was explicitly held fixed during these dependency-edge probes.
- Other wrapper dependencies are normal compiler-generated `.d` includes; their source and shared header have explicit Make prerequisites, and included original `.cpp` files are recorded by `-MMD`. The generated TCU body's two source inputs are explicit prerequisites because textual concatenation alone would not expose them to the compiler's `.d` file.

Also inspected the author's retained evidence in `w02-access-validation.log`, `w02-access.md`, and `w02-access-records-results.json`: the final ordinary and checked runs passed syntax for all five access TUs under unchanged normalized production flags; Make dry runs had 45 compile records and one link with the four original objects absent; the runner's compiler-record parser accepted both modes and exact generated-source binding. Earlier access-control/include-context failures in that log belong to superseded implementations, not the hashed state below.

## Limits and open obligations

Native simulator linking, 33-selector execution, checked aggregation failure propagation, and clean-reopen runtime behavior: **not run by this reviewer**. The local disk budget and assignment explicitly excluded a native build. Those results must come from the separately authorized native execution stage. This review does not cover the runner's packet validation/retention rules, the harness in full, historical packet compatibility, or public-runtime diagnostic changes.

No repository files were edited; no commit, push, checkout, reset, stash, or clean operation was performed.

## Reviewed SHA-256 identities

| File | SHA-256 |
|---|---|
| `tests/unittest/checked_counters/counter_access.h` | `b0b1591ff79595dba77961460e3e0f946ddb5673a1a5eefbfdee274dae1aba5b` |
| `tests/unittest/checked_counters/counter_access.cpp` | `f687b107b27048b5cd6265911c872326996035f86dec10bc2917b84438205db7` |
| `tests/unittest/checked_counters/access_socket.cpp` | `33ddaa82618fa644489b7aad40bc193818908eb0eb34e65f5a5a27fdc2b7cf73` |
| `tests/unittest/checked_counters/access_cache.cpp` | `362d67fd919ec97ef90d6a8b45179886b1b19dc65d2165ee02627744a6771e5c` |
| `tests/unittest/checked_counters/access_memory.cpp` | `cf8e614d3e1fd197f849282a08bd68bed4012bbcfacd09edae9d564f19c233e0` |
| `tests/unittest/checked_counters/access_tcu.cpp` | `82625e07f4cfee0c7e4e55bd0a8aaef28a6ec9e9ab7064292fe11815e8a6ec7f` |
| `sim/simx/checked_counters.mk` | `5080bbe88f3c6612258932953ada6d7ac983617bbba56806f37d3ab488b9ae99` |
