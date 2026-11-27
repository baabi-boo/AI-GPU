// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_mx_fedp_align import VX_tcu_v2_pkg::*; #(
    parameter int LANES = TCU_V2_MAX_LANES,
    parameter int EXP_W = TCU_V2_FP_EXP_W,
    parameter int SIG_W = TCU_V2_FP_SIG_W,
    parameter int ACC_W = TCU_V2_WIDE_ACC_W
) (
    // Scaled product lanes (0..LANES-1)
    input  logic [LANES-1:0]                         lane_sign_in,
    input  logic signed [LANES-1:0][EXP_W-1:0]       lane_exp_in,
    input  logic [LANES-1:0][SIG_W-1:0]              lane_sig_in,
    input  logic [LANES-1:0]                         lane_is_zero_in,
    // FP32 C accumulator term
    input  logic                                     c_sign_in,
    input  logic signed [EXP_W-1:0]                  c_exp_in,
    input  logic [SIG_W-1:0]                         c_sig_in,
    input  logic                                     c_is_zero_in,
    input  logic                                     c_is_subnormal_in,
    input  logic                                     accum_en,
    // Aligned two's-complement terms + metadata
    output logic signed [EXP_W-1:0]                  max_exp_out,
    output logic [LANES:0][ACC_W-1:0]                aligned_terms_out,
    output logic [LANES:0]                           sticky_vec_out,
    output logic                                     all_terms_zero_out,
    output logic [LANES:0][$clog2(ACC_W+1)-1:0]      shift_dist_dbg_out,
    output logic [LANES:0]                           overshift_vec_out,
    output logic [LANES:0]                           exact_align_vec_out,
    output logic [$clog2(LANES+2)-1:0]               active_term_count_out,
    output logic                                     c_dominates_out,
    output logic                                     any_prod_dominates_out,
    output logic signed [EXP_W-1:0]                  min_active_exp_out,
    output logic signed [EXP_W-1:0]                  exp_spread_out,
    output logic [LANES:0]                           term_negated_out,
    output logic [LANES:0]                           tiny_subulp_sticky_out,
    output logic [3:0]                               max_exp_winner_idx_out,
    output logic signed [EXP_W-1:0]                  c_norm_exp_out,
    output logic [SIG_W-1:0]                         c_norm_sig_out,
    output logic [LANES:0]                           prod_exact_aligned_out,
    output logic                                     pos_sticky_out,
    output logic                                     neg_sticky_out,
    output logic signed [EXP_W-1:0]                  lane_max_exp_out,
    output logic [LANES-1:0][ACC_W-1:0]              lane_aligned_terms_out,
    output logic                                     lanes_all_zero_out,
    output logic                                     c_eff_zero_out,
    output logic                                     c_eff_sign_out
);

    localparam int NUM_TERMS   = LANES + 1;
    localparam int GUARD_BITS  = 4;
    localparam int FRAC_SLOTS  = ACC_W - GUARD_BITS - 1;
    localparam int SHIFT_W     = $clog2(ACC_W + 1);
    localparam int TREE_LEVELS = $clog2(NUM_TERMS);
    localparam int PAD_TERMS   = 1 << TREE_LEVELS;
    localparam logic signed [EXP_W-1:0] NEG_INF_EXP = $signed({1'b1, {(EXP_W-1){1'b0}}});
    localparam logic signed [EXP_W-1:0] POS_INF_EXP = $signed({1'b0, {(EXP_W-1){1'b1}}});

    function automatic logic [4:0] find_msb_offset_24(
        input logic [SIG_W-1:0] sig_val
    );
        logic [4:0] lzc_res;
        logic       found;
        lzc_res = 5'd0;
        found   = 1'b0;
        for (int b = SIG_W - 1; b >= 0; --b) begin
            if (sig_val[b] && !found) begin
                lzc_res = 5'(SIG_W - 1 - b);
                found   = 1'b1;
            end
        end
        return lzc_res;
    endfunction

    function automatic logic [5:0] count_trailing_zeros_acc(
        input logic [ACC_W-1:0] val_w
    );
        logic [5:0] tzc;
        logic       found;
        tzc   = 6'(ACC_W);
        found = 1'b0;
        for (int b = 0; b < ACC_W; ++b) begin
            if (val_w[b] && !found) begin
                tzc   = 6'(b);
                found = 1'b1;
            end
        end
        return tzc;
    endfunction

    // Pack all LANES product terms plus accumulator C (index LANES) into unified packed vectors.
    logic [NUM_TERMS-1:0]                    term_sign;
    logic signed [NUM_TERMS-1:0][EXP_W-1:0]  term_exp;
    logic [NUM_TERMS-1:0][SIG_W-1:0]         term_sig;
    logic [NUM_TERMS-1:0]                    term_zero;
    logic [NUM_TERMS-1:0]                    term_active;

    logic [4:0]                              c_lzc;
    logic [SIG_W-1:0]                        c_sig_norm;
    logic signed [EXP_W-1:0]                 c_exp_norm;
    logic                                    c_eff_zero;

    assign c_eff_zero = (!accum_en) || c_is_zero_in || (c_sig_in == '0);
    assign c_lzc      = find_msb_offset_24(c_sig_in);

    // Normalize subnormal C significand before alignment so bit SIG_W-1 has weight 2^exp.
    always_comb begin
        if (c_eff_zero) begin
            c_sig_norm = '0;
            c_exp_norm = '0;
        end else if (c_is_subnormal_in && !c_sig_in[SIG_W-1]) begin
            c_sig_norm = c_sig_in << c_lzc;
            c_exp_norm = c_exp_in - $signed({{(EXP_W-5){1'b0}}, c_lzc});
        end else begin
            c_sig_norm = c_sig_in;
            c_exp_norm = c_exp_in;
        end
    end

    assign c_norm_exp_out = c_exp_norm;
    assign c_norm_sig_out = c_sig_norm;

    for (genvar i = 0; i < LANES; ++i) begin : g_pack_lanes
        assign term_sign[i]   = lane_sign_in[i];
        assign term_exp[i]    = lane_is_zero_in[i] ? NEG_INF_EXP : lane_exp_in[i];
        assign term_sig[i]    = lane_is_zero_in[i] ? '0 : lane_sig_in[i];
        assign term_zero[i]   = lane_is_zero_in[i];
        assign term_active[i] = !lane_is_zero_in[i];
    end

    assign term_sign[LANES]   = c_sign_in;
    assign term_exp[LANES]    = c_eff_zero ? NEG_INF_EXP : c_exp_norm;
    assign term_sig[LANES]    = c_eff_zero ? '0 : c_sig_norm;
    assign term_zero[LANES]   = c_eff_zero;
    assign term_active[LANES] = !c_eff_zero;

    assign all_terms_zero_out = &term_zero;

    // Fully packed binary reduction trees for max/min active exponents and winner index.
    logic signed [TREE_LEVELS:0][PAD_TERMS-1:0][EXP_W-1:0] exp_max_tree;
    logic signed [TREE_LEVELS:0][PAD_TERMS-1:0][EXP_W-1:0] exp_min_tree;
    logic [TREE_LEVELS:0][PAD_TERMS-1:0][3:0]              idx_max_tree;
    logic [TREE_LEVELS:0][PAD_TERMS-1:0]                   act_tree;

    for (genvar p = 0; p < PAD_TERMS; ++p) begin : g_tree_init
        if (p < NUM_TERMS) begin : g_in_range
            assign exp_max_tree[0][p] = term_active[p] ? term_exp[p] : NEG_INF_EXP;
            assign exp_min_tree[0][p] = term_active[p] ? term_exp[p] : POS_INF_EXP;
            assign idx_max_tree[0][p] = 4'(p);
            assign act_tree[0][p]     = term_active[p];
        end else begin : g_pad
            assign exp_max_tree[0][p] = NEG_INF_EXP;
            assign exp_min_tree[0][p] = POS_INF_EXP;
            assign idx_max_tree[0][p] = 4'd0;
            assign act_tree[0][p]     = 1'b0;
        end
    end

    for (genvar lvl = 0; lvl < TREE_LEVELS; ++lvl) begin : g_tree_lvl
        localparam int NODES = PAD_TERMS >> (lvl + 1);
        for (genvar n = 0; n < NODES; ++n) begin : g_tree_node
            logic signed [EXP_W-1:0] lhs_max;
            logic signed [EXP_W-1:0] rhs_max;
            logic signed [EXP_W-1:0] lhs_min;
            logic signed [EXP_W-1:0] rhs_min;
            logic [3:0]              lhs_idx;
            logic [3:0]              rhs_idx;
            logic                    lhs_act;
            logic                    rhs_act;
            logic                    pick_lhs_max;
            logic                    pick_lhs_min;

            assign lhs_max = exp_max_tree[lvl][2*n];
            assign rhs_max = exp_max_tree[lvl][2*n+1];
            assign lhs_min = exp_min_tree[lvl][2*n];
            assign rhs_min = exp_min_tree[lvl][2*n+1];
            assign lhs_idx = idx_max_tree[lvl][2*n];
            assign rhs_idx = idx_max_tree[lvl][2*n+1];
            assign lhs_act = act_tree[lvl][2*n];
            assign rhs_act = act_tree[lvl][2*n+1];

            always_comb begin
                if (lhs_act && rhs_act) begin
                    pick_lhs_max = (lhs_max >= rhs_max);
                    pick_lhs_min = (lhs_min <= rhs_min);
                end else if (lhs_act) begin
                    pick_lhs_max = 1'b1;
                    pick_lhs_min = 1'b1;
                end else begin
                    pick_lhs_max = 1'b0;
                    pick_lhs_min = 1'b0;
                end
            end

            assign exp_max_tree[lvl+1][n] = pick_lhs_max ? lhs_max : rhs_max;
            assign exp_min_tree[lvl+1][n] = pick_lhs_min ? lhs_min : rhs_min;
            assign idx_max_tree[lvl+1][n] = pick_lhs_max ? lhs_idx : rhs_idx;
            assign act_tree[lvl+1][n]     = lhs_act | rhs_act;
        end
        for (genvar rem = NODES; rem < PAD_TERMS; ++rem) begin : g_tree_unused
            assign exp_max_tree[lvl+1][rem] = NEG_INF_EXP;
            assign exp_min_tree[lvl+1][rem] = POS_INF_EXP;
            assign idx_max_tree[lvl+1][rem] = 4'd0;
            assign act_tree[lvl+1][rem]     = 1'b0;
        end
    end

    logic signed [EXP_W-1:0] max_exp;
    logic signed [EXP_W-1:0] min_exp;
    logic                    any_act_tree;
    assign any_act_tree           = act_tree[TREE_LEVELS][0];
    assign max_exp                = (all_terms_zero_out || !any_act_tree) ? '0 : exp_max_tree[TREE_LEVELS][0];
    assign min_exp                = (all_terms_zero_out || !any_act_tree) ? '0 : exp_min_tree[TREE_LEVELS][0];
    assign max_exp_out            = max_exp;
    assign min_active_exp_out     = min_exp;
    assign exp_spread_out         = all_terms_zero_out ? '0 : (max_exp - min_exp);
    assign max_exp_winner_idx_out = any_act_tree ? idx_max_tree[TREE_LEVELS][0] : 4'd0;

    `UNUSED_VAR (act_tree[TREE_LEVELS][PAD_TERMS-1:1])

    // Also compute product-lane-only max exponent and exact lane alignment (zero sticky loss across lanes).
    logic signed [EXP_W-1:0] lane_max_exp;
    logic                    lanes_all_zero;
    always_comb begin
        logic signed [EXP_W-1:0] p_max;
        logic                    p_seen;
        p_max  = NEG_INF_EXP;
        p_seen = 1'b0;
        for (int k = 0; k < LANES; ++k) begin
            if (term_active[k]) begin
                if (!p_seen || ($signed(term_exp[k]) > $signed(p_max))) begin
                    p_max  = term_exp[k];
                    p_seen = 1'b1;
                end
            end
        end
        lanes_all_zero = !p_seen;
        lane_max_exp   = p_seen ? p_max : '0;
    end

    assign lane_max_exp_out   = lane_max_exp;
    assign lanes_all_zero_out = lanes_all_zero;
    assign c_eff_zero_out     = c_eff_zero;
    assign c_eff_sign_out     = c_sign_in;

    for (genvar lp = 0; lp < LANES; ++lp) begin : g_align_lanes_exact
        logic signed [EXP_W:0] lp_diff_s;
        logic [SHIFT_W-1:0]    lp_shamt;
        logic [ACC_W-1:0]      lp_pre_mag;
        logic [ACC_W-1:0]      lp_shifted;
        logic [ACC_W-1:0]      lp_signed;
        assign lp_diff_s = $signed({lane_max_exp[EXP_W-1], lane_max_exp})
                         - $signed({term_exp[lp][EXP_W-1], term_exp[lp]});
        assign lp_pre_mag = {
            {GUARD_BITS{1'b0}},
            term_sig[lp],
            {(FRAC_SLOTS - SIG_W + 1){1'b0}}
        };
        always_comb begin
            if (term_zero[lp] || (lp_diff_s < 0) || (lp_diff_s >= $signed((EXP_W+1)'(ACC_W)))) begin
                lp_shamt   = SHIFT_W'(ACC_W);
                lp_shifted = '0;
            end else begin
                lp_shamt   = lp_diff_s[SHIFT_W-1:0];
                lp_shifted = lp_pre_mag >> lp_shamt;
            end
            if (term_zero[lp]) begin
                lp_signed = '0;
            end else if (term_sign[lp]) begin
                lp_signed = (~lp_shifted) + {{(ACC_W-1){1'b0}}, 1'b1};
            end else begin
                lp_signed = lp_shifted;
            end
        end
        assign lane_aligned_terms_out[lp] = lp_signed;
    end

    // Right-align every active term into a wide ACC_W-bit signed two's-complement frame.
    // Layout of unsigned aligned magnitude in ACC_W bits:
    //   [ACC_W-1 : ACC_W-GUARD_BITS] : 4 guard/sign/carry bits (all 0 before sign negation)
    //   [FRAC_SLOTS]                 : 2^0 bit (aligned MSB for max_exp)
    //   [FRAC_SLOTS-1 : 0]           : FRAC_SLOTS fractional bits below max_exp
    for (genvar t = 0; t < NUM_TERMS; ++t) begin : g_align_terms
        logic signed [EXP_W:0]    exp_diff_s;
        logic [EXP_W:0]           shift_amt_full;
        logic                     shift_overflow;
        logic [SHIFT_W-1:0]       shift_amt_clamped;

        logic [ACC_W-1:0]         pre_aligned_mag;
        logic [5:0]               pre_tzc;
        logic [ACC_W-1:0]         shifted_mag;
        logic [ACC_W-1:0]         discarded_mask;
        logic                     sticky_bit;
        logic                     sticky_by_tzc;
        logic [ACC_W-1:0]         signed_term;

        assign exp_diff_s        = $signed({max_exp[EXP_W-1], max_exp})
                                 - $signed({term_exp[t][EXP_W-1], term_exp[t]});
        assign shift_amt_full    = term_zero[t] ? '0 : exp_diff_s;
        assign shift_overflow    = (!term_zero[t]) && ((exp_diff_s < 0) || (shift_amt_full >= (EXP_W+1)'(ACC_W)));
        assign shift_amt_clamped = shift_overflow ? SHIFT_W'(ACC_W) : shift_amt_full[SHIFT_W-1:0];

        // Place SIG_W bits starting at bit FRAC_SLOTS downward: [FRAC_SLOTS : FRAC_SLOTS - SIG_W + 1].
        assign pre_aligned_mag = {
            {GUARD_BITS{1'b0}},
            term_sig[t],
            {(FRAC_SLOTS - SIG_W + 1){1'b0}}
        };
        assign pre_tzc = count_trailing_zeros_acc(pre_aligned_mag);

        always_comb begin
            if (term_zero[t]) begin
                shifted_mag    = '0;
                discarded_mask = '0;
                sticky_bit     = 1'b0;
                sticky_by_tzc  = 1'b0;
            end else if (shift_overflow) begin
                shifted_mag    = '0;
                discarded_mask = pre_aligned_mag;
                sticky_bit     = (|pre_aligned_mag);
                sticky_by_tzc  = (|pre_aligned_mag);
            end else if (shift_amt_clamped == '0) begin
                shifted_mag    = pre_aligned_mag;
                discarded_mask = '0;
                sticky_bit     = 1'b0;
                sticky_by_tzc  = 1'b0;
            end else begin
                shifted_mag    = pre_aligned_mag >> shift_amt_clamped;
                discarded_mask = pre_aligned_mag & (({ACC_W{1'b1}}) >> (SHIFT_W'(ACC_W) - shift_amt_clamped));
                sticky_bit     = (|discarded_mask);
                sticky_by_tzc  = (|pre_aligned_mag) && (shift_amt_clamped > pre_tzc);
            end
        end

        // Exact two's complement conversion for signed fixed-point CSA accumulation.
        always_comb begin
            if (term_zero[t]) begin
                signed_term = '0;
            end else if (term_sign[t]) begin
                signed_term = (~shifted_mag) + {{(ACC_W-1){1'b0}}, 1'b1};
            end else begin
                signed_term = shifted_mag;
            end
        end

        assign aligned_terms_out[t]      = signed_term;
        assign sticky_vec_out[t]         = sticky_bit | sticky_by_tzc;
        assign shift_dist_dbg_out[t]     = shift_amt_clamped;
        assign overshift_vec_out[t]      = shift_overflow;
        assign exact_align_vec_out[t]    = (!term_zero[t]) && (shift_amt_clamped == '0);
        assign term_negated_out[t]       = (!term_zero[t]) && term_sign[t];
        assign tiny_subulp_sticky_out[t] = (!term_zero[t]) && (shifted_mag == '0) && (sticky_bit | sticky_by_tzc);
        assign prod_exact_aligned_out[t] = (!term_zero[t]) && !(sticky_bit | sticky_by_tzc);
    end

    always_comb begin
        logic [$clog2(LANES+2)-1:0] act_cnt;
        act_cnt = '0;
        for (int k = 0; k < NUM_TERMS; ++k) begin
            act_cnt = act_cnt + {{($clog2(LANES+2)-1){1'b0}}, term_active[k]};
        end
        active_term_count_out = act_cnt;
    end

    assign c_dominates_out        = (!c_eff_zero) && (term_exp[LANES] == max_exp);
    assign any_prod_dominates_out = (|exact_align_vec_out[LANES-1:0]);

    always_comb begin
        logic p_stk;
        logic n_stk;
        p_stk = 1'b0;
        n_stk = 1'b0;
        for (int idx = 0; idx < NUM_TERMS; ++idx) begin
            if (sticky_vec_out[idx]) begin
                if (term_sign[idx]) begin
                    n_stk = 1'b1;
                end else begin
                    p_stk = 1'b1;
                end
            end
        end
        pos_sticky_out = p_stk;
        neg_sticky_out = n_stk;
    end

    `STATIC_ASSERT(ACC_W >= (SIG_W + GUARD_BITS + 16), ("Wide accumulator width ACC_W too narrow"))

endmodule
