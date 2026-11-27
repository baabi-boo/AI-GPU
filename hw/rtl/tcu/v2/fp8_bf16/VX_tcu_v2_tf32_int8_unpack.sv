// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_tf32_int8_unpack #(
    parameter int   LANES         = 8,
    parameter int   LANE_STRIDE_W = 32,
    parameter logic OUT_REG       = 1'b0
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            enable,
    input  logic                                            valid_in,
    input  logic                                            is_int8,
    input  logic [LANES*LANE_STRIDE_W-1:0]                  data_raw,
    output logic                                            valid_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_unpacked_t [LANES-1:0]  fp_out,
    output logic [LANES-1:0][10:0]                          exp_s11_out,
    output logic [LANES-1:0][31:0]                          fp32_equiv_out,
    output logic signed [LANES-1:0][7:0]                    int8_out,
    output logic [LANES-1:0][7:0]                           int8_abs_out,
    output logic [LANES-1:0]                                is_snan_out,
    output logic [LANES-1:0]                                is_qnan_out,
    output logic [LANES-1:0]                                nan_mask_out,
    output logic [LANES-1:0]                                inf_pos_mask_out,
    output logic [LANES-1:0]                                inf_neg_mask_out,
    output logic [LANES-1:0]                                zero_mask_out,
    output logic [LANES-1:0]                                neg_zero_mask_out,
    output logic [LANES-1:0]                                subnormal_mask_out,
    output logic [LANES-1:0]                                int_neg_mask_out,
    output logic [LANES-1:0]                                int_min_mask_out,
    output logic                                            any_nan_out,
    output logic                                            any_snan_out,
    output logic                                            any_inf_out,
    output logic                                            all_zero_out,
    output logic signed [10:0]                              max_finite_exp_out,
    output logic signed [10:0]                              min_finite_exp_out,
    output logic                                            has_finite_nonzero_out
);
    import VX_tcu_v2_pkg::*;

    localparam int TF32_BIAS    = 127;
    localparam int EXP_TREE_LVL = (LANES <= 1) ? 1 : $clog2(LANES);
    localparam int EXP_TREE_W   = 1 << EXP_TREE_LVL;

    // -------------------------------------------------------------------------
    // TF32 (19-bit S.E8.M10 in 32-bit container) and Signed INT8 Unpacker
    // -------------------------------------------------------------------------
    tcu_v2_fp_unpacked_t [LANES-1:0] comb_fp;
    logic [LANES-1:0][10:0]          comb_exp_s11;
    logic [LANES-1:0][31:0]          comb_fp32_equiv;
    logic signed [LANES-1:0][7:0]    comb_int8;
    logic [LANES-1:0][7:0]           comb_int8_abs;
    logic [LANES-1:0]                comb_is_snan;
    logic [LANES-1:0]                comb_is_qnan;
    logic [LANES-1:0]                comb_nan_mask;
    logic [LANES-1:0]                comb_inf_pos_mask;
    logic [LANES-1:0]                comb_inf_neg_mask;
    logic [LANES-1:0]                comb_zero_mask;
    logic [LANES-1:0]                comb_neg_zero_mask;
    logic [LANES-1:0]                comb_subnorm_mask;
    logic [LANES-1:0]                comb_int_neg_mask;
    logic [LANES-1:0]                comb_int_min_mask;
    logic [LANES-1:0]                comb_finite_nz;

    for (genvar i = 0; i < LANES; ++i) begin : g_tf32_int8_lanes
        logic [31:0]        raw_word;
        logic               tf32_sign;
        logic [7:0]         tf32_exp_raw;
        logic [9:0]         tf32_man_raw;

        logic               exp_is_zero;
        logic               exp_is_max;
        logic               man_is_zero;

        logic               tf32_is_zero;
        logic               tf32_is_subnorm;
        logic               tf32_is_inf;
        logic               tf32_is_nan;
        logic               tf32_is_snan;
        logic               tf32_is_qnan;
        logic               tf32_is_normal;

        logic [3:0]         sub_lzc;
        logic [10:0]        sub_shifted_sig11;
        logic [10:0]        norm_sig11;
        logic signed [10:0] exp_s11_val;
        logic [31:0]        fp32_word;

        logic signed [7:0]  int8_val;
        logic [7:0]         int8_abs_val;
        logic               int8_is_zero;
        logic               int8_is_neg;
        logic               int8_is_min;

        assign raw_word        = data_raw[i*LANE_STRIDE_W +: 32];
        assign tf32_sign       = raw_word[31];
        assign tf32_exp_raw    = raw_word[30:23];
        assign tf32_man_raw    = raw_word[22:13];

        `UNUSED_VAR (raw_word[12:0])

        assign exp_is_zero = (tf32_exp_raw == 8'h00);
        assign exp_is_max  = (tf32_exp_raw == 8'hFF);
        assign man_is_zero = (tf32_man_raw == 10'h000);

        assign tf32_is_zero    = exp_is_zero && man_is_zero;
        assign tf32_is_subnorm = exp_is_zero && !man_is_zero;
        assign tf32_is_inf     = exp_is_max  && man_is_zero;
        assign tf32_is_nan     = exp_is_max  && !man_is_zero;
        assign tf32_is_snan    = tf32_is_nan && !tf32_man_raw[9];
        assign tf32_is_qnan    = tf32_is_nan && tf32_man_raw[9];
        assign tf32_is_normal  = !exp_is_zero && !exp_is_max;

        assign int8_val     = $signed(raw_word[7:0]);
        assign int8_is_zero = (raw_word[7:0] == 8'h00);
        assign int8_is_neg  = raw_word[7];
        assign int8_is_min  = (raw_word[7:0] == 8'h80);
        assign int8_abs_val = int8_is_neg ? (~raw_word[7:0] + 8'd1) : raw_word[7:0];

        always_comb begin
            sub_lzc           = 4'd0;
            sub_shifted_sig11 = 11'd0;
            if (tf32_man_raw[9]) begin
                sub_lzc           = 4'd0;
                sub_shifted_sig11 = {tf32_man_raw, 1'b0};
            end else if (tf32_man_raw[8]) begin
                sub_lzc           = 4'd1;
                sub_shifted_sig11 = {tf32_man_raw[8:0], 2'b00};
            end else if (tf32_man_raw[7]) begin
                sub_lzc           = 4'd2;
                sub_shifted_sig11 = {tf32_man_raw[7:0], 3'b000};
            end else if (tf32_man_raw[6]) begin
                sub_lzc           = 4'd3;
                sub_shifted_sig11 = {tf32_man_raw[6:0], 4'b0000};
            end else if (tf32_man_raw[5]) begin
                sub_lzc           = 4'd4;
                sub_shifted_sig11 = {tf32_man_raw[5:0], 5'b00000};
            end else if (tf32_man_raw[4]) begin
                sub_lzc           = 4'd5;
                sub_shifted_sig11 = {tf32_man_raw[4:0], 6'b000000};
            end else if (tf32_man_raw[3]) begin
                sub_lzc           = 4'd6;
                sub_shifted_sig11 = {tf32_man_raw[3:0], 7'b0000000};
            end else if (tf32_man_raw[2]) begin
                sub_lzc           = 4'd7;
                sub_shifted_sig11 = {tf32_man_raw[2:0], 8'b00000000};
            end else if (tf32_man_raw[1]) begin
                sub_lzc           = 4'd8;
                sub_shifted_sig11 = {tf32_man_raw[1:0], 9'b000000000};
            end else if (tf32_man_raw[0]) begin
                sub_lzc           = 4'd9;
                sub_shifted_sig11 = {tf32_man_raw[0], 10'b0000000000};
            end else begin
                sub_lzc           = 4'd10;
                sub_shifted_sig11 = 11'd0;
            end
        end

        always_comb begin
            norm_sig11  = 11'd0;
            exp_s11_val = 11'sd0;
            if (is_int8) begin
                norm_sig11  = {3'b000, raw_word[7:0]};
                exp_s11_val = 11'sd0;
            end else if (tf32_is_nan || tf32_is_inf) begin
                norm_sig11  = {1'b0, tf32_man_raw};
                exp_s11_val = 11'sd0;
            end else if (tf32_is_zero) begin
                norm_sig11  = 11'd0;
                exp_s11_val = 11'sd0;
            end else if (tf32_is_subnorm) begin
                norm_sig11  = sub_shifted_sig11;
                exp_s11_val = $signed(11'(1 - TF32_BIAS)) - $signed({7'd0, sub_lzc}) - 11'sd1;
            end else begin
                norm_sig11  = {1'b1, tf32_man_raw};
                exp_s11_val = $signed({3'd0, tf32_exp_raw}) - $signed(11'(TF32_BIAS));
            end
        end

        always_comb begin
            if (is_int8) begin
                fp32_word = {{24{int8_is_neg}}, raw_word[7:0]};
            end else if (tf32_is_nan) begin
                fp32_word = {tf32_sign, 8'hFF, 1'b1, tf32_man_raw[8:0], 13'd0};
            end else if (tf32_is_inf) begin
                fp32_word = {tf32_sign, 8'hFF, 23'd0};
            end else if (tf32_is_zero) begin
                fp32_word = {tf32_sign, 31'd0};
            end else if (tf32_is_subnorm) begin
                fp32_word = {tf32_sign, 8'h00, tf32_man_raw, 13'd0};
            end else begin
                fp32_word = {tf32_sign, tf32_exp_raw, tf32_man_raw, 13'd0};
            end
        end

        always_comb begin
            if (is_int8) begin
                comb_fp[i].sign         = int8_is_neg;
                comb_fp[i].exp          = '0;
                comb_fp[i].sig          = {16'd0, raw_word[7:0]};
                comb_fp[i].is_zero      = int8_is_zero;
                comb_fp[i].is_inf       = 1'b0;
                comb_fp[i].is_nan       = 1'b0;
                comb_fp[i].is_subnormal = 1'b0;
            end else begin
                comb_fp[i].sign         = tf32_sign;
                comb_fp[i].exp          = exp_s11_val[TCU_V2_FP_EXP_W-1:0];
                comb_fp[i].sig          = {norm_sig11, 13'd0};
                comb_fp[i].is_zero      = tf32_is_zero;
                comb_fp[i].is_inf       = tf32_is_inf;
                comb_fp[i].is_nan       = tf32_is_nan;
                comb_fp[i].is_subnormal = tf32_is_subnorm;
            end
        end

        assign comb_exp_s11[i]       = exp_s11_val;
        assign comb_fp32_equiv[i]    = fp32_word;
        assign comb_int8[i]          = int8_val;
        assign comb_int8_abs[i]      = int8_abs_val;
        assign comb_is_snan[i]       = !is_int8 && tf32_is_snan;
        assign comb_is_qnan[i]       = !is_int8 && tf32_is_qnan;
        assign comb_nan_mask[i]      = !is_int8 && tf32_is_nan;
        assign comb_inf_pos_mask[i]  = !is_int8 && tf32_is_inf && !tf32_sign;
        assign comb_inf_neg_mask[i]  = !is_int8 && tf32_is_inf && tf32_sign;
        assign comb_zero_mask[i]     = is_int8 ? int8_is_zero : tf32_is_zero;
        assign comb_neg_zero_mask[i] = !is_int8 && tf32_is_zero && tf32_sign;
        assign comb_subnorm_mask[i]  = !is_int8 && tf32_is_subnorm;
        assign comb_int_neg_mask[i]  = is_int8 && int8_is_neg;
        assign comb_int_min_mask[i]  = is_int8 && int8_is_min;
        assign comb_finite_nz[i]     = !is_int8 && (tf32_is_normal || tf32_is_subnorm);

        if (LANE_STRIDE_W > 32) begin : g_unused_upper_bits
            `UNUSED_VAR (data_raw[i*LANE_STRIDE_W + 32 +: (LANE_STRIDE_W - 32)])
        end
    end

    // -------------------------------------------------------------------------
    // Summary Flags and Packed Max/Min Exponent Reduction Across Lanes
    // -------------------------------------------------------------------------
    logic               comb_any_nan;
    logic               comb_any_snan;
    logic               comb_any_inf;
    logic               comb_all_zero;
    logic               comb_has_finite_nz;
    logic signed [10:0] comb_max_finite_exp;
    logic signed [10:0] comb_min_finite_exp;
    logic [3:0]         comb_nan_count;
    logic [3:0]         comb_inf_count;
    logic [3:0]         comb_zero_count;
    logic [3:0]         comb_int_neg_count;
    logic               comb_sign_xor;

    assign comb_any_nan       = |comb_nan_mask;
    assign comb_any_snan      = |comb_is_snan;
    assign comb_any_inf       = (|comb_inf_pos_mask) || (|comb_inf_neg_mask);
    assign comb_all_zero      = &comb_zero_mask;
    assign comb_has_finite_nz = |comb_finite_nz;

    always_comb begin
        comb_nan_count     = 4'd0;
        comb_inf_count     = 4'd0;
        comb_zero_count    = 4'd0;
        comb_int_neg_count = 4'd0;
        comb_sign_xor      = 1'b0;
        for (int p = 0; p < LANES; ++p) begin
            comb_nan_count     = comb_nan_count     + {3'd0, comb_nan_mask[p]};
            comb_inf_count     = comb_inf_count     + {3'd0, comb_inf_pos_mask[p] | comb_inf_neg_mask[p]};
            comb_zero_count    = comb_zero_count    + {3'd0, comb_zero_mask[p]};
            comb_int_neg_count = comb_int_neg_count + {3'd0, comb_int_neg_mask[p]};
            comb_sign_xor      = comb_sign_xor      ^ comb_fp[p].sign;
        end
    end

    `UNUSED_VAR (comb_nan_count)
    `UNUSED_VAR (comb_inf_count)
    `UNUSED_VAR (comb_zero_count)
    `UNUSED_VAR (comb_int_neg_count)
    `UNUSED_VAR (comb_sign_xor)

    logic [EXP_TREE_LVL:0][EXP_TREE_W-1:0][10:0] max_tree_exp;
    logic [EXP_TREE_LVL:0][EXP_TREE_W-1:0][10:0] min_tree_exp;
    logic [EXP_TREE_LVL:0][EXP_TREE_W-1:0]       tree_vld;

    for (genvar k = 0; k < EXP_TREE_W; ++k) begin : g_tree_init
        if (k < LANES) begin : g_leaf_active
            assign max_tree_exp[0][k] = comb_exp_s11[k];
            assign min_tree_exp[0][k] = comb_exp_s11[k];
            assign tree_vld[0][k]     = comb_finite_nz[k];
        end else begin : g_leaf_pad
            assign max_tree_exp[0][k] = 11'sd0;
            assign min_tree_exp[0][k] = 11'sd0;
            assign tree_vld[0][k]     = 1'b0;
        end
    end

    for (genvar lvl = 0; lvl < EXP_TREE_LVL; ++lvl) begin : g_tree_lvl
        localparam int NODES = EXP_TREE_W >> (lvl + 1);
        for (genvar j = 0; j < NODES; ++j) begin : g_tree_node
            logic signed [10:0] left_max;
            logic signed [10:0] right_max;
            logic signed [10:0] left_min;
            logic signed [10:0] right_min;
            logic               left_v;
            logic               right_v;

            assign left_max  = $signed(max_tree_exp[lvl][2*j]);
            assign right_max = $signed(max_tree_exp[lvl][2*j+1]);
            assign left_min  = $signed(min_tree_exp[lvl][2*j]);
            assign right_min = $signed(min_tree_exp[lvl][2*j+1]);
            assign left_v    = tree_vld[lvl][2*j];
            assign right_v   = tree_vld[lvl][2*j+1];

            always_comb begin
                if (left_v && right_v) begin
                    max_tree_exp[lvl+1][j] = (left_max >= right_max) ? left_max : right_max;
                    min_tree_exp[lvl+1][j] = (left_min <= right_min) ? left_min : right_min;
                    tree_vld[lvl+1][j]     = 1'b1;
                end else if (left_v) begin
                    max_tree_exp[lvl+1][j] = left_max;
                    min_tree_exp[lvl+1][j] = left_min;
                    tree_vld[lvl+1][j]     = 1'b1;
                end else if (right_v) begin
                    max_tree_exp[lvl+1][j] = right_max;
                    min_tree_exp[lvl+1][j] = right_min;
                    tree_vld[lvl+1][j]     = 1'b1;
                end else begin
                    max_tree_exp[lvl+1][j] = 11'sd0;
                    min_tree_exp[lvl+1][j] = 11'sd0;
                    tree_vld[lvl+1][j]     = 1'b0;
                end
            end
        end
        for (genvar j = NODES; j < EXP_TREE_W; ++j) begin : g_tree_unused
            assign max_tree_exp[lvl+1][j] = 11'sd0;
            assign min_tree_exp[lvl+1][j] = 11'sd0;
            assign tree_vld[lvl+1][j]     = 1'b0;
        end
    end

    assign comb_max_finite_exp = tree_vld[EXP_TREE_LVL][0] ? $signed(max_tree_exp[EXP_TREE_LVL][0]) : 11'sd0;
    assign comb_min_finite_exp = tree_vld[EXP_TREE_LVL][0] ? $signed(min_tree_exp[EXP_TREE_LVL][0]) : 11'sd0;

    // -------------------------------------------------------------------------
    // Optional Registered Output Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic                                    valid_r;
        tcu_v2_fp_unpacked_t [LANES-1:0]         fp_r;
        logic [LANES-1:0][10:0]                  exp_s11_r;
        logic [LANES-1:0][31:0]                  fp32_equiv_r;
        logic signed [LANES-1:0][7:0]            int8_r;
        logic [LANES-1:0][7:0]                   int8_abs_r;
        logic [LANES-1:0]                        is_snan_r;
        logic [LANES-1:0]                        is_qnan_r;
        logic [LANES-1:0]                        nan_mask_r;
        logic [LANES-1:0]                        inf_pos_mask_r;
        logic [LANES-1:0]                        inf_neg_mask_r;
        logic [LANES-1:0]                        zero_mask_r;
        logic [LANES-1:0]                        neg_zero_mask_r;
        logic [LANES-1:0]                        subnorm_mask_r;
        logic [LANES-1:0]                        int_neg_mask_r;
        logic [LANES-1:0]                        int_min_mask_r;
        logic                                    any_nan_r;
        logic                                    any_snan_r;
        logic                                    any_inf_r;
        logic                                    all_zero_r;
        logic signed [10:0]                      max_finite_exp_r;
        logic signed [10:0]                      min_finite_exp_r;
        logic                                    has_finite_nz_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r          <= 1'b0;
                fp_r             <= '0;
                exp_s11_r        <= '0;
                fp32_equiv_r     <= '0;
                int8_r           <= '0;
                int8_abs_r       <= '0;
                is_snan_r        <= '0;
                is_qnan_r        <= '0;
                nan_mask_r       <= '0;
                inf_pos_mask_r   <= '0;
                inf_neg_mask_r   <= '0;
                zero_mask_r      <= '0;
                neg_zero_mask_r  <= '0;
                subnorm_mask_r   <= '0;
                int_neg_mask_r   <= '0;
                int_min_mask_r   <= '0;
                any_nan_r        <= 1'b0;
                any_snan_r       <= 1'b0;
                any_inf_r        <= 1'b0;
                all_zero_r       <= 1'b0;
                max_finite_exp_r <= 11'sd0;
                min_finite_exp_r <= 11'sd0;
                has_finite_nz_r  <= 1'b0;
            end else if (enable) begin
                valid_r          <= valid_in;
                fp_r             <= comb_fp;
                exp_s11_r        <= comb_exp_s11;
                fp32_equiv_r     <= comb_fp32_equiv;
                int8_r           <= comb_int8;
                int8_abs_r       <= comb_int8_abs;
                is_snan_r        <= comb_is_snan;
                is_qnan_r        <= comb_is_qnan;
                nan_mask_r       <= comb_nan_mask;
                inf_pos_mask_r   <= comb_inf_pos_mask;
                inf_neg_mask_r   <= comb_inf_neg_mask;
                zero_mask_r      <= comb_zero_mask;
                neg_zero_mask_r  <= comb_neg_zero_mask;
                subnorm_mask_r   <= comb_subnorm_mask;
                int_neg_mask_r   <= comb_int_neg_mask;
                int_min_mask_r   <= comb_int_min_mask;
                any_nan_r        <= comb_any_nan;
                any_snan_r       <= comb_any_snan;
                any_inf_r        <= comb_any_inf;
                all_zero_r       <= comb_all_zero;
                max_finite_exp_r <= comb_max_finite_exp;
                min_finite_exp_r <= comb_min_finite_exp;
                has_finite_nz_r  <= comb_has_finite_nz;
            end
        end

        assign valid_out              = valid_r;
        assign fp_out                 = fp_r;
        assign exp_s11_out            = exp_s11_r;
        assign fp32_equiv_out         = fp32_equiv_r;
        assign int8_out               = int8_r;
        assign int8_abs_out           = int8_abs_r;
        assign is_snan_out            = is_snan_r;
        assign is_qnan_out            = is_qnan_r;
        assign nan_mask_out           = nan_mask_r;
        assign inf_pos_mask_out       = inf_pos_mask_r;
        assign inf_neg_mask_out       = inf_neg_mask_r;
        assign zero_mask_out          = zero_mask_r;
        assign neg_zero_mask_out      = neg_zero_mask_r;
        assign subnormal_mask_out     = subnorm_mask_r;
        assign int_neg_mask_out       = int_neg_mask_r;
        assign int_min_mask_out       = int_min_mask_r;
        assign any_nan_out            = any_nan_r;
        assign any_snan_out           = any_snan_r;
        assign any_inf_out            = any_inf_r;
        assign all_zero_out           = all_zero_r;
        assign max_finite_exp_out     = max_finite_exp_r;
        assign min_finite_exp_out     = min_finite_exp_r;
        assign has_finite_nonzero_out = has_finite_nz_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out              = valid_in;
        assign fp_out                 = comb_fp;
        assign exp_s11_out            = comb_exp_s11;
        assign fp32_equiv_out         = comb_fp32_equiv;
        assign int8_out               = comb_int8;
        assign int8_abs_out           = comb_int8_abs;
        assign is_snan_out            = comb_is_snan;
        assign is_qnan_out            = comb_is_qnan;
        assign nan_mask_out           = comb_nan_mask;
        assign inf_pos_mask_out       = comb_inf_pos_mask;
        assign inf_neg_mask_out       = comb_inf_neg_mask;
        assign zero_mask_out          = comb_zero_mask;
        assign neg_zero_mask_out      = comb_neg_zero_mask;
        assign subnormal_mask_out     = comb_subnorm_mask;
        assign int_neg_mask_out       = comb_int_neg_mask;
        assign int_min_mask_out       = comb_int_min_mask;
        assign any_nan_out            = comb_any_nan;
        assign any_snan_out           = comb_any_snan;
        assign any_inf_out            = comb_any_inf;
        assign all_zero_out           = comb_all_zero;
        assign max_finite_exp_out     = comb_max_finite_exp;
        assign min_finite_exp_out     = comb_min_finite_exp;
        assign has_finite_nonzero_out = comb_has_finite_nz;
    end

endmodule
