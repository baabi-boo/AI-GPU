// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_block_align import VX_tcu_v2_pkg::*; #(
    parameter int EXP_W = TCU_V2_FP_EXP_W
) (
    input  tcu_v2_scale_decoded_t        scale_a,
    input  tcu_v2_scale_decoded_t        scale_b,
    input  tcu_v2_fmt_e                  fmt_a,
    input  tcu_v2_fmt_e                  fmt_b,
    input  tcu_v2_scale_fmt_e            expected_scale_fmt,
    input  logic                         enable_subnorm_norm,
    output logic signed [EXP_W-1:0]      comb_exp_out,
    output logic [7:0]                   comb_mant_u2p6_out,
    output logic [7:0]                   comb_mant_norm_u1p7_out,
    output logic                         comb_is_zero_out,
    output logic                         comb_is_nan_out,
    output logic                         comb_exp_ovf_out,
    output logic                         comb_exp_unf_out,
    output logic                         comb_is_unity_out,
    output logic                         comb_is_pow2_out,
    output logic [5:0]                   block_size_out,
    output logic                         is_k16_block_out,
    output logic                         is_k32_block_out,
    output logic                         scale_mismatch_out,
    output logic [31:0]                  comb_scale_fp32_out,
    output logic [3:0]                   mant_lzc_out,
    output logic                         scale_a_gt_b_out,
    output logic signed [EXP_W-1:0]      scale_exp_diff_out,
    output logic [7:0]                   comb_scale_ue8m0_approx_out,
    output logic [3:0]                   comb_scale_e4m3_exp_hint_out,
    output logic                         comb_requires_fp32_subnorm_out,
    output logic [3:0]                   comb_scale_e4m3_quant_out,
    output logic [7:0]                   comb_scale_e4m3_byte_out,
    output logic                         comb_scale_round_inexact_out,
    output logic                         comb_both_e4m3_subnorm_out,
    output logic                         comb_any_e4m3_subnorm_out
);

    localparam int EXP_SUM_W         = EXP_W + 2;
    localparam int EXP_MIN_GUARD     = -510;
    localparam int EXP_MAX_GUARD     = 510;
    localparam int FP32_MIN_NORM_EXP = -126;

    function automatic logic [5:0] fmt_block_granule(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_NVFP4_E2M1: return 6'd16;
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2: return 6'd32;
            default:               return 6'd1;
        endcase
    endfunction

    function automatic logic [2:0] lzc_8bit(
        input logic [7:0] val8
    );
        if (val8[7]) begin
            return 3'd0;
        end else if (val8[6]) begin
            return 3'd1;
        end else if (val8[5]) begin
            return 3'd2;
        end else if (val8[4]) begin
            return 3'd3;
        end else if (val8[3]) begin
            return 3'd4;
        end else if (val8[2]) begin
            return 3'd5;
        end else if (val8[1]) begin
            return 3'd6;
        end else if (val8[0]) begin
            return 3'd7;
        end else begin
            return 3'd0;
        end
    endfunction

    function automatic logic [7:0] mul_u4x4_scale(
        input logic [3:0] ma,
        input logic [3:0] mb
    );
        logic [7:0] p0;
        logic [7:0] p1;
        logic [7:0] p2;
        logic [7:0] p3;
        p0 = mb[0] ? {4'd0, ma}        : 8'd0;
        p1 = mb[1] ? {3'd0, ma, 1'b0}  : 8'd0;
        p2 = mb[2] ? {2'd0, ma, 2'b00} : 8'd0;
        p3 = mb[3] ? {1'b0, ma, 3'b000}: 8'd0;
        return (p0 + p1) + (p2 + p3);
    endfunction

    function automatic logic [31:0] pack_comb_scale_fp32(
        input logic                    is_nan_b,
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [7:0]              mant_u1p7_b
    );
        logic signed [EXP_W-1:0] fp32_exp;
        if (is_nan_b) begin
            return TCU_V2_CANONICAL_QNAN;
        end else if (is_zero_b || !mant_u1p7_b[7]) begin
            return TCU_V2_FP32_POS_ZERO;
        end else begin
            fp32_exp = exp_b + $signed(EXP_W'(127));
            if (fp32_exp <= 0) begin
                return TCU_V2_FP32_POS_ZERO;
            end else if (fp32_exp >= 255) begin
                return TCU_V2_FP32_POS_INF;
            end else begin
                return {1'b0, fp32_exp[7:0], mant_u1p7_b[6:0], 16'd0};
            end
        end
    endfunction

    function automatic logic [7:0] clamp_ue8m0_exp(
        input logic                    is_nan_b,
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] exp_b
    );
        logic signed [EXP_W-1:0] biased;
        if (is_nan_b) begin
            return 8'hFF;
        end else if (is_zero_b) begin
            return 8'h00;
        end else begin
            biased = exp_b + $signed(EXP_W'(127));
            if (biased <= 0) begin
                return 8'h00;
            end else if (biased >= 254) begin
                return 8'hFE;
            end else begin
                return biased[7:0];
            end
        end
    endfunction

    // Re-quantize combined scale product into positive E4M3FN byte with RNE rounding.
    function automatic logic [8:0] requantize_e4m3_scale(
        input logic                    is_nan_b,
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [7:0]              mant_u1p7_b
    );
        logic signed [EXP_W-1:0] biased_e4;
        logic [2:0]              m3;
        logic                    g_bit;
        logic                    s_bit;
        logic                    rup;
        logic [3:0]              m_inc;
        logic [7:0]              byte_out;
        logic                    inexact;
        if (is_nan_b) begin
            return {1'b0, 8'h7F};
        end else if (is_zero_b || !mant_u1p7_b[7]) begin
            return {1'b0, 8'h00};
        end else begin
            biased_e4 = exp_b + $signed(EXP_W'(7));
            m3        = mant_u1p7_b[6:4];
            g_bit     = mant_u1p7_b[3];
            s_bit     = |mant_u1p7_b[2:0];
            inexact   = g_bit | s_bit;
            rup       = g_bit && (s_bit || m3[0]);
            m_inc     = {1'b0, m3} + {3'b0, rup};
            if (biased_e4 <= -3) begin
                return {1'b1, 8'h00};
            end else if (biased_e4 <= 0) begin
                return {1'b1, 1'b0, 4'd0, mant_u1p7_b[6:4]};
            end else if (biased_e4 >= 16) begin
                return {1'b1, 8'h7E};
            end else if (m_inc[3]) begin
                if (biased_e4 >= 15) begin
                    return {1'b1, 8'h7E};
                end else begin
                    byte_out = {1'b0, (biased_e4[3:0] + 4'd1), 3'd0};
                    return {inexact, byte_out};
                end
            end else begin
                if ((biased_e4[3:0] == 4'hF) && (m_inc[2:0] == 3'h7)) begin
                    byte_out = 8'h7E;
                end else begin
                    byte_out = {1'b0, biased_e4[3:0], m_inc[2:0]};
                end
                return {inexact, byte_out};
            end
        end
    endfunction

    logic [3:0]                   mant_a_u1p3;
    logic [3:0]                   mant_b_u1p3;
    logic [7:0]                   mant_prod_raw;
    logic [7:0]                   mant_prod_norm;
    logic [2:0]                   norm_shift_left;
    logic                         prod_has_carry;
    logic                         prod_is_zero;

    logic signed [EXP_SUM_W-1:0]  exp_a_ext;
    logic signed [EXP_SUM_W-1:0]  exp_b_ext;
    logic signed [EXP_SUM_W-1:0]  exp_raw_sum;
    logic signed [EXP_SUM_W-1:0]  exp_norm_adj;
    logic signed [EXP_SUM_W-1:0]  exp_final_ext;
    logic signed [EXP_W-1:0]      comb_exp_clamped;

    logic                         any_nan;
    logic                         any_zero;
    logic                         ovf_flag;
    logic                         unf_flag;

    logic [5:0]                   blk_a;
    logic [5:0]                   blk_b;
    logic                         fmt_a_nvfp4;
    logic                         fmt_b_nvfp4;
    logic                         fmt_expect_ok;
    logic [8:0]                   e4m3_requant_pack;

    assign mant_a_u1p3 = scale_a.mant_u1p3;
    assign mant_b_u1p3 = scale_b.mant_u1p3;

    assign any_nan  = scale_a.is_nan || scale_b.is_nan;
    assign any_zero = scale_a.is_zero || scale_b.is_zero || (mant_a_u1p3 == 4'd0) || (mant_b_u1p3 == 4'd0);

    // Exact 4b x 4b unsigned mantissa product (u1.3 * u1.3 = u2.6).
    assign mant_prod_raw   = mul_u4x4_scale(mant_a_u1p3, mant_b_u1p3);
    assign prod_is_zero    = (mant_prod_raw == 8'd0);
    assign prod_has_carry  = mant_prod_raw[7];
    assign norm_shift_left = lzc_8bit(mant_prod_raw);

    // Normalize u2.6 product into u1.7 (leading 1 at bit 7 when non-zero)
    // and compute the signed exponent delta adjustment.
    always_comb begin
        if (any_nan || any_zero || prod_is_zero) begin
            mant_prod_norm = 8'd0;
            exp_norm_adj   = '0;
        end else if (prod_has_carry) begin
            mant_prod_norm = mant_prod_raw;
            exp_norm_adj   = $signed(EXP_SUM_W'(1));
        end else if (enable_subnorm_norm || mant_prod_raw[6]) begin
            mant_prod_norm = mant_prod_raw << norm_shift_left;
            exp_norm_adj   = $signed(EXP_SUM_W'(1)) - $signed({{(EXP_SUM_W-3){1'b0}}, norm_shift_left});
        end else begin
            mant_prod_norm = {mant_prod_raw[6:0], 1'b0};
            exp_norm_adj   = '0;
        end
    end

    assign exp_a_ext   = {{(EXP_SUM_W-EXP_W){scale_a.exp_delta[EXP_W-1]}}, scale_a.exp_delta};
    assign exp_b_ext   = {{(EXP_SUM_W-EXP_W){scale_b.exp_delta[EXP_W-1]}}, scale_b.exp_delta};
    assign exp_raw_sum = exp_a_ext + exp_b_ext;

    // Combined normalized exponent tracks u1.7 mantissa.
    always_comb begin
        if (any_nan || any_zero || prod_is_zero) begin
            exp_final_ext = '0;
            ovf_flag      = 1'b0;
            unf_flag      = 1'b0;
        end else begin
            exp_final_ext = exp_raw_sum + exp_norm_adj;
            ovf_flag      = (exp_final_ext > $signed(EXP_SUM_W'(EXP_MAX_GUARD)));
            unf_flag      = (exp_final_ext < $signed(EXP_SUM_W'(EXP_MIN_GUARD)));
        end
    end

    assign comb_exp_clamped = (any_nan || any_zero || prod_is_zero) ? '0 :
                              (ovf_flag ? $signed(EXP_W'(EXP_MAX_GUARD)) :
                              (unf_flag ? $signed(EXP_W'(EXP_MIN_GUARD)) : exp_final_ext[EXP_W-1:0]));

    // Determine effective microscaling block size (k=16 for NVFP4, k=32 for MXFP4/MXFP6).
    assign fmt_a_nvfp4   = (fmt_a == TCU_V2_FMT_NVFP4_E2M1);
    assign fmt_b_nvfp4   = (fmt_b == TCU_V2_FMT_NVFP4_E2M1);
    assign blk_a         = fmt_block_granule(fmt_a);
    assign blk_b         = fmt_block_granule(fmt_b);
    assign fmt_expect_ok = (expected_scale_fmt == TCU_V2_SCALE_NONE) ||
                           ((scale_a.scale_fmt == expected_scale_fmt) && (scale_b.scale_fmt == expected_scale_fmt));

    assign e4m3_requant_pack = requantize_e4m3_scale(
        any_nan, comb_is_zero_out, comb_exp_clamped, mant_prod_norm
    );

    assign is_k16_block_out               = fmt_a_nvfp4 || fmt_b_nvfp4;
    assign is_k32_block_out               = !is_k16_block_out && ((blk_a == 6'd32) || (blk_b == 6'd32));
    assign block_size_out                 = is_k16_block_out ? 6'd16 : (is_k32_block_out ? 6'd32 : 6'd1);
    assign scale_mismatch_out             = (scale_a.scale_fmt != scale_b.scale_fmt) || (blk_a != blk_b) || !fmt_expect_ok;

    assign comb_exp_out                   = comb_exp_clamped;
    assign comb_mant_u2p6_out             = (any_nan || any_zero) ? 8'd0 : mant_prod_raw;
    assign comb_mant_norm_u1p7_out        = mant_prod_norm;
    assign comb_is_zero_out               = (!any_nan) && (any_zero || prod_is_zero);
    assign comb_is_nan_out                = any_nan;
    assign comb_exp_ovf_out               = ovf_flag;
    assign comb_exp_unf_out               = unf_flag;
    assign comb_is_pow2_out               = (!any_nan) && (!any_zero) && (mant_prod_norm == 8'h80);
    assign comb_is_unity_out              = comb_is_pow2_out && (comb_exp_clamped == '0);
    assign mant_lzc_out                   = {1'b0, norm_shift_left};
    assign comb_scale_fp32_out            = pack_comb_scale_fp32(any_nan, comb_is_zero_out, comb_exp_clamped, mant_prod_norm);
    assign scale_a_gt_b_out               = (scale_a.exp_delta > scale_b.exp_delta) ||
                                            ((scale_a.exp_delta == scale_b.exp_delta) && (mant_a_u1p3 > mant_b_u1p3));
    assign scale_exp_diff_out             = scale_a.exp_delta - scale_b.exp_delta;
    assign comb_scale_ue8m0_approx_out    = clamp_ue8m0_exp(any_nan, comb_is_zero_out, comb_exp_clamped);
    assign comb_scale_e4m3_exp_hint_out   = (comb_exp_clamped < -6) ? 4'd0 :
                                            ((comb_exp_clamped > 8) ? 4'hF : (4'(comb_exp_clamped[3:0]) + 4'd7));
    assign comb_requires_fp32_subnorm_out = (!any_nan) && (!comb_is_zero_out) &&
                                            (comb_exp_clamped < $signed(EXP_W'(FP32_MIN_NORM_EXP)));
    assign comb_scale_e4m3_quant_out      = e4m3_requant_pack[6:3];
    assign comb_scale_e4m3_byte_out       = e4m3_requant_pack[7:0];
    assign comb_scale_round_inexact_out   = e4m3_requant_pack[8];
    assign comb_both_e4m3_subnorm_out     = (!any_nan) && (!any_zero) && !mant_a_u1p3[3] && !mant_b_u1p3[3];
    assign comb_any_e4m3_subnorm_out      = (!any_nan) && (!any_zero) && (!mant_a_u1p3[3] || !mant_b_u1p3[3]);

    `STATIC_ASSERT(EXP_W >= 10, ("Block align requires EXP_W >= 10"))

endmodule
