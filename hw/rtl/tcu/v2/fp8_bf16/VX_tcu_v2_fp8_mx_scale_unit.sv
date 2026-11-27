// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp8_mx_scale_unit #(
    parameter int   LANES   = 8,
    parameter logic OUT_REG = 1'b0
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    enable,
    input  logic                                    valid_in,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e              fmt_a,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e              fmt_b,
    input  VX_tcu_v2_pkg::tcu_v2_scale_fmt_e        scale_fmt,
    input  logic [7:0]                              scale_a_raw,
    input  logic [7:0]                              scale_b_raw,
    input  logic [LANES-1:0][21:0]                  prod_sig22_in,
    input  logic [LANES-1:0][10:0]                  prod_exp_s11_in,
    input  logic [LANES-1:0]                        prod_zero_in,
    input  logic [LANES-1:0]                        prod_inf_in,
    input  logic [LANES-1:0]                        prod_nan_in,
    input  logic [LANES-1:0]                        prod_sign_in,
    output logic                                    valid_out,
    output VX_tcu_v2_pkg::tcu_v2_scale_decoded_t    scale_a_dec_out,
    output VX_tcu_v2_pkg::tcu_v2_scale_decoded_t    scale_b_dec_out,
    output logic signed [10:0]                      combined_exp_delta_out,
    output logic [7:0]                              scale_mant_prod_out,
    output logic                                    scale_mant_active_out,
    output logic                                    scale_any_nan_out,
    output logic                                    scale_any_zero_out,
    output logic                                    scale_inf_mul_zero_nv_out,
    output logic                                    scale_a_is_unity_out,
    output logic                                    scale_b_is_unity_out,
    output logic                                    scale_exp_clamp_of_out,
    output logic                                    scale_exp_clamp_uf_out,
    output logic [LANES-1:0][21:0]                  scaled_sig22_out,
    output logic [LANES-1:0][10:0]                  scaled_exp_s11_out,
    output logic [LANES-1:0]                        scaled_zero_out,
    output logic [LANES-1:0]                        scaled_inf_out,
    output logic [LANES-1:0]                        scaled_nan_out,
    output logic [LANES-1:0]                        scaled_sign_out
);
    import VX_tcu_v2_pkg::*;

    // -------------------------------------------------------------------------
    // Scale Format Resolution & Per-Operand Scale Decode
    // -------------------------------------------------------------------------
    logic              a_is_mx;
    logic              b_is_mx;
    logic              scale_enabled;
    tcu_v2_scale_fmt_e eff_scale_fmt_a;
    tcu_v2_scale_fmt_e eff_scale_fmt_b;

    assign a_is_mx = (fmt_a == TCU_V2_FMT_MXFP8_E4M3) || (fmt_a == TCU_V2_FMT_MXFP8_E5M2);
    assign b_is_mx = (fmt_b == TCU_V2_FMT_MXFP8_E4M3) || (fmt_b == TCU_V2_FMT_MXFP8_E5M2);
    assign scale_enabled = (scale_fmt != TCU_V2_SCALE_NONE) && (a_is_mx || b_is_mx);

    always_comb begin
        if (scale_fmt == TCU_V2_SCALE_NONE) begin
            eff_scale_fmt_a = TCU_V2_SCALE_NONE;
            eff_scale_fmt_b = TCU_V2_SCALE_NONE;
        end else begin
            eff_scale_fmt_a = a_is_mx ? scale_fmt : TCU_V2_SCALE_NONE;
            eff_scale_fmt_b = b_is_mx ? scale_fmt : TCU_V2_SCALE_NONE;
        end
    end

    tcu_v2_scale_decoded_t comb_scale_a_dec;
    tcu_v2_scale_decoded_t comb_scale_b_dec;

    always_comb begin
        comb_scale_a_dec = tcu_v2_decode_scale(eff_scale_fmt_a, scale_a_raw);
        comb_scale_b_dec = tcu_v2_decode_scale(eff_scale_fmt_b, scale_b_raw);
    end

    // -------------------------------------------------------------------------
    // Subnormal E4M3 Scale Normalization (for scale_fmt == TCU_V2_SCALE_E4M3)
    // -------------------------------------------------------------------------
    function automatic void normalize_u1p3(
        input  logic [3:0]        mant_in,
        output logic [3:0]        mant_norm,
        output logic signed [2:0] exp_shift
    );
        begin
            if (mant_in[3]) begin
                mant_norm = mant_in;
                exp_shift = 3'sd0;
            end else if (mant_in[2]) begin
                mant_norm = {mant_in[2:0], 1'b0};
                exp_shift = -3'sd1;
            end else if (mant_in[1]) begin
                mant_norm = {mant_in[1:0], 2'b00};
                exp_shift = -3'sd2;
            end else if (mant_in[0]) begin
                mant_norm = {mant_in[0], 3'b000};
                exp_shift = -3'sd3;
            end else begin
                mant_norm = 4'd0;
                exp_shift = 3'sd0;
            end
        end
    endfunction

    logic [3:0]        sa_mant_norm;
    logic [3:0]        sb_mant_norm;
    logic signed [2:0] sa_sub_shift;
    logic signed [2:0] sb_sub_shift;

    always_comb begin
        normalize_u1p3(comb_scale_a_dec.mant_u1p3, sa_mant_norm, sa_sub_shift);
        normalize_u1p3(comb_scale_b_dec.mant_u1p3, sb_mant_norm, sb_sub_shift);
    end

    // -------------------------------------------------------------------------
    // Scale Exponent Addition, Mantissa Product Normalization, and Unity Checks
    // -------------------------------------------------------------------------
    logic signed [10:0] scale_a_exp_s11;
    logic signed [10:0] scale_b_exp_s11;
    logic signed [10:0] comb_exp_delta;
    logic [7:0]         raw_mant_mul;
    logic               scale_mant_carry;
    logic [7:0]         norm_scale_mant_u2p6;
    logic signed [10:0] scale_mant_exp_adj;
    logic [7:0]         comb_scale_mant_prod;
    logic               comb_scale_mant_active;
    logic               comb_scale_any_nan;
    logic               comb_scale_any_zero;
    logic               comb_scale_inf_mul_zero_nv;
    logic               comb_scale_a_is_unity;
    logic               comb_scale_b_is_unity;
    logic               comb_exp_clamp_of;
    logic               comb_exp_clamp_uf;

    assign scale_a_exp_s11 = $signed({comb_scale_a_dec.exp_delta[TCU_V2_FP_EXP_W-1], comb_scale_a_dec.exp_delta}) +
                             $signed({{8{sa_sub_shift[2]}}, sa_sub_shift});
    assign scale_b_exp_s11 = $signed({comb_scale_b_dec.exp_delta[TCU_V2_FP_EXP_W-1], comb_scale_b_dec.exp_delta}) +
                             $signed({{8{sb_sub_shift[2]}}, sb_sub_shift});

    assign raw_mant_mul     = {4'd0, sa_mant_norm} * {4'd0, sb_mant_norm};
    assign scale_mant_carry = raw_mant_mul[7];

    always_comb begin
        if (scale_mant_carry) begin
            norm_scale_mant_u2p6 = raw_mant_mul;
            scale_mant_exp_adj   = 11'sd1;
        end else begin
            norm_scale_mant_u2p6 = {raw_mant_mul[6:0], 1'b0};
            scale_mant_exp_adj   = 11'sd0;
        end
    end

    assign comb_scale_mant_active = scale_enabled && (scale_fmt == TCU_V2_SCALE_E4M3) &&
                                    !comb_scale_a_dec.is_nan && !comb_scale_b_dec.is_nan &&
                                    !comb_scale_a_dec.is_zero && !comb_scale_b_dec.is_zero;
    assign comb_scale_mant_prod   = comb_scale_mant_active ? norm_scale_mant_u2p6 : 8'b1000_0000;
    assign comb_exp_delta         = scale_enabled ?
                                    (scale_a_exp_s11 + scale_b_exp_s11 + (comb_scale_mant_active ? scale_mant_exp_adj : 11'sd0)) :
                                    11'sd0;

    assign comb_scale_any_nan     = scale_enabled && (comb_scale_a_dec.is_nan || comb_scale_b_dec.is_nan);
    assign comb_scale_any_zero    = scale_enabled && (comb_scale_a_dec.is_zero || comb_scale_b_dec.is_zero);

    assign comb_scale_a_is_unity  = !comb_scale_a_dec.is_nan && !comb_scale_a_dec.is_zero &&
                                    (scale_a_exp_s11 == 11'sd0) && (sa_mant_norm == 4'b1000);
    assign comb_scale_b_is_unity  = !comb_scale_b_dec.is_nan && !comb_scale_b_dec.is_zero &&
                                    (scale_b_exp_s11 == 11'sd0) && (sb_mant_norm == 4'b1000);

    logic scale_a_is_subnorm;
    logic scale_b_is_subnorm;
    logic scale_exp_is_zero;
    logic scale_exp_in_fp32_range;

    assign scale_a_is_subnorm      = (eff_scale_fmt_a == TCU_V2_SCALE_E4M3) && (sa_sub_shift != 3'sd0);
    assign scale_b_is_subnorm      = (eff_scale_fmt_b == TCU_V2_SCALE_E4M3) && (sb_sub_shift != 3'sd0);
    assign scale_exp_is_zero       = (comb_exp_delta == 11'sd0);
    assign scale_exp_in_fp32_range = (comb_exp_delta >= -11'sd126) && (comb_exp_delta <= 11'sd127);

    `UNUSED_VAR (scale_a_is_subnorm)
    `UNUSED_VAR (scale_b_is_subnorm)
    `UNUSED_VAR (scale_exp_is_zero)
    `UNUSED_VAR (scale_exp_in_fp32_range)

    // -------------------------------------------------------------------------
    // Per-Lane Scale Application (Exponent + Optional E4M3 Mantissa) & Guards
    // -------------------------------------------------------------------------
    logic [LANES-1:0][21:0] comb_scaled_sig22;
    logic [LANES-1:0][10:0] comb_scaled_exp_s11;
    logic [LANES-1:0]       comb_scaled_zero;
    logic [LANES-1:0]       comb_scaled_inf;
    logic [LANES-1:0]       comb_scaled_nan;
    logic [LANES-1:0]       comb_scaled_sign;
    logic [LANES-1:0]       lane_inf_mul_zero_nv;
    logic [LANES-1:0]       lane_exp_of;
    logic [LANES-1:0]       lane_exp_uf;

    for (genvar i = 0; i < LANES; ++i) begin : g_scale_lanes
        logic [21:0]        lane_sig_in;
        logic signed [10:0] lane_exp_in;
        logic               lane_is_zero;
        logic               lane_is_inf;
        logic               lane_is_nan;
        logic               lane_inf_zero_nv;
        logic [29:0]        sig_scaled_full;
        logic               sig_scaled_carry;
        logic [21:0]        sig_scaled_norm;
        logic signed [10:0] exp_mant_carry;
        logic               lane_out_nan;
        logic               lane_out_inf;
        logic               lane_out_zero;
        logic signed [10:0] lane_exp_adj;
        logic [21:0]        lane_sig_out;

        assign lane_sig_in      = prod_sig22_in[i];
        assign lane_exp_in      = $signed(prod_exp_s11_in[i]);
        assign lane_is_zero     = prod_zero_in[i];
        assign lane_is_inf      = prod_inf_in[i];
        assign lane_is_nan      = prod_nan_in[i];
        assign lane_inf_zero_nv = lane_is_inf && comb_scale_any_zero;

        // 22-bit U1.21 * 8-bit U1.7 -> 30-bit U2.28 (bit [29] is >= 2.0 carry)
        assign sig_scaled_full  = {8'd0, lane_sig_in} * {22'd0, comb_scale_mant_prod};
        assign sig_scaled_carry = sig_scaled_full[29];
        assign sig_scaled_norm  = sig_scaled_carry ? sig_scaled_full[29:8] : sig_scaled_full[28:7];
        assign exp_mant_carry   = (comb_scale_mant_active && sig_scaled_carry) ? 11'sd1 : 11'sd0;

        always_comb begin
            lane_out_nan  = 1'b0;
            lane_out_inf  = 1'b0;
            lane_out_zero = 1'b0;
            lane_exp_adj  = lane_exp_in;
            lane_sig_out  = lane_sig_in;

            if (lane_is_nan || comb_scale_any_nan || lane_inf_zero_nv) begin
                lane_out_nan = 1'b1;
                lane_exp_adj = 11'sd0;
                lane_sig_out = 22'd0;
            end else if (lane_is_inf) begin
                lane_out_inf = 1'b1;
                lane_exp_adj = 11'sd0;
                lane_sig_out = 22'd0;
            end else if (lane_is_zero || comb_scale_any_zero) begin
                lane_out_zero = 1'b1;
                lane_exp_adj  = 11'sd0;
                lane_sig_out  = 22'd0;
            end else begin
                lane_exp_adj = lane_exp_in + comb_exp_delta + exp_mant_carry;
                lane_sig_out = comb_scale_mant_active ? sig_scaled_norm : lane_sig_in;
            end
        end

        assign lane_inf_mul_zero_nv[i] = lane_inf_zero_nv;
        assign lane_exp_of[i]          = !lane_out_nan && !lane_out_inf && !lane_out_zero && (lane_exp_adj > 11'sd127);
        assign lane_exp_uf[i]          = !lane_out_nan && !lane_out_inf && !lane_out_zero && (lane_exp_adj < -11'sd149);

        assign comb_scaled_sig22[i]    = lane_sig_out;
        assign comb_scaled_exp_s11[i]  = lane_exp_adj;
        assign comb_scaled_zero[i]     = lane_out_zero;
        assign comb_scaled_inf[i]      = lane_out_inf;
        assign comb_scaled_nan[i]      = lane_out_nan;
        assign comb_scaled_sign[i]     = prod_sign_in[i];

        `UNUSED_VAR (sig_scaled_full)
    end

    assign comb_scale_inf_mul_zero_nv = |lane_inf_mul_zero_nv;
    assign comb_exp_clamp_of          = |lane_exp_of;
    assign comb_exp_clamp_uf          = |lane_exp_uf;

    // -------------------------------------------------------------------------
    // Optional Pipeline Register
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic                        valid_r;
        tcu_v2_scale_decoded_t       scale_a_dec_r;
        tcu_v2_scale_decoded_t       scale_b_dec_r;
        logic signed [10:0]          combined_exp_delta_r;
        logic [7:0]                  scale_mant_prod_r;
        logic                        scale_mant_active_r;
        logic                        scale_any_nan_r;
        logic                        scale_any_zero_r;
        logic                        scale_inf_mul_zero_nv_r;
        logic                        scale_a_is_unity_r;
        logic                        scale_b_is_unity_r;
        logic                        scale_exp_clamp_of_r;
        logic                        scale_exp_clamp_uf_r;
        logic [LANES-1:0][21:0]      scaled_sig22_r;
        logic [LANES-1:0][10:0]      scaled_exp_s11_r;
        logic [LANES-1:0]            scaled_zero_r;
        logic [LANES-1:0]            scaled_inf_r;
        logic [LANES-1:0]            scaled_nan_r;
        logic [LANES-1:0]            scaled_sign_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r                 <= 1'b0;
                scale_a_dec_r           <= '0;
                scale_b_dec_r           <= '0;
                combined_exp_delta_r    <= 11'sd0;
                scale_mant_prod_r       <= 8'b1000_0000;
                scale_mant_active_r     <= 1'b0;
                scale_any_nan_r         <= 1'b0;
                scale_any_zero_r        <= 1'b0;
                scale_inf_mul_zero_nv_r <= 1'b0;
                scale_a_is_unity_r      <= 1'b1;
                scale_b_is_unity_r      <= 1'b1;
                scale_exp_clamp_of_r    <= 1'b0;
                scale_exp_clamp_uf_r    <= 1'b0;
                scaled_sig22_r          <= '0;
                scaled_exp_s11_r        <= '0;
                scaled_zero_r           <= '0;
                scaled_inf_r            <= '0;
                scaled_nan_r            <= '0;
                scaled_sign_r           <= '0;
            end else if (enable) begin
                valid_r                 <= valid_in;
                scale_a_dec_r           <= comb_scale_a_dec;
                scale_b_dec_r           <= comb_scale_b_dec;
                combined_exp_delta_r    <= comb_exp_delta;
                scale_mant_prod_r       <= comb_scale_mant_prod;
                scale_mant_active_r     <= comb_scale_mant_active;
                scale_any_nan_r         <= comb_scale_any_nan;
                scale_any_zero_r        <= comb_scale_any_zero;
                scale_inf_mul_zero_nv_r <= comb_scale_inf_mul_zero_nv;
                scale_a_is_unity_r      <= comb_scale_a_is_unity;
                scale_b_is_unity_r      <= comb_scale_b_is_unity;
                scale_exp_clamp_of_r    <= comb_exp_clamp_of;
                scale_exp_clamp_uf_r    <= comb_exp_clamp_uf;
                scaled_sig22_r          <= comb_scaled_sig22;
                scaled_exp_s11_r        <= comb_scaled_exp_s11;
                scaled_zero_r           <= comb_scaled_zero;
                scaled_inf_r            <= comb_scaled_inf;
                scaled_nan_r            <= comb_scaled_nan;
                scaled_sign_r           <= comb_scaled_sign;
            end
        end

        assign valid_out                 = valid_r;
        assign scale_a_dec_out           = scale_a_dec_r;
        assign scale_b_dec_out           = scale_b_dec_r;
        assign combined_exp_delta_out    = combined_exp_delta_r;
        assign scale_mant_prod_out       = scale_mant_prod_r;
        assign scale_mant_active_out     = scale_mant_active_r;
        assign scale_any_nan_out         = scale_any_nan_r;
        assign scale_any_zero_out        = scale_any_zero_r;
        assign scale_inf_mul_zero_nv_out = scale_inf_mul_zero_nv_r;
        assign scale_a_is_unity_out      = scale_a_is_unity_r;
        assign scale_b_is_unity_out      = scale_b_is_unity_r;
        assign scale_exp_clamp_of_out    = scale_exp_clamp_of_r;
        assign scale_exp_clamp_uf_out    = scale_exp_clamp_uf_r;
        assign scaled_sig22_out          = scaled_sig22_r;
        assign scaled_exp_s11_out        = scaled_exp_s11_r;
        assign scaled_zero_out           = scaled_zero_r;
        assign scaled_inf_out            = scaled_inf_r;
        assign scaled_nan_out            = scaled_nan_r;
        assign scaled_sign_out           = scaled_sign_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out                 = valid_in;
        assign scale_a_dec_out           = comb_scale_a_dec;
        assign scale_b_dec_out           = comb_scale_b_dec;
        assign combined_exp_delta_out    = comb_exp_delta;
        assign scale_mant_prod_out       = comb_scale_mant_prod;
        assign scale_mant_active_out     = comb_scale_mant_active;
        assign scale_any_nan_out         = comb_scale_any_nan;
        assign scale_any_zero_out        = comb_scale_any_zero;
        assign scale_inf_mul_zero_nv_out = comb_scale_inf_mul_zero_nv;
        assign scale_a_is_unity_out      = comb_scale_a_is_unity;
        assign scale_b_is_unity_out      = comb_scale_b_is_unity;
        assign scale_exp_clamp_of_out    = comb_exp_clamp_of;
        assign scale_exp_clamp_uf_out    = comb_exp_clamp_uf;
        assign scaled_sig22_out          = comb_scaled_sig22;
        assign scaled_exp_s11_out        = comb_scaled_exp_s11;
        assign scaled_zero_out           = comb_scaled_zero;
        assign scaled_inf_out            = comb_scaled_inf;
        assign scaled_nan_out            = comb_scaled_nan;
        assign scaled_sign_out           = comb_scaled_sign;
    end

endmodule
