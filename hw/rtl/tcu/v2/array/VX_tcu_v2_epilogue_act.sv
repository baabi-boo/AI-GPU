// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_EPILOGUE_ACT_SV
`define VX_TCU_V2_EPILOGUE_ACT_SV

`include "VX_platform.vh"

module VX_tcu_v2_epilogue_act #(
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
    output logic                                    out_valid,
    input  logic                                    out_ready,
    output VX_tcu_v2_pkg::tcu_v2_uop_t              uop_out,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   tile_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_out
);

    import VX_tcu_v2_pkg::*;

    // -------------------------------------------------------------------------
    // Pure IEEE-754 FP32 Ordering, Multiply, Add, and PWL Activation Helpers
    // -------------------------------------------------------------------------
    function automatic logic fp32_lt_total(
        input logic [31:0] a,
        input logic [31:0] b
    );
        logic sa, sb;
        logic [30:0] ma, mb;
        sa = a[31];
        sb = b[31];
        ma = a[30:0];
        mb = b[30:0];
        if ((ma == 31'd0) && (mb == 31'd0)) begin
            return 1'b0;
        end
        if (sa != sb) begin
            return sa;
        end
        if (sa) begin
            return (ma > mb);
        end
        return (ma < mb);
    endfunction

    function automatic logic [31:0] fp32_abs(
        input logic [30:0] mag
    );
        return {1'b0, mag};
    endfunction

    function automatic logic [31:0] fp32_mul_rne(
        input logic [31:0] a,
        input logic [31:0] b
    );
        logic        sa, sb, sr;
        logic [7:0]  ea, eb;
        logic [22:0] ma, mb;
        logic        a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        logic [23:0] sig_a, sig_b;
        logic signed [9:0] exp_a, exp_b, exp_prod;
        logic [4:0]  lzc_a, lzc_b;
        logic [47:0] prod;
        logic [23:0] mant_24;
        logic        guard, round_bit, sticky, round_up;
        logic [24:0] mant_rnd;
        logic signed [9:0] exp_final;
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

        sig_a = sig_a << lzc_a;
        sig_b = sig_b << lzc_b;
        exp_a = exp_a - $signed({5'b0, lzc_a});
        exp_b = exp_b - $signed({5'b0, lzc_b});

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

    function automatic logic [31:0] fp32_add_rne(
        input logic [31:0] a,
        input logic [31:0] b
    );
        logic        sa, sb, sr;
        logic [7:0]  ea, eb;
        logic [22:0] ma, mb;
        logic        a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        logic [23:0] sig_a, sig_b, sig_hi, sig_lo;
        logic signed [9:0] exp_a, exp_b, exp_hi, exp_lo;
        logic        swap_ab, s_hi, s_lo, eff_sub;
        logic [27:0] ext_hi, ext_lo;
        logic [9:0]  shift_amt;
        logic        sticky;
        logic [28:0] sum_mag;
        logic [26:0] norm_sig;
        logic signed [9:0] norm_exp, final_exp;
        logic [4:0]  lzc_cnt;
        logic        guard, round_bit, stick_bit, round_up;
        logic [24:0] rounded_mant;
        logic [22:0] final_man;

        sa = a[31];
        sb = b[31];
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

        if (a_nan || b_nan) begin
            return TCU_V2_CANONICAL_QNAN;
        end
        if (a_inf && b_inf) begin
            return (sa != sb) ? TCU_V2_CANONICAL_QNAN : (sa ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF);
        end
        if (a_inf) begin
            return sa ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end
        if (b_inf) begin
            return sb ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end
        if (a_zero && b_zero) begin
            return (sa && sb) ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
        end
        if (a_zero) begin
            return b;
        end
        if (b_zero) begin
            return a;
        end

        sig_a = (ea == 8'd0) ? {1'b0, ma} : {1'b1, ma};
        sig_b = (eb == 8'd0) ? {1'b0, mb} : {1'b1, mb};
        exp_a = (ea == 8'd0) ? $signed(10'd1) : $signed({2'b00, ea});
        exp_b = (eb == 8'd0) ? $signed(10'd1) : $signed({2'b00, eb});

        swap_ab = (exp_b > exp_a) || ((exp_b == exp_a) && (sig_b > sig_a));
        if (swap_ab) begin
            s_hi   = sb;
            s_lo   = sa;
            exp_hi = exp_b;
            exp_lo = exp_a;
            sig_hi = sig_b;
            sig_lo = sig_a;
        end else begin
            s_hi   = sa;
            s_lo   = sb;
            exp_hi = exp_a;
            exp_lo = exp_b;
            sig_hi = sig_a;
            sig_lo = sig_b;
        end

        eff_sub   = (s_hi != s_lo);
        shift_amt = 10'(exp_hi - exp_lo);
        ext_hi    = {1'b0, sig_hi, 3'b000};
        ext_lo    = {1'b0, sig_lo, 3'b000};

        sticky = 1'b0;
        if (shift_amt >= 10'd28) begin
            sticky = |ext_lo;
            ext_lo = 28'd0;
        end else if (shift_amt > 10'd0) begin
            for (int b_i = 0; b_i < 28; ++b_i) begin
                if (b_i < int'(shift_amt)) begin
                    sticky = sticky || ext_lo[b_i];
                end
            end
            ext_lo = ext_lo >> shift_amt;
        end
        ext_lo[0] = ext_lo[0] | sticky;

        sum_mag = eff_sub ? ({1'b0, ext_hi} - {1'b0, ext_lo}) : ({1'b0, ext_hi} + {1'b0, ext_lo});
        if (sum_mag == 29'd0) begin
            return TCU_V2_FP32_POS_ZERO;
        end

        sr = s_hi;
        if (sum_mag[27]) begin
            norm_sig    = sum_mag[27:1];
            norm_sig[0] = norm_sig[0] | sum_mag[0];
            norm_exp    = exp_hi + $signed(10'd1);
        end else begin
            lzc_cnt = 5'd0;
            for (int k = 26; k >= 0; --k) begin
                if ((lzc_cnt == 5'(26 - k)) && !sum_mag[k]) begin
                    lzc_cnt = lzc_cnt + 5'd1;
                end
            end
            if ($signed(exp_hi) > $signed({5'b0, lzc_cnt})) begin
                norm_sig = sum_mag[26:0] << lzc_cnt;
                norm_exp = exp_hi - $signed({5'b0, lzc_cnt});
            end else begin
                norm_sig = (exp_hi > $signed(10'd1)) ? (sum_mag[26:0] << (exp_hi - $signed(10'd1))) : sum_mag[26:0];
                norm_exp = $signed(10'd1);
            end
        end

        guard     = norm_sig[2];
        round_bit = norm_sig[1];
        stick_bit = norm_sig[0];
        round_up  = guard && (round_bit || stick_bit || norm_sig[3]);

        rounded_mant = {1'b0, norm_sig[26:3]} + {24'd0, round_up};
        final_exp    = norm_exp;
        if (rounded_mant[24]) begin
            final_man = rounded_mant[23:1];
            final_exp = norm_exp + $signed(10'd1);
        end else begin
            final_man = rounded_mant[22:0];
        end

        if (final_exp >= $signed(10'd255)) begin
            return sr ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end
        if ((final_exp == $signed(10'd1)) && !rounded_mant[23]) begin
            return {sr, 8'd0, final_man};
        end
        return {sr, final_exp[7:0], final_man};
    endfunction

    // Piecewise-linear sigmoid(x) on [0, 5] -> [0.5, 1.0], using symmetry for x < 0
    function automatic logic [31:0] fp32_pwl_silu(
        input logic [31:0] x
    );
        logic [31:0] ax;
        logic [31:0] sig_pos;
        logic [31:0] sig_val;
        logic [31:0] term;
        if (tcu_v2_fp32_is_nan(x)) begin
            return TCU_V2_CANONICAL_QNAN;
        end
        if (tcu_v2_fp32_is_inf(x)) begin
            return x[31] ? TCU_V2_FP32_POS_ZERO : TCU_V2_FP32_POS_INF;
        end
        ax = fp32_abs(x[30:0]);
        if (!fp32_lt_total(ax, 32'h3F80_0000)) begin
            if (!fp32_lt_total(ax, 32'h4080_0000)) begin
                if (!fp32_lt_total(ax, 32'h40A0_0000)) begin
                    sig_pos = 32'h3F80_0000;
                end else begin
                    term    = fp32_mul_rne(32'h3C93_74BC, fp32_add_rne(ax, 32'hC080_0000));
                    sig_pos = fp32_add_rne(32'h3F7B_645A, term);
                end
            end else if (!fp32_lt_total(ax, 32'h4018_0000)) begin
                term    = fp32_mul_rne(32'h3D28_BE62, fp32_add_rne(ax, 32'hC018_0000));
                sig_pos = fp32_add_rne(32'h3F6A_3D71, term);
            end else begin
                term    = fp32_mul_rne(32'h3E09_02DE, fp32_add_rne(ax, 32'hBF80_0000));
                sig_pos = fp32_add_rne(32'h3F3B_22D1, term);
            end
        end else begin
            term    = fp32_mul_rne(32'h3E6C_A5E4, ax);
            sig_pos = fp32_add_rne(32'h3F00_0000, term);
        end
        sig_val = x[31] ? fp32_add_rne(32'h3F80_0000, {1'b1, sig_pos[30:0]}) : sig_pos;
        return fp32_mul_rne(x, sig_val);
    endfunction

    // Piecewise-linear GELU(x) = x * Phi(x) over symmetric breakpoints
    function automatic logic [31:0] fp32_pwl_gelu(
        input logic [31:0] x
    );
        logic [31:0] ax;
        logic [31:0] phi_pos;
        logic [31:0] phi_val;
        logic [31:0] term;
        if (tcu_v2_fp32_is_nan(x)) begin
            return TCU_V2_CANONICAL_QNAN;
        end
        if (tcu_v2_fp32_is_inf(x)) begin
            return x[31] ? TCU_V2_FP32_POS_ZERO : TCU_V2_FP32_POS_INF;
        end
        ax = fp32_abs(x[30:0]);
        if (!fp32_lt_total(ax, 32'h4040_0000)) begin
            phi_pos = 32'h3F80_0000;
        end else if (!fp32_lt_total(ax, 32'h3FC0_0000)) begin
            term    = fp32_mul_rne(32'h3D32_95E9, fp32_add_rne(ax, 32'hBFC0_0000));
            phi_pos = fp32_add_rne(32'h3F6E_E632, term);
        end else if (!fp32_lt_total(ax, 32'h3F40_0000)) begin
            term    = fp32_mul_rne(32'h3E5A_36E3, fp32_add_rne(ax, 32'hBF40_0000));
            phi_pos = fp32_add_rne(32'h3F45_FCBB, term);
        end else begin
            term    = fp32_mul_rne(32'h3EBA_9FBE, ax);
            phi_pos = fp32_add_rne(32'h3F00_0000, term);
        end
        phi_val = x[31] ? fp32_add_rne(32'h3F80_0000, {1'b1, phi_pos[30:0]}) : phi_pos;
        return fp32_mul_rne(x, phi_val);
    endfunction

    function automatic logic [31:0] fp32_apply_activation(
        input logic [31:0] x,
        input tcu_v2_act_e act,
        input logic [31:0] clamp_min,
        input logic [31:0] clamp_max
    );
        logic [31:0] res;
        case (act)
            TCU_V2_ACT_NONE: begin
                res = tcu_v2_fp32_is_nan(x) ? TCU_V2_CANONICAL_QNAN : x;
            end
            TCU_V2_ACT_RELU: begin
                if (tcu_v2_fp32_is_nan(x)) begin
                    res = TCU_V2_CANONICAL_QNAN;
                end else if (x[31]) begin
                    res = TCU_V2_FP32_POS_ZERO;
                end else begin
                    res = x;
                end
            end
            TCU_V2_ACT_CLAMP: begin
                if (tcu_v2_fp32_is_nan(x) || tcu_v2_fp32_is_nan(clamp_min) || tcu_v2_fp32_is_nan(clamp_max)) begin
                    res = TCU_V2_CANONICAL_QNAN;
                end else if (fp32_lt_total(x, clamp_min)) begin
                    res = clamp_min;
                end else if (fp32_lt_total(clamp_max, x)) begin
                    res = clamp_max;
                end else begin
                    res = x;
                end
            end
            TCU_V2_ACT_SILU: begin
                res = fp32_pwl_silu(x);
            end
            TCU_V2_ACT_GELU: begin
                res = fp32_pwl_gelu(x);
            end
            default: begin
                res = tcu_v2_fp32_is_nan(x) ? TCU_V2_CANONICAL_QNAN : x;
            end
        endcase
        return res;
    endfunction

    // -------------------------------------------------------------------------
    // Stage 1 Input Register -> Stage 2 Activation Compute -> Stage 3 Output
    // -------------------------------------------------------------------------
    logic                                  st1_valid_r;
    tcu_v2_uop_t                           st1_uop_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] st1_tile_r;
    tcu_v2_fp_flags_t                      st1_flags_r;
    logic                                  st1_clamp_inverted_r;
    logic                                  st1_ready;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] tile_act_comb;
    tcu_v2_fp_flags_t                      flags_act_comb;
    logic                                  is_int_acc;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]       elem_clamped_comb;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]       elem_zeroed_comb;

    assign in_ready = !st1_valid_r || st1_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            st1_valid_r          <= 1'b0;
            st1_uop_r            <= '0;
            st1_tile_r           <= '0;
            st1_flags_r          <= '0;
            st1_clamp_inverted_r <= 1'b0;
        end else if (in_valid && in_ready) begin
            st1_valid_r          <= 1'b1;
            st1_uop_r            <= uop_in;
            st1_tile_r           <= tile_in;
            st1_flags_r          <= flags_in;
            st1_clamp_inverted_r <= (uop_in.act == TCU_V2_ACT_CLAMP) &&
                                    fp32_lt_total(uop_in.clamp_max_fp32, uop_in.clamp_min_fp32);
        end else if (st1_valid_r && st1_ready) begin
            st1_valid_r <= 1'b0;
        end
    end

    always_comb begin
        logic signed [31:0] val_s;
        logic signed [31:0] lo_s;
        logic signed [31:0] hi_s;
        is_int_acc     = tcu_v2_fmt_is_int(st1_uop_r.fmt_a) && tcu_v2_fmt_is_int(st1_uop_r.fmt_b);
        flags_act_comb = st1_flags_r;
        val_s          = 32'sd0;
        lo_s           = $signed(st1_uop_r.clamp_min_fp32);
        hi_s           = $signed(st1_uop_r.clamp_max_fp32);

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                elem_clamped_comb[r][c] = 1'b0;
                elem_zeroed_comb[r][c]  = 1'b0;

                if (is_int_acc) begin
                    val_s = $signed(st1_tile_r[r][c]);
                    if (st1_uop_r.act == TCU_V2_ACT_RELU) begin
                        tile_act_comb[r][c]    = (val_s < 0) ? 32'd0 : st1_tile_r[r][c];
                        elem_zeroed_comb[r][c] = (val_s < 0);
                    end else if (st1_uop_r.act == TCU_V2_ACT_CLAMP) begin
                        if (val_s < lo_s) begin
                            tile_act_comb[r][c]     = lo_s;
                            elem_clamped_comb[r][c] = 1'b1;
                        end else if (val_s > hi_s) begin
                            tile_act_comb[r][c]     = hi_s;
                            elem_clamped_comb[r][c] = 1'b1;
                        end else begin
                            tile_act_comb[r][c] = st1_tile_r[r][c];
                        end
                    end else begin
                        tile_act_comb[r][c] = st1_tile_r[r][c];
                    end
                end else if (st1_clamp_inverted_r) begin
                    tile_act_comb[r][c] = TCU_V2_CANONICAL_QNAN;
                    flags_act_comb.nv   = 1'b1;
                end else begin
                    tile_act_comb[r][c] = fp32_apply_activation(
                        st1_tile_r[r][c],
                        st1_uop_r.act,
                        st1_uop_r.clamp_min_fp32,
                        st1_uop_r.clamp_max_fp32
                    );
                    if ((st1_uop_r.act == TCU_V2_ACT_RELU) && st1_tile_r[r][c][31] &&
                        !tcu_v2_fp32_is_nan(st1_tile_r[r][c])) begin
                        elem_zeroed_comb[r][c] = 1'b1;
                    end
                    if ((st1_uop_r.act == TCU_V2_ACT_CLAMP) &&
                        (tile_act_comb[r][c] != st1_tile_r[r][c])) begin
                        elem_clamped_comb[r][c] = 1'b1;
                    end
                    if ((st1_uop_r.act == TCU_V2_ACT_SILU) || (st1_uop_r.act == TCU_V2_ACT_GELU)) begin
                        if (!tcu_v2_fp32_is_nan(st1_tile_r[r][c]) && !tcu_v2_fp32_is_zero(st1_tile_r[r][c])) begin
                            flags_act_comb.nx = 1'b1;
                        end
                    end
                    if (tcu_v2_fp32_is_nan(tile_act_comb[r][c]) && !tcu_v2_fp32_is_nan(st1_tile_r[r][c])) begin
                        flags_act_comb.nv = 1'b1;
                    end
                end
            end
        end
    end

    logic                                  out_valid_r;
    tcu_v2_uop_t                           uop_out_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] tile_out_r;
    tcu_v2_fp_flags_t                      flags_out_r;
    logic [31:0]                           act_tiles_done_r;
    logic [31:0]                           act_relu_tiles_r;
    logic [31:0]                           act_clamp_tiles_r;
    logic [31:0]                           act_silu_tiles_r;
    logic [31:0]                           act_gelu_tiles_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]       last_clamped_mask_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]       last_zeroed_mask_r;

    assign st1_ready = !out_valid_r || out_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            out_valid_r         <= 1'b0;
            uop_out_r           <= '0;
            tile_out_r          <= '0;
            flags_out_r         <= '0;
            act_tiles_done_r    <= 32'd0;
            act_relu_tiles_r    <= 32'd0;
            act_clamp_tiles_r   <= 32'd0;
            act_silu_tiles_r    <= 32'd0;
            act_gelu_tiles_r    <= 32'd0;
            last_clamped_mask_r <= '0;
            last_zeroed_mask_r  <= '0;
        end else if (st1_valid_r && st1_ready) begin
            out_valid_r         <= 1'b1;
            uop_out_r           <= st1_uop_r;
            tile_out_r          <= tile_act_comb;
            flags_out_r         <= flags_act_comb;
            act_tiles_done_r    <= act_tiles_done_r + 32'd1;
            last_clamped_mask_r <= elem_clamped_comb;
            last_zeroed_mask_r  <= elem_zeroed_comb;
            case (st1_uop_r.act)
                TCU_V2_ACT_RELU:  act_relu_tiles_r  <= act_relu_tiles_r  + 32'd1;
                TCU_V2_ACT_CLAMP: act_clamp_tiles_r <= act_clamp_tiles_r + 32'd1;
                TCU_V2_ACT_SILU:  act_silu_tiles_r  <= act_silu_tiles_r  + 32'd1;
                TCU_V2_ACT_GELU:  act_gelu_tiles_r  <= act_gelu_tiles_r  + 32'd1;
                default: ;
            endcase
        end else if (out_valid_r && out_ready) begin
            out_valid_r <= 1'b0;
        end
    end

    `UNUSED_VAR (act_tiles_done_r)
    `UNUSED_VAR (act_relu_tiles_r)
    `UNUSED_VAR (act_clamp_tiles_r)
    `UNUSED_VAR (act_silu_tiles_r)
    `UNUSED_VAR (act_gelu_tiles_r)
    `UNUSED_VAR (last_clamped_mask_r)
    `UNUSED_VAR (last_zeroed_mask_r)

    assign out_valid = out_valid_r;
    assign uop_out   = uop_out_r;
    assign tile_out  = tile_out_r;
    assign flags_out = flags_out_r;

endmodule

`endif // VX_TCU_V2_EPILOGUE_ACT_SV
