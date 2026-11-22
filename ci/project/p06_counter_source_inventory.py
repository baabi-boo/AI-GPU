# SPDX-License-Identifier: Apache-2.0
"""Caller-pinned source expectations for inert P06 counter diagnostic readers.

A complete external manifest can describe a later producer revision while every
original source name remains mandatory. Its independently supplied SHA-256 is
the trust anchor for the expected descriptors; a source revision string does
not prove that the descriptors belong to Git or that any binary was built.

All descriptor validation is pure. Only ``load_source_inventory`` reads a file:
the explicitly supplied external manifest, through the trusted bounded no-follow
reader. No source descriptor or recorded producer path is opened, resolved,
imported or executed. Success establishes consistency only, never qualification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from baseline_packet_io import PacketReader, load_json_bytes


CONTRACT_ID = "simx-counter-source-inventory-v1"
CHECKED_PRODUCER_CONTRACT_ID = "simx-checked-counters-native-v2"
PUBLIC_PRODUCER_CONTRACT_ID = "simx-counter-public-native-v1"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 20000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_PATH_DEPTH = 64
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
PATH = re.compile(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*\Z")
MANIFEST_FIELDS = {"schema_version", "contract_id", "producer_contract_id", "source_revision", "sources"}
DESCRIPTOR_FIELDS = {"path", "sha256", "size_bytes"}

CHECKED_SOURCE_REVISION = "407ab9fea5e4f793a2a5088f566a87f3e631aa84"
PUBLIC_SOURCE_REVISION = "81ed6871634fefbf5c78fb27cf10dce913bd4d9c"
CHECKED_SOURCE_NAMES_SHA256 = "d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108"
PUBLIC_SOURCE_NAMES_SHA256 = "f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da"

# This bounded extension surface admits new production/header/helper files only
# within reviewed producer source roots, plus the exact original singleton names.
# The checked producer's fixed helper/fixture lists may grow within their existing
# directories. Broader roots or a removed original name require contract review.
_CHECKED_ROOTS = ("ci/project", "sim", "sw/common", "tests/unittest/checked_counters",
                  "third_party/ramulator_ext")
_PUBLIC_ROOTS = ("ci/project", "sim", "sw/common", "sw/include", "sw/runtime", "sw/kernel/include",
                 "tests/unittest/checked_counters", "tests/regression/ai_bench_common",
                 "third_party/ramulator_ext")

LIMITATIONS = (
    "The externally supplied manifest digest defines the trusted source expectations.",
    "A matching revision label and manifest do not independently authenticate GitHub or Git provenance.",
    "Matching retained source descriptors do not establish absent object or executable bytes, or actual execution.",
    "No source descriptor or producer path is opened, resolved, imported or executed.",
    "The original complete source inventories remain mandatory; newly added roots need separate contract review.",
    "Bounded no-follow reads and before/after identity checks do not defeat malicious concurrent filesystem writers.",
    "Successful source consistency validation is diagnostic only and grants no qualification or acceptance.",
)

# Frozen from each immutable producer tree, independently cross-checked against
# the original report's complete inventory and every retained descriptor's Git
# blob SHA-256/length. These names are data, not imports or filesystem paths to
# read. Do not discover them from the current checkout: later replay helpers did
# not exist in the original producer. The checked set is a subset of the public
# set; storing only the public additions avoids duplicating 270 mandatory names.
_CHECKED_SOURCE_NAMES = tuple("""
.gitmodules
VERSION
VX_config.toml
VX_types.toml
ci/blackbox.sh
ci/gen_config.py
ci/project/baseline_inventory.py
ci/project/baseline_matrix.py
ci/project/baseline_packet_contract.py
ci/project/baseline_packet_io.py
ci/project/baseline_process.py
ci/project/compiler_records.py
ci/project/p02_matrix_records.py
ci/project/p06_checked_execute.py
ci/project/p06_compiler_records.py
ci/project/p06_mpm_execute.py
ci/project/preflight.py
config.mk.in
configure
profiles/p02-tfr.json
sim/Makefile
sim/avedsim/Makefile
sim/avedsim/verilator.vlt.in
sim/avedsim/vortex_afu_shim.sv
sim/avedsim/vrt_c.cpp
sim/avedsim/vrt_c.h
sim/common.mk
sim/common/axi_latency_pipe.h
sim/common/cmd_processor.cpp
sim/common/cmd_processor.h
sim/common/cout_drainer.cpp
sim/common/cout_drainer.h
sim/common/dram_bank_model.h
sim/common/dram_sim.cpp
sim/common/dram_sim.h
sim/common/elf_loader.cpp
sim/common/elf_loader.h
sim/common/host_monitor.cpp
sim/common/host_monitor.h
sim/common/mem.cpp
sim/common/mem.h
sim/common/perf_counter.h
sim/common/simobject.h
sim/common/simobject_functional.h
sim/firesim/Makefile
sim/firesim/firesim_emul_main.cpp
sim/firesim/firesim_sim.cpp
sim/firesim/firesim_sim.h
sim/foldsim/Makefile
sim/foldsim/xilinx_fp_models.sv
sim/opaesim/Makefile
sim/opaesim/fpga.cpp
sim/opaesim/fpga.h
sim/opaesim/opae_sim.cpp
sim/opaesim/opae_sim.h
sim/opaesim/verilator.vlt.in
sim/opaesim/vortex_afu_shim.sv
sim/rtlsim/Makefile
sim/rtlsim/main.cpp
sim/rtlsim/p02_wgmma_scoreboard_monitor.sv
sim/rtlsim/processor.cpp
sim/rtlsim/processor.h
sim/rtlsim/rtlsim_axi_shim.sv
sim/rtlsim/rtlsim_shim.sv
sim/rtlsim/verilator.vlt.in
sim/simx/Makefile
sim/simx/alu_unit.cpp
sim/simx/alu_unit.h
sim/simx/amo/amo_ops.h
sim/simx/amo/amo_unit.cpp
sim/simx/amo/amo_unit.h
sim/simx/barrier_unit.cpp
sim/simx/barrier_unit.h
sim/simx/checked_counters.mk
sim/simx/cluster.cpp
sim/simx/cluster.h
sim/simx/completion.mk
sim/simx/constants.h
sim/simx/core.cpp
sim/simx/core.h
sim/simx/cp_llc_port.h
sim/simx/csr_unit.cpp
sim/simx/csr_unit.h
sim/simx/cta_dispatcher.cpp
sim/simx/cta_dispatcher.h
sim/simx/debug.h
sim/simx/decode.cpp
sim/simx/decode.h
sim/simx/decompressor.cpp
sim/simx/decompressor.h
sim/simx/delay_buffer.h
sim/simx/dispatcher.cpp
sim/simx/dispatcher.h
sim/simx/dtm/debug_module.cpp
sim/simx/dtm/debug_module.h
sim/simx/dtm/jtag_dtm.cpp
sim/simx/dtm/jtag_dtm.h
sim/simx/dtm/remote_bitbang.cpp
sim/simx/dtm/remote_bitbang.h
sim/simx/dtm/vortex.cfg
sim/simx/dxa/dxa_core.cpp
sim/simx/dxa/dxa_core.h
sim/simx/dxa/dxa_unit.cpp
sim/simx/dxa/dxa_unit.h
sim/simx/fpu_unit.cpp
sim/simx/fpu_unit.h
sim/simx/fragment_layout.h
sim/simx/func_unit.h
sim/simx/gbar_unit.cpp
sim/simx/gbar_unit.h
sim/simx/gem5/SConscript
sim/simx/gem5/VortexGPGPU.py
sim/simx/gem5/dev_mem.cpp
sim/simx/gem5/dev_mem.h
sim/simx/gem5/install.sh
sim/simx/gem5/vortex_gpgpu.cpp
sim/simx/gem5/vortex_gpgpu.h
sim/simx/gem5/vortex_gpgpu_dev.cc
sim/simx/gem5/vortex_gpgpu_dev.hh
sim/simx/gfx_doctrine.h
sim/simx/instr.h
sim/simx/instr_trace.h
sim/simx/kmu/kmu.cpp
sim/simx/kmu/kmu.h
sim/simx/lsu_unit.cpp
sim/simx/lsu_unit.h
sim/simx/main.cpp
sim/simx/mem/addr_hash.h
sim/simx/mem/cache.cpp
sim/simx/mem/cache.h
sim/simx/mem/cache_cluster.cpp
sim/simx/mem/cache_cluster.h
sim/simx/mem/local_mem.cpp
sim/simx/mem/local_mem.h
sim/simx/mem/local_mem_switch.cpp
sim/simx/mem/local_mem_switch.h
sim/simx/mem/lsu_mem_adapter.cpp
sim/simx/mem/lsu_mem_adapter.h
sim/simx/mem/mem_block_pool.h
sim/simx/mem/mem_coalescer.cpp
sim/simx/mem/mem_coalescer.h
sim/simx/mem/memory.cpp
sim/simx/mem/memory.h
sim/simx/mem/mmu.cpp
sim/simx/mem/mmu.h
sim/simx/mem/mmu_tlb.cpp
sim/simx/mem/mmu_tlb.h
sim/simx/mem/ptw.cpp
sim/simx/mem/ptw.h
sim/simx/mem/tlb_l2.cpp
sim/simx/mem/tlb_l2.h
sim/simx/mem/tlb_types.h
sim/simx/mpm_transport.mk
sim/simx/mufu_unit.cpp
sim/simx/mufu_unit.h
sim/simx/om/om_core.cpp
sim/simx/om/om_core.h
sim/simx/om/om_unit.cpp
sim/simx/om/om_unit.h
sim/simx/opc_unit.cpp
sim/simx/opc_unit.h
sim/simx/operands.cpp
sim/simx/operands.h
sim/simx/processor.cpp
sim/simx/processor.h
sim/simx/processor_impl.h
sim/simx/raster/raster_core.cpp
sim/simx/raster/raster_core.h
sim/simx/raster/raster_unit.h
sim/simx/regslice.h
sim/simx/rtu/rtu_bvh.h
sim/simx/rtu/rtu_classifier.cpp
sim/simx/rtu/rtu_classifier.h
sim/simx/rtu/rtu_core.cpp
sim/simx/rtu/rtu_core.h
sim/simx/rtu/rtu_isect.cpp
sim/simx/rtu/rtu_isect.h
sim/simx/rtu/rtu_memory.cpp
sim/simx/rtu/rtu_memory.h
sim/simx/rtu/rtu_raylog.cpp
sim/simx/rtu/rtu_raylog.h
sim/simx/rtu/rtu_types.h
sim/simx/rtu/rtu_unit.cpp
sim/simx/rtu/rtu_unit.h
sim/simx/rtu/rtu_walker.cpp
sim/simx/rtu/rtu_walker.h
sim/simx/rtu/rtu_window.h
sim/simx/scheduler.cpp
sim/simx/scheduler.h
sim/simx/scoreboard.cpp
sim/simx/scoreboard.h
sim/simx/sequencer.cpp
sim/simx/sequencer.h
sim/simx/sfu_unit.cpp
sim/simx/sfu_unit.h
sim/simx/socket.cpp
sim/simx/socket.h
sim/simx/sst/vortex_gpgpu.cpp
sim/simx/sst/vortex_gpgpu.h
sim/simx/sst/vortex_simulator.cpp
sim/simx/sst/vortex_simulator.h
sim/simx/stack_interleave.h
sim/simx/tcu/tcu_tbuf.cpp
sim/simx/tcu/tcu_tbuf.h
sim/simx/tcu/tcu_unit.cpp
sim/simx/tcu/tcu_unit.h
sim/simx/tex/tex_core.cpp
sim/simx/tex/tex_core.h
sim/simx/tex/tex_unit.cpp
sim/simx/tex/tex_unit.h
sim/simx/types.h
sim/simx/wctl_unit.cpp
sim/simx/wctl_unit.h
sim/xrtsim/Makefile
sim/xrtsim/verilator.vlt.in
sim/xrtsim/vortex_afu_shim.sv
sim/xrtsim/xrt_c.cpp
sim/xrtsim/xrt_c.h
sim/xrtsim/xrt_sim.cpp
sim/xrtsim/xrt_sim.h
sw/common/ai_matmul_args.h
sw/common/ai_matmul_profile.h
sw/common/bitmanip.h
sw/common/bitvector.h
sw/common/dram_timing.h
sw/common/dxa_meta.h
sw/common/fedp.h
sw/common/gfx_dcr.h
sw/common/gfx_ff_model.cpp
sw/common/gfx_ff_model.h
sw/common/gfx_frag_rast.h
sw/common/gfx_frag_tex.h
sw/common/gfx_frontend_abi.h
sw/common/gfx_fs_desc_abi.h
sw/common/gfx_setup.h
sw/common/gfx_sw.h
sw/common/gfx_sw_abi.h
sw/common/gfx_tex_const.h
sw/common/linked_list.h
sw/common/mem_alloc.h
sw/common/mempool.h
sw/common/mp_macros.h
sw/common/mufu.cpp
sw/common/mufu.h
sw/common/mufu_tables.h
sw/common/nan_box.h
sw/common/ringqueue.h
sw/common/rtu_cfg.h
sw/common/rvfloats.cpp
sw/common/rvfloats.h
sw/common/smallfunc.h
sw/common/softfloat_ext.cpp
sw/common/softfloat_ext.h
sw/common/stringutil.h
sw/common/tensor_cfg.h
sw/common/util.cpp
sw/common/util.h
sw/common/v80_pcie.h
sw/common/vm_types.h
sw/common/vx_gfx_abi.h
sw/common/vx_tex_lod.h
sw/runtime/common/async_run.h
tests/unittest/checked_counters/access_cache.cpp
tests/unittest/checked_counters/access_memory.cpp
tests/unittest/checked_counters/access_socket.cpp
tests/unittest/checked_counters/access_tcu.cpp
tests/unittest/checked_counters/counter_access.cpp
tests/unittest/checked_counters/counter_access.h
tests/unittest/checked_counters/main.cpp
vortex_opae.toml
""".strip().splitlines())

_PUBLIC_ADDITIONAL_SOURCE_NAMES = tuple("""
.github/workflows/p06-checked-counters.yml
ci/project/baseline.py
ci/project/baseline_bootstrap.py
ci/project/baseline_host.py
ci/project/baseline_packet.py
ci/project/baseline_packet_export.py
ci/project/baseline_packet_export_fixture.py
ci/project/baseline_packet_fixture.py
ci/project/check_baseline_packets.py
ci/project/check_project.py
ci/project/fixtures/checked_counter_public.cpp
ci/project/fixtures/p02_layout_v1.json
ci/project/fixtures/p02_tfr_v1.json
ci/project/fixtures/p02_wgmma_host_stub.cpp
ci/project/fixtures/p02_wgmma_v1.json
ci/project/fixtures/p02_wmma_numerical_v1.json
ci/project/fixtures/p02_wmma_runtime_stub.cpp
ci/project/fixtures/p03_device_reader_test.cpp
ci/project/fixtures/p03_managed_runtime_test.cpp
ci/project/fixtures/p03_operator_contract_test.cpp
ci/project/fixtures/p04_app_contract_test.cpp
ci/project/fixtures/p04_host_bridge_test.cpp
ci/project/fixtures/p04_mlp_runtime_test.cpp
ci/project/fixtures/p04_tiny_mlp_v1.json
ci/project/fixtures/p05_python_runtime.cpp
ci/project/fixtures/p06_checked_counter_test.cpp
ci/project/fixtures/p06_mpm_transport_host.cpp
ci/project/fixtures/p06_observer_api.cpp
ci/project/fixtures/p06_observer_caller.cpp
ci/project/fixtures/p06_warm_caller_backend.cpp
ci/project/fixtures/p06_warm_observer_test.cpp
ci/project/fixtures/p06_workspace_caller_backend.cpp
ci/project/fixtures/p06_workspace_edge_test.cpp
ci/project/fixtures/p06_workspace_model_guard_test.cpp
ci/project/fixtures/p06_workspace_runtime_test.cpp
ci/project/fixtures/simulator_async_run_test.cpp
ci/project/fixtures/simulator_completion/control.h
ci/project/fixtures/simulator_completion/main.cpp
ci/project/fixtures/simulator_completion/mem.h
ci/project/fixtures/simulator_completion/processor.h
ci/project/fixtures/simulator_error_boundary.cpp
ci/project/fixtures/simulator_error_boundary_control.h
ci/project/fixtures/simulator_error_boundary_processor.h
ci/project/fixtures/simulator_platform_cleanup.cpp
ci/project/fixtures/simulator_public_completion.cpp
ci/project/hwemu.py
ci/project/hwemu_build.py
ci/project/hwemu_contract.py
ci/project/hwemu_fixture.py
ci/project/hwemu_inventory.py
ci/project/hwemu_io.py
ci/project/hwemu_plan.py
ci/project/hwemu_source.py
ci/project/local_qualification.py
ci/project/local_qualification_cases.py
ci/project/local_qualification_inventory.py
ci/project/p01_baseline.json
ci/project/p01_toolchain.lock.json
ci/project/p01_xrt_environment.example.json
ci/project/p02_api_compile.py
ci/project/p02_fixture_oracle.py
ci/project/p02_layout_fixture_oracle.py
ci/project/p02_matrix.py
ci/project/p02_tensor_contract.json
ci/project/p02_wgmma_dependencies.py
ci/project/p02_wgmma_fixture_oracle.py
ci/project/p02_wgmma_matrix.json
ci/project/p02_wgmma_matrix.py
ci/project/p02_wgmma_packet.py
ci/project/p02_wgmma_records.py
ci/project/p02_wgmma_unit.py
ci/project/p02_wgmma_witness.py
ci/project/p02_wmma_fixtures.py
ci/project/p02_wmma_numerical_fixture_oracle.py
ci/project/p03_execute.py
ci/project/p03_execution_records.py
ci/project/p03_operator_manifest.json
ci/project/p04_catalog.py
ci/project/p04_ci_prepare.py
ci/project/p04_execute.py
ci/project/p04_execution_records.py
ci/project/p04_fixture_adapter.py
ci/project/p04_model_contract.py
ci/project/p04_model_manifest.json
ci/project/p04_reference.py
ci/project/p05_bundle.py
ci/project/p05_bundle_test_fixture.py
ci/project/p05_execute.py
ci/project/p05_execution_records.py
ci/project/p05_installed_check.py
ci/project/p05_qualification_test_fixture.py
ci/project/p05_test_runtime.py
ci/project/p05_torch_contract.json
ci/project/p05_torch_execute.py
ci/project/p05_torch_host_tests.py
ci/project/p05_torch_installed_check.py
ci/project/p05_torch_native_host_tests.py
ci/project/p05_torch_qualification_test_fixture.py
ci/project/p05_torch_records.py
ci/project/p05_torch_requirements.lock
ci/project/p06_analyze.py
ci/project/p06_benchmark_contract.json
ci/project/p06_contract.py
ci/project/p06_counter_public_build.py
ci/project/p06_counter_public_execute.py
ci/project/p06_counter_public_records.py
ci/project/p06_execute.py
ci/project/p06_mpm_parent.py
ci/project/p06_mpm_synthesis.py
ci/project/p06_records.py
ci/project/p06_replay.py
ci/project/p06_simulator_execute.py
ci/project/p06_simulator_parent.py
ci/project/p06_test_frozen_sources.py
ci/project/p06_test_packets.py
ci/project/p06_test_samples.py
ci/project/p06_warm_analyze.py
ci/project/p06_warm_compiler_records.py
ci/project/p06_warm_contract.json
ci/project/p06_warm_contract.py
ci/project/p06_warm_execute.py
ci/project/p06_warm_records.py
ci/project/p06_warm_replay.py
ci/project/p06_warm_test_fixture.py
ci/project/p06_warm_test_packets.py
ci/project/p06_workspace_compiler_records.py
ci/project/p06_workspace_contract.json
ci/project/p06_workspace_execute.py
ci/project/p06_workspace_records.py
ci/project/p06_workspace_replay.py
ci/project/p06_workspace_test_samples.py
ci/project/tensor_host_tools.py
ci/project/test_adversarial.py
ci/project/test_ai_profile.py
ci/project/test_baseline.py
ci/project/test_baseline_bootstrap.py
ci/project/test_baseline_build_identity.py
ci/project/test_baseline_host.py
ci/project/test_baseline_identity.py
ci/project/test_baseline_inventory.py
ci/project/test_baseline_matrix.py
ci/project/test_baseline_packet.py
ci/project/test_baseline_packet_ci.py
ci/project/test_baseline_packet_containment.py
ci/project/test_baseline_packet_contract.py
ci/project/test_baseline_packet_export.py
ci/project/test_baseline_packet_interruptions.py
ci/project/test_baseline_packet_io.py
ci/project/test_baseline_packet_matrix_versions.py
ci/project/test_baseline_packet_operands.py
ci/project/test_baseline_packet_provenance.py
ci/project/test_baseline_packet_stamps.py
ci/project/test_baseline_packet_xlen.py
ci/project/test_baseline_process.py
ci/project/test_check_project.py
ci/project/test_compiler_records_generated.py
ci/project/test_compiler_records_oracle.py
ci/project/test_configure_headers.py
ci/project/test_hwemu_arch.py
ci/project/test_hwemu_build.py
ci/project/test_hwemu_cli.py
ci/project/test_hwemu_cli_integration.py
ci/project/test_hwemu_contract.py
ci/project/test_hwemu_flags.py
ci/project/test_hwemu_git_environment.py
ci/project/test_hwemu_inventory.py
ci/project/test_hwemu_io.py
ci/project/test_hwemu_membership.py
ci/project/test_hwemu_plan.py
ci/project/test_hwemu_resources.py
ci/project/test_hwemu_shell.py
ci/project/test_hwemu_source.py
ci/project/test_local_qualification_cases.py
ci/project/test_local_qualification_cli.py
ci/project/test_local_qualification_generated.py
ci/project/test_local_qualification_identity.py
ci/project/test_local_qualification_inventory.py
ci/project/test_local_qualification_process.py
ci/project/test_local_qualification_runner.py
ci/project/test_markdown_edges.py
ci/project/test_p02_api_compile.py
ci/project/test_p02_build_contract.py
ci/project/test_p02_layout_contract.py
ci/project/test_p02_matrix.py
ci/project/test_p02_simx_config.py
ci/project/test_p02_tensor_catalog.py
ci/project/test_p02_tensor_contract.py
ci/project/test_p02_wgmma_adapter.py
ci/project/test_p02_wgmma_assertions.py
ci/project/test_p02_wgmma_catalog.py
ci/project/test_p02_wgmma_dependencies.py
ci/project/test_p02_wgmma_fixtures.py
ci/project/test_p02_wgmma_lmem.py
ci/project/test_p02_wgmma_matrix.py
ci/project/test_p02_wgmma_packet.py
ci/project/test_p02_wgmma_retention.py
ci/project/test_p02_wgmma_unit.py
ci/project/test_p02_wgmma_witness.py
ci/project/test_p02_wmma_adapter.py
ci/project/test_p02_wmma_fixtures.py
ci/project/test_p03_device_reader.py
ci/project/test_p03_execution_records.py
ci/project/test_p03_managed_runtime.py
ci/project/test_p03_operator_contract.py
ci/project/test_p04_app_contract.py
ci/project/test_p04_ci_contract.py
ci/project/test_p04_ci_prepare.py
ci/project/test_p04_execution_records.py
ci/project/test_p04_fixture_adapter.py
ci/project/test_p04_host_bridge.py
ci/project/test_p04_mlp_runtime.py
ci/project/test_p04_model_contract.py
ci/project/test_p04_numerics.py
ci/project/test_p04_reference.py
ci/project/test_p04_runner.py
ci/project/test_p05_bundle.py
ci/project/test_p05_bundle_producer.py
ci/project/test_p05_ci_workflow.py
ci/project/test_p05_execution_records.py
ci/project/test_p05_governance_integration.py
ci/project/test_p05_installed_check.py
ci/project/test_p05_launcher.py
ci/project/test_p05_native_binding.py
ci/project/test_p05_orchestration.py
ci/project/test_p05_packaging.py
ci/project/test_p05_python_api.py
ci/project/test_p05_torch_adversarial.py
ci/project/test_p05_torch_ci.py
ci/project/test_p05_torch_contract.py
ci/project/test_p05_torch_native_host_orchestration.py
ci/project/test_p05_torch_orchestration.py
ci/project/test_p05_torch_records.py
ci/project/test_p05_torch_retained_installation.py
ci/project/test_p05_torch_runner_review.py
ci/project/test_p06_analysis_compatibility.py
ci/project/test_p06_analysis_metrics.py
ci/project/test_p06_analyze.py
ci/project/test_p06_checked_ci.py
ci/project/test_p06_checked_counter.py
ci/project/test_p06_checked_execute.py
ci/project/test_p06_checked_integration.py
ci/project/test_p06_checked_public.py
ci/project/test_p06_ci_contract.py
ci/project/test_p06_compiler_records.py
ci/project/test_p06_contract.py
ci/project/test_p06_counter_public_build.py
ci/project/test_p06_counter_public_execute.py
ci/project/test_p06_counter_public_records.py
ci/project/test_p06_mpm_ci.py
ci/project/test_p06_mpm_execute.py
ci/project/test_p06_mpm_parent.py
ci/project/test_p06_mpm_reference.py
ci/project/test_p06_mpm_synthesis.py
ci/project/test_p06_mpm_transport.py
ci/project/test_p06_observer.py
ci/project/test_p06_published_baseline.py
ci/project/test_p06_records.py
ci/project/test_p06_replay.py
ci/project/test_p06_replay_ci.py
ci/project/test_p06_runner.py
ci/project/test_p06_simulator_async_run.py
ci/project/test_p06_simulator_build.py
ci/project/test_p06_simulator_ci.py
ci/project/test_p06_simulator_completion.py
ci/project/test_p06_simulator_error_boundary.py
ci/project/test_p06_simulator_execute.py
ci/project/test_p06_simulator_parent.py
ci/project/test_p06_simulator_platform.py
ci/project/test_p06_simulator_public.py
ci/project/test_p06_simulator_runner_failures.py
ci/project/test_p06_timing.py
ci/project/test_p06_warm_analyze.py
ci/project/test_p06_warm_caller.py
ci/project/test_p06_warm_ci.py
ci/project/test_p06_warm_compiler_records.py
ci/project/test_p06_warm_contract.py
ci/project/test_p06_warm_observer.py
ci/project/test_p06_warm_records.py
ci/project/test_p06_warm_replay.py
ci/project/test_p06_warm_runner.py
ci/project/test_p06_workspace_caller.py
ci/project/test_p06_workspace_ci.py
ci/project/test_p06_workspace_compiler_records.py
ci/project/test_p06_workspace_edges.py
ci/project/test_p06_workspace_model_guard.py
ci/project/test_p06_workspace_records.py
ci/project/test_p06_workspace_replay.py
ci/project/test_p06_workspace_runner.py
ci/project/test_p06_workspace_runtime.py
ci/project/test_preflight.py
ci/project/test_repository_contract.py
ci/project/test_rtl_gate_resources.py
ci/project/test_sst_setup.py
ci/project/test_tensor_exact_cases.py
ci/project/test_tensor_fp32_compare.py
ci/project/test_tensor_int_reference.py
ci/project/test_xrt_baseline.py
ci/project/test_xrt_boundaries.py
ci/project/test_xrt_cancellation.py
ci/project/test_xrt_compiler_execution.py
ci/project/test_xrt_compiler_provenance.py
ci/project/test_xrt_compiler_records.py
ci/project/test_xrt_configuration.py
ci/project/test_xrt_contract.py
ci/project/test_xrt_drift.py
ci/project/test_xrt_elf_compatibility.py
ci/project/test_xrt_generated_build.py
ci/project/test_xrt_inventory.py
ci/project/test_xrt_path_revalidation.py
ci/project/test_xrt_resources.py
ci/project/test_xrt_runtime.py
ci/project/test_xrt_runtime_integration.py
ci/project/test_xrt_source.py
ci/project/test_xrt_tool_selection.py
ci/project/xrt_baseline.py
ci/project/xrt_contract.py
ci/project/xrt_inventory.py
ci/project/xrt_runtime.py
ci/project/xrt_signals.py
ci/project/xrt_source.py
ci/project/xrt_test_support.py
sw/kernel/include/vx_barrier.h
sw/kernel/include/vx_dxa.h
sw/kernel/include/vx_graphics.h
sw/kernel/include/vx_intrinsics.h
sw/kernel/include/vx_mufu.h
sw/kernel/include/vx_print.h
sw/kernel/include/vx_raytrace.h
sw/kernel/include/vx_spawn.h
sw/kernel/include/vx_spawn2.h
sw/kernel/include/vx_tensor.h
sw/runtime/Makefile
sw/runtime/ai/contract.cpp
sw/runtime/ai/contract.h
sw/runtime/ai/mlp_host.cpp
sw/runtime/ai/mlp_host.h
sw/runtime/ai/mlp_runtime.cpp
sw/runtime/ai/mlp_runtime.h
sw/runtime/ai/runtime.cpp
sw/runtime/ai/runtime.h
sw/runtime/aved/Makefile
sw/runtime/aved/vortex.cpp
sw/runtime/common.mk
sw/runtime/common/buffer.cpp
sw/runtime/common/callbacks.h
sw/runtime/common/callbacks.inc
sw/runtime/common/caps.h
sw/runtime/common/common.h
sw/runtime/common/device.cpp
sw/runtime/common/dispatcher.h
sw/runtime/common/event.cpp
sw/runtime/common/graphics.cpp
sw/runtime/common/legacy_runtime.cpp
sw/runtime/common/legacy_utils.cpp
sw/runtime/common/module.cpp
sw/runtime/common/nlohmann_json.hpp
sw/runtime/common/perf.cpp
sw/runtime/common/queue.cpp
sw/runtime/common/result.cpp
sw/runtime/common/runtime_helpers.cpp
sw/runtime/common/scope.cpp
sw/runtime/common/scope.h
sw/runtime/common/utils.cpp
sw/runtime/common/vm.cpp
sw/runtime/common/vm.h
sw/runtime/common/vortex2_internal.h
sw/runtime/firesim/Makefile
sw/runtime/firesim/card.mk
sw/runtime/firesim/vortex.cpp
sw/runtime/firesim/xrt.ini
sw/runtime/foldsim/Makefile
sw/runtime/foldsim/vortex.cpp
sw/runtime/gem5/Makefile
sw/runtime/gem5/driver.cpp
sw/runtime/gem5/driver.h
sw/runtime/gem5/vortex.cpp
sw/runtime/include/dxa.h
sw/runtime/include/graphics.h
sw/runtime/include/raytrace.h
sw/runtime/include/tensor_mx.h
sw/runtime/include/tensor_sp.h
sw/runtime/include/vortex.h
sw/runtime/include/vortex2.h
sw/runtime/opae/Makefile
sw/runtime/opae/driver.cpp
sw/runtime/opae/driver.h
sw/runtime/opae/vortex.cpp
sw/runtime/rtlsim/Makefile
sw/runtime/rtlsim/vortex.cpp
sw/runtime/rtlsim_config.stamp
sw/runtime/simx/Makefile
sw/runtime/simx/vortex.cpp
sw/runtime/stub/Makefile
sw/runtime/stub/vortex.cpp
sw/runtime/vortex-kernel.pc.in
sw/runtime/vortex-runtime.pc.in
sw/runtime/xrt/Makefile
sw/runtime/xrt/vortex.cpp
sw/runtime/xrt/xrt.ini.in
sw/runtime/xrt/xsim.tcl
tests/regression/ai_bench_common/counters.h
tests/regression/ai_bench_common/observer.cpp
tests/unittest/checked_counters/public.mk
tests/unittest/checked_counters/public_hooks.cpp
tests/unittest/checked_counters/public_hooks.h
tests/unittest/checked_counters/public_main.cpp
""".strip().splitlines())


class SourceInventoryError(ValueError):
    """An expected source inventory is unsafe, incomplete or inconsistent."""


def _require(condition, message):
    if not condition:
        raise SourceInventoryError(message)


def _producer(producer_contract_id):
    _require(type(producer_contract_id) is str and producer_contract_id in (
        CHECKED_PRODUCER_CONTRACT_ID, PUBLIC_PRODUCER_CONTRACT_ID),
        "unsupported source inventory producer contract")


def _expectations(expected_revision, producer_contract_id, expected_sha256=None, *, require_sha256=False):
    _producer(producer_contract_id)
    _require(type(expected_revision) is str and REVISION.fullmatch(expected_revision),
             "an external 40-character source revision is required")
    if require_sha256:
        _require(type(expected_sha256) is str and SHA256.fullmatch(expected_sha256),
                 "an external source inventory SHA-256 is required")


def required_source_names(producer_contract_id):
    """Return the complete immutable original inventory after its digest check.

    The digest covers each lexicographically sorted source-relative name followed
    by LF. It pins the full original inventory, including uncompiled headers and
    producer helper bodies, rather than only the compiled translation units.
    """
    _producer(producer_contract_id)
    if producer_contract_id == CHECKED_PRODUCER_CONTRACT_ID:
        names, count, expected = _CHECKED_SOURCE_NAMES, 270, CHECKED_SOURCE_NAMES_SHA256
    else:
        names = tuple(sorted((*_CHECKED_SOURCE_NAMES, *_PUBLIC_ADDITIONAL_SOURCE_NAMES)))
        count, expected = 676, PUBLIC_SOURCE_NAMES_SHA256
    _require(len(names) == count and len(set(names)) == count and tuple(sorted(names)) == names,
             "trusted original source inventory count or order differs")
    digest = hashlib.sha256("".join(name + "\n" for name in names).encode("ascii")).hexdigest()
    _require(digest == expected, "trusted original source inventory digest differs")
    return names


def _source_path(value):
    _require(type(value) is str and 0 < len(value) <= MAX_PATH_BYTES and PATH.fullmatch(value),
             "source inventory path must be a bounded canonical ASCII POSIX relative path")
    parts = value.split("/")
    _require(len(parts) <= MAX_PATH_DEPTH
             and all(part not in (".", "..", ".git") and len(part) <= 255 for part in parts),
             "source inventory path is unsafe or too deep")
    return value


def _sources(rows, producer_contract_id):
    _require(type(rows) is list and 0 < len(rows) <= MAX_SOURCES,
             "source inventory must be a bounded nonempty list")
    required = set(required_source_names(producer_contract_id))
    roots = _CHECKED_ROOTS if producer_contract_id == CHECKED_PRODUCER_CONTRACT_ID else _PUBLIC_ROOTS
    result, names = [], []
    for row in rows:
        _require(type(row) is dict and set(row) == DESCRIPTOR_FIELDS,
                 "source inventory descriptor fields differ")
        name = _source_path(row["path"])
        _require(not names or names[-1] < name,
                 "source inventory paths must be unique and lexicographically sorted")
        _require(name in required or any(name.startswith(root + "/") for root in roots),
                 "source inventory path is outside the reviewed producer roots")
        _require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"]),
                 "source inventory descriptor SHA-256 is invalid")
        _require(type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= MAX_SOURCE_BYTES,
                 "source inventory descriptor size is invalid")
        names.append(name)
        result.append({key: row[key] for key in ("path", "sha256", "size_bytes")})
    _require(required <= set(names), "source inventory omits an original required body")
    return result


def validate_source_inventory(manifest, *, expected_revision, producer_contract_id):
    """Purely validate and copy an expected manifest, without authenticating it.

    A dict has no trusted origin by itself. Readers consuming external files must
    use ``decode_source_inventory`` or ``load_source_inventory`` with a separately
    supplied digest before using these expectations to compare an archive.
    """
    _expectations(expected_revision, producer_contract_id)
    _require(type(manifest) is dict and set(manifest) == MANIFEST_FIELDS,
             "source inventory manifest fields differ")
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
             "source inventory schema version differs")
    _require(type(manifest["contract_id"]) is str and manifest["contract_id"] == CONTRACT_ID,
             "source inventory contract differs")
    _require(type(manifest["producer_contract_id"]) is str
             and manifest["producer_contract_id"] == producer_contract_id,
             "source inventory producer contract differs")
    _require(type(manifest["source_revision"]) is str and manifest["source_revision"] == expected_revision,
             "source inventory revision differs from the externally expected revision")
    return {"schema_version": 1, "contract_id": CONTRACT_ID,
            "producer_contract_id": producer_contract_id, "source_revision": expected_revision,
            "sources": _sources(manifest["sources"], producer_contract_id)}


def decode_source_inventory(contents, *, expected_sha256, expected_revision, producer_contract_id):
    """Hash exact externally supplied manifest bytes, then validate strict JSON.

    The mandatory digest is supplied by the caller, never read from the manifest
    or an archive. Whitespace is included in that digest. A correct digest binds
    expected data; it does not independently authenticate its asserted provenance.
    """
    _expectations(expected_revision, producer_contract_id, expected_sha256, require_sha256=True)
    _require(type(contents) is bytes and 0 < len(contents) <= MAX_MANIFEST_BYTES,
             "source inventory manifest is empty or exceeds its byte limit")
    _require(hashlib.sha256(contents).hexdigest() == expected_sha256,
             "source inventory manifest SHA-256 differs from the external digest")
    try:
        manifest = load_json_bytes(contents, "source inventory manifest")
    except ValueError as error:
        raise SourceInventoryError(str(error)) from error
    return validate_source_inventory(manifest, expected_revision=expected_revision,
                                     producer_contract_id=producer_contract_id)


def load_source_inventory(path, *, expected_sha256, expected_revision, producer_contract_id):
    """Read only one explicitly supplied external manifest with bounded no-follow I/O.

    The trusted PacketReader rejects symlink components and nonregular files,
    bounds the fd read, and compares fd/named-file identities before and after.
    It never receives a source descriptor or a recorded producer path. A failed
    explicit load always raises; there is no fallback to the original inventory.
    """
    _expectations(expected_revision, producer_contract_id, expected_sha256, require_sha256=True)
    try:
        selected = Path(path)
        with PacketReader(selected.parent, max_total_bytes=MAX_MANIFEST_BYTES, max_files=1) as reader:
            contents = reader.read_bytes(selected.name, limit=MAX_MANIFEST_BYTES)
    except (OSError, TypeError, ValueError) as error:
        raise SourceInventoryError("external source inventory cannot be read safely: " + str(error)) from error
    return decode_source_inventory(contents, expected_sha256=expected_sha256,
                                   expected_revision=expected_revision, producer_contract_id=producer_contract_id)


def validate_archive_sources(sources, inventory, *, expected_revision, producer_contract_id):
    """Purely require exact equality of every archive and expected descriptor.

    ``inventory`` must come from the digest-pinned loader/decoder or another
    explicitly trusted caller. Archive bytes still need the reader's independent
    retained-member hash/length validation; descriptor equality cannot do that.
    """
    manifest = validate_source_inventory(inventory, expected_revision=expected_revision,
                                         producer_contract_id=producer_contract_id)
    observed = _sources(sources, producer_contract_id)
    _require(observed == manifest["sources"],
             "archive source descriptors differ from the externally pinned complete inventory")
    return observed
