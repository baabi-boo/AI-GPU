# P05 copying-binding development audit

## Initial decision

The audited base was `6aac9c421180805a5621156e3d914c685fc6f4a5` on `master`.
The selected bounded development step was the first plain-Python implementation
of P05-T01: a copying binding to the existing managed matmul owners and frozen
P04 model-case executor. The entry handoff and inspection of the runtime and
retained evidence supported that choice. The resulting implementation and
qualification are recorded below; the [current handoff](p05-entry-handoff.md)
now carries the scoped framework work forward.

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

## Qualification outcome and next development step

The implementation at `e1420fd550f716df33a2556057b7086a03032cbe` now has
[bounded P05-A01 acceptance](evidence/p05-python/acceptance-binding.json).
The [packet](evidence/p05-python/README.md) preserves both installed SimX variants,
all six matmul signatures and ten frozen model cases, native comparison logs,
exact source/build/package identities and independent numerical, dispatch and
provenance audits. Its 144 launches comprise 72 through Python and 72 through
the native comparison; 660 event/profile pairs exclude the unprofiled standalone
native calls. Fresh external installations passed with CPython 3.12.14 and
G++ 11.4.0, and the clean hosted suite passed 2,174 tests in 421.584 seconds.
The binding-source digest is
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.

Host-native lifecycle probes and local packaging evidence retain their exact
source scopes in the [host history](evidence/p05-python/development/host-validation.md).
The earlier source-changing local full-suite failure and inherited configure
timeout remain failures; later isolated and clean hosted passes do not erase
them. Independent counterexample reviews also found and repaired evidence-auditor
gaps before the formal matrix review, retaining the original failures.

The next bounded development step is the scoped PyTorch custom-op route:
freeze its framework version and operator/representation/error contract, reuse
the qualified owners, reject unsupported gradients/layouts and reproduce the
fixed model with new installation and native-dispatch evidence. A02 and A03
remain unearned; P05 stays `in_progress`. Neither a documentation delivery commit
nor the number of worker assignments establishes new execution or phase closure.

## Local execution prerequisites and preserved blockers

The initial local audit environment has CPython 3.12.14, GCC 14.2.0, setuptools
84.2.1 and wheel 0.48.0. Its governance check passes. Simulation preflight reports missing
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
