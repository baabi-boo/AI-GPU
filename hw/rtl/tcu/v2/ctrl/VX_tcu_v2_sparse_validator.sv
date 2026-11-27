// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_sparse_validator #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            valid_in,
    input  logic                                            sparse_en,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e                      fmt_a,
    input  logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0]      desc_id_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]              sparse_meta_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]              a_tile_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]              a_sparse_cand_in,
    input  logic                                            fault_clear,
    input  logic                                            comp_meta_valid,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]              comp_meta_in,
    output logic                                            fault_detected_comb_out,
    output logic [ARRAY_M-1:0][ARRAY_K*4-1:0]               group_err_mask_comb_out,
    output logic                                            val_valid_out,
    output logic                                            fault_detected_out,
    output logic                                            fault_sticky_out,
    output logic                                            fmt_illegal_out,
    output logic [ARRAY_M-1:0][ARRAY_K*4-1:0]               group_err_mask_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0]      val_desc_id_out,
    output logic [7:0]                                      syndrome_row_out,
    output logic [7:0]                                      syndrome_group_out,
    output VX_tcu_v2_pkg::tcu_v2_sparse_meta4_t             syndrome_meta_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0]      syndrome_desc_id_out,
    output logic [3:0]                                      syndrome_code_out,
    output logic [15:0]                                     checked_tiles_out,
    output logic [15:0]                                     fault_events_out,
    output logic [15:0]                                     comp_mismatch_cnt_out
);

    import VX_tcu_v2_pkg::*;

    localparam int GROUPS_PER_ROW = ARRAY_K * 4;
    localparam int TOTAL_GROUPS   = ARRAY_M * GROUPS_PER_ROW;

    localparam logic [3:0] FAULT_CODE_NONE        = 4'd0;
    localparam logic [3:0] FAULT_CODE_ORDER       = 4'd1;
    localparam logic [3:0] FAULT_CODE_EQUAL_IDX   = 4'd2;
    localparam logic [3:0] FAULT_CODE_UNSUP_FMT   = 4'd3;
    localparam logic [3:0] FAULT_CODE_ZERO_CAND   = 4'd4;

    function automatic logic fmt_supports_sparse(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8:       return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic [GROUPS_PER_ROW-1:0] active_group_mask_for_fmt(
        input tcu_v2_fmt_e fmt
    );
        logic [GROUPS_PER_ROW-1:0] mask;
        int unsigned half_k;
        mask   = '0;
        half_k = ARRAY_K / 2;
        case (fmt)
            TCU_V2_FMT_TF32: begin
                for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                    if (g < int'(half_k)) begin
                        mask[g] = 1'b1;
                    end
                end
            end
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16: begin
                for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                    if (g < ARRAY_K) begin
                        mask[g] = 1'b1;
                    end
                end
            end
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8: begin
                for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                    if (g < (ARRAY_K * 2)) begin
                        mask[g] = 1'b1;
                    end
                end
            end
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: begin
                mask = {GROUPS_PER_ROW{1'b1}};
            end
            default: begin
                mask = '0;
            end
        endcase
        return mask;
    endfunction

    function automatic logic elem16_is_zero(
        input logic [15:0] val
    );
        logic unused_sign;
        unused_sign = val[15];
        return (val[14:0] == 15'd0) && ((unused_sign == 1'b0) || (unused_sign == 1'b1));
    endfunction

    function automatic logic elem8_is_zero(
        input logic [7:0] val,
        input tcu_v2_fmt_e fmt
    );
        logic unused_sign;
        unused_sign = val[7];
        if (fmt == TCU_V2_FMT_INT8) begin
            return (val == 8'd0);
        end else begin
            return (val[6:0] == 7'd0) && ((unused_sign == 1'b0) || (unused_sign == 1'b1));
        end
    endfunction

    function automatic logic elem32_is_zero(
        input logic [31:0] val
    );
        logic unused_sign;
        unused_sign = val[31];
        return (val[30:0] == 31'd0) && ((unused_sign == 1'b0) || (unused_sign == 1'b1));
    endfunction

    function automatic logic [3:0] group_cand_zero_flags(
        input tcu_v2_fmt_e               fmt,
        input int                        grp_idx,
        input logic [ARRAY_K*32-1:0]     row_tile,
        input logic [ARRAY_K*32-1:0]     row_cand
    );
        logic [3:0] zflags;
        int         k_idx;
        int         sub_idx;
        int         fp4_k;
        int         fp4_q;
        zflags  = 4'b0000;
        k_idx   = grp_idx / 2;
        sub_idx = grp_idx % 2;
        fp4_k   = grp_idx / 4;
        fp4_q   = grp_idx % 4;
        case (fmt)
            TCU_V2_FMT_TF32: begin
                if ((2 * grp_idx + 1) < ARRAY_K) begin
                    zflags[0] = elem32_is_zero(row_tile[(2 * grp_idx) * 32 +: 32]);
                    zflags[1] = elem32_is_zero(row_tile[(2 * grp_idx + 1) * 32 +: 32]);
                    zflags[2] = elem32_is_zero(row_cand[(2 * grp_idx) * 32 +: 32]);
                    zflags[3] = elem32_is_zero(row_cand[(2 * grp_idx + 1) * 32 +: 32]);
                end
            end
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16: begin
                if (grp_idx < ARRAY_K) begin
                    zflags[0] = elem16_is_zero(row_tile[grp_idx * 32 +: 16]);
                    zflags[1] = elem16_is_zero(row_tile[grp_idx * 32 + 16 +: 16]);
                    zflags[2] = elem16_is_zero(row_cand[grp_idx * 32 +: 16]);
                    zflags[3] = elem16_is_zero(row_cand[grp_idx * 32 + 16 +: 16]);
                end
            end
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_INT8: begin
                if (k_idx < ARRAY_K) begin
                    if (sub_idx == 0) begin
                        zflags[0] = elem8_is_zero(row_tile[k_idx * 32 +: 8], fmt);
                        zflags[1] = elem8_is_zero(row_tile[k_idx * 32 + 8 +: 8], fmt);
                        zflags[2] = elem8_is_zero(row_cand[k_idx * 32 +: 8], fmt);
                        zflags[3] = elem8_is_zero(row_cand[k_idx * 32 + 8 +: 8], fmt);
                    end else begin
                        zflags[0] = elem8_is_zero(row_tile[k_idx * 32 + 16 +: 8], fmt);
                        zflags[1] = elem8_is_zero(row_tile[k_idx * 32 + 24 +: 8], fmt);
                        zflags[2] = elem8_is_zero(row_cand[k_idx * 32 + 16 +: 8], fmt);
                        zflags[3] = elem8_is_zero(row_cand[k_idx * 32 + 24 +: 8], fmt);
                    end
                end
            end
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2: begin
                if (k_idx < ARRAY_K) begin
                    if (sub_idx == 0) begin
                        zflags[0] = (row_tile[k_idx * 32 +: 5] == 5'd0);
                        zflags[1] = (row_tile[k_idx * 32 + 8 +: 5] == 5'd0);
                        zflags[2] = (row_cand[k_idx * 32 +: 5] == 5'd0);
                        zflags[3] = (row_cand[k_idx * 32 + 8 +: 5] == 5'd0);
                    end else begin
                        zflags[0] = (row_tile[k_idx * 32 + 16 +: 5] == 5'd0);
                        zflags[1] = (row_tile[k_idx * 32 + 24 +: 5] == 5'd0);
                        zflags[2] = (row_cand[k_idx * 32 + 16 +: 5] == 5'd0);
                        zflags[3] = (row_cand[k_idx * 32 + 24 +: 5] == 5'd0);
                    end
                end
            end
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: begin
                if (fp4_k < ARRAY_K) begin
                    zflags[0] = (row_tile[fp4_k * 32 + fp4_q * 8 +: 3] == 3'd0);
                    zflags[1] = (row_tile[fp4_k * 32 + fp4_q * 8 + 4 +: 3] == 3'd0);
                    zflags[2] = (row_cand[fp4_k * 32 + fp4_q * 8 +: 3] == 3'd0);
                    zflags[3] = (row_cand[fp4_k * 32 + fp4_q * 8 + 4 +: 3] == 3'd0);
                end
            end
            default: begin
                zflags = 4'b0000;
            end
        endcase
        return zflags;
    endfunction

    logic [GROUPS_PER_ROW-1:0]                active_groups_comb;
    logic                                     fmt_supported_comb;
    logic                                     fmt_illegal_comb;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   err_mask_comb;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   equal_idx_mask_comb;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   order_inv_mask_comb;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   comp_mismatch_comb;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   zero_cand_mask_comb;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   legal_2_4_mask_comb;

    logic                                     any_group_err_comb;
    logic                                     any_comp_mismatch_comb;
    logic                                     fault_this_cycle_comb;
    logic [7:0]                               first_err_row_comb;
    logic [7:0]                               first_err_grp_comb;
    tcu_v2_sparse_meta4_t                     first_err_meta_comb;
    logic [3:0]                               first_err_code_comb;
    logic                                     err_found_comb;
    logic [$clog2(TOTAL_GROUPS+1)-1:0]        err_group_popcnt_comb;
    logic [$clog2(TOTAL_GROUPS+1)-1:0]        legal_group_popcnt_comb;

    always_comb begin
        tcu_v2_sparse_meta4_t cur_meta;
        tcu_v2_sparse_meta4_t cmp_meta;
        logic [3:0]           zflags;
        logic                 grp_active;
        logic                 legal_pair;
        logic                 sel0_zero;
        logic                 sel1_zero;

        fmt_supported_comb      = fmt_supports_sparse(fmt_a);
        active_groups_comb      = active_group_mask_for_fmt(fmt_a);
        fmt_illegal_comb        = valid_in && sparse_en && !fmt_supported_comb;
        err_mask_comb           = '0;
        equal_idx_mask_comb     = '0;
        order_inv_mask_comb     = '0;
        comp_mismatch_comb      = '0;
        zero_cand_mask_comb     = '0;
        legal_2_4_mask_comb     = '0;
        err_group_popcnt_comb   = '0;
        legal_group_popcnt_comb = '0;

        cur_meta   = '0;
        cmp_meta   = '0;
        zflags     = 4'd0;
        grp_active = 1'b0;
        legal_pair = 1'b0;
        sel0_zero  = 1'b0;
        sel1_zero  = 1'b0;

        for (int m = 0; m < ARRAY_M; ++m) begin
            for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                cur_meta   = tcu_v2_sparse_meta4_t'(sparse_meta_in[m][g*4 +: 4]);
                cmp_meta   = tcu_v2_sparse_meta4_t'(comp_meta_in[m][g*4 +: 4]);
                grp_active = valid_in && sparse_en && active_groups_comb[g];
                legal_pair = tcu_v2_sparse_pair_legal(cur_meta);
                zflags     = active_groups_comb[g]
                             ? group_cand_zero_flags(fmt_a, g, a_tile_in[m], a_sparse_cand_in[m])
                             : 4'b0000;
                sel0_zero  = zflags[cur_meta.idx0];
                sel1_zero  = zflags[cur_meta.idx1];

                if (grp_active && !legal_pair) begin
                    err_mask_comb[m][g]   = 1'b1;
                    err_group_popcnt_comb = err_group_popcnt_comb + 1'b1;
                    if (cur_meta.idx0 == cur_meta.idx1) begin
                        equal_idx_mask_comb[m][g] = 1'b1;
                    end else begin
                        order_inv_mask_comb[m][g] = 1'b1;
                    end
                end else if (grp_active && legal_pair) begin
                    legal_2_4_mask_comb[m][g] = 1'b1;
                    legal_group_popcnt_comb   = legal_group_popcnt_comb + 1'b1;
                end

                if (grp_active && legal_pair && sel0_zero && sel1_zero) begin
                    zero_cand_mask_comb[m][g] = 1'b1;
                end

                if (grp_active && comp_meta_valid && (cur_meta != cmp_meta)) begin
                    comp_mismatch_comb[m][g] = 1'b1;
                end
            end
        end

        any_group_err_comb     = (err_mask_comb != '0);
        any_comp_mismatch_comb = (comp_mismatch_comb != '0);
        fault_this_cycle_comb  = valid_in && sparse_en && (fmt_illegal_comb || any_group_err_comb);

        err_found_comb      = 1'b0;
        first_err_row_comb  = 8'd0;
        first_err_grp_comb  = 8'd0;
        first_err_meta_comb = '0;
        first_err_code_comb = FAULT_CODE_NONE;

        if (fmt_illegal_comb) begin
            err_found_comb      = 1'b1;
            first_err_code_comb = FAULT_CODE_UNSUP_FMT;
        end else begin
            for (int m = 0; m < ARRAY_M; ++m) begin
                for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                    if (!err_found_comb && err_mask_comb[m][g]) begin
                        err_found_comb      = 1'b1;
                        first_err_row_comb  = 8'(m);
                        first_err_grp_comb  = 8'(g);
                        first_err_meta_comb = tcu_v2_sparse_meta4_t'(sparse_meta_in[m][g*4 +: 4]);
                        if (equal_idx_mask_comb[m][g]) begin
                            first_err_code_comb = FAULT_CODE_EQUAL_IDX;
                        end else if (order_inv_mask_comb[m][g]) begin
                            first_err_code_comb = FAULT_CODE_ORDER;
                        end else if (zero_cand_mask_comb[m][g]) begin
                            first_err_code_comb = FAULT_CODE_ZERO_CAND;
                        end else begin
                            first_err_code_comb = FAULT_CODE_ORDER;
                        end
                    end
                end
            end
        end
    end

    typedef struct packed {
        logic                         valid;
        logic [TCU_V2_DESC_ID_W-1:0]  desc_id;
        logic [7:0]                   row;
        logic [7:0]                   grp;
        tcu_v2_sparse_meta4_t         meta;
        logic [3:0]                   code;
    } fault_hist_entry_t;

    localparam int FAULT_HIST_DEPTH = 4;

    logic                                     val_valid_r;
    logic                                     fault_detected_r;
    logic                                     fault_sticky_r;
    logic                                     fmt_illegal_r;
    logic [ARRAY_M-1:0][GROUPS_PER_ROW-1:0]   group_err_mask_r;
    logic [TCU_V2_DESC_ID_W-1:0]              val_desc_id_r;
    logic [7:0]                               syndrome_row_r;
    logic [7:0]                               syndrome_group_r;
    tcu_v2_sparse_meta4_t                     syndrome_meta_r;
    logic [TCU_V2_DESC_ID_W-1:0]              syndrome_desc_id_r;
    logic [3:0]                               syndrome_code_r;
    logic [15:0]                              checked_tiles_r;
    logic [15:0]                              fault_events_r;
    logic [15:0]                              comp_mismatch_cnt_r;
    logic [31:0]                              legal_groups_total_r;
    logic [31:0]                              illegal_groups_total_r;
    fault_hist_entry_t [FAULT_HIST_DEPTH-1:0] fault_hist_r;
    logic [1:0]                               fault_hist_ptr_r;

    logic [$clog2(TOTAL_GROUPS+1)-1:0] zero_cand_popcnt;
    always_comb begin
        zero_cand_popcnt = '0;
        for (int m = 0; m < ARRAY_M; ++m) begin
            for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                if (zero_cand_mask_comb[m][g]) begin
                    zero_cand_popcnt = zero_cand_popcnt + 1'b1;
                end
            end
        end
    end

    logic zero_cand_observed_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            val_valid_r            <= 1'b0;
            fault_detected_r       <= 1'b0;
            fault_sticky_r         <= 1'b0;
            fmt_illegal_r          <= 1'b0;
            group_err_mask_r       <= '0;
            val_desc_id_r          <= '0;
            syndrome_row_r         <= 8'd0;
            syndrome_group_r       <= 8'd0;
            syndrome_meta_r        <= '0;
            syndrome_desc_id_r     <= '0;
            syndrome_code_r        <= FAULT_CODE_NONE;
            checked_tiles_r        <= 16'd0;
            fault_events_r         <= 16'd0;
            comp_mismatch_cnt_r    <= 16'd0;
            zero_cand_observed_r   <= 1'b0;
            legal_groups_total_r   <= 32'd0;
            illegal_groups_total_r <= 32'd0;
            fault_hist_ptr_r       <= 2'd0;
            for (int i = 0; i < FAULT_HIST_DEPTH; ++i) begin
                fault_hist_r[i] <= '0;
            end
        end else begin
            val_valid_r      <= valid_in;
            fault_detected_r <= fault_this_cycle_comb;
            fmt_illegal_r    <= fmt_illegal_comb;
            group_err_mask_r <= err_mask_comb;
            val_desc_id_r    <= desc_id_in;

            if (valid_in) begin
                checked_tiles_r      <= checked_tiles_r + 16'd1;
                zero_cand_observed_r <= (zero_cand_popcnt != '0);
                if (sparse_en) begin
                    legal_groups_total_r   <= legal_groups_total_r + 32'(legal_group_popcnt_comb);
                    illegal_groups_total_r <= illegal_groups_total_r + 32'(err_group_popcnt_comb);
                end
            end else begin
                zero_cand_observed_r <= 1'b0;
            end

            if (fault_clear) begin
                fault_sticky_r <= fault_this_cycle_comb;
                if (fault_this_cycle_comb) begin
                    syndrome_row_r     <= first_err_row_comb;
                    syndrome_group_r   <= first_err_grp_comb;
                    syndrome_meta_r    <= first_err_meta_comb;
                    syndrome_desc_id_r <= desc_id_in;
                    syndrome_code_r    <= first_err_code_comb;
                end else begin
                    syndrome_row_r     <= 8'd0;
                    syndrome_group_r   <= 8'd0;
                    syndrome_meta_r    <= '0;
                    syndrome_desc_id_r <= '0;
                    syndrome_code_r    <= FAULT_CODE_NONE;
                end
            end else if (fault_this_cycle_comb) begin
                fault_events_r                               <= fault_events_r + 16'd1;
                fault_hist_r[fault_hist_ptr_r].valid         <= 1'b1;
                fault_hist_r[fault_hist_ptr_r].desc_id       <= desc_id_in;
                fault_hist_r[fault_hist_ptr_r].row           <= first_err_row_comb;
                fault_hist_r[fault_hist_ptr_r].grp           <= first_err_grp_comb;
                fault_hist_r[fault_hist_ptr_r].meta          <= first_err_meta_comb;
                fault_hist_r[fault_hist_ptr_r].code          <= first_err_code_comb;
                fault_hist_ptr_r                             <= fault_hist_ptr_r + 2'd1;
                if (!fault_sticky_r) begin
                    fault_sticky_r     <= 1'b1;
                    syndrome_row_r     <= first_err_row_comb;
                    syndrome_group_r   <= first_err_grp_comb;
                    syndrome_meta_r    <= first_err_meta_comb;
                    syndrome_desc_id_r <= desc_id_in;
                    syndrome_code_r    <= first_err_code_comb;
                end
            end

            if (valid_in && sparse_en && comp_meta_valid && any_comp_mismatch_comb) begin
                comp_mismatch_cnt_r <= comp_mismatch_cnt_r + 16'd1;
            end
        end
    end

    `UNUSED_VAR (legal_2_4_mask_comb)
    `UNUSED_VAR (legal_groups_total_r)
    `UNUSED_VAR (illegal_groups_total_r)
    `UNUSED_VAR (fault_hist_r)

    assign fault_detected_comb_out = fault_this_cycle_comb;
    assign group_err_mask_comb_out = err_mask_comb;
    assign val_valid_out           = val_valid_r;
    assign fault_detected_out      = fault_detected_r;
    assign fault_sticky_out        = fault_sticky_r;
    assign fmt_illegal_out         = fmt_illegal_r;
    assign group_err_mask_out      = group_err_mask_r;
    assign val_desc_id_out         = val_desc_id_r;
    assign syndrome_row_out        = syndrome_row_r;
    assign syndrome_group_out      = syndrome_group_r;
    assign syndrome_meta_out       = syndrome_meta_r;
    assign syndrome_desc_id_out    = syndrome_desc_id_r;
    assign syndrome_code_out       = zero_cand_observed_r && (syndrome_code_r == FAULT_CODE_NONE)
                                     ? FAULT_CODE_ZERO_CAND : syndrome_code_r;
    assign checked_tiles_out       = checked_tiles_r;
    assign fault_events_out        = fault_events_r;
    assign comp_mismatch_cnt_out   = comp_mismatch_cnt_r;

endmodule
