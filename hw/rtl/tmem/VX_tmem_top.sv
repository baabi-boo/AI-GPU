// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_top
    import VX_tmem_pkg::*;
#(
    parameter int NUM_BANKS  = TMEM_NUM_BANKS,
    parameter int BANK_DEPTH = TMEM_BANK_DEPTH_WORDS,
    parameter int LANES      = 8
) (
    input  logic                                clk,
    input  logic                                reset,
    // 1) Dynamic Allocation / Deallocation / Query Port
    input  logic                                alloc_valid,
    output logic                                alloc_ready,
    input  logic [2:0]                          alloc_op,
    input  logic                                alloc_auto_place,
    input  logic                                alloc_buddy_align,
    input  logic                                alloc_strict_owner,
    input  tmem_alloc_req_t                     alloc_req,
    output tmem_alloc_rsp_t                     alloc_rsp,
    output logic                                alloc_query_valid,
    output tmem_region_entry_t                  alloc_query_entry,
    // 2) Decoupled Load (tmem.ld) Port
    input  logic                                ld_desc_valid,
    output logic                                ld_desc_ready,
    input  logic [TMEM_TAG_W-1:0]               ld_desc_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_desc_region_id,
    input  logic [4:0]                          ld_desc_warp_id,
    input  logic [TMEM_ROW_W-1:0]               ld_desc_row_base,
    input  logic [TMEM_COL_W-1:0]               ld_desc_col_base,
    input  logic [7:0]                          ld_desc_num_rows,
    input  logic [9:0]                          ld_desc_num_cols,
    input  logic [1:0]                          ld_desc_elem_bytes,
    input  logic                                ld_desc_col_major,
    input  logic [2:0]                          ld_desc_subbyte_shift,
    input  logic                                ld_xform_en,
    input  logic [2:0]                          ld_xform_mode,
    input  logic [2:0]                          ld_xform_fmt,
    input  logic                                ld_xform_tile8x8,
    input  logic                                ld_xform_unpack32,
    output logic                                ld_rsp_valid,
    input  logic                                ld_rsp_ready,
    output logic [TMEM_TAG_W-1:0]               ld_rsp_tag,
    output logic [4:0]                          ld_rsp_warp_id,
    output tmem_status_e                        ld_rsp_status,
    output logic [LANES-1:0][63:0]              ld_rsp_data,
    output logic [LANES-1:0]                    ld_rsp_lane_mask,
    output logic                                ld_rsp_last,
    output logic                                ld_rsp_ecc_ce,
    output logic                                ld_rsp_ecc_ue,
    // 3) Decoupled Store (tmem.st) Port
    input  logic                                st_req_valid,
    output logic                                st_req_ready,
    input  logic [TMEM_TAG_W-1:0]               st_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         st_req_region_id,
    input  logic [4:0]                          st_req_warp_id,
    input  logic [TMEM_ROW_W-1:0]               st_req_row_base,
    input  logic [TMEM_COL_W-1:0]               st_req_col_base,
    input  logic [7:0]                          st_req_num_rows,
    input  logic [9:0]                          st_req_num_cols,
    input  logic                                st_req_col_major,
    input  logic                                st_req_cell32_mode,
    input  logic [LANES-1:0][63:0]              st_req_data,
    input  logic [LANES-1:0][7:0]               st_req_be,
    input  logic                                st_req_last,
    output logic                                st_ack_valid,
    input  logic                                st_ack_ready,
    output logic [TMEM_TAG_W-1:0]               st_ack_tag,
    output logic [4:0]                          st_ack_warp_id,
    output tmem_status_e                        st_ack_status,
    // 4) Dedicated MMA Operand & Writeback Port
    input  logic                                mma_req_valid,
    output logic                                mma_req_ready,
    input  tmem_op_e                            mma_req_op,
    input  logic [TMEM_TAG_W-1:0]               mma_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         mma_req_region_id,
    input  logic [4:0]                          mma_req_warp_id,
    input  logic [TMEM_ROW_W-1:0]               mma_req_row,
    input  logic [TMEM_COL_W-1:0]               mma_req_col,
    input  tmem_swizzle_e                       mma_req_swizzle,
    input  logic [7:0]                          mma_req_col_count,
    input  logic                                mma_req_ping_pong_sel,
    input  logic [LANES-1:0][63:0]              mma_req_wr_data,
    input  logic [LANES-1:0][7:0]               mma_req_wr_be,
    output logic                                mma_rsp_valid,
    input  logic                                mma_rsp_ready,
    output tmem_op_e                            mma_rsp_op,
    output logic [TMEM_TAG_W-1:0]               mma_rsp_tag,
    output tmem_status_e                        mma_rsp_status,
    output logic [LANES-1:0][63:0]              mma_rsp_data,
    output logic [LANES-1:0]                    mma_rsp_lane_mask,
    output logic                                mma_rsp_ecc_ce,
    output logic                                mma_rsp_ecc_ue,
    // 5) Decoupled Wait / Fence & 2-CTA Barrier Port
    input  logic                                wait_req_valid,
    output logic                                wait_req_ready,
    input  tmem_op_e                            wait_req_op,
    input  logic [TMEM_TAG_W-1:0]               wait_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         wait_req_region_id,
    input  logic [4:0]                          wait_req_warp_id,
    input  logic                                wait_req_scope_warp,
    input  logic [TMEM_BARRIER_ID_W-1:0]        wait_req_barrier_id,
    input  logic                                wait_req_barrier_phase,
    input  logic                                peer_bar_valid,
    output logic                                peer_bar_ready,
    input  logic [TMEM_BARRIER_ID_W-1:0]        peer_bar_id,
    input  logic                                peer_bar_phase,
    output logic                                bar_wakeup_valid,
    output logic [TMEM_BARRIER_ID_W-1:0]        bar_wakeup_id,
    output logic                                bar_wakeup_phase,
    output logic                                wait_rsp_valid,
    input  logic                                wait_rsp_ready,
    output tmem_op_e                            wait_rsp_op,
    output logic [TMEM_TAG_W-1:0]               wait_rsp_tag,
    output tmem_status_e                        wait_rsp_status,
    // Arbiter QoS, ECC Injection/Scrub, and Telemetry
    input  logic [3:0]                          cfg_weight_ld,
    input  logic [3:0]                          cfg_weight_st,
    input  logic [3:0]                          cfg_weight_mma,
    input  logic                                cfg_strict_mma_prio,
    input  logic [4:0]                          cfg_starve_limit,
    input  logic                                ecc_inj_en,
    input  logic [4:0]                          ecc_inj_bank,
    input  logic [71:0]                         ecc_inj_mask,
    input  logic                                scrub_en,
    input  logic                                perf_clear,
    output logic                                deadlock_fault_out,
    output logic                                bounds_fault_out,
    output logic [2:0]                          bounds_fault_reason_out,
    output tmem_perf_cnt_t                      perf_cnt_out,
    output logic [31:0]                         ecc_ce_count_out,
    output logic [31:0]                         ecc_ue_count_out,
    output logic [4:0]                          occupied_granules_out,
    output logic [4:0]                          peak_granules_out
);

    // Live region table & granule bitmap
    tmem_region_entry_t [TMEM_MAX_REGIONS-1:0]  region_table;
    logic [TMEM_NUM_ALLOC_UNITS-1:0]            granule_bitmap;
    logic [4:0]                                 occupied_granules_w;
    logic [4:0]                                 peak_granules_w;
    logic [4:0]                                 active_regions_w;
    logic [31:0]                                alloc_ok_cnt_w;
    logic [31:0]                                alloc_err_cnt_w;
    logic [31:0]                                dealloc_cnt_w;

    // Hazard unit signals
    logic                                       ld_haz_allow;
    logic                                       st_haz_allow;
    logic                                       mma_haz_allow;
    logic                                       ld_haz_issue_fire;
    logic [TMEM_REGION_ID_W-1:0]                ld_haz_issue_region_id;
    logic [4:0]                                 ld_haz_issue_warp_id;
    logic                                       st_haz_issue_fire;
    logic [TMEM_REGION_ID_W-1:0]                st_haz_issue_region_id;
    logic [4:0]                                 st_haz_issue_warp_id;
    logic                                       mma_haz_issue_fire;
    logic [TMEM_REGION_ID_W-1:0]                mma_haz_issue_region_id;
    logic [4:0]                                 mma_haz_issue_warp_id;
    logic                                       ld_haz_commit_valid;
    logic [TMEM_TAG_W-1:0]                      ld_haz_commit_tag;
    logic [TMEM_REGION_ID_W-1:0]                ld_haz_commit_region_id;
    logic [4:0]                                 ld_haz_commit_warp_id;
    logic                                       st_haz_commit_valid;
    logic [TMEM_TAG_W-1:0]                      st_haz_commit_tag;
    logic [TMEM_REGION_ID_W-1:0]                st_haz_commit_region_id;
    logic [4:0]                                 st_haz_commit_warp_id;
    logic                                       mma_haz_commit_valid;
    logic [TMEM_TAG_W-1:0]                      mma_haz_commit_tag;
    logic [TMEM_REGION_ID_W-1:0]                mma_haz_commit_region_id;
    logic [4:0]                                 mma_haz_commit_warp_id;
    logic                                       ld_haz_chk_valid;
    logic [TMEM_REGION_ID_W-1:0]                ld_haz_chk_region_id;
    logic [TMEM_COL_W-1:0]                      ld_haz_chk_col_start;
    logic [9:0]                                 ld_haz_chk_col_count;
    logic [TMEM_TAG_W-1:0]                      ld_haz_chk_tag;
    logic                                       st_haz_chk_valid;
    logic [TMEM_REGION_ID_W-1:0]                st_haz_chk_region_id;
    logic [TMEM_COL_W-1:0]                      st_haz_chk_col_start;
    logic [9:0]                                 st_haz_chk_col_count;
    logic [TMEM_TAG_W-1:0]                      st_haz_chk_tag;
    logic                                       mma_haz_chk_valid;
    logic                                       mma_haz_chk_is_write;
    logic [TMEM_REGION_ID_W-1:0]                mma_haz_chk_region_id;
    logic [TMEM_COL_W-1:0]                      mma_haz_chk_col_start;
    logic [9:0]                                 mma_haz_chk_col_count;
    logic [TMEM_TAG_W-1:0]                      mma_haz_chk_tag;
    logic                                       fence_req_active;
    logic                                       fence_region_only;
    logic                                       fence_drained;
    logic                                       raw_stall_w;
    logic                                       war_stall_w;
    logic                                       waw_stall_w;
    logic                                       haz_table_full_w;
    logic [7:0]                                 haz_epoch_w;
    logic [4:0]                                 haz_inflight_w;
    logic [31:0]                                haz_stall_cycles_w;
    logic [31:0]                                haz_raw_cnt_w;
    logic [31:0]                                haz_war_cnt_w;
    logic [31:0]                                haz_waw_cnt_w;

    // Bounds checker signals
    logic                                       ld_comb_bounds_fault;
    logic                                       st_comb_bounds_fault;
    logic                                       mma_comb_bounds_fault;
    logic                                       ld_bounds_fault;
    logic                                       st_bounds_fault;
    logic                                       mma_bounds_fault;
    logic                                       any_bounds_fault;
    logic [1:0]                                 bounds_fault_client_w;
    logic [2:0]                                 bounds_fault_reason_w;
    logic [TMEM_REGION_ID_W-1:0]                bounds_fault_region_w;
    logic [4:0]                                 bounds_fault_warp_w;
    logic [TMEM_ROW_W-1:0]                      bounds_fault_row_w;
    logic [TMEM_COL_W-1:0]                      bounds_fault_col_w;
    logic [31:0]                                bounds_total_faults_w;
    logic [31:0]                                bounds_ld_cnt_w;
    logic [31:0]                                bounds_st_cnt_w;
    logic [31:0]                                bounds_mma_cnt_w;

    // Client <-> Arbiter buses
    logic [LANES-1:0]                           ld_arb_valid, ld_arb_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           ld_arb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           ld_arb_col;
    tmem_swizzle_e                              ld_arb_swizzle;

    logic [LANES-1:0]                           st_arb_valid, st_arb_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           st_arb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           st_arb_col;
    tmem_swizzle_e                              st_arb_swizzle;
    logic [LANES-1:0][63:0]                     st_arb_data;
    logic [LANES-1:0][7:0]                      st_arb_be;

    logic [LANES-1:0]                           mma_rda_arb_valid, mma_rda_arb_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           mma_rda_arb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           mma_rda_arb_col;
    tmem_swizzle_e                              mma_rda_arb_swizzle;

    logic [LANES-1:0]                           mma_rdb_arb_valid, mma_rdb_arb_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           mma_rdb_arb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           mma_rdb_arb_col;
    tmem_swizzle_e                              mma_rdb_arb_swizzle;

    logic [LANES-1:0]                           mma_wr_arb_valid, mma_wr_arb_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           mma_wr_arb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           mma_wr_arb_col;
    tmem_swizzle_e                              mma_wr_arb_swizzle;
    logic [LANES-1:0][63:0]                     mma_wr_arb_data;
    logic [LANES-1:0][7:0]                      mma_wr_arb_be;

    // Arbiter <-> Bank Array buses
    logic [LANES-1:0]                           bank_rda_valid, bank_rda_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           bank_rda_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           bank_rda_col;
    tmem_swizzle_e                              bank_rda_swizzle;
    logic [LANES-1:0]                           bank_rda_rsp_valid;
    logic [LANES-1:0][63:0]                     bank_rda_rsp_data;
    logic [LANES-1:0]                           bank_rda_ecc_ce;
    logic [LANES-1:0]                           bank_rda_ecc_ue;

    logic [LANES-1:0]                           bank_rdb_valid, bank_rdb_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           bank_rdb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           bank_rdb_col;
    tmem_swizzle_e                              bank_rdb_swizzle;
    logic [LANES-1:0]                           bank_rdb_rsp_valid;
    logic [LANES-1:0][63:0]                     bank_rdb_rsp_data;
    logic [LANES-1:0]                           bank_rdb_ecc_ce;
    logic [LANES-1:0]                           bank_rdb_ecc_ue;

    logic [LANES-1:0]                           bank_wr_valid, bank_wr_ready;
    logic [LANES-1:0][TMEM_ROW_W-1:0]           bank_wr_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]           bank_wr_col;
    tmem_swizzle_e                              bank_wr_swizzle;
    logic [LANES-1:0][63:0]                     bank_wr_data;
    logic [LANES-1:0][7:0]                      bank_wr_be;

    logic [5:0]                                 rd_a_conflict_ways_w;
    logic [5:0]                                 rd_b_conflict_ways_w;
    logic [5:0]                                 wr_conflict_ways_w;
    logic [31:0]                                bank_ecc_ce_count_w;
    logic [31:0]                                bank_ecc_ue_count_w;

    // Arbiter telemetry
    logic                                       grant_rda_is_mma_w;
    logic                                       grant_wr_is_mma_w;
    logic [31:0]                                arb_ld_grants_w;
    logic [31:0]                                arb_st_grants_w;
    logic [31:0]                                arb_mma_rda_grants_w;
    logic [31:0]                                arb_mma_rdb_grants_w;
    logic [31:0]                                arb_mma_wr_grants_w;
    logic [31:0]                                arb_escalations_w;
    logic [31:0]                                arb_conflict_stall_w;
    logic [31:0]                                prev_arb_conflict_stall_q;
    logic                                       arb_conflict_stall_pulse;

    // Load Engine <-> Layout Xform intermediate signals
    logic                                       ld_eng_rsp_valid;
    logic                                       ld_eng_rsp_ready;
    logic [TMEM_TAG_W-1:0]                      ld_eng_rsp_tag;
    logic [4:0]                                 ld_eng_rsp_warp_id;
    tmem_status_e                               ld_eng_rsp_status;
    logic [LANES-1:0][63:0]                     ld_eng_rsp_data;
    logic [LANES-1:0]                           ld_eng_rsp_lane_mask;
    logic                                       ld_eng_rsp_last;
    logic                                       ld_eng_rsp_ecc_ce;
    logic                                       ld_eng_rsp_ecc_ue;
    logic [31:0]                                ld_beats_w;
    logic [31:0]                                ld_oob_faults_w;
    logic [31:0]                                st_beats_w;
    logic [31:0]                                st_oob_faults_w;
    logic [TMEM_MAX_REGIONS-1:0]                mma_ping_pong_w;
    logic [31:0]                                mma_rd_beats_w;
    logic [31:0]                                mma_wr_beats_w;

    // Layout transform wires + metadata side-band FIFO
    logic                                       xform_in_valid;
    logic                                       xform_in_ready;
    logic                                       xform_out_valid;
    logic                                       xform_out_ready;
    logic [TMEM_TAG_W-1:0]                      xform_out_tag;
    logic [LANES-1:0][63:0]                     xform_out_data;
    logic [31:0]                                xform_ops_w;

    typedef struct packed {
        logic [TMEM_TAG_W-1:0] tag;
        logic [4:0]            warp_id;
        tmem_status_e          status;
        logic [LANES-1:0]      lane_mask;
        logic                  last;
        logic                  ecc_ce;
        logic                  ecc_ue;
        logic                  bypass_xform;
    } ld_meta_t;

    ld_meta_t [7:0] ld_meta_q;
    logic [2:0]     ld_meta_head_q, ld_meta_tail_q;
    logic [3:0]     ld_meta_cnt_q;
    logic           ld_meta_push, ld_meta_pop;

    // Wait/Barrier telemetry
    logic [TMEM_MAX_REGIONS-1:0][7:0]           wb_reg_outst_w;
    logic [31:0][7:0]                           wb_warp_outst_w;
    logic [7:0]                                 wb_epoch_w;
    logic [31:0]                                wb_wait_cycles_w;
    logic [31:0]                                wb_fence_done_w;
    logic [31:0]                                wb_timeout_faults_w;

    // Perf monitor exported signals
    logic [31:0]                                pm_rd_a_beats_w;
    logic [31:0]                                pm_rd_b_beats_w;
    logic [31:0]                                pm_wr_beats_w;
    logic [31:0]                                pm_haz_stall_w;
    logic [4:0]                                 pm_util_peak_w;
    logic [31:0]                                pm_ecc_ce_snap_w;
    logic [31:0]                                pm_ecc_ue_snap_w;
    logic [31:0]                                pm_oob_snap_w;
    logic [31:0]                                pm_active_cycles_w;

    // Previous-cycle arbiter conflict counter snapshot for 1-cycle stall pulse detection
    always_ff @(posedge clk) begin
        if (reset) begin
            prev_arb_conflict_stall_q <= 32'd0;
        end else begin
            prev_arb_conflict_stall_q <= arb_conflict_stall_w;
        end
    end
    assign arb_conflict_stall_pulse = (arb_conflict_stall_w != prev_arb_conflict_stall_q);

    // -------------------------------------------------------------------------
    // 1. Dynamic Region Allocator
    // -------------------------------------------------------------------------
    VX_tmem_allocator #(
        .NUM_GRANULES (TMEM_NUM_ALLOC_UNITS),
        .MAX_REGIONS  (TMEM_MAX_REGIONS),
        .NUM_WARPS    (32)
    ) u_allocator (
        .clk                   (clk),
        .reset                 (reset),
        .req_valid             (alloc_valid),
        .req_ready             (alloc_ready),
        .req_op                (alloc_op),
        .auto_place_en         (alloc_auto_place),
        .buddy_align_en        (alloc_buddy_align),
        .strict_owner_chk      (alloc_strict_owner),
        .alloc_req             (alloc_req),
        .alloc_rsp             (alloc_rsp),
        .query_valid           (alloc_query_valid),
        .query_entry_out       (alloc_query_entry),
        .region_table_out      (region_table),
        .granule_bitmap_out    (granule_bitmap),
        .occupied_granules_out (occupied_granules_w),
        .peak_granules_out     (peak_granules_w),
        .active_regions_out    (active_regions_w),
        .alloc_ok_count_out    (alloc_ok_cnt_w),
        .alloc_err_count_out   (alloc_err_cnt_w),
        .dealloc_count_out     (dealloc_cnt_w)
    );

    // -------------------------------------------------------------------------
    // 2. Region Permission & Bounds Checker
    // -------------------------------------------------------------------------
    VX_tmem_bounds_chk #(
        .MAX_REGIONS (TMEM_MAX_REGIONS)
    ) u_bounds_chk (
        .clk                 (clk),
        .reset               (reset),
        .region_table_in     (region_table),
        .strict_owner_en     (alloc_strict_owner),
        .ld_chk_valid        (ld_desc_valid),
        .ld_chk_region_id    (ld_desc_region_id),
        .ld_chk_warp_id      (ld_desc_warp_id),
        .ld_chk_row          (ld_desc_row_base),
        .ld_chk_col          (ld_desc_col_base),
        .ld_chk_num_rows     (ld_desc_num_rows),
        .ld_chk_num_cols     (ld_desc_num_cols),
        .st_chk_valid        (st_req_valid),
        .st_chk_region_id    (st_req_region_id),
        .st_chk_warp_id      (st_req_warp_id),
        .st_chk_row          (st_req_row_base),
        .st_chk_col          (st_req_col_base),
        .st_chk_num_rows     (st_req_num_rows),
        .st_chk_num_cols     (st_req_num_cols),
        .mma_chk_valid       (mma_req_valid),
        .mma_chk_is_write    (mma_req_op == TMEM_OP_MMA_WR_D),
        .mma_chk_region_id   (mma_req_region_id),
        .mma_chk_warp_id     (mma_req_warp_id),
        .mma_chk_row         (mma_req_row),
        .mma_chk_col         (mma_req_col),
        .mma_chk_num_cols    (mma_req_col_count),
        .ld_comb_fault_out   (ld_comb_bounds_fault),
        .st_comb_fault_out   (st_comb_bounds_fault),
        .mma_comb_fault_out  (mma_comb_bounds_fault),
        .ld_fault_out        (ld_bounds_fault),
        .st_fault_out        (st_bounds_fault),
        .mma_fault_out       (mma_bounds_fault),
        .any_fault_out       (any_bounds_fault),
        .fault_client_out    (bounds_fault_client_w),
        .fault_reason_out    (bounds_fault_reason_w),
        .fault_region_id_out (bounds_fault_region_w),
        .fault_warp_id_out   (bounds_fault_warp_w),
        .fault_row_out       (bounds_fault_row_w),
        .fault_col_out       (bounds_fault_col_w),
        .total_faults_out    (bounds_total_faults_w),
        .ld_fault_cnt_out    (bounds_ld_cnt_w),
        .st_fault_cnt_out    (bounds_st_cnt_w),
        .mma_fault_cnt_out   (bounds_mma_cnt_w)
    );

    // -------------------------------------------------------------------------
    // 3. RAW / WAR / WAW Hazard Tracker & Fence Drain
    // -------------------------------------------------------------------------
    assign fence_req_active  = wait_req_valid && (wait_req_op == TMEM_OP_FENCE);
    assign fence_region_only = (wait_req_region_id != 4'd0);

    VX_tmem_hazard_unit #(
        .TRACK_DEPTH (16),
        .EPOCH_W     (8)
    ) u_hazard_unit (
        .clk                     (clk),
        .reset                   (reset),
        .ld_req_valid            (ld_haz_chk_valid),
        .ld_req_allow            (ld_haz_allow),
        .ld_region_id            (ld_haz_chk_region_id),
        .ld_col_start            (ld_haz_chk_col_start),
        .ld_col_count            (ld_haz_chk_col_count),
        .ld_tag                  (ld_haz_chk_tag),
        .st_req_valid            (st_haz_chk_valid),
        .st_req_allow            (st_haz_allow),
        .st_region_id            (st_haz_chk_region_id),
        .st_col_start            (st_haz_chk_col_start),
        .st_col_count            (st_haz_chk_col_count),
        .st_tag                  (st_haz_chk_tag),
        .mma_req_valid           (mma_haz_chk_valid),
        .mma_req_allow           (mma_haz_allow),
        .mma_is_write            (mma_haz_chk_is_write),
        .mma_region_id           (mma_haz_chk_region_id),
        .mma_col_start           (mma_haz_chk_col_start),
        .mma_col_count           (mma_haz_chk_col_count),
        .mma_tag                 (mma_haz_chk_tag),
        .ld_issue_fire           (ld_haz_issue_fire),
        .st_issue_fire           (st_haz_issue_fire),
        .mma_issue_fire          (mma_haz_issue_fire),
        .ld_commit_valid         (ld_haz_commit_valid),
        .ld_commit_tag           (ld_haz_commit_tag),
        .st_commit_valid         (st_haz_commit_valid),
        .st_commit_tag           (st_haz_commit_tag),
        .mma_commit_valid        (mma_haz_commit_valid),
        .mma_commit_tag          (mma_haz_commit_tag),
        .fence_req_valid         (fence_req_active),
        .fence_region_only       (fence_region_only),
        .fence_region_id         (wait_req_region_id),
        .fence_drained           (fence_drained),
        .raw_stall_out           (raw_stall_w),
        .war_stall_out           (war_stall_w),
        .waw_stall_out           (waw_stall_w),
        .table_full_out          (haz_table_full_w),
        .current_epoch_out       (haz_epoch_w),
        .inflight_count_out      (haz_inflight_w),
        .hazard_stall_cycles_out (haz_stall_cycles_w),
        .raw_hazards_out         (haz_raw_cnt_w),
        .war_hazards_out         (haz_war_cnt_w),
        .waw_hazards_out         (haz_waw_cnt_w)
    );

    // -------------------------------------------------------------------------
    // 4. Decoupled Load Engine + 5. Layout Transform Engine
    // -------------------------------------------------------------------------
    VX_tmem_ld_engine #(
        .LANES      (LANES),
        .DESC_DEPTH (4)
    ) u_ld_engine (
        .clk                   (clk),
        .reset                 (reset),
        .ld_desc_valid         (ld_desc_valid),
        .ld_desc_ready         (ld_desc_ready),
        .ld_desc_tag           (ld_desc_tag),
        .ld_desc_region_id     (ld_desc_region_id),
        .ld_desc_warp_id       (ld_desc_warp_id),
        .ld_desc_row_base      (ld_desc_row_base),
        .ld_desc_col_base      (ld_desc_col_base),
        .ld_desc_num_rows      (ld_desc_num_rows),
        .ld_desc_num_cols      (ld_desc_num_cols),
        .ld_desc_elem_bytes    (ld_desc_elem_bytes),
        .ld_desc_col_major     (ld_desc_col_major),
        .ld_desc_subbyte_shift (ld_desc_subbyte_shift),
        .region_table_in       (region_table),
        .hazard_allow            (ld_haz_allow),
        .bounds_fault_in         (ld_comb_bounds_fault),
        .hazard_issue_fire       (ld_haz_issue_fire),
        .hazard_issue_region_id  (ld_haz_issue_region_id),
        .hazard_issue_warp_id    (ld_haz_issue_warp_id),
        .hazard_commit_valid     (ld_haz_commit_valid),
        .hazard_commit_tag       (ld_haz_commit_tag),
        .hazard_commit_region_id (ld_haz_commit_region_id),
        .hazard_commit_warp_id   (ld_haz_commit_warp_id),
        .hazard_chk_valid        (ld_haz_chk_valid),
        .hazard_chk_region_id    (ld_haz_chk_region_id),
        .hazard_chk_col_start    (ld_haz_chk_col_start),
        .hazard_chk_col_count    (ld_haz_chk_col_count),
        .hazard_chk_tag          (ld_haz_chk_tag),
        .bank_rd_valid         (ld_arb_valid),
        .bank_rd_ready         (ld_arb_ready),
        .bank_rd_row           (ld_arb_row),
        .bank_rd_col           (ld_arb_col),
        .bank_rd_swizzle       (ld_arb_swizzle),
        .bank_rsp_valid        (bank_rda_rsp_valid),
        .bank_rsp_data         (bank_rda_rsp_data),
        .bank_rsp_ecc_ce       (bank_rda_ecc_ce),
        .bank_rsp_ecc_ue       (bank_rda_ecc_ue),
        .ld_rsp_valid          (ld_eng_rsp_valid),
        .ld_rsp_ready          (ld_eng_rsp_ready),
        .ld_rsp_tag            (ld_eng_rsp_tag),
        .ld_rsp_warp_id        (ld_eng_rsp_warp_id),
        .ld_rsp_status         (ld_eng_rsp_status),
        .ld_rsp_data           (ld_eng_rsp_data),
        .ld_rsp_lane_mask      (ld_eng_rsp_lane_mask),
        .ld_rsp_last           (ld_eng_rsp_last),
        .ld_rsp_ecc_ce         (ld_eng_rsp_ecc_ce),
        .ld_rsp_ecc_ue         (ld_eng_rsp_ecc_ue),
        .ld_beats_out          (ld_beats_w),
        .ld_oob_faults_out     (ld_oob_faults_w)
    );

    assign xform_in_valid  = ld_eng_rsp_valid && (ld_meta_cnt_q != 4'd8);
    assign ld_eng_rsp_ready = xform_in_ready && (ld_meta_cnt_q != 4'd8);
    assign ld_meta_push    = xform_in_valid && xform_in_ready;
    assign ld_meta_pop     = xform_out_valid && xform_out_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            ld_meta_q      <= '0;
            ld_meta_head_q <= 3'd0;
            ld_meta_tail_q <= 3'd0;
            ld_meta_cnt_q  <= 4'd0;
        end else begin
            if (ld_meta_push) begin
                ld_meta_q[ld_meta_tail_q].tag          <= ld_eng_rsp_tag;
                ld_meta_q[ld_meta_tail_q].warp_id      <= ld_eng_rsp_warp_id;
                ld_meta_q[ld_meta_tail_q].status       <= ld_eng_rsp_status;
                ld_meta_q[ld_meta_tail_q].lane_mask    <= ld_eng_rsp_lane_mask;
                ld_meta_q[ld_meta_tail_q].last         <= ld_eng_rsp_last;
                ld_meta_q[ld_meta_tail_q].ecc_ce       <= ld_eng_rsp_ecc_ce;
                ld_meta_q[ld_meta_tail_q].ecc_ue       <= ld_eng_rsp_ecc_ue;
                ld_meta_q[ld_meta_tail_q].bypass_xform <= ~ld_xform_en;
                ld_meta_tail_q <= ld_meta_tail_q + 3'd1;
            end
            if (ld_meta_pop) begin
                ld_meta_head_q <= ld_meta_head_q + 3'd1;
            end
            case ({ld_meta_push, ld_meta_pop})
                2'b10:   ld_meta_cnt_q <= ld_meta_cnt_q + 4'd1;
                2'b01:   ld_meta_cnt_q <= ld_meta_cnt_q - 4'd1;
                default: ld_meta_cnt_q <= ld_meta_cnt_q;
            endcase
        end
    end

    VX_tmem_layout_xform #(
        .LANES (LANES)
    ) u_layout_xform (
        .clk           (clk),
        .reset         (reset),
        .in_valid      (xform_in_valid),
        .in_ready      (xform_in_ready),
        .xform_mode    (ld_xform_en ? ld_xform_mode : 3'd0),
        .elem_fmt      (ld_xform_fmt),
        .tile_8x8_mode (ld_xform_en && ld_xform_tile8x8),
        .unpack_to_32b (ld_xform_unpack32),
        .in_tag        (ld_eng_rsp_tag),
        .in_data       (ld_eng_rsp_data),
        .out_valid     (xform_out_valid),
        .out_ready     (xform_out_ready),
        .out_tag       (xform_out_tag),
        .out_data      (xform_out_data),
        .xform_ops_out (xform_ops_w)
    );

    assign xform_out_ready  = ld_rsp_ready;
    assign ld_rsp_valid     = xform_out_valid;
    assign ld_rsp_tag       = xform_out_tag;
    assign ld_rsp_data      = xform_out_data;
    assign ld_rsp_warp_id   = ld_meta_q[ld_meta_head_q].warp_id;
    assign ld_rsp_status    = ld_meta_q[ld_meta_head_q].status;
    assign ld_rsp_lane_mask = ld_meta_q[ld_meta_head_q].lane_mask;
    assign ld_rsp_last      = ld_meta_q[ld_meta_head_q].last;
    assign ld_rsp_ecc_ce    = ld_meta_q[ld_meta_head_q].ecc_ce;
    assign ld_rsp_ecc_ue    = ld_meta_q[ld_meta_head_q].ecc_ue;

    // -------------------------------------------------------------------------
    // 6. Decoupled Store Engine
    // -------------------------------------------------------------------------
    VX_tmem_st_engine #(
        .LANES      (LANES),
        .DESC_DEPTH (4)
    ) u_st_engine (
        .clk                 (clk),
        .reset               (reset),
        .st_req_valid        (st_req_valid),
        .st_req_ready        (st_req_ready),
        .st_req_tag          (st_req_tag),
        .st_req_region_id    (st_req_region_id),
        .st_req_warp_id      (st_req_warp_id),
        .st_req_row_base     (st_req_row_base),
        .st_req_col_base     (st_req_col_base),
        .st_req_num_rows     (st_req_num_rows),
        .st_req_num_cols     (st_req_num_cols),
        .st_req_col_major    (st_req_col_major),
        .st_req_cell32_mode  (st_req_cell32_mode),
        .st_req_data         (st_req_data),
        .st_req_be           (st_req_be),
        .st_req_last         (st_req_last),
        .region_table_in     (region_table),
        .hazard_allow            (st_haz_allow),
        .bounds_fault_in         (st_comb_bounds_fault),
        .hazard_issue_fire       (st_haz_issue_fire),
        .hazard_issue_region_id  (st_haz_issue_region_id),
        .hazard_issue_warp_id    (st_haz_issue_warp_id),
        .hazard_commit_valid     (st_haz_commit_valid),
        .hazard_commit_tag       (st_haz_commit_tag),
        .hazard_commit_region_id (st_haz_commit_region_id),
        .hazard_commit_warp_id   (st_haz_commit_warp_id),
        .hazard_chk_valid        (st_haz_chk_valid),
        .hazard_chk_region_id    (st_haz_chk_region_id),
        .hazard_chk_col_start    (st_haz_chk_col_start),
        .hazard_chk_col_count    (st_haz_chk_col_count),
        .hazard_chk_tag          (st_haz_chk_tag),
        .bank_wr_valid       (st_arb_valid),
        .bank_wr_ready       (st_arb_ready),
        .bank_wr_row         (st_arb_row),
        .bank_wr_col         (st_arb_col),
        .bank_wr_swizzle     (st_arb_swizzle),
        .bank_wr_data        (st_arb_data),
        .bank_wr_be          (st_arb_be),
        .st_ack_valid        (st_ack_valid),
        .st_ack_ready        (st_ack_ready),
        .st_ack_tag          (st_ack_tag),
        .st_ack_warp_id      (st_ack_warp_id),
        .st_ack_status       (st_ack_status),
        .st_beats_out        (st_beats_w),
        .st_oob_faults_out   (st_oob_faults_w)
    );

    // -------------------------------------------------------------------------
    // 7. Dedicated MMA Operand Feeder & Drain Bridge
    // -------------------------------------------------------------------------
    VX_tmem_mma_feeder #(
        .LANES (LANES)
    ) u_mma_feeder (
        .clk                   (clk),
        .reset                 (reset),
        .mma_req_valid         (mma_req_valid),
        .mma_req_ready         (mma_req_ready),
        .mma_req_op            (mma_req_op),
        .mma_req_tag             (mma_req_tag),
        .mma_req_region_id       (mma_req_region_id),
        .mma_req_warp_id         (mma_req_warp_id),
        .mma_req_row             (mma_req_row),
        .mma_req_col             (mma_req_col),
        .mma_req_swizzle         (mma_req_swizzle),
        .mma_req_col_count       (mma_req_col_count),
        .mma_req_ping_pong_sel   (mma_req_ping_pong_sel),
        .mma_req_wr_data         (mma_req_wr_data),
        .mma_req_wr_be           (mma_req_wr_be),
        .region_table_in         (region_table),
        .hazard_allow            (mma_haz_allow),
        .bounds_fault_in         (mma_comb_bounds_fault),
        .hazard_issue_fire       (mma_haz_issue_fire),
        .hazard_issue_region_id  (mma_haz_issue_region_id),
        .hazard_issue_warp_id    (mma_haz_issue_warp_id),
        .hazard_commit_valid     (mma_haz_commit_valid),
        .hazard_commit_tag       (mma_haz_commit_tag),
        .hazard_commit_region_id (mma_haz_commit_region_id),
        .hazard_commit_warp_id   (mma_haz_commit_warp_id),
        .hazard_chk_valid        (mma_haz_chk_valid),
        .hazard_chk_is_write     (mma_haz_chk_is_write),
        .hazard_chk_region_id    (mma_haz_chk_region_id),
        .hazard_chk_col_start    (mma_haz_chk_col_start),
        .hazard_chk_col_count    (mma_haz_chk_col_count),
        .hazard_chk_tag          (mma_haz_chk_tag),
        .bank_rda_valid        (mma_rda_arb_valid),
        .bank_rda_ready        (mma_rda_arb_ready),
        .bank_rda_row          (mma_rda_arb_row),
        .bank_rda_col          (mma_rda_arb_col),
        .bank_rda_swizzle      (mma_rda_arb_swizzle),
        .bank_rdb_valid        (mma_rdb_arb_valid),
        .bank_rdb_ready        (mma_rdb_arb_ready),
        .bank_rdb_row          (mma_rdb_arb_row),
        .bank_rdb_col          (mma_rdb_arb_col),
        .bank_rdb_swizzle      (mma_rdb_arb_swizzle),
        .bank_wr_valid         (mma_wr_arb_valid),
        .bank_wr_ready         (mma_wr_arb_ready),
        .bank_wr_row           (mma_wr_arb_row),
        .bank_wr_col           (mma_wr_arb_col),
        .bank_wr_swizzle       (mma_wr_arb_swizzle),
        .bank_wr_data          (mma_wr_arb_data),
        .bank_wr_be            (mma_wr_arb_be),
        .bank_rda_rsp_valid    (bank_rda_rsp_valid),
        .bank_rda_rsp_data     (bank_rda_rsp_data),
        .bank_rda_ecc_ce       (bank_rda_ecc_ce),
        .bank_rda_ecc_ue       (bank_rda_ecc_ue),
        .bank_rdb_rsp_valid    (bank_rdb_rsp_valid),
        .bank_rdb_rsp_data     (bank_rdb_rsp_data),
        .bank_rdb_ecc_ce       (bank_rdb_ecc_ce),
        .bank_rdb_ecc_ue       (bank_rdb_ecc_ue),
        .mma_rsp_valid         (mma_rsp_valid),
        .mma_rsp_ready         (mma_rsp_ready),
        .mma_rsp_op            (mma_rsp_op),
        .mma_rsp_tag           (mma_rsp_tag),
        .mma_rsp_status        (mma_rsp_status),
        .mma_rsp_data          (mma_rsp_data),
        .mma_rsp_lane_mask     (mma_rsp_lane_mask),
        .mma_rsp_ecc_ce        (mma_rsp_ecc_ce),
        .mma_rsp_ecc_ue        (mma_rsp_ecc_ue),
        .ping_pong_ptr_out     (mma_ping_pong_w),
        .mma_rd_beats_out      (mma_rd_beats_w),
        .mma_wr_beats_out      (mma_wr_beats_w)
    );

    // -------------------------------------------------------------------------
    // 8. 3-Client Priority + Deficit Round-Robin Arbiter
    // -------------------------------------------------------------------------
    VX_tmem_arbiter #(
        .LANES         (LANES),
        .NUM_BANKS     (NUM_BANKS),
        .AGE_THRESHOLD (8),
        .DEFICIT_MAX   (16)
    ) u_arbiter (
        .clk                       (clk),
        .reset                     (reset),
        .weight_ld                 (cfg_weight_ld),
        .weight_st                 (cfg_weight_st),
        .weight_mma                (cfg_weight_mma),
        .strict_mma_prio           (cfg_strict_mma_prio),
        .starve_limit              (cfg_starve_limit),
        .ld_req_valid              (ld_arb_valid),
        .ld_req_ready              (ld_arb_ready),
        .ld_req_row                (ld_arb_row),
        .ld_req_col                (ld_arb_col),
        .ld_req_swizzle            (ld_arb_swizzle),
        .st_req_valid              (st_arb_valid),
        .st_req_ready              (st_arb_ready),
        .st_req_row                (st_arb_row),
        .st_req_col                (st_arb_col),
        .st_req_swizzle            (st_arb_swizzle),
        .st_req_data               (st_arb_data),
        .st_req_be                 (st_arb_be),
        .mma_rda_valid             (mma_rda_arb_valid),
        .mma_rda_ready             (mma_rda_arb_ready),
        .mma_rda_row               (mma_rda_arb_row),
        .mma_rda_col               (mma_rda_arb_col),
        .mma_rda_swizzle           (mma_rda_arb_swizzle),
        .mma_rdb_valid             (mma_rdb_arb_valid),
        .mma_rdb_ready             (mma_rdb_arb_ready),
        .mma_rdb_row               (mma_rdb_arb_row),
        .mma_rdb_col               (mma_rdb_arb_col),
        .mma_rdb_swizzle           (mma_rdb_arb_swizzle),
        .mma_wr_valid              (mma_wr_arb_valid),
        .mma_wr_ready              (mma_wr_arb_ready),
        .mma_wr_row                (mma_wr_arb_row),
        .mma_wr_col                (mma_wr_arb_col),
        .mma_wr_swizzle            (mma_wr_arb_swizzle),
        .mma_wr_data               (mma_wr_arb_data),
        .mma_wr_be                 (mma_wr_arb_be),
        .bank_rda_valid            (bank_rda_valid),
        .bank_rda_ready            (bank_rda_ready),
        .bank_rda_row              (bank_rda_row),
        .bank_rda_col              (bank_rda_col),
        .bank_rda_swizzle          (bank_rda_swizzle),
        .bank_rdb_valid            (bank_rdb_valid),
        .bank_rdb_ready            (bank_rdb_ready),
        .bank_rdb_row              (bank_rdb_row),
        .bank_rdb_col              (bank_rdb_col),
        .bank_rdb_swizzle          (bank_rdb_swizzle),
        .bank_wr_valid             (bank_wr_valid),
        .bank_wr_ready             (bank_wr_ready),
        .bank_wr_row               (bank_wr_row),
        .bank_wr_col               (bank_wr_col),
        .bank_wr_swizzle           (bank_wr_swizzle),
        .bank_wr_data              (bank_wr_data),
        .bank_wr_be                (bank_wr_be),
        .grant_rda_is_mma_out      (grant_rda_is_mma_w),
        .grant_wr_is_mma_out       (grant_wr_is_mma_w),
        .ld_grants_out             (arb_ld_grants_w),
        .st_grants_out             (arb_st_grants_w),
        .mma_rda_grants_out        (arb_mma_rda_grants_w),
        .mma_rdb_grants_out        (arb_mma_rdb_grants_w),
        .mma_wr_grants_out         (arb_mma_wr_grants_w),
        .escalations_out           (arb_escalations_w),
        .conflict_stall_cycles_out (arb_conflict_stall_w)
    );

    // -------------------------------------------------------------------------
    // 9. 32-Bank ECC-Protected TMEM Storage Array
    // -------------------------------------------------------------------------
    VX_tmem_bank_array #(
        .NUM_BANKS  (NUM_BANKS),
        .BANK_DEPTH (BANK_DEPTH),
        .LANES      (LANES)
    ) u_bank_array (
        .clk                (clk),
        .reset              (reset),
        .rd_a_valid         (bank_rda_valid),
        .rd_a_ready         (bank_rda_ready),
        .rd_a_row           (bank_rda_row),
        .rd_a_col           (bank_rda_col),
        .rd_a_swizzle       (bank_rda_swizzle),
        .rd_a_rsp_valid     (bank_rda_rsp_valid),
        .rd_a_rsp_data      (bank_rda_rsp_data),
        .rd_a_ecc_ce        (bank_rda_ecc_ce),
        .rd_a_ecc_ue        (bank_rda_ecc_ue),
        .rd_b_valid         (bank_rdb_valid),
        .rd_b_ready         (bank_rdb_ready),
        .rd_b_row           (bank_rdb_row),
        .rd_b_col           (bank_rdb_col),
        .rd_b_swizzle       (bank_rdb_swizzle),
        .rd_b_rsp_valid     (bank_rdb_rsp_valid),
        .rd_b_rsp_data      (bank_rdb_rsp_data),
        .rd_b_ecc_ce        (bank_rdb_ecc_ce),
        .rd_b_ecc_ue        (bank_rdb_ecc_ue),
        .wr_valid           (bank_wr_valid),
        .wr_ready           (bank_wr_ready),
        .wr_row             (bank_wr_row),
        .wr_col             (bank_wr_col),
        .wr_swizzle         (bank_wr_swizzle),
        .wr_data            (bank_wr_data),
        .wr_be              (bank_wr_be),
        .ecc_inj_en         (ecc_inj_en),
        .ecc_inj_bank       (ecc_inj_bank),
        .ecc_inj_mask       (ecc_inj_mask),
        .scrub_en           (scrub_en),
        .rd_a_conflict_ways (rd_a_conflict_ways_w),
        .rd_b_conflict_ways (rd_b_conflict_ways_w),
        .wr_conflict_ways   (wr_conflict_ways_w),
        .ecc_ce_count       (bank_ecc_ce_count_w),
        .ecc_ue_count       (bank_ecc_ue_count_w)
    );

    // -------------------------------------------------------------------------
    // 10. Decoupled Wait / Fence & 2-CTA Barrier Sync Unit
    // -------------------------------------------------------------------------
    VX_tmem_wait_barrier #(
        .MAX_REGIONS    (TMEM_MAX_REGIONS),
        .NUM_WARPS      (32),
        .NUM_BARRIERS   (16),
        .TIMEOUT_CYCLES (4096)
    ) u_wait_barrier (
        .clk                    (clk),
        .reset                  (reset),
        .ld_launch_valid        (ld_haz_issue_fire),
        .ld_launch_region_id    (ld_haz_issue_region_id),
        .ld_launch_warp_id      (ld_haz_issue_warp_id),
        .st_launch_valid        (st_haz_issue_fire),
        .st_launch_region_id    (st_haz_issue_region_id),
        .st_launch_warp_id      (st_haz_issue_warp_id),
        .mma_launch_valid       (mma_haz_issue_fire),
        .mma_launch_region_id   (mma_haz_issue_region_id),
        .mma_launch_warp_id     (mma_haz_issue_warp_id),
        .ld_retire_valid        (ld_haz_commit_valid),
        .ld_retire_region_id    (ld_haz_commit_region_id),
        .ld_retire_warp_id      (ld_haz_commit_warp_id),
        .st_retire_valid        (st_haz_commit_valid),
        .st_retire_region_id    (st_haz_commit_region_id),
        .st_retire_warp_id      (st_haz_commit_warp_id),
        .mma_retire_valid       (mma_haz_commit_valid),
        .mma_retire_region_id   (mma_haz_commit_region_id),
        .mma_retire_warp_id     (mma_haz_commit_warp_id),
        .hazard_drained         (fence_drained),
        .wait_req_valid         (wait_req_valid),
        .wait_req_ready         (wait_req_ready),
        .wait_req_op            (wait_req_op),
        .wait_req_tag           (wait_req_tag),
        .wait_req_region_id     (wait_req_region_id),
        .wait_req_warp_id       (wait_req_warp_id),
        .wait_req_scope_warp    (wait_req_scope_warp),
        .wait_req_barrier_id    (wait_req_barrier_id),
        .wait_req_barrier_phase (wait_req_barrier_phase),
        .peer_bar_valid         (peer_bar_valid),
        .peer_bar_ready         (peer_bar_ready),
        .peer_bar_id            (peer_bar_id),
        .peer_bar_phase         (peer_bar_phase),
        .bar_wakeup_valid       (bar_wakeup_valid),
        .bar_wakeup_id          (bar_wakeup_id),
        .bar_wakeup_phase       (bar_wakeup_phase),
        .wait_rsp_valid         (wait_rsp_valid),
        .wait_rsp_ready         (wait_rsp_ready),
        .wait_rsp_op            (wait_rsp_op),
        .wait_rsp_tag           (wait_rsp_tag),
        .wait_rsp_status        (wait_rsp_status),
        .deadlock_fault_out     (deadlock_fault_out),
        .region_outstanding_out (wb_reg_outst_w),
        .warp_outstanding_out   (wb_warp_outst_w),
        .current_epoch_out      (wb_epoch_w),
        .wait_cycles_out        (wb_wait_cycles_w),
        .fence_completed_out    (wb_fence_done_w),
        .timeout_faults_out     (wb_timeout_faults_w)
    );

    // -------------------------------------------------------------------------
    // 11. Hardware Performance & Telemetry Monitor
    // -------------------------------------------------------------------------
    VX_tmem_perf_mon #(
        .LANES (LANES)
    ) u_perf_mon (
        .clk                     (clk),
        .reset                   (reset),
        .clear_counters          (perf_clear),
        .rd_a_fire               (bank_rda_valid & bank_rda_ready),
        .rd_b_fire               (bank_rdb_valid & bank_rdb_ready),
        .wr_fire                 (bank_wr_valid  & bank_wr_ready),
        .rd_a_conflict_ways      (rd_a_conflict_ways_w),
        .rd_b_conflict_ways      (rd_b_conflict_ways_w),
        .wr_conflict_ways        (wr_conflict_ways_w),
        .arb_conflict_stall      (arb_conflict_stall_pulse),
        .hazard_stall            (raw_stall_w | war_stall_w | waw_stall_w | haz_table_full_w),
        .wait_stall              (wait_req_valid & ~wait_req_ready),
        .alloc_fire              (alloc_valid && alloc_ready && (alloc_op == 3'd0)),
        .dealloc_fire            (alloc_valid && alloc_ready && (alloc_op == 3'd1)),
        .scrub_fire              (scrub_en),
        .occupied_granules_in    (occupied_granules_w),
        .ecc_ce_total_in         (bank_ecc_ce_count_w),
        .ecc_ue_total_in         (bank_ecc_ue_count_w),
        .oob_fault_total_in      (bounds_total_faults_w),
        .perf_cnt_out            (perf_cnt_out),
        .rd_a_beats_out          (pm_rd_a_beats_w),
        .rd_b_beats_out          (pm_rd_b_beats_w),
        .wr_beats_out            (pm_wr_beats_w),
        .hazard_stall_cycles_out (pm_haz_stall_w),
        .alloc_util_peak_out     (pm_util_peak_w),
        .ecc_ce_snap_out         (pm_ecc_ce_snap_w),
        .ecc_ue_snap_out         (pm_ecc_ue_snap_w),
        .oob_faults_snap_out     (pm_oob_snap_w),
        .active_cycles_out       (pm_active_cycles_w)
    );

    // Export top-level status/telemetry and tag unused internal diagnostic wires
    assign bounds_fault_out        = any_bounds_fault;
    assign bounds_fault_reason_out = bounds_fault_reason_w;
    assign ecc_ce_count_out        = bank_ecc_ce_count_w;
    assign ecc_ue_count_out        = bank_ecc_ue_count_w;
    assign occupied_granules_out   = occupied_granules_w;
    assign peak_granules_out       = peak_granules_w;

    `UNUSED_VAR (ld_bounds_fault)
    `UNUSED_VAR (st_bounds_fault)
    `UNUSED_VAR (mma_bounds_fault)
    `UNUSED_VAR (granule_bitmap)
    `UNUSED_VAR (active_regions_w)
    `UNUSED_VAR (alloc_ok_cnt_w)
    `UNUSED_VAR (alloc_err_cnt_w)
    `UNUSED_VAR (dealloc_cnt_w)
    `UNUSED_VAR (haz_epoch_w)
    `UNUSED_VAR (haz_inflight_w)
    `UNUSED_VAR (haz_stall_cycles_w)
    `UNUSED_VAR (haz_raw_cnt_w)
    `UNUSED_VAR (haz_war_cnt_w)
    `UNUSED_VAR (haz_waw_cnt_w)
    `UNUSED_VAR (bounds_fault_client_w)
    `UNUSED_VAR (bounds_fault_region_w)
    `UNUSED_VAR (bounds_fault_warp_w)
    `UNUSED_VAR (bounds_fault_row_w)
    `UNUSED_VAR (bounds_fault_col_w)
    `UNUSED_VAR (bounds_ld_cnt_w)
    `UNUSED_VAR (bounds_st_cnt_w)
    `UNUSED_VAR (bounds_mma_cnt_w)
    `UNUSED_VAR (grant_rda_is_mma_w)
    `UNUSED_VAR (grant_wr_is_mma_w)
    `UNUSED_VAR (arb_ld_grants_w)
    `UNUSED_VAR (arb_st_grants_w)
    `UNUSED_VAR (arb_mma_rda_grants_w)
    `UNUSED_VAR (arb_mma_rdb_grants_w)
    `UNUSED_VAR (arb_mma_wr_grants_w)
    `UNUSED_VAR (arb_escalations_w)
    `UNUSED_VAR (ld_beats_w)
    `UNUSED_VAR (ld_oob_faults_w)
    `UNUSED_VAR (st_beats_w)
    `UNUSED_VAR (st_oob_faults_w)
    `UNUSED_VAR (mma_ping_pong_w)
    `UNUSED_VAR (mma_rd_beats_w)
    `UNUSED_VAR (mma_wr_beats_w)
    `UNUSED_VAR (xform_ops_w)
    `UNUSED_VAR (wb_reg_outst_w)
    `UNUSED_VAR (wb_warp_outst_w)
    `UNUSED_VAR (wb_epoch_w)
    `UNUSED_VAR (wb_wait_cycles_w)
    `UNUSED_VAR (wb_fence_done_w)
    `UNUSED_VAR (wb_timeout_faults_w)
    `UNUSED_VAR (pm_rd_a_beats_w)
    `UNUSED_VAR (pm_rd_b_beats_w)
    `UNUSED_VAR (pm_wr_beats_w)
    `UNUSED_VAR (pm_haz_stall_w)
    `UNUSED_VAR (pm_util_peak_w)
    `UNUSED_VAR (pm_ecc_ce_snap_w)
    `UNUSED_VAR (pm_ecc_ue_snap_w)
    `UNUSED_VAR (pm_oob_snap_w)
    `UNUSED_VAR (pm_active_cycles_w)

endmodule
