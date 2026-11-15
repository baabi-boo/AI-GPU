# Risk register

This register describes risks to the [AI-GPU charter](charter.md), not verified defects in every configuration. Its initial evidence is source inspection at `da55a516a48b49013724f697d3c12a48932b449f`; it does not certify a simulator, FPGA or silicon result. The [baseline](baseline.md) records what is inherited. [roadmap.json](roadmap.json) is authoritative for phase dependencies and acceptance IDs.

## Rating, ownership and closure

- **Severity:** critical threatens trustworthy results, release safety or an irreversible silicon commitment; high can block a milestone or require substantial rework; moderate is locally recoverable.
- **Likelihood:** high means a known exposure is likely to be encountered on the proposed path; medium means a credible scenario needs testing; unknown means there is insufficient evidence. These are engineering judgments, not numerical probabilities.
- Every risk below starts **open**. Owner names are **roles to staff**, not claims that people, vendors or resources have been assigned. The maintainer must assign an accountable person before the affected gate is reviewed.
- Closing a risk requires a linked issue/decision, the tested revision and configuration, evidence addressing its trigger, residual limitations, and maintainer disposition. A lower rating, missing equipment, or a rewritten plan does not satisfy a blocked acceptance criterion.
- A triggered risk blocks the affected claim or gate, not necessarily unrelated development. Record the next bounded action in [status](status.md) and [backlog](backlog.md). New spending, external IP access and manufacturing commitments need explicit authorization.

## Register

| ID | Risk | Severity / likelihood | Accountable role | Affected acceptance gates |
|---|---|---|---|---|
| RK-001 | Numerical behavior differs across formats/backends | Critical / high | Compute architecture lead | P02-A01, P02-A02 |
| RK-002 | DPI or source presence is mistaken for native RTL proof | Critical / high | Verification lead | P01-A02, P02-A02 |
| RK-003 | WGMMA layout, synchronization or metadata hazards | High / medium | Compute architecture lead | P02-A03, P03-A02 |
| RK-004 | External toolchain and prebuilt identities drift | High / high | Verification lead | P01-A01, P05-A01 |
| RK-005 | HIP support is mistaken for tensor/framework compatibility | High / high | Framework integration lead | P03-A01, P05-A02, P05-A03 |
| RK-006 | Runtime ownership errors or silent CPU fallback | Critical / medium | Kernel and runtime lead | P03-A03, P04-A03, P08-A01 |
| RK-007 | Memory bandwidth, addressing or coherence limits scaling | High / high | Performance and memory lead | P06-A01, P06-A03, P07-A02 |
| RK-008 | A listed FPGA target is not an operational physical platform | High / unknown | FPGA platform lead | P07-A01, P07-A02, P07-A03 |
| RK-009 | ASIC estimates omit manufacturable memory/IP/sign-off | Critical / high | Silicon program lead | P10-A01, P10-A02, P11-A01 |
| RK-010 | Silicon work lacks funding, partners or authorized commitments | Critical / unknown | Silicon program lead | P10-A03, P11-A01 |
| RK-011 | Performance claims exceed the evidence | Critical / high | Performance and memory lead | P06-A01, P07-A03, P11-A03 |
| RK-012 | Builds, waveforms or installers exhaust or damage resources | High / high | Verification lead | P01-A01, P06-A03 |
| RK-013 | Cold-cache CI unexpectedly launches expensive work | High / high | Release and reliability lead | P01-A01, P08-A03 |
| RK-014 | Coverage or golden values are weakened to obtain a pass | Critical / medium | Verification lead | P01-A02, P02-A03, P06-A02 |
| RK-015 | Code, models or commercial IP lack redistribution rights | Critical / unknown | Release and reliability lead | P04-A01, P08-A03, P10-A01 |
| RK-016 | Training/multi-device scope overwhelms the inference milestone | High / high | Research lead | P09-A01, P09-A02, P09-A03 |
| RK-017 | Prototype correctness is mistaken for release reliability | Critical / medium | Release and reliability lead | P08-A01, P08-A02, P08-A03 |

## Triggers, mitigations and required evidence

### RK-001 — Numerical semantics

**Trigger:** a format is advertised without a frozen numerical contract, or changing arithmetic backend changes results outside the declared contract. The [tensor design](../designs/tensor_core_wgmma_engine.md) documents distinct rounding behavior and an open question for NVFP4 subnormal scales.

**Mitigation and closure evidence:** begin with the bounded FP16/BF16-to-FP32 profile; specify rounding, accumulation, exceptional values, overflow/underflow and tolerances before running tests. Use the appropriate independent/bit-exact reference and cancellation, subnormal, scale and sparse-metadata fixtures. Keep unresolved formats explicitly unsupported for product claims; do not widen tolerances to absorb a failure.

### RK-002 — Evidence substitution

**Trigger:** a `VX_CFG_TCU_TYPE_DPI` case, a filename, or a successful metadata check is offered as proof of native tensor RTL correctness. The [tensor catalog](../../ci/testcases/tensor.yaml) contains both native and DPI cases; the [backend documentation](../designs/tensor_core_wgmma_engine.md) identifies DPI as simulation-only C arithmetic.

**Mitigation and closure evidence:** record the resolved backend and build flags for every result. Separate functional simulation, native processor RTL, full AFU integration, physical FPGA and silicon reports. Require native datapath logs for the native RTL gates; a missing run remains `not_run` or blocked.

### RK-003 — Tensor scheduling and layouts

**Trigger:** larger shapes, multiple warps/CTAs, shared-memory descriptors, metadata or backpressure produce divergent results, hangs or stale operands. Existing [WGMMA attention](../../tests/regression/flash_attn_tcu_wg/) is a useful implementation and test starting point, not exhaustive verification.

**Mitigation and closure evidence:** freeze supported layouts and alignment, reject unsupported shapes, and exercise concurrency, reset, barriers and backpressure. Use matched SimX/native RTL traces to isolate the first divergence. Preserve the documented applicability limits of generic instruction/cycle parity; use an explicitly reviewed alternate comparison where required, not an unlabelled skip.

### RK-004 — Toolchain provenance

**Trigger:** compiler/runtime changes are consumed with old prebuilts, a mutable tag resolves differently, or application and backend configuration disagree. [VERSION](../../VERSION), the [installer](../../ci/toolchain_install.sh.in) and [AGENTS.md](../../AGENTS.md) describe coupled external dependencies.

**Mitigation and closure evidence:** record source/submodule SHAs, resolved prebuilt commit and archive hashes, XLEN/profile and generated configuration. Use isolated versioned tool directories and reconfigure after input changes. Land external component changes and matching approved artifacts before their consumer; a tag name alone is not reproducibility evidence.

### RK-005 — Software compatibility overreach

**Trigger:** basic HIP samples are treated as a CUDA-compatible stack or a PyTorch backend. The current [chipStar path](../designs/hip_on_vortex_chipstar.md) does not expose Vortex-specific tensor intrinsics.

**Mitigation and closure evidence:** use native kernels and the existing runtime for the initial operator library and model. Add a thin Python/custom-op bridge with explicit tested versions and unsupported-operation errors. A full framework device backend, ONNX support, autograd and CUDA binary compatibility each require separate scope and evidence; none follows from basic HIP execution.

### RK-006 — Runtime correctness and hidden placement

**Trigger:** host/device pointer-width or argument-layout mismatch, buffer lifetime errors, missing event ordering, out-of-bounds transfers, or host execution hidden behind an apparent GPU success.

**Mitigation and closure evidence:** define ownership and ABI contracts over [vortex2.h](../../sw/runtime/include/vortex2.h). Test negative inputs, resource exhaustion, repeated allocate/free and queue/event cleanup. Record operator placement and transfer traces; reject unsupported accelerated operations unless an explicitly requested host path is separately reported. Require no unexplained leaks or silent fallback in the supported path.

### RK-007 — Feeding and addressing the compute units

**Trigger:** more cores increase stalls, a memory-bank boundary corrupts data, or a configured capacity is mistaken for usable memory. The [cache contract](../designs/cache_subsystem.md), [DXA design](../designs/dxa_async_copy_multicast.md) and [U250 descriptor](../../hw/syn/xilinx/platforms/u250.toml) illustrate dependencies; U250 currently binds only bank 0.

**Mitigation and closure evidence:** retain coherence requirements while scaling, measure useful bandwidth and transfer traffic, and test allocations/bank boundaries on the selected platform. Distinguish theoretical bandwidth from sustained throughput and installed board memory from accessible GPU memory. Do not treat DXA as an arbitrary bidirectional host DMA engine.

### RK-008 — Physical platform availability and integration

**Trigger:** the board, compatible shell/firmware, licensed tools or host driver is unavailable; emulation passes but the board fails; or achieved clock differs from the requested frequency. [U200](../../hw/syn/xilinx/platforms/u200.toml) carries an incomplete-addressing warning, and the [XRT flow](../../hw/syn/xilinx/xrt/Makefile) permits frequency scaling.

**Mitigation and closure evidence:** select one supported, obtainable board through a recorded decision. Pin platform, firmware, device identity, memory map, bitstream and achieved clock. Pass physical enumeration, DMA, tensor/model and reset/soak tests. FPGA platform PCIe and DRAM/HBM controller/PHY facilities are dependencies, not capabilities supplied merely by the GPU core RTL. No board purchase or universal target-support promise is authorized by this plan.

### RK-009 — Manufacturing readiness gap

**Trigger:** synthesis area, a predictive library, black-box SRAM estimates or a generated layout file is presented as tapeout readiness. The [synthesis guide](../synthesis_analysis.md) explicitly includes pre-layout estimation and black-box SRAM treatment.

**Mitigation and closure evidence:** obtain foundry-qualified PDKs, SRAM macros, PCIe and memory controller/PHY IP, package/board strategy and appropriate licenses. Require real CDC/reset, DFT/scan/MBIST, timing, DRC/LVS and power-integrity sign-off from accountable specialists. HBM packaging and physical memory interfaces cannot be added by a software option. Keep estimates labelled as estimates until qualified sign-off exists.

### RK-010 — Funding and external commitments

**Trigger:** a silicon node, memory capacity, manufacturing schedule or purchase is promised before supplier availability, quotes, staffing and funds are established.

**Mitigation and closure evidence:** record a human go/no-go decision with scoped requirements, qualified partners, quotes, contingency and procurement authority before manufacturing release. The board, node, memory/IP suppliers, named specialists, budget and dates remain **undecided/unassigned** until documented. This register contains no fabricated cost or delivery estimate; repository agents cannot authorize spending.

### RK-011 — Invalid performance comparisons

**Trigger:** simulator host speed, `SIMX_FUNCTIONAL` cycle output, requested clock, sparse theoretical operations, or historical upstream figures are marketed as measured AI-GPU throughput or NVIDIA parity.

**Mitigation and closure evidence:** freeze workload/configuration, precision, sparsity, transfer inclusion, warm-up and repetition rules before comparison. Keep raw samples and compute-count definitions. Separate simulated cycles, synthesis predictions, achieved FPGA results and silicon measurements. Publish energy efficiency only with an actual power measurement and defined measurement boundary. See [benchmark policy](benchmarks.md).

### RK-012 — Resource exhaustion and destructive setup

**Trigger:** unconstrained parallel compilation or waveform collection consumes disk/RAM, or the tool installer replaces a shared directory. [AGENTS.md](../../AGENTS.md) documents approximately 95 GB for a whole-GPU Beacon build, not a universal machine requirement.

**Mitigation and closure evidence:** preflight the requested tier, review a resource budget, use bounded jobs and dedicated build/tool directories, and begin with small cases. Do not enable long traces by default. Retain concise evidence and checksums; clean only explicitly owned, validated targets with authority. Governance checks must not install the GPU toolchain. Follow the [developer guide](developer-guide.md).

### RK-013 — CI cost and availability

**Trigger:** a routine push encounters a cold toolchain cache or missing self-hosted FPGA tools. The inherited [CI workflow](../../.github/workflows/ci.yml) can escalate a cold-cache push to extensive ordinary driver/tier coverage, even for documentation changes.

**Mitigation and closure evidence:** inspect the planned matrix, cache status, runner availability and resource policy before expensive executions. Additive lightweight project checks validate metadata only; they neither make all inherited CI lightweight nor replace its tests. Do not dispatch heavy FPGA/ASIC tiers for documentation setup. Any future selection-policy change requires its own independent review and must preserve relevant functional coverage.

### RK-014 — Regression evidence erosion

**Trigger:** a test is removed, tolerated error widened or golden result edited solely to turn a failing gate green.

**Mitigation and closure evidence:** preserve [golden data](../../ci/baselines/) and the [review policy](../review/code-review-policy.md). Diagnose and fix the responsible change; add a regression case. Human-run, reviewed baseline regeneration is required where authorized. Independent review must explain every intentional coverage/threshold change; an agent cannot grant its own waiver.

### RK-015 — Licensing and provenance

**Trigger:** model weights, training fixtures, proprietary PDK/IP, tool outputs or copied code are redistributed without verified rights; inherited authorship is obscured by project branding.

**Mitigation and closure evidence:** preserve [LICENSE](../../LICENSE), attribution and original assets; maintain a dependency/model/IP inventory with provenance, license and redistribution constraints. Prefer a small reproducible model fixture with documented rights. Do not commit commercial IP, secrets or restricted artifacts. Resolve rights before the affected release or silicon decision.

### RK-016 — Training and multi-device expansion

**Trigger:** inference success is described as training support, or single-device work is delayed by promising distributed execution, collectives or NVLink-like performance without a physical topology.

**Mitigation and closure evidence:** keep P09 a separate research branch of the roadmap after the hardened prototype. Require gradient/convergence checks, two-device collective correctness, ordering/failure recovery and measured scaling. Transport choice and additional hardware remain decisions, not assigned resources. P09 is not a prerequisite for the bounded inference-ASIC feasibility gate.

### RK-017 — Reliability and security boundaries

**Trigger:** a short correct demo is released as a dependable or multi-tenant accelerator without fault handling, memory isolation, recovery or sustained-load evidence.

**Mitigation and closure evidence:** document the supported trust/deployment model; test malformed requests, exhaustion, reset/recovery and isolation before making those claims. Complete the canonical P07 initial and P08 release soak gates with traceable physical results and published limitations. An experimental release must identify unsupported production/security guarantees. See [verification](verification.md) and [release policy](releases.md).
