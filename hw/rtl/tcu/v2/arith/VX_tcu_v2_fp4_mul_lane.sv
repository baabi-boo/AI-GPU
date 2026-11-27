// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp4_mul_lane import VX_tcu_v2_pkg::*; #(
    parameter int LANES    = TCU_V2_MAX_LANES,
    parameter int PIPE_REG = 0
) (
    input  logic                                     clk,
    input  logic                                     reset,
    input  logic                                     enable,
    input  logic                                     valid_in,
    input  tcu_v2_fp_unpacked_t [LANES-1:0]          a_in,
    input  tcu_v2_fp_unpacked_t [LANES-1:0]          b_in,
    output logic                                     valid_out,
    output logic [LANES-1:0]                         prod_sign_out,
    output logic signed [LANES-1:0][TCU_V2_FP_EXP_W-1:0] prod_exp_out,
    output logic [LANES-1:0][3:0]                    prod_mant_u1p3_out,
    output logic [LANES-1:0]                         prod_is_zero_out,
    output logic [LANES-1:0]                         prod_neg_zero_out,
    output logic [LANES-1:0]                         prod_pos_zero_out,
    output logic [LANES-1:0]                         prod_has_carry_out,
    output logic [LANES-1:0]                         prod_subnorm_pair_out,
    output logic [LANES-1:0]                         prod_is_exact_int_out,
    output logic [LANES-1:0][31:0]                   prod_fp32_equiv_out,
    output logic [$clog2(LANES+1)-1:0]               active_lanes_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        min_prod_exp_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        max_prod_exp_out,
    output logic                                     all_prod_zero_out,
    output logic [3:0]                               pos_prod_cnt_out,
    output logic [3:0]                               neg_prod_cnt_out
);

    localparam int EXP_W = TCU_V2_FP_EXP_W;
    localparam int SIG_W = TCU_V2_FP_SIG_W;

    function automatic logic [3:0] mul_e2m1_mant_2x2(
        input logic [1:0] ma,
        input logic [1:0] mb
    );
        logic [3:0] p;
        p[0] = ma[0] & mb[0];
        p[1] = (ma[1] & mb[0]) ^ (ma[0] & mb[1]);
        p[2] = (ma[1] & mb[1]) ^ ((ma[1] & mb[0]) & (ma[0] & mb[1]));
        p[3] = (ma[1] & mb[1]) & ((ma[1] & mb[0]) & (ma[0] & mb[1]));
        return p;
    endfunction

    function automatic logic [31:0] encode_fp4_prod_fp32(
        input logic                    is_zero_b,
        input logic                    sign_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [3:0]              mant_u1p3_b
    );
        logic signed [EXP_W-1:0] fp32_e;
        if (is_zero_b || !mant_u1p3_b[3]) begin
            return {sign_b, 31'd0};
        end else begin
            fp32_e = exp_b + $signed(EXP_W'(127));
            if (fp32_e <= 0) begin
                return {sign_b, 31'd0};
            end else if (fp32_e >= 255) begin
                return sign_b ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            end else begin
                return {sign_b, fp32_e[7:0], mant_u1p3_b[2:0], 20'd0};
            end
        end
    endfunction

    function automatic logic fp4_prod_is_exact_int(
        input logic                    is_zero_b,
        input logic signed [EXP_W-1:0] exp_b,
        input logic [3:0]              mant_u1p3_b
    );
        if (is_zero_b || !mant_u1p3_b[3]) begin
            return 1'b1;
        end else if (exp_b < 0) begin
            return 1'b0;
        end else if (exp_b == 0) begin
            return (mant_u1p3_b[2:0] == 3'b000);
        end else if (exp_b == 1) begin
            return (mant_u1p3_b[1:0] == 2'b00);
        end else if (exp_b == 2) begin
            return (mant_u1p3_b[0] == 1'b0);
        end else begin
            return 1'b1;
        end
    endfunction

    logic [LANES-1:0]                    comb_sign;
    logic signed [LANES-1:0][EXP_W-1:0]  comb_exp;
    logic [LANES-1:0][3:0]               comb_mant;
    logic [LANES-1:0]                    comb_zero;
    logic [LANES-1:0]                    comb_neg_zero;
    logic [LANES-1:0]                    comb_pos_zero;
    logic [LANES-1:0]                    comb_carry;
    logic [LANES-1:0]                    comb_subn_pair;
    logic [LANES-1:0]                    comb_exact_int;
    logic [LANES-1:0][31:0]              comb_fp32_eq;
    logic [$clog2(LANES+1)-1:0]          comb_active;
    logic signed [EXP_W-1:0]             comb_min_exp;
    logic signed [EXP_W-1:0]             comb_max_exp;
    logic                                comb_all_zero;
    logic [3:0]                          comb_pos_cnt;
    logic [3:0]                          comb_neg_cnt;

    for (genvar i = 0; i < LANES; ++i) begin : g_fp4_mul
        logic       a_sign;
        logic       b_sign;
        logic       a_zero;
        logic       b_zero;
        logic       a_subn;
        logic       b_subn;
        logic [1:0] a_mant_raw;
        logic [1:0] b_mant_raw;
        logic [1:0] a_mant_norm;
        logic [1:0] b_mant_norm;

        logic signed [EXP_W-1:0] a_exp_norm;
        logic signed [EXP_W-1:0] b_exp_norm;
        logic signed [EXP_W-1:0] exp_sum;

        logic [3:0] raw_mant_prod;
        logic [3:0] norm_mant_prod;
        logic       mant_carry;
        logic       lane_zero;
        logic       lane_sign;

        assign a_sign     = a_in[i].sign;
        assign b_sign     = b_in[i].sign;
        assign a_zero     = a_in[i].is_zero;
        assign b_zero     = b_in[i].is_zero;
        assign a_subn     = a_in[i].is_subnormal;
        assign b_subn     = b_in[i].is_subnormal;
        assign a_mant_raw = a_in[i].sig[SIG_W-1 -: 2];
        assign b_mant_raw = b_in[i].sig[SIG_W-1 -: 2];

        assign lane_zero = a_zero || b_zero || (a_mant_raw == 2'b00) || (b_mant_raw == 2'b00);
        assign lane_sign = a_sign ^ b_sign;

        // Normalize E2M1 subnormals (0.1 * 2^0 -> 1.0 * 2^-1).
        always_comb begin
            if (a_zero) begin
                a_mant_norm = 2'b00;
                a_exp_norm  = '0;
            end else if (a_subn) begin
                a_mant_norm = 2'b10;
                a_exp_norm  = a_in[i].exp - $signed(EXP_W'(1));
            end else begin
                a_mant_norm = a_mant_raw;
                a_exp_norm  = a_in[i].exp;
            end

            if (b_zero) begin
                b_mant_norm = 2'b00;
                b_exp_norm  = '0;
            end else if (b_subn) begin
                b_mant_norm = 2'b10;
                b_exp_norm  = b_in[i].exp - $signed(EXP_W'(1));
            end else begin
                b_mant_norm = b_mant_raw;
                b_exp_norm  = b_in[i].exp;
            end
        end

        // Exact 2b x 2b unsigned significand product in u2.2 -> normalized to u1.3.
        assign raw_mant_prod = mul_e2m1_mant_2x2(a_mant_norm, b_mant_norm);
        assign mant_carry    = raw_mant_prod[3];

        always_comb begin
            if (lane_zero) begin
                norm_mant_prod = 4'b0000;
                exp_sum        = '0;
            end else if (mant_carry) begin
                norm_mant_prod = raw_mant_prod;
                exp_sum        = a_exp_norm + b_exp_norm + $signed(EXP_W'(1));
            end else begin
                norm_mant_prod = {raw_mant_prod[2:0], 1'b0};
                exp_sum        = a_exp_norm + b_exp_norm;
            end
        end

        assign comb_sign[i]      = lane_sign;
        assign comb_exp[i]       = exp_sum;
        assign comb_mant[i]      = norm_mant_prod;
        assign comb_zero[i]      = lane_zero;
        assign comb_neg_zero[i]  = lane_zero && lane_sign;
        assign comb_pos_zero[i]  = lane_zero && !lane_sign;
        assign comb_carry[i]     = !lane_zero && mant_carry;
        assign comb_subn_pair[i] = !lane_zero && a_subn && b_subn;
        assign comb_exact_int[i] = fp4_prod_is_exact_int(lane_zero, exp_sum, norm_mant_prod);
        assign comb_fp32_eq[i]   = encode_fp4_prod_fp32(lane_zero, lane_sign, exp_sum, norm_mant_prod);
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
        assign prod_mant_u1p3_out    = comb_mant;
        assign prod_is_zero_out      = comb_zero;
        assign prod_neg_zero_out     = comb_neg_zero;
        assign prod_pos_zero_out     = comb_pos_zero;
        assign prod_has_carry_out    = comb_carry;
        assign prod_subnorm_pair_out = comb_subn_pair;
        assign prod_is_exact_int_out = comb_exact_int;
        assign prod_fp32_equiv_out   = comb_fp32_eq;
        assign active_lanes_out      = comb_active;
        assign min_prod_exp_out      = comb_min_exp;
        assign max_prod_exp_out      = comb_max_exp;
        assign all_prod_zero_out     = comb_all_zero;
        assign pos_prod_cnt_out      = comb_pos_cnt;
        assign neg_prod_cnt_out      = comb_neg_cnt;
    end else begin : g_reg_out
        logic                                reg_valid;
        logic [LANES-1:0]                    reg_sign;
        logic signed [LANES-1:0][EXP_W-1:0]  reg_exp;
        logic [LANES-1:0][3:0]               reg_mant;
        logic [LANES-1:0]                    reg_zero;
        logic [LANES-1:0]                    reg_neg_zero;
        logic [LANES-1:0]                    reg_pos_zero;
        logic [LANES-1:0]                    reg_carry;
        logic [LANES-1:0]                    reg_subn_pair;
        logic [LANES-1:0]                    reg_exact_int;
        logic [LANES-1:0][31:0]              reg_fp32_eq;
        logic [$clog2(LANES+1)-1:0]          reg_active;
        logic signed [EXP_W-1:0]             reg_min_exp;
        logic signed [EXP_W-1:0]             reg_max_exp;
        logic                                reg_all_zero;
        logic [3:0]                          reg_pos_cnt;
        logic [3:0]                          reg_neg_cnt;

        always_ff @(posedge clk) begin
            if (reset) begin
                reg_valid     <= 1'b0;
                reg_sign      <= '0;
                reg_exp       <= '0;
                reg_mant      <= '0;
                reg_zero      <= {LANES{1'b1}};
                reg_neg_zero  <= '0;
                reg_pos_zero  <= {LANES{1'b1}};
                reg_carry     <= '0;
                reg_subn_pair <= '0;
                reg_exact_int <= {LANES{1'b1}};
                reg_fp32_eq   <= '0;
                reg_active    <= '0;
                reg_min_exp   <= '0;
                reg_max_exp   <= '0;
                reg_all_zero  <= 1'b1;
                reg_pos_cnt   <= 4'd0;
                reg_neg_cnt   <= 4'd0;
            end else if (enable) begin
                reg_valid     <= valid_in;
                reg_sign      <= comb_sign;
                reg_exp       <= comb_exp;
                reg_mant      <= comb_mant;
                reg_zero      <= comb_zero;
                reg_neg_zero  <= comb_neg_zero;
                reg_pos_zero  <= comb_pos_zero;
                reg_carry     <= comb_carry;
                reg_subn_pair <= comb_subn_pair;
                reg_exact_int <= comb_exact_int;
                reg_fp32_eq   <= comb_fp32_eq;
                reg_active    <= comb_active;
                reg_min_exp   <= comb_min_exp;
                reg_max_exp   <= comb_max_exp;
                reg_all_zero  <= comb_all_zero;
                reg_pos_cnt   <= comb_pos_cnt;
                reg_neg_cnt   <= comb_neg_cnt;
            end
        end

        assign valid_out             = reg_valid;
        assign prod_sign_out         = reg_sign;
        assign prod_exp_out          = reg_exp;
        assign prod_mant_u1p3_out    = reg_mant;
        assign prod_is_zero_out      = reg_zero;
        assign prod_neg_zero_out     = reg_neg_zero;
        assign prod_pos_zero_out     = reg_pos_zero;
        assign prod_has_carry_out    = reg_carry;
        assign prod_subnorm_pair_out = reg_subn_pair;
        assign prod_is_exact_int_out = reg_exact_int;
        assign prod_fp32_equiv_out   = reg_fp32_eq;
        assign active_lanes_out      = reg_active;
        assign min_prod_exp_out      = reg_min_exp;
        assign max_prod_exp_out      = reg_max_exp;
        assign all_prod_zero_out     = reg_all_zero;
        assign pos_prod_cnt_out      = reg_pos_cnt;
        assign neg_prod_cnt_out      = reg_neg_cnt;
    end

endmodule
