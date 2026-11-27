// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_lza_norm import VX_tcu_v2_pkg::*; #(
    parameter int ACC_W = TCU_V2_WIDE_ACC_W,
    parameter int EXP_W = TCU_V2_FP_EXP_W
) (
    input  logic [ACC_W-1:0]               mag_in,
    input  logic                           sign_in,
    input  logic signed [EXP_W-1:0]        max_exp_in,
    input  logic                           sticky_in,
    input  logic                           pos_sticky_in,
    input  logic                           neg_sticky_in,
    input  logic                           all_zero_in,
    output logic [23:0]                    norm_sig_u1p23_out,
    output logic signed [EXP_W-1:0]        norm_exp_out,
    output logic                           guard_bit_out,
    output logic                           round_bit_out,
    output logic                           sticky_bit_out,
    output logic                           norm_sign_out,
    output logic                           is_zero_out,
    output logic                           is_subnormal_out,
    output logic                           is_overflow_pre_out,
    output logic                           is_tiny_flush_out,
    output logic                           norm_msb_ok_out,
    output logic [$clog2(ACC_W)-1:0]       lzc_out,
    output logic [5:0]                     subnorm_shamt_out,
    output logic                           had_carry_growth_out,
    output logic                           had_cancel_shift_out,
    output logic [5:0]                     effective_shift_mag_out,
    output logic [5:0]                     trailing_zero_cnt_out,
    output logic                           is_exact_pow2_mag_out,
    output logic                           norm_round_window_nz_out,
    output logic                           subnorm_border_out
);

    localparam int GUARD_BITS   = 4;
    localparam int LZC_W        = $clog2(ACC_W);
    localparam int TREE_DEPTH   = LZC_W;
    localparam int PAD_W        = 1 << TREE_DEPTH;
    localparam int FP32_MIN_EXP = -126;
    localparam int FP32_MAX_EXP = 127;

    // Barrel shifter right on 27-bit {sig, G, R, S} bundle with exact sticky retention.
    function automatic logic [27:0] shift_right_sticky_27(
        input logic [26:0] val27,
        input logic [5:0]  shamt
    );
        logic [26:0] shifted;
        logic [26:0] lost_mask;
        logic        lost_sticky;
        if (shamt == 6'd0) begin
            shifted     = val27;
            lost_sticky = 1'b0;
        end else if (shamt >= 6'd27) begin
            shifted     = 27'd0;
            lost_sticky = (|val27);
        end else begin
            shifted     = val27 >> shamt;
            lost_mask   = val27 & (27'h7FF_FFFF >> (6'd27 - shamt));
            lost_sticky = (|lost_mask);
        end
        return {lost_sticky, shifted};
    endfunction

    // Signed sticky borrow adjustment:
    // When an opposite-sign infinitesimal tail was shifted past ACC_W, subtract 1 from mag_in
    // and set the sub-LSB borrow sticky (fractional tail ...111) so rounding sees exact value.
    logic             same_sign_sticky;
    logic             opp_sign_sticky;
    logic             apply_sticky_borrow;
    logic             borrow_unit_mag;
    logic [ACC_W-1:0] eff_mag_in;

    assign same_sign_sticky    = sign_in ? neg_sticky_in : pos_sticky_in;
    assign opp_sign_sticky     = sign_in ? pos_sticky_in : neg_sticky_in;
    assign apply_sticky_borrow = !all_zero_in && (mag_in != '0) && opp_sign_sticky && !same_sign_sticky;
    assign borrow_unit_mag     = apply_sticky_borrow && (mag_in == {{(ACC_W-1){1'b0}}, 1'b1});
    assign eff_mag_in          = apply_sticky_borrow ? (mag_in - {{(ACC_W-1){1'b0}}, 1'b1}) : mag_in;

    // Binary-tree Leading Zero Counter over PAD_W bits (MSB-first).
    // Fully packed arrays prevent UNOPTFLAT false cycle warnings.
    logic [PAD_W-1:0]                          padded_mag;
    logic [TREE_DEPTH:0][PAD_W-1:0]            valid_tree;
    logic [TREE_DEPTH:0][PAD_W-1:0][LZC_W-1:0] count_tree;

    assign padded_mag = {eff_mag_in, {(PAD_W - ACC_W){1'b0}}};

    for (genvar b = 0; b < PAD_W; ++b) begin : g_lzc_leaf
        assign valid_tree[0][b] = padded_mag[PAD_W - 1 - b];
        assign count_tree[0][b] = '0;
    end

    for (genvar lvl = 0; lvl < TREE_DEPTH; ++lvl) begin : g_lzc_lvl
        localparam int NODES = PAD_W >> (lvl + 1);
        for (genvar n = 0; n < NODES; ++n) begin : g_lzc_node
            logic             left_v;
            logic             right_v;
            logic [LZC_W-1:0] left_c;
            logic [LZC_W-1:0] right_c;

            assign left_v  = valid_tree[lvl][2*n];
            assign right_v = valid_tree[lvl][2*n+1];
            assign left_c  = count_tree[lvl][2*n];
            assign right_c = count_tree[lvl][2*n+1];

            assign valid_tree[lvl+1][n] = left_v | right_v;
            always_comb begin
                if (left_v) begin
                    count_tree[lvl+1][n] = left_c;
                end else if (right_v) begin
                    count_tree[lvl+1][n] = right_c | (LZC_W'(1) << lvl);
                end else begin
                    count_tree[lvl+1][n] = (LZC_W'(1) << (lvl + 1)) - LZC_W'(1);
                end
            end
        end
        for (genvar rem = NODES; rem < PAD_W; ++rem) begin : g_lzc_pad
            assign valid_tree[lvl+1][rem] = 1'b0;
            assign count_tree[lvl+1][rem] = '0;
        end
    end

    // Parallel Trailing Zero Counter over PAD_W bits (LSB-first) for exact power-of-two detection.
    logic [PAD_W-1:0]                          tzc_pad_mag;
    logic [TREE_DEPTH:0][PAD_W-1:0]            tzc_valid_tree;
    logic [TREE_DEPTH:0][PAD_W-1:0][LZC_W-1:0] tzc_count_tree;

    assign tzc_pad_mag = {{(PAD_W - ACC_W){1'b0}}, eff_mag_in};

    for (genvar b = 0; b < PAD_W; ++b) begin : g_tzc_leaf
        assign tzc_valid_tree[0][b] = tzc_pad_mag[b];
        assign tzc_count_tree[0][b] = '0;
    end

    for (genvar lvl = 0; lvl < TREE_DEPTH; ++lvl) begin : g_tzc_lvl
        localparam int NODES = PAD_W >> (lvl + 1);
        for (genvar n = 0; n < NODES; ++n) begin : g_tzc_node
            logic             low_v;
            logic             high_v;
            logic [LZC_W-1:0] low_c;
            logic [LZC_W-1:0] high_c;

            assign low_v  = tzc_valid_tree[lvl][2*n];
            assign high_v = tzc_valid_tree[lvl][2*n+1];
            assign low_c  = tzc_count_tree[lvl][2*n];
            assign high_c = tzc_count_tree[lvl][2*n+1];

            assign tzc_valid_tree[lvl+1][n] = low_v | high_v;
            always_comb begin
                if (low_v) begin
                    tzc_count_tree[lvl+1][n] = low_c;
                end else if (high_v) begin
                    tzc_count_tree[lvl+1][n] = high_c | (LZC_W'(1) << lvl);
                end else begin
                    tzc_count_tree[lvl+1][n] = (LZC_W'(1) << (lvl + 1)) - LZC_W'(1);
                end
            end
        end
        for (genvar rem = NODES; rem < PAD_W; ++rem) begin : g_tzc_pad
            assign tzc_valid_tree[lvl+1][rem] = 1'b0;
            assign tzc_count_tree[lvl+1][rem] = '0;
        end
    end

    logic             mag_nonzero;
    logic [LZC_W-1:0] raw_lzc;
    logic [LZC_W-1:0] raw_tzc;

    assign mag_nonzero      = (valid_tree[TREE_DEPTH][0] || borrow_unit_mag) && !all_zero_in;
    assign raw_lzc          = borrow_unit_mag ? LZC_W'(ACC_W - 1) :
                              (mag_nonzero ? count_tree[TREE_DEPTH][0] : LZC_W'(ACC_W - 1));
    assign raw_tzc          = tzc_valid_tree[TREE_DEPTH][0] ? tzc_count_tree[TREE_DEPTH][0] : LZC_W'(ACC_W - 1);
    assign lzc_out          = raw_lzc;
    `UNUSED_VAR (valid_tree[TREE_DEPTH][PAD_W-1:1])
    `UNUSED_VAR (tzc_valid_tree[TREE_DEPTH][PAD_W-1:1])

    // Logarithmic barrel left-shifter for exact leading-1 normalization, shifting in 1s on borrow.
    logic [TREE_DEPTH:0][ACC_W-1:0] lshift_stage;
    assign lshift_stage[0] = mag_nonzero ? eff_mag_in : '0;
    for (genvar s = 0; s < TREE_DEPTH; ++s) begin : g_lshift
        localparam int STEP = 1 << s;
        logic [ACC_W-1:0] fill_lo;
        assign fill_lo = apply_sticky_borrow ? {{(ACC_W - STEP){1'b0}}, {STEP{1'b1}}} : '0;
        assign lshift_stage[s+1] = raw_lzc[s] ? ((lshift_stage[s] << STEP) | fill_lo) : lshift_stage[s];
    end

    logic [ACC_W-1:0]      shifted_norm;
    logic signed [EXP_W:0] exp_norm_wide;
    logic signed [EXP_W:0] subnorm_shift_wide;
    logic                  needs_subnorm_shift;
    logic                  pre_ovf_flag;
    logic                  tiny_flush_flag;

    assign shifted_norm = borrow_unit_mag ? {ACC_W{1'b1}} : lshift_stage[TREE_DEPTH];
    assign exp_norm_wide = $signed({max_exp_in[EXP_W-1], max_exp_in})
                         + $signed((EXP_W+1)'(GUARD_BITS))
                         - $signed({{(EXP_W+1-LZC_W){1'b0}}, raw_lzc})
                         - (borrow_unit_mag ? $signed((EXP_W+1)'(1)) : $signed((EXP_W+1)'(0)));

    assign needs_subnorm_shift = mag_nonzero && (exp_norm_wide < $signed((EXP_W+1)'(FP32_MIN_EXP)));
    assign subnorm_shift_wide  = $signed((EXP_W+1)'(FP32_MIN_EXP)) - exp_norm_wide;
    assign pre_ovf_flag        = mag_nonzero && (exp_norm_wide > $signed((EXP_W+1)'(FP32_MAX_EXP)));
    assign tiny_flush_flag     = needs_subnorm_shift && (subnorm_shift_wide >= 27);

    // Extract 24-bit significand + G/R/S from shifted_norm (leading 1 at ACC_W-1).
    logic [23:0] pre_sig;
    logic        pre_g;
    logic        pre_r;
    logic        pre_s;

    assign pre_sig = shifted_norm[ACC_W-1 -: 24];
    assign pre_g   = shifted_norm[ACC_W-25];
    assign pre_r   = shifted_norm[ACC_W-26];
    assign pre_s   = (|shifted_norm[ACC_W-27:0]) | sticky_in | apply_sticky_borrow;

    logic [26:0] ext_grs;
    logic [5:0]  subnorm_shamt;
    logic [27:0] subnorm_res_pack;
    logic [26:0] subnorm_shifted_grs;
    logic        subnorm_lost_sticky;

    assign ext_grs = {pre_sig, pre_g, pre_r, pre_s};

    always_comb begin
        if (!needs_subnorm_shift) begin
            subnorm_shamt = 6'd0;
        end else if (subnorm_shift_wide >= 27) begin
            subnorm_shamt = 6'd27;
        end else begin
            subnorm_shamt = subnorm_shift_wide[5:0];
        end
    end

    assign subnorm_res_pack    = shift_right_sticky_27(ext_grs, subnorm_shamt);
    assign subnorm_shifted_grs = subnorm_res_pack[26:0];
    assign subnorm_lost_sticky = subnorm_res_pack[27];

    always_comb begin
        if (!mag_nonzero) begin
            norm_sig_u1p23_out = 24'd0;
            norm_exp_out       = '0;
            guard_bit_out      = 1'b0;
            round_bit_out      = 1'b0;
            sticky_bit_out     = sticky_in;
            norm_sign_out      = sign_in;
            is_zero_out        = 1'b1;
            is_subnormal_out   = 1'b0;
        end else if (needs_subnorm_shift) begin
            norm_sig_u1p23_out = subnorm_shifted_grs[26:3];
            norm_exp_out       = $signed(EXP_W'(FP32_MIN_EXP));
            guard_bit_out      = subnorm_shifted_grs[2];
            round_bit_out      = subnorm_shifted_grs[1];
            sticky_bit_out     = subnorm_shifted_grs[0] | subnorm_lost_sticky | pre_s;
            norm_sign_out      = sign_in;
            is_zero_out        = 1'b0;
            is_subnormal_out   = 1'b1;
        end else begin
            norm_sig_u1p23_out = pre_sig;
            norm_exp_out       = exp_norm_wide[EXP_W-1:0];
            guard_bit_out      = pre_g;
            round_bit_out      = pre_r;
            sticky_bit_out     = pre_s;
            norm_sign_out      = sign_in;
            is_zero_out        = 1'b0;
            is_subnormal_out   = 1'b0;
        end
    end

    assign is_overflow_pre_out      = pre_ovf_flag;
    assign is_tiny_flush_out        = tiny_flush_flag;
    assign norm_msb_ok_out          = (!mag_nonzero) || shifted_norm[ACC_W-1];
    assign subnorm_shamt_out        = subnorm_shamt;
    assign had_carry_growth_out     = mag_nonzero && (raw_lzc < LZC_W'(GUARD_BITS));
    assign had_cancel_shift_out     = mag_nonzero && (raw_lzc > LZC_W'(GUARD_BITS));
    assign effective_shift_mag_out  = mag_nonzero ?
                                      ((raw_lzc >= LZC_W'(GUARD_BITS)) ?
                                          (raw_lzc - LZC_W'(GUARD_BITS)) :
                                          (LZC_W'(GUARD_BITS) - raw_lzc)) :
                                      6'd0;
    assign trailing_zero_cnt_out    = raw_tzc;
    assign is_exact_pow2_mag_out    = mag_nonzero && ((raw_lzc + raw_tzc) == LZC_W'(ACC_W - 1));
    assign norm_round_window_nz_out = mag_nonzero && (guard_bit_out | round_bit_out | sticky_bit_out);
    assign subnorm_border_out       = mag_nonzero && (exp_norm_wide == $signed((EXP_W+1)'(FP32_MIN_EXP)));

    `STATIC_ASSERT((ACC_W >= 30) && (EXP_W >= 10), ("Normalizer requires ACC_W >= 30 and EXP_W >= 10"))

endmodule
