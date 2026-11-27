// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_bf16_fp16_unpack #(
    parameter int   LANES         = 8,
    parameter int   LANE_STRIDE_W = 32,
    parameter logic OUT_REG       = 1'b0
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            enable,
    input  logic                                            valid_in,
    input  logic                                            is_bf16,
    input  logic [LANES*LANE_STRIDE_W-1:0]                  data_raw,
    output logic                                            valid_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_unpacked_t [LANES-1:0]  fp_out,
    output logic [LANES-1:0][10:0]                          exp_s11_out,
    output logic [LANES-1:0][31:0]                          fp32_equiv_out,
    output logic [LANES-1:0]                                is_snan_out,
    output logic [LANES-1:0]                                is_qnan_out,
    output logic [LANES-1:0]                                nan_mask_out,
    output logic [LANES-1:0]                                inf_pos_mask_out,
    output logic [LANES-1:0]                                inf_neg_mask_out,
    output logic [LANES-1:0]                                zero_mask_out,
    output logic [LANES-1:0]                                neg_zero_mask_out,
    output logic [LANES-1:0]                                subnormal_mask_out,
    output logic                                            any_nan_out,
    output logic                                            any_snan_out,
    output logic                                            any_inf_out,
    output logic                                            all_zero_out,
    output logic signed [10:0]                              max_finite_exp_out,
    output logic signed [10:0]                              min_finite_exp_out,
    output logic                                            has_finite_nonzero_out,
    output logic [3:0]                                      subnormal_count_out
);
    import VX_tcu_v2_pkg::*;

    localparam int BF16_BIAS    = 127;
    localparam int FP16_BIAS    = 15;
    localparam int EXP_TREE_LVL = (LANES <= 1) ? 1 : $clog2(LANES);
    localparam int EXP_TREE_W   = 1 << EXP_TREE_LVL;

    // -------------------------------------------------------------------------
    // Dual-Mode BF16 (E8M7) / FP16 (E5M10) Lane Unpack, Subnormal Normalization,
    // and Canonical FP32 Equivalent Encoding
    // -------------------------------------------------------------------------
    tcu_v2_fp_unpacked_t [LANES-1:0] comb_fp;
    logic [LANES-1:0][10:0]          comb_exp_s11;
    logic [LANES-1:0][31:0]          comb_fp32_equiv;
    logic [LANES-1:0]                comb_is_snan;
    logic [LANES-1:0]                comb_is_qnan;
    logic [LANES-1:0]                comb_nan_mask;
    logic [LANES-1:0]                comb_inf_pos_mask;
    logic [LANES-1:0]                comb_inf_neg_mask;
    logic [LANES-1:0]                comb_zero_mask;
    logic [LANES-1:0]                comb_neg_zero_mask;
    logic [LANES-1:0]                comb_subnorm_mask;
    logic [LANES-1:0]                comb_finite_nz;

    for (genvar i = 0; i < LANES; ++i) begin : g_bfloat_fp16_lanes
        logic [15:0]        raw_half;
        logic               lane_sign;
        logic [7:0]         bf16_exp_raw;
        logic [6:0]         bf16_man_raw;
        logic [4:0]         fp16_exp_raw;
        logic [9:0]         fp16_man_raw;

        logic               bf16_exp_zero;
        logic               bf16_exp_max;
        logic               bf16_man_zero;
        logic               fp16_exp_zero;
        logic               fp16_exp_max;
        logic               fp16_man_zero;

        logic               is_zero_val;
        logic               is_subnorm_val;
        logic               is_inf_val;
        logic               is_nan_val;
        logic               is_snan_val;
        logic               is_qnan_val;
        logic               is_normal_val;

        logic [9:0]         sub_man_vec;
        logic [3:0]         sub_lzc;
        logic [10:0]        sub_shifted_sig11;
        logic [10:0]        norm_sig11;
        logic signed [10:0] exp_s11_val;
        logic [7:0]         fp32_exp_biased;
        logic [31:0]        fp32_word;

        assign raw_half     = data_raw[i*LANE_STRIDE_W +: 16];
        assign lane_sign    = raw_half[15];
        assign bf16_exp_raw = raw_half[14:7];
        assign bf16_man_raw = raw_half[6:0];
        assign fp16_exp_raw = raw_half[14:10];
        assign fp16_man_raw = raw_half[9:0];

        assign bf16_exp_zero = (bf16_exp_raw == 8'h00);
        assign bf16_exp_max  = (bf16_exp_raw == 8'hFF);
        assign bf16_man_zero = (bf16_man_raw == 7'h00);

        assign fp16_exp_zero = (fp16_exp_raw == 5'h00);
        assign fp16_exp_max  = (fp16_exp_raw == 5'h1F);
        assign fp16_man_zero = (fp16_man_raw == 10'h000);

        always_comb begin
            if (is_bf16) begin
                is_zero_val    = bf16_exp_zero && bf16_man_zero;
                is_subnorm_val = bf16_exp_zero && !bf16_man_zero;
                is_inf_val     = bf16_exp_max  && bf16_man_zero;
                is_nan_val     = bf16_exp_max  && !bf16_man_zero;
                is_snan_val    = is_nan_val    && !bf16_man_raw[6];
                is_qnan_val    = is_nan_val    && bf16_man_raw[6];
                is_normal_val  = !bf16_exp_zero && !bf16_exp_max;
            end else begin
                is_zero_val    = fp16_exp_zero && fp16_man_zero;
                is_subnorm_val = fp16_exp_zero && !fp16_man_zero;
                is_inf_val     = fp16_exp_max  && fp16_man_zero;
                is_nan_val     = fp16_exp_max  && !fp16_man_zero;
                is_snan_val    = is_nan_val    && !fp16_man_raw[9];
                is_qnan_val    = is_nan_val    && fp16_man_raw[9];
                is_normal_val  = !fp16_exp_zero && !fp16_exp_max;
            end
        end

        // Unified 10-bit priority encoder for subnormal normalization.
        assign sub_man_vec = is_bf16 ? {bf16_man_raw, 3'b000} : fp16_man_raw;

        always_comb begin
            sub_lzc           = 4'd0;
            sub_shifted_sig11 = 11'd0;
            if (sub_man_vec[9]) begin
                sub_lzc           = 4'd0;
                sub_shifted_sig11 = {sub_man_vec, 1'b0};
            end else if (sub_man_vec[8]) begin
                sub_lzc           = 4'd1;
                sub_shifted_sig11 = {sub_man_vec[8:0], 2'b00};
            end else if (sub_man_vec[7]) begin
                sub_lzc           = 4'd2;
                sub_shifted_sig11 = {sub_man_vec[7:0], 3'b000};
            end else if (sub_man_vec[6]) begin
                sub_lzc           = 4'd3;
                sub_shifted_sig11 = {sub_man_vec[6:0], 4'b0000};
            end else if (sub_man_vec[5]) begin
                sub_lzc           = 4'd4;
                sub_shifted_sig11 = {sub_man_vec[5:0], 5'b00000};
            end else if (sub_man_vec[4]) begin
                sub_lzc           = 4'd5;
                sub_shifted_sig11 = {sub_man_vec[4:0], 6'b000000};
            end else if (sub_man_vec[3]) begin
                sub_lzc           = 4'd6;
                sub_shifted_sig11 = {sub_man_vec[3:0], 7'b0000000};
            end else if (sub_man_vec[2]) begin
                sub_lzc           = 4'd7;
                sub_shifted_sig11 = {sub_man_vec[2:0], 8'b00000000};
            end else if (sub_man_vec[1]) begin
                sub_lzc           = 4'd8;
                sub_shifted_sig11 = {sub_man_vec[1:0], 9'b000000000};
            end else if (sub_man_vec[0]) begin
                sub_lzc           = 4'd9;
                sub_shifted_sig11 = {sub_man_vec[0], 10'b0000000000};
            end else begin
                sub_lzc           = 4'd10;
                sub_shifted_sig11 = 11'd0;
            end
        end

        always_comb begin
            norm_sig11  = 11'd0;
            exp_s11_val = 11'sd0;
            if (is_nan_val || is_inf_val) begin
                norm_sig11  = is_bf16 ? {1'b0, bf16_man_raw, 3'b000} : {1'b0, fp16_man_raw};
                exp_s11_val = 11'sd0;
            end else if (is_zero_val) begin
                norm_sig11  = 11'd0;
                exp_s11_val = 11'sd0;
            end else if (is_subnorm_val) begin
                norm_sig11  = sub_shifted_sig11;
                if (is_bf16) begin
                    exp_s11_val = $signed(11'(1 - BF16_BIAS)) - $signed({7'd0, sub_lzc}) - 11'sd1;
                end else begin
                    exp_s11_val = $signed(11'(1 - FP16_BIAS)) - $signed({7'd0, sub_lzc}) - 11'sd1;
                end
            end else begin
                if (is_bf16) begin
                    norm_sig11  = {1'b1, bf16_man_raw, 3'b000};
                    exp_s11_val = $signed({3'd0, bf16_exp_raw}) - $signed(11'(BF16_BIAS));
                end else begin
                    norm_sig11  = {1'b1, fp16_man_raw};
                    exp_s11_val = $signed({6'd0, fp16_exp_raw}) - $signed(11'(FP16_BIAS));
                end
            end
        end

        // Exact lossless FP32 conversion (note BF16 subnormals stay FP32 subnormals).
        always_comb begin
            fp32_exp_biased = 8'd0;
            if (is_nan_val) begin
                fp32_word = {lane_sign, 8'hFF, 1'b1, norm_sig11[8:0], 13'd0};
            end else if (is_inf_val) begin
                fp32_word = {lane_sign, 8'hFF, 23'd0};
            end else if (is_zero_val) begin
                fp32_word = {lane_sign, 31'd0};
            end else if (is_bf16 && is_subnorm_val) begin
                fp32_word = {lane_sign, 8'h00, bf16_man_raw, 16'd0};
            end else begin
                fp32_exp_biased = 8'(exp_s11_val + 11'sd127);
                fp32_word       = {lane_sign, fp32_exp_biased, norm_sig11[9:0], 13'd0};
            end
        end

        always_comb begin
            comb_fp[i].sign         = lane_sign;
            comb_fp[i].exp          = exp_s11_val[TCU_V2_FP_EXP_W-1:0];
            comb_fp[i].sig          = {norm_sig11, 13'd0};
            comb_fp[i].is_zero      = is_zero_val;
            comb_fp[i].is_inf       = is_inf_val;
            comb_fp[i].is_nan       = is_nan_val;
            comb_fp[i].is_subnormal = is_subnorm_val;
        end

        assign comb_exp_s11[i]       = exp_s11_val;
        assign comb_fp32_equiv[i]    = fp32_word;
        assign comb_is_snan[i]       = is_snan_val;
        assign comb_is_qnan[i]       = is_qnan_val;
        assign comb_nan_mask[i]      = is_nan_val;
        assign comb_inf_pos_mask[i]  = is_inf_val && !lane_sign;
        assign comb_inf_neg_mask[i]  = is_inf_val && lane_sign;
        assign comb_zero_mask[i]     = is_zero_val;
        assign comb_neg_zero_mask[i] = is_zero_val && lane_sign;
        assign comb_subnorm_mask[i]  = is_subnorm_val;
        assign comb_finite_nz[i]     = is_normal_val || is_subnorm_val;

        if (LANE_STRIDE_W > 16) begin : g_unused_upper_bits
            `UNUSED_VAR (data_raw[i*LANE_STRIDE_W + 16 +: (LANE_STRIDE_W - 16)])
        end
    end

    // -------------------------------------------------------------------------
    // Summary Flags, Subnormal Popcount, and Packed Max/Min Exponent Trees
    // -------------------------------------------------------------------------
    logic               comb_any_nan;
    logic               comb_any_snan;
    logic               comb_any_inf;
    logic               comb_all_zero;
    logic               comb_has_finite_nz;
    logic signed [10:0] comb_max_finite_exp;
    logic signed [10:0] comb_min_finite_exp;
    logic [3:0]         comb_subnorm_count;
    logic [3:0]         comb_nan_count;
    logic [3:0]         comb_inf_count;
    logic [3:0]         comb_zero_count;
    logic               comb_sign_xor;

    assign comb_any_nan       = |comb_nan_mask;
    assign comb_any_snan      = |comb_is_snan;
    assign comb_any_inf       = (|comb_inf_pos_mask) || (|comb_inf_neg_mask);
    assign comb_all_zero      = &comb_zero_mask;
    assign comb_has_finite_nz = |comb_finite_nz;

    always_comb begin
        comb_subnorm_count = 4'd0;
        comb_nan_count     = 4'd0;
        comb_inf_count     = 4'd0;
        comb_zero_count    = 4'd0;
        comb_sign_xor      = 1'b0;
        for (int p = 0; p < LANES; ++p) begin
            comb_subnorm_count = comb_subnorm_count + {3'd0, comb_subnorm_mask[p]};
            comb_nan_count     = comb_nan_count     + {3'd0, comb_nan_mask[p]};
            comb_inf_count     = comb_inf_count     + {3'd0, comb_inf_pos_mask[p] | comb_inf_neg_mask[p]};
            comb_zero_count    = comb_zero_count    + {3'd0, comb_zero_mask[p]};
            comb_sign_xor      = comb_sign_xor      ^ comb_fp[p].sign;
        end
    end

    `UNUSED_VAR (comb_nan_count)
    `UNUSED_VAR (comb_inf_count)
    `UNUSED_VAR (comb_zero_count)
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
        logic [LANES-1:0]                        is_snan_r;
        logic [LANES-1:0]                        is_qnan_r;
        logic [LANES-1:0]                        nan_mask_r;
        logic [LANES-1:0]                        inf_pos_mask_r;
        logic [LANES-1:0]                        inf_neg_mask_r;
        logic [LANES-1:0]                        zero_mask_r;
        logic [LANES-1:0]                        neg_zero_mask_r;
        logic [LANES-1:0]                        subnorm_mask_r;
        logic                                    any_nan_r;
        logic                                    any_snan_r;
        logic                                    any_inf_r;
        logic                                    all_zero_r;
        logic signed [10:0]                      max_finite_exp_r;
        logic signed [10:0]                      min_finite_exp_r;
        logic                                    has_finite_nz_r;
        logic [3:0]                              subnorm_count_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r          <= 1'b0;
                fp_r             <= '0;
                exp_s11_r        <= '0;
                fp32_equiv_r     <= '0;
                is_snan_r        <= '0;
                is_qnan_r        <= '0;
                nan_mask_r       <= '0;
                inf_pos_mask_r   <= '0;
                inf_neg_mask_r   <= '0;
                zero_mask_r      <= '0;
                neg_zero_mask_r  <= '0;
                subnorm_mask_r   <= '0;
                any_nan_r        <= 1'b0;
                any_snan_r       <= 1'b0;
                any_inf_r        <= 1'b0;
                all_zero_r       <= 1'b0;
                max_finite_exp_r <= 11'sd0;
                min_finite_exp_r <= 11'sd0;
                has_finite_nz_r  <= 1'b0;
                subnorm_count_r  <= 4'd0;
            end else if (enable) begin
                valid_r          <= valid_in;
                fp_r             <= comb_fp;
                exp_s11_r        <= comb_exp_s11;
                fp32_equiv_r     <= comb_fp32_equiv;
                is_snan_r        <= comb_is_snan;
                is_qnan_r        <= comb_is_qnan;
                nan_mask_r       <= comb_nan_mask;
                inf_pos_mask_r   <= comb_inf_pos_mask;
                inf_neg_mask_r   <= comb_inf_neg_mask;
                zero_mask_r      <= comb_zero_mask;
                neg_zero_mask_r  <= comb_neg_zero_mask;
                subnorm_mask_r   <= comb_subnorm_mask;
                any_nan_r        <= comb_any_nan;
                any_snan_r       <= comb_any_snan;
                any_inf_r        <= comb_any_inf;
                all_zero_r       <= comb_all_zero;
                max_finite_exp_r <= comb_max_finite_exp;
                min_finite_exp_r <= comb_min_finite_exp;
                has_finite_nz_r  <= comb_has_finite_nz;
                subnorm_count_r  <= comb_subnorm_count;
            end
        end

        assign valid_out              = valid_r;
        assign fp_out                 = fp_r;
        assign exp_s11_out            = exp_s11_r;
        assign fp32_equiv_out         = fp32_equiv_r;
        assign is_snan_out            = is_snan_r;
        assign is_qnan_out            = is_qnan_r;
        assign nan_mask_out           = nan_mask_r;
        assign inf_pos_mask_out       = inf_pos_mask_r;
        assign inf_neg_mask_out       = inf_neg_mask_r;
        assign zero_mask_out          = zero_mask_r;
        assign neg_zero_mask_out      = neg_zero_mask_r;
        assign subnormal_mask_out     = subnorm_mask_r;
        assign any_nan_out            = any_nan_r;
        assign any_snan_out           = any_snan_r;
        assign any_inf_out            = any_inf_r;
        assign all_zero_out           = all_zero_r;
        assign max_finite_exp_out     = max_finite_exp_r;
        assign min_finite_exp_out     = min_finite_exp_r;
        assign has_finite_nonzero_out = has_finite_nz_r;
        assign subnormal_count_out    = subnorm_count_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out              = valid_in;
        assign fp_out                 = comb_fp;
        assign exp_s11_out            = comb_exp_s11;
        assign fp32_equiv_out         = comb_fp32_equiv;
        assign is_snan_out            = comb_is_snan;
        assign is_qnan_out            = comb_is_qnan;
        assign nan_mask_out           = comb_nan_mask;
        assign inf_pos_mask_out       = comb_inf_pos_mask;
        assign inf_neg_mask_out       = comb_inf_neg_mask;
        assign zero_mask_out          = comb_zero_mask;
        assign neg_zero_mask_out      = comb_neg_zero_mask;
        assign subnormal_mask_out     = comb_subnorm_mask;
        assign any_nan_out            = comb_any_nan;
        assign any_snan_out           = comb_any_snan;
        assign any_inf_out            = comb_any_inf;
        assign all_zero_out           = comb_all_zero;
        assign max_finite_exp_out     = comb_max_finite_exp;
        assign min_finite_exp_out     = comb_min_finite_exp;
        assign has_finite_nonzero_out = comb_has_finite_nz;
        assign subnormal_count_out    = comb_subnorm_count;
    end

endmodule
