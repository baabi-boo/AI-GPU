// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp32_acc_norm #(
    parameter int   ACC_MAG_W  = 64,
    parameter int   ACC_SIGN_W = 72,
    parameter logic OUT_REG    = 1'b0
) (
    input  logic                        clk,
    input  logic                        reset,
    input  logic                        enable,
    input  logic                        valid_in,
    input  logic [ACC_SIGN_W-1:0]       abs_mag_in,
    input  logic                        sum_sign_in,
    input  logic                        sum_is_zero_in,
    input  logic                        sticky_in,
    input  logic                        sticky_pos_in,
    input  logic                        sticky_neg_in,
    input  logic signed [10:0]          max_exp_s11_in,
    input  VX_tcu_v2_pkg::tcu_v2_rm_e   rm,
    output logic                        valid_out,
    output logic [31:0]                 fp32_norm_out,
    output logic                        res_is_zero_out,
    output logic                        res_is_inf_out,
    output logic                        res_sign_out,
    output logic                        flag_of_out,
    output logic                        flag_uf_out,
    output logic                        flag_nx_out,
    output logic                        is_subnorm_out,
    output logic                        round_up_out
);
    import VX_tcu_v2_pkg::*;

    localparam int HEADROOM_W  = ACC_SIGN_W - ACC_MAG_W;
    localparam int LZC_W       = $clog2(ACC_SIGN_W);
    localparam int SHIFT_PAD_W = ACC_SIGN_W + 28;

    // -------------------------------------------------------------------------
    // Helper: 7-Stage Binary-Tree Leading-Zero Counter (up to 128 bits)
    // -------------------------------------------------------------------------
    function automatic logic [6:0] clz_acc(
        input  logic [ACC_SIGN_W-1:0] vec_in,
        output logic                  valid_nz
    );
        logic [127:0] v128;
        logic [6:0]   cnt;
        logic [63:0]  hi64;
        logic [31:0]  hi32;
        logic [15:0]  hi16;
        logic [7:0]   hi8;
        logic [3:0]   hi4;
        logic         hi2_msb;
        begin
            valid_nz = (vec_in != {ACC_SIGN_W{1'b0}});
            // Left-align vec_in at MSB of 128-bit frame so CLZ directly measures leading zeros.
            v128 = {vec_in, {(128 - ACC_SIGN_W){1'b0}}};
            cnt  = 7'd0;
            if (v128[127:64] == 64'd0) begin
                cnt[6] = 1'b1;
                hi64   = v128[63:0];
            end else begin
                cnt[6] = 1'b0;
                hi64   = v128[127:64];
            end
            if (hi64[63:32] == 32'd0) begin
                cnt[5] = 1'b1;
                hi32   = hi64[31:0];
            end else begin
                cnt[5] = 1'b0;
                hi32   = hi64[63:32];
            end
            if (hi32[31:16] == 16'd0) begin
                cnt[4] = 1'b1;
                hi16   = hi32[15:0];
            end else begin
                cnt[4] = 1'b0;
                hi16   = hi32[31:16];
            end
            if (hi16[15:8] == 8'd0) begin
                cnt[3] = 1'b1;
                hi8    = hi16[7:0];
            end else begin
                cnt[3] = 1'b0;
                hi8    = hi16[15:8];
            end
            if (hi8[7:4] == 4'd0) begin
                cnt[2] = 1'b1;
                hi4    = hi8[3:0];
            end else begin
                cnt[2] = 1'b0;
                hi4    = hi8[7:4];
            end
            if (hi4[3:2] == 2'd0) begin
                cnt[1]  = 1'b1;
                hi2_msb = hi4[1] | (hi4[0] & 1'b0);
            end else begin
                cnt[1]  = 1'b0;
                hi2_msb = hi4[3];
            end
            cnt[0] = ~hi2_msb;
            return cnt;
        end
    endfunction

    // -------------------------------------------------------------------------
    // Signed Sticky Borrow & Staged Logarithmic Left-Shift Normalization
    // -------------------------------------------------------------------------
    logic                  same_sign_sticky;
    logic                  opp_sign_sticky;
    logic                  apply_sticky_borrow;
    logic                  borrow_unit_mag;
    logic [ACC_SIGN_W-1:0] eff_mag_in;
    logic [6:0]            lz_count_7;
    logic [LZC_W-1:0]      lz_count;
    logic                  lzc_valid;
    logic signed [10:0]    norm_exp_unbiased;
    logic [SHIFT_PAD_W-1:0] padded_mag;
    logic [SHIFT_PAD_W-1:0] shl_s0;
    logic [SHIFT_PAD_W-1:0] shl_s1;
    logic [SHIFT_PAD_W-1:0] shl_s2;
    logic [SHIFT_PAD_W-1:0] shl_s3;
    logic [SHIFT_PAD_W-1:0] shl_s4;
    logic [SHIFT_PAD_W-1:0] shl_s5;
    logic [SHIFT_PAD_W-1:0] shifted_mag;

    assign same_sign_sticky    = sum_sign_in ? sticky_neg_in : sticky_pos_in;
    assign opp_sign_sticky     = sum_sign_in ? sticky_pos_in : sticky_neg_in;
    assign apply_sticky_borrow = !sum_is_zero_in && (abs_mag_in != '0) && opp_sign_sticky && !same_sign_sticky;
    assign borrow_unit_mag     = apply_sticky_borrow && (abs_mag_in == {{(ACC_SIGN_W-1){1'b0}}, 1'b1});
    assign eff_mag_in          = apply_sticky_borrow ? (abs_mag_in - {{(ACC_SIGN_W-1){1'b0}}, 1'b1}) : abs_mag_in;

    always_comb begin
        logic [SHIFT_PAD_W-1:0] fill_s5;
        logic [SHIFT_PAD_W-1:0] fill_s4;
        logic [SHIFT_PAD_W-1:0] fill_s3;
        logic [SHIFT_PAD_W-1:0] fill_s2;
        logic [SHIFT_PAD_W-1:0] fill_s1;
        logic [SHIFT_PAD_W-1:0] fill_s0;
        logic                   raw_lzc_vld;

        lz_count_7 = clz_acc(eff_mag_in, raw_lzc_vld);
        lzc_valid  = raw_lzc_vld || borrow_unit_mag;
        lz_count   = borrow_unit_mag ? LZC_W'(ACC_SIGN_W - 1) : lz_count_7[LZC_W-1:0];
        padded_mag = {eff_mag_in, {28{apply_sticky_borrow}}};

        fill_s5     = apply_sticky_borrow ? {{(SHIFT_PAD_W-64){1'b0}}, 64'hFFFF_FFFF_FFFF_FFFF} : '0;
        fill_s4     = apply_sticky_borrow ? {{(SHIFT_PAD_W-32){1'b0}}, 32'hFFFF_FFFF} : '0;
        fill_s3     = apply_sticky_borrow ? {{(SHIFT_PAD_W-16){1'b0}}, 16'hFFFF} : '0;
        fill_s2     = apply_sticky_borrow ? {{(SHIFT_PAD_W-8){1'b0}},  8'hFF} : '0;
        fill_s1     = apply_sticky_borrow ? {{(SHIFT_PAD_W-4){1'b0}},  4'hF} : '0;
        fill_s0     = apply_sticky_borrow ? {{(SHIFT_PAD_W-2){1'b0}},  2'h3} : '0;

        shl_s5      = (LZC_W > 6 && lz_count[LZC_W-1]) ? ({padded_mag[SHIFT_PAD_W-65:0], 64'd0} | fill_s5) : padded_mag;
        shl_s0      = lz_count[5] ? ({shl_s5[SHIFT_PAD_W-33:0], 32'd0} | fill_s4) : shl_s5;
        shl_s1      = lz_count[4] ? ({shl_s0[SHIFT_PAD_W-17:0], 16'd0} | fill_s3) : shl_s0;
        shl_s2      = lz_count[3] ? ({shl_s1[SHIFT_PAD_W-9:0],   8'd0} | fill_s2) : shl_s1;
        shl_s3      = lz_count[2] ? ({shl_s2[SHIFT_PAD_W-5:0],   4'd0} | fill_s1) : shl_s2;
        shl_s4      = lz_count[1] ? ({shl_s3[SHIFT_PAD_W-3:0],   2'd0} | fill_s0) : shl_s3;
        shifted_mag = borrow_unit_mag ? {SHIFT_PAD_W{1'b1}} :
                      (lz_count[0] ? ({shl_s4[SHIFT_PAD_W-2:0],   1'b0} | {{(SHIFT_PAD_W-1){1'b0}}, apply_sticky_borrow}) : shl_s4);
    end

    `UNUSED_VAR (lz_count_7)

    assign norm_exp_unbiased = max_exp_s11_in + $signed(11'(HEADROOM_W))
                             - $signed({{(11 - LZC_W){1'b0}}, lz_count})
                             - (borrow_unit_mag ? 11'sd1 : 11'sd0);

    logic [23:0] norm_sig24;
    logic        norm_guard;
    logic        norm_round;
    logic        norm_tail_sticky;

    assign norm_sig24       = shifted_mag[SHIFT_PAD_W - 1 -: 24];
    assign norm_guard       = shifted_mag[SHIFT_PAD_W - 25];
    assign norm_round       = shifted_mag[SHIFT_PAD_W - 26];
    assign norm_tail_sticky = (|shifted_mag[SHIFT_PAD_W - 27 : 0]) | sticky_in | apply_sticky_borrow;

    // -------------------------------------------------------------------------
    // Subnormal Right-Shift Path (biased_exp <= 0)
    // -------------------------------------------------------------------------
    logic signed [10:0] biased_exp_pre;
    logic               is_subnorm_range;
    logic signed [10:0] subnorm_rshift_s;
    logic [5:0]         subnorm_rshift;
    logic [51:0]        subnorm_ext;
    logic [51:0]        subnorm_shifted;
    logic [23:0]        subnorm_sig24;
    logic               subnorm_guard;
    logic               subnorm_round;
    logic               subnorm_sticky;

    assign biased_exp_pre   = norm_exp_unbiased + 11'sd127;
    assign is_subnorm_range = (biased_exp_pre <= 11'sd0);
    assign subnorm_rshift_s = 11'sd1 - biased_exp_pre;

    always_comb begin
        if (subnorm_rshift_s <= 11'sd0) begin
            subnorm_rshift = 6'd0;
        end else if (subnorm_rshift_s >= 11'sd28) begin
            subnorm_rshift = 6'd28;
        end else begin
            subnorm_rshift = subnorm_rshift_s[5:0];
        end
    end

    assign subnorm_ext     = {norm_sig24, norm_guard, norm_round, norm_tail_sticky, 25'd0};
    assign subnorm_shifted = subnorm_ext >> subnorm_rshift;

    assign subnorm_sig24  = subnorm_shifted[51:28];
    assign subnorm_guard  = subnorm_shifted[27];
    assign subnorm_round  = subnorm_shifted[26];
    assign subnorm_sticky = (|subnorm_shifted[25:0]) | norm_tail_sticky;

    logic [23:0] pre_round_sig24;
    logic        pre_round_g;
    logic        pre_round_r;
    logic        pre_round_s;

    always_comb begin
        if (is_subnorm_range) begin
            pre_round_sig24 = subnorm_sig24;
            pre_round_g     = subnorm_guard;
            pre_round_r     = subnorm_round;
            pre_round_s     = subnorm_sticky;
        end else begin
            pre_round_sig24 = norm_sig24;
            pre_round_g     = norm_guard;
            pre_round_r     = norm_round;
            pre_round_s     = norm_tail_sticky;
        end
    end

    // -------------------------------------------------------------------------
    // 5-Mode IEEE-754 Rounder (RNE, RTZ, RDN, RUP, RMM)
    // -------------------------------------------------------------------------
    logic               any_lost_bits;
    logic               round_up;
    logic [24:0]        rounded_sig25;
    logic               round_carry;
    logic [22:0]        rounded_man23;
    logic signed [10:0] rounded_biased_exp;

    assign any_lost_bits = pre_round_g | pre_round_r | pre_round_s;

    always_comb begin
        round_up = 1'b0;
        case (rm)
            TCU_V2_RM_RNE: begin
                round_up = pre_round_g && (pre_round_r || pre_round_s || pre_round_sig24[0]);
            end
            TCU_V2_RM_RTZ: begin
                round_up = 1'b0;
            end
            TCU_V2_RM_RDN: begin
                round_up = sum_sign_in && any_lost_bits;
            end
            TCU_V2_RM_RUP: begin
                round_up = !sum_sign_in && any_lost_bits;
            end
            TCU_V2_RM_RMM: begin
                round_up = pre_round_g;
            end
            default: begin
                round_up = pre_round_g && (pre_round_r || pre_round_s || pre_round_sig24[0]);
            end
        endcase
    end

    assign rounded_sig25 = {1'b0, pre_round_sig24} + {24'd0, round_up};
    assign round_carry   = rounded_sig25[24];

    always_comb begin
        if (is_subnorm_range) begin
            rounded_man23 = rounded_sig25[22:0];
            if (rounded_sig25[23]) begin
                rounded_biased_exp = 11'sd1;
            end else begin
                rounded_biased_exp = 11'sd0;
            end
        end else if (round_carry) begin
            rounded_man23      = rounded_sig25[23:1];
            rounded_biased_exp = biased_exp_pre + 11'sd1;
        end else begin
            rounded_man23      = rounded_sig25[22:0];
            rounded_biased_exp = biased_exp_pre;
        end
    end

    // -------------------------------------------------------------------------
    // Overflow / Underflow / Inexact Classification & IEEE-754 Packing
    // -------------------------------------------------------------------------
    logic        actual_zero;
    logic        is_overflow;
    logic        is_underflow;
    logic        is_inexact;
    logic        is_exact_tie;
    logic        subnorm_rounded_to_normal;
    logic        overflow_to_max_finite;
    logic [31:0] comb_fp32;
    logic        comb_res_zero;
    logic        comb_res_inf;
    logic        comb_res_sign;
    logic        comb_of;
    logic        comb_uf;
    logic        comb_nx;
    logic        comb_is_subnorm;

    assign actual_zero               = sum_is_zero_in || !lzc_valid;
    assign is_overflow               = !actual_zero && (rounded_biased_exp >= 11'sd255);
    assign is_underflow              = !actual_zero && !is_overflow && (rounded_biased_exp == 11'sd0) && any_lost_bits;
    assign is_inexact                = !actual_zero && (any_lost_bits || is_overflow);
    assign comb_is_subnorm           = !actual_zero && !is_overflow && (rounded_biased_exp == 11'sd0) && (rounded_man23 != 23'd0);
    assign is_exact_tie              = pre_round_g && !pre_round_r && !pre_round_s;
    assign subnorm_rounded_to_normal = is_subnorm_range && (rounded_biased_exp == 11'sd1);

    logic tiny_before_round;
    logic tiny_after_round;
    logic max_normal_clamp;
    logic min_subnorm_hit;

    assign tiny_before_round = !actual_zero && (biased_exp_pre <= 11'sd0);
    assign tiny_after_round  = !actual_zero && (rounded_biased_exp == 11'sd0);
    assign max_normal_clamp  = is_overflow && overflow_to_max_finite;
    assign min_subnorm_hit   = comb_is_subnorm && (rounded_man23 == 23'd1);

    `UNUSED_VAR (is_exact_tie)
    `UNUSED_VAR (subnorm_rounded_to_normal)
    `UNUSED_VAR (tiny_before_round)
    `UNUSED_VAR (tiny_after_round)
    `UNUSED_VAR (max_normal_clamp)
    `UNUSED_VAR (min_subnorm_hit)

    always_comb begin
        overflow_to_max_finite = 1'b0;
        case (rm)
            TCU_V2_RM_RTZ: overflow_to_max_finite = 1'b1;
            TCU_V2_RM_RDN: overflow_to_max_finite = !sum_sign_in;
            TCU_V2_RM_RUP: overflow_to_max_finite = sum_sign_in;
            default:       overflow_to_max_finite = 1'b0;
        endcase
    end

    always_comb begin
        comb_res_zero = 1'b0;
        comb_res_inf  = 1'b0;
        comb_res_sign = sum_sign_in;
        comb_of       = 1'b0;
        comb_uf       = 1'b0;
        comb_nx       = 1'b0;

        if (actual_zero) begin
            comb_res_zero = 1'b1;
            comb_res_sign = sum_sign_in;
            comb_fp32     = {sum_sign_in, 8'h00, 23'd0};
        end else if (is_overflow) begin
            comb_of = 1'b1;
            comb_nx = 1'b1;
            if (overflow_to_max_finite) begin
                comb_fp32 = {sum_sign_in, 8'hFE, 23'h7FFFFF};
            end else begin
                comb_res_inf = 1'b1;
                comb_fp32    = {sum_sign_in, 8'hFF, 23'd0};
            end
        end else if (rounded_biased_exp == 11'sd0) begin
            comb_res_zero = (rounded_man23 == 23'd0);
            comb_uf       = is_underflow;
            comb_nx       = is_inexact;
            comb_fp32     = {sum_sign_in, 8'h00, rounded_man23};
        end else begin
            comb_uf   = is_underflow;
            comb_nx   = is_inexact;
            comb_fp32 = {sum_sign_in, rounded_biased_exp[7:0], rounded_man23};
        end
    end

    // -------------------------------------------------------------------------
    // Optional Pipeline Register Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic        valid_r;
        logic [31:0] fp32_norm_r;
        logic        res_is_zero_r;
        logic        res_is_inf_r;
        logic        res_sign_r;
        logic        flag_of_r;
        logic        flag_uf_r;
        logic        flag_nx_r;
        logic        is_subnorm_r;
        logic        round_up_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r       <= 1'b0;
                fp32_norm_r   <= 32'd0;
                res_is_zero_r <= 1'b1;
                res_is_inf_r  <= 1'b0;
                res_sign_r    <= 1'b0;
                flag_of_r     <= 1'b0;
                flag_uf_r     <= 1'b0;
                flag_nx_r     <= 1'b0;
                is_subnorm_r  <= 1'b0;
                round_up_r    <= 1'b0;
            end else if (enable) begin
                valid_r       <= valid_in;
                fp32_norm_r   <= comb_fp32;
                res_is_zero_r <= comb_res_zero;
                res_is_inf_r  <= comb_res_inf;
                res_sign_r    <= comb_res_sign;
                flag_of_r     <= comb_of;
                flag_uf_r     <= comb_uf;
                flag_nx_r     <= comb_nx;
                is_subnorm_r  <= comb_is_subnorm;
                round_up_r    <= round_up;
            end
        end

        assign valid_out       = valid_r;
        assign fp32_norm_out   = fp32_norm_r;
        assign res_is_zero_out = res_is_zero_r;
        assign res_is_inf_out  = res_is_inf_r;
        assign res_sign_out    = res_sign_r;
        assign flag_of_out     = flag_of_r;
        assign flag_uf_out     = flag_uf_r;
        assign flag_nx_out     = flag_nx_r;
        assign is_subnorm_out  = is_subnorm_r;
        assign round_up_out    = round_up_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out       = valid_in;
        assign fp32_norm_out   = comb_fp32;
        assign res_is_zero_out = comb_res_zero;
        assign res_is_inf_out  = comb_res_inf;
        assign res_sign_out    = comb_res_sign;
        assign flag_of_out     = comb_of;
        assign flag_uf_out     = comb_uf;
        assign flag_nx_out     = comb_nx;
        assign is_subnorm_out  = comb_is_subnorm;
        assign round_up_out    = round_up;
    end

endmodule
