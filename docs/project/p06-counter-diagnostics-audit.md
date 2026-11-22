# P06 native counter diagnostics audit

## Decision and completed scope

**The selected diagnostic development is implemented, has a reviewed original
native pass, and passes complete clean local governance at the published
test-only repair. The next bounded task is measurement qualification.** The work
started at clean `master` revision
`7455e008c1e001d3329e74fd55ffcd942592ec5f`. It closes the missing native
backing-source coverage, actual public-runtime fault/terminal observations and
retained-data reader gaps identified at that parent. It does not qualify the
complete managed warm caller or a later measurement executable.

The latest independently audited native evidence belongs to the published
reader and source-inventory checkpoint
`4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, tree
`061ecbddc9b321edbd70c054c8efce4d188de04f`, run `45034575685`. It separately
repeats the corrected diagnostic pass at
`e5f152464dda5e488d6d1a030c1fcdc49b5a9701`, tree
`74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`; each execution keeps its original
source and receipt. The
[evidence packet](evidence/p06-counter-diagnostics/README.md),
[native index](evidence/p06-counter-diagnostics/native/index.json) and
[development handoff](p06-counter-diagnostics-handoff.md) retain the exact
originals, replay commands and remaining receipt updates.

P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open. Diagnostic and
replay qualification, warm readiness, full warm coverage, warm execution and
acceptance claims remain false. Historical warm-v1 still rejects
unconditionally with `P06-WARM-RV64-MPM-HIGH-HALF` and
`absolute_no_wrap_bound="not_established"`. The
[qualification plan](p06-mpm-qualification-plan.md) defines the remaining
sequence without changing the warm experiment or accepted cold evidence.

## Findings and implemented corrections

| Finding | Implemented result and review | Remaining boundary |
|---|---|---|
| The prior checked harness seeded only 19 of 33 available selectors. | The [v2 model diagnostic](../designs/simx_counter_diagnostics_v2.md) accesses all 33 selectors and all 40 component-owned sources through the real model/DCR path, including both D-cache banks and both private TCU buffers. | Seeded transport inputs do not qualify an unseeded workload or prove its complete lifetime. |
| Standalone statistics additions did not exercise actual cache/CSR ownership. | Native failures now overflow the real two-bank D-cache and two-buffer TCU aggregates, retaining typed errors and unchanged poisoned components. | Directed component/aggregate controls remain separate from complete warm execution. |
| Controlled public tests substituted Processor and RAM. | The [public native diagnostic](../designs/simx_counter_public_diagnostics_v1.md) links the actual Processor/RAM, backend, CP and common runtime. Diagnostic linker hooks call the original methods, retain real updater/aggregate faults and observe sticky failure, repeated wait/query rejection, queue-error consumption and fresh-context controls. | A fresh successful context is independent evidence; it never repairs a failed lifetime. |
| Processor-entry counts alone could miss direct-RAM DMA side effects. | Negative modes attempt the bitwise inverse of the three-word program and independently compare actual RAM before/after. RAM remains unchanged. Namespace-scope `constexpr` original/inverse arrays keep asynchronous source payloads alive through waits and cleanup. | The check is specific to the VM-off, CP-on-direct-RAM route. |
| The first public harness equated host head-writeback bytes with the internal CP head. | The [CP observation repair](evidence/p06-counter-diagnostics/reviews/wave06/w06-cp-drain-fix.md) retains unsupported raw head bytes explicitly and uses schema-2 retirement/enable/error/tail observations plus a source-backed drain inference. Its [independent review](evidence/p06-counter-diagnostics/reviews/wave06/w06-cp-drain-review.md) preserves the original native failure. | This changes the diagnostic assertion, not production CP semantics or the public API's concurrency guarantee. |
| Terminal reads and release success alone did not establish lifetime closure. | Successful public contexts establish exact selector/component inventory, retired workers, empty registries, actual final Device ownership, stable terminal vectors and completed Processor destruction. The [lifetime contract](../designs/simx_counter_lifetime_v1.md) supplies the separate conditional source argument. | The complete managed caller and actual loaded dependency provenance remain to be bound. |
| Live build validation would open producer object paths during offline replay. | The [model](../../ci/project/p06_counter_diagnostics_replay.py) and [public](../../ci/project/p06_counter_public_replay.py) readers validate retained records as inert data through current trusted helpers. They never execute archived code or open recorded producer paths. | Missing object/library/tool payloads cannot be independently rehashed; archive consistency does not authenticate execution. |
| A successful marker could coexist with contradictory failure text. | The [checked-log repair](evidence/p06-counter-diagnostics/reviews/wave06/w06-checked-log-fix.md) rejects contradictory boundary/failure markers, including adjacent explicit `FAIL`/`ERROR` text. Rehashed mutations remain rejected. | A packet-integrity pass for a failed original does not turn its native outcome into success. |
| Controlled native-runner fixtures exposed the host interpreter to a strict native pin. | The [fixture repair](evidence/p06-counter-diagnostics/reviews/wave06/w06-governance-fixture-fix.md) isolates synthetic observations without mutating shared host modules. Native CPython 3.12.14/Linux and executing/PATH interpreter equality remain enforced. | Hosted governance on Python 3.12.3 is host-test evidence, separate from native interpreter qualification. |
| Public mutation tests still targeted old schema/CP fields and could make no change. | Current schema-2 fields are targeted and mutation helpers reject no-ops. The [independent delta review](evidence/p06-counter-diagnostics/reviews/wave07/w07-public-replay-test-delta-review.md) and complete genuine-original replay close this test finding. | Previously skipped success-dependent methods remain historical non-execution, not retroactive passes. |
| A later producer's source names could not safely be inferred from the replay checkout. | The [source-inventory helper](../../ci/project/p06_counter_source_inventory.py) pins all 270 original model and 676 original public names. Explicit manifests require their independently supplied byte digest, complete descriptors and retained bodies; errors fail without fallback. The helper is included in the before/after trusted reader closure. | A manifest digest binds expected bytes; it is not Git-origin or source-to-binary authentication and does not expand the diagnostic contract to the warm caller. |

Typed test accessors use C++17 explicit instantiation with normal compiler access
checking. Wrapper translation units include unchanged production bodies; the TCU
unit retains its byte-exact production body followed by its test-only footer.
An earlier access-control compiler option was rejected because it invalidated
protected lifecycle-hook detection. Production object lists, class definitions,
public ABI, generated configuration and ordinary `uint64_t` counter semantics
are preserved. Diagnostic seeds and accessor objects must remain outside future
measurement binaries. See the [model contract](../designs/simx_counter_diagnostics_v2.md)
for compilation and component-ownership requirements.

## Original native outcomes

| Original source and run | Actual result | Interpretation |
|---|---|---|
| `407ab9fea5e4f793a2a5088f566a87f3e631aa84`; [45026112992](https://github.com/baabi-boo/AI-GPU/actions/runs/45026112992), attempt 1 | Seven model cells pass. | All-selector transport and checked arithmetic; no public-runtime execution claim. |
| `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`; [45029135146](https://github.com/baabi-boo/AI-GPU/actions/runs/45029135146), attempt 1 | Seven model cells and the public build's boundary control pass; `public-normal` fails; four later public modes are blocked. | Real diagnostic failure from the unsupported host head-writeback assumption; the original archive remains failed. |
| `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`; [45031746149](https://github.com/baabi-boo/AI-GPU/actions/runs/45031746149), attempt 1, job `137236632765` | Seven model cells plus six public-runner cases pass: one model boundary control and five actual public modes, for 13 native test process cases. | Reviewed corrected diagnostic success at this exact source/tree; no warm execution or acceptance. |
| `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`; [45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685), attempt 1, job `137245341329` | Seven model cells plus the public build's boundary control and five public modes pass: 13 native test process cases. | Independently audited new execution at the published reader/source-inventory tree; diagnostic scope remains unchanged. |

The latest [independent original-packet audit](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
binds artifact `14760051170` to the retained
[run-45034575685-attempt1.zip](evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip):
4,290,949 bytes, 1,046 members, SHA-256
`6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb`.
All 270 model and 683 public source bodies match immutable Git at the exact
source/tree above. The 17 model and 14 public command records remain separate.
Model replay passes; public replay passes with the independently Git-pinned
[683-source manifest](evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json).
The original fixed 676-name public route rejects this expanded inventory, and
an invalid explicit digest fails without fallback. The earlier `e5f1524`
public pass locator remains unchanged.

Each ordinary/checked model boundary cell has **6,389 assertions and 1,788
half reads** over 33 selectors and 40 backing components. The five public modes
are normal, immediate overflow, delayed overflow, cache overflow and coherent
terminal. Together they observe ten actual Processor constructions/disposals,
seven complete terminal snapshots, 231 selector queries, 462 successful native
half reads and one additional failed cache half read. The 12 unavailable L2/L3
rows remain unqueried. The two normal contexts are unseeded; coherent-terminal
and overflow seeds retain their diagnostic scope and separate fresh unseeded
controls. The [independent original-artifact audit](evidence/p06-counter-diagnostics/reviews/wave07/w07-native-public-audit.md)
and [public contract](../designs/simx_counter_public_diagnostics_v1.md) bind these
counts and distinctions.

CP observations keep `head_writeback_raw=0` and
`head_writeback_status="not-published"`. The raw tail pair combines the staged
low register with committed high bits; it is not an independent complete
committed-tail observation. Under exclusive serial submission, both CP enables
are one, status/error are zero, retirement is exact and each half-read command
consumes one cacheline. In the corrected snapshots, sequence 26 → 92 and
runtime/raw-pair tail 1,664 → 5,888 account for 66 commands. Source inspection
then supplies the drain inference. `cp_quiesce_()`, release success and idle
after CP disable are not independent drain certificates.

## Host and retained-data verification

| Evidence | Result | Scope |
|---|---|---|
| Concurrent local governance | 3,070 tests; 149 failures, no errors. | The workspace changed while it ran; no immutable-source pass is claimed. |
| Hosted `81ed687`, run `45029135196`, job `137228604836` | 3,146 tests; 18 failures and six errors. | Retained original controlled-fixture interpreter-exposure failure. |
| Hosted `e5f1524`, run `45031746158`, job `137236633104` | **3,158 distinct tests pass in 1,305.183 seconds on Python 3.12.3**, with no failures, errors or skips. | Original-log review independently reconciled every method/result; this suite predates the `4268d2d5` replay/inventory additions. |
| [Hosted `4268d2d5` original](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json), run `45034575638`, job `137245340992` | **3,312 distinct tests execute in 1,811.712 seconds on Python 3.12.3: 3,310 `ok`, two `FAIL`, zero errors/skips; exit 1.** | Independently reviewed original failure; the checked/public replay isolation guards stop on current trusted helper path resolution. |
| [Clean local `142b2d6` original](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json) | **All 3,318 distinct tests pass in 1,918.414 seconds on CPython 3.12.14; zero failures/errors/skips; all four commands exit 0.** | Independently reviewed clean detached worktree before/after; 365 source records match immutable Git; local governance only. |
| [Checked replay review](evidence/p06-counter-diagnostics/reviews/wave06/w06-checked-replay-review.md) | 43 methods / 167 subtests pass. | Model archive consistency and rejection at the recorded reader bytes. |
| [Complete public replay](evidence/p06-counter-diagnostics/reviews/wave07/w07-public-replay-integration-tests.md) | 40 methods / 247 subtests pass, no skips. | Genuine corrected original, failed-original rejection and mutation coverage; no new native execution. |
| [Source-inventory review](evidence/p06-counter-diagnostics/reviews/wave08/w08-source-inventory-review.md) | 48 methods / 278 subtests pass. | Helper contract, bounded paths, exact descriptors and fail-closed behavior. |
| [Independent reader integration review](evidence/p06-counter-diagnostics/reviews/wave08/w08-replay-integration-review.md) | 37 methods / 110 subtests pass. | Actual reader/helper integration, externally pinned manifests and preserved original outcomes. |

The [host index](evidence/p06-counter-diagnostics/host/index.json) binds five
original local/hosted attempts and their suite logs. The focused counts are
separately scoped; they are not added together or represented as a full-suite
run. Reader receipts retain
`scope="retained-data-consistency-only"`, `native_execution="not_run"` and
`retained_code_executed=false`, with qualification and acceptance claims false.

The published `4268d2d5` native run and independent inert replay review retain
their completed diagnostic scopes. The separate
[completed hosted review](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/failed-review.md)
confirms that all 3,312 previously discovered IDs actually executed, including
all 154 additions with no archive skips. The two failed isolation guards reject
current trusted `baseline_inventory.py` when its GitHub checkout pathname
equals the recorded producer source root. Both guarded checks stop before
completion; the original full-suite result remains **failed**. The retained
696,999-byte log has SHA-256
`1d093819f62493536a2444b6efec31a75e522e7e3a3cfc197a0a101c833160a8`.

The [independently reviewed test-only repair](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md)
is published at `142b2d6aaea2fa4226118b857514113032d2e26c`, tree
`754ef8577f9a72785c0809048762c70b16cb4857`. It changes exactly the two replay
test modules and closes **F2-01**, the current/recorded-root path collision,
and **F2-02**, the filename-only execution witness. Exact current helper
permissions preserve producer-path denials, while exact compiled parser-code
identity rejects altered executable bodies before dispatch. The
[earlier 87-test candidate](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-fix.md)
and its demonstrated witness gap remain historical evidence.

| Separate final repair scope | Actual result |
|---|---|
| [Author's complete affected modules](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-fix-exec-identity.md) | 89 methods pass in 139.141 seconds; no failures/errors/skips |
| [Independent changed/new methods](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md) | 8 methods / 670 subtests pass in 4.956 seconds; no failures/errors/skips |
| [Independent compiled-identity and original probes](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md) | 3 methods / 15 subtests pass in 4.437 seconds; no failures/errors/skips |

The subsequent [independent clean local review](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/review.md)
completes full-suite verification at the exact `142b2d6` source/tree above.
All 3,318 expected IDs actually execute with `ok` results, including both
formerly failed guards and all six added methods. Preflight, project metadata,
baseline-packet checking and the full unittest command each exit 0. The detached
worktree is clean before/after, and all 365 recorded source bodies match the
immutable Git bytes and remain unchanged. The 578,913-byte raw local
[unittest log](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/unittest.log)
has SHA-256
`dd05f5f1b09e8e97ae5fc13b2da5c739d39ef6d22a34d035f1cc9142f564e4c7`.
The 1,918.414-second suite duration is distinct from the wrapper's command
monitoring interval. The focused scopes above are not added to this actual
full-suite count, and the failed `4268d2d5` original remains failed.

The separate [hosted retry observation](evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json)
records run `45040805357`, job `137264592244`, queued at 2026-11-22 16:55:09 UTC,
with no runner, steps or conclusion. Native retry `45040805341`, job
`137264592580`, also remains queued with no executed result. The clean local
suite supplies the documented project governance verification; it supplies no
hosted or native execution. The latest audited thirteen native cases remain
bound to `4268d2d5`.

## Conditional lifetime proof and next development

The [lifetime argument](../designs/simx_counter_lifetime_v1.md) binds 45
production bodies and ten inventory/caller bodies at `407ab9f`, plus 21 pinned
Ramulator bodies at `e62c84a6f0e06566ba6e182d308434b4532068a5`. For zero-origin,
nonnegative monotone components, every earlier aggregate is no larger than its
successful checked terminal aggregate. This bounds the complete storage lifetime
only if every update/reset obeys that invariant and no component can change
during or after terminal readout until destruction. Checked primitive storage
alone, sampled monotonicity and small endpoint values do not prove those premises.

The selected Ramulator finalizers calculate or print statistics without ticking
or serving request callbacks. The adapter independently confines GPU callback
delivery to `tick()`/`drain()`, which its destructor does not call. This resolves
the selected source-level boundary. It remains conditional on the **actual loaded
dependency** implementing that source graph; a cached-library digest does not
establish its compilation origin. The source manifest is a set of proof premises,
not a complete transitive build attestation.

The next work is a separately versioned qualification record, reader and
execution binding for actual seed-free checked binaries, the complete managed
caller and loaded dependency provenance. Independently review strict rejection
before performance collection; then run the four-process preflight and, only
after its prerequisites pass, the unchanged **24-process / 792-launch /
25,344-word** matched attempt. The
[qualification plan](p06-mpm-qualification-plan.md#qualification-work-to-implement-and-review)
defines the exact ordering, terminal obligations, frozen populations, statistics
and resource limits. P01 vendor `hw_emu`, P05 obligations, inherited area findings,
RTL/full-AFU qualification and physical hardware evidence remain separate.

## Task and publication accounting

The unchanged [retained historical snapshot](evidence/p06-counter-diagnostics/reviews/session-agents-wave08.json)
contains 47 actual task names at its original capture. The
[current actual-task ledger](evidence/p06-counter-diagnostics/agent-ledger.json)
records all 60 assignments complete, with six actual tasks in each of ten waves;
none remains in progress. The reviewed repair, clean local full-suite verification,
final actual-result prose and independent final certification are complete.
The actual-60/ten-wave completion flag is true. Each row
separates original evidence, related independent review and missing author notes.
The independently certified 60/59 candidate and all earlier snapshots and failed
attempts remain unchanged beneath this final transition. The captured
ledger records published test-only checkpoint
`142b2d6aaea2fa4226118b857514113032d2e26c`, its completed clean local pass and
separately queued hosted/native retries. Later documentation publication remains
root-owned; no queued remote result is inferred.
