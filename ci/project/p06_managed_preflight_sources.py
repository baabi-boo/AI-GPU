# SPDX-License-Identifier: Apache-2.0
"""Externally pinned source expectations for inert managed-preflight replay.

Only the explicit manifest path is opened. Source descriptors are inert data;
matching them does not authenticate Git provenance, prove compilation, execute
retained code, or establish counter qualification. The caller must supply the
manifest digest independently of the packet under review.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from baseline_packet_io import PacketReader, load_json_bytes


CONTRACT_ID = "p06-managed-counter-preflight-source-inventory-v1"
PRODUCER_CONTRACT_ID = "p06-managed-counter-preflight-v1"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 20000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_PATH_DEPTH = 64
SOURCE_NAMES_SHA256 = "29d404d27008fa1e83f3110541782a9f641f2d426602cac096477f7f383f4f1a"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
PATH = re.compile(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*\Z")
MANIFEST_FIELDS = {"schema_version", "contract_id", "producer_contract_id", "source_revision", "sources"}
DESCRIPTOR_FIELDS = {"path", "sha256", "size_bytes"}

# Freeze complete known first-party discovery, not only compiled translation
# units. Derived from a fresh trusted producer import plus its lazy records
# import; dirty/untracked additions were excluded without asserting a clean
# checkout. Dependency submodules were absent locally, so their exact populated
# header inventory is an externally pinned extension, never inferred here.
REQUIRED_SOURCE_NAMES = tuple("""
.github/workflows/p04-model.yml
.github/workflows/p06-managed-preflight.yml
.gitmodules
VERSION
VX_config.toml
VX_types.toml
ci/blackbox.sh
ci/gen_config.py
ci/install_dependencies.sh
ci/project/baseline_inventory.py
ci/project/baseline_matrix.py
ci/project/baseline_packet_contract.py
ci/project/baseline_packet_io.py
ci/project/baseline_process.py
ci/project/compiler_records.py
ci/project/fixtures/p02_layout_v1.json
ci/project/fixtures/p02_tfr_v1.json
ci/project/fixtures/p02_wmma_numerical_v1.json
ci/project/p02_fixture_oracle.py
ci/project/p02_layout_fixture_oracle.py
ci/project/p02_matrix.py
ci/project/p02_matrix_records.py
ci/project/p02_tensor_contract.json
ci/project/p02_wmma_fixtures.py
ci/project/p02_wmma_numerical_fixture_oracle.py
ci/project/p03_execute.py
ci/project/p03_execution_records.py
ci/project/p03_operator_manifest.json
ci/project/p04_ci_prepare.py
ci/project/p04_execution_records.py
ci/project/p04_fixture_adapter.py
ci/project/p04_model_contract.py
ci/project/p04_reference.py
ci/project/p06_compiler_records.py
ci/project/p06_contract.py
ci/project/p06_managed_preflight_build.py
ci/project/p06_managed_preflight_contract.py
ci/project/p06_managed_preflight_execute.py
ci/project/p06_managed_preflight_records.py
ci/project/p06_records.py
ci/project/p06_warm_compiler_records.py
ci/project/p06_warm_contract.json
ci/project/p06_warm_contract.py
ci/project/p06_warm_execute.py
ci/project/p06_warm_records.py
ci/project/p06_workspace_compiler_records.py
ci/project/p06_workspace_records.py
ci/project/preflight.py
ci/toolchain_rev.sh
config.mk.in
configure
docs/designs/ai_operator_contract_v1.md
docs/designs/managed_counter_preflight_v1.md
docs/designs/serial_matmul_workspace_v1.md
docs/designs/simx_counter_lifetime_v1.md
docs/designs/tensor_numerics_v1.md
docs/designs/warm_workspace_benchmark_v1.md
hw/dpi/dpi_float.cpp
hw/dpi/dpi_float.vh
hw/dpi/dpi_util.cpp
hw/dpi/dpi_util.vh
hw/rtl/VX_cluster.sv
hw/rtl/VX_define.vh
hw/rtl/VX_gpu_pkg.sv
hw/rtl/VX_graphics.sv
hw/rtl/VX_kmu.sv
hw/rtl/VX_platform.vh
hw/rtl/VX_scope.vh
hw/rtl/VX_socket.sv
hw/rtl/VX_trace_pkg.sv
hw/rtl/Vortex.sv
hw/rtl/Vortex_axi.sv
hw/rtl/afu/aved/vortex_afu.v
hw/rtl/afu/common/VX_afu_axi_drain.sv
hw/rtl/afu/common/VX_afu_axil_demux.sv
hw/rtl/afu/common/VX_afu_ctrl.sv
hw/rtl/afu/common/VX_afu_req_gate.sv
hw/rtl/afu/common/VX_afu_reset_seq.sv
hw/rtl/afu/common/VX_afu_wr_gate.sv
hw/rtl/afu/common/VX_afu_wrap.sv
hw/rtl/afu/common/vortex_afu.vh
hw/rtl/afu/firesim/VX_firesim_wrap.sv
hw/rtl/afu/firesim/toy/VX_adder4.v
hw/rtl/afu/foldsim/target/foldsim_target.sv
hw/rtl/afu/opae/ccip/ccip_if_pkg.sv
hw/rtl/afu/opae/ccip_interface_reg.sv
hw/rtl/afu/opae/ccip_std_afu.sv
hw/rtl/afu/opae/local_mem_cfg_pkg.sv
hw/rtl/afu/opae/vortex_afu.sv
hw/rtl/afu/xrt/vortex_afu.v
hw/rtl/cache/VX_amo_alu.sv
hw/rtl/cache/VX_amo_unit.sv
hw/rtl/cache/VX_cache.sv
hw/rtl/cache/VX_cache_amo.sv
hw/rtl/cache/VX_cache_bank.sv
hw/rtl/cache/VX_cache_bypass.sv
hw/rtl/cache/VX_cache_cluster.sv
hw/rtl/cache/VX_cache_data.sv
hw/rtl/cache/VX_cache_define.vh
hw/rtl/cache/VX_cache_flush.sv
hw/rtl/cache/VX_cache_init.sv
hw/rtl/cache/VX_cache_mshr.sv
hw/rtl/cache/VX_cache_repl.sv
hw/rtl/cache/VX_cache_tags.sv
hw/rtl/cache/VX_cache_wrap.sv
hw/rtl/core/VX_alu_block.sv
hw/rtl/core/VX_alu_int.sv
hw/rtl/core/VX_alu_muldiv.sv
hw/rtl/core/VX_alu_unit.sv
hw/rtl/core/VX_backend_slice.sv
hw/rtl/core/VX_bar_unit.sv
hw/rtl/core/VX_commit.sv
hw/rtl/core/VX_commit_slice.sv
hw/rtl/core/VX_compute_slice.sv
hw/rtl/core/VX_core.sv
hw/rtl/core/VX_csr_cta.sv
hw/rtl/core/VX_csr_data.sv
hw/rtl/core/VX_csr_fpu.sv
hw/rtl/core/VX_csr_mpm.sv
hw/rtl/core/VX_csr_unit.sv
hw/rtl/core/VX_cta_dispatch.sv
hw/rtl/core/VX_dcr_arb.sv
hw/rtl/core/VX_dcr_data.sv
hw/rtl/core/VX_dcr_flush.sv
hw/rtl/core/VX_decode.sv
hw/rtl/core/VX_decompressor.sv
hw/rtl/core/VX_dispatcher.sv
hw/rtl/core/VX_execute.sv
hw/rtl/core/VX_execute_slice.sv
hw/rtl/core/VX_fetch.sv
hw/rtl/core/VX_frontend_slice.sv
hw/rtl/core/VX_frontend_xbar.sv
hw/rtl/core/VX_gfx_uops.sv
hw/rtl/core/VX_ibuffer.sv
hw/rtl/core/VX_ipdom_stack.sv
hw/rtl/core/VX_issue.sv
hw/rtl/core/VX_issue_slice.sv
hw/rtl/core/VX_kmu_bus_arb.sv
hw/rtl/core/VX_lane_dispatch.sv
hw/rtl/core/VX_lane_gather.sv
hw/rtl/core/VX_lsu_agu.sv
hw/rtl/core/VX_lsu_block.sv
hw/rtl/core/VX_lsu_mem_path.sv
hw/rtl/core/VX_lsu_scheduler.sv
hw/rtl/core/VX_lsu_unit.sv
hw/rtl/core/VX_mem_unit.sv
hw/rtl/core/VX_opc_unit.sv
hw/rtl/core/VX_operands.sv
hw/rtl/core/VX_pe_switch.sv
hw/rtl/core/VX_scheduler.sv
hw/rtl/core/VX_scoreboard.sv
hw/rtl/core/VX_sfu_block.sv
hw/rtl/core/VX_sfu_shared.sv
hw/rtl/core/VX_sfu_unit.sv
hw/rtl/core/VX_split_join.sv
hw/rtl/core/VX_txbar_arb.sv
hw/rtl/core/VX_uop_amo.sv
hw/rtl/core/VX_uop_packld.sv
hw/rtl/core/VX_uop_sequencer.sv
hw/rtl/core/VX_uuid_gen.sv
hw/rtl/core/VX_warp_sched.sv
hw/rtl/core/VX_warp_shared_unit.sv
hw/rtl/core/VX_wctl_unit.sv
hw/rtl/cp/VX_cp_arbiter.sv
hw/rtl/cp/VX_cp_axil_regfile.sv
hw/rtl/cp/VX_cp_axil_s_if.sv
hw/rtl/cp/VX_cp_completion.sv
hw/rtl/cp/VX_cp_core.sv
hw/rtl/cp/VX_cp_dcr_proxy.sv
hw/rtl/cp/VX_cp_dma.sv
hw/rtl/cp/VX_cp_engine.sv
hw/rtl/cp/VX_cp_engine_bid_if.sv
hw/rtl/cp/VX_cp_event_unit.sv
hw/rtl/cp/VX_cp_fetch.sv
hw/rtl/cp/VX_cp_gpu_if.sv
hw/rtl/cp/VX_cp_gpu_slice.sv
hw/rtl/cp/VX_cp_launch.sv
hw/rtl/cp/VX_cp_pkg.sv
hw/rtl/cp/VX_cp_profiling.sv
hw/rtl/cp/VX_cp_unpack.sv
hw/rtl/dxa/VX_dxa_addr_gen.sv
hw/rtl/dxa/VX_dxa_completion.sv
hw/rtl/dxa/VX_dxa_core.sv
hw/rtl/dxa/VX_dxa_desc_table.sv
hw/rtl/dxa/VX_dxa_dispatch.sv
hw/rtl/dxa/VX_dxa_gmem_req.sv
hw/rtl/dxa/VX_dxa_pkg.sv
hw/rtl/dxa/VX_dxa_req_arb.sv
hw/rtl/dxa/VX_dxa_req_bus_if.sv
hw/rtl/dxa/VX_dxa_setup.sv
hw/rtl/dxa/VX_dxa_smem_wr.sv
hw/rtl/dxa/VX_dxa_unit.sv
hw/rtl/dxa/VX_dxa_watchdog.sv
hw/rtl/dxa/VX_dxa_worker.sv
hw/rtl/dxa/VX_dxa_worker_req_if.sv
hw/rtl/fpu/VX_fcvt_unit.sv
hw/rtl/fpu/VX_fdiv_unit.sv
hw/rtl/fpu/VX_fdiv_unit_rtl.sv
hw/rtl/fpu/VX_fdivsqrt_unit.sv
hw/rtl/fpu/VX_fma_unit.sv
hw/rtl/fpu/VX_fma_unit_rtl.sv
hw/rtl/fpu/VX_fncp_unit.sv
hw/rtl/fpu/VX_fp_classifier.sv
hw/rtl/fpu/VX_fp_rounding.sv
hw/rtl/fpu/VX_fpu_block.sv
hw/rtl/fpu/VX_fpu_csr_if.sv
hw/rtl/fpu/VX_fpu_define.vh
hw/rtl/fpu/VX_fpu_dpi.sv
hw/rtl/fpu/VX_fpu_dsp.sv
hw/rtl/fpu/VX_fpu_fpnew.sv
hw/rtl/fpu/VX_fpu_pkg.sv
hw/rtl/fpu/VX_fpu_std.sv
hw/rtl/fpu/VX_fpu_unit.sv
hw/rtl/fpu/VX_fsqrt_unit.sv
hw/rtl/fpu/VX_fsqrt_unit_rtl.sv
hw/rtl/interfaces/VX_branch_ctl_if.sv
hw/rtl/interfaces/VX_commit_if.sv
hw/rtl/interfaces/VX_commit_sched_if.sv
hw/rtl/interfaces/VX_dcr_bus_if.sv
hw/rtl/interfaces/VX_dcr_csr_if.sv
hw/rtl/interfaces/VX_dcr_flush_if.sv
hw/rtl/interfaces/VX_decode_if.sv
hw/rtl/interfaces/VX_decode_sched_if.sv
hw/rtl/interfaces/VX_dispatch_if.sv
hw/rtl/interfaces/VX_execute_if.sv
hw/rtl/interfaces/VX_fetch_if.sv
hw/rtl/interfaces/VX_ibuffer_if.sv
hw/rtl/interfaces/VX_issue_sched_if.sv
hw/rtl/interfaces/VX_kmu_bus_if.sv
hw/rtl/interfaces/VX_lsu_sched_if.sv
hw/rtl/interfaces/VX_operands_if.sv
hw/rtl/interfaces/VX_result_if.sv
hw/rtl/interfaces/VX_sched_csr_if.sv
hw/rtl/interfaces/VX_sched_unlock_if.sv
hw/rtl/interfaces/VX_schedule_if.sv
hw/rtl/interfaces/VX_scoreboard_if.sv
hw/rtl/interfaces/VX_sfu_csr_if.sv
hw/rtl/interfaces/VX_slice_sched_if.sv
hw/rtl/interfaces/VX_txbar_bus_if.sv
hw/rtl/interfaces/VX_warp_ctl_if.sv
hw/rtl/interfaces/VX_warp_shared_if.sv
hw/rtl/interfaces/VX_writeback_if.sv
hw/rtl/libs/VX_1rw1r_ram.sv
hw/rtl/libs/VX_allocator.sv
hw/rtl/libs/VX_axi_write_ack.sv
hw/rtl/libs/VX_bits_concat.sv
hw/rtl/libs/VX_bits_insert.sv
hw/rtl/libs/VX_bits_remove.sv
hw/rtl/libs/VX_bypass_buffer.sv
hw/rtl/libs/VX_clockgate.sv
hw/rtl/libs/VX_csa_32.sv
hw/rtl/libs/VX_csa_42.sv
hw/rtl/libs/VX_csa_mod4.sv
hw/rtl/libs/VX_csa_tree.sv
hw/rtl/libs/VX_cyclic_arbiter.sv
hw/rtl/libs/VX_delay_buffer.sv
hw/rtl/libs/VX_demux.sv
hw/rtl/libs/VX_divider.sv
hw/rtl/libs/VX_dp_ram.sv
hw/rtl/libs/VX_edge_trigger.sv
hw/rtl/libs/VX_elastic_adapter.sv
hw/rtl/libs/VX_elastic_buffer.sv
hw/rtl/libs/VX_fanout_buffer.sv
hw/rtl/libs/VX_fifo_queue.sv
hw/rtl/libs/VX_find_first.sv
hw/rtl/libs/VX_fold_mul.sv
hw/rtl/libs/VX_generic_arbiter.sv
hw/rtl/libs/VX_gto_arbiter.sv
hw/rtl/libs/VX_index_buffer.sv
hw/rtl/libs/VX_index_queue.sv
hw/rtl/libs/VX_ks_adder.sv
hw/rtl/libs/VX_lzc.sv
hw/rtl/libs/VX_matrix_arbiter.sv
hw/rtl/libs/VX_mem_bank_adapter.sv
hw/rtl/libs/VX_mem_coalescer.sv
hw/rtl/libs/VX_mem_data_adapter.sv
hw/rtl/libs/VX_mem_from_axi.sv
hw/rtl/libs/VX_mem_scheduler.sv
hw/rtl/libs/VX_mem_to_avs.sv
hw/rtl/libs/VX_mem_to_axi.sv
hw/rtl/libs/VX_mm_axi_arb.sv
hw/rtl/libs/VX_mm_axi_slice.sv
hw/rtl/libs/VX_mm_axi_xbar.sv
hw/rtl/libs/VX_multiplier.sv
hw/rtl/libs/VX_mux.sv
hw/rtl/libs/VX_nz_iterator.sv
hw/rtl/libs/VX_onehot_encoder.sv
hw/rtl/libs/VX_onehot_mux.sv
hw/rtl/libs/VX_onehot_shift.sv
hw/rtl/libs/VX_pe_serializer.sv
hw/rtl/libs/VX_pending_size.sv
hw/rtl/libs/VX_pipe_buffer.sv
hw/rtl/libs/VX_pipe_register.sv
hw/rtl/libs/VX_popcount.sv
hw/rtl/libs/VX_priority_arbiter.sv
hw/rtl/libs/VX_priority_encoder.sv
hw/rtl/libs/VX_reduce_tree.sv
hw/rtl/libs/VX_reset_relay.sv
hw/rtl/libs/VX_rom.sv
hw/rtl/libs/VX_rr_arbiter.sv
hw/rtl/libs/VX_scan.sv
hw/rtl/libs/VX_scope_switch.sv
hw/rtl/libs/VX_scope_tap.sv
hw/rtl/libs/VX_serial_div.sv
hw/rtl/libs/VX_serial_mul.sv
hw/rtl/libs/VX_shift_register.sv
hw/rtl/libs/VX_skid_buffer.sv
hw/rtl/libs/VX_sp_ram.sv
hw/rtl/libs/VX_stream_arb.sv
hw/rtl/libs/VX_stream_buffer.sv
hw/rtl/libs/VX_stream_dispatch.sv
hw/rtl/libs/VX_stream_fork.sv
hw/rtl/libs/VX_stream_join.sv
hw/rtl/libs/VX_stream_omega.sv
hw/rtl/libs/VX_stream_pack.sv
hw/rtl/libs/VX_stream_switch.sv
hw/rtl/libs/VX_stream_unpack.sv
hw/rtl/libs/VX_stream_xbar.sv
hw/rtl/libs/VX_stream_xpoint.sv
hw/rtl/libs/VX_ticket_lock.sv
hw/rtl/libs/VX_toggle_buffer.sv
hw/rtl/libs/VX_transpose.sv
hw/rtl/libs/VX_wallace_mul.sv
hw/rtl/mem/VX_cp_llc_port.sv
hw/rtl/mem/VX_gbar_arb.sv
hw/rtl/mem/VX_gbar_bus_if.sv
hw/rtl/mem/VX_gbar_unit.sv
hw/rtl/mem/VX_lmem_engine.sv
hw/rtl/mem/VX_lmem_switch.sv
hw/rtl/mem/VX_lmem_unit.sv
hw/rtl/mem/VX_lsu_adapter.sv
hw/rtl/mem/VX_lsu_mem_arb.sv
hw/rtl/mem/VX_lsu_mem_if.sv
hw/rtl/mem/VX_mem_axi_arb.sv
hw/rtl/mem/VX_mem_axi_if.sv
hw/rtl/mem/VX_mem_axi_slice.sv
hw/rtl/mem/VX_mem_axi_xbar.sv
hw/rtl/mem/VX_mem_bus_arb.sv
hw/rtl/mem/VX_mem_bus_delay.sv
hw/rtl/mem/VX_mem_bus_if.sv
hw/rtl/mem/VX_mem_bus_slice.sv
hw/rtl/mem/VX_mem_bus_switch.sv
hw/rtl/mem/VX_mem_req_pending.sv
hw/rtl/mem/VX_mem_xbar.sv
hw/rtl/mem/VX_membus_from_axi.sv
hw/rtl/mem/VX_membus_to_axi.sv
hw/rtl/mufu/VX_mufu_pe.sv
hw/rtl/mufu/VX_mufu_rom.sv
hw/rtl/mufu/VX_mufu_unit.sv
hw/rtl/om/VX_om_blend.sv
hw/rtl/om/VX_om_blend_func.sv
hw/rtl/om/VX_om_blend_minmax.sv
hw/rtl/om/VX_om_blend_multadd.sv
hw/rtl/om/VX_om_bus_arb.sv
hw/rtl/om/VX_om_bus_if.sv
hw/rtl/om/VX_om_compare.sv
hw/rtl/om/VX_om_core.sv
hw/rtl/om/VX_om_dcr.sv
hw/rtl/om/VX_om_define.vh
hw/rtl/om/VX_om_ds.sv
hw/rtl/om/VX_om_ingress.sv
hw/rtl/om/VX_om_logic_op.sv
hw/rtl/om/VX_om_mem.sv
hw/rtl/om/VX_om_perf_if.sv
hw/rtl/om/VX_om_pkg.sv
hw/rtl/om/VX_om_steer.sv
hw/rtl/om/VX_om_stencil_op.sv
hw/rtl/raster/VX_raster_be.sv
hw/rtl/raster/VX_raster_bus_arb.sv
hw/rtl/raster/VX_raster_bus_if.sv
hw/rtl/raster/VX_raster_core.sv
hw/rtl/raster/VX_raster_dcr.sv
hw/rtl/raster/VX_raster_define.vh
hw/rtl/raster/VX_raster_earlyz.sv
hw/rtl/raster/VX_raster_edge.sv
hw/rtl/raster/VX_raster_extents.sv
hw/rtl/raster/VX_raster_launch.sv
hw/rtl/raster/VX_raster_launch_fork.sv
hw/rtl/raster/VX_raster_launch_if.sv
hw/rtl/raster/VX_raster_mem.sv
hw/rtl/raster/VX_raster_packer.sv
hw/rtl/raster/VX_raster_perf_if.sv
hw/rtl/raster/VX_raster_pkg.sv
hw/rtl/raster/VX_raster_qe.sv
hw/rtl/raster/VX_raster_slice.sv
hw/rtl/raster/VX_raster_te.sv
hw/rtl/rtu/VX_rtu_box_pe.sv
hw/rtl/rtu/VX_rtu_bus_arb.sv
hw/rtl/rtu/VX_rtu_bus_if.sv
hw/rtl/rtu/VX_rtu_bus_slice.sv
hw/rtl/rtu/VX_rtu_core.sv
hw/rtl/rtu/VX_rtu_node_decode.sv
hw/rtl/rtu/VX_rtu_pkg.sv
hw/rtl/rtu/VX_rtu_recip.sv
hw/rtl/rtu/VX_rtu_scheduler.sv
hw/rtl/rtu/VX_rtu_tri_pe.sv
hw/rtl/rtu/VX_rtu_unit.sv
hw/rtl/rtu/VX_rtu_xform.sv
hw/rtl/tcu/VX_tcu_abuf.sv
hw/rtl/tcu/VX_tcu_agu.sv
hw/rtl/tcu/VX_tcu_bbuf.sv
hw/rtl/tcu/VX_tcu_block.sv
hw/rtl/tcu/VX_tcu_core.sv
hw/rtl/tcu/VX_tcu_dsm.sv
hw/rtl/tcu/VX_tcu_lockstep.sv
hw/rtl/tcu/VX_tcu_meta.sv
hw/rtl/tcu/VX_tcu_mx_scale.sv
hw/rtl/tcu/VX_tcu_pkg.sv
hw/rtl/tcu/VX_tcu_shared.sv
hw/rtl/tcu/VX_tcu_sp_mux.sv
hw/rtl/tcu/VX_tcu_tbuf.sv
hw/rtl/tcu/VX_tcu_unit.sv
hw/rtl/tcu/VX_tcu_uops.sv
hw/rtl/tcu/VX_tcu_wgmma.sv
hw/rtl/tcu/bhf/HardFloat_consts.vi
hw/rtl/tcu/bhf/HardFloat_localFuncs.vi
hw/rtl/tcu/bhf/VX_tcu_bhf_fadd.sv
hw/rtl/tcu/bhf/VX_tcu_bhf_fmul.sv
hw/rtl/tcu/bhf/VX_tcu_bhf_fp8mul.sv
hw/rtl/tcu/bhf/VX_tcu_fedp_bhf.sv
hw/rtl/tcu/bhf/bsg_counting_leading_zeros.sv
hw/rtl/tcu/dpi/VX_tcu_fedp_dpi.sv
hw/rtl/tcu/dsp/VX_tcu_fedp_dsp.sv
hw/rtl/tcu/fpnew/VX_tcu_fedp_fpnew.sv
hw/rtl/tcu/fpnew/VX_tcu_fpnew_addfp32.sv
hw/rtl/tcu/fpnew/VX_tcu_fpnew_mulfp32.sv
hw/rtl/tcu/tfr/VX_tcu_fedp_tfr.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_acc.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_align.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_classifier.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_exc_reduce.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_lane_mask.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_max_exp.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f16.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f4.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f8.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_mul_i4.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_mul_i8.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_mul_join.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_norm_round.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_pipe_register.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_shared_mul.sv
hw/rtl/tcu/tfr/VX_tcu_tfr_wmul.sv
hw/rtl/tex/VX_tex_addr.sv
hw/rtl/tex/VX_tex_bus_arb.sv
hw/rtl/tex/VX_tex_bus_if.sv
hw/rtl/tex/VX_tex_core.sv
hw/rtl/tex/VX_tex_csr.sv
hw/rtl/tex/VX_tex_dcr.sv
hw/rtl/tex/VX_tex_define.vh
hw/rtl/tex/VX_tex_format.sv
hw/rtl/tex/VX_tex_lerp.sv
hw/rtl/tex/VX_tex_mem.sv
hw/rtl/tex/VX_tex_perf_if.sv
hw/rtl/tex/VX_tex_pkg.sv
hw/rtl/tex/VX_tex_sampler.sv
hw/rtl/tex/VX_tex_sat.sv
hw/rtl/tex/VX_tex_stride.sv
hw/rtl/tex/VX_tex_unit.sv
hw/rtl/tex/VX_tex_wrap.sv
hw/rtl/vm/VX_mmu.sv
hw/rtl/vm/VX_mmu_dcr.sv
hw/rtl/vm/VX_mmu_fault_if.sv
hw/rtl/vm/VX_mmu_snoop.sv
hw/rtl/vm/VX_ptw.sv
hw/rtl/vm/VX_ptw_cache.sv
hw/rtl/vm/VX_ptw_walker.sv
hw/rtl/vm/VX_tlb_bus_arb.sv
hw/rtl/vm/VX_tlb_bus_if.sv
hw/rtl/vm/VX_tlb_cam.sv
hw/rtl/vm/VX_tlb_flush_if.sv
hw/rtl/vm/VX_tlb_l1.sv
hw/rtl/vm/VX_tlb_l2.sv
hw/rtl/vm/VX_tlb_mshr.sv
hw/rtl/vm/VX_tlb_pkg.sv
profiles/p02-tfr.json
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
sim/simx/gem5/VortexGPGPU.py
sim/simx/gem5/dev_mem.cpp
sim/simx/gem5/dev_mem.h
sim/simx/gem5/install.sh
sim/simx/gem5/vortex_gpgpu.cpp
sim/simx/gem5/vortex_gpgpu.h
sim/simx/gem5/vortex_gpgpu_dev.cc
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
sw/kernel/Makefile
sw/kernel/ai/matmul.cpp
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
sw/kernel/scripts/kernel_startup.sh
sw/kernel/scripts/link32.ld
sw/kernel/scripts/link64.ld
sw/kernel/scripts/vxbin.py
sw/kernel/src/common.h
sw/kernel/src/tinyprintf.c
sw/kernel/src/tinyprintf.h
sw/kernel/src/vx_print.S
sw/kernel/src/vx_print.c
sw/kernel/src/vx_serial.S
sw/kernel/src/vx_spawn.c
sw/kernel/src/vx_start.S
sw/kernel/src/vx_syscalls.c
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
sw/runtime/common/async_run.h
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
sw/runtime/simx/Makefile
sw/runtime/simx/vortex.cpp
sw/runtime/stub/Makefile
sw/runtime/stub/vortex.cpp
sw/runtime/vortex-kernel.pc.in
sw/runtime/vortex-runtime.pc.in
sw/runtime/xrt/Makefile
sw/runtime/xrt/vortex.cpp
sw/runtime/xrt/xrt.ini.in
tests/regression/ai_bench_common/counters.h
tests/regression/ai_counter_preflight/Makefile
tests/regression/ai_counter_preflight/backend.mk
tests/regression/ai_counter_preflight/hooks.cpp
tests/regression/ai_counter_preflight/hooks.h
tests/regression/ai_counter_preflight/main.cpp
tests/regression/ai_matmul/Makefile
tests/regression/ai_matmul/main.cpp
tests/regression/ai_warm_workspace/main.cpp
tests/regression/ai_warm_workspace/observer.cpp
tests/regression/ai_warm_workspace/observer.h
tests/regression/common.mk
tests/regression/sgemm_tcu/Makefile
tests/regression/sgemm_tcu/common.h
tests/regression/sgemm_tcu/kernel.cpp
tests/regression/sgemm_tcu/main.cpp
tests/regression/sgemm_tcu/p02_fixture_adapter.h
tests/regression/sgemm_tcu/p02_fixtures.h
tests/runtime/Makefile
tests/runtime/test_ai_lifecycle.cpp
tests/runtime/test_async.cpp
tests/runtime/test_basic.cpp
tests/runtime/test_module_kernel.cpp
tests/runtime/test_rect_fill.cpp
tests/runtime/test_timeline_events.cpp
third_party/Makefile
""".split())

# Extensions are source inputs within the producer's reviewed discovery roots.
# Existing singleton workflow/design/configuration names are allowed only by
# the frozen list. Neither evidence archives nor arbitrary new roots are inputs.
_EXTENSION_ROOTS = (
    "ci/project", "sim/common", "sim/simx", "sim/rtlsim",
    "sw/common", "sw/kernel", "sw/runtime", "hw/rtl", "hw/dpi",
    "tests/runtime", "tests/regression/ai_counter_preflight",
    "tests/regression/ai_warm_workspace", "tests/regression/ai_bench_common",
    "tests/regression/ai_matmul", "tests/regression/sgemm_tcu",
    "third_party/ramulator/ext/spdlog/include", "third_party/ramulator/ext/yaml-cpp/include",
    "third_party/ramulator/src", "third_party/softfloat/source/include",
    "third_party/softfloat/source/RISCV",
)
_EXTENSION_SUFFIXES = frozenset((
    ".c", ".cc", ".cpp", ".h", ".hpp", ".inc", ".tpp", ".S", ".s", ".sv",
    ".v", ".vh", ".vi", ".mk", ".in", ".ld", ".sh", ".py", ".toml", ".json",
))
LIMITATIONS = (
    "The independently supplied manifest digest defines the expected complete source descriptors.",
    "A matching revision label does not independently prove Git or GitHub provenance.",
    "Descriptor matching does not authenticate execution or prove source-to-binary compilation.",
    "The known first-party source inventory is mandatory; populated dependency headers are exact externally pinned extensions.",
    "The archive reader must independently rehash every retained source body; descriptors alone are insufficient.",
    "No descriptor path or recorded producer path is opened, resolved, imported or executed.",
    "Source consistency grants no counter qualification, warm readiness, performance or phase acceptance.",
    "Bounded no-follow I/O and identity checks do not defeat malicious concurrent filesystem writers.",
)


class SourceInventoryError(ValueError):
    """Source expectations are missing, unsafe, malformed or inconsistent."""


def _require(condition, message):
    if not condition:
        raise SourceInventoryError(message)


def required_source_names():
    names = REQUIRED_SOURCE_NAMES
    _require(len(names) == len(set(names)) == 806 and tuple(sorted(names)) == names,
             "trusted source minimum count or ordering differs")
    observed = hashlib.sha256("".join(name + "\n" for name in names).encode("ascii")).hexdigest()
    _require(observed == SOURCE_NAMES_SHA256, "trusted source minimum digest differs")
    return names


def _expectations(expected_revision, expected_sha256=None, *, digest_required=False):
    _require(type(expected_revision) is str and REVISION.fullmatch(expected_revision),
             "an independently expected lowercase full source revision is required")
    if digest_required:
        _require(type(expected_sha256) is str and SHA256.fullmatch(expected_sha256),
                 "an independently expected source manifest SHA-256 is required")


def _source_path(value):
    _require(type(value) is str and 0 < len(value) <= MAX_PATH_BYTES and PATH.fullmatch(value),
             "source path must be bounded canonical ASCII POSIX relative text")
    parts = value.split("/")
    _require(len(parts) <= MAX_PATH_DEPTH and all(
        part not in (".", "..", ".git") and len(part) <= 255 for part in parts),
        "source path is unsafe or exceeds its component/depth bound")
    return value


def _extension(name):
    parts = name.split("/")
    return (not any(part.startswith(".") or part.lower() == "evidence" for part in parts)
        and any(name.startswith(root + "/") for root in _EXTENSION_ROOTS)
        and (parts[-1] == "Makefile" or Path(parts[-1]).suffix in _EXTENSION_SUFFIXES))


def _sources(rows):
    _require(type(rows) is list and 0 < len(rows) <= MAX_SOURCES,
             "source inventory must be a bounded nonempty list")
    required = set(required_source_names())
    result, names = [], []
    for row in rows:
        _require(type(row) is dict and set(row) == DESCRIPTOR_FIELDS,
                 "source descriptor fields differ")
        name = _source_path(row["path"])
        _require(not names or names[-1] < name, "source paths must be unique and sorted")
        _require(name in required or _extension(name), "source path is outside reviewed source inputs")
        _require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"]),
                 "source descriptor SHA-256 is invalid")
        _require(type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= MAX_SOURCE_BYTES,
                 "source descriptor size is invalid")
        names.append(name)
        result.append({key: row[key] for key in ("path", "sha256", "size_bytes")})
    _require(required <= set(names), "source inventory omits a required source body")
    return result


def validate_source_inventory(document, *, expected_revision):
    """Validate/copy a trusted expectation; a dictionary alone has no provenance."""
    _expectations(expected_revision)
    _require(type(document) is dict and set(document) == MANIFEST_FIELDS,
             "source manifest fields differ")
    _require(type(document["schema_version"]) is int and document["schema_version"] == 1,
             "source manifest schema differs")
    _require(type(document["contract_id"]) is str and document["contract_id"] == CONTRACT_ID,
             "source manifest contract differs")
    _require(type(document["producer_contract_id"]) is str
             and document["producer_contract_id"] == PRODUCER_CONTRACT_ID,
             "source manifest producer differs")
    _require(type(document["source_revision"]) is str and document["source_revision"] == expected_revision,
             "source manifest revision differs from the external expectation")
    return {"schema_version": 1, "contract_id": CONTRACT_ID,
            "producer_contract_id": PRODUCER_CONTRACT_ID, "source_revision": expected_revision,
            "sources": _sources(document["sources"])}


def decode_source_inventory(contents, *, expected_sha256, expected_revision):
    """Verify the independently supplied exact-byte digest before strict JSON."""
    _expectations(expected_revision, expected_sha256, digest_required=True)
    _require(type(contents) is bytes and 0 < len(contents) <= MAX_MANIFEST_BYTES,
             "source manifest bytes are absent or exceed the limit")
    _require(hashlib.sha256(contents).hexdigest() == expected_sha256,
             "source manifest SHA-256 differs from the external digest")
    try:
        document = load_json_bytes(contents, "managed preflight source manifest")
    except ValueError as error:
        raise SourceInventoryError(str(error)) from error
    return validate_source_inventory(document, expected_revision=expected_revision)


def load_source_inventory(path, *, expected_sha256, expected_revision):
    """Read only the explicit caller-selected manifest through no-follow I/O."""
    _expectations(expected_revision, expected_sha256, digest_required=True)
    try:
        selected = Path(path)
        with PacketReader(selected.parent, max_total_bytes=MAX_MANIFEST_BYTES, max_files=1) as reader:
            contents = reader.read_bytes(selected.name, limit=MAX_MANIFEST_BYTES)
            reader.recheck()
    except (OSError, TypeError, ValueError) as error:
        raise SourceInventoryError("source manifest cannot be read safely: " + str(error)) from error
    return decode_source_inventory(contents, expected_sha256=expected_sha256,
                                   expected_revision=expected_revision)


def validate_retained_sources(actual, expected, *, expected_revision):
    """Compare every descriptor to caller-pinned expectations without file I/O.

    ``expected`` must come from the digest-pinned loader/decoder or an explicitly
    trusted caller. The archive layer must additionally rehash each retained body.
    """
    manifest = validate_source_inventory(expected, expected_revision=expected_revision)
    observed = _sources(actual)
    _require(observed == manifest["sources"],
             "retained source descriptors differ from the independently pinned inventory")
    return observed
