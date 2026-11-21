# P05 copying-binding development audit

## Decision

The audited base is `6aac9c421180805a5621156e3d914c685fc6f4a5` on `master`.
The next bounded development step is the first plain-Python implementation of
P05-T01: a copying binding to the existing managed matmul owners and the frozen
P04 model-case executor. The [entry handoff](p05-entry-handoff.md) already names
this step, and inspection of the runtime and retained evidence supports it.
The Python route must earn its own execution and installation evidence.

P04's accepted numerical and dispatch records identify four SimX/processor-RTL
variants at `c9d139cc9f84839b6a56b6228dd304460cbfe45c`. The GitHub CI and governance
runs for the audited base both report success. No open pull request or issue was
returned by the connected repository queries at audit time. These observations
establish a usable starting point, not a Python qualification result.

## Findings that determine the implementation

| Finding | Consequence |
|---|---|
| `ExecutionResult::ok()` checks error codes but not completion | Python success and output publication must also require completed work and valid actual output |
| A failed submission can return an incomplete native operation | Allocate and retain its Python owner before submitting; preserve access through exceptions and a pending-operation snapshot |
| Native operation/model destructors can drain indefinitely | Timeout is retryable and never cancellation; explicit close remains required and finalization cannot promise a bounded shutdown |
| `ManagedMatmul::create` trusts profile attestations and a syntactically valid qualification ID | The extension must establish its own matched artifact boundary before constructing that binding |
| The dispatcher caches a backend process-wide and loads it by basename | Support one bundle/format/backend per fresh process, verify actual loaded objects, and reject incompatible preloads and forked owners |
| Simulator dependencies include Ramulator DSOs with source-tree search paths | Bind the complete five-library project closure and prove a relocated installation rather than copying only `libvortex.so` |
| `ManagedMlp` creates a separate managed matmul context | A Python model operation owns that distinct context and selects internal frozen cases; it does not claim shared device allocations |
| Model outputs may be observed before a later cleanup/resource failure | Preserve diagnostic traces independently; successful output publication requires the final successful model and cleanup state |
| SimX device destruction finalizes shared process-wide simulation objects | Enforce one live native context, suspend idle matmul ownership for model runs, and retain the lease through pending operations and cleanup |
| Distinct runtime queues use separate launch-setup mutexes while writing shared device configuration | Require an explicit completed matmul close before another submission; overlapping native queue execution remains outside this binding contract |
| A Python verifier callback can be replaced | Native code verifies compiled manifest/artifact pins itself; the producer and startup launcher add independent preflight checks |
| Retaining an operation in a private registry alone does not make it recoverable | Expose the actual pending owners through an immutable tuple after interrupted or failed publication |

The immutable fixture, existing integer reference, native matmul implementation,
host bridge and native record serializers remain the comparison authorities.
The binding introduces no arithmetic implementation, floating-point conversion,
CPU matmul fallback, hardware change or relaxed numerical bound.

## Chosen first scope

Use Linux CPython 3.12 and a C++17 CPython extension without NumPy or a binding
framework dependency. Compile the existing managed sources into the extension
and load the identified runtime explicitly. A wheel is bound at build time to
one immutable native bundle; an unbound wheel is importable but cannot execute.
The source distribution preserves that identity when rebuilt outside the source
checkout. Inputs are explicit FP16/BF16 little-endian packed byte tensors, with
the three existing shape tuples and existing row/column-major conventions.

Initial native qualification targets SimX in separate FP16/BF16 processes and
separate pinned installations. The matrix contains all six supported matmul
signatures and all ten frozen model cases, two output poisons per route. The
unchanged native executables remain independent comparison paths. Native and
Python launches are counted separately; host fault injection is identified as
host-only lifecycle evidence.

This slice does not establish the later PyTorch custom-op gate, a full framework
device backend, arbitrary model loading, autograd, training, CUDA compatibility,
zero-copy execution, physical GPU speed or a new processor-RTL qualification.
The complete P05 exit conditions remain in the [phase guide](phases/p05-framework.md).

## Local execution prerequisites and preserved blockers

The audit environment has CPython 3.12.14, GCC 14.2.0, setuptools 84.2.1 and
wheel 0.48.0. Its governance check passes. Simulation preflight reports missing
RISC-V/LLVM/Verilator tools and uninitialized required submodules; no local native
execution is inferred from host checks. Hosted qualification reuses the existing
reviewed cache preparation and fresh-build path with explicit resource limits.

P01-A03 vendor XRT `hw_emu` remains blocked. The inherited tensor DSP increase
from 267 to 283 remains an unresolved area-gate finding. Neither is closed by
Python work, and no golden, tolerance, hardware configuration or existing gate is
changed to make this continuation pass.

## Review and delivery

The implementation owner is `/root`. The requested program uses sixty distinct
worker assignments across ten waves for audit, implementation, failure tests,
qualification, independent review and publication evidence; the final ledger
records actual completed work.
Workers own disjoint files and do not publish. The primary agent integrates,
checks the current remote head, and publishes only to the authorized `master`.
Phase state and acceptance remain evidence-driven; an assignment count does not
complete a gate.
