# P10 — ASIC Feasibility Dossier & Sign-Off Planning Package

> [!IMPORTANT]
> **Phase status: `not_started` in [roadmap.json](roadmap.json).**
> **Evidence scope: `source_present` preparatory dossier and open-source academic synthesis estimates only.**
> This document records a bounded inference-ASIC candidate, exact open-source ASAP7 Yosys/OpenSTA synthesis baselines, the unacquired PDK/IP/package/EDA dependency register (`ODR-007` / `ODR-008`), engineering sign-off checklists, and an **unapproved** Go/No-Go gate template.
> **It is NOT foundry sign-off, NOT approved funding, NOT a tapeout commitment, and NOT authority to negotiate commercial contracts or purchase IP/hardware.**

Governed by [P10 phase criteria](phases/p10-asic.md), [hardware policy](hardware.md), [decision log](decisions.md), [risk register](risks.md), and [acceptance policy](acceptance.md). Companion lab bring-up plan: [p11-silicon-bringup-plan.md](p11-silicon-bringup-plan.md). Machine-checkable validator: [`p10_feasibility_check.py`](../../ci/project/p10_feasibility_check.py).

---

## 1. Bounded Inference ASIC Target Architecture (`P10-A02` Scope)

Per [ADR-003](decisions.md) and [P10 entry rules](phases/p10-asic.md), this dossier bounds the first custom-silicon candidate to **single-chip inference only**. [P09](phases/p09-research.md) training and multi-device collectives are **not** prerequisites and are explicitly excluded from the first silicon target.

### 1.1 Architectural Baseline vs. Scaled Candidate

| Dimension | Baseline Anchor (`p02-tfr`) | Scaled ASIC Candidate (`2–4 Core L2`) | Contract / Decision Status |
|---|---|---|---|
| **ISA / Address Width** | RV64 (`VX_CFG_XLEN=64`, `VX_CFG_MEM_ADDR_WIDTH=48`) | RV64 (`VX_CFG_XLEN=64`, `VX_CFG_MEM_ADDR_WIDTH=48`) | Carried forward from [`p02-tfr.json`](../../profiles/p02-tfr.json) |
| **Cluster / Core Topology** | 1 cluster × 1 core (`VX_CFG_NUM_CLUSTERS=1`, `VX_CFG_NUM_CORES=1`) | 1 cluster × 2 to 4 cores (`VX_CFG_NUM_CORES=2..4`) | Candidate scaling envelope (`ODR-007` undecided) |
| **Warps / Threads / Issue** | 4 warps × 4 threads, `VX_CFG_ISSUE_WIDTH=1` | 4–8 warps × 4–8 threads, `VX_CFG_ISSUE_WIDTH=1..2` | Subject to area/timing/bandwidth closure |
| **Native Tensor Backend** | `VX_CFG_EXT_TCU_ENABLE=true`, `VX_CFG_TCU_TYPE=TFR`, `VX_CFG_TCU_USE_DSP=0` | Same native `TFR` backend (`VX_CFG_NUM_TCU_BLOCKS == VX_CFG_ISSUE_WIDTH`) | Native RTL contract ([`tensor_numerics_v1.md`](../designs/tensor_numerics_v1.md)) |
| **Scalar FPU** | `VX_CFG_FPU_TYPE=STD`, `VX_CFG_FPU_USE_DSP=0` | `VX_CFG_FPU_TYPE=STD`, `VX_CFG_FPU_USE_DSP=0` | Non-DPI ASIC RTL path ([`VX_config.toml`](../../VX_config.toml)) |
| **Tensor Formats** | Dense FP16/BF16→FP32 WMMA (`VX_CFG_TCU_FP16_ENABLE=true`; all other format banks `*_DISABLE`) | Dense FP16/BF16→FP32 baseline; WGMMA/DXA/MX only if separately qualified | Frozen P02 numerics; no silent format expansion |
| **On-Chip Memory / Coherence** | L1 I/D-cache + shared LMEM (`VX_CFG_LMEM_ENABLE=true`) | Shared cluster L2 (`VX_CFG_L2_ENABLE=true`, `VX_CFG_L2_WRITEBACK=1`, `VX_CFG_CP_ON_LLC=1`) + per-core L1/LMEM | Follows single-cluster LLC coherence rules in [`VX_config.toml`](../../VX_config.toml) |
| **External Memory Interface** | Simulator memory model only (`HBM2` placeholder in `VX_config.toml`) | **Undecided**: HBM2/2e (with interposer) vs. LPDDR5 controller + PHY | `UNDECIDED` (`ODR-007`) |
| **Host Interface** | Simulator/AFU wrapper only | **Undecided**: PCIe Gen4 or Gen5 x8/x16 Endpoint Controller + PHY | `UNDECIDED` (`ODR-007`) |
| **Validation Workloads** | P02 TFR unit/WMMA suite, P03 operator suite, P04 [`tiny_mlp_fixture_v1`](../designs/tiny_mlp_fixture_v1.md) | Same frozen numerical/operator/MLP contracts + P06/P07 scaled inference suite | Frozen contracts; no silicon measurements exist |

### 1.2 Carried-Forward Invariants & Prerequisites

1. **P08 FPGA Hardening Prerequisite:** Per [roadmap.json](roadmap.json), `P10` depends on `P08` completion (which in turn requires `P01-A03` vendor `hw_emu`, `P05`, `P06`, `P07` physical FPGA proof, and 24-hour physical soak). Preliminary feasibility work does not waive `P08`.
2. **RAM Folding & Synchronous Macro Mapping:** As implemented in [`VX_sp_ram.sv`](../../hw/rtl/libs/VX_sp_ram.sv) and [`VX_dp_ram.sv`](../../hw/rtl/libs/VX_dp_ram.sv), only `FORCE_BRAM && OUT_REG != 0` arrays instantiate `VX_sp_ram_asic` / `VX_dp_ram_asic`; combinational-read (`OUT_REG=0`) or LUTRAM-flagged arrays synthesize into flip-flops unless folded by `hw/scripts/ram_fold.py` (`ram_fold.rpt`). Every ASIC SRAM instance must be audited for real macro mapping before physical design.
3. **Configuration Discipline:** Boolean format/feature disables must continue to resolve via `VX_CFG_*_DISABLE` through `VX_config.toml` and `ci/gen_config.py`, never via `VX_CFG_*_ENABLE=0` workarounds.

---

## 2. Open-Source Yosys + OpenSTA ASAP7 PPA Estimates (`P10-A02` Estimates)

> [!WARNING]
> **Academic ASAP7 Open-Source Synthesis Estimates — NOT Foundry Sign-Off.**
> The metrics below are reproduced verbatim from the checked-in Yosys + OpenSTA baselines in [`ci/baselines/synthesis/yosys/tensor.json`](../../ci/baselines/synthesis/yosys/tensor.json) and [`ci/baselines/synthesis/yosys/core.json`](../../ci/baselines/synthesis/yosys/core.json).
> They are **pre-layout academic ASAP7 estimates without real SRAM macros, PHY/IO pads, or foundry sign-off**. They **cannot** be cited as post-layout ASIC PPA, silicon Fmax, or manufacturing readiness.

### 2.1 Checked-In Yosys/OpenSTA ASAP7 Baseline Table

Common synthesis environment across all rows below: `pdk=asap7`, `vt=rvt`, `corner=tt`, `xlen=32`, `yosys="Yosys 0.69"`, `sta="3.1.0"`, `clock_mhz=800` (1.25 ns period). Note that `tcu` lives inside [`ci/baselines/synthesis/yosys/tensor.json`](../../ci/baselines/synthesis/yosys/tensor.json) alongside `tensor`, and `cache`, `core`, `lmem`, and `top` live inside [`ci/baselines/synthesis/yosys/core.json`](../../ci/baselines/synthesis/yosys/core.json) (DUT definitions in [`hw/syn/yosys/dut/catalog.mk`](../../hw/syn/yosys/dut/catalog.mk)).

| DUT | Baseline File | Effective Configs / Notes | Cell Count | Cell Area (um^2) | Seq Area (um^2) | Est. Black-Box SRAM Area (um^2) | Target-Clamped Fmax (MHz) | WNS / TNS (ns) | Vectorless Power (mW) | Build Time (s) | Evidence Label |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `tcu` (`VX_tcu_unit_top`) | [`tensor.json`](../../ci/baselines/synthesis/yosys/tensor.json) | `config_hash: 5110889c4c9985a1` (`tcu_CFG`: 16T/16W, TFR, FP16/FP8/I8/I4/TF32/Sparse/WGMMA, F disabled) | `760,362` | `74,231.737` | `12,099.067` | `0.0` | `870.549` | `0.101` / `0.0` | `359.0` | `2,210` | Academic ASAP7 pre-layout estimate |
| `tensor` (`VX_tensor_top`) | [`tensor.json`](../../ci/baselines/synthesis/yosys/tensor.json) | `config_hash: 5e33a96e107c9a6b` (`-DVX_CFG_NUM_THREADS=8 -DVX_CFG_NUM_WARPS=8`, 2 cores, 256 KiB L2, TCU+WGMMA+MX+DXA+A) | `888,126` | `96,735.909` | `41,783.364` | `52,361.6` | `1,119.445` | `0.357` / `0.0` | `236.0` | `834` | Academic ASAP7 pre-layout estimate (black-box SRAM) |
| `core` (`VX_core_top`) | [`core.json`](../../ci/baselines/synthesis/yosys/core.json) | `config_hash: 67eb0ef49175ab38` (`-DVX_CFG_NUM_THREADS=8 -DVX_CFG_NUM_WARPS=8`, A+C) | `731,009` | `76,015.6` | `25,929.947` | `27,814.4` | `1,019.992` | `0.27` / `0.0` | `832.0` | `803` | Academic ASAP7 pre-layout estimate (black-box SRAM) |
| `cache` (`VX_cache_top`) | [`core.json`](../../ci/baselines/synthesis/yosys/core.json) | `config_hash: 4fd77575a6f5f52c` (`cache_CFG`: `EXT_A_ENABLE`) | `547,028` | `59,584.48` | `28,618.499` | `16,307.2` | `1,291.823` | `0.476` / `0.0` | `161.0` | `296` | Academic ASAP7 pre-layout estimate (black-box SRAM) |
| `lmem` (`VX_lmem_unit_top`) | [`core.json`](../../ci/baselines/synthesis/yosys/core.json) | `config_hash: 47081ee86b993ce8` (`-DVX_CFG_NUM_THREADS=16 -DVX_CFG_ISSUE_WIDTH=2 -DVX_CFG_EXT_A_ENABLE`) | `166,236` | `17,137.142` | `6,527.758` | `55,628.8` | `2,003.606` | `0.751` / `0.0` | `42.2` | `110` | Academic ASAP7 pre-layout estimate (black-box SRAM) |
| `top` (`VX_afu_wrap`) | [`core.json`](../../ci/baselines/synthesis/yosys/core.json) | `config_hash: 23d795386c3e20c0` (`-DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4`, 2 cores, A+VM, DCACHE_LATENCY=3) | `1,609,348` | `172,526.117` | `72,499.05` | `72,302.4` | `1,028.807` | `0.278` / `0.0` | `247.0` | `1,376` | Academic ASAP7 pre-layout estimate (black-box SRAM) |

### 2.2 Mandatory Interpretation Boundaries for ASAP7 Estimates

Every figure in Section 2.1 carries six hard structural limitations documented in [`docs/synthesis_analysis.md`](../synthesis_analysis.md) and [`hw/syn/yosys/sram_cost.py`](../../hw/syn/yosys/sram_cost.py):

1. **Predictive Academic PDK Only:** ASAP7 (`7.5-track v28`, BSD-3-Clause) is an academic predictive 7nm library (`tt` corner only here). It supplies no foundry DRC/LVS decks, no calibrated silicon aging/EM/IR rules, and no physical manufacturing collateral.
2. **Black-Box SRAM Heuristic (`sram_cost.py`):** `sram_area_um2` is computed purely by port-width/address-width connectivity inference on black-box [`VX_sp_ram_asic.v`](../../hw/syn/libs/no_mem/VX_sp_ram_asic.v) and [`VX_dp_ram_asic.v`](../../hw/syn/libs/no_mem/VX_dp_ram_asic.v) using `(width × depth × 0.1 um^2/bit) + 100.0 um^2`. Black-box stubs omit macro aspect ratios, routing blockages, MBIST wrappers, bit-cell leakage/dynamic power, and real setup/hold/clk-to-q timing.
3. **RV32 Baseline vs. RV64 Target Gap:** All six checked-in Yosys baselines above were synthesized at `xlen=32`. The bounded inference ASIC target (`p02-tfr`) is **RV64** (`xlen=64`), which widens integer datapaths, register files, addresses (`48-bit`), and L1/L2 tag/data widths.
4. **Target-Clamped `fmax_mhz`:** ABC maps to the requested `800 MHz` period and stops once positive slack is achieved; `fmax_mhz` only reflects pre-layout `tt`-corner slack (`1 / (1.25 ns - wns_ns)`), not silicon clock capability across `ss`/`ff` PVT corners or post-CTS/post-route interconnect delay.
5. **Vectorless Power Excludes Macros & I/O:** OpenSTA `power_mw` assumes default toggle rate (`12.5%`) and static probability (`0.5`) on standard cells only; it excludes SRAM macro power, clock-tree buffers, I/O pads, PLL, and SerDes/PHY power.
6. **Zero Uncore / PHY / Pad Coverage:** `VX_afu_wrap` (`top`) is an internal control/memory wrapper, not an ASIC pad ring, PCIe Gen4/5 controller+PHY, or HBM2/LPDDR5 controller+PHY. Inherited `hw/syn/libs/cln28hpm/` and `hw/syn/libs/cln28hpc/` files are restricted/proprietary vendor collateral without active project licensing or sign-off authorization.

---

## 3. External PDK, IP, Package & EDA Dependency Register (`ODR-007` / `ODR-008`, `P10-A01`)

All commercial foundry, IP, packaging, and EDA dependencies below are currently **unacquired**. Under [P10](phases/p10-asic.md) and [RK-009 / RK-010 / RK-015](risks.md), `P10-A01` cannot pass until every required category has an assigned accountable owner, verified license/redistribution compliance, and **written supplier availability, delivery, and cost quotes**.

| Dep ID | Category | Required Component & Integration Interface | Accountable Role (Role Only) | Required Qualification Evidence | Current Status | Blocking Gate |
|---|---|---|---|---|---|---|
| `DEP-PDK-01` | **Foundry Process & PDK** (`ODR-007`) | Target foundry process node (e.g., 28nm/22nm/12nm/7nm/5nm), PDK design rules, DRC/LVS/PEX decks, reliability/EM rules | Silicon program lead | Executed Foundry NDA, PDK release version, MPW/shuttle schedule, written wafer/mask quote | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-STD-02` | **Standard Cells & IO/Pad Ring** | Multi-VT standard-cell libraries (`.lib`/`.db`/LEF/GDS/CDL), GPIO/ESD pads, level shifters, power switches/isolation cells | Physical design lead | Licensed foundry/library vendor collateral across PVT corners (`ss`/`tt`/`ff`), written license quote | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-SRAM-03` | **SRAM Macro Compiler & Wrappers** | Single-port (`1RW`), dual-port (`1R1W`/`2RW`), and register-file memory compilers replacing [`VX_sp_ram_asic.v`](../../hw/syn/libs/no_mem/VX_sp_ram_asic.v) & [`VX_dp_ram_asic.v`](../../hw/syn/libs/no_mem/VX_dp_ram_asic.v), plus MBIST & repair collars | Physical design lead / Memory lead | Generated macro `.lib`/LEF/GDS/Verilog across all Vortex array sizes, silicon-proven yield/BIST spec, written compiler quote | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-CLK-04` | **Clock & Reset Infrastructure IP** | Fractional/integer PLL(s), crystal oscillator IO, POR, glitch-free clock muxes/dividers, PVT/droop monitors | Silicon program lead | Silicon-qualified analog/mixed-signal PLL datasheets, jitter spec, GDS/LEF/Liberty views, written quote | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-PCIE-05` | **PCIe Gen4/Gen5 Controller + PHY** (`ODR-007`) | PCIe Gen4 or Gen5 (x8/x16) Endpoint Controller + SerDes PHY, PIPE interface, AXI/DMA bridge, MSI-X, BAR/config space | Silicon program lead / Host interface owner | Vendor IP entitlement, PCI-SIG compliance record, PHY bump/package constraints, integration RTL/VIP, written NRE/royalty quote | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-MEM-06` | **HBM2/2e or LPDDR5 Controller + PHY** (`ODR-007`) | Selected external memory Controller + PHY (AXI4/CHI bridge to Vortex memory fabric, training firmware, ECC/scrubbing). **If HBM2/2e:** requires 2.5D silicon interposer/CoWoS-class substrate, uBump PHY, known-good-die (KGD) DRAM supply & thermal plan | Memory lead | Vendor IP datasheet, bandwidth/latency/area/power spec, training firmware license, HBM interposer/OSAT feasibility (if HBM), written quote | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-PKG-07` | **Package, Interposer & OSAT Assembly** | Flip-chip BGA or 2.5D interposer substrate design, ballout/bump map, SI/PI co-design, lid/TIM thermal stack, ATE test socket | Package / board lead | OSAT partner acceptance, substrate stackup & design rules, thermal dissipation spec, written assembly & test quotes | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-EDA-08` | **Commercial EDA Tool Licenses** | Commercial RTL/gate sim, formal/CDC/RDC/LEC, synthesis, P&R, sign-off STA (MCMM/SI), DRC/LVS/PEX, IR-drop/EM, DFT/ATPG/MBIST, package SI/PI | Verification lead / Physical design lead | Active commercial tool licenses covering full seat/compute duration through tapeout, written vendor quotes | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A01` |
| `DEP-FAB-09` | **MPW / Foundry & Test Partner Commitment** (`ODR-008`) | Multi-project wafer (MPW) or dedicated mask shuttle, wafer sort, packaging, reliability/burn-in, and ATE production test access | Silicon program lead / Project maintainer | Written foundry/broker/OSAT SOWs, lead-time schedule, respin contingency, and human procurement authorization | `UNACQUIRED / REQUIRES WRITTEN QUOTE` | `P10-A03` |

---

## 4. Engineering Sign-Off Checklists (`P10-A02` / `P11-A01`)

No checklist item below may rely on black-box SRAM timing/area stubs, predictive ASAP7 models, or simulator-only DPI arithmetic. Every sign-off exception requires an accountable specialist's written disposition (`P11-A01`), never an agent-issued waiver.

### 4.1 Functional, Formal, Equivalence & CDC/RDC Verification Checklist

- [ ] **RTL & Contract Freeze:** Pin exact source commit, `VX_config.toml` / `p02-tfr` (or scaled L2) resolved configuration hash, and frozen P02/P03/P04 numerical contracts.
- [ ] **Native Datapath Regression:** 100% pass of native `TFR` FP16/BF16→FP32 WMMA, scalar `STD` FPU, L1/L2 coherence, and `p04-tiny-mlp-v1` in RTL simulation (zero DPI substitution).
- [ ] **Formal Property & Protocol Verification:** Formal proofs/bounded checks on WGMMA/barrier synchronization, arbitration starvation/deadlock freedom, AXI/memory-fabric protocol compliance, and cache-coherence invariants.
- [ ] **Clock-Domain & Reset-Domain Crossing (CDC/RDC):** Structural and formal CDC/RDC sign-off across core clock, PCIe PHY/controller clocks, DRAM/HBM clocks, and JTAG/TCK domains; zero unsynchronized crossings or reset-glitch paths.
- [ ] **Logic Equivalence Checking (LEC):** Formal RTL-vs-post-synthesis, post-synthesis-vs-post-DFT, and post-DFT-vs-post-route netlist equivalence (zero unverified black boxes or unmapped compare points).
- [ ] **SDF Back-Annotated Gate-Level Simulation (GLS):** Reset initialization (zero X-propagation), JTAG/MBIST bring-up sequences, and representative native tensor/DMA bursts simulated with real compiled SRAM/PHY Verilog models and worst-case SDF timing.

### 4.2 DFT, Scan, ATPG, MBIST & JTAG Sign-Off Checklist

- [ ] **IEEE 1149.1 JTAG TAP & Boundary Scan:** Dedicated JTAG TAP controller, chip IDCODE register, boundary-scan chain around digital IOs, and secure/authenticated debug-mode gating (if applicable).
- [ ] **Full-Scan & ATPG Coverage:** Muxed-D scan insertion across all non-exempt flops; on-chip scan compression; ATPG fault grading meeting program targets (target `>= 99%` stuck-at and `>= 90%` transition-delay/at-speed coverage, or reviewed coverage gaps).
- [ ] **Real Compiled-Macro MBIST (Zero Black-Box Stubs):** Hardware MBIST controllers wrapping **every** instantiated foundry SRAM macro (L1 I/D-cache data & tag arrays, L2 data & tag arrays, LMEM banks, register files, TCU buffers) with march/retention patterns and redundancy/repair fuse mapping where supported.
- [ ] **DFT Mode Timing & Shift-Power Analysis:** Separate STA corners for scan-shift and capture modes; IR-drop/thermal check during high-toggle scan shift.
- [ ] **ATE Test Program Readiness:** STIL/WGL pattern export verified in zero-delay and SDF-timed simulation, correlated with OSAT/ATE tester channel and vector-memory limits.

### 4.3 Physical Design, Floorplan, CTS & Physical Verification Checklist

- [ ] **Macro & Die Floorplanning:** Explicit placement of compiled SRAM macros, PCIe PHY, DRAM/HBM PHY, PLLs, and IO ring with foundry-compliant keep-out halos, channel widths, and bump/pad alignment.
- [ ] **Clock-Tree Synthesis (CTS):** Balanced clock trees with target skew, max transition/capacitance, OCV-aware useful skew bounds, and shielded high-speed/clock trunks.
- [ ] **Routing & Congestion Closure:** Post-route DRC-clean routing with bounded detouring, via-pillar/double-cut via optimization, and antenna/metal-density compliance.
- [ ] **Foundry Physical Sign-Off:** Zero unwaived DRC, LVS (netlist-to-GDS schematic match), ERC, antenna, metal-fill, and latch-up violations using qualified foundry decks (never ASAP7).

### 4.4 Sign-Off Static Timing Analysis (STA) Checklist

- [ ] **Qualified Models Only:** All standard cells, IO pads, PLLs, PCIe PHY, DRAM/HBM PHY, and **every compiled SRAM macro** modeled with foundry-qualified `.lib`/`.db` and extracted SPEF parasitics (no `VX_sp_ram_asic`/`VX_dp_ram_asic` black-box placeholders).
- [ ] **Multi-Corner Multi-Mode (MCMM) Closure:** Simultaneous setup, hold, recovery, removal, max-transition, max-capacitance, and min-pulse-width closure across all required PVT corners (`ss`/`ff`/`tt`, temperature extremes, voltage droop corners) and functional/test/reset modes.
- [ ] **OCV / AOCV / POCV & SI Crosstalk:** Statistical/parametric on-chip variation derating, coupling-capacitance crosstalk delta-delay analysis, and explicit clock uncertainty/PLL jitter margins.

### 4.5 Power Integrity (IR Drop, EM) & Thermal Sign-Off Checklist

- [ ] **Static & Dynamic IR Drop:** Rail-level static and vector-driven (SAIF/VCD) dynamic IR-drop analysis ensuring worst-case voltage droop remains strictly within standard-cell, SRAM, and PHY characterization bounds.
- [ ] **Electromigration (EM):** Signal, clock, and power-grid DC/RMS/peak EM compliance across target lifetime and junction temperature.
- [ ] **Package / Board PDN & Thermal Co-Design:** Package substrate/interposer RLC extraction coupled to on-die PDN; thermal resistance ($\theta_{JA}$ / $\theta_{JC}$) and TDP envelope validated for active cooling plan.

---

## 5. Human Go/No-Go Approval & Funding Gate (`P10-A03` — `UNAPPROVED`)

> [!CAUTION]
> **CURRENT DECISION STATUS: `UNAPPROVED` (`go_approved = false`).**
> Under [P10 stop conditions](phases/p10-asic.md) and [RK-010](risks.md), repository agents **cannot** select commercial suppliers, commit budgets, approve `ODR-007` or `ODR-008`, or mark `go_approved=true`. A valid approval requires explicit human sign-off backed by written supplier quotes and non-black-box sign-off plans, enforced mechanically by [`ci/project/p10_feasibility_check.py`](../../ci/project/p10_feasibility_check.py).

### 5.1 Approval & Commitment Template

| Gate Item | Required Content Before `P10-A03` Closure | Current Record | Status |
|---|---|---|---|
| **Go / No-Go Decision** | Explicit recorded human decision (`go_approved`: `true` or `false`) | `false` (`UNAPPROVED`) | `UNAPPROVED` |
| **Accountable Human Approver** | Named human decision owner (non-agent, non-placeholder) + ISO date | `UNASSIGNED` | `UNAPPROVED` |
| **Procurement Authority** | Named budget/contracting signatory authorizing external spend | `UNASSIGNED` | `UNAPPROVED` |
| **Target Configuration (`ODR-007`)** | Frozen node, core/L2 geometry, memory type/capacity, PCIe gen/lanes, package | `UNDECIDED` (candidate in §1) | `UNAPPROVED` |
| **Budget & Reserve (`ODR-008`)** | Written quotes summed across PDK/MPW, IP NRE/royalties, EDA, OSAT/package, bring-up board + contingency reserve | `REQUIRES WRITTEN QUOTES` | `UNAPPROVED` |
| **Schedule & Milestones** | Critical-path schedule from RTL freeze through sign-off, tapeout, fab, assembly, and bring-up | `UNSCHEDULED` | `UNAPPROVED` |
| **External Partners** | Named foundry/shuttle broker, IP vendors, EDA vendor, OSAT, and test house | `UNSELECTED` | `UNAPPROVED` |
| **Accountable Engineering Owners** | Named human leads for Silicon Program, Architecture, Verification, PD, DFT, Package/Board, Bring-Up | `UNASSIGNED` (roles only) | `UNAPPROVED` |
| **Risk Disposition** | Formal maintainer disposition for `RK-009`, `RK-010`, `RK-015`, plus residual yield/respin reserve | `OPEN` | `UNAPPROVED` |

### 5.2 Machine-Checkable Validation Gate

Before any future P10 feasibility JSON record is accepted or reviewed for `P10-A03`:

```sh
python3 ci/project/p10_feasibility_check.py validate <feasibility_package.json>
```

The validator enforces that:
1. Academic ASAP7 / Yosys / OpenSTA / black-box SRAM estimates are **never** marked as foundry manufacturing sign-off (unconditional rejection even when `go_approved=false`).
2. `go_approved=true` is rejected unless a named human approver, ISO approval date, explicit funding approval, written foundry/PDK/SRAM/PCIe/memory IP/package/EDA quotes, named foundry/OSAT partners, and complete non-black-box verification/DFT/MBIST/STA/PI sign-off plans are all present.
