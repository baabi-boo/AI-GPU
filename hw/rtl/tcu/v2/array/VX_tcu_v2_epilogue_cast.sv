// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_EPILOGUE_CAST_SV
`define VX_TCU_V2_EPILOGUE_CAST_SV

`include "VX_platform.vh"

module VX_tcu_v2_epilogue_cast #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    in_valid,
    output logic                                    in_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t              uop_in,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   tile_in,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_in,
    input  logic [31:0]                             dyn_scale_fp32,
    input  logic                                    dyn_scale_en,
    output logic                                    out_valid,
    input  logic                                    out_ready,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   d_tile_out,
    output logic [7:0]                              out_desc_id,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_out
);

    import VX_tcu_v2_pkg::*;

    // -------------------------------------------------------------------------
    // Dynamic Scale Multiplier & Multi-Format RNE Down-Cast Helpers
    // -------------------------------------------------------------------------
    function automatic logic [31:0] fp32_scale_mul(
        input logic [31:0] a,
        input logic [31:0] b
    );
        logic        sa, sb, sr;
        logic [7:0]  ea, eb;
        logic [22:0] ma, mb;
        logic        a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        logic [23:0] sig_a, sig_b;
        logic signed [9:0] exp_a, exp_b, exp_prod, exp_final;
        logic [4:0]  lzc_a, lzc_b;
        logic [47:0] prod;
        logic [23:0] mant_24;
        logic        guard, round_bit, sticky, round_up;
        logic [24:0] mant_rnd;
        logic [22:0] man_final;

        sa = a[31];
        sb = b[31];
        sr = sa ^ sb;
        ea = a[30:23];
        eb = b[30:23];
        ma = a[22:0];
        mb = b[22:0];

        a_nan  = (ea == 8'hFF) && (ma != 23'd0);
        b_nan  = (eb == 8'hFF) && (mb != 23'd0);
        a_inf  = (ea == 8'hFF) && (ma == 23'd0);
        b_inf  = (eb == 8'hFF) && (mb == 23'd0);
        a_zero = (ea == 8'd0)  && (ma == 23'd0);
        b_zero = (eb == 8'd0)  && (mb == 23'd0);

        if (a_nan || b_nan || (a_inf && b_zero) || (b_inf && a_zero)) begin
            return TCU_V2_CANONICAL_QNAN;
        end
        if (a_inf || b_inf) begin
            return sr ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end
        if (a_zero || b_zero) begin
            return sr ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
        end

        sig_a = (ea == 8'd0) ? {1'b0, ma} : {1'b1, ma};
        sig_b = (eb == 8'd0) ? {1'b0, mb} : {1'b1, mb};
        exp_a = (ea == 8'd0) ? $signed(10'd1) : $signed({2'b00, ea});
        exp_b = (eb == 8'd0) ? $signed(10'd1) : $signed({2'b00, eb});

        lzc_a = 5'd0;
        for (int i = 23; i >= 0; --i) begin
            if ((lzc_a == 5'(23 - i)) && !sig_a[i]) begin
                lzc_a = lzc_a + 5'd1;
            end
        end
        lzc_b = 5'd0;
        for (int i = 23; i >= 0; --i) begin
            if ((lzc_b == 5'(23 - i)) && !sig_b[i]) begin
                lzc_b = lzc_b + 5'd1;
            end
        end

        sig_a    = sig_a << lzc_a;
        sig_b    = sig_b << lzc_b;
        exp_a    = exp_a - $signed({5'b0, lzc_a});
        exp_b    = exp_b - $signed({5'b0, lzc_b});
        prod     = 48'(sig_a) * 48'(sig_b);
        exp_prod = exp_a + exp_b - $signed(10'd127);

        if (prod[47]) begin
            exp_prod  = exp_prod + $signed(10'd1);
            mant_24   = prod[47:24];
            guard     = prod[23];
            round_bit = prod[22];
            sticky    = |prod[21:0];
        end else begin
            mant_24   = prod[46:23];
            guard     = prod[22];
            round_bit = prod[21];
            sticky    = |prod[20:0];
        end

        if (exp_prod <= $signed(10'd0)) begin
            logic [9:0] rsh;
            rsh = 10'($signed(10'd1) - exp_prod);
            if (rsh >= 10'd26) begin
                return sr ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
            end
            begin
                logic [26:0] sub_pack;
                logic        sub_sticky;
                sub_pack   = {mant_24, guard, round_bit, sticky};
                sub_sticky = 1'b0;
                for (int b_i = 0; b_i < 27; ++b_i) begin
                    if (b_i < int'(rsh)) begin
                        sub_sticky = sub_sticky || sub_pack[b_i];
                    end
                end
                sub_pack  = sub_pack >> rsh;
                mant_24   = sub_pack[26:3];
                guard     = sub_pack[2];
                round_bit = sub_pack[1];
                sticky    = sub_pack[0] | sub_sticky;
                exp_prod  = $signed(10'd1);
            end
        end

        round_up  = guard && (round_bit || sticky || mant_24[0]);
        mant_rnd  = {1'b0, mant_24} + {24'd0, round_up};
        exp_final = exp_prod;
        if (mant_rnd[24]) begin
            man_final = mant_rnd[23:1];
            exp_final = exp_prod + $signed(10'd1);
        end else begin
            man_final = mant_rnd[22:0];
        end

        if (exp_final >= $signed(10'd255)) begin
            return sr ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end
        if ((exp_final == $signed(10'd1)) && !mant_rnd[23]) begin
            return {sr, 8'd0, man_final};
        end
        return {sr, exp_final[7:0], man_final};
    endfunction

    function automatic logic round_decision(
        input logic       sign,
        input logic       lsb,
        input logic       guard,
        input logic       sticky,
        input tcu_v2_rm_e rm
    );
        logic inexact;
        inexact = guard || sticky;
        case (rm)
            TCU_V2_RM_RNE: return guard && (sticky || lsb);
            TCU_V2_RM_RTZ: return 1'b0;
            TCU_V2_RM_RDN: return sign && inexact;
            TCU_V2_RM_RUP: return !sign && inexact;
            TCU_V2_RM_RMM: return guard;
            default:       return guard && (sticky || lsb);
        endcase
    endfunction

    // Helper: select directed-rounding overflow value (+/-Inf vs +/-max_finite)
    function automatic logic [15:0] select_ovf_16(
        input logic        sign,
        input tcu_v2_rm_e  rm,
        input logic [14:0] pos_inf_mag,
        input logic [14:0] pos_max_mag
    );
        logic use_max;
        case (rm)
            TCU_V2_RM_RTZ: use_max = 1'b1;
            TCU_V2_RM_RDN: use_max = !sign;
            TCU_V2_RM_RUP: use_max = sign;
            default:       use_max = 1'b0;
        endcase
        return {sign, use_max ? pos_max_mag : pos_inf_mag};
    endfunction

    function automatic logic [7:0] select_ovf_8(
        input logic       sign,
        input tcu_v2_rm_e rm,
        input logic       has_inf,
        input logic [6:0] pos_inf_mag,
        input logic [6:0] pos_max_mag
    );
        logic use_max;
        if (!has_inf) begin
            use_max = 1'b1;
        end else begin
            case (rm)
                TCU_V2_RM_RTZ: use_max = 1'b1;
                TCU_V2_RM_RDN: use_max = !sign;
                TCU_V2_RM_RUP: use_max = sign;
                default:       use_max = 1'b0;
            endcase
        end
        return {sign, use_max ? pos_max_mag : pos_inf_mag};
    endfunction

    // Convert FP32 to BF16 (packed into low 16 bits of 32-bit lane)
    function automatic logic [20:0] cast_fp32_to_bf16(
        input logic [31:0]  val,
        input tcu_v2_rm_e   rm
    );
        logic             s;
        logic [7:0]       e;
        logic [22:0]      m;
        logic             guard, sticky, rnd_up, inexact;
        logic [15:0]      bf16_bits;
        logic [15:0]      bf16_mag;
        tcu_v2_fp_flags_t flg;

        flg = '0;
        s   = val[31];
        e   = val[30:23];
        m   = val[22:0];

        if (e == 8'hFF) begin
            if (m != 23'd0) begin
                flg.nv    = !m[22];
                bf16_bits = 16'h7FC0;
            end else begin
                bf16_bits = {s, 8'hFF, 7'd0};
            end
            return {flg, bf16_bits};
        end

        guard    = m[15];
        sticky   = |m[14:0];
        inexact  = guard || sticky;
        rnd_up   = round_decision(s, m[16], guard, sticky, rm);
        bf16_mag = {1'b0, e, m[22:16]} + {15'd0, rnd_up};

        if (bf16_mag[15] || (bf16_mag[14:7] == 8'hFF)) begin
            flg.of    = 1'b1;
            flg.nx    = 1'b1;
            bf16_bits = select_ovf_16(s, rm, 15'h7F80, 15'h7F7F);
        end else begin
            bf16_bits = {s, bf16_mag[14:0]};
            flg.nx    = inexact;
            flg.uf    = (bf16_bits[14:7] == 8'h00) && inexact;
        end
        return {flg, bf16_bits};
    endfunction

    // Convert FP32 to IEEE FP16 (5-bit exponent bias 15, 10-bit mantissa)
    function automatic logic [20:0] cast_fp32_to_fp16(
        input logic [31:0]  val,
        input tcu_v2_rm_e   rm
    );
        logic             s;
        logic [7:0]       e;
        logic [22:0]      m;
        logic signed [9:0] exp_unbiased;
        logic [23:0]      sig;
        logic [10:0]      mant11;
        logic             guard, sticky, rnd_up, inexact;
        logic [11:0]      mant_rnd;
        logic signed [9:0] exp16;
        logic [15:0]      fp16_bits;
        tcu_v2_fp_flags_t flg;

        flg = '0;
        s   = val[31];
        e   = val[30:23];
        m   = val[22:0];

        if (e == 8'hFF) begin
            if (m != 23'd0) begin
                flg.nv    = !m[22];
                fp16_bits = 16'h7E00;
            end else begin
                fp16_bits = {s, 5'h1F, 10'd0};
            end
            return {flg, fp16_bits};
        end
        if ((e == 8'd0) && (m == 23'd0)) begin
            return {flg, s, 15'd0};
        end

        exp_unbiased = (e == 8'd0) ? $signed(-10'd126) : ($signed({2'b00, e}) - $signed(10'd127));
        sig          = (e == 8'd0) ? {1'b0, m} : {1'b1, m};
        exp16        = exp_unbiased + $signed(10'd15);

        if (exp16 >= $signed(10'd31)) begin
            flg.of    = 1'b1;
            flg.nx    = 1'b1;
            fp16_bits = select_ovf_16(s, rm, 15'h7C00, 15'h7BFF);
            return {flg, fp16_bits};
        end

        if (exp16 <= $signed(10'd0)) begin
            logic [9:0] rsh;
            rsh = 10'($signed(10'd1) - exp16);
            if (rsh >= 10'd25) begin
                logic round_to_min_sub;
                round_to_min_sub = ((rm == TCU_V2_RM_RUP) && !s) || ((rm == TCU_V2_RM_RDN) && s);
                flg.uf           = 1'b1;
                flg.nx           = 1'b1;
                fp16_bits        = round_to_min_sub ? {s, 15'd1} : {s, 15'd0};
                return {flg, fp16_bits};
            end
            begin
                logic [24:0] pack;
                logic        sub_sticky;
                pack       = {sig, 1'b0};
                sub_sticky = 1'b0;
                for (int b_i = 0; b_i < 25; ++b_i) begin
                    if (b_i < int'(rsh) + 13) begin
                        sub_sticky = sub_sticky || pack[b_i];
                    end
                end
                pack    = pack >> rsh;
                mant11  = pack[24:14];
                guard   = pack[13];
                sticky  = sub_sticky;
                exp16   = $signed(10'd0);
            end
        end else begin
            mant11 = sig[23:13];
            guard  = sig[12];
            sticky = |sig[11:0];
        end

        inexact  = guard || sticky;
        rnd_up   = round_decision(s, mant11[0], guard, sticky, rm);
        mant_rnd = {1'b0, mant11} + {11'd0, rnd_up};

        if ((exp16 == $signed(10'd0)) && mant_rnd[10]) begin
            exp16     = $signed(10'd1);
            fp16_bits = {s, 5'd1, mant_rnd[9:0]};
        end else if (mant_rnd[11]) begin
            exp16 = exp16 + $signed(10'd1);
            if (exp16 >= $signed(10'd31)) begin
                flg.of    = 1'b1;
                fp16_bits = select_ovf_16(s, rm, 15'h7C00, 15'h7BFF);
            end else begin
                fp16_bits = {s, exp16[4:0], mant_rnd[10:1]};
            end
        end else begin
            fp16_bits = {s, exp16[4:0], mant_rnd[9:0]};
        end

        flg.nx = inexact || flg.of;
        flg.uf = (exp16 == $signed(10'd0)) && inexact;
        return {flg, fp16_bits};
    endfunction

    // Convert FP32 to OFG FP8 E4M3FN (bias=7, no Inf, NaN=S.1111.111, max finite=448)
    function automatic logic [12:0] cast_fp32_to_e4m3(
        input logic [31:0]  val,
        input tcu_v2_rm_e   rm
    );
        logic             s;
        logic [7:0]       e;
        logic [22:0]      m;
        logic signed [9:0] exp_unbiased, exp8;
        logic [23:0]      sig;
        logic [3:0]       mant4;
        logic             guard, sticky, rnd_up, inexact;
        logic [4:0]       mant_rnd;
        logic [7:0]       fp8_bits;
        tcu_v2_fp_flags_t flg;

        flg = '0;
        s   = val[31];
        e   = val[30:23];
        m   = val[22:0];

        if (e == 8'hFF) begin
            flg.nv   = (m == 23'd0) || !m[22];
            flg.of   = (m == 23'd0);
            fp8_bits = (m == 23'd0) ? {s, 4'hF, 3'h6} : {s, 4'hF, 3'h7};
            return {flg, fp8_bits};
        end
        if ((e == 8'd0) && (m == 23'd0)) begin
            return {flg, s, 7'd0};
        end

        exp_unbiased = (e == 8'd0) ? $signed(-10'd126) : ($signed({2'b00, e}) - $signed(10'd127));
        sig          = (e == 8'd0) ? {1'b0, m} : {1'b1, m};
        exp8         = exp_unbiased + $signed(10'd7);

        if (exp8 > $signed(10'd15)) begin
            flg.of   = 1'b1;
            flg.nx   = 1'b1;
            fp8_bits = select_ovf_8(s, rm, 1'b0, 7'h7F, 7'h7E);
            return {flg, fp8_bits};
        end

        if (exp8 <= $signed(10'd0)) begin
            logic [9:0] rsh;
            rsh = 10'($signed(10'd1) - exp8);
            if (rsh >= 10'd8) begin
                logic round_to_min_sub;
                round_to_min_sub = ((rm == TCU_V2_RM_RUP) && !s) || ((rm == TCU_V2_RM_RDN) && s);
                flg.uf           = 1'b1;
                flg.nx           = 1'b1;
                fp8_bits         = round_to_min_sub ? {s, 7'd1} : {s, 7'd0};
                return {flg, fp8_bits};
            end
            begin
                logic [24:0] pack;
                logic        sub_sticky;
                pack       = {sig, 1'b0};
                sub_sticky = |pack[19:0];
                for (int b_i = 0; b_i < 25; ++b_i) begin
                    if (b_i < int'(rsh) + 20) begin
                        sub_sticky = sub_sticky || pack[b_i];
                    end
                end
                pack   = pack >> rsh;
                mant4  = pack[24:21];
                guard  = pack[20];
                sticky = sub_sticky;
                exp8   = $signed(10'd0);
            end
        end else begin
            mant4  = sig[23:20];
            guard  = sig[19];
            sticky = |sig[18:0];
        end

        inexact  = guard || sticky;
        rnd_up   = round_decision(s, mant4[0], guard, sticky, rm);
        mant_rnd = {1'b0, mant4} + {4'd0, rnd_up};

        if ((exp8 == $signed(10'd0)) && mant_rnd[3]) begin
            exp8     = $signed(10'd1);
            fp8_bits = {s, 4'd1, mant_rnd[2:0]};
        end else if (mant_rnd[4]) begin
            exp8 = exp8 + $signed(10'd1);
            if ((exp8 > $signed(10'd15)) || ((exp8 == $signed(10'd15)) && (mant_rnd[3:1] == 3'h7))) begin
                flg.of   = 1'b1;
                fp8_bits = select_ovf_8(s, rm, 1'b0, 7'h7F, 7'h7E);
            end else begin
                fp8_bits = {s, exp8[3:0], mant_rnd[3:1]};
            end
        end else if ((exp8 == $signed(10'd15)) && (mant_rnd[2:0] == 3'h7)) begin
            flg.of   = 1'b1;
            fp8_bits = select_ovf_8(s, rm, 1'b0, 7'h7F, 7'h7E);
        end else begin
            fp8_bits = {s, exp8[3:0], mant_rnd[2:0]};
        end

        flg.nx = inexact || flg.of;
        flg.uf = (exp8 == $signed(10'd0)) && inexact;
        return {flg, fp8_bits};
    endfunction

    // Convert FP32 to FP8 E5M2 (bias=15, Inf=S.11111.00, NaN=S.11111.xx)
    function automatic logic [12:0] cast_fp32_to_e5m2(
        input logic [31:0]  val,
        input tcu_v2_rm_e   rm
    );
        logic             s;
        logic [7:0]       e;
        logic [22:0]      m;
        logic signed [9:0] exp_unbiased, exp8;
        logic [23:0]      sig;
        logic [2:0]       mant3;
        logic             guard, sticky, rnd_up, inexact;
        logic [3:0]       mant_rnd;
        logic [7:0]       fp8_bits;
        tcu_v2_fp_flags_t flg;

        flg = '0;
        s   = val[31];
        e   = val[30:23];
        m   = val[22:0];

        if (e == 8'hFF) begin
            if (m != 23'd0) begin
                flg.nv   = !m[22];
                fp8_bits = {s, 5'h1F, 2'b10};
            end else begin
                fp8_bits = {s, 5'h1F, 2'b00};
            end
            return {flg, fp8_bits};
        end
        if ((e == 8'd0) && (m == 23'd0)) begin
            return {flg, s, 7'd0};
        end

        exp_unbiased = (e == 8'd0) ? $signed(-10'd126) : ($signed({2'b00, e}) - $signed(10'd127));
        sig          = (e == 8'd0) ? {1'b0, m} : {1'b1, m};
        exp8         = exp_unbiased + $signed(10'd15);

        if (exp8 >= $signed(10'd31)) begin
            flg.of   = 1'b1;
            flg.nx   = 1'b1;
            fp8_bits = select_ovf_8(s, rm, 1'b1, 7'h7C, 7'h7B);
            return {flg, fp8_bits};
        end

        if (exp8 <= $signed(10'd0)) begin
            logic [9:0] rsh;
            rsh = 10'($signed(10'd1) - exp8);
            if (rsh >= 10'd6) begin
                logic round_to_min_sub;
                round_to_min_sub = ((rm == TCU_V2_RM_RUP) && !s) || ((rm == TCU_V2_RM_RDN) && s);
                flg.uf           = 1'b1;
                flg.nx           = 1'b1;
                fp8_bits         = round_to_min_sub ? {s, 7'd1} : {s, 7'd0};
                return {flg, fp8_bits};
            end
            begin
                logic [24:0] pack;
                logic        sub_sticky;
                pack       = {sig, 1'b0};
                sub_sticky = |pack[20:0];
                for (int b_i = 0; b_i < 25; ++b_i) begin
                    if (b_i < int'(rsh) + 21) begin
                        sub_sticky = sub_sticky || pack[b_i];
                    end
                end
                pack   = pack >> rsh;
                mant3  = pack[24:22];
                guard  = pack[21];
                sticky = sub_sticky;
                exp8   = $signed(10'd0);
            end
        end else begin
            mant3  = sig[23:21];
            guard  = sig[20];
            sticky = |sig[19:0];
        end

        inexact  = guard || sticky;
        rnd_up   = round_decision(s, mant3[0], guard, sticky, rm);
        mant_rnd = {1'b0, mant3} + {3'd0, rnd_up};

        if ((exp8 == $signed(10'd0)) && mant_rnd[2]) begin
            exp8     = $signed(10'd1);
            fp8_bits = {s, 5'd1, mant_rnd[1:0]};
        end else if (mant_rnd[3]) begin
            exp8 = exp8 + $signed(10'd1);
            if (exp8 >= $signed(10'd31)) begin
                flg.of   = 1'b1;
                fp8_bits = select_ovf_8(s, rm, 1'b1, 7'h7C, 7'h7B);
            end else begin
                fp8_bits = {s, exp8[4:0], mant_rnd[2:1]};
            end
        end else begin
            fp8_bits = {s, exp8[4:0], mant_rnd[1:0]};
        end

        flg.nx = inexact || flg.of;
        flg.uf = (exp8 == $signed(10'd0)) && inexact;
        return {flg, fp8_bits};
    endfunction

    // Convert FP32 or INT32 to clamped signed INT8
    function automatic logic [12:0] cast_to_int8(
        input logic [31:0]  val,
        input logic         src_is_int,
        input tcu_v2_rm_e   rm
    );
        logic signed [31:0] int_val;
        logic [7:0]         i8_bits;
        tcu_v2_fp_flags_t   flg;

        flg = '0;
        if (src_is_int) begin
            int_val = $signed(val);
            if (int_val > 32'sd127) begin
                i8_bits = 8'h7F;
                flg.of  = 1'b1;
                flg.nx  = 1'b1;
            end else if (int_val < -32'sd128) begin
                i8_bits = 8'h80;
                flg.of  = 1'b1;
                flg.nx  = 1'b1;
            end else begin
                i8_bits = int_val[7:0];
            end
            return {flg, i8_bits};
        end

        if (tcu_v2_fp32_is_nan(val)) begin
            flg.nv = 1'b1;
            return {flg, 8'd0};
        end
        if (tcu_v2_fp32_is_inf(val)) begin
            flg.of  = 1'b1;
            flg.nx  = 1'b1;
            i8_bits = val[31] ? 8'h80 : 8'h7F;
            return {flg, i8_bits};
        end
        if (tcu_v2_fp32_is_zero(val)) begin
            return {flg, 8'd0};
        end

        begin
            logic        s;
            logic [7:0]  e;
            logic [22:0] m;
            logic signed [9:0] exp_unbiased;
            logic [31:0] mag;
            logic [23:0] sig;
            logic        frac_any, half_bit, sticky_f, inc;
            logic signed [15:0] signed_mag;

            s            = val[31];
            e            = val[30:23];
            m            = val[22:0];
            exp_unbiased = (e == 8'd0) ? $signed(-10'd126) : ($signed({2'b00, e}) - $signed(10'd127));
            sig          = (e == 8'd0) ? {1'b0, m} : {1'b1, m};

            if (exp_unbiased < $signed(10'd0)) begin
                mag      = 32'd0;
                half_bit = (exp_unbiased == $signed(-10'd1)) && sig[23];
                sticky_f = (exp_unbiased < $signed(-10'd1)) || (|sig[22:0]);
                frac_any = 1'b1;
            end else if (exp_unbiased >= $signed(10'd8)) begin
                flg.of  = 1'b1;
                flg.nx  = 1'b1;
                i8_bits = s ? 8'h80 : 8'h7F;
                return {flg, i8_bits};
            end else begin
                logic [31:0] shifted;
                shifted  = {8'd0, sig} << exp_unbiased;
                mag      = shifted >> 23;
                half_bit = shifted[22];
                sticky_f = |shifted[21:0];
                frac_any = half_bit || sticky_f;
            end

            inc        = round_decision(s, mag[0], half_bit, sticky_f, rm);
            mag        = mag + {31'd0, inc};
            signed_mag = s ? -$signed(mag[15:0]) : $signed(mag[15:0]);
            flg.nx     = frac_any;

            if (signed_mag > 16'sd127) begin
                flg.of  = 1'b1;
                flg.nx  = 1'b1;
                i8_bits = 8'h7F;
            end else if (signed_mag < -16'sd128) begin
                flg.of  = 1'b1;
                flg.nx  = 1'b1;
                i8_bits = 8'h80;
            end else begin
                i8_bits = signed_mag[7:0];
            end
        end
        return {flg, i8_bits};
    endfunction

    // -------------------------------------------------------------------------
    // Stage 1 Dynamic Scale Multiply -> Stage 2 Multi-Format Down-Cast
    // -------------------------------------------------------------------------
    logic                                  st1_valid_r;
    tcu_v2_uop_t                           st1_uop_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] st1_scaled_tile_r;
    tcu_v2_fp_flags_t                      st1_flags_r;
    logic                                  st1_ready;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] st1_scale_comb;
    tcu_v2_fp_flags_t                      st1_flags_comb;
    logic                                  st1_src_is_int;

    assign in_ready = !st1_valid_r || st1_ready;

    always_comb begin
        logic [31:0] scaled_elem;
        st1_src_is_int = tcu_v2_fmt_is_int(uop_in.fmt_a) && tcu_v2_fmt_is_int(uop_in.fmt_b);
        st1_flags_comb = flags_in;
        scaled_elem    = 32'd0;

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                if (dyn_scale_en && !st1_src_is_int) begin
                    scaled_elem = fp32_scale_mul(tile_in[r][c], dyn_scale_fp32);
                    if (tcu_v2_fp32_is_inf(scaled_elem) && !tcu_v2_fp32_is_inf(tile_in[r][c]) &&
                        !tcu_v2_fp32_is_inf(dyn_scale_fp32)) begin
                        st1_flags_comb.of = 1'b1;
                        st1_flags_comb.nx = 1'b1;
                    end
                    if (tcu_v2_fp32_is_nan(scaled_elem) && !tcu_v2_fp32_is_nan(tile_in[r][c]) &&
                        !tcu_v2_fp32_is_nan(dyn_scale_fp32)) begin
                        st1_flags_comb.nv = 1'b1;
                    end
                    st1_scale_comb[r][c] = scaled_elem;
                end else begin
                    st1_scale_comb[r][c] = tile_in[r][c];
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            st1_valid_r       <= 1'b0;
            st1_uop_r         <= '0;
            st1_scaled_tile_r <= '0;
            st1_flags_r       <= '0;
        end else if (in_valid && in_ready) begin
            st1_valid_r       <= 1'b1;
            st1_uop_r         <= uop_in;
            st1_scaled_tile_r <= st1_scale_comb;
            st1_flags_r       <= st1_flags_comb;
        end else if (st1_valid_r && st1_ready) begin
            st1_valid_r <= 1'b0;
        end
    end

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] cast_tile_comb;
    tcu_v2_fp_flags_t                      cast_flags_comb;
    logic                                  src_is_int;

    always_comb begin
        logic [20:0] cast16_res;
        logic [12:0] cast8_res;
        src_is_int      = tcu_v2_fmt_is_int(st1_uop_r.fmt_a) && tcu_v2_fmt_is_int(st1_uop_r.fmt_b);
        cast_flags_comb = st1_flags_r;
        cast16_res      = 21'd0;
        cast8_res       = 13'd0;

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                case (st1_uop_r.fmt_d)
                    TCU_V2_FMT_FP32,
                    TCU_V2_FMT_I32: begin
                        cast_tile_comb[r][c] = st1_scaled_tile_r[r][c];
                    end
                    TCU_V2_FMT_BF16: begin
                        cast16_res           = cast_fp32_to_bf16(st1_scaled_tile_r[r][c], st1_uop_r.rm);
                        cast_tile_comb[r][c] = {16'd0, cast16_res[15:0]};
                        cast_flags_comb      = tcu_v2_flags_or(cast_flags_comb, tcu_v2_fp_flags_t'(cast16_res[20:16]));
                    end
                    TCU_V2_FMT_FP16: begin
                        cast16_res           = cast_fp32_to_fp16(st1_scaled_tile_r[r][c], st1_uop_r.rm);
                        cast_tile_comb[r][c] = {16'd0, cast16_res[15:0]};
                        cast_flags_comb      = tcu_v2_flags_or(cast_flags_comb, tcu_v2_fp_flags_t'(cast16_res[20:16]));
                    end
                    TCU_V2_FMT_FP8_E4M3,
                    TCU_V2_FMT_MXFP8_E4M3: begin
                        cast8_res            = cast_fp32_to_e4m3(st1_scaled_tile_r[r][c], st1_uop_r.rm);
                        cast_tile_comb[r][c] = {24'd0, cast8_res[7:0]};
                        cast_flags_comb      = tcu_v2_flags_or(cast_flags_comb, tcu_v2_fp_flags_t'(cast8_res[12:8]));
                    end
                    TCU_V2_FMT_FP8_E5M2,
                    TCU_V2_FMT_MXFP8_E5M2: begin
                        cast8_res            = cast_fp32_to_e5m2(st1_scaled_tile_r[r][c], st1_uop_r.rm);
                        cast_tile_comb[r][c] = {24'd0, cast8_res[7:0]};
                        cast_flags_comb      = tcu_v2_flags_or(cast_flags_comb, tcu_v2_fp_flags_t'(cast8_res[12:8]));
                    end
                    TCU_V2_FMT_INT8: begin
                        cast8_res            = cast_to_int8(st1_scaled_tile_r[r][c], src_is_int, st1_uop_r.rm);
                        cast_tile_comb[r][c] = {{24{cast8_res[7]}}, cast8_res[7:0]};
                        cast_flags_comb      = tcu_v2_flags_or(cast_flags_comb, tcu_v2_fp_flags_t'(cast8_res[12:8]));
                    end
                    default: begin
                        cast_tile_comb[r][c] = st1_scaled_tile_r[r][c];
                    end
                endcase
            end
        end
    end

    logic                                  out_valid_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] d_tile_out_r;
    logic [7:0]                            out_desc_id_r;
    tcu_v2_fp_flags_t                      flags_out_r;
    logic [31:0]                           cast_tiles_done_r;
    logic [31:0]                           cast_ovf_tiles_r;
    logic [31:0]                           cast_uf_tiles_r;
    logic [31:0]                           cast_nx_tiles_r;
    logic [31:0]                           cast_bf16_tiles_r;
    logic [31:0]                           cast_fp16_tiles_r;
    logic [31:0]                           cast_fp8_tiles_r;
    logic [31:0]                           cast_int8_tiles_r;
    logic [31:0]                           cast_stall_cycles_r;

    assign st1_ready = !out_valid_r || out_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            out_valid_r         <= 1'b0;
            d_tile_out_r        <= '0;
            out_desc_id_r       <= 8'd0;
            flags_out_r         <= '0;
            cast_tiles_done_r   <= 32'd0;
            cast_ovf_tiles_r    <= 32'd0;
            cast_uf_tiles_r     <= 32'd0;
            cast_nx_tiles_r     <= 32'd0;
            cast_bf16_tiles_r   <= 32'd0;
            cast_fp16_tiles_r   <= 32'd0;
            cast_fp8_tiles_r    <= 32'd0;
            cast_int8_tiles_r   <= 32'd0;
            cast_stall_cycles_r <= 32'd0;
        end else begin
            if (out_valid_r && !out_ready) begin
                cast_stall_cycles_r <= cast_stall_cycles_r + 32'd1;
            end
            if (st1_valid_r && st1_ready) begin
                out_valid_r       <= 1'b1;
                d_tile_out_r      <= cast_tile_comb;
                out_desc_id_r     <= st1_uop_r.desc_id;
                flags_out_r       <= cast_flags_comb;
                cast_tiles_done_r <= cast_tiles_done_r + 32'd1;
                if (cast_flags_comb.of) begin
                    cast_ovf_tiles_r <= cast_ovf_tiles_r + 32'd1;
                end
                if (cast_flags_comb.uf) begin
                    cast_uf_tiles_r <= cast_uf_tiles_r + 32'd1;
                end
                if (cast_flags_comb.nx) begin
                    cast_nx_tiles_r <= cast_nx_tiles_r + 32'd1;
                end
                case (st1_uop_r.fmt_d)
                    TCU_V2_FMT_BF16:      cast_bf16_tiles_r <= cast_bf16_tiles_r + 32'd1;
                    TCU_V2_FMT_FP16:      cast_fp16_tiles_r <= cast_fp16_tiles_r + 32'd1;
                    TCU_V2_FMT_FP8_E4M3,
                    TCU_V2_FMT_FP8_E5M2,
                    TCU_V2_FMT_MXFP8_E4M3,
                    TCU_V2_FMT_MXFP8_E5M2: cast_fp8_tiles_r <= cast_fp8_tiles_r + 32'd1;
                    TCU_V2_FMT_INT8:      cast_int8_tiles_r <= cast_int8_tiles_r + 32'd1;
                    default: ;
                endcase
            end else if (out_valid_r && out_ready) begin
                out_valid_r <= 1'b0;
            end
        end
    end

    `UNUSED_VAR (cast_tiles_done_r)
    `UNUSED_VAR (cast_ovf_tiles_r)
    `UNUSED_VAR (cast_uf_tiles_r)
    `UNUSED_VAR (cast_nx_tiles_r)
    `UNUSED_VAR (cast_bf16_tiles_r)
    `UNUSED_VAR (cast_fp16_tiles_r)
    `UNUSED_VAR (cast_fp8_tiles_r)
    `UNUSED_VAR (cast_int8_tiles_r)
    `UNUSED_VAR (cast_stall_cycles_r)
    `UNUSED_VAR (st1_uop_r)

    assign out_valid   = out_valid_r;
    assign d_tile_out  = d_tile_out_r;
    assign out_desc_id = out_desc_id_r;
    assign flags_out   = flags_out_r;

endmodule

`endif // VX_TCU_V2_EPILOGUE_CAST_SV
