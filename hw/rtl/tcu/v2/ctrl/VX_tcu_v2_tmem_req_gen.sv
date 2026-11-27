// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_tmem_req_gen #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                uop_valid,
    output logic                                uop_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t          uop_in,
    input  logic                                tmem_wb_en_in,
    input  logic [1:0]                          swizzle_mode_in,
    input  logic                                dbl_buf_toggle_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] a_row_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] a_col_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] b_row_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] b_col_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] c_row_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] c_col_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_ROW_W-1:0] d_row_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] d_col_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_TMEM_COL_W-1:0] dbl_buf_col_stride,
    output logic                                tmem_req_valid,
    input  logic                                tmem_req_ready,
    output VX_tcu_v2_pkg::tcu_v2_tmem_req_t     tmem_req_out,
    output logic                                busy_out,
    output logic                                tmem_stall_out,
    output logic [31:0]                         rd_a_cnt_out,
    output logic [31:0]                         rd_b_cnt_out,
    output logic [31:0]                         rd_c_cnt_out,
    output logic [31:0]                         wr_d_cnt_out
);

    import VX_tcu_v2_pkg::*;

    typedef enum logic [2:0] {
        REQ_IDLE  = 3'd0,
        REQ_RD_A  = 3'd1,
        REQ_RD_B  = 3'd2,
        REQ_RD_C  = 3'd3,
        REQ_WR_D  = 3'd4
    } req_state_e;

    req_state_e                         state_r;
    tcu_v2_uop_t                        cur_uop_r;
    logic                               cur_wb_en_r;
    logic [1:0]                         cur_swizzle_r;
    logic                               cur_buf_sel_r;
    logic [TCU_V2_TMEM_ROW_W-1:0]       a_row_r;
    logic [TCU_V2_TMEM_COL_W-1:0]       a_col_r;
    logic [TCU_V2_TMEM_ROW_W-1:0]       b_row_r;
    logic [TCU_V2_TMEM_COL_W-1:0]       b_col_r;
    logic [TCU_V2_TMEM_ROW_W-1:0]       c_row_r;
    logic [TCU_V2_TMEM_COL_W-1:0]       c_col_r;
    logic [TCU_V2_TMEM_ROW_W-1:0]       d_row_r;
    logic [TCU_V2_TMEM_COL_W-1:0]       d_col_r;
    logic [TCU_V2_TMEM_COL_W-1:0]       buf_stride_r;
    logic [31:0]                        rd_a_cnt_r;
    logic [31:0]                        rd_b_cnt_r;
    logic [31:0]                        rd_c_cnt_r;
    logic [31:0]                        wr_d_cnt_r;
    logic [31:0]                        stall_cycles_r;
    logic [31:0]                        bytes_xferred_r;
    logic [4:0]                         last_bank_id_r;
    logic [7:0]                         last_col_cnt_r;

    function automatic logic [4:0] preview_swizzled_bank(
        input logic [TCU_V2_TMEM_ROW_W-1:0] row,
        input logic [TCU_V2_TMEM_COL_W-1:0] col,
        input logic [1:0]                   swizzle_mode
    );
        logic [4:0] base_b;
        base_b = col[4:0];
        `UNUSED_VAR (row)
        `UNUSED_VAR (col)
        case (swizzle_mode)
            2'd0:    return base_b;
            2'd1:    return base_b ^ {2'b00, row[2:0]};
            2'd2:    return base_b ^ {1'b0, row[3:0]};
            2'd3:    return base_b ^ row[4:0];
            default: return base_b;
        endcase
    endfunction

    function automatic logic [7:0] calc_col_count(
        input tcu_v2_fmt_e fmt,
        input int          elems,
        input logic        sparse_en
    );
        int unsigned bits_per_elem;
        int unsigned eff_elems;
        int unsigned total_bytes;
        int unsigned cols;
        bits_per_elem = tcu_v2_fmt_bitwidth(fmt);
        if (bits_per_elem == 0) begin
            bits_per_elem = 16;
        end
        eff_elems = sparse_en ? (elems / 2) : elems;
        if (eff_elems == 0) begin
            eff_elems = 1;
        end
        total_bytes = (eff_elems * bits_per_elem + 7) / 8;
        cols        = (total_bytes + 3) / 4;
        if (cols == 0) begin
            return 8'd1;
        end else if (cols > 255) begin
            return 8'd255;
        end else begin
            return 8'(cols);
        end
    endfunction

    function automatic logic [TCU_V2_TMEM_COL_W-1:0] apply_buf_offset(
        input logic [TCU_V2_TMEM_COL_W-1:0] base_col,
        input logic                         buf_sel,
        input logic [TCU_V2_TMEM_COL_W-1:0] stride
    );
        logic [9:0] sum_c;
        if (!buf_sel) begin
            return base_col;
        end
        sum_c = {1'b0, base_col} + {1'b0, stride};
        if (sum_c[9]) begin
            return sum_c[TCU_V2_TMEM_COL_W-1:0];
        end
        return sum_c[TCU_V2_TMEM_COL_W-1:0];
    endfunction

    tcu_v2_tmem_req_t req_comb;
    logic [4:0]       bank_preview_w;
    logic             req_fire_w;

    always_comb begin
        req_comb              = '0;
        req_comb.valid        = (state_r != REQ_IDLE);
        req_comb.desc_id      = cur_uop_r.desc_id;
        req_comb.swizzle_mode = cur_swizzle_r;

        case (state_r)
            REQ_RD_A: begin
                req_comb.is_write    = 1'b0;
                req_comb.operand_sel = 2'd0;
                req_comb.row         = a_row_r;
                req_comb.col         = apply_buf_offset(a_col_r, cur_buf_sel_r, buf_stride_r);
                req_comb.col_count   = calc_col_count(cur_uop_r.fmt_a, ARRAY_K, cur_uop_r.sparse_en);
            end
            REQ_RD_B: begin
                req_comb.is_write    = 1'b0;
                req_comb.operand_sel = 2'd1;
                req_comb.row         = b_row_r;
                req_comb.col         = apply_buf_offset(b_col_r, cur_buf_sel_r, buf_stride_r);
                req_comb.col_count   = calc_col_count(cur_uop_r.fmt_b, ARRAY_K, 1'b0);
            end
            REQ_RD_C: begin
                req_comb.is_write    = 1'b0;
                req_comb.operand_sel = 2'd2;
                req_comb.row         = c_row_r;
                req_comb.col         = c_col_r;
                req_comb.col_count   = (ARRAY_M > 0) ? 8'(ARRAY_N) : 8'd1;
            end
            REQ_WR_D: begin
                req_comb.is_write    = 1'b1;
                req_comb.operand_sel = 2'd3;
                req_comb.row         = d_row_r;
                req_comb.col         = d_col_r;
                req_comb.col_count   = calc_col_count(cur_uop_r.fmt_d, ARRAY_N, 1'b0);
            end
            default: begin
                req_comb.valid = 1'b0;
            end
        endcase

        bank_preview_w = preview_swizzled_bank(req_comb.row, req_comb.col, cur_swizzle_r);
    end

    `UNUSED_VAR (cur_uop_r)
    `UNUSED_VAR (stall_cycles_r)
    `UNUSED_VAR (bytes_xferred_r)
    `UNUSED_VAR (last_bank_id_r)
    `UNUSED_VAR (last_col_cnt_r)

    assign uop_ready      = (state_r == REQ_IDLE);
    assign tmem_req_valid = req_comb.valid;
    assign tmem_req_out   = req_comb;
    assign req_fire_w     = tmem_req_valid && tmem_req_ready;
    assign busy_out       = (state_r != REQ_IDLE);
    assign tmem_stall_out = tmem_req_valid && !tmem_req_ready;
    assign rd_a_cnt_out   = rd_a_cnt_r;
    assign rd_b_cnt_out   = rd_b_cnt_r;
    assign rd_c_cnt_out   = rd_c_cnt_r;
    assign wr_d_cnt_out   = wr_d_cnt_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            state_r         <= REQ_IDLE;
            cur_uop_r       <= '0;
            cur_wb_en_r     <= 1'b0;
            cur_swizzle_r   <= 2'd0;
            cur_buf_sel_r   <= 1'b0;
            a_row_r         <= '0;
            a_col_r         <= '0;
            b_row_r         <= '0;
            b_col_r         <= '0;
            c_row_r         <= '0;
            c_col_r         <= '0;
            d_row_r         <= '0;
            d_col_r         <= '0;
            buf_stride_r    <= '0;
            rd_a_cnt_r      <= 32'd0;
            rd_b_cnt_r      <= 32'd0;
            rd_c_cnt_r      <= 32'd0;
            wr_d_cnt_r      <= 32'd0;
            stall_cycles_r  <= 32'd0;
            bytes_xferred_r <= 32'd0;
            last_bank_id_r  <= 5'd0;
            last_col_cnt_r  <= 8'd0;
        end else begin
            if (tmem_stall_out) begin
                stall_cycles_r <= stall_cycles_r + 32'd1;
            end

            if (req_fire_w) begin
                bytes_xferred_r <= bytes_xferred_r + {22'd0, req_comb.col_count, 2'b00};
                last_bank_id_r  <= bank_preview_w;
                last_col_cnt_r  <= req_comb.col_count;
            end

            case (state_r)
                REQ_IDLE: begin
                    if (uop_valid) begin
                        cur_uop_r     <= uop_in;
                        cur_wb_en_r   <= tmem_wb_en_in;
                        cur_swizzle_r <= swizzle_mode_in;
                        cur_buf_sel_r <= dbl_buf_toggle_in ^ uop_in.step_k[0];
                        a_row_r       <= a_row_in;
                        a_col_r       <= a_col_in;
                        b_row_r       <= b_row_in;
                        b_col_r       <= b_col_in;
                        c_row_r       <= c_row_in;
                        c_col_r       <= c_col_in;
                        d_row_r       <= d_row_in;
                        d_col_r       <= d_col_in;
                        buf_stride_r  <= dbl_buf_col_stride;
                        state_r       <= REQ_RD_A;
                    end
                end

                REQ_RD_A: begin
                    if (req_fire_w) begin
                        rd_a_cnt_r <= rd_a_cnt_r + 32'd1;
                        state_r    <= REQ_RD_B;
                    end
                end

                REQ_RD_B: begin
                    if (req_fire_w) begin
                        rd_b_cnt_r <= rd_b_cnt_r + 32'd1;
                        if (cur_uop_r.is_first_k && cur_uop_r.accum_en) begin
                            state_r <= REQ_RD_C;
                        end else if (cur_uop_r.is_last_k && cur_wb_en_r) begin
                            state_r <= REQ_WR_D;
                        end else begin
                            state_r <= REQ_IDLE;
                        end
                    end
                end

                REQ_RD_C: begin
                    if (req_fire_w) begin
                        rd_c_cnt_r <= rd_c_cnt_r + 32'd1;
                        if (cur_uop_r.is_last_k && cur_wb_en_r) begin
                            state_r <= REQ_WR_D;
                        end else begin
                            state_r <= REQ_IDLE;
                        end
                    end
                end

                REQ_WR_D: begin
                    if (req_fire_w) begin
                        wr_d_cnt_r <= wr_d_cnt_r + 32'd1;
                        state_r    <= REQ_IDLE;
                    end
                end

                default: begin
                    state_r <= REQ_IDLE;
                end
            endcase
        end
    end

endmodule
