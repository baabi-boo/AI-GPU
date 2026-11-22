# Independent R3 review — wave 3, agent 6

## Scope and identity

Reviewer: `/root/w03_a06_independent_r3`, independent of implementation. Reviewed the working tree against `42809ff0c1b81384d7c9b079e4ef786be8407600`; HEAD still equaled that base during this review. The changes included untracked files, so the tracked `git diff` alone was insufficient. This is a working-tree review, not a review of an invented candidate commit. The file hashes below bind the snapshot. Refresh against actual checkpoint and final commit hashes is still required.

Read the repository code-review and simx-review skills and their required AGENTS, C++/Verilog conventions, bug-fix policy, review policy, SimObject and SimX architecture documents. Also read the full new simulator completion contract, the audit, acceptance policy, resource guidance and relevant current status. Reviewed every production hunk, the new AsyncRun header, all new native test files and completion build fragment, the new workflow/native runner, all new host fixtures/test drivers, and the existing CP, callback adapter, device polling, queue and event consumers.

No repository source edits, commits, checkouts, resets, native builds, downloads, golden changes or waivers were performed. The only authored file is this requested review report outside the repository.

## Findings

### F2 high static-proof — new host fixtures omit required control-flow braces

Working-tree paths: `ci/project/fixtures/simulator_completion/control.h:40`, `:48`, `:74`, `:76`; `processor.h:15`; `mem.h:28`; and `main.cpp:34`, `:39`, `:49`, `:71`, `:126`, `:163`, `:186`, `:222`, `:269`, and the group dispatch beginning at `:274`.

**What:** These new C++ fixtures use brace-less if/else/for bodies, contrary to the unconditional requirement in `docs/coding_guidelines_cpp.md` §2 and the SimX review checklist. These are new files in this change, so they are not pre-existing violations outside the diff.

**Scenario:** The current fixture source directly violates the mandatory rule. The rule addresses reachable maintenance mistakes such as adding a second statement to the exception-injection branch in `Control::execute()` or the reset-write loop in `sticky_failure()`, leaving that statement outside the intended branch/loop. This is a rule finding, not a claim that the current statements already fail at runtime.

**Smallest correction:** Add braces to each new control body without changing the assertions or fault behavior, and retain the relevant host rerun after fixture bytes are final. Root has already corrected the two native main.cpp files; I reread those corrections and dropped the earlier native-file brace finding. Root was notified of the remaining host fixture locations while their parent sensitivity build was active.

### F2 high missing-test — required native completion evidence remains not run

Working-tree contract: `docs/designs/simulator_completion_v1.md`, “Required verification”; new native paths: `tests/unittest/simx_completion/main.cpp`, `tests/regression/simx_completion/` and `ci/project/p06_simulator_execute.py`.

**What:** The linked real-Processor/bounded-RAM test and real public-runtime success regression are source-present but not executed in the evidence available to this review. They are expressly listed as required verification by the new contract. The local 15 GiB reserve prevents running them here and must remain intact.

**Scenario:** The controlled Processor fixture can pass even if the real linked checked entry, real RAM fault, real generated kernel/startup, or real repeated-context path fails to build or execute. In particular, controlled `legacy_gp=7` is not native proof that normal x3 values 7 and -1 survive the checked path, nor that an actual global-data kernel works. A proposed workflow or parser test does not resolve those risks.

**Smallest correction:** Execute the fixed hosted native runner from a clean, freshly configured checkpoint tree with the original resource bounds; inspect the raw unit/public logs, compiler records, generated inputs, source/tool hashes and final report. Both cells must pass their exact observations, and the independent review must then name that actual tested commit. Preserve every blocked/failed attempt. This finding blocks completed native-contract qualification; it does not forbid an explicitly unqualified, user-authorized checkpoint publication whose purpose is obtaining the hosted evidence. Such a checkpoint is not a waiver or a pass.

### F1 high missing-test — no deterministic successful collection through check() before first busy poll

Working-tree fixture: `ci/project/fixtures/simulator_async_run_test.cpp:88`–`:116`; helper: `sw/runtime/common/async_run.h:38`–`:52`.

**What:** The deterministic immediate tests consume success with `wait()` or `wait_for()` before the first busy observation. The subsequent `check()` calls therefore see an invalid future. They do not directly exercise `check()` collecting a successful ready future while its launch edge remains unobserved. The backend/public fixtures deliberately observe a pending launch before releasing their worker.

**Scenario:** A future regression that clears `start_pending_` only in `check()`'s ready-success branch would lose the CP's first busy edge when a task completes before its first poll, while the two deterministic immediate tests as written could still pass. The current implementation is correct on static inspection; this finding concerns sensitivity of the claimed coverage, not an observed production failure.

**Smallest correction:** Add a disclosed deterministic seam that establishes an already-ready successful future, invoke `check()` as its first collector, and require exactly busy then idle. Do not substitute a sleep or repeated lucky scheduling. Alternatively identify a separate already-retained test that proves this exact branch.

## Production review conclusions

No production correctness defect was identified in the reviewed snapshot.

| Obligation | Review result and reason |
|---|---|
| First busy edge | `start_pending_` is independent of future validity. `busy()` first checks/collects completion, then consumes the pending launch edge exactly once. Normal collection by `check`, `wait` or `wait_for` does not erase it. Thus an immediately completed normal task still produces busy then idle. |
| Exceptional completion | Every operational observer calls `require_healthy`; `collect()` uses `future.get()`, marks terminal failure and rethrows. `busy()` cannot return idle for an exceptional future, and cannot return the initial busy edge instead of observing an already-ready exception. |
| Overlap and task creation failure | `start()` rejects a valid pending future or unobserved launch edge, retaining failure without replacing the original task. An exception from async task construction is latched and reaches the guarded CP callback. |
| No false error for valid gp | Runtime SimX now calls the void checked entry, which invokes the unchanged implementation and discards its legacy register-derived result. It does not interpret nonzero x3, including -1, as execution failure. The legacy direct `run()` catch/log/-1 path is unchanged. |
| Unchanged execution loop | A read-only byte comparison showed that removing only the new `Processor::run_checked()` definition makes current processor.cpp identical to its base version. No model timing, retirement, arithmetic or pipeline hunk changed. |
| Failure before CP retirement | The existing CP launch FSM must observe busy before transitioning to its drain state, then observes idle before the engine can retire the launch. A thrown busy observation unwinds before those transitions. Both backend callbacks catch it and latch failure. |
| Same-burst suppression | After a failed busy observation, the exception exits the 256-tick loop. No subsequent tick in that transaction executes. All later CP transactions fail at their initial health check. A later DCR in the same fetched cache line cannot run. |
| Failed read output | Both callbacks perform their guarded checks before assigning the result pointer. Exceptions return -1 and leave the supplied value untouched. A task still pending at the last check may complete later; that does not create a false retired sequence because its CP launch has not reached idle/retire. |
| DCR/LLC/drain synchronization | The existing DCR and LLC access waits now consume task results rather than only waiting for readiness. Processor RTL drain does the same. Direct RAM and registered-host-memory routes retain their serial CP ordering; the contract does not claim independent concurrent host access is safe. |
| Destruction | Each backend explicitly calls `run_.join()` before freeing its registered host regions. `join()` consumes the future, catches exceptions without throwing, and still waits when failure was latched earlier. Processor and RAM members therefore outlive the worker. AsyncRun's own destructor is an additional cleanup guard. |
| Public mapping | `CallbacksAdapter::r()` maps nonzero HAL results to the existing `VX_ERR_INVALID_VALUE`. `Device::cp_poll_seqnum_()` checks that status before accepting seqnum. Queue completion forwards the failure to Event; Event retains it across repeated and higher-value waits. |
| Queue error consumption | `Queue::finish()` clears a queue-local asynchronous error, but it cannot clear the backend's `failed_`. Later commands on the same device, including a new queue, encounter the same failed CP boundary. No backend reset/recovery path was added. |
| Serial control and ABI | The runtime's CP mutex serializes its register transactions. AsyncRun deliberately adds no concurrent-caller lock or cross-device SimX scheduling claim. The public callback table, installed API, on-wire status and error enum remain unchanged. |
| Incremental build dependency | Both backend shared-library targets now depend on the common async header. Their compiler recipes still compile only SRCS, so the header is a dependency rather than a translation-unit input. The new completion.mk includes the accepted SimX Makefile, which was independently confirmed unchanged. Configure copies the additive .mk fragment. |

The helper intentionally does not cancel hung workers, recover failed device state, catch signals/abort, or confer native SimX concurrency. Those limitations match the written contract. No parity claim is derived from host wall time; the unchanged execution loop supports the narrower conclusion that this patch introduces no model timing operation.

## Workflow and runner review

The new workflow executes only on a hosted `ubuntu-22.04` runner, with `contents: read`, credentials not persisted by checkout, no secrets interpolation, no self-hosted runner, no pull_request_target/workflow_run escalation, and restore-only cache actions. Fork PRs do not gain a persistent runner or write credentials. Cache identity and clean-source preparation use the existing p04 preparation helper; missing cache/resource prerequisites fail rather than silently install a replacement toolchain. There is no suppression via continue-on-error or successful failure masking, and shell pipelines use pipefail.

The native runner keeps a fixed RV64/p02-tfr/timing-SimX/perf-on scope, two jobs, one model thread, a 15 GiB reserve, 4 GiB RSS budget, bounded command timeouts and raw-log limits. It requires fresh non-overlapping paths and a clean source snapshot, configures from the source tree into a new build tree, validates original per-role compiler records independently, hashes/retains source and generated inputs, binds tool and binary identities, and checks stability around execution. The verifier requires all ordered unit observations and all six correctly computed public-success witnesses. Report booleans remain `acceptance_claimed=false` and `qualified=false`; the exact completed matrix is distinct from phase acceptance. The workflow retains the initialized identity and artifacts even on failure.

The review did not observe a real hosted run, a cache restoration, a native build, a native fault, or a runtime/performance result from this workflow. Its source and host boundary tests establish preparation and verification intent only.

## Evidence actually seen and checks actually run

Read retained initial host logs showing seven AsyncRun tests, six backend/CP groups, and three public-runtime groups passing. The test sources expand the backend/public groups across both backends and RAM/LLC routes. These tests use production callbacks, CP and common runtime with controlled Processor/RAM replacements; they do not execute the actual simulator model. The parent report records eight built old-backend fault cases failing the intended behavioral assertion with exit 1, not a compile failure or timeout. Initial public build failure is retained separately. These initial logs predate in-flight fixture edits and do not establish the final candidate revision.

This reviewer directly ran only inexpensive static checks: `git diff --check`, `bash ci/check_simx_mt_boundary.sh` and `bash ci/check_sw_sim_boundary.sh`; all returned success. Also performed read-only byte comparisons proving the additive-only processor.cpp change and unchanged accepted sim/simx/Makefile. No native or host C++ build was run by this reviewer.

Native unit/public execution: **not run**. Native parent sensitivity: **not run**. RTL elaboration, model parity, performance gates, XRT/FPGA/silicon work: **not run** and not claimed by this review. Existing warm qualification remains false; P06-A02/A03 and all other declared outstanding gates remain open.

## Classification and landing recommendation

**Manual impact class: R3**, because the repair changes externally observable completion/error behavior even though the installed ABI is unchanged, and it adds CI enforcement. The base-copy classifier cannot meaningfully classify the uncommitted/untracked candidate while HEAD still equals the base; rerun the base revision's classifier locally after the actual checkpoint exists, because a workflow changed. A classifier result below R3 does not lower this external-contract classification.

**Verdict: land after the listed mandatory fixes/evidence, within the stated scope.** Fix the remaining new-fixture brace violations, freeze and rerun relevant host evidence, obtain/review the required native evidence, and refresh this review against actual hashes before calling the repair fully verified. A clearly labeled authorized checkpoint to make hosted execution possible is reasonable after code-rule fixes and current host verification; it must retain the native not-run blocker until the hosted packet is reviewed. No golden, gate, phase or hardware waiver is authorized or supplied by this review.

## Snapshot hashes

| Path | SHA-256 |
|---|---|
| `sw/runtime/common/async_run.h` | `17e229eb116c6d50d273780bb969630d0e0141a8aec39f22c0ab0fb62b74d2ed` |
| `sw/runtime/simx/vortex.cpp` | `61a14d8c29f9c2e9bef292d4ef8bbc5892ff6b13ad62110a80915f788917edd4` |
| `sw/runtime/rtlsim/vortex.cpp` | `048f7e96625243024a7f4952fb7e616b4f28c47744e1670e346917b554b6fce4` |
| `sw/runtime/simx/Makefile` | `a904a327b54481567d5efd205da7cba3fed0f7ecb6410ab641753d789c8ee975` |
| `sw/runtime/rtlsim/Makefile` | `1a2e731e8a676d3f57a891dfa380c4992d42ed066c81256a82ea278e78602ab4` |
| `sim/simx/processor.cpp` | `569cf629d1e25ec9a295b20bfadfabbe21cd0989127f2b825fceee99a8062b78` |
| `sim/simx/processor.h` | `588db10c3997e91dd471771cd12bb0329dacbc3902248b84353beebd19bc0438` |
| `sim/simx/completion.mk` | `371f1cc7ad00e00094cb80e03074e114bf38134c59e03a617f34ec9fe209f235` |
| `.github/workflows/p06-simulator-completion.yml` | `233521df10f3b3c90035a533849a17e783a5977a705023609ef73d07ca21b65c` |
| `ci/project/p06_simulator_execute.py` | `b3b5013f4ab8bf3c5bae44a57cfc534ccd306fa98c23b46283161eaf5b0e2843` |
| `docs/designs/simulator_completion_v1.md` | `03825e18a97be8f6031b7cee4ec727578f05d7b96f3894b183967e12c3d3ff15` |
| `tests/unittest/simx_completion/main.cpp` | `343f68f1cf90ea5e81ae9d97d8428df9e5db246fb35ac29af163c5b099b1727e` |
| `tests/regression/simx_completion/main.cpp` | `07687cbb532f3f6901d928da5de181fa76d8c0efc8796bfd578d0c485008b468` |
| `tests/regression/simx_completion/kernel.cpp` | `15f6df7b29f9211b4fdf8ac589265241c177e8059e9a2bebcb479bc3baef8cc6` |
| `tests/regression/simx_completion/common.h` | `ab20e7e7dff9ede29b045f9a38405ee0eab8f366517cc51f9fb1a836b521b926` |
| `tests/regression/simx_completion/Makefile` | `a2f83c95a4b976ea179a5e6f850799f5795646042cff4e2df9afcc1ca4ecbad7` |
| `ci/project/fixtures/simulator_async_run_test.cpp` | `6595038711d89033722de2e2648debda7ae6d3262b9efe073e28778f27752263` |
| `ci/project/fixtures/simulator_completion/control.h` | `ec6018c8119b409ed85c48f977a9c9756b7a8b79267b2406c53b634cb2d727f4` |
| `ci/project/fixtures/simulator_completion/processor.h` | `aa6186abf7450fc10dbdc60c2d31bfc1cabd915025572e9bf29efdef6b03ae87` |
| `ci/project/fixtures/simulator_completion/mem.h` | `dbc3a00e2684b13902bd476e5d33d6d29c318ff9aa347137b10c5d753db2d5e7` |
| `ci/project/fixtures/simulator_completion/main.cpp` | `f06257ac726a6e67dcd9bfe941ef85802f1a53a8705ed9644f9a53e1bd0e728e` |
