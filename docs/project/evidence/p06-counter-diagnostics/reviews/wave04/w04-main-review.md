# Wave 4 independent review: public checked-counter main

## Verdict and exact scope

Reviewer: `/root/w04_main_review`, independent of the implementation author.
Repository HEAD: `407ab9fea5e4f793a2a5088f566a87f3e631aa84`.

Reviewed every line of the new 823-line `tests/unittest/checked_counters/public_main.cpp`, including all five modes and every printed result field, against the actual common runtime, SimX backend, command processor, decoder, model state, and diagnostic hooks. This review is source-level evidence. It is not a native execution or linker pass.

**One F2 missing-evidence finding remains: the DMA retry has no independent witness of suppressed RAM side effects.** No F3 finding was identified. The other requested boundaries are consistent with the inspected production source. Final landing remains contingent on the applicable native build/run and evidence checks; they were pending at review time.

The reviewed main SHA-256 is `b5285920e318bb8ea1752f57b675ba3fef356b52075f3e5950d2f7e3665eb825`. Its contents were unchanged when the final hashes were collected.

| Contextual file | SHA-256 |
|---|---|
| `tests/unittest/checked_counters/public_hooks.h` | `cb85ffb6df7151a3b9d747cfe243e464a3f16c4bd1063718b28af0800e86e95a` |
| `tests/unittest/checked_counters/public_hooks.cpp` | `c67ee622d159941d6c0ba3e759847cbe2fc463dcff9f9a989fd8dbf702ef434f` |
| `tests/unittest/checked_counters/public.mk` | `ce65fef47f9c977ef5cb7f40f2e6ece0c4975f1999c607f63d6f0fc72ce3882a` |
| `sw/runtime/common/device.cpp` | `9b32e38a9bbc0460a7f2af522fd5efdc96e1c06e359e28c5151285557f89d90a` |
| `sw/runtime/common/queue.cpp` | `1d785262d128de3ffbf1feb32cc2b32f6457a6644df6ef9a04d4e8b4d45c962e` |
| `sw/runtime/simx/vortex.cpp` | `0d890c95fecb67da26d23ea4a0af10ac328dddf110cd2575baff3aa5d4c905cb` |

Read AGENTS.md, the repository code-review and simx-review skills, both language coding guidelines, bug-fix guidance, review policy, the simulator architecture, and relevant SimObject lifetime/idle/reset sections. Read `w03-public-main.md`, the public-hook/build handoffs, and retained main syntax evidence. Review rules were applied to the whole new main, not only selected assertions.

## Findings

### F2 — Independently observe DMA side effects before claiming the retry was suppressed

**Confidence:** high for the evidence gap. **Evidence type:** `missing-test`, supported by a static source trace. **Location:** `public_main.cpp` 143–149 and 510–531, especially `failed_event(context.write_program())` at line 518.

`write_program()` always writes the same `kProgram` bytes to the same program buffer. After that rejected write, `suppressed_work()` checks only wrapped Processor run/DCR entry counts, typed overflow counts, and the 40 selected model counters. It never observes the program's backing RAM or the RAM write route. The direct-RAM backend used by this cell implements the device-memory branch of `dram_write` with `ram_.write(...)` in `sw/runtime/simx/vortex.cpp` 184–194. That write bypasses the observed Processor entrypoints. The queued request really does reach the common runtime's CP DMA path (`Queue::enqueue_write`, `Device::cp_submit_mem_write`), so this is the relevant memory boundary.

**Concrete failure this diagnostic cannot distinguish:** a failure-path implementation performs the requested direct-RAM transfer but still returns the expected error. The retry's event and repeated waits would remain erroneous, all recorded Processor-entry/counter comparisons could remain equal, and re-copying the existing program is invisible. The context is then destroyed and the fresh context receives separate RAM, so the later scalar success also cannot reveal that side effect. The JSON can therefore count this as a suppressed request without independent DMA evidence.

This finding does **not** assert that the present production `run_.check()` guards permit this fault: the inspected backend checks before CP transactions. It identifies an unobserved part of the new diagnostic's stated suppression contract, not an observed current production bug or a demonstrated native mutation test.

**Bounded remedy:** use distinct retry bytes and retain actual backing-memory before/after observations through a test-only accessor, or observe the real RAM write operation in the diagnostic build and require no write during the failed request. Keep the actual public enqueue, CP, backend, and model path. Record the raw evidence and check it in the validator. Error response alone should not be represented as independent proof of zero DMA side effects. Any additional checks will require updating the source-derived assertion totals below.

Parent was notified promptly before this report and accepted the finding for a bounded fix. The existing `Core::processor()` and `ProcessorImpl::ram()` accessors provide the actual RAM without another production wrapper; their declarations were checked. Parent plans to observe the three original words, attempt distinct words through the unchanged public DMA route, and observe the actual words afterward under the diagnostic mutex after model failure. A follow-up review must cover the raw before/attempted/after words, failure status, source/hash changes, assertion totals, and matching validator checks. No implementation was changed by this reviewer.

### F0 — Scalar execution and descriptor provenance are real

**Confidence:** high. **Evidence type:** `static-proof`.

The three words are an actual scalar `addi x3, x0, 7`, WSYNC, and TMC-to-zero program accepted by the production decoder. Production exit-code access reads that architectural register. Both contexts upload and read back the three words through the public runtime before execution; the native execution witness is the real architectural value 7 plus positive model cycles/instructions and an actual successful wrapped `run_checked` entry.

The harness manually writes the 19 required startup/KMU DCRs. Its launch descriptor has null kernel/arguments and zero dimensions, so `Queue::enqueue_launch` preserves those programmed descriptors and contributes no concealed descriptor writes. There is no fake Processor, substituted RAM, fabricated completion, or matrix-performance claim in this main.

### F0 — Positive terminal snapshots enforce caller ownership and CP retirement

**Confidence:** high. **Evidence type:** `static-proof`.

Successful event handles are released, queue destruction joins the worker, and buffers are released before `terminal_snapshot()` requires Device reference count 1 and empty queue/buffer sets. Its deliberate extra retain makes that exact ownership predicate fail, and releasing it restores the predicate. These checks occur before final Device release.

`terminal_cp()` requires CP-enabled state, global and queue controls enabled, no status/error bits, a nonzero expected sequence matching retired sequence, and the pulled head equal to the submitted tail. The 66 terminal half reads advance the real CP sequence by exactly 66, and a second CP observation re-establishes retirement. The code does not infer CP drainage from `cp_quiesce_` disabling the queue or from a failed teardown read.

There are no surviving queue workers that could race the private-set reads at this diagnostic's observation point. This remains evidence for this caller and ownership protocol, not arbitrary runtime callers.

### F0 — Counter inventory and raw-half checks match the sources

**Confidence:** high. **Evidence type:** `static-proof`.

The frozen manifest has 45 selectors: 12 disabled L2/L3 selectors and 33 enabled selectors in this build. Six D-cache selectors each have two banks and TCU local-memory reads have two buffers, yielding 40 actual components. Main checks names, classes, CSR selectors, capabilities, and component multiplicities instead of trusting a fixed total alone.

Every successful terminal public value is compared with the overflow-checked sum of the actual selected backing components. Each raw low/high DCR trace is checked for the exact class/CSR tag, generation, return status, overflow flag, word value, consecutive sequence, unchanged simulation ticks/reset generation, and class restoration. The source-derived half ordering agrees with `vx_device_mpm_query`, which stores the destination only after both halves succeed.

### F0 — Failure propagation and destructor/fresh-context checks cross real boundaries

**Confidence:** high. **Evidence type:** `static-proof`, subject to the DMA finding above.

Immediate and delayed cycle overflow originate in actual checked counter increments during real model runs. The delayed case requires positive intervening simulation progress. Cache aggregation failure uses the two actual D-cache read sources at MAX and 1 and invokes the real public MPM query. Its one failed raw DCR trace preserves the exception evidence, while failed public queries leave sentinel destinations unchanged.

Repeated waits at the completed value, zero-time waits, higher requested values, and multi-event waits all check the sticky error. The first queue finish consumes the queue-local asynchronous error and the second finish succeeds; a newly created queue still cannot revive the poisoned backend. Run and DCR entry counts independently show that later launch/DCR/query attempts do not re-enter those wrapped Processor operations.

Every failed or successful context ultimately releases the true final Device reference and records actual Processor destructor entry/completion. The pre-destructor state is compared independently from post-cleanup tick/idle observations. Only after real destruction is observed does the fresh public context execute the scalar program successfully. Exception-path best-effort cleanup cannot manufacture a PASS record.

## Independently derived fixed counts

These totals are valid for the exact reviewed main hash above. They are source-derived expectations, not observed native results.

| Contribution | Assertions |
|---|---:|
| Context construction | 90 |
| Inventory | 146 |
| Healthy model | 4 |
| Same-model comparison | 4 |
| Each CP terminal observation | 13 |
| Each half check | 5 |
| Successful resource close | 24 |
| Complete terminal snapshot | 714 |
| Successful context | 823 |
| Seeded context extra inventory | 146 |
| Suppressed-work checks | 40 |
| Failed async context | 336 |
| Failed cache context | 333 |
| Main and final result checks | 6 |

| Cell | Exact expected assertion count | DCR writes | DCR read entries |
|---|---:|---:|---:|
| normal | 1652 | 38 | 132 |
| coherent | 1798 | 38 | 132 |
| async immediate | 1165 | 38 | 66 |
| async delayed | 1165 | 38 | 66 |
| cache aggregate | 1162 | 38 | 67 |

The 38 writes come from 19 manual descriptor writes per context. Each successful terminal snapshot contributes 66 read entries. Cache aggregation contributes its one failing read in addition to the fresh-context 66; poisoned async contexts contribute no DCR reads. These calculations were sent to both the parent and `/root/w03_public_records`.

## Verification status and limitations

- **Run by this reviewer:** complete main/source trace, fixed-count derivation, final source SHA-256 collection, and examination of retained build/syntax evidence.
- **Previously run, retained evidence inspected:** the final main syntax probe in `w03-public-main-build-syntax.log` used the real emitted runtime compile flags from a fresh RV64 p02-tfr checked configuration, replaced compile/output side effects with `-fsyntax-only`, and ended `exit=0`. This reviewer did not rerun it or represent it as an independent native pass.
- **Not run here:** linking the combined backend/public executable, any of the five native public cells, mutation testing of DMA behavior, sanitizer tests, or the separate CI integration/validator suite. The shared environment lacked the required native disk reserve; no resource guard was weakened.
- **Out of claim scope:** full warm-workspace qualification, seed-free performance acceptance, GEMM/matrix correctness, other callers' lifetime protocols, arbitrary concurrency, LLC/VM operation, high-half failure injection, and RTL parity. The main's qualification/readiness/acceptance flags remain false.
- No production edits, no commit, no push, no native execution, and no shared-session manipulation were performed by this reviewer.
