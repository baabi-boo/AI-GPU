# AI-GPU B1 Foundry RFQ & Clean-RTL Handoff Package

**Target Profiles:** `aigpu-b1` (64-core datacenter AI-only SoC) and `aigpu-b1-tile` (4-core MPW/shuttle test chip)  
**Evidence Level:** `source_present` (pre-silicon RTL + non-sign-off open-source ASAP7/Nangate45 physical proof)  
**Sign-Off Flags:** `foundry_signoff: false` | `silicon_measured: false` | `clean_ip_verified: true`

> [!IMPORTANT]
> **Commercial Sign-Off & Authority Boundary:**
> This document is a technical Request-for-Quotation (RFQ) and design-house handoff specification derived strictly from verified repository sources. It is **not** commercial foundry PDK sign-off, **not** tape-out readiness certification, **not** vendor pricing, and **not** authorization to execute foundry NDAs, IP licenses, or mask/MPW spend (all external procurement remains gated under [P10](file:///home/antigravity/baabi-boo/AI-GPU/docs/project/phases/p10-asic.md) / [P11](file:///home/antigravity/baabi-boo/AI-GPU/docs/project/phases/p11-silicon.md) and [`p10_feasibility_check.py`](file:///home/antigravity/baabi-boo/AI-GPU/ci/project/p10_feasibility_check.py)).

---

## 1. Executive Scope & Evidence Boundary

AI-GPU B1 is an open-source, RV64X SIMT + native TFR Tensor-Core AI accelerator architecture derived from Vortex, pruned of graphics/raster/texture/ray-tracing blocks (`VX_CFG_EXT_{TEX,RASTER,OM,RTU}_ENABLE = false`). Two hardware configurations are packaged for foundry and ASIC design-house RFQ evaluation:

| Parameter | `aigpu-b1-tile` (MPW / Shuttle Test Chip) | `aigpu-b1` (Full Datacenter SoC Target) | Source Reference |
|---|---|---|---|
| **Role in Program** | 4-core RTL-verifiable compute tile & MPW silicon bring-up vehicle | 64-core datacenter AI-only SoC / chiplet target | [`profiles/aigpu-b1-tile.json`](file:///home/antigravity/baabi-boo/AI-GPU/profiles/aigpu-b1-tile.json), [`profiles/aigpu-b1.json`](file:///home/antigravity/baabi-boo/AI-GPU/profiles/aigpu-b1.json) |
| **ISA / Address Space** | RV64IMAFD + A + Zfhmin (`xlen=64`, 48-bit mem addr) | RV64IMAFD + A + Zacas + Zfhmin + SV39 VM (`xlen=64`, 48-bit mem addr) | [`VX_config.toml`](file:///home/antigravity/baabi-boo/AI-GPU/VX_config.toml) |
| **Compute Topology** | 1 cluster × 1 socket × 4 cores (`8W × 8T`, `ISSUE_WIDTH=2`, `NUM_OPCS=1`) | 4 clusters × 16 1-core sockets = 64 cores (`32W × 32T`, `ISSUE_WIDTH=4`, `NUM_OPCS=2`) | [`sram_macro_manifest.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/sram_macro_manifest.json) |
| **FP32 Lanes / TCU Blocks** | 64 FP32 lanes; 2 TFR TCU blocks/core (8 total) | 8,192 FP32 lanes; 4 TFR TCU blocks/core (256 total, `TCU_PE_RATIO=2`) | [`profiles/aigpu-b1.json`](file:///home/antigravity/baabi-boo/AI-GPU/profiles/aigpu-b1.json) |
| **Tensor Formats & Engines** | Native TFR (FP16/BF16, FP8, FP4/MX/MXFP4/NVFP4, INT8, 2:4 Sparse, WGMMA) + DXA + MUFU | Native TFR (+ TF32) + WGMMA + DXA async 5D tensor DMA + 16-lane MUFU | [`profiles/aigpu-b1.json`](file:///home/antigravity/baabi-boo/AI-GPU/profiles/aigpu-b1.json) |
| **On-Chip SRAM (Manifest)** | 131 logical arrays (218 physical macro cuts), **0.516045 MiB** (`541,112 B`) | 8,256 logical arrays (22,784 physical macro cuts), **100.335327 MiB** (`105,209,216 B`) | [`sram_macro_manifest.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/sram_macro_manifest.json) |
| **Target Clock / Memory** | Modeled baseline: 400 MHz (`VX_config.toml` default); MPW interface TBD (LPDDR5 / QSPI / PCIe) | Target envelope: 2.0 GHz `clk_core` (`0.500 ns`), 1.0 GHz `clk_axi`, HBM3E-class 4 TB/s (64 × 128b @ 3906 MT/s) | [`aigpu_b1.sdc`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/constraints/aigpu_b1.sdc) |

### What Is Proven vs. What Must Be Procured Under P10/P11

1. **Verified Pre-Silicon Collateral (`source_present` / Open-Source EDA Only):**
   - **Clean RTL & ASIC Wrappers:** Synthesizable SystemVerilog RTL across [`hw/rtl/`](file:///home/antigravity/baabi-boo/AI-GPU/hw/rtl), standalone foundry-portable SRAM/DFT/SoC wrappers under [`hw/asic/`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/README.md), and dual-clock SDC/UPF collateral.
   - **Open-Source RTL-to-GDSII Physical Proof ([`hw/asic/phys/phys_results.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/phys/phys_results.json)):** Real Yosys 0.69 (`read_slang`) + OpenSTA 3.1.0 + OpenROAD ORFS (`pdngen` + CTS + TritonRoute + OpenRCX) + KLayout runs (`source_revision: 0775c9a`) on academic ASAP7 7nm RVT and Nangate45 libraries — including `fakeram7_256x32` macro floorplanning + `16,866` PDN segments + `1,966.66 MHz` `clk_core` / `1,061.01 MHz` `clk_axi` post-route Fmax on `VX_asic_soc_top` (`12,662,474 B` GDS), `0` DRT DRC violations across all 4 routed GDSII macros, and `1,071.83 MHz` FEDP / `1,272.44 MHz` post-synth (`1,079.53 MHz` post-route, `348.0 um^2`, `2,958` PDN segs, `3,137,082 B` GDS) Fmax on `VX_tcu_tfr_mul_f16` ASAP7.
   - **Silicon-Grade DV & Formal Proofs ([`hw/dv/dv_results.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/dv/dv_results.json)):** Yosys 0.69 + Z3 4.8.12 `k`-induction (`dft_tap_k_induction` bound directly to `dut.tap_state_q` via `read_slang` with 4/4 DUT mutation negative controls verified) and BMC formal proofs (`source_revision: 0775c9a`, plus `formal-smt2` SVA elaborations with `depth: null`) on `VX_asic_dft_top` (16-state JTAG TAP, `IDCODE=32'h1A16_B101`) and dual-clock Gray-code CDC FIFOs, plus 70 active concurrent SVA monitors (`VX_axi4_sva`, `VX_cdc_fifo_sva`, `VX_tcu_handshake_sva`) passing Verilator constrained-random stress (`37,532` AXI / `36,618` core / `9,431` TCK cycles, 0 SVA failures, 96.9% DUT line coverage).
2. **Unacquired / Out-of-Scope Commercial Dependencies (`ODR-007`, `ODR-008`, P10/P11):**
   - Commercial foundry PDK (DRC/LVS/PEX decks, multi-corner standard-cell libraries, IO/ESD pads).
   - Commercial SRAM compiler views (`.lib`/`.db`/LEF/GDS/CDL/MBIST collars) replacing `VX_sram_*_macro` and `VX_sp_ram_asic`/`VX_dp_ram_asic`.
   - Hardened HBM3E controller + PHY + 2.5D CoWoS-S/R interposer (for `aigpu-b1`) or LPDDR5 PHY (for `aigpu-b1-tile` option), PCIe Gen5/Gen6 Endpoint Controller + PHY, UCIe D2D PHY, PLLs, PVT/droop monitors, eFuse/OTP, and ATE/OSAT packaging.
   - Commercial UPF verification (Synopsys VC LP / Cadence Conformal LP), LEC, MCMM sign-off STA, IR-drop/EM, and physical DRC/LVS closure.

---

## 2. Clean Apache-2.0 IP Provenance Audit

All handoff exports are generated and verified by [`ci/project/export_clean_rtl_handoff.py`](file:///home/antigravity/baabi-boo/AI-GPU/ci/project/export_clean_rtl_handoff.py), which enforces deterministic checksums, excludes vendor/third-party trees, and scans every path and text line against forbidden IP patterns.

### Measured Dry-Run Audit Results

Command executed: `python3 ci/project/export_clean_rtl_handoff.py --dry-run --json`

| Audit Metric | Measured Value | Notes |
|---|---:|---|
| **`clean_ip_verified`** | `true` | `0` forbidden path, extension, content, or license violations |
| **`foundry_signoff` / `silicon_measured`** | `false` / `false` | Preserved in every `handoff_manifest.json` |
| **Total Exported Files** | **443** | `4,572,345` bytes (`110,261` total lines) |
| **Exported RTL Files (`.sv`, `.v`, `.vh`, `.vi`)** | **424** | **`101,282` RTL lines** (`hw/rtl`: 414 files; `hw/asic`: 5 SV files; `hw/dv`: 5 SV files) |
| **Tree Breakdown** | `hw/rtl`: 414, `hw/asic`: 14, `hw/dv`: 10, `profiles`: 2, root configs/license: 3 | `hw/rtl/.DS_Store` stripped (`excluded_cache_count = 1`) |
| **License Classification** | 440 Apache-2.0 + 3 permissive BSD-3-Clause | `Apache-2.0` (423), `Apache-2.0 (repo-collateral)` (13), `Apache-2.0 (implicit-repo)` (4), `BSD-3-Clause (permissive)` (3: `HardFloat_consts.vi`, `HardFloat_localFuncs.vi`, `local_mem_cfg_pkg.sv`) |
| **SRAM Manifest SHA-256** | `d9ff8a9e0ba0968187e9b3f53738b68866f3464e17ff55753c347fc7611d9e2d` | Verified against [`hw/asic/sram/sram_macro_manifest.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/sram_macro_manifest.json) |

### Strictly Excluded Repository Trees & Forbidden Patterns

The exporter **strictly excludes** all non-handoff, third-party, vendor-encrypted, and restricted directories and fails closed (`exit 1`) if any matching artifact enters the clean export scope:

| Excluded Tree / Pattern | File Count in Repo | Reason for Exclusion |
|---|---:|---|
| `third_party/` | 2,778 | Contains Ramulator2 + Micron DDR4 proprietary verification sources (`MICRON TECHNOLOGY, INC. - CONFIDENTIAL AND PROPRIETARY`), SoftFloat, HardFloat, CVFPU, and CocoGfx |
| `hw/syn/libs/cln28hpc/` & `hw/syn/libs/cln28hpm/` | 53 + 139 | Unlicensed/restricted commercial 28nm library & hard-macro collateral (`micron` geometry files, `.db`/`.lib`/`.lef`) |
| `hw/syn/xilinx/` & `hw/syn/altera/` | 47 + 20 | FPGA-vendor Vivado/XRT and Quartus synthesis flows |
| `hw/scripts/` | 29 | FPGA flow scripts and Xilinx IP stubs (`xilinx_ip_gen.tcl`, `xilinx_ip_stubs.sv`, etc.) |
| `build*/` & `.git/` | — (556 in `.git`) | Build outputs, compiled artifacts, and VCS history |
| Forbidden Extensions / Markers | — | `.xci`, `.dcp`, `.bit`, `.xclbin`, `.xcix`, `.vp`, `.svp`, `micron`, `ramulator`, IEEE-1735 `` `pragma protect `` / `begin_protected`, and confidential/proprietary/NDA banners |

---

## 3. Complete SRAM Macro Compiler Cut Table

All SRAM figures below are sourced directly from [`hw/asic/sram/sram_macro_manifest.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/sram_macro_manifest.json). Under `` `ifdef ASIC ``, RTL `VX_sp_ram` maps to `VX_sp_ram_asic` ([`VX_sram_1rw.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/VX_sram_1rw.sv)), `VX_dp_ram` maps to `VX_dp_ram_asic` ([`VX_sram_1r1w.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/VX_sram_1r1w.sv)), and `VX_1rw1r_ram` (LMEM with `ISSUE_WIDTH > 1`) maps to two write-mirrored `VX_sram_1r1w` instances per logical bank. Small `SIZE=1` / `LUTRAM=1` buffers (`VX_tcu_abuf`, `VX_tcu_bbuf`, cache valid/dirty bitvectors) remain standard-cell flip-flops.

### 3.1 `aigpu-b1-tile` (4-Core MPW Shuttle Profile — 131 Logical Arrays, 218 Physical Macro Cuts, 0.516045 MiB)

| Array ID | Subsystem / RTL Module | Port | Depth × Width | Write Mask (`WRENW × BYTE_W`) | Banks / Scope | Logical Inst | Physical Macro Cut Spec | Physical Cuts | Total KiB | Total MiB |
|---|---|---|---:|---|---|---:|---|---:|---:|---:|
| `rf_gpr_bank` | Register File (`VX_opc_unit`) | `1r1w` | `64 × 512` | Yes (`64 × 8b`) | 4 / core | 16 | `2x 64x256b_wm1` per bank | 32 | 64.000 | 0.062500 |
| `icache_tag` | I-Cache (`VX_cache_tags`) | `1r1w` | `32 × 144` | Yes (`4 × 36b`) | 2 / socket | 2 | `1x 32x144b_wm1` RF/SRAM | 2 | 1.125 | 0.001099 |
| `icache_data` | I-Cache (`VX_cache_data`) | `1rw` | `128 × 32` | No (`1 × 32b`) | 32 / socket | 32 | `1x 128x32b_wm0` per 32b slice | 32 | 16.000 | 0.015625 |
| `dcache_tag` | D-Cache (`VX_cache_tags`) | `1r1w` | `64 × 144` | Yes (`4 × 36b`) | 1 / socket | 1 | `1x 64x144b_wm1` | 1 | 1.125 | 0.001099 |
| `dcache_data` | D-Cache (`VX_cache_data`) | `1rw` | `256 × 256` | Yes (`32 × 8b`) | 2 / socket | 2 | `2x 256x128b_wm1` per slice | 4 | 16.000 | 0.015625 |
| `lmem_bank` | Local Mem (`VX_lmem_unit`) | `1r1w` | `256 × 64` | Yes (`8 × 8b`) | 16 / core (2×8) | 64 | `2x 256x64b_wm1` write-mirrored | 64 | 128.000 | 0.125000 |
| `l2_tag` | L2 Cache (`VX_cache_tags`) | `1r1w` | `256 × 264` | Yes (`8 × 33b`) | 1 / cluster | 1 | `2x 256x132b_wm1` | 2 | 8.250 | 0.008057 |
| `l2_data` | L2 Cache (`VX_cache_data`) | `1rw` | `2048 × 512` | Yes (`64 × 8b`) | 2 / cluster | 2 | `4x 2048x128b_wm1` per slice | 8 | 256.000 | 0.250000 |
| `l2_dirty_mask` | L2 Cache (`VX_cache_data`) | `1r1w` | `2048 × 128` | No (`1 × 128b`) | 1 / cluster | 1 | `1x 2048x128b_wm0` | 1 | 32.000 | 0.031250 |
| `tcu_meta` | TCU Meta (`VX_tcu_meta`) | `1r1w` | `4 × 1024` | Yes (`32 × 32b`) | 2 / core | 8 | `8x 4x128b_wm1` RF cuts | 64 | 4.000 | 0.003906 |
| `dxa_desc_table` | DXA (`VX_dxa_desc_table`) | `1r1w` | `16 × 768` | Yes (`24 × 32b`) | 1 / socket | 1 | `6x 16x128b_wm1` RF cuts | 6 | 1.500 | 0.001465 |
| `dxa_async_desc_fifo` | DXA (`VX_dxa_core`) | `1r1w` | `16 × 220` | No (`1 × 220b`) | 1 / socket | 1 | `2x 16x110b_wm0` RF cuts | 2 | 0.430 | 0.000420 |
| **Tile Totals** | **7 Subsystems** | — | — | — | **1 cluster, 4 cores** | **131** | *(4,328,896 bits / 541,112 B)* | **218** | **528.430** | **0.516045** |

*(Note: `VX_asic_soc_top` additionally instantiates 1 × `256 × 32b` (`1 KiB`) always-on boot/scratchpad SRAM `u_boot_sram` via `VX_sram_1rw`.)*

### 3.2 `aigpu-b1` (64-Core Datacenter SoC Profile — 8,256 Logical Arrays, 22,784 Physical Macro Cuts, 100.335327 MiB)

| Array ID | Subsystem / RTL Module | Port | Depth × Width | Write Mask (`WRENW × BYTE_W`) | Banks / Scope | Logical Inst | Physical Macro Cut Spec | Physical Cuts | Total KiB | Total MiB |
|---|---|---|---:|---|---|---:|---|---:|---:|---:|
| `rf_gpr_bank` | Register File (`VX_opc_unit`) | `1r1w` | `64 × 2048` | Yes (`256 × 8b`) | 8 / core | 512 | `8x 64x256b_wm1` per bank | 4,096 | 8,192.000 | 8.000000 |
| `icache_tag` | I-Cache (`VX_cache_tags`) | `1r1w` | `16 × 144` | Yes (`4 × 36b`) | 4 / socket | 256 | `1x 16x144b_wm1` RF/SRAM | 256 | 72.000 | 0.070312 |
| `icache_data` | I-Cache (`VX_cache_data`) | `1rw` | `64 × 32` | No (`1 × 32b`) | 64 / socket | 4,096 | `1x 64x32b_wm0` per 32b slice | 4,096 | 1,024.000 | 1.000000 |
| `dcache_tag` | D-Cache (`VX_cache_tags`) | `1r1w` | `128 × 132` | Yes (`4 × 33b`) | 4 / socket | 256 | `1x 128x132b_wm1` | 256 | 528.000 | 0.515625 |
| `dcache_data` | D-Cache (`VX_cache_data`) | `1rw` | `512 × 256` | Yes (`32 × 8b`) | 8 / socket | 512 | `2x 512x128b_wm1` per slice | 1,024 | 8,192.000 | 8.000000 |
| `lmem_bank` | Local Mem (`VX_lmem_unit`) | `1r1w` | `1024 × 64` | Yes (`8 × 8b`) | 32 / core (2×16) | 2,048 | `2x 1024x64b_wm1` write-mirrored | 2,048 | 16,384.000 | 16.000000 |
| `l2_tag` | L2 Cache (`VX_cache_tags`) | `1r1w` | `512 × 416` | Yes (`16 × 26b`) | 16 / cluster | 64 | `4x 512x104b_wm1` per bank | 256 | 1,664.000 | 1.625000 |
| `l2_data` | L2 Cache (`VX_cache_data`) | `1rw` | `8192 × 512` | Yes (`64 × 8b`) | 32 / cluster | 128 | `16x 2048x128b_wm1` sub-cuts/slice | 2,048 | 65,536.000 | 64.000000 |
| `tcu_meta` | TCU Meta (`VX_tcu_meta`) | `1r1w` | `8 × 4096` | Yes (`128 × 32b`) | 4 / core | 256 | `32x 8x128b_wm1` RF cuts | 8,192 | 1,024.000 | 1.000000 |
| `dxa_desc_table` | DXA (`VX_dxa_desc_table`) | `1r1w` | `16 × 768` | Yes (`24 × 32b`) | 1 / socket | 64 | `6x 16x128b_wm1` RF cuts | 384 | 96.000 | 0.093750 |
| `dxa_async_desc_fifo` | DXA (`VX_dxa_core`) | `1r1w` | `16 × 251` | No (`1 × 251b`) | 1 / socket | 64 | `2x 16x126b_wm0` RF cuts | 128 | 31.375 | 0.030640 |
| **SoC Totals** | **7 Subsystems** | — | — | — | **4 clusters, 64 cores** | **8,256** | *(841,673,728 bits / 105,209,216 B)* | **22,784** | **102,743.375** | **100.335327** |

*(Note: `aigpu-b1` sets `VX_CFG_L2_WRITEBACK=0` in multi-cluster mode so `l2_dirty_mask` is omitted; `l2_data` `total_bits` / `MiB` reflect the chip-wide `64 MiB` target in `profiles/aigpu-b1.json`. Unmodified `VX_cluster.sv` requires cluster-scaled `L2_SIZE` parameter wiring during full-chip integration.)*

---

## 4. Process Node & Hard-IP Procurement Matrix

Vendors and design houses responding to this RFQ should quote PDK, foundation IP, and hard-IP entitlements across the target options below (`ODR-007` remains `UNDECIDED` until written quotes are reviewed under P10):

| Subsystem / IP Category | TSMC N4P / N3E (Primary `aigpu-b1` Target) | Samsung SF4X (Alternate `aigpu-b1` Target) | GlobalFoundries 12LP+ (MPW Shuttle Option for `aigpu-b1-tile`) | Required RFQ Deliverables |
|---|---|---|---|---|
| **Process PDK & Foundries** | N4P (2.0 GHz class) or N3E FinFET; DRC/LVS/PEX sign-off decks | SF4X 4nm FinFET; DRC/LVS/PEX sign-off decks | 12LP+ FinFET MPW shuttle (4-core tile bring-up at ~0.8–1.2 GHz scaled target) | NDA, PDK rev, MPW/dedicated mask schedule, wafer & mask pricing |
| **Standard Cells & Power Kit** | Multi-VT (`ULVT`/`LVT`/`SVT`) std-cell libs + ECO + UPF cells (header switches, clamp-0 isolation, level shifters) | Multi-VT std-cell libs + UPF power-management kit | Multi-VT 12LP+ std-cell libs + retention/isolation cells | `.lib`/`.db` across `ss`/`tt`/`ff` + OCV/AOCV/POCV, LEF, GDS, CDL |
| **SRAM & RF Compilers** | High-density 1RW (`2048×128`), dual-rail 1R1W (`1024×64`, `512×128`), high-speed RF (`64×256`, `16×128`, `8×128`, `4×128`) + MBIST/repair collars | Equivalent SF4X SRAM + RF compilers + MBIST collars | 12LP+ 1RW/1R1W SRAM + RF compilers for 131-array `aigpu-b1-tile` | Compiler access, generated `.lib`/LEF/GDS/Verilog, BIST/bisr collar spec |
| **HBM3E Memory Subsystem** | HBM3E PHY + Controller (AXI4/CHI bridge, training FW, ECC) + **CoWoS-S / CoWoS-R 2.5D interposer** + KGD HBM3E sourcing (`aigpu-b1` 4 TB/s class) | HBM3E PHY + Controller + I-CubeS 2.5D interposer | **Not required for 12LP+ MPW**; substitute LPDDR5 / DDR5 or SRAM-only + host-DMA test harness | PHY bump pitch/escape rules, controller RTL/VIP, interposer SI/PI & OSAT SOW |
| **PCIe Host Interface** | PCIe Gen5 / Gen6 x16 Endpoint Controller + SerDes PHY (AXI4 DMA bridge, MSI-X, PIPE) | PCIe Gen5 / Gen6 x16 Controller + PHY | PCIe Gen4 x4/x8 (or JTAG/AXI-over-SerDes debug bridge for MPW) | PCI-SIG compliance record, bump/ballout constraints, SerDes channel loss budget |
| **Die-to-Die (UCIe)** | Optional UCIe 1.1/2.0 Advanced Package PHY (CoWoS) for multi-reticle `aigpu-b1` scaling | Optional UCIe D2D PHY (I-CubeS) | Excluded on single-tile MPW | Lane count, shoreline mm/Gbps density, latency/BER spec |
| **Clocking, PVT, Security & IO** | Fractional/Integer fractional-N PLLs (`clk_core`, `clk_axi`, `clk_pcie`), POR, PVT/droop monitors, eFuse/OTP, GPIO/JTAG/I2C ESD pads | Equivalent SF4X analog/IO macro kit | 12LP+ PLL, POR, GPIO/JTAG ESD pad ring | Jitter/phase-noise spec, pad ring ESD (HBM/CDM), bump/wirebond pitch |

---

## 5. Clocking, Reset, Power Intent (UPF 2.1) & DFT/JTAG Handoff Collateral Map

All architectural handoff collateral lives under [`hw/asic/`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/README.md) and [`hw/dv/`](file:///home/antigravity/baabi-boo/AI-GPU/hw/dv/README.md):

| Domain / Deliverable | Exact Repository Path | Technical Specification & Integration Contract | Verification Status |
|---|---|---|---|
| **Multi-Clock SDC Constraints** | [`hw/asic/constraints/aigpu_b1.sdc`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/constraints/aigpu_b1.sdc) | 4 async clock domains: `clk_core` (`0.500 ns` / 2.0 GHz, parameterized `CORE_PERIOD`), `clk_axi` (`1.000 ns` / 1.0 GHz), `clk_pcie` (`2.000 ns` / 500 MHz), `tck` (`20.00 ns` / 50 MHz); `set_clock_groups -asynchronous`; net-anchored CDC `set_max_delay` across all 22 Gray-pointer, FIFO payload, `cycle_snap`, and 2-FF sync paths; `0.120 ns` max transition, fanout `32`. | Checked in OpenSTA 3.1.0 (`22/22` CDC pairs matched, 0 unconstrained endpoints on `VX_asic_soc_top`) |
| **IEEE-1801 UPF 2.1 Power Intent** | [`hw/asic/power/aigpu_b1.upf`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/power/aigpu_b1.upf) | `PD_AON` (`VDD_AON` 0.75 V nominal: AXI4-Lite CSRs, `u_boot_sram` retention via `mbist_ret_sync2_q`, CDC FIFOs, `u_dft`) + 4 switchable compute cluster domains `PD_CLUSTER_0..3` (`VDD_CLUST` 0.75 V nom / 0.85 V ODV); header switches `PSW_CLUSTER_0..3`, clamp-0 isolation `ISO_CLUST_0..3_OUT`, bidirectional level shifters `LS_*`, SRAM array retention `RET_CLUST_0..3_SRAM`, and 5-state PST (`ALL_ON`, `BOOST_ODV`, `TILE_HALF`, `SINGLE_TILE`, `DEEP_SLEEP`). | `source_present` template matching RTL pins (`pwr_clust_{en,iso_en,ret_en}`); **requires commercial VC LP / Conformal LP check** |
| **IEEE-1149.1 JTAG TAP & DFT Wrapper** | [`hw/asic/dft/VX_asic_dft_top.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/dft/VX_asic_dft_top.sv) | 16-state TAP FSM, `IDCODE = 32'h1A16_B101`, `BYPASS`, `SCAN_CTRL` (`dft_scan_enable`, `dft_test_mode`, `dft_cg_override`, 8-chain bypass), `MBIST_CTRL` (internal 2-FF `clk_axi -> tck` syncs on `mbist_done`/`mbist_fail`), and `PWR_CTRL` (`pwr_clust_en/iso_en/ret_en`). | Formal `k`-induction + BMC PASS (Yosys/Z3); OpenROAD PnR + KLayout GDSII (`0` DRT DRC) on ASAP7 & Nangate45 |
| **Dual-Clock CDC SoC Shell** | [`hw/asic/soc/VX_asic_soc_top.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/soc/VX_asic_soc_top.sv) | Independent 2-FF reset syncs (`clk_core`, `clk_axi`), 2-FF `tck -> clk_axi` DFT/power syncs, AXI4-Lite CSR + `u_boot_sram` (`SLVERR` guard when `mbist_active=1`), dual Gray-code async CDC FIFOs, toggle-handshake cycle counter snapshot, AXI4-Full HBM master, embedded `u_dft` and `u_boot_sram` (`VX_sram_1rw`). | Verilator/CIRCT/Yosys lint PASS; 70 SVA constrained-random stress PASS (`96.9%` DUT line coverage); ASAP7 synthesis w/ `fakeram7_256x32` |
| **Foundry SRAM Wrappers** | [`hw/asic/sram/VX_sram_1rw.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/VX_sram_1rw.sv), [`VX_sram_1r1w.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/VX_sram_1r1w.sv), [`VX_sram_2rw.sv`](file:///home/antigravity/baabi-boo/AI-GPU/hw/asic/sram/VX_sram_2rw.sv) | Parameterized `DEPTH`, `DATAW`, `WRENW`, `BYTE_W`, `HAS_BIST`; `` `ifdef ASIC_SRAM_MACROS `` instantiates foundry macro hooks (`VX_sram_*_macro`) with MBIST mux bypass and `sleep`/`sd`/`ret` pins; zero-latch synchronous `$mem_v2` fallback for FPGA/open synthesis. | Verified in Verilator 5.050, CIRCT, and Yosys 0.69 (`0` warnings, `0` latches, `-DASIC_SRAM_MACROS` clean) |
| **SVA & Formal DV Suite** | [`hw/dv/`](file:///home/antigravity/baabi-boo/AI-GPU/hw/dv/README.md) | `VX_axi4_sva.sv` (18 assertions), `VX_tcu_handshake_sva.sv` (10 assertions), `VX_cdc_fifo_sva.sv` (12 assertions), `VX_asic_dft_formal.sv`, `VX_cdc_fifo_formal.sv`, `tb_asic_soc.cpp`. | All formal proofs & constrained-random coverage PASS ([`dv_results.json`](file:///home/antigravity/baabi-boo/AI-GPU/hw/dv/dv_results.json)) |

---

## 6. Phased Tapeout Roadmap & Indicative NRE / MPW Budget Template

> [!WARNING]
> **Budgetary Planning Ranges Only — NOT Vendor Quotes:**
> The cost envelopes below are non-binding **RFQ solicitation planning ranges** to structure vendor bids across foundry shuttle/mask, IP NRE, EDA, and OSAT packaging. No prices have been quoted or committed; actual spend requires written vendor SOWs and human `P10-A03` approval (`go_approved = true`).

### 6.1 Recommended Two-Step Silicon Realization Strategy

| Phase | Vehicle | Recommended Node | Key Gate Objective |
|---|---|---|---|
| **Phase A (Risk-Reduction MPW)** | `aigpu-b1-tile` (4 cores, 0.52 MiB SRAM, ~10–15 mm² test die) | GF 12LP+ (or TSMC N12/N6/N4P MPW shuttle) | Validate RV64X + TFR tensor numerics, JTAG/MBIST/UPF power gating, SRAM compiler integration, and PCIe/memory bring-up on packaged silicon (`P11-A02`/`A03`) before committing full-reticle N4P/N3E masks |
| **Phase B (Production SoC)** | `aigpu-b1` (64 cores, 100.34 MiB SRAM, full-reticle die + CoWoS interposer) | TSMC N4P / N3E or Samsung SF4X | Scale to 4 clusters × 16 cores, 64 MiB L2, HBM3E 4 TB/s CoWoS-S/R, PCIe Gen5/6 x16, and optional UCIe D2D after `aigpu-b1-tile` silicon bring-up |

### 6.2 Indicative NRE / MPW Budget Template (USD Planning Ranges — For RFQ Breakdown)

| Cost Line Item | `aigpu-b1-tile` (MPW Shuttle Planning Range) | `aigpu-b1` (Full-Reticle 4nm/3nm SoC Planning Range) | RFQ Quote Status |
|---|---|---|---|
| **MPW Shuttle / Dedicated Mask Set + Engineering Wafers** | \$0.3M – \$1.5M *(12nm MPW shuttle; higher if 4nm MPW)* | \$12.0M – \$25.0M *(N4P/N3E full-reticle mask set + engineering lot)* | `REQUIRES_WRITTEN_QUOTE` |
| **PDK, Standard-Cell & SRAM Compiler Licenses** | \$0.2M – \$0.8M | \$1.5M – \$4.0M | `REQUIRES_WRITTEN_QUOTE` |
| **High-Speed & Analog IP (HBM3E, PCIe, UCIe, PLL, Pads)** | \$0.4M – \$2.0M *(PCIe Gen4/5 + LPDDR5/debug PHY + PLL)* | \$6.0M – \$15.0M *(HBM3E PHY/Ctrl + PCIe Gen5/6 + UCIe + PLL/PVT)* | `REQUIRES_WRITTEN_QUOTE` |
| **Design-House Physical / Sign-Off Services & EDA Seats** | \$0.8M – \$2.5M | \$6.0M – \$15.0M | `REQUIRES_WRITTEN_QUOTE` |
| **2.5D Interposer, Substrate, OSAT Assembly & ATE Test** | \$0.15M – \$0.5M *(FC-BGA + socket + bring-up board)* | \$3.0M – \$8.0M *(CoWoS interposer + HBM3E KGD + ATE + bring-up)* | `REQUIRES_WRITTEN_QUOTE` |
| **Total Indicative Planning Envelope (Pre-Quote)** | **\$1.85M – \$7.30M** | **\$28.5M – \$67.0M** | `UNAPPROVED (go_approved = false)` |

---

## 7. Reproducible Export & Verification Commands

Run from the repository root (pure Python 3 stdlib, zero external dependencies):

```bash
# 1. Dry-run IP cleanliness audit + JSON summary (no archive written)
python3 ci/project/export_clean_rtl_handoff.py --dry-run --json

# 2. Export deterministic Apache-2.0 clean-RTL tarball and standalone manifest
python3 ci/project/export_clean_rtl_handoff.py \
  --output /tmp/aigpu-b1-clean-rtl-handoff.tar.gz \
  --manifest-out /tmp/handoff_manifest.json

# 3. Verify exporter self-tests (6 unit tests, 0 skips)
python3 -m unittest ci/project/test_export_clean_rtl_handoff.py -v
```
