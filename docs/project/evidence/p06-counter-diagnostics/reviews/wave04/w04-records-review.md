# Wave 4 independent public-record and DMA-repair review

## Verdict and scope

Reviewer: `/root/w04_records_review`, independent of the record implementation and the parent's DMA repair. Repository HEAD: `af0a904154e15452b7138bfd6cfa5702af7e4bc9`.

**No remaining F1, F2, or F3 findings in the reviewed scope.** The prior F2 missing-DMA-evidence finding is closed by the repair described below. A new F2 caller-lifetime issue found during this review was repaired by the parent and independently rechecked; it is also closed. The source-level review is complete for these exact hashes. Native public linking and all five public runtime executions remain pending, so this is not a native execution pass or final release qualification.

Read both Python files in their entirety, including every schema/type/count check and every synthetic test. Reviewed the three C++ files in context, with particular attention to every new DMA observation, payload, lifetime, status, and JSON change. Cross-checked the record obligations against public_main, hooks, the actual counter-access inventory, runtime queue/event/CP paths, production public MPM query, native CSR/model accessors, and actual functional RAM implementation.

Read AGENTS.md, the repository `code-review` and `simx-review` skills, both coding guidelines, bug-fix guidance, review policy, simulator architecture, and relevant SimObject observation/idle/reset/lifetime sections. Read the wave-3 record handoff and wave-4 main review. Applied the independent R3 contract-review standard; no implementation or production file was edited by this reviewer.

### Reviewed file identities

| File | SHA-256 |
|---|---|
| `ci/project/p06_counter_public_records.py` | `e3e09b062ab6878acd1ffc8963f2eff0b5df5227967c9731786e7484c98dc44e` |
| `ci/project/test_p06_counter_public_records.py` | `425650557e2f2ca529686ad0c11a722aab48d5de9495db087519ccadbeebe27e` |
| `tests/unittest/checked_counters/public_hooks.h` | `94d79601112904489b9c8ec8b33ba9cb97a6db2e18c0e84c90ae7905f82fdcfa` |
| `tests/unittest/checked_counters/public_hooks.cpp` | `6665821766a403269eda2e0c145fe60782f5563b9e25d4fc67dddfc74152a76f` |
| `tests/unittest/checked_counters/public_main.cpp` | `4d9a2178754052a3dc771c65f0c7b6829fa55d10195a26f9e89ec3f96911656b` |

The final main hash incorporates the static-payload lifetime repair. Its hash at the start of this review was `fc1b045c66c0fa5efce2b2f1ddde412344fa87b3626bc74bed9858762354c60f`. Only that one reviewed file changed during this review, at the parent's direction after the finding. The other four reviewed files stayed unchanged. Final hashes were checked again before this report was written.

## Closed findings

### F2 — Missing direct-RAM side-effect evidence: closed

**Confidence:** high. **Evidence type:** `static-proof` for the observation path and retained-record obligations, supplemented by synthetic negative tests. The original finding was `missing-test`; no native fault-mutation execution is claimed.

The original retry sent the same words already present and observed only Processor run/DCR entries and selected counters. A direct-RAM write could therefore happen while those observations stayed unchanged. The new code now retains the program's actual public allocation address, calls `read_program_words` before the rejected DMA, attempts the bitwise inverse of all three instruction words, collects the real event status, and reads the same actual RAM again afterward. It asserts original contents, a distinct attempted payload, and unchanged post-request contents. These are three additional assertions in each negative mode.

The hook resolves the live wrapped Processor to its actual first Core, follows `Core::processor()` to the owning ProcessorImpl, and reads `ProcessorImpl::ram()`. In the real SimX backend, the constructor attaches its own `ram_` to that Processor. The direct-memory CP write branch writes that same `ram_`. VM is prohibited by the existing counter-access build guard, so the public buffer address used for the attempt is also the physical backing-store address observed here. This is not a substitute array, a reply copied from the record, or a query through the already-poisoned CP.

`RAM::read` performs checked byte reads through `get(addr + i, false)` and allocates no RAM pages. It does not tick, reset, execute pending events, or enter the counter-query path. The hook rejects an absent Processor/RAM and address-plus-length overflow, holds the same diagnostic mutex used by wrapped model calls, and returns copied words. The source-level failure path has collected the original native run/query before these reads; the DMA completion and queue-finish checks precede the post-attempt read. Host observation between completed operations fits the documented SimObject host-read contract. This change introduces no production timing behavior, new linker wrappers, or access-control/compiler-flag bypass.

The new `failure.suppression.dma` object is required exactly, with only `address`, `status`, `before`, `attempted`, and `after`. The verifier bounds the address and every 32-bit word, rejects booleans as numbers, requires actual failure status 3, requires the exact original three words on both sides, and requires the exact inverse words as the attempted payload. The JSON printer correctly closes the DMA and suppression objects before emitting the failure's raw read trace.

These observations close the specific blind spot: a forbidden transfer of the requested distinct bytes followed by an error response cannot retain the required after-image. This remains an observed final-memory contract for this diagnostic, not a claim that it detects a hypothetical transient write-and-restore or arbitrary runtime callers.

### F2 — Asynchronous payload could expire on timeout/unwind: closed

**Confidence:** high. **Evidence type:** `static-proof` of the original lifetime hole and of its bounded repair; no runtime timeout reproduction or sanitizer pass was run.

The first repair passed `result.dma_attempted`, a local member of the Suppression result, to the asynchronous public enqueue. `Queue::enqueue_write` retains the device buffer but captures the host pointer without owning its storage. If `failed_event` threw on an unexpected timeout while work remained queued, unwinding `suppressed_work` could end that local array's lifetime before the outer Context destructor drained/joined its worker.

The parent changed the enqueue argument to the namespace-scope `constexpr kRejectedProgram`. This has static storage duration and remains valid through normal completion, timeout, and exception cleanup. The result still records an exact copy of the same immutable array, so the attempted data and retained evidence agree. The argument no longer depends on a local return object's lifetime or copy elision. No checks or counts changed in this second repair.

On the expected path, `Queue::worker_loop` finishes the work, destroys its work closure, sets queue error state, and only then completes the event. `Event::wait_value` observes completion/error under its mutex, and `consume_queue_error` finishes the queue twice. The post-attempt RAM read therefore follows the attempted command's completion. `failed_event` returns the first actual `vx_event_wait_value` status after independently checking repeated, higher-timeline, multi-event, and completion-value behavior.

## F0 observations supporting the contract

### Recursive schema and inert parsing

**Confidence:** high. **Evidence type:** `static-proof` plus synthetic tests.

The parser requires a string with a 16 MiB output bound, exactly one final result line, a 256 KiB result payload, supported record separators, no accompanying failure/unrelated result, maximum JSON nesting 16, integer tokens of at most 20 digits, and no float/nonfinite numeric tokens. `json.loads` enforces complete JSON consumption; duplicate-key detection runs for every object, including escaped-equivalent keys. Malformed structures do not bypass the normal decoder.

Every record layer has an exact key inventory. Every list has an exact length. All scalar contracts use exact primitive types, with explicit unsigned bounds or signed exit-code bounds. Nested component and DMA arrays validate each element before equality comparisons, so Python's bool/int equality does not weaken those comparisons. Rows, model snapshots, CP records, queries, failures, suppression entries, and destruction records are all covered. The validator performs no file reads, producer-path resolution, subprocess calls, native loading, or execution. It checks consistency; source/build/process authentication remains the separate runner's responsibility.

### Counter identity, raw replies, and aggregation

**Confidence:** high. **Evidence type:** `static-proof` plus synthetic tests.

The independent fixed tuple inventory matches the frozen public contract after excluding its 12 disabled L2/L3 selectors. Its 33 ordered names/classes/CSRs cover exactly 40 sources: one source for ordinary entries, two actual banks for each of six D-cache rows, and two TCU buffer-read sources. Those identities and multiplicities match `counter_access.cpp` and its real cache/TCU accessors, not producer-reported totals alone.

All source components are uint64. Each successful sum is independently recomputed and rejected if it exceeds uint64. Both low and high replies are required, with exact class/CSR/core-zero tags, sequential entry numbers, context generation, status/overflow/completion fields, unchanged ticks/reset generation, and restored class. Each reply word must equal the appropriate half of the recomputed sum, and the reported public value must reconstruct from both words. The production `vx_device_mpm_query` emits those exact tags, reads low then high, and writes the destination only after both succeed.

The coherent mode's exact 40 nonzero seeds exercise both halves and real aggregate sources; the unseeded successful scalar witness remains separately required. The failed cache low-half correctly records the production exception's class transition from 0 to 4, because the throw occurs before Core restores the saved class. No healthy terminal record can use that transition.

### Terminal drainage, ownership, destruction, and fresh context

**Confidence:** high. **Evidence type:** `static-proof` plus synthetic tests.

Healthy states require a live complete inventory, idle platform, no running core, zero pending reads, architectural exit witness 7, and positive cycle/instruction/tick observations. Before/after states must be identical. CP controls remain enabled, status/error are clear, retired and expected agree, head equals tail, and tail equals 64 times the sequence. Exactly 66 CP commands must retire for each 33-row terminal snapshot. The expected sequence is bounded by the actual 32-bit retired register.

Exclusive final ownership requires Device references 1, no queues or buffers, and rejection of the diagnostic's extra retain. These observations correspond to main's actual resource releases and private ownership checks before final Device release. Destruction records must match the final live snapshot exactly, then show actual destructor completion, zero clock, unchanged reset identity, and idle platform. Generation/reset expectations distinguish the second native context, whose fresh scalar success is required after the first is destroyed.

Only the selected 33 counters / 40 actual components are covered by counter-preservation equality; this does not assert preservation of all unrelated derived model statistics.

### Failure and nonqualification invariants

**Confidence:** high. **Evidence type:** `static-proof` plus synthetic tests.

Async failures require fresh quiescent seeded storage, MAX or MAX-2 cycle seed, saturated final destination, no retired instructions, no decreasing selected source, exact typed-overflow/run counts, and positive progress for the delayed case. The cache failure requires actual bank slots 16 and 17 at MAX and 1 and its one failing raw low-half. Repeated public query status and unchanged sentinel destinations are raw requirements.

Suppression retains exact pre/post native run/read/write/overflow entries and all five attempted request obligations in the fixed control flow. Exact global counts bind extra or omitted model entries; cache's one failing read shifts the fresh context's first read sequence to 2. The DMA evidence above now covers the route that bypasses Processor wrappers. All five modes must keep `qualified`, `ready_for_warm`, `warm_execution`, and `acceptance_claimed` false. Synthetic records or coherent diagnostic seeds cannot promote those claims.

## Independently reconciled source-derived totals

These are source-derived expectations, not native receipts. Context construction contributes 90 assertions; inventory contributes 146; terminal snapshot 714; an unseeded successful context 823; the coherent first context adds 146. Suppression now contributes 43 instead of 40. A failed async context contributes 339 and a failed cache context 336. Main entry and final result checks contribute 6.

| Mode | Assertions | DCR write entries/completions | DCR read entries | DCR read errors |
|---|---:|---:|---:|---:|
| normal | 1652 | 38 | 132 | 0 |
| coherent-terminal | 1798 | 38 | 132 | 0 |
| immediate-overflow | 1168 | 38 | 66 | 0 |
| delayed-overflow | 1168 | 38 | 66 | 0 |
| cache-overflow | 1165 | 38 | 67 | 1 |

The main's actual 19 descriptor writes per context explain 38 total. Each successful terminal contributes 66 half reads; only cache failure contributes an additional failed read. The static-payload repair does not alter those totals. Both Python modules agree with the recomputed counts.

## Validation performed and limits

- Independently ran `python3 -m unittest discover -s ci/project -p test_p06_counter_public_records.py -v`: **30 tests passed in 1.549 seconds**. Log: `/workspace/scratch/98908dfa3444/w04-records-review-tests.log`.
- Independently ran **18 additional targeted adversarial probes** for the new DMA object: missing/unknown fields, negative/oversized words, float status in each negative mode, literal/escaped duplicate DMA keys, and trailing second JSON. All were rejected. Log: `/workspace/scratch/98908dfa3444/w04-records-review-probes.log`.
- Inspected all existing tests rather than treating their pass count as sufficient. Tests explicitly attack reordered/substituted inventories, hidden aggregate overflow, adjusted-but-wrong coherent source banks, zero-only seeds, word/tag/order/class drift, model advancement, CP nonretirement, resource retention, destruction mismatch, failed sentinel mutation, wrong failure progression, revived model entries, and false acceptance claims. Their fixtures are clearly labeled synthetic.
- Read and traced actual runtime/model/RAM behavior; captured exact final file hashes. The parent reported syntax checks for the C++ repair; this reviewer did not independently rerun C++ syntax, linking, native public cells, fault-mutation native tests, or sanitizers and does not count those as independent evidence.
- No production or reviewed implementation edits, commit, push, resource-guard weakening, native build, or shared-session manipulation was performed by this reviewer. The only writes were this report and its scratch review logs/hash records.
- Native source/build/process-bound public evidence is still required before claiming those five cells pass. Scope excludes warm acceptance, benchmark speedups, arbitrary concurrency/callers, LLC or VM routes, matrix correctness, and RTL parity.

### Context source identities

The exact source snapshots used for the cross-file reasoning are retained here and in `w04-records-review-final-hashes.json`.

| File | SHA-256 |
|---|---|
| `sw/runtime/common/queue.cpp` | `1d785262d128de3ffbf1feb32cc2b32f6457a6644df6ef9a04d4e8b4d45c962e` |
| `sw/runtime/common/event.cpp` | `7a9b9a39a0d77295f62a8435a0a962d367fa0d2623d3ca580a3b2ba748c11b67` |
| `sw/runtime/common/device.cpp` | `9b32e38a9bbc0460a7f2af522fd5efdc96e1c06e359e28c5151285557f89d90a` |
| `sw/runtime/common/perf.cpp` | `fa6945cf379ae184d4e3edca5fcbc147d11f725e5ad3574ff3f89a16167099b3` |
| `sw/runtime/simx/vortex.cpp` | `0d890c95fecb67da26d23ea4a0af10ac328dddf110cd2575baff3aa5d4c905cb` |
| `sim/common/mem.cpp` | `2dc21e7ccb04e773b091f209652107bac673edbc6d6640cfca0418ad89a73cba` |
| `sim/simx/processor.cpp` | `569cf629d1e25ec9a295b20bfadfabbe21cd0989127f2b825fceee99a8062b78` |
| `sim/simx/processor_impl.h` | `f72e86ce9204a80a8246ab9c6ec1fab9bfccaf334a5ee487e4dc9dc01a7f921b` |
| `sim/simx/core.cpp` | `f95003971a6052962b761b1ee8e815ead42f6a60fccf8157fa94c3ded3e44f31` |
| `sim/simx/csr_unit.cpp` | `c35bd6a80120f76c9cf65076c736aaf577329285a74aac8c11c03f0ce829fc3d` |
| `tests/unittest/checked_counters/counter_access.cpp` | `f687b107b27048b5cd6265911c872326996035f86dec10bc2917b84438205db7` |
| `tests/unittest/checked_counters/access_cache.cpp` | `362d67fd919ec97ef90d6a8b45179886b1b19dc65d2165ee02627744a6771e5c` |
| `tests/unittest/checked_counters/access_tcu.cpp` | `82625e07f4cfee0c7e4e55bd0a8aaef28a6ec9e9ab7064292fe11815e8a6ec7f` |
| `tests/unittest/checked_counters/access_socket.cpp` | `33ddaa82618fa644489b7aad40bc193818908eb0eb34e65f5a5a27fdc2b7cf73` |
| `ci/project/p06_contract.py` | `780086070739b6d3586f9b3695ad4dc31d209a7817cf1af3651160a9fe6e1376` |
