// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp_exception_unit #(
    parameter int   LANES   = 8,
    parameter logic OUT_REG = 1'b0
) (
    input  logic                              clk,
    input  logic                              reset,
    input  logic                              enable,
    input  logic                              valid_in,
    input  VX_tcu_v2_pkg::tcu_v2_rm_e         rm,
    input  logic [LANES-1:0]                  prod_zero_in,
    input  logic [LANES-1:0]                  prod_inf_in,
    input  logic [LANES-1:0]                  prod_nan_in,
    input  logic [LANES-1:0]                  prod_snan_in,
    input  logic [LANES-1:0]                  prod_nv_zero_inf_in,
    input  logic [LANES-1:0]                  prod_sign_in,
    input  logic                              scale_any_nan_in,
    input  logic                              scale_inf_mul_zero_nv_in,
    input  logic                              c_is_zero_in,
    input  logic                              c_is_neg_zero_in,
    input  logic                              c_is_inf_in,
    input  logic                              c_is_nan_in,
    input  logic                              c_is_snan_in,
    input  logic                              c_sign_in,
    input  logic                              accum_en_in,
    input  logic [31:0]                       norm_fp32_in,
    input  logic                              norm_is_zero_in,
    input  logic                              norm_is_inf_in,
    input  logic                              norm_sign_in,
    input  logic                              norm_of_in,
    input  logic                              norm_uf_in,
    input  logic                              norm_nx_in,
    output logic                              valid_out,
    output logic [31:0]                       resolved_fp32_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t   flags_out,
    output logic                              exc_override_out,
    output logic [3:0]                        exc_cause_code_out,
    output logic                              inf_cancel_nan_out,
    output logic                              all_inputs_zero_out
);
    import VX_tcu_v2_pkg::*;

    localparam logic [3:0] EXC_NONE          = 4'd0;
    localparam logic [3:0] EXC_PROD_SNAN     = 4'd1;
    localparam logic [3:0] EXC_PROD_QNAN     = 4'd2;
    localparam logic [3:0] EXC_ZERO_X_INF    = 4'd3;
    localparam logic [3:0] EXC_SCALE_NAN     = 4'd4;
    localparam logic [3:0] EXC_SCALE_ZERO_INF= 4'd5;
    localparam logic [3:0] EXC_C_SNAN        = 4'd6;
    localparam logic [3:0] EXC_C_QNAN        = 4'd7;
    localparam logic [3:0] EXC_INF_CANCEL    = 4'd8;
    localparam logic [3:0] EXC_POS_INF       = 4'd9;
    localparam logic [3:0] EXC_NEG_INF       = 4'd10;
    localparam logic [3:0] EXC_SIGNED_ZERO   = 4'd11;
    localparam logic [3:0] EXC_NORM_OVERFLOW = 4'd12;

    // -------------------------------------------------------------------------
    // Aggregate Product & Accumulator Inf / NaN / Zero Classifications
    // -------------------------------------------------------------------------
    logic any_prod_nan;
    logic any_prod_snan;
    logic any_prod_nv_zero_inf;
    logic any_prod_pos_inf;
    logic any_prod_neg_inf;
    logic all_prod_zero;
    logic all_prod_neg_zero;

    logic [LANES-1:0] prod_pos_inf_vec;
    logic [LANES-1:0] prod_neg_inf_vec;
    logic [LANES-1:0] prod_neg_zero_vec;
    logic [LANES-1:0] prod_pos_zero_vec;

    for (genvar i = 0; i < LANES; ++i) begin : g_classify_prods
        assign prod_pos_inf_vec[i]  = prod_inf_in[i]  && !prod_sign_in[i];
        assign prod_neg_inf_vec[i]  = prod_inf_in[i]  &&  prod_sign_in[i];
        assign prod_neg_zero_vec[i] = prod_zero_in[i] &&  prod_sign_in[i];
        assign prod_pos_zero_vec[i] = prod_zero_in[i] && !prod_sign_in[i];
    end

    assign any_prod_nan         = |prod_nan_in;
    assign any_prod_snan        = |prod_snan_in;
    assign any_prod_nv_zero_inf = |prod_nv_zero_inf_in;
    assign any_prod_pos_inf     = |prod_pos_inf_vec;
    assign any_prod_neg_inf     = |prod_neg_inf_vec;
    assign all_prod_zero        = &prod_zero_in;
    assign all_prod_neg_zero    = &prod_neg_zero_vec;

    // -------------------------------------------------------------------------
    // IEEE-754 / OFG / OCP MX Exception & Signed-Zero Resolution
    // -------------------------------------------------------------------------
    logic c_pos_inf;
    logic c_neg_inf;
    logic c_active_nan;
    logic c_active_snan;
    logic has_pos_inf;
    logic has_neg_inf;
    logic inf_cancel_nan;
    logic any_nan_result;
    logic any_inf_result;
    logic inf_result_sign;
    logic invalid_op_flag;

    assign c_pos_inf     = accum_en_in && c_is_inf_in && !c_sign_in;
    assign c_neg_inf     = accum_en_in && c_is_inf_in &&  c_sign_in;
    assign c_active_nan  = accum_en_in && c_is_nan_in;
    assign c_active_snan = accum_en_in && c_is_snan_in;

    assign has_pos_inf    = any_prod_pos_inf || c_pos_inf;
    assign has_neg_inf    = any_prod_neg_inf || c_neg_inf;
    assign inf_cancel_nan = has_pos_inf && has_neg_inf;

    assign any_nan_result = any_prod_nan || any_prod_nv_zero_inf || scale_any_nan_in ||
                            scale_inf_mul_zero_nv_in || c_active_nan || inf_cancel_nan;
    assign any_inf_result = !any_nan_result && (has_pos_inf || has_neg_inf);
    assign inf_result_sign = has_neg_inf;

    // IEEE-754 invalid operation (NV) triggers on:
    //   - signaling NaN input (operand or C)
    //   - 0 * Inf (element * element or scale = 0 * Inf)
    //   - +Inf + (-Inf) during accumulation
    assign invalid_op_flag = any_prod_snan || any_prod_nv_zero_inf || scale_inf_mul_zero_nv_in ||
                             c_active_snan || inf_cancel_nan;

    logic [4:0] comb_nv_bitmap;
    assign comb_nv_bitmap = {inf_cancel_nan, c_active_snan, scale_inf_mul_zero_nv_in,
                             any_prod_nv_zero_inf, any_prod_snan};

    `UNUSED_VAR (comb_nv_bitmap)

    // Priority encoder for exception cause classification
    logic [3:0] comb_exc_cause;
    always_comb begin
        if (any_prod_snan) begin
            comb_exc_cause = EXC_PROD_SNAN;
        end else if (any_prod_nv_zero_inf) begin
            comb_exc_cause = EXC_ZERO_X_INF;
        end else if (scale_inf_mul_zero_nv_in) begin
            comb_exc_cause = EXC_SCALE_ZERO_INF;
        end else if (c_active_snan) begin
            comb_exc_cause = EXC_C_SNAN;
        end else if (inf_cancel_nan) begin
            comb_exc_cause = EXC_INF_CANCEL;
        end else if (scale_any_nan_in) begin
            comb_exc_cause = EXC_SCALE_NAN;
        end else if (any_prod_nan) begin
            comb_exc_cause = EXC_PROD_QNAN;
        end else if (c_active_nan) begin
            comb_exc_cause = EXC_C_QNAN;
        end else if (any_inf_result) begin
            comb_exc_cause = inf_result_sign ? EXC_NEG_INF : EXC_POS_INF;
        end else if (norm_of_in && norm_is_inf_in) begin
            comb_exc_cause = EXC_NORM_OVERFLOW;
        end else if (norm_is_zero_in) begin
            comb_exc_cause = EXC_SIGNED_ZERO;
        end else begin
            comb_exc_cause = EXC_NONE;
        end
    end

    // Signed-zero arbitration when all active inputs are zero or finite terms cancel to zero.
    logic       exact_all_inputs_zero;
    logic       all_inputs_neg_zero;
    logic       any_inputs_neg_zero;
    logic       any_inputs_pos_zero;
    logic       resolved_zero_sign;
    logic [1:0] zero_rule_case;

    assign exact_all_inputs_zero = all_prod_zero && (!accum_en_in || c_is_zero_in);
    assign all_inputs_neg_zero   = all_prod_neg_zero && (!accum_en_in || c_is_neg_zero_in);
    assign any_inputs_neg_zero   = (|prod_neg_zero_vec) || (accum_en_in && c_is_zero_in && c_is_neg_zero_in);
    assign any_inputs_pos_zero   = (|prod_pos_zero_vec) || (accum_en_in && c_is_zero_in && !c_is_neg_zero_in);

    always_comb begin
        zero_rule_case = 2'd0;
        if (exact_all_inputs_zero) begin
            if (all_inputs_neg_zero) begin
                resolved_zero_sign = 1'b1;
                zero_rule_case     = 2'd1;
            end else if (any_inputs_neg_zero) begin
                resolved_zero_sign = (rm == TCU_V2_RM_RDN);
                zero_rule_case     = 2'd2;
            end else begin
                resolved_zero_sign = 1'b0;
                zero_rule_case     = 2'd2;
            end
        end else if (norm_is_zero_in) begin
            resolved_zero_sign = norm_uf_in ? norm_sign_in : (norm_sign_in || (rm == TCU_V2_RM_RDN));
            zero_rule_case     = 2'd3;
        end else begin
            resolved_zero_sign = norm_sign_in;
            zero_rule_case     = 2'd0;
        end
    end

    `UNUSED_VAR (zero_rule_case)
    `UNUSED_VAR (any_inputs_pos_zero)

    logic [3:0] comb_prod_nan_cnt;
    logic [3:0] comb_prod_inf_cnt;
    logic [3:0] comb_prod_zero_cnt;
    logic [3:0] comb_prod_neg_zero_cnt;

    always_comb begin
        comb_prod_nan_cnt      = 4'd0;
        comb_prod_inf_cnt      = 4'd0;
        comb_prod_zero_cnt     = 4'd0;
        comb_prod_neg_zero_cnt = 4'd0;
        for (int p = 0; p < LANES; ++p) begin
            comb_prod_nan_cnt      = comb_prod_nan_cnt      + {3'd0, prod_nan_in[p]};
            comb_prod_inf_cnt      = comb_prod_inf_cnt      + {3'd0, prod_inf_in[p]};
            comb_prod_zero_cnt     = comb_prod_zero_cnt     + {3'd0, prod_zero_in[p]};
            comb_prod_neg_zero_cnt = comb_prod_neg_zero_cnt + {3'd0, prod_neg_zero_vec[p]};
        end
    end

    `UNUSED_VAR (comb_prod_nan_cnt)
    `UNUSED_VAR (comb_prod_inf_cnt)
    `UNUSED_VAR (comb_prod_zero_cnt)
    `UNUSED_VAR (comb_prod_neg_zero_cnt)

    logic [31:0]      comb_resolved_fp32;
    tcu_v2_fp_flags_t comb_flags;
    logic             comb_exc_override;

    always_comb begin
        comb_flags        = '0;
        comb_exc_override = 1'b0;
        if (any_nan_result) begin
            comb_resolved_fp32 = TCU_V2_CANONICAL_QNAN;
            comb_flags.nv      = invalid_op_flag;
            comb_exc_override  = 1'b1;
        end else if (any_inf_result) begin
            comb_resolved_fp32 = inf_result_sign ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            comb_exc_override  = 1'b1;
        end else if (exact_all_inputs_zero || norm_is_zero_in) begin
            comb_resolved_fp32 = resolved_zero_sign ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
            comb_flags.uf      = norm_uf_in;
            comb_flags.nx      = norm_nx_in;
            comb_exc_override  = exact_all_inputs_zero || (norm_is_zero_in && (resolved_zero_sign != norm_sign_in));
        end else begin
            comb_resolved_fp32 = norm_fp32_in;
            comb_flags.of      = norm_of_in;
            comb_flags.uf      = norm_uf_in;
            comb_flags.nx      = norm_nx_in;
            comb_exc_override  = norm_is_inf_in;
        end
    end

    // -------------------------------------------------------------------------
    // Optional Pipeline Register Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic             valid_r;
        logic [31:0]      resolved_fp32_r;
        tcu_v2_fp_flags_t flags_r;
        logic             exc_override_r;
        logic [3:0]       exc_cause_r;
        logic             inf_cancel_nan_r;
        logic             all_inputs_zero_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r           <= 1'b0;
                resolved_fp32_r   <= 32'd0;
                flags_r           <= '0;
                exc_override_r    <= 1'b0;
                exc_cause_r       <= EXC_NONE;
                inf_cancel_nan_r  <= 1'b0;
                all_inputs_zero_r <= 1'b0;
            end else if (enable) begin
                valid_r           <= valid_in;
                resolved_fp32_r   <= comb_resolved_fp32;
                flags_r           <= comb_flags;
                exc_override_r    <= comb_exc_override;
                exc_cause_r       <= comb_exc_cause;
                inf_cancel_nan_r  <= inf_cancel_nan;
                all_inputs_zero_r <= exact_all_inputs_zero;
            end
        end

        assign valid_out           = valid_r;
        assign resolved_fp32_out   = resolved_fp32_r;
        assign flags_out           = flags_r;
        assign exc_override_out    = exc_override_r;
        assign exc_cause_code_out  = exc_cause_r;
        assign inf_cancel_nan_out  = inf_cancel_nan_r;
        assign all_inputs_zero_out = all_inputs_zero_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out           = valid_in;
        assign resolved_fp32_out   = comb_resolved_fp32;
        assign flags_out           = comb_flags;
        assign exc_override_out    = comb_exc_override;
        assign exc_cause_code_out  = comb_exc_cause;
        assign inf_cancel_nan_out  = inf_cancel_nan;
        assign all_inputs_zero_out = exact_all_inputs_zero;
    end

endmodule
