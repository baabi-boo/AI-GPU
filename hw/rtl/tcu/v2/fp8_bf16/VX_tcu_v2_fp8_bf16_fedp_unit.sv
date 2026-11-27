// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp8_bf16_fedp_unit #(
    parameter int LANES = 8
) (
    input  logic                        clk,
    input  logic                        reset,
    input  logic                        valid_in,
    output logic                        ready_in,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e  fmt_a,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e  fmt_b,
    input  VX_tcu_v2_pkg::tcu_v2_scale_fmt_e scale_fmt,
    input  VX_tcu_v2_pkg::tcu_v2_rm_e   rm,
    input  logic [LANES*32-1:0]         a_raw,      // up to 32b per lane (TF32); narrower types use low bits per lane
    input  logic [LANES*32-1:0]         b_raw,
    input  logic [7:0]                  scale_a_raw,
    input  logic [7:0]                  scale_b_raw,
    input  logic [31:0]                 c_in,       // FP32 or INT32 accumulator
    input  logic                        accum_en,
    input  logic                        int_saturate,
    output logic                        valid_out,
    input  logic                        ready_out,
    output logic [31:0]                 d_out,      // FP32 or INT32 result
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t flags_out
);
    import VX_tcu_v2_pkg::*;

    localparam int ACC_MAG_W  = 64;
    localparam int ACC_SIGN_W = 72;

    // -------------------------------------------------------------------------
    // Pipeline Backpressure Control (3 registered stages: Mul/Int, CSA, Output)
    // -------------------------------------------------------------------------
    logic pipe_stall;
    logic pipe_en;

    assign pipe_stall = valid_out && !ready_out;
    assign pipe_en    = !pipe_stall;
    assign ready_in   = pipe_en;

    // -------------------------------------------------------------------------
    // Stage 0: Per-Format Operand Unpackers (A & B in parallel)
    // -------------------------------------------------------------------------
    logic a_is_e4m3;
    logic a_is_e5m2;
    logic a_is_bf16;
    logic a_is_fp16;
    logic a_is_tf32;
    logic a_is_int8;

    logic b_is_e4m3;
    logic b_is_e5m2;
    logic b_is_bf16;
    logic b_is_fp16;
    logic b_is_tf32;
    logic b_is_int8;

    assign a_is_e4m3 = (fmt_a == TCU_V2_FMT_FP8_E4M3) || (fmt_a == TCU_V2_FMT_MXFP8_E4M3);
    assign a_is_e5m2 = (fmt_a == TCU_V2_FMT_FP8_E5M2) || (fmt_a == TCU_V2_FMT_MXFP8_E5M2);
    assign a_is_bf16 = (fmt_a == TCU_V2_FMT_BF16);
    assign a_is_fp16 = (fmt_a == TCU_V2_FMT_FP16);
    assign a_is_tf32 = (fmt_a == TCU_V2_FMT_TF32);
    assign a_is_int8 = (fmt_a == TCU_V2_FMT_INT8);

    assign b_is_e4m3 = (fmt_b == TCU_V2_FMT_FP8_E4M3) || (fmt_b == TCU_V2_FMT_MXFP8_E4M3);
    assign b_is_e5m2 = (fmt_b == TCU_V2_FMT_FP8_E5M2) || (fmt_b == TCU_V2_FMT_MXFP8_E5M2);
    assign b_is_bf16 = (fmt_b == TCU_V2_FMT_BF16);
    assign b_is_fp16 = (fmt_b == TCU_V2_FMT_FP16);
    assign b_is_tf32 = (fmt_b == TCU_V2_FMT_TF32);
    assign b_is_int8 = (fmt_b == TCU_V2_FMT_INT8);

    logic mode_int8;
    assign mode_int8 = a_is_int8 && b_is_int8;

    // Unpacker outputs for A
    tcu_v2_fp_unpacked_t [LANES-1:0] a_e4m3_fp;
    logic [LANES-1:0][10:0]          a_e4m3_exp;
    logic [LANES-1:0][31:0]          a_e4m3_fp32_unused;
    logic [LANES-1:0]                a_e4m3_snan;
    logic                            a_e4m3_vld_unused;
    logic [LANES-1:0]                a_e4m3_nan_unused;
    logic [LANES-1:0]                a_e4m3_zero_unused;
    logic [LANES-1:0]                a_e4m3_nzero_unused;
    logic [LANES-1:0]                a_e4m3_sub_unused;
    logic                            a_e4m3_any_nan_unused;
    logic                            a_e4m3_any_snan_unused;
    logic                            a_e4m3_all_zero_unused;
    logic signed [10:0]              a_e4m3_max_exp_unused;
    logic signed [10:0]              a_e4m3_min_exp_unused;
    logic                            a_e4m3_has_fnz_unused;
    logic [3:0]                      a_e4m3_nan_cnt_unused;
    logic [3:0]                      a_e4m3_zero_cnt_unused;
    logic [3:0]                      a_e4m3_sub_cnt_unused;

    VX_tcu_v2_fp8_e4m3_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_a_e4m3 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && a_is_e4m3),
        .data_raw               (a_raw),
        .valid_out              (a_e4m3_vld_unused),
        .fp_out                 (a_e4m3_fp),
        .exp_s11_out            (a_e4m3_exp),
        .fp32_equiv_out         (a_e4m3_fp32_unused),
        .is_snan_out            (a_e4m3_snan),
        .nan_mask_out           (a_e4m3_nan_unused),
        .zero_mask_out          (a_e4m3_zero_unused),
        .neg_zero_mask_out      (a_e4m3_nzero_unused),
        .subnormal_mask_out     (a_e4m3_sub_unused),
        .any_nan_out            (a_e4m3_any_nan_unused),
        .any_snan_out           (a_e4m3_any_snan_unused),
        .all_zero_out           (a_e4m3_all_zero_unused),
        .max_finite_exp_out     (a_e4m3_max_exp_unused),
        .min_finite_exp_out     (a_e4m3_min_exp_unused),
        .has_finite_nonzero_out (a_e4m3_has_fnz_unused),
        .nan_count_out          (a_e4m3_nan_cnt_unused),
        .zero_count_out         (a_e4m3_zero_cnt_unused),
        .subnormal_count_out    (a_e4m3_sub_cnt_unused)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] a_e5m2_fp;
    logic [LANES-1:0][10:0]          a_e5m2_exp;
    logic [LANES-1:0][31:0]          a_e5m2_fp32_unused;
    logic [LANES-1:0]                a_e5m2_snan;
    logic [LANES-1:0]                a_e5m2_qnan_unused;
    logic                            a_e5m2_vld_unused;
    logic [LANES-1:0]                a_e5m2_nan_unused;
    logic [LANES-1:0]                a_e5m2_pinf_unused;
    logic [LANES-1:0]                a_e5m2_ninf_unused;
    logic [LANES-1:0]                a_e5m2_zero_unused;
    logic [LANES-1:0]                a_e5m2_nzero_unused;
    logic [LANES-1:0]                a_e5m2_sub_unused;
    logic                            a_e5m2_any_nan_unused;
    logic                            a_e5m2_any_snan_unused;
    logic                            a_e5m2_any_inf_unused;
    logic                            a_e5m2_all_zero_unused;
    logic signed [10:0]              a_e5m2_max_exp_unused;
    logic signed [10:0]              a_e5m2_min_exp_unused;
    logic                            a_e5m2_has_fnz_unused;
    logic [3:0]                      a_e5m2_nan_cnt_unused;
    logic [3:0]                      a_e5m2_inf_cnt_unused;
    logic [3:0]                      a_e5m2_zero_cnt_unused;
    logic [3:0]                      a_e5m2_sub_cnt_unused;

    VX_tcu_v2_fp8_e5m2_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_a_e5m2 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && a_is_e5m2),
        .data_raw               (a_raw),
        .valid_out              (a_e5m2_vld_unused),
        .fp_out                 (a_e5m2_fp),
        .exp_s11_out            (a_e5m2_exp),
        .fp32_equiv_out         (a_e5m2_fp32_unused),
        .is_snan_out            (a_e5m2_snan),
        .is_qnan_out            (a_e5m2_qnan_unused),
        .nan_mask_out           (a_e5m2_nan_unused),
        .inf_pos_mask_out       (a_e5m2_pinf_unused),
        .inf_neg_mask_out       (a_e5m2_ninf_unused),
        .zero_mask_out          (a_e5m2_zero_unused),
        .neg_zero_mask_out      (a_e5m2_nzero_unused),
        .subnormal_mask_out     (a_e5m2_sub_unused),
        .any_nan_out            (a_e5m2_any_nan_unused),
        .any_snan_out           (a_e5m2_any_snan_unused),
        .any_inf_out            (a_e5m2_any_inf_unused),
        .all_zero_out           (a_e5m2_all_zero_unused),
        .max_finite_exp_out     (a_e5m2_max_exp_unused),
        .min_finite_exp_out     (a_e5m2_min_exp_unused),
        .has_finite_nonzero_out (a_e5m2_has_fnz_unused),
        .nan_count_out          (a_e5m2_nan_cnt_unused),
        .inf_count_out          (a_e5m2_inf_cnt_unused),
        .zero_count_out         (a_e5m2_zero_cnt_unused),
        .subnormal_count_out    (a_e5m2_sub_cnt_unused)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] a_bf16_fp16_fp;
    logic [LANES-1:0][10:0]          a_bf16_fp16_exp;
    logic [LANES-1:0][31:0]          a_bf16_fp32_unused;
    logic [LANES-1:0]                a_bf16_fp16_snan;
    logic [LANES-1:0]                a_bf16_qnan_unused;
    logic                            a_bf16_vld_unused;
    logic [LANES-1:0]                a_bf16_nan_unused;
    logic [LANES-1:0]                a_bf16_pinf_unused;
    logic [LANES-1:0]                a_bf16_ninf_unused;
    logic [LANES-1:0]                a_bf16_zero_unused;
    logic [LANES-1:0]                a_bf16_nzero_unused;
    logic [LANES-1:0]                a_bf16_sub_unused;
    logic                            a_bf16_any_nan_unused;
    logic                            a_bf16_any_snan_unused;
    logic                            a_bf16_any_inf_unused;
    logic                            a_bf16_all_zero_unused;
    logic signed [10:0]              a_bf16_max_exp_unused;
    logic signed [10:0]              a_bf16_min_exp_unused;
    logic                            a_bf16_has_fnz_unused;
    logic [3:0]                      a_bf16_sub_cnt_unused;

    VX_tcu_v2_bf16_fp16_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_a_bf16_fp16 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && (a_is_bf16 || a_is_fp16)),
        .is_bf16                (a_is_bf16),
        .data_raw               (a_raw),
        .valid_out              (a_bf16_vld_unused),
        .fp_out                 (a_bf16_fp16_fp),
        .exp_s11_out            (a_bf16_fp16_exp),
        .fp32_equiv_out         (a_bf16_fp32_unused),
        .is_snan_out            (a_bf16_fp16_snan),
        .is_qnan_out            (a_bf16_qnan_unused),
        .nan_mask_out           (a_bf16_nan_unused),
        .inf_pos_mask_out       (a_bf16_pinf_unused),
        .inf_neg_mask_out       (a_bf16_ninf_unused),
        .zero_mask_out          (a_bf16_zero_unused),
        .neg_zero_mask_out      (a_bf16_nzero_unused),
        .subnormal_mask_out     (a_bf16_sub_unused),
        .any_nan_out            (a_bf16_any_nan_unused),
        .any_snan_out           (a_bf16_any_snan_unused),
        .any_inf_out            (a_bf16_any_inf_unused),
        .all_zero_out           (a_bf16_all_zero_unused),
        .max_finite_exp_out     (a_bf16_max_exp_unused),
        .min_finite_exp_out     (a_bf16_min_exp_unused),
        .has_finite_nonzero_out (a_bf16_has_fnz_unused),
        .subnormal_count_out    (a_bf16_sub_cnt_unused)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] a_tf32_fp;
    logic [LANES-1:0][10:0]          a_tf32_exp;
    logic [LANES-1:0][31:0]          a_tf32_fp32_unused;
    logic signed [LANES-1:0][7:0]    a_int8_vec;
    logic [LANES-1:0][7:0]           a_int8_abs_unused;
    logic [LANES-1:0]                a_tf32_snan;
    logic [LANES-1:0]                a_tf32_qnan_unused;
    logic                            a_tf32_vld_unused;
    logic [LANES-1:0]                a_tf32_nan_unused;
    logic [LANES-1:0]                a_tf32_pinf_unused;
    logic [LANES-1:0]                a_tf32_ninf_unused;
    logic [LANES-1:0]                a_tf32_zero_unused;
    logic [LANES-1:0]                a_tf32_nzero_unused;
    logic [LANES-1:0]                a_tf32_sub_unused;
    logic [LANES-1:0]                a_int_neg_unused;
    logic [LANES-1:0]                a_int_min_unused;
    logic                            a_tf32_any_nan_unused;
    logic                            a_tf32_any_snan_unused;
    logic                            a_tf32_any_inf_unused;
    logic                            a_tf32_all_zero_unused;
    logic signed [10:0]              a_tf32_max_exp_unused;
    logic signed [10:0]              a_tf32_min_exp_unused;
    logic                            a_tf32_has_fnz_unused;

    VX_tcu_v2_tf32_int8_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_a_tf32_int8 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && (a_is_tf32 || a_is_int8)),
        .is_int8                (a_is_int8),
        .data_raw               (a_raw),
        .valid_out              (a_tf32_vld_unused),
        .fp_out                 (a_tf32_fp),
        .exp_s11_out            (a_tf32_exp),
        .fp32_equiv_out         (a_tf32_fp32_unused),
        .int8_out               (a_int8_vec),
        .int8_abs_out           (a_int8_abs_unused),
        .is_snan_out            (a_tf32_snan),
        .is_qnan_out            (a_tf32_qnan_unused),
        .nan_mask_out           (a_tf32_nan_unused),
        .inf_pos_mask_out       (a_tf32_pinf_unused),
        .inf_neg_mask_out       (a_tf32_ninf_unused),
        .zero_mask_out          (a_tf32_zero_unused),
        .neg_zero_mask_out      (a_tf32_nzero_unused),
        .subnormal_mask_out     (a_tf32_sub_unused),
        .int_neg_mask_out       (a_int_neg_unused),
        .int_min_mask_out       (a_int_min_unused),
        .any_nan_out            (a_tf32_any_nan_unused),
        .any_snan_out           (a_tf32_any_snan_unused),
        .any_inf_out            (a_tf32_any_inf_unused),
        .all_zero_out           (a_tf32_all_zero_unused),
        .max_finite_exp_out     (a_tf32_max_exp_unused),
        .min_finite_exp_out     (a_tf32_min_exp_unused),
        .has_finite_nonzero_out (a_tf32_has_fnz_unused)
    );

    // Unpacker outputs for B
    tcu_v2_fp_unpacked_t [LANES-1:0] b_e4m3_fp;
    logic [LANES-1:0][10:0]          b_e4m3_exp;
    logic [LANES-1:0][31:0]          b_e4m3_fp32_unused;
    logic [LANES-1:0]                b_e4m3_snan;
    logic                            b_e4m3_vld_unused;
    logic [LANES-1:0]                b_e4m3_nan_unused;
    logic [LANES-1:0]                b_e4m3_zero_unused;
    logic [LANES-1:0]                b_e4m3_nzero_unused;
    logic [LANES-1:0]                b_e4m3_sub_unused;
    logic                            b_e4m3_any_nan_unused;
    logic                            b_e4m3_any_snan_unused;
    logic                            b_e4m3_all_zero_unused;
    logic signed [10:0]              b_e4m3_max_exp_unused;
    logic signed [10:0]              b_e4m3_min_exp_unused;
    logic                            b_e4m3_has_fnz_unused;
    logic [3:0]                      b_e4m3_nan_cnt_unused;
    logic [3:0]                      b_e4m3_zero_cnt_unused;
    logic [3:0]                      b_e4m3_sub_cnt_unused;

    VX_tcu_v2_fp8_e4m3_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_b_e4m3 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && b_is_e4m3),
        .data_raw               (b_raw),
        .valid_out              (b_e4m3_vld_unused),
        .fp_out                 (b_e4m3_fp),
        .exp_s11_out            (b_e4m3_exp),
        .fp32_equiv_out         (b_e4m3_fp32_unused),
        .is_snan_out            (b_e4m3_snan),
        .nan_mask_out           (b_e4m3_nan_unused),
        .zero_mask_out          (b_e4m3_zero_unused),
        .neg_zero_mask_out      (b_e4m3_nzero_unused),
        .subnormal_mask_out     (b_e4m3_sub_unused),
        .any_nan_out            (b_e4m3_any_nan_unused),
        .any_snan_out           (b_e4m3_any_snan_unused),
        .all_zero_out           (b_e4m3_all_zero_unused),
        .max_finite_exp_out     (b_e4m3_max_exp_unused),
        .min_finite_exp_out     (b_e4m3_min_exp_unused),
        .has_finite_nonzero_out (b_e4m3_has_fnz_unused),
        .nan_count_out          (b_e4m3_nan_cnt_unused),
        .zero_count_out         (b_e4m3_zero_cnt_unused),
        .subnormal_count_out    (b_e4m3_sub_cnt_unused)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] b_e5m2_fp;
    logic [LANES-1:0][10:0]          b_e5m2_exp;
    logic [LANES-1:0][31:0]          b_e5m2_fp32_unused;
    logic [LANES-1:0]                b_e5m2_snan;
    logic [LANES-1:0]                b_e5m2_qnan_unused;
    logic                            b_e5m2_vld_unused;
    logic [LANES-1:0]                b_e5m2_nan_unused;
    logic [LANES-1:0]                b_e5m2_pinf_unused;
    logic [LANES-1:0]                b_e5m2_ninf_unused;
    logic [LANES-1:0]                b_e5m2_zero_unused;
    logic [LANES-1:0]                b_e5m2_nzero_unused;
    logic [LANES-1:0]                b_e5m2_sub_unused;
    logic                            b_e5m2_any_nan_unused;
    logic                            b_e5m2_any_snan_unused;
    logic                            b_e5m2_any_inf_unused;
    logic                            b_e5m2_all_zero_unused;
    logic signed [10:0]              b_e5m2_max_exp_unused;
    logic signed [10:0]              b_e5m2_min_exp_unused;
    logic                            b_e5m2_has_fnz_unused;
    logic [3:0]                      b_e5m2_nan_cnt_unused;
    logic [3:0]                      b_e5m2_inf_cnt_unused;
    logic [3:0]                      b_e5m2_zero_cnt_unused;
    logic [3:0]                      b_e5m2_sub_cnt_unused;

    VX_tcu_v2_fp8_e5m2_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_b_e5m2 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && b_is_e5m2),
        .data_raw               (b_raw),
        .valid_out              (b_e5m2_vld_unused),
        .fp_out                 (b_e5m2_fp),
        .exp_s11_out            (b_e5m2_exp),
        .fp32_equiv_out         (b_e5m2_fp32_unused),
        .is_snan_out            (b_e5m2_snan),
        .is_qnan_out            (b_e5m2_qnan_unused),
        .nan_mask_out           (b_e5m2_nan_unused),
        .inf_pos_mask_out       (b_e5m2_pinf_unused),
        .inf_neg_mask_out       (b_e5m2_ninf_unused),
        .zero_mask_out          (b_e5m2_zero_unused),
        .neg_zero_mask_out      (b_e5m2_nzero_unused),
        .subnormal_mask_out     (b_e5m2_sub_unused),
        .any_nan_out            (b_e5m2_any_nan_unused),
        .any_snan_out           (b_e5m2_any_snan_unused),
        .any_inf_out            (b_e5m2_any_inf_unused),
        .all_zero_out           (b_e5m2_all_zero_unused),
        .max_finite_exp_out     (b_e5m2_max_exp_unused),
        .min_finite_exp_out     (b_e5m2_min_exp_unused),
        .has_finite_nonzero_out (b_e5m2_has_fnz_unused),
        .nan_count_out          (b_e5m2_nan_cnt_unused),
        .inf_count_out          (b_e5m2_inf_cnt_unused),
        .zero_count_out         (b_e5m2_zero_cnt_unused),
        .subnormal_count_out    (b_e5m2_sub_cnt_unused)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] b_bf16_fp16_fp;
    logic [LANES-1:0][10:0]          b_bf16_fp16_exp;
    logic [LANES-1:0][31:0]          b_bf16_fp32_unused;
    logic [LANES-1:0]                b_bf16_fp16_snan;
    logic [LANES-1:0]                b_bf16_qnan_unused;
    logic                            b_bf16_vld_unused;
    logic [LANES-1:0]                b_bf16_nan_unused;
    logic [LANES-1:0]                b_bf16_pinf_unused;
    logic [LANES-1:0]                b_bf16_ninf_unused;
    logic [LANES-1:0]                b_bf16_zero_unused;
    logic [LANES-1:0]                b_bf16_nzero_unused;
    logic [LANES-1:0]                b_bf16_sub_unused;
    logic                            b_bf16_any_nan_unused;
    logic                            b_bf16_any_snan_unused;
    logic                            b_bf16_any_inf_unused;
    logic                            b_bf16_all_zero_unused;
    logic signed [10:0]              b_bf16_max_exp_unused;
    logic signed [10:0]              b_bf16_min_exp_unused;
    logic                            b_bf16_has_fnz_unused;
    logic [3:0]                      b_bf16_sub_cnt_unused;

    VX_tcu_v2_bf16_fp16_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_b_bf16_fp16 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && (b_is_bf16 || b_is_fp16)),
        .is_bf16                (b_is_bf16),
        .data_raw               (b_raw),
        .valid_out              (b_bf16_vld_unused),
        .fp_out                 (b_bf16_fp16_fp),
        .exp_s11_out            (b_bf16_fp16_exp),
        .fp32_equiv_out         (b_bf16_fp32_unused),
        .is_snan_out            (b_bf16_fp16_snan),
        .is_qnan_out            (b_bf16_qnan_unused),
        .nan_mask_out           (b_bf16_nan_unused),
        .inf_pos_mask_out       (b_bf16_pinf_unused),
        .inf_neg_mask_out       (b_bf16_ninf_unused),
        .zero_mask_out          (b_bf16_zero_unused),
        .neg_zero_mask_out      (b_bf16_nzero_unused),
        .subnormal_mask_out     (b_bf16_sub_unused),
        .any_nan_out            (b_bf16_any_nan_unused),
        .any_snan_out           (b_bf16_any_snan_unused),
        .any_inf_out            (b_bf16_any_inf_unused),
        .all_zero_out           (b_bf16_all_zero_unused),
        .max_finite_exp_out     (b_bf16_max_exp_unused),
        .min_finite_exp_out     (b_bf16_min_exp_unused),
        .has_finite_nonzero_out (b_bf16_has_fnz_unused),
        .subnormal_count_out    (b_bf16_sub_cnt_unused)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] b_tf32_fp;
    logic [LANES-1:0][10:0]          b_tf32_exp;
    logic [LANES-1:0][31:0]          b_tf32_fp32_unused;
    logic signed [LANES-1:0][7:0]    b_int8_vec;
    logic [LANES-1:0][7:0]           b_int8_abs_unused;
    logic [LANES-1:0]                b_tf32_snan;
    logic [LANES-1:0]                b_tf32_qnan_unused;
    logic                            b_tf32_vld_unused;
    logic [LANES-1:0]                b_tf32_nan_unused;
    logic [LANES-1:0]                b_tf32_pinf_unused;
    logic [LANES-1:0]                b_tf32_ninf_unused;
    logic [LANES-1:0]                b_tf32_zero_unused;
    logic [LANES-1:0]                b_tf32_nzero_unused;
    logic [LANES-1:0]                b_tf32_sub_unused;
    logic [LANES-1:0]                b_int_neg_unused;
    logic [LANES-1:0]                b_int_min_unused;
    logic                            b_tf32_any_nan_unused;
    logic                            b_tf32_any_snan_unused;
    logic                            b_tf32_any_inf_unused;
    logic                            b_tf32_all_zero_unused;
    logic signed [10:0]              b_tf32_max_exp_unused;
    logic signed [10:0]              b_tf32_min_exp_unused;
    logic                            b_tf32_has_fnz_unused;

    VX_tcu_v2_tf32_int8_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_unpack_b_tf32_int8 (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (pipe_en),
        .valid_in               (valid_in && (b_is_tf32 || b_is_int8)),
        .is_int8                (b_is_int8),
        .data_raw               (b_raw),
        .valid_out              (b_tf32_vld_unused),
        .fp_out                 (b_tf32_fp),
        .exp_s11_out            (b_tf32_exp),
        .fp32_equiv_out         (b_tf32_fp32_unused),
        .int8_out               (b_int8_vec),
        .int8_abs_out           (b_int8_abs_unused),
        .is_snan_out            (b_tf32_snan),
        .is_qnan_out            (b_tf32_qnan_unused),
        .nan_mask_out           (b_tf32_nan_unused),
        .inf_pos_mask_out       (b_tf32_pinf_unused),
        .inf_neg_mask_out       (b_tf32_ninf_unused),
        .zero_mask_out          (b_tf32_zero_unused),
        .neg_zero_mask_out      (b_tf32_nzero_unused),
        .subnormal_mask_out     (b_tf32_sub_unused),
        .int_neg_mask_out       (b_int_neg_unused),
        .int_min_mask_out       (b_int_min_unused),
        .any_nan_out            (b_tf32_any_nan_unused),
        .any_snan_out           (b_tf32_any_snan_unused),
        .any_inf_out            (b_tf32_any_inf_unused),
        .all_zero_out           (b_tf32_all_zero_unused),
        .max_finite_exp_out     (b_tf32_max_exp_unused),
        .min_finite_exp_out     (b_tf32_min_exp_unused),
        .has_finite_nonzero_out (b_tf32_has_fnz_unused)
    );

    // Select active unpacked A and B vectors
    tcu_v2_fp_unpacked_t [LANES-1:0] a_fp_sel;
    logic [LANES-1:0][10:0]          a_exp_sel;
    logic [LANES-1:0]                a_snan_sel;

    tcu_v2_fp_unpacked_t [LANES-1:0] b_fp_sel;
    logic [LANES-1:0][10:0]          b_exp_sel;
    logic [LANES-1:0]                b_snan_sel;

    always_comb begin
        if (a_is_e4m3) begin
            a_fp_sel   = a_e4m3_fp;
            a_exp_sel  = a_e4m3_exp;
            a_snan_sel = a_e4m3_snan;
        end else if (a_is_e5m2) begin
            a_fp_sel   = a_e5m2_fp;
            a_exp_sel  = a_e5m2_exp;
            a_snan_sel = a_e5m2_snan;
        end else if (a_is_bf16 || a_is_fp16) begin
            a_fp_sel   = a_bf16_fp16_fp;
            a_exp_sel  = a_bf16_fp16_exp;
            a_snan_sel = a_bf16_fp16_snan;
        end else begin
            a_fp_sel   = a_tf32_fp;
            a_exp_sel  = a_tf32_exp;
            a_snan_sel = a_tf32_snan;
        end

        if (b_is_e4m3) begin
            b_fp_sel   = b_e4m3_fp;
            b_exp_sel  = b_e4m3_exp;
            b_snan_sel = b_e4m3_snan;
        end else if (b_is_e5m2) begin
            b_fp_sel   = b_e5m2_fp;
            b_exp_sel  = b_e5m2_exp;
            b_snan_sel = b_e5m2_snan;
        end else if (b_is_bf16 || b_is_fp16) begin
            b_fp_sel   = b_bf16_fp16_fp;
            b_exp_sel  = b_bf16_fp16_exp;
            b_snan_sel = b_bf16_fp16_snan;
        end else begin
            b_fp_sel   = b_tf32_fp;
            b_exp_sel  = b_tf32_exp;
            b_snan_sel = b_tf32_snan;
        end
    end

    // -------------------------------------------------------------------------
    // Stage 1: Multi-Precision FP Multiplier Bank & INT8 Dot-Product Unit
    // -------------------------------------------------------------------------
    logic                   s1_fp_valid;
    logic [LANES-1:0][21:0] s1_prod_sig22;
    logic [LANES-1:0][10:0] s1_prod_exp_s11;
    logic [LANES-1:0]       s1_prod_sign;
    logic [LANES-1:0]       s1_prod_zero;
    logic [LANES-1:0]       s1_prod_inf;
    logic [LANES-1:0]       s1_prod_nan;
    logic [LANES-1:0]       s1_prod_snan;
    logic [LANES-1:0]       s1_prod_nv_zero_inf;
    logic [LANES-1:0]       s1_prod_norm_carry_unused;
    logic [2:0]             s1_prec_mode_unused;

    VX_tcu_v2_fp8_bf16_mul_bank #(
        .LANES     (LANES),
        .USE_BOOTH (1'b1),
        .OUT_REG   (1'b1)
    ) u_mul_bank (
        .clk                  (clk),
        .reset                (reset),
        .enable               (pipe_en),
        .valid_in             (valid_in && !mode_int8),
        .fmt_a                (fmt_a),
        .fmt_b                (fmt_b),
        .a_fp_in              (a_fp_sel),
        .b_fp_in              (b_fp_sel),
        .a_exp_s11_in         (a_exp_sel),
        .b_exp_s11_in         (b_exp_sel),
        .a_is_snan_in         (a_snan_sel),
        .b_is_snan_in         (b_snan_sel),
        .valid_out            (s1_fp_valid),
        .prod_sig22_out       (s1_prod_sig22),
        .prod_exp_s11_out     (s1_prod_exp_s11),
        .prod_sign_out        (s1_prod_sign),
        .prod_zero_out        (s1_prod_zero),
        .prod_inf_out         (s1_prod_inf),
        .prod_nan_out         (s1_prod_nan),
        .prod_snan_out        (s1_prod_snan),
        .prod_nv_zero_inf_out (s1_prod_nv_zero_inf),
        .prod_norm_carry_out  (s1_prod_norm_carry_unused),
        .precision_mode_out   (s1_prec_mode_unused)
    );

    logic                   s1_int_valid;
    logic [31:0]            s1_d_int32;
    logic signed [35:0]     s1_int_exact_unused;
    logic [LANES-1:0][15:0] s1_int_lane_prod_unused;
    logic                   s1_int_ovf_unused;
    logic                   s1_int_sat_pos_unused;
    logic                   s1_int_sat_neg_unused;
    logic                   s1_int_zero_unused;
    logic [31:0]            s1_int_abs_u32_unused;

    VX_tcu_v2_int8_dot_acc #(
        .LANES   (LANES),
        .OUT_REG (1'b1)
    ) u_int8_dot (
        .clk               (clk),
        .reset             (reset),
        .enable            (pipe_en),
        .valid_in          (valid_in && mode_int8),
        .a_int8_in         (a_int8_vec),
        .b_int8_in         (b_int8_vec),
        .c_int32_in        ($signed(c_in)),
        .accum_en          (accum_en),
        .int_saturate      (int_saturate),
        .valid_out         (s1_int_valid),
        .d_int32_out       (s1_d_int32),
        .exact_sum_s36_out (s1_int_exact_unused),
        .lane_prod_s16_out (s1_int_lane_prod_unused),
        .overflow_out      (s1_int_ovf_unused),
        .sat_pos_out       (s1_int_sat_pos_unused),
        .sat_neg_out       (s1_int_sat_neg_unused),
        .zero_sum_out      (s1_int_zero_unused),
        .abs_sum_u32_out   (s1_int_abs_u32_unused)
    );

    // Sideband pipeline registers for Stage 0 -> Stage 1
    tcu_v2_fmt_e       s1_fmt_a;
    tcu_v2_fmt_e       s1_fmt_b;
    tcu_v2_scale_fmt_e s1_scale_fmt;
    tcu_v2_rm_e        s1_rm;
    logic [7:0]        s1_scale_a_raw;
    logic [7:0]        s1_scale_b_raw;
    logic [31:0]       s1_c_in;
    logic              s1_accum_en;
    logic              s1_mode_int8;

    always_ff @(posedge clk) begin
        if (reset) begin
            s1_fmt_a       <= TCU_V2_FMT_FP32;
            s1_fmt_b       <= TCU_V2_FMT_FP32;
            s1_scale_fmt   <= TCU_V2_SCALE_NONE;
            s1_rm          <= TCU_V2_RM_RNE;
            s1_scale_a_raw <= 8'd0;
            s1_scale_b_raw <= 8'd0;
            s1_c_in        <= 32'd0;
            s1_accum_en    <= 1'b0;
            s1_mode_int8   <= 1'b0;
        end else if (pipe_en) begin
            s1_fmt_a       <= fmt_a;
            s1_fmt_b       <= fmt_b;
            s1_scale_fmt   <= scale_fmt;
            s1_rm          <= rm;
            s1_scale_a_raw <= scale_a_raw;
            s1_scale_b_raw <= scale_b_raw;
            s1_c_in        <= c_in;
            s1_accum_en    <= accum_en;
            s1_mode_int8   <= mode_int8;
        end
    end

    // -------------------------------------------------------------------------
    // Stage 1.5 (Comb): MX Scale Application + Exponent Alignment
    // -------------------------------------------------------------------------
    logic                   mx_vld_unused;
    tcu_v2_scale_decoded_t  mx_sa_dec_unused;
    tcu_v2_scale_decoded_t  mx_sb_dec_unused;
    logic signed [10:0]     mx_exp_delta_unused;
    logic [7:0]             mx_mant_prod_unused;
    logic                   mx_mant_act_unused;
    logic                   mx_scale_any_nan;
    logic                   mx_scale_any_zero_unused;
    logic                   mx_scale_inf_zero_nv;
    logic                   mx_sa_unity_unused;
    logic                   mx_sb_unity_unused;
    logic                   mx_exp_clamp_of_unused;
    logic                   mx_exp_clamp_uf_unused;
    logic [LANES-1:0][21:0] mx_scaled_sig22;
    logic [LANES-1:0][10:0] mx_scaled_exp_s11;
    logic [LANES-1:0]       mx_scaled_zero;
    logic [LANES-1:0]       mx_scaled_inf;
    logic [LANES-1:0]       mx_scaled_nan;
    logic [LANES-1:0]       mx_scaled_sign;

    VX_tcu_v2_fp8_mx_scale_unit #(
        .LANES   (LANES),
        .OUT_REG (1'b0)
    ) u_mx_scale (
        .clk                       (clk),
        .reset                     (reset),
        .enable                    (pipe_en),
        .valid_in                  (s1_fp_valid),
        .fmt_a                     (s1_fmt_a),
        .fmt_b                     (s1_fmt_b),
        .scale_fmt                 (s1_scale_fmt),
        .scale_a_raw               (s1_scale_a_raw),
        .scale_b_raw               (s1_scale_b_raw),
        .prod_sig22_in             (s1_prod_sig22),
        .prod_exp_s11_in           (s1_prod_exp_s11),
        .prod_zero_in              (s1_prod_zero),
        .prod_inf_in               (s1_prod_inf),
        .prod_nan_in               (s1_prod_nan),
        .prod_sign_in              (s1_prod_sign),
        .valid_out                 (mx_vld_unused),
        .scale_a_dec_out           (mx_sa_dec_unused),
        .scale_b_dec_out           (mx_sb_dec_unused),
        .combined_exp_delta_out    (mx_exp_delta_unused),
        .scale_mant_prod_out       (mx_mant_prod_unused),
        .scale_mant_active_out     (mx_mant_act_unused),
        .scale_any_nan_out         (mx_scale_any_nan),
        .scale_any_zero_out        (mx_scale_any_zero_unused),
        .scale_inf_mul_zero_nv_out (mx_scale_inf_zero_nv),
        .scale_a_is_unity_out      (mx_sa_unity_unused),
        .scale_b_is_unity_out      (mx_sb_unity_unused),
        .scale_exp_clamp_of_out    (mx_exp_clamp_of_unused),
        .scale_exp_clamp_uf_out    (mx_exp_clamp_uf_unused),
        .scaled_sig22_out          (mx_scaled_sig22),
        .scaled_exp_s11_out        (mx_scaled_exp_s11),
        .scaled_zero_out           (mx_scaled_zero),
        .scaled_inf_out            (mx_scaled_inf),
        .scaled_nan_out            (mx_scaled_nan),
        .scaled_sign_out           (mx_scaled_sign)
    );

    logic                            aln_vld_unused;
    logic signed [10:0]              aln_max_exp_s11;
    logic                            aln_has_active_unused;
    logic [LANES:0][ACC_SIGN_W-1:0]  aln_tc;
    logic [LANES:0]                  aln_sticky;
    logic [LANES:0]                  aln_sticky_pos;
    logic [LANES:0]                  aln_sticky_neg;
    logic [LANES:0]                  aln_active_unused;
    logic [LANES:0]                  aln_overshift_unused;
    logic                            aln_c_zero;
    logic                            aln_c_nzero;
    logic                            aln_c_inf;
    logic                            aln_c_nan;
    logic                            aln_c_snan;
    logic                            aln_c_sign;
    logic signed [10:0]              aln_c_exp_s11;
    logic [23:0]                     aln_c_norm_sig24;
    logic                            aln_c_active;
    logic signed [10:0]              aln_lane_max_exp_s11;
    logic                            aln_lanes_active;
    logic [LANES-1:0][ACC_SIGN_W-1:0] aln_lane_tc;
    logic [LANES-1:0]                aln_lane_sticky_pos;
    logic [LANES-1:0]                aln_lane_sticky_neg;

    logic signed [10:0]               aln_tail_max_exp_s11;
    logic                             aln_tail_active;
    logic [LANES-1:0][ACC_SIGN_W-1:0] aln_tail_tc;
    logic [LANES-1:0]                 aln_tail_stk_pos;
    logic [LANES-1:0]                 aln_tail_stk_neg;

    VX_tcu_v2_fp8_fedp_align #(
        .LANES      (LANES),
        .ACC_MAG_W  (ACC_MAG_W),
        .ACC_SIGN_W (ACC_SIGN_W),
        .OUT_REG    (1'b0)
    ) u_fedp_align (
        .clk                  (clk),
        .reset                (reset),
        .enable               (pipe_en),
        .valid_in             (s1_fp_valid),
        .prod_sig22_in        (mx_scaled_sig22),
        .prod_exp_s11_in      (mx_scaled_exp_s11),
        .prod_sign_in         (mx_scaled_sign),
        .prod_zero_in         (mx_scaled_zero),
        .prod_inf_in          (mx_scaled_inf),
        .prod_nan_in          (mx_scaled_nan),
        .c_fp32_in            (s1_c_in),
        .accum_en             (s1_accum_en),
        .valid_out            (aln_vld_unused),
        .max_exp_s11_out      (aln_max_exp_s11),
        .has_active_term_out  (aln_has_active_unused),
        .aligned_tc_out       (aln_tc),
        .sticky_bits_out      (aln_sticky),
        .sticky_pos_out       (aln_sticky_pos),
        .sticky_neg_out       (aln_sticky_neg),
        .term_active_out      (aln_active_unused),
        .term_overshift_out   (aln_overshift_unused),
        .c_is_zero_out        (aln_c_zero),
        .c_is_neg_zero_out    (aln_c_nzero),
        .c_is_inf_out         (aln_c_inf),
        .c_is_nan_out         (aln_c_nan),
        .c_is_snan_out        (aln_c_snan),
        .c_sign_out           (aln_c_sign),
        .c_exp_s11_out        (aln_c_exp_s11),
        .c_norm_sig24_out     (aln_c_norm_sig24),
        .c_active_out         (aln_c_active),
        .lane_max_exp_s11_out (aln_lane_max_exp_s11),
        .lanes_active_out     (aln_lanes_active),
        .lane_aligned_tc_out  (aln_lane_tc),
        .lane_sticky_pos_out  (aln_lane_sticky_pos),
        .lane_sticky_neg_out  (aln_lane_sticky_neg),
        .tail_max_exp_s11_out (aln_tail_max_exp_s11),
        .tail_active_out      (aln_tail_active),
        .tail_aligned_tc_out  (aln_tail_tc),
        .tail_sub_stk_pos_out (aln_tail_stk_pos),
        .tail_sub_stk_neg_out (aln_tail_stk_neg)
    );

    // -------------------------------------------------------------------------
    // Stage 2: CSA Reduction Tree + CPA + Sign-Magnitude Extraction (Registered)
    // -------------------------------------------------------------------------
    logic                  s2_fp_valid;
    logic [ACC_SIGN_W-1:0] s2_sum_tc_unused;
    logic [ACC_SIGN_W-1:0] s2_abs_mag;
    logic                  s2_sum_sign;
    logic                  s2_sum_is_zero;
    logic                  s2_sticky;
    logic                  s2_sticky_pos;
    logic                  s2_sticky_neg;
    logic signed [10:0]    s2_eff_max_exp_s11;
    logic [ACC_SIGN_W-1:0] s2_csa_sum_dbg_unused;
    logic [ACC_SIGN_W-1:0] s2_csa_carry_dbg_unused;

    VX_tcu_v2_fp8_csa_reduce #(
        .NUM_TERMS  (LANES + 1),
        .ACC_MAG_W  (ACC_MAG_W),
        .ACC_SIGN_W (ACC_SIGN_W),
        .OUT_REG    (1'b1)
    ) u_csa_reduce (
        .clk                 (clk),
        .reset               (reset),
        .enable              (pipe_en),
        .valid_in            (s1_fp_valid),
        .aligned_tc_in       (aln_tc),
        .sticky_bits_in      (aln_sticky),
        .sticky_pos_in       (aln_sticky_pos),
        .sticky_neg_in       (aln_sticky_neg),
        .lane_max_exp_s11_in (aln_lane_max_exp_s11),
        .lanes_active_in     (aln_lanes_active),
        .lane_aligned_tc_in  (aln_lane_tc),
        .lane_sticky_pos_in  (aln_lane_sticky_pos),
        .lane_sticky_neg_in  (aln_lane_sticky_neg),
        .tail_max_exp_s11_in (aln_tail_max_exp_s11),
        .tail_active_in      (aln_tail_active),
        .tail_aligned_tc_in  (aln_tail_tc),
        .tail_sub_stk_pos_in (aln_tail_stk_pos),
        .tail_sub_stk_neg_in (aln_tail_stk_neg),
        .c_exp_s11_in        (aln_c_exp_s11),
        .c_norm_sig24_in     (aln_c_norm_sig24),
        .c_active_in         (aln_c_active),
        .c_sign_in           (aln_c_sign),
        .valid_out           (s2_fp_valid),
        .sum_tc_out          (s2_sum_tc_unused),
        .abs_mag_out         (s2_abs_mag),
        .sum_sign_out        (s2_sum_sign),
        .sum_is_zero_out     (s2_sum_is_zero),
        .sticky_out          (s2_sticky),
        .sticky_pos_out      (s2_sticky_pos),
        .sticky_neg_out      (s2_sticky_neg),
        .eff_max_exp_s11_out (s2_eff_max_exp_s11),
        .csa_sum_dbg_out     (s2_csa_sum_dbg_unused),
        .csa_carry_dbg_out   (s2_csa_carry_dbg_unused)
    );

    // Sideband pipeline registers for Stage 1 -> Stage 2
    tcu_v2_rm_e         s2_rm;
    logic signed [10:0] s2_max_exp_s11;
    logic [LANES-1:0]   s2_prod_zero;
    logic [LANES-1:0]   s2_prod_inf;
    logic [LANES-1:0]   s2_prod_nan;
    logic [LANES-1:0]   s2_prod_snan;
    logic [LANES-1:0]   s2_prod_nv_zero_inf;
    logic [LANES-1:0]   s2_prod_sign;
    logic               s2_scale_any_nan;
    logic               s2_scale_inf_zero_nv;
    logic               s2_c_zero;
    logic               s2_c_nzero;
    logic               s2_c_inf;
    logic               s2_c_nan;
    logic               s2_c_snan;
    logic               s2_c_sign;
    logic               s2_accum_en;
    logic               s2_int_valid;
    logic [31:0]        s2_d_int32;
    logic               s2_mode_int8;

    always_ff @(posedge clk) begin
        if (reset) begin
            s2_rm                <= TCU_V2_RM_RNE;
            s2_max_exp_s11       <= 11'sd0;
            s2_prod_zero         <= '0;
            s2_prod_inf          <= '0;
            s2_prod_nan          <= '0;
            s2_prod_snan         <= '0;
            s2_prod_nv_zero_inf  <= '0;
            s2_prod_sign         <= '0;
            s2_scale_any_nan     <= 1'b0;
            s2_scale_inf_zero_nv <= 1'b0;
            s2_c_zero            <= 1'b1;
            s2_c_nzero           <= 1'b0;
            s2_c_inf             <= 1'b0;
            s2_c_nan             <= 1'b0;
            s2_c_snan            <= 1'b0;
            s2_c_sign            <= 1'b0;
            s2_accum_en          <= 1'b0;
            s2_int_valid         <= 1'b0;
            s2_d_int32           <= 32'd0;
            s2_mode_int8         <= 1'b0;
        end else if (pipe_en) begin
            s2_rm                <= s1_rm;
            s2_max_exp_s11       <= aln_max_exp_s11;
            s2_prod_zero         <= mx_scaled_zero;
            s2_prod_inf          <= mx_scaled_inf;
            s2_prod_nan          <= mx_scaled_nan;
            s2_prod_snan         <= s1_prod_snan;
            s2_prod_nv_zero_inf  <= s1_prod_nv_zero_inf;
            s2_prod_sign         <= mx_scaled_sign;
            s2_scale_any_nan     <= mx_scale_any_nan;
            s2_scale_inf_zero_nv <= mx_scale_inf_zero_nv;
            s2_c_zero            <= aln_c_zero;
            s2_c_nzero           <= aln_c_nzero;
            s2_c_inf             <= aln_c_inf;
            s2_c_nan             <= aln_c_nan;
            s2_c_snan            <= aln_c_snan;
            s2_c_sign            <= aln_c_sign;
            s2_accum_en          <= s1_accum_en;
            s2_int_valid         <= s1_int_valid;
            s2_d_int32           <= s1_d_int32;
            s2_mode_int8         <= s1_mode_int8;
        end
    end

    // -------------------------------------------------------------------------
    // Stage 3: FP32 Normalizer/Rounder + Exception Arbiter + Output Registers
    // -------------------------------------------------------------------------
    logic        norm_vld_unused;
    logic [31:0] norm_fp32;
    logic        norm_is_zero;
    logic        norm_is_inf;
    logic        norm_sign;
    logic        norm_of;
    logic        norm_uf;
    logic        norm_nx;
    logic        norm_subnorm_unused;
    logic        norm_rup_unused;

    VX_tcu_v2_fp32_acc_norm #(
        .ACC_MAG_W  (ACC_MAG_W),
        .ACC_SIGN_W (ACC_SIGN_W),
        .OUT_REG    (1'b0)
    ) u_acc_norm (
        .clk             (clk),
        .reset           (reset),
        .enable          (pipe_en),
        .valid_in        (s2_fp_valid),
        .abs_mag_in      (s2_abs_mag),
        .sum_sign_in     (s2_sum_sign),
        .sum_is_zero_in  (s2_sum_is_zero),
        .sticky_in       (s2_sticky),
        .sticky_pos_in   (s2_sticky_pos),
        .sticky_neg_in   (s2_sticky_neg),
        .max_exp_s11_in  (s2_eff_max_exp_s11),
        .rm              (s2_rm),
        .valid_out       (norm_vld_unused),
        .fp32_norm_out   (norm_fp32),
        .res_is_zero_out (norm_is_zero),
        .res_is_inf_out  (norm_is_inf),
        .res_sign_out    (norm_sign),
        .flag_of_out     (norm_of),
        .flag_uf_out     (norm_uf),
        .flag_nx_out     (norm_nx),
        .is_subnorm_out  (norm_subnorm_unused),
        .round_up_out    (norm_rup_unused)
    );

    logic             exc_vld_unused;
    logic [31:0]      exc_resolved_fp32;
    tcu_v2_fp_flags_t exc_flags;
    logic             exc_override_unused;
    logic [3:0]       exc_cause_unused;
    logic             exc_inf_cancel_unused;
    logic             exc_all_zero_unused;

    VX_tcu_v2_fp_exception_unit #(
        .LANES   (LANES),
        .OUT_REG (1'b0)
    ) u_fp_exception (
        .clk                      (clk),
        .reset                    (reset),
        .enable                   (pipe_en),
        .valid_in                 (s2_fp_valid),
        .rm                       (s2_rm),
        .prod_zero_in             (s2_prod_zero),
        .prod_inf_in              (s2_prod_inf),
        .prod_nan_in              (s2_prod_nan),
        .prod_snan_in             (s2_prod_snan),
        .prod_nv_zero_inf_in      (s2_prod_nv_zero_inf),
        .prod_sign_in             (s2_prod_sign),
        .scale_any_nan_in         (s2_scale_any_nan),
        .scale_inf_mul_zero_nv_in (s2_scale_inf_zero_nv),
        .c_is_zero_in             (s2_c_zero),
        .c_is_neg_zero_in         (s2_c_nzero),
        .c_is_inf_in              (s2_c_inf),
        .c_is_nan_in              (s2_c_nan),
        .c_is_snan_in             (s2_c_snan),
        .c_sign_in                (s2_c_sign),
        .accum_en_in              (s2_accum_en),
        .norm_fp32_in             (norm_fp32),
        .norm_is_zero_in          (norm_is_zero),
        .norm_is_inf_in           (norm_is_inf),
        .norm_sign_in             (norm_sign),
        .norm_of_in               (norm_of),
        .norm_uf_in               (norm_uf),
        .norm_nx_in               (norm_nx),
        .valid_out                (exc_vld_unused),
        .resolved_fp32_out        (exc_resolved_fp32),
        .flags_out                (exc_flags),
        .exc_override_out         (exc_override_unused),
        .exc_cause_code_out       (exc_cause_unused),
        .inf_cancel_nan_out       (exc_inf_cancel_unused),
        .all_inputs_zero_out      (exc_all_zero_unused)
    );

    logic             out_valid_r;
    logic [31:0]      out_d_r;
    tcu_v2_fp_flags_t out_flags_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            out_valid_r <= 1'b0;
            out_d_r     <= 32'd0;
            out_flags_r <= '0;
        end else if (pipe_en) begin
            out_valid_r <= s2_mode_int8 ? s2_int_valid : s2_fp_valid;
            out_d_r     <= s2_mode_int8 ? s2_d_int32   : exc_resolved_fp32;
            out_flags_r <= s2_mode_int8 ? '0           : exc_flags;
        end
    end

    assign valid_out = out_valid_r;
    assign d_out     = out_d_r;
    assign flags_out = out_flags_r;

    logic [2:0] pipe_occupancy;
    always_comb begin
        pipe_occupancy = {2'd0, (s1_fp_valid || s1_int_valid)} +
                         {2'd0, (s2_fp_valid || s2_int_valid)} +
                         {2'd0, out_valid_r};
    end

    logic fmt_a_supported;
    logic fmt_b_supported;
    logic mixed_int_fp_illegal;

    assign fmt_a_supported      = a_is_e4m3 || a_is_e5m2 || a_is_bf16 || a_is_fp16 || a_is_tf32 || a_is_int8;
    assign fmt_b_supported      = b_is_e4m3 || b_is_e5m2 || b_is_bf16 || b_is_fp16 || b_is_tf32 || b_is_int8;
    assign mixed_int_fp_illegal = (a_is_int8 ^ b_is_int8);

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (!reset && valid_in) begin
            if (!fmt_a_supported || !fmt_b_supported || mixed_int_fp_illegal) begin
                $error("VX_tcu_v2_fp8_bf16_fedp_unit: unsupported format combination fmt_a=%0d fmt_b=%0d", fmt_a, fmt_b);
            end
        end
    end
`endif

    `UNUSED_VAR (s2_max_exp_s11)
    `UNUSED_VAR (pipe_occupancy)
    `UNUSED_VAR (fmt_a_supported)
    `UNUSED_VAR (fmt_b_supported)
    `UNUSED_VAR (mixed_int_fp_illegal)
    `UNUSED_VAR (a_e4m3_vld_unused)
    `UNUSED_VAR (a_e4m3_fp32_unused)
    `UNUSED_VAR (a_e4m3_nan_unused)
    `UNUSED_VAR (a_e4m3_zero_unused)
    `UNUSED_VAR (a_e4m3_nzero_unused)
    `UNUSED_VAR (a_e4m3_sub_unused)
    `UNUSED_VAR (a_e4m3_any_nan_unused)
    `UNUSED_VAR (a_e4m3_any_snan_unused)
    `UNUSED_VAR (a_e4m3_all_zero_unused)
    `UNUSED_VAR (a_e4m3_max_exp_unused)
    `UNUSED_VAR (a_e4m3_min_exp_unused)
    `UNUSED_VAR (a_e4m3_has_fnz_unused)
    `UNUSED_VAR (a_e4m3_nan_cnt_unused)
    `UNUSED_VAR (a_e4m3_zero_cnt_unused)
    `UNUSED_VAR (a_e4m3_sub_cnt_unused)
    `UNUSED_VAR (a_e5m2_vld_unused)
    `UNUSED_VAR (a_e5m2_fp32_unused)
    `UNUSED_VAR (a_e5m2_qnan_unused)
    `UNUSED_VAR (a_e5m2_nan_unused)
    `UNUSED_VAR (a_e5m2_pinf_unused)
    `UNUSED_VAR (a_e5m2_ninf_unused)
    `UNUSED_VAR (a_e5m2_zero_unused)
    `UNUSED_VAR (a_e5m2_nzero_unused)
    `UNUSED_VAR (a_e5m2_sub_unused)
    `UNUSED_VAR (a_e5m2_any_nan_unused)
    `UNUSED_VAR (a_e5m2_any_snan_unused)
    `UNUSED_VAR (a_e5m2_any_inf_unused)
    `UNUSED_VAR (a_e5m2_all_zero_unused)
    `UNUSED_VAR (a_e5m2_max_exp_unused)
    `UNUSED_VAR (a_e5m2_min_exp_unused)
    `UNUSED_VAR (a_e5m2_has_fnz_unused)
    `UNUSED_VAR (a_e5m2_nan_cnt_unused)
    `UNUSED_VAR (a_e5m2_inf_cnt_unused)
    `UNUSED_VAR (a_e5m2_zero_cnt_unused)
    `UNUSED_VAR (a_e5m2_sub_cnt_unused)
    `UNUSED_VAR (a_bf16_vld_unused)
    `UNUSED_VAR (a_bf16_fp32_unused)
    `UNUSED_VAR (a_bf16_qnan_unused)
    `UNUSED_VAR (a_bf16_nan_unused)
    `UNUSED_VAR (a_bf16_pinf_unused)
    `UNUSED_VAR (a_bf16_ninf_unused)
    `UNUSED_VAR (a_bf16_zero_unused)
    `UNUSED_VAR (a_bf16_nzero_unused)
    `UNUSED_VAR (a_bf16_sub_unused)
    `UNUSED_VAR (a_bf16_any_nan_unused)
    `UNUSED_VAR (a_bf16_any_snan_unused)
    `UNUSED_VAR (a_bf16_any_inf_unused)
    `UNUSED_VAR (a_bf16_all_zero_unused)
    `UNUSED_VAR (a_bf16_max_exp_unused)
    `UNUSED_VAR (a_bf16_min_exp_unused)
    `UNUSED_VAR (a_bf16_has_fnz_unused)
    `UNUSED_VAR (a_bf16_sub_cnt_unused)
    `UNUSED_VAR (a_tf32_vld_unused)
    `UNUSED_VAR (a_tf32_fp32_unused)
    `UNUSED_VAR (a_int8_abs_unused)
    `UNUSED_VAR (a_tf32_qnan_unused)
    `UNUSED_VAR (a_tf32_nan_unused)
    `UNUSED_VAR (a_tf32_pinf_unused)
    `UNUSED_VAR (a_tf32_ninf_unused)
    `UNUSED_VAR (a_tf32_zero_unused)
    `UNUSED_VAR (a_tf32_nzero_unused)
    `UNUSED_VAR (a_tf32_sub_unused)
    `UNUSED_VAR (a_int_neg_unused)
    `UNUSED_VAR (a_int_min_unused)
    `UNUSED_VAR (a_tf32_any_nan_unused)
    `UNUSED_VAR (a_tf32_any_snan_unused)
    `UNUSED_VAR (a_tf32_any_inf_unused)
    `UNUSED_VAR (a_tf32_all_zero_unused)
    `UNUSED_VAR (a_tf32_max_exp_unused)
    `UNUSED_VAR (a_tf32_min_exp_unused)
    `UNUSED_VAR (a_tf32_has_fnz_unused)
    `UNUSED_VAR (b_e4m3_vld_unused)
    `UNUSED_VAR (b_e4m3_fp32_unused)
    `UNUSED_VAR (b_e4m3_nan_unused)
    `UNUSED_VAR (b_e4m3_zero_unused)
    `UNUSED_VAR (b_e4m3_nzero_unused)
    `UNUSED_VAR (b_e4m3_sub_unused)
    `UNUSED_VAR (b_e4m3_any_nan_unused)
    `UNUSED_VAR (b_e4m3_any_snan_unused)
    `UNUSED_VAR (b_e4m3_all_zero_unused)
    `UNUSED_VAR (b_e4m3_max_exp_unused)
    `UNUSED_VAR (b_e4m3_min_exp_unused)
    `UNUSED_VAR (b_e4m3_has_fnz_unused)
    `UNUSED_VAR (b_e4m3_nan_cnt_unused)
    `UNUSED_VAR (b_e4m3_zero_cnt_unused)
    `UNUSED_VAR (b_e4m3_sub_cnt_unused)
    `UNUSED_VAR (b_e5m2_vld_unused)
    `UNUSED_VAR (b_e5m2_fp32_unused)
    `UNUSED_VAR (b_e5m2_qnan_unused)
    `UNUSED_VAR (b_e5m2_nan_unused)
    `UNUSED_VAR (b_e5m2_pinf_unused)
    `UNUSED_VAR (b_e5m2_ninf_unused)
    `UNUSED_VAR (b_e5m2_zero_unused)
    `UNUSED_VAR (b_e5m2_nzero_unused)
    `UNUSED_VAR (b_e5m2_sub_unused)
    `UNUSED_VAR (b_e5m2_any_nan_unused)
    `UNUSED_VAR (b_e5m2_any_snan_unused)
    `UNUSED_VAR (b_e5m2_any_inf_unused)
    `UNUSED_VAR (b_e5m2_all_zero_unused)
    `UNUSED_VAR (b_e5m2_max_exp_unused)
    `UNUSED_VAR (b_e5m2_min_exp_unused)
    `UNUSED_VAR (b_e5m2_has_fnz_unused)
    `UNUSED_VAR (b_e5m2_nan_cnt_unused)
    `UNUSED_VAR (b_e5m2_inf_cnt_unused)
    `UNUSED_VAR (b_e5m2_zero_cnt_unused)
    `UNUSED_VAR (b_e5m2_sub_cnt_unused)
    `UNUSED_VAR (b_bf16_vld_unused)
    `UNUSED_VAR (b_bf16_fp32_unused)
    `UNUSED_VAR (b_bf16_qnan_unused)
    `UNUSED_VAR (b_bf16_nan_unused)
    `UNUSED_VAR (b_bf16_pinf_unused)
    `UNUSED_VAR (b_bf16_ninf_unused)
    `UNUSED_VAR (b_bf16_zero_unused)
    `UNUSED_VAR (b_bf16_nzero_unused)
    `UNUSED_VAR (b_bf16_sub_unused)
    `UNUSED_VAR (b_bf16_any_nan_unused)
    `UNUSED_VAR (b_bf16_any_snan_unused)
    `UNUSED_VAR (b_bf16_any_inf_unused)
    `UNUSED_VAR (b_bf16_all_zero_unused)
    `UNUSED_VAR (b_bf16_max_exp_unused)
    `UNUSED_VAR (b_bf16_min_exp_unused)
    `UNUSED_VAR (b_bf16_has_fnz_unused)
    `UNUSED_VAR (b_bf16_sub_cnt_unused)
    `UNUSED_VAR (b_tf32_vld_unused)
    `UNUSED_VAR (b_tf32_fp32_unused)
    `UNUSED_VAR (b_int8_abs_unused)
    `UNUSED_VAR (b_tf32_qnan_unused)
    `UNUSED_VAR (b_tf32_nan_unused)
    `UNUSED_VAR (b_tf32_pinf_unused)
    `UNUSED_VAR (b_tf32_ninf_unused)
    `UNUSED_VAR (b_tf32_zero_unused)
    `UNUSED_VAR (b_tf32_nzero_unused)
    `UNUSED_VAR (b_tf32_sub_unused)
    `UNUSED_VAR (b_int_neg_unused)
    `UNUSED_VAR (b_int_min_unused)
    `UNUSED_VAR (b_tf32_any_nan_unused)
    `UNUSED_VAR (b_tf32_any_snan_unused)
    `UNUSED_VAR (b_tf32_any_inf_unused)
    `UNUSED_VAR (b_tf32_all_zero_unused)
    `UNUSED_VAR (b_tf32_max_exp_unused)
    `UNUSED_VAR (b_tf32_min_exp_unused)
    `UNUSED_VAR (b_tf32_has_fnz_unused)
    `UNUSED_VAR (s1_prod_norm_carry_unused)
    `UNUSED_VAR (s1_prec_mode_unused)
    `UNUSED_VAR (s1_int_exact_unused)
    `UNUSED_VAR (s1_int_lane_prod_unused)
    `UNUSED_VAR (s1_int_ovf_unused)
    `UNUSED_VAR (s1_int_sat_pos_unused)
    `UNUSED_VAR (s1_int_sat_neg_unused)
    `UNUSED_VAR (s1_int_zero_unused)
    `UNUSED_VAR (s1_int_abs_u32_unused)
    `UNUSED_VAR (mx_vld_unused)
    `UNUSED_VAR (mx_sa_dec_unused)
    `UNUSED_VAR (mx_sb_dec_unused)
    `UNUSED_VAR (mx_exp_delta_unused)
    `UNUSED_VAR (mx_mant_prod_unused)
    `UNUSED_VAR (mx_mant_act_unused)
    `UNUSED_VAR (mx_scale_any_zero_unused)
    `UNUSED_VAR (mx_sa_unity_unused)
    `UNUSED_VAR (mx_sb_unity_unused)
    `UNUSED_VAR (mx_exp_clamp_of_unused)
    `UNUSED_VAR (mx_exp_clamp_uf_unused)
    `UNUSED_VAR (aln_vld_unused)
    `UNUSED_VAR (aln_has_active_unused)
    `UNUSED_VAR (aln_active_unused)
    `UNUSED_VAR (aln_overshift_unused)
    `UNUSED_VAR (s2_sum_tc_unused)
    `UNUSED_VAR (s2_csa_sum_dbg_unused)
    `UNUSED_VAR (s2_csa_carry_dbg_unused)
    `UNUSED_VAR (norm_vld_unused)
    `UNUSED_VAR (norm_subnorm_unused)
    `UNUSED_VAR (norm_rup_unused)
    `UNUSED_VAR (exc_vld_unused)
    `UNUSED_VAR (exc_override_unused)
    `UNUSED_VAR (exc_cause_unused)
    `UNUSED_VAR (exc_inf_cancel_unused)
    `UNUSED_VAR (exc_all_zero_unused)

endmodule
