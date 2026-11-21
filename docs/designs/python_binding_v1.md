# Copying Python binding v1

This is the implemented contract for package `vortex-ai==0.1.0`, import name
`vortex_ai`, and `BINDING_API = 1`. The public surface is
[`_api.py`](../../python/vortex_ai/_api.py); opaque native owners are implemented
in [`module.cpp`](../../python/native/module.cpp). This contract does not grant
P05 acceptance. See the [compatibility and qualification record](../project/p05-python-compatibility.md)
for evidenced environments and pending gates, and the [package guide](../../python/README.md)
for installation and complete invocation examples.

## Numerical and representation boundary

The extension compiles the existing managed matmul/model owners; their C++
classes are not an installed C ABI. It uses the unchanged
[`p02_tfr_wmma_v1` profile](../../ci/project/p03_operator_manifest.json) and
[TFR numerical rules](tensor_numerics_v1.md): matching FP16 or BF16 inputs,
FP32 accumulation/output, initial C = +0, and only these six signatures:

| `(M,N,K)` | A: shape; byte strides; bytes | B: shape; byte strides; bytes | Output: shape; byte strides; bytes |
|---|---|---|---|
| `(8,4,8)` | `(8,8)`; `(16,2)`; 128 | `(8,4)`; `(2,16)`; 64 | `(8,4)`; `(16,4)`; 128 |
| `(8,4,16)` | `(8,16)`; `(32,2)`; 256 | `(16,4)`; `(2,32)`; 128 | `(8,4)`; `(16,4)`; 128 |
| `(16,8,16)` | `(16,16)`; `(32,2)`; 512 | `(16,8)`; `(2,32)`; 256 | `(16,8)`; `(32,4)`; 512 |

Each row exists for `dtype="fp16"` and `dtype="bf16"`; a session accepts only
its bound format. A is `layout="row_major"`, B is `layout="column_major"`.
General byte strides are A `(2*K, 2)`, B `(2, 2*K)`, output `(4*N, 4)`.
Inputs contain explicit little-endian 16-bit words. Output contains actual
little-endian row-major FP32 words, with no Python float conversion.

`Tensor(data, *, dtype, shape, layout, strides=None)` has frozen metadata and
retains its exporter without copying at construction. `data` must be an exact
`bytes`, `bytearray`, or `memoryview`; the resulting view must have rank one,
item size 1, format `B`, `b`, or `c`, contiguous positive byte stride `(1,)`,
no indirect storage, and exactly `2*rows*columns` bytes. Read-only storage works.
The tensor itself is logically rank two. `shape` and explicit `strides` must be
exact two-element tuples of exact integers; booleans are rejected. Dimensions
are positive uint32 values, byte strides positive uint64 values, and the byte
extent must fit both uint64 and `sys.maxsize`. Explicit strides must equal the
packed strides; omitted strides select them. Submission checks the three shapes.

There is no implicit dtype, byte-order, layout, transpose, padding, broadcasting,
or floating-point conversion. Prepare any conversion explicitly before creating
the tensor. Host-buffer addresses are not device addresses; native allocation
and validation enforce device alignment, accessible extents, and disjoint ranges.
The binding has no CPU matmul fallback.

## Public API

| Call or property | Result and meaning |
|---|---|
| `build_info()` | Fresh dict: `binding_api`, compiled `bundle_sha256`, compiled `source_sha256`; loads the extension but no native runtime |
| `fixture_cases()` | Tuple of the ten compiled case IDs; no runtime opened |
| `Session.open(bundle_root)` | Bound session; requires a nonempty exact string path without NUL and the native path rules below; no caller provenance, dtype, or module override |
| `session.info` | Read-only snapshot: format, backend, qualification/source identities, bundle/source hashes, and tuple of five library paths |
| `session.status` | Last `ExecutionStatus` |
| `session.submit(a, b, *, poison=0x7fc0dead)` | Copying `Operation`, including a native-reported submission failure |
| `session.model(case_id, *, poison=0x7fc0dead)` | `ModelOperation` for one compiled case in the session's format |
| `session.pending_operations()` | Immutable tuple of the actual retained operation/model owners |
| `session.memory_info()` | `(code, free_bytes, used_bytes)`; nonzero code raises with the native status |
| `session.close()` | `ExecutionStatus`; disallows further work, does not drain arbitrary pending operations |
| `operation.wait(timeout_ns=100_000_000)` | Matmul `ExecutionStatus` |
| `model.advance(timeout_ns=100_000_000)` | `ModelStatus`; advances the fixed graph |
| `operation.close(timeout_ns=100_000_000)` | Both operation types return `ExecutionStatus`; drain/release explicitly |
| `operation.output_bytes()` / `output_words()` | Independent `bytes` / tuple of unsigned raw FP32 words |
| `operation.trace()` | Detached dict of actual native diagnostics; diagnostic presence does not imply success |
| `model.record(iteration=0)` | Detached native P04 record envelope, including incomplete/failing outcomes |

`poison` is an exact uint32 integer, excluding bool. It initializes native output
storage; it does not provide expected answers. `model.record()` accepts only
iterations 0 and 1, with matching creation poisons `0x7fc0dead` and `0xdeadbeef`.

## Status and exceptions

`ExecutionStatus` is frozen: `validation: str`, `primary: int`, `cleanup: int`,
`complete: bool`. Its `.ok` requires `validation == "success"`, both codes zero,
and completion. Validation names follow the [native contract](ai_operator_contract_v1.md);
integer codes follow [`vortex2.h`](../../sw/runtime/include/vortex2.h).
`VX_ERR_TIMEOUT` is 7. Timeout is retryable and never cancels the operation.
Successful later progress can replace the transient timeout; primary failures
and terminal cleanup failures remain observable.

`ModelStatus` adds `status`, `execution`, and `terminal`; `.ok` also requires
terminal `"success"`. States are `in_progress`, `success`, `runtime_error`,
`hidden_mismatch`, `bridge_error`, `bridge_mismatch`, `output_mismatch`,
`resource_mismatch`, and `closed`. A successful cleanup status alone does not
prove a model succeeded. Call `model.status.raise_for_status(model)` as well.

| Failure | Public behavior |
|---|---|
| Wrong Python type, including bool for integers | `TypeError` |
| Unsupported tag/shape/layout/extent/stride or invalid bounded value | `ValueError` |
| Integer or addressable-buffer extent overflow | `OverflowError` |
| Native-reported submission/creation failure | Retained owner and status; use `.raise_for_status(owner)` to raise |
| Bundle, state, protocol, execution, or cleanup failure | `BindingError`, a `RuntimeError` subclass, with diagnostic attributes |
| Allocation failure or interruption | `MemoryError` / the original interruption may propagate; retain/recover the owner |
| Other C++ exception | Converted to `RuntimeError`; some public boundaries wrap it in `BindingError` |

`BindingError` carries `kind`, `status`, `operation`, `session`, `model_status`,
and `close_error` where applicable. Kinds are `bundle`, `state`, `process`,
`reentrancy`, `protocol`, `validation`, `native`, `cleanup`, `incomplete`, or
`model`. `.raise_for_status(operation=None)` does not close the owner. C++
exceptions do not cross the CPython boundary; allocating an exception/status can
itself fail, so exception attributes are not the sole ownership mechanism.

## Copies, recovery, and closure

Submission retains Python buffer views through synchronous copying into native
storage. After submission returns, caller storage may be mutated or released;
the native operation owns its inputs. Matmul output is available only with a
complete successful current status and the expected nonempty extent. Model
output additionally requires successful inference, completed explicit close,
profiling, and resource checks; its output is `(16,4)`, 256 bytes. Returned
bytes, words, and trace snapshots remain owned by Python after closure.

The Python operation and empty native handle are allocated and registered in
the session before native submission/creation. A partial failure, `MemoryError`,
or interrupt during publication leaves recoverable owners in
`session.pending_operations()`. Exceptions receive `.operation`/`.session` when
possible. Keep the session and these owners, then retry bounded `wait`, `advance`,
or `close`; completed explicit close removes an owner from that registry.
A native state refusal raises `BindingError(kind="state")` and can retain an
empty owner if submission/creation never started. Close that owner to remove it;
it has no work to advance or trace.
If model close-status publication is interrupted, retry `close()` or `advance(0)`
to recover status; use completed `close()` to finish registry removal.

Wait/advance/operation-close arguments are exact integers in
`0..1_000_000_000` nanoseconds. The default is 100 ms. This bound applies to
each native wait/drain; a model call can perform multiple waits and is not a
whole-call wall-clock deadline. Repeated calls have no aggregate deadline.
An incomplete close retains ownership and must be retried. Context-manager exit
makes one default bounded close attempt; failure raises with the owner retained
and the body exception chained as its cause. It does not abandon work.

Native operation/model destructors drain using `VX_TIMEOUT_INFINITE`, retrying
until completion. Garbage collection and interpreter shutdown may therefore
block indefinitely. Explicit closure is required for controlled lifecycle;
dropping references is not bounded cancellation.

## Process and concurrency restrictions

Calls retain the GIL. Linux CPython 3.12's main interpreter is required;
free-threaded builds, subinterpreters, concurrent/reentrant owner access, and
inherited package/owner state after `fork` are rejected. Use spawn or exec for a
fresh process. Operations can outlive the Python session; their native lease
survives session destruction and incomplete waits/close calls.

SimX permits **one live native context per process**. A session permits **one
outstanding matmul until completed explicit close**. Successful `wait()` alone
does not release this restriction. Starting a model closes/suspends the idle
matmul context and gives the model its own context. Close all matmuls first.
After model closure releases its lease, `submit()` or `memory_info()` lazily
recreates the session's matmul context. A competing live owner prevents resume.
Closing a suspended session closes its metadata without closing its independently
owned model. Session close can be incomplete while matmul operations retain it.

Any observed explicit or destructor cleanup failure permanently poisons further
context acquisition/submission in that process. Retain and drain existing
owners; start a fresh process for new work. This rule does not promise device
reset, fault containment, or physical recovery.

## Native bundle and startup

The producer pins one SimX format, source inventory, profile, frozen fixture,
native qualification, and six artifact identities in canonical
`p05-python-bundle-v1` manifest bytes. The bound extension embeds the manifest
SHA-256 and artifact path/size/SHA-256 table. Native code itself verifies the
receipt and all artifacts before loading; it does not trust a mutable Python
verification callback or caller-supplied expected digest.

The external bundle contains `kernel.vxbin` and exactly five regular, nonsymlink
files in `lib/`: `libramulator.so`, `libramulator-vortex.so`, `libvortex.so`,
`libsimx.so`, and `libvortex-simx.so`. Extra library-directory entries fail.
Use a canonical absolute bundle root without symlink components. Native path
traversal rejects `:`, `;`, `$`, ASCII controls (0–31 and 127), and paths of
4096 or more UTF-8 bytes; relative inputs include the current directory in
these checks. The launcher validates the canonical root before child startup.
The loader checks actual loaded project-library paths, rejects foreign paths or
project libraries loaded outside this binding, and retains its selection for process life.
System ELF dependencies still require a compatible host.

Use `python -I -m vortex_ai.launch --bundle BUNDLE -- SCRIPT [ARGS...]`.
The launcher rejects nonempty parent `LD_PRELOAD`, `LD_AUDIT`, or
`LD_LIBRARY_PATH`, and a conflicting `VORTEX_DRIVER`. After checking the installed
pin and bundle, it starts the same interpreter as `python -I -B SCRIPT ...`,
with `LD_LIBRARY_PATH` exactly the canonical `BUNDLE/lib` and
`VORTEX_DRIVER=simx`. No extra or empty path segments are allowed. Setting a
library path after interpreter startup is not a substitute. The launcher checks
artifact identity; it is not a process/filesystem sandbox.

## Fixed model inventory

`Session.model` exposes the frozen [P04 fixture](tiny_mlp_fixture_v1.md), a
bias-free batch-16 `16 → 8 → 4` graph with three native matmuls and the declared
host ReLU, exact cast, and row assembly. Expected arrays remain internal
comparison data; callers cannot provide replacement references or arbitrary
weights/models. Output/trace/record methods preserve actual observed results.

| Family | FP16 case ID | BF16 case ID |
|---|---|---|
| Dense | `fp16-seeded_dense` | `bf16-seeded_dense` |
| Negated dense | `fp16-negated_dense` | `bf16-negated_dense` |
| Zero | `fp16-zero` | `bf16-zero` |
| Signed basis | `fp16-signed_basis` | `bf16-signed_basis` |
| Split boundary | `fp16-split_boundary` | `bf16-split_boundary` |
