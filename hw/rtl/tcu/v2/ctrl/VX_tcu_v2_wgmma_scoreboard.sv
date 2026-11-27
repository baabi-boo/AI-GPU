// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_wgmma_scoreboard #(
    parameter int DEPTH     = VX_tcu_v2_pkg::TCU_V2_DESC_Q_DEPTH,
    parameter int NUM_PIPES = 1,
    parameter int ARRAY_M   = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N   = VX_tcu_v2_pkg::TCU_V2_ARRAY_N
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                alloc_valid,
    output logic                                alloc_ready,
    input  VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t   alloc_desc,
    input  logic [$clog2(NUM_PIPES > 1 ? NUM_PIPES : 2)-1:0] alloc_pipe_id,
    input  logic                                query_valid,
    input  VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t   query_desc,
    output logic                                hazard_raw_out,
    output logic                                hazard_war_out,
    output logic                                hazard_waw_out,
    output logic                                hazard_any_out,
    output logic [DEPTH-1:0]                    hazard_slot_mask_out,
    input  logic                                uop_retire_valid,
    input  logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] uop_retire_desc_id,
    input  logic                                uop_retire_last,
    input  logic                                commit_group_fence_en,
    output logic                                commit_group_idle_out,
    output logic                                retire_pulse_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] retire_desc_id_out,
    output logic [DEPTH-1:0]                    inflight_mask_out,
    output logic [$clog2(DEPTH+1)-1:0]          inflight_count_out,
    output logic [31:0]                         descs_retired_cnt_out,
    output logic [31:0]                         hazard_stall_cnt_out
);

    import VX_tcu_v2_pkg::*;

    localparam int PIPE_W = $clog2(NUM_PIPES > 1 ? NUM_PIPES : 2);
    localparam int CNT_W  = $clog2(DEPTH + 1);

    typedef struct packed {
        logic                         valid;
        logic                         done_pending;
        logic [TCU_V2_DESC_ID_W-1:0]  desc_id;
        logic [PIPE_W-1:0]            pipe_id;
        logic [15:0]                  seq_no;
        logic [15:0]                  uops_expected;
        logic [15:0]                  uops_retired;
        logic [TCU_V2_TMEM_COL_W-1:0] a_col_start;
        logic [TCU_V2_TMEM_COL_W-1:0] a_col_end;
        logic [TCU_V2_TMEM_COL_W-1:0] b_col_start;
        logic [TCU_V2_TMEM_COL_W-1:0] b_col_end;
        logic [TCU_V2_TMEM_COL_W-1:0] c_col_start;
        logic [TCU_V2_TMEM_COL_W-1:0] c_col_end;
        logic [TCU_V2_TMEM_COL_W-1:0] d_col_start;
        logic [TCU_V2_TMEM_COL_W-1:0] d_col_end;
        logic                         reads_c;
        logic                         writes_d;
    } sb_slot_t;

    function automatic logic [TCU_V2_TMEM_COL_W-1:0] calc_col_end(
        input logic [TCU_V2_TMEM_COL_W-1:0] start_col,
        input logic [15:0]                  extent_elems
    );
        logic [9:0] span;
        logic [9:0] sum_col;
        span    = (extent_elems > 16'd32) ? extent_elems[9:0] : 10'd32;
        sum_col = {1'b0, start_col} + span - 10'd1;
        if (sum_col >= 10'd512) begin
            return 9'd511;
        end else begin
            return sum_col[8:0];
        end
    endfunction

    function automatic logic ranges_overlap(
        input logic [TCU_V2_TMEM_COL_W-1:0] a0,
        input logic [TCU_V2_TMEM_COL_W-1:0] a1,
        input logic [TCU_V2_TMEM_COL_W-1:0] b0,
        input logic [TCU_V2_TMEM_COL_W-1:0] b1
    );
        return (a0 <= b1) && (b0 <= a1);
    endfunction

    sb_slot_t [DEPTH-1:0]         slots_r;
    logic [15:0]                  next_seq_r;
    logic [31:0]                  descs_retired_r;
    logic [31:0]                  hazard_stall_r;
    logic [31:0]                  raw_hazard_cnt_r;
    logic [31:0]                  war_hazard_cnt_r;
    logic [31:0]                  waw_hazard_cnt_r;
    logic [31:0]                  uops_retired_total_r;
    logic [NUM_PIPES-1:0][4:0]    pipe_inflight_cnt_r;
    logic [4:0]                   peak_inflight_r;
    logic                         retire_pulse_r;
    logic [TCU_V2_DESC_ID_W-1:0]  retire_desc_id_r;

    logic [DEPTH-1:0]             free_vec_w;
    logic                         has_free_w;
    logic [$clog2(DEPTH)-1:0]     free_idx_w;

    logic [TCU_V2_TMEM_COL_W-1:0] q_a_start_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_a_end_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_b_start_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_b_end_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_c_start_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_c_end_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_d_start_w;
    logic [TCU_V2_TMEM_COL_W-1:0] q_d_end_w;
    logic                         q_reads_c_w;
    logic                         q_writes_d_w;

    logic                         haz_raw_comb;
    logic                         haz_war_comb;
    logic                         haz_waw_comb;
    logic [DEPTH-1:0]             haz_mask_comb;

    logic                         retire_cand_found_w;
    logic [$clog2(DEPTH)-1:0]     retire_cand_idx_w;
    logic [15:0]                  retire_oldest_seq_w;

    always_comb begin
        has_free_w = 1'b0;
        free_idx_w = '0;
        free_vec_w = '0;
        for (int i = 0; i < DEPTH; ++i) begin
            free_vec_w[i] = !slots_r[i].valid;
            if (!has_free_w && !slots_r[i].valid) begin
                has_free_w = 1'b1;
                free_idx_w = ($clog2(DEPTH))'(i);
            end
        end
    end

    always_comb begin
        logic same_id;
        logic raw_hit;
        logic war_hit;
        logic waw_hit;

        q_a_start_w  = query_desc.tmem_a_col;
        q_a_end_w    = calc_col_end(query_desc.tmem_a_col, query_desc.tile_k);
        q_b_start_w  = query_desc.tmem_b_col;
        q_b_end_w    = calc_col_end(query_desc.tmem_b_col, query_desc.tile_k);
        q_c_start_w  = query_desc.tmem_c_col;
        q_c_end_w    = calc_col_end(query_desc.tmem_c_col, query_desc.tile_n);
        q_d_start_w  = query_desc.tmem_d_col;
        q_d_end_w    = calc_col_end(query_desc.tmem_d_col, query_desc.tile_n);
        q_reads_c_w  = query_desc.accum_en;
        q_writes_d_w = query_desc.tmem_wb_en;

        haz_raw_comb  = 1'b0;
        haz_war_comb  = 1'b0;
        haz_waw_comb  = 1'b0;
        haz_mask_comb = '0;
        same_id       = 1'b0;
        raw_hit       = 1'b0;
        war_hit       = 1'b0;
        waw_hit       = 1'b0;

        for (int i = 0; i < DEPTH; ++i) begin
            same_id = 1'b0;
            raw_hit = 1'b0;
            war_hit = 1'b0;
            waw_hit = 1'b0;
            if (query_valid && slots_r[i].valid) begin
                same_id = (slots_r[i].desc_id == query_desc.desc_id);

                if (slots_r[i].writes_d) begin
                    if (ranges_overlap(slots_r[i].d_col_start, slots_r[i].d_col_end, q_a_start_w, q_a_end_w) ||
                        ranges_overlap(slots_r[i].d_col_start, slots_r[i].d_col_end, q_b_start_w, q_b_end_w) ||
                        (q_reads_c_w && ranges_overlap(slots_r[i].d_col_start, slots_r[i].d_col_end, q_c_start_w, q_c_end_w))) begin
                        raw_hit = 1'b1;
                    end
                end

                if (q_writes_d_w) begin
                    if (ranges_overlap(q_d_start_w, q_d_end_w, slots_r[i].a_col_start, slots_r[i].a_col_end) ||
                        ranges_overlap(q_d_start_w, q_d_end_w, slots_r[i].b_col_start, slots_r[i].b_col_end) ||
                        (slots_r[i].reads_c && ranges_overlap(q_d_start_w, q_d_end_w, slots_r[i].c_col_start, slots_r[i].c_col_end))) begin
                        war_hit = 1'b1;
                    end
                end

                if (slots_r[i].writes_d && q_writes_d_w) begin
                    if (ranges_overlap(slots_r[i].d_col_start, slots_r[i].d_col_end, q_d_start_w, q_d_end_w)) begin
                        waw_hit = 1'b1;
                    end
                end

                if (same_id || raw_hit || war_hit || waw_hit) begin
                    haz_mask_comb[i] = 1'b1;
                    haz_raw_comb     = haz_raw_comb || raw_hit;
                    haz_war_comb     = haz_war_comb || war_hit;
                    haz_waw_comb     = haz_waw_comb || waw_hit || same_id;
                end
            end
        end
    end

    always_comb begin
        retire_cand_found_w = 1'b0;
        retire_cand_idx_w   = '0;
        retire_oldest_seq_w = 16'hFFFF;
        for (int i = 0; i < DEPTH; ++i) begin
            if (slots_r[i].valid && slots_r[i].done_pending) begin
                if (!retire_cand_found_w || (slots_r[i].seq_no < retire_oldest_seq_w)) begin
                    retire_cand_found_w = 1'b1;
                    retire_cand_idx_w   = ($clog2(DEPTH))'(i);
                    retire_oldest_seq_w = slots_r[i].seq_no;
                end
            end
        end
    end

    logic [DEPTH-1:0]   inflight_mask_w;
    logic [CNT_W-1:0]   inflight_cnt_w;

    always_comb begin
        inflight_cnt_w = '0;
        for (int i = 0; i < DEPTH; ++i) begin
            inflight_mask_w[i] = slots_r[i].valid;
            if (slots_r[i].valid) begin
                inflight_cnt_w = inflight_cnt_w + CNT_W'(1);
            end
        end
    end

    `UNUSED_VAR (query_desc)
    `UNUSED_VAR (free_vec_w)
    `UNUSED_VAR (raw_hazard_cnt_r)
    `UNUSED_VAR (war_hazard_cnt_r)
    `UNUSED_VAR (waw_hazard_cnt_r)
    `UNUSED_VAR (uops_retired_total_r)
    `UNUSED_VAR (pipe_inflight_cnt_r)
    `UNUSED_VAR (peak_inflight_r)

    assign alloc_ready           = has_free_w && !commit_group_fence_en;
    assign hazard_raw_out        = haz_raw_comb;
    assign hazard_war_out        = haz_war_comb;
    assign hazard_waw_out        = haz_waw_comb;
    assign hazard_any_out        = (haz_mask_comb != '0);
    assign hazard_slot_mask_out  = haz_mask_comb;
    assign commit_group_idle_out = (inflight_cnt_w == '0);
    assign retire_pulse_out      = retire_pulse_r;
    assign retire_desc_id_out    = retire_desc_id_r;
    assign inflight_mask_out     = inflight_mask_w;
    assign inflight_count_out    = inflight_cnt_w;
    assign descs_retired_cnt_out = descs_retired_r;
    assign hazard_stall_cnt_out  = hazard_stall_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            next_seq_r           <= 16'd0;
            descs_retired_r      <= 32'd0;
            hazard_stall_r       <= 32'd0;
            raw_hazard_cnt_r     <= 32'd0;
            war_hazard_cnt_r     <= 32'd0;
            waw_hazard_cnt_r     <= 32'd0;
            uops_retired_total_r <= 32'd0;
            pipe_inflight_cnt_r  <= '0;
            peak_inflight_r      <= 5'd0;
            retire_pulse_r       <= 1'b0;
            retire_desc_id_r     <= '0;
            for (int i = 0; i < DEPTH; ++i) begin
                slots_r[i] <= '0;
            end
        end else begin
            retire_pulse_r <= 1'b0;

            if (5'(inflight_cnt_w) > peak_inflight_r) begin
                peak_inflight_r <= 5'(inflight_cnt_w);
            end

            if (query_valid && (haz_mask_comb != '0)) begin
                hazard_stall_r <= hazard_stall_r + 32'd1;
                if (haz_raw_comb) begin
                    raw_hazard_cnt_r <= raw_hazard_cnt_r + 32'd1;
                end
                if (haz_war_comb) begin
                    war_hazard_cnt_r <= war_hazard_cnt_r + 32'd1;
                end
                if (haz_waw_comb) begin
                    waw_hazard_cnt_r <= waw_hazard_cnt_r + 32'd1;
                end
            end

            if (uop_retire_valid) begin
                uops_retired_total_r <= uops_retired_total_r + 32'd1;
                for (int i = 0; i < DEPTH; ++i) begin
                    if (slots_r[i].valid && (slots_r[i].desc_id == uop_retire_desc_id)) begin
                        slots_r[i].uops_retired <= slots_r[i].uops_retired + 16'd1;
                        if (uop_retire_last || ((slots_r[i].uops_retired + 16'd1) >= slots_r[i].uops_expected)) begin
                            slots_r[i].done_pending <= 1'b1;
                        end
                    end
                end
            end

            if (retire_cand_found_w) begin
                slots_r[retire_cand_idx_w].valid        <= 1'b0;
                slots_r[retire_cand_idx_w].done_pending <= 1'b0;
                retire_pulse_r                          <= 1'b1;
                retire_desc_id_r                        <= slots_r[retire_cand_idx_w].desc_id;
                descs_retired_r                         <= descs_retired_r + 32'd1;
                if (pipe_inflight_cnt_r[slots_r[retire_cand_idx_w].pipe_id] != 5'd0) begin
                    pipe_inflight_cnt_r[slots_r[retire_cand_idx_w].pipe_id] <=
                        pipe_inflight_cnt_r[slots_r[retire_cand_idx_w].pipe_id] - 5'd1;
                end
            end

            if (alloc_valid && alloc_ready) begin
                logic [15:0] exp_uops;
                exp_uops = 16'(tcu_v2_output_tile_count_for_desc(alloc_desc, ARRAY_M, ARRAY_N));
                slots_r[free_idx_w].valid         <= 1'b1;
                slots_r[free_idx_w].done_pending  <= (exp_uops == 16'd0);
                slots_r[free_idx_w].desc_id       <= alloc_desc.desc_id;
                slots_r[free_idx_w].pipe_id       <= alloc_pipe_id;
                slots_r[free_idx_w].seq_no        <= next_seq_r;
                slots_r[free_idx_w].uops_expected <= (exp_uops == 16'd0) ? 16'd1 : exp_uops;
                slots_r[free_idx_w].uops_retired  <= 16'd0;
                slots_r[free_idx_w].a_col_start   <= alloc_desc.tmem_a_col;
                slots_r[free_idx_w].a_col_end     <= calc_col_end(alloc_desc.tmem_a_col, alloc_desc.tile_k);
                slots_r[free_idx_w].b_col_start   <= alloc_desc.tmem_b_col;
                slots_r[free_idx_w].b_col_end     <= calc_col_end(alloc_desc.tmem_b_col, alloc_desc.tile_k);
                slots_r[free_idx_w].c_col_start   <= alloc_desc.tmem_c_col;
                slots_r[free_idx_w].c_col_end     <= calc_col_end(alloc_desc.tmem_c_col, alloc_desc.tile_n);
                slots_r[free_idx_w].d_col_start   <= alloc_desc.tmem_d_col;
                slots_r[free_idx_w].d_col_end     <= calc_col_end(alloc_desc.tmem_d_col, alloc_desc.tile_n);
                slots_r[free_idx_w].reads_c       <= alloc_desc.accum_en;
                slots_r[free_idx_w].writes_d      <= alloc_desc.tmem_wb_en;
                next_seq_r                        <= next_seq_r + 16'd1;
                pipe_inflight_cnt_r[alloc_pipe_id] <= pipe_inflight_cnt_r[alloc_pipe_id] + 5'd1;
            end
        end
    end

endmodule
