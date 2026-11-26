# Architecture and program decisions

This log separates **accepted project-setup and scoped development decisions**
from **unresolved engineering and funding choices**. An accepted design direction
does not prove implementation, test success or permission to spend money. Phase progress and
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

**Scope and consequences at this decision's checkpoint:** 12 phases and all 36
acceptance IDs remained. P01 was `blocked`, P02 had begun and its three gates
remained unaccepted, and P03–P11 were `not_started`. Vendor XRT P01-T05 remains
an independently funded/qualified workstream. No new tool, platform, board,
dataset or numerical tolerance was
approved or modified. If accepted A01/A02 evidence is invalidated, the offline
validator will reject P02's in-progress/complete state. P07 acceptance requires
P01 completion and its own physical FPGA measurements. Follow the
[handoff](p02-entry-handoff.md) and [acceptance policy](acceptance.md).

## ADR-005 — Fixed nonlinear MLP on the accepted matmul signatures

**Status:** P04-T01 complete, with [P04-A01 accepted at `source_present`
scope](evidence/p04-fixture/acceptance.json), 2026-11-20. This resolves ODR-002's
model and placement selection. P04 remains `in_progress`; P04-A02/A03 are unearned.
The [qualification packet](evidence/p04-fixture/README.md) binds the reviewed
contract and all five passing formal commands to source
`10ace66193686e3862c3c218760b66c044f1d4ae`, tree
`775aa7d5f96cfc5f7346e591ca151f36c485d2cf`. Its source suite passed 1,733 tests
in 752.879 seconds with no failures, errors or skips and unchanged source.

**Decision owner:** the primary coding agent (`/root`), carrying out the user's
instruction to audit and implement the next bounded development step. Model
runtime lead remains the accountable role for model execution. This records the
actual engineering decision; it does not claim a separate human design approval
or waive the required independent review.

**Problem:** P03 qualifies six ordinary FP16/BF16-to-FP32 matmul signatures.
Native activation, conversion, reduction, normalization and attention operators
are explicitly unavailable. A transformer would require a wider operator
program before its execution could satisfy the current contract. One isolated
matmul would not exercise a nonlinear multilayer model or actual intermediate
dependencies.

**Decision:** select the [fixed tiny MLP v1](../designs/tiny_mlp_fixture_v1.md):
a bias-free 16→8→4 ReLU network evaluated on a fixed batch of 16. Generate its
160 original synthetic weights and deterministic inputs without external model
downloads. Freeze five families in each of FP16 and BF16, with independent
integer layer/final references, exact encodings, provenance and hashes in the
[fixture](../../ci/project/fixtures/p04_tiny_mlp_v1.json) and
[manifest](../../ci/project/p04_model_manifest.json).

Map the hidden layer to `(16,8,16)` and the two output row blocks to
`(8,4,8)`. Declare ReLU, exact FP32-to-input-format conversion and output row
assembly as host work before execution. Actual hidden outputs must feed the
bridge, and actual bridge bytes must feed the second layer. Frozen reference
arrays are comparator data only. A native failure fails the case; it cannot
select a CPU matmul path.

**Alternatives:** expanding native activation/cast/attention first remains a
future development option, but exceeds this fixture-freeze task. A linear-only
network would miss the nonlinear dependency this fixture is designed to check.
A pretrained model would introduce larger redistribution and numerical-scope
requirements without providing evidence for the current fixed operators.

**Consequences and evidence boundary:** the bounded integer domain permits
exact comparisons under P02; no tolerance changes or P03 signature expansion
are needed. Synthetic weights establish correctness targets, not learned-model
quality. Source/reference/host-helper checks cannot prove device placement or
model execution. The [P04-T02 executor plan](p04-executor-plan.md) retains the
separate actual execution, intermediate comparison, resource lifetime and
host/transfer accounting obligations for P04-A02/A03. P01-A03 vendor `hw_emu`
remains blocked and required before P07 completion.

## ADR-006 — Staged Pre-Silicon Tapeout Readiness Tracks A–F

**Status:** user-directed pre-silicon engineering sequencing decision,
2026-11-26. This authorizes a parallel, machine-validated pre-silicon readiness
ledger ([`presilicon_readiness.json`](presilicon_readiness.json)) alongside
[roadmap.json](roadmap.json). It is **not** a hardware acceptance waiver,
foundry sign-off, commercial IP license, spending authorization, or physical
hardware/silicon evidence.

**Problem:** in [roadmap.json](roadmap.json), `P01-A03` (vendor XRT `hw_emu`)
is legitimately `blocked` due to missing commercial Vitis/Vivado/XRT host
infrastructure, and `P07`–`P11` are legitimately `not_started` awaiting physical
FPGA hardware, human go/no-go approval, and fabricated silicon. That physical
and commercial boundary must remain unwaived and unaltered. At the same time,
substantial pre-silicon engineering, RTL architecture definition, RTL
verification, open-source/synthetic physical-design preparation, and software/ISA
hardening for the target AI silicon class can advance honestly in parallel if
tracked under strict evidence ceilings that never claim physical FPGA or
manufactured silicon proof.

**Decision:**

1. **Preserve [roadmap.json](roadmap.json) honesty without modification or
   waiver:** `P01` remains `blocked` on `P01-A03` (vendor XRT `hw_emu`), and
   `P07`–`P11` remain `not_started` (physical FPGA prototype, reliability
   hardening, research, human go/no-go approval, and funded silicon
   realization). No pre-silicon track alters phase statuses, phase
   dependencies, or physical acceptance criteria in [roadmap.json](roadmap.json).
2. **Authorize a parallel, machine-validated pre-silicon tapeout readiness
   ledger:** establish [`presilicon_readiness.json`](presilicon_readiness.json),
   validated offline by [`ci/project/check_presilicon.py`](../../ci/project/check_presilicon.py),
   tracking six bounded pre-silicon tracks (`TRACK-A` through `TRACK-F`)
   spanning architecture & profile freeze, compute-tile RTL & datapath
   verification, memory/interconnect/NoC & coherence verification, pre-silicon
   PPA/DFT/CDC/physical-readiness preparation, software/runtime/compiler
   hardening, and pre-silicon sign-off dossier & handoff packaging.
3. **Strict evidence-level ceiling (`source_present`, `simulated`,
   `rtl_verified` only):** every track and evidence entry in the pre-silicon
   ledger is strictly bounded to `source_present`, `simulated`, and
   `rtl_verified`. Claims of `fpga_measured` or `silicon_measured` are
   unconditionally rejected by the pre-silicon validator, and every evidence
   entry must resolve to an existing repository artifact with matching SHA-256
   checksum, valid commit hash, and compatible evidence level.
4. **Target silicon class and RTL verification slice:** record the target
   datacenter AI-only SoC architecture (`aigpu-b1`, 64-core datacenter AI-only
   SoC) paired with a bounded 4-core RTL-verifiable compute tile profile
   (`aigpu-b1-tile`, 4-core RTL-verifiable compute tile) so RTL simulation,
   open-source synthesis, and protocol/coherence checks execute within bounded
   compute and memory budgets without misrepresenting tile simulation as full
   64-core SoC or physical silicon closure.

**Alternatives considered:** (1) relax `P01-A03` or `P07`–`P11` gates in
[roadmap.json](roadmap.json) to `in_progress`/`complete` before physical FPGA
and human go/no-go approval exist; (2) track pre-silicon readiness only in
unvalidated prose. Option (1) would violate [ADR-002](decisions.md#adr-002--evidence-labels-and-exact-execution-scope),
[ADR-003](decisions.md#adr-003--physical-fpga-proof-before-funded-asic-realization),
and [acceptance policy](acceptance.md); option (2) lacks hash-checked,
machine-enforced separation between pre-silicon evidence and physical/tapeout
sign-off.

**Consequences and evidence boundary:** `physical_gates_unwaived` remains
`true`. `aigpu-b1` (64-core datacenter AI-only SoC) and `aigpu-b1-tile` (4-core
RTL-verifiable compute tile) define engineering targets and verification scopes
only; they do not approve `ODR-007`/`ODR-008`, select commercial foundries,
PDKs, memory PHYs, or PCIe IP, or authorize any spending or tapeout commitment.
Physical FPGA measurements (`P07`–`P09`), human go/no-go authorization (`P10`),
and foundry manufacturing sign-off/silicon bring-up (`P11`) remain governed
exclusively by [roadmap.json](roadmap.json).

## Open decisions

All entries below are **unresolved**. Owner columns identify accountable roles,
not named appointments or approvals.

| ID | Decision required | Required evidence before acceptance | Accountable role | Latest gate |
|---|---|---|---|---|
| ODR-001 | First AI configuration: XLEN, cores, tensor backend, formats and local memory | Reproducible baseline and native arithmetic coverage; explicit unsupported cases | Compute architecture lead | P02 |
| ODR-003 | Initial Python/framework versions and bridge boundary | Packaging prototype, supported-op matrix and resource-lifetime tests | Framework integration lead | P05 |
| ODR-004 | Physical FPGA board, host and tool/platform versions | Availability, license/access approval, supported shell, memory-map and resource assessment | FPGA platform lead | P07 |
| ODR-005 | Performance, memory capacity and power targets | Frozen workload, baseline measurements, feasible resource/timing budgets and measurement plan | Performance and memory lead | P06/P07 |
| ODR-006 | Training workload and multi-device transport | Numerical requirements, physical topology, communication/failure model and resources | Research lead | P09 |
| ODR-007 | ASIC process, memory, PCIe/DRAM PHY/controller IP and package | Qualified PDK/macros/IP, licensing, vendor availability, estimates and sign-off plan | Silicon program lead | P10 |
| ODR-008 | ASIC funding, procurement, manufacturing and lab commitments | Reviewed quotes, accountable partners, schedule/risk reserves and explicit human approval | Silicon program lead / project maintainer | P10/P11 |

Hardware purchase, paid cloud use, license acquisition and manufacturing orders
require separate explicit authorization. A development roadmap is not that
authorization.
