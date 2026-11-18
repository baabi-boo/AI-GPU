# P03 managed native operator handoff

**P03 is complete for the declared six-signature native matmul scope.**
P03-T01/A01 retain their [historical source-level acceptance](evidence/p03-operators/acceptance.json).
The independently reviewed [A02 numerical acceptance](evidence/p03-managed-matmul/acceptance-numerics.json)
and [A03 lifecycle acceptance](evidence/p03-managed-matmul/acceptance-lifecycle.json) complete
P03-T02 using actual managed execution and resource-lifetime results. The
matching device reader, wrapper, qualification runner and runtime fixes are
implemented and tested. P02 remains complete; P01-A03 vendor integration remains
blocked and required before P07. **P04 remains `not_started`** until its bounded
model contract and fixtures are deliberately selected.

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

## Accepted validation and exact source

Formal execution used clean source `319ad63532cee17ae88fa75757a5ac87ed5c6a77`, tree
`d7768f5f392cef417e59ccadfc29f20d3f67f707`. Source, tool, configuration and identified dependency
artifacts remained stable across the retained runs. The linked acceptance
records and their [published packet index](evidence/p03-managed-matmul/README.md)
define the exact scope; raw command receipts retain the underlying observations.

| Check | Observed result | Scope |
|---|---|---|
| Managed operator matrix | 176 case/backend executions, 352 separately poisoned launches and 14,336 exact FP32 output words passed | All 88 independent fixtures on each of SimX and native processor RTL, 44 per format; six declared signatures only |
| Actual runtime lifecycle integration | RV64 `p02-tfr` SimX and default RV32 SimX: 12 groups passed in each recorded execution | Bounds, wait-list/timeout ownership, failed commands, allocation/module/DMA failures, recovery and repeated resource accounting |
| Focused P03 host checks | 45 tests passed | 12 contract, 7 reader/profile, 9 managed-wrapper and 17 execution-record checks; wrapper stubs do not establish GPU arithmetic |
| Complete offline project suite | 1,669 tests passed, zero failures/errors/skips, 427.714 seconds | Full suite at source `319ad63532cee17ae88fa75757a5ac87ed5c6a77`; tooling/source checks remain distinct from GPU execution |
| Actual Vortex Clang target objects | FP16 and BF16 RV64 objects compiled | Original development compile observations retain their source identities separately from formal launches |

All 210 retained matrix commands passed. The 45 focused P03 checks are included
in the 1,669-test total. The full-suite test framework reported 427.714 seconds;
its complete bounded command took 428.757821 seconds. The matrix
peak process-group RSS was 1,484,550,144 bytes. At qualification closeout,
54,525,153,280 bytes (50.8 GiB) of disk space remained free. These resource
observations are distinct from accelerator performance measurements.

Every arithmetic result was compared against the unchanged independently
produced P02 fixture words; no expected output came from the production
simulator and no numerical tolerance was widened. Repeated launches retain
different output poison values, byte-exact argument records and device-memory
counters returning to the pre-operation baseline. The actual lifecycle groups
include selected simulated DMA allocation failures and explicit no-replay
recovery checks; synthetic skipped-kernel handles prove ownership only.

Host runtime stubs separately exercise device-loss and cleanup-error decisions.
They do not prove physical device recovery. DMA failure evidence is bounded to
the injected host-allocation stages; arbitrary partially completed transfers
may already have modified memory, and transactional rollback/cancellation is
not provided. RV32 runtime lifecycle coverage does not qualify RV32 matmul.
The RV32 receipt's raw `cache_enabled=false` field refers to disabled compiler
caching (`CCACHE_DISABLE=1`); the tested processor had instruction and data
caches enabled.

Run the focused checks from the source root:

```sh
python3 -m unittest discover -s ci/project -p 'test_p03_*.py' -v
python3 ci/project/check_project.py
```

The [historical A01 packet](evidence/p03-operators/README.md) separately retains
clean source `6367ce34e12915e12271207b207f93bd4d391869`, its 1636-test full-suite
pass and equivalent published tree at
`04c3cbf42c68e3b116051343083b86119f67f53d`. Its original six source bodies are
preserved byte-for-byte; the active historical acceptance changes their
artifact paths only. Its four RV32/RV64 compilations and review keep their
original source-level scope. The separate new A02/A03 records establish
managed execution and lifecycle acceptance.

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
module handles in skipped-command tests establish ownership only. The
default runner covers RV64 `p02-tfr` lifecycle execution; the accepted
default-RV32 lifecycle run has its own retained receipt.

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

## Next bounded action: P04-T01 model freeze

P04 remains `not_started`. Freeze one small redistributable model or deterministic
model generator, its weights/inputs/license hashes and an independent layerwise
reference before implementing the executor. Map every accelerated operation to
the accepted dtype, shape and layout manifest. The current library exposes
matmul only: activations, bias, normalization, casts and arbitrary shapes are
not implicitly available. Any additional operator must earn its own contract
and qualification; any deliberately permitted host work must be explicit.

Use the [P04 phase guide](phases/p04-inference.md) to choose a bounded network
that fits the available operations and predeclare model-level comparison rules.
Operator acceptance does not establish complete model inference, a framework
backend, training, physical performance or P01-A03 vendor integration. Preserve
the current accepted source/evidence while extending the next work package.
