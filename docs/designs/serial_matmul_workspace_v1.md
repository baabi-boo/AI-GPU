# Serial matmul workspace v1

**Frozen narrow runtime and correctness contract — 2026-11-21.** This contract
is frozen before runtime implementation, against baseline
`3235cd59d724663dda1bece20645d5ccf30462e1`. It specifies required behavior;
source presence is not execution evidence or acceptance. The
[development audit](../project/p06-workspace-audit.md) and
[wave-1 receipts](../project/evidence/p06-serial-workspace/agents/) record its
inputs. Warm-context performance sampling remains a separate, unfrozen task.

## 1. API and fixed treatment

Add only this policy to the internal managed C++ interface:

```cpp
enum class WorkspacePolicy : uint32_t {
  per_operation = 0,
  reusable_single_tile = 1,
};

// Field in ExecutionBinding:
WorkspacePolicy workspace_policy = WorkspacePolicy::per_operation;
```

The existing create/submit signatures and `vortex2.h` ABI are unchanged. Unknown
policy values return `validation=Status::invalid_argument` before device open
or native allocation. `ManagedMlp::create` rejects every non-default policy with
that validation status before creating its underlying managed context. Existing
model, Python, PyTorch and cold-benchmark callers retain the default policy.

| Policy | Accepted `(M,N,K)` tuples, in each of FP16/BF16 | A/B/D ownership |
|---|---|---|
| `per_operation` (default) | `(8,4,8)`, `(8,4,16)`, `(16,8,16)` | Allocate and release for each operation, preserving all six signatures. |
| `reusable_single_tile` | `(8,4,8)` only | Create exactly A=128, B=64, D=128 payload bytes during context creation; retain until context teardown. |

Resident A/B use `VX_MEM_READ`; D uses `VX_MEM_WRITE`. All three allocations,
address queries and planner validation of actual disjoint addresses and full
tracked extents must succeed before publishing the owner. Setup failure rolls
back every acquired handle. There is no lazy allocation, resizing, pooling or
fallback. Other resident shapes return `Status::unsupported_shape` before new
operation resources or enqueue work. Exact input-span and profile validation
remain mandatory.

Every operation owns fresh host input/output staging, result storage, queue and
events. Resident operations borrow the three context buffers while retaining the
context. Each successful call rewrites all 128 A bytes, 64 B bytes and 128 D
poison bytes, performs one launch, and reads all 128 D bytes. The unchanged
[operator contract](ai_operator_contract_v1.md), native matmul kernel, 56-byte
argument schema, compact layouts, positive-zero accumulation, WMMA traversal,
RV64 `p02-tfr` profile and independent exact output bits remain authoritative.
This treatment changes tensor-buffer lifetime only.

## 2. Ownership and enforcement boundary

One linked managed-runtime instance has one shared context reservation and one
sticky observed-cleanup-error latch. Direct matmul, real model and binding paths
that reach that instance share the reservation. Raw runtime clients and multiple
independently linked runtime copies are unsupported coexistence paths and are
not guarded. Individual owners remain single-caller objects; this is not a
thread-safety or concurrency qualification.

Context reservation must be atomic and precede device open. Publication occurs
only after complete setup. Acquisition rollback must cover exceptions before a
context or owner object exists. Clean rollback returns the reservation; observed
cleanup failure poisons the instance before any reservation could become
available. Concurrent managed creates must never both reach device open.

Each context permits one operation lease. Validate arguments before acquisition;
acquire the lease before staging/resource creation or enqueue, with exception-safe
rollback. Rejected calls do not alter another operation's lease. A queued,
partially submitted, timed-out, failed-but-unclosed or successfully waited
operation retains its lease. Only completed operation close with healthy cleanup
permits another submission. Keeping an already closed operation object alive
does not hold the lease.

Owner close with a live operation returns timeout/incomplete and retains the
context. It does **not** latch a closing state: after the operation's completed
healthy close, that owner can submit again. Owner destruction instead drops its
reference; the retained operation keeps device/module/kernel, resident buffers
and context reservation alive. Its final completed close performs and reports
last-owner context teardown.

Completed operation close releases all events and the queue before releasing
default-policy buffers or returning a reusable lease. Resident buffers remain
owned by the context. Final context teardown releases resident buffers before
kernel/module/device teardown. Attempt every remaining cleanup step after an
error, retain the first cleanup error, and consume each handle at most once;
a failing release is not permission to retry a possibly consumed handle.

## 3. State and error contract

`ExecutionResult` keeps validation, primary runtime error, cleanup error and
completion independent. `ok()` does not include `complete`. In this table,
`S` means the relevant success value and `E` is the original first error. Busy
and poisoned rows describe otherwise valid calls; validation rejection performs
no work and leaves existing ownership untouched. Poison takes precedence over
busy when both apply to an otherwise valid new-work request.

| State / action | Validation | Primary | Cleanup | Complete | Ownership / result |
|---|---|---|---|---|---|
| Invalid policy, model non-default policy, invalid owner/input | Specific validation error | S | S | `true` | No new work; no reservation disturbed. |
| Unsupported resident tuple | `unsupported_shape` | S | S | `true` | No operation allocation or enqueue. |
| Create while context reserved | S | `VX_ERR_TIMEOUT` | S | `true` | Rejected attempt queued nothing; no second device open. |
| Submit while operation lease held, including after successful wait | S | `VX_ERR_TIMEOUT` | S | `true` | Rejected attempt queued nothing; no new resources or mutation of active operation. |
| New create/submit after observed cleanup failure | S | `VX_ERR_INTERNAL` | Original latched E | `true` | Reject without native side effects; no recovery by reset/recreate. |
| Owner close with live operation | S | `VX_ERR_TIMEOUT` | Existing context cleanup, if any | `false` | Keep context; no closing latch. |
| Submit failure before any accepted command | First validation error or S | First runtime E, if any | Rollback result | `true` | May return an already closed operation, as before; clean rollback releases its lease. |
| Submit failure after an accepted command | S | First submit E | S until cleanup | `false` | Publish/retain operation and accepted prefix for drain. |
| Wait/operation-close timeout | Retained | Earlier sticky E, otherwise `VX_ERR_TIMEOUT` for this observation | Retained | `false` | Keep all required resources and both reservations; timeout alone is retryable. |
| First non-timeout wait/query error, or observed value below target | Retained | First sticky E; below-target without earlier E is `VX_ERR_INTERNAL` | Retained | `false` until completion is established | Continue draining; no output. |
| Successful completion observation | Retained | Retained sticky E or S | Retained | `true` | Wait alone retains lease; output only if fully submitted and successful. |
| Completed operation close | Retained | Retained | First cleanup E or S | `true` | Release once; healthy cleanup returns lease; cleanup failure poisons new work and hides output. |
| Completed owner close / repeated close | Retained close result | Retained close result | First context cleanup E or S | `true` | Teardown once; subsequent close returns sticky result. |

Record a non-timeout wait error **before** querying the completion value. A
later query failure must not replace it; a later successful drain must not erase
either failure. A successful query proving the last accepted event reached its
target is required to establish completion. A timeout alone never becomes a
sticky primary error or cancellation. Retain the original submit failure through
all later observations and cleanup.

No-work failure may use existing automatic close only after proving that no
command was accepted. An enqueue failure at steps 2–5 owns the accepted prefix
of 1–4 events. It must retain staging, queue/events, buffer access, context and
lease until drain and close. Host exceptions must not reset completion to true
after partial dispatch. Host allocation failure reports
`VX_ERR_OUT_OF_HOST_MEMORY`; other caught host exceptions report
`VX_ERR_INTERNAL`, with acquired ownership safely rolled back or retained.

Any observed cleanup error from setup rollback, operation close, context close
or destruction latches the first error in the affected context and shared
instance. Owner close reports that retained context cleanup even if later
teardown steps succeed; repeated close cannot erase it. Destructors latch
observed errors despite having no return channel. Poison lasts for the linked
instance's lifetime; neither a fake-backend reset nor a new owner clears it.
Existing owners can drain/close, but cannot submit new work. Destructor drain
remains unbounded when completion cannot be established.

After primary failure or cleanup failure observed by an operation, subsequent
`output_words()` access on that operation is empty. This includes last-owner
context teardown performed during its close. A healthy closed operation has
already detached its context and owns its successful host result; a later owner
teardown failure poisons new work but does not retroactively revoke that result.
Previously copied successful host output also cannot be revoked. Healthy
completed operation output and trace remain owned and unchanged when later calls
reuse device buffers. This operation-local scope was clarified by the independent
W04-A03 review before publication; it adds no recovery or concurrency guarantee.
A successful release call proves only the reported API result: common-runtime
cleanup can suppress underlying free errors, so this contract promises poisoning
on **observed** cleanup failures only.

## 4. Frozen native correctness smoke

Use a dedicated workspace caller, records/parser and workflow; preserve the
existing native/cold-benchmark callers, fixtures and contracts. Each invocation
uses one format, one backend, one policy and one context, followed by four
separate native calls with completed explicit operation close between calls:

| Sequence | Existing fixture ID suffix | D poison |
|---|---|---|
| 0 | `single-dense_boundaries` | `0xdeadbeef` |
| 1 | `numerical-zero` | `0x7fc0dead` |
| 2 | `single-k03` | `0xdeadbeef` |
| 3 | `single-dense_boundaries` | `0x7fc0dead` |

The machine-readable [correctness manifest](../../ci/project/p06_workspace_contract.json)
has contract ID `p06-serial-workspace-correctness-v1` and binds this sequence,
matrix and expected counts.

Prefix IDs with `fp16-` or `bf16-`. The frozen starting poison here is the root
integration decision, superseding the opposite starting poison in the wave-1
proposal; no golden value changes. Read the exact existing P02 fixture inputs
and FP32 expected words. Both inputs change at each adjacent transition, and the
last call returns to dense inputs with the other poison. Expected results must
not come from runtime arithmetic or a previous call.

The full smoke is `simx` / native processor `rtlsim` × FP16 / BF16 × the two
policies, each in its own process: **8 processes, 32 launches, 1,024 exact FP32
output words**, if all succeed. Each process has 4 queues, 20 completion events,
12 writes, 4 launches and 4 reads. Retain all rejected attempts separately; they
must add zero launches. No prime or measured warm batch is part of this smoke.
It is bounded changed-input reuse evidence, not the full numerical inventory.

For every call retain policy/backend/format, sequence and fixture identity,
actual output words, poison, native addresses/extents, 56 argument bytes,
dispatch counts and separate validation/primary/cleanup/completion results.
Require stable, disjoint resident A/B/D addresses across all four calls; repeated
addresses alone do not prove retained allocation. Observe competing-context and
live-operation rejection, waited-but-unclosed rejection, successful resubmission
after completed close, and unsupported resident-shape rejection without dispatch.

## 5. Allocation observer and resource assertions

Use a dedicated test-only native allocation observer in this caller. It must
delegate to actual native functions, track tensor handles separately from other
runtime allocations, and preserve returned statuses and resource behavior.
Wrap `vx_buffer_create`/`vx_buffer_release`; device-open/release observation may
establish device identity and live-device boundaries. Validate these linker flags
with a workspace-specific validator, leaving existing compiler/linker contracts
unchanged. There is no production observer/reset API.

| Successful four-call process | `per_operation` | `reusable_single_tile` |
|---|---:|---:|
| Tensor allocations / releases | 12 / 12 | 3 / 3 |
| Tensor allocations during context setup | 0 | 3 |
| New tensor allocations per call | 3 | 0 |
| Tensor releases at each operation close | 3 | 0 |
| Tensor releases at final context teardown | 0 | 3 |
| Peak live tracked tensor payload | 320 bytes | 320 bytes |
| Idle tensor payload after an operation close, before owner close | 0 bytes | 320 bytes |
| Tracked tensor payload after healthy final teardown | 0 bytes | 0 bytes |

The 320-byte bound is A128+B64+D128 requested payload, not device-wide allocator
usage or host RSS. Compute peak from allocation/release events, not snapshots.
Track attempts and successes separately, without counting unrelated buffers.

The native observer counts device and tensor-buffer calls. It does not count
queue creation, event creation or enqueue calls. Its busy-probe snapshots
therefore establish zero observed device/buffer side effects and no returned
operation; absence of hidden queue/enqueue work also relies on reviewed guard
placement and the separately scoped host fault tests. The queue/event totals
above are required execution behavior, not independently observed native totals.

For every tracked tensor handle, retain its live device and native memory-info
status/free/used values immediately before and after actual allocation and actual
release. Require successful observations and release deltas that reconcile with
the corresponding allocation deltas, allowing documented allocator rounding but
not unexplained retained tensor allocation. Also retain context-setup and
completed-operation-close snapshots. Resident final-release observations must
occur **after buffer release and before device release**; public owner
`memory_info()` after close is invalid. Failed/missing queries are unavailable
evidence, never zero usage. Handle-release counts without this accounting do not
prove allocator reclamation, and simulator memory counters do not prove physical
memory release or device recovery.

## 6. Required tests, provenance and limits

Host fault tests must cover both policies and formats: concurrent context
reservation and clean rollback; every setup capability/allocation/address stage;
host allocation failure before publication; invalid calls without lease damage;
queued, timed-out, partial and waited-but-unclosed operation exclusion; every
enqueue/event/query boundary; sticky first error followed by eventual drain;
owner destruction before/after wait; each event/queue/A/B/D/kernel/module/device
release failure; output suppression; repeated close; and final operation-owned
context teardown. Failed releases must not skip remaining cleanup or permit
double release. Preserve healthy timeout-then-success behavior.

Link real `runtime.cpp` with real `mlp_runtime.cpp` for combined host coverage of
matmul/model/model context exclusion in both creation orders, idle and terminal
models, model policy rejection, default six-signature support and Python model
suspend/resume. Existing mocks replacing `ManagedMatmul` cannot qualify the
native guard. Cleanup-poison cases run in separate process invocations; production
poison must not gain a test reset. Fresh-process success is a managed-lifetime
boundary check, not physical recovery evidence. Host synthetic arithmetic stays
labelled as host fault/control evidence.

Native records must bind exact source revision/tree, sequence, policy, fixture
hashes, tools/dependencies, generated configuration, independently validated
runtime/backend/kernel/host/linker records and binary hashes before execution,
then check source/tool stability afterward. Retain raw logs with size/hash
verification and failed attempts. Parser mutation tests reject reordered/missing
calls, altered fixture/output/poison/arguments, unbound policy, incorrect lifetime
counts and partial matrices described as complete. Regenerate build trees before
native execution. Preserve two jobs, 4 GiB polled RSS, 15 GiB disk reserve,
16 MiB command logs, 1,800-second build / 180-second invocation limits and the
90-minute hosted job deadline; no resource limit is relaxed for local execution.

The [audit](../project/p06-workspace-audit.md) records unavailable local pinned
GPU tools and disk reserve. This freeze claims no tests run, speedup, physical
FPGA/silicon result, synthesis or passed gate. Processor `rtlsim` bypasses the
AFU and retains integer DPI helpers; it does not close vendor P01-A03. P06-A02/A03,
the inherited 267-to-283 DSP finding and P07 obligations remain open. Warm
performance evaluation requires its own frozen matched-source sampling,
measurement and rejection contract before any performance conclusion.
