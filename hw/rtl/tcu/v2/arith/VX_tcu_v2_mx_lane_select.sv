// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_lane_select import VX_tcu_v2_pkg::*; #(
    parameter int LANES = TCU_V2_MAX_LANES,
    parameter int SIG_W = TCU_V2_FP_SIG_W,
    parameter int EXP_W = TCU_V2_FP_EXP_W
) (
    input  tcu_v2_fmt_e                              fmt_a,
    input  tcu_v2_fmt_e                              fmt_b,
    input  logic [LANES-1:0]                         lane_enable_mask,
    // FP4 lane product inputs
    input  logic [LANES-1:0]                         fp4_sign_in,
    input  logic signed [LANES-1:0][EXP_W-1:0]       fp4_exp_in,
    input  logic [LANES-1:0][3:0]                    fp4_mant_u1p3_in,
    input  logic [LANES-1:0]                         fp4_zero_in,
    input  logic [LANES-1:0]                         fp4_neg_zero_in,
    // FP6 / mixed lane product inputs
    input  logic [LANES-1:0]                         fp6_sign_in,
    input  logic signed [LANES-1:0][EXP_W-1:0]       fp6_exp_in,
    input  logic [LANES-1:0][7:0]                    fp6_mant_u1p7_in,
    input  logic [LANES-1:0]                         fp6_zero_in,
    input  logic [LANES-1:0]                         fp6_neg_zero_in,
    // Combined block microscale inputs
    input  logic signed [EXP_W-1:0]                  scale_comb_exp_in,
    input  logic [7:0]                               scale_comb_mant_u1p7_in,
    input  logic                                     scale_comb_is_zero_in,
    input  logic                                     scale_comb_is_nan_in,
    input  logic                                     scale_comb_exp_ovf_in,
    input  logic                                     scale_comb_exp_unf_in,
    // Scaled lane product outputs (normalized u1.23 significand + signed unbiased exp)
    output logic [LANES-1:0]                         lane_sign_out,
    output logic signed [LANES-1:0][EXP_W-1:0]       lane_exp_out,
    output logic [LANES-1:0][SIG_W-1:0]              lane_sig_u1p23_out,
    output logic [LANES-1:0]                         lane_is_zero_out,
    output logic [LANES-1:0]                         lane_is_neg_zero_out,
    output logic [LANES-1:0]                         lane_is_nan_out,
    output logic [LANES-1:0]                         lane_is_inf_out,
    output logic [LANES-1:0]                         lane_underflow_out,
    output logic [LANES-1:0]                         lane_overflow_out,
    output logic [LANES-1:0]                         lane_subnormal_fp32_out,
    output logic [LANES-1:0][31:0]                   lane_fp32_equiv_out,
    output logic [LANES-1:0]                         lane_scaled_exact_int_out,
    output logic [LANES-1:0][15:0]                   lane_scaled_raw_u2p14_out,
    output logic                                     any_lane_nan_out,
    output logic                                     any_lane_inf_out,
    output logic                                     any_lane_uf_out,
    output logic                                     any_lane_of_out,
    output logic                                     all_lanes_zero_out,
    output logic                                     all_lanes_neg_zero_out,
    output logic                                     use_fp6_path_out,
    output logic                                     illegal_fmt_combo_out,
    output logic [$clog2(LANES+1)-1:0]               active_scaled_lanes_out,
    output logic signed [EXP_W-1:0]                  min_scaled_exp_out,
    output logic signed [EXP_W-1:0]                  max_scaled_exp_out,
    output logic [3:0]                               pos_scaled_cnt_out,
    output logic [3:0]                               neg_scaled_cnt_out,
    output logic signed [EXP_W-1:0]                  scaled_exp_span_out
);

    localparam int FP32_EXP_HI_GUARD = 160;
    localparam int FP32_EXP_LO_GUARD = -190;
    localparam int FP32_SUBN_EXP     = -126;

    function automatic logic [15:0] mul_u8x8_exact(
        input logic [7:0] lhs,
        input logic [7:0] rhs
    );
        logic [15:0] acc;
        acc = 16'd0;
        for (int b = 0; b < 8; ++b) begin
            if (rhs[b]) begin
                acc = acc + ({8'd0, lhs} << b);
            end
        end
        return acc;
    endfunction

    function automatic logic [31:0] encode_scaled_lane_fp32(
        input logic                    is_nan_b,
        input logic                    is_inf_b,
        input logic                    is_zero_b,
        input logic                    sign_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [SIG_W-1:0]        sig_b
    );
        logic signed [EXP_W-1:0] biased_e;
        if (is_nan_b) begin
            return TCU_V2_CANONICAL_QNAN;
        end else if (is_inf_b) begin
            return sign_b ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end else if (is_zero_b || !sig_b[SIG_W-1]) begin
            return sign_b ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
        end else begin
            biased_e = exp_b + $signed(EXP_W'(127));
            if (biased_e <= 0) begin
                return sign_b ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
            end else if (biased_e >= 255) begin
                return sign_b ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            end else begin
                return {sign_b, biased_e[7:0], sig_b[SIG_W-2:0]};
            end
        end
    endfunction

    function automatic logic scaled_lane_is_exact_int(
        input logic                    is_zero_b,
        input logic                    is_special_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [SIG_W-1:0]        sig_b
    );
        if (is_special_b) begin
            return 1'b0;
        end else if (is_zero_b || !sig_b[SIG_W-1]) begin
            return 1'b1;
        end else if (exp_b < 0) begin
            return 1'b0;
        end else if (exp_b >= $signed(EXP_W'(SIG_W - 1))) begin
            return 1'b1;
        end else begin
            logic [SIG_W-2:0] frac_mask;
            frac_mask = {(SIG_W-1){1'b1}} >> exp_b[4:0];
            return ((sig_b[SIG_W-2:0] & frac_mask) == '0);
        end
    endfunction

    logic a_is_fp4;
    logic b_is_fp4;
    logic a_is_fp6;
    logic b_is_fp6;
    logic use_fp4_only;
    logic use_fp6_path;
    logic both_valid_fmts;

    assign a_is_fp4 = tcu_v2_fmt_is_fp4(fmt_a);
    assign b_is_fp4 = tcu_v2_fmt_is_fp4(fmt_b);
    assign a_is_fp6 = tcu_v2_fmt_is_fp6(fmt_a);
    assign b_is_fp6 = tcu_v2_fmt_is_fp6(fmt_b);

    assign both_valid_fmts       = (a_is_fp4 || a_is_fp6) && (b_is_fp4 || b_is_fp6);
    assign use_fp4_only          = a_is_fp4 && b_is_fp4;
    assign use_fp6_path          = !use_fp4_only && (a_is_fp6 || b_is_fp6);
    assign use_fp6_path_out      = use_fp6_path;
    assign illegal_fmt_combo_out = !both_valid_fmts;

    for (genvar i = 0; i < LANES; ++i) begin : g_select_scale
        logic                         raw_sign;
        logic signed [EXP_W-1:0]      raw_exp;
        logic [7:0]                   raw_mant_u1p7;
        logic                         raw_zero;
        logic                         raw_neg_zero;

        logic [15:0]                  scaled_mant_u2p14;
        logic [15:0]                  scaled_mant_norm;
        logic                         scaled_carry;
        logic signed [EXP_W:0]        scaled_exp_wide;

        logic                         eff_zero;
        logic                         eff_neg_zero;
        logic                         eff_nan;
        logic                         eff_inf;
        logic                         eff_unf;
        logic                         eff_ovf;
        logic                         eff_subn;
        logic                         lane_active;

        assign lane_active = lane_enable_mask[i] && both_valid_fmts;

        // Multiplex between dedicated FP4 path (extended u1.3 -> u1.7) and FP6/mixed path.
        always_comb begin
            if (use_fp6_path) begin
                raw_sign      = fp6_sign_in[i];
                raw_exp       = fp6_exp_in[i];
                raw_mant_u1p7 = fp6_mant_u1p7_in[i];
                raw_zero      = fp6_zero_in[i] || !lane_active;
                raw_neg_zero  = fp6_neg_zero_in[i] && lane_active;
            end else begin
                raw_sign      = fp4_sign_in[i];
                raw_exp       = fp4_exp_in[i];
                raw_mant_u1p7 = {fp4_mant_u1p3_in[i], 4'b0000};
                raw_zero      = fp4_zero_in[i] || !lane_active;
                raw_neg_zero  = fp4_neg_zero_in[i] && lane_active;
            end
        end

        // Exact 8b x 8b unsigned multiplication: raw_mant (u1.7) * scale_mant (u1.7) = u2.14.
        assign scaled_mant_u2p14 = mul_u8x8_exact(raw_mant_u1p7, scale_comb_mant_u1p7_in);
        assign scaled_carry      = scaled_mant_u2p14[15];

        always_comb begin
            if (scaled_carry) begin
                scaled_mant_norm = scaled_mant_u2p14;
                scaled_exp_wide  = $signed({raw_exp[EXP_W-1], raw_exp})
                                 + $signed({scale_comb_exp_in[EXP_W-1], scale_comb_exp_in})
                                 + $signed({{(EXP_W){1'b0}}, 1'b1});
            end else begin
                scaled_mant_norm = {scaled_mant_u2p14[14:0], 1'b0};
                scaled_exp_wide  = $signed({raw_exp[EXP_W-1], raw_exp})
                                 + $signed({scale_comb_exp_in[EXP_W-1], scale_comb_exp_in});
            end
        end

        always_comb begin
            eff_nan      = scale_comb_is_nan_in || !both_valid_fmts;
            eff_inf      = (!eff_nan) && (!raw_zero) && (!scale_comb_is_zero_in) && scale_comb_exp_ovf_in;
            eff_unf      = (!eff_nan) && (!raw_zero) && (!scale_comb_is_zero_in) &&
                           (scale_comb_exp_unf_in || (scaled_exp_wide < $signed((EXP_W+1)'(FP32_EXP_LO_GUARD))));
            eff_ovf      = (!eff_nan) && (!raw_zero) && (!scale_comb_is_zero_in) &&
                           (scale_comb_exp_ovf_in || (scaled_exp_wide > $signed((EXP_W+1)'(FP32_EXP_HI_GUARD))));
            eff_zero     = (!eff_nan) && (!eff_inf) &&
                           (raw_zero || scale_comb_is_zero_in || (scaled_mant_u2p14 == 16'd0));
            eff_neg_zero = eff_zero && (raw_neg_zero || raw_sign);
            eff_subn     = (!eff_nan) && (!eff_inf) && (!eff_zero) &&
                           (scaled_exp_wide < $signed((EXP_W+1)'(FP32_SUBN_EXP)));
        end

        always_comb begin
            if (eff_nan || eff_inf || eff_zero) begin
                lane_sign_out[i]      = eff_nan ? 1'b0 : raw_sign;
                lane_exp_out[i]       = '0;
                lane_sig_u1p23_out[i] = '0;
            end else begin
                lane_sign_out[i]      = raw_sign;
                lane_exp_out[i]       = scaled_exp_wide[EXP_W-1:0];
                lane_sig_u1p23_out[i] = {scaled_mant_norm, {(SIG_W-16){1'b0}}};
            end
        end

        assign lane_is_zero_out[i]          = eff_zero;
        assign lane_is_neg_zero_out[i]      = eff_neg_zero;
        assign lane_is_nan_out[i]           = eff_nan;
        assign lane_is_inf_out[i]           = eff_inf;
        assign lane_underflow_out[i]        = eff_unf;
        assign lane_overflow_out[i]         = eff_ovf;
        assign lane_subnormal_fp32_out[i]   = eff_subn;
        assign lane_scaled_raw_u2p14_out[i] = (eff_nan || eff_inf || eff_zero) ? 16'd0 : scaled_mant_u2p14;
        assign lane_fp32_equiv_out[i]       = encode_scaled_lane_fp32(
            eff_nan, eff_inf, eff_zero, lane_sign_out[i], lane_exp_out[i], lane_sig_u1p23_out[i]
        );
        assign lane_scaled_exact_int_out[i] = scaled_lane_is_exact_int(
            eff_zero, (eff_nan || eff_inf), lane_exp_out[i], lane_sig_u1p23_out[i]
        );
    end

    assign any_lane_nan_out       = |lane_is_nan_out;
    assign any_lane_inf_out       = |lane_is_inf_out;
    assign any_lane_uf_out        = |lane_underflow_out;
    assign any_lane_of_out        = |lane_overflow_out;
    assign all_lanes_zero_out     = &lane_is_zero_out;
    assign all_lanes_neg_zero_out = &lane_is_neg_zero_out;

    // Summarize active scaled lanes, min/max exponents, and sign balance for alignment diagnostics.
    always_comb begin
        logic [$clog2(LANES+1)-1:0] act_cnt;
        logic [3:0]                 p_cnt;
        logic [3:0]                 n_cnt;
        logic signed [EXP_W-1:0]    peak_e;
        logic signed [EXP_W-1:0]    trough_e;
        logic                       seen_act;
        act_cnt  = '0;
        p_cnt    = 4'd0;
        n_cnt    = 4'd0;
        peak_e   = $signed(EXP_W'(-512));
        trough_e = $signed(EXP_W'(511));
        seen_act = 1'b0;

        for (int k = 0; k < LANES; ++k) begin
            if (!lane_is_zero_out[k] && !lane_is_nan_out[k] && !lane_is_inf_out[k]) begin
                act_cnt = act_cnt + {{($clog2(LANES+1)-1){1'b0}}, 1'b1};
                if (lane_sign_out[k]) begin
                    n_cnt = n_cnt + 4'd1;
                end else begin
                    p_cnt = p_cnt + 4'd1;
                end
                if (!seen_act) begin
                    peak_e   = lane_exp_out[k];
                    trough_e = lane_exp_out[k];
                    seen_act = 1'b1;
                end else begin
                    if ($signed(lane_exp_out[k]) > $signed(peak_e)) begin
                        peak_e = lane_exp_out[k];
                    end
                    if ($signed(lane_exp_out[k]) < $signed(trough_e)) begin
                        trough_e = lane_exp_out[k];
                    end
                end
            end
        end
        active_scaled_lanes_out = act_cnt;
        max_scaled_exp_out      = seen_act ? peak_e : '0;
        min_scaled_exp_out      = seen_act ? trough_e : '0;
        pos_scaled_cnt_out      = p_cnt;
        neg_scaled_cnt_out      = n_cnt;
        scaled_exp_span_out     = seen_act ? (peak_e - trough_e) : '0;
    end

    `STATIC_ASSERT((SIG_W == 24) && (EXP_W == 10), ("Unexpected SIG_W or EXP_W"))

endmodule
