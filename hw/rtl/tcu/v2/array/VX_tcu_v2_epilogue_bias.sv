// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_EPILOGUE_BIAS_SV
`define VX_TCU_V2_EPILOGUE_BIAS_SV

`include "VX_platform.vh"

module VX_tcu_v2_epilogue_bias #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    in_valid,
    output logic                                    in_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t              uop_in,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   tile_in,
    input  logic [ARRAY_N-1:0][31:0]                bias_in,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_in,
    output logic                                    out_valid,
    input  logic                                    out_ready,
    output VX_tcu_v2_pkg::tcu_v2_uop_t              uop_out,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   tile_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_out
);

    import VX_tcu_v2_pkg::*;

    // -------------------------------------------------------------------------
    // Exact IEEE-754 FP32 Addition Helper (All 5 Rounding Modes & Exceptions)
    // -------------------------------------------------------------------------
    function automatic logic [36:0] fp32_add_exact(
        input logic [31:0]   a,
        input logic [31:0]   b,
        input tcu_v2_rm_e    rm
    );
        logic        sa, sb;
        logic [7:0]  ea, eb;
        logic [22:0] ma, mb;
        logic        a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        logic        res_sign;
        logic [31:0] res_bits;
        tcu_v2_fp_flags_t flg;

        logic [23:0] sig_a, sig_b;
        logic signed [9:0] exp_a, exp_b;
        logic        swap_ab;
        logic        s_hi, s_lo;
        logic signed [9:0] exp_hi, exp_lo;
        logic [23:0] sig_hi, sig_lo;
        logic [27:0] ext_hi, ext_lo;
        logic [9:0]  shift_amt;
        logic        sticky;
        logic [28:0] sum_mag;
        logic        eff_sub;
        logic [4:0]  lzc_cnt;
        logic [26:0] norm_sig;
        logic signed [9:0] norm_exp;
        logic        guard, round_bit, stick_bit;
        logic        round_up;
        logic [24:0] rounded_mant;
        logic signed [9:0] final_exp;
        logic [22:0] final_man;
        logic        inexact;
        logic        overflow;
        logic        underflow;
        logic        sub_shift_done;

        flg = '0;
        sa  = a[31];
        sb  = b[31];
        ea  = a[30:23];
        eb  = b[30:23];
        ma  = a[22:0];
        mb  = b[22:0];

        a_nan  = (ea == 8'hFF) && (ma != 23'd0);
        b_nan  = (eb == 8'hFF) && (mb != 23'd0);
        a_inf  = (ea == 8'hFF) && (ma == 23'd0);
        b_inf  = (eb == 8'hFF) && (mb == 23'd0);
        a_zero = (ea == 8'd0)  && (ma == 23'd0);
        b_zero = (eb == 8'd0)  && (mb == 23'd0);

        if (a_nan || b_nan) begin
            flg.nv   = (a_nan && !ma[22]) || (b_nan && !mb[22]);
            res_bits = TCU_V2_CANONICAL_QNAN;
            return {flg, res_bits};
        end

        if (a_inf && b_inf) begin
            if (sa != sb) begin
                flg.nv   = 1'b1;
                res_bits = TCU_V2_CANONICAL_QNAN;
            end else begin
                res_bits = sa ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            end
            return {flg, res_bits};
        end

        if (a_inf) begin
            res_bits = sa ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            return {flg, res_bits};
        end

        if (b_inf) begin
            res_bits = sb ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            return {flg, res_bits};
        end

        if (a_zero && b_zero) begin
            if (sa == sb) begin
                res_sign = sa;
            end else begin
                res_sign = (rm == TCU_V2_RM_RDN);
            end
            res_bits = res_sign ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
            return {flg, res_bits};
        end

        if (a_zero) begin
            return {flg, b};
        end
        if (b_zero) begin
            return {flg, a};
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
            for (int bit_i = 0; bit_i < 28; ++bit_i) begin
                if (bit_i < int'(shift_amt)) begin
                    sticky = sticky || ext_lo[bit_i];
                end
            end
            ext_lo = ext_lo >> shift_amt;
        end
        ext_lo[0] = ext_lo[0] | sticky;

        if (eff_sub) begin
            sum_mag = {1'b0, ext_hi} - {1'b0, ext_lo};
        end else begin
            sum_mag = {1'b0, ext_hi} + {1'b0, ext_lo};
        end

        if (sum_mag == 29'd0) begin
            res_sign = (rm == TCU_V2_RM_RDN);
            res_bits = res_sign ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
            return {flg, res_bits};
        end

        res_sign = s_hi;
        if (sum_mag[27]) begin
            sticky      = sum_mag[0];
            norm_sig    = sum_mag[27:1];
            norm_sig[0] = norm_sig[0] | sticky;
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
                if (exp_hi > $signed(10'd1)) begin
                    sub_shift_done = 1'b1;
                    norm_sig       = sum_mag[26:0] << (exp_hi - $signed(10'd1));
                    norm_exp       = $signed(10'd1);
                end else begin
                    sub_shift_done = 1'b0;
                    norm_sig       = sum_mag[26:0];
                    norm_exp       = $signed(10'd1);
                end
                if (!sub_shift_done && norm_sig[26]) begin
                    norm_exp = $signed(10'd1);
                end
            end
        end

        guard     = norm_sig[2];
        round_bit = norm_sig[1];
        stick_bit = norm_sig[0];
        inexact   = guard || round_bit || stick_bit;

        round_up = 1'b0;
        case (rm)
            TCU_V2_RM_RNE: round_up = guard && (round_bit || stick_bit || norm_sig[3]);
            TCU_V2_RM_RTZ: round_up = 1'b0;
            TCU_V2_RM_RDN: round_up = res_sign && inexact;
            TCU_V2_RM_RUP: round_up = !res_sign && inexact;
            TCU_V2_RM_RMM: round_up = guard;
            default:       round_up = 1'b0;
        endcase

        rounded_mant = {1'b0, norm_sig[26:3]} + {24'd0, round_up};
        final_exp    = norm_exp;
        if (rounded_mant[24]) begin
            final_man = rounded_mant[23:1];
            final_exp = norm_exp + $signed(10'd1);
        end else begin
            final_man = rounded_mant[22:0];
        end

        overflow  = (final_exp >= $signed(10'd255));
        underflow = (final_exp == $signed(10'd1)) && !rounded_mant[23] && inexact;

        flg.nx = inexact || overflow;
        flg.of = overflow;
        flg.uf = underflow;

        if (overflow) begin
            case (rm)
                TCU_V2_RM_RTZ: res_bits = {res_sign, 8'hFE, 23'h7FFFFF};
                TCU_V2_RM_RDN: res_bits = res_sign ? TCU_V2_FP32_NEG_INF : {1'b0, 8'hFE, 23'h7FFFFF};
                TCU_V2_RM_RUP: res_bits = res_sign ? {1'b1, 8'hFE, 23'h7FFFFF} : TCU_V2_FP32_POS_INF;
                default:       res_bits = res_sign ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            endcase
        end else if ((final_exp == $signed(10'd1)) && !rounded_mant[23]) begin
            res_bits = {res_sign, 8'd0, final_man};
        end else begin
            res_bits = {res_sign, final_exp[7:0], final_man};
        end

        return {flg, res_bits};
    endfunction

    // -------------------------------------------------------------------------
    // Exact INT32 Addition Helper with Signed Wrap or Saturation
    // -------------------------------------------------------------------------
    function automatic logic [36:0] int32_add_exact(
        input logic [31:0] a,
        input logic [31:0] b,
        input logic        saturate
    );
        logic [31:0]      sum_32;
        logic [31:0]      res_bits;
        tcu_v2_fp_flags_t flg;
        logic             ovf_pos;
        logic             ovf_neg;

        flg     = '0;
        sum_32  = 32'($signed(a) + $signed(b));
        ovf_pos = (!a[31] && !b[31] && sum_32[31]);
        ovf_neg = (a[31] && b[31] && !sum_32[31]);

        if (saturate && ovf_pos) begin
            res_bits = TCU_V2_INT32_MAX;
            flg.of   = 1'b1;
            flg.nx   = 1'b1;
        end else if (saturate && ovf_neg) begin
            res_bits = TCU_V2_INT32_MIN;
            flg.of   = 1'b1;
            flg.nx   = 1'b1;
        end else begin
            res_bits = sum_32;
            flg.of   = ovf_pos || ovf_neg;
        end
        return {flg, res_bits};
    endfunction

    // -------------------------------------------------------------------------
    // Stage 1 Input Latch -> Stage 2 Combinational Bias Add -> Stage 3 Output
    // -------------------------------------------------------------------------
    logic                                  st1_valid_r;
    tcu_v2_uop_t                           st1_uop_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] st1_tile_r;
    logic [ARRAY_N-1:0][31:0]              st1_bias_r;
    tcu_v2_fp_flags_t                      st1_flags_r;
    logic [ARRAY_N-1:0]                    st1_bias_zero_r;
    logic [ARRAY_N-1:0]                    st1_bias_nan_r;
    logic [ARRAY_N-1:0]                    st1_bias_inf_r;
    logic                                  st1_ready;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] tile_comb;
    tcu_v2_fp_flags_t                      flags_comb;
    logic                                  is_int_acc;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]       elem_ovf_comb;

    assign in_ready = !st1_valid_r || st1_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            st1_valid_r     <= 1'b0;
            st1_uop_r       <= '0;
            st1_tile_r      <= '0;
            st1_bias_r      <= '0;
            st1_flags_r     <= '0;
            st1_bias_zero_r <= '0;
            st1_bias_nan_r  <= '0;
            st1_bias_inf_r  <= '0;
        end else if (in_valid && in_ready) begin
            st1_valid_r <= 1'b1;
            st1_uop_r   <= uop_in;
            st1_tile_r  <= tile_in;
            st1_bias_r  <= bias_in;
            st1_flags_r <= flags_in;
            for (int c = 0; c < ARRAY_N; ++c) begin
                st1_bias_zero_r[c] <= (bias_in[c][30:0] == 31'd0);
                st1_bias_nan_r[c]  <= tcu_v2_fp32_is_nan(bias_in[c]);
                st1_bias_inf_r[c]  <= tcu_v2_fp32_is_inf(bias_in[c]);
            end
        end else if (st1_valid_r && st1_ready) begin
            st1_valid_r <= 1'b0;
        end
    end

    always_comb begin
        logic [36:0]      elem_res;
        tcu_v2_fp_flags_t elem_flg;
        is_int_acc = tcu_v2_fmt_is_int(st1_uop_r.fmt_a) && tcu_v2_fmt_is_int(st1_uop_r.fmt_b);
        flags_comb = st1_flags_r;
        elem_res   = '0;
        elem_flg   = '0;

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                elem_ovf_comb[r][c] = 1'b0;
                if (!st1_uop_r.bias_en) begin
                    tile_comb[r][c] = st1_tile_r[r][c];
                end else if (!is_int_acc && st1_bias_nan_r[c]) begin
                    tile_comb[r][c] = TCU_V2_CANONICAL_QNAN;
                    flags_comb.nv   = flags_comb.nv || !st1_bias_r[c][22];
                end else if (is_int_acc) begin
                    if (st1_bias_r[c] == 32'd0) begin
                        tile_comb[r][c] = st1_tile_r[r][c];
                    end else begin
                        elem_res            = int32_add_exact(st1_tile_r[r][c], st1_bias_r[c], st1_uop_r.int_saturate);
                        elem_flg            = tcu_v2_fp_flags_t'(elem_res[36:32]);
                        tile_comb[r][c]     = elem_res[31:0];
                        flags_comb          = tcu_v2_flags_or(flags_comb, elem_flg);
                        elem_ovf_comb[r][c] = elem_flg.of;
                    end
                end else if (st1_bias_zero_r[c] && !tcu_v2_fp32_is_zero(st1_tile_r[r][c]) &&
                             !tcu_v2_fp32_is_nan(st1_tile_r[r][c])) begin
                    tile_comb[r][c] = st1_tile_r[r][c];
                end else begin
                    elem_res            = fp32_add_exact(st1_tile_r[r][c], st1_bias_r[c], st1_uop_r.rm);
                    elem_flg            = tcu_v2_fp_flags_t'(elem_res[36:32]);
                    tile_comb[r][c]     = elem_res[31:0];
                    flags_comb          = tcu_v2_flags_or(flags_comb, elem_flg);
                    elem_ovf_comb[r][c] = elem_flg.of;
                end
            end
        end
    end

    logic                                  out_valid_r;
    tcu_v2_uop_t                           uop_out_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] tile_out_r;
    tcu_v2_fp_flags_t                      flags_out_r;
    logic [31:0]                           bias_tiles_done_r;
    logic [31:0]                           bias_applied_tiles_r;
    logic [31:0]                           bias_zero_skips_r;
    logic [31:0]                           bias_ovf_events_r;
    logic [31:0]                           bias_inf_events_r;
    logic [31:0]                           bias_sat_events_r;
    logic [31:0]                           bias_fp32_events_r;
    logic [31:0]                           bias_int_events_r;
    logic [31:0]                           bias_stall_cycles_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]       last_ovf_mask_r;

    assign st1_ready = !out_valid_r || out_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            out_valid_r          <= 1'b0;
            uop_out_r            <= '0;
            tile_out_r           <= '0;
            flags_out_r          <= '0;
            bias_tiles_done_r    <= 32'd0;
            bias_applied_tiles_r <= 32'd0;
            bias_zero_skips_r    <= 32'd0;
            bias_ovf_events_r    <= 32'd0;
            bias_inf_events_r    <= 32'd0;
            bias_sat_events_r    <= 32'd0;
            bias_fp32_events_r   <= 32'd0;
            bias_int_events_r    <= 32'd0;
            bias_stall_cycles_r  <= 32'd0;
            last_ovf_mask_r      <= '0;
        end else begin
            if (out_valid_r && !out_ready) begin
                bias_stall_cycles_r <= bias_stall_cycles_r + 32'd1;
            end
            if (st1_valid_r && st1_ready) begin
                out_valid_r       <= 1'b1;
                uop_out_r         <= st1_uop_r;
                tile_out_r        <= tile_comb;
                flags_out_r       <= flags_comb;
                last_ovf_mask_r   <= elem_ovf_comb;
                bias_tiles_done_r <= bias_tiles_done_r + 32'd1;
                if (st1_uop_r.bias_en) begin
                    bias_applied_tiles_r <= bias_applied_tiles_r + 32'd1;
                    if (is_int_acc) begin
                        bias_int_events_r <= bias_int_events_r + 32'd1;
                        if (st1_uop_r.int_saturate && (|elem_ovf_comb)) begin
                            bias_sat_events_r <= bias_sat_events_r + 32'd1;
                        end
                    end else begin
                        bias_fp32_events_r <= bias_fp32_events_r + 32'd1;
                    end
                    if (&st1_bias_zero_r) begin
                        bias_zero_skips_r <= bias_zero_skips_r + 32'd1;
                    end
                    if (|elem_ovf_comb) begin
                        bias_ovf_events_r <= bias_ovf_events_r + 32'd1;
                    end
                    if (!is_int_acc && (|st1_bias_inf_r)) begin
                        bias_inf_events_r <= bias_inf_events_r + 32'd1;
                    end
                end
            end else if (out_valid_r && out_ready) begin
                out_valid_r <= 1'b0;
            end
        end
    end

    `UNUSED_VAR (bias_tiles_done_r)
    `UNUSED_VAR (bias_applied_tiles_r)
    `UNUSED_VAR (bias_zero_skips_r)
    `UNUSED_VAR (bias_ovf_events_r)
    `UNUSED_VAR (bias_inf_events_r)
    `UNUSED_VAR (bias_sat_events_r)
    `UNUSED_VAR (bias_fp32_events_r)
    `UNUSED_VAR (bias_int_events_r)
    `UNUSED_VAR (bias_stall_cycles_r)
    `UNUSED_VAR (last_ovf_mask_r)

    assign out_valid = out_valid_r;
    assign uop_out   = uop_out_r;
    assign tile_out  = tile_out_r;
    assign flags_out = flags_out_r;

endmodule

`endif // VX_TCU_V2_EPILOGUE_BIAS_SV
