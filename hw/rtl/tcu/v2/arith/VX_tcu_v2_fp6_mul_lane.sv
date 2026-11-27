// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp6_mul_lane import VX_tcu_v2_pkg::*; #(
    parameter int LANES    = TCU_V2_MAX_LANES,
    parameter int PIPE_REG = 0
) (
    input  logic                                     clk,
    input  logic                                     reset,
    input  logic                                     enable,
    input  logic                                     valid_in,
    input  tcu_v2_fmt_e                              fmt_a,
    input  tcu_v2_fmt_e                              fmt_b,
    input  tcu_v2_fp_unpacked_t [LANES-1:0]          a_in,
    input  tcu_v2_fp_unpacked_t [LANES-1:0]          b_in,
    output logic                                     valid_out,
    output logic [LANES-1:0]                         prod_sign_out,
    output logic signed [LANES-1:0][TCU_V2_FP_EXP_W-1:0] prod_exp_out,
    output logic [LANES-1:0][7:0]                    prod_mant_u1p7_out,
    output logic [LANES-1:0]                         prod_is_zero_out,
    output logic [LANES-1:0]                         prod_neg_zero_out,
    output logic [LANES-1:0]                         prod_pos_zero_out,
    output logic [LANES-1:0]                         prod_has_carry_out,
    output logic [LANES-1:0]                         prod_subnorm_any_out,
    output logic [LANES-1:0]                         prod_is_exact_int_out,
    output logic [LANES-1:0][31:0]                   prod_fp32_equiv_out,
    output logic [$clog2(LANES+1)-1:0]               active_lanes_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        min_prod_exp_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        max_prod_exp_out,
    output logic                                     all_prod_zero_out,
    output logic                                     is_mixed_mode_out,
    output logic                                     is_e2m3_mode_out,
    output logic                                     is_e3m2_mode_out,
    output logic [3:0]                               pos_prod_cnt_out,
    output logic [3:0]                               neg_prod_cnt_out
);

    localparam int EXP_W = TCU_V2_FP_EXP_W;
    localparam int SIG_W = TCU_V2_FP_SIG_W;

    function automatic logic [1:0] lzc_4bit(
        input logic [3:0] sig4
    );
        if (sig4[3]) begin
            return 2'd0;
        end else if (sig4[2]) begin
            return 2'd1;
        end else if (sig4[1]) begin
            return 2'd2;
        end else if (sig4[0]) begin
            return 2'd3;
        end else begin
            return 2'd0;
        end
    endfunction

    // Exact 4x4 unsigned significand multiplier via partial-product accumulation.
    function automatic logic [7:0] mul_u4x4_exact(
        input logic [3:0] lhs,
        input logic [3:0] rhs
    );
        logic [7:0] pp0;
        logic [7:0] pp1;
        logic [7:0] pp2;
        logic [7:0] pp3;
        pp0 = rhs[0] ? {4'b0000, lhs}         : 8'd0;
        pp1 = rhs[1] ? {3'b000,  lhs, 1'b0}   : 8'd0;
        pp2 = rhs[2] ? {2'b00,   lhs, 2'b00}  : 8'd0;
        pp3 = rhs[3] ? {1'b0,    lhs, 3'b000} : 8'd0;
        return (pp0 + pp1) + (pp2 + pp3);
    endfunction

    function automatic logic [31:0] encode_fp6_prod_fp32(
        input logic                    is_zero_b,
        input logic                    sign_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [7:0]              mant_u1p7_b
    );
        logic signed [EXP_W-1:0] fp32_e;
        if (is_zero_b || !mant_u1p7_b[7]) begin
            return {sign_b, 31'd0};
        end else begin
            fp32_e = exp_b + $signed(EXP_W'(127));
            if (fp32_e <= 0) begin
                return {sign_b, 31'd0};
            end else if (fp32_e >= 255) begin
                return sign_b ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            end else begin
                return {sign_b, fp32_e[7:0], mant_u1p7_b[6:0], 16'd0};
            end
        end
    endfunction

    function automatic logic fp6_prod_is_exact_int(
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [7:0]              mant_u1p7_b
    );
        if (is_zero_b || !mant_u1p7_b[7]) begin
            return 1'b1;
        end else if (exp_b < 0) begin
            return 1'b0;
        end else if (exp_b >= 7) begin
            return 1'b1;
        end else begin
            logic [6:0] frac_mask;
            frac_mask = 7'h7F >> exp_b[2:0];
            return ((mant_u1p7_b[6:0] & frac_mask) == 7'd0);
        end
    endfunction

    logic [LANES-1:0]                    comb_sign;
    logic signed [LANES-1:0][EXP_W-1:0]  comb_exp;
    logic [LANES-1:0][7:0]               comb_mant;
    logic [LANES-1:0]                    comb_zero;
    logic [LANES-1:0]                    comb_neg_zero;
    logic [LANES-1:0]                    comb_pos_zero;
    logic [LANES-1:0]                    comb_carry;
    logic [LANES-1:0]                    comb_subnorm_any;
    logic [LANES-1:0]                    comb_exact_int;
    logic [LANES-1:0][31:0]              comb_fp32_eq;
    logic [$clog2(LANES+1)-1:0]          comb_active;
    logic signed [EXP_W-1:0]             comb_min_exp;
    logic signed [EXP_W-1:0]             comb_max_exp;
    logic                                comb_all_zero;
    logic                                comb_mixed;
    logic                                comb_e2m3_only;
    logic                                comb_e3m2_only;
    logic [3:0]                          comb_pos_cnt;
    logic [3:0]                          comb_neg_cnt;

    assign comb_mixed     = (fmt_a != fmt_b);
    assign comb_e2m3_only = (fmt_a == TCU_V2_FMT_MXFP6_E2M3) && (fmt_b == TCU_V2_FMT_MXFP6_E2M3);
    assign comb_e3m2_only = (fmt_a == TCU_V2_FMT_MXFP6_E3M2) && (fmt_b == TCU_V2_FMT_MXFP6_E3M2);

    for (genvar i = 0; i < LANES; ++i) begin : g_fp6_mul
        logic       a_sign;
        logic       b_sign;
        logic       a_zero;
        logic       b_zero;
        logic       a_subn;
        logic       b_subn;
        logic [3:0] a_sig_raw;
        logic [3:0] b_sig_raw;

        logic [1:0] a_lzc;
        logic [1:0] b_lzc;
        logic [3:0] a_sig_norm;
        logic [3:0] b_sig_norm;

        logic signed [EXP_W-1:0] a_exp_norm;
        logic signed [EXP_W-1:0] b_exp_norm;

        logic [7:0] raw_prod_u2p6;
        logic [7:0] norm_prod_u1p7;
        logic       prod_carry;
        logic signed [EXP_W-1:0] prod_exp_sum;

        logic       lane_zero;
        logic       lane_sign;

        // Extract top 4 bits of sig (u1.3 for E2M3/FP4, or {u1.2, 1'b0} for E3M2).
        assign a_sign    = a_in[i].sign;
        assign b_sign    = b_in[i].sign;
        assign a_zero    = a_in[i].is_zero;
        assign b_zero    = b_in[i].is_zero;
        assign a_subn    = a_in[i].is_subnormal;
        assign b_subn    = b_in[i].is_subnormal;
        assign a_sig_raw = a_in[i].sig[SIG_W-1 -: 4];
        assign b_sig_raw = b_in[i].sig[SIG_W-1 -: 4];

        assign lane_zero = a_zero || b_zero || (a_sig_raw == 4'd0) || (b_sig_raw == 4'd0);
        assign lane_sign = a_sign ^ b_sign;

        assign a_lzc = a_zero ? 2'd0 : lzc_4bit(a_sig_raw);
        assign b_lzc = b_zero ? 2'd0 : lzc_4bit(b_sig_raw);

        always_comb begin
            if (a_zero) begin
                a_sig_norm = 4'b0000;
                a_exp_norm = '0;
            end else begin
                a_sig_norm = a_sig_raw << a_lzc;
                a_exp_norm = a_in[i].exp - $signed({{(EXP_W-2){1'b0}}, a_lzc});
            end

            if (b_zero) begin
                b_sig_norm = 4'b0000;
                b_exp_norm = '0;
            end else begin
                b_sig_norm = b_sig_raw << b_lzc;
                b_exp_norm = b_in[i].exp - $signed({{(EXP_W-2){1'b0}}, b_lzc});
            end
        end

        // Exact 4b x 4b unsigned significand product in u2.6 -> normalized to u1.7.
        assign raw_prod_u2p6 = mul_u4x4_exact(a_sig_norm, b_sig_norm);
        assign prod_carry    = raw_prod_u2p6[7];

        always_comb begin
            if (lane_zero) begin
                norm_prod_u1p7 = 8'd0;
                prod_exp_sum   = '0;
            end else if (prod_carry) begin
                norm_prod_u1p7 = raw_prod_u2p6;
                prod_exp_sum   = a_exp_norm + b_exp_norm + $signed(EXP_W'(1));
            end else begin
                norm_prod_u1p7 = {raw_prod_u2p6[6:0], 1'b0};
                prod_exp_sum   = a_exp_norm + b_exp_norm;
            end
        end

        assign comb_sign[i]        = lane_sign;
        assign comb_exp[i]         = prod_exp_sum;
        assign comb_mant[i]        = norm_prod_u1p7;
        assign comb_zero[i]        = lane_zero;
        assign comb_neg_zero[i]    = lane_zero && lane_sign;
        assign comb_pos_zero[i]    = lane_zero && !lane_sign;
        assign comb_carry[i]       = !lane_zero && prod_carry;
        assign comb_subnorm_any[i] = !lane_zero && (a_subn || b_subn);
        assign comb_exact_int[i]   = fp6_prod_is_exact_int(lane_zero, prod_exp_sum, norm_prod_u1p7);
        assign comb_fp32_eq[i]     = encode_fp6_prod_fp32(lane_zero, lane_sign, prod_exp_sum, norm_prod_u1p7);
    end

    always_comb begin
        logic [$clog2(LANES+1)-1:0] cnt;
        logic [3:0]                 p_cnt;
        logic [3:0]                 n_cnt;
        logic signed [EXP_W-1:0]    min_e;
        logic signed [EXP_W-1:0]    max_e;
        logic                       seen_nz;

        cnt     = '0;
        p_cnt   = 4'd0;
        n_cnt   = 4'd0;
        min_e   = $signed(EXP_W'(127));
        max_e   = $signed(EXP_W'(-128));
        seen_nz = 1'b0;

        for (int k = 0; k < LANES; ++k) begin
            if (!comb_zero[k]) begin
                cnt = cnt + {{($clog2(LANES+1)-1){1'b0}}, 1'b1};
                if (comb_sign[k]) begin
                    n_cnt = n_cnt + 4'd1;
                end else begin
                    p_cnt = p_cnt + 4'd1;
                end
                if (!seen_nz) begin
                    min_e   = comb_exp[k];
                    max_e   = comb_exp[k];
                    seen_nz = 1'b1;
                end else begin
                    if ($signed(comb_exp[k]) < $signed(min_e)) begin
                        min_e = comb_exp[k];
                    end
                    if ($signed(comb_exp[k]) > $signed(max_e)) begin
                        max_e = comb_exp[k];
                    end
                end
            end
        end

        comb_active   = cnt;
        comb_all_zero = !seen_nz;
        comb_min_exp  = seen_nz ? min_e : '0;
        comb_max_exp  = seen_nz ? max_e : '0;
        comb_pos_cnt  = p_cnt;
        comb_neg_cnt  = n_cnt;
    end

    if (PIPE_REG == 0) begin : g_comb_out
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)
        assign valid_out             = valid_in;
        assign prod_sign_out         = comb_sign;
        assign prod_exp_out          = comb_exp;
        assign prod_mant_u1p7_out    = comb_mant;
        assign prod_is_zero_out      = comb_zero;
        assign prod_neg_zero_out     = comb_neg_zero;
        assign prod_pos_zero_out     = comb_pos_zero;
        assign prod_has_carry_out    = comb_carry;
        assign prod_subnorm_any_out  = comb_subnorm_any;
        assign prod_is_exact_int_out = comb_exact_int;
        assign prod_fp32_equiv_out   = comb_fp32_eq;
        assign active_lanes_out      = comb_active;
        assign min_prod_exp_out      = comb_min_exp;
        assign max_prod_exp_out      = comb_max_exp;
        assign all_prod_zero_out     = comb_all_zero;
        assign is_mixed_mode_out     = comb_mixed;
        assign is_e2m3_mode_out      = comb_e2m3_only;
        assign is_e3m2_mode_out      = comb_e3m2_only;
        assign pos_prod_cnt_out      = comb_pos_cnt;
        assign neg_prod_cnt_out      = comb_neg_cnt;
    end else begin : g_reg_out
        logic                                reg_valid;
        logic [LANES-1:0]                    reg_sign;
        logic signed [LANES-1:0][EXP_W-1:0]  reg_exp;
        logic [LANES-1:0][7:0]               reg_mant;
        logic [LANES-1:0]                    reg_zero;
        logic [LANES-1:0]                    reg_neg_zero;
        logic [LANES-1:0]                    reg_pos_zero;
        logic [LANES-1:0]                    reg_carry;
        logic [LANES-1:0]                    reg_subnorm_any;
        logic [LANES-1:0]                    reg_exact_int;
        logic [LANES-1:0][31:0]              reg_fp32_eq;
        logic [$clog2(LANES+1)-1:0]          reg_active;
        logic signed [EXP_W-1:0]             reg_min_exp;
        logic signed [EXP_W-1:0]             reg_max_exp;
        logic                                reg_all_zero;
        logic                                reg_mixed;
        logic                                reg_e2m3_only;
        logic                                reg_e3m2_only;
        logic [3:0]                          reg_pos_cnt;
        logic [3:0]                          reg_neg_cnt;

        always_ff @(posedge clk) begin
            if (reset) begin
                reg_valid       <= 1'b0;
                reg_sign        <= '0;
                reg_exp         <= '0;
                reg_mant        <= '0;
                reg_zero        <= {LANES{1'b1}};
                reg_neg_zero    <= '0;
                reg_pos_zero    <= {LANES{1'b1}};
                reg_carry       <= '0;
                reg_subnorm_any <= '0;
                reg_exact_int   <= {LANES{1'b1}};
                reg_fp32_eq     <= '0;
                reg_active      <= '0;
                reg_min_exp     <= '0;
                reg_max_exp     <= '0;
                reg_all_zero    <= 1'b1;
                reg_mixed       <= 1'b0;
                reg_e2m3_only   <= 1'b0;
                reg_e3m2_only   <= 1'b0;
                reg_pos_cnt     <= 4'd0;
                reg_neg_cnt     <= 4'd0;
            end else if (enable) begin
                reg_valid       <= valid_in;
                reg_sign        <= comb_sign;
                reg_exp         <= comb_exp;
                reg_mant        <= comb_mant;
                reg_zero        <= comb_zero;
                reg_neg_zero    <= comb_neg_zero;
                reg_pos_zero    <= comb_pos_zero;
                reg_carry       <= comb_carry;
                reg_subnorm_any <= comb_subnorm_any;
                reg_exact_int   <= comb_exact_int;
                reg_fp32_eq     <= comb_fp32_eq;
                reg_active      <= comb_active;
                reg_min_exp     <= comb_min_exp;
                reg_max_exp     <= comb_max_exp;
                reg_all_zero    <= comb_all_zero;
                reg_mixed       <= comb_mixed;
                reg_e2m3_only   <= comb_e2m3_only;
                reg_e3m2_only   <= comb_e3m2_only;
                reg_pos_cnt     <= comb_pos_cnt;
                reg_neg_cnt     <= comb_neg_cnt;
            end
        end

        assign valid_out             = reg_valid;
        assign prod_sign_out         = reg_sign;
        assign prod_exp_out          = reg_exp;
        assign prod_mant_u1p7_out    = reg_mant;
        assign prod_is_zero_out      = reg_zero;
        assign prod_neg_zero_out     = reg_neg_zero;
        assign prod_pos_zero_out     = reg_pos_zero;
        assign prod_has_carry_out    = reg_carry;
        assign prod_subnorm_any_out  = reg_subnorm_any;
        assign prod_is_exact_int_out = reg_exact_int;
        assign prod_fp32_equiv_out   = reg_fp32_eq;
        assign active_lanes_out      = reg_active;
        assign min_prod_exp_out      = reg_min_exp;
        assign max_prod_exp_out      = reg_max_exp;
        assign all_prod_zero_out     = reg_all_zero;
        assign is_mixed_mode_out     = reg_mixed;
        assign is_e2m3_mode_out      = reg_e2m3_only;
        assign is_e3m2_mode_out      = reg_e3m2_only;
        assign pos_prod_cnt_out      = reg_pos_cnt;
        assign neg_prod_cnt_out      = reg_neg_cnt;
    end

endmodule
