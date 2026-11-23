# AI-GPU documentation

AI-GPU has two complementary documentation sets: the development plans and
evidence under [`docs/project/`](project/index.md), and the inherited Vortex
technical reference below. A planned capability is not an implemented or
qualified result; consult the current status and evidence before making a claim.

## AI-GPU project entry points

- [Project documentation hub](project/index.md): reader-specific paths and the complete project index
- [Goal and scope](project/charter.md): what AI-GPU aims to build and what the initial milestone excludes
- [Roadmap](../ROADMAP.md): phases, dependencies and acceptance, with [canonical gates](project/roadmap.json)
- [Current status](project/status.md) and [backlog](project/backlog.md): observed progress, blockers and the next bounded work item
- [Developer guide](project/developer-guide.md): source-only checks, execution prerequisites and resource safeguards
- [Acceptance and evidence](project/acceptance.md): what phase completion actually requires
- [Native lifetime witness](designs/managed_counter_lifetime_v1.md),
  [reviewed original packet](project/evidence/p06-native-lifetime/README.md) and
  [current dependency handoff](project/p06-dependency-provenance-handoff.md):
  executed pending-read/run-reset observations for all four managed SimX processes;
  fresh dependency compilation provenance and complete qualification remain open
- [Complete managed-preflight replay](designs/managed_counter_preflight_replay_v1.md)
  and [historical evidence packet](project/evidence/p06-managed-preflight-replay/README.md):
  inert verification of the preceding four-process original under its v1 contract
- [P06 counter transport audit](project/p06-mpm-transport-audit.md),
  [handoff](project/p06-mpm-transport-handoff.md) and
  [evidence packet](project/evidence/p06-mpm-transport/README.md): RV64 high-word
  repair, reviewed native/parent checks and measured decoder selection; continue with
  the [versioned qualification plan](project/p06-mpm-qualification-plan.md) and
  [current dependency handoff](project/p06-dependency-provenance-handoff.md)
- [P06 serial workspace handoff](project/p06-workspace-handoff.md),
  [runtime/correctness contract](designs/serial_matmul_workspace_v1.md) and
  [reviewed original packet](project/evidence/p06-warm-workspace/README.md):
  implemented ownership and opt-in workspace, with original native correctness
  reviewed separately from warm measurement qualification, which remains blocked
  under the [warm contract](designs/warm_workspace_benchmark_v1.md)
- [P01 local qualification](project/p01-local-qualification.md) and [handoff](project/p01-local-qualification-handoff.md):
  supplemental vendor-free full-AFU `xrtsim` and focused unit checks, separate
  from the vendor `hw_emu` gate (`P01-A03`)

The sections below preserve the Vortex setup, architecture, development and
implemented-subsystem references. Use the project developer guide to choose a
bounded task before following a toolchain, simulation or hardware-build recipe.

## Getting Started

- [Environment Setup](environment_setup.md): system prerequisites and toolchain setup
- [Installing Vortex](install_vortex.md): building and installing the Vortex stack
- [Building the Toolchain from Source](building_toolchain.md): maintainer-facing build recipes for Verilator, RISC-V GNU, LLVM (with X86 + lld + SPIR-V), compiler-rt, musl, POCL, Mesa, chipStar, gem5, CIRCT, and Foldsim
- [FPGA Setup](fpga_setup.md): running Vortex on Altera and Xilinx FPGA cards
- [SLASH / Alveo V80 Setup](xilinx_slash_setup.md): building the SLASH platform stack, the prerequisite for the `aved` backend

## Architecture

- [Codebase Layout](codebase.md): summary of the repo file tree
- [Microarchitecture](designs/microarchitecture.md): Vortex pipeline microarchitectural details and reconfigurability — the natural first read before the subsystem design documents
- [Hardware IP Library](hardware_library.md): catalog of the reusable RTL modules in `hw/rtl/libs/`
- [Software Stack](software.md): OpenCL support and the software layers above the driver

## Development

- [Simulation](simulation.md): building and running each simulation driver
- [Testing](testing.md): running applications and test suites with `blackbox.sh`
- [Continuous Integration](continuous_integration.md): the CI catalog and how to run it locally
- [Debugging](debugging.md): debugging configurations for each Vortex driver
- [Kernel Debugging](kernel_debugging.md): source-level kernel debugging with GDB and OpenOCD
- [Perfetto Analysis](perfetto_analysis.md): performance analysis with Perfetto traces
- [Synthesis and Power Analysis](synthesis_analysis.md): FPGA/ASIC synthesis flows and PPA reporting
- [SimObject Framework](designs/simobject.md): the SimX simulator's component model
- [Coding Guidelines — Verilog](coding_guidelines_verilog.md)
- [Coding Guidelines — C++](coding_guidelines_cpp.md)
- [Bug-Fix Discipline](bug_fixes.md): root-cause-first rules for fixing defects
- [References](references.md): foundational external resources on GPU architecture
- [Contributing](../CONTRIBUTING.md): process for contributing your own features

## Design Documents

Detailed architectural specifications for Vortex subsystems live under
[designs/](designs/):

- **Core pipeline**
  - [Microarchitecture Overview](designs/microarchitecture.md)
  - [Kernel Entry and Dispatch](designs/kernel_entry_and_dispatch.md)
  - [CTA Dispatch Architecture](designs/cta_dispatch_architecture.md)
  - [LSU Pipeline](designs/lsu_pipeline_design.md)
  - [Floating Point Unit](designs/floating_point_unit.md)
  - [Compressed Instruction Support](designs/compressed_instruction_support.md)
  - [Trap and Exception Foundation](designs/trap_and_exception_foundation.md)
  - [Custom Accelerator ISA Extensions](designs/custom_accelerator_isa_extensions.md)
- **Memory system**
  - [Cache Subsystem](designs/cache_subsystem.md)
  - [Memory-Level Parallelism Optimizations](designs/mlp_optimizations.md)
  - [Atomic Memory Operations](designs/atomic_memory_operations.md)
  - [Multi-Cache AMO Coherence](designs/multicache_amo_coherence.md)
  - [Memory Fabric Attributes](designs/memory_fabric_attributes.md)
  - [Virtual Memory](designs/virtual_memory_subsystem.md)
- **Accelerators**
  - [Tensor Core (WGMMA)](designs/tensor_core_wgmma_engine.md)
  - [DXA — Async Copy and Multicast (DMA)](designs/dxa_async_copy_multicast.md)
  - [Ray-Tracing Architecture (RTU)](designs/ray_tracing_architecture.md)
  - [Graphics — Hardware Stack (RASTER/TEX/OM)](designs/graphics_hardware_stack.md)
    - [Rasterizer](designs/rasterizer_architecture.md)
    - [Texture Sampler](designs/texture_sampler_architecture.md)
    - [Output Merger](designs/output_merger_architecture.md)
  - [Graphics — Software Stack](designs/graphics_software_stack.md)
- **System and host interface**
  - [Command Processor](designs/command_processor.md)
  - [Vortex Runtime API](designs/vortex_runtime_api.md)
  - [Host MPM Transport Contract](designs/host_mpm_transport_v1.md)
  - [FPGA AFU Shell](designs/fpga_afu_shell.md)
  - [`aved` Driver (Alveo V80)](designs/aved_driver_architecture.md)
  - [Build Configuration System](designs/build_configuration_system.md)
- **Software stacks**
  - [OpenCL Support (PoCL)](designs/opencl_on_vortex.md)
  - [Vulkan Support (vortexpipe)](designs/vortexpipe_architecture.md)
  - [HIP Support (chipStar)](designs/hip_on_vortex_chipstar.md)
- **Simulation and CI**
  - [SimX Simulator Architecture](designs/simx_simulator_architecture.md)
  - [gem5 Integration](designs/vortex_gem5_integration.md)
  - [FireSim Integration](designs/firesim_integration.md)
  - [Foldsim: threaded FPGA simulation on CIRCT](designs/foldsim.md)
  - [Continuous Integration Design](designs/continuous_integration.md)
