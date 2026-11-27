// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_tmem_cluster_slice
    import VX_tcu_v2_pkg::*;
    import VX_tmem_pkg::*;
#(
    parameter int NUM_TCU_PIPES = 2,
    parameter int ARRAY_M       = TCU_V2_ARRAY_M,
    parameter int ARRAY_N       = TCU_V2_ARRAY_N,
    parameter int ARRAY_K       = TCU_V2_ARRAY_K,
    parameter int TMEM_LANES    = 8
) (
    input  logic                                                        clk,
    input  logic                                                        reset,
    // WGMMA descriptor ports (1 per TCU pipe / CTA peer)
    input  logic [NUM_TCU_PIPES-1:0]                                    desc_valid,
    output logic [NUM_TCU_PIPES-1:0]                                    desc_ready,
    input  tcu_v2_wgmma_desc_t [NUM_TCU_PIPES-1:0]                      desc_in,
    // External tile operand feed & output per TCU pipe
    input  logic [NUM_TCU_PIPES-1:0]                                    ext_tile_in_valid,
    output logic [NUM_TCU_PIPES-1:0]                                    ext_tile_in_ready,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*32-1:0]       ext_a_tile_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][ARRAY_K*32-1:0]       ext_b_tile_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*32-1:0]       ext_a_sparse_cand_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*16-1:0]       ext_sparse_meta_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][7:0]                  ext_scale_a_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][7:0]                  ext_scale_b_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0]    ext_c_tile_in,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][31:0]                 ext_bias_in,
    output logic [NUM_TCU_PIPES-1:0]                                    tile_out_valid,
    input  logic [NUM_TCU_PIPES-1:0]                                    tile_out_ready,
    output logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0]    d_tile_out,
    output logic [NUM_TCU_PIPES-1:0][7:0]                               out_desc_id,
    output tcu_v2_fp_flags_t [NUM_TCU_PIPES-1:0]                        flags_out,
    output logic [NUM_TCU_PIPES-1:0]                                    desc_done_valid,
    output logic [NUM_TCU_PIPES-1:0][7:0]                               desc_done_id,
    output logic [NUM_TCU_PIPES-1:0]                                    sparse_fault_out,
    output logic [NUM_TCU_PIPES-1:0]                                    sparse_decomp_valid_out,
    output logic [NUM_TCU_PIPES-1:0]                                    sparse_decomp_illegal_out,
    output tcu_v2_perf_cnt_t [NUM_TCU_PIPES-1:0]                        tcu_perf_cnt_out,
    // TCU pipe control & status register (CSR) interface
    input  logic [NUM_TCU_PIPES-1:0]                                    tcu_cfg_wr_valid     = '0,
    input  logic [NUM_TCU_PIPES-1:0][7:0]                               tcu_cfg_wr_addr      = '0,
    input  logic [NUM_TCU_PIPES-1:0][31:0]                              tcu_cfg_wr_data      = '0,
    input  logic [NUM_TCU_PIPES-1:0]                                    tcu_cfg_rd_valid     = '0,
    input  logic [NUM_TCU_PIPES-1:0][7:0]                               tcu_cfg_rd_addr      = '0,
    output logic [NUM_TCU_PIPES-1:0]                                    tcu_cfg_rd_rsp_valid,
    output logic [NUM_TCU_PIPES-1:0][31:0]                              tcu_cfg_rd_rsp_data,
    // TMEM Allocation, Load, Store, and Wait/Fence host/SM ports
    input  logic                                                        tmem_alloc_valid,
    output logic                                                        tmem_alloc_ready,
    input  logic [2:0]                                                  tmem_alloc_op,
    input  logic                                                        tmem_alloc_auto_place,
    input  logic                                                        tmem_alloc_buddy_align,
    input  logic                                                        tmem_alloc_strict_owner,
    input  tmem_alloc_req_t                                             tmem_alloc_req,
    output tmem_alloc_rsp_t                                             tmem_alloc_rsp,
    output logic                                                        tmem_alloc_query_valid,
    output tmem_region_entry_t                                          tmem_alloc_query_entry,

    input  logic                                                        tmem_ld_desc_valid,
    output logic                                                        tmem_ld_desc_ready,
    input  logic [TMEM_TAG_W-1:0]                                       tmem_ld_desc_tag,
    input  logic [TMEM_REGION_ID_W-1:0]                                 tmem_ld_desc_region_id,
    input  logic [4:0]                                                  tmem_ld_desc_warp_id,
    input  logic [TMEM_ROW_W-1:0]                                       tmem_ld_desc_row_base,
    input  logic [TMEM_COL_W-1:0]                                       tmem_ld_desc_col_base,
    input  logic [7:0]                                                  tmem_ld_desc_num_rows,
    input  logic [9:0]                                                  tmem_ld_desc_num_cols,
    input  logic [1:0]                                                  tmem_ld_desc_elem_bytes,
    input  logic                                                        tmem_ld_desc_col_major,
    input  logic [2:0]                                                  tmem_ld_desc_subbyte_shift,
    input  logic                                                        tmem_ld_xform_en,
    input  logic [2:0]                                                  tmem_ld_xform_mode,
    input  logic [2:0]                                                  tmem_ld_xform_fmt,
    input  logic                                                        tmem_ld_xform_tile8x8,
    input  logic                                                        tmem_ld_xform_unpack32,
    output logic                                                        tmem_ld_rsp_valid,
    input  logic                                                        tmem_ld_rsp_ready,
    output logic [TMEM_TAG_W-1:0]                                       tmem_ld_rsp_tag,
    output logic [4:0]                                                  tmem_ld_rsp_warp_id,
    output tmem_status_e                                                tmem_ld_rsp_status,
    output logic [TMEM_LANES-1:0][63:0]                                 tmem_ld_rsp_data,
    output logic [TMEM_LANES-1:0]                                       tmem_ld_rsp_lane_mask,
    output logic                                                        tmem_ld_rsp_last,
    output logic                                                        tmem_ld_rsp_ecc_ce,
    output logic                                                        tmem_ld_rsp_ecc_ue,

    input  logic                                                        tmem_st_req_valid,
    output logic                                                        tmem_st_req_ready,
    input  logic [TMEM_TAG_W-1:0]                                       tmem_st_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]                                 tmem_st_req_region_id,
    input  logic [4:0]                                                  tmem_st_req_warp_id,
    input  logic [TMEM_ROW_W-1:0]                                       tmem_st_req_row_base,
    input  logic [TMEM_COL_W-1:0]                                       tmem_st_req_col_base,
    input  logic [7:0]                                                  tmem_st_req_num_rows,
    input  logic [9:0]                                                  tmem_st_req_num_cols,
    input  logic                                                        tmem_st_req_col_major,
    input  logic                                                        tmem_st_req_cell32_mode,
    input  logic [TMEM_LANES-1:0][63:0]                                 tmem_st_req_data,
    input  logic [TMEM_LANES-1:0][7:0]                                  tmem_st_req_be,
    input  logic                                                        tmem_st_req_last,
    output logic                                                        tmem_st_ack_valid,
    input  logic                                                        tmem_st_ack_ready,
    output logic [TMEM_TAG_W-1:0]                                       tmem_st_ack_tag,
    output logic [4:0]                                                  tmem_st_ack_warp_id,
    output tmem_status_e                                                tmem_st_ack_status,

    input  logic                                                        tmem_wait_req_valid,
    output logic                                                        tmem_wait_req_ready,
    input  tmem_op_e                                                    tmem_wait_req_op,
    input  logic [TMEM_TAG_W-1:0]                                       tmem_wait_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]                                 tmem_wait_req_region_id,
    input  logic [4:0]                                                  tmem_wait_req_warp_id,
    input  logic                                                        tmem_wait_req_scope_warp,
    input  logic [TMEM_BARRIER_ID_W-1:0]                                tmem_wait_req_barrier_id,
    input  logic                                                        tmem_wait_req_barrier_phase,
    output logic                                                        tmem_wait_rsp_valid,
    input  logic                                                        tmem_wait_rsp_ready,
    output tmem_op_e                                                    tmem_wait_rsp_op,
    output logic [TMEM_TAG_W-1:0]                                       tmem_wait_rsp_tag,
    output tmem_status_e                                                tmem_wait_rsp_status,
    // Cluster Configuration, ECC Injection/Scrub, and Telemetry
    input  logic                                                        tmem_mma_route_en,
    input  logic [NUM_TCU_PIPES-1:0][TMEM_REGION_ID_W-1:0]              pipe_region_id_cfg,
    input  logic [NUM_TCU_PIPES-1:0][4:0]                               pipe_warp_id_cfg,
    input  logic [NUM_TCU_PIPES-1:0]                                    pipe_ping_pong_cfg,
    input  logic [3:0]                                                  cfg_weight_ld,
    input  logic [3:0]                                                  cfg_weight_st,
    input  logic [3:0]                                                  cfg_weight_mma,
    input  logic                                                        cfg_strict_mma_prio,
    input  logic [4:0]                                                  cfg_starve_limit,
    input  logic                                                        ecc_inj_en,
    input  logic [4:0]                                                  ecc_inj_bank,
    input  logic [71:0]                                                 ecc_inj_mask,
    input  logic                                                        scrub_en,
    input  logic                                                        perf_clear,
    output logic                                                        tmem_deadlock_fault_out,
    output logic                                                        tmem_bounds_fault_out,
    output logic [2:0]                                                  tmem_bounds_fault_reason_out,
    output tmem_perf_cnt_t                                              tmem_perf_cnt_out,
    output logic [31:0]                                                 tmem_ecc_ce_count_out,
    output logic [31:0]                                                 tmem_ecc_ue_count_out,
    output logic [4:0]                                                  tmem_occupied_granules_out,
    output logic [4:0]                                                  tmem_peak_granules_out
);

    localparam int PIPE_IDX_W = (NUM_TCU_PIPES > 1) ? $clog2(NUM_TCU_PIPES) : 1;

    // -------------------------------------------------------------------------
    // Per-Pipe TCU v2 Signals & Direct 2-CTA Peer Sync Interconnect
    // -------------------------------------------------------------------------
    logic [NUM_TCU_PIPES-1:0]                                   pipe_tile_in_valid;
    logic [NUM_TCU_PIPES-1:0]                                   pipe_tile_in_ready;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*32-1:0]      pipe_a_tile_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][ARRAY_K*32-1:0]      pipe_b_tile_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*32-1:0]      pipe_a_sparse_cand_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*16-1:0]      pipe_sparse_meta_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][7:0]                 pipe_scale_a_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][7:0]                 pipe_scale_b_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0]   pipe_c_tile_in;
    logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][31:0]                pipe_bias_in;

    logic [NUM_TCU_PIPES-1:0]                                   pipe_tmem_req_valid;
    logic [NUM_TCU_PIPES-1:0]                                   pipe_tmem_req_ready;
    tcu_v2_tmem_req_t [NUM_TCU_PIPES-1:0]                       pipe_tmem_req_out;

    logic [NUM_TCU_PIPES-1:0]                                   pipe_tile_out_valid;
    logic [NUM_TCU_PIPES-1:0]                                   pipe_tile_out_ready;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0]   pipe_d_tile_out;
    logic [NUM_TCU_PIPES-1:0][7:0]                              pipe_out_desc_id;
    tcu_v2_fp_flags_t [NUM_TCU_PIPES-1:0]                       pipe_flags_out;

    logic [NUM_TCU_PIPES-1:0]                                   cta_sync_out_valid;
    logic [NUM_TCU_PIPES-1:0]                                   cta_sync_out_ready;
    logic [NUM_TCU_PIPES-1:0][3:0]                              cta_sync_out_bar_id;
    logic [NUM_TCU_PIPES-1:0]                                   cta_sync_out_phase;

    logic [NUM_TCU_PIPES-1:0]                                   cta_sync_in_valid;
    logic [NUM_TCU_PIPES-1:0]                                   cta_sync_in_ready;
    logic [NUM_TCU_PIPES-1:0][3:0]                              cta_sync_in_bar_id;
    logic [NUM_TCU_PIPES-1:0]                                   cta_sync_in_phase;

    // -------------------------------------------------------------------------
    // TMEM MMA Bridge & Peer Barrier Signals
    // -------------------------------------------------------------------------
    logic                               tmem_mma_req_valid;
    logic                               tmem_mma_req_ready;
    tmem_op_e                           tmem_mma_req_op;
    logic [TMEM_TAG_W-1:0]              tmem_mma_req_tag;
    logic [TMEM_REGION_ID_W-1:0]        tmem_mma_req_region_id;
    logic [4:0]                         tmem_mma_req_warp_id;
    logic [TMEM_ROW_W-1:0]              tmem_mma_req_row;
    logic [TMEM_COL_W-1:0]              tmem_mma_req_col;
    tmem_swizzle_e                      tmem_mma_req_swizzle;
    logic [7:0]                         tmem_mma_req_col_count;
    logic                               tmem_mma_req_ping_pong_sel;
    logic [TMEM_LANES-1:0][63:0]        tmem_mma_req_wr_data;
    logic [TMEM_LANES-1:0][7:0]         tmem_mma_req_wr_be;

    logic                               tmem_mma_rsp_valid;
    logic                               tmem_mma_rsp_ready;
    tmem_op_e                           tmem_mma_rsp_op;
    logic [TMEM_TAG_W-1:0]              tmem_mma_rsp_tag;
    tmem_status_e                       tmem_mma_rsp_status;
    logic [TMEM_LANES-1:0][63:0]        tmem_mma_rsp_data;
    logic [TMEM_LANES-1:0]              tmem_mma_rsp_lane_mask;
    logic                               tmem_mma_rsp_ecc_ce;
    logic                               tmem_mma_rsp_ecc_ue;

    logic                               tmem_peer_bar_valid;
    logic                               tmem_peer_bar_ready;
    logic [TMEM_BARRIER_ID_W-1:0]       tmem_peer_bar_id;
    logic                               tmem_peer_bar_phase;
    logic                               tmem_bar_wakeup_valid;
    logic [TMEM_BARRIER_ID_W-1:0]       tmem_bar_wakeup_id;
    logic                               tmem_bar_wakeup_phase;

    // Round-robin pipe arbiter for TMEM MMA port + response/writeback beat staging
    logic [PIPE_IDX_W-1:0]              rr_pipe_q, rr_pipe_d;
    logic                               sel_pipe_found;
    logic [PIPE_IDX_W-1:0]              sel_pipe_idx;
    logic [NUM_TCU_PIPES-1:0]           pipe_tmem_grant;
    logic [NUM_TCU_PIPES-1:0]           pipe_wb_pending_q, pipe_wb_pending_d;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0] pipe_wb_buf_q, pipe_wb_buf_d;
    logic [NUM_TCU_PIPES-1:0][3:0]      pipe_wb_beat_q, pipe_wb_beat_d;
    logic [NUM_TCU_PIPES-1:0]           tmem_rd_ready_q, tmem_rd_ready_d;
    logic [NUM_TCU_PIPES-1:0][3:0]      tmem_rd_beat_q, tmem_rd_beat_d;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*32-1:0] tmem_a_buf_q, tmem_a_buf_d;
    logic [NUM_TCU_PIPES-1:0][ARRAY_N-1:0][ARRAY_K*32-1:0] tmem_b_buf_q, tmem_b_buf_d;
    logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0] tmem_c_buf_q, tmem_c_buf_d;
    logic [PIPE_IDX_W-1:0]              rsp_target_p;
    logic                               rsp_pipe_in_range;
    logic                               tmem_rsp_consume_w;

    // -------------------------------------------------------------------------
    // Instantiate NUM_TCU_PIPES Instances of VX_tcu_v2_top
    // -------------------------------------------------------------------------
    for (genvar p = 0; p < NUM_TCU_PIPES; ++p) begin : g_tcu_pipes
        VX_tcu_v2_top #(
            .ARRAY_M   (ARRAY_M),
            .ARRAY_N   (ARRAY_N),
            .ARRAY_K   (ARRAY_K),
            .NUM_PIPES (1)
        ) u_tcu_pipe (
            .clk                       (clk),
            .reset                     (reset),
            .desc_valid                (desc_valid[p]),
            .desc_ready                (desc_ready[p]),
            .desc_in                   (desc_in[p]),
            .tile_in_valid             (pipe_tile_in_valid[p]),
            .tile_in_ready             (pipe_tile_in_ready[p]),
            .a_tile_in                 (pipe_a_tile_in[p]),
            .b_tile_in                 (pipe_b_tile_in[p]),
            .a_sparse_cand_in          (pipe_a_sparse_cand_in[p]),
            .sparse_meta_in            (pipe_sparse_meta_in[p]),
            .scale_a_in                (pipe_scale_a_in[p]),
            .scale_b_in                (pipe_scale_b_in[p]),
            .c_tile_in                 (pipe_c_tile_in[p]),
            .bias_in                   (pipe_bias_in[p]),
            .tmem_req_valid            (pipe_tmem_req_valid[p]),
            .tmem_req_ready            (pipe_tmem_req_ready[p]),
            .tmem_req_out              (pipe_tmem_req_out[p]),
            .tile_out_valid            (pipe_tile_out_valid[p]),
            .tile_out_ready            (pipe_tile_out_ready[p]),
            .d_tile_out                (pipe_d_tile_out[p]),
            .out_desc_id               (pipe_out_desc_id[p]),
            .flags_out                 (pipe_flags_out[p]),
            .cta_sync_out_valid        (cta_sync_out_valid[p]),
            .cta_sync_out_ready        (cta_sync_out_ready[p]),
            .cta_sync_out_bar_id       (cta_sync_out_bar_id[p]),
            .cta_sync_out_phase        (cta_sync_out_phase[p]),
            .cta_sync_in_valid         (cta_sync_in_valid[p]),
            .cta_sync_in_ready         (cta_sync_in_ready[p]),
            .cta_sync_in_bar_id        (cta_sync_in_bar_id[p]),
            .cta_sync_in_phase         (cta_sync_in_phase[p]),
            .cfg_wr_valid              (tcu_cfg_wr_valid[p]),
            .cfg_wr_addr               (tcu_cfg_wr_addr[p]),
            .cfg_wr_data               (tcu_cfg_wr_data[p]),
            .cfg_rd_valid              (tcu_cfg_rd_valid[p]),
            .cfg_rd_addr               (tcu_cfg_rd_addr[p]),
            .cfg_rd_rsp_valid          (tcu_cfg_rd_rsp_valid[p]),
            .cfg_rd_rsp_data           (tcu_cfg_rd_rsp_data[p]),
            .desc_done_valid           (desc_done_valid[p]),
            .desc_done_id              (desc_done_id[p]),
            .sparse_fault              (sparse_fault_out[p]),
            .sparse_decomp_valid_out   (sparse_decomp_valid_out[p]),
            .sparse_decomp_illegal_out (sparse_decomp_illegal_out[p]),
            .perf_cnt_out              (tcu_perf_cnt_out[p])
        );
    end

    // -------------------------------------------------------------------------
    // Direct 2-CTA Peer Synchronization Cross-Link Ring (with TMEM Barrier Tap)
    // -------------------------------------------------------------------------
    if (NUM_TCU_PIPES == 1) begin : g_single_cta_sync
        assign cta_sync_in_valid[0]  = tmem_bar_wakeup_valid ? 1'b1 : cta_sync_out_valid[0];
        assign cta_sync_in_bar_id[0] = tmem_bar_wakeup_valid ? tmem_bar_wakeup_id : cta_sync_out_bar_id[0];
        assign cta_sync_in_phase[0]  = tmem_bar_wakeup_valid ? tmem_bar_wakeup_phase : cta_sync_out_phase[0];
        assign cta_sync_out_ready[0] = !tmem_bar_wakeup_valid && cta_sync_in_ready[0] && tmem_peer_bar_ready;
        assign tmem_peer_bar_valid   = !tmem_bar_wakeup_valid && cta_sync_out_valid[0] && cta_sync_in_ready[0];
        assign tmem_peer_bar_id      = cta_sync_out_bar_id[0];
        assign tmem_peer_bar_phase   = cta_sync_out_phase[0];
    end else begin : g_multi_cta_sync
        for (genvar p = 0; p < NUM_TCU_PIPES; ++p) begin : g_sync_ring
            localparam int PEER_IDX      = (p + 1) % NUM_TCU_PIPES;
            localparam int PREV_PEER_IDX = (p + NUM_TCU_PIPES - 1) % NUM_TCU_PIPES;
            assign cta_sync_in_valid[p]  = tmem_bar_wakeup_valid
                                           ? 1'b1
                                           : cta_sync_out_valid[PEER_IDX];
            assign cta_sync_in_bar_id[p] = tmem_bar_wakeup_valid
                                           ? tmem_bar_wakeup_id
                                           : cta_sync_out_bar_id[PEER_IDX];
            assign cta_sync_in_phase[p]  = tmem_bar_wakeup_valid
                                           ? tmem_bar_wakeup_phase
                                           : cta_sync_out_phase[PEER_IDX];
            if (p == 0) begin : g_tap_p0
                assign cta_sync_out_ready[p] = !tmem_bar_wakeup_valid &&
                                               cta_sync_in_ready[PREV_PEER_IDX] &&
                                               tmem_peer_bar_ready;
            end else begin : g_tap_pn
                assign cta_sync_out_ready[p] = !tmem_bar_wakeup_valid &&
                                               cta_sync_in_ready[PREV_PEER_IDX];
            end
        end
        // Mirror pipe 0's peer barrier arrival into TMEM wait/barrier unit
        assign tmem_peer_bar_valid = !tmem_bar_wakeup_valid &&
                                     cta_sync_out_valid[0] &&
                                     cta_sync_in_ready[(NUM_TCU_PIPES - 1)];
        assign tmem_peer_bar_id    = cta_sync_out_bar_id[0];
        assign tmem_peer_bar_phase = cta_sync_out_phase[0];
    end

    // -------------------------------------------------------------------------
    // Pipe Tile Feed & Output Routing
    // -------------------------------------------------------------------------
    always_comb begin
        for (int p = 0; p < NUM_TCU_PIPES; ++p) begin
            if (tmem_mma_route_en && !ext_tile_in_valid[p] && tmem_rd_ready_q[p]) begin
                pipe_tile_in_valid[p] = 1'b1;
                ext_tile_in_ready[p]  = 1'b0;
                pipe_a_tile_in[p]     = tmem_a_buf_q[p];
                pipe_b_tile_in[p]     = tmem_b_buf_q[p];
                pipe_c_tile_in[p]     = tmem_c_buf_q[p];
            end else begin
                pipe_tile_in_valid[p] = ext_tile_in_valid[p];
                ext_tile_in_ready[p]  = pipe_tile_in_ready[p];
                pipe_a_tile_in[p]     = ext_a_tile_in[p];
                pipe_b_tile_in[p]     = ext_b_tile_in[p];
                pipe_c_tile_in[p]     = ext_c_tile_in[p];
            end
            pipe_a_sparse_cand_in[p] = ext_a_sparse_cand_in[p];
            pipe_sparse_meta_in[p]   = ext_sparse_meta_in[p];
            pipe_scale_a_in[p]       = ext_scale_a_in[p];
            pipe_scale_b_in[p]       = ext_scale_b_in[p];
            pipe_bias_in[p]          = ext_bias_in[p];

            tile_out_valid[p]      = pipe_tile_out_valid[p];
            pipe_tile_out_ready[p] = tile_out_ready[p];
            d_tile_out[p]          = pipe_d_tile_out[p];
            out_desc_id[p]         = pipe_out_desc_id[p];
            flags_out[p]           = pipe_flags_out[p];
        end
    end

    // -------------------------------------------------------------------------
    // TCU Pipe -> TMEM MMA Port Round-Robin Arbitrated Bridge
    // -------------------------------------------------------------------------
    function automatic tmem_op_e map_tcu_operand_to_tmem_op(
        input logic       is_write,
        input logic [1:0] operand_sel
    );
        if (is_write) begin
            return TMEM_OP_MMA_WR_D;
        end else begin
            case (operand_sel)
                2'd0:    return TMEM_OP_MMA_RD_A;
                2'd1:    return TMEM_OP_MMA_RD_B;
                default: return TMEM_OP_MMA_RD_C;
            endcase
        end
    endfunction

    always_comb begin
        int m_base;
        int n_base;
        int k_pair_base;

        k_pair_base    = 0;
        n_base         = 0;
        sel_pipe_found = 1'b0;
        sel_pipe_idx   = rr_pipe_q;
        for (int offset = 0; offset < NUM_TCU_PIPES; ++offset) begin
            int idx;
            idx = (int'(rr_pipe_q) + offset) % NUM_TCU_PIPES;
            if (!sel_pipe_found && pipe_tmem_req_valid[idx] && pipe_tmem_req_out[idx].valid) begin
                sel_pipe_found = 1'b1;
                sel_pipe_idx   = PIPE_IDX_W'(idx);
            end
        end

        pipe_tmem_grant    = '0;
        tmem_mma_req_valid = sel_pipe_found;
        if (sel_pipe_found) begin
            pipe_tmem_grant[sel_pipe_idx] = tmem_mma_req_ready;
        end

        for (int p = 0; p < NUM_TCU_PIPES; ++p) begin
            pipe_tmem_req_ready[p] = pipe_tmem_grant[p];
        end

        tmem_mma_req_op            = map_tcu_operand_to_tmem_op(
                                        pipe_tmem_req_out[sel_pipe_idx].is_write,
                                        pipe_tmem_req_out[sel_pipe_idx].operand_sel
                                     );
        tmem_mma_req_tag           = {pipe_tmem_req_out[sel_pipe_idx].desc_id[7-PIPE_IDX_W:0],
                                      sel_pipe_idx};
        tmem_mma_req_region_id     = pipe_region_id_cfg[sel_pipe_idx];
        tmem_mma_req_warp_id       = pipe_warp_id_cfg[sel_pipe_idx];
        tmem_mma_req_row           = pipe_tmem_req_out[sel_pipe_idx].row;
        tmem_mma_req_col           = pipe_tmem_req_out[sel_pipe_idx].col;
        tmem_mma_req_swizzle       = tmem_swizzle_e'(pipe_tmem_req_out[sel_pipe_idx].swizzle_mode);
        tmem_mma_req_col_count     = pipe_tmem_req_out[sel_pipe_idx].col_count;
        tmem_mma_req_ping_pong_sel = pipe_ping_pong_cfg[sel_pipe_idx];

        tmem_mma_req_wr_data = '0;
        tmem_mma_req_wr_be   = '0;
        m_base               = (int'(pipe_wb_beat_q[sel_pipe_idx]) * 2) % ARRAY_M;
        for (int l = 0; l < TMEM_LANES; ++l) begin
            int m_idx;
            int n_pair;
            m_idx  = (m_base + (l / ((ARRAY_N > 1) ? ((ARRAY_N + 1) / 2) : 1))) % ARRAY_M;
            n_pair = (l % ((ARRAY_N > 1) ? ((ARRAY_N + 1) / 2) : 1)) * 2;
            if ((l < (ARRAY_M * ((ARRAY_N + 1) / 2))) && (n_pair < ARRAY_N)) begin
                if ((n_pair + 1) < ARRAY_N) begin
                    tmem_mma_req_wr_data[l] = {pipe_wb_buf_q[sel_pipe_idx][m_idx][n_pair + 1],
                                               pipe_wb_buf_q[sel_pipe_idx][m_idx][n_pair]};
                    tmem_mma_req_wr_be[l]   = pipe_tmem_req_out[sel_pipe_idx].is_write ? 8'hFF : 8'h00;
                end else begin
                    tmem_mma_req_wr_data[l] = {32'd0, pipe_wb_buf_q[sel_pipe_idx][m_idx][n_pair]};
                    tmem_mma_req_wr_be[l]   = pipe_tmem_req_out[sel_pipe_idx].is_write ? 8'h0F : 8'h00;
                end
            end
        end

        // Capture output tiles into per-pipe writeback buffer for TMEM MMA_WR_D drain
        pipe_wb_pending_d = pipe_wb_pending_q;
        pipe_wb_buf_d     = pipe_wb_buf_q;
        pipe_wb_beat_d    = pipe_wb_beat_q;
        for (int p = 0; p < NUM_TCU_PIPES; ++p) begin
            if (pipe_tile_out_valid[p] && pipe_tile_out_ready[p]) begin
                pipe_wb_pending_d[p] = 1'b1;
                pipe_wb_buf_d[p]     = pipe_d_tile_out[p];
                pipe_wb_beat_d[p]    = 4'd0;
            end else if (pipe_tmem_grant[p] && pipe_tmem_req_out[p].is_write) begin
                if (int'(pipe_wb_beat_q[p]) + 1 >= ((ARRAY_M * ((ARRAY_N + 1) / 2) + TMEM_LANES - 1) / TMEM_LANES)) begin
                    pipe_wb_pending_d[p] = 1'b0;
                    pipe_wb_beat_d[p]    = 4'd0;
                end else begin
                    pipe_wb_beat_d[p] = pipe_wb_beat_q[p] + 4'd1;
                end
            end
        end

        rr_pipe_d = rr_pipe_q;
        if (tmem_mma_req_valid && tmem_mma_req_ready) begin
            if (int'(sel_pipe_idx) + 1 >= NUM_TCU_PIPES) begin
                rr_pipe_d = '0;
            end else begin
                rr_pipe_d = sel_pipe_idx + PIPE_IDX_W'(1);
            end
        end

        // Gather TMEM MMA read beats into staged tile operand buffers when routed
        rsp_target_p      = tmem_mma_rsp_tag[PIPE_IDX_W-1:0];
        rsp_pipe_in_range = (int'(rsp_target_p) < NUM_TCU_PIPES);

        if (!tmem_mma_route_en) begin
            tmem_mma_rsp_ready = !reset;
        end else if (!rsp_pipe_in_range) begin
            tmem_mma_rsp_ready = !reset;
        end else begin
            tmem_mma_rsp_ready = !reset &&
                                 !ext_tile_in_valid[rsp_target_p] &&
                                 !tmem_rd_ready_q[rsp_target_p] &&
                                 pipe_tile_in_ready[rsp_target_p];
        end

        tmem_rsp_consume_w = tmem_mma_rsp_valid && tmem_mma_rsp_ready;
        tmem_rd_ready_d    = tmem_rd_ready_q;
        tmem_rd_beat_d     = tmem_rd_beat_q;
        tmem_a_buf_d       = tmem_a_buf_q;
        tmem_b_buf_d       = tmem_b_buf_q;
        tmem_c_buf_d       = tmem_c_buf_q;

        for (int p = 0; p < NUM_TCU_PIPES; ++p) begin
            if (tmem_mma_route_en && !ext_tile_in_valid[p] &&
                tmem_rd_ready_q[p] && pipe_tile_in_ready[p]) begin
                tmem_rd_ready_d[p] = 1'b0;
                tmem_rd_beat_d[p]  = 4'd0;
            end
        end

        if (tmem_mma_route_en && tmem_rsp_consume_w && rsp_pipe_in_range) begin
            k_pair_base = int'(tmem_rd_beat_q[rsp_target_p]) * 2;
            n_base      = int'(tmem_rd_beat_q[rsp_target_p]) * 2;
            if (tmem_mma_rsp_op == TMEM_OP_MMA_RD_A) begin
                for (int m = 0; m < ARRAY_M; ++m) begin
                    if ((m < TMEM_LANES) && tmem_mma_rsp_lane_mask[m]) begin
                        for (int kp = 0; kp < 2; ++kp) begin
                            if ((k_pair_base + kp) < ARRAY_K) begin
                                tmem_a_buf_d[rsp_target_p][m][(k_pair_base + kp)*32 +: 32] =
                                    tmem_mma_rsp_data[m][kp*32 +: 32];
                            end
                        end
                    end
                end
                if ((k_pair_base + 2) >= ARRAY_K) begin
                    tmem_rd_beat_d[rsp_target_p] = 4'd0;
                end else begin
                    tmem_rd_beat_d[rsp_target_p] = tmem_rd_beat_q[rsp_target_p] + 4'd1;
                end
            end else if (tmem_mma_rsp_op == TMEM_OP_MMA_RD_B) begin
                for (int n = 0; n < ARRAY_N; ++n) begin
                    if ((n < TMEM_LANES) && tmem_mma_rsp_lane_mask[n]) begin
                        for (int kp = 0; kp < 2; ++kp) begin
                            if ((k_pair_base + kp) < ARRAY_K) begin
                                tmem_b_buf_d[rsp_target_p][n][(k_pair_base + kp)*32 +: 32] =
                                    tmem_mma_rsp_data[n][kp*32 +: 32];
                            end
                        end
                    end
                end
                if ((k_pair_base + 2) >= ARRAY_K) begin
                    tmem_rd_beat_d[rsp_target_p] = 4'd0;
                end else begin
                    tmem_rd_beat_d[rsp_target_p] = tmem_rd_beat_q[rsp_target_p] + 4'd1;
                end
            end else if (tmem_mma_rsp_op == TMEM_OP_MMA_RD_C) begin
                for (int m = 0; m < ARRAY_M; ++m) begin
                    if ((m < TMEM_LANES) && tmem_mma_rsp_lane_mask[m]) begin
                        if (n_base < ARRAY_N) begin
                            tmem_c_buf_d[rsp_target_p][m][n_base] = tmem_mma_rsp_data[m][31:0];
                        end
                        if ((n_base + 1) < ARRAY_N) begin
                            tmem_c_buf_d[rsp_target_p][m][n_base + 1] = tmem_mma_rsp_data[m][63:32];
                        end
                    end
                end
                if ((n_base + 2) >= ARRAY_N) begin
                    tmem_rd_beat_d[rsp_target_p]  = 4'd0;
                    tmem_rd_ready_d[rsp_target_p] = 1'b1;
                end else begin
                    tmem_rd_beat_d[rsp_target_p] = tmem_rd_beat_q[rsp_target_p] + 4'd1;
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            rr_pipe_q         <= '0;
            pipe_wb_pending_q <= '0;
            pipe_wb_buf_q     <= '0;
            pipe_wb_beat_q    <= '0;
            tmem_rd_ready_q   <= '0;
            tmem_rd_beat_q    <= '0;
            tmem_a_buf_q      <= '0;
            tmem_b_buf_q      <= '0;
            tmem_c_buf_q      <= '0;
        end else begin
            rr_pipe_q         <= rr_pipe_d;
            pipe_wb_pending_q <= pipe_wb_pending_d;
            pipe_wb_buf_q     <= pipe_wb_buf_d;
            pipe_wb_beat_q    <= pipe_wb_beat_d;
            tmem_rd_ready_q   <= tmem_rd_ready_d;
            tmem_rd_beat_q    <= tmem_rd_beat_d;
            tmem_a_buf_q      <= tmem_a_buf_d;
            tmem_b_buf_q      <= tmem_b_buf_d;
            tmem_c_buf_q      <= tmem_c_buf_d;
        end
    end

    // -------------------------------------------------------------------------
    // Instantiate Complete 256 KiB/core Dedicated TMEM Subsystem
    // -------------------------------------------------------------------------
    VX_tmem_top #(
        .NUM_BANKS  (TMEM_NUM_BANKS),
        .BANK_DEPTH (TMEM_BANK_DEPTH_WORDS),
        .LANES      (TMEM_LANES)
    ) u_tmem_top (
        .clk                      (clk),
        .reset                    (reset),
        .alloc_valid              (tmem_alloc_valid),
        .alloc_ready              (tmem_alloc_ready),
        .alloc_op                 (tmem_alloc_op),
        .alloc_auto_place         (tmem_alloc_auto_place),
        .alloc_buddy_align        (tmem_alloc_buddy_align),
        .alloc_strict_owner       (tmem_alloc_strict_owner),
        .alloc_req                (tmem_alloc_req),
        .alloc_rsp                (tmem_alloc_rsp),
        .alloc_query_valid        (tmem_alloc_query_valid),
        .alloc_query_entry        (tmem_alloc_query_entry),
        .ld_desc_valid            (tmem_ld_desc_valid),
        .ld_desc_ready            (tmem_ld_desc_ready),
        .ld_desc_tag              (tmem_ld_desc_tag),
        .ld_desc_region_id        (tmem_ld_desc_region_id),
        .ld_desc_warp_id          (tmem_ld_desc_warp_id),
        .ld_desc_row_base         (tmem_ld_desc_row_base),
        .ld_desc_col_base         (tmem_ld_desc_col_base),
        .ld_desc_num_rows         (tmem_ld_desc_num_rows),
        .ld_desc_num_cols         (tmem_ld_desc_num_cols),
        .ld_desc_elem_bytes       (tmem_ld_desc_elem_bytes),
        .ld_desc_col_major        (tmem_ld_desc_col_major),
        .ld_desc_subbyte_shift    (tmem_ld_desc_subbyte_shift),
        .ld_xform_en              (tmem_ld_xform_en),
        .ld_xform_mode            (tmem_ld_xform_mode),
        .ld_xform_fmt             (tmem_ld_xform_fmt),
        .ld_xform_tile8x8         (tmem_ld_xform_tile8x8),
        .ld_xform_unpack32        (tmem_ld_xform_unpack32),
        .ld_rsp_valid             (tmem_ld_rsp_valid),
        .ld_rsp_ready             (tmem_ld_rsp_ready),
        .ld_rsp_tag               (tmem_ld_rsp_tag),
        .ld_rsp_warp_id           (tmem_ld_rsp_warp_id),
        .ld_rsp_status            (tmem_ld_rsp_status),
        .ld_rsp_data              (tmem_ld_rsp_data),
        .ld_rsp_lane_mask         (tmem_ld_rsp_lane_mask),
        .ld_rsp_last              (tmem_ld_rsp_last),
        .ld_rsp_ecc_ce            (tmem_ld_rsp_ecc_ce),
        .ld_rsp_ecc_ue            (tmem_ld_rsp_ecc_ue),
        .st_req_valid             (tmem_st_req_valid),
        .st_req_ready             (tmem_st_req_ready),
        .st_req_tag               (tmem_st_req_tag),
        .st_req_region_id         (tmem_st_req_region_id),
        .st_req_warp_id           (tmem_st_req_warp_id),
        .st_req_row_base          (tmem_st_req_row_base),
        .st_req_col_base          (tmem_st_req_col_base),
        .st_req_num_rows          (tmem_st_req_num_rows),
        .st_req_num_cols          (tmem_st_req_num_cols),
        .st_req_col_major         (tmem_st_req_col_major),
        .st_req_cell32_mode       (tmem_st_req_cell32_mode),
        .st_req_data              (tmem_st_req_data),
        .st_req_be                (tmem_st_req_be),
        .st_req_last              (tmem_st_req_last),
        .st_ack_valid             (tmem_st_ack_valid),
        .st_ack_ready             (tmem_st_ack_ready),
        .st_ack_tag               (tmem_st_ack_tag),
        .st_ack_warp_id           (tmem_st_ack_warp_id),
        .st_ack_status            (tmem_st_ack_status),
        .mma_req_valid            (tmem_mma_req_valid),
        .mma_req_ready            (tmem_mma_req_ready),
        .mma_req_op               (tmem_mma_req_op),
        .mma_req_tag              (tmem_mma_req_tag),
        .mma_req_region_id        (tmem_mma_req_region_id),
        .mma_req_warp_id          (tmem_mma_req_warp_id),
        .mma_req_row              (tmem_mma_req_row),
        .mma_req_col              (tmem_mma_req_col),
        .mma_req_swizzle          (tmem_mma_req_swizzle),
        .mma_req_col_count        (tmem_mma_req_col_count),
        .mma_req_ping_pong_sel    (tmem_mma_req_ping_pong_sel),
        .mma_req_wr_data          (tmem_mma_req_wr_data),
        .mma_req_wr_be            (tmem_mma_req_wr_be),
        .mma_rsp_valid            (tmem_mma_rsp_valid),
        .mma_rsp_ready            (tmem_mma_rsp_ready),
        .mma_rsp_op               (tmem_mma_rsp_op),
        .mma_rsp_tag              (tmem_mma_rsp_tag),
        .mma_rsp_status           (tmem_mma_rsp_status),
        .mma_rsp_data             (tmem_mma_rsp_data),
        .mma_rsp_lane_mask        (tmem_mma_rsp_lane_mask),
        .mma_rsp_ecc_ce           (tmem_mma_rsp_ecc_ce),
        .mma_rsp_ecc_ue           (tmem_mma_rsp_ecc_ue),
        .wait_req_valid           (tmem_wait_req_valid),
        .wait_req_ready           (tmem_wait_req_ready),
        .wait_req_op              (tmem_wait_req_op),
        .wait_req_tag             (tmem_wait_req_tag),
        .wait_req_region_id       (tmem_wait_req_region_id),
        .wait_req_warp_id         (tmem_wait_req_warp_id),
        .wait_req_scope_warp      (tmem_wait_req_scope_warp),
        .wait_req_barrier_id      (tmem_wait_req_barrier_id),
        .wait_req_barrier_phase   (tmem_wait_req_barrier_phase),
        .peer_bar_valid           (tmem_peer_bar_valid),
        .peer_bar_ready           (tmem_peer_bar_ready),
        .peer_bar_id              (tmem_peer_bar_id),
        .peer_bar_phase           (tmem_peer_bar_phase),
        .bar_wakeup_valid         (tmem_bar_wakeup_valid),
        .bar_wakeup_id            (tmem_bar_wakeup_id),
        .bar_wakeup_phase         (tmem_bar_wakeup_phase),
        .wait_rsp_valid           (tmem_wait_rsp_valid),
        .wait_rsp_ready           (tmem_wait_rsp_ready),
        .wait_rsp_op              (tmem_wait_rsp_op),
        .wait_rsp_tag             (tmem_wait_rsp_tag),
        .wait_rsp_status          (tmem_wait_rsp_status),
        .cfg_weight_ld            (cfg_weight_ld),
        .cfg_weight_st            (cfg_weight_st),
        .cfg_weight_mma           (cfg_weight_mma),
        .cfg_strict_mma_prio      (cfg_strict_mma_prio),
        .cfg_starve_limit         (cfg_starve_limit),
        .ecc_inj_en               (ecc_inj_en),
        .ecc_inj_bank             (ecc_inj_bank),
        .ecc_inj_mask             (ecc_inj_mask),
        .scrub_en                 (scrub_en),
        .perf_clear               (perf_clear),
        .deadlock_fault_out       (tmem_deadlock_fault_out),
        .bounds_fault_out         (tmem_bounds_fault_out),
        .bounds_fault_reason_out  (tmem_bounds_fault_reason_out),
        .perf_cnt_out             (tmem_perf_cnt_out),
        .ecc_ce_count_out         (tmem_ecc_ce_count_out),
        .ecc_ue_count_out         (tmem_ecc_ue_count_out),
        .occupied_granules_out    (tmem_occupied_granules_out),
        .peak_granules_out        (tmem_peak_granules_out)
    );

    // Silence unused slice diagnostic bits
    `UNUSED_VAR (tmem_mma_rsp_tag)
    `UNUSED_VAR (tmem_mma_rsp_status)
    `UNUSED_VAR (tmem_mma_rsp_ecc_ce)
    `UNUSED_VAR (tmem_mma_rsp_ecc_ue)
    `UNUSED_VAR (pipe_wb_pending_q)

endmodule
