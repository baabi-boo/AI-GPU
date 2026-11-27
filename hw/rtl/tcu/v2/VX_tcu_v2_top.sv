// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_top #(
    parameter int ARRAY_M   = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N   = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K   = VX_tcu_v2_pkg::TCU_V2_ARRAY_K,
    parameter int NUM_PIPES = 1
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // WGMMA descriptor submission
    input  logic                                    desc_valid,
    output logic                                    desc_ready,
    input  VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t       desc_in,
    // Tile operand feed (from TMEM MMA port or external feed)
    input  logic                                    tile_in_valid,
    output logic                                    tile_in_ready,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      a_tile_in,
    input  logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      b_tile_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      a_sparse_cand_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]      sparse_meta_in,
    input  logic [ARRAY_M-1:0][7:0]                 scale_a_in,
    input  logic [ARRAY_N-1:0][7:0]                 scale_b_in,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   c_tile_in,
    input  logic [ARRAY_N-1:0][31:0]                bias_in,
    // TMEM MMA address request output (read/write coordination)
    output logic                                    tmem_req_valid,
    input  logic                                    tmem_req_ready,
    output VX_tcu_v2_pkg::tcu_v2_tmem_req_t         tmem_req_out,
    // Tile output
    output logic                                    tile_out_valid,
    input  logic                                    tile_out_ready,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   d_tile_out,
    output logic [7:0]                              out_desc_id,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_out,
    // 2-CTA peer synchronization
    output logic                                    cta_sync_out_valid,
    input  logic                                    cta_sync_out_ready,
    output logic [3:0]                              cta_sync_out_bar_id,
    output logic                                    cta_sync_out_phase,
    input  logic                                    cta_sync_in_valid,
    output logic                                    cta_sync_in_ready,
    input  logic [3:0]                              cta_sync_in_bar_id,
    input  logic                                    cta_sync_in_phase,
    // Control & status register (CSR) interface
    input  logic                                    cfg_wr_valid = 1'b0,
    input  logic [7:0]                              cfg_wr_addr  = 8'd0,
    input  logic [31:0]                             cfg_wr_data  = 32'd0,
    input  logic                                    cfg_rd_valid = 1'b0,
    input  logic [7:0]                              cfg_rd_addr  = 8'd0,
    output logic                                    cfg_rd_rsp_valid,
    output logic [31:0]                             cfg_rd_rsp_data,
    // Completion & telemetry
    output logic                                    desc_done_valid,
    output logic [7:0]                              desc_done_id,
    output logic                                    sparse_fault,
    output logic                                    sparse_decomp_valid_out,
    output logic                                    sparse_decomp_illegal_out,
    output VX_tcu_v2_pkg::tcu_v2_perf_cnt_t         perf_cnt_out
);

    import VX_tcu_v2_pkg::*;

    localparam int PIPE_W      = $clog2(NUM_PIPES > 1 ? NUM_PIPES : 2);
    localparam int DESC_DEPTH  = TCU_V2_DESC_Q_DEPTH;
    localparam int BAR_DEPTH   = TCU_V2_MAX_BARRIERS;

    // -------------------------------------------------------------------------
    // Descriptor Queue & Scoreboard Signals
    // -------------------------------------------------------------------------
    logic                               q_deq_valid_w;
    logic                               q_deq_ready_w;
    tcu_v2_wgmma_desc_t                 q_deq_desc_w;
    tcu_v2_wgmma_desc_t                 q_peek_desc_w;
    logic                               q_peek_valid_w;
    logic                               q_empty_w;
    logic                               q_full_w;
    logic [$clog2(DESC_DEPTH+1)-1:0]    q_occupancy_w;
    logic [$clog2(DESC_DEPTH+1)-1:0]    q_credits_w;
    logic                               q_reject_pulse_w;
    logic [TCU_V2_DESC_ID_W-1:0]        q_reject_id_w;
    logic [31:0]                        q_acc_cnt_w;
    logic [31:0]                        q_rej_cnt_w;
    logic [31:0]                        q_flu_cnt_w;

    logic                               sb_alloc_valid_w;
    logic                               sb_alloc_ready_w;
    logic [PIPE_W-1:0]                  sb_alloc_pipe_w;
    logic                               sb_haz_raw_w;
    logic                               sb_haz_war_w;
    logic                               sb_haz_waw_w;
    logic                               sb_haz_any_w;
    logic [DESC_DEPTH-1:0]              sb_haz_mask_w;
    logic                               sb_commit_idle_w;
    logic                               sb_retire_pulse_w;
    logic [TCU_V2_DESC_ID_W-1:0]        sb_retire_id_w;
    logic [DESC_DEPTH-1:0]              sb_inflight_mask_w;
    logic [$clog2(DESC_DEPTH+1)-1:0]    sb_inflight_cnt_w;
    logic [31:0]                        sb_retired_cnt_w;
    logic [31:0]                        sb_haz_stall_cnt_w;

    // -------------------------------------------------------------------------
    // Barrier Unit & 2-CTA Peer Sync Signals
    // -------------------------------------------------------------------------
    logic                               bar_cmd_valid_w;
    logic                               bar_cmd_ready_w;
    logic [2:0]                         bar_cmd_op_w;
    logic [TCU_V2_BARRIER_ID_W-1:0]     bar_cmd_id_w;
    logic [15:0]                        bar_cmd_cnt_w;
    logic                               bar_cmd_phase_w;
    logic                               bar_wait_valid_w;
    logic                               bar_wait_pass_w;
    logic                               bar_wakeup_valid_w;
    logic [TCU_V2_BARRIER_ID_W-1:0]     bar_wakeup_id_w;
    logic                               bar_wakeup_phase_w;
    logic                               bar_status_valid_w;
    logic                               bar_status_phase_w;
    logic [15:0]                        bar_status_arr_w;
    logic [15:0]                        bar_status_tx_w;
    logic [BAR_DEPTH-1:0]               bar_active_mask_w;
    logic [BAR_DEPTH-1:0]               bar_phase_vec_w;
    logic                               bar_stall_w;
    logic [31:0]                        bar_flips_cnt_w;
    logic [31:0]                        bar_stall_cycles_w;

    logic                               cta_req_valid_w;
    logic                               cta_req_ready_w;
    logic                               cta_gate_open_w;
    logic                               cta_m_half_w;
    logic                               cta_n_half_w;
    logic                               cta_sync_busy_w;
    logic                               cta_sync_stall_w;
    logic                               cta_wdt_timeout_w;
    logic [31:0]                        cta_pair_cnt_w;
    logic [31:0]                        cta_wait_cycles_w;

    // -------------------------------------------------------------------------
    // Expander, Pipe Scheduler, and TMEM Request Generator Signals
    // -------------------------------------------------------------------------
    logic                               exp_desc_valid_w;
    logic                               exp_desc_ready_w;
    logic                               exp_uop_valid_w;
    logic                               exp_uop_ready_w;
    tcu_v2_uop_t                        exp_uop_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]       exp_a_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]       exp_a_col_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]       exp_b_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]       exp_b_col_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]       exp_c_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]       exp_c_col_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]       exp_d_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]       exp_d_col_w;
    logic                               exp_tmem_valid_w;
    logic                               exp_tmem_ready_w;
    tcu_v2_tmem_req_t                   exp_tmem_req_w;
    logic                               exp_done_w;
    logic [TCU_V2_DESC_ID_W-1:0]        exp_desc_id_w;
    logic                               exp_busy_w;
    logic [31:0]                        exp_uops_cnt_w;

    logic [NUM_PIPES-1:0]               sched_req_valid_w;
    logic [NUM_PIPES-1:0]               sched_req_ready_w;
    logic [NUM_PIPES-1:0]               sched_haz_stall_w;
    logic [NUM_PIPES-1:0]               sched_bar_wait_w;
    tcu_v2_uop_t [NUM_PIPES-1:0]        sched_uop_in_w;
    logic [NUM_PIPES-1:0]               sched_credit_ret_w;
    logic                               sched_issue_valid_w;
    logic                               sched_issue_ready_w;
    logic [PIPE_W-1:0]                  sched_issue_pipe_w;
    tcu_v2_uop_t                        sched_issue_uop_w;
    logic [NUM_PIPES-1:0][3:0]          sched_credits_w;
    logic [NUM_PIPES-1:0][7:0]          sched_age_w;
    logic [NUM_PIPES-1:0]               sched_starved_w;
    logic [31:0]                        sched_issues_cnt_w;
    logic [31:0]                        sched_stall_cnt_w;

    logic                               tmem_gen_uop_ready_w;
    logic                               tmem_gen_req_valid_w;
    logic                               tmem_gen_req_ready_w;
    tcu_v2_tmem_req_t                   tmem_gen_req_w;
    logic                               tmem_gen_busy_w;
    logic                               tmem_gen_stall_w;
    logic [31:0]                        tmem_rd_a_cnt_w;
    logic [31:0]                        tmem_rd_b_cnt_w;
    logic [31:0]                        tmem_rd_c_cnt_w;
    logic [31:0]                        tmem_wr_d_cnt_w;

    // -------------------------------------------------------------------------
    // Sparse Datapath & Systolic Array Signals
    // -------------------------------------------------------------------------
    logic                               sp_fault_det_comb_w;
    logic [ARRAY_M-1:0][ARRAY_K*4-1:0]  sp_err_mask_comb_w;
    logic                               sp_val_valid_w;
    logic                               sp_fault_det_w;
    logic                               sp_fault_sticky_w;
    logic                               sp_fmt_illegal_w;
    logic [ARRAY_M-1:0][ARRAY_K*4-1:0]  sp_err_mask_w;
    logic [TCU_V2_DESC_ID_W-1:0]        sp_val_desc_id_w;
    logic [7:0]                         sp_syn_row_w;
    logic [7:0]                         sp_syn_grp_w;
    tcu_v2_sparse_meta4_t               sp_syn_meta_w;
    logic [TCU_V2_DESC_ID_W-1:0]        sp_syn_desc_id_w;
    logic [3:0]                         sp_syn_code_w;
    logic [15:0]                        sp_chk_tiles_w;
    logic [15:0]                        sp_flt_events_w;
    logic [15:0]                        sp_cmp_mismatch_w;

    logic                               sp_comp_ready_w;
    logic                               sp_comp_valid_w;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] sp_comp_data_w;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] sp_comp_meta_w;
    logic                               sp_prune_loss_w;
    logic [15:0]                        sp_pruned_grps_w;
    logic [15:0]                        sp_exact_grps_w;

    logic                               sp_sel_ready_w;
    logic                               sp_sel_valid_w;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] sp_a_selected_w;
    logic                               sp_fault_masked_w;
    logic [15:0]                        sp_active_lanes_w;

    logic                               arr_uop_valid_w;
    logic                               arr_uop_ready_w;
    logic                               arr_out_valid_w;
    logic                               arr_out_ready_w;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] arr_d_tile_w;
    logic [TCU_V2_DESC_ID_W-1:0]        arr_out_desc_id_w;
    tcu_v2_fp_flags_t                   arr_flags_out_w;
    logic                               arr_busy_w;
    logic [31:0]                        arr_active_cyc_w;

    // -------------------------------------------------------------------------
    // Additional Control Subsystem Signals (Arbiter, Prefetch, Mapper, ROB, CSR)
    // -------------------------------------------------------------------------
    logic [1:0]                         arb_req_valid_w;
    logic [1:0]                         arb_req_ready_w;
    tcu_v2_wgmma_desc_t [1:0]           arb_req_desc_w;
    logic [1:0][3:0]                    arb_req_prio_w;
    logic                               arb_grant_valid_w;
    logic                               arb_grant_ready_w;
    tcu_v2_wgmma_desc_t                 arb_grant_desc_w;
    logic                               arb_grant_qid_w;
    logic [1:0][31:0]                   arb_qid_grants_w;
    logic [31:0]                        arb_conflicts_w;

    logic                               pf_out_valid_w;
    logic                               pf_out_ready_w;
    logic                               pf_buf_sel_w;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] pf_a_tile_w;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] pf_b_tile_w;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] pf_a_cand_w;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] pf_meta_w;
    logic [ARRAY_M-1:0][7:0]            pf_scale_a_w;
    logic [ARRAY_N-1:0][7:0]            pf_scale_b_w;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] pf_c_tile_w;
    logic [ARRAY_N-1:0][31:0]           pf_bias_w;
    logic [1:0]                         pf_occ_w;
    logic [31:0]                        pf_swaps_w;
    logic [31:0]                        pf_stalls_w;

    logic                               decomp_ready_w;
    logic                               decomp_valid_w;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] decomp_lo_w;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] decomp_hi_w;
    logic [ARRAY_M-1:0][ARRAY_K*8-1:0]  decomp_occ_w;
    logic [15:0]                        decomp_active_w;
    logic                               decomp_illegal_w;
    logic                               decomp_chk_err_w;

    logic                               map_req_ready_w;
    logic                               map_out_valid_w;
    logic                               map_out_ready_w;
    tcu_v2_tmem_req_t                   map_req_out_w;
    logic [4:0]                         map_bank_id_w;
    logic [9:0]                         map_word_addr_w;
    logic                               map_half_sel_w;
    logic                               map_conflict_w;
    logic                               map_bounds_err_w;
    logic [31:0]                        map_cnt_w;
    logic [31:0]                        map_conflict_cnt_w;

    logic                               rob_enq_ready_w;
    logic                               rob_fence_done_w;
    logic                               rob_commit_valid_w;
    logic [TCU_V2_DESC_ID_W-1:0]        rob_commit_id_w;
    tcu_v2_fp_flags_t                   rob_commit_flags_w;
    logic                               rob_commit_bar_arr_w;
    logic [TCU_V2_BARRIER_ID_W-1:0]     rob_commit_bar_id_w;
    logic                               rob_commit_bar_ph_w;
    logic                               rob_empty_w;
    logic                               rob_full_w;
    logic [$clog2(DESC_DEPTH+1)-1:0]    rob_count_w;
    logic [31:0]                        rob_committed_cnt_w;
    logic [31:0]                        rob_fence_cycles_w;

    logic                               csr_rd_rsp_valid_w;
    logic [31:0]                        csr_rd_rsp_data_w;
    logic [1:0]                         csr_swizzle_mode_w;
    logic                               csr_fault_clear_w;
    logic                               csr_perf_clear_w;
    logic                               csr_wdt_clear_w;
    logic                               csr_fence_req_w;
    logic                               csr_split_n_mode_w;
    logic                               csr_local_cta_rank_w;
    logic [8:0]                         csr_dbl_buf_stride_w;
    logic [31:0]                        csr_wr_cnt_w;

    // -------------------------------------------------------------------------
    // Descriptor Dispatch & Tile Staging Registers
    // -------------------------------------------------------------------------
    logic                               dispatch_can_fire_w;
    logic                               dispatch_fire_w;
    logic                               active_tmem_wb_r;
    logic [PIPE_W-1:0]                  next_pipe_r;
    logic                               dbl_buf_toggle_r;

    logic                               uop_buf_valid_r;
    tcu_v2_uop_t                        uop_buf_r;
    logic [PIPE_W-1:0]                  uop_buf_pipe_r;
    logic                               tile_latched_r;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] a_tile_lat_r;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] b_tile_lat_r;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] a_cand_lat_r;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] sp_meta_lat_r;
    logic [ARRAY_M-1:0][7:0]            scale_a_lat_r;
    logic [ARRAY_N-1:0][7:0]            scale_b_lat_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] c_tile_lat_r;
    logic [ARRAY_N-1:0][31:0]           bias_lat_r;

    logic                               sp_sel_pending_r;
    tcu_v2_uop_t                        sp_sel_uop_r;
    logic [PIPE_W-1:0]                  sp_sel_pipe_r;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] sp_sel_b_r;
    logic [ARRAY_M-1:0][7:0]            sp_sel_sa_r;
    logic [ARRAY_N-1:0][7:0]            sp_sel_sb_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] sp_sel_c_r;
    logic [ARRAY_N-1:0][31:0]           sp_sel_bias_r;

    localparam int PIPE_FIFO_DEPTH = 32;
    localparam int PIPE_FIFO_PTR_W = $clog2(PIPE_FIFO_DEPTH);
    localparam int PIPE_FIFO_CNT_W = $clog2(PIPE_FIFO_DEPTH + 1);

    logic [PIPE_FIFO_DEPTH-1:0][PIPE_W-1:0] pipe_fifo_r;
    logic [PIPE_FIFO_PTR_W-1:0]             pipe_fifo_wr_r;
    logic [PIPE_FIFO_PTR_W-1:0]             pipe_fifo_rd_r;
    logic [PIPE_FIFO_CNT_W-1:0]             pipe_fifo_cnt_r;
    logic                                   pipe_fifo_push_w;
    logic                                   pipe_fifo_pop_w;

    logic [TCU_V2_DESC_ID_W-1:0]        last_retired_uop_id_r;
    logic                               last_retired_uop_valid_r;
    logic                               last_retired_uop_last_r;

    tcu_v2_tmem_req_t                   tmem_req_out_r;
    logic                               tmem_req_valid_r;
    logic                               desc_done_valid_r;
    logic [7:0]                         desc_done_id_r;
    logic                               sparse_fault_r;
    logic                               decomp_valid_out_r;
    logic                               decomp_illegal_out_r;
    tcu_v2_perf_cnt_t                   perf_cnt_out_r;

    // -------------------------------------------------------------------------
    // 0. Descriptor Arbiter & Control Regfile
    // -------------------------------------------------------------------------
    assign arb_req_valid_w[0] = desc_valid;
    assign arb_req_valid_w[1] = 1'b0;
    assign arb_req_desc_w[0]  = desc_in;
    assign arb_req_desc_w[1]  = '0;
    assign arb_req_prio_w[0]  = 4'd1;
    assign arb_req_prio_w[1]  = 4'd0;

    VX_tcu_v2_desc_arbiter #(
        .NUM_QUEUES (2)
    ) u_desc_arbiter (
        .clk                  (clk),
        .reset                (reset),
        .req_valid            (arb_req_valid_w),
        .req_ready            (arb_req_ready_w),
        .req_desc             (arb_req_desc_w),
        .req_prio             (arb_req_prio_w),
        .grant_valid          (arb_grant_valid_w),
        .grant_ready          (arb_grant_ready_w),
        .grant_desc           (arb_grant_desc_w),
        .grant_qid            (arb_grant_qid_w),
        .qid_grant_cnt_out    (arb_qid_grants_w),
        .arb_conflict_cnt_out (arb_conflicts_w)
    );

    assign desc_ready = arb_req_ready_w[0];

    VX_tcu_v2_ctrl_regfile #(
        .NUM_PIPES (NUM_PIPES)
    ) u_ctrl_regfile (
        .clk                      (clk),
        .reset                    (reset),
        .cfg_wr_valid             (cfg_wr_valid),
        .cfg_wr_addr              (cfg_wr_addr),
        .cfg_wr_data              (cfg_wr_data),
        .cfg_rd_valid             (cfg_rd_valid),
        .cfg_rd_addr              (cfg_rd_addr),
        .cfg_rd_rsp_valid         (csr_rd_rsp_valid_w),
        .cfg_rd_rsp_data          (csr_rd_rsp_data_w),
        .perf_cnt_in              (pmu_perf_cnt_w),
        .fault_sticky_in          (sp_fault_sticky_w),
        .syndrome_code_in         (sp_syn_code_w),
        .syndrome_row_in          (sp_syn_row_w),
        .syndrome_group_in        (sp_syn_grp_w),
        .syndrome_desc_id_in      (sp_syn_desc_id_w),
        .decomp_valid_in          (decomp_valid_w),
        .decomp_illegal_in        (decomp_illegal_w || decomp_chk_err_w),
        .decomp_active_elems_in   (decomp_active_w),
        .swizzle_mode_out         (csr_swizzle_mode_w),
        .fault_clear_pulse_out    (csr_fault_clear_w),
        .perf_clear_pulse_out     (csr_perf_clear_w),
        .watchdog_clear_pulse_out (csr_wdt_clear_w),
        .commit_fence_req_out     (csr_fence_req_w),
        .split_n_mode_out         (csr_split_n_mode_w),
        .local_cta_rank_out       (csr_local_cta_rank_w),
        .dbl_buf_stride_out       (csr_dbl_buf_stride_w),
        .ctrl_reg_writes_out      (csr_wr_cnt_w)
    );

    assign cfg_rd_rsp_valid = csr_rd_rsp_valid_w;
    assign cfg_rd_rsp_data  = csr_rd_rsp_data_w;

    // -------------------------------------------------------------------------
    // 1. WGMMA Descriptor FIFO
    // -------------------------------------------------------------------------
    VX_tcu_v2_wgmma_desc_q #(
        .DEPTH (DESC_DEPTH)
    ) u_desc_q (
        .clk                (clk),
        .reset              (reset),
        .flush              (1'b0),
        .enq_valid          (arb_grant_valid_w),
        .enq_ready          (arb_grant_ready_w),
        .enq_desc           (arb_grant_desc_w),
        .deq_ready          (q_deq_ready_w),
        .deq_valid          (q_deq_valid_w),
        .deq_desc           (q_deq_desc_w),
        .peek_desc          (q_peek_desc_w),
        .peek_valid         (q_peek_valid_w),
        .empty              (q_empty_w),
        .full               (q_full_w),
        .occupancy          (q_occupancy_w),
        .credits_avail      (q_credits_w),
        .reject_pulse       (q_reject_pulse_w),
        .reject_desc_id     (q_reject_id_w),
        .total_accepted_cnt (q_acc_cnt_w),
        .total_rejected_cnt (q_rej_cnt_w),
        .total_flushed_cnt  (q_flu_cnt_w)
    );

    // -------------------------------------------------------------------------
    // 2. Async WGMMA Scoreboard & In-Order Commit ROB
    // -------------------------------------------------------------------------
    assign dispatch_can_fire_w = q_deq_valid_w &&
                                 !q_empty_w &&
                                 !sb_haz_any_w &&
                                 !sb_haz_raw_w &&
                                 !sb_haz_war_w &&
                                 !sb_haz_waw_w;
    assign q_deq_ready_w       = sb_alloc_ready_w &&
                                 rob_enq_ready_w &&
                                 exp_desc_ready_w &&
                                 cta_req_ready_w &&
                                 !sb_haz_any_w &&
                                 !sb_haz_raw_w &&
                                 !sb_haz_war_w &&
                                 !sb_haz_waw_w;
    assign sb_alloc_valid_w    = dispatch_can_fire_w && rob_enq_ready_w && exp_desc_ready_w && cta_req_ready_w;
    assign sb_alloc_pipe_w     = next_pipe_r;
    assign exp_desc_valid_w    = dispatch_can_fire_w && sb_alloc_ready_w && rob_enq_ready_w && cta_req_ready_w;
    assign cta_req_valid_w     = dispatch_can_fire_w && sb_alloc_ready_w && rob_enq_ready_w && exp_desc_ready_w;
    assign dispatch_fire_w     = dispatch_can_fire_w &&
                                 sb_alloc_ready_w &&
                                 rob_enq_ready_w &&
                                 exp_desc_ready_w &&
                                 cta_req_ready_w;

    VX_tcu_v2_wgmma_scoreboard #(
        .DEPTH     (DESC_DEPTH),
        .NUM_PIPES (NUM_PIPES),
        .ARRAY_M   (ARRAY_M),
        .ARRAY_N   (ARRAY_N)
    ) u_scoreboard (
        .clk                     (clk),
        .reset                   (reset),
        .alloc_valid             (sb_alloc_valid_w),
        .alloc_ready             (sb_alloc_ready_w),
        .alloc_desc              (q_deq_desc_w),
        .alloc_pipe_id           (sb_alloc_pipe_w),
        .query_valid             (q_peek_valid_w),
        .query_desc              (q_peek_desc_w),
        .hazard_raw_out          (sb_haz_raw_w),
        .hazard_war_out          (sb_haz_war_w),
        .hazard_waw_out          (sb_haz_waw_w),
        .hazard_any_out          (sb_haz_any_w),
        .hazard_slot_mask_out    (sb_haz_mask_w),
        .uop_retire_valid        (last_retired_uop_valid_r),
        .uop_retire_desc_id      (last_retired_uop_id_r),
        .uop_retire_last         (last_retired_uop_last_r),
        .commit_group_fence_en   (csr_fence_req_w),
        .commit_group_idle_out   (sb_commit_idle_w),
        .retire_pulse_out        (sb_retire_pulse_w),
        .retire_desc_id_out      (sb_retire_id_w),
        .inflight_mask_out       (sb_inflight_mask_w),
        .inflight_count_out      (sb_inflight_cnt_w),
        .descs_retired_cnt_out   (sb_retired_cnt_w),
        .hazard_stall_cnt_out    (sb_haz_stall_cnt_w)
    );

    VX_tcu_v2_commit_ctrl #(
        .DEPTH (DESC_DEPTH)
    ) u_commit_ctrl (
        .clk               (clk),
        .reset             (reset),
        .enq_valid         (dispatch_can_fire_w && sb_alloc_ready_w && exp_desc_ready_w && cta_req_ready_w),
        .enq_ready         (rob_enq_ready_w),
        .enq_desc_id       (q_deq_desc_w.desc_id),
        .enq_tmem_wb_en    (q_deq_desc_w.tmem_wb_en),
        .enq_barrier_id    (q_deq_desc_w.barrier_id),
        .enq_barrier_phase (q_deq_desc_w.barrier_phase),
        .enq_uop_total     (16'(tcu_v2_output_tile_count_for_desc(q_deq_desc_w, ARRAY_M, ARRAY_N))),
        .uop_wb_valid      (arr_out_valid_w && arr_out_ready_w),
        .uop_wb_desc_id    (arr_out_desc_id_w),
        .uop_wb_flags      (arr_flags_out_w),
        .fence_req         (csr_fence_req_w),
        .fence_done        (rob_fence_done_w),
        .commit_valid      (rob_commit_valid_w),
        .commit_ready      (bar_cmd_ready_w),
        .commit_desc_id    (rob_commit_id_w),
        .commit_flags      (rob_commit_flags_w),
        .commit_bar_arrive (rob_commit_bar_arr_w),
        .commit_bar_id     (rob_commit_bar_id_w),
        .commit_bar_phase  (rob_commit_bar_ph_w),
        .rob_empty         (rob_empty_w),
        .rob_full          (rob_full_w),
        .rob_count         (rob_count_w),
        .committed_cnt_out (rob_committed_cnt_w),
        .fence_cycles_out  (rob_fence_cycles_w)
    );

    // -------------------------------------------------------------------------
    // 3. Hardware Barrier Unit
    // -------------------------------------------------------------------------
    assign bar_cmd_valid_w  = (rob_commit_valid_w && rob_commit_bar_arr_w) ||
                              (sb_retire_pulse_w && !rob_commit_valid_w);
    assign bar_cmd_op_w     = 3'd2;
    assign bar_cmd_id_w     = rob_commit_valid_w ? rob_commit_bar_id_w :
                              (q_peek_valid_w ? q_peek_desc_w.barrier_id : '0);
    assign bar_cmd_cnt_w    = 16'd1;
    assign bar_cmd_phase_w  = rob_commit_valid_w ? rob_commit_bar_ph_w :
                              (q_peek_valid_w ? q_peek_desc_w.barrier_phase : 1'b0);
    assign bar_wait_valid_w = 1'b0;

    VX_tcu_v2_barrier_unit #(
        .NUM_BARRIERS (BAR_DEPTH)
    ) u_barrier_unit (
        .clk                   (clk),
        .reset                 (reset),
        .cmd_valid             (bar_cmd_valid_w),
        .cmd_ready             (bar_cmd_ready_w),
        .cmd_op                (bar_cmd_op_w),
        .cmd_bar_id            (bar_cmd_id_w),
        .cmd_count             (bar_cmd_cnt_w),
        .cmd_phase             (bar_cmd_phase_w),
        .wait_valid            (bar_wait_valid_w),
        .wait_bar_id           (q_peek_desc_w.barrier_id),
        .wait_phase            (q_peek_desc_w.barrier_phase),
        .wait_pass_out         (bar_wait_pass_w),
        .wakeup_valid_out      (bar_wakeup_valid_w),
        .wakeup_bar_id_out     (bar_wakeup_id_w),
        .wakeup_phase_out      (bar_wakeup_phase_w),
        .status_bar_id         (q_peek_desc_w.barrier_id),
        .status_valid_out      (bar_status_valid_w),
        .status_phase_out      (bar_status_phase_w),
        .status_arrive_rem_out (bar_status_arr_w),
        .status_tx_rem_out     (bar_status_tx_w),
        .bar_active_mask_out   (bar_active_mask_w),
        .bar_phase_vec_out     (bar_phase_vec_w),
        .bar_stall_out         (bar_stall_w),
        .phase_flips_cnt_out   (bar_flips_cnt_w),
        .wait_stall_cycles_out (bar_stall_cycles_w)
    );

    // -------------------------------------------------------------------------
    // 4. 2-CTA Cooperative Pair Synchronizer
    // -------------------------------------------------------------------------
    VX_tcu_v2_cta_pair_sync #(
        .WATCHDOG_LIMIT (4096)
    ) u_cta_pair_sync (
        .clk                  (clk),
        .reset                (reset),
        .req_valid            (cta_req_valid_w),
        .req_ready            (cta_req_ready_w),
        .cta_pair_en          (q_deq_desc_w.cta_pair_en),
        .split_n_mode         (csr_split_n_mode_w),
        .local_cta_rank       (csr_local_cta_rank_w),
        .desc_id_in           (q_deq_desc_w.desc_id),
        .bar_id_in            (q_deq_desc_w.barrier_id),
        .phase_in             (q_deq_desc_w.barrier_phase),
        .peer_done_release    (exp_done_w),
        .exec_gate_open_out   (cta_gate_open_w),
        .exec_m_half_sel_out  (cta_m_half_w),
        .exec_n_half_sel_out  (cta_n_half_w),
        .sync_busy_out        (cta_sync_busy_w),
        .sync_stall_out       (cta_sync_stall_w),
        .watchdog_timeout_out (cta_wdt_timeout_w),
        .watchdog_clear       (csr_wdt_clear_w),
        .cta_sync_out_valid   (cta_sync_out_valid),
        .cta_sync_out_ready   (cta_sync_out_ready),
        .cta_sync_out_bar_id  (cta_sync_out_bar_id),
        .cta_sync_out_phase   (cta_sync_out_phase),
        .cta_sync_in_valid    (cta_sync_in_valid),
        .cta_sync_in_ready    (cta_sync_in_ready),
        .cta_sync_in_bar_id   (cta_sync_in_bar_id),
        .cta_sync_in_phase    (cta_sync_in_phase),
        .pair_sync_count_out  (cta_pair_cnt_w),
        .sync_wait_cycles_out (cta_wait_cycles_w)
    );

    // -------------------------------------------------------------------------
    // 5. Micro-Op Expander
    // -------------------------------------------------------------------------
    VX_tcu_v2_uop_expander #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_uop_expander (
        .clk                  (clk),
        .reset                (reset),
        .desc_valid           (exp_desc_valid_w),
        .desc_ready           (exp_desc_ready_w),
        .desc_in              (q_deq_desc_w),
        .cta_gate_open        (cta_gate_open_w),
        .cta_m_half_sel       (cta_m_half_w),
        .cta_n_half_sel       (cta_n_half_w),
        .swizzle_mode_in      (csr_swizzle_mode_w),
        .uop_valid            (exp_uop_valid_w),
        .uop_ready            (exp_uop_ready_w),
        .uop_out              (exp_uop_w),
        .a_tmem_row_out       (exp_a_row_w),
        .a_tmem_col_out       (exp_a_col_w),
        .b_tmem_row_out       (exp_b_row_w),
        .b_tmem_col_out       (exp_b_col_w),
        .c_tmem_row_out       (exp_c_row_w),
        .c_tmem_col_out       (exp_c_col_w),
        .d_tmem_row_out       (exp_d_row_w),
        .d_tmem_col_out       (exp_d_col_w),
        .tmem_req_valid       (exp_tmem_valid_w),
        .tmem_req_ready       (exp_tmem_ready_w),
        .tmem_req_out         (exp_tmem_req_w),
        .desc_expand_done     (exp_done_w),
        .active_desc_id_out   (exp_desc_id_w),
        .busy_out             (exp_busy_w),
        .uops_emitted_cnt_out (exp_uops_cnt_w)
    );

    assign exp_uop_ready_w  = !uop_buf_valid_r && tmem_gen_uop_ready_w;
    assign exp_tmem_ready_w = 1'b1;

    // -------------------------------------------------------------------------
    // 6. TMEM MMA Request Generator & Bank Address Mapper
    // -------------------------------------------------------------------------
    VX_tcu_v2_tmem_req_gen #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_tmem_req_gen (
        .clk                (clk),
        .reset              (reset),
        .uop_valid          (exp_uop_valid_w && !uop_buf_valid_r),
        .uop_ready          (tmem_gen_uop_ready_w),
        .uop_in             (exp_uop_w),
        .tmem_wb_en_in      (active_tmem_wb_r),
        .swizzle_mode_in    (csr_swizzle_mode_w),
        .dbl_buf_toggle_in  (dbl_buf_toggle_r),
        .a_row_in           (exp_a_row_w),
        .a_col_in           (exp_a_col_w),
        .b_row_in           (exp_b_row_w),
        .b_col_in           (exp_b_col_w),
        .c_row_in           (exp_c_row_w),
        .c_col_in           (exp_c_col_w),
        .d_row_in           (exp_d_row_w),
        .d_col_in           (exp_d_col_w),
        .dbl_buf_col_stride (csr_dbl_buf_stride_w),
        .tmem_req_valid     (tmem_gen_req_valid_w),
        .tmem_req_ready     (tmem_gen_req_ready_w),
        .tmem_req_out       (tmem_gen_req_w),
        .busy_out           (tmem_gen_busy_w),
        .tmem_stall_out     (tmem_gen_stall_w),
        .rd_a_cnt_out       (tmem_rd_a_cnt_w),
        .rd_b_cnt_out       (tmem_rd_b_cnt_w),
        .rd_c_cnt_out       (tmem_rd_c_cnt_w),
        .wr_d_cnt_out       (tmem_wr_d_cnt_w)
    );

    assign tmem_gen_req_ready_w = map_req_ready_w;

    VX_tcu_v2_tmem_addr_mapper #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_tmem_addr_mapper (
        .clk                   (clk),
        .reset                 (reset),
        .req_valid             (tmem_gen_req_valid_w),
        .req_ready             (map_req_ready_w),
        .tmem_req_in           (tmem_gen_req_w),
        .swizzle_override_en   (2'b00),
        .swizzle_override_mode (csr_swizzle_mode_w),
        .mapped_valid          (map_out_valid_w),
        .mapped_ready          (map_out_ready_w),
        .mapped_req_out        (map_req_out_w),
        .phys_bank_id_out      (map_bank_id_w),
        .phys_word_addr_out    (map_word_addr_w),
        .phys_half_sel_out     (map_half_sel_w),
        .conflict_warn_out     (map_conflict_w),
        .bounds_err_out        (map_bounds_err_w),
        .mapped_cnt_out        (map_cnt_w),
        .bank_conflict_cnt_out (map_conflict_cnt_w)
    );

    assign map_out_ready_w = !tmem_req_valid_r || tmem_req_ready;

    // -------------------------------------------------------------------------
    // 7. Tile Prefetch Double-Buffer & Multi-Pipe Issue Scheduler
    // -------------------------------------------------------------------------
    VX_tcu_v2_tile_prefetch_ctrl #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_tile_prefetch_ctrl (
        .clk                (clk),
        .reset              (reset),
        .tile_in_valid      (tile_in_valid),
        .tile_in_ready      (tile_in_ready),
        .uop_is_sparse      (uop_buf_valid_r ? uop_buf_r.sparse_en : 1'b0),
        .a_tile_in          (a_tile_in),
        .b_tile_in          (b_tile_in),
        .a_cand_in          (a_sparse_cand_in),
        .meta_in            (sparse_meta_in),
        .scale_a_in         (scale_a_in),
        .scale_b_in         (scale_b_in),
        .c_tile_in          (c_tile_in),
        .bias_in            (bias_in),
        .tile_out_valid     (pf_out_valid_w),
        .tile_out_ready     (pf_out_ready_w),
        .buf_sel_out        (pf_buf_sel_w),
        .a_tile_out         (pf_a_tile_w),
        .b_tile_out         (pf_b_tile_w),
        .a_cand_out         (pf_a_cand_w),
        .meta_out           (pf_meta_w),
        .scale_a_out        (pf_scale_a_w),
        .scale_b_out        (pf_scale_b_w),
        .c_tile_out         (pf_c_tile_w),
        .bias_out           (pf_bias_w),
        .occupancy_out      (pf_occ_w),
        .pingpong_swaps_out (pf_swaps_w),
        .stall_cycles_out   (pf_stalls_w)
    );

    assign pf_out_ready_w = !tile_latched_r;

    always_comb begin
        sched_req_valid_w  = '0;
        sched_haz_stall_w  = '0;
        sched_bar_wait_w   = '0;
        sched_credit_ret_w = '0;
        for (int p = 0; p < NUM_PIPES; ++p) begin
            sched_uop_in_w[p] = uop_buf_r;
        end
        if (uop_buf_valid_r && tile_latched_r) begin
            sched_req_valid_w[uop_buf_pipe_r] = 1'b1;
            sched_bar_wait_w[uop_buf_pipe_r]  = bar_stall_w;
        end
        if (pipe_fifo_pop_w) begin
            sched_credit_ret_w[pipe_fifo_r[pipe_fifo_rd_r]] = 1'b1;
        end
    end

    VX_tcu_v2_pipe_sched #(
        .NUM_PIPES    (NUM_PIPES),
        .CREDITS_INIT (4),
        .STARVE_LIMIT (16)
    ) u_pipe_sched (
        .clk                  (clk),
        .reset                (reset),
        .pipe_req_valid       (sched_req_valid_w),
        .pipe_req_ready       (sched_req_ready_w),
        .pipe_hazard_stall    (sched_haz_stall_w),
        .pipe_barrier_wait    (sched_bar_wait_w),
        .pipe_uop_in          (sched_uop_in_w),
        .credit_return        (sched_credit_ret_w),
        .issue_valid          (sched_issue_valid_w),
        .issue_ready          (sched_issue_ready_w),
        .issue_pipe_id        (sched_issue_pipe_w),
        .issue_uop_out        (sched_issue_uop_w),
        .pipe_credits_out     (sched_credits_w),
        .pipe_age_out         (sched_age_w),
        .pipe_starved_out     (sched_starved_w),
        .total_issues_cnt_out (sched_issues_cnt_w),
        .arb_stall_cnt_out    (sched_stall_cnt_w)
    );

    // -------------------------------------------------------------------------
    // 8. Structured 2:4 Sparse Validator, Compressor, Decompressor & Selector
    // -------------------------------------------------------------------------
    logic issue_fire_w;
    assign issue_fire_w        = sched_issue_valid_w && sched_issue_ready_w;
    assign sched_issue_ready_w = sp_sel_ready_w && sp_comp_ready_w && decomp_ready_w &&
                                 !sp_sel_pending_r &&
                                 (pipe_fifo_cnt_r != PIPE_FIFO_CNT_W'(PIPE_FIFO_DEPTH));

    VX_tcu_v2_sparse_validator #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_sparse_validator (
        .clk                     (clk),
        .reset                   (reset),
        .valid_in                (issue_fire_w),
        .sparse_en               (sched_issue_uop_w.sparse_en),
        .fmt_a                   (sched_issue_uop_w.fmt_a),
        .desc_id_in              (sched_issue_uop_w.desc_id),
        .sparse_meta_in          (sp_meta_lat_r),
        .a_tile_in               (a_tile_lat_r),
        .a_sparse_cand_in        (a_cand_lat_r),
        .fault_clear             (csr_fault_clear_w),
        .comp_meta_valid         (sp_comp_valid_w),
        .comp_meta_in            (sp_comp_meta_w),
        .fault_detected_comb_out (sp_fault_det_comb_w),
        .group_err_mask_comb_out (sp_err_mask_comb_w),
        .val_valid_out           (sp_val_valid_w),
        .fault_detected_out      (sp_fault_det_w),
        .fault_sticky_out        (sp_fault_sticky_w),
        .fmt_illegal_out         (sp_fmt_illegal_w),
        .group_err_mask_out      (sp_err_mask_w),
        .val_desc_id_out         (sp_val_desc_id_w),
        .syndrome_row_out        (sp_syn_row_w),
        .syndrome_group_out      (sp_syn_grp_w),
        .syndrome_meta_out       (sp_syn_meta_w),
        .syndrome_desc_id_out    (sp_syn_desc_id_w),
        .syndrome_code_out       (sp_syn_code_w),
        .checked_tiles_out       (sp_chk_tiles_w),
        .fault_events_out        (sp_flt_events_w),
        .comp_mismatch_cnt_out   (sp_cmp_mismatch_w)
    );

    VX_tcu_v2_sparse_compressor #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_sparse_compressor (
        .clk                  (clk),
        .reset                (reset),
        .valid_in             (sched_issue_valid_w && !sched_issue_uop_w.sparse_en &&
                               sp_sel_ready_w && decomp_ready_w && !sp_sel_pending_r &&
                               (pipe_fifo_cnt_r != PIPE_FIFO_CNT_W'(PIPE_FIFO_DEPTH))),
        .ready_in             (sp_comp_ready_w),
        .fmt_a                (sched_issue_uop_w.fmt_a),
        .dense_lo_in          (a_tile_lat_r),
        .dense_hi_in          (a_cand_lat_r),
        .valid_out            (sp_comp_valid_w),
        .ready_out            (1'b1),
        .compressed_out       (sp_comp_data_w),
        .meta_out             (sp_comp_meta_w),
        .prune_loss_out       (sp_prune_loss_w),
        .pruned_groups_out    (sp_pruned_grps_w),
        .exact_2_4_groups_out (sp_exact_grps_w)
    );

    VX_tcu_v2_sparse_decompressor #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_sparse_decompressor (
        .clk                 (clk),
        .reset               (reset),
        .valid_in            (sched_issue_valid_w && sched_issue_uop_w.sparse_en &&
                              sp_sel_ready_w && sp_comp_ready_w && !sp_sel_pending_r &&
                              (pipe_fifo_cnt_r != PIPE_FIFO_CNT_W'(PIPE_FIFO_DEPTH))),
        .ready_in            (decomp_ready_w),
        .sparse_en           (sched_issue_uop_w.sparse_en),
        .fmt_a               (sched_issue_uop_w.fmt_a),
        .compressed_in       (a_tile_lat_r),
        .meta_in             (sp_meta_lat_r),
        .valid_out           (decomp_valid_w),
        .ready_out           (1'b1),
        .dense_lo_out        (decomp_lo_w),
        .dense_hi_out        (decomp_hi_w),
        .occupancy_mask_out  (decomp_occ_w),
        .active_elem_cnt_out (decomp_active_w),
        .meta_illegal_out    (decomp_illegal_w)
    );

    assign decomp_chk_err_w = decomp_valid_w &&
                              ((decomp_occ_w == '0) || (decomp_active_w == 16'd0)) &&
                              !decomp_illegal_w;

    VX_tcu_v2_sparse_selector #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_sparse_selector (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (sched_issue_valid_w && sp_comp_ready_w && decomp_ready_w &&
                            !sp_sel_pending_r &&
                            (pipe_fifo_cnt_r != PIPE_FIFO_CNT_W'(PIPE_FIFO_DEPTH))),
        .ready_in          (sp_sel_ready_w),
        .sparse_en         (sched_issue_uop_w.sparse_en),
        .fault_suppress    (sp_fault_det_comb_w),
        .fmt_a             (sched_issue_uop_w.fmt_a),
        .a_tile_in         (a_tile_lat_r),
        .a_sparse_cand_in  (a_cand_lat_r),
        .sparse_meta_in    (sp_meta_lat_r),
        .group_err_mask_in (sp_err_mask_comb_w),
        .valid_out         (sp_sel_valid_w),
        .ready_out         (arr_uop_ready_w),
        .a_selected_out    (sp_a_selected_w),
        .fault_masked_out  (sp_fault_masked_w),
        .active_lanes_out  (sp_active_lanes_w)
    );

    // -------------------------------------------------------------------------
    // 9. Wide Systolic / FEDP Array Top
    // -------------------------------------------------------------------------
    assign arr_uop_valid_w = sp_sel_valid_w && sp_sel_pending_r;

    VX_tcu_v2_systolic_top #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_systolic_top (
        .clk               (clk),
        .reset             (reset),
        .uop_valid         (arr_uop_valid_w),
        .uop_ready         (arr_uop_ready_w),
        .uop_in            (sp_sel_uop_r),
        .a_tile_in         (sp_a_selected_w),
        .b_tile_in         (sp_sel_b_r),
        .scale_a_in        (sp_sel_sa_r),
        .scale_b_in        (sp_sel_sb_r),
        .c_tile_in         (sp_sel_c_r),
        .bias_in           (sp_sel_bias_r),
        .out_valid         (arr_out_valid_w),
        .out_ready         (arr_out_ready_w),
        .d_tile_out        (arr_d_tile_w),
        .out_desc_id       (arr_out_desc_id_w),
        .flags_out         (arr_flags_out_w),
        .busy              (arr_busy_w),
        .active_cycles_out (arr_active_cyc_w)
    );

    assign arr_out_ready_w = tile_out_ready;
    assign pipe_fifo_push_w = arr_uop_valid_w && arr_uop_ready_w && sp_sel_uop_r.is_last_k;
    assign pipe_fifo_pop_w  = arr_out_valid_w && arr_out_ready_w && (pipe_fifo_cnt_r != '0);

    // -------------------------------------------------------------------------
    // 10. Performance Monitor Unit
    // -------------------------------------------------------------------------
    logic [NUM_PIPES-1:0]       pmu_pipe_active_w;
    tcu_v2_perf_cnt_t           pmu_perf_cnt_w;
    logic [31:0]                pmu_dense_ops_w;
    logic [31:0]                pmu_sparse_ops_w;
    logic [31:0]                pmu_tmem_stall_w;
    logic [31:0]                pmu_bar_stall_w;
    logic [31:0]                pmu_fp_nv_w;
    logic [31:0]                pmu_fp_of_w;
    logic [31:0]                pmu_fp_uf_w;
    logic [31:0]                pmu_fp_nx_w;
    logic [NUM_PIPES-1:0][31:0] pmu_pipe_busy_w;

    always_comb begin
        pmu_pipe_active_w = '0;
        if (arr_busy_w) begin
            pmu_pipe_active_w[0] = 1'b1;
        end
    end

    VX_tcu_v2_perf_mon #(
        .NUM_PIPES (NUM_PIPES)
    ) u_perf_mon (
        .clk                      (clk),
        .reset                    (reset),
        .clear_counters           (csr_perf_clear_w),
        .array_busy               (arr_busy_w || exp_busy_w),
        .pipe_stall               (sb_haz_any_w || (sched_issue_valid_w && !sched_issue_ready_w)),
        .tmem_stall               (tmem_gen_stall_w || (tmem_req_valid_r && !tmem_req_ready)),
        .barrier_stall            (bar_stall_w),
        .cta_sync_stall           (cta_sync_stall_w),
        .uop_issue_fire           (issue_fire_w),
        .uop_issue_sparse         (sched_issue_uop_w.sparse_en),
        .uop_retire_fire          (arr_out_valid_w && arr_out_ready_w),
        .desc_done_fire           (sb_retire_pulse_w),
        .sparse_fault_pulse       (sp_fault_det_w || decomp_illegal_w || decomp_chk_err_w),
        .fp_flags_valid           (arr_out_valid_w && arr_out_ready_w),
        .fp_flags_in              (arr_flags_out_w),
        .pipe_active_mask         (pmu_pipe_active_w),
        .perf_cnt_out             (pmu_perf_cnt_w),
        .dense_ops_cnt_out        (pmu_dense_ops_w),
        .sparse_ops_cnt_out       (pmu_sparse_ops_w),
        .tmem_stall_cycles_out    (pmu_tmem_stall_w),
        .barrier_stall_cycles_out (pmu_bar_stall_w),
        .fp_nv_cnt_out            (pmu_fp_nv_w),
        .fp_of_cnt_out            (pmu_fp_of_w),
        .fp_uf_cnt_out            (pmu_fp_uf_w),
        .fp_nx_cnt_out            (pmu_fp_nx_w),
        .pipe_busy_cycles_out     (pmu_pipe_busy_w)
    );

    // -------------------------------------------------------------------------
    // Unused Diagnostic Telemetry Suppression
    // -------------------------------------------------------------------------
    `UNUSED_VAR (q_full_w)
    `UNUSED_VAR (q_occupancy_w)
    `UNUSED_VAR (q_credits_w)
    `UNUSED_VAR (q_reject_pulse_w)
    `UNUSED_VAR (q_reject_id_w)
    `UNUSED_VAR (q_acc_cnt_w)
    `UNUSED_VAR (q_rej_cnt_w)
    `UNUSED_VAR (q_flu_cnt_w)
    `UNUSED_VAR (sb_haz_mask_w)
    `UNUSED_VAR (sb_commit_idle_w)
    `UNUSED_VAR (sb_inflight_mask_w)
    `UNUSED_VAR (sb_inflight_cnt_w)
    `UNUSED_VAR (sb_retired_cnt_w)
    `UNUSED_VAR (sb_haz_stall_cnt_w)
    `UNUSED_VAR (bar_wait_pass_w)
    `UNUSED_VAR (bar_wakeup_valid_w)
    `UNUSED_VAR (bar_wakeup_id_w)
    `UNUSED_VAR (bar_wakeup_phase_w)
    `UNUSED_VAR (bar_status_valid_w)
    `UNUSED_VAR (bar_status_phase_w)
    `UNUSED_VAR (bar_status_arr_w)
    `UNUSED_VAR (bar_status_tx_w)
    `UNUSED_VAR (bar_active_mask_w)
    `UNUSED_VAR (bar_phase_vec_w)
    `UNUSED_VAR (bar_flips_cnt_w)
    `UNUSED_VAR (bar_stall_cycles_w)
    `UNUSED_VAR (cta_sync_busy_w)
    `UNUSED_VAR (cta_pair_cnt_w)
    `UNUSED_VAR (cta_wait_cycles_w)
    `UNUSED_VAR (exp_tmem_valid_w)
    `UNUSED_VAR (exp_tmem_req_w)
    `UNUSED_VAR (exp_desc_id_w)
    `UNUSED_VAR (exp_uops_cnt_w)
    `UNUSED_VAR (sched_req_ready_w)
    `UNUSED_VAR (sched_credits_w)
    `UNUSED_VAR (sched_age_w)
    `UNUSED_VAR (sched_starved_w)
    `UNUSED_VAR (sched_issues_cnt_w)
    `UNUSED_VAR (sched_stall_cnt_w)
    `UNUSED_VAR (tmem_gen_busy_w)
    `UNUSED_VAR (tmem_rd_a_cnt_w)
    `UNUSED_VAR (tmem_rd_b_cnt_w)
    `UNUSED_VAR (tmem_rd_c_cnt_w)
    `UNUSED_VAR (tmem_wr_d_cnt_w)
    `UNUSED_VAR (sp_val_valid_w)
    `UNUSED_VAR (sp_err_mask_w)
    `UNUSED_VAR (sp_fmt_illegal_w)
    `UNUSED_VAR (sp_val_desc_id_w)
    `UNUSED_VAR (sp_syn_meta_w)
    `UNUSED_VAR (sp_chk_tiles_w)
    `UNUSED_VAR (sp_flt_events_w)
    `UNUSED_VAR (sp_cmp_mismatch_w)
    `UNUSED_VAR (sp_comp_data_w)
    `UNUSED_VAR (sp_prune_loss_w)
    `UNUSED_VAR (sp_pruned_grps_w)
    `UNUSED_VAR (sp_exact_grps_w)
    `UNUSED_VAR (sp_fault_masked_w)
    `UNUSED_VAR (sp_active_lanes_w)
    `UNUSED_VAR (arr_active_cyc_w)
    `UNUSED_VAR (pmu_dense_ops_w)
    `UNUSED_VAR (pmu_sparse_ops_w)
    `UNUSED_VAR (pmu_tmem_stall_w)
    `UNUSED_VAR (pmu_bar_stall_w)
    `UNUSED_VAR (pmu_fp_nv_w)
    `UNUSED_VAR (pmu_fp_of_w)
    `UNUSED_VAR (pmu_fp_uf_w)
    `UNUSED_VAR (pmu_fp_nx_w)
    `UNUSED_VAR (pmu_pipe_busy_w)
    `UNUSED_VAR (arb_grant_qid_w)
    `UNUSED_VAR (arb_qid_grants_w)
    `UNUSED_VAR (arb_conflicts_w)
    `UNUSED_VAR (pf_buf_sel_w)
    `UNUSED_VAR (pf_occ_w)
    `UNUSED_VAR (pf_swaps_w)
    `UNUSED_VAR (pf_stalls_w)
    `UNUSED_VAR (decomp_lo_w)
    `UNUSED_VAR (decomp_hi_w)
    `UNUSED_VAR (map_bank_id_w)
    `UNUSED_VAR (map_word_addr_w)
    `UNUSED_VAR (map_half_sel_w)
    `UNUSED_VAR (map_conflict_w)
    `UNUSED_VAR (map_bounds_err_w)
    `UNUSED_VAR (map_cnt_w)
    `UNUSED_VAR (map_conflict_cnt_w)
    `UNUSED_VAR (rob_fence_done_w)
    `UNUSED_VAR (rob_commit_id_w)
    `UNUSED_VAR (rob_commit_flags_w)
    `UNUSED_VAR (rob_empty_w)
    `UNUSED_VAR (rob_full_w)
    `UNUSED_VAR (rob_count_w)
    `UNUSED_VAR (rob_committed_cnt_w)
    `UNUSED_VAR (rob_fence_cycles_w)
    `UNUSED_VAR (csr_wr_cnt_w)
    `UNUSED_VAR (arb_req_ready_w)

    always_ff @(posedge clk) begin
        if (reset) begin
            active_tmem_wb_r         <= 1'b0;
            next_pipe_r              <= '0;
            dbl_buf_toggle_r         <= 1'b0;
            uop_buf_valid_r          <= 1'b0;
            uop_buf_r                <= '0;
            uop_buf_pipe_r           <= '0;
            tile_latched_r           <= 1'b0;
            a_tile_lat_r             <= '0;
            b_tile_lat_r             <= '0;
            a_cand_lat_r             <= '0;
            sp_meta_lat_r            <= '0;
            scale_a_lat_r            <= '0;
            scale_b_lat_r            <= '0;
            c_tile_lat_r             <= '0;
            bias_lat_r               <= '0;
            sp_sel_pending_r         <= 1'b0;
            sp_sel_uop_r             <= '0;
            sp_sel_pipe_r            <= '0;
            sp_sel_b_r               <= '0;
            sp_sel_sa_r              <= '0;
            sp_sel_sb_r              <= '0;
            sp_sel_c_r               <= '0;
            sp_sel_bias_r            <= '0;
            pipe_fifo_wr_r           <= '0;
            pipe_fifo_rd_r           <= '0;
            pipe_fifo_cnt_r          <= '0;
            for (int f = 0; f < PIPE_FIFO_DEPTH; ++f) begin
                pipe_fifo_r[f] <= '0;
            end
            last_retired_uop_id_r    <= '0;
            last_retired_uop_valid_r <= 1'b0;
            last_retired_uop_last_r  <= 1'b0;
            tmem_req_valid_r         <= 1'b0;
            tmem_req_out_r           <= '0;
            desc_done_valid_r        <= 1'b0;
            desc_done_id_r           <= 8'd0;
            sparse_fault_r           <= 1'b0;
            decomp_valid_out_r       <= 1'b0;
            decomp_illegal_out_r     <= 1'b0;
            perf_cnt_out_r           <= '0;
        end else begin
            if (dispatch_fire_w) begin
                active_tmem_wb_r <= q_deq_desc_w.tmem_wb_en;
                dbl_buf_toggle_r <= !dbl_buf_toggle_r;
                if ((int'(next_pipe_r) + 1) >= NUM_PIPES) begin
                    next_pipe_r <= '0;
                end else begin
                    next_pipe_r <= next_pipe_r + PIPE_W'(1);
                end
            end

            if (exp_uop_valid_w && exp_uop_ready_w) begin
                uop_buf_valid_r <= 1'b1;
                uop_buf_r       <= exp_uop_w;
                uop_buf_pipe_r  <= next_pipe_r;
            end else if (issue_fire_w) begin
                uop_buf_valid_r <= 1'b0;
            end

            if (pf_out_valid_w && pf_out_ready_w) begin
                tile_latched_r <= 1'b1;
                a_tile_lat_r   <= pf_a_tile_w;
                b_tile_lat_r   <= pf_b_tile_w;
                a_cand_lat_r   <= pf_a_cand_w;
                sp_meta_lat_r  <= pf_meta_w;
                scale_a_lat_r  <= pf_scale_a_w;
                scale_b_lat_r  <= pf_scale_b_w;
                c_tile_lat_r   <= pf_c_tile_w;
                bias_lat_r     <= pf_bias_w;
            end else if (issue_fire_w) begin
                tile_latched_r <= 1'b0;
            end

            if (issue_fire_w) begin
                sp_sel_pending_r <= 1'b1;
                sp_sel_uop_r     <= sched_issue_uop_w;
                sp_sel_pipe_r    <= sched_issue_pipe_w;
                sp_sel_b_r       <= b_tile_lat_r;
                sp_sel_sa_r      <= scale_a_lat_r;
                sp_sel_sb_r      <= scale_b_lat_r;
                sp_sel_c_r       <= c_tile_lat_r;
                sp_sel_bias_r    <= bias_lat_r;
            end else if (arr_uop_valid_w && arr_uop_ready_w) begin
                sp_sel_pending_r <= 1'b0;
            end

            if (pipe_fifo_push_w) begin
                pipe_fifo_r[pipe_fifo_wr_r] <= sp_sel_pipe_r;
                pipe_fifo_wr_r              <= pipe_fifo_wr_r + PIPE_FIFO_PTR_W'(1);
            end
            if (pipe_fifo_pop_w) begin
                pipe_fifo_rd_r <= pipe_fifo_rd_r + PIPE_FIFO_PTR_W'(1);
            end
            case ({pipe_fifo_push_w, pipe_fifo_pop_w})
                2'b10: pipe_fifo_cnt_r <= pipe_fifo_cnt_r + PIPE_FIFO_CNT_W'(1);
                2'b01: pipe_fifo_cnt_r <= pipe_fifo_cnt_r - PIPE_FIFO_CNT_W'(1);
                default: pipe_fifo_cnt_r <= pipe_fifo_cnt_r;
            endcase

            last_retired_uop_valid_r <= arr_out_valid_w && arr_out_ready_w;
            if (arr_out_valid_w && arr_out_ready_w) begin
                last_retired_uop_id_r   <= arr_out_desc_id_w;
                last_retired_uop_last_r <= 1'b0;
            end

            if (map_out_valid_w && map_out_ready_w) begin
                tmem_req_valid_r <= 1'b1;
                tmem_req_out_r   <= map_req_out_w;
            end else if (tmem_req_valid_r && tmem_req_ready) begin
                tmem_req_valid_r <= 1'b0;
            end

            desc_done_valid_r <= sb_retire_pulse_w;
            if (sb_retire_pulse_w) begin
                desc_done_id_r <= sb_retire_id_w;
            end

            sparse_fault_r       <= sp_fault_sticky_w || cta_wdt_timeout_w;
            decomp_valid_out_r   <= decomp_valid_w;
            decomp_illegal_out_r <= decomp_valid_w && (decomp_illegal_w || decomp_chk_err_w);
            perf_cnt_out_r       <= pmu_perf_cnt_w;
        end
    end

    assign tmem_req_valid            = tmem_req_valid_r;
    assign tmem_req_out              = tmem_req_out_r;
    assign tile_out_valid            = arr_out_valid_w;
    assign d_tile_out                = arr_d_tile_w;
    assign out_desc_id               = arr_out_desc_id_w;
    assign flags_out                 = arr_flags_out_w;
    assign desc_done_valid           = desc_done_valid_r;
    assign desc_done_id              = desc_done_id_r;
    assign sparse_fault              = sparse_fault_r;
    assign sparse_decomp_valid_out   = decomp_valid_out_r;
    assign sparse_decomp_illegal_out = decomp_illegal_out_r;
    assign perf_cnt_out              = perf_cnt_out_r;

endmodule
