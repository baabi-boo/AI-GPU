# Architecture and program decisions

This log separates **accepted project-setup decisions** from **unresolved
engineering and funding choices**. An accepted design direction does not prove
implementation, test success or permission to spend money. Phase progress and
acceptance remain in [roadmap.json](roadmap.json).

## Decision process

Before implementation, record the problem, alternatives, chosen scope,
consequences, affected requirements/acceptance IDs, evidence and actual decision
owner. Proposed decisions stay proposed until that owner accepts them. A later
decision supersedes an earlier entry explicitly; do not erase its rationale.

Changes to arithmetic tolerances, platform targets or performance thresholds
must precede their acceptance measurements. Failed evidence is not grounds for
silently relaxing a contract. Follow the inherited
[review policy](../review/code-review-policy.md).

## ADR-001 — Native tensor kernels before a new HIP stack

**Status:** accepted project-setup direction.

**Context:** inherited [`vx_tensor.h`](../../sw/kernel/include/vx_tensor.h)
exposes WMMA/WGMMA to native kernels; the
[`vortex2.h`](../../sw/runtime/include/vortex2.h) runtime supplies buffers,
queues, events and launches. The current
[chipStar HIP path](../designs/hip_on_vortex_chipstar.md) does not expose these
Vortex-specific tensor intrinsics.

**Decision:** P01–P04 reproduce native tensor examples, establish numerical
contracts, build a native operator library and compose a tiny inference model.
P05 then adds a thin Python binding and a separately scoped PyTorch custom-op
bridge. A bespoke HIP compiler/runtime is not a prerequisite for this milestone.

**Alternatives:** a new native HIP toolchain or complete framework device
backend could provide broader integration, but each adds an independent compiler,
ABI, compatibility and maintenance program before the first model is proven.

**Consequences:** preserve existing HIP/OpenCL paths and report their actual
coverage. Do not claim CUDA compatibility, complete PyTorch device support or
autograd from a native kernel or custom-op demonstration. Revisit the compiler
choice only with demonstrated operator requirements and a funded ownership plan.

## ADR-002 — Evidence labels and exact execution scope

**Status:** accepted project-setup direction.

**Decision:** every capability claim records one of the canonical labels below
plus the exact source revision, configuration, backend and test scope.

| Label | What the evidence establishes | What it does not establish |
|---|---|---|
| `source_present` | Inspectable implementation or reviewed setup artifact exists | A passing execution |
| `simulated` | The declared simulator/model execution passed its checks | Native arithmetic RTL or physical performance |
| `rtl_verified` | The named native RTL/integration scope passed its declared checks | Physical board operation or manufacturing sign-off |
| `fpga_measured` | A named physical FPGA configuration produced the recorded result | Custom-silicon behavior or commercial parity |
| `silicon_measured` | A named manufactured device produced the recorded result | Untested configurations, production yield or universal compatibility |

These labels are not automatic substitutes for one another: a physical test
does not cover untested RTL corner cases. Processor `rtlsim`, full AFU/XRT
integration and XRT `hw_emu` must be distinguished in the evidence record.
Simulation-only DPI arithmetic does not certify the native tensor datapath.
Physical `hw` results require device identification; synthesis estimates remain
estimates even when recorded alongside RTL verification.

**Consequences:** phase completion requires the specified evidence, not a README
claim or an empty report template. `not_run`, failure and blocking dependencies
remain visible. Golden baselines and tolerances retain their existing review
and human-regeneration rules. See [acceptance](acceptance.md) and
[verification](verification.md).

## ADR-003 — Physical FPGA proof before funded ASIC realization

**Status:** accepted project-setup direction.

**Decision:** validate one selected supported FPGA configuration with real
external memory and host transfers before committing to custom silicon. P10
requires a qualified feasibility package and explicit human go/no-go approval;
P11 requires funded manufacturing sign-off and lab bring-up.

**Rationale:** an FPGA exposes integration, numerical, bandwidth, timing and
recovery issues while the design remains reconfigurable. Existing synthesis
flows do not supply all foundry-qualified memories, PHY/controller IP,
packaging, DFT or sign-off obligations.

**Consequences:** no board, memory technology, process node, tapeout date or
procurement is approved by this ADR. Early feasibility research may inform the
architecture, but does not bypass P10/P11 entry criteria. P09 training and
multi-device research can proceed separately and is not required for a bounded
inference ASIC. See [hardware](hardware.md) and [risks](risks.md).

## ADR-004 — Staged native development entry with vendor integration retained

**Status:** user-directed development sequencing decision, 2026-11-16.
This authorizes the roadmap dependency change; it is **not** an acceptance
waiver, hardware qualification, tool purchase or test result.

**Problem:** P01-A01 and P01-A02 are already backed by independently reviewed
clean-build and native numerical results. P01-A03 requires a qualified vendor
Vitis/Vivado/XRT platform unavailable to the current development environment.
The original all-of-P01 dependency prevented unrelated numerical and operator
work despite its satisfied native prerequisites.

**Decision:** leave P01-A03 in P01 unchanged and blocked. Make P02 depend on
completed P00 and on the **specific accepted P01-A01/A02 evidence**, not on
completion of P01-A03. Introduce machine-validated `entry_acceptances`: each
required ID must resolve to a compatible, genuinely passing report before
P02 may be `in_progress` or `complete`; adding a text claim is insufficient.
Require full P01 completion as an additional dependency for P07's final
acceptance, retaining the vendor full-AFU `hw_emu` obligation before declaring
the physical FPGA phase complete. P02/P03/P04/P05/P06 do **not** inherit a
hardware-vendor dependency that their declared native/simulated criteria do not
need. Every phase's own acceptance obligations remain unchanged.

**Alternatives considered:** (1) buy/provision expensive vendor infrastructure
before any more native development; (2) delete or label A03 passed without
running it; (3) silently replace vendor `hw_emu` with `xrtsim`. The latter two
would misrepresent evidence, and the first would block otherwise independent
native software progress without improving P02's numerical contract.

**Scope and consequences:** 12 phases and all 36 acceptance IDs remain. P01 is
`blocked`, P02 has begun and its three gates remain unaccepted, P03–P11 are
`not_started`. Vendor XRT P01-T05 remains an independently funded/qualified
workstream. No new tool, platform, board, dataset or numerical tolerance was
approved or modified. If accepted A01/A02 evidence is invalidated, the offline
validator will reject P02's in-progress/complete state. P07 acceptance requires
P01 completion and its own physical FPGA measurements. Follow the
[handoff](p02-entry-handoff.md) and [acceptance policy](acceptance.md).

## Open decisions

All entries below are **unresolved**. Owner columns identify accountable roles,
not named appointments or approvals.

| ID | Decision required | Required evidence before acceptance | Accountable role | Latest gate |
|---|---|---|---|---|
| ODR-001 | First AI configuration: XLEN, cores, tensor backend, formats and local memory | Reproducible baseline and native arithmetic coverage; explicit unsupported cases | Compute architecture lead | P02 |
| ODR-002 | Tiny model and supported operator/shape contract | Redistributable fixtures, deterministic reference, declared host/device work | Model runtime lead | P04 |
| ODR-003 | Initial Python/framework versions and bridge boundary | Packaging prototype, supported-op matrix and resource-lifetime tests | Framework integration lead | P05 |
| ODR-004 | Physical FPGA board, host and tool/platform versions | Availability, license/access approval, supported shell, memory-map and resource assessment | FPGA platform lead | P07 |
| ODR-005 | Performance, memory capacity and power targets | Frozen workload, baseline measurements, feasible resource/timing budgets and measurement plan | Performance and memory lead | P06/P07 |
| ODR-006 | Training workload and multi-device transport | Numerical requirements, physical topology, communication/failure model and resources | Research lead | P09 |
| ODR-007 | ASIC process, memory, PCIe/DRAM PHY/controller IP and package | Qualified PDK/macros/IP, licensing, vendor availability, estimates and sign-off plan | Silicon program lead | P10 |
| ODR-008 | ASIC funding, procurement, manufacturing and lab commitments | Reviewed quotes, accountable partners, schedule/risk reserves and explicit human approval | Silicon program lead / project maintainer | P10/P11 |

Hardware purchase, paid cloud use, license acquisition and manufacturing orders
require separate explicit authorization. A development roadmap is not that
authorization.
