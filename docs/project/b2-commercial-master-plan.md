# AI-GPU B2 Commercial Pre-Silicon & Full-Stack Master Plan (`Waves 13–32`)

**Charter Authority:** [ADR-007](decisions.md#adr-007--reticle-class-blackwell-competing-aigpu-b2-commercial-pre-silicon--full-stack-program) (approved 2026-11-26)  
**Base Commit:** `96424fa` (`master`, ADR-006 Tracks A–F complete)  
**Integration Branch:** `feat/aigpu-b2-commercial` (draft PR to `master`, wave-by-wave verified pushes)  
**Machine-Readable Ledger:** [`docs/project/b2_program_ledger.json`](b2_program_ledger.json)  
**Automated LOC & Gate Tracker:** [`ci/project/b2_program_tracker.py`](../../ci/project/b2_program_tracker.py)  
**Evidence Ceiling (Strict, Unwaived):** `source_present`, `simulated`, `rtl_verified`, `open_source_synth_pnr_gds` (`foundry_signoff: false`, `fpga_measured: false`, `silicon_measured: false`, `P01-A03` `blocked`, `P07`–`P11` `not_started`).

---

## 1. Mission & Target Silicon Profiles

Close the architectural, SoC-integration, verification, and commercial software gaps between `aigpu-b1` (`131 TFLOPS` FP16 / `524 TOPS` FP4 dense, `244.4 mm²` N4P estimate) and a genuine **NVIDIA Blackwell-class datacenter AI GPU**, producing an Apache-2.0 clean-IP codebase ready for investor technical diligence, physical FPGA bring-up (`P07`), and commercial foundry/design-house handoff (`P10`/`P11`).

| Target Profile | Role | Compute Topology | Dense FP16 / FP8 / FP4 Peak (Modeled @ 2.0 GHz) | 2:4 Sparse FP16 / FP8 / FP4 | On-Die SRAM + TMEM | Modeled Memory / D2D Fabric | Target Die Class (N4P Est.) |
|---|---|---|---|---|---|---|---|
| **`aigpu-b2-tile`** | RTL-verifiable compute tile & MPW slice | 1 cluster × 4 RV64X cores (`TFRv2` + `TMEM`) | `~18 / 36 / 72 TFLOPS` (scaled @ 2 GHz; 400 MHz RTL ref) | `~36 / 72 / 144 TFLOPS` | `1.5 MiB` L1/L2 + `1 MiB` TMEM | Local AXI4 + NoC router + UCIe stub | `~12–18 mm²` MPW |
| **`aigpu-b2`** | Full-reticle single-die datacenter AI GPU | 8 clusters × 16 RV64X cores = **128 cores**, 4 `TFRv2`/`tcgen05` tensor pipes/core (`PE_RATIO=1`, wide `16×8×8` systolic/FEDP), **256 KiB TMEM/core** | **`1,152 TFLOPS` FP16 / `2,304 TFLOPS` FP8 / `4,608 TOPS` FP4** | **`2,304` / `4,608` / `9,216`** | `128 MiB` L2/SLC + `32 MiB` TMEM + `32 MiB` LMEM/RF/L1 | `4.0 TB/s` HBM3E (`8` stacks) + `10 TB/s` UCIe 2.0 D2D + PCIe Gen6 x16 | `~740–810 mm²` (`<=858 mm²` reticle) |
| **`aigpu-b2-dual`** | Dual-die CoWoS/UCIe unified GPU (B200 class) | 2 × `aigpu-b2` coherent dies = **256 cores** (single logical GPU via UCIe 2.0 coherent directory) | **`2,304 TFLOPS` FP16 / `4,608 TFLOPS` FP8 / `9,216 TOPS` FP4** | **`4,608` / `9,216` / `18,432`** | `256 MiB` unified L2/SLC + `64 MiB` TMEM | `8.0 TB/s` HBM3E (`16` stacks) + `10 TB/s` coherent D2D | `2 × ~780 mm²` CoWoS-L |

*Preserved Legacy Profiles:* `aigpu-b1` (64 cores), `aigpu-b1-tile` (4 cores), `p02-tfr`, frozen P05 `python/vortex_ai/` (23 files), and `docs/assets/img/vortex_framework_stack.svg` MUST remain untouched and passing.

---

## 2. Production Code Scale & Anti-Bloat Standard (`>=500,000` Net New Non-Test Production LOC)

To satisfy the explicit requirement of **at least 500,000 lines of genuine, production-grade code (not just tests)** without cutting corners or padding:

1. **Strict Counting Rule (enforced by [`ci/project/b2_program_tracker.py`](../../ci/project/b2_program_tracker.py)):**
   - **Counts toward the `>=500,000` production LOC bar:** Net non-blank, non-comment-only added lines vs. `96424fa` in real production source trees (`hw/rtl/`, `hw/asic/`, `sim/simx/`, `sim/common/`, `compiler/`, `sw/libs/`, `sw/driver/`, `sw/runtime_b2/`, `sw/ccl/`, `python/aigpu_triton/`, `python/aigpu_torch/`, `python/aigpu_serve/`, `python/aigpu_sdk/`, `tools/`, `ci/project/` non-test tools).
   - **Tracked separately (does NOT count toward the 500K production bar):** `hw/dv/`, `tests/`, `**/test_*.py`, `**/*_test.cpp`, `docs/`, JSON/evidence logs, generated files (`build*/`), vendored/third-party files (`third_party/`).
   - **Anti-bloat automated rejection:** No auto-generated lookup-table dumps, no copy-pasted repetitive boilerplate modules, no dead unreachable code, and every new module MUST be imported/instantiated/compiled and exercised by at least one live passing test.

| Program Pillar | Production Directories | Target Net Production LOC | Verification / DV / Test LOC (Separate) |
|---|---|---:|---:|
| **0. Bootstrap, Profiles & Data Room Tooling** | `profiles/`, `ci/project/`, `tools/dashboard/` | `10,000` | `5,000` |
| **1. Blackwell-Class Silicon RTL & ASIC/PnR Collateral** | `hw/rtl/`, `hw/asic/` | `150,000` | `45,000` (`hw/dv/` SVA + formal + TB) |
| **2. Cycle-Accurate SimX Lockstep Models** | `sim/simx/`, `sim/common/` | `75,000` | `15,000` (parity & unit suites) |
| **3. Tensor Compiler, Triton-like DSL & Autotuner** | `compiler/aigpu_cc/`, `python/aigpu_triton/` | `90,000` | `20,000` |
| **4. Production AI/Math Kernel Libraries** | `sw/libs/aigpu_{blas,flash,moe,dnn,quant}/` | `80,000` | `18,000` |
| **5. Linux DRM/KFD Driver, Async Runtime & `aigpuCCL`** | `sw/driver/`, `sw/runtime_b2/`, `sw/ccl/` | `65,000` | `15,000` |
| **6. PyTorch `PrivateUse1`/Inductor, vLLM Serving, Training & Profiler/Debugger** | `python/aigpu_{torch,serve}/`, `tools/aigpu_{prof,dbg}/` | `55,000` | `12,000` |
| **Program Total** | **All Production Subsystems** | **`525,000` (`>=500,000` gate)** | **`130,000` (separate verification)** |

---

## 3. Orchestration Architecture & Multi-Day Execution Protocol

Designed specifically for continuous multi-day `/teamwork` or `/goal` autonomous execution:

### 3.1 Agent Roles & Explicit Model Tier Mapping
- **1 Lead Project Manager / Architect (`Model: "pro"` / `"inherit"`):**
  - Owns wave decomposition, interface contracts, file-ownership locks, integration merges, evidence ledger updates, `b2_program_tracker.py` LOC audits, and Git commits/pushes.
  - Never delegates conflicting writes to the same file across parallel implementers.
- **Independent Reviewers (`Model: "pro"` / `"inherit"`):**
  - Mandatory before every wave commit using [`code-review`](../../.agents/skills/code-review/SKILL.md) (plus `rtl-review` for `hw/` diffs and `simx-review` for `sim/` diffs).
  - Enforces zero `F0`/`F1` findings, zero anti-bloat violations, zero SimX↔RTL parity regressions, zero protected-asset/frozen-P05 mutations, and honest evidence labels.
- **Parallel Subsystem Implementers (`Model: "flash"`, 3–6 concurrent workers per wave):**
  - Each implementer owns a strictly disjoint directory/file set defined in the wave dispatch sheet.
  - Each implementer writes production code + matching unit/SVA/formal tests and runs local compile/test verification before handing back to the PM.

### 3.2 Resource & Live Verification Budget (Local VM: `85 GB` free disk, `7.8 GB` RAM + `8 GB` swap)
- Always bound parallel compiles/simulations to `-j2` (or `-j1` for Verilator/OpenROAD peak-memory jobs) and monitor `free -h` / `df -h` before heavy builds.
- Use separate out-of-tree build directories (`build64_b2/`, `build32_beacon/`, `build_sw_b2/`). Re-run `../configure` whenever `VX_config.toml` or Makefiles change.
- **Every single wave MUST pass all applicable live gates before commit & push:**
  1. `python3 ci/project/check_project.py` (0 errors)
  2. `python3 ci/project/b2_program_tracker.py --verify` (anti-bloat + ledger integrity)
  3. Native C++/Python compilation & unit tests (`0` failures, `0` skips)
  4. For RTL waves: Verilator `--lint-only` (`0` warnings/errors), native `rtlsim`/unit simulation, SVA assertions (`0` failures), Yosys synthesis + Z3 formal proofs where applicable, and Beacon `logic_gate` check
  5. For SimX waves: SimX↔RTL exact retired-instruction & sub-5% cycle parity
  6. Independent `pro` review sign-off recorded in wave evidence JSON
  7. Push to `origin feat/aigpu-b2-commercial` and update the draft PR description with live progress & LOC telemetry.

### 3.3 Continuous Non-Stop Rule
- When Wave `N` closes, the Lead PM immediately dispatches Wave `N+1`.
- If a wave encounters a local memory/tool issue, fix the root cause (per `AGENTS.md §3`), never skip or weaken gates.
- Do **not** declare program completion until **all 20 waves (Waves 13–32)** are `complete`, `b2_program_tracker.py` reports **`>=500,000` verified net new non-test production LOC**, and all Wave 32 investor/foundry deliverables pass independent `pro` review.

---

## 4. Ordered 20-Wave Execution Roadmap (`Waves 13–32`)

### Phase I — Environment Bootstrap & `aigpu-b2` Architecture Freeze
- **Wave 13 — Full Toolchain/EDA Bootstrap & `aigpu-b2` Architecture Spec (`~5K` prod LOC):**
  - Install Vortex prebuilt toolchain (`$HOME/tools`: Verilator, RISC-V LLVM/GCC, libc/libcrt, CIRCT/Beacon), `yosys` + `z3`, `openroad`/`opensta`/`klayout` (bounded within disk/RAM), and Python `numpy`, `torch` (CPU), `onnx`, `pytest`, `scipy`.
  - Freeze `profiles/aigpu-b2.json`, `profiles/aigpu-b2-dual.json`, and `profiles/aigpu-b2-tile.json`; extend `ci/profile_check.py`, `ci/project/b1_roofline_compare.py` → `b2_roofline_compare.py`, and `ci/project/aigpu_ppa_model.py` for reticle-class N4P/N3E single-die and dual-die CoWoS-L modeling vs. NVIDIA B200 / H200 / MI300X.
  - Verify `build64_b2` compiles cleanly and baseline `demo` + `sgemm_tcu` pass on SimX & `rtlsim`.

### Phase II — Blackwell-Class Silicon RTL & ASIC/Physical Collateral (`~150K` prod LOC + `~45K` DV/Formal/SVA)
- **Wave 14 — Pillar 1: 5th-Gen `TFRv2` / `tcgen05`-Class Tensor Core + Dedicated `TMEM` (`~28K` RTL LOC + `~10K` DV/Formal):**
  - Implement `hw/rtl/tcu/v2/`: wide `16×8×8` `TFRv2` FEDP systolic pipelines (`PE_RATIO=1`), hardware block microscaling (`UE8M0` / `E4M3` scale factors), native `NVFP4`, `MXFP4`, `MXFP6` (`E2M3`/`E3M2`), `FP8` (`E4M3`/`E5M2`), `MXFP8`, `BF16`, `FP16`, `TF32`, `INT8`, `2:4` structured sparsity metadata compressor/selector, and asynchronous 2-CTA warp-group MMA controller.
  - Implement `hw/rtl/tmem/`: 256 KiB/core banked **Tensor Memory (`TMEM`)** decoupled accumulator SRAM with `tcgen05`-class `ld`/`st`/`mma`/`wait`/`alloc` micro-op ports, bank-conflict arbiter, and swizzle address generator.
  - Formal Z3 equivalence proofs on FP4/FP6/FP8 microscaling datapath + Verilator unit tests + SVA handshakes.
- **Wave 15 — Pillar 2: Coherent 2D Mesh NoC, Distributed L2/SLC Directory & UCIe 2.0 D2D Coherent Link (`~30K` RTL LOC + `~10K` DV/Formal):**
  - Implement `hw/rtl/noc/`: parameterized 2D Mesh NoC (virtual-channel wormhole routers, credit-based flow control, XY dimension-order deadlock-free routing, request/response/snoop virtual networks, multicast tree support, QoS arbitration).
  - Implement `hw/rtl/coherence/`: distributed MESI/MOESI directory controller across 8 cluster L2/SLC slices (`128 MiB` logical capacity), snoop filter, atomic ALU-in-L2, and writeback/invalidation ordering engine.
  - Implement `hw/rtl/ucie/`: UCIe 2.0 die-to-die coherent link layer (FDI/RDI protocol adapter, CRC/retry/flit-packing engine, credit flow control, multi-die address interleaving, link-training FSM) unifying two `aigpu-b2` dies into `aigpu-b2-dual`.
  - Formal deadlock-freedom & coherence-invariant Z3 proofs + dual-die Verilator mesh stress bench.
- **Wave 16 — Pillar 3: HBM3E Multi-Channel Controller/Scheduler, Hardware Decompression Engine & 5D DXA/TMA Multicast (`~28K` RTL LOC + `~8K` DV/Formal):**
  - Implement `hw/rtl/hbm3e/`: multi-channel AXI4-to-HBM3E controller & FR-FCFS bank-group/pseudo-channel command scheduler (row-buffer hit prioritization, tRCD/tRP/tRAS/tFAW/tREFI timing generators, per-bank refresh, SECDED + Chipkill ECC encoder/decoder & background scrubber).
  - Implement `hw/rtl/de/`: **Hardware Decompression Engine (`VX_de_top`)** supporting streaming LZ4, Snappy, Deflate/Huffman, and Bitcomp/FP4-weight decompression directly along the HBM→L2/LMEM DMA path.
  - Upgrade `hw/rtl/dxa/`: 5D tensor TMA multicast across cluster CTAs, im2col/swizzle tiling, barrier-arrive-expect-tx completion counters, and decompression-hooked async copy.
- **Wave 17 — Pillar 4: GigaThread Command Processor, MIG Isolation, PCIe Gen6 DMA/IOMMU/SR-IOV & Full `aigpu-b2` SoC Integration (`~34K` RTL LOC + `~10K` DV/Formal):**
  - Implement `hw/rtl/cp_b2/`: hardware GigaThread Command Processor (64 hardware work queues, doorbell ring buffers, priority/preemption engine, dynamic persistent CTA dispatcher, hardware grid-sync barriers, stream/event dependency graph walker).
  - Implement `hw/rtl/mig/`: hardware-enforced Multi-Instance GPU (MIG) spatial & QoS partitioner (cluster/L2-way/HBM-channel/NoC-bandwidth isolation + per-slice fault containment).
  - Implement `hw/rtl/pcie/`: PCIe Gen6 x16 TLP/DMA engine (multi-channel scatter-gather descriptors, MSI-X vector table, SR-IOV PF/VF routing) + **IOMMU / SV48 page-table walker** with TLB, ATS/PRI page-fault queue, and PASID isolation.
  - Integrate `hw/asic/soc/VX_asic_b2_soc_top.sv`: wire actual `aigpu-b2-tile` / multi-cluster compute fabric to the NoC, L2 directory, HBM3E controller, CP, MIG, PCIe/IOMMU, UCIe D2D, and JTAG/DFT shell (resolving `VX_cluster.sv` L2 scaling).
- **Wave 18 — Pillar 5: Datacenter RAS/ECC, DVFS/Thermal Telemetry, Confidential Computing & Hierarchical ASIC/OpenROAD Collateral (`~30K` RTL/ASIC LOC + `~7K` DV/Formal):**
  - Implement `hw/rtl/ras/`: chip-wide RAS aggregator, SRAM/RF/TMEM/L2 ECC error injection & scrubbing controller, poison-bit propagation across NoC/L2/cores, machine-check bank registers, and fatal/recoverable IRQ containment.
  - Implement `hw/rtl/pmu/`: DVFS frequency/voltage droop FSM, per-cluster power-proxy counters, thermal throttling/power-cap governor, and clock/power-gating sequencer.
  - Implement `hw/rtl/sec/`: Confidential Computing secure-boot RoT FSM, SPDM-style measurement registers, and inline AES-256-GCM memory/PCIe encryption-authentication engine (`XTS/GCM` datapath + key-slot table).
  - Complete `hw/asic/b2/`: full `aigpu-b2` / `aigpu-b2-tile` SRAM macro manifest, multi-clock SDC, IEEE-1801 UPF 2.1, DFT/MBIST scan controller, and hierarchical OpenROAD ORFS PnR scripts targeting `TFRv2` slice, `TMEM` bank, NoC router, HBM scheduler, and `VX_asic_b2_soc_top`.

### Phase III — Cycle-Accurate SimX Lockstep Models (`~75K` prod LOC + `~15K` tests)
- **Wave 19 — Full `aigpu-b2` SimX Lockstep Engine (`~75K` C++ LOC):**
  - Mirror every Wave 14–18 silicon block in `sim/simx/` via strict `SimChannel` Cardinal Rule compliance: `TFRv2`/TMEM/microscaling cycle & bit-exact FP4/FP6/FP8/BF16/FP16 arithmetic engine, 2D Mesh NoC + L2/SLC MOESI directory simulator, UCIe dual-die coherent interconnect simulator, HBM3E bank-accurate timing model, Hardware Decompression Engine model, GigaThread CP + MIG partition model, PCIe Gen6 DMA/IOMMU page-fault model, RAS fault-injection hooks, and hardware telemetry/PMU counters.
  - Verify `aigpu-b2-tile` SimX↔Verilator `rtlsim` exact retired-instruction & `<5%` cycle parity across core/tensor/NoC/DXA/CP workloads.

### Phase IV — Commercial GPU Compiler, Triton-like DSL & Autotuner (`~90K` prod LOC + `~20K` tests)
- **Wave 20 — `aigpu-cc` Multi-Level SSA IR, Tiling & Memory Optimization (`~30K` C++/Python LOC):**
  - Build `compiler/aigpu_cc/`: dialect hierarchy (`TensorIR` → `TileIR` → `SimtIR` → `Rv64xIR`), SSA verifier, shape/dtype/layout inference, operator fusion (matmul+epilogue, flash-attn, norm+quant, MoE), polyhedral/blocked tile planner, and bank-conflict-free LMEM/TMEM swizzle allocator.
- **Wave 21 — Warp Specialization, Async Pipelining & RV64X Codegen (`~32K` C++ LOC):**
  - Producer/consumer warp specialization passes (DXA DMA warps + `tcgen05` MMA warps + epilogue warps), multi-stage software pipelining with hardware barrier allocation, linear-scan/graph-coloring register allocator with TMEM-aware spilling, RV64X + `TFRv2`/`TMEM`/`DXA`/`MUFU` instruction selection, peephole optimizer, binary ELF/kernel-bundle emitter.
- **Wave 22 — Triton-Like Python Tensor DSL & Persistent-Kernel Autotuner (`~28K` Python LOC):**
  - Build `python/aigpu_triton/`: `@aigpu.jit` decorator, `tl`-compatible block primitives (`load`, `store`, `dot`, `dot_scaled` FP4/FP8, `make_block_ptr` → DXA 5D descriptor, `atomic_*`, `cdiv`, `program_id`), AST→`TensorIR` frontend, `@aigpu.autotune` search engine with SimX cost-model pruning, persistent disk kernel cache, and end-to-end compiled kernel execution on SimX.

### Phase V — Production Math & AI Kernel Libraries (`~80K` prod LOC + `~18K` tests)
- **Wave 23 — `aigpuBLAS` (CUTLASS-Class Multi-Precision GEMM Library, `~32K` C++/RV64X LOC):**
  - Tile/mainloop/epilogue template architecture in `sw/libs/aigpu_blas/`: dense & `2:4` sparse GEMM, GEMV, Batched GEMM, Grouped GEMM, Split-K/Stream-K persistent GEMM across `FP16`, `BF16`, `TF32`, `FP8` (`E4M3`/`E5M2`), `MXFP8`, `MXFP6`, `MXFP4`, `NVFP4`, `INT8`, with fused bias/activation/residual/quantization epilogues and heuristic kernel dispatcher.
- **Wave 24 — `aigpuFlash` (FlashAttention-3/4, MLA & PagedAttention Library, `~24K` C++/RV64X LOC):**
  - Build `sw/libs/aigpu_flash/`: warp-specialized async DXA+TMEM FlashAttention forward & backward (`FP16`/`BF16`/`FP8`), GQA/MQA, DeepSeek Multi-Head Latent Attention (MLA), PagedAttention v2 for KV-cache serving, causal/sliding-window/block-sparse masks, softcapping, and rotary embedding fusion.
- **Wave 25 — `aigpuMoE`, `aigpuDNN` & `aigpuQuant` (`~24K` C++/RV64X LOC):**
  - Fused Mixture-of-Experts (`top-k` gating, capacity/load-balance routing, scatter/gather permutation, grouped FP4/FP8 expert GEMM, weighted combine), fused norms (`RMSNorm`/`LayerNorm` fwd+bwd), activations (`SwiGLU`/`GeGLU`/`SiLU`/`GELU` fwd+bwd), fused `CrossEntropy`/`Softmax`, fused `AdamW`/`SGD`/`Lion` optimizers, and dynamic block-scale `NVFP4`/`MXFP4`/`FP8` delayed-scaling quantizers.

### Phase VI — OS Kernel Driver, Async Runtime & Multi-GPU Collectives (`~65K` prod LOC + `~15K` tests)
- **Wave 26 — `aigpu-drm` Linux DRM/KFD-Style Kernel Driver (`~26K` C LOC):**
  - Build `sw/driver/aigpu_drm/`: clean Linux DRM/KFD-structured kernel driver + user-space mock-PCI/VFIO harness for live VM testing — PCIe Gen6 probe/BAR/MSI-X setup, GEM/TTM/HMM GPU virtual memory manager, IOMMU/SV48 page-fault & migration handler, GigaThread hardware queue/doorbell submission, MIG slice lifecycle, RAS/ECC & thermal `sysfs`/`hwmon` telemetry, confidential-compute attestation ioctls, and versioned UAPI header (`include/uapi/drm/aigpu_drm.h`).
- **Wave 27 — `libaigpu` Production User-Mode Async Runtime (`~22K` C++ LOC):**
  - Build `sw/runtime_b2/`: CUDA/HIP-familiar async C/C++ runtime (`aigpuStream`, `aigpuEvent`, `aigpuGraph` DAG capture/instantiate/update/replay, stream-ordered virtual memory allocator & caching slab pool, unified memory prefetch/advise, multi-device/MIG contexts, hardware decompression API, and SimX/rtlsim/DRM backend adapters).
- **Wave 28 — `aigpuCCL` Multi-Die & Multi-GPU Collectives (`~17K` C++ LOC):**
  - Build `sw/ccl/`: Ring, Double-Binary-Tree, and Hierarchical UCIe-D2D/NVLS-style `AllReduce`, `AllGather`, `ReduceScatter`, `AllToAll`, `Broadcast`, `Reduce`, and `Send`/`Recv` across FP32/FP16/BF16/FP8/INT8, topology-aware communicator planner, overlapped compute/comm streams, and live multi-device SimX verification.

### Phase VII — Frameworks, LLM Serving, Training, Profiler & Final Qualification (`~60K` prod LOC + `~17K` tests)
- **Wave 29 — PyTorch `PrivateUse1` Backend, `torch.compile` Inductor & Autograd Training (`~20K` C++/Python LOC):**
  - Build `python/aigpu_torch/`: PyTorch `PrivateUse1` device registration (`tensor.to("aigpu")`), ATen dispatcher bindings to `aigpuBLAS`/`aigpuFlash`/`aigpuDNN`, `torch.compile` Inductor codegen lowering to `aigpu_triton`/`aigpu_cc`, autograd backward + mixed-precision `AMP`/FP8 `GradScaler` training loop, and `ProcessGroupAIGPU` wrapping `aigpuCCL` (strictly keeping frozen P05 `python/vortex_ai/` untouched).
- **Wave 30 — `aigpu_serve` vLLM/SGLang-Class LLM Serving Engine (`~20K` Python/C++ LOC):**
  - Build `python/aigpu_serve/`: continuous-batching scheduler (chunked prefill + decode), PagedAttention KV-cache block allocator with Radix/prefix caching, speculative decoding, tensor/expert/pipeline parallelism over `aigpuCCL`, `.safetensors` & HuggingFace config loaders for Llama-3, Qwen-2.5, and DeepSeek-MoE architectures, plus an OpenAI-compatible HTTP/streaming server.
- **Wave 31 — Nsight-Class Profiler (`aigpu-prof`) & Kernel Debugger (`aigpu-dbg`) (`~15K` C++/Python LOC):**
  - Build `tools/aigpu_prof/`: hardware PMU counter collector, warp-stall & TMEM/DXA/NoC/HBM bottleneck attribution, automated roofline plotter, Perfetto Chrome-trace & interactive HTML report generator.
  - Build `tools/aigpu_dbg/`: DWARF/ELF kernel symbolizer, warp/lane register & TMEM inspector, out-of-bounds/race/NaN/Inf compute sanitizer, and deterministic SimX trace-diff localizer.
- **Wave 32 — Hierarchical OpenROAD 0-DRC GDSII, Full-Stack Qualification & Investor/Foundry Data Room (`~5K` prod LOC + full evidence closure):**
  - Run OpenROAD ORFS RTL→GDSII (`foundry_signoff: false`) on key `aigpu-b2` macros (`TFRv2` slice, `TMEM` bank wrapper, 2D NoC router, `VX_asic_b2_soc_top`) and record 0-DRC / STA / power metrics.
  - Execute live end-to-end qualification: `aigpu-b2-tile` SimX + Verilator `rtlsim` parity, multi-precision FP4/FP8/BF16 GEMM + FlashAttention + MoE, multi-layer Llama/MoE `.safetensors` serving through `aigpu_serve` + PyTorch `PrivateUse1` + backward training convergence check + multi-device `aigpuCCL` AllReduce/AllToAll.
  - Verify `python3 ci/project/b2_program_tracker.py --verify --require-500k` passes **`>=500,000` net new non-test production LOC**, `export_clean_rtl_handoff.py` passes with `0` proprietary IP violations, `check_project.py` passes cleanly, and publish the updated **Investor Technical Datasheet**, **Interactive Architecture/Roofline/PPA Dashboard**, and **Foundry RFQ Package (`aigpu-b2` / `aigpu-b2-dual`)**.
