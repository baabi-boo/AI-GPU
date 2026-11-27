// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp8_csa_reduce #(
    parameter int   NUM_TERMS  = 9,
    parameter int   ACC_MAG_W  = 64,
    parameter int   ACC_SIGN_W = 72,
    parameter logic OUT_REG    = 1'b1
) (
    input  logic                                   clk,
    input  logic                                   reset,
    input  logic                                   enable,
    input  logic                                   valid_in,
    input  logic [NUM_TERMS-1:0][ACC_SIGN_W-1:0]   aligned_tc_in,
    input  logic [NUM_TERMS-1:0]                   sticky_bits_in,
    input  logic [NUM_TERMS-1:0]                   sticky_pos_in,
    input  logic [NUM_TERMS-1:0]                   sticky_neg_in,
    input  logic signed [10:0]                     lane_max_exp_s11_in,
    input  logic                                   lanes_active_in,
    input  logic [NUM_TERMS-2:0][ACC_SIGN_W-1:0]   lane_aligned_tc_in,
    input  logic [NUM_TERMS-2:0]                   lane_sticky_pos_in,
    input  logic [NUM_TERMS-2:0]                   lane_sticky_neg_in,
    input  logic signed [10:0]                     tail_max_exp_s11_in,
    input  logic                                   tail_active_in,
    input  logic [NUM_TERMS-2:0][ACC_SIGN_W-1:0]   tail_aligned_tc_in,
    input  logic [NUM_TERMS-2:0]                   tail_sub_stk_pos_in,
    input  logic [NUM_TERMS-2:0]                   tail_sub_stk_neg_in,
    input  logic signed [10:0]                     c_exp_s11_in,
    input  logic [23:0]                            c_norm_sig24_in,
    input  logic                                   c_active_in,
    input  logic                                   c_sign_in,
    output logic                                   valid_out,
    output logic [ACC_SIGN_W-1:0]                  sum_tc_out,
    output logic [ACC_SIGN_W-1:0]                  abs_mag_out,
    output logic                                   sum_sign_out,
    output logic                                   sum_is_zero_out,
    output logic                                   sticky_out,
    output logic                                   sticky_pos_out,
    output logic                                   sticky_neg_out,
    output logic signed [10:0]                     eff_max_exp_s11_out,
    output logic [ACC_SIGN_W-1:0]                  csa_sum_dbg_out,
    output logic [ACC_SIGN_W-1:0]                  csa_carry_dbg_out
);
    // -------------------------------------------------------------------------
    // Internal Packed Compressor & Parallel-Prefix Kogge-Stone Adder Helpers
    // -------------------------------------------------------------------------
    function automatic void csa_3to2_vec(
        input  logic [ACC_SIGN_W-1:0] x_in,
        input  logic [ACC_SIGN_W-1:0] y_in,
        input  logic [ACC_SIGN_W-1:0] z_in,
        output logic [ACC_SIGN_W-1:0] sum_out,
        output logic [ACC_SIGN_W-1:0] carry_out
    );
        logic [ACC_SIGN_W-1:0] s_int;
        logic [ACC_SIGN_W-2:0] c_int;
        begin
            s_int     = x_in ^ y_in ^ z_in;
            c_int     = (x_in[ACC_SIGN_W-2:0] & y_in[ACC_SIGN_W-2:0]) |
                        ((x_in[ACC_SIGN_W-2:0] ^ y_in[ACC_SIGN_W-2:0]) & z_in[ACC_SIGN_W-2:0]);
            sum_out   = s_int;
            carry_out = {c_int, 1'b0};
        end
    endfunction

    function automatic void csa_4to2_vec(
        input  logic [ACC_SIGN_W-1:0] x_in,
        input  logic [ACC_SIGN_W-1:0] y_in,
        input  logic [ACC_SIGN_W-1:0] z_in,
        input  logic [ACC_SIGN_W-1:0] d_in,
        output logic [ACC_SIGN_W-1:0] sum_out,
        output logic [ACC_SIGN_W-1:0] carry_out
    );
        logic [ACC_SIGN_W-1:0] s1_int;
        logic [ACC_SIGN_W-2:0] cout_int;
        logic [ACC_SIGN_W-1:0] cin_vec;
        logic [ACC_SIGN_W-1:0] sum_int;
        logic [ACC_SIGN_W-2:0] carry_int;
        begin
            s1_int    = x_in ^ y_in ^ z_in;
            cout_int  = (x_in[ACC_SIGN_W-2:0] & y_in[ACC_SIGN_W-2:0]) |
                        (y_in[ACC_SIGN_W-2:0] & z_in[ACC_SIGN_W-2:0]) |
                        (x_in[ACC_SIGN_W-2:0] & z_in[ACC_SIGN_W-2:0]);
            cin_vec   = {cout_int, 1'b0};
            sum_int   = s1_int ^ d_in ^ cin_vec;
            carry_int = (s1_int[ACC_SIGN_W-2:0] & d_in[ACC_SIGN_W-2:0]) |
                        (d_in[ACC_SIGN_W-2:0] & cin_vec[ACC_SIGN_W-2:0]) |
                        (s1_int[ACC_SIGN_W-2:0] & cin_vec[ACC_SIGN_W-2:0]);
            sum_out   = sum_int;
            carry_out = {carry_int, 1'b0};
        end
    endfunction

    // 7-stage Kogge-Stone Parallel-Prefix Carry-Lookahead Adder (supports up to 128b)
    function automatic logic [ACC_SIGN_W-1:0] kogge_stone_add(
        input logic [ACC_SIGN_W-1:0] x_in,
        input logic [ACC_SIGN_W-1:0] y_in,
        input logic                  cin
    );
        logic [127:0]          g0;
        logic [127:0]          p0;
        logic [127:0]          g1;
        logic [127:0]          p1;
        logic [127:0]          g2;
        logic [127:0]          p2;
        logic [127:0]          g3;
        logic [127:0]          p3;
        logic [127:0]          g4;
        logic [127:0]          p4;
        logic [127:0]          g5;
        logic [127:0]          p5;
        logic [127:0]          g6;
        logic [127:0]          p6;
        logic [ACC_SIGN_W-2:0] g7_lo;
        logic [ACC_SIGN_W-1:0] carries;
        logic [127:0]          a128;
        logic [127:0]          b128;
        logic [ACC_SIGN_W-1:0] sum_res;
        begin
            a128 = 128'(x_in);
            b128 = 128'(y_in);

            p0 = a128 ^ b128;
            g0 = a128 & b128;

            // Incorporate cin at bit 0 into prefix generation
            g1[0] = g0[0] | (p0[0] & cin);
            p1[0] = 1'b0;
            for (int k = 1; k < 128; ++k) begin : g_ks_s1
                g1[k] = g0[k] | (p0[k] & g0[k-1]);
                p1[k] = p0[k] & p0[k-1];
            end

            for (int k = 0; k < 128; ++k) begin : g_ks_s2
                if (k < 2) begin
                    g2[k] = g1[k];
                    p2[k] = p1[k];
                end else begin
                    g2[k] = g1[k] | (p1[k] & g1[k-2]);
                    p2[k] = p1[k] & p1[k-2];
                end
            end

            for (int k = 0; k < 128; ++k) begin : g_ks_s3
                if (k < 4) begin
                    g3[k] = g2[k];
                    p3[k] = p2[k];
                end else begin
                    g3[k] = g2[k] | (p2[k] & g2[k-4]);
                    p3[k] = p2[k] & p2[k-4];
                end
            end

            for (int k = 0; k < 128; ++k) begin : g_ks_s4
                if (k < 8) begin
                    g4[k] = g3[k];
                    p4[k] = p3[k];
                end else begin
                    g4[k] = g3[k] | (p3[k] & g3[k-8]);
                    p4[k] = p3[k] & p3[k-8];
                end
            end

            for (int k = 0; k < 128; ++k) begin : g_ks_s5
                if (k < 16) begin
                    g5[k] = g4[k];
                    p5[k] = p4[k];
                end else begin
                    g5[k] = g4[k] | (p4[k] & g4[k-16]);
                    p5[k] = p4[k] & p4[k-16];
                end
            end

            for (int k = 0; k < 128; ++k) begin : g_ks_s6
                if (k < 32) begin
                    g6[k] = g5[k];
                    p6[k] = p5[k];
                end else begin
                    g6[k] = g5[k] | (p5[k] & g5[k-32]);
                    p6[k] = p5[k] & p5[k-32];
                end
            end

            for (int k = 0; k < ACC_SIGN_W - 1; ++k) begin : g_ks_s7
                if (k < 64) begin
                    g7_lo[k] = g6[k];
                end else begin
                    g7_lo[k] = g6[k] | (p6[k] & g6[k-64]);
                end
            end

            `UNUSED_VAR (p6)
            carries = {g7_lo, cin};
            sum_res = p0[ACC_SIGN_W-1:0] ^ carries;
            return sum_res;
        end
    endfunction

    // -------------------------------------------------------------------------
    // Multi-Level Packed 4:2 / 3:2 Wallace-Dadda Compressor Tree
    // -------------------------------------------------------------------------
    localparam int MAX_VECS  = (NUM_TERMS < 4) ? 4 : NUM_TERMS;
    localparam int MAX_LEVEL = 6;

    logic [ACC_SIGN_W-1:0] csa_sum_vec;
    logic [ACC_SIGN_W-1:0] csa_carry_vec;

    if (NUM_TERMS == 9) begin : g_csa_9_wallace
        logic [ACC_SIGN_W-1:0] s1_a;
        logic [ACC_SIGN_W-1:0] c1_a;
        logic [ACC_SIGN_W-1:0] s1_b;
        logic [ACC_SIGN_W-1:0] c1_b;
        logic [ACC_SIGN_W-1:0] s2_a;
        logic [ACC_SIGN_W-1:0] c2_a;

        always_comb begin
            // Level 1: Two parallel 4:2 compressors over lanes [0..3] and [4..7]
            csa_4to2_vec(aligned_tc_in[0], aligned_tc_in[1], aligned_tc_in[2], aligned_tc_in[3], s1_a, c1_a);
            csa_4to2_vec(aligned_tc_in[4], aligned_tc_in[5], aligned_tc_in[6], aligned_tc_in[7], s1_b, c1_b);
            // Level 2: 4:2 compressor folding (s1_a, c1_a, s1_b, c1_b)
            csa_4to2_vec(s1_a, c1_a, s1_b, c1_b, s2_a, c2_a);
            // Level 3: 3:2 compressor folding (s2_a, c2_a, C-term [8])
            csa_3to2_vec(s2_a, c2_a, aligned_tc_in[8], csa_sum_vec, csa_carry_vec);
        end
    end else begin : g_csa_generic
        logic [MAX_LEVEL:0][MAX_VECS-1:0][ACC_SIGN_W-1:0] vec_pipe;

        for (genvar v = 0; v < MAX_VECS; ++v) begin : g_init_vecs
            if (v < NUM_TERMS) begin : g_in_term
                assign vec_pipe[0][v] = aligned_tc_in[v];
            end else begin : g_pad_term
                assign vec_pipe[0][v] = {ACC_SIGN_W{1'b0}};
            end
        end

        for (genvar lvl = 0; lvl < MAX_LEVEL; ++lvl) begin : g_red_lvl
            always_comb begin
                for (int w = 0; w < MAX_VECS; ++w) begin
                    vec_pipe[lvl+1][w] = {ACC_SIGN_W{1'b0}};
                end
                for (int g = 0; g < (MAX_VECS / 3); ++g) begin
                    logic [ACC_SIGN_W-1:0] s_v;
                    logic [ACC_SIGN_W-1:0] cr_v;
                    csa_3to2_vec(vec_pipe[lvl][3*g], vec_pipe[lvl][3*g+1], vec_pipe[lvl][3*g+2], s_v, cr_v);
                    vec_pipe[lvl+1][2*g]   = s_v;
                    vec_pipe[lvl+1][2*g+1] = cr_v;
                end
                for (int r = (MAX_VECS / 3) * 3; r < MAX_VECS; ++r) begin
                    int dst_idx;
                    dst_idx = (MAX_VECS / 3) * 2 + (r - (MAX_VECS / 3) * 3);
                    vec_pipe[lvl+1][dst_idx] = vec_pipe[lvl][r];
                end
            end
        end

        assign csa_sum_vec   = vec_pipe[MAX_LEVEL][0];
        assign csa_carry_vec = vec_pipe[MAX_LEVEL][1];
    end

    // -------------------------------------------------------------------------
    // Stage 2A: Reduce Product Lanes First -> Normalize -> Combine with C
    // -------------------------------------------------------------------------
    localparam int HEADROOM_W = ACC_SIGN_W - ACC_MAG_W;
    localparam int LZC_W      = $clog2(ACC_SIGN_W);

    logic [ACC_SIGN_W-1:0] lane_csa_s;
    logic [ACC_SIGN_W-1:0] lane_csa_c;

    if (NUM_TERMS == 9) begin : g_lane_csa_8
        logic [ACC_SIGN_W-1:0] ls1_a;
        logic [ACC_SIGN_W-1:0] lc1_a;
        logic [ACC_SIGN_W-1:0] ls1_b;
        logic [ACC_SIGN_W-1:0] lc1_b;
        always_comb begin
            csa_4to2_vec(lane_aligned_tc_in[0], lane_aligned_tc_in[1], lane_aligned_tc_in[2], lane_aligned_tc_in[3], ls1_a, lc1_a);
            csa_4to2_vec(lane_aligned_tc_in[4], lane_aligned_tc_in[5], lane_aligned_tc_in[6], lane_aligned_tc_in[7], ls1_b, lc1_b);
            csa_4to2_vec(ls1_a, lc1_a, ls1_b, lc1_b, lane_csa_s, lane_csa_c);
        end
    end else begin : g_lane_csa_gen
        logic [NUM_TERMS-2:0][ACC_SIGN_W-1:0] l_s;
        logic [NUM_TERMS-2:0][ACC_SIGN_W-1:0] l_c;
        assign l_s[0] = lane_aligned_tc_in[0];
        assign l_c[0] = '0;
        for (genvar lt = 1; lt < NUM_TERMS - 1; ++lt) begin : g_lt_step
            always_comb begin
                csa_3to2_vec(l_s[lt-1], l_c[lt-1], lane_aligned_tc_in[lt], l_s[lt], l_c[lt]);
            end
        end
        assign lane_csa_s = l_s[NUM_TERMS-2];
        assign lane_csa_c = l_c[NUM_TERMS-2];
    end

    logic [ACC_SIGN_W-1:0] lane_sum_tc;
    logic [ACC_SIGN_W-1:0] lane_dec_s;
    logic [ACC_SIGN_W-1:0] lane_dec_c;
    logic [ACC_SIGN_W-1:0] lane_neg_mag;
    logic                  lane_sum_sign;
    logic [ACC_SIGN_W-1:0] lane_abs_mag;
    logic                  lane_sum_is_zero;
    logic                  lane_stk_pos;
    logic                  lane_stk_neg;

    always_comb begin
        lane_sum_tc = kogge_stone_add(lane_csa_s, lane_csa_c, 1'b0);
        csa_3to2_vec(lane_csa_s, lane_csa_c, {ACC_SIGN_W{1'b1}}, lane_dec_s, lane_dec_c);
        lane_neg_mag = ~kogge_stone_add(lane_dec_s, lane_dec_c, 1'b0);
    end
    assign lane_sum_sign    = lane_sum_tc[ACC_SIGN_W-1];
    assign lane_abs_mag     = lane_sum_sign ? lane_neg_mag : lane_sum_tc;
    assign lane_stk_pos     = |lane_sticky_pos_in;
    assign lane_stk_neg     = |lane_sticky_neg_in;
    assign lane_sum_is_zero = (!lanes_active_in) || ((lane_abs_mag == '0) && !lane_stk_pos && !lane_stk_neg);

    // Normalize lane_abs_mag to leading-1 at bit ACC_SIGN_W-1 and compute lane_sum_exp_s11.
    logic [LZC_W-1:0]      lane_lzc;
    logic                  lane_lzc_hit;
    logic [ACC_SIGN_W-1:0] lane_norm_mag;
    logic signed [10:0]    lane_sum_exp_s11;
    logic                  lane_mag_nz;
    logic                  lane_norm_lo_stk;

    always_comb begin
        lane_lzc     = '0;
        lane_lzc_hit = 1'b0;
        for (int b = ACC_SIGN_W - 1; b >= 0; --b) begin
            if (lane_abs_mag[b] && !lane_lzc_hit) begin
                lane_lzc     = LZC_W'(ACC_SIGN_W - 1 - b);
                lane_lzc_hit = 1'b1;
            end
        end
        lane_mag_nz = lanes_active_in && lane_lzc_hit;
        if (!lane_mag_nz) begin
            lane_norm_mag    = '0;
            lane_sum_exp_s11 = lane_max_exp_s11_in - $signed(11'(ACC_MAG_W));
        end else begin
            lane_norm_mag    = lane_abs_mag << lane_lzc;
            lane_sum_exp_s11 = lane_max_exp_s11_in + $signed(11'(HEADROOM_W))
                             - $signed({{(11-LZC_W){1'b0}}, lane_lzc});
        end
    end

    assign lane_norm_lo_stk = lane_mag_nz && (|lane_norm_mag[HEADROOM_W-1:0]);

    // Combine normalized lane_sum with C (2-term exact addition in ACC_SIGN_W frame).
    logic signed [10:0]    comb_eff_max_exp;
    logic                  two_all_zero;
    logic [ACC_MAG_W-1:0]  ls_base;
    logic [ACC_MAG_W-1:0]  c_base;
    logic signed [10:0]    ls_diff;
    logic signed [10:0]    c_diff;
    logic [ACC_MAG_W-1:0]  ls_shifted;
    logic [ACC_MAG_W-1:0]  c_shifted;
    logic                  ls_lost_stk;
    logic                  c_lost_stk;
    logic [ACC_SIGN_W-1:0] ls_tc_final;
    logic [ACC_SIGN_W-1:0] c_tc_final;

    // Reduce the secondary tail lane frame to resolve exact net tail sign and magnitude
    logic [ACC_SIGN_W-1:0] tail_csa_s;
    logic [ACC_SIGN_W-1:0] tail_csa_c;
    logic [ACC_SIGN_W-1:0] tail_sum_tc;
    logic                  tail_sum_sign;
    logic                  tail_sum_nz;

    if (NUM_TERMS == 9) begin : g_tail_csa_8
        logic [ACC_SIGN_W-1:0] ts1_a;
        logic [ACC_SIGN_W-1:0] tc1_a;
        logic [ACC_SIGN_W-1:0] ts1_b;
        logic [ACC_SIGN_W-1:0] tc1_b;
        always_comb begin
            csa_4to2_vec(tail_aligned_tc_in[0], tail_aligned_tc_in[1], tail_aligned_tc_in[2], tail_aligned_tc_in[3], ts1_a, tc1_a);
            csa_4to2_vec(tail_aligned_tc_in[4], tail_aligned_tc_in[5], tail_aligned_tc_in[6], tail_aligned_tc_in[7], ts1_b, tc1_b);
            csa_4to2_vec(ts1_a, tc1_a, ts1_b, tc1_b, tail_csa_s, tail_csa_c);
        end
    end else begin : g_tail_csa_gen
        logic [NUM_TERMS-2:0][ACC_SIGN_W-1:0] t_s;
        logic [NUM_TERMS-2:0][ACC_SIGN_W-1:0] t_c;
        assign t_s[0] = tail_aligned_tc_in[0];
        assign t_c[0] = '0;
        for (genvar tt = 1; tt < NUM_TERMS - 1; ++tt) begin : g_tt_step
            always_comb begin
                csa_3to2_vec(t_s[tt-1], t_c[tt-1], tail_aligned_tc_in[tt], t_s[tt], t_c[tt]);
            end
        end
        assign tail_csa_s = t_s[NUM_TERMS-2];
        assign tail_csa_c = t_c[NUM_TERMS-2];
    end

    assign tail_sum_tc   = kogge_stone_add(tail_csa_s, tail_csa_c, 1'b0);
    assign tail_sum_sign = tail_sum_tc[ACC_SIGN_W-1];
    assign tail_sum_nz   = tail_active_in && (tail_sum_tc != '0);

    // -------------------------------------------------------------------------
    // Normalize Tail Frame and Promote to Active Operand When Primary Lanes Cancel
    // -------------------------------------------------------------------------
    logic [ACC_SIGN_W-1:0] tail_neg_tc;
    logic [ACC_SIGN_W-1:0] tail_abs_mag;
    logic [LZC_W-1:0]      tail_lzc;
    logic                  tail_lzc_hit;
    logic [ACC_MAG_W-1:0]  tail_norm_mag64;
    logic signed [10:0]    tail_norm_exp_s11;
    logic                  tail_sub_lo_stk;
    logic [ACC_SIGN_W-1:0] tail_norm_sh;

    assign tail_neg_tc  = (~tail_sum_tc) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
    assign tail_abs_mag = tail_sum_sign ? tail_neg_tc : tail_sum_tc;

    always_comb begin
        tail_lzc     = '0;
        tail_lzc_hit = 1'b0;
        for (int b = ACC_SIGN_W - 1; b >= 0; --b) begin
            if (tail_abs_mag[b] && !tail_lzc_hit) begin
                tail_lzc     = LZC_W'(ACC_SIGN_W - 1 - b);
                tail_lzc_hit = 1'b1;
            end
        end
        if (!tail_active_in || !tail_lzc_hit) begin
            tail_norm_sh      = '0;
            tail_norm_mag64   = '0;
            tail_norm_exp_s11 = 11'sd0;
            tail_sub_lo_stk   = 1'b0;
        end else begin
            tail_norm_sh      = tail_abs_mag << tail_lzc;
            tail_norm_mag64   = tail_norm_sh[ACC_SIGN_W-1 -: ACC_MAG_W];
            tail_norm_exp_s11 = tail_max_exp_s11_in + $signed(11'(HEADROOM_W))
                              - $signed({{(11-LZC_W){1'b0}}, tail_lzc});
            tail_sub_lo_stk   = |tail_norm_sh[HEADROOM_W-1:0];
        end
    end

    logic                  eff_ls_active;
    logic [ACC_MAG_W-1:0]  eff_ls_base;
    logic signed [10:0]    eff_ls_exp_s11;
    logic                  eff_ls_sign;
    logic                  eff_ls_lo_stk;
    logic [ACC_MAG_W-1:0]  eff_ls_lo_raw;
    logic                  tail_promoted_to_ls;
    logic                  tail_rem_active;

    assign tail_promoted_to_ls = !lane_mag_nz && tail_active_in && tail_lzc_hit;
    assign tail_rem_active     = tail_active_in && tail_lzc_hit && !tail_promoted_to_ls;

    assign eff_ls_active  = lane_mag_nz || tail_promoted_to_ls;
    assign eff_ls_base    = lane_mag_nz ? lane_norm_mag[ACC_SIGN_W-1 -: ACC_MAG_W] :
                            (tail_promoted_to_ls ? tail_norm_mag64 : '0);
    assign eff_ls_exp_s11 = lane_mag_nz ? lane_sum_exp_s11 :
                            (tail_promoted_to_ls ? tail_norm_exp_s11 : 11'sd0);
    assign eff_ls_sign    = lane_mag_nz ? lane_sum_sign : tail_sum_sign;
    assign eff_ls_lo_stk  = lane_mag_nz ? lane_norm_lo_stk :
                            (tail_promoted_to_ls ? tail_sub_lo_stk : 1'b0);
    assign eff_ls_lo_raw  = lane_mag_nz ? {lane_norm_mag[HEADROOM_W-1:0], {(ACC_MAG_W-HEADROOM_W){1'b0}}} :
                            (tail_promoted_to_ls ? {tail_norm_sh[HEADROOM_W-1:0], {(ACC_MAG_W-HEADROOM_W){1'b0}}} : '0);

    always_comb begin
        if (!eff_ls_active && !c_active_in) begin
            comb_eff_max_exp = 11'sd0;
            two_all_zero     = 1'b1;
        end else if (!eff_ls_active) begin
            comb_eff_max_exp = c_exp_s11_in;
            two_all_zero     = 1'b0;
        end else if (!c_active_in) begin
            comb_eff_max_exp = eff_ls_exp_s11;
            two_all_zero     = 1'b0;
        end else begin
            comb_eff_max_exp = (eff_ls_exp_s11 >= c_exp_s11_in) ? eff_ls_exp_s11 : c_exp_s11_in;
            two_all_zero     = 1'b0;
        end
    end

    `UNUSED_VAR (tail_sum_nz)
    `UNUSED_VAR (lane_sum_is_zero)
    `UNUSED_VAR (lane_stk_pos)
    `UNUSED_VAR (lane_stk_neg)

    assign ls_base = eff_ls_base;
    assign c_base  = c_active_in ? {c_norm_sig24_in, {(ACC_MAG_W - 24){1'b0}}} : '0;
    assign ls_diff = comb_eff_max_exp - eff_ls_exp_s11;
    assign c_diff  = comb_eff_max_exp - c_exp_s11_in;

    logic                  ls_rem_active;
    logic signed [10:0]    ls_rem_exp_s11;
    logic [ACC_MAG_W-1:0]  ls_rem_mag64;
    logic                  c_rem_active;
    logic signed [10:0]    c_rem_exp_s11;
    logic [ACC_MAG_W-1:0]  c_rem_mag64;

    always_comb begin
        logic [ACC_MAG_W-1:0]  ls_disc;
        logic [ACC_MAG_W-1:0]  c_disc;
        logic [6:0]            ls_sh;
        logic [6:0]            c_sh;
        logic [ACC_SIGN_W-1:0] ls_ext;
        logic [ACC_SIGN_W-1:0] c_ext;
        logic [ACC_MAG_W-1:0]  ls_rem_raw;
        logic [ACC_MAG_W-1:0]  c_rem_raw;
        logic [5:0]            ls_rlzc;
        logic                  ls_rhit;
        logic [5:0]            c_rlzc;
        logic                  c_rhit;

        ls_disc       = '0;
        c_disc        = '0;
        ls_sh         = 7'd0;
        c_sh          = 7'd0;
        ls_shifted    = '0;
        ls_lost_stk   = 1'b0;
        c_shifted     = '0;
        c_lost_stk    = 1'b0;
        ls_rem_raw    = '0;
        c_rem_raw     = '0;
        ls_rem_active = 1'b0;
        ls_rem_exp_s11 = 11'sd0;
        ls_rem_mag64  = '0;
        c_rem_active  = 1'b0;
        c_rem_exp_s11 = 11'sd0;
        c_rem_mag64   = '0;
        ls_rlzc       = 6'd0;
        ls_rhit       = 1'b0;
        c_rlzc        = 6'd0;
        c_rhit        = 1'b0;

        if (!eff_ls_active) begin
            ls_shifted  = '0;
            ls_lost_stk = 1'b0;
        end else if ((ls_diff < 11'sd0) || (ls_diff >= $signed(11'(ACC_MAG_W)))) begin
            ls_shifted     = '0;
            ls_disc        = ls_base;
            ls_lost_stk    = (|ls_disc) | eff_ls_lo_stk;
            ls_rem_active  = (|ls_disc);
            ls_rem_exp_s11 = eff_ls_exp_s11;
            ls_rem_mag64   = ls_base;
        end else if (ls_diff == 11'sd0) begin
            ls_shifted  = ls_base;
            ls_lost_stk = eff_ls_lo_stk;
            if (eff_ls_lo_stk) begin
                ls_rem_raw = eff_ls_lo_raw;
                for (int b = ACC_MAG_W - 1; b >= 0; --b) begin
                    if (ls_rem_raw[b] && !ls_rhit) begin
                        ls_rlzc = 6'(ACC_MAG_W - 1 - b);
                        ls_rhit = 1'b1;
                    end
                end
                ls_rem_active  = ls_rhit;
                ls_rem_exp_s11 = eff_ls_exp_s11 - $signed(11'(ACC_MAG_W)) - $signed({5'd0, ls_rlzc});
                ls_rem_mag64   = ls_rem_raw << ls_rlzc;
            end
        end else begin
            ls_sh       = ls_diff[6:0];
            ls_shifted  = ls_base >> ls_sh;
            ls_disc     = ls_base & (({ACC_MAG_W{1'b1}}) >> (7'(ACC_MAG_W) - ls_sh));
            ls_lost_stk = (|ls_disc) | eff_ls_lo_stk;
            if (|ls_disc) begin
                ls_rem_raw = ls_base << (7'(ACC_MAG_W) - ls_sh);
                for (int b = ACC_MAG_W - 1; b >= 0; --b) begin
                    if (ls_rem_raw[b] && !ls_rhit) begin
                        ls_rlzc = 6'(ACC_MAG_W - 1 - b);
                        ls_rhit = 1'b1;
                    end
                end
                ls_rem_active  = ls_rhit;
                ls_rem_exp_s11 = comb_eff_max_exp - $signed(11'(ACC_MAG_W)) - $signed({5'd0, ls_rlzc});
                ls_rem_mag64   = ls_rem_raw << ls_rlzc;
            end else if (eff_ls_lo_stk) begin
                ls_rem_raw = eff_ls_lo_raw;
                for (int b = ACC_MAG_W - 1; b >= 0; --b) begin
                    if (ls_rem_raw[b] && !ls_rhit) begin
                        ls_rlzc = 6'(ACC_MAG_W - 1 - b);
                        ls_rhit = 1'b1;
                    end
                end
                ls_rem_active  = ls_rhit;
                ls_rem_exp_s11 = eff_ls_exp_s11 - $signed(11'(ACC_MAG_W)) - $signed({5'd0, ls_rlzc});
                ls_rem_mag64   = ls_rem_raw << ls_rlzc;
            end
        end

        if (!c_active_in) begin
            c_shifted  = '0;
            c_lost_stk = 1'b0;
        end else if ((c_diff < 11'sd0) || (c_diff >= $signed(11'(ACC_MAG_W)))) begin
            c_shifted     = '0;
            c_disc        = c_base;
            c_lost_stk    = (|c_disc);
            c_rem_active  = (|c_disc);
            c_rem_exp_s11 = c_exp_s11_in;
            c_rem_mag64   = c_base;
        end else if (c_diff == 11'sd0) begin
            c_shifted  = c_base;
            c_lost_stk = 1'b0;
        end else begin
            c_sh       = c_diff[6:0];
            c_shifted  = c_base >> c_sh;
            c_disc     = c_base & (({ACC_MAG_W{1'b1}}) >> (7'(ACC_MAG_W) - c_sh));
            c_lost_stk = (|c_disc);
            if (|c_disc) begin
                c_rem_raw = c_base << (7'(ACC_MAG_W) - c_sh);
                for (int b = ACC_MAG_W - 1; b >= 0; --b) begin
                    if (c_rem_raw[b] && !c_rhit) begin
                        c_rlzc = 6'(ACC_MAG_W - 1 - b);
                        c_rhit = 1'b1;
                    end
                end
                c_rem_active  = c_rhit;
                c_rem_exp_s11 = comb_eff_max_exp - $signed(11'(ACC_MAG_W)) - $signed({5'd0, c_rlzc});
                c_rem_mag64   = c_rem_raw << c_rlzc;
            end
        end

        ls_ext = {{HEADROOM_W{1'b0}}, ls_shifted};
        c_ext  = {{HEADROOM_W{1'b0}}, c_shifted};

        if (!eff_ls_active) begin
            ls_tc_final = '0;
        end else if (eff_ls_sign) begin
            ls_tc_final = (~ls_ext) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
        end else begin
            ls_tc_final = ls_ext;
        end

        if (!c_active_in) begin
            c_tc_final = '0;
        end else if (c_sign_in) begin
            c_tc_final = (~c_ext) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
        end else begin
            c_tc_final = c_ext;
        end
    end

    // Align and add (ls_rem, c_rem, tail_norm) to get exact net sign of overshifted bits
    logic signed [10:0]    rem_max_exp_s11;
    logic                  rem_any_active;
    logic [ACC_SIGN_W-1:0] rem_tc_0, rem_tc_1, rem_tc_2;
    logic [ACC_SIGN_W-1:0] rem_csa_s, rem_csa_c, rem_sum_tc;
    logic                  rem_sub_pos, rem_sub_neg;
    logic                  rem_sum_nz, rem_sum_sign;

    always_comb begin
        logic signed [10:0] rmax;
        logic               rseen;
        logic signed [10:0] d0, d1, d2;
        logic [ACC_MAG_W-1:0] m0, m1, m2;
        logic [ACC_SIGN_W-1:0] e0, e1, e2;
        logic                  m0_lost, m1_lost, m2_lost;

        rmax  = 11'sd0;
        rseen = 1'b0;
        if (ls_rem_active) begin
            rmax  = ls_rem_exp_s11;
            rseen = 1'b1;
        end
        if (c_rem_active && (!rseen || (c_rem_exp_s11 > rmax))) begin
            rmax  = c_rem_exp_s11;
            rseen = 1'b1;
        end
        if (tail_rem_active && (!rseen || (tail_norm_exp_s11 > rmax))) begin
            rmax  = tail_norm_exp_s11;
            rseen = 1'b1;
        end

        rem_max_exp_s11 = rmax;
        rem_any_active  = rseen;
        d0 = rmax - ls_rem_exp_s11;
        d1 = rmax - c_rem_exp_s11;
        d2 = rmax - tail_norm_exp_s11;

        m0 = (!ls_rem_active || d0 < 11'sd0 || d0 >= $signed(11'(ACC_MAG_W))) ? '0 : (ls_rem_mag64 >> d0[5:0]);
        m1 = (!c_rem_active  || d1 < 11'sd0 || d1 >= $signed(11'(ACC_MAG_W))) ? '0 : (c_rem_mag64 >> d1[5:0]);
        m2 = (!tail_rem_active || d2 < 11'sd0 || d2 >= $signed(11'(ACC_MAG_W))) ? '0 : (tail_norm_mag64 >> d2[5:0]);

        m0_lost = ls_rem_active &&
                  ((d0 >= $signed(11'(ACC_MAG_W))) ? (|ls_rem_mag64)
                   : ((d0 > 11'sd0) && ((ls_rem_mag64 << (7'(ACC_MAG_W) - {1'b0, d0[5:0]})) != '0)));
        m1_lost = c_rem_active &&
                  ((d1 >= $signed(11'(ACC_MAG_W))) ? (|c_rem_mag64)
                   : ((d1 > 11'sd0) && ((c_rem_mag64 << (7'(ACC_MAG_W) - {1'b0, d1[5:0]})) != '0)));
        m2_lost = tail_rem_active &&
                  ((d2 >= $signed(11'(ACC_MAG_W))) ? (|tail_norm_mag64)
                   : ((d2 > 11'sd0) && ((tail_norm_mag64 << (7'(ACC_MAG_W) - {1'b0, d2[5:0]})) != '0)));

        e0 = {{HEADROOM_W{1'b0}}, m0};
        e1 = {{HEADROOM_W{1'b0}}, m1};
        e2 = {{HEADROOM_W{1'b0}}, m2};

        rem_tc_0 = (!ls_rem_active) ? '0 : (eff_ls_sign ? ((~e0) + {{(ACC_SIGN_W-1){1'b0}}, 1'b1}) : e0);
        rem_tc_1 = (!c_rem_active)  ? '0 : (c_sign_in   ? ((~e1) + {{(ACC_SIGN_W-1){1'b0}}, 1'b1}) : e1);
        rem_tc_2 = (!tail_rem_active) ? '0 : (tail_sum_sign ? ((~e2) + {{(ACC_SIGN_W-1){1'b0}}, 1'b1}) : e2);

        rem_sub_pos = (|tail_sub_stk_pos_in) ||
                      ((tail_sub_lo_stk && (!tail_promoted_to_ls || (ls_diff == 11'sd0) || eff_ls_lo_stk)) && !tail_sum_sign) ||
                      (m0_lost && !eff_ls_sign) ||
                      (m1_lost && !c_sign_in)   ||
                      (m2_lost && !tail_sum_sign);
        rem_sub_neg = (|tail_sub_stk_neg_in) ||
                      ((tail_sub_lo_stk && (!tail_promoted_to_ls || (ls_diff == 11'sd0) || eff_ls_lo_stk)) && tail_sum_sign) ||
                      (m0_lost &&  eff_ls_sign) ||
                      (m1_lost &&  c_sign_in)   ||
                      (m2_lost &&  tail_sum_sign);

        csa_3to2_vec(rem_tc_0, rem_tc_1, rem_tc_2, rem_csa_s, rem_csa_c);
        rem_sum_tc = kogge_stone_add(rem_csa_s, rem_csa_c, 1'b0);
    end

    `UNUSED_VAR (rem_max_exp_s11)
    `UNUSED_VAR (ls_lost_stk)
    `UNUSED_VAR (c_lost_stk)

    assign rem_sum_nz   = rem_any_active && (rem_sum_tc != '0);
    assign rem_sum_sign = rem_sum_tc[ACC_SIGN_W-1];

    logic [ACC_SIGN_W-1:0] comb_sum_tc;
    logic [ACC_SIGN_W-1:0] neg_sum_tc;
    logic                  comb_sum_sign;
    logic [ACC_SIGN_W-1:0] comb_abs_mag;
    logic                  comb_sum_is_zero;
    logic                  comb_sticky;
    logic                  comb_sticky_pos;
    logic                  comb_sticky_neg;

    assign comb_sum_tc      = kogge_stone_add(ls_tc_final, c_tc_final, 1'b0);
    assign neg_sum_tc       = (~comb_sum_tc) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
    assign comb_sum_sign    = comb_sum_tc[ACC_SIGN_W-1];
    assign comb_abs_mag     = comb_sum_sign ? neg_sum_tc : comb_sum_tc;
    assign comb_sticky_pos  = rem_sum_nz ? !rem_sum_sign : rem_sub_pos;
    assign comb_sticky_neg  = rem_sum_nz ?  rem_sum_sign : rem_sub_neg;
    assign comb_sticky      = comb_sticky_pos | comb_sticky_neg;
    assign comb_sum_is_zero = two_all_zero || ((comb_abs_mag == {ACC_SIGN_W{1'b0}}) && !comb_sticky);

    `UNUSED_VAR (sticky_bits_in)
    `UNUSED_VAR (sticky_pos_in)
    `UNUSED_VAR (sticky_neg_in)

    // Cross-check parity and magnitude headroom (upper guard bits should match sign)
    logic comb_headroom_ovf;
    logic comb_csa_parity;
    assign comb_headroom_ovf = (comb_abs_mag[ACC_SIGN_W-1 -: 4] != 4'd0);
    assign comb_csa_parity   = (^csa_sum_vec) ^ (^csa_carry_vec);

    `UNUSED_VAR (comb_headroom_ovf)
    `UNUSED_VAR (comb_csa_parity)

    // -------------------------------------------------------------------------
    // Optional Pipeline Register Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic                  valid_r;
        logic [ACC_SIGN_W-1:0] sum_tc_r;
        logic [ACC_SIGN_W-1:0] abs_mag_r;
        logic                  sum_sign_r;
        logic                  sum_is_zero_r;
        logic                  sticky_r;
        logic                  sticky_pos_r;
        logic                  sticky_neg_r;
        logic signed [10:0]    eff_max_exp_r;
        logic [ACC_SIGN_W-1:0] csa_sum_dbg_r;
        logic [ACC_SIGN_W-1:0] csa_carry_dbg_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r         <= 1'b0;
                sum_tc_r        <= '0;
                abs_mag_r       <= '0;
                sum_sign_r      <= 1'b0;
                sum_is_zero_r   <= 1'b1;
                sticky_r        <= 1'b0;
                sticky_pos_r    <= 1'b0;
                sticky_neg_r    <= 1'b0;
                eff_max_exp_r   <= 11'sd0;
                csa_sum_dbg_r   <= '0;
                csa_carry_dbg_r <= '0;
            end else if (enable) begin
                valid_r         <= valid_in;
                sum_tc_r        <= comb_sum_tc;
                abs_mag_r       <= comb_abs_mag;
                sum_sign_r      <= comb_sum_sign;
                sum_is_zero_r   <= comb_sum_is_zero;
                sticky_r        <= comb_sticky;
                sticky_pos_r    <= comb_sticky_pos;
                sticky_neg_r    <= comb_sticky_neg;
                eff_max_exp_r   <= comb_eff_max_exp;
                csa_sum_dbg_r   <= csa_sum_vec;
                csa_carry_dbg_r <= csa_carry_vec;
            end
        end

        assign valid_out           = valid_r;
        assign sum_tc_out          = sum_tc_r;
        assign abs_mag_out         = abs_mag_r;
        assign sum_sign_out        = sum_sign_r;
        assign sum_is_zero_out     = sum_is_zero_r;
        assign sticky_out          = sticky_r;
        assign sticky_pos_out      = sticky_pos_r;
        assign sticky_neg_out      = sticky_neg_r;
        assign eff_max_exp_s11_out = eff_max_exp_r;
        assign csa_sum_dbg_out     = csa_sum_dbg_r;
        assign csa_carry_dbg_out   = csa_carry_dbg_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out           = valid_in;
        assign sum_tc_out          = comb_sum_tc;
        assign abs_mag_out         = comb_abs_mag;
        assign sum_sign_out        = comb_sum_sign;
        assign sum_is_zero_out     = comb_sum_is_zero;
        assign sticky_out          = comb_sticky;
        assign sticky_pos_out      = comb_sticky_pos;
        assign sticky_neg_out      = comb_sticky_neg;
        assign eff_max_exp_s11_out = comb_eff_max_exp;
        assign csa_sum_dbg_out     = csa_sum_vec;
        assign csa_carry_dbg_out   = csa_carry_vec;
    end

endmodule
