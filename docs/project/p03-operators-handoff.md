# P03 managed native operator handoff

P03 is `in_progress`. **P03-T01 is complete and P03-A01 is accepted at source
scope** through the [historical reviewed evidence](evidence/p03-operators/acceptance.json).
P03-T02 now implements a matching device reader, managed matmul wrapper,
qualification runner and runtime lifecycle fixes. **P03-A02/A03 remain pending
execution and independent acceptance at this checkpoint.** P02 is complete;
P01-A03 vendor integration remains blocked and required before P07.

## Implemented boundary

The [manifest](../../ci/project/p03_operator_manifest.json) and
[v1 specification](../designs/ai_operator_contract_v1.md) declare exactly six
matmul signatures: FP16 or BF16 inputs, FP32 accumulation/output and
`(M,N,K) = (8,4,8), (8,4,16), (16,8,16)`. A is compact row-major, B compact
column-major and D compact row-major. Accumulation starts at exact positive
zero. The kernel preserves ordinary WMMA's `8 x 4 x 8` tile and K traversal;
separate WGMMA or sparse evidence does not expand this API.

The [planner](../../sw/runtime/ai/contract.h) retains its pure checked-input
contract and returns `execution_available=false` because planning itself
performs no dispatch. The manifest's execution availability describes the
separate [managed wrapper](../../sw/runtime/ai/runtime.h), not a planner side
effect or an automatic acceptance decision. GEMV, reductions, softmax,
normalization, activations, layout/casts and attention remain unavailable.
There is no CPU fallback, installed API or new arithmetic implementation.

The unchanged 56-byte little-endian schema now resides in
[the shared internal header](../../sw/common/ai_matmul_args.h), with a matching
[device reader and kernel](../../sw/kernel/ai/matmul.cpp). It is still
incompatible with the inherited regression `kernel_arg_t`. The reader validates
version, size, flags, reserved fields, compiled dtype, shape, representation,
alignment and range separation; the kernel validates grid/block geometry.
Invalid raw arguments leave D untouched, with no device error-result field.
Width-32 representation tests do not qualify RV32 execution.

## Binding, ownership and failures

The [execution runner](../../ci/project/p03_execute.py) is the trusted source
of `ExecutionBinding`. It validates runtime, arithmetic backend, kernel and
host compiler records independently; reproduces generated headers; hashes the
actual binaries; and selects the matching driver and runtime library directory.
The resulting SHA-256 binding identifier appears in every operation trace.
The wrapper copies and loads the exact supplied module bytes and independently
queries device geometry, address representation, local memory and feature bits.
The TCU bit alone cannot prove TFR/STD arithmetic or format-bank selection.
Directly supplying a well-formed identifier is not provenance verification or
arbitrary hardware authentication.

`ManagedMatmul` owns the device/module/kernel context. `submit` accepts compact
host spans and creates its own A/B/D allocations, using their returned device
addresses and recorded extents/access permissions for the planner. It does not
accept arbitrary buffer handles or caller-supplied allocation metadata. Each
operation owns a queue, copied host input bytes, poisoned output storage and
five dependent events: three writes, one launch and one read.

A partial submission may return an operation together with a primary failure;
the caller must retain and drain that operation. `wait(timeout_ns)` and
`close(timeout_ns)` retain resources while completion is unestablished. Check
`complete` as well as `validation`, `primary` and `cleanup`; the latter keeps
release failures separate from the original runtime error. Only successful
completion exposes `output_words()`. The operation may outlive its owner.
`ManagedMatmul::close()` returns incomplete while operations still own its
context. Repeated close after successful cleanup is safe.

The operation destructor waits indefinitely for terminal completion. A caller
requiring bounded waits must retain the operation after timeout, then retry;
destruction is not cancellation. Explicit close also exposes cleanup errors.
The native caller in
[`tests/regression/ai_matmul/main.cpp`](../../tests/regression/ai_matmul/main.cpp)
demonstrates the complete create/submit/wait/inspect/close sequence.

The shared runtime now owns command resources independently of whether a work
lambda executes. Failed dependencies and sticky queue errors therefore release
retained buffers, kernels and events before signaling completion. The changes
also cover overflow-safe linear spans, failed-map rollback, exception cleanup
and scratch-slot recycling under host allocation failure. Their actual runtime
qualification is separate from the wrapper's stub-based decision tests.

## Validation observed before formal execution

| Check | Observed result | Scope |
|---|---|---|
| Existing operator contract module | 12 tests passed | Host planner/ABI and updated availability manifest |
| Device reader/profile module | 7 tests passed | Literal bytes, decoder rejections and positive/negative compiler-profile probes |
| Managed wrapper module | 9 tests passed | Real wrapper with injected runtime stubs, including ownership, timeout and failures; fake output is not an arithmetic oracle |
| Execution-record module | 17 tests passed | Separate compiler-record validation and corrupted trace/result rejection |
| Actual Vortex Clang target objects | FP16 and BF16 RV64 objects compiled | Device-source compilation only; no launch implied |
| Formal managed SimX/native-RTL matrix and actual lifecycle integration | Pending at this checkpoint | Required execution evidence for A02/A03 |

These are development observations, not a combined full-suite result or a claim
that the final frozen source has already executed. Run focused host checks from
the source root:

```sh
python3 -m unittest discover -s ci/project -p 'test_p03_*.py' -v
python3 ci/project/check_project.py
```

The [historical A01 packet](evidence/p03-operators/README.md) separately retains
clean source `6367ce34e12915e12271207b207f93bd4d391869`, its 1636-test full-suite
pass and equivalent published tree at
`04c3cbf42c68e3b116051343083b86119f67f53d`. Its original six source bodies are
preserved byte-for-byte; the active acceptance changes their artifact paths
only. Its four RV32/RV64 compilations and review remain historical source-level
evidence and do not establish the new execution or lifetime gates.

## Reproduce the bounded execution matrix

Prepare the pinned tools, exact initialized submodules and identified dependency
libraries using the [developer guide](developer-guide.md). The runner does not
install dependencies. Choose a clean committed source checkout and new work and
output directories under existing parents; the three roots must be disjoint.
Replace these absolute example paths with the prepared locations:

```sh
AI_GPU_SOURCE=/absolute/path/AI-GPU
python3 "$AI_GPU_SOURCE/ci/project/p03_execute.py" run \
  --source-dir "$AI_GPU_SOURCE" \
  --tools-dir /absolute/path/tools-v3.0.2 \
  --host-bin /absolute/path/gcc12-bin \
  --work-dir /absolute/path/p03-builds \
  --output /absolute/path/p03-results \
  --jobs 2
```

The default formal run builds separate FP16/BF16 variants on SimX and native
processor `rtlsim`, then executes the unchanged 88 independent P02 fixtures
on both backends. Its expected inventory is 176 case/backend executions and
352 separately poisoned launches. Each case checks raw FP32 words, exact
argument bytes, transfer/launch/wait traces and device-memory restoration.
The SimX FP16 build also runs
[`test_ai_lifecycle`](../../tests/runtime/test_ai_lifecycle.cpp) against the
actual common runtime; it has no silent kernel-dependent skips. Synthetic
module handles in skipped-command tests establish ownership only.

The runner reserves 15 GiB free disk, budgets 6 GiB process-group RSS and 16 MiB
per-command logs, and defaults to two build jobs. These are polled budgets,
not hard quotas. It retains command outcomes, source/tool/dependency identities,
configuration/source snapshots, binary hashes and raw logs in `report.json`
and its adjacent packet. Binary bodies are not retained for replay. A passing
packet never changes phase status automatically. `--development` permits dirty
source and selected cases for iteration; it is not formal acceptance.

Native processor RTL bypasses the AFU and retains integer DPI helpers while
using the native TFR tensor/STD scalar paths. It does not supply vendor
`hw_emu`, physical FPGA, PPA or silicon evidence.

## Next bounded action: qualify P03-T02

Freeze the reviewed source, execute the full runner matrix and actual lifecycle
tests, retain failures as well as successful retries, and run the full offline
suite on the final stable implementation. Obtain independent source/evidence
review before attaching A02/A03 acceptance records. Until those gates are
accepted, P03 remains `in_progress`; the P04 handoff then selects a fixed,
redistributable tiny model composed from the accepted operators.
