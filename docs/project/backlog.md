# Ordered development backlog

This is the actionable queue, not a second completion ledger. Live phase status,
dependencies and authoritative acceptance text are in [roadmap.json](roadmap.json);
the current handoff is in [status](status.md). Keep work-item IDs stable when
adding issue links or evidence. Role names below describe responsibilities;
the active execution owner is recorded in [status](status.md). Later-phase roles
remain unassigned until an actual owner is identified.

## Start here: P06-T01 dependency provenance

**Current bounded task: P06-T01 — collect and independently review the complete
fresh dependency/native original under the
[dependency handoff](p06-dependency-provenance-handoff.md).**
The current production implementation is published at
`19333193192ba5a2d3667c0111235ec9e21a5898`: immutable source locks, recorded-build
receipts, exact product staging, full 30-command application admission and
complete inert native/control readers. Actual host builds exposed three
corrected issues: repeated compiler prerequisite names, a map assigned to the
wrong payload-size category, and an unused spdlog archive incorrectly required
to contribute a member. The [packet](evidence/p06-dependency-provenance/README.md)
preserves the failed attempts, independent reviews and distinct validation
checkpoints. Follow the
[intake/replay guide](evidence/p06-dependency-provenance/replay-guide.md) for the
still-required formal original and its external pins. At the
[2026-11-23 11:11:01 UTC provider observation](evidence/p06-dependency-provenance/validation/provider-observation-19333193.json),
fresh run `45162083701` was pending with no jobs, while governance run
`45162084006` had one queued job and no steps. No cause or fresh native result
is established by that observation. The separate host diagnostic cannot supply
formal preparation/cache/staging or native loader evidence.

The [completed host diagnostic `05`](evidence/p06-dependency-provenance/host-diagnostic/execution-05-summary.json)
at `19333193` passes all 413 actual selected operations: 406 compilations, three
archives, two indexes and two shared links, with complete diagnostic graph
validation and [independent host-original consistency review](evidence/p06-dependency-provenance/host-diagnostic/review-05.json).
This establishes the host dependency-build scope; the next task
still needs the formal producer, both managed format builds, four native
processes and the separate controls in one identified original.

The [native lifetime witness](evidence/p06-native-lifetime/README.md) is
implemented at `b4127b19a004b5aebb8d52eab9ceda0da3ff4561`.
[Run 45130300651, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300651)
passed four FP16/BF16 × allocation-policy processes, **132 launches and 4,224
exact FP32 result words**, with independent original review. Its separate
positive-pending probe and exact always-zero rejection are outside that matrix.
Complete counter qualification remains open.

The [complete inert preflight reader](../designs/managed_counter_preflight_replay_v1.md)
and [historical evidence packet](evidence/p06-managed-preflight-replay/README.md)
retain the successful original at `57248e73` and preserve the failed `8756f400`
original as an exact negative control. Their v1 observation scope remains
unchanged; the [historical handoff](p06-managed-preflight-handoff.md) records the
pending/reset gaps that the later witness increment addressed.

[P06-A01 is accepted](evidence/p06-baseline/acceptance.json) for the original
[run 44901052221, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44901052221)
at `84b6ca0ca75fba248ba330642bbf8764db3d459c`. The
[packet](evidence/p06-baseline/README.md) retains eight FP16/BF16 workloads,
48 processes / 72 launches (40 measured processes / 60 measured launches),
and 45 counter rows: 33 available and 12 explicitly unavailable. The
[qualification audit](p06-qualification-audit.md) and
[analysis contract](../designs/native_baseline_analysis_v1.md) document independent
review, the reusable analyzer, stricter timing checks and host timing limitations.

The [frozen ownership/correctness contract](../designs/serial_matmul_workspace_v1.md)
is implemented. The [reviewed original workspace packet](evidence/p06-warm-workspace/README.md)
records eight processes, 32 launches, 1,024 exact output words and 60 reconciled
tensor-buffer lifetimes at `13dc0d1fdb6d5322104e381aa342dc139c7bb80c`,
[run 44925627664](https://github.com/baabi-boo/AI-GPU/actions/runs/44925627664).
This retained-data review is historical correctness evidence, not fresh execution
or a warm performance result. The default six signatures and model policy remain
available.

The [current audit](p06-mpm-transport-audit.md) repairs the RV64 host counter
high-half defect in SimX and RTL. The [native review](evidence/p06-mpm-transport/reviews/native-review.md)
verifies all eight candidate passes and both numeric parent failures at `18c8880`;
the immutable governance suite passes 2,910 tests. The
[alternative review](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the concrete comparison finding and retains the direct decoder, preserving
raw area failures. The [transport handoff](p06-mpm-transport-handoff.md)
retains that repair's separate integration/publication history.

The [completion audit](p06-simulator-completion-audit.md) found discarded
asynchronous exceptions, a missed immediate-completion busy edge and abandoned
channel accounting surviving full teardown. Those repairs are implemented in
the [completion contract](../designs/simulator_completion_v1.md), with host
backend/public/framework checks and built-parent sensitivity. Dedicated native
controls at `db5ebb3` passed real-model exception/fresh-context and six public
success launches; 2,988 governance tests passed at that checkpoint.

A subsequent compatibility correction preserves recoverable CP-copy allocation
errors while keeping processor failures terminal. The unchanged lifecycle suite
passes four backend/memory cells and all three allocation stages, with 34 further
terminal-model-fault cells and four intended old-backend failures. Independent
review found no remaining F2/F3 defect. At repaired checkpoint `4781ca9`, the
clean focused suite passed **83 tests**, all eight compiled-parent failure
controls passed, and fresh
[native run 45009314161](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314161)
passed independent original-artifact review. That native scope is RV64 `p02-tfr`,
timing SimX, `PERF=1`, one worker and direct-RAM CP; it covers the actual-model
fault/success unit and six public successes. Both full Project Governance runs
at this repaired tree passed **2,993 tests each**, including all 83 focused
completion tests, with independent review of the original completed logs. The
broader CI matrix remains separately scoped. Use the
[completion evidence index](evidence/p06-simulator-completion/README.md) for exact
source, command and review scope. Documentation/evidence additions preserve the
tested inputs without relabeling the earlier execution as a run of the later tree.

The [checked-counter prerequisite](../designs/simx_checked_counters_v1.md) is
implemented at published `9fd7eac203c77fa54c7af80fa0220ae09553cd55`. Its
[development audit](p06-checked-counters-audit.md) records source/update and formed
aggregate checks, typed processor failure and the preserved ordinary `uint64_t`
alias. The implementation-stage runs passed 64 focused host methods, including
ten controlled RAM/LLC public-fault/success cells, plus five executing-interpreter
identity tests in the existing transport suite. Controlled Processor/RAM and
mocked native commands remain distinct from native model execution.

The [dedicated native run 45017731063](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063)
passed all five cells at that published SHA, attempt 1. Its
[independent original-packet review](evidence/p06-checked-counters/reviews/native-review.md)
confirms behavior, all 264 retained source files and 44 actual translation
units plus one link per variant. The separate
[immutable host-governance receipt](evidence/p06-checked-counters/local/governance-53f4ad08c/index.json)
records **3,043 passing tests** at actual local `53f4ad08c`, whose complete tree
equals published `a9227933`; 19 later workflow/public-runtime methods initially
passed separately. A subsequent [actual hosted governance run](evidence/p06-checked-counters/hosted/governance-index.json)
at `9fd7eac` passed **3,062 tests**, with independent original-log review.
That is a distinct execution, not an inferred sum of earlier results. The native
boundary matrix at that checkpoint covered **19 seeded available selectors**,
with **14 available sources unseeded** and **12 L2/L3 rows unavailable**.
The successful directed packet
retains `qualified=false` and `ready_for_warm=false`.

The [diagnostic continuation](p06-counter-diagnostics-audit.md) closes those
fourteen gaps. Its [reviewed original packet](evidence/p06-counter-diagnostics/README.md)
at `e5f1524`, run `45031746149`, covers **33 available selectors and 40 backing
components**, leaving twelve unavailable L2/L3 rows unqueried. Seven model cases
and six public-runner cases pass; the latter combine one boundary control with
five actual Processor/RAM modes and retain ten context disposals and seven
terminal snapshots. The separate clean host receipt passes 3,158 tests and
excludes later offline replay/source-inventory additions at `4268d2d5`.

The latest [native run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685)
separately passes all **13 diagnostic process cases** at `4268d2d5`. Its
[independent original-packet audit](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
matches all 270 model and 683 public source bodies to immutable Git and validates
both inert replays. The explicit Git-pinned 683-source manifest is required for
this public packet; the fixed original 676-name route rejects it. The separate
[completed host receipt](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json)
for run `45034575638` records **3,312 executed tests in 1,811.712 seconds:
3,310 pass and two isolation-guard failures**, with no errors or skips. The
[test-only repair](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md)
is independently reviewed and published at `142b2d6`, closing both F2 findings.
The subsequent [clean local governance receipt](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json)
records **all 3,318 tests passing in 1,918.414 seconds on CPython 3.12.14**, with
four successful commands and independent review of the clean source/log record.
The separate [hosted retry](evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json)
`45040805357` and native retry `45040805341` were queued at that retained
receipt's checkpoint, with no executed result in the receipt. The original
failed attempt remains retained, and the latest audited native diagnostic
scope stays at `4268d2d5`.

The completed [replay continuation](evidence/p06-managed-preflight-replay/development-audit.md)
verifies the original [run 45085300171](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171)
at `57248e73dfce4ae2d21d2cbdb82c3953eef2e3db`: FP16/BF16 × both ownership
policies, four processes, **132 launches and 4,224 exact output words**. It
binds 999 retained source bodies and 17 payload bodies to externally selected
source inventory/derivation expectations and checks complete application,
backend, generated-input, process and hosted-envelope relationships. The
failed [run 45084009157](https://github.com/baabi-boo/AI-GPU/actions/runs/45084009157)
at `8756f40029e59c87546fa22f4da33acd4e5d8e02` must still reject exactly with
`report.outcome: value differs`; it completed no managed launch. Replay is
retained-data verification, not another native run or qualification.

The implemented [native lifetime witness](evidence/p06-native-lifetime/README.md)
at `b4127b19`, run `45130300651`, records all 33 run/reset boundary pairs,
exact reset increments, required flushes, terminal readout and actual destruction
for each managed process. Zero pending balance is observed before reset can
clear it. The [conditional lifetime proof](../designs/simx_counter_lifetime_v1.md)
still needs its full source-bound 33-selector/40-component premises: zero
origins, audited nonnegative checked updates, admitted resets, exclusive
ownership, worker/queue cleanup, successful terminal sums and no later update.
A separate transient pending observation does not close that complete theorem.

The [dependency provenance route](p06-dependency-provenance-handoff.md) now has
immutable source locks, recorded configure/compile/archive/link operations,
product/loader admission and the existing complete application-build validator
bound into live execution. Complete inert native and combined-control readers
are published. The next action is to collect a successful formal fresh original
at a named published revision, retain all earlier failures, and review the exact
archive with independent external pins and provider identities. Reconcile its
406 compilations/413 selected operations with managed builds and actual loaded
products; separate host diagnostics cannot establish that complete join.
Keep the four-process, 132-launch, 4,224-word
managed population unchanged, with pending-read, always-zero and alternate-library
controls counted separately. Independently reconcile the complete original
before advancing the broader qualification work.
The [broader qualification plan](p06-mpm-qualification-plan.md) still requires
an independently reviewed admission/final-validation path for the eventual
measurement binaries. The current preflight/replay retain all three unresolved
obligations: `all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance`, and
`independent_complete_counter_qualification`.

Follow only a qualified route with the unchanged fresh matched warm attempt:
24 processes, 792 launches and 25,344 exact output words under the
[implemented sampling/rejection contract](../designs/warm_workspace_benchmark_v1.md).
Keep the unconditional v1 `P06-WARM-RV64-MPM-HIGH-HALF` block, `qualified=false`
and unestablished absolute no-wrap bound; source repair cannot recover historical
high bits. Current preflight/replay fields `qualified`, `ready_for_warm`,
`warm_execution`, `full_warm_coverage`, `acceptance_claimed`, `phase_acceptance`,
and `performance_acceptance` remain false. Preserve the cold baseline separately. P04 supplies the prerequisite;
P05 is independent. P06 and P06-T01 remain `in_progress`, with A02/A03 open.
Keep the two-job, 4 GiB memory and 15 GiB disk prerequisites unchanged, together
with the inherited 267 → 283 DSP finding and vendor `hw_emu` blocker.

**P02-A03 is accepted, completing P02-T02 and P02.** The
[acceptance record](evidence/p02-wgmma/processor/acceptance.json),
[WGMMA handoff](p02-wgmma-handoff.md) and
[processor packet](evidence/p02-wgmma/processor/README.md) record a finished,
passing formal matrix at clean source `4af2307`: 113 commands, 12 builds, 24 case
executions, 48 launches and 24,576 exact output-word comparisons. All 12 declared
performance pairs pass, and the two sparse RTL cases complete 64 metadata
transactions with observed waits. The corrected original-packet verifier checked
1,103 files against the independently supplied report digest. Independent
engineering and publication-integrity reviews support the bounded acceptance.

**P03-T01 and P03-T02 are complete for the declared six-signature matmul scope.**
The [historical A01 contract](evidence/p03-operators/acceptance.json),
[accepted numerical execution](evidence/p03-managed-matmul/acceptance-numerics.json) and
[accepted lifecycle integration](evidence/p03-managed-matmul/acceptance-lifecycle.json) preserve
their distinct source/evidence scopes. The managed path passed 176 case/backend
executions, 352 launches and 14,336 exact output-word checks from the 88
independent fixtures on SimX/native processor RTL. Actual runtime lifecycle
results cover RV64 `p02-tfr` SimX and default RV32 SimX, with 12 groups per recorded execution.

**P04-T01 is complete, with [P04-A01 accepted at source scope](evidence/p04-fixture/acceptance.json).**
The earlier [qualification packet](evidence/p04-fixture/README.md)
binds all five passing formal commands to clean source
`10ace66193686e3862c3c218760b66c044f1d4ae`; its complete source suite passed
1,733 tests in 752.879 seconds, including 64 P04 tests, with no errors, failures
or skips and unchanged source. The [fixed tiny MLP](../designs/tiny_mlp_fixture_v1.md)
defines a synthetic, bias-free batch-16 16→8→4 ReLU network, 160 original
deterministic weights and ten cases across FP16/BF16. The
[fixture producer](../../ci/project/p04_reference.py),
[model manifest](../../ci/project/p04_model_manifest.json), checked host bridge
and source regression tests are implemented. Their acceptance scope is
`source_present`; composed model execution is covered by the subsequent P04-T02
records below.

Each model run executes one `(16,8,16)` hidden matmul and two `(8,4,8)` output calls,
using the accepted [P03 signatures](../../ci/project/p03_operator_manifest.json).
ReLU, exact format conversion and row assembly are declared host work, with
actual outputs feeding each dependent operation and no CPU matmul fallback.
Other native operator families remain unavailable. The
[P03 handoff](p03-operators-handoff.md) retains the trusted runner boundary and
the absence of general partial-DMA rollback or physical recovery proof.

**P04-T02 is complete**, with accepted
[numerical execution](evidence/p04-executor/acceptance-numerics.json) and
[dispatch/transfer evidence](evidence/p04-executor/acceptance-dispatch.json).
The fresh four-variant matrix at `c9d139cc9f84839b6a56b6228dd304460cbfe45c`
passed 20 case/backend pairs, 40 model runs, 120 launches and 600 event/profile
pairs, plus 1,816 host tests. The [executor packet](evidence/p04-executor/README.md)
retains exact intermediate/output comparisons, actual-input lineage, complete
source/build records, independent review and replayable original archives.
Earlier cache-preparation and missing-stamp failures remain separately recorded.

**P05-A01 now accepts the first copying Python binding** at
`e1420fd550f716df33a2556057b7086a03032cbe`; its
[acceptance record](evidence/p05-python/acceptance-binding.json) and
[execution packet](evidence/p05-python/README.md) retain the two-format installed
SimX matrix, clean packaging, ownership/error tests and independent audits.
The matrix has 144 combined Python/native launches and 660 event/profile pairs;
the clean hosted suite passed 2,174 tests at that source revision.

**Parallel task: P05-T01 — independently review the scoped PyTorch custom-op
qualification.** Use the [handoff](p05-entry-handoff.md),
[binding contract](../designs/python_binding_v1.md) and
[compatibility matrix](p05-python-compatibility.md). The implementation and
successful prior installed CI jobs exist; independent original-artifact review
and acceptance remain outstanding, as recorded in the
[current audit](p06-benchmark-audit.md). This continuation makes no new P05
acceptance decision. P05 remains `in_progress`; A02/A03 are unearned and no
PyTorch version has accepted qualification.
The [executor audit](p04-executor-audit.md) retains the unresolved inherited
267 → 283 DSP area-gate failure; Python qualification does not resolve it.

The [ordinary WMMA handoff](p02-wmma-handoff.md) and
[P02-A02 record](evidence/p02-wmma/acceptance.json) bind full-processor checks to
clean source `58faf6d68879e1db92122df493172eab59c02458`: 88 cases, 176
case/backend executions, 352 launches and 14,336 exact output words passed.
The 20 original layout cases are unchanged; 68 numerical cases cover normal,
edge, cancellation and K-traversal behavior. The scope remains RV64 ordinary
FP16/BF16-to-FP32 WMMA, initial C = +0, K = 8 or 16 and an `8 x 4 x 8` tile.
Native TFR tensor and STD scalar floating-point paths are checked; integer DPI
helpers remain. The separate actual API matrix met 47 expectations across 94
WMMA/WGMMA contexts, including 30 intended compiler rejections.

The first 1,448-test offline run retained one source-contract failure. The
reporting-only child `c9cf9ba0730f236e110a1d48a54d8f47a9faf9af` restores the
legacy random-path report. Its exact patch passed the focused test and 15 adapter
tests. Its full suite passed all 1,448 tests, and the rebuilt hosts repeated
all 352 launches and 14,336 exact comparisons successfully. The independent
recovery review and passing hosted CI are recorded in [status](status.md),
with the original fresh processor revision retained separately.
The earlier [numerical handoff](p02-numerics-handoff.md) and
[A01 record](evidence/p02-numerics/acceptance.json) retain the completed T01
contract and original leaf/model/compiler evidence.

P02, P03 and P04 are `complete` within their accepted scopes.
The vendor P01-T05/P01-A03 obligation still blocks **P01 completion and P07**.
The preserved [entry decision](p02-entry-handoff.md) permits native development
without turning the missing vendor result into a pass.

**Parallel hardware action: resolve P01-T05's vendor `hw_emu` prerequisites.**
P01-A01's clean generated-build and P01-A02's complete six-case native numerical
packet are independently reviewed and accepted. The environment inventory,
immutable toolchain lock, native matrix and bounded runner are implemented.
FP16/BF16 GEMM and TF32 attention pass on both SimX and native processor RTL;
the fresh FP16 SimX build and supplemental full-AFU integer `xrtsim` smoke also
pass. Identify a compatible vendor release and supported platform whose required
compiler, simulator, runtime and build inputs fit the recorded resource budget.
Freeze their identities and retain matching build artifacts with producer
commands, input hashes and exit results. Independently review the execution
runner's own manifest/receipt before bounded supervised DMA/launch/completion
execution.
Preserve the earlier GCC 14 spdlog/fmt and missing-`ccache` failures.

Follow the [P01 runbook](p01-baseline-runbook.md). The two-worker budget, 15 GiB
disk reserve and per-command memory/log/time limits remain part of the packet.
The [vendor integration guide](p01-xrt-integration.md) now provides the executable
P01-T05 `probe`/`plan`/`run` route. Its strict receipt and artifact checks prepare
the missing vendor run; they do not replace it or grant acceptance.
It requires its own manifest/receipt, CLI budgets and fresh build directory;
there is no automatic adapter from the read-only `hwemu.py` candidate.
P00, P02, P03 and P04 are complete, P01 remains blocked on A03,
P05 and P06 are `in_progress`, and P07–P11 remain `not_started`. Check the actual
execution state and accepted reports before extending the baseline:

```sh
git status --short
git rev-parse HEAD HEAD^{tree}
git submodule status --recursive
python3 ci/project/preflight.py --tier governance
python3 ci/project/preflight.py --tier simulation --json
```

A blocked simulation preflight is a list of prerequisites, not permission to
install everything automatically. The [developer guide](developer-guide.md)
defines separate tool directories, build trees, resource checks and safe cleanup.
Commands in this backlog are instructions; observed outcomes and current blockers
belong in [status](status.md) and the reviewed phase evidence.

### Current supplemental P01 tensor-oracle hardening

Use the [tensor-oracle guide](p01-tensor-oracles.md) and
[evidence index](evidence/p01-tensor-oracles/README.md) to review comparator and
accumulator corrections, independent FP16/BF16 fixtures, modular integer references
and strict selection/replay checks. Retain failed attempts and exact selections;
empty runs or disabled formats cannot establish coverage.

Matrix/full-suite source: `ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`; native matrix: **pass — nine builds, 62 commands and 95 CLI checks**;
full tooling suite: **1,272 tests passed, zero failures/errors/skips in 336.269 seconds**. At that checkpoint,
P01-T05/P01-A03 remained blocked and P02–P11 were `not_started`. The later
staged-entry decision opens P02 without changing those test outcomes.

### Supplemental local AFU/RTL qualification continuation

The [local qualification guide](p01-local-qualification.md) provides the
implemented [runner](../../ci/project/local_qualification.py) for generated-build
XRT/local-`xrtsim` full-AFU applications and focused RTL unit harnesses. Fixed
integer, reopen and AXI-memory cases plus explicitly selected FP16/BF16 GEMM
retain their source-backed checks and inherited reference tolerances. This
continuation resolves the stencil block-size parser, child temporary-directory
placement and helper-drift diagnostics. At frozen source `7e4ac585`, all eight
selected cases pass across 32 monitored commands; the separate tooling suite
passes 1,260 tests in 293.241 seconds.

Use the [qualification handoff](p01-local-qualification-handoff.md) for exact
scoped results, test counts, tested revisions, retained failures and not-runs.
CP/LLC unit-oracle hardening is implemented at `143c69fe`: all 37 original
assertions and six functions remain, three isolated mutation faults are
detected, and both unit selections pass in a fresh five-command packet. Its
focused CI guardrail test also passes after the reviewed five-to-ten-minute
governance timeout change. The full tooling suite and eight-case matrix were
not rerun at this follow-up revision.
Local shim memory and DPI-assisted integer arithmetic remain explicit limits.
This supplemental route does not satisfy vendor P01-T05/P01-A03 or itself
authorize later-phase work. The separately accepted P01-A01/A02 reports now
authorize **P02 entry only**, through the machine-validated staged-entry rule;
qualified vendor release/platform and matching build provenance remain needed
before P01 completion/P07.

## Priority 1 — P01 baseline work

Short `Txx` dependency references use the work item's own phase prefix.

T01/T02 have executable tooling and a frozen contract. T03/T04 are supported by
the accepted [clean-build](evidence/p01-build.json) and
[six-case numerical](evidence/p01-native.json) reports. T06 has retained and
independently reviewed the compact packet, historical failures and attention SS
coverage correction. T05 remains [blocked](evidence/p01-xrt-blocked.json) by
missing vendor `hw_emu` tools/platform. No phase-completion change is justified
while T05 remains blocked. The [handoff](p01-handoff.md) records exact source/tool
identities, review boundaries and the next integration obligation.

T05 now has read-only [inventory/planning tooling](../../ci/project/hwemu.py),
a [vendor-emulation runbook](p01-hwemu-runbook.md), a strict
[manifest/receipt contract](p01-hwemu-manifest.md) and a
[preparation handoff](p01-hwemu-handoff.md). Source, submodule, generated-build,
artifact and resource checks describe a candidate without launching it or
qualifying the vendor environment. The XRT source hook path is corrected and
waveform collection is opt-in. This preparation supplies no new GPU/vendor or
physical result; `planned` does not close T05 or P01-A03.

The reviewed **F1 compiler-glob follow-up is resolved** by the shared
[compiler-record validator](p01-compiler-records.md). It rejects pathname patterns
instead of expanding them and checks actual compiler option boundaries. The XRT
execution inspector now checks each runtime, kernel and host record independently;
definitions consumed as operands or supplied only by another record cannot
establish the frozen configuration. Exact kernel ISA/ABI and generated-runtime
linker checks accompany the correction. Real compiler and generated-Make oracles,
negative cases and runner-boundary tests support the implementation; the
[verification record](evidence/p01-compiler-records/verification.json) and
[compiler-record handoff](p01-compiler-records-handoff.md) retain its tested identity,
review and delivery state.

This completes a bounded T05 tooling correction. Actual producer records,
vendor/platform qualification and independently reviewed effective invocations
remain required before supervised execution. The preparation candidate gains no
launch readiness, T05 remains blocked on vendor integration, and P01 gates remain
unchanged.

| Work item | Deliverable and completion check | Prerequisite / accountable role | Gate supported |
|---|---|---|---|
| **P01-T01 — Environment manifest** | Record exact source/tree and dirty state, all submodule commits, source pins and resolved tool/bundle identities, host/tool availability, effective RAM, free-disk reserve, job/runtime limits and retained-artifact budget. Missing access or licenses remain named blockers. | P00 accepted; verification lead | P01-A01 |
| **P01-T02 — Native matrix** | Freeze a small list of catalog IDs, XLEN, TFR/native versus DPI, dtypes/accumulation, warp geometry, dimensions, reference checks and expected failures. Record the full effective application/backend configuration and review any coverage gaps before adding cases. | T01; compute architecture lead with verification lead | P01-A02 |
| **P01-T03 — Clean build** | Prepare only the approved pinned dependencies, initialize exact submodules, configure a dedicated out-of-tree variant and build the selected path. Retain command exits, tool identities and generated-config hashes; reproduce from a clean checkout. | T01/T02 and resource/access approval; build/toolchain lead | P01-A01 |
| **P01-T04 — Native numerical baseline** | Run selected cases one at a time on SimX and matching native processor RTL. Preserve CPU-reference checks, output logs, exact numerics and applicable parity evidence. Add a focused regression for a missing required combination; do not alter inherited cases to reduce coverage. | T03; verification lead | P01-A02 |
| **P01-T05 — Full AFU integration** | Qualify the vendor release/platform, retain an actual matching build packet, check its strict manifest and review the candidate before bounded supervised `hw_emu` execution. Prove DMA, launch and completion with retained logs/configuration, or preserve an explicit blocked record. Planning, processor-only `rtlsim` and supplemental local AFU/unit results do not close this item. | T03/T04 plus platform/license access; FPGA platform lead | P01-A03 |
| **P01-T06 — Reviewed baseline packet** | Assemble hashes, exact commands/results, native/DPI distinctions, failures and limitations; obtain independent review, attach each satisfied gate, and update status plus the next task. Close P01 only when all three gates pass. | T01–T05 evidence; verification lead / maintainer | P01-A01, P01-A02, P01-A03 |

### Frozen catalog-derived matrix

[`p01_baseline.json`](../../ci/project/p01_baseline.json) is the execution contract.
Its strict [loader](../../ci/project/baseline_matrix.py) checks paired coverage,
native arithmetic, dimensions and inherited numerical tolerances. Both drivers
use the same explicit configuration for each workload; native RTL coverage added
by the matrix is identified as derived coverage, without changing inherited cases.

| Catalog source | Frozen P01 coverage |
|---|---|
| [`tensor.yaml`](../../ci/testcases/tensor.yaml): `sgemm_tcu-3` | FP16-to-FP32 GEMM, `64 × 64 × 64`, on SimX and processor RTL |
| Same catalog: `sgemm_tcu-4` | BF16-to-FP32 GEMM, `64 × 64 × 64`, on SimX and processor RTL; the existing DPI RTL case is not a substitute |
| [`tensor_wg.yaml`](../../ci/testcases/tensor_wg.yaml): `flash_attn_tcu_wg-rtlsim` | RV64 TF32-to-FP32 attention, `-N 32 -D 16 -c 8 -t 8`, on both drivers; no FP16 attention result is implied |

Use [baseline.py](../../ci/project/baseline.py) to plan and execute these six
cases after following the runbook. A plan or a partial selected run cannot close
P01. Preserve the separate native processor and full-AFU integration obligations.

After the environment is prepared, inspect selection from the **configured build
tree**, without running the workloads:

```sh
python3 -m pytest ci/test_runner.py --collect-only -q -m 'tensor and simx' --strict-markers
python3 -m pytest ci/test_runner.py --collect-only -q -m 'tensor_wg and rtlsim' --strict-markers
```

Collection requires the catalog's pytest/PyYAML environment and is not a build or
numerical pass. Record the selected node IDs, review their cost, then execute only
the approved nodes. The generated `ci/regression.sh --test '<marker expression>'`
runs a **slice**, potentially many cases; it is not automatically a bounded smoke
test. Do not use `--all` as the first baseline run. Any proposed `ai-dev` profile
remains an unqualified candidate until its selected configuration earns evidence.

## Priority 2 — Active native AI software track

P02-T01 is complete with reviewed source-level P02-A01 evidence. P02-A02 has
accepted full-processor ordinary WMMA arithmetic/layout and API rejection
evidence. P02-T02 is complete with independently reviewed A03 acceptance for the
bounded WGMMA execution and protocol evidence. P03-T01 retains source-level A01
acceptance; P03-T02 now has accepted A02 numerical and A03 lifecycle evidence,
completing P03 for the declared six signatures. P04-T01 is complete with
source-level P04-A01 acceptance. P04-T02 now has accepted A02/A03 execution and
trace evidence for the fixed model, completing P04 at bounded processor RTL
scope. P05-A01 now accepts the bounded copying Python binding; P05-T01 remains
in progress for the scoped framework route. P06-T01 is also in progress, with
[P06-A01 accepted](evidence/p06-baseline/acceptance.json). Original serial-workspace
correctness has [independent artifact review](evidence/p06-warm-workspace/README.md).
The [transport handoff](p06-mpm-transport-handoff.md) tracks the RV64 counter
repair's separate integration/publication history. The
[simulator completion prerequisite](p06-simulator-completion-audit.md) now has
independently reviewed host and fresh native evidence for the repaired CP-error
boundary at `4781ca9`. The [checked-counter prerequisite](../designs/simx_checked_counters_v1.md)
is implemented, and the [diagnostic packet](evidence/p06-counter-diagnostics/README.md)
now covers all 33 available selectors plus native public failure/coherence cases.
The [historical managed preflight and replay](evidence/p06-managed-preflight-replay/README.md)
retain the preceding four-process original. The later
[native lifetime witness](evidence/p06-native-lifetime/README.md) adds executed
pending-balance, run/reset and disposal observations without claiming full
qualification. The [provenance packet](evidence/p06-dependency-provenance/README.md)
now records implemented producers, full application admission and complete inert
readers. Follow the [dependency handoff](p06-dependency-provenance-handoff.md) to
collect and independently replay/review the fresh dependency/native original,
then independently review the complete
qualification path before a fresh matched warm attempt.
Detailed work packages remain in the
phase guides, the [development audit](p05-binding-audit.md) and the
[Python binding handoff](p05-entry-handoff.md).

| Work item | First bounded deliverable | Entry / accountable role | Gates |
|---|---|---|---|
| **P02-T01 — Arithmetic contract — complete** | Reviewed v1 FP16/BF16-to-FP32 semantics, runnable T4 application profile, 98 independent arithmetic fixtures and 20 layout fixtures; frozen comparisons and inherited tolerances preserved. | P00 plus accepted P01-A01/A02; compute architecture lead | [P02-A01 source evidence](evidence/p02-numerics/acceptance.json) |
| **P02-T02 — Arithmetic and concurrency proof — complete** | Ordinary WMMA and bounded WGMMA native-unit/full-processor arithmetic, metadata witness, directed pressure and declared parity evidence are independently reviewed and accepted. | T01; verification lead | [P02-A02 accepted](evidence/p02-wmma/acceptance.json); [P02-A03 accepted](evidence/p02-wgmma/processor/acceptance.json) |
| **P03-T01 — Operator contract — complete** | Versioned manifest, exact six format/shape signatures, checked descriptor planner, 56-byte argument encoding, explicit unavailable categories and required ownership/completion rules; source-level validation only. | P02; kernel and runtime lead | P03-A01 |
| **P03-T02 — Operator implementations and lifetime tests — complete** | Managed six-signature matmul has independent SimX/native-RTL arithmetic and actual common-runtime lifecycle acceptance; exact scope and partial-transfer limits remain recorded. | T01; kernel and runtime lead | [P03-A02](evidence/p03-managed-matmul/acceptance-numerics.json), [P03-A03](evidence/p03-managed-matmul/acceptance-lifecycle.json) |
| **P04-T01 — Fixed tiny model — complete** | Fixed nonlinear MLP, ten deterministic FP16/BF16 cases, independent exact references, manifest, placement contract and checked host bridge have reviewed exact-source/host qualification. | P03; model runtime lead | [P04-A01 accepted at source scope](evidence/p04-fixture/acceptance.json) |
| **P04-T02 — Native model execution — complete** | Four clean SimX/native processor RTL × FP16/BF16 variants pass exact intermediate/final comparisons, live-input lineage, native placement and separate host/transfer accounting after independent review. | T01; model runtime lead | [P04-A02](evidence/p04-executor/acceptance-numerics.json), [P04-A03](evidence/p04-executor/acceptance-dispatch.json) |
| **P05-T01 — Python/custom-op bridge — in progress** | Preserve the accepted copying binding; independently review the existing custom-op implementation's installed dispatch, compatibility and explicit failure evidence before an acceptance decision. | P04; framework integration lead; [handoff](p05-entry-handoff.md) | [P05-A01 accepted](evidence/p05-python/acceptance-binding.json); P05-A02/P05-A03 unearned |
| **P06-T01 — Measured optimization — in progress** | Collect a complete fresh dependency/native original through the implemented provenance and full application-admission route; retain separate controls and independently verify the exact original with the complete inert readers. Preserve historical lifetime evidence and finish separate complete qualification before the unchanged warm matrix. | P04; performance and memory lead; [dependency handoff](p06-dependency-provenance-handoff.md), [qualification plan](p06-mpm-qualification-plan.md) | [P06-A01 accepted](evidence/p06-baseline/acceptance.json); [A02/A03 open](phases/p06-performance.md) |

Use [P02](phases/p02-tensor.md), [P03](phases/p03-operators.md),
[P04](phases/p04-inference.md), [P05](phases/p05-framework.md) and
[P06](phases/p06-performance.md). A custom-op
bridge is not a full device backend, CUDA compatibility, autograd or training.

## Later work — gated, not forgotten

| Queue | First decision or deliverable | Entry / accountable role |
|---|---|---|
| **P07-T01 — One physical FPGA** | Obtain an authorized board/platform decision; prove usable memory, DMA and the model on `hw`, followed by the specified initial soak. | P01/P04/P06; FPGA platform lead; [P07 gates](phases/p07-fpga.md) |
| **P08-T01 — Experimental release qualification** | Freeze a threat/failure model, test recovery/isolation, complete the specified physical soak and reproduce the release packet. | P05/P07; reliability and release lead; [P08 gates](phases/p08-reliability.md) |
| **P09-T01 — Optional research branch** | Select a bounded training/gradient workload and two-device transport experiment; obtain physical correctness evidence before scaling claims. | P08; research lead; [P09 gates](phases/p09-research.md) |
| **P10-T01 — ASIC feasibility decision** | Qualify PDK/macros/IP/package/tool access and owners; develop sign-off, cost and risk evidence for a human go/no-go decision. | P08; silicon program lead; [P10 gates](phases/p10-asic.md) |
| **P11-T01 — Authorized silicon program** | Only after funded approval, complete qualified sign-off/manufacturing and measured board/silicon bring-up. | P10; silicon program lead; [P11 gates](phases/p11-silicon.md) |

P09 is not a prerequisite for the bounded inference-ASIC route. No queue entry
authorizes purchases, paid IP, partner commitments or tapeout. Resolve open
[decisions](decisions.md) and [risks](risks.md) before those commitments.

## Stop and hand off correctly

Stop an affected item for missing access/budget, stale or mismatched configuration,
unexplained numerical differences, hidden CPU fallback, resource overrun or absent
required evidence. Preserve failures; never widen tolerances, edit goldens or
rename emulation as physical hardware to close work. Follow [acceptance](acceptance.md).

Every work-item handoff records the actual owner, exact revision/configuration,
commands and observed outcomes, compact hash-checked artifacts, review disposition,
unresolved blockers and **one next bounded action**. Update the canonical phase
evidence and [status](status.md) together. A completed task or agent count alone
does not complete its phase.
