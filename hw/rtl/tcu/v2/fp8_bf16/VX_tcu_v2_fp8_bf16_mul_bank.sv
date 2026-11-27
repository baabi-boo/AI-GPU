// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp8_bf16_mul_bank #(
    parameter int   LANES     = 8,
    parameter logic USE_BOOTH = 1'b1,
    parameter logic OUT_REG   = 1'b1
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            enable,
    input  logic                                            valid_in,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e                      fmt_a,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e                      fmt_b,
    input  VX_tcu_v2_pkg::tcu_v2_fp_unpacked_t [LANES-1:0]  a_fp_in,
    input  VX_tcu_v2_pkg::tcu_v2_fp_unpacked_t [LANES-1:0]  b_fp_in,
    input  logic [LANES-1:0][10:0]                          a_exp_s11_in,
    input  logic [LANES-1:0][10:0]                          b_exp_s11_in,
    input  logic [LANES-1:0]                                a_is_snan_in,
    input  logic [LANES-1:0]                                b_is_snan_in,
    output logic                                            valid_out,
    output logic [LANES-1:0][21:0]                          prod_sig22_out,
    output logic [LANES-1:0][10:0]                          prod_exp_s11_out,
    output logic [LANES-1:0]                                prod_sign_out,
    output logic [LANES-1:0]                                prod_zero_out,
    output logic [LANES-1:0]                                prod_inf_out,
    output logic [LANES-1:0]                                prod_nan_out,
    output logic [LANES-1:0]                                prod_snan_out,
    output logic [LANES-1:0]                                prod_nv_zero_inf_out,
    output logic [LANES-1:0]                                prod_norm_carry_out,
    output logic [2:0]                                      precision_mode_out
);
    import VX_tcu_v2_pkg::*;

    localparam logic [2:0] MODE_FP8_MIX = 3'd0;
    localparam logic [2:0] MODE_BF16    = 3'd1;
    localparam logic [2:0] MODE_HI11    = 3'd2;

    // -------------------------------------------------------------------------
    // Format Mode Classification for Active Mantissa Precision
    // -------------------------------------------------------------------------
    logic       a_is_fp8;
    logic       b_is_fp8;
    logic       a_is_bf16;
    logic       b_is_bf16;
    logic       a_is_hi11;
    logic       b_is_hi11;
    logic       both_fp8;
    logic       use_bf16_path;
    logic       use_hi11_path;
    logic [2:0] comb_precision_mode;

    assign a_is_fp8  = tcu_v2_fmt_is_fp8(fmt_a);
    assign b_is_fp8  = tcu_v2_fmt_is_fp8(fmt_b);
    assign a_is_bf16 = (fmt_a == TCU_V2_FMT_BF16);
    assign b_is_bf16 = (fmt_b == TCU_V2_FMT_BF16);
    assign a_is_hi11 = (fmt_a == TCU_V2_FMT_FP16) || (fmt_a == TCU_V2_FMT_TF32);
    assign b_is_hi11 = (fmt_b == TCU_V2_FMT_FP16) || (fmt_b == TCU_V2_FMT_TF32);

    assign both_fp8      = a_is_fp8 && b_is_fp8;
    assign use_bf16_path = !both_fp8 && !a_is_hi11 && !b_is_hi11 && (a_is_bf16 || b_is_bf16);
    assign use_hi11_path = !both_fp8 && !use_bf16_path;

    always_comb begin
        if (both_fp8) begin
            comb_precision_mode = MODE_FP8_MIX;
        end else if (use_bf16_path) begin
            comb_precision_mode = MODE_BF16;
        end else begin
            comb_precision_mode = MODE_HI11;
        end
    end

    // -------------------------------------------------------------------------
    // Helper: 12-bit Radix-4 Modified Booth Partial-Product Multiplier
    // Computes exact unsigned 11x11 product (22 bits) with 6 Booth partials.
    // -------------------------------------------------------------------------
    function automatic logic [21:0] mul11_radix4_booth(
        input logic [10:0] op_a,
        input logic [10:0] op_b
    );
        logic [11:0]          mcand_u12;
        logic [12:0]          mplier_padded;
        logic signed [23:0]   accum_s24;
        logic [2:0]           booth_grp;
        logic signed [12:0]   mcand_s13;
        logic signed [12:0]   pp_mag_s13;
        logic signed [23:0]   pp_shifted_s24;
        begin
            mcand_u12     = {1'b0, op_a};
            mcand_s13     = $signed({1'b0, mcand_u12});
            mplier_padded = {1'b0, op_b, 1'b0};
            accum_s24     = 24'sd0;
            for (int g = 0; g < 6; ++g) begin
                booth_grp = mplier_padded[2*g +: 3];
                case (booth_grp)
                    3'b001,
                    3'b010:  pp_mag_s13 = mcand_s13;
                    3'b011:  pp_mag_s13 = mcand_s13 <<< 1;
                    3'b100:  pp_mag_s13 = -(mcand_s13 <<< 1);
                    3'b101,
                    3'b110:  pp_mag_s13 = -mcand_s13;
                    default: pp_mag_s13 = 13'sd0;
                endcase
                pp_shifted_s24 = $signed({{11{pp_mag_s13[12]}}, pp_mag_s13}) <<< (2 * g);
                accum_s24      = accum_s24 + pp_shifted_s24;
            end
            return accum_s24[21:0];
        end
    endfunction

    // -------------------------------------------------------------------------
    // Helper: 8-bit Radix-4 Modified Booth Partial-Product Multiplier (BF16)
    // Computes exact unsigned 8x8 product (16 bits) with 5 Booth partials.
    // -------------------------------------------------------------------------
    function automatic logic [15:0] mul8_radix4_booth(
        input logic [7:0] op_a,
        input logic [7:0] op_b
    );
        logic [8:0]           mcand_u9;
        logic [10:0]          mplier_padded;
        logic signed [19:0]   accum_s20;
        logic [2:0]           booth_grp;
        logic signed [9:0]    mcand_s10;
        logic signed [9:0]    pp_mag_s10;
        logic signed [19:0]   pp_shifted_s20;
        begin
            mcand_u9      = {1'b0, op_a};
            mcand_s10     = $signed({1'b0, mcand_u9});
            mplier_padded = {2'b00, op_b, 1'b0};
            accum_s20     = 20'sd0;
            for (int g = 0; g < 5; ++g) begin
                booth_grp = mplier_padded[2*g +: 3];
                case (booth_grp)
                    3'b001,
                    3'b010:  pp_mag_s10 = mcand_s10;
                    3'b011:  pp_mag_s10 = mcand_s10 <<< 1;
                    3'b100:  pp_mag_s10 = -(mcand_s10 <<< 1);
                    3'b101,
                    3'b110:  pp_mag_s10 = -mcand_s10;
                    default: pp_mag_s10 = 10'sd0;
                endcase
                pp_shifted_s20 = $signed({{10{pp_mag_s10[9]}}, pp_mag_s10}) <<< (2 * g);
                accum_s20      = accum_s20 + pp_shifted_s20;
            end
            return accum_s20[15:0];
        end
    endfunction

    // -------------------------------------------------------------------------
    // Helper: 4-bit Radix-4 Modified Booth Partial-Product Multiplier (FP8)
    // Computes exact unsigned 4x4 product (8 bits) with 3 Booth partials.
    // -------------------------------------------------------------------------
    function automatic logic [7:0] mul4_radix4_booth(
        input logic [3:0] op_a,
        input logic [3:0] op_b
    );
        logic [4:0]         mcand_u5;
        logic [6:0]         mplier_padded;
        logic signed [11:0] accum_s12;
        logic [2:0]         booth_grp;
        logic signed [5:0]  mcand_s6;
        logic signed [5:0]  pp_mag_s6;
        logic signed [11:0] pp_shifted_s12;
        begin
            mcand_u5      = {1'b0, op_a};
            mcand_s6      = $signed({1'b0, mcand_u5});
            mplier_padded = {2'b00, op_b, 1'b0};
            accum_s12     = 12'sd0;
            for (int g = 0; g < 3; ++g) begin
                booth_grp = mplier_padded[2*g +: 3];
                case (booth_grp)
                    3'b001,
                    3'b010:  pp_mag_s6 = mcand_s6;
                    3'b011:  pp_mag_s6 = mcand_s6 <<< 1;
                    3'b100:  pp_mag_s6 = -(mcand_s6 <<< 1);
                    3'b101,
                    3'b110:  pp_mag_s6 = -mcand_s6;
                    default: pp_mag_s6 = 6'sd0;
                endcase
                pp_shifted_s12 = $signed({{6{pp_mag_s6[5]}}, pp_mag_s6}) <<< (2 * g);
                accum_s12      = accum_s12 + pp_shifted_s12;
            end
            return accum_s12[7:0];
        end
    endfunction

    // -------------------------------------------------------------------------
    // Per-Lane Mantissa Product, Unbiased Exponent Sum, and Exception Classify
    // -------------------------------------------------------------------------
    logic [LANES-1:0][21:0] comb_prod_sig22;
    logic [LANES-1:0][10:0] comb_prod_exp_s11;
    logic [LANES-1:0]       comb_prod_sign;
    logic [LANES-1:0]       comb_prod_zero;
    logic [LANES-1:0]       comb_prod_inf;
    logic [LANES-1:0]       comb_prod_nan;
    logic [LANES-1:0]       comb_prod_snan;
    logic [LANES-1:0]       comb_prod_nv_zero_inf;
    logic [LANES-1:0]       comb_prod_norm_carry;

    for (genvar i = 0; i < LANES; ++i) begin : g_mul_lanes
        logic [10:0]        a_sig11;
        logic [10:0]        b_sig11;
        logic [7:0]         a_sig8;
        logic [7:0]         b_sig8;
        logic [3:0]         a_sig4;
        logic [3:0]         b_sig4;

        logic [21:0]        prod22_hi11;
        logic [15:0]        prod16_bf16;
        logic [7:0]         prod8_fp8;
        logic [21:0]        prod22_selected;
        logic               norm_carry;
        logic [21:0]        prod22_norm;

        logic signed [10:0] a_exp_s;
        logic signed [10:0] b_exp_s;
        logic signed [10:0] exp_sum_raw;
        logic signed [10:0] exp_sum_norm;

        logic               a_is_zero;
        logic               b_is_zero;
        logic               a_is_inf;
        logic               b_is_inf;
        logic               a_is_nan;
        logic               b_is_nan;
        logic               nv_zero_inf;
        logic               out_nan;
        logic               out_snan;
        logic               out_inf;
        logic               out_zero;
        logic               out_sign;

        assign a_sig11 = a_fp_in[i].sig[23:13];
        assign b_sig11 = b_fp_in[i].sig[23:13];
        assign a_sig8  = a_fp_in[i].sig[23:16];
        assign b_sig8  = b_fp_in[i].sig[23:16];
        assign a_sig4  = a_fp_in[i].sig[23:20];
        assign b_sig4  = b_fp_in[i].sig[23:20];

        `UNUSED_VAR (a_fp_in)
        `UNUSED_VAR (b_fp_in)

        if (USE_BOOTH) begin : g_booth_mul
            assign prod22_hi11 = mul11_radix4_booth(a_sig11, b_sig11);
            assign prod16_bf16 = mul8_radix4_booth(a_sig8, b_sig8);
            assign prod8_fp8   = mul4_radix4_booth(a_sig4, b_sig4);
        end else begin : g_direct_mul
            assign prod22_hi11 = {11'd0, a_sig11} * {11'd0, b_sig11};
            assign prod16_bf16 = {8'd0, a_sig8} * {8'd0, b_sig8};
            assign prod8_fp8   = {4'd0, a_sig4} * {4'd0, b_sig4};
        end

        always_comb begin
            if (both_fp8) begin
                prod22_selected = {prod8_fp8, 14'd0};
            end else if (use_bf16_path) begin
                prod22_selected = {prod16_bf16, 6'd0};
            end else begin
                prod22_selected = prod22_hi11;
            end
        end

        assign a_is_zero = a_fp_in[i].is_zero;
        assign b_is_zero = b_fp_in[i].is_zero;
        assign a_is_inf  = a_fp_in[i].is_inf;
        assign b_is_inf  = b_fp_in[i].is_inf;
        assign a_is_nan  = a_fp_in[i].is_nan;
        assign b_is_nan  = b_fp_in[i].is_nan;

        assign nv_zero_inf = (a_is_zero && b_is_inf) || (a_is_inf && b_is_zero);
        assign out_nan     = a_is_nan || b_is_nan || nv_zero_inf;
        assign out_snan    = a_is_snan_in[i] || b_is_snan_in[i];
        assign out_inf     = !out_nan && (a_is_inf || b_is_inf);
        assign out_zero    = !out_nan && !out_inf && (a_is_zero || b_is_zero);
        assign out_sign    = a_fp_in[i].sign ^ b_fp_in[i].sign;

        assign a_exp_s     = $signed(a_exp_s11_in[i]);
        assign b_exp_s     = $signed(b_exp_s11_in[i]);
        assign exp_sum_raw = a_exp_s + b_exp_s;

        // Normalize product [1, 4) -> [1, 2): bit [21] indicates product >= 2.0
        assign norm_carry = prod22_selected[21];
        always_comb begin
            if (out_nan || out_inf || out_zero) begin
                prod22_norm  = 22'd0;
                exp_sum_norm = 11'sd0;
            end else if (norm_carry) begin
                prod22_norm  = prod22_selected;
                exp_sum_norm = exp_sum_raw + 11'sd1;
            end else begin
                prod22_norm  = {prod22_selected[20:0], 1'b0};
                exp_sum_norm = exp_sum_raw;
            end
        end

        assign comb_prod_sig22[i]       = prod22_norm;
        assign comb_prod_exp_s11[i]     = exp_sum_norm;
        assign comb_prod_sign[i]        = out_sign;
        assign comb_prod_zero[i]        = out_zero;
        assign comb_prod_inf[i]         = out_inf;
        assign comb_prod_nan[i]         = out_nan;
        assign comb_prod_snan[i]        = out_snan;
        assign comb_prod_nv_zero_inf[i] = nv_zero_inf;
        assign comb_prod_norm_carry[i]  = !out_nan && !out_inf && !out_zero && norm_carry;
    end

    logic [3:0] comb_prod_nan_cnt;
    logic [3:0] comb_prod_inf_cnt;
    logic [3:0] comb_prod_zero_cnt;
    logic [3:0] comb_norm_carry_cnt;

    always_comb begin
        comb_prod_nan_cnt   = 4'd0;
        comb_prod_inf_cnt   = 4'd0;
        comb_prod_zero_cnt  = 4'd0;
        comb_norm_carry_cnt = 4'd0;
        for (int p = 0; p < LANES; ++p) begin
            comb_prod_nan_cnt   = comb_prod_nan_cnt   + {3'd0, comb_prod_nan[p]};
            comb_prod_inf_cnt   = comb_prod_inf_cnt   + {3'd0, comb_prod_inf[p]};
            comb_prod_zero_cnt  = comb_prod_zero_cnt  + {3'd0, comb_prod_zero[p]};
            comb_norm_carry_cnt = comb_norm_carry_cnt + {3'd0, comb_prod_norm_carry[p]};
        end
    end

    `UNUSED_VAR (use_hi11_path)
    `UNUSED_VAR (comb_prod_nan_cnt)
    `UNUSED_VAR (comb_prod_inf_cnt)
    `UNUSED_VAR (comb_prod_zero_cnt)
    `UNUSED_VAR (comb_norm_carry_cnt)

    // -------------------------------------------------------------------------
    // Optional Pipeline Register Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic                   valid_r;
        logic [LANES-1:0][21:0] prod_sig22_r;
        logic [LANES-1:0][10:0] prod_exp_s11_r;
        logic [LANES-1:0]       prod_sign_r;
        logic [LANES-1:0]       prod_zero_r;
        logic [LANES-1:0]       prod_inf_r;
        logic [LANES-1:0]       prod_nan_r;
        logic [LANES-1:0]       prod_snan_r;
        logic [LANES-1:0]       prod_nv_zero_inf_r;
        logic [LANES-1:0]       prod_norm_carry_r;
        logic [2:0]             precision_mode_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r            <= 1'b0;
                prod_sig22_r       <= '0;
                prod_exp_s11_r     <= '0;
                prod_sign_r        <= '0;
                prod_zero_r        <= '0;
                prod_inf_r         <= '0;
                prod_nan_r         <= '0;
                prod_snan_r        <= '0;
                prod_nv_zero_inf_r <= '0;
                prod_norm_carry_r  <= '0;
                precision_mode_r   <= MODE_HI11;
            end else if (enable) begin
                valid_r            <= valid_in;
                prod_sig22_r       <= comb_prod_sig22;
                prod_exp_s11_r     <= comb_prod_exp_s11;
                prod_sign_r        <= comb_prod_sign;
                prod_zero_r        <= comb_prod_zero;
                prod_inf_r         <= comb_prod_inf;
                prod_nan_r         <= comb_prod_nan;
                prod_snan_r        <= comb_prod_snan;
                prod_nv_zero_inf_r <= comb_prod_nv_zero_inf;
                prod_norm_carry_r  <= comb_prod_norm_carry;
                precision_mode_r   <= comb_precision_mode;
            end
        end

        assign valid_out            = valid_r;
        assign prod_sig22_out       = prod_sig22_r;
        assign prod_exp_s11_out     = prod_exp_s11_r;
        assign prod_sign_out        = prod_sign_r;
        assign prod_zero_out        = prod_zero_r;
        assign prod_inf_out         = prod_inf_r;
        assign prod_nan_out         = prod_nan_r;
        assign prod_snan_out        = prod_snan_r;
        assign prod_nv_zero_inf_out = prod_nv_zero_inf_r;
        assign prod_norm_carry_out  = prod_norm_carry_r;
        assign precision_mode_out   = precision_mode_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out            = valid_in;
        assign prod_sig22_out       = comb_prod_sig22;
        assign prod_exp_s11_out     = comb_prod_exp_s11;
        assign prod_sign_out        = comb_prod_sign;
        assign prod_zero_out        = comb_prod_zero;
        assign prod_inf_out         = comb_prod_inf;
        assign prod_nan_out         = comb_prod_nan;
        assign prod_snan_out        = comb_prod_snan;
        assign prod_nv_zero_inf_out = comb_prod_nv_zero_inf;
        assign prod_norm_carry_out  = comb_prod_norm_carry;
        assign precision_mode_out   = comb_precision_mode;
    end

endmodule
