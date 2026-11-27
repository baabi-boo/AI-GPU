// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp8_fedp_align #(
    parameter int   LANES      = 8,
    parameter int   ACC_MAG_W  = 64,
    parameter int   ACC_SIGN_W = 72,
    parameter logic OUT_REG    = 1'b0
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                enable,
    input  logic                                valid_in,
    input  logic [LANES-1:0][21:0]              prod_sig22_in,
    input  logic [LANES-1:0][10:0]              prod_exp_s11_in,
    input  logic [LANES-1:0]                    prod_sign_in,
    input  logic [LANES-1:0]                    prod_zero_in,
    input  logic [LANES-1:0]                    prod_inf_in,
    input  logic [LANES-1:0]                    prod_nan_in,
    input  logic [31:0]                         c_fp32_in,
    input  logic                                accum_en,
    output logic                                valid_out,
    output logic signed [10:0]                  max_exp_s11_out,
    output logic                                has_active_term_out,
    output logic [LANES:0][ACC_SIGN_W-1:0]      aligned_tc_out,
    output logic [LANES:0]                      sticky_bits_out,
    output logic [LANES:0]                      sticky_pos_out,
    output logic [LANES:0]                      sticky_neg_out,
    output logic [LANES:0]                      term_active_out,
    output logic [LANES:0]                      term_overshift_out,
    output logic                                c_is_zero_out,
    output logic                                c_is_neg_zero_out,
    output logic                                c_is_inf_out,
    output logic                                c_is_nan_out,
    output logic                                c_is_snan_out,
    output logic                                c_sign_out,
    output logic signed [10:0]                  c_exp_s11_out,
    output logic [23:0]                         c_norm_sig24_out,
    output logic                                c_active_out,
    output logic signed [10:0]                  lane_max_exp_s11_out,
    output logic                                lanes_active_out,
    output logic [LANES-1:0][ACC_SIGN_W-1:0]    lane_aligned_tc_out,
    output logic [LANES-1:0]                    lane_sticky_pos_out,
    output logic [LANES-1:0]                    lane_sticky_neg_out,
    output logic signed [10:0]                  tail_max_exp_s11_out,
    output logic                                tail_active_out,
    output logic [LANES-1:0][ACC_SIGN_W-1:0]    tail_aligned_tc_out,
    output logic [LANES-1:0]                    tail_sub_stk_pos_out,
    output logic [LANES-1:0]                    tail_sub_stk_neg_out
);
    import VX_tcu_v2_pkg::*;

    localparam int NUM_TERMS   = LANES + 1;
    localparam int TREE_LVL    = $clog2(NUM_TERMS) + 1;
    localparam int TREE_W      = 1 << TREE_LVL;
    localparam int SHIFT_AMT_W = 11;
    localparam int TZC_W       = $clog2(ACC_MAG_W);

    // -------------------------------------------------------------------------
    // Helper: Binary-Tree Leading-Zero Counter (24-bit for FP32 C subnormal)
    // -------------------------------------------------------------------------
    function automatic logic [4:0] clz24(
        input logic [23:0] vec_in
    );
        logic [23:0] v;
        logic [4:0]  cnt;
        logic [15:0] hi16;
        logic [7:0]  hi8;
        logic [3:0]  hi4;
        logic        hi2_msb;
        begin
            v   = vec_in;
            cnt = 5'd0;
            if (v[23:8] == 16'd0) begin
                cnt[4] = 1'b1;
                hi16   = {v[7:0], 8'd0};
            end else begin
                cnt[4] = 1'b0;
                hi16   = v[23:8];
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
    // Helper: Binary-Tree Trailing-Zero Counter (parameterizable up to 64-bit)
    // -------------------------------------------------------------------------
    function automatic logic [5:0] ctz_acc(
        input logic [ACC_MAG_W-1:0] vec_in,
        output logic                nz_out
    );
        logic [63:0] v64;
        logic [5:0]  cnt;
        logic [31:0] s32;
        logic [15:0] s16;
        logic [7:0]  s8;
        logic [3:0]  s4;
        logic        s2_lsb;
        begin
            v64 = 64'(vec_in);
            nz_out = (vec_in != {ACC_MAG_W{1'b0}});
            cnt = 6'd0;
            if (v64[31:0] == 32'd0) begin
                cnt[5] = 1'b1;
                s32    = v64[63:32];
            end else begin
                cnt[5] = 1'b0;
                s32    = v64[31:0];
            end
            if (s32[15:0] == 16'd0) begin
                cnt[4] = 1'b1;
                s16    = s32[31:16];
            end else begin
                cnt[4] = 1'b0;
                s16    = s32[15:0];
            end
            if (s16[7:0] == 8'd0) begin
                cnt[3] = 1'b1;
                s8     = s16[15:8];
            end else begin
                cnt[3] = 1'b0;
                s8     = s16[7:0];
            end
            if (s8[3:0] == 4'd0) begin
                cnt[2] = 1'b1;
                s4     = s8[7:4];
            end else begin
                cnt[2] = 1'b0;
                s4     = s8[3:0];
            end
            if (s4[1:0] == 2'd0) begin
                cnt[1] = 1'b1;
                s2_lsb = s4[2] | (s4[3] & 1'b0);
            end else begin
                cnt[1] = 1'b0;
                s2_lsb = s4[0];
            end
            cnt[0] = ~s2_lsb;
            return cnt;
        end
    endfunction

    // -------------------------------------------------------------------------
    // Unpack FP32 Accumulator Input C with Subnormal Normalization
    // -------------------------------------------------------------------------
    logic        c_raw_sign;
    logic [7:0]  c_raw_exp;
    logic [22:0] c_raw_man;
    logic        c_exp_zero;
    logic        c_exp_max;
    logic        c_man_zero;
    logic        c_is_zero_raw;
    logic        c_is_subnorm_raw;
    logic        c_is_inf_raw;
    logic        c_is_nan_raw;
    logic        c_is_snan_raw;

    logic        comb_c_is_zero;
    logic        comb_c_is_neg_zero;
    logic        comb_c_is_inf;
    logic        comb_c_is_nan;
    logic        comb_c_is_snan;
    logic        comb_c_sign;

    logic [4:0]         c_sub_lzc;
    logic [23:0]        c_sub_sig24;
    logic [23:0]        c_norm_sig24;
    logic signed [10:0] c_exp_s11;
    logic               c_active;

    assign c_raw_sign = c_fp32_in[31];
    assign c_raw_exp  = c_fp32_in[30:23];
    assign c_raw_man  = c_fp32_in[22:0];

    assign c_exp_zero = (c_raw_exp == 8'h00);
    assign c_exp_max  = (c_raw_exp == 8'hFF);
    assign c_man_zero = (c_raw_man == 23'd0);

    assign c_is_zero_raw    = c_exp_zero && c_man_zero;
    assign c_is_subnorm_raw = c_exp_zero && !c_man_zero;
    assign c_is_inf_raw     = c_exp_max  && c_man_zero;
    assign c_is_nan_raw     = c_exp_max  && !c_man_zero;
    assign c_is_snan_raw    = c_is_nan_raw && !c_raw_man[22];

    assign comb_c_is_zero     = accum_en ? c_is_zero_raw : 1'b1;
    assign comb_c_is_neg_zero = accum_en && c_is_zero_raw && c_raw_sign;
    assign comb_c_is_inf      = accum_en && c_is_inf_raw;
    assign comb_c_is_nan      = accum_en && c_is_nan_raw;
    assign comb_c_is_snan     = accum_en && c_is_snan_raw;
    assign comb_c_sign        = accum_en ? c_raw_sign : 1'b0;

    always_comb begin
        c_sub_lzc   = clz24({c_raw_man, 1'b0});
        c_sub_sig24 = {c_raw_man, 1'b0} << c_sub_lzc;
        if (!accum_en || c_is_zero_raw || c_is_inf_raw || c_is_nan_raw) begin
            c_norm_sig24 = 24'd0;
            c_exp_s11    = 11'sd0;
            c_active     = 1'b0;
        end else if (c_is_subnorm_raw) begin
            c_norm_sig24 = c_sub_sig24;
            c_exp_s11    = -11'sd126 - $signed({6'd0, c_sub_lzc}) - 11'sd1;
            c_active     = 1'b1;
        end else begin
            c_norm_sig24 = {1'b1, c_raw_man};
            c_exp_s11    = $signed({3'd0, c_raw_exp}) - 11'sd127;
            c_active     = 1'b1;
        end
    end

    // -------------------------------------------------------------------------
    // Assemble Combined (LANES + C) Term Vectors & Find Maximum Exponent
    // -------------------------------------------------------------------------
    logic [NUM_TERMS-1:0][10:0]          term_exp_s11;
    logic [NUM_TERMS-1:0][ACC_MAG_W-1:0] term_mag_base;
    logic [NUM_TERMS-1:0]                term_sign;
    logic [NUM_TERMS-1:0]                comb_term_active;

    for (genvar i = 0; i < LANES; ++i) begin : g_pack_prod_terms
        logic lane_finite_nz;
        assign lane_finite_nz      = !prod_zero_in[i] && !prod_inf_in[i] && !prod_nan_in[i];
        assign term_exp_s11[i]     = prod_exp_s11_in[i];
        assign term_mag_base[i]    = {prod_sig22_in[i], {(ACC_MAG_W - 22){1'b0}}};
        assign term_sign[i]        = prod_sign_in[i];
        assign comb_term_active[i] = lane_finite_nz;
    end

    assign term_exp_s11[LANES]     = c_exp_s11;
    assign term_mag_base[LANES]    = {c_norm_sig24, {(ACC_MAG_W - 24){1'b0}}};
    assign term_sign[LANES]        = comb_c_sign;
    assign comb_term_active[LANES] = c_active;

    // Fully packed binary max-exponent reduction tree.
    logic [TREE_LVL:0][TREE_W-1:0][10:0] max_tree_exp;
    logic [TREE_LVL:0][TREE_W-1:0]       max_tree_vld;

    for (genvar k = 0; k < TREE_W; ++k) begin : g_max_init
        if (k < NUM_TERMS) begin : g_active_leaf
            assign max_tree_exp[0][k] = term_exp_s11[k];
            assign max_tree_vld[0][k] = comb_term_active[k];
        end else begin : g_pad_leaf
            assign max_tree_exp[0][k] = 11'sd0;
            assign max_tree_vld[0][k] = 1'b0;
        end
    end

    for (genvar lvl = 0; lvl < TREE_LVL; ++lvl) begin : g_max_lvl
        localparam int NODES = TREE_W >> (lvl + 1);
        for (genvar j = 0; j < NODES; ++j) begin : g_max_node
            logic signed [10:0] le;
            logic signed [10:0] re;
            logic               lv;
            logic               rv;

            assign le = $signed(max_tree_exp[lvl][2*j]);
            assign re = $signed(max_tree_exp[lvl][2*j+1]);
            assign lv = max_tree_vld[lvl][2*j];
            assign rv = max_tree_vld[lvl][2*j+1];

            always_comb begin
                if (lv && rv) begin
                    max_tree_exp[lvl+1][j] = (le >= re) ? le : re;
                    max_tree_vld[lvl+1][j] = 1'b1;
                end else if (lv) begin
                    max_tree_exp[lvl+1][j] = le;
                    max_tree_vld[lvl+1][j] = 1'b1;
                end else if (rv) begin
                    max_tree_exp[lvl+1][j] = re;
                    max_tree_vld[lvl+1][j] = 1'b1;
                end else begin
                    max_tree_exp[lvl+1][j] = 11'sd0;
                    max_tree_vld[lvl+1][j] = 1'b0;
                end
            end
        end
        for (genvar j = NODES; j < TREE_W; ++j) begin : g_max_unused
            assign max_tree_exp[lvl+1][j] = 11'sd0;
            assign max_tree_vld[lvl+1][j] = 1'b0;
        end
    end

    logic               comb_has_active_term;
    logic signed [10:0] comb_max_exp_s11;

    assign comb_has_active_term = max_tree_vld[TREE_LVL][0];
    assign comb_max_exp_s11     = comb_has_active_term ? $signed(max_tree_exp[TREE_LVL][0]) : 11'sd0;

    // -------------------------------------------------------------------------
    // Per-Term Staged Barrel Right-Shift Alignment, TZC Sticky, Two's Complement
    // -------------------------------------------------------------------------
    logic [NUM_TERMS-1:0][ACC_SIGN_W-1:0] comb_aligned_tc;
    logic [NUM_TERMS-1:0]                 comb_sticky_bits;
    logic [NUM_TERMS-1:0]                 comb_sticky_pos;
    logic [NUM_TERMS-1:0]                 comb_sticky_neg;
    logic [NUM_TERMS-1:0]                 comb_term_overshift;

    for (genvar t = 0; t < NUM_TERMS; ++t) begin : g_align_terms
        logic signed [10:0]     exp_diff;
        logic [SHIFT_AMT_W-1:0] shift_dist;
        logic                   overshift;
        logic [ACC_MAG_W-1:0]   sh_s0;
        logic [ACC_MAG_W-1:0]   sh_s1;
        logic [ACC_MAG_W-1:0]   sh_s2;
        logic [ACC_MAG_W-1:0]   sh_s3;
        logic [ACC_MAG_W-1:0]   sh_s4;
        logic [ACC_MAG_W-1:0]   mag_shifted;
        logic [5:0]             mag_tz6;
        logic [TZC_W-1:0]       mag_tz;
        logic                   mag_nz;
        logic                   sticky_hit;
        logic [ACC_SIGN_W-1:0]  mag_ext;
        logic [ACC_SIGN_W-1:0]  signed_val;

        assign exp_diff   = comb_max_exp_s11 - $signed(term_exp_s11[t]);
        assign shift_dist = exp_diff[SHIFT_AMT_W-1:0];
        assign overshift  = !comb_term_active[t] || (exp_diff < 11'sd0) || (exp_diff >= $signed(11'(ACC_MAG_W)));

        // Explicit 6-stage logarithmic barrel right-shifter (32/16/8/4/2/1)
        always_comb begin
            if (overshift) begin
                sh_s0       = {ACC_MAG_W{1'b0}};
                sh_s1       = {ACC_MAG_W{1'b0}};
                sh_s2       = {ACC_MAG_W{1'b0}};
                sh_s3       = {ACC_MAG_W{1'b0}};
                sh_s4       = {ACC_MAG_W{1'b0}};
                mag_shifted = {ACC_MAG_W{1'b0}};
            end else begin
                sh_s0       = shift_dist[5] ? {{32{1'b0}}, term_mag_base[t][ACC_MAG_W-1:32]} : term_mag_base[t];
                sh_s1       = shift_dist[4] ? {{16{1'b0}}, sh_s0[ACC_MAG_W-1:16]} : sh_s0;
                sh_s2       = shift_dist[3] ? {{8{1'b0}},  sh_s1[ACC_MAG_W-1:8]}  : sh_s1;
                sh_s3       = shift_dist[2] ? {{4{1'b0}},  sh_s2[ACC_MAG_W-1:4]}  : sh_s2;
                sh_s4       = shift_dist[1] ? {{2{1'b0}},  sh_s3[ACC_MAG_W-1:2]}  : sh_s3;
                mag_shifted = shift_dist[0] ? {1'b0,       sh_s4[ACC_MAG_W-1:1]}  : sh_s4;
            end
        end

        always_comb begin
            mag_tz6    = ctz_acc(term_mag_base[t], mag_nz);
            mag_tz     = mag_tz6[TZC_W-1:0];
            sticky_hit = 1'b0;
            if (comb_term_active[t] && mag_nz) begin
                if (exp_diff > $signed({{(11 - TZC_W){1'b0}}, mag_tz})) begin
                    sticky_hit = 1'b1;
                end
            end
        end

        `UNUSED_VAR (shift_dist)
        `UNUSED_VAR (mag_tz6)

        assign mag_ext = {{(ACC_SIGN_W - ACC_MAG_W){1'b0}}, mag_shifted};
        always_comb begin
            if (!comb_term_active[t]) begin
                signed_val = {ACC_SIGN_W{1'b0}};
            end else if (term_sign[t]) begin
                signed_val = (~mag_ext) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
            end else begin
                signed_val = mag_ext;
            end
        end

        assign comb_aligned_tc[t]     = signed_val;
        assign comb_sticky_bits[t]    = sticky_hit;
        assign comb_sticky_pos[t]     = sticky_hit && !term_sign[t];
        assign comb_sticky_neg[t]     = sticky_hit &&  term_sign[t];
        assign comb_term_overshift[t] = comb_term_active[t] && (exp_diff >= $signed(11'(ACC_MAG_W)));
    end

    // Also align product lanes strictly relative to lane_max_exp_s11 AND capture
    // any discarded/overshifted lane bits into a secondary 64-bit tail frame.
    logic signed [10:0]                   comb_lane_max_exp_s11;
    logic                                 comb_lanes_active;
    logic [LANES-1:0][ACC_SIGN_W-1:0]     comb_lane_aligned_tc;
    logic [LANES-1:0]                     comb_lane_sticky_pos;
    logic [LANES-1:0]                     comb_lane_sticky_neg;
    logic [LANES-1:0]                     comb_tl_term_active;
    logic [LANES-1:0][10:0]               comb_tl_term_exp_s11;
    logic [LANES-1:0][ACC_MAG_W-1:0]      comb_tl_term_mag;
    logic [LANES-1:0]                     comb_tl_term_sign;

    always_comb begin
        logic signed [10:0] l_max;
        logic               l_seen;
        l_max  = 11'sd0;
        l_seen = 1'b0;
        for (int k = 0; k < LANES; ++k) begin
            if (comb_term_active[k]) begin
                if (!l_seen || ($signed(term_exp_s11[k]) > l_max)) begin
                    l_max  = $signed(term_exp_s11[k]);
                    l_seen = 1'b1;
                end
            end
        end
        comb_lanes_active     = l_seen;
        comb_lane_max_exp_s11 = l_seen ? l_max : 11'sd0;
    end

    for (genvar lp = 0; lp < LANES; ++lp) begin : g_align_lanes_only
        logic signed [10:0]    lp_diff;
        logic [5:0]            lp_sh;
        logic                  lp_ovsh;
        logic [ACC_MAG_W-1:0]  lp_mag_sh;
        logic [ACC_MAG_W-1:0]  lp_disc_mask;
        logic                  lp_stk;
        logic [ACC_SIGN_W-1:0] lp_ext;
        logic [ACC_SIGN_W-1:0] lp_tc;
        logic [ACC_MAG_W-1:0]  lp_rem_raw;

        logic [5:0]            rem_lzc;
        logic                  rem_hit;

        assign lp_diff = comb_lane_max_exp_s11 - $signed(term_exp_s11[lp]);
        assign lp_ovsh = !comb_term_active[lp] || (lp_diff < 11'sd0) || (lp_diff >= $signed(11'(ACC_MAG_W)));
        assign lp_sh   = lp_diff[5:0];

        always_comb begin
            lp_rem_raw = '0;
            rem_lzc    = 6'd0;
            rem_hit    = 1'b0;
            if (lp_ovsh) begin
                lp_mag_sh    = '0;
                lp_disc_mask = comb_term_active[lp] ? term_mag_base[lp] : '0;
                lp_stk       = comb_term_active[lp] && (|lp_disc_mask);
            end else if (lp_diff == 11'sd0) begin
                lp_mag_sh    = term_mag_base[lp];
                lp_disc_mask = '0;
                lp_stk       = 1'b0;
            end else begin
                lp_mag_sh    = term_mag_base[lp] >> lp_sh;
                lp_disc_mask = term_mag_base[lp] & (({ACC_MAG_W{1'b1}}) >> (7'(ACC_MAG_W) - {1'b0, lp_sh}));
                lp_stk       = (|lp_disc_mask);
                lp_rem_raw   = term_mag_base[lp] << (7'(ACC_MAG_W) - {1'b0, lp_sh});
            end

            lp_ext = {{(ACC_SIGN_W - ACC_MAG_W){1'b0}}, lp_mag_sh};
            if (!comb_term_active[lp]) begin
                lp_tc = '0;
            end else if (term_sign[lp]) begin
                lp_tc = (~lp_ext) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
            end else begin
                lp_tc = lp_ext;
            end

            comb_tl_term_sign[lp] = term_sign[lp];
            if (!comb_term_active[lp] || !lp_stk) begin
                comb_tl_term_active[lp]  = 1'b0;
                comb_tl_term_exp_s11[lp] = 11'sd0;
                comb_tl_term_mag[lp]     = '0;
            end else if (lp_ovsh) begin
                comb_tl_term_active[lp]  = 1'b1;
                comb_tl_term_exp_s11[lp] = term_exp_s11[lp];
                comb_tl_term_mag[lp]     = term_mag_base[lp];
            end else begin
                for (int rb = ACC_MAG_W - 1; rb >= 0; --rb) begin
                    if (lp_rem_raw[rb] && !rem_hit) begin
                        rem_lzc = 6'(ACC_MAG_W - 1 - rb);
                        rem_hit = 1'b1;
                    end
                end
                comb_tl_term_active[lp]  = rem_hit;
                comb_tl_term_exp_s11[lp] = comb_lane_max_exp_s11 - $signed(11'(ACC_MAG_W))
                                         - $signed({5'd0, rem_lzc});
                comb_tl_term_mag[lp]     = lp_rem_raw << rem_lzc;
            end
        end

        assign comb_lane_aligned_tc[lp] = lp_tc;
        assign comb_lane_sticky_pos[lp] = lp_stk && !term_sign[lp];
        assign comb_lane_sticky_neg[lp] = lp_stk &&  term_sign[lp];
    end

    // Secondary 64-bit tail-lane alignment frame
    logic signed [10:0]               comb_tail_max_exp_s11;
    logic                             comb_tail_active;
    logic [LANES-1:0][ACC_SIGN_W-1:0] comb_tail_aligned_tc;
    logic [LANES-1:0]                 comb_tail_sub_stk_pos;
    logic [LANES-1:0]                 comb_tail_sub_stk_neg;

    always_comb begin
        logic signed [10:0] t_max;
        logic               t_seen;
        t_max  = 11'sd0;
        t_seen = 1'b0;
        for (int k = 0; k < LANES; ++k) begin
            if (comb_tl_term_active[k]) begin
                if (!t_seen || ($signed(comb_tl_term_exp_s11[k]) > t_max)) begin
                    t_max  = $signed(comb_tl_term_exp_s11[k]);
                    t_seen = 1'b1;
                end
            end
        end
        comb_tail_active      = t_seen;
        comb_tail_max_exp_s11 = t_seen ? t_max : 11'sd0;
    end

    for (genvar tp = 0; tp < LANES; ++tp) begin : g_align_tail_lanes
        logic signed [10:0]    tp_diff;
        logic [5:0]            tp_sh;
        logic                  tp_ovsh;
        logic [ACC_MAG_W-1:0]  tp_mag_sh;
        logic [ACC_MAG_W-1:0]  tp_disc_mask;
        logic                  tp_stk;
        logic [ACC_SIGN_W-1:0] tp_ext;
        logic [ACC_SIGN_W-1:0] tp_tc;

        assign tp_diff = comb_tail_max_exp_s11 - $signed(comb_tl_term_exp_s11[tp]);
        assign tp_ovsh = !comb_tl_term_active[tp] || (tp_diff < 11'sd0) || (tp_diff >= $signed(11'(ACC_MAG_W)));
        assign tp_sh   = tp_diff[5:0];

        always_comb begin
            if (tp_ovsh) begin
                tp_mag_sh    = '0;
                tp_disc_mask = comb_tl_term_active[tp] ? comb_tl_term_mag[tp] : '0;
                tp_stk       = comb_tl_term_active[tp] && (|tp_disc_mask);
            end else if (tp_diff == 11'sd0) begin
                tp_mag_sh    = comb_tl_term_mag[tp];
                tp_disc_mask = '0;
                tp_stk       = 1'b0;
            end else begin
                tp_mag_sh    = comb_tl_term_mag[tp] >> tp_sh;
                tp_disc_mask = comb_tl_term_mag[tp] & (({ACC_MAG_W{1'b1}}) >> (7'(ACC_MAG_W) - {1'b0, tp_sh}));
                tp_stk       = (|tp_disc_mask);
            end

            tp_ext = {{(ACC_SIGN_W - ACC_MAG_W){1'b0}}, tp_mag_sh};
            if (!comb_tl_term_active[tp]) begin
                tp_tc = '0;
            end else if (comb_tl_term_sign[tp]) begin
                tp_tc = (~tp_ext) + {{(ACC_SIGN_W - 1){1'b0}}, 1'b1};
            end else begin
                tp_tc = tp_ext;
            end
        end

        assign comb_tail_aligned_tc[tp]  = tp_tc;
        assign comb_tail_sub_stk_pos[tp] = tp_stk && !comb_tl_term_sign[tp];
        assign comb_tail_sub_stk_neg[tp] = tp_stk &&  comb_tl_term_sign[tp];
    end

    logic       comb_c_dominates_max;
    logic [3:0] comb_active_term_cnt;
    always_comb begin
        comb_c_dominates_max = c_active && (c_exp_s11 == comb_max_exp_s11);
        comb_active_term_cnt = 4'd0;
        for (int idx = 0; idx < NUM_TERMS; ++idx) begin
            comb_active_term_cnt = comb_active_term_cnt + {3'd0, comb_term_active[idx]};
        end
    end

    `UNUSED_VAR (comb_c_dominates_max)
    `UNUSED_VAR (comb_active_term_cnt)

    // -------------------------------------------------------------------------
    // Optional Registered Output Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic                                 valid_r;
        logic signed [10:0]                   max_exp_s11_r;
        logic                                 has_active_term_r;
        logic [NUM_TERMS-1:0][ACC_SIGN_W-1:0] aligned_tc_r;
        logic [NUM_TERMS-1:0]                 sticky_bits_r;
        logic [NUM_TERMS-1:0]                 sticky_pos_r;
        logic [NUM_TERMS-1:0]                 sticky_neg_r;
        logic [NUM_TERMS-1:0]                 term_active_r;
        logic [NUM_TERMS-1:0]                 term_overshift_r;
        logic                                 c_is_zero_r;
        logic                                 c_is_neg_zero_r;
        logic                                 c_is_inf_r;
        logic                                 c_is_nan_r;
        logic                                 c_is_snan_r;
        logic                                 c_sign_r;
        logic signed [10:0]                   c_exp_s11_r;
        logic [23:0]                          c_norm_sig24_r;
        logic                                 c_active_r;
        logic signed [10:0]                   lane_max_exp_s11_r;
        logic                                 lanes_active_r;
        logic [LANES-1:0][ACC_SIGN_W-1:0]     lane_aligned_tc_r;
        logic [LANES-1:0]                     lane_sticky_pos_r;
        logic [LANES-1:0]                     lane_sticky_neg_r;
        logic signed [10:0]                   tail_max_exp_s11_r;
        logic                                 tail_active_r;
        logic [LANES-1:0][ACC_SIGN_W-1:0]     tail_aligned_tc_r;
        logic [LANES-1:0]                     tail_sub_stk_pos_r;
        logic [LANES-1:0]                     tail_sub_stk_neg_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r            <= 1'b0;
                max_exp_s11_r      <= 11'sd0;
                has_active_term_r  <= 1'b0;
                aligned_tc_r       <= '0;
                sticky_bits_r      <= '0;
                sticky_pos_r       <= '0;
                sticky_neg_r       <= '0;
                term_active_r      <= '0;
                term_overshift_r   <= '0;
                c_is_zero_r        <= 1'b1;
                c_is_neg_zero_r    <= 1'b0;
                c_is_inf_r         <= 1'b0;
                c_is_nan_r         <= 1'b0;
                c_is_snan_r        <= 1'b0;
                c_sign_r           <= 1'b0;
                c_exp_s11_r        <= 11'sd0;
                c_norm_sig24_r     <= 24'd0;
                c_active_r         <= 1'b0;
                lane_max_exp_s11_r <= 11'sd0;
                lanes_active_r     <= 1'b0;
                lane_aligned_tc_r  <= '0;
                lane_sticky_pos_r  <= '0;
                lane_sticky_neg_r  <= '0;
                tail_max_exp_s11_r <= 11'sd0;
                tail_active_r      <= 1'b0;
                tail_aligned_tc_r  <= '0;
                tail_sub_stk_pos_r <= '0;
                tail_sub_stk_neg_r <= '0;
            end else if (enable) begin
                valid_r            <= valid_in;
                max_exp_s11_r      <= comb_max_exp_s11;
                has_active_term_r  <= comb_has_active_term;
                aligned_tc_r       <= comb_aligned_tc;
                sticky_bits_r      <= comb_sticky_bits;
                sticky_pos_r       <= comb_sticky_pos;
                sticky_neg_r       <= comb_sticky_neg;
                term_active_r      <= comb_term_active;
                term_overshift_r   <= comb_term_overshift;
                c_is_zero_r        <= comb_c_is_zero;
                c_is_neg_zero_r    <= comb_c_is_neg_zero;
                c_is_inf_r         <= comb_c_is_inf;
                c_is_nan_r         <= comb_c_is_nan;
                c_is_snan_r        <= comb_c_is_snan;
                c_sign_r           <= comb_c_sign;
                c_exp_s11_r        <= c_exp_s11;
                c_norm_sig24_r     <= c_norm_sig24;
                c_active_r         <= c_active;
                lane_max_exp_s11_r <= comb_lane_max_exp_s11;
                lanes_active_r     <= comb_lanes_active;
                lane_aligned_tc_r  <= comb_lane_aligned_tc;
                lane_sticky_pos_r  <= comb_lane_sticky_pos;
                lane_sticky_neg_r  <= comb_lane_sticky_neg;
                tail_max_exp_s11_r <= comb_tail_max_exp_s11;
                tail_active_r      <= comb_tail_active;
                tail_aligned_tc_r  <= comb_tail_aligned_tc;
                tail_sub_stk_pos_r <= comb_tail_sub_stk_pos;
                tail_sub_stk_neg_r <= comb_tail_sub_stk_neg;
            end
        end

        assign valid_out            = valid_r;
        assign max_exp_s11_out      = max_exp_s11_r;
        assign has_active_term_out  = has_active_term_r;
        assign aligned_tc_out       = aligned_tc_r;
        assign sticky_bits_out      = sticky_bits_r;
        assign sticky_pos_out       = sticky_pos_r;
        assign sticky_neg_out       = sticky_neg_r;
        assign term_active_out      = term_active_r;
        assign term_overshift_out   = term_overshift_r;
        assign c_is_zero_out        = c_is_zero_r;
        assign c_is_neg_zero_out    = c_is_neg_zero_r;
        assign c_is_inf_out         = c_is_inf_r;
        assign c_is_nan_out         = c_is_nan_r;
        assign c_is_snan_out        = c_is_snan_r;
        assign c_sign_out           = c_sign_r;
        assign c_exp_s11_out        = c_exp_s11_r;
        assign c_norm_sig24_out     = c_norm_sig24_r;
        assign c_active_out         = c_active_r;
        assign lane_max_exp_s11_out = lane_max_exp_s11_r;
        assign lanes_active_out     = lanes_active_r;
        assign lane_aligned_tc_out  = lane_aligned_tc_r;
        assign lane_sticky_pos_out  = lane_sticky_pos_r;
        assign lane_sticky_neg_out  = lane_sticky_neg_r;
        assign tail_max_exp_s11_out = tail_max_exp_s11_r;
        assign tail_active_out      = tail_active_r;
        assign tail_aligned_tc_out  = tail_aligned_tc_r;
        assign tail_sub_stk_pos_out = tail_sub_stk_pos_r;
        assign tail_sub_stk_neg_out = tail_sub_stk_neg_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out            = valid_in;
        assign max_exp_s11_out      = comb_max_exp_s11;
        assign has_active_term_out  = comb_has_active_term;
        assign aligned_tc_out       = comb_aligned_tc;
        assign sticky_bits_out      = comb_sticky_bits;
        assign sticky_pos_out       = comb_sticky_pos;
        assign sticky_neg_out       = comb_sticky_neg;
        assign term_active_out      = comb_term_active;
        assign term_overshift_out   = comb_term_overshift;
        assign c_is_zero_out        = comb_c_is_zero;
        assign c_is_neg_zero_out    = comb_c_is_neg_zero;
        assign c_is_inf_out         = comb_c_is_inf;
        assign c_is_nan_out         = comb_c_is_nan;
        assign c_is_snan_out        = comb_c_is_snan;
        assign c_sign_out           = comb_c_sign;
        assign c_exp_s11_out        = c_exp_s11;
        assign c_norm_sig24_out     = c_norm_sig24;
        assign c_active_out         = c_active;
        assign lane_max_exp_s11_out = comb_lane_max_exp_s11;
        assign lanes_active_out     = comb_lanes_active;
        assign lane_aligned_tc_out  = comb_lane_aligned_tc;
        assign lane_sticky_pos_out  = comb_lane_sticky_pos;
        assign lane_sticky_neg_out  = comb_lane_sticky_neg;
        assign tail_max_exp_s11_out = comb_tail_max_exp_s11;
        assign tail_active_out      = comb_tail_active;
        assign tail_aligned_tc_out  = comb_tail_aligned_tc;
        assign tail_sub_stk_pos_out = comb_tail_sub_stk_pos;
        assign tail_sub_stk_neg_out = comb_tail_sub_stk_neg;
    end

endmodule
