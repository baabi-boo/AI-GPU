// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_fp32_round import VX_tcu_v2_pkg::*; #(
    parameter int EXP_W = TCU_V2_FP_EXP_W
) (
    input  tcu_v2_rm_e                   rm,
    input  logic                         sign_in,
    input  logic signed [EXP_W-1:0]      norm_exp_in,
    input  logic [23:0]                  norm_sig_u1p23_in,
    input  logic                         guard_in,
    input  logic                         round_in,
    input  logic                         sticky_in,
    input  logic                         is_zero_in,
    input  logic                         is_subnormal_in,
    input  logic                         is_nan_in,
    input  logic                         is_inf_in,
    input  logic                         inf_sign_in,
    input  logic                         zero_sign_in,
    input  logic                         invalid_op_in,
    input  logic                         pre_uf_in,
    input  logic                         pre_of_in,
    output logic [31:0]                  fp32_out,
    output tcu_v2_fp_flags_t             flags_out,
    output logic                         rounded_up_out,
    output logic                         carry_realign_out,
    output logic                         subnorm_promoted_out,
    output logic                         result_is_nan_out,
    output logic                         result_is_inf_out,
    output logic                         result_is_zero_out,
    output logic                         result_is_subnorm_out,
    output logic                         tie_exact_half_out,
    output logic                         tie_broken_even_out,
    output logic                         ovf_clamped_max_out,
    output logic [7:0]                   final_biased_exp_out,
    output logic [22:0]                  final_mantissa_out,
    output logic [15:0]                  fp16_downcast_out,
    output logic [15:0]                  bf16_downcast_out,
    output logic                         ulp_parity_lsb_out,
    output logic                         subnormal_tininess_out,
    output logic                         exact_normal_out
);

    localparam int FP32_BIAS     = 127;
    localparam int FP32_EXP_MAX  = 254;
    localparam logic [31:0] FP32_POS_MAX = 32'h7F7F_FFFF;
    localparam logic [31:0] FP32_NEG_MAX = 32'hFF7F_FFFF;

    function automatic logic compute_round_up(
        input tcu_v2_rm_e mode,
        input logic       sgn,
        input logic       lsb,
        input logic       g_bit,
        input logic       r_bit,
        input logic       s_bit
    );
        logic tail;
        tail = g_bit | r_bit | s_bit;
        case (mode)
            TCU_V2_RM_RNE: return g_bit && (r_bit || s_bit || lsb);
            TCU_V2_RM_RTZ: return 1'b0;
            TCU_V2_RM_RDN: return sgn && tail;
            TCU_V2_RM_RUP: return (!sgn) && tail;
            TCU_V2_RM_RMM: return g_bit;
            default:       return g_bit && (r_bit || s_bit || lsb);
        endcase
    endfunction

    function automatic logic select_ovf_to_inf(
        input tcu_v2_rm_e mode,
        input logic       sgn
    );
        case (mode)
            TCU_V2_RM_RNE,
            TCU_V2_RM_RMM: return 1'b1;
            TCU_V2_RM_RTZ: return 1'b0;
            TCU_V2_RM_RDN: return sgn;
            TCU_V2_RM_RUP: return !sgn;
            default:       return 1'b1;
        endcase
    endfunction

    function automatic logic [31:0] pack_ieee754_fp32(
        input logic        sgn,
        input logic [7:0]  exp8,
        input logic [22:0] man23
    );
        return {sgn, exp8, man23};
    endfunction

    // Secondary BF16 RNE preview from final FP32 word for epilogue downcast correlation.
    function automatic logic [15:0] fp32_to_bf16_rne(
        input logic [31:0] f32
    );
        logic        s;
        logic [7:0]  e;
        logic [22:0] m;
        logic        lsb_b;
        logic        g_b;
        logic        s_b;
        logic        rup_b;
        logic [15:0] upper;
        s     = f32[31];
        e     = f32[30:23];
        m     = f32[22:0];
        upper = f32[31:16];
        if (e == 8'hFF) begin
            if (m != 23'd0) begin
                return 16'h7FC0;
            end else begin
                return {s, 8'hFF, 7'd0};
            end
        end else begin
            lsb_b = f32[16];
            g_b   = f32[15];
            s_b   = |f32[14:0];
            rup_b = g_b && (s_b || lsb_b);
            return rup_b ? (upper + 16'd1) : upper;
        end
    endfunction

    // Secondary FP16 RNE preview from final FP32 word.
    function automatic logic [15:0] fp32_to_fp16_rne(
        input logic [31:0] f32
    );
        logic        s;
        logic [7:0]  e;
        logic [22:0] m;
        logic signed [9:0] exp16_s;
        logic [9:0]  man10;
        logic        g_h;
        logic        r_h;
        logic        s_h;
        logic        rup_h;
        logic [10:0] man11_inc;
        s = f32[31];
        e = f32[30:23];
        m = f32[22:0];
        if (e == 8'hFF) begin
            if (m != 23'd0) begin
                return 16'h7E00;
            end else begin
                return {s, 5'h1F, 10'd0};
            end
        end else if (e == 8'd0) begin
            return {s, 15'd0};
        end else begin
            exp16_s = $signed({2'b00, e}) - $signed(10'd112);
            man10   = m[22:13];
            g_h     = m[12];
            r_h     = m[11];
            s_h     = |m[10:0];
            rup_h   = g_h && (r_h || s_h || man10[0]);
            man11_inc = {1'b0, man10} + {10'd0, rup_h};
            if (exp16_s > 30) begin
                return {s, 5'h1F, 10'd0};
            end else if (exp16_s <= 0) begin
                return {s, 15'd0};
            end else if (man11_inc[10]) begin
                if (exp16_s == 30) begin
                    return {s, 5'h1F, 10'd0};
                end else begin
                    return {s, (exp16_s[4:0] + 5'd1), man11_inc[9:0]};
                end
            end else begin
                return {s, exp16_s[4:0], man11_inc[9:0]};
            end
        end
    endfunction

    logic inexact_tail;
    logic exact_half_tie;
    logic lsb_bit;
    logic round_up;
    logic ovf_to_inf;

    assign lsb_bit        = norm_sig_u1p23_in[0];
    assign inexact_tail   = guard_in | round_in | sticky_in;
    assign exact_half_tie = guard_in && !round_in && !sticky_in;
    assign round_up       = compute_round_up(rm, sign_in, lsb_bit, guard_in, round_in, sticky_in);
    assign ovf_to_inf     = select_ovf_to_inf(rm, sign_in);

    // Parallel pre-incremented significand for timing-friendly rounding mux.
    logic [24:0] sig_pre;
    logic [24:0] sig_inc;
    logic [24:0] sig_rounded;
    logic        sig_carry_out;
    logic        subnorm_promo;
    logic [22:0] final_man;

    logic signed [EXP_W:0] biased_exp_base;
    logic signed [EXP_W:0] biased_exp_final;

    assign sig_pre       = {1'b0, norm_sig_u1p23_in};
    assign sig_inc       = sig_pre + 25'd1;
    assign sig_rounded   = round_up ? sig_inc : sig_pre;
    assign sig_carry_out = sig_rounded[24];
    assign subnorm_promo = is_subnormal_in && !sig_carry_out && sig_rounded[23];

    // If rounding carries out of bit 23 (into bit 24), shift right by 1 and bump exponent,
    // except for subnormals where carry into bit 23 promotes subnormal to exp=1 normal.
    always_comb begin
        if (sig_carry_out) begin
            final_man        = sig_rounded[23:1];
            biased_exp_base  = $signed({norm_exp_in[EXP_W-1], norm_exp_in}) + $signed((EXP_W+1)'(FP32_BIAS));
            biased_exp_final = biased_exp_base + $signed((EXP_W+1)'(1));
        end else if (is_subnormal_in) begin
            final_man        = sig_rounded[22:0];
            biased_exp_base  = '0;
            biased_exp_final = sig_rounded[23] ? $signed((EXP_W+1)'(1)) : $signed((EXP_W+1)'(0));
        end else begin
            final_man        = sig_rounded[22:0];
            biased_exp_base  = $signed({norm_exp_in[EXP_W-1], norm_exp_in}) + $signed((EXP_W+1)'(FP32_BIAS));
            biased_exp_final = biased_exp_base;
        end
    end

    logic exp_overflow;
    logic exp_underflow_to_zero;
    logic is_subnorm_result;

    assign exp_overflow          = pre_of_in || (biased_exp_final > $signed((EXP_W+1)'(FP32_EXP_MAX)));
    assign exp_underflow_to_zero = (biased_exp_final <= 0) && (sig_rounded[23:0] == 24'd0);
    assign is_subnorm_result     = (biased_exp_final <= 0) && (sig_rounded[23:0] != 24'd0);

    logic [31:0]      normal_pack;
    logic [31:0]      subnorm_pack;
    logic [31:0]      ovf_pack;
    logic [31:0]      zero_pack;
    logic [31:0]      res_word;
    tcu_v2_fp_flags_t flags_calc;

    assign normal_pack  = pack_ieee754_fp32(sign_in, biased_exp_final[7:0], final_man);
    assign subnorm_pack = pack_ieee754_fp32(sign_in, 8'd0, sig_rounded[22:0]);
    assign ovf_pack     = ovf_to_inf ?
                          (sign_in ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF) :
                          (sign_in ? FP32_NEG_MAX : FP32_POS_MAX);
    assign zero_pack    = zero_sign_in ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;

    always_comb begin
        flags_calc = '0;
        if (is_nan_in || invalid_op_in) begin
            res_word      = TCU_V2_CANONICAL_QNAN;
            flags_calc.nv = invalid_op_in;
        end else if (is_inf_in) begin
            res_word = inf_sign_in ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end else if (is_zero_in) begin
            res_word      = zero_pack;
            flags_calc.uf = sticky_in | pre_uf_in;
            flags_calc.nx = sticky_in | pre_uf_in;
        end else if (exp_overflow) begin
            res_word      = ovf_pack;
            flags_calc.of = 1'b1;
            flags_calc.nx = 1'b1;
        end else if (exp_underflow_to_zero) begin
            res_word      = sign_in ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
            flags_calc.uf = 1'b1;
            flags_calc.nx = 1'b1;
        end else if (is_subnorm_result) begin
            res_word      = subnorm_pack;
            flags_calc.uf = inexact_tail | pre_uf_in;
            flags_calc.nx = inexact_tail | pre_uf_in;
        end else begin
            res_word      = normal_pack;
            flags_calc.nx = inexact_tail;
        end
    end

    assign fp32_out               = res_word;
    assign flags_out              = flags_calc;
    assign rounded_up_out         = round_up && !is_nan_in && !is_inf_in && !is_zero_in;
    assign carry_realign_out      = sig_carry_out;
    assign subnorm_promoted_out   = subnorm_promo;
    assign result_is_nan_out      = tcu_v2_fp32_is_nan(res_word);
    assign result_is_inf_out      = tcu_v2_fp32_is_inf(res_word);
    assign result_is_zero_out     = tcu_v2_fp32_is_zero(res_word);
    assign result_is_subnorm_out  = tcu_v2_fp32_is_subnormal(res_word);
    assign tie_exact_half_out     = exact_half_tie && !is_nan_in && !is_inf_in && !is_zero_in;
    assign tie_broken_even_out    = tie_exact_half_out && (rm == TCU_V2_RM_RNE) && lsb_bit;
    assign ovf_clamped_max_out    = exp_overflow && !ovf_to_inf && !is_nan_in && !is_inf_in && !is_zero_in;
    assign final_biased_exp_out   = res_word[30:23];
    assign final_mantissa_out     = res_word[22:0];
    assign fp16_downcast_out      = fp32_to_fp16_rne(res_word);
    assign bf16_downcast_out      = fp32_to_bf16_rne(res_word);
    assign ulp_parity_lsb_out     = res_word[0];
    assign subnormal_tininess_out = is_subnormal_in && !subnorm_promo;
    assign exact_normal_out       = !is_nan_in && !is_inf_in && !is_zero_in &&
                                    !exp_overflow && !exp_underflow_to_zero &&
                                    !is_subnorm_result && !inexact_tail;

    `STATIC_ASSERT(EXP_W >= 10, ("FP32 rounder requires EXP_W >= 10"))

endmodule
