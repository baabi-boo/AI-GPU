# AI-GPU Fab-Handoff ASIC RTL Collateral Kit (`hw/asic/`)

Standalone, foundry-portable ASIC handoff collateral for `aigpu-b1` (64 RV64X cores across 4 clusters, 64 MiB L2) and `aigpu-b1-tile` (4 cores, 256 KiB L2).

> **Evidence Boundary:** Files under `hw/asic/` represent `source_present` pre-PDK / pre-signoff ASIC RTL, constraint, and power-intent collateral verified through open-source lint, CIRCT elaboration, Yosys synthesis/elaboration, and OpenSTA constraint checking. They do **not** establish commercial foundry PDK signoff, physical DRC/LVS closure, or tape-out readiness (vendor PDK access and EDA signoff flows remain unacquired / gated).

---

## 1. Collateral Inventory

| Deliverable | Purpose | Key Contract |
|---|---|---|
| `hw/asic/sram/VX_sram_1rw.sv` | Single-port (1RW) synchronous SRAM wrapper | `DEPTH`, `DATAW`, `WRENW`, `BYTE_W`, `HAS_BIST`; `` `ifdef ASIC_SRAM_MACROS `` `VX_sram_1rw_macro` hook; MBIST mux bypass (`bist_en`, `bist_ce`, `bist_we`, `bist_wmask`, `bist_addr`, `bist_wdata`); power pins (`sleep`, `sd`, `ret`); synchronous `$mem_v2` read decoupled from reset/power-down clamping |
| `hw/asic/sram/VX_sram_1r1w.sv` | Two-port (1R+1W) synchronous SRAM wrapper | `WRITE_FIRST` read-during-write forwarding (disabled automatically during `bist_en` when `HAS_BIST != 0`), latch-free local loop indexing, synchronous `$mem_v2` read, MBIST hooks, power pins |
| `hw/asic/sram/VX_sram_2rw.sv` | True dual-port (2RW) synchronous SRAM wrapper | Single synchronous `clk`, independent A/B ports, `ifndef SYNTHESIS` read-write/write-write collision `$warning` monitor, synchronous `$mem_v2` reads, MBIST hooks, power pins |
| `hw/asic/sram/sram_macro_manifest.json` | Memory-compiler cut manifest | Profile-aligned enumeration for `aigpu-b1` and `aigpu-b1-tile` covering Register File (`VX_opc_unit`), I-Cache/D-Cache (`VX_cache_tags`/`VX_cache_data`), Local Memory (`VX_lmem_unit` via `VX_1rw1r_ram`), L2 Cache, TCU metadata (`VX_tcu_meta`), and DXA (`VX_dxa_desc_table`, `VX_dxa_core`); explicitly clarifies RTL `VX_sp_ram`/`VX_dp_ram`/`VX_1rw1r_ram` mapping (`VX_tcu_abuf`/`bbuf` stay `SIZE=1` LUTRAM/flops; `VX_dxa_gmem_req` has no `rsp_buf` BRAM) |
| `hw/asic/constraints/aigpu_b1.sdc` | Multi-clock SDC timing constraints | Parameterized `CORE_PERIOD` (`0.500 ns` / 2.0 GHz), `clk_axi` (`1.000 ns` / 1.0 GHz), `clk_pcie` (`2.000 ns` / 500 MHz), `tck` (`20.00 ns` / 50 MHz), `set_clock_groups -asynchronous`, net-anchored (`get_nets -hierarchical` with hierarchical pin fan-in fallback) CDC skew constraints covering all Gray pointers, FIFOs, `cycle_snap_core_q -> cycle_cnt_axi_q` MCP, and `tck <-> clk_axi` 2-FF syncs; output-scoped static DFT/power false paths |
| `hw/asic/power/aigpu_b1.upf` | IEEE-1801 UPF 2.1 template (`source_present`, **unvalidated by commercial UPF tooling**) | `PD_AON` (`VDD_AON`, boot SRAM retention aligned to `mbist_ret_sync2_q`) + switchable `PD_CLUSTER_0..3` (`VDD_CLUST` / `VDD_CLUST_0..3`), `PSW_CLUSTER_*` header switches, clamp-0 `ISO_CLUST_*_OUT` isolation, `LS_*` level shifters, `RET_*` SRAM retention, and `PST_AIGPU_B1` |
| `hw/asic/dft/VX_asic_dft_top.sv` | IEEE-1149.1 JTAG TAP + DFT/MBIST wrapper | 16-state TAP FSM, 32-bit `IDCODE` (`32'h1A16_B101`), `BYPASS`, `SCAN_CTRL`, `MBIST_CTRL` with internal 2-FF `clk_axi -> tck` synchronizers on `mbist_done`/`mbist_fail`, `PWR_CTRL`, scan-chain bypass flops (`SCAN_CHAINS`), DFT clock-gate override and cluster power/isolation/retention controls |
| `hw/asic/soc/VX_asic_soc_top.sv` | Dual-clock CDC-clean SoC top-level shell | Independent 2-FF reset synchronizers (`clk_axi`, `clk_core`), 2-FF `tck -> clk_axi` synchronizers for `dft_test_mode` and `dft_pwr_clust_*`, AXI4-Lite slave CSR bank + boot SRAM (`SLVERR` on SRAM read/write while `mbist_active=1`, strictly registered `s_axil_arready` with zero `awvalid`/`wvalid` feedthrough), dual Gray-code async CDC FIFOs, toggle-handshake `cycle_cnt_axi_q` MCP snapshot, AXI4-Full HBM master port, embedded `VX_asic_dft_top` (`u_dft`), and hardware-MBIST-tested `VX_sram_1rw` (`u_boot_sram`) |

> **UPF Status Note:** `hw/asic/power/aigpu_b1.upf` is a `source_present` IEEE-1801 UPF 2.1 template authored to match `VX_asic_soc_top` (`mbist_ret_sync2_q`, `pwr_clust_*`) and full-chip cluster naming; it has **not** been compiled or checked by a commercial UPF verification tool (e.g., Synopsys VC LP or Cadence Conformal LP).

---

## 2. SRAM Memory Compiler Cut Summary

Measured totals from `hw/asic/sram/sram_macro_manifest.json` (`python3 -m json.tool` and arithmetic consistency validated against `profiles/aigpu-b1.json`, `profiles/aigpu-b1-tile.json`, and `hw/rtl/`):

| Profile | Cores | Logical SRAM Arrays | Total Bits | Total Bytes | Total MiB |
|---|---:|---:|---:|---:|---:|
| `aigpu-b1-tile` | 4 | 131 | 4,328,896 | 541,112 | 0.516045 MiB |
| `aigpu-b1` | 64 | 8,256 | 841,673,728 | 105,209,216 | 100.335327 MiB |

Notes on exact RTL correspondence in `sram_macro_manifest.json`:
- RTL memory modules instantiate `VX_sp_ram` (maps under `` `ifdef ASIC `` to `VX_sp_ram_asic`, foundry wrapper equivalent `VX_sram_1rw`) and `VX_dp_ram` (maps to `VX_dp_ram_asic`, foundry wrapper equivalent `VX_sram_1r1w`).
- Under `` `ifdef ASIC `` with `ISSUE_WIDTH > 1` (`DUAL=1`), `VX_lmem_unit` implements each logical LMEM bank via `VX_1rw1r_ram` as two write-mirrored `VX_dp_ram` (`VX_sram_1r1w`) copies (physically 32 KiB/core in `aigpu-b1-tile` for 16 KiB logical; 256 KiB/core in `aigpu-b1` for 128 KiB logical).
- `aigpu-b1` L2 totals reflect the chip-wide `64 MiB` (`67,108,864 B`, 16 ways, 64 total banks = 16 banks/cluster across 4 clusters, `VX_CFG_L2_WRITEBACK=0` / `VX_CFG_L2_DIRTYBYTES=0`) specification in `profiles/aigpu-b1.json` (the manifest notes that unmodified `VX_cluster.sv` instantiates `VX_CFG_L2_SIZE`/`VX_CFG_L2_NUM_BANKS` per cluster unless scaled per cluster).

---

## 3. Verified Tool Check Results

All five SystemVerilog modules pass with **exit code 0 and zero lint/synthesis warnings** on the standalone RTL wrappers and **clean `$mem_v2` / `RAMB36E1` synchronous memory inference** across Verilator, CIRCT, and Yosys; the SRAM macro hook path (`-DASIC_SRAM_MACROS`) passes across all three tools, and `aigpu_b1.sdc` is checked in OpenSTA 3.1.0 on both flattened and hierarchical Yosys-synthesized `VX_asic_soc_top` Nangate45 netlists.

### Tool Versions
- **Verilator**: `Verilator 5.050 2026-07-01 rev v5.050` (`/home/antigravity/tools/verilator/bin/verilator`)
- **CIRCT**: `CIRCT 892a65a01` / `slang version 11.0.0+0` (`/home/antigravity/tools/circt/bin/circt-verilog`)
- **Yosys**: `Yosys 0.69` (`/home/antigravity/tools/yosys/bin/yosys`)
- **OpenSTA**: `3.1.0` (`/home/antigravity/tools/sta/bin/sta`)

### Exact Commands & Results

1. **Per-module RTL lint & HW-IR elaboration (`Verilator 5.050`, `CIRCT`)**:
   ```bash
   for f in hw/asic/sram/VX_sram_1rw.sv hw/asic/sram/VX_sram_1r1w.sv hw/asic/sram/VX_sram_2rw.sv hw/asic/dft/VX_asic_dft_top.sv; do
     /home/antigravity/tools/verilator/bin/verilator --lint-only -Wall --language 1800-2012 "$f"
     /home/antigravity/tools/circt/bin/circt-verilog --ir-hw "$f" -o /dev/null
   done
   /home/antigravity/tools/verilator/bin/verilator --lint-only -Wall --language 1800-2012 -GWRITE_FIRST=1 hw/asic/sram/VX_sram_1r1w.sv
   /home/antigravity/tools/circt/bin/circt-verilog --ir-hw -G WRITE_FIRST=1 hw/asic/sram/VX_sram_1r1w.sv -o /dev/null
   ```
   - Result: `VX_sram_1rw`, `VX_sram_1r1w` (`WRITE_FIRST=0` and `WRITE_FIRST=1`), `VX_sram_2rw`, and `VX_asic_dft_top` -> **all runs exit 0** with zero warnings.

2. **Yosys 0.69 Memory Inference & Zero-Latch Verification (`memory -nomap` and `synth_xilinx`)**:
   ```bash
   yosys -p "read_verilog -sv hw/asic/sram/VX_sram_1rw.sv; hierarchy -check -top VX_sram_1rw; proc; opt; memory -nomap; stat"
   yosys -p "read_verilog -sv hw/asic/sram/VX_sram_1r1w.sv; chparam -set WRITE_FIRST 1 VX_sram_1r1w; hierarchy -check -top VX_sram_1r1w; proc; opt; memory -nomap; stat"
   yosys -p "read_verilog -sv hw/asic/sram/VX_sram_2rw.sv; hierarchy -check -top VX_sram_2rw; proc; opt; memory -nomap; stat"
   ```
   - `VX_sram_1rw`: **exit 0**, 34 cells including **1 synchronous `$mem_v2`** (0 latch warnings; `synth_xilinx` maps to `1 RAMB36E1`, eliminating prior LUTRAM/register expansion).
   - `VX_sram_1r1w` (`WRITE_FIRST=1` and `WRITE_FIRST=0`): **exit 0**, **ZERO latch warnings** (`No latch inferred for signal \VX_sram_1r1w.\g_write_first.$fordecl_block$3.fi`), 54 cells including **1 synchronous `$mem_v2`** (`synth_xilinx` maps to `1 RAMB36E1`).
   - `VX_sram_2rw`: **exit 0**, 62 cells including **1 synchronous `$mem_v2`** (0 latch warnings; `synth_xilinx` maps to `1 RAMB36E1`).
   - `VX_asic_dft_top`: **exit 0**, 88 cells, zero latch/lint warnings.

3. **SoC Top-Level Hierarchy (`VX_asic_soc_top`)**:
   ```bash
   /home/antigravity/tools/verilator/bin/verilator --lint-only -Wall --language 1800-2012 --top-module VX_asic_soc_top hw/asic/sram/VX_sram_1rw.sv hw/asic/dft/VX_asic_dft_top.sv hw/asic/soc/VX_asic_soc_top.sv
   /home/antigravity/tools/circt/bin/circt-verilog --ir-hw --top=VX_asic_soc_top hw/asic/sram/VX_sram_1rw.sv hw/asic/dft/VX_asic_dft_top.sv hw/asic/soc/VX_asic_soc_top.sv -o /dev/null
   /home/antigravity/tools/yosys/bin/yosys -p "read_verilog -sv hw/asic/sram/VX_sram_1rw.sv hw/asic/dft/VX_asic_dft_top.sv hw/asic/soc/VX_asic_soc_top.sv; hierarchy -check -top VX_asic_soc_top; proc; opt; memory -nomap; stat"
   ```
   - Result: **all 3 tools exit 0** (`VX_asic_soc_top` hierarchy: 671 cells including `VX_sram_1rw` [34 cells with 1 `$mem_v2`] and `VX_asic_dft_top` [88 cells]; Yosys emits 2 expected informational `Replacing memory \rsp_fifo_mem / \cmd_fifo_mem with list of registers` messages for the 8-entry CDC FIFO register-file arrays).

4. **Foundry Macro Hook Check (`-DASIC_SRAM_MACROS` with blackbox macro stubs)**:
   - Verified `VX_sram_1rw`, `VX_sram_1r1w` (`WRITE_FIRST=0` and `WRITE_FIRST=1`), and `VX_sram_2rw` with `-DASIC_SRAM_MACROS` across Verilator 5.050 (`--lint-only -Wall`), CIRCT (`--ir-hw`), and Yosys 0.69 (`read_verilog -sv -DASIC_SRAM_MACROS ...; hierarchy -check; proc; opt; stat`) -> **all runs exit 0** with zero warnings.

5. **OpenSTA 3.1.0 Multi-Clock SDC Verification (`NangateOpenCellLibrary_typical.lib`, flattened & hierarchical netlists)**:
   - Synthesized `VX_asic_soc_top` (`-DASIC_SRAM_MACROS` + blackbox `VX_sram_1rw_macro`) to `NangateOpenCellLibrary_typical.lib` both with `-flatten` (6,140 leaf cells) and hierarchically without `-flatten` (6,192 leaf cells, preserving `u_dft` and `u_boot_sram`).
   - **What matched in OpenSTA:** Because Yosys replaces RTL instance names with anonymous cell IDs (`_09905_`, etc.) during tech-mapping, `aigpu_b1.sdc` anchors constraints via `(* keep = "true" *)` net names (`get_nets -hierarchical` -> output driver leaf cells, with `get_pins` + `get_fanin -flat -only_cells -startpoints_only` fallback for aliased submodule/output nets). Across **both flattened and hierarchical netlists**, all **22/22** SDC source/destination CDC pairs (`ALL_MATCHED=1`), output-scoped DFT/power false paths, and I/O delays matched non-zero cells, and `check_setup -verbose` reported **zero unconstrained endpoints / warnings**.
   - **OpenSTA vs. Commercial SDC Behavior:** OpenSTA 3.1.0 does not accept PrimeTime's `set_max_delay -datapath_only` option, so `_aigpu_set_cdc_max_delay` falls back cleanly to `set_max_delay -ignore_clock_latency`; additionally, because `set_clock_groups -asynchronous` is asserted, OpenSTA suppresses reporting of asynchronous CDC paths even with `set_max_delay`. In commercial signoff flows (Synopsys PrimeTime / Design Compiler / Cadence Genus), enable `keep_hierarchy` / `dont_touch` preservation on CDC/DFT boundaries so `-datapath_only` takes precedence over `-asynchronous` clock groups as intended.
   - **Observed Nangate45 Timing (`NangateOpenCellLibrary_typical.lib`):** `Nangate45` is an academic 45 nm open cell library; the 2.0 GHz `clk_core` (`0.500 ns`) and 1.0 GHz `clk_axi` (`1.000 ns`) budgets target 4 nm-class (`N4P`) silicon and are intentionally over-constrained on 45 nm gates. On the hierarchical (flattened) Nangate45 netlists, OpenSTA reported overall `wns max -2.52 ns` (`-2.39 ns`), `tns max -4489.13 ns` (`-4178.09 ns`), worst `clk_core` setup slack `-2.00 ns` (`-2.00 ns`), worst `clk_axi` setup slack `-2.52 ns` (`-2.39 ns`), and `tck` (50 MHz) met timing with `+4.38 ns` slack.

6. **JSON & Repository Governance Checks**:
   - `python3 -m json.tool hw/asic/sram/sram_macro_manifest.json > /dev/null` -> **exit 0** (plus manifest arithmetic cross-check: `aigpu-b1-tile` 131 arrays / 4,328,896 bits; `aigpu-b1` 8,256 arrays / 841,673,728 bits).
   - `python3 ci/project/check_project.py` -> **exit 0** (`Project governance validation passed (structure and metadata only; no GPU execution certified).`).
   - `python3 -m unittest discover -s ci/project -p 'test_b1_*.py' -v` -> **exit 0** (`Ran 8 tests ... OK`).
