# P06 simulator completion audit

## Decision

The audit starts at `42809ff0c1b81384d7c9b079e4ef786be8407600` on `master`.
The selected implementation is reliable simulator completion at the host backend
boundary, a prerequisite discovered while reviewing the
[counter qualification plan](p06-mpm-qualification-plan.md). Execution faults
must reach the caller before a future counter-bound guard can be trusted.

The completion and full-platform accounting repairs are implemented. The first
checkpoint, `db5ebb3a16770004423f2456ec6d0caaa0aced6d`, passed host tests and
dedicated hosted native controls. A later consumer audit found and repaired an
overbroad exception boundary that broke recoverable CP allocation errors. That
correction has independent host regression, source review and fresh native
verification at `4781ca96db15a1d130626edc7a73411a4f6c2e7c`.
[Native run 45009314161](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314161)
passed both declared cells, with independent review of the original artifact.
Its executed merge `e929c52d05bad80b28dd4085a97838d7fe2de354` has the identical
tree `6dd0d759390cda78ec63ad0caacc00a08f03e2bc`. Both completed Project
Governance runs at that repaired tree passed **2,993 tests each**, including all
83 focused completion tests, with independent original-log verification. The
[evidence packet](evidence/p06-simulator-completion/README.md) records the distinct
revisions and original results. No performance or phase acceptance follows from
either checkpoint.

## Findings and disposition

The first four findings concern the audited parent. Cleanup was reproduced
using the actual SimObject/SimChannel framework. The CP allocation finding was
discovered in the initial completion implementation during consumer review.

| Finding | Evidence and consequence | Disposition |
|---|---|---|
| SimX suppresses processor exceptions | Legacy `Processor::run()` catches exceptions and returns `-1`; the runtime's void launch lambda discards that result | Add `run_checked()` to propagate model exceptions while preserving the legacy API and body |
| Legacy return is not a reliable status | `Operands::get_exit_code()` reads x3 (`gp`), a legitimate global-data pointer; even integer `-1` can be valid | Ignore the legacy register-derived result on the checked path; native controls exercise `7` and `-1` |
| Both host backends discard asynchronous exceptions | Future readiness/wait without `get()` can hide a stored exception | `AsyncRun` consumes outcomes and keeps processor failures terminal |
| Immediate completion can lose the busy edge | The CP requires busy to rise before falling; current readiness alone can skip the rise and leave `WaitBusy` stuck | Preserve the unobserved launch edge independently of future completion; deterministic and mutation controls cover it |
| Exceptional teardown can retain channel accounting | A real-framework probe left `inflight_count=1` after finalization; a fresh context consumed its message but remained non-idle | Timing and functional cleanup retire abandoned accounting after disposing all platform work; actual-framework tests and native fresh-context control exercise declared scopes |
| Initial catch-all breaks recoverable CP OOM | CP scratch allocation throws after selecting `EngState::Retire`; blanket catch changed OOM into terminal INVALID_VALUE and prevented safe continuation | Latch only processor-origin failures, preserve inherited CP/host exception mapping, and run the original lifecycle suite unchanged |
| Counter qualification remains incomplete | The old native SimX transport test seeds five of 33 required available sources, under a different TCU-disabled configuration; no absolute cumulative bound exists | Preserve warm v1 rejection and freeze the exact selector/coherence/lifetime contract before new qualification |

Processor RTL's `Processor::run()` returns `void`; no RTL kernel exit-code
reporting is inferred. Its completion repair concerns host exception transport
and ordering. The existing callback adapter maps nonzero HAL results to
`VX_ERR_INVALID_VALUE`; no public error code or ABI mapping is changed.

## Implemented boundaries

The [completion contract](../designs/simulator_completion_v1.md) separates checked
SimX execution from the legacy register result. Both backends use the shared
[AsyncRun owner](../../sw/runtime/common/async_run.h) to consume asynchronous
outcomes, retain an unobserved launch edge, reject work after processor failure,
and join pending execution before freeing memory or destroying the processor.
Synchronous DCR, LLC-memory and applicable drain hooks use the same terminal
processor-failure boundary. Exception type alone does not determine recovery:
a processor `std::bad_alloc` is terminal too.

Unrelated CP/host exceptions keep the inherited common-runtime path. In the
specific CP-copy scratch case, `EngState::Retire` is selected before allocation;
unwinding releases staging, the queue reports `VX_ERR_OUT_OF_HOST_MEMORY`, and
the next CP transaction retires the abandoned descriptor without replaying its
copy. The unchanged [lifecycle test](../../tests/runtime/test_ai_lifecycle.cpp)
requires seeded data to remain unchanged before a fresh same-device transfer
succeeds. Preserving the OOM number alone would not satisfy this contract.

Both timing and functional SimObject cleanup clear abandoned global accounting
only after workers are stopped and platform objects, scheduled events, domains
and inboxes are disposed. Neither ordinary reset nor launch reset is a failed
context recovery entry. External owners surviving finalization are
destruction-only; they do not authorize concurrent live contexts or reuse of old
channels. The normal run loop, packet scheduling and simulated-cycle behavior
remain unchanged.

## Verification by revision and scope

The evidence index retains original logs, exact source/tool identities, review
reports and failed attempts. The initial development logs are historical and
must not be substituted for later clean-source receipts.

| Evidence | Observed result | Scope and limit |
|---|---|---|
| Clean focused host suite at `db5ebb3` | **78 tests passed** in 68.480 seconds, with unchanged tracked source and tool identities | Host backend/common-runtime/framework and runner-policy checks; precedes the CP error-boundary correction |
| Clean focused host suite at repaired `4781ca9` | **83 tests passed** in 87.502 seconds, with source, tool and driver identities unchanged | Includes the five new CP/model error-boundary methods; native verification of this revision remains separate |
| Actual backend/CP and public runtime fixtures | **24 backend cells** and **12 public-runtime cells** pass, using controlled Processor/RAM | Real production callback, CP, adapter, queue and event paths; no native arithmetic or RTL fault mechanism |
| Completion owner | **Eight directed groups**, including deterministic completion before first busy and a ready-`check()` mutation failure | Helper-level scheduling and failure semantics; not native model execution |
| Timing and functional frameworks | **Eight actual-framework cells** pass; old-header controls fail six fault cases while two healthy controls pass | Actual channel/event accounting, one worker and a joined asynchronous fault task; no native functional or multiworker recovery claim |
| Pinned audited-parent sensitivity at `4781ca9` | Both old backends compile; **eight standard/unknown exception cells** fail their intended behavioral assertions | The parent is fixed at `42809ff`; build failures or timeouts are not accepted as sensitivity; the earlier `db5ebb3` replay is retained |
| Native runner policy | **26 focused tests** cover original compiler options/include order, preflight, outputs and failure handling | Tooling checks support the runner but do not replace native execution |
| First dedicated native run | [Run 45006726571](https://github.com/baabi-boo/AI-GPU/actions/runs/45006726571) passes at checkpoint `db5ebb3`, executed as merge `782552fdbb5a216fe7907dde84d8f3f0dc6eb6dd` with the identical tree | RV64 `p02-tfr`, timing SimX, `PERF=1`; independent original-artifact review verifies source/build/log identities |
| Fresh repaired native run | [Run 45009314161](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314161) passes at `4781ca9`, executed as same-tree merge `e929c52d05bad80b28dd4085a97838d7fe2de354`; independent original-artifact review passes | Exact repaired runtime/helper and contract bytes; RV64 `p02-tfr`, timing SimX, `PERF=1`, one worker, direct-RAM CP |
| Real linked processor unit in both native runs | **Five contexts:** nine checked successes, three legacy successes, one checked `OutOfRange`, one legacy caught exception; fresh normal context after the fault | Real Processor/RAM and legacy `gp` values `7`/`-1`; not native public-runtime injected failure |
| Native public success in both native runs | **Two contexts, six launches**, nonzero `gp`, exact global-data/output witnesses and cleanup | Real generated kernel/runtime success; not processor RTL or native fault injection |
| Initial full governance | [Run 45006726409](https://github.com/baabi-boo/AI-GPU/actions/runs/45006726409): **2,988 tests passed** in 1,191.429 seconds | Exact initial checkpoint; not a claim that all broader CI or later production bytes passed |
| Repaired PR governance | [Run 45009314170](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314170), job `137167865708`: **2,993 distinct tests passed** in 1,864.865 seconds, all `ok`, including the 83 focused completion tests | Executed same-tree merge `e929c52d`; original full log and 174 test-module identities independently reviewed |
| Repaired push governance | [Run 45009309941](https://github.com/baabi-boo/AI-GPU/actions/runs/45009309941), job `137167851515`: **2,993 distinct tests passed** in 1,891.161 seconds, all `ok`, including the same 83 focused tests | Executed `4781ca9` directly; same ordered test inventory; Project Governance success does not establish that broader CI passed |
| CP error-boundary correction | **Four full unchanged lifecycle cells** cover three OOM stages, no replay, released ownership and same-device continuation; **34 further cells** keep processor faults terminal | Both backend adapters with RAM/LLC as applicable, controlled Processor/RAM; the separate repaired native packet establishes only its declared native scope |
| CP regression sensitivity | Both `db5ebb3` backends/helper compile against the same lifecycle test; **four controls fail the intended OOM assertion** after allocation stages 0/1 pass | Proves the narrower boundary repairs a reproduced regression; every expected failure is exit 1, not compile failure or timeout |

The native archive for the initial checkpoint has SHA-256
`d5f71cec99321c5f8e6c11fab37875aa93e551270a1a15c29b3fe9af6c766588`.
Review verified 761 retained source bodies against the checkpoint, 18 command/log
records and five compiler/header roles. Its three backend/helper input files
subsequently changed for CP OOM compatibility, so the earlier native pass cannot
close verification of that repair. The fresh
[repaired native archive](evidence/p06-simulator-completion/checkpoints/native-4781ca9.tar.gz)
retains artifact `14749901531`, whose original ZIP is 2,792,870 bytes with SHA-256
`461ddd226474aff20205b5ae852489fd4e88f21f7065a74efba25e706eb087b9`.
Its independent review again checks 761 source bodies, 18 command/log records,
five compiler/header roles and 87 actual model-object compile commands, including
the three repaired runtime/helper files and completion contract.

The execution checkpoint remains `4781ca9`. Later additions are confined to
README/project documentation and evidence; independent source projection checks
all 3,339 existing blobs outside that allowlist, including every one of the 761
native-retained inputs, against the tested bytes. The allowlist has no overlap
with those native inputs. A later documentation/evidence commit is not described
as the entire tree executed by earlier CI. Structural and manifest validation
apply separately to the assembled documents. The
[evidence packet](evidence/p06-simulator-completion/README.md) retains the exact
projection and final publication observations when completed.

The original failed public-fixture build, runner provenance failures, cleanup
probes and compiled-parent failures remain retained. Native binaries are
identified but not archived; tool records do not inventory every host system
header or dynamic library. Before/after hashes detect observed drift and are not
a hermetic-execution claim. The 15 GiB native disk reserve remains mandatory;
local host fixtures and adequately provisioned hosted native execution have
separate resource scopes.

## Next bounded development

Build on the independently reviewed host and fresh native evidence for repaired
`4781ca9`. Freeze and review the
[versioned counter qualification contract](p06-mpm-qualification-plan.md) before
implementing its enforcement. It must bind the exact RV64 tensor configuration,
all **33 available selectors** and 12 unavailable rows, real backing-source
coverage, coherent two-half reads, and an enforceable absolute bound over the
complete cumulative context lifetime. A per-launch clock or host timeout cannot
bound counters that survive launch resets. No such guard is implemented here.

Only after those obligations pass should a fresh matched warm attempt run under
the unchanged sampling and rejection rules: **24 processes, 792 launches and
25,344 exact output words**, including excluded primes and warm-ups. Historical
warm v1 remains unconditionally blocked. A successful workload or replay does
not establish qualified performance.

## Preserved obligations

P06-A02/A03 remain open. Warm v1 keeps `qualified=false` and
`absolute_no_wrap_bound="not_established"`. P01-A03 vendor `hw_emu`, independent
P05-A02/A03 framework qualification, the inherited **267 → 283 DSP-area failure**
against the unchanged **5% threshold**, and physical FPGA/silicon work remain
separate. No pipeline, arithmetic, ISA, public ABI, frozen workload, statistical
predicate, golden, tolerance or phase acceptance is changed by this repair.

The [delivery ledger](evidence/p06-simulator-completion/delivery-ledger.md) records
**60 actual agents across ten logical waves**, six per wave, with completed initial
assignments and separately scoped follow-ups.
An agent count is not a test result, native qualification, human approval or gate
waiver. Existing acceptance records and retained failures preserve their scopes.
