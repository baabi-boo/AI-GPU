# P07 — Alveo U55C / V80 Physical FPGA Readiness & Execution Plan

> [!IMPORTANT]
> **Status: Proposed preparatory package (`source_present` only).**
> This document records a candidate `ODR-004` board proposal, pre-implementation
> Beacon synthesis resource comparisons, and the physical execution contract for
> P07. **P07 remains `not_started` in [roadmap.json](roadmap.json) until
> P01-A03 (`hw_emu`) passes, P04 and P06 prerequisites are complete, `ODR-004` is
> formally approved by the project owner, and actual physical FPGA hardware is
> measured and independently reviewed.**

## 1. Proposed target board record (`ODR-004` proposal — NOT approved/measured)

Under [decisions.md](decisions.md#open-decisions), `ODR-004` requires selecting
one supported, obtainable physical FPGA board, host platform, shell/firmware
stack, and tool/license entitlement before physical qualification. The proposed
selection (currently **unapproved and unmeasured**) is:

| Role | Proposed Board | Part / Family | Memory & Host Interface | Flow & Descriptor |
|---|---|---|---|---|
| **Primary** | AMD/Xilinx Alveo U55C | `xcu55c-fsvh2892-2L-e` (`virtexuplusHBM`) | 16 GiB HBM2 (32 × 512 MiB pseudo-channels, `HBM[0:31]`, 34-bit addr), PCIe Gen3x16 / Gen4x8, `HOST[0]` XDMA slave bridge | XRT (`TARGET=hw`, `platform: xilinx_u55c_gen3x16_xdma_3_202210_1`), [u55c.toml](../../hw/syn/xilinx/platforms/u55c.toml) |
| **Secondary** | AMD/Xilinx Alveo V80 | `xcv80-lsva4737-2MHP-e-S` (`versal`) | HBM2e (`MEM` 32 GiB VNOC window at `0x40_0000_0000`, `HBM8` host staging; QDMA `HOST` bridge refused) | SLASH / AVED compute shell (`TARGET=hw`), [v80.toml](../../hw/syn/xilinx/platforms/v80.toml), [SLASH setup](../xilinx_slash_setup.md) |

### Scope and non-approvals

- This `ODR-004` proposal **does not** authorize hardware procurement, paid
  cloud FPGA rental, or commercial Vivado/Vitis license acquisition.
- Alveo U55C is proposed as primary because the inherited [XRT Makefile](../../hw/syn/xilinx/xrt/Makefile)
  and [AFU shell](../designs/fpga_afu_shell.md) already target XRT `v++` linking
  across `HBM[0:31]` and `HOST[0]`, whereas the V80 secondary path requires the
  external SLASH/AVED stack and host-staging workarounds.
- Listing `u55c.toml` or `v80.toml` is a configuration definition (`source_present`),
  **not** proof of host access, valid shell flashing, timing closure, or usable
  memory bandwidth.

## 2. Alveo U55C resource budget vs. Beacon synthesis measurements

The table below compares the Xilinx Alveo U55C (`xcu55c-fsvh2892-2L-e`) device
capacity against local RV64 Beacon synthesis runs measured at commit `1cf68ff`
(`16T/16W`, `SOCKET_SIZE=2`, `USE_DSP=0`, `VX_CFG_TCU_MX_ENABLE`,
`VX_CFG_PLATFORM_MEMORY_NUM_BANKS=1`).

| Configuration / Target | LUT | FF | BRAM (36K) | URAM | DSP | Max Logic Levels | Evidence Scope |
|---|---|---|---|---|---|---|---|
| **Alveo U55C Capacity (`xcu55c-fsvh2892-2L-e`)** | `1,303,680` | `2,607,360` | `2,016` | `960` | `9,024` | — | Device datasheet capacity |
| **`p02-tfr` 1-core RV64** ([profile](../../profiles/p02-tfr.json)) | `132,962` (`10.2%`) | `89,432` (`3.4%`) | `20.0` (`1.0%`) | `0` (`0.0%`) | `33` (`0.37%`) | `24` | Local RV64 Beacon run at `1cf68ff` (core/unit only) |
| **`VX_tensor_top` 2-core + 256 KiB L2 + WGMMA + DXA RV64** | `367,926` (`28.2%`) | `197,220` (`7.6%`) | `132.5` (`6.6%`) | `0` (`0.0%`) | `11` (`0.12%`) | `25` | Local RV64 Beacon run at `1cf68ff` (`16T/16W`, `SOCKET_SIZE=2`, `USE_DSP=0`, `TCU_MX_ENABLE`, `PLATFORM_MEMORY_NUM_BANKS=1`) |

### Resource interpretation boundaries

1. **Local RV64 Beacon runs vs. checked-in `XLEN=32` baselines.** The rows above
   come from local `XLEN=64` Beacon runs at commit `1cf68ff` with explicit flags
   (`USE_DSP=0`, `16T/16W`, `SOCKET_SIZE=2`, `TCU_MX_ENABLE`,
   `PLATFORM_MEMORY_NUM_BANKS=1`), **not** from the checked-in `XLEN=32`
   synthesis baselines under [ci/baselines/synthesis/beacon/](../../ci/baselines/synthesis/beacon/).
   (`p02-tfr` uses `4T/4W` and `USE_DSP=0`; `VX_tensor_top` uses `16T/16W`,
   `SOCKET_SIZE=2`, `USE_DSP=0`, `TCU_MX_ENABLE`, and
   `PLATFORM_MEMORY_NUM_BANKS=1`.)
2. **Beacon estimates exclude the XRT shell and physical routing.** Beacon runs
   logic/area estimation on isolated RTL DUTs (`p02-tfr` 1-core RV64 and
   `VX_tensor_top` 2-core + 256 KiB L2 + WGMMA + DXA RV64). It **does not**
   include the Alveo U55C dynamic/static shell, HBM AXI crossbar/interconnect,
   XDMA host bridge, or [VX_afu_wrap](../designs/fpga_afu_shell.md) overhead.
3. **Routing, SLR crossings, and achieved clock require full `v++` `TARGET=hw`.**
   The U55C has three SLRs and HBM pseudo-channels anchored to SLR0; multi-core
   builds may require SLR floorplanning (`VORTEX_SLR`) or `KERNEL_FREQ` tuning
   in [hw/syn/xilinx/xrt/Makefile](../../hw/syn/xilinx/xrt/Makefile).
4. **Frequency downscaling is enabled by default.** `FREQ_SCALING ?= 1` allows
   Vivado/Vitis to scale down the kernel clock from 300 MHz if timing is not
   met. Sign-off builds must inspect `_new_clk_freq` and routed timing reports
   via `xilinx_check_kernel_clock.py` (or build with `FREQ_SCALING=0`) and
   record the **actual achieved clock**.
5. **No `fpga_measured` claim from synthesis.** Beacon numbers are
   pre-implementation estimates; they establish feasibility headroom (`~10.2%`
   to `~28.2%` LUT) only and never satisfy `P07-A01`, `P07-A02`, or `P07-A03`.

## 3. P07-A01 / P07-A02 / P07-A03 physical execution checklist

Use the turnkey harness [ci/project/p07_fpga_harness.py](../../ci/project/p07_fpga_harness.py)
(verified offline by [ci/project/test_p07_fpga_harness.py](../../ci/project/test_p07_fpga_harness.py))
to enforce preflight checks, generate deterministic run plans, and validate
1-hour soak telemetry.

### P07-A01 — Readiness and pinned implementation (`source_present`)

- [ ] **Prerequisite gates:** Confirm `P01` is `complete` (including vendor XRT
  `hw_emu` `P01-A03`), `P04` is `complete`, and `P06` is `complete`.
- [ ] **Approve `ODR-004`:** Record formal board/host access approval, Vitis /
  Vivado / XRT versions, license entitlement, and U55C shell/firmware version in
  [decisions.md](decisions.md).
- [ ] **Enable U55C host-memory bridge:** On the authorized host, enable the
  XRT slave bridge once per card (requires root; see [FPGA setup](../fpga_setup.md)):
  ```bash
  sudo bash -c 'source /opt/xilinx/xrt/setup.sh && \
    xrt-smi configure --host-mem -d <BDF> --size 1G enable'
  ```
- [ ] **Build `TARGET=hw` bitstream:** Build from a clean, committed source tree
  using [hw/syn/xilinx/xrt/Makefile](../../hw/syn/xilinx/xrt/Makefile) with
  `TARGET=hw` and the frozen RV64 configuration. Preserve `vivado.log`,
  utilization reports, `impl_1_hw_bb_locked_timing_summary_routed.rpt`,
  `_new_clk_freq`, and the SHA-256 of `vortex_afu.xclbin`.
- [ ] **Verify physical preflight:** Run:
  ```bash
  python3 ci/project/p07_fpga_harness.py preflight \
    --target hw --bdf <BDF> --platform <PLATFORM_VBNV> \
    --xclbin <PATH_TO_XCLBIN>
  ```
  Preflight must confirm `xbutil`, `XILINX_XRT`, real physical BDF/platform
  identity, unset `XCL_EMULATION_MODE`, and exact `.xclbin` SHA-256. Any
  `--target hw_emu` or `--target xrtsim` invocation is explicitly rejected for
  `fpga_measured`.

### P07-A02 — Physical board functional, memory, and model execution (`fpga_measured`)

All commands **must** execute from the configured RV64 build tree with
`XCL_EMULATION_MODE` unset, `FPGA_BIN_DIR` pointing to the `TARGET=hw`
bitstream directory, and explicit `--driver=xrt --target=hw` passed to
`./ci/blackbox.sh` (exporting `TARGET=hw` alone is reset by `blackbox.sh` and
falls back to `xrtsim`). Generate the exact plan via:

```bash
python3 ci/project/p07_fpga_harness.py plan \
  --board u55c --bdf <BDF> --platform <PLATFORM_VBNV> \
  --build-dir <BUILD_DIR> --fpga-bin-dir <FPGA_BIN_DIR>
```

- [ ] **Enumeration, reset, and reopen:** Verify `xbutil examine -d <BDF> --format json`,
  `--driver=xrt --target=hw --app=demo`, and `--app=reopen` across repeated
  open/close cycles.
- [ ] **DMA round-trips:** Exercise host-to-device and device-to-host transfers,
  alignment/length edge cases, completion, and allocation/free (`vecadd`,
  `io_addr`, `mstress`).
- [ ] **HBM bank/address boundaries:** Test usable 34-bit HBM2 channel
  boundaries (`32 × 512 MiB`, `HBM[0:31]`), reserved-range protection, and
  compute/DMA cache visibility (`mstress`, `stencil3d`, `fence`).
- [ ] **Native tensor GEMM (`FP16` / `BF16`):** Run `sgemm_tcu` on physical `hw`
  with native TFR arithmetic (FP16-to-FP32 and BF16-to-FP32) against frozen CPU
  references.
- [ ] **Attention:** Run native attention (`flash_attn_tcu_wg` / `flash_attn`)
  on physical `hw` against frozen references.
- [ ] **Tiny-MLP (`P04` model):** Run `ai_mlp` against frozen
  [p04_tiny_mlp_v1](../designs/tiny_mlp_fixture_v1.md) integer/exact
  references on physical `hw` and retain dispatch/transfer logs.

### P07-A03 — One-hour physical soak & telemetry (`fpga_measured`)

- [ ] **Execute 3,600-second soak:** Run the continuous physical workload loop
  for at least `3600` seconds on `--driver=xrt --target=hw`, polling
  `xbutil examine -d <BDF> --format json` throughout the run to record
  timestamped JSONL iteration results and telemetry (temperature °C, power W,
  reset/ECC/PCIe error counters).
- [ ] **Analyze soak strictly:** Validate the JSONL log via:
  ```bash
  python3 ci/project/p07_fpga_harness.py soak-analyze \
    --input <SOAK_TELEMETRY_JSONL> --bdf <BDF>
  ```
  The analyzer fails the run on any duration `< 3600s`, any non-`hw` target
  marker, any numerical mismatch, any DMA/reset/telemetry error, or any
  thermal/power excursion above threshold. Unavailable sensor readings must be
  explicitly recorded as `null` (`unavailable`), never synthesized.

## 4. Hard gate boundary

**P07 remains `not_started`** until:
1. **P01-A03 passes** with genuine vendor XRT `hw_emu` evidence, and **P04**
   and **P06** close their respective `depends_on` obligations in
   [roadmap.json](roadmap.json).
2. **`ODR-004` is formally decided** with authorized physical board/host access
   and pinned platform/toolchain/bitstream provenance (`P07-A01`).
3. **Physical hardware is measured** on the selected board using
   `--driver=xrt --target=hw` (`P07-A02` and `P07-A03`) and independently
   reviewed under [acceptance.md](acceptance.md) and [verification.md](verification.md).

Emulation (`hw_emu`, `xrtsim`), processor RTL simulation (`rtlsim`), functional
simulation (`simx`), Beacon synthesis estimates, and offline Python harness
unit tests **never** qualify as `fpga_measured` evidence.
