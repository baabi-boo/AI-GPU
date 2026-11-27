// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_scale_decode import VX_tcu_v2_pkg::*; #(
    parameter int EXP_W = TCU_V2_FP_EXP_W
) (
    input  tcu_v2_scale_fmt_e            scale_fmt,
    input  logic [7:0]                   scale_raw,
    output tcu_v2_scale_decoded_t        decoded_out,
    output logic signed [EXP_W-1:0]      exp_delta_out,
    output logic [3:0]                   mant_u1p3_out,
    output logic [3:0]                   norm_mant_u1p3_out,
    output logic signed [EXP_W-1:0]      norm_exp_delta_out,
    output logic [1:0]                   mant_lzc_out,
    output logic                         is_zero_out,
    output logic                         is_nan_out,
    output logic                         is_subnormal_out,
    output logic                         is_unity_out,
    output logic                         is_max_finite_out,
    output logic                         is_min_pos_out,
    output logic                         is_power_of_two_out,
    output logic                         invalid_encoding_out,
    output logic [2:0]                   scale_class_out,
    output logic [31:0]                  scale_as_fp32_out,
    output logic [31:0]                  recip_approx_fp32_out,
    output logic [7:0]                   bias_adjusted_raw_out,
    output logic                         is_gt_unity_out,
    output logic                         is_lt_unity_out,
    output logic [7:0]                   e4m3_to_ue8m0_floor_out,
    output logic [7:0]                   e4m3_to_ue8m0_ceil_out,
    output logic [15:0]                  scale_bf16_equiv_out
);

    localparam int UE8M0_BIAS = 127;
    localparam int E4M3_BIAS  = 7;

    localparam logic [2:0] SCLS_UNITY     = 3'd0;
    localparam logic [2:0] SCLS_ZERO      = 3'd1;
    localparam logic [2:0] SCLS_SUBNORM   = 3'd2;
    localparam logic [2:0] SCLS_NORMAL    = 3'd3;
    localparam logic [2:0] SCLS_MAX_FIN   = 3'd4;
    localparam logic [2:0] SCLS_NAN       = 3'd5;
    localparam logic [2:0] SCLS_INVALID   = 3'd6;

    function automatic logic [1:0] lzc_3bit(
        input logic [2:0] man3
    );
        if (man3[2]) begin
            return 2'd1;
        end else if (man3[1]) begin
            return 2'd2;
        end else if (man3[0]) begin
            return 2'd3;
        end else begin
            return 2'd0;
        end
    endfunction

    function automatic logic [31:0] encode_scale_fp32(
        input logic                    is_nan_b,
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] norm_exp_b,
        input logic [3:0]              norm_mant_b
    );
        logic signed [EXP_W-1:0] fp32_biased_exp;
        logic [22:0]             fp32_man;
        if (is_nan_b) begin
            return TCU_V2_CANONICAL_QNAN;
        end else if (is_zero_b || !norm_mant_b[3]) begin
            return TCU_V2_FP32_POS_ZERO;
        end else begin
            fp32_biased_exp = norm_exp_b + $signed(EXP_W'(127));
            fp32_man        = {norm_mant_b[2:0], 20'd0};
            if (fp32_biased_exp <= 0) begin
                return TCU_V2_FP32_POS_ZERO;
            end else if (fp32_biased_exp >= 255) begin
                return TCU_V2_FP32_POS_INF;
            end else begin
                return {1'b0, fp32_biased_exp[7:0], fp32_man};
            end
        end
    endfunction

    // Compute approximate FP32 reciprocal of positive scale factor for quantize/dequantize paths.
    function automatic logic [31:0] encode_recip_fp32(
        input logic                    is_nan_b,
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] norm_exp_b,
        input logic [3:0]              norm_mant_b
    );
        logic signed [EXP_W-1:0] recip_exp;
        logic [2:0]              man_lo;
        logic [22:0]             recip_man;
        if (is_nan_b) begin
            return TCU_V2_CANONICAL_QNAN;
        end else if (is_zero_b || !norm_mant_b[3]) begin
            return TCU_V2_FP32_POS_INF;
        end else begin
            man_lo = norm_mant_b[2:0];
            if (man_lo == 3'b000) begin
                recip_exp = $signed(EXP_W'(127)) - norm_exp_b;
                recip_man = 23'd0;
            end else begin
                recip_exp = $signed(EXP_W'(126)) - norm_exp_b;
                // 1 / (1 + m/8) = 8 / (8 + m) in [0.533, 0.889] -> normalized 1.xxxx * 2^-1
                case (man_lo)
                    3'd1: recip_man = {3'b110, 20'd0};
                    3'd2: recip_man = {3'b100, 20'd0};
                    3'd3: recip_man = {3'b011, 20'd0};
                    3'd4: recip_man = {3'b010, 20'd0};
                    3'd5: recip_man = {3'b001, 20'd0};
                    3'd6: recip_man = {3'b001, 20'd0};
                    3'd7: recip_man = {3'b000, 20'd0};
                    default: recip_man = 23'd0;
                endcase
            end
            if (recip_exp <= 0) begin
                return TCU_V2_FP32_POS_ZERO;
            end else if (recip_exp >= 255) begin
                return TCU_V2_FP32_POS_INF;
            end else begin
                return {1'b0, recip_exp[7:0], recip_man};
            end
        end
    endfunction

    function automatic logic [7:0] convert_to_ue8m0(
        input logic                    is_nan_b,
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] norm_exp_b,
        input logic [3:0]              norm_mant_b,
        input logic                    round_up_ceil
    );
        logic signed [EXP_W-1:0] biased_e;
        logic                    has_frac;
        if (is_nan_b) begin
            return 8'hFF;
        end else if (is_zero_b || !norm_mant_b[3]) begin
            return 8'h00;
        end else begin
            has_frac = (norm_mant_b[2:0] != 3'b000);
            biased_e = norm_exp_b + $signed(EXP_W'(127))
                     + ((round_up_ceil && has_frac) ? $signed(EXP_W'(1)) : $signed(EXP_W'(0)));
            if (biased_e <= 0) begin
                return 8'h00;
            end else if (biased_e >= 254) begin
                return 8'hFE;
            end else begin
                return biased_e[7:0];
            end
        end
    endfunction

    logic                         sign_bit;
    logic [3:0]                   e4m3_exp;
    logic [2:0]                   e4m3_man;
    logic                         e4m3_exp_zero;
    logic                         e4m3_man_zero;
    logic                         e4m3_is_nan;
    logic                         e4m3_is_zero;
    logic                         e4m3_is_subnorm;
    logic                         e4m3_is_max_fin;
    logic                         e4m3_is_min_pos;
    logic [3:0]                   e4m3_mant_raw;
    logic [3:0]                   e4m3_mant_norm;
    logic [1:0]                   e4m3_lzc;
    logic signed [EXP_W-1:0]      e4m3_exp_unbiased;
    logic signed [EXP_W-1:0]      e4m3_exp_norm;

    logic                         ue8m0_is_nan;
    logic                         ue8m0_is_max_fin;
    logic                         ue8m0_is_min_pos;
    logic signed [EXP_W-1:0]      ue8m0_exp_unbiased;

    logic                         dec_is_zero;
    logic                         dec_is_nan;
    logic                         dec_is_subnorm;
    logic                         dec_is_unity;
    logic                         dec_is_max_fin;
    logic                         dec_is_min_pos;
    logic                         dec_is_pow2;
    logic                         dec_invalid;
    logic signed [EXP_W-1:0]      dec_exp_delta;
    logic signed [EXP_W-1:0]      dec_norm_exp;
    logic [3:0]                   dec_mant_u1p3;
    logic [3:0]                   dec_norm_mant;
    logic [1:0]                   dec_mant_lzc;
    logic [2:0]                   dec_class;
    logic [31:0]                  dec_fp32;

    assign sign_bit = scale_raw[7];
    assign e4m3_exp = scale_raw[6:3];
    assign e4m3_man = scale_raw[2:0];

    assign e4m3_exp_zero   = (e4m3_exp == 4'd0);
    assign e4m3_man_zero   = (e4m3_man == 3'd0);
    assign e4m3_is_nan     = sign_bit || ((e4m3_exp == 4'hF) && (e4m3_man == 3'h7));
    assign e4m3_is_zero    = !sign_bit && e4m3_exp_zero && e4m3_man_zero;
    assign e4m3_is_subnorm = !sign_bit && e4m3_exp_zero && !e4m3_man_zero;
    assign e4m3_is_max_fin = !sign_bit && (e4m3_exp == 4'hF) && (e4m3_man == 3'h6);
    assign e4m3_is_min_pos = !sign_bit && (e4m3_exp == 4'd0) && (e4m3_man == 3'd1);

    assign e4m3_lzc = e4m3_is_subnorm ? lzc_3bit(e4m3_man) : 2'd0;

    always_comb begin
        if (e4m3_is_nan || e4m3_is_zero) begin
            e4m3_mant_raw     = 4'b0000;
            e4m3_mant_norm    = 4'b0000;
            e4m3_exp_unbiased = '0;
            e4m3_exp_norm     = '0;
        end else if (e4m3_is_subnorm) begin
            e4m3_mant_raw     = {1'b0, e4m3_man};
            e4m3_mant_norm    = e4m3_mant_raw << e4m3_lzc;
            e4m3_exp_unbiased = $signed(EXP_W'(1 - E4M3_BIAS));
            e4m3_exp_norm     = $signed(EXP_W'(1 - E4M3_BIAS))
                              - $signed({{(EXP_W-2){1'b0}}, e4m3_lzc});
        end else begin
            e4m3_mant_raw     = {1'b1, e4m3_man};
            e4m3_mant_norm    = {1'b1, e4m3_man};
            e4m3_exp_unbiased = $signed({{(EXP_W-4){1'b0}}, e4m3_exp})
                              - $signed(EXP_W'(E4M3_BIAS));
            e4m3_exp_norm     = e4m3_exp_unbiased;
        end
    end

    // OCP UE8M0: unsigned 8-bit exponent with bias 127, 0xFF reserved for NaN.
    assign ue8m0_is_nan       = (scale_raw == 8'hFF);
    assign ue8m0_is_max_fin   = (scale_raw == 8'hFE);
    assign ue8m0_is_min_pos   = (scale_raw == 8'h00);
    assign ue8m0_exp_unbiased = ue8m0_is_nan ? '0 :
                                ($signed({{(EXP_W-8){1'b0}}, scale_raw}) - $signed(EXP_W'(UE8M0_BIAS)));

    always_comb begin
        dec_is_zero    = 1'b0;
        dec_is_nan     = 1'b0;
        dec_is_subnorm = 1'b0;
        dec_is_unity   = 1'b0;
        dec_is_max_fin = 1'b0;
        dec_is_min_pos = 1'b0;
        dec_is_pow2    = 1'b0;
        dec_invalid    = 1'b0;
        dec_exp_delta  = '0;
        dec_norm_exp   = '0;
        dec_mant_u1p3  = 4'b1000;
        dec_norm_mant  = 4'b1000;
        dec_mant_lzc   = 2'd0;
        dec_class      = SCLS_NORMAL;

        case (scale_fmt)
            TCU_V2_SCALE_NONE: begin
                dec_exp_delta = '0;
                dec_norm_exp  = '0;
                dec_mant_u1p3 = 4'b1000;
                dec_norm_mant = 4'b1000;
                dec_is_unity  = 1'b1;
                dec_is_pow2   = 1'b1;
                dec_class     = SCLS_UNITY;
            end
            TCU_V2_SCALE_UE8M0: begin
                dec_is_nan     = ue8m0_is_nan;
                dec_invalid    = ue8m0_is_nan;
                dec_exp_delta  = ue8m0_exp_unbiased;
                dec_norm_exp   = ue8m0_exp_unbiased;
                dec_mant_u1p3  = ue8m0_is_nan ? 4'b0000 : 4'b1000;
                dec_norm_mant  = ue8m0_is_nan ? 4'b0000 : 4'b1000;
                dec_is_unity   = (!ue8m0_is_nan) && (scale_raw == 8'h7F);
                dec_is_max_fin = ue8m0_is_max_fin;
                dec_is_min_pos = ue8m0_is_min_pos;
                dec_is_pow2    = !ue8m0_is_nan;
                if (ue8m0_is_nan) begin
                    dec_class = SCLS_NAN;
                end else if (dec_is_unity) begin
                    dec_class = SCLS_UNITY;
                end else if (ue8m0_is_max_fin) begin
                    dec_class = SCLS_MAX_FIN;
                end else begin
                    dec_class = SCLS_NORMAL;
                end
            end
            TCU_V2_SCALE_E4M3: begin
                dec_is_nan     = e4m3_is_nan;
                dec_invalid    = sign_bit || e4m3_is_nan;
                dec_is_zero    = e4m3_is_zero;
                dec_is_subnorm = e4m3_is_subnorm;
                dec_is_max_fin = e4m3_is_max_fin;
                dec_is_min_pos = e4m3_is_min_pos;
                dec_exp_delta  = e4m3_exp_unbiased;
                dec_norm_exp   = e4m3_exp_norm;
                dec_mant_u1p3  = e4m3_mant_raw;
                dec_norm_mant  = e4m3_mant_norm;
                dec_mant_lzc   = e4m3_lzc;
                dec_is_unity   = (!e4m3_is_nan) && (e4m3_exp == 4'd7) && (e4m3_man == 3'd0);
                dec_is_pow2    = (!e4m3_is_nan) && (!e4m3_is_zero) && (e4m3_mant_norm == 4'b1000);
                if (e4m3_is_nan) begin
                    dec_class = SCLS_NAN;
                end else if (e4m3_is_zero) begin
                    dec_class = SCLS_ZERO;
                end else if (e4m3_is_subnorm) begin
                    dec_class = SCLS_SUBNORM;
                end else if (dec_is_unity) begin
                    dec_class = SCLS_UNITY;
                end else if (e4m3_is_max_fin) begin
                    dec_class = SCLS_MAX_FIN;
                end else begin
                    dec_class = SCLS_NORMAL;
                end
            end
            default: begin
                dec_is_nan    = 1'b1;
                dec_invalid   = 1'b1;
                dec_mant_u1p3 = 4'b0000;
                dec_norm_mant = 4'b0000;
                dec_class     = SCLS_INVALID;
            end
        endcase
    end

    always_comb begin
        decoded_out           = '0;
        decoded_out.scale_fmt = scale_fmt;
        decoded_out.is_zero   = dec_is_zero;
        decoded_out.is_nan    = dec_is_nan;
        decoded_out.exp_delta = dec_exp_delta;
        decoded_out.mant_u1p3 = dec_mant_u1p3;
    end

    assign dec_fp32                 = encode_scale_fp32(dec_is_nan, dec_is_zero, dec_norm_exp, dec_norm_mant);
    assign exp_delta_out            = dec_exp_delta;
    assign mant_u1p3_out            = dec_mant_u1p3;
    assign norm_mant_u1p3_out       = dec_norm_mant;
    assign norm_exp_delta_out       = dec_norm_exp;
    assign mant_lzc_out             = dec_mant_lzc;
    assign is_zero_out              = dec_is_zero;
    assign is_nan_out               = dec_is_nan;
    assign is_subnormal_out         = dec_is_subnorm;
    assign is_unity_out             = dec_is_unity;
    assign is_max_finite_out        = dec_is_max_fin;
    assign is_min_pos_out           = dec_is_min_pos;
    assign is_power_of_two_out      = dec_is_pow2;
    assign invalid_encoding_out     = dec_invalid;
    assign scale_class_out          = dec_class;
    assign scale_as_fp32_out        = dec_fp32;
    assign recip_approx_fp32_out    = encode_recip_fp32(dec_is_nan, dec_is_zero, dec_norm_exp, dec_norm_mant);
    assign bias_adjusted_raw_out    = dec_norm_exp[7:0] + 8'd127;
    assign is_gt_unity_out          = (!dec_is_nan) && (!dec_is_zero) &&
                                      ((dec_norm_exp > 0) || ((dec_norm_exp == 0) && (dec_norm_mant > 4'b1000)));
    assign is_lt_unity_out          = (!dec_is_nan) && (dec_is_zero || (dec_norm_exp < 0));
    assign e4m3_to_ue8m0_floor_out  = convert_to_ue8m0(dec_is_nan, dec_is_zero, dec_norm_exp, dec_norm_mant, 1'b0);
    assign e4m3_to_ue8m0_ceil_out   = convert_to_ue8m0(dec_is_nan, dec_is_zero, dec_norm_exp, dec_norm_mant, 1'b1);
    assign scale_bf16_equiv_out     = dec_fp32[31:16];

    `STATIC_ASSERT(EXP_W >= 10, ("Scale decoder requires EXP_W >= 10"))

endmodule
