// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_formal_fp8_bf16_props
    import VX_tcu_v2_pkg::*;
#(
    parameter int LANES = 8
) (
    input  logic                            clk,
    input  logic                            reset,
    // Symbolic inputs for FP8 E4M3, FP8 E5M2, BF16/FP16 unpackers
    input  logic [LANES*32-1:0]             sym_data_raw,
    input  logic                            sym_is_bf16,
    // Symbolic inputs for INT8 dot-accumulator
    input  logic signed [LANES-1:0][7:0]    sym_a_int8,
    input  logic signed [LANES-1:0][7:0]    sym_b_int8,
    input  logic signed [31:0]              sym_c_int32,
    input  logic                            sym_accum_en,
    input  logic                            sym_int_saturate,
    // Symbolic inputs for FP exception unit
    input  tcu_v2_rm_e                      sym_rm,
    input  logic [LANES-1:0]                sym_prod_zero,
    input  logic [LANES-1:0]                sym_prod_inf,
    input  logic [LANES-1:0]                sym_prod_nan,
    input  logic [LANES-1:0]                sym_prod_snan,
    input  logic [LANES-1:0]                sym_prod_nv_zero_inf,
    input  logic [LANES-1:0]                sym_prod_sign,
    input  logic                            sym_scale_any_nan,
    input  logic                            sym_scale_zero_inf_nv,
    input  logic                            sym_c_is_zero,
    input  logic                            sym_c_is_neg_zero,
    input  logic                            sym_c_is_inf,
    input  logic                            sym_c_is_nan,
    input  logic                            sym_c_is_snan,
    input  logic                            sym_c_sign,
    input  logic [31:0]                     sym_norm_fp32,
    input  logic                            sym_norm_is_zero,
    input  logic                            sym_norm_is_inf,
    input  logic                            sym_norm_sign,
    input  logic                            sym_norm_of,
    input  logic                            sym_norm_uf,
    input  logic                            sym_norm_nx,
    output logic                            formal_ok_out
);

    // -------------------------------------------------------------------------
    // 1. Instantiate Combinational Unpackers: FP8 E4M3FN, FP8 E5M2, BF16/FP16
    // -------------------------------------------------------------------------
    tcu_v2_fp_unpacked_t [LANES-1:0] e4m3_fp;
    logic [LANES-1:0][10:0]          e4m3_exp_s11;
    logic [LANES-1:0][31:0]          e4m3_fp32;
    logic [LANES-1:0]                e4m3_snan, e4m3_nan, e4m3_zero, e4m3_nzero, e4m3_sub;
    logic                            e4m3_any_nan, e4m3_any_snan, e4m3_all_zero, e4m3_has_fnz;
    logic signed [10:0]              e4m3_max_exp, e4m3_min_exp;
    logic [3:0]                      e4m3_nan_cnt, e4m3_zero_cnt, e4m3_sub_cnt;

    VX_tcu_v2_fp8_e4m3_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_e4m3_dut (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (1'b1),
        .valid_in               (1'b1),
        .data_raw               (sym_data_raw),
        .valid_out              (),
        .fp_out                 (e4m3_fp),
        .exp_s11_out            (e4m3_exp_s11),
        .fp32_equiv_out         (e4m3_fp32),
        .is_snan_out            (e4m3_snan),
        .nan_mask_out           (e4m3_nan),
        .zero_mask_out          (e4m3_zero),
        .neg_zero_mask_out      (e4m3_nzero),
        .subnormal_mask_out     (e4m3_sub),
        .any_nan_out            (e4m3_any_nan),
        .any_snan_out           (e4m3_any_snan),
        .all_zero_out           (e4m3_all_zero),
        .max_finite_exp_out     (e4m3_max_exp),
        .min_finite_exp_out     (e4m3_min_exp),
        .has_finite_nonzero_out (e4m3_has_fnz),
        .nan_count_out          (e4m3_nan_cnt),
        .zero_count_out         (e4m3_zero_cnt),
        .subnormal_count_out    (e4m3_sub_cnt)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] e5m2_fp;
    logic [LANES-1:0][10:0]          e5m2_exp_s11;
    logic [LANES-1:0][31:0]          e5m2_fp32;
    logic [LANES-1:0]                e5m2_snan, e5m2_qnan, e5m2_nan;
    logic [LANES-1:0]                e5m2_pinf, e5m2_ninf, e5m2_zero, e5m2_nzero, e5m2_sub;
    logic                            e5m2_any_nan, e5m2_any_snan, e5m2_any_inf, e5m2_all_zero, e5m2_has_fnz;
    logic signed [10:0]              e5m2_max_exp, e5m2_min_exp;
    logic [3:0]                      e5m2_nan_cnt, e5m2_inf_cnt, e5m2_zero_cnt, e5m2_sub_cnt;

    VX_tcu_v2_fp8_e5m2_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_e5m2_dut (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (1'b1),
        .valid_in               (1'b1),
        .data_raw               (sym_data_raw),
        .valid_out              (),
        .fp_out                 (e5m2_fp),
        .exp_s11_out            (e5m2_exp_s11),
        .fp32_equiv_out         (e5m2_fp32),
        .is_snan_out            (e5m2_snan),
        .is_qnan_out            (e5m2_qnan),
        .nan_mask_out           (e5m2_nan),
        .inf_pos_mask_out       (e5m2_pinf),
        .inf_neg_mask_out       (e5m2_ninf),
        .zero_mask_out          (e5m2_zero),
        .neg_zero_mask_out      (e5m2_nzero),
        .subnormal_mask_out     (e5m2_sub),
        .any_nan_out            (e5m2_any_nan),
        .any_snan_out           (e5m2_any_snan),
        .any_inf_out            (e5m2_any_inf),
        .all_zero_out           (e5m2_all_zero),
        .max_finite_exp_out     (e5m2_max_exp),
        .min_finite_exp_out     (e5m2_min_exp),
        .has_finite_nonzero_out (e5m2_has_fnz),
        .nan_count_out          (e5m2_nan_cnt),
        .inf_count_out          (e5m2_inf_cnt),
        .zero_count_out         (e5m2_zero_cnt),
        .subnormal_count_out    (e5m2_sub_cnt)
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] b16_fp;
    logic [LANES-1:0][10:0]          b16_exp_s11;
    logic [LANES-1:0][31:0]          b16_fp32;
    logic [LANES-1:0]                b16_snan, b16_qnan, b16_nan;
    logic [LANES-1:0]                b16_pinf, b16_ninf, b16_zero, b16_nzero, b16_sub;
    logic                            b16_any_nan, b16_any_snan, b16_any_inf, b16_all_zero, b16_has_fnz;
    logic signed [10:0]              b16_max_exp, b16_min_exp;
    logic [3:0]                      b16_sub_cnt;

    VX_tcu_v2_bf16_fp16_unpack #(
        .LANES         (LANES),
        .LANE_STRIDE_W (32),
        .OUT_REG       (1'b0)
    ) u_bf16_fp16_dut (
        .clk                    (clk),
        .reset                  (reset),
        .enable                 (1'b1),
        .valid_in               (1'b1),
        .is_bf16                (sym_is_bf16),
        .data_raw               (sym_data_raw),
        .valid_out              (),
        .fp_out                 (b16_fp),
        .exp_s11_out            (b16_exp_s11),
        .fp32_equiv_out         (b16_fp32),
        .is_snan_out            (b16_snan),
        .is_qnan_out            (b16_qnan),
        .nan_mask_out           (b16_nan),
        .inf_pos_mask_out       (b16_pinf),
        .inf_neg_mask_out       (b16_ninf),
        .zero_mask_out          (b16_zero),
        .neg_zero_mask_out      (b16_nzero),
        .subnormal_mask_out     (b16_sub),
        .any_nan_out            (b16_any_nan),
        .any_snan_out           (b16_any_snan),
        .any_inf_out            (b16_any_inf),
        .all_zero_out           (b16_all_zero),
        .max_finite_exp_out     (b16_max_exp),
        .min_finite_exp_out     (b16_min_exp),
        .has_finite_nonzero_out (b16_has_fnz),
        .subnormal_count_out    (b16_sub_cnt)
    );

    // -------------------------------------------------------------------------
    // 2. Instantiate INT8 Dot Accumulator (OUT_REG=0 for direct symbolic proof)
    // -------------------------------------------------------------------------
    logic [31:0]             int8_d_out;
    logic signed [35:0]      int8_exact_sum;
    logic [LANES-1:0][15:0]  int8_lane_prod;
    logic                    int8_ovf, int8_sat_pos, int8_sat_neg, int8_zero_sum;
    logic [31:0]             int8_abs_u32;

    VX_tcu_v2_int8_dot_acc #(
        .LANES   (LANES),
        .OUT_REG (1'b0)
    ) u_int8_dot_dut (
        .clk               (clk),
        .reset             (reset),
        .enable            (1'b1),
        .valid_in          (1'b1),
        .a_int8_in         (sym_a_int8),
        .b_int8_in         (sym_b_int8),
        .c_int32_in        (sym_c_int32),
        .accum_en          (sym_accum_en),
        .int_saturate      (sym_int_saturate),
        .valid_out         (),
        .d_int32_out       (int8_d_out),
        .exact_sum_s36_out (int8_exact_sum),
        .lane_prod_s16_out (int8_lane_prod),
        .overflow_out      (int8_ovf),
        .sat_pos_out       (int8_sat_pos),
        .sat_neg_out       (int8_sat_neg),
        .zero_sum_out      (int8_zero_sum),
        .abs_sum_u32_out   (int8_abs_u32)
    );

    // Direct 36-bit arithmetic reference for INT8 dot product + optional C
    logic signed [35:0] ref_int8_sum;
    always_comb begin
        ref_int8_sum = sym_accum_en ? $signed({{4{sym_c_int32[31]}}, sym_c_int32}) : 36'sd0;
        for (int i = 0; i < LANES; ++i) begin
            logic signed [15:0] p16;
            p16 = $signed({{8{sym_a_int8[i][7]}}, sym_a_int8[i]}) *
                  $signed({{8{sym_b_int8[i][7]}}, sym_b_int8[i]});
            ref_int8_sum = ref_int8_sum + $signed({{20{p16[15]}}, p16});
        end
    end

    // -------------------------------------------------------------------------
    // 3. Instantiate FP Exception Unit (OUT_REG=0 for direct symbolic proof)
    // -------------------------------------------------------------------------
    logic [31:0]      exc_resolved_fp32;
    tcu_v2_fp_flags_t exc_flags;
    logic             exc_override;
    logic [3:0]       exc_cause_code;
    logic             exc_inf_cancel;
    logic             exc_all_zero;

    VX_tcu_v2_fp_exception_unit #(
        .LANES   (LANES),
        .OUT_REG (1'b0)
    ) u_fp_exc_dut (
        .clk                      (clk),
        .reset                    (reset),
        .enable                   (1'b1),
        .valid_in                 (1'b1),
        .rm                       (sym_rm),
        .prod_zero_in             (sym_prod_zero),
        .prod_inf_in              (sym_prod_inf),
        .prod_nan_in              (sym_prod_nan),
        .prod_snan_in             (sym_prod_snan),
        .prod_nv_zero_inf_in      (sym_prod_nv_zero_inf),
        .prod_sign_in             (sym_prod_sign),
        .scale_any_nan_in         (sym_scale_any_nan),
        .scale_inf_mul_zero_nv_in (sym_scale_zero_inf_nv),
        .c_is_zero_in             (sym_c_is_zero),
        .c_is_neg_zero_in         (sym_c_is_neg_zero),
        .c_is_inf_in              (sym_c_is_inf),
        .c_is_nan_in              (sym_c_is_nan),
        .c_is_snan_in             (sym_c_is_snan),
        .c_sign_in                (sym_c_sign),
        .accum_en_in              (sym_accum_en),
        .norm_fp32_in             (sym_norm_fp32),
        .norm_is_zero_in          (sym_norm_is_zero),
        .norm_is_inf_in           (sym_norm_is_inf),
        .norm_sign_in             (sym_norm_sign),
        .norm_of_in               (sym_norm_of),
        .norm_uf_in               (sym_norm_uf),
        .norm_nx_in               (sym_norm_nx),
        .valid_out                (),
        .resolved_fp32_out        (exc_resolved_fp32),
        .flags_out                (exc_flags),
        .exc_override_out         (exc_override),
        .exc_cause_code_out       (exc_cause_code),
        .inf_cancel_nan_out       (exc_inf_cancel),
        .all_inputs_zero_out      (exc_all_zero)
    );

    assign formal_ok_out = !e4m3_any_nan && !e5m2_any_nan && !exc_inf_cancel;

    // -------------------------------------------------------------------------
    // Formal Proofs & Reachability Covers
    // -------------------------------------------------------------------------
`ifdef FORMAL
    always @(posedge clk) begin
        // --- 1. FP8 E4M3FN Properties ---
        // NEVER produces is_inf on any lane or in FP32 equivalent
        assert (!e4m3_any_snan);
        assert (e4m3_any_nan == (|e4m3_nan));
        assert (e4m3_all_zero == (&e4m3_zero));
        if (e4m3_has_fnz) begin
            assert (e4m3_min_exp <= e4m3_max_exp);
        end

        for (int i = 0; i < LANES; ++i) begin
            logic [7:0] b;
            b = sym_data_raw[i*32 +: 8];
            assert (!e4m3_fp[i].is_inf);
            assert (!e4m3_snan[i]);
            assert (!tcu_v2_fp32_is_inf(e4m3_fp32[i]));

            // 0x7F and 0xFF ALWAYS produce is_nan; ONLY 0x7F/0xFF produce is_nan
            if ((b == 8'h7F) || (b == 8'hFF)) begin
                assert (e4m3_fp[i].is_nan);
                assert (e4m3_nan[i]);
                assert (tcu_v2_fp32_is_nan(e4m3_fp32[i]));
            end
            assert (e4m3_fp[i].is_nan == ((b[6:0] == 7'h7F)));
            assert (e4m3_fp[i].is_zero == (b[6:0] == 7'h00));
            assert (!(e4m3_nan[i] && e4m3_zero[i]));
            assert (!(e4m3_nan[i] && e4m3_sub[i]));
            assert (!(e4m3_zero[i] && e4m3_sub[i]));
            assert (e4m3_nzero[i] == (b == 8'h80));
            if (e4m3_sub[i]) begin
                assert (e4m3_fp[i].sig[23] == 1'b1);
                assert ($signed(e4m3_exp_s11[i]) <= -11'sd7);
            end
        end

        // --- 2. FP8 E5M2 Properties ---
        assert (e5m2_any_nan == (|e5m2_nan));
        assert (e5m2_any_snan == (|e5m2_snan));
        assert (e5m2_any_inf == ((|e5m2_pinf) || (|e5m2_ninf)));
        assert (e5m2_all_zero == (&e5m2_zero));
        if (e5m2_has_fnz) begin
            assert (e5m2_min_exp <= e5m2_max_exp);
        end

        for (int i = 0; i < LANES; ++i) begin
            logic [7:0] b;
            b = sym_data_raw[i*32 +: 8];
            // Inf/NaN exclusivity and exact IEEE-like encoding
            assert (!(e5m2_fp[i].is_inf && e5m2_fp[i].is_nan));
            assert (!(e5m2_pinf[i] && e5m2_ninf[i]));
            assert (e5m2_fp[i].is_inf == ((b[6:2] == 5'h1F) && (b[1:0] == 2'b00)));
            assert (e5m2_fp[i].is_nan == ((b[6:2] == 5'h1F) && (b[1:0] != 2'b00)));
            assert (e5m2_nan[i] == (e5m2_snan[i] || e5m2_qnan[i]));
            assert (!(e5m2_snan[i] && e5m2_qnan[i]));
            assert (e5m2_fp[i].is_zero == (b[6:0] == 7'h00));
            assert (e5m2_nzero[i] == (b == 8'h80));
            if (e5m2_fp[i].is_inf) begin
                assert (tcu_v2_fp32_is_inf(e5m2_fp32[i]));
            end else if (e5m2_fp[i].is_nan) begin
                assert (tcu_v2_fp32_is_nan(e5m2_fp32[i]));
            end
        end

        // --- 3. BF16 / FP16 Unpacker Properties ---
        assert (b16_any_nan == (|b16_nan));
        assert (b16_any_snan == (|b16_snan));
        assert (b16_any_inf == ((|b16_pinf) || (|b16_ninf)));
        assert (b16_all_zero == (&b16_zero));
        if (b16_has_fnz) begin
            assert (b16_min_exp <= b16_max_exp);
        end
        for (int i = 0; i < LANES; ++i) begin
            assert (!(b16_fp[i].is_inf && b16_fp[i].is_nan));
            assert (!(b16_fp[i].is_zero && b16_fp[i].is_subnormal));
            assert (b16_nan[i] == (b16_snan[i] || b16_qnan[i]));
            assert (!(b16_snan[i] && b16_qnan[i]));
            assert (!(b16_pinf[i] && b16_ninf[i]));
            assert (b16_nzero[i] == (b16_zero[i] && b16_fp[i].sign));
            if (b16_fp[i].is_inf) begin
                assert (tcu_v2_fp32_is_inf(b16_fp32[i]));
                assert (b16_fp32[i][31] == b16_fp[i].sign);
            end else if (b16_fp[i].is_nan) begin
                assert (tcu_v2_fp32_is_nan(b16_fp32[i]));
            end
            if (b16_sub[i] && !sym_is_bf16) begin
                assert (b16_fp[i].sig[23] == 1'b1);
                assert ($signed(b16_exp_s11[i]) <= -11'sd15);
            end
        end

        // --- 4. INT8 Dot Accumulator Exactness & Saturation Clamp Bounds ---
        assert (int8_exact_sum == ref_int8_sum);
        assert (int8_zero_sum == (ref_int8_sum == 36'sd0));
        assert (!(int8_sat_pos && int8_sat_neg));
        for (int i = 0; i < LANES; ++i) begin
            logic signed [15:0] p_ref;
            p_ref = $signed({{8{sym_a_int8[i][7]}}, sym_a_int8[i]}) *
                    $signed({{8{sym_b_int8[i][7]}}, sym_b_int8[i]});
            assert ($signed(int8_lane_prod[i]) == p_ref);
        end

        assert (int8_ovf == ((ref_int8_sum > $signed({4'b0000, TCU_V2_INT32_MAX})) ||
                             (ref_int8_sum < $signed({4'b1111, TCU_V2_INT32_MIN}))));

        if (sym_int_saturate) begin
            // Saturated output must stay clamped in [INT32_MIN, INT32_MAX]
            assert ($signed(int8_d_out) >= $signed(TCU_V2_INT32_MIN));
            assert ($signed(int8_d_out) <= $signed(TCU_V2_INT32_MAX));
            if (ref_int8_sum > $signed({4'b0000, TCU_V2_INT32_MAX})) begin
                assert (int8_sat_pos);
                assert (!int8_sat_neg);
                assert (int8_d_out == TCU_V2_INT32_MAX);
            end else if (ref_int8_sum < $signed({4'b1111, TCU_V2_INT32_MIN})) begin
                assert (int8_sat_neg);
                assert (!int8_sat_pos);
                assert (int8_d_out == TCU_V2_INT32_MIN);
            end else begin
                assert (!int8_sat_pos && !int8_sat_neg);
                assert ($signed({{4{int8_d_out[31]}}, int8_d_out}) == ref_int8_sum);
            end
        end else begin
            assert (!int8_sat_pos && !int8_sat_neg);
            assert (int8_d_out == ref_int8_sum[31:0]);
        end

        if (int8_d_out != TCU_V2_INT32_MIN) begin
            if ($signed(int8_d_out) < 0) begin
                assert (int8_abs_u32 == 32'(-$signed(int8_d_out)));
            end else begin
                assert (int8_abs_u32 == int8_d_out);
            end
        end

        // --- 5. FP Exception Unit Algebraic Properties ---
        // Constraint for coherent input encodings: sNaN implies NaN, prod_inf/prod_nan disjoint
        assume ((sym_prod_snan & ~sym_prod_nan) == '0);
        assume ((sym_prod_inf & sym_prod_nan) == '0);
        assume (!sym_c_is_snan || sym_c_is_nan);
        assume (!(sym_c_is_inf && sym_c_is_nan));

        // NaN dominance (product NaN, scale NaN, or active C NaN)
        if ((|sym_prod_nan) || sym_scale_any_nan || (sym_accum_en && sym_c_is_nan)) begin
            assert (exc_resolved_fp32 == TCU_V2_CANONICAL_QNAN);
            assert (exc_override);
        end

        // 0 * Inf -> NaN + NV flag
        if ((|sym_prod_nv_zero_inf) || sym_scale_zero_inf_nv) begin
            assert (exc_resolved_fp32 == TCU_V2_CANONICAL_QNAN);
            assert (exc_flags.nv);
            assert (exc_override);
        end

        // (+Inf) + (-Inf) -> NaN + NV flag
        if (sym_accum_en && sym_c_is_inf && (|sym_prod_inf)) begin
            // Check explicit opposite-sign infinity cancellation
            if (((|(sym_prod_inf & ~sym_prod_sign)) && sym_c_sign) ||
                ((|(sym_prod_inf & sym_prod_sign)) && !sym_c_sign)) begin
                assert (exc_inf_cancel);
                assert (exc_resolved_fp32 == TCU_V2_CANONICAL_QNAN);
                assert (exc_flags.nv);
                assert (exc_override);
            end
        end

        // Product-internal (+Inf) + (-Inf) cancellation
        if ((|(sym_prod_inf & ~sym_prod_sign)) && (|(sym_prod_inf & sym_prod_sign))) begin
            assert (exc_inf_cancel);
            assert (exc_resolved_fp32 == TCU_V2_CANONICAL_QNAN);
            assert (exc_flags.nv);
        end

        // --- Reachability Covers ---
        cover ((sym_data_raw[7:0] == 8'h7F) && e4m3_nan[0]);
        cover ((sym_data_raw[7:0] == 8'hFF) && e4m3_nan[0]);
        cover (e4m3_sub[0] && !e4m3_any_nan);
        cover (e5m2_pinf[0]);
        cover (e5m2_ninf[0]);
        cover (e5m2_snan[0]);
        cover (e5m2_qnan[0]);
        cover (!sym_is_bf16 && b16_sub[0]);
        cover (!sym_is_bf16 && b16_pinf[0]);
        cover (!sym_is_bf16 && b16_snan[0]);
        cover (sym_int_saturate && int8_sat_pos && (int8_d_out == TCU_V2_INT32_MAX));
        cover (sym_int_saturate && int8_sat_neg && (int8_d_out == TCU_V2_INT32_MIN));
        cover (sym_accum_en && !sym_c_is_nan && !(|sym_prod_nan) && exc_inf_cancel && exc_flags.nv);
        cover ((|sym_prod_nv_zero_inf) && exc_flags.nv && (exc_resolved_fp32 == TCU_V2_CANONICAL_QNAN));
        cover ((exc_cause_code == 4'd0) && !exc_override && !exc_flags.nv);
    end
`endif

endmodule
