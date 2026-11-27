// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_uop_expander #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                desc_valid,
    output logic                                desc_ready,
    input  VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t   desc_in,
    input  logic                                cta_gate_open,
    input  logic                                cta_m_half_sel,
    input  logic                                cta_n_half_sel,
    input  logic [1:0]                          swizzle_mode_in,
    output logic                                uop_valid,
    input  logic                                uop_ready,
    output VX_tcu_v2_pkg::tcu_v2_uop_t          uop_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] a_tmem_row_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] a_tmem_col_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] b_tmem_row_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] b_tmem_col_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] c_tmem_row_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] c_tmem_col_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] d_tmem_row_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] d_tmem_col_out,
    output logic                                tmem_req_valid,
    input  logic                                tmem_req_ready,
    output VX_tcu_v2_pkg::tcu_v2_tmem_req_t     tmem_req_out,
    output logic                                desc_expand_done,
    output logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] active_desc_id_out,
    output logic                                busy_out,
    output logic [31:0]                         uops_emitted_cnt_out
);

    import VX_tcu_v2_pkg::*;

    typedef enum logic [1:0] {
        EXP_IDLE = 2'd0,
        EXP_RUN  = 2'd1,
        EXP_WAIT = 2'd2
    } exp_state_e;

    exp_state_e                         state_r;
    tcu_v2_wgmma_desc_t                 cur_desc_r;
    logic [1:0]                         swizzle_r;
    logic [3:0]                         step_m_r;
    logic [3:0]                         step_n_r;
    logic [7:0]                         step_k_r;
    logic [3:0]                         max_m_r;
    logic [3:0]                         max_n_r;
    logic [7:0]                         max_k_r;
    logic                               uop_sent_r;
    logic                               tmem_sent_r;
    logic                               desc_done_r;
    logic [31:0]                        uops_emitted_r;
    logic [31:0]                        descs_expanded_r;
    logic [31:0]                        first_k_uops_r;
    logic [31:0]                        last_k_uops_r;
    logic [31:0]                        cta_stall_cycles_r;
    logic [15:0]                        cur_desc_uop_idx_r;
    logic [15:0]                        cur_desc_uop_tot_r;

    function automatic logic [3:0] calc_steps_m(
        input logic [15:0] tile_m
    );
        int unsigned cnt;
        cnt = (int'(tile_m) + ARRAY_M - 1) / ARRAY_M;
        if (cnt == 0) begin
            return 4'd0;
        end else if (cnt > 16) begin
            return 4'd15;
        end else begin
            return 4'(cnt - 1);
        end
    endfunction

    function automatic logic [3:0] calc_steps_n(
        input logic [15:0] tile_n
    );
        int unsigned cnt;
        cnt = (int'(tile_n) + ARRAY_N - 1) / ARRAY_N;
        if (cnt == 0) begin
            return 4'd0;
        end else if (cnt > 16) begin
            return 4'd15;
        end else begin
            return 4'(cnt - 1);
        end
    endfunction

    function automatic logic [7:0] calc_steps_k(
        input logic [15:0] tile_k,
        input logic        sparse_en
    );
        int unsigned k_step;
        int unsigned cnt;
        k_step = sparse_en ? (2 * ARRAY_K) : ARRAY_K;
        cnt    = (int'(tile_k) + k_step - 1) / k_step;
        if (cnt == 0) begin
            return 8'd0;
        end else if (cnt > 256) begin
            return 8'd255;
        end else begin
            return 8'(cnt - 1);
        end
    endfunction

    function automatic logic [TCU_V2_TMEM_ROW_W-1:0] calc_row_addr(
        input logic [TCU_V2_TMEM_ROW_W-1:0] base_row,
        input logic [3:0]                   tile_idx,
        input logic [9:0]                   tile_stride
    );
        logic [9:0] sum_row;
        sum_row = {3'b000, base_row} + (10'(tile_idx) * tile_stride);
        if (sum_row[9:7] != 3'd0) begin
            return sum_row[TCU_V2_TMEM_ROW_W-1:0];
        end
        return sum_row[TCU_V2_TMEM_ROW_W-1:0];
    endfunction

    function automatic logic [TCU_V2_TMEM_COL_W-1:0] calc_col_addr(
        input logic [TCU_V2_TMEM_COL_W-1:0] base_col,
        input logic [7:0]                   tile_idx,
        input logic [11:0]                  tile_stride
    );
        logic [11:0] sum_col;
        sum_col = {3'b000, base_col} + (12'(tile_idx) * tile_stride);
        if (sum_col[11:9] != 3'd0) begin
            return sum_col[TCU_V2_TMEM_COL_W-1:0];
        end
        return sum_col[TCU_V2_TMEM_COL_W-1:0];
    endfunction

    logic [3:0]                     eff_step_m_w;
    logic [3:0]                     eff_step_n_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]   a_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]   a_col_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]   b_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]   b_col_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]   c_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]   c_col_w;
    logic [TCU_V2_TMEM_ROW_W-1:0]   d_row_w;
    logic [TCU_V2_TMEM_COL_W-1:0]   d_col_w;
    logic                           is_first_k_w;
    logic                           is_last_k_w;
    logic                           is_last_tile_w;
    logic                           step_can_emit_w;
    logic                           uop_fire_w;
    logic                           tmem_fire_w;
    logic                           step_advance_w;

    assign eff_step_m_w = (cur_desc_r.cta_pair_en && cta_m_half_sel) ? (step_m_r + 4'd1) : step_m_r;
    assign eff_step_n_w = (cur_desc_r.cta_pair_en && cta_n_half_sel) ? (step_n_r + 4'd1) : step_n_r;

    assign a_row_w = calc_row_addr(cur_desc_r.tmem_a_row, eff_step_m_w, 10'(ARRAY_M));
    assign a_col_w = calc_col_addr(cur_desc_r.tmem_a_col, step_k_r, 12'(ARRAY_K));
    assign b_row_w = calc_row_addr(cur_desc_r.tmem_b_row, eff_step_n_w, 10'(ARRAY_N));
    assign b_col_w = calc_col_addr(cur_desc_r.tmem_b_col, step_k_r, 12'(ARRAY_K));
    assign c_row_w = calc_row_addr(cur_desc_r.tmem_c_row, eff_step_m_w, 10'(ARRAY_M));
    assign c_col_w = calc_col_addr(cur_desc_r.tmem_c_col, {4'd0, eff_step_n_w}, 12'(ARRAY_N));
    assign d_row_w = calc_row_addr(cur_desc_r.tmem_d_row, eff_step_m_w, 10'(ARRAY_M));
    assign d_col_w = calc_col_addr(cur_desc_r.tmem_d_col, {4'd0, eff_step_n_w}, 12'(ARRAY_N));

    assign is_first_k_w   = (step_k_r == 8'd0);
    assign is_last_k_w    = (step_k_r == max_k_r);
    assign is_last_tile_w = (step_m_r == max_m_r) && (step_n_r == max_n_r) && is_last_k_w;

    assign step_can_emit_w = (state_r == EXP_RUN) && cta_gate_open;
    assign uop_valid       = step_can_emit_w && !uop_sent_r;
    assign tmem_req_valid  = step_can_emit_w && !tmem_sent_r;

    assign uop_fire_w  = uop_valid && uop_ready;
    assign tmem_fire_w = tmem_req_valid && tmem_req_ready;
    assign step_advance_w = step_can_emit_w &&
                            (uop_sent_r || uop_fire_w) &&
                            (tmem_sent_r || tmem_fire_w);

    always_comb begin
        uop_out                = '0;
        uop_out.desc_id        = cur_desc_r.desc_id;
        uop_out.step_m         = eff_step_m_w;
        uop_out.step_n         = eff_step_n_w;
        uop_out.step_k         = step_k_r;
        uop_out.fmt_a          = cur_desc_r.fmt_a;
        uop_out.fmt_b          = cur_desc_r.fmt_b;
        uop_out.fmt_d          = cur_desc_r.fmt_d;
        uop_out.scale_fmt      = cur_desc_r.scale_fmt;
        uop_out.rm             = cur_desc_r.rm;
        uop_out.act            = is_last_k_w ? cur_desc_r.act : TCU_V2_ACT_NONE;
        uop_out.is_first_k     = is_first_k_w;
        uop_out.is_last_k      = is_last_k_w;
        uop_out.accum_en       = is_first_k_w ? cur_desc_r.accum_en : 1'b1;
        uop_out.bias_en        = is_last_k_w ? cur_desc_r.bias_en : 1'b0;
        uop_out.sparse_en      = cur_desc_r.sparse_en;
        uop_out.int_saturate   = cur_desc_r.int_saturate;
        uop_out.clamp_min_fp32 = cur_desc_r.clamp_min_fp32;
        uop_out.clamp_max_fp32 = cur_desc_r.clamp_max_fp32;

        tmem_req_out              = '0;
        tmem_req_out.valid        = tmem_req_valid;
        tmem_req_out.is_write     = is_last_k_w && cur_desc_r.tmem_wb_en;
        tmem_req_out.desc_id      = cur_desc_r.desc_id;
        tmem_req_out.operand_sel  = is_last_k_w && cur_desc_r.tmem_wb_en ? 2'd3 :
                                    (is_first_k_w && cur_desc_r.accum_en ? 2'd2 : 2'd0);
        tmem_req_out.row          = (is_last_k_w && cur_desc_r.tmem_wb_en) ? d_row_w : a_row_w;
        tmem_req_out.col          = (is_last_k_w && cur_desc_r.tmem_wb_en) ? d_col_w : a_col_w;
        tmem_req_out.swizzle_mode = swizzle_r;
        tmem_req_out.col_count    = 8'(ARRAY_K);
    end

    `UNUSED_VAR (cur_desc_r)
    `UNUSED_VAR (descs_expanded_r)
    `UNUSED_VAR (first_k_uops_r)
    `UNUSED_VAR (last_k_uops_r)
    `UNUSED_VAR (cta_stall_cycles_r)
    `UNUSED_VAR (cur_desc_uop_idx_r)
    `UNUSED_VAR (cur_desc_uop_tot_r)

    assign desc_ready           = (state_r == EXP_IDLE);
    assign a_tmem_row_out       = a_row_w;
    assign a_tmem_col_out       = a_col_w;
    assign b_tmem_row_out       = b_row_w;
    assign b_tmem_col_out       = b_col_w;
    assign c_tmem_row_out       = c_row_w;
    assign c_tmem_col_out       = c_col_w;
    assign d_tmem_row_out       = d_row_w;
    assign d_tmem_col_out       = d_col_w;
    assign desc_expand_done     = desc_done_r;
    assign active_desc_id_out   = cur_desc_r.desc_id;
    assign busy_out             = (state_r != EXP_IDLE);
    assign uops_emitted_cnt_out = uops_emitted_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            state_r            <= EXP_IDLE;
            cur_desc_r         <= '0;
            swizzle_r          <= 2'd0;
            step_m_r           <= 4'd0;
            step_n_r           <= 4'd0;
            step_k_r           <= 8'd0;
            max_m_r            <= 4'd0;
            max_n_r            <= 4'd0;
            max_k_r            <= 8'd0;
            uop_sent_r         <= 1'b0;
            tmem_sent_r        <= 1'b0;
            desc_done_r        <= 1'b0;
            uops_emitted_r     <= 32'd0;
            descs_expanded_r   <= 32'd0;
            first_k_uops_r     <= 32'd0;
            last_k_uops_r      <= 32'd0;
            cta_stall_cycles_r <= 32'd0;
            cur_desc_uop_idx_r <= 16'd0;
            cur_desc_uop_tot_r <= 16'd0;
        end else begin
            desc_done_r <= 1'b0;

            case (state_r)
                EXP_IDLE: begin
                    uop_sent_r         <= 1'b0;
                    tmem_sent_r        <= 1'b0;
                    cur_desc_uop_idx_r <= 16'd0;
                    if (desc_valid) begin
                        cur_desc_r         <= desc_in;
                        swizzle_r          <= swizzle_mode_in;
                        step_m_r           <= 4'd0;
                        step_n_r           <= 4'd0;
                        step_k_r           <= 8'd0;
                        max_m_r            <= calc_steps_m(desc_in.tile_m);
                        max_n_r            <= calc_steps_n(desc_in.tile_n);
                        max_k_r            <= calc_steps_k(desc_in.tile_k, desc_in.sparse_en);
                        cur_desc_uop_tot_r <= 16'(tcu_v2_uop_count_for_desc(desc_in, ARRAY_M, ARRAY_N, ARRAY_K));
                        state_r            <= EXP_RUN;
                    end
                end

                EXP_RUN: begin
                    if (!cta_gate_open) begin
                        cta_stall_cycles_r <= cta_stall_cycles_r + 32'd1;
                    end

                    if (uop_fire_w) begin
                        uop_sent_r     <= 1'b1;
                        uops_emitted_r <= uops_emitted_r + 32'd1;
                        if (is_first_k_w) begin
                            first_k_uops_r <= first_k_uops_r + 32'd1;
                        end
                        if (is_last_k_w) begin
                            last_k_uops_r <= last_k_uops_r + 32'd1;
                        end
                    end
                    if (tmem_fire_w) begin
                        tmem_sent_r <= 1'b1;
                    end

                    if (step_advance_w) begin
                        uop_sent_r         <= 1'b0;
                        tmem_sent_r        <= 1'b0;
                        cur_desc_uop_idx_r <= cur_desc_uop_idx_r + 16'd1;
                        if (is_last_tile_w) begin
                            desc_done_r      <= 1'b1;
                            descs_expanded_r <= descs_expanded_r + 32'd1;
                            state_r          <= EXP_WAIT;
                        end else if (!is_last_k_w) begin
                            step_k_r <= step_k_r + 8'd1;
                        end else if (step_n_r != max_n_r) begin
                            step_k_r <= 8'd0;
                            step_n_r <= step_n_r + 4'd1;
                        end else begin
                            step_k_r <= 8'd0;
                            step_n_r <= 4'd0;
                            step_m_r <= step_m_r + 4'd1;
                        end
                    end
                end

                EXP_WAIT: begin
                    state_r <= EXP_IDLE;
                end

                default: begin
                    state_r <= EXP_IDLE;
                end
            endcase
        end
    end

endmodule
