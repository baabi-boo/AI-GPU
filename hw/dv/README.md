# Silicon-Grade Design Verification (`hw/dv/`)

This directory implements silicon design verification collateral for the AI-GPU project:

1. **Dual-Flow SVA Protocol Checkers ([`hw/dv/sva/`](sva/))** — SystemVerilog 2012 concurrent assertions (`assert property`) for Verilator `--assert` coupled with Yosys-compatible formal immediate assertions (`` `ifdef FORMAL ``):
   - [`VX_axi4_sva.sv`](sva/VX_axi4_sva.sv) (18 concurrent SVA assertions): checks AXI4-Lite & AXI4-Full channel stability (`AWVALID && !AWREADY |=> AWVALID && $stable(...)`, `W`, `B`, `AR`, `R`), burst encoding legality, single-beat `WLAST` consistency (tracking captured `awlen_q` on `aw_fire` in formal mode), channel stall watchdogs, and post-reset `$isunknown` guarantees.
   - [`VX_tcu_handshake_sva.sv`](sva/VX_tcu_handshake_sva.sv) (10 concurrent SVA assertions): checks Vortex TCU/functional-unit request/response valid/ready stability, FIFO-ordered tag/UUID conservation, inflight credit bounds, and completion latency/stall watchdogs.
   - [`VX_cdc_fifo_sva.sv`](sva/VX_cdc_fifo_sva.sv) (12 concurrent SVA assertions): checks Gray-code 1-bit pointer step property (`popcount(g ^ g_prev) <= 1`), `bin2gray`/`gray2bin` equivalence, full/empty flag exactness, zero write-when-full corruption, zero read-when-empty underflow, and cross-domain pointer occupancy conservation.

2. **Open-Source Formal Verification ([`hw/dv/formal/`](formal/))** — Executed via **Yosys 0.69 (`read_slang` / `read_verilog -sv -formal` + `clk2fflogic` + `write_smt2`)**, **`yosys-smtbmc --unroll`**, and **Z3 4.8.12**:
   - [`VX_asic_dft_formal.sv`](formal/VX_asic_dft_formal.sv):
     - **`dft_tap_k_induction`** (`read_slang` + `yosys-smtbmc -s z3 -i -t 4 --unroll`, **PASS**, 5.393s): unbounded temporal induction bound directly to `dut.tap_state_q` and `VX_asic_dft_top` outputs (`tdo_oe_n`, `dft_scan_enable`, `dft_test_mode`, `mbist_run`, `pwr_clust_en`), proving 1-step `dut.tap_state_q` transition equivalence against the IEEE-1149.1 table, 5-cycle `TMS=1` return to `TAP_TEST_LOGIC_RESET` from any 4-bit state of `dut.tap_state_q`, reset/idle functional safety, and `tdo_oe_n` polarity.
     - **`dft_tap_bmc`** (`yosys-smtbmc -s z3 -t 20 --unroll`, **PASS**, 97.708s): full dual-edge BMC directly on `VX_asic_dft_top` proving reachable 5-cycle `TMS=1` reset, `IDCODE` immutability (`32'h1A16_B101` verified bit-serially on `tdo`), and `tdo_oe_n` active strictly in `SHIFT_DR`/`SHIFT_IR`.
   - [`VX_cdc_fifo_formal.sv`](formal/VX_cdc_fifo_formal.sv):
     - **`cdc_fifo_k_induction`** (`yosys-smtbmc -s z3 -i -t 4 --unroll`, **PASS**, 1.036s): temporal induction proving `gray2bin(bin2gray(x)) == x` and `bin2gray(gray2bin(x)) == x` for all `(ADDRW+1)`-bit pointer values, exact 1-bit Hamming distance on consecutive Gray transitions, and full/empty Gray equivalence without aliasing.
     - **`cdc_fifo_bmc`** (`yosys-smtbmc -s z3 -t 12 --unroll`, **PASS**, 57.331s): dual-clock async BMC (`ADDRW=3`, `DATAW=8`) proving the mirrored async Gray-code CDC FIFO architecture (`VX_cdc_fifo_formal` + `VX_cdc_fifo_sva`) under unconstrained `wclk`/`rclk` scheduling with zero violations, exact pointer/occupancy conservation, and bit-exact head data integrity (while `tb_asic_soc` binds `VX_cdc_fifo_sva` directly to `VX_asic_soc_top` via `u_cmd_cdc_sva` and `u_rsp_cdc_sva`).
   - [`run_formal.py`](formal/run_formal.py): orchestrates all 4 formal proofs + SMT-LIBv2 elaboration of [`VX_axi4_sva.sv`](sva/VX_axi4_sva.sv) and [`VX_tcu_handshake_sva.sv`](sva/VX_tcu_handshake_sva.sv).

3. **Verilator `--assert --coverage` Constrained-Random SoC Stress Testbench ([`hw/dv/coverage/`](coverage/))** — Compiled out-of-tree into `/home/antigravity/vortex_builds/dv_cov/` against `VX_asic_soc_top.sv` + `VX_asic_dft_top.sv` + `VX_sram_1rw.sv` + 5 bound SVA monitor instances (`70` active concurrent SVA properties total: `u_axil_sva` and `u_axi_m_sva` bound directly to `VX_asic_soc_top`, `u_cmd_cdc_sva` and `u_rsp_cdc_sva` bound directly to `VX_asic_soc_top`'s Gray-code CDC FIFOs, and `u_tcu_sva` exercising `VX_tcu_handshake_sva` via testbench-driven handshake stimulus on `clk_core` until bound to a full core/TCU RTL bench):
   - [`tb_asic_soc.cpp`](coverage/tb_asic_soc.cpp) & [`run_coverage.sh`](coverage/run_coverage.sh): sweeps JTAG 16-state TAP (including Pause/Exit2 paths, unimplemented IR `0x03`, `IDCODE` `0x1A16_B101`, `BYPASS`, `SCAN_CTRL` scan loopback, `MBIST_CTRL` SRAM BIST pass + sleep/retention fail injection + AXI SRAM `SLVERR` guard, `PWR_CTRL` cluster isolation/retention/power switch toggles), three prime asynchronous `clk_axi`/`clk_core` ratios (`5:3`, `3:11`, `7:11`), constrained-random AXI4-Lite CSR/Boot-SRAM scoreboard (with randomized `AW`/`W` skew, byte `wstrb`, simultaneous `AW+W+AR` SRAM deferral, unmapped aperture `SLVERR`, CDC FIFO overflow sticky fault + soft reset recovery), and AXI4-Full HBM read/write transactions with randomized ready/valid backpressure and injected `SLVERR` fault propagation.

## Verified Results Summary (`hw/dv/dv_results.json`, rev `0775c9a`)

| Check | Engine / Command | Scope | Verdict / Metrics |
|---|---|---|---|
| `VX_axi4_sva` / `VX_tcu_handshake_sva` / `VX_cdc_fifo_sva` lint | `verilator --lint-only --assert -Wall -Wpedantic --language 1800-2012` | All 3 SVA modules + injected negative-control checks | **PASS** (0 warnings; all 3 injected faults caught) |
| `dft_tap_k_induction` | `read_slang` + `yosys-smtbmc -s z3 -i -t 4 --unroll` | Exhaustive 16-state 1-step & 5-cycle `TMS=1` reset + safe idle directly on `dut.tap_state_q` and `VX_asic_dft_top` outputs | **PASS** (depth=4, 5.393s) |
| `dft_tap_bmc` | `yosys-smtbmc -s z3 -t 20 --unroll` | Reachable JTAG TAP + bit-serial `IDCODE` `0x1A16_B101` + functional safety | **PASS** (depth=20, 97.708s) |
| `cdc_fifo_k_induction` | `yosys-smtbmc -s z3 -i -t 4 --unroll` | Universal Gray bijection, 1-bit transitions, full/empty non-aliasing | **PASS** (depth=4, 1.036s) |
| `cdc_fifo_bmc` | `yosys-smtbmc -s z3 -t 12 --unroll` | Mirrored dual-clock Gray-code CDC FIFO under unconstrained `wclk`/`rclk` schedule + `VX_cdc_fifo_sva` + data integrity | **PASS** (depth=12, 57.331s) |
| `tb_asic_soc` (`seed=1511464998`) | `verilator --cc --assert --coverage-line --coverage-toggle` | `37,532` AXI cycles, `36,618` core cycles, `9,431` TCK cycles, `4,307` AXIL RD / `2,210` WR, `717` SRAM RD / `461` WR, `298` CDC pushes + `1` overflow fault, `99` HBM WR / `97` HBM RD + `2` SLVERR injects | **PASS** (`70` active concurrent SVA properties, **0 SVA failures**) |
| ASIC RTL Coverage (`verilator_coverage --annotate`) | `VX_asic_soc_top.sv` + `VX_asic_dft_top.sv` + `VX_sram_1rw.sv` | Isolated ASIC RTL modules under `tb_asic_soc` | **Line: 96.9% (123/127)**, **Toggle: 83.5% (3230/3868)**, **Branch: 89.8% (203/226)** |
| Full Harness Coverage (`verilator_coverage --annotate`) | ASIC RTL + SVA monitor instances + `tb_soc_wrap.sv` | Combined DUT + SVA assertion branches (untriggered `$error` arms count uncovered) | **Line: 68.4% (134/196)**, **Toggle: 78.0% (6269/8034)**, **Branch: 89.3% (250/280)** |

### Per-Module Verilator Coverage Breakdown

| Module | Line Coverage | Toggle Coverage | Branch Coverage |
|---|---|---|---|
| [`VX_asic_soc_top.sv`](../asic/soc/VX_asic_soc_top.sv) | **95.52%** (64/67) | **80.93%** (2554/3156) | **87.04%** (141/162) |
| [`VX_asic_dft_top.sv`](../asic/dft/VX_asic_dft_top.sv) | **98.25%** (56/57) | **89.73%** (262/292) | **95.83%** (46/48) |
| [`VX_sram_1rw.sv`](../asic/sram/VX_sram_1rw.sv) | **100.0%** (3/3) | **98.57%** (414/420) | **100.0%** (16/16) |
| [`VX_axi4_sva.sv`](sva/VX_axi4_sva.sv) | 10.00% (4/40) | 63.07% (1380/2188) | 80.56% (29/36) |
| [`VX_cdc_fifo_sva.sv`](sva/VX_cdc_fifo_sva.sv) | 29.41% (5/17) | 95.68% (155/162) | 100.0% (4/4) |
| [`VX_tcu_handshake_sva.sv`](sva/VX_tcu_handshake_sva.sv) | 16.67% (2/12) | 85.04% (580/682) | 100.0% (14/14) |

*(Note: inside SVA monitor modules, low line coverage reflects untriggered assertion `$error` failure statements because zero protocol violations occurred during clean constrained-random simulation; each monitor's error path was separately verified via injected fault smoke tests.)*

## Reproduce Commands

```bash
# 1. Lint SVA checkers
/home/antigravity/tools/verilator/bin/verilator --lint-only --assert -Wall -Wpedantic --language 1800-2012 hw/dv/sva/VX_axi4_sva.sv
/home/antigravity/tools/verilator/bin/verilator --lint-only --assert -Wall -Wpedantic --language 1800-2012 hw/dv/sva/VX_tcu_handshake_sva.sv
/home/antigravity/tools/verilator/bin/verilator --lint-only --assert -Wall -Wpedantic --language 1800-2012 hw/dv/sva/VX_cdc_fifo_sva.sv

# 2. Run Yosys + yosys-smtbmc + Z3 formal proofs
python3 -B hw/dv/formal/run_formal.py --out-json /home/antigravity/vortex_builds/dv_formal/formal_report_fixed.json

# 3. Compile and run Verilator --assert --coverage stress bench (out-of-tree under /home/antigravity/vortex_builds/dv_cov)
bash hw/dv/coverage/run_coverage.sh

# 4. Validate JSON & project governance checks
python3 -m json.tool hw/dv/dv_results.json > /dev/null
python3 ci/project/check_project.py
```
