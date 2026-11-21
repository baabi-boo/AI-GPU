# P06 ownership review matrix: serial workspace experiment

**DRAFT — design/test input only; unimplemented, unexecuted and unfrozen.**
This companion to the [experiment proposal](p06-next-experiment-proposal.md)
specifies review questions and proposed checks, not a new runtime contract or
acceptance result. Existing behavior below was inspected at source HEAD
`9036b379e3dbdf2b68d1590ca37a47cbf099b7b4`; no native test was run for this document.

## Existing reference interfaces and limits

| Exact interface/source | Existing behavior relevant to this proposal |
|---|---|
| [`ExecutionResult`, `ExecutionBinding`, `ManagedMatmul`, `MatmulOperation`](../../sw/runtime/ai/runtime.h) | `ok()` checks validation, primary and cleanup, **not** `complete`. Callers need both. Output and trace references belong to the operation. |
| [`ManagedMatmul::create`, `submit`, `close`; `RuntimeContext`](../../sw/runtime/ai/runtime.cpp) | Create opens a context; submit has no live-operation exclusion and creates a queue and three buffers per call. Owner close is incomplete while an operation shares its context. There is no native process-wide context/cleanup-poison guard here. |
| [`MatmulOperation::wait`, `close`; `OperationState::release`](../../sw/runtime/ai/runtime.cpp) | Wait does not release resources. Close releases after established completion. Submit already closes no-work failures when `complete` is true; a partial enqueue can return an incomplete operation plus an error. Destruction drains indefinitely. |
| [`ManagedMlp::create`, `advance`, `close`](../../sw/runtime/ai/mlp_runtime.cpp) and [`MlpResult`, `MlpTrace`](../../sw/runtime/ai/mlp_runtime.h) | A model creates its own `ManagedMatmul`, closes each stage before the next, and retains failed/incomplete work for drain. Terminal inference is not proof of release; successful advance leaves the model context open until close. |
| [Managed contract](../designs/ai_operator_contract_v1.md#managed-execution-and-completion); [Python restrictions](../designs/python_binding_v1.md#process-and-concurrency-restrictions) | Native objects are single-caller; this alone permits multiple live operations. Python separately restricts contexts/operations, suspends its idle matmul context for a model, and poisons new work after cleanup failure. These binding rules do not establish a native lease implementation. |

The [queue launch path](../../sw/runtime/common/queue.cpp) locks each queue's
`enqueue_mu_`; [device submission](../../sw/runtime/common/device.cpp) locks
individual command submissions. Separate queues do not establish an exclusive
launch-setup sequence. The SimX process-wide context restriction must also cover
contexts created through `ManagedMlp`, including idle and terminal-but-open models.

## Proposed common guard and states

Both new arms must contain the **same reviewed native ownership guard**, before
the candidate changes buffer lifetime. Reference buffers belong to each operation;
candidate A/B/D buffers belong to its context. Both still create/release queues
and events per operation. A live operation retains the context and its process
reservation. The proposed lease is permission for exactly one outstanding
operation; successful wait alone never returns it. No overlap is proposed.

| Context / operation state | Proposed permitted transition and ownership |
|---|---|
| No context, process healthy | Reserve the single process context slot before native creation; publish one owner only after successful setup. Verified complete rollback returns the slot. |
| Context open, no operation | Validate and acquire its single operation lease before allocation/enqueue. Candidate resident buffers remain owned by the context while idle. |
| Operation preparing or queued | Retain staging, queue/events, buffer ownership and context; reject another submit and another context. Partial submission follows the same rule. |
| Operation complete, not explicitly closed | Output may be read only on successful completion. Lease and context remain held; reject resubmission even after successful wait. |
| Wait/close incomplete | Keep every resource needed by queued work and keep both reservations. Retry bounded drain; timeout is not cancellation. |
| Completed explicit operation close, cleanup successful | Release events/queue and reference buffers; then return the operation lease. Candidate buffers remain until context teardown. Preserve any earlier primary failure. |
| Owner close with outstanding lease | Report incomplete and retain context. Owner destruction leaves the retained operation responsible for context lifetime; its final close performs last-owner teardown. |
| Cleanup failed, whether explicit or during destruction | Mark the process unusable for new contexts/submissions. Continue draining retained owners; never return a reusable lease or erase the failure by repeated close. |
| Context teardown complete, cleanup successful | Release resident buffers and remaining context resources, then the process reservation. Repeated close performs no duplicate release. |

The exact state/error representation, acquisition rollback and destructor reporting
remain freeze questions below; these rows do not describe implemented behavior.

## Proposed failure and test matrix

Every row is **not run**. Apply the common-guard cases to both arms and both
formats; identify host fault injection separately from actual native execution.

| ID / stimulus | Required observable result before qualification |
|---|---|
| O01 — competing contexts | Test matmul/matmul, matmul/model and model/model in both creation orders. Reject before second device open, including idle owners, completed waits and terminal models not closed. Verify the Python suspend/resume route still obeys the same native reservation. |
| O02 — second operation | Attempt sequential submits while the first is queued, timed out, partially submitted, and successfully waited but not closed. Reject without new allocations/enqueues or mutation of the first operation; accept only after completed explicit close with successful cleanup. |
| O03 — validation and host allocation failure | Exercise invalid output owner/shape/extents and staging/owner allocation failure. No stranded lease or unpublished active work; retain any recoverable operation. Verify acquisition rollback rather than assuming an empty output pointer proves release. |
| O04 — setup/allocation failure | Inject device open/query/module/kernel setup, queue creation, every buffer creation/address query, and candidate workspace initialization failure. Record the retained handles and rollback status; no command may use a partial workspace. Distinguish current automatic no-work close from the proposed publication rule. |
| O05 — partial enqueue and skipped dependencies | Fail each of A write, B write, poison write, launch and read; also fail each created event. Preserve the accepted prefix and original error, drain skipped/queued captures, expose no valid output, and start no dependent MLP stage. |
| O06 — unestablished completion | Force wait timeout, close timeout, event-value query failure and value below completion. `complete` stays false; buffers, context and lease stay live; output stays unavailable. Later successful drain must neither duplicate work nor erase a nontransient failure. |
| O07 — successful explicit close | Capture owned output/trace before destruction; verify completion and separate cleanup result. Release queue/events before the next submit. Reference allocation returns to its idle level; candidate retains exactly its declared workspace, with no growth across calls. |
| O08 — owner close/destruction with retained operation | Close/reset the owner both before and after completed wait. A retained operation keeps device/module/kernel, process reservation and candidate buffers alive. Its explicit close drains and reports final context cleanup when it is the last owner. |
| O09 — cleanup failure and repeated close | Repeat successful and failed operation/owner closes. Inject release failures at event, queue, buffer, kernel, module and device boundaries, including destructor paths. Preserve primary and cleanup separately; no double release, hidden success or re-enabled submission/context after cleanup failure. |
| O10 — model close and late failure | Cover each of three model stages, failed hidden/bridge/output comparison, close before completion, terminal failure with pending work, and repeated close. No dependent launch after failure; model cleanup does not convert failed inference to success. |
| O11 — serial reuse and compatibility | Change inputs and retain existing poison cases across 32 serial calls; compare exact FP32 words and native dispatch, check no stale output/cross-call write, bounded resident/peak bytes and complete final release. Preserve all six supported shape/format signatures and the fixed MLP graph. |
| O12 — recovery boundary | After injected cleanup failure, reject all new work in the original process while draining existing owners. A fresh spawn/exec process must create, execute, validate and close successfully; preserve the failed attempt. This is not physical device reset/recovery evidence. |

Use the existing [P03 host fixture](../../ci/project/fixtures/p03_managed_runtime_test.cpp)
(`partial_failures`, `timeout_ownership`, `asynchronous_errors`) and
[P04 host fixture](../../ci/project/fixtures/p04_mlp_runtime_test.cpp)
(`partial_submission`, `close_boundaries`, `resources_and_owner`) as starting
interfaces, not proof that these proposed guard/reuse tests exist or pass.

## Questions to resolve before freezing

| Decision still open | Required frozen answer |
|---|---|
| Guard scope and publication | Locate one shared reservation mechanism covering direct matmul, model and Python entry paths; define raw native-context coexistence, reentrancy and exact rejection codes without implying new concurrency support. |
| No-work rollback and close requests | Define when a failed submit returns an operation versus rolls back without one, how explicit close interacts with today's automatic no-work close, and whether an incomplete owner close latches a closing state. |
| Workspace compatibility | Specify fixed `(8,4,8)` extents and policy selection while preserving other accepted signatures and the MLP hidden `(16,8,16)` call. Freeze idle/resident accounting and initialization timing identically with the measurement plan. |
| Failure persistence | Define sticky cleanup reporting after owner reset/destruction and repeated close; classify primary failures such as device loss for recovery. A clean drain never rehabilitates a failed sample. |
| Evidence and execution | Pin matched commits, reviewed diff, fault locations, expected statuses, lease/context IDs, release order, addresses/extents, allocation counters and final accounting. Freeze commands, deadlines, backend coverage and independent reviewers before running. |

Record submission, completion, operation cleanup and owner cleanup independently,
including `validation`, `primary`, `cleanup`, `complete` and model terminal status.
Query native memory while the owner is open; post-close `memory_info()` is invalid.
Resident-buffer release needs a separately defined final accounting observation.
Reject any correctness, ownership, cleanup, provenance or resource failure; keep
all failures and do not replace samples. Apply the [acceptance policy](acceptance.md).
This draft changes no native code, source pins, goldens, tolerances or budgets.
P06-A01 retains its accepted scope; P06-A02/A03, the DSP finding and P01-A03 remain open.
