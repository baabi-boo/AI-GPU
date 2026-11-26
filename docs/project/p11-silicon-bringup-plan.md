# P11 — Silicon Bring-Up & Validation Plan Template

> [!IMPORTANT]
> **Phase status: `not_started` in [roadmap.json](roadmap.json).**
> **Evidence scope: `source_present` laboratory bring-up plan template only.**
> This document defines the structured pre-fabrication and post-silicon lab validation template for future packaged AI-GPU silicon (`P11-A01`, `P11-A02`, `P11-A03`).
> **It does NOT certify tapeout readiness, authorize fabrication or lab spend, or substitute simulation/FPGA measurements for `silicon_measured` evidence.**

Governed by [P11 phase criteria](phases/p11-silicon.md), [hardware policy](hardware.md), [acceptance policy](acceptance.md), [verification strategy](verification.md), [benchmark policy](benchmarks.md), and [release policy](releases.md). Prerequisite dossier: [p10-asic-feasibility-dossier.md](p10-asic-feasibility-dossier.md).

---

## 1. Pre-Bring-Up Entry & Safety Prerequisites (`P11-A01` Gate)

No board may be energized or device tested under `P11-A02` until `P10` is `complete` (`P10-A03` human go/no-go approved) and all items below are frozen and retained:

1. **Foundry Manufacturing Sign-Off & Tapeout Freeze (`P11-A01`):**
   - Complete functional, formal, CDC/RDC, LEC, SDF-GLS, ATPG/MBIST, MCMM STA, IR-drop/EM, and foundry DRC/LVS sign-off reports with zero unwaived violations.
   - Explicit human manufacturing-release approval, frozen GDS/OASIS checksum, mask revision ID, and foundry/OSAT lot traceability.
   - Manufacturing ATE test results (wafer sort / packaged part pass/fail bins, IDDQ, scan/MBIST bin summaries) archived per lot and sample ID.
2. **Board & Lab Readiness (`P11` WP 4):**
   - Bring-up board schematic/layout revision, BOM, assembly X-ray/optical inspection, and bare-board continuity/short checks prior to silicon population.
   - Calibrated bench supplies with strict hardware current limits, power-sequencing verification without silicon (or on dummy load), oscilloscope/logic-analyzer/thermal-camera calibration records, and active cooling/heatsink mounting verified.
   - **Operator safety boundary:** Only qualified lab operators may energize, probe, or rework physical bring-up hardware. Any unexpected over-current, thermal excursion, or smoke/odor triggers immediate power-off and root-cause quarantine.

### 1.1 Mandatory Sample & Environment Provenance Header (Per Tested Part)

| Field | Required Recorded Value (Never Omitted or Synthesized) |
|---|---|
| `device_lot_wafer_die_id` | Foundry lot ID, wafer #, die X/Y coordinates, ATE bin |
| `package_revision` | Package part #, substrate rev, OSAT assembly lot |
| `board_revision` | Bring-up / PCIe AIC board PCB rev, serial #, rework log |
| `rtl_tapeout_commit_hash` | Exact frozen git commit & config hash taped out |
| `firmware_driver_versions` | Memory-training FW version, PCIe/board BMC FW, host kernel driver & `vortex2` runtime SHA-256 |
| `ambient_and_cooling` | Ambient temp (°C), cooling solution (fan RPM / liquid flow / cold-plate setpoint) |
| `instrument_ids` | Oscilloscope, power analyzer/SMU, thermal sensor, logic analyzer serials & calibration dates |

---

## 2. Ordered Silicon Lab Bring-Up Sequence (`P11-A02`)

Proceed strictly in stage order. A stage failure halts progression into higher-risk stages until root-caused and explicitly dispositioned.

### Stage 1 — Power Rails, Sequencing, Clocks & Reset Sanity

- [ ] **Cold Impedance & Short Check:** Measure resistance to GND on every power rail (`VDD_CORE`, `VDD_SRAM`, `VDD_IO`, `VDD_PCIE_AVDD`, `VDD_MEM_PHY`, `VDD_PLL`) against bare-board/datasheet bounds before applying power.
- [ ] **Rail Ramp & Sequencing:** Bring up rails with bounded current limits; capture oscilloscope waveforms verifying monotonic ramp, zero overshoot/undershoot beyond spec, and exact inter-rail sequencing delays (`PG_ALL` assertion).
- [ ] **Idle / Reset Leakage Current:** Measure standby current on all rails with `POR_N` held asserted; compare against foundry/sign-off leakage envelope across corner expectations.
- [ ] **Reference Clocks & PLL Lock:** Verify external crystal/oscillator frequency, jitter/duty cycle, PLL lock indicator assertion, and divided clock-out test pins across target frequencies.
- [ ] **Reset Release & Strap Capture:** Deassert `POR_N` / `RST_N`; verify boot/configuration pin straps and absence of brownout/watchdog re-triggers.

### Stage 2 — JTAG, IDCODE, Scan & MBIST Sanity

- [ ] **IEEE 1149.1 JTAG TAP Access:** Connect JTAG probe; verify TDI→TDO bypass continuity and read exact silicon `IDCODE` matching tapeout freeze.
- [ ] **On-Chip Sensors & Monitors:** Read on-die PVT/thermal diode/voltage-droop monitors (if present); cross-check against calibrated external thermocouple/SMU.
- [ ] **Lab MBIST Execution:** Trigger on-chip MBIST across all SRAM domains (L1 I/D-cache, L2 cache, LMEM, register files, TCU buffers) at nominal voltage/clock; record pass/fail and any repair-fuse signature.
- [ ] **Lab Structural Scan / Reset-State Check:** Run structural scan/LBIST sanity vectors (where unlocked in lab mode) and confirm clean core/uncore reset register defaults via JTAG/DCR debug port.

### Stage 3 — External Memory Controller & PHY Training (HBM2/2e or LPDDR5)

- [ ] **PHY Initialization & Calibration:** Execute memory controller/PHY reset, ZQ/impedance calibration, PLL lock, and VREF training.
- [ ] **Read/Write Leveling & Eye Margining:** Complete command/address, write-leveling, DQS gate, and per-bit read/write data-eye training; retain per-channel/per-lane eye width & height shmoo logs.
- [ ] **Boundary & Stress Patterns:** Run walking-1/0, PRBS, March, and bank/channel boundary checks across the **entire usable device address aperture** (including first/last words of every bank/pseudo-channel and reserved-range guards), verifying ECC single-bit/double-bit counters remain zero (or match fault-injection test).

### Stage 4 — PCIe Host Enumeration & Register/BAR Sanity

- [ ] **Link Training (LTSSM):** Verify PCIe link training to expected generation/width (`L0` state), lane polarity/reversal handling, and Receiver/Transmitter equalization logs (`lspci -vvv` / protocol analyzer).
- [ ] **Host Enumeration & BAR Mapping:** Confirm Vendor/Device ID, BAR0/BAR2 aperture sizes, MSI-X capability, and clean host MMIO read/write to Vortex DCR/command-processor status registers without AER (`Uncorrectable`/`Correctable`) errors.
- [ ] **Link Stability Check:** Exercise hot-reset, secondary bus reset, and link retrain across multiple host boot cycles.

### Stage 5 — Host↔Device DMA, Memory Boundaries & Isolation

- [ ] **DMA Round-Trips (`H2D` / `D2H`):** Exercise aligned and edge-length DMA transfers (`4 B` up to multi-MiB bursts) across all usable memory channels with bit-exact host verification.
- [ ] **Address Boundaries & Canary Guards:** Verify allocation bounds, non-overlapping buffer checks, adjacent canary-word preservation, and explicit error propagation on malformed/out-of-bounds descriptors (`P08` fault classes carried into silicon).
- [ ] **Cache Coherence & Fence Ordering:** Verify command-processor DMA ↔ L2 LLC ↔ core L1 D-cache visibility, write-back flush/invalidation boundaries, and outstanding-request drain under concurrent core and DMA traffic.

### Stage 6 — Native Core Execution, Tensor Arithmetic & Error Recovery

- [ ] **Scalar & Control Sanity:** Run `demo`, `reopen`, `vecadd`, and RV64 integer/FP (`STD` FPU) diagnostics; verify kernel launch, completion interrupt/polling, and zero leftover state across repeated open/close cycles.
- [ ] **Native Tensor Datapath (`TFR` FP16/BF16→FP32):** Run P02 exact boundary/cancellation/layout vectors and `sgemm_tcu` against frozen integer/CPU bit-exact references. Verify unsupported formats/shapes fail explicitly without silent CPU fallback.
- [ ] **Operator & Multi-Warp Stress (`P03` Suite):** Run matmul, reductions, softmax, normalization, activations, and attention kernels across single-core and multi-core/L2 configurations (`2–4` cores if scaled).
- [ ] **Fault & Reset Recovery:** Inject controlled timeouts, malformed arguments, and device reset/re-init sequences; verify clean recovery and bit-exact execution of a subsequent healthy workload.

---

## 3. Frozen Model Suite & Silicon Characterization (`P11-A03`)

All `P11-A03` claims must derive strictly from `silicon_measured` runs on identified packaged devices; never blend simulated cycles, synthesis estimates, or FPGA results into silicon tables.

### 3.1 Frozen Workload Matrix

| Workload ID | Contract / Fixture | Required Verification on Silicon |
|---|---|---|
| `SIL-W01` | [`p02_tensor_contract.json`](../../ci/project/p02_tensor_contract.json) | Bit-exact match against frozen `TFR` FP16/BF16→FP32 edge, cancellation, and layout vectors |
| `SIL-W02` | [`ai_operator_contract_v1.md`](../designs/ai_operator_contract_v1.md) | P03 operator suite with device dispatch traces and explicit transfer accounting |
| `SIL-W03` | [`tiny_mlp_fixture_v1.md`](../designs/tiny_mlp_fixture_v1.md) | End-to-end `p04-tiny-mlp-v1` (all 10 cases, raw-word equality at `H`, `R`, and `Y` boundaries) |
| `SIL-W04` | [`benchmarks.md`](benchmarks.md) (`B1`–`B4` frozen suite) | Warm-up + repeated samples (`N >= 5` or declared count) separating kernel-only, H2D/D2H DMA, and E2E latency |

### 3.2 Honest Frequency, Power, Thermal, Capacity & Yield Reporting Template

Record `unavailable` explicitly for any unmeasured sensor or uncharacterized corner; never report peak theoretical TOPS as sustained model throughput.

#### A. Operating Envelope & Shmoo Summary

| Operating Point | Core Clock (MHz) | VDD_CORE (V) | Mem Clock / Rate | Usable Memory Capacity | Temp Range (°C) | Pass / Fail (Sample Count) | Notes / Limiting Path |
|---|---|---|---|---|---|---|---|
| Nominal (`TBD`) | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run (0 samples)` | Template entry |
| Min-VDD / Fmax Corner | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run (0 samples)` | Template entry |
| Sustained Thermal Soak | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run (0 samples)` | Template entry |

#### B. Measured Performance & Power Telemetry (Per Workload)

| Workload | Precision | Device Kernel Time (us, median / range) | H2D+D2H DMA Time (us) | Sustained Useful GFLOP/s (2·M·N·K / time) | Board Power (W) & Instrument | Core Rail Power (W) | Energy / Inference (mJ) | Reference Match |
|---|---|---|---|---|---|---|---|---|
| `SIL-W03` (`p04-tiny-mlp-v1`) | FP16 / BF16 → FP32 | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` |
| `SIL-W04` (`B1` GEMM) | FP16 / BF16 → FP32 | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` | `not_run` |

#### C. Sample Count, Yield & Failure-Analysis Disposition

| Metric | Value (Exact Observed Counts Only) | Scope / Limitation |
|---|---|---|
| Packaged Samples Received | `0` (`not_run`) | First-silicon engineering sample count is not production volume |
| ATE Known-Good / Functional Pass Count | `0 / 0` (`not_run`) | State exact test temperature/voltage/frequency bin |
| Bench Bring-Up Pass (`P11-A02` / `P11-A03`) | `0 / 0` (`not_run`) | State die-to-die Fmax/leakage spread honestly |
| Observed Hardware Errata / Failure Modes | `none_observed (not_run)` | Link failure-analysis (FA) / FIB / respin tickets if triggered |
| Silicon Release Scope Decision (`P11-A03`) | `UNDECIDED / NOT RELEASED` | Requires human maintainer sign-off under [`releases.md`](releases.md) |
