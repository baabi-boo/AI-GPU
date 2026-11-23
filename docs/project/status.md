# Current project status

**P06-A01 is [accepted at simulated scope](evidence/p06-baseline/acceptance.json);
P06 and P06-T01 remain `in_progress`.** Independent original-artifact review
qualifies the eight-workload baseline at `84b6ca0ca75fba248ba330642bbf8764db3d459c`,
[run 44901052221, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44901052221):
48 processes and 72 launches, including 40 measured processes and 60 measured
launches. The [qualification audit](p06-qualification-audit.md),
[packet](evidence/p06-baseline/README.md) and
[analysis contract](../designs/native_baseline_analysis_v1.md) record the accepted
scope and new validation. P06-A02/A03 remain open.

The current continuation implements the [complete inert managed-preflight
reader](../designs/managed_counter_preflight_replay_v1.md). It rechecks the
successful original at `57248e73dfce4ae2d21d2cbdb82c3953eef2e3db`,
[run 45085300171](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171):
four FP16/BF16 × policy processes, **132 launches and 4,224 exact output words**.
The [evidence packet](evidence/p06-managed-preflight-replay/README.md) separates
that historical native execution from current replay. The next native task is
the missing pending-read and per-run/reset witness described in the
[handoff](p06-managed-preflight-handoff.md); complete qualification remains open.

The [clean governance packet](evidence/p06-managed-preflight-replay/local-governance/5d2b2df/files.json)
records **3,725 tests passed in 2,528.577 seconds**, with all four commands
exiting 0 and a clean checkout before and after, at local `5d2b2df` (complete
tree equivalent to published `150f9d551`). The later standalone exporter repair
and eight added tests are covered by the separately retained
[203-test dedicated workflow](evidence/p06-managed-preflight-replay/local-replay/f88cccff/files.json)
at local `f88cccff` (tree equivalent to `9c9a8ec6`), completed in 351.775 seconds.
The [completion summary](evidence/p06-managed-preflight-replay/completion-summary.md)
and independent reviews preserve those distinct execution scopes; no full suite
at the later revision or hosted CI pass is inferred.

The [serial workspace prerequisite](../designs/serial_matmul_workspace_v1.md)
is implemented, and the [reviewed original correctness packet](evidence/p06-warm-workspace/README.md)
binds eight processes, 32 launches, 1,024 exact output words and 60 reconciled
tensor-buffer lifetimes to `13dc0d1fdb6d5322104e381aa342dc139c7bb80c`,
[run 44925627664](https://github.com/baabi-boo/AI-GPU/actions/runs/44925627664).
That historical artifact review establishes its declared correctness scope;
it is not a new execution or performance acceptance.

The [current transport audit](p06-mpm-transport-audit.md) repairs the RV64 host
counter high-half defect in SimX and RTL. The
[reviewed native packet](evidence/p06-mpm-transport/reviews/native-review.md)
verifies all eight candidate cells and both numeric parent failures at `18c8880`;
its immutable governance suite passes 2,910 tests. Eight Beacon and eight generic
Yosys measurements are complete. The
[alternative review](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the specific comparison finding and retains the direct `18c8880` decoder;
raw RV64 area failures remain failures. The
[handoff](p06-mpm-transport-handoff.md) retains that repair's separate integration
and publication history.

The [completion audit](p06-simulator-completion-audit.md) identified a prerequisite:
execution faults must reach public waits before a future counter guard can be
trusted. The [implementation](../designs/simulator_completion_v1.md) now consumes
asynchronous results, preserves the first busy edge, keeps processor failures
terminal and clears abandoned channel accounting at complete platform disposal.
It also preserves the inherited recoverable CP-copy allocation-error path.
At repaired checkpoint `4781ca9`, **83 focused host tests**, the eight compiled-parent
failure controls and the fresh dedicated native completion controls pass.
Independent original-artifact review binds native execution to the exact repaired
tree. Both repaired-checkpoint Project Governance runs passed **2,993 tests each**,
including the 83 focused completion tests, with independent original-log review.
The earlier `db5ebb3` native and 2,988-test receipts remain historical. The
[evidence packet](evidence/p06-simulator-completion/README.md) records each result's
source and scope, including the later documentation/evidence source projection.

The [checked-counter prerequisite](../designs/simx_checked_counters_v1.md) is now
implemented in published checkpoint `9fd7eac203c77fa54c7af80fa0220ae09553cd55`.
It guards the selected SimX storage and formed aggregates, raising typed errors
through the existing terminal processor-failure path. Ordinary builds retain
the exact `uint64_t` alias. The [development audit](p06-checked-counters-audit.md)
separates the actual **3,062-test hosted governance pass** from the independently
reviewed five-cell native pass, both at `9fd7eac20`. The native run is
`45017731063`, attempt 1; the [governance receipt](evidence/p06-checked-counters/hosted/governance-index.json)
records run `45017731138`, attempt 1.

The subsequent [diagnostic continuation](p06-counter-diagnostics-audit.md) closes
the declared native source and public-runtime gaps. Its latest independently
audited original at `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, run
`45034575685`, passes **13 native process cases**: seven model cases plus six
public-runner cases. All **33
available selectors and 40 backing components** are exercised; twelve
unavailable L2/L3 rows remain unqueried. The
[evidence packet](evidence/p06-counter-diagnostics/README.md) keeps original
native execution, host governance and inert replay validation distinct, including
the earlier corrected `e5f1524` native pass and its 3,158-test host receipt.
The new [completed hosted original](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json)
executed 3,312 tests and failed two isolation-guard tests. The test-only repair
is independently reviewed and published at `142b2d6`. Its subsequent
[clean local full suite](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json)
passes **3,318 tests in 1,918.414 seconds on CPython 3.12.14**, with independent
source/log review. Hosted and native retries were queued at the
[retained receipt's checkpoint](evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json),
which contains no executed result for either retry. This is local governance
verification; the latest audited native diagnostic scope stays at `4268d2d5`.

**Next bounded development:** implement and independently review the
[versioned native lifetime witness](p06-managed-preflight-handoff.md): read-only
pending-read observations at all 33 run/reset boundary pairs, each required
flush, terminal readout and actual destruction, with exact reset increments.
Apply the [conditional lifetime argument](../designs/simx_counter_lifetime_v1.md)
to the bound 33 selectors and 40 checked components. Fresh dependency
source/compile/link/product receipts connected to the actual loaded libraries
remain a separate prerequisite. The current four-process original and its
replay do not contain those missing observations. The broader
[qualification plan](p06-mpm-qualification-plan.md) still requires a separately
reviewed admission/final-validation path before the unchanged fresh warm matrix.
The [implemented warm v1 contract](../designs/warm_workspace_benchmark_v1.md)
remains unconditionally blocked by `P06-WARM-RV64-MPM-HIGH-HALF`, with
`qualified=false` and `absolute_no_wrap_bound="not_established"`. No warm
speedup or new P06 gate is established by this continuation.

**P04 is complete for the fixed tiny-model contract.**
[P04-A01](evidence/p04-fixture/acceptance.json) retains its accepted source scope;
[P04-A02](evidence/p04-executor/acceptance-numerics.json) and
[P04-A03](evidence/p04-executor/acceptance-dispatch.json) accept native execution
and placement at bounded processor RTL scope. The synthetic, bias-free batch-16
`16 → 8 → 4` ReLU MLP uses ten frozen FP16/BF16 cases, independent integer
references and the unchanged [manifest](../../ci/project/p04_model_manifest.json).

Fresh qualification at `c9d139cc9f84839b6a56b6228dd304460cbfe45c` passed all four
SimX/native processor RTL × FP16/BF16 variants: **20 case/backend pairs,
40 model runs, 120 native launches and 600 event/profile pairs**. Independent
numerical, dispatch and provenance reviews reconcile actual intermediate/output
bits, live bridge inputs, source/build identities, cleanup and transfer accounting.
The complete host suite passed **1,816 tests in 366.568 seconds** at the same
revision. The [executor packet](evidence/p04-executor/README.md) retains the
original archives, failed attempts, exact auditors and successful relocated replay.

**P05-T01 remains in progress; its plain-Python binding now has
[P05-A01 acceptance](evidence/p05-python/acceptance-binding.json).** The
[installed SimX packet](evidence/p05-python/README.md) binds the supported
representations, ownership/error checks and clean installation to
`e1420fd550f716df33a2556057b7086a03032cbe`. The scoped PyTorch custom-op route now
has an implementation and successful prior installed CI jobs; its independent
artifact review remains outstanding, as recorded in the
[current audit](p06-benchmark-audit.md). The [binding handoff](p05-entry-handoff.md)
retains the earlier contract. This continuation makes no new P05 acceptance decision.
P05-A02 and P05-A03 remain unearned; this result establishes no framework backend
or physical GPU performance.

**P03 is complete with independently reviewed A01–A03 evidence.** The
[historical operator contract](evidence/p03-operators/acceptance.json) remains
accepted at source scope. The [numerical acceptance](evidence/p03-managed-matmul/acceptance-numerics.json)
and [lifecycle acceptance](evidence/p03-managed-matmul/acceptance-lifecycle.json)
complete P03-T02 for six ordinary FP16/BF16-to-FP32 matmul signatures. They bind
actual SimX/native processor RTL dispatch and actual RV32/RV64 SimX lifecycle
results to clean source `319ad63532cee17ae88fa75757a5ac87ed5c6a77`.
The [P03 handoff](p03-operators-handoff.md) supplies the accepted operator inputs
and ownership rules for the selected P04 network.

**P02 remains complete.** Its reviewed [contract](evidence/p02-numerics/acceptance.json),
[ordinary WMMA](evidence/p02-wmma/acceptance.json) and
[WGMMA](evidence/p02-wgmma/processor/acceptance.json) evidence retain their
original numerical, metadata/backpressure and declared parity scopes.

P02 entered development through the user-directed staged-entry decision.
P01-A01 and P01-A02 are accepted, while P01 itself remains blocked on vendor
`hw_emu` (P01-A03). This blocks completion of P01 and acceptance of P07,
**not** the P02–P06 software/RTL development chain.
At the accepted historical revision, all six frozen numerical executions pass
from a clean GPU source checkout. The fresh generated FP16 SimX build and
supplemental full-AFU integer `xrtsim` smoke also pass. Independent reviews accept
the clean-build and native numerical packets. Qualified vendor tools/platform
are still missing for P01-A03. P00, P02, P03 and P04 are complete,
P05 and P06 are `in_progress`, and P07–P11 remain `not_started`.
[roadmap.json](roadmap.json) remains authoritative for phase state and evidence;
the linked reports define the exact accepted scope.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `complete` | Its three source-level acceptance gates and verified default-branch delivery remain preserved |
| P01 — reproducible baseline | `blocked` | A01 clean-build and A02 six-case numerical reports accepted; A03 vendor integration is still required before P07 |
| P02 — tensor numerical contract | `complete` | A01 source contract, A02 ordinary WMMA and A03 bounded WGMMA evidence accepted after required review; T01/T02 complete |
| P03 — native AI operator library | `complete` | T01/T02 complete; A01 manifest/ABI, A02 actual native arithmetic/dispatch and A03 simulated lifetime/error/resource evidence accepted |
| P04 — tiny-model inference | `complete` | A01 fixed fixture preserved; A02/A03 accept the full four-variant composed-model matrix at native processor RTL scope |
| P05 — Python/framework bridge | `in_progress` | A01 accepts the bounded copying Python binding on SimX; the custom-op implementation and prior CI still need independent artifact review for A02/A03 |
| P06 — Memory and performance scaling | `in_progress` | A01 and prior prerequisites remain preserved; all-33 native/public diagnostics pass in their declared scope, while actual seed-free measurement/full-caller qualification, loaded dependency provenance and A02/A03 remain open |
| P07–P11 | `not_started` | Later hardware, reliability, research and silicon gates have not been earned |
| Full vendor XRT `hw_emu` | `blocked` | Required vendor tools, identified platform and matching integration artifacts are unavailable |
| Physical FPGA / custom silicon | Not qualified | No physical board or fabricated silicon measurements are established |

Execution and integration owner for this continuation: the primary coding agent
(`/root`). Independent agent reviews supply scoped engineering evidence; they
are not invented human approvals or waivers.

## Latest continuation — complete managed-preflight archive replay

The [development audit](evidence/p06-managed-preflight-replay/development-audit.md)
identified the missing complete reader after the managed producer had already
emitted its successful original. The new reader takes seven external inputs:
the archive and its digest, source revision, source inventory and its digest,
and an independent Git-object derivation receipt and its digest. It rechecks
**999 retained source bodies and 17 payload bodies**, complete report/command
and hosted-envelope inventories, build identities, loader observations, all
four process logs, lifecycle records and before/after stability. It never
executes retained code or commands or opens recorded producer paths.

The reader closes three demonstrated consistency gaps: the application must
have all 30 required commands per format; the four generated headers and full
compiler flags must reproduce from pinned current trusted inputs; and each
backend log must contain exactly 46 records in valid prerequisite order.
The 43 model object identities per format have descriptors but no retained
bodies; their absent bytes are not claimed to have been rehashed. Cached
library identities do not prove dependency compilation provenance.

The correctly pinned failed original at
`8756f40029e59c87546fa22f4da33acd4e5d8e02`,
[run 45084009157](https://github.com/baabi-boo/AI-GPU/actions/runs/45084009157),
remains rejected with **`report.outcome: value differs`**. Its application build
failed before managed execution. The new host-only
[replay workflow](../../.github/workflows/p06-managed-preflight-replay.yml)
requires that exact rejection, not an arbitrary nonzero exit.

Independent [core/backend review](evidence/p06-managed-preflight-replay/agents/w04_a06.md)
passed 20 core and 15 backend tests on its recorded snapshot. Subsequent
[archive-loader review](evidence/p06-managed-preflight-replay/agents/w05_a03.md)
verified the managed reader's direct compilation of hash-checked current source
instead of cached bytecode: three new tests and two changed isolation methods
passed, with one method also repeated alone in a fresh interpreter. These
scoped runs are not added together as a final integrated suite. The
[evidence index](evidence/p06-managed-preflight-replay/README.md) retains the
other reviews and final verification/publication follow-ups; no new hosted or
complete-suite pass is asserted here.

All seven fields remain false: `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance`, and
`performance_acceptance`. The unresolved obligations remain
`all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance`, and
`independent_complete_counter_qualification`. Replay reports
`native_execution="not_run"` and `retained_code_executed=false`. The
[next native handoff](p06-managed-preflight-handoff.md) specifies the missing
witness and separate dependency evidence without promoting any acceptance.

## Previous continuation — native counter diagnostics and inert replay

The [audit](p06-counter-diagnostics-audit.md) began at
`7455e008c1e001d3329e74fd55ffcd942592ec5f`. The
[model diagnostic contract](../designs/simx_counter_diagnostics_v2.md) extends
the earlier nineteen-selector coverage through actual backing storage, including
distinct D-cache banks and private TCU buffers. Each ordinary/checked boundary
variant exercises all 33 available selectors and 40 components with **6,389
checks and 1,788 half reads**. Seven model cases cover boundaries and separate
Core, cache aggregate, pending primitive, cache backing and TCU backing faults.
The twelve unavailable L2/L3 rows receive no query.

The [public diagnostic contract](../designs/simx_counter_public_diagnostics_v1.md)
adds five actual Processor/RAM modes: normal, immediate overflow, delayed
overflow, cache overflow and coherent terminal readout. Its build boundary
control is a sixth public-runner case. The corrected
[original native packet](evidence/p06-counter-diagnostics/native/index.json)
at `e5f1524`, [run 45031746149](https://github.com/baabi-boo/AI-GPU/actions/runs/45031746149),
passes all thirteen combined process cases and has
[independent original-artifact review](evidence/p06-counter-diagnostics/reviews/wave07/w07-native-public-audit.md).
Public observations retain ten actual Processor constructions/disposals and
seven complete terminal vectors: 231 selector queries and 462 successful half
reads, plus one separately failed cache half read. Seeded terminal values and
fresh unseeded scalar controls remain distinct from full managed matmul execution.

The latest [native run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685),
attempt 1, job `137245341329`, separately passes all thirteen cases at
`4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, tree
`061ecbddc9b321edbd70c054c8efce4d188de04f`. Its
[independent original-packet audit](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
checks the 1,046-member archive, matches 270 model and 683 public source bodies
against immutable Git, and reconciles the same public observation counts.
Model replay and public replay with the explicit Git-pinned 683-source manifest
pass. The original fixed 676-name public route rejects the expanded packet;
the earlier corrected pass locator remains unchanged.

The [lifetime argument](../designs/simx_counter_lifetime_v1.md) supplies a
conditional source proof for the selected route. A successful terminal checked
sum bounds prior nonnegative monotone sums only when zero origins, admitted
updates/resets, stable storage and no later update are established for the
entire context lifetime. Actual loaded dependency provenance and every full
warm-caller terminal premise remain unqualified. Recorded library/tool identities
alone do not establish absent payloads or cached compilation origin.

The offline model/public readers and explicit source-inventory helper were
published at `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`. They consume complete
retained source inventories and require an externally supplied exact manifest
digest for the explicit inventory route. Invalid explicit inputs fail closed;
retained code remains inert. Their result is retained-data consistency only,
with `native_execution="not_run"` and `retained_code_executed=false`.

| Separate verification receipt | Observed result | Scope |
|---|---|---|
| [Clean hosted governance at `e5f1524`](evidence/p06-counter-diagnostics/host/index.json), run `45031746158` | 3,158 tests pass in 1,305.183 seconds | Predates the later replay/source-inventory additions |
| [Completed hosted governance at `4268d2d5`](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json), run `45034575638` | 3,312 executed tests in 1,811.712 seconds: 3,310 `ok`, two `FAIL`, no errors or skips; exit 1 | Original failed run; two isolation guards stopped on trusted helper path resolution |
| [Clean local governance at `142b2d6`](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json) | All 3,318 distinct tests pass in 1,918.414 seconds on CPython 3.12.14; all four commands exit 0 | Independently reviewed clean detached source checkout; 365 source records match immutable Git before/after; no hosted or native execution claim |
| [Genuine-original public replay](evidence/p06-counter-diagnostics/reviews/wave07/w07-public-replay-integration-tests.md) | 40 methods / 247 subtests pass | Corrected original archive plus replay rejection controls; no native execution |
| [Source-inventory helper review](evidence/p06-counter-diagnostics/reviews/wave08/w08-source-inventory-review.md) | 48 methods / 278 subtests pass | Explicit expectations, parser and source-inventory rejection |
| [Independent replay integration review](evidence/p06-counter-diagnostics/reviews/wave08/w08-replay-integration-review.md) | 37 methods / 110 subtests pass | Both readers, genuine originals and independent rejection checks |
| [Checked replay review](evidence/p06-counter-diagnostics/reviews/wave06/w06-checked-replay-review.md) | 43 methods / 167 subtests pass | Model retained-data consistency and rejection controls |
| [Affected repair modules at `142b2d6`](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-fix-exec-identity.md) | 89 methods pass in 139.141 seconds | Final two-file test repair; not a full governance run |
| [Independent final repair-method review](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md) | 8 methods / 670 subtests pass in 4.956 seconds | Root-collision and execution-witness controls at the exact reviewed test bytes |
| [Independent compiled-identity/original probes](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md) | 3 methods / 15 subtests pass in 4.437 seconds | Separately executed code-identity and genuine-original scope |

The [independent completed-log review](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/failed-review.md)
confirms that run `45034575638`, job `137245340992`, actually executed all
3,312 discovered IDs at `4268d2d5`, including all 154 additions, with no archive
skips. Its two failed guards rejected current trusted `baseline_inventory.py`
when the GitHub checkout pathname equaled the recorded producer source root;
neither guard completed. The original remains failed. The independently reviewed
test-only repair is published at `142b2d6aaea2fa4226118b857514113032d2e26c`, tree
`754ef8577f9a72785c0809048762c70b16cb4857`, closing both F2 findings. The
[independent clean local review](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/review.md)
now reconciles all 3,318 executed IDs with `ok` results, including both formerly
failed guards and all six added methods, with no failures, errors or skips.
It verifies a clean detached checkout before/after and 365 unchanged source
records against immutable Git. This actual full-suite result is distinct from
the separately scoped focused tests.

The [hosted API observation](evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json)
records run `45040805357`, job `137264592244`, queued at 2026-11-22 16:55:09 UTC,
with no runner, steps or conclusion. Native retry `45040805341`, job
`137264592580`, was also queued at that observation. Neither has an executed
result in this retained receipt; the local suite does not supply a hosted or
native pass. The latest independently audited native diagnostic execution
remains `4268d2d5`.
The [host index](evidence/p06-counter-diagnostics/host/index.json)
preserves the separate concurrent local failure and `81ed687` hosted fixture
failure. The latter exposed an unpinned host interpreter observation; its repair
isolates the controlled fixture while retaining native CPython 3.12.14. The
`81ed687` native public-normal failure separately came from an unsupported host
CP-head writeback assertion; its failed original remains retained. Neither
hosted failure is attributed to concurrent edits.

At that diagnostic checkpoint, the [handoff](p06-counter-diagnostics-handoff.md)
and [qualification plan](p06-mpm-qualification-plan.md) still proposed the
four-process managed-caller preflight. The current continuation above now
records its original execution and complete inert replay; the missing lifetime
and dependency premises remain explicit in the
[new native handoff](p06-managed-preflight-handoff.md). The unchanged
**24-process, 792-launch, 25,344-word** warm attempt still requires separately
reviewed complete qualification. Diagnostic/replay qualification, readiness,
warm execution and acceptance remain false; P06/P06-T01 stay `in_progress`,
A02/A03 open.

## Previous continuation — checked counter prerequisite

The [counter audit](p06-checked-counters-audit.md) selected checked arithmetic as
the next prerequisite after the high-half transport and simulator completion
repairs. `SIMX_CHECKED_COUNTERS=1` checks the actual selected backing counters,
pending-read balance and intermediate reductions before overflow or underflow.
The dedicated `PerfCounterError` follows `run_checked()` and guarded synchronous
processor queries into persistent failure; it does not terminate the process
outside the completion owner. The initial abort candidate was rejected during
independent review and is retained only as historical work.

The [implemented contract](../designs/simx_checked_counters_v1.md) covers audited
stored updates and successfully formed aggregates. It does not claim a complete
context-lifetime bound from process success alone. The
[integrated review](evidence/p06-checked-counters/reviews/integrated-review.md)
found no open F2/F3 in its bounded scope. The
[publication map](evidence/p06-checked-counters/publication.json) records exact
file-tree equivalence between reviewed local and published checkpoints; it does
not relabel earlier executions as runs under a later commit identity.

The implementation-stage runs passed **64 focused host test methods**:

| Suite | Methods | Scope |
|---|---:|---|
| Counter primitive and completion owner | 12 | Release/UBSan arithmetic, unchanged rejected values and actual `AsyncRun` failure retention |
| Production statistics integration | 6 | 48 field types, layout parity, actual aggregate operators and harness syntax |
| Native-runner enforcement | 27 | Real temporary identities with explicitly mocked native process execution |
| Hosted workflow contract | 14 | Actual preflight/interpreter bodies, failure pipelines and trust/resource invariants |
| Public counter-fault transport | 5 | Ten RAM/LLC cells through the actual runtime/backend/CP, with controlled Processor/RAM |

Five additional executing-interpreter tests extend the existing transport-runner
suite. These are separately scoped host results on their recorded input bytes.
The [immutable full-governance receipt](evidence/p06-checked-counters/local/governance-53f4ad08c/index.json)
records **3,043 passing tests in 1,647.227 seconds** at actual local checkpoint
`53f4ad08c469a1cc73fa604249b302f9416055e0`, with source and Python identity stable.
Its tree `80553bb237af44b187dd6d18178e851cd6671ec8` is identical to published
`a9227933c340fd44e73deaffafdd353fecf65492`; the receipt retains the actual local
execution identity. The 19 later workflow/public-runtime methods passed
separately. Those earlier results are not relabeled as a later full-suite run.
The subsequent [actual hosted governance receipt](evidence/p06-checked-counters/hosted/governance-index.json)
independently records **3,062 passing tests in 1,295.925 seconds** at published
`9fd7eac`, run `45017731138`, attempt 1, with zero failures/errors/skips and
successful job cleanup. Its original log passed independent review.

The [dedicated native run 45017731063](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063)
passed at published `9fd7eac203c77fa54c7af80fa0220ae09553cd55`, attempt 1.
The [independent original-packet review](evidence/p06-checked-counters/reviews/native-review.md)
confirms both real builds, 44 translation units and one link per variant, and
all five cells. That checkpoint's boundary matrix seeded **19 available
selectors**, leaving **14 available selectors unseeded** and **12 unavailable**.
The other cells
exercise an actual Core updater fault with fresh-context success, a production
cache aggregate fault and a separately scoped pending-counter primitive fault.
The original source, configuration, command and log bindings passed independent
review. Local native execution remains separately blocked by the unchanged
15 GiB disk reserve. The successful hosted packet keeps `qualified=false` and
`ready_for_warm=false`.

That checkpoint left backing-source coverage and native public failure/coherence
checks to the diagnostic continuation above. The terminal proof still requires
actual measurement/caller/dependency bindings before a new qualification reader
can admit fresh warm execution. Historical warm-v1 rejection, accepted cold
results, statistical predicates and P06-A02/A03 remain unchanged.

## Previous continuation — simulator completion prerequisite

The [audit](p06-simulator-completion-audit.md) begins at
`42809ff0c1b81384d7c9b079e4ef786be8407600`. SimX's legacy run swallowed model
exceptions, both host backends discarded asynchronous results, and a task ready
before its first poll could fail to expose the required busy edge. A guard for
future counter qualification cannot rely on a failure path that loses errors.

The [completion contract](../designs/simulator_completion_v1.md) separates
checked SimX execution from the legacy register-derived return; valid `gp`
values, including `-1`, remain successful. Both backends use `AsyncRun` to consume
outcomes, retain processor failure, preserve the launch edge and join outstanding
execution before freeing owned memory or processor state. Full cleanup in both
timing and functional SimObject frameworks disposes of abandoned channel
accounting after workers, scheduled events and inboxes have been removed. Normal
packet flow, reset/launch behavior, arithmetic, public error codes and ABI remain
unchanged.

The first clean checkpoint, `db5ebb3a16770004423f2456ec6d0caaa0aced6d`, passed
78 focused host tests and the hosted
[native completion run 45006726571](https://github.com/baabi-boo/AI-GPU/actions/runs/45006726571).
Its unit exercised real `Processor`/RAM, nine checked normal runs, three legacy
normal runs, one legacy caught exception and one checked `OutOfRange` exception,
with a fresh successful context after the fault. Its separate public-runtime
cell passed six serial launches across two contexts with nonzero `gp` and exact
outputs. Independent review binds the executed merge tree to that checkpoint.
The [governance run](https://github.com/baabi-boo/AI-GPU/actions/runs/45006726409)
passed all 2,988 tests. These receipts precede the CP error-boundary correction
described next; they are not verification of later production bytes.

A late consumer audit caught a compatibility regression in the initial broad
exception catch: CP-copy scratch `std::bad_alloc` became a terminal
`VX_ERR_INVALID_VALUE` instead of the inherited recoverable
`VX_ERR_OUT_OF_HOST_MEMORY`. The repair latches failures at actual processor
operations and leaves unrelated CP/host exceptions on their existing runtime
path. The unchanged lifecycle test now passes all three allocation-failure stages
in SimX/rtlsim × RAM/LLC (**four full lifecycle cells**), including resource
restoration, unchanged seeded data, no replay and same-device continuation.
Another **34 host cells** keep asynchronous and synchronous processor faults
terminal. All four built `db5ebb3` negative controls fail the intended OOM
assertion. Independent review found no remaining F2/F3 defect in this boundary.

At repaired production checkpoint
`4781ca96db15a1d130626edc7a73411a4f6c2e7c`, the clean focused suite passed
**83 tests in 87.502 seconds**, with source, tool and driver identities unchanged.
The compiled audited-parent replay also passed all eight intended old-backend
failure controls. The fresh
[native run 45009314161](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314161)
passed both native cells, and independent original-artifact review verified the
actual repaired runtime/helper and contract bytes. The executed PR merge
`e929c52d05bad80b28dd4085a97838d7fe2de354` has the same tree,
`6dd0d759390cda78ec63ad0caacc00a08f03e2bc`, as that checkpoint.
The original ZIP and review are retained in the
[repaired native packet](evidence/p06-simulator-completion/checkpoints/native-4781ca9.tar.gz).

The declared native route is RV64 `p02-tfr`, timing SimX, `PERF=1`, one worker and
direct-RAM CP. It repeats the real-model fault/legacy-success/fresh-context unit
and six public success launches. It does not inject a native public-runtime
fault or establish native functional SimX, multiworker exception recovery or
processor RTL execution. The local 15 GiB native disk reserve remains enforced;
native execution used adequately provisioned hosted CI.

Both full Project Governance runs at the repaired tree passed independent
original-log review: [PR run 45009314170](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314170)
completed **2,993 distinct tests in 1,864.865 seconds**, and
[push run 45009309941](https://github.com/baabi-boo/AI-GPU/actions/runs/45009309941)
completed **2,993 distinct tests in 1,891.161 seconds**. Every result was `ok`,
and each run includes the same 83 focused completion tests. The PR executed
same-tree merge `e929c52d`; the push executed `4781ca9` directly. These outcomes
cover governance and bounded host tests; they do not establish that the broader
CI matrix passed. The [completion packet](evidence/p06-simulator-completion/README.md)
retains the original logs, historical pending observations and exact source scope.
The later delivery
adds only README/project documentation and evidence. Independent source
projection checks the unchanged execution inputs against tested `4781ca9`;
earlier CI is not represented as an execution of the later documentation tree.
The [delivery ledger](evidence/p06-simulator-completion/delivery-ledger.md) records
all **60 actual agents across ten logical waves**, with follow-ups retained under
their original identities. Publication verification is recorded separately.

## Previous continuation — host counter transport

The [transport contract](../designs/host_mpm_transport_v1.md) preserves the
32-bit DCR wire format and public API while repairing RV64 half selection in
both production implementations. Architectural CSR semantics and the response
stage count stay unchanged. The [evidence index](evidence/p06-mpm-transport/README.md)
separates reviewed native/parent execution, completed circuit measurements and
retained failed setup attempts. The strict run used checkout
`6e6426a0bf761baab11e932a4c86b49a5de81217`, tree
`d6dd742a905e0f3e76c7374cc678ba87e5c2a19e`, identical to candidate
`18c888058ac851b802350c99770ed9ac2d27b582`. The
[alternative review](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the original cost review's specific missing-comparison F2. Shared decoding
saves 2/68 Beacon LUTs but adds 9/21 generic cells, worsens PERF-off path 7 → 8
and increases PERF-on watch endpoints 12 → 32. Retain the direct decoder; the
experimental code is not adopted. This is a measured choice between the tested
candidates, not global optimality or an area-gate pass. The
[enforcement review](evidence/p06-mpm-transport/reviews/enforcement-review.md)
records an F1 standalone executing-interpreter identity follow-up, with hosted
execution already checking interpreter equality. None of these results qualifies
older warm observations. Resume from the [transport handoff](p06-mpm-transport-handoff.md).

## Previous continuation — serial ownership and fixed workspace

The [development audit](p06-workspace-audit.md) at
`3235cd59d724663dda1bece20645d5ccf30462e1` found unguarded native context/operation
coexistence and errors that could be lost after later successful observations.
The [frozen contract](../designs/serial_matmul_workspace_v1.md) specifies the
implemented reservation, explicit-close lease and sticky-error behavior.
Observed cleanup failure poisons new managed work; timeout remains retryable and
retains all required resources. Raw runtime clients, separate linked copies and
concurrent methods on one owner remain outside the guard's qualification scope.

`WorkspacePolicy::reusable_single_tile` owns A128/B64/D128 requested bytes for
`(8,4,8)`; all input and poison writes, the kernel and output read remain per
operation. Default `per_operation` keeps all six supported format/shape
signatures. Real MLP, Python, PyTorch and cold-benchmark callers keep their
default allocation policy; the MLP rejects non-default policy before native open.

The [implementation packet](evidence/p06-serial-workspace/README.md) retains
source-bound host fault/control checks and their original limitations. The later
[original-artifact review](evidence/p06-warm-workspace/README.md) reconciles all
four SimX/processor-RTL × FP16/BF16 variants at `13dc0d1`, run `44925627664`:
eight processes, 32 native launches, 1,024 exact FP32 output words with no
mismatches, and all 60 observed tensor-buffer lifetimes. Offline replay checks
retained data; it does not rerun native binaries or establish physical memory
reclamation. Processor RTL still bypasses the AFU.

The [correctness runner](../../ci/project/p06_workspace_execute.py),
[manifest](../../ci/project/p06_workspace_contract.json) and
[handoff](p06-workspace-handoff.md) preserve that separate scope. Warm sampling
now has an [implemented contract](../designs/warm_workspace_benchmark_v1.md)
and runner, but the v1 analyzer unconditionally blocks full qualification on
counter transport. Neither the correctness review nor the transport repair
accepts performance or P06-A02/A03.

## Previous continuation — accepted native performance baseline

P04 is complete and supplies P06's accepted native-model prerequisite. P05 is an
independent track. The [qualification audit](p06-qualification-audit.md) completes
review of the baseline implemented in the [preceding audit](p06-benchmark-audit.md).
[P06-A01](evidence/p06-baseline/acceptance.json) accepts the original execution at
`84b6ca0ca75fba248ba330642bbf8764db3d459c`, run `44901052221`, attempt 1; the
[independent acceptance review](evidence/p06-baseline/reviews/acceptance-review.json)
records the exact obligations and limitations.

The [implemented contract](../designs/native_benchmark_v1.md) freezes three
accepted matmul shapes and the fixed model in each of FP16/BF16: **eight workloads**
on the RV64 `p02-tfr` SimX timing model. Each uses one retained warm-up followed
by five measured fresh processes. The complete suite passed **48 processes and 72
launches**, including **40 measured processes and 60 measured launches**.
Every process starts a fresh device context; the warm-up does not establish
warm-cache measurements. The counter table contains **45 rows: 33 available
and 12 explicitly unavailable**. Counts span the whole context, including all
three model launches, and do not provide per-stage or physical-device timing.

The [packet](evidence/p06-baseline/README.md) preserves both original archives and
failed prior attempts. Independent review reconciles 4,608 exact native output
words, 768 bridge words and 768 assembled output words, plus source, compiler,
dispatch, cleanup and raw-counter records. The new
[analyzer](../../ci/project/p06_analyze.py) replays the full matrix and derives
per-sample diagnostics under its [contract](../designs/native_baseline_analysis_v1.md).
Stricter serial timing containment rejects impossible lifecycle/advance totals
while preserving the original measurements and the 1,000 ns process allowance.

A separate host-only reproduction found an approximately 100 ms supervisor
exit-observation delay. Original host durations remain unchanged; exact exit
timestamps are unavailable, so no guessed correction or fine-grained host speedup
is inferred. Original-artifact qualification reviews the historical run; fresh
checkpoint regression execution at `9036b37` is recorded in the
[implementation validation packet](evidence/p06-analysis-validation/README.md),
with acceptance kept at its original source. The cold SimX counts motivate a small-workload
amortization experiment; they do not establish a causal bottleneck or successful
optimization. That continuation identified native multiple-live-operation
ownership as the prerequisite. Its subsequent implementation and current
verification scope are recorded in the workspace continuation above.

P06-A02/A03 remain open. This continuation establishes no native-RTL performance,
synthesis or physical speed result. P01-A03 still lacks qualified vendor `hw_emu`
evidence before P07, and the inherited [267 → 283 DSP area-gate failure](p04-executor-audit.md)
remains unresolved. The two-job, 4 GiB memory and 15 GiB disk prerequisites are
unchanged.

## Previous continuation — copying Python binding

The [development audit](p05-binding-audit.md) selected the first P05-T01 slice:
a Linux CPython 3.12 extension around the unchanged managed native owners.
The [binding contract](../designs/python_binding_v1.md) defines exact packed
FP16/BF16 inputs, owned FP32 results, explicit close and retryable timeouts.
The [compatibility matrix](p05-python-compatibility.md) separates qualified
SimX execution, host-only failure tests and unsupported framework behavior.

The [A01 record](evidence/p05-python/acceptance-binding.json) accepts the copying
binding at `e1420fd550f716df33a2556057b7086a03032cbe`, with binding-source SHA-256
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.
The installed FP16/BF16 matrix passed all six supported matmul signatures and ten
frozen model cases, using two output poisons per route. The combined matrix has
**144 native launches: 72 through Python and 72 through the native comparison**.
Its **660 event/profile pairs** comprise 360 Python and 300 native pairs; the
twelve standalone native comparison launches are unprofiled. The copied original
native packet is not an additional execution.

Each variant rebuilt a bound source archive offline and installed its wheel in a
fresh external environment. Hosted qualification used **CPython 3.12.14 and
G++ 11.4.0**; the separate local packaging checks used GCC/G++ 14.2.0.
The clean hosted source suite passed **2,174 tests in 421.584 seconds** at the
implementation revision. Independent numerical, dispatch and provenance audits
reconcile the original archives, actual outputs, source/build identities and
installation records in the [evidence packet](evidence/p05-python/README.md).

The [host history](evidence/p05-python/development/host-validation.md) retains
107 host-native lifecycle scenarios, eleven targeted probes, actual package
build checks and earlier failures. The changing-source local full-suite failure,
its isolated rechecks and the inherited configure timeout are not relabelled as
passes. Host fault injection does not establish accelerator arithmetic. Current
documentation records the tested implementation revision; it does not claim a
new execution at a later evidence-delivery commit.

Independent review found two inherited constraints at the new caller boundary:
SimX uses process-wide simulation state, and distinct queues can interleave
launch setup. The binding therefore permits one live native context and requires
completed explicit matmul close before resubmission. Models suspend the idle
matmul context and own their separate context until close. These restrictions
preserve the accepted runtime without changing native scheduling or arithmetic.

## Previous continuation — qualified managed model execution

The [executor audit](p04-executor-audit.md) selected P04-T02 after the accepted
fixture and managed operator work. The implemented model owns incomplete native
operations through timeout and cleanup, compares actual hidden results before
the host bridge, feeds its actual bytes into both output calls, and assembles
the returned row blocks. Profiling is opt-in; records preserve event-query
outcomes, actual launch arguments, comparisons, transfer bytes and resource
counters. The [record contract](../designs/mlp_execution_records_v1.md) and strict
consumer check these observations against the frozen inputs and build binding.

The fresh [native workflow](https://github.com/baabi-boo/AI-GPU/actions/runs/44762622060)
passed 62 bounded commands across four clean variants, with two distinct output
poisons per case. Exact checks cover 5,120 hidden words, 2,560 packed bridge words,
2,560 output-block words and 2,560 assembled-output words. Explicit tensor traffic
is 76,800 H2D bytes including destination poison and 30,720 D2H bytes; actual host
row assembly copies 10,240 bytes. Argument/control, module and setup traffic are
outside these totals. ReLU, exact conversion and assembly remain declared host
work; native matmuls never select a CPU fallback.

Initial preparation rejected cached `cocogfx` build products. A strict quarantine
restored the unchanged clean-source requirement. The next four native runs
succeeded, but their uploads omitted `.config.stamp`; those incomplete packets
remain failed qualification evidence. Corrected narrow artifact uploads retained
the stamps in the fresh accepted matrix. Earlier runs are not added to its totals.
Independent review also corrected and rechecked the evidence auditors' include
path and timing-consistency checks before acceptance.

The runner uses two build jobs, a polled 4 GiB process-group RSS cap, 15 GiB disk
reserve, 16 MiB command logs and bounded build/case deadlines. Selected source and
generated bodies plus binary hashes support reproduction; complete tool/native
binaries are not archived. Host steady-clock profiles and overlapping host wait
durations do not measure physical GPU latency. Processor RTL bypasses the AFU.
The [executor packet](evidence/p04-executor/README.md) records exact scope and
replay instructions. The inherited **267 → 283 DSP** area-gate failure remains
unresolved; no RTL, simulator behavior, baseline or tolerance changed here.

## Previous continuation — fixed tiny-model source contract

The [development-entry audit](p04-audit.md) maps the selected network onto three
native matmul calls per case using accepted shapes: one `(16,8,16)` hidden projection
and two `(8,4,8)` output row blocks. The planned host work is limited to ReLU,
exact FP32-to-FP16/BF16 conversion and copying the actual output row blocks.
The host bridge must consume actual first-layer results, after their exact
comparison; reference arrays may not supply subsequent native inputs. This
placement does not add native activation/cast support or CPU matmul fallback.

The original generated weights, input families, seeds, layouts and exact
preactivation/bridge/final targets are fixed before executor development. The
manifest pins the fixture, independent producer, accepted profile and relevant
source dependencies. The [P04-A01 acceptance](evidence/p04-fixture/acceptance.json)
binds this contract to clean source `10ace66193686e3862c3c218760b66c044f1d4ae`,
tree `775aa7d5f96cfc5f7346e591ca151f36c485d2cf`. All five formal commands passed:
fixture reproduction, contract validation, project governance, historical packet
consistency and the complete source suite. The suite passed **1,733 tests in
752.879 seconds**, including all **64 P04 tests**, with no errors, failures or
skips. The tested source remained unchanged. Python 3.12.14 and GCC 14.2.0
provided Python/reference and C++17/UBSan host checks; these results establish
no P04-A02/A03 execution, device dispatch, transfer timing or model performance.

The audit also preserves a separate unresolved CI area failure: tensor DSP usage
is **267 → 283**, beyond the unchanged 5% gate threshold. The linked audit names
the existing runs and a static candidate requiring measured attribution. This
continuation changes no RTL, native profile, golden baseline or gate tolerance;
its source checks cannot resolve that failure.

## Previous continuation — qualified managed native matmul

P03-T02 implements the six declared matmul signatures through an internal
managed `vortex2.h` wrapper and the matching ordinary WMMA kernel. The wrapper
owns copied host inputs, actual allocations, module/kernel handles, per-operation
queues and completion events. Timeouts retain ownership; primary execution and
cleanup errors remain distinct. The trusted runner validates runtime, backend,
kernel and host compiler records separately and binds exact artifacts to each
trace. Capability bits alone do not identify the numerical profile.

The [accepted packet](evidence/p03-managed-matmul/README.md) records clean source
`319ad63532cee17ae88fa75757a5ac87ed5c6a77`, tree
`d7768f5f392cef417e59ccadfc29f20d3f67f707`, with unchanged source, tools,
dependencies and artifacts throughout execution and independent review.

| Observed result | Scope |
|---|---|
| 176 case executions, 352 actual launches, 14,336 exact output words | 88 unchanged independent P02 fixtures on each of SimX and native processor RTL; FP16/BF16, three shapes each, two distinct output poisons |
| 210 bounded commands passed | Fresh configuration/builds, separate compiler records, numerical launches and RV64 lifecycle execution |
| Twelve lifecycle groups passed in each RV64/RV32 SimX configuration | Bounds, wait/event ownership, timeout retention, skipped work, module/setup allocation failures, three transfer allocation-failure stages, scratch cleanup and 32 release/recovery cycles |
| All 1,669 host tests passed in 427.714 seconds | No errors, failures or skips; includes 45 P03 tests: 12 contract, seven reader/profile, nine managed mocks and 17 record-parser checks |
| Peak sampled matrix RSS 1,484,550,144 bytes; 54,525,153,280 bytes disk free afterward | Two build jobs, 6 GiB polled RSS budget, 15 GiB disk reserve and 16 MiB per-command log limit; no downloads |

Shared runtime fixes retain resources through skipped commands and exceptions,
reject overflowing spans, roll back failed map reservations and reclaim partial
setup allocations. The software command processor retires a failed synchronous
transfer before freed staging can be replayed. Its successful tick ordering is
unchanged. The regression reads a seeded destination after the injected failure
and before recovery can conceal a stale write. No new timing/performance claim
or additional `model_parity` execution is made.

The independent qualification reviewer reconstructed the wire arguments and raw
output comparisons without using the new output parser. A separate reviewer
checked lifecycle scope; source/policy review verified CI coverage expansion,
unchanged installed interfaces, protected assets and historical A01 provenance.
The RV32 receipt's `cache_enabled=false` means compiler caching is disabled;
actual processor instruction/data caches are enabled.

Earlier dependency-header/public-kernel-name failures, the nested-submodule
preflight block and controlled interruptions for braces/inventory corrections
are retained as development history. They do not count toward acceptance.
Native processor RTL bypasses the AFU. Physical device recovery, arbitrary
simulator exceptions, partial-DMA rollback, exhaustive host-heap leak freedom,
vendor `hw_emu`, FPGA performance, PPA and silicon remain outside this evidence.

## Previous continuation — native operator contract

**P03-T01 is complete; P03-A01 is [accepted at source scope](evidence/p03-operators/acceptance.json).**
Clean source `6367ce34e12915e12271207b207f93bd4d391869` passed 1636 tests with
zero failures/errors/skips in 397.573 seconds. The exact tree is published as
`04c3cbf42c68e3b116051343083b86119f67f53d`; the [source mapping and receipts](evidence/p03-operators/README.md)
retain all identities. Four RV32/RV64 object compilations passed separately.
At that earlier checkpoint, independent review approved only the contract
boundary; A02/A03 were still open.

P03-T01 implements the [versioned manifest](../../ci/project/p03_operator_manifest.json),
[design contract](../designs/ai_operator_contract_v1.md) and internal C++17
[planner/encoder](../../sw/runtime/ai/contract.h). The only contract signatures
are ordinary dense FP16/BF16-to-FP32 matmul at `(8,4,8)`, `(8,4,16)` and
`(16,8,16)`, with row-major A, column-major B, row-major D and initial C=+0.
The implementation validates checked sizes, exact strides, tracked allocation
bounds/access, device/profile identity, representation width and nonaliasing.
Failures preserve caller output. All plans explicitly report execution unavailable.

The new 56-byte argument schema is internal and is not compatible with the
existing regression kernel argument block. That checkpoint required P03-T02 to supply its actual
reader/adapter, managed runtime wrapper and retained resource lifetimes before
launching it. No installed runtime ABI, P02 numerical contract, protected asset,
GPU datapath or simulator has changed. [The handoff](p03-operators-handoff.md)
records validation scope and the next bounded work.

The previous unfinished WGMMA publication is also reconciled. Its four immutable
archives are unchanged; a final W10F review replaces the stale active mapping,
while old captures, original failed audits and unfinished historical agent
approvals remain explicit. The new independent
[closure review](evidence/p02-wgmma/processor/reviews/closure-review.md) accepts
P02-A03 using the retained actual execution, not a fresh GPU-run claim.

## Completed WGMMA processor qualification

The [processor packet](evidence/p02-wgmma/processor/README.md) and
[WGMMA handoff](p02-wgmma-handoff.md) retain a finished, passing formal run at
clean source `4af2307e57202c1269e20f893267a5583ad3cba0`, tree
`42e5d6f2c9c0c2035c4d3ec8c86125e8cca45192`. The original report SHA-256 is
`b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78`.
The source stayed clean and stable throughout execution. The final results are:

| Result | Demonstrated scope |
|---|---|
| 113 successful commands; 12 backend/configuration builds | Six frozen configurations on full SimX and native processor RTL; matching effective configuration and retained compiler/input provenance |
| 24 case executions, 48 launches and 24,576 exact output-word comparisons passed | Two signature cases per configuration/backend, each with two poisoned launches; dense FP16/BF16 SS/RS, FP16 SS row-major A and bounded sparse FP16 SS |
| Both sparse RTL witness cases passed | 64 completed metadata transactions across four launches, all 64 with observed waits; each launch covers eight physical warps, four issue instances and two CTAs |
| All 12 performance pairs passed | Exact retired-instruction equality and the unchanged 5% launch-delta cycle rule; maximum observed difference 1.356484% |
| Corrected original-packet CLI passed; 1,103 files verified | Independent report-digest anchor, retained-body/input/command consistency and reparsed arithmetic, witness and parity results; no binary replay |

Each sparse case records 723 and 651 slot-wait cycles on its two launches.
These are sums across scoreboard slots, not elapsed launch time. Per-slot
reservation, real XREG0 wait, matching release and eventual issue establish
ordering. The reviewed sparse binary places the load and dependent WGMMA at
adjacent PCs; the scoreboard records supply the dependency proof. Auxiliary
cache/stall counters retain their observed differences: the frozen parity
predicates are exact instructions and the cycle bound, not equality or causal
attribution of every auxiliary counter.

The [historical native unit](evidence/p02-wgmma/unit/README.md) retains its
original clean execution at `9006939aa123452b198bc0987e34aae8fab45fdd`: nine
commands, eight groups, 392 accepted/committed transactions and 3,072 checked
arithmetic words. Independent bridge review confirms all 417 named RTL/harness
paths remain unchanged at the processor source. Dense NRC16 RS supplies the
causal blocked-result/execute/dispatch pressure observation; its following eight
stable cycles do not each prove that full conjunction. Forced sparse-compute
pressure remains unclaimed. Unit totals are separate from processor totals.

The corrected verifier is published as
`359a8c007f450a8146540f795cb576b29818fa03`, equivalent to tested local
`5e3b74fd569169ad921315223c121a037ae656b7`, tree
`97116818da872f43f952a351eb6616fc327be438`. It requires exactly eight generic
checkout inputs and strict equality for every execution-inventory overlap. Only
unused `ci/blackbox.sh` may remain checkout-only, with its identity explicitly
reported and its body unverified. Mandatory consumer source copies and helper
closure remain required. The earlier verifier's checkout/source mismatch is
retained as a failure; the original execution packet was unchanged.

Tooling results retain separate source identities: 1,602 tests passed at local
implementation `7360bba` (the same tree later published as `4af2307`), and the
earlier verifier tree published as `ad94b69` passed 1,619 tests before the known
checkout-input correction. The corrected verifier's 22 focused tests passed.
Its actual hosted full suite at published `359a8c0` passed **1,624 tests in
312.155 seconds**, with zero failures, errors or skips. The
[independent hosted review](evidence/p02-wgmma/processor/reviews/w10d.md)
verified the decoded job log and source identity for
[Governance run 44241512544](https://github.com/baabi-boo/AI-GPU/actions/runs/44241512544).
This is a fresh observed full-suite result, not a sum of earlier test counts.
None of those tooling checks is GPU execution or an automatic acceptance decision.

Execution source `4af2307` also completed
[general CI run 44235141936](https://github.com/baabi-boo/AI-GPU/actions/runs/44235141936)
with all 42 jobs passing. Corrected-source
[general CI run 44241512594](https://github.com/baabi-boo/AI-GPU/actions/runs/44241512594)
was still in progress at the last retained observation; no complete pass is
claimed for that workflow or transferred to a later documentation revision.

The first formal attempt at local `7360bba` failed compilation under GCC 14.2.0
with `-Werror=dangling-reference`, before any case, launch or word comparison.
A separate Clang 20.1.8 compatibility probe also failed under the unchanged
warning policy. The GCC 12 preparation and successful retry retain both earlier
failures; see [host compiler compatibility](developer-guide.md#host-compiler-compatibility-for-wgmma).

Independent engineering and publication-integrity reviews support the
[P02-A03 acceptance](evidence/p02-wgmma/processor/acceptance.json), record
`p02-a03-wgmma-4af2307-359a8c0`, completing P02-T02 and P02. The original verifier
result remains `independent_review_required` with its acceptance and
phase-completion flags false; the separate reviewed acceptance record supplies
the decision. Native TFR/STD processor arithmetic retains integer
DPI helpers and bypasses the AFU. No full-AFU, vendor `hw_emu`, physical FPGA,
synthesis/PPA or silicon result follows. P01-A03 remains blocked. P03 was
`not_started` at that acceptance checkpoint; the newer contract work is above.

<a id="latest-continuation--full-processor-ordinary-wmma"></a>

## Earlier continuation — full-processor ordinary WMMA

Formal processor and API validation used clean source
`58faf6d68879e1db92122df493172eab59c02458`, tree
`cd35869ee89cb42685e9bac367667a7dffbe1b1d`. The
[WMMA evidence packet](evidence/p02-wmma/README.md) and
[handoff](p02-wmma-handoff.md) retain exact configurations, independent reviews,
source and compiler provenance, raw results and failed attempts.

| Result | Demonstrated scope |
|---|---|
| 88 source cases: 20 unchanged layout cases and 68 numerical cases, 44 per format | Independent FP16/BF16 expected words, normal and exceptional values, cancellation, tile layouts and K traversal |
| 176 case/backend executions, 352 launches and 14,336 exact output-word checks passed | All selected cases on both full SimX and native processor `rtlsim`, with two separately poisoned launches per case/backend and zero mismatched FP32 words |
| 47 actual RISC-V API expectations met: 17 successful compilations and 30 intended compiler rejections | Both WMMA/WGMMA class contexts, 94 context checks; explicit public-API rejection, without an unsupported-instruction hardware-trap claim |

The accepted arithmetic scope is ordinary dense WMMA under the unchanged
RV64 `p02-tfr` profile: FP16/BF16 inputs, FP32 accumulation/output, initial
C = +0, K = 8 or 16, `KUNROLL=1` and an `8 x 4 x 8` tile. A is row-major,
B is column-major, and C/D are row-major. The profile has one cluster/core,
four warps of four threads and issue width one. Native `rtlsim` uses the
TFR tensor and STD scalar floating-point paths; integer DPI helpers remain
present. The processor result bypasses the AFU and supplies no vendor `hw_emu`,
physical FPGA, silicon, WGMMA concurrency or timing-model parity qualification.

The initial development SimX cancellation failure remains retained: it returned
`33800000` where the frozen expected word was `00000000`. The build omitted the
resolved TFR selector despite its raw profile flag. Corrected configuration
propagation selects the existing TFR model, and the formal paired runs match
the original expected words. Production arithmetic, the profile, the numerical
specification, inherited goldens and earlier evidence are unchanged.

The first full offline suite at `58faf6d` ran **1,448 tests and failed one
inherited source-contract check**, with no errors or skips. That failure is
retained. The reporting-only child
`c9cf9ba0730f236e110a1d48a54d8f47a9faf9af`, tree
`df62aa14b7dee5e02ad85027ac0e3225d1d8e4a1`, changes only
`tests/regression/sgemm_tcu/main.cpp` to restore the legacy random-path iteration
report while preserving fixture reporting. Its exact patch passed the focused
source-contract test and all 15 host-adapter tests before the child was created.
The full suite at clean `c9cf9ba` passed all **1,448 tests**, with zero failures,
errors or skips in 589.248 seconds. The corrected-host replay passed **184
commands, 176 case/backend executions, 352 launches and 14,336 exact output
words**. Four hosts changed; all 108 nonhost artifacts remained identical.
The earlier failed suite remains retained, and the original fresh processor/API
results retain their `58faf6d` source identity.

Implementation `c9cf9ba` is published and remotely verified on `master`.
Project Governance run `43982209440` and the full CI run `43982209402` passed.
Both hosted scaled-format cells
passed all 20 cases each, including every one of the 20 changed case/XLEN
obligations. The [CI recovery record](evidence/p02-wmma/ci-recovery.json) keeps
those compatibility results separate from exact-bit A02 qualification.
An [independent recovery review](evidence/p02-wmma/recovery-review.json) verified
the original and published artifacts before accepting the bounded A02 scope.

At that checkpoint, P02-T02 stayed active for the subsequent WGMMA concurrency
matrix. The completed execution is recorded above. The ordinary A02 result
alone did not close P02, start P03 or change the blocked P01-A03 obligation.

## Earlier continuation — P02 contract and executable fixtures

The following A01 checkpoint predates the processor continuation above; its
reported execution results and outstanding work retain their original scope.

Formal validation used clean source
`a25321496d802f43830c1658487f1adf79c838c3`, tree
`7e459269e22f90691cf410e42068982f5a8c7a2d`. The
[evidence packet](evidence/p02-numerics/README.md) retains exact commands,
configuration, selected compiler-header identities, logs, source hashes,
independent reviews and failed attempts.

| Result | Demonstrated scope |
|---|---|
| 1,343 offline tests passed; zero failures, errors or skips | Project tooling, contract checks and host model-function tests |
| 98 native dense and the same 98 stalled fixtures passed, with 306 hold checks | Direct native TFR FEDP leaf, exact FP32 bits, without DPI arithmetic |
| 98 production-model fixtures passed | Host `TfrFedp` calls; no full SimX processor run |
| 47 actual RISC-V compiler cases passed: 17 positive, 30 intended rejections | Disabled-format and output-contract checks in both WMMA/WGMMA contexts, 94 context checks |
| Four existing FP16/BF16 WMMA/WGMMA kernel objects compiled | Compile-only integration; WGMMA uses explicit overrides outside the ordinary profile |

The runnable `p02-tfr` profile and 20 matrix-memory fixtures freeze the first
ordinary WMMA application geometry and layouts. The matrix fixture adapter and
their full-processor execution remain outstanding. Leaf enable stalls do not
establish WGMMA synchronization, metadata handling, multiple warps or backpressure.

The first clean candidate `135cfec14d1fed0b4e950bc243e69a91879e4275`
failed native harness compilation because raw profile enum flags did not supply
the resolved C++ selectors. The corrected Makefile uses the established resolved
flag path, and a real-profile regression preserves raw rejection guards. An
earlier dirty-source stall run exposed a shared Verilator-context lifecycle bug;
each DUT now owns its context. Both failures remain retained with their exact
provenance limits. Production arithmetic, inherited goldens and P01 evidence
were preserved. The [agent ledger](evidence/p02-numerics/agent-execution.json)
records collaboration separately from qualification.

## Preserved sequencing decision — staged numerical development entry

On 2026-11-16 the user directed an execution-sequencing change to avoid making
vendor-only tools a prerequisite for native AI software development. The
[machine-readable roadmap](roadmap.json) now permits P02 entry based on both
accepted P01-A01/A02 evidence records, with P00 complete. The governance
validator requires passing, compatible evidence for **every** named entry
acceptance before a phase may be `in_progress` or `complete`. A missing,
blocked or failed record will reject the transition. P02's existing three
acceptance obligations were unchanged and none was claimed accepted by that
entry decision. The later P02-A01 source result is recorded above.

**P01-A03 stays blocked and required.** P07 now also depends on full P01
completion, so an FPGA prototype cannot be declared complete without the
vendor integration result and later actual physical measurements. The
[staging handoff](p02-entry-handoff.md) records the next work, and
[ADR-004](decisions.md#adr-004--staged-native-development-entry-with-vendor-integration-retained)
records the decision. Historical evidence, failed attempts, vendor runbooks
and source-level numerical tolerances were not changed by this decision.

## Preserved continuation — supplemental tensor-oracle hardening

The [tensor-oracle guide](p01-tensor-oracles.md) and
[evidence index](evidence/p01-tensor-oracles/README.md) describe this supplemental
P01 correction and retain each execution's exact source and configuration.

- Class-aware NaN/infinity handling and overflow-safe finite ULP distances prevent
  nonfinite mismatches and signed overflow from producing false comparisons.
- FEDP preserves the FP32 accumulator C bits; independent packed FP16/BF16
  fixtures check operand layout, accumulation and numerical edge cases.
- Integer references use modular 32-bit arithmetic. Strict CLI checks reject
  malformed, empty and disabled-format selections; seeded single-case replay
  consumes the same input stream as the corresponding full run.

Matrix/full-suite source: **`ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`**. Native matrix: **pass — nine builds, 62 commands and 95 CLI checks**.
Full tooling suite: **1,272 tests passed, zero failures/errors/skips in 336.269 seconds**. The earlier `20ea50d` native-matrix
attempt failed during compilation on a GCC diagnostic; retain that failure
separately from later retries and the accepted historical baseline.

At that tensor-oracle execution checkpoint, P00 was `complete`, the historical
P01-A01/A02 reports were unchanged, P01-A03 was blocked, and P02–P11 were
`not_started`. Those checks do not complete P01 or qualify physical hardware;
the newer staged-entry decision is described above.

<a id="latest-continuation--supplemental-local-afurtl-qualification"></a>

The later host-only diagnostic correction at `a25ee6663e37d5fe28e7a6fd40b3857083ddeecc`
preserves nonzero-exit context when child output contains invalid UTF-8. All 12
tensor host groups and the actual malformed-output negative control pass there.
Native consumer/configuration hashes remain identical to the matrix source; the
nine-build matrix and full-suite results above retain their original revision.

## Earlier continuation — supplemental local AFU/RTL qualification

The [local qualification guide](p01-local-qualification.md) documents the
[bounded runner](../../ci/project/local_qualification.py) for real execution
through the XRT runtime, local `libxrtsim` shim and full AFU RTL, alongside
focused CP/LLC-port and AXI-arbiter RTL unit harnesses. Its fixed application
cases cover integer transfers/launch, cold and warm reopen, and reordered AXI
memory traffic; FP16/BF16 GEMM are explicit selections with the frozen P01
configurations and reference tolerances. Separate generated build trees and
retained source, tool, dependency and configuration identities bound each run.

The frozen source `7e4ac5851f1f71d292ed1802c3f92456d96faf8d` completed
**all eight selected cases and 32 monitored commands**, including both native
TFR FP16/BF16-to-FP32 GEMMs. The same source passed **1,260 tooling tests in
293.241 seconds**. It fixes the stencil application's advertised block-size
option, rejects zero geometry before device work, places child compiler
temporary files on the monitored build filesystem, and retains accurate
helper-drift and process-launch diagnostics. The
[qualification handoff](p01-local-qualification-handoff.md) and
[evidence index](evidence/p01-local-qualification/README.md) retain the exact
commands, finished packets, configuration reviews and failed attempts.

The subsequent source `143c69fe284bc2a1628721cf8a4237ac82d2547d` strengthens
the CP/LLC test oracle while preserving its six functions and all 37 original
assertions. Both affected unit selections pass in a **fresh five-command
packet**. Paired isolated mutation proofs detect three faults that the original
harness missed. That follow-up also raises the governance job timeout from five
to ten minutes with matching policy text; its focused CI guardrail test passes.
The full tooling suite and eight-case matrix were **not rerun at this later
revision**. The handoff retains source-to-GitHub mappings and points to
commit-scoped delivery and hosted CI checks.

The initial published-head governance run at `1b1bf572` then found one stale
test expectation: five minutes instead of the reviewed ten-minute job budget.
The exact one-line correction at local source `420937e` (GitHub `f269505c`)
passed the full 1,260-test tooling suite again in **257.346 seconds**, with
clean, unchanged source and completed cleanup. The
[separate CI follow-up](evidence/p01-local-qualification/ci-followup/README.md)
preserves the failed hosted run, correction review, fresh full-suite evidence
and source mapping. Native results retain their earlier revisions; the original
sealed archive and 60-agent ledger remain unchanged.

The local shim uses modeled host/device memory and retains DPI-assisted integer
multiply/divide. STD floating-point and TFR tensor claims are limited to each
retained configuration; local AFU/unit evidence does not qualify vendor
loading/platform semantics, physical cache coherence or physical hardware.
At that earlier checkpoint, P00 was `complete`, P01-A01/A02 retained their
accepted reports, P01-A03 was blocked on vendor `hw_emu`, and P02–P11 were
`not_started`. The later staged entry and P02 completion are recorded above.

<a id="latest-tooling-continuation--compiler-records"></a>

## Earlier tooling continuation — compiler records

The shared [compiler-record validator](p01-compiler-records.md) resolves the
preparation planner's F1 glob ambiguity and the XRT execution inspector's
operand and record-aggregation gaps. It checks the runtime, kernel and host
compiler records independently, consumes option operands before crediting macro
definitions, requires the kernel's direct RV64 ISA/ABI selections, and preserves
the exact generated-runtime linker binding. Shell expansion syntax, unsupported
compiler transports and non-LF record separators cannot qualify a candidate.
The execution runner rejects invalid records before smoke launch and rejects
later configuration drift before recording success.

The clean implementation commit
**`f11190c87778ef049237650bbba4234ca62026b2`**, tree
`36335b94da7392e4c5fd24618d4ce85addbf2d20`, passed **1,120 tooling tests,
with zero failures, errors or skips**. The baseline at `9740532` passed 1,075
tests; the continuation adds 45 tests, including real compiler-preprocessor
oracles, actual Make-generated stamp compatibility, file-backed rejection cases,
runner failure handling and retained-helper provenance. The working tree was
clean before and after the full run, and all captured project Python source
hashes remained unchanged. The
[verification packet](evidence/p01-compiler-records/verification.json) retains
the exact commands, source identities and results; subsequent documentation and
publication records do not relabel that execution as a test of another revision.

The identical implementation tree is published on `master` as
[`623544c`](https://github.com/baabi-boo/AI-GPU/commit/623544cdd51f9c70a4e2fcef29ed3b56d8cce3fe);
the [publication map](evidence/p01-compiler-records/publication-map.json) retains
the original local commit bytes and exact remote tree/parent verification.

Use the [compiler-record handoff](p01-compiler-records-handoff.md) for review dispositions,
delivery state and the continuation's actual assignment record. This work
preserved the accepted numerical packets and established no new GPU, vendor
`hw_emu` or physical-device result. At that earlier checkpoint, P01-A03 remained
blocked, P02 was `not_started`, and the next bounded action was vendor/platform
qualification. The later native-development sequence is recorded above.

The [completed execution ledger](p01-compiler-records-agent-execution.json)
records 60 distinct assignments in ten logical waves. Hosted
[Project Governance](https://github.com/baabi-boo/AI-GPU/actions/runs/43790120429)
also passed all 1,120 tests on the published implementation. Its
[observation](evidence/p01-compiler-records/code-ci-final.json) keeps the general
CI workflow's still-queued state separate from that successful result.

## Implemented P01 work

The [P01 runbook](p01-baseline-runbook.md) supplies the reproduction sequence.
The implementation contains:

- An immutable [toolchain lock](../../ci/project/p01_toolchain.lock.json) and
  [bootstrap](../../ci/project/baseline_bootstrap.py) for the minimal RV64 tool
  set, with verified archive identities, bounded extraction and install receipts.
- A [six-case matrix](../../ci/project/p01_baseline.json) and strict
  [loader](../../ci/project/baseline_matrix.py), preserving catalog provenance,
  dimensions, random seeds and inherited numerical tolerances.
- [Source/tool/build inventory](../../ci/project/baseline_inventory.py) and
  [bounded process execution](../../ci/project/baseline_process.py), retaining
  exact identities, logs, failures and resource-stop reasons.
- A [sequential runner](../../ci/project/baseline.py) with read-only planning,
  fresh output directories, atomic progress records, effective configuration
  checks and CPU-reference success-marker checks.
- Independent tooling tests for provenance, matrix integrity, shell-token
  rejection, resource limits, descendant cleanup, archive safety and failure
  retention. Passing these tests does not demonstrate GPU numerical correctness.

| Frozen workload | Dimensions | Observed SimX / processor RTL results |
|---|---|---|
| FP16 → FP32 GEMM | `M=N=K=64` | `pass` / `pass` |
| BF16 → FP32 GEMM | `M=N=K=64` | `pass` / `pass` |
| TF32 → FP32 attention | `N=32, D=16, c=8, t=8` | `pass` / `pass` |

Each pair explicitly selects **TFR tensor and STD scalar arithmetic**. SimX
remains a software model. Processor `rtlsim` and supplemental full-AFU `xrtsim`
remain distinct from vendor `hw_emu`, physical FPGA execution and silicon.
Attention uses SS operands for both GEMMs. The unused `WGMMA_RS` command macro
does not establish RS coverage; the [erratum](evidence/p01/attention-operand-erratum.md)
preserves and corrects the original matrix's descriptive error.

## Historical reviewed execution packet

The GPU source checkout is pinned to
**`03181532b81fe95b1cfeac2ffb25d8597af689b2`**, separately from the evolving
baseline tooling published at **`e9c9ac01f93b0d84915340999100260f2599ec44`**.
All six executing helper snapshots match that implementation commit. Source/tree,
recursive submodule and generated-build identities are retained. The toolchain
tag `v3.0.2` resolves to immutable commit
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`; the lock covers 18 archive parts,
**720,873,529 compressed bytes**.

| Observation | Outcome and boundary |
|---|---|
| Pinned source, recursive submodules and minimal RV64 tool provisioning | Prepared; inventory checks passed against the clean execution checkout |
| Memory-model dependencies, kernel library and host runtime | Built successfully; this does not prove a GPU workload result |
| Initial FP16 SimX attempt with GCC 14.2 | Failed during compilation of pinned spdlog/fmt with `-Werror=dangling-reference`, before the numerical workload ran; the failed command and log are retained |
| Dedicated GCC 11.3 compiler and completed numerical cases | Compiler smoke and all three paired workloads passed their CPU-reference checks |
| First FP16 processor-RTL build | Stopped because the supplied Verilator Makefile expected an absent `ccache` executable; the runner now explicitly sets `OBJCACHE=''`, and the bounded direct-compile retry passed. Both attempts are retained |
| Frozen six-case numerical matrix | [P01-A02 accepted](evidence/p01-native.json): all six cases pass; review reconciled 15 command logs, 18 configuration snapshots and 41 exported artifacts |
| Separate fresh generated-build smoke | [P01-A01 accepted](evidence/p01-build.json): fresh FP16 SimX generated build, five successful commands and zero reference errors; reused dependency libraries remain explicitly pinned |
| Supplemental full-AFU `xrtsim` smoke | [Pass](evidence/p01/xrtsim/report.json): four successful commands and all 16 integer reference points; vendor `hw_emu` remains a separate obligation |
| Historical source-root project/tooling checks | The reviewed baseline revision passed 346 tests and governance validation; this is not the current continuation's test count and does not certify numerical execution |
| Full vendor XRT `hw_emu` | Blocked by missing vendor tools/platform; no P01-A03 pass is claimed |
| Synthesis, physical FPGA and silicon qualification | Not performed by this baseline continuation |

The execution budget uses two compile workers, a 15 GiB free-disk reserve,
6 GiB sampled process-group RSS and bounded logs/time. Host available-memory
observations do not certify a cgroup limit; the execution environment does not
expose that limit. Keep this limitation in the packet.
The baseline's final [resource observation](evidence/p01/resource-observation.json)
records no budget stops, a highest sampled process-group RSS of **3,494,166,528 bytes
(about 3.25 GiB)**, and **53.48 GiB free disk** after all three packets completed.
Simulation durations and these host-resource measurements do not establish
physical accelerator performance.

The [historical packet](evidence/p01/history/README.md) retains failures and old
instrumentation with [raw-to-published hash mappings](evidence/p01/history-manifest.json).
The [implementation review](evidence/p01-review.md) records concrete findings,
independent corrections and acceptance reviews. The [P01 handoff](p01-handoff.md)
records the delivered scope and remaining vendor-integration obligation.

## Offline packet verification continuation

The published [offline packet verifier](p01-packet-verification.md) implements
P01-T06 evidence checks: original-byte verification, a separate unsigned
inventory, and an explicit published-export mode. It also adds a bounded
[CI consistency check](../../ci/project/check_baseline_packets.py) for the
retained native and clean-build exports. Run from the source root:

```sh
python3 ci/project/check_baseline_packets.py
python3 ci/project/baseline_packet.py verify-export docs/project/evidence/p01/native \
  --require-native-records
```

The [packet continuation handoff](p01-packet-handoff.md) records the initial
`e9c9ac0` checkpoint, incorporation of baseline delivery `25ca2e6`, and published
implementation [22c545c](https://github.com/baabi-boo/AI-GPU/commit/22c545c632628f9da9f18ccf8fb512a8bfac7f81).
That historical immutable release checkout passed all 591 governance/tooling
tests, the project checker, preflight and both published-packet checks. The handoff records
exact identities, independent review and hosted CI observations. This
continuation performed no new GPU execution and grants no new acceptance.
The six-case and clean-build evidence above remain the reviewed execution record;
P01-A01/A02 remain accepted and P01-A03 remains blocked. Published verification
checks public bytes and retained records, without proving original log bytes or
the asserted redaction relationship.

The separate [packet continuation ledger](p01-packet-agent-execution.json)
records that historical delivery's actual assignments and dispositions. The
original P00 and P01 execution ledgers remain separate historical records.

## Vendor hardware-emulation preparation

The [hw_emu runbook](p01-hwemu-runbook.md),
[manifest contract](p01-hwemu-manifest.md) and
[preparation handoff](p01-hwemu-handoff.md) describe the read-only P01-T05
preparation route. Its implemented source includes:

- Read-only [inventory and planning commands](../../ci/project/hwemu.py).
  Inventory reports local prerequisites without invoking vendor tools. Planning
  validates a strict inert manifest, file hashes and a matching retained receipt,
  clean source/submodule identities, existing generated-build copies and compiler
  records, lean XRT settings and bounded input/resource observations.
- The corrected XRT INI hook path, `sw/runtime/xrt/xsim.tcl`, with debug mode off
  and the inherited profiling/trace options disabled. Waveforms require explicit
  debug configuration plus
  `VORTEX_XRT_WAVEFORM=1`; the environment flag alone does not enable debug mode.

A successful plan establishes input consistency only. It retains
`launch_ready: false`, `vendor_qualification_verified: false`,
`execution_performed: false`, `phase_complete: false` and P01-A03
`acceptance_outcome: blocked`. The planner launches no workload and does not
enforce the candidate's execution budget. Actual vendor compatibility, artifact
production provenance and separately supervised execution still require review.
That preparation continuation established no new GPU execution, vendor-emulation
result or physical measurement. At that checkpoint, P01-A01/A02 retained their
accepted evidence, P01-A03 remained blocked and P02 was `not_started`.

## Vendor integration tooling continuation

The [vendor XRT runner](../../ci/project/xrt_baseline.py) now implements the
prepared-artifact P01-T05 route. Its [guide](p01-xrt-integration.md) defines the
fixed RV64 integer smoke, pinned platform/runtime/artifact manifest, reviewed
build receipt, fresh host/kernel build and tracing-disabled direct launch.
Independent tooling tests exercise blocked prerequisites, provenance drift,
configuration mismatches, process failures and reference-result handling.
The [continuation handoff](p01-xrt-handoff.md) records verification and delivery.
The [review record](p01-xrt-review.md) documents the corrected findings; the
separate [execution ledger](p01-xrt-agent-execution.json) records **60 completed
assignments in ten waves of six**, without counting or changing the historical
P00/P01 and concurrent preparation assignments.

The combined implementation at `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b`
passed **1,075 tooling tests, with zero failures, errors or skips**. The
[merge verification packet](evidence/p01-xrt-merge/merge-verification.json)
retains the exact source identity, test log and immutable-base R2 classification.
The working tree was clean before and after that run, and all 92 recorded
selected source hashes stayed unchanged. Later documentation and delivery
records are separate from this tested source checkpoint. The original
[875-test packet](evidence/p01-xrt-tooling/verification.json) and intermediate
1,071-test result remain historical observations at their own revisions.
The [publication map](p01-xrt-publication-map.json) distinguishes these local
execution identities from API-created GitHub commits with identical trees;
the actual test runs are not relabelled as later executions.

The two tools have separate manifest, receipt and report schemas; their shared
`schema_version: 1` does not make inputs interchangeable. The XRT runner requires
its own independently reviewed manifest/receipt and a fresh build directory,
constructs fixed commands and does not consume a `hwemu.py` candidate. There is
no automatic adapter or promotion from a preparation plan to execution. The
later [compiler-record continuation](p01-compiler-records.md) resolves the
read-only planner's F1 compiler-glob follow-up and strengthens both inspectors.
That correction does not grant a preparation candidate launch readiness or
replace the execution runner's independent input review.

That vendor-tooling continuation found no vendor executables, vendor roots or
qualified platform/artifact packet. No vendor `hw_emu` job ran, and it left the
then-existing accepted native evidence and phase states unchanged. P01-A03
remains blocked; tooling tests or a read-only plan cannot supply its missing run.

## Next bounded action

**P06-T01 — implement and independently review a separately versioned native
pending-balance and run/reset witness.** Start with the
[managed-preflight handoff](p06-managed-preflight-handoff.md),
[completed replay audit](evidence/p06-managed-preflight-replay/development-audit.md),
[conditional lifetime argument](../designs/simx_counter_lifetime_v1.md), and
[broader qualification plan](p06-mpm-qualification-plan.md). The successful
`57248e73` original already contains four managed processes, 132 launches and
4,224 exact output words. Its complete inert replay is implemented; neither
the original nor replay supplies the missing per-run pending observations.

Expose the live processor's pending-read balance read-only. Bind all 33 run
boundary pairs to the owned processor, zero balance before reset and after
successful completion, exactly one launch reset per run, each output flush,
the terminal vector and actual destruction. Retain zero origins, checked
updates, exclusive ownership, worker joins and absence of later updates. Apply
the source-bound 33-selector-to-40-component theorem; a new 40-field inspector
is not required merely to restate its monotone-storage premises. The transient
pending balance is separate because responses decrease it and reset clears it.
Exclude diagnostic seeds, mutation accessors and tiny guard limits from the
actual measurement binaries.

Fresh dependency receipts must separately connect reviewed source and complete
build inputs to configure/compile/link products and the bytes actually loaded
or statically linked. Cached product hashes and source inventories do not
establish that origin. Preserve the exact RV64 `p02-tfr`, timing SimX, `PERF=1`
route, 33 available selectors, 40 backing components and twelve unqueried
unavailable rows.

Extend the inert validation through a distinct reviewed witness version;
retain the original v1 packet and reject it as incomplete evidence for the new
lifetime requirement. Review controls for missing, duplicate or reordered
boundaries, nonzero balance erased by reset, invalid terminal ownership,
incomplete cleanup and source/product substitution. Then obtain a fresh
four-process FP16/BF16 × policy original with the unchanged 132-launch,
4,224-word population and the additional actual observations. Complete
qualification still requires both lifetime and dependency obligations plus a
separately reviewed pre-execution admission/final-validation path. All seven
qualification/readiness/execution/coverage/acceptance fields remain false in
the current preflight and replay; the three unresolved obligations listed above
remain open. Preserve warm v1's unconditional `P06-WARM-RV64-MPM-HIGH-HALF`
block and `absolute_no_wrap_bound="not_established"`.

Run a fresh complete matched warm attempt only under the reviewed qualification
route and unchanged [sampling/rejection rules](../designs/warm_workspace_benchmark_v1.md):
24 processes, 792 launches and 25,344 exact output words, including excluded
primes and warm-ups. Retain all failed attempts and exact identities. Preserve
the [accepted cold baseline](evidence/p06-baseline/README.md) separately.
P06-A02 still requires matched correctness, native RTL and applicable
parity/performance evidence; A03 requires a reviewed target budget and
synthesis/resource/timing reports. See the [phase guide](phases/p06-performance.md)
and [backlog](backlog.md). The two-job, 4 GiB memory and 15 GiB disk prerequisites
and inherited 267 → 283 DSP area finding against the 5% threshold remain unchanged.

**Parallel framework task:** preserve the
[accepted copying binding](evidence/p05-python/acceptance-binding.json) and
[handoff](p05-entry-handoff.md), then independently review the existing PyTorch
custom-op implementation's installed execution and compatibility artifacts.
Prior successful CI does not itself close A02/A03; no new P05 acceptance decision
is made here. P05 remains `in_progress`; its
[phase guide](phases/p05-framework.md) retains the outstanding gates.

**Parallel blocked hardware task:** P01-T05 still needs a qualified vendor
release/platform, matching prepared `hw_emu` artifact packet and actual reviewed
DMA/launch/completion smoke through the [vendor integration guide](p01-xrt-integration.md).
Do not spend money, install oversized vendor tooling, claim a P01-A03 pass or close
P01 without the missing evidence. This work must be completed before P07.

## Preserved P00 history

P00 was authorized and merged through
[pull request 1](https://github.com/baabi-boo/AI-GPU/pull/1). The original source
baseline is `da55a516a48b49013724f697d3c12a48932b449f`; the reviewed source candidate
was `5a97e59ed95163c585106250194f816353d6ca4e`, tree
`9f65ae6e2bce7adeaec2432c11756510028c8bc0`. The reviewed PR head was
`bebef861742165db1d0d78352ac008b079a35fdd`, and the verified merge commit was
`106b01945d102eec169e68400b2cb8df985236cb`.

The [accepted delivery record](evidence/setup-accepted.json),
[merge observation](evidence/setup-merged.json),
[source validation](evidence/setup-validation.json),
[command log](evidence/setup-validation.log),
[independent review](evidence/setup-review.md),
[publication observation](evidence/setup-publication.json) and earlier
[blocked delivery record](evidence/setup-delivery.json) remain unchanged.
Their historical checks and workflow observations do not qualify P01.
The original [P00 agent ledger](agent-execution.json) records its 60 completed
assignments across 10 waves; it is not the ledger for this P01 continuation.
The separate historical [P01 ledger](p01-agent-execution.json) records the baseline
delivery's completed assignments. Neither historical ledger counts the current
hardware-emulation preparation; requested totals do not establish completion or
hardware evidence.
The protected README illustration, upstream attribution and inherited golden
results remain preserved; see the [baseline inventory](baseline.md).

## Required handoff for every continuation

Read [AGENTS.md](../../AGENTS.md), this page and the canonical roadmap against
the current checkout. Use the [handoff template](handoff.example.md) to record
exact changes, tested source/tooling identities, commands, results, not-runs,
review findings, publication state and one next bounded action. Update status
and phase evidence together. Preserve failures and never convert missing native
or integration evidence into a passing gate.

## Preserved baseline collaboration history

The historical [P01 execution ledger](p01-agent-execution.json) records **60 completed
distinct agent assignments across 10 logical waves**, scheduled with at most three
subagents active concurrently for the accepted baseline delivery. It does not
count assignments in later hardware-emulation or local-qualification continuations. The original
P00 ledger remains unchanged. The completed historical assignments support that
implementation and review; vendor A03 remains blocked independently of agent count.
