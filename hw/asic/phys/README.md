# AI-GPU Open-Source RTL-to-GDSII Physical Design (`hw/asic/phys/`)

Reproducible open-source ASIC synthesis, static timing/power analysis, OpenROAD place-and-route, OpenRCX parasitic extraction, and KLayout GDSII streamout flow for AI-GPU SoC/DFT collateral and Tensor Core Unit (TFR) datapath macros.

> **Commercial Foundry Sign-Off Boundary (`foundry_signoff: false`):**
> All numbers and layouts in this directory are **real measured open-source EDA outputs** (`Yosys 0.69`, `OpenSTA 3.1.0`, `OpenROAD ORFS`, `KLayout`) targeting open academic process design kits (**ASAP7 7nm RVT NLDM** and **Nangate45 45nm typical**) and ORFS's `fakeram7_256x32` SRAM blackbox macro view. They establish physical feasibility, standard-cell density, PDN rail closure, CTS/routing closure, DRC cleanliness within TritonRoute, and post-route OpenRCX timing/power trends; they do **not** constitute commercial foundry PDK sign-off, commercial DRC/LVS closure, compiled foundry SRAM characterization, or tape-out readiness.

---

## 1. Deliverables & Reproducibility

| File | Purpose |
|---|---|
| [run_phys_flow.py](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/run_phys_flow.py) | Master Python driver: generates resolved hardware config (`VX_config.vh`/`VX_types.vh`), synthesizes all target designs in Yosys 0.69 (`read_slang` + bounded ABC), runs OpenSTA 3.1.0 timing/power, executes OpenROAD PnR + PDN + OpenRCX + KLayout GDSII in `openroad/orfs:latest`, and emits `phys_results.json`. |
| [asap7_synth_sta.tcl](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/asap7_synth_sta.tcl) | Parameterized OpenSTA 3.1.0 script (`TOP`, `NETLIST`, `LIB_FILES`, `SDC_FILE`, `SPEF_FILE`, `TARGET_PERIOD_NS`) computing setup/hold `wns`/`tns`/`worst_slack`, `report_clock_min_period -include_port_paths`, critical paths per clock group, and `report_power`. |
| [openroad_pnr.tcl](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/openroad_pnr.tcl) | Parameterized OpenROAD PnR recipe (`PDK=asap7|nangate45`): LEF/Liberty/SDC load, optional `fakeram7_256x32` macro floorplan (`place_macro` + `cut_rows` + PDN macro grid), `tapcell`, `pdngen`, `place_pins`, `repair_tie_fanout`, `global_placement`, `detailed_placement`, CTS, `repair_design` + `repair_timing` (setup & hold), `global_route`, `detailed_route` DRC, `filler_placement`, OpenRCX SPEF extraction, post-route STA/power, DEF/Verilog export. |
| [phys_results.json](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/phys_results.json) | Machine-readable physical proof record (`foundry_signoff: false`) capturing tool versions, SHA-256 checksums, gate/FF/instance counts, areas, slacks, Fmax, power, wirelengths, via counts, PDN routed segments, DRC counts, and external `.def`/`.spef`/`.gds` paths. |
| [README.md](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/README.md) | This physical design summary & reproducibility guide. |

### Binary Artifact Storage Policy
Large binary layout artifacts (`.gds`, `.def`, `.spef`, logs) are stored out-of-tree under `/home/antigravity/vortex_builds/phys_out/` (`synth/`, `sta/`, `pnr/`, `gds/`), while exact byte sizes, KLayout cell/layer/die checks, and SHA-256 digests are retained in [phys_results.json](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/phys_results.json).

### Verified Toolchain Provenance
- **Git Revision:** `0775c9a2b2d0ed79e9132dba8466ca5453fc74d8` (generated `2026-11-26T23:08:01Z`)
- **Yosys:** `Yosys 0.69 (git sha1 9f75ca1f9, Release, GNU /usr/bin/c++ 11.4.0)` via `/home/antigravity/tools/yosys/bin/yosys` (`read_slang` SV frontend + bounded ABC fanout-32 script + singleton `hilomap` tie mapping + `insbuf`)
- **OpenSTA:** `3.1.0` via `/home/antigravity/tools/sta/bin/sta`
- **OpenROAD + KLayout:** Docker `openroad/orfs:latest` (`sha256:b7be8a1b7be792eface91b4df4a737bee93ec15136a77a03ed0bdf1416905510`, `/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad`, `klayout.db 0.30.13`)
- **Libraries:**
  - ASAP7 7nm RVT TT NLDM (`/home/antigravity/vortex_builds/build32_asic_gate/hw/syn/libs/asap7/lib/asap7_rvt_tt.lib` for Yosys/OpenSTA; ORFS ASAP7 split TT NLDM libs, LEFs, `asap7sc7p5t_28_R_220121a.gds`, `fakeram7_256x32.{lef,lib}`, `rcx_patterns.rules`, `asap7.lyt`)
  - Nangate45 45nm typical (`hw/syn/libs/NangateOpenCellLibrary_typical.lib`; ORFS Nangate45 LEFs, `NangateOpenCellLibrary.gds`, `rcx_patterns.rules`, `FreePDK45.lyt`)

To reproduce the full synthesis + STA + PnR + GDSII flow from the repository root:
```bash
python3 -B hw/asic/phys/run_phys_flow.py --clean
```
(Or stage cleanly inside a 600s shell budget via `--clean --only-synth`, `--only-macro-pnr` / `--only-pnr-id <id>`, and `--only-soc-pnr`.)

---

## 2. Real Yosys 0.69 Synthesis & OpenSTA 3.1.0 Post-Synthesis Results

All synthesis runs use Yosys `read_slang` elaboration, `dfflibmap`, bounded `abc` (`buffer -N 32; upsize; dnsize`), singleton `hilomap`, and `insbuf`. Power figures are OpenSTA static estimates at typical corner (`0.70 V` for ASAP7 / `1.10 V` for Nangate45, `25 C`) with default 0.1 toggle activity and 0.5 duty cycle.

| Design / Variant | PDK | Std Cells + Macro | Flip-Flops | Std-Cell Area (µm²) | Total Area w/ SRAM (µm²) | Worst Setup Slack (ns) | Setup WNS (ns) | Achieved Fmax (MHz) | Total Power (mW) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `VX_asic_dft_top` | ASAP7 7nm | 495 | 100 | 68.861 | 68.861 | +4.3819 (`tck`) | 0.0000 | 177.83 (`tck` @ 50 MHz SDC) | 0.024183 |
| `VX_asic_dft_top` | Nangate45 | 518 | 100 | 1,008.672 | 1,008.672 | +4.3615 (`tck`) | 0.0000 | 175.05 (`tck` @ 50 MHz SDC) | 0.18644 |
| `VX_asic_soc_top` (`ASIC_SRAM_MACROS` + `fakeram7_256x32`) | ASAP7 7nm | 10,631 + 1 SRAM | 2,076 | 1,327.611 | 1,671.596 | -1.2070 *(raw pre-CTS reset fanout)* / +0.0136 *(datapath)* | -1.2070 *(raw)* / 0.0000 *(datapath)* | `clk_core` **2,055.81** / `clk_axi` **1,263.29** / `tck` 177.51 *(datapath)* | 6.6877 |
| `VX_asic_soc_top` (behavioral all-FF boot SRAM) | ASAP7 7nm | 49,797 | 10,300 | 5,950.448 | 5,950.448 | -1.5397 *(raw pre-CTS reset fanout)* | -1.5397 *(raw)* | `clk_core` 666.52 / `clk_axi` 393.75 / `tck` 177.81 *(raw)* | 16.783 |
| `VX_tcu_fedp_tfr` (`NT=4`, FP16/BF16, `LATENCY=4`) | ASAP7 7nm | 8,031 | 416 | 793.516 | 793.516 | +0.0670 (1.0 GHz) | 0.0000 | **1,071.83** | 1.4859 |
| `VX_tcu_fedp_tfr` (`NT=4`, FP16/BF16, `LATENCY=5`) | ASAP7 7nm | 8,564 | 594 | 871.534 | 871.534 | +0.0653 (1.0 GHz) | 0.0000 | **1,069.81** | 1.8102 |
| `VX_tcu_fedp_tfr` (`NT=4`, FP16/BF16, `LATENCY=4`) | Nangate45 | 8,739 | 416 | 12,187.854 | 12,187.854 | +0.6658 (500 MHz) | 0.0000 | **749.52** | 7.1048 |
| `VX_tcu_tfr_mul_f16` (`PROD_REG=1`, FP16/BF16/TF32) | ASAP7 7nm | 3,207 | 93 | 327.715 | 327.715 | +0.2141 (1.0 GHz) | 0.0000 | **1,272.44** | 0.20835 |

### Diagnostic Notes on Post-Synthesis STA
- **SoC Raw Pre-CTS Reset Fanout vs. Synchronous Datapath Timing:** Pre-CTS Yosys netlists route the unbuffered 2-FF synchronizer nets (`rst_core_sync1_q` and `rst_axi_sync1_q`) through single `INVx1_ASAP7_75t_R` cells, yielding `-0.9344 ns` (`clk_core`) and `-1.1423 ns` (`clk_axi`) pre-CTS recovery slack prior to physical buffering. Isolating those two unbuffered reset nets confirms the synchronous datapath meets `aigpu_b1.sdc` with **WNS = 0.0000 ns / TNS = 0.0000 ns** (`+0.0136 ns` slack at 2.0 GHz `clk_core`, Fmax **2,055.81 MHz**; `+0.2084 ns` slack at 1.0 GHz `clk_axi`, Fmax **1,263.29 MHz**). OpenROAD PnR buffers these reset trees explicitly (`+0.0855 ns` post-route recovery slack on `clk_core`).
- **JTAG `tck` Fmax:** Reported `tck` Fmax (`177.51`–`177.83 MHz` pre-CTS, `173.35`–`173.97 MHz` post-route) is bounded by the `aigpu_b1.sdc` external output delay budget (`5.0 ns` output delay + `0.500 ns` setup uncertainty at `TCK_PERIOD = 20.0 ns`), easily exceeding the 50 MHz JTAG spec (`+4.2246 ns` to `+4.3819 ns` slack).
- **Pre-CTS Hold Note:** Pre-CTS ASAP7 synthesis exhibits small unbuffered min-delay hold slack (`-0.1115 ns` on `tck` due to `0.100 ns` hold uncertainty; `-0.0012 ns` on `VX_tcu_fedp_tfr`); OpenROAD PnR inserts hold buffers (`-hold_margin 0.025`) to achieve positive post-route hold slack across all placed-and-routed designs.

---

## 3. Real OpenROAD Place-and-Route -> PDN -> OpenRCX -> GDSII Results

All 4 PnR targets completed full OpenROAD place-and-route, `pdngen` power-grid generation (routed `VDD`/`VSS` `SPECIALNETS` verified in every `.def`), CTS, setup/hold timing repair, global routing, TritonRoute detailed routing (**0 DRC violations**), filler/decap placement, OpenRCX 3D parasitic `.spef` extraction, post-route STA, and `def2stream.py` KLayout `.gds` generation:

| Design | PDK | Die Size & Area (µm²) | Design Area (µm²) | Core Util (%) | Post-Route Insts (Std+M / Tap / Fill) | PDN Segs | Wirelength (µm) | Vias | DRT DRC | Post-Route Setup WNS / TNS (ns) | Post-Route Min Hold Slack (ns) | Post-Route Fmax (MHz) | Post-Route Power (mW) | External `.gds` Bytes & SHA-256 |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `VX_asic_dft_top` | ASAP7 7nm | `15.526 x 15.526` (`241.06`) | 110.0 | 62.0% | 1,060 / 98 / 1,529 | 780 | 2,186 | 7,279 | **0** | **0.0000 / 0.0000** | **+0.0264** | 173.94 (`tck`) | 0.019938 | `1,046,438 B` (`5860b695...dfd84de`) |
| `VX_asic_dft_top` | Nangate45 | `58.215 x 58.215` (`3,388.99`) | 1,122.0 | 46.0% | 603 / 70 / 1,110 | 162 | 6,691 | 4,156 | **0** | **0.0000 / 0.0000** | **+0.0259** | 173.35 (`tck`) | 0.14853 | `598,488 B` (`2d0693d1...b22fbeb`) |
| `VX_tcu_tfr_mul_f16` (`PROD_REG=1`) | ASAP7 7nm | `30.636 x 30.636` (`938.56`) | 348.0 | 43.0% | 3,379 / 263 / 5,843 | 2,958 | 12,932 | 30,684 | **0** | **0.0000 / 0.0000** | **+0.0294** | **1,079.53** (`clk`) | 0.25077 | `3,137,082 B` (`1b5b188b...f953eda`) |
| `VX_asic_soc_top` (`fakeram7_256x32`) | ASAP7 7nm | `80.000 x 80.000` (`6,400.00`) | 2,131.0 | 37.0% | 16,403 / 1,242 / 32,176 | 16,866 | 64,317 | 129,741 | **0** | `-0.0085 / -0.0288` | **+0.0242** | `clk_core` **1,966.66** / `clk_axi` **1,061.01** / `tck` 173.97 | 8.8805 | `12,662,474 B` (`327d8145...ca5246a`) |

### `VX_asic_soc_top` Physical & Post-Route Observations
- **Hard SRAM Macro Floorplan & PDN:** Placed 1 `fakeram7_256x32` macro (`8.360 x 42.000 µm`) at `(8.0, 18.0)` with `2.0 µm` macro row-cutting halo (`cut_rows`), ASAP7 M4/M5 macro power grid stripes + M1/M2/M5/M6 standard-cell PDN grid (`16,866` routed `SPECIALNETS` segments across `VDD`/`VSS`), `1,242` `TAPCELL` instances, `16,402` standard cells (+1 SRAM macro = `16,403`), and `32,176` `FILLER`/`DECAP` cells inside a `5,739.85 µm²` core (`80.0 x 80.0 µm` die, 37% macro+cell utilization).
- **Zero DRT Violations & Parasitic-Extracted Performance:** TritonRoute finished cleanly with **0 DRC violations** across M2–M6 (`64,317 µm` total routed wirelength, `129,741` vias) and KLayout verified `103` cells / `34` layers in `VX_asic_soc_top_asap7.gds` (`12,662,474 B`, empty `fakeram7_256x32` outline allowed per `GDS_ALLOW_EMPTY=fakeram.*` since ORFS supplies LEF/Liberty only for FakeRAM).
- **Post-Route Timing Detail:** Under full post-route propagated clocks and OpenRCX SPEF parasitics at the aggressive `0.500 ns` (2.0 GHz) `clk_core` target (`-0.030 ns` setup uncertainty), `clk_axi` (`1.000 ns`) closes at **+0.0575 ns slack (1,061.01 MHz)**, `tck` (`20.0 ns`) closes at **+4.2531 ns slack (173.97 MHz)**, hold closes across all clocks (**+0.0242 ns** worst hold slack), async reset recovery (`rst_core_sync1_q`) closes at **+0.0855 ns**, and `clk_core` achieves **1,966.66 MHz** (`0.5085 ns` critical path, `-0.0085 ns` WNS on `_19445_ -> _19396_`, `-0.0288 ns` TNS at 2.0 GHz — closing with positive slack up to 1.96 GHz on ASAP7 RVT TT).

---

## 4. Verification Commands Run
```bash
python3 -m json.tool hw/asic/phys/phys_results.json > /dev/null
python3 ci/project/check_project.py
```
Both exited `0`.
