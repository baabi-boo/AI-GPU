// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp8_e4m3_unpack #(
    parameter int   LANES         = 8,
    parameter int   LANE_STRIDE_W = 32,
    parameter logic OUT_REG       = 1'b0
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            enable,
    input  logic                                            valid_in,
    input  logic [LANES*LANE_STRIDE_W-1:0]                  data_raw,
    output logic                                            valid_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_unpacked_t [LANES-1:0]  fp_out,
    output logic [LANES-1:0][10:0]                          exp_s11_out,
    output logic [LANES-1:0][31:0]                          fp32_equiv_out,
    output logic [LANES-1:0]                                is_snan_out,
    output logic [LANES-1:0]                                nan_mask_out,
    output logic [LANES-1:0]                                zero_mask_out,
    output logic [LANES-1:0]                                neg_zero_mask_out,
    output logic [LANES-1:0]                                subnormal_mask_out,
    output logic                                            any_nan_out,
    output logic                                            any_snan_out,
    output logic                                            all_zero_out,
    output logic signed [10:0]                              max_finite_exp_out,
    output logic signed [10:0]                              min_finite_exp_out,
    output logic                                            has_finite_nonzero_out,
    output logic [3:0]                                      nan_count_out,
    output logic [3:0]                                      zero_count_out,
    output logic [3:0]                                      subnormal_count_out
);
    import VX_tcu_v2_pkg::*;

    localparam int EXP_BIAS     = 7;
    localparam int SUBNORM_EXP  = 1 - EXP_BIAS;
    localparam int EXP_TREE_LVL = (LANES <= 1) ? 1 : $clog2(LANES);
    localparam int EXP_TREE_W   = 1 << EXP_TREE_LVL;

    // -------------------------------------------------------------------------
    // Per-Lane Combinational OFG FP8 E4M3FN Decode, Subnormal Normalization,
    // and Exact FP32 Upcast Generation
    // -------------------------------------------------------------------------
    tcu_v2_fp_unpacked_t [LANES-1:0] comb_fp;
    logic [LANES-1:0][10:0]          comb_exp_s11;
    logic [LANES-1:0][31:0]          comb_fp32_equiv;
    logic [LANES-1:0]                comb_is_snan;
    logic [LANES-1:0]                comb_nan_mask;
    logic [LANES-1:0]                comb_zero_mask;
    logic [LANES-1:0]                comb_neg_zero_mask;
    logic [LANES-1:0]                comb_subnorm_mask;
    logic [LANES-1:0]                comb_finite_nz;

    for (genvar i = 0; i < LANES; ++i) begin : g_e4m3_lanes
        logic [7:0]         raw_byte;
        logic               lane_sign;
        logic [3:0]         lane_exp_raw;
        logic [2:0]         lane_man_raw;
        logic               exp_is_zero;
        logic               exp_is_max;
        logic               man_is_zero;
        logic               man_is_all_ones;
        logic               is_zero_val;
        logic               is_subnorm_val;
        logic               is_nan_val;
        logic               is_normal_val;
        logic [1:0]         sub_lzc;
        logic [3:0]         norm_sig4;
        logic [3:0]         subnorm_shift_sig;
        logic signed [10:0] exp_s11_val;
        logic [7:0]         fp32_exp_biased;
        logic [22:0]        fp32_man_field;
        logic [31:0]        fp32_word;

        assign raw_byte     = data_raw[i*LANE_STRIDE_W +: 8];
        assign lane_sign    = raw_byte[7];
        assign lane_exp_raw = raw_byte[6:3];
        assign lane_man_raw = raw_byte[2:0];

        assign exp_is_zero     = (lane_exp_raw == 4'h0);
        assign exp_is_max      = (lane_exp_raw == 4'hF);
        assign man_is_zero     = (lane_man_raw == 3'h0);
        assign man_is_all_ones = (lane_man_raw == 3'h7);

        // OFG E4M3FN has no Inf; NaN exists solely at 0x7F and 0xFF.
        assign is_zero_val    = exp_is_zero && man_is_zero;
        assign is_subnorm_val = exp_is_zero && !man_is_zero;
        assign is_nan_val     = exp_is_max && man_is_all_ones;
        assign is_normal_val  = !is_zero_val && !is_subnorm_val && !is_nan_val;

        always_comb begin
            sub_lzc           = 2'd0;
            subnorm_shift_sig = 4'd0;
            if (lane_man_raw[2]) begin
                sub_lzc           = 2'd0;
                subnorm_shift_sig = {lane_man_raw, 1'b0};
            end else if (lane_man_raw[1]) begin
                sub_lzc           = 2'd1;
                subnorm_shift_sig = {lane_man_raw[1:0], 2'b00};
            end else if (lane_man_raw[0]) begin
                sub_lzc           = 2'd2;
                subnorm_shift_sig = {lane_man_raw[0], 3'b000};
            end else begin
                sub_lzc           = 2'd3;
                subnorm_shift_sig = 4'd0;
            end
        end

        always_comb begin
            norm_sig4   = 4'd0;
            exp_s11_val = 11'sd0;
            if (is_nan_val) begin
                norm_sig4   = {1'b0, lane_man_raw};
                exp_s11_val = 11'sd0;
            end else if (is_zero_val) begin
                norm_sig4   = 4'd0;
                exp_s11_val = 11'sd0;
            end else if (is_subnorm_val) begin
                norm_sig4   = subnorm_shift_sig;
                exp_s11_val = $signed(11'(SUBNORM_EXP)) - $signed({9'd0, sub_lzc}) - 11'sd1;
            end else begin
                norm_sig4   = {1'b1, lane_man_raw};
                exp_s11_val = $signed({7'd0, lane_exp_raw}) - $signed(11'(EXP_BIAS));
            end
        end

        always_comb begin
            fp32_exp_biased = 8'd0;
            fp32_man_field  = 23'd0;
            if (is_nan_val) begin
                fp32_word = {lane_sign, 8'hFF, 1'b1, 22'd0};
            end else if (is_zero_val) begin
                fp32_word = {lane_sign, 31'd0};
            end else begin
                fp32_exp_biased = 8'(exp_s11_val + 11'sd127);
                fp32_man_field  = {norm_sig4[2:0], 20'd0};
                fp32_word       = {lane_sign, fp32_exp_biased, fp32_man_field};
            end
        end

        always_comb begin
            comb_fp[i].sign         = lane_sign;
            comb_fp[i].exp          = exp_s11_val[TCU_V2_FP_EXP_W-1:0];
            comb_fp[i].sig          = {norm_sig4, 20'd0};
            comb_fp[i].is_zero      = is_zero_val;
            comb_fp[i].is_inf       = 1'b0;
            comb_fp[i].is_nan       = is_nan_val;
            comb_fp[i].is_subnormal = is_subnorm_val;
        end

        assign comb_exp_s11[i]       = exp_s11_val;
        assign comb_fp32_equiv[i]    = fp32_word;
        assign comb_is_snan[i]       = 1'b0;
        assign comb_nan_mask[i]      = is_nan_val;
        assign comb_zero_mask[i]     = is_zero_val;
        assign comb_neg_zero_mask[i] = is_zero_val && lane_sign;
        assign comb_subnorm_mask[i]  = is_subnorm_val;
        assign comb_finite_nz[i]     = is_normal_val || is_subnorm_val;

        if (LANE_STRIDE_W > 8) begin : g_unused_upper_bits
            `UNUSED_VAR (data_raw[i*LANE_STRIDE_W + 8 +: (LANE_STRIDE_W - 8)])
        end
    end

    // -------------------------------------------------------------------------
    // Summary Flags, Diagnostic Popcounts, and Packed Max/Min Exponent Trees
    // -------------------------------------------------------------------------
    logic               comb_any_nan;
    logic               comb_any_snan;
    logic               comb_all_zero;
    logic               comb_has_finite_nz;
    logic signed [10:0] comb_max_finite_exp;
    logic signed [10:0] comb_min_finite_exp;
    logic [3:0]         comb_nan_count;
    logic [3:0]         comb_zero_count;
    logic [3:0]         comb_subnorm_count;
    logic [LANES-1:0]   comb_max_finite_mask;
    logic               comb_sign_xor;

    assign comb_any_nan       = |comb_nan_mask;
    assign comb_any_snan      = |comb_is_snan;
    assign comb_all_zero      = &comb_zero_mask;
    assign comb_has_finite_nz = |comb_finite_nz;

    always_comb begin
        comb_nan_count       = 4'd0;
        comb_zero_count      = 4'd0;
        comb_subnorm_count   = 4'd0;
        comb_max_finite_mask = {LANES{1'b0}};
        comb_sign_xor        = 1'b0;
        for (int p = 0; p < LANES; ++p) begin
            comb_nan_count     = comb_nan_count     + {3'd0, comb_nan_mask[p]};
            comb_zero_count    = comb_zero_count    + {3'd0, comb_zero_mask[p]};
            comb_subnorm_count = comb_subnorm_count + {3'd0, comb_subnorm_mask[p]};
            comb_max_finite_mask[p] = (data_raw[p*LANE_STRIDE_W +: 7] == 7'h7E);
            comb_sign_xor      = comb_sign_xor ^ comb_fp[p].sign;
        end
    end

    `UNUSED_VAR (comb_max_finite_mask)
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
        logic [LANES-1:0]                        nan_mask_r;
        logic [LANES-1:0]                        zero_mask_r;
        logic [LANES-1:0]                        neg_zero_mask_r;
        logic [LANES-1:0]                        subnorm_mask_r;
        logic                                    any_nan_r;
        logic                                    any_snan_r;
        logic                                    all_zero_r;
        logic signed [10:0]                      max_finite_exp_r;
        logic signed [10:0]                      min_finite_exp_r;
        logic                                    has_finite_nz_r;
        logic [3:0]                              nan_count_r;
        logic [3:0]                              zero_count_r;
        logic [3:0]                              subnorm_count_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r          <= 1'b0;
                fp_r             <= '0;
                exp_s11_r        <= '0;
                fp32_equiv_r     <= '0;
                is_snan_r        <= '0;
                nan_mask_r       <= '0;
                zero_mask_r      <= '0;
                neg_zero_mask_r  <= '0;
                subnorm_mask_r   <= '0;
                any_nan_r        <= 1'b0;
                any_snan_r       <= 1'b0;
                all_zero_r       <= 1'b0;
                max_finite_exp_r <= 11'sd0;
                min_finite_exp_r <= 11'sd0;
                has_finite_nz_r  <= 1'b0;
                nan_count_r      <= 4'd0;
                zero_count_r     <= 4'd0;
                subnorm_count_r  <= 4'd0;
            end else if (enable) begin
                valid_r          <= valid_in;
                fp_r             <= comb_fp;
                exp_s11_r        <= comb_exp_s11;
                fp32_equiv_r     <= comb_fp32_equiv;
                is_snan_r        <= comb_is_snan;
                nan_mask_r       <= comb_nan_mask;
                zero_mask_r      <= comb_zero_mask;
                neg_zero_mask_r  <= comb_neg_zero_mask;
                subnorm_mask_r   <= comb_subnorm_mask;
                any_nan_r        <= comb_any_nan;
                any_snan_r       <= comb_any_snan;
                all_zero_r       <= comb_all_zero;
                max_finite_exp_r <= comb_max_finite_exp;
                min_finite_exp_r <= comb_min_finite_exp;
                has_finite_nz_r  <= comb_has_finite_nz;
                nan_count_r      <= comb_nan_count;
                zero_count_r     <= comb_zero_count;
                subnorm_count_r  <= comb_subnorm_count;
            end
        end

        assign valid_out              = valid_r;
        assign fp_out                 = fp_r;
        assign exp_s11_out            = exp_s11_r;
        assign fp32_equiv_out         = fp32_equiv_r;
        assign is_snan_out            = is_snan_r;
        assign nan_mask_out           = nan_mask_r;
        assign zero_mask_out          = zero_mask_r;
        assign neg_zero_mask_out      = neg_zero_mask_r;
        assign subnormal_mask_out     = subnorm_mask_r;
        assign any_nan_out            = any_nan_r;
        assign any_snan_out           = any_snan_r;
        assign all_zero_out           = all_zero_r;
        assign max_finite_exp_out     = max_finite_exp_r;
        assign min_finite_exp_out     = min_finite_exp_r;
        assign has_finite_nonzero_out = has_finite_nz_r;
        assign nan_count_out          = nan_count_r;
        assign zero_count_out         = zero_count_r;
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
        assign nan_mask_out           = comb_nan_mask;
        assign zero_mask_out          = comb_zero_mask;
        assign neg_zero_mask_out      = comb_neg_zero_mask;
        assign subnormal_mask_out     = comb_subnorm_mask;
        assign any_nan_out            = comb_any_nan;
        assign any_snan_out           = comb_any_snan;
        assign all_zero_out           = comb_all_zero;
        assign max_finite_exp_out     = comb_max_finite_exp;
        assign min_finite_exp_out     = comb_min_finite_exp;
        assign has_finite_nonzero_out = comb_has_finite_nz;
        assign nan_count_out          = comb_nan_count;
        assign zero_count_out         = comb_zero_count;
        assign subnormal_count_out    = comb_subnorm_count;
    end

endmodule
