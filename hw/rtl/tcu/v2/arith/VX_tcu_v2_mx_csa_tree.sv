// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_csa_tree import VX_tcu_v2_pkg::*; #(
    parameter int LANES = TCU_V2_MAX_LANES,
    parameter int ACC_W = TCU_V2_WIDE_ACC_W,
    parameter int EXP_W = TCU_V2_FP_EXP_W,
    parameter int SIG_W = TCU_V2_FP_SIG_W
) (
    input  logic [LANES:0][ACC_W-1:0]  terms_in,
    input  logic [LANES:0]             sticky_in,
    input  logic [LANES:0]             term_sign_in,
    input  logic [LANES-1:0][ACC_W-1:0] lane_terms_in,
    input  logic signed [EXP_W-1:0]    lane_max_exp_in,
    input  logic                       lanes_all_zero_in,
    input  logic                       c_eff_zero_in,
    input  logic                       c_eff_sign_in,
    input  logic signed [EXP_W-1:0]    c_norm_exp_in,
    input  logic [SIG_W-1:0]           c_norm_sig_in,
    output logic [ACC_W-1:0]           sum_vec_out,
    output logic [ACC_W-1:0]           carry_vec_out,
    output logic [ACC_W-1:0]           signed_sum_out,
    output logic [ACC_W-1:0]           mag_out,
    output logic                       sign_out,
    output logic                       is_zero_out,
    output logic                       sticky_out,
    output logic                       pos_sticky_out,
    output logic                       neg_sticky_out,
    output logic                       sticky_sign_out,
    output logic                       exact_cancel_out,
    output logic                       pos_terms_present_out,
    output logic                       neg_terms_present_out,
    output logic [3:0]                 nonzero_terms_cnt_out,
    output logic                       sum_overflow_guard_out,
    output logic [ACC_W-1:0]           pos_partial_sum_out,
    output logic [ACC_W-1:0]           neg_partial_sum_out,
    output logic                       sticky_parity_out,
    output logic [3:0]                 sticky_count_out,
    output logic [ACC_W-1:0]           prod_only_sum_out,
    output logic                       prod_only_sign_out,
    output logic                       prod_only_zero_out,
    output logic                       c_flipped_sign_out,
    output logic signed [EXP_W-1:0]    eff_max_exp_out
);

    localparam int NUM_TERMS = LANES + 1;

    // 4:2 compressor cell operating across ACC_W bits.
    function automatic logic [2*ACC_W-1:0] csa_42_compress(
        input logic [ACC_W-1:0] x0,
        input logic [ACC_W-1:0] x1,
        input logic [ACC_W-1:0] x2,
        input logic [ACC_W-1:0] x3
    );
        logic [ACC_W-1:0] s_int;
        logic [ACC_W-2:0] c_int;
        logic [ACC_W-1:0] s_out;
        logic [ACC_W-1:0] c_out;
        logic             cin_bit;
        logic             s1;
        logic             cout_bit;
        logic             carry_bit;

        cin_bit = 1'b0;
        s_int   = '0;
        c_int   = '0;
        for (int b = 0; b < ACC_W; ++b) begin
            s1        = x0[b] ^ x1[b] ^ x2[b];
            cout_bit  = (x0[b] & x1[b]) | (x1[b] & x2[b]) | (x0[b] & x2[b]);
            s_int[b]  = s1 ^ x3[b] ^ cin_bit;
            carry_bit = (s1 & x3[b]) | (x3[b] & cin_bit) | (s1 & cin_bit);
            if (b < (ACC_W - 1)) begin
                c_int[b] = carry_bit;
            end
            cin_bit   = cout_bit;
        end
        s_out = s_int;
        c_out = {c_int, 1'b0};
        return {c_out, s_out};
    endfunction

    // 3:2 full-adder compressor cell across ACC_W bits.
    function automatic logic [2*ACC_W-1:0] csa_32_compress(
        input logic [ACC_W-1:0] x0,
        input logic [ACC_W-1:0] x1,
        input logic [ACC_W-1:0] x2
    );
        logic [ACC_W-1:0] s_out;
        logic [ACC_W-2:0] c_raw;
        logic [ACC_W-1:0] c_out;

        s_out = x0 ^ x1 ^ x2;
        c_raw = (x0[ACC_W-2:0] & x1[ACC_W-2:0])
              | (x1[ACC_W-2:0] & x2[ACC_W-2:0])
              | (x0[ACC_W-2:0] & x2[ACC_W-2:0]);
        c_out = {c_raw, 1'b0};
        return {c_out, s_out};
    endfunction

    // Kogge-Stone parallel prefix adder over ACC_W bits for carry-propagate resolution.
    function automatic logic [ACC_W-1:0] kogge_stone_add(
        input logic [ACC_W-1:0] op_a,
        input logic [ACC_W-1:0] op_b
    );
        logic [ACC_W-1:0] p_cur;
        logic [ACC_W-1:0] g_cur;
        logic [ACC_W-1:0] p_nxt;
        logic [ACC_W-1:0] g_nxt;
        logic [ACC_W-1:0] carries;
        logic [ACC_W-1:0] sum_res;
        int               stride;

        p_cur = op_a ^ op_b;
        g_cur = op_a & op_b;

        for (int stage = 0; stage < 6; ++stage) begin
            stride = 1 << stage;
            if (stride < ACC_W) begin
                p_nxt = p_cur;
                g_nxt = g_cur;
                for (int bit_i = stride; bit_i < ACC_W; ++bit_i) begin
                    g_nxt[bit_i] = g_cur[bit_i] | (p_cur[bit_i] & g_cur[bit_i - stride]);
                    p_nxt[bit_i] = p_cur[bit_i] & p_cur[bit_i - stride];
                end
                p_cur = p_nxt;
                g_cur = g_nxt;
            end
        end

        carries[0] = 1'b0;
        for (int b = 1; b < ACC_W; ++b) begin
            carries[b] = g_cur[b - 1];
        end
        sum_res = (op_a ^ op_b) ^ carries;
        return sum_res;
    endfunction

    logic [ACC_W-1:0]   l1_sum_a;
    logic [ACC_W-1:0]   l1_car_a;
    logic [ACC_W-1:0]   l1_sum_b;
    logic [ACC_W-1:0]   l1_car_b;
    logic [ACC_W-1:0]   c_term;

    logic [ACC_W-1:0]   l2_sum;
    logic [ACC_W-1:0]   l2_car;
    logic [ACC_W-1:0]   l3_sum;
    logic [ACC_W-1:0]   l3_car;

    logic [2*ACC_W-1:0] pack_l1a;
    logic [2*ACC_W-1:0] pack_l1b;
    logic [2*ACC_W-1:0] pack_l2;
    logic [2*ACC_W-1:0] pack_l3;

    assign c_term = terms_in[LANES];

    if (LANES == 8) begin : g_csa_9_to_2
        // Level 1: two parallel 4:2 compressors on lanes 0..3 and 4..7 -> 4 vectors
        assign pack_l1a = csa_42_compress(terms_in[0], terms_in[1], terms_in[2], terms_in[3]);
        assign pack_l1b = csa_42_compress(terms_in[4], terms_in[5], terms_in[6], terms_in[7]);
        assign l1_sum_a = pack_l1a[ACC_W-1:0];
        assign l1_car_a = pack_l1a[2*ACC_W-1:ACC_W];
        assign l1_sum_b = pack_l1b[ACC_W-1:0];
        assign l1_car_b = pack_l1b[2*ACC_W-1:ACC_W];

        // Level 2: 4:2 compressor on (l1_sum_a, l1_car_a, l1_sum_b, l1_car_b) -> 2 vectors
        assign pack_l2 = csa_42_compress(l1_sum_a, l1_car_a, l1_sum_b, l1_car_b);
        assign l2_sum  = pack_l2[ACC_W-1:0];
        assign l2_car  = pack_l2[2*ACC_W-1:ACC_W];

        // Level 3: 3:2 compressor combining (l2_sum, l2_car, c_term) -> final (sum, carry)
        assign pack_l3 = csa_32_compress(l2_sum, l2_car, c_term);
        assign l3_sum  = pack_l3[ACC_W-1:0];
        assign l3_car  = pack_l3[2*ACC_W-1:ACC_W];
    end else begin : g_csa_generic
        logic [NUM_TERMS-1:0][ACC_W-1:0] stage_s;
        logic [NUM_TERMS-1:0][ACC_W-1:0] stage_c;

        assign pack_l1a = '0;
        assign pack_l1b = '0;
        assign pack_l2  = '0;
        assign pack_l3  = '0;
        assign l1_sum_a = '0;
        assign l1_car_a = '0;
        assign l1_sum_b = '0;
        assign l1_car_b = '0;

        assign stage_s[0] = terms_in[0];
        assign stage_c[0] = '0;
        for (genvar t = 1; t < LANES; ++t) begin : g_prod_step
            logic [2*ACC_W-1:0] step_pack;
            assign step_pack  = csa_32_compress(stage_s[t-1], stage_c[t-1], terms_in[t]);
            assign stage_s[t] = step_pack[ACC_W-1:0];
            assign stage_c[t] = step_pack[2*ACC_W-1:ACC_W];
        end
        assign l2_sum = stage_s[LANES-1];
        assign l2_car = stage_c[LANES-1];
        assign stage_s[LANES] = l2_sum;
        assign stage_c[LANES] = l2_car;
        assign pack_l3 = csa_32_compress(l2_sum, l2_car, c_term);
        assign l3_sum  = pack_l3[ACC_W-1:0];
        assign l3_car  = pack_l3[2*ACC_W-1:ACC_W];
    end

    assign sum_vec_out   = l3_sum;
    assign carry_vec_out = l3_car;

    // Resolve product-only partial sum alongside full (products + C) sum.
    logic [ACC_W-1:0]   prod_sum;
    logic [ACC_W-1:0]   pos_sum;
    logic [ACC_W-1:0]   dec_s;
    logic [ACC_W-1:0]   dec_c;
    logic [2*ACC_W-1:0] dec_pack;
    logic [ACC_W-1:0]   dec_sum;
    logic [ACC_W-1:0]   neg_mag;

    assign prod_sum = kogge_stone_add(l2_sum, l2_car);
    assign pos_sum  = kogge_stone_add(l3_sum, l3_car);
    assign dec_pack = csa_32_compress(l3_sum, l3_car, {ACC_W{1'b1}});
    assign dec_s    = dec_pack[ACC_W-1:0];
    assign dec_c    = dec_pack[2*ACC_W-1:ACC_W];
    assign dec_sum  = kogge_stone_add(dec_s, dec_c);
    assign neg_mag  = ~dec_sum;

    // Exact 8-lane product sum FIRST (zero sticky loss since lanes share block scale),
    // then combine normalized lane_sum with C as a 2-term exact addition.
    localparam int GUARD_BITS = 4;
    localparam int FRAC_SLOTS = ACC_W - GUARD_BITS - 1;
    localparam int LZC_W      = $clog2(ACC_W);
    localparam int SH_W       = $clog2(ACC_W + 1);

    logic [ACC_W-1:0] lane_l1_s_a;
    logic [ACC_W-1:0] lane_l1_c_a;
    logic [ACC_W-1:0] lane_l1_s_b;
    logic [ACC_W-1:0] lane_l1_c_b;
    logic [ACC_W-1:0] lane_l2_s;
    logic [ACC_W-1:0] lane_l2_c;
    logic [2*ACC_W-1:0] lane_pack_1a;
    logic [2*ACC_W-1:0] lane_pack_1b;
    logic [2*ACC_W-1:0] lane_pack_2;

    if (LANES == 8) begin : g_lane_csa_8
        assign lane_pack_1a = csa_42_compress(lane_terms_in[0], lane_terms_in[1], lane_terms_in[2], lane_terms_in[3]);
        assign lane_pack_1b = csa_42_compress(lane_terms_in[4], lane_terms_in[5], lane_terms_in[6], lane_terms_in[7]);
        assign lane_l1_s_a  = lane_pack_1a[ACC_W-1:0];
        assign lane_l1_c_a  = lane_pack_1a[2*ACC_W-1:ACC_W];
        assign lane_l1_s_b  = lane_pack_1b[ACC_W-1:0];
        assign lane_l1_c_b  = lane_pack_1b[2*ACC_W-1:ACC_W];
        assign lane_pack_2  = csa_42_compress(lane_l1_s_a, lane_l1_c_a, lane_l1_s_b, lane_l1_c_b);
        assign lane_l2_s    = lane_pack_2[ACC_W-1:0];
        assign lane_l2_c    = lane_pack_2[2*ACC_W-1:ACC_W];
    end else begin : g_lane_csa_gen
        logic [LANES-1:0][ACC_W-1:0] lp_s;
        logic [LANES-1:0][ACC_W-1:0] lp_c;
        assign lane_pack_1a = '0;
        assign lane_pack_1b = '0;
        assign lane_pack_2  = '0;
        assign lane_l1_s_a  = '0;
        assign lane_l1_c_a  = '0;
        assign lane_l1_s_b  = '0;
        assign lane_l1_c_b  = '0;
        assign lp_s[0] = lane_terms_in[0];
        assign lp_c[0] = '0;
        for (genvar lt = 1; lt < LANES; ++lt) begin : g_lp_step
            logic [2*ACC_W-1:0] lp_step;
            assign lp_step = csa_32_compress(lp_s[lt-1], lp_c[lt-1], lane_terms_in[lt]);
            assign lp_s[lt] = lp_step[ACC_W-1:0];
            assign lp_c[lt] = lp_step[2*ACC_W-1:ACC_W];
        end
        assign lane_l2_s = lp_s[LANES-1];
        assign lane_l2_c = lp_c[LANES-1];
    end

    logic [ACC_W-1:0]   lane_sum_tc;
    logic [2*ACC_W-1:0] lane_dec_pack;
    logic [ACC_W-1:0]   lane_dec_sum;
    logic [ACC_W-1:0]   lane_neg_mag;
    logic               lane_sum_sign;
    logic [ACC_W-1:0]   lane_sum_mag;
    logic               lane_sum_zero;

    assign lane_sum_tc   = kogge_stone_add(lane_l2_s, lane_l2_c);
    assign lane_dec_pack = csa_32_compress(lane_l2_s, lane_l2_c, {ACC_W{1'b1}});
    assign lane_dec_sum  = kogge_stone_add(lane_dec_pack[ACC_W-1:0], lane_dec_pack[2*ACC_W-1:ACC_W]);
    assign lane_neg_mag  = ~lane_dec_sum;
    assign lane_sum_sign = lane_sum_tc[ACC_W-1];
    assign lane_sum_mag  = lane_sum_sign ? lane_neg_mag : lane_sum_tc;
    assign lane_sum_zero = lanes_all_zero_in || (lane_sum_mag == '0);

    // Normalize lane_sum_mag to an exact exponent + ACC_W-bit left-aligned magnitude.
    logic [LZC_W-1:0]        lane_lzc;
    logic                    lane_lzc_found;
    logic [ACC_W-1:0]        lane_norm_mag;
    logic signed [EXP_W-1:0] lane_sum_exp;

    always_comb begin
        lane_lzc       = '0;
        lane_lzc_found = 1'b0;
        for (int b = ACC_W - 1; b >= 0; --b) begin
            if (lane_sum_mag[b] && !lane_lzc_found) begin
                lane_lzc       = LZC_W'(ACC_W - 1 - b);
                lane_lzc_found = 1'b1;
            end
        end
        if (lane_sum_zero || !lane_lzc_found) begin
            lane_norm_mag = '0;
            lane_sum_exp  = '0;
        end else begin
            lane_norm_mag = lane_sum_mag << lane_lzc;
            lane_sum_exp  = lane_max_exp_in + $signed(EXP_W'(GUARD_BITS))
                          - $signed({{(EXP_W-LZC_W){1'b0}}, lane_lzc});
        end
    end

    // Combine the two exact terms: lane_sum (ACC_W bits normalized at MSB) and C (SIG_W bits normalized at MSB).
    logic signed [EXP_W-1:0] eff_max_exp;
    logic                    two_term_all_zero;
    logic signed [EXP_W:0]   ls_diff_s;
    logic signed [EXP_W:0]   c_diff_s;
    logic [ACC_W-1:0]        ls_base_mag;
    logic [ACC_W-1:0]        c_base_mag;
    logic [ACC_W-1:0]        ls_shifted;
    logic [ACC_W-1:0]        c_shifted;
    logic                    ls_sticky;
    logic                    c_sticky;
    logic [ACC_W-1:0]        ls_tc;
    logic [ACC_W-1:0]        c_tc_two;
    logic [ACC_W-1:0]        two_sum_tc;
    logic [ACC_W-1:0]        two_neg_mag;
    logic                    two_sum_sign;
    logic [ACC_W-1:0]        two_abs_mag;
    logic                    two_is_zero;

    always_comb begin
        if (lane_sum_zero && c_eff_zero_in) begin
            eff_max_exp       = '0;
            two_term_all_zero = 1'b1;
        end else if (lane_sum_zero) begin
            eff_max_exp       = c_norm_exp_in;
            two_term_all_zero = 1'b0;
        end else if (c_eff_zero_in) begin
            eff_max_exp       = lane_sum_exp;
            two_term_all_zero = 1'b0;
        end else begin
            eff_max_exp       = ($signed(lane_sum_exp) >= $signed(c_norm_exp_in)) ? lane_sum_exp : c_norm_exp_in;
            two_term_all_zero = 1'b0;
        end
    end

    // Place leading bit of lane_norm_mag at bit FRAC_SLOTS (right-shift by GUARD_BITS),
    // and leading bit of c_norm_sig_in at bit FRAC_SLOTS.
    logic lane_norm_lo_stk;
    assign lane_norm_lo_stk = (!lane_sum_zero) && (|lane_norm_mag[GUARD_BITS-1:0]);
    assign ls_base_mag      = lane_norm_mag >> GUARD_BITS;
    assign c_base_mag       = {
        {GUARD_BITS{1'b0}},
        c_norm_sig_in,
        {(FRAC_SLOTS - SIG_W + 1){1'b0}}
    };

    assign ls_diff_s = $signed({eff_max_exp[EXP_W-1], eff_max_exp})
                     - $signed({lane_sum_exp[EXP_W-1], lane_sum_exp});
    assign c_diff_s  = $signed({eff_max_exp[EXP_W-1], eff_max_exp})
                     - $signed({c_norm_exp_in[EXP_W-1], c_norm_exp_in});

    always_comb begin
        logic [ACC_W-1:0] ls_disc;
        logic [ACC_W-1:0] c_disc;
        logic [SH_W-1:0]  ls_sh;
        logic [SH_W-1:0]  c_sh;

        ls_disc    = '0;
        c_disc     = '0;
        ls_sh      = '0;
        c_sh       = '0;
        ls_shifted = '0;
        ls_sticky  = lane_norm_lo_stk;
        c_shifted  = '0;
        c_sticky   = 1'b0;

        if (lane_sum_zero) begin
            ls_shifted = '0;
            ls_sticky  = 1'b0;
        end else if ((ls_diff_s < 0) || (ls_diff_s >= $signed((EXP_W+1)'(ACC_W)))) begin
            ls_shifted = '0;
            ls_disc    = ls_base_mag;
            ls_sticky  = (|ls_disc) | lane_norm_lo_stk;
        end else if (ls_diff_s == 0) begin
            ls_shifted = ls_base_mag;
            ls_sticky  = lane_norm_lo_stk;
        end else begin
            ls_sh      = ls_diff_s[SH_W-1:0];
            ls_shifted = ls_base_mag >> ls_sh;
            ls_disc    = ls_base_mag & (({ACC_W{1'b1}}) >> (SH_W'(ACC_W) - ls_sh));
            ls_sticky  = (|ls_disc) | lane_norm_lo_stk;
        end

        if (c_eff_zero_in) begin
            c_shifted = '0;
            c_sticky  = 1'b0;
        end else if ((c_diff_s < 0) || (c_diff_s >= $signed((EXP_W+1)'(ACC_W)))) begin
            c_shifted = '0;
            c_disc    = c_base_mag;
            c_sticky  = (|c_disc);
        end else if (c_diff_s == 0) begin
            c_shifted = c_base_mag;
            c_sticky  = 1'b0;
        end else begin
            c_sh      = c_diff_s[SH_W-1:0];
            c_shifted = c_base_mag >> c_sh;
            c_disc    = c_base_mag & (({ACC_W{1'b1}}) >> (SH_W'(ACC_W) - c_sh));
            c_sticky  = (|c_disc);
        end

        ls_tc    = lane_sum_zero ? '0 : (lane_sum_sign ? ((~ls_shifted) + {{(ACC_W-1){1'b0}}, 1'b1}) : ls_shifted);
        c_tc_two = c_eff_zero_in ? '0 : (c_eff_sign_in ? ((~c_shifted)  + {{(ACC_W-1){1'b0}}, 1'b1}) : c_shifted);
    end

    assign two_sum_tc   = kogge_stone_add(ls_tc, c_tc_two);
    assign two_neg_mag  = (~two_sum_tc) + {{(ACC_W-1){1'b0}}, 1'b1};
    assign two_sum_sign = two_sum_tc[ACC_W-1];
    assign two_abs_mag  = two_sum_sign ? two_neg_mag : two_sum_tc;
    assign two_is_zero  = two_term_all_zero || (two_abs_mag == '0);

    // Track exact positive and negative sticky from the two-term addition (and original sticky_in metadata).
    logic two_pos_sticky;
    logic two_neg_sticky;
    assign two_pos_sticky = (ls_sticky && !lane_sum_sign) || (c_sticky && !c_eff_sign_in);
    assign two_neg_sticky = (ls_sticky &&  lane_sum_sign) || (c_sticky &&  c_eff_sign_in);

    assign signed_sum_out     = two_sum_tc;
    assign sign_out           = two_sum_sign;
    assign mag_out            = two_abs_mag;
    assign is_zero_out        = two_is_zero;
    assign eff_max_exp_out    = eff_max_exp;
    assign prod_only_sum_out  = prod_sum;
    assign prod_only_sign_out = prod_sum[ACC_W-1];
    assign prod_only_zero_out = (prod_sum == '0);
    assign c_flipped_sign_out = (c_term != '0) && (two_sum_tc != '0) && (c_term[ACC_W-1] != two_sum_tc[ACC_W-1]);

    `UNUSED_VAR (pos_sum)
    `UNUSED_VAR (neg_mag)

    // Split positive vs negative partial sums for cancellation and catastrophic-cancellation telemetry.
    logic [ACC_W-1:0] pos_acc_sum;
    logic [ACC_W-1:0] neg_acc_sum;
    logic             any_pos_term;
    logic             any_neg_term;
    logic [3:0]       nz_cnt;
    logic [3:0]       stk_cnt;

    always_comb begin
        pos_acc_sum  = '0;
        neg_acc_sum  = '0;
        any_pos_term = 1'b0;
        any_neg_term = 1'b0;
        nz_cnt       = 4'd0;
        stk_cnt      = 4'd0;

        for (int idx = 0; idx < NUM_TERMS; ++idx) begin
            if (terms_in[idx] != '0) begin
                nz_cnt = nz_cnt + 4'd1;
                if (terms_in[idx][ACC_W-1]) begin
                    any_neg_term = 1'b1;
                    neg_acc_sum  = neg_acc_sum + terms_in[idx];
                end else begin
                    any_pos_term = 1'b1;
                    pos_acc_sum  = pos_acc_sum + terms_in[idx];
                end
            end
            if (sticky_in[idx]) begin
                stk_cnt = stk_cnt + 4'd1;
            end
        end
    end

    `UNUSED_VAR (term_sign_in)

    assign sticky_out             = two_pos_sticky | two_neg_sticky;
    assign pos_sticky_out         = two_pos_sticky;
    assign neg_sticky_out         = two_neg_sticky;
    assign sticky_sign_out        = two_neg_sticky && !two_pos_sticky;
    assign pos_terms_present_out  = any_pos_term;
    assign neg_terms_present_out  = any_neg_term;
    assign nonzero_terms_cnt_out  = nz_cnt;
    assign exact_cancel_out       = two_is_zero && !(two_pos_sticky || two_neg_sticky) &&
                                    ((!lanes_all_zero_in) || (!c_eff_zero_in));
    assign sum_overflow_guard_out = (mag_out[ACC_W-1] == 1'b1);
    assign pos_partial_sum_out    = pos_acc_sum;
    assign neg_partial_sum_out    = neg_acc_sum;
    assign sticky_parity_out      = ^sticky_in;
    assign sticky_count_out       = stk_cnt;

    `STATIC_ASSERT(NUM_TERMS >= 2, ("CSA tree requires at least 2 terms"))

endmodule
