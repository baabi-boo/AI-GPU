# Wave 1 selector audit

Audited checkout: `7455e008c1e001d3329e74fd55ffcd942592ec5f`. Audit only; no production edits, builds or commits. Read AGENTS, the current qualification plan, acceptance policy and code-review policy.

## Conclusion

The missing fourteen selectors have real, already checked backing storage. There is no need to add a production API or test-hook macro. Use a diagnostic-only, typed source-inclusion seam for the implementation-private objects, and verify all aggregate contributors rather than seeding temporary `PerfStats` return values.

Recommended implementation: four test translation units each include one unchanged production `.cpp` and append a few typed accessors. Compile these four units with GCC `-fno-access-control`; the local compiler advertises `-faccess-control` as the access-check flag. Only the diagnostic target substitutes these wrapper objects for the corresponding ordinary objects. All production methods, class definitions and layouts remain unchanged. A fifth small test TU can access the private `ProcessorImpl` fields using its existing complete header. There is no pointer arithmetic, assumed object layout, `#define private public`, or installed/runtime symbol.

This compiler option belongs only to diagnostic objects. The runner must explicitly admit it only for an exact allowlist of retained wrapper sources and reject it in ordinary model objects. Keep test seeds out of the benchmark/runtime measurement binary.

## Exact source map

| Required selector | Real backing storage | Route to published value |
|---|---|---|
| `icache_reads` | `CacheBank::perf_stats_.reads`, one bank | `Cache::Impl::perf_stats` → `CacheCluster::perf_stats` → `Socket::perf_stats` → CSR |
| `icache_miss_r` | `CacheBank::perf_stats_.read_misses`, one bank | Same |
| `icache_mshr_st` | `CacheBank::perf_stats_.mshr_stalls`, one bank | Same |
| `dcache_reads` | `CacheBank::perf_stats_.reads`, **two banks** | Same chain for D-cache |
| `dcache_writes` | `CacheBank::perf_stats_.writes`, two banks | Same |
| `dcache_miss_r` | `CacheBank::perf_stats_.read_misses`, two banks | Same |
| `dcache_miss_w` | `CacheBank::perf_stats_.write_misses`, two banks | Same |
| `dcache_evicts` | `CacheBank::perf_stats_.evictions`, two banks | Same |
| `dcache_mshr_st` | `CacheBank::perf_stats_.mshr_stalls`, two banks | Same |
| `memory_reads` | `ProcessorImpl::perf_mem_reads_` | `ProcessorImpl::perf_stats` → CSR |
| `memory_writes` | `ProcessorImpl::perf_mem_writes_` | Same |
| `memory_lt` | `ProcessorImpl::perf_mem_latency_` | Same |
| `memory_bank_st` | `Memory::Impl::mem_xbar_->crossbar_->collisions_` (`TxCrossBar<MemReq>`) | `TxCrossBar::collisions` → `TxRxCrossBar::collisions` → `Memory::perf_stats` → processor → CSR |
| `tcu_lmem_reads` | `TcuTbuf::Impl::bufs_[i].reads_`, **two buffers** | checked `TcuTbuf::reads()` sum → `TcuUnit::perf_stats().lmem_reads` → CSR |

Relevant locations: `sim/simx/mem/cache.cpp:816,874,2291,3472`; `cache_cluster.cpp:83`; `socket.cpp:42,454,547`; `processor_impl.h:119`; `processor.cpp:205,211,344,433,449,546`; `mem/memory.cpp:41,76`; `types.h:1696,1720,1736,1784,1986`; `tcu/tcu_tbuf.cpp:40,72,106,194`; `tcu/tcu_unit.cpp:1298`; `csr_unit.cpp:171–250`.

## Accessor organization

Put a small typed interface entirely under `tests/unittest/checked_counters/`:

- Socket wrapper includes `sim/simx/socket.cpp`; returns I/D `Cache*` values through `socket.impl_->icaches_/dcaches_->caches_`. Require the exact one-cache topology at runtime.
- Cache wrapper includes `sim/simx/mem/cache.cpp`; returns pointers to the actual bank-owned `PerfCounter` fields for a `PerfCounter Cache::PerfStats::*` member. `CacheBank::perf_stats()` returns a const reference to mutable non-const storage, so a local `const_cast` is valid; private `Cache::impl_->banks_` requires the diagnostic access flag. Require one I-cache and two D-cache banks.
- Memory wrapper includes `sim/simx/mem/memory.cpp`; returns the collision accumulator pointer through `memory.impl_->mem_xbar_->crossbar_`. Require the pointer to exist; never replace absent source with fabricated storage.
- TCU wrapper includes `sim/simx/tcu/tcu_tbuf.cpp`; returns pointers to both `impl_->buf(i).reads_`. `core.tcu_unit()->tbuf()` already exposes the actual buffer owner.
- Processor-access TU includes complete `processor_impl.h` and `core.h`; obtains `ProcessorImpl` through the existing `core.socket()->cluster()->processor()` path, returns the three fields and `memsim_` for the memory accessor.

The model's cardinal rule remains intact: no production SimObject accesses are added. These accessors are external diagnostic seed code.

## Diagnostic coverage to require

1. Replace the one-pointer selector representation with a list of actual component pointers, with expected component counts. Bind the exact 33 names/classes/CSRs/core 0 from the frozen manifest; the 12 unavailable L2/L3 rows remain unqueried.
2. Run existing ten independent numeric vectors, including both 32-bit carry and values above 44 bits, through both half orders for **all 33** selectors. Verify MPM class restoration and successful status on every half.
3. For each six D-cache selectors and TCU local reads, seed each component individually and then nontrivial splits summing to the expected value. At minimum use `(0xffffffff,1)` and `(UINT64_MAX/2,UINT64_MAX/2+1)`. A bank-0-only seed cannot prove bank 1 or aggregation transport.
4. Give every non-target selector a safe unique sentinel to catch selector aliasing. Do not inadvertently overflow a different aggregate: CSR reads can build complete processor/socket statistics before selecting the requested field.
5. Read actual DCR values after `Processor::reset()` and verify cumulative source preservation. Check all component origins are zero before seeding. Do not claim the pending balance is cumulative: `perf_mem_pending_reads_` explicitly resets to zero and requires separate request/response proof.
6. Inject `UINT64_MAX + 1` across the **actual D-cache banks** and through the **actual two TCU buffers**, then query through real `Processor::dcr_read` under the real `AsyncRun::invoke` boundary. Check `PerfCounterError` and persistent terminal state. Existing `cache_overflow()` merely creates standalone `Cache::PerfStats` objects; it does not exercise the actual native cache ownership/CSR route.
7. Keep source/transport coverage distinct from updater coverage, terminal lifetime, public-runtime failure, warm readiness and RTL parity. A new all-33 transport result may set a narrowly named `all_available_selector_transport=true`, while `qualified=false`, `ready_for_warm=false` and `warm_execution=false` remain mandatory until their separate obligations pass.

If the existing `full_warm_coverage` key is retained, avoid silently redefining it. A new schema/version or explicit new result key is clearer; all-33 transport alone is not full warm qualification.

## Runner/build obligations

`sim/simx/checked_counters.mk` currently links `$(OBJS)` with the harness. The diagnostic target should filter the four original objects and link exactly the four wrapper replacements plus the processor-access helper. A wrapper includes only its nominated original production `.cpp`, which remains in the retained source snapshot and dependency record.

`ci/project/p06_checked_execute.py:verify_build_log` currently requires direct compilation of `cache.cpp` and `tcu_tbuf.cpp` and exact stamp flags for every TU. Extend this to a fixed wrapper→included-production-source map, preserving exact object/link inventory and forbidding both a wrapper and its original object in one link. Record actual compiled wrapper paths and included production bodies separately; do not relabel them as direct compilation. Ensure all wrapper headers/sources enter `CRITICAL`/source snapshots (the current snapshot includes `tests/.../main.cpp` only through that explicit list). Update fixture `MODEL_SOURCES`, source-drift checks and malformed-record tests accordingly.

Native builds should run through the hosted bounded workflow because local free disk is below the unchanged 15 GiB reserve. Host unit tests can verify command generation, flags, topology rejection, exact output schemas, bad component counts, omitted/repeated selectors, and rejected aggregate-failure transcripts.

## Findings and limits

- F2/high/static-proof, current qualification gap: nine cache outputs are copies, processor fields are copied, and memory/TCU derived fields are overwritten on read. Casting a returned aggregate or seeding `TcuUnit::PerfStats::lmem_reads` cannot establish true source transport. The proposed wrappers address the gap at actual storage.
- F1/high/static-proof: `TcuTbuf::reads()` header comment says “since the last reset”, but buffer reset preserves `reads_` (the source is context cumulative). Correct that comment with the eventual source review.
- No missing check was found in the fourteen stored/formed-value paths: their actual source fields use `PerfCounter`, D-cache and TCU sums use checked accumulation, and their cumulative resets preserve them. This is source inspection, not a terminal lifetime proof or native execution result.
- D-cache port-arbiter `collisions_` remains plain `uint64_t` and resets, but `dcache_bank_st` is **outside** the selected 33. Do not accidentally expand scope to it while iterating all `Cache::PerfStats` fields. Global-memory `memory_bank_st` is the different checked `TxCrossBar` source.
- The SimX MEM bank-stall selector still has no corresponding RTL MEM decode case. All-33 SimX transport cannot establish all-33 RTL parity.
