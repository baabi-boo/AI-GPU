# P06 simulator completion audit

## Decision

The audit starts at `42809ff0c1b81384d7c9b079e4ef786be8407600` on `master`.
The selected implementation is reliable asynchronous simulator completion at
the host backend boundary, a prerequisite discovered while reviewing the
[counter qualification plan](p06-mpm-qualification-plan.md). Development host
checks are available, but implementation and checkpoint evidence remain
incomplete: exceptional channel cleanup needs repair, and actual native
completion execution is `not_run` pending hosted CI.

The repaired RV64 host counter route still needs exact warm-configuration
coverage, coherent-read qualification and an absolute cumulative no-wrap bound.
A prospective guard cannot be trusted if its failure disappears at the runtime
boundary. This audit therefore addresses failure propagation before enabling
any new warm performance qualification.

## Findings

The first four findings describe the audited parent implementation. The channel
cleanup finding was subsequently confirmed by a development host probe using
the actual [SimObject/SimChannel implementation](../../sim/common/simobject.h).

| Finding | Evidence | Consequence |
|---|---|---|
| SimX suppresses processor exceptions | `sim/simx/processor.cpp::Processor::run()` catches exceptions and returns `-1`; the runtime's void launch lambda discards that return | A failed simulation can appear to finish successfully |
| Legacy return is not a reliable status | `Operands::get_exit_code()` reads register x3 (`gp`); kernel startup initializes `gp` for legitimate global-data access, while `_Exit` writes the exit-code MMIO address | Rejecting every nonzero legacy return would break valid kernels |
| Both host simulation backends discard asynchronous exceptions | SimX and processor RTL use `future<void>` readiness/wait calls without consuming the result | An exception stored by the future need not reach the host caller |
| Both can miss an immediate completion | `CommandProcessor::tick_launch()` requires busy to rise before falling, while the backend hooks expose only current future readiness | A task finished before its first poll can leave `WaitBusy` stuck |
| Exceptional teardown can retain channel accounting | A host probe leaves `SimChannelBase::inflight_count()` at 1 after an exception, `SimPlatform::finalize()` and full object destruction; a fresh context consumes its own message but still reports `idle=false` | Cleanup accounting remains an implementation blocker; a new device/context is not yet qualified to run successfully after that failure |
| Qualification remains incomplete | The directed transport packet uses TCU-disabled configurations; 33 warm counters are available and accumulate without a proved absolute bound | Existing v1 rejection and phase states must remain unchanged |

Processor RTL's `Processor::run()` returns `void`; no RTL kernel-exit-code
reporting is inferred. Its repair concerns asynchronous exceptions and completion
ordering. The public adapter currently maps nonzero HAL results to
`VX_ERR_INVALID_VALUE`; that ABI and mapping remain the applicable contract.

## Implementation and verification scope

The [completion contract](../designs/simulator_completion_v1.md) preserves the
legacy SimX `run()` interface and adds `run_checked()` to propagate model
exceptions without interpreting `gp` as a runtime status. Valid nonzero values,
including `-1`, remain successful. Both runtime backends now use the shared
[AsyncRun owner](../../sw/runtime/common/async_run.h) to consume each asynchronous
outcome, retain terminal failure for the backend device lifetime and preserve the
launch edge before completion. A failed launch must not retire successfully or
execute later work from the same command burst. Cleanup joins the worker before
freeing memory or destroying the processor, but the newly observed channel-count
leak still requires a separate repair and proof. Do not infer successful native
cleanup or fresh-context execution from the host wrapper checks.

Verification must exercise actual production backend callbacks and command
processor behavior, including immediately ready success, delayed completion,
valid nonzero `gp`, standard and unknown exceptions, persistent failure,
queued work and destruction. Parent sensitivity must distinguish a successfully
built old implementation failing behavioral assertions from a build failure.
Fault-injected host evidence and actual native execution are reported separately.

## Development verification checkpoint

These results belong to development based on the audited parent. They are not a
completed clean-source integration or acceptance packet. The retained initial
logs precede later helper/runner refinements; final source identities, all raw
outcomes and independent review still need reconciliation.

| Check | Observed checkpoint scope | Limit |
|---|---|---|
| Backend and command processor host fixture | [Six passing groups](evidence/p06-simulator-completion/host/initial-backend-tests.log) × two backends × RAM/LLC = **24 cells** | Production backend/CP code with controlled Processor/RAM faults; no native processor or RTL arithmetic result |
| Public runtime host integration | [Three passing groups](evidence/p06-simulator-completion/host/initial-public-runtime-tests.log) × two backends × RAM/LLC = **12 cells** | Actual adapter, polling, queue and event paths with controlled Processor/RAM faults |
| Completion-owner helper | Eight directed groups now cover immediate completion, retained launch edges, sticky exceptions, overlap and destruction; the ready-`check()` case has mutation sensitivity | The [initial retained log](evidence/p06-simulator-completion/host/initial-async-owner-tests.log) records the earlier seven-group pass; later eighth-group and mutation results require final packet reconciliation |
| Parent sensitivity | The [pinned parent report](evidence/p06-simulator-completion/host/initial-parent-report.json) records successful old-backend compilation and intended behavioral failures in all **eight exception cells** | The failures establish sensitivity to discarded exceptions; compile failures or timeouts do not substitute for these observations |
| Native-runner host checks | **26 focused tests** cover output, compiler/preflight and failure handling, including strengthened provenance checks | Development tooling evidence; final source/log reconciliation remains pending and no native execution is implied |
| Production SimObject cleanup probe | `inflight_count=1` and `idle=false` survive exceptional teardown; the fresh context remains non-idle after consuming its own message | Confirms an open cleanup defect; repair, regression and retained final evidence are still required |
| Linked native model and public-success regression | **`not_run`**, pending adequately provisioned hosted CI | The [native unit](../../tests/unittest/simx_completion/main.cpp), [public regression](../../tests/regression/simx_completion/main.cpp), [runner](../../ci/project/p06_simulator_execute.py) and [workflow](../../.github/workflows/p06-simulator-completion.yml) are implemented, not executed evidence |

The native runner's declared scope is RV64 `p02-tfr` timing SimX with performance
counters enabled. Its real-model exception/legacy-`gp` unit and successful public
launch controls have distinct purposes. Neither supplies a native public-runtime
injected-failure result or processor-RTL execution. Retain the native fresh-context
check while repairing channel cleanup. The earlier
[public-fixture build failure](evidence/p06-simulator-completion/host/initial-public-build-failure.log)
remains part of the development history.

No pipeline, arithmetic implementation, ISA, public ABI, frozen workload,
statistical predicate, golden or threshold change is part of this repair.
The 15 GiB native disk reserve remains mandatory; the initial local inventory
is below it. Host verification is available locally; formal native execution
requires an adequately provisioned environment.

## Next bounded action

Repair and prove exceptional channel accounting without changing normal packet
or processor timing. Then complete native completion verification, including
the checked real-model failure and fresh-context control, and independently
reconcile the final host/parent/native packet. Keep any unexecuted scope marked
`not_run`; a workflow definition or host-tooling pass cannot supply that execution.

After completion verification, implement and independently review the
[versioned counter qualification route](p06-mpm-qualification-plan.md): exact
warm configuration and required selectors, coherent reads and a proved absolute
cumulative no-wrap bound. Only then collect the unchanged fresh matched warm
attempt: **24 processes, 792 launches and 25,344 exact output words**, including
excluded primes and warm-ups. Preserve the unconditional warm v1 rejection.

## Preserved obligations

P06-A02/A03 remain open. Historical warm v1 remains blocked with
`qualified=false` and no established absolute no-wrap bound. P01-A03 vendor
`hw_emu`, P05-A02/A03 independent framework qualification, the inherited
267-to-283 DSP area failure, and physical FPGA/silicon work remain separate.
All existing acceptance records and retained failed attempts keep their scope.

Final implementation results, independent reviews and exact source-bound
verification will be added when complete. Requested agent counts are not evidence;
the delivery ledger records actual completed assignments only.
