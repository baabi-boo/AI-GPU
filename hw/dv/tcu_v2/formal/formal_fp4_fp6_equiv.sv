// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_formal_fp4_fp6_equiv
    import VX_tcu_v2_pkg::*;
#(
    parameter int LANES = 8
) (
    input  logic                        clk,
    input  logic                        reset,
    // Symbolic unconstrained inputs for FP4 & FP6 unpackers
    input  logic [LANES*8-1:0]          sym_data_a,
    input  logic [LANES*8-1:0]          sym_data_b,
    input  logic                        sym_packed_nibble_mode,
    input  logic                        sym_use_upper_nibble,
    input  logic                        sym_is_nvfp4,
    input  logic                        sym_bit_packed_mode,
    input  logic [LANES-1:0]            sym_lane_mask,
    // Symbolic inputs for MX scale decode & block align
    input  tcu_v2_scale_fmt_e           sym_scale_fmt_a,
    input  tcu_v2_scale_fmt_e           sym_scale_fmt_b,
    input  logic [7:0]                  sym_scale_a_raw,
    input  logic [7:0]                  sym_scale_b_raw,
    input  tcu_v2_fmt_e                 sym_fmt_a,
    input  tcu_v2_fmt_e                 sym_fmt_b,
    input  tcu_v2_scale_fmt_e           sym_expected_scale_fmt,
    input  logic                        sym_enable_subnorm_norm,
    // Observed summary outputs
    output logic                        formal_ok_out
);

    localparam int EXP_W = TCU_V2_FP_EXP_W;

    // -------------------------------------------------------------------------
    // Flip sign bit on every byte/packed lane for sign-negation symmetry proofs
    // -------------------------------------------------------------------------
    logic [LANES*8-1:0] sym_fp4_neg_data;
    logic [LANES*8-1:0] sym_fp6_neg_data;

    always_comb begin
        sym_fp4_neg_data = sym_data_a;
        sym_fp6_neg_data = sym_data_b;
        for (int i = 0; i < LANES; ++i) begin
            if (sym_packed_nibble_mode) begin
                sym_fp4_neg_data[i*8 + 3] = ~sym_data_a[i*8 + 3];
                sym_fp4_neg_data[i*8 + 7] = ~sym_data_a[i*8 + 7];
            end else if (sym_use_upper_nibble) begin
                sym_fp4_neg_data[i*8 + 7] = ~sym_data_a[i*8 + 7];
            end else begin
                sym_fp4_neg_data[i*8 + 3] = ~sym_data_a[i*8 + 3];
            end
        end

        for (int i = 0; i < LANES; ++i) begin
            if (!sym_bit_packed_mode) begin
                sym_fp6_neg_data[i*8 + 5] = ~sym_data_b[i*8 + 5];
            end else begin
                sym_fp6_neg_data[i*6 + 5] = ~sym_data_b[i*6 + 5];
            end
        end
    end

    // -------------------------------------------------------------------------
    // 1. Instantiate FP4 E2M1 Unpackers (Original + Sign-Flipped)
    // -------------------------------------------------------------------------
    tcu_v2_fp_unpacked_t [LANES-1:0] fp4_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] fp4_neg_unp;
    logic [LANES-1:0][3:0]           fp4_nib;
    logic [LANES-1:0][3:0]           fp4_neg_nib;
    logic [LANES-1:0][1:0]           fp4_raw_exp;
    logic [LANES-1:0]                fp4_raw_man;
    logic [LANES-1:0][1:0]           fp4_norm_sig;
    logic [LANES-1:0]                fp4_is_pz;
    logic [LANES-1:0]                fp4_is_nz;
    logic [LANES-1:0]                fp4_is_max;
    logic [LANES-1:0]                fp4_is_sub;
    logic [LANES-1:0]                fp4_is_norm;
    logic [LANES-1:0]                fp4_any_z;
    logic [$clog2(LANES+1)-1:0]      fp4_nz_cnt;
    logic                            fp4_all_z;
    logic                            fp4_nv_out;
    logic [LANES-1:0][2:0]           fp4_cls;
    logic [LANES-1:0]                fp4_half;
    logic [LANES-1:0]                fp4_one;
    logic [LANES-1:0]                fp4_int;
    logic signed [EXP_W-1:0]         fp4_min_e;
    logic signed [EXP_W-1:0]         fp4_max_e;
    logic [LANES-1:0]                fp4_pbz;
    logic [LANES-1:0]                fp4_psm;
    logic [3:0]                      fp4_hz, fp4_hs, fp4_hn, fp4_hx;
    logic [LANES-1:0][31:0]          fp4_fp32;
    logic [LANES-1:0][31:0]          fp4_neg_fp32;
    logic [LANES-1:0][7:0]           fp4_q84;
    logic [LANES-1:0][7:0]           fp4_neg_q84;
    logic [3:0]                      fp4_pos_cnt, fp4_neg_cnt;

    VX_tcu_v2_fp4_unpack #(
        .LANES (LANES)
    ) u_fp4_dut (
        .data_in             (sym_data_a),
        .packed_nibble_mode  (sym_packed_nibble_mode),
        .use_upper_nibble    (sym_use_upper_nibble),
        .is_nvfp4            (sym_is_nvfp4),
        .lane_mask           (sym_lane_mask),
        .unpacked_out        (fp4_unp),
        .raw_nibble_out      (fp4_nib),
        .raw_exp_out         (fp4_raw_exp),
        .raw_man_out         (fp4_raw_man),
        .norm_sig_out        (fp4_norm_sig),
        .is_pos_zero         (fp4_is_pz),
        .is_neg_zero         (fp4_is_nz),
        .is_max_mag          (fp4_is_max),
        .is_subnormal_out    (fp4_is_sub),
        .is_normal_out       (fp4_is_norm),
        .any_zero_vec        (fp4_any_z),
        .nonzero_count       (fp4_nz_cnt),
        .all_lanes_zero      (fp4_all_z),
        .fmt_is_nvfp4_out    (fp4_nv_out),
        .class_code_out      (fp4_cls),
        .is_half_mag_out     (fp4_half),
        .is_one_mag_out      (fp4_one),
        .is_integer_val_out  (fp4_int),
        .lane_min_exp_out    (fp4_min_e),
        .lane_max_exp_out    (fp4_max_e),
        .pair_both_zero_out  (fp4_pbz),
        .pair_sign_match_out (fp4_psm),
        .hist_bin_zero_cnt   (fp4_hz),
        .hist_bin_sub_cnt    (fp4_hs),
        .hist_bin_norm_cnt   (fp4_hn),
        .hist_bin_sat_cnt    (fp4_hx),
        .lane_fp32_equiv_out (fp4_fp32),
        .lane_q8_4_fixed_out (fp4_q84),
        .pos_lane_cnt_out    (fp4_pos_cnt),
        .neg_lane_cnt_out    (fp4_neg_cnt)
    );

    VX_tcu_v2_fp4_unpack #(
        .LANES (LANES)
    ) u_fp4_neg_dut (
        .data_in             (sym_fp4_neg_data),
        .packed_nibble_mode  (sym_packed_nibble_mode),
        .use_upper_nibble    (sym_use_upper_nibble),
        .is_nvfp4            (sym_is_nvfp4),
        .lane_mask           (sym_lane_mask),
        .unpacked_out        (fp4_neg_unp),
        .raw_nibble_out      (fp4_neg_nib),
        .raw_exp_out         (),
        .raw_man_out         (),
        .norm_sig_out        (),
        .is_pos_zero         (),
        .is_neg_zero         (),
        .is_max_mag          (),
        .is_subnormal_out    (),
        .is_normal_out       (),
        .any_zero_vec        (),
        .nonzero_count       (),
        .all_lanes_zero      (),
        .fmt_is_nvfp4_out    (),
        .class_code_out      (),
        .is_half_mag_out     (),
        .is_one_mag_out      (),
        .is_integer_val_out  (),
        .lane_min_exp_out    (),
        .lane_max_exp_out    (),
        .pair_both_zero_out  (),
        .pair_sign_match_out (),
        .hist_bin_zero_cnt   (),
        .hist_bin_sub_cnt    (),
        .hist_bin_norm_cnt   (),
        .hist_bin_sat_cnt    (),
        .lane_fp32_equiv_out (fp4_neg_fp32),
        .lane_q8_4_fixed_out (fp4_neg_q84),
        .pos_lane_cnt_out    (),
        .neg_lane_cnt_out    ()
    );

    // -------------------------------------------------------------------------
    // 2. Instantiate FP6 E2M3 & E3M2 Unpackers (Original + Sign-Flipped)
    // -------------------------------------------------------------------------
    tcu_v2_fp_unpacked_t [LANES-1:0] e2m3_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] e2m3_neg_unp;
    logic [LANES-1:0][5:0]           e2m3_raw;
    logic [LANES-1:0][1:0]           e2m3_exp;
    logic [LANES-1:0][2:0]           e2m3_man;
    logic [LANES-1:0][3:0]           e2m3_raw_sig;
    logic [LANES-1:0][3:0]           e2m3_norm_sig;
    logic [LANES-1:0][1:0]           e2m3_lzc;
    logic [LANES-1:0]                e2m3_pz, e2m3_nz, e2m3_sub, e2m3_norm, e2m3_max;
    logic [$clog2(LANES+1)-1:0]      e2m3_nz_cnt;
    logic                            e2m3_all_z;
    logic [LANES-1:0][2:0]           e2m3_cls;
    logic [LANES-1:0]                e2m3_slot_err;
    logic                            e2m3_any_slot_err;
    logic signed [EXP_W-1:0]         e2m3_min_e, e2m3_max_e;
    logic [3:0]                      e2m3_hz, e2m3_hs, e2m3_hn, e2m3_hx;
    logic [LANES-1:0][31:0]          e2m3_fp32;
    logic [LANES-1:0]                e2m3_exact_int;
    logic [3:0]                      e2m3_pos_cnt, e2m3_neg_cnt;

    VX_tcu_v2_fp6_e2m3_unpack #(
        .LANES (LANES)
    ) u_fp6_e2m3_dut (
        .data_in             (sym_data_b),
        .bit_packed_mode     (sym_bit_packed_mode),
        .lane_mask           (sym_lane_mask),
        .unpacked_out        (e2m3_unp),
        .raw_fp6_out         (e2m3_raw),
        .raw_exp_out         (e2m3_exp),
        .raw_man_out         (e2m3_man),
        .sig_u1p3_out        (e2m3_raw_sig),
        .subnorm_lzc_out     (e2m3_lzc),
        .is_pos_zero         (e2m3_pz),
        .is_neg_zero         (e2m3_nz),
        .is_subnormal_out    (e2m3_sub),
        .is_normal_out       (e2m3_norm),
        .is_max_mag          (e2m3_max),
        .nonzero_count       (e2m3_nz_cnt),
        .all_lanes_zero      (e2m3_all_z),
        .class_code_out      (e2m3_cls),
        .slot_upper_err_out  (e2m3_slot_err),
        .any_slot_err_out    (e2m3_any_slot_err),
        .lane_min_exp_out    (e2m3_min_e),
        .lane_max_exp_out    (e2m3_max_e),
        .hist_zero_cnt       (e2m3_hz),
        .hist_subnorm_cnt    (e2m3_hs),
        .hist_norm_cnt       (e2m3_hn),
        .hist_max_cnt        (e2m3_hx),
        .norm_sig_u1p3_out   (e2m3_norm_sig),
        .lane_fp32_equiv_out (e2m3_fp32),
        .is_exact_int_out    (e2m3_exact_int),
        .pos_lane_cnt_out    (e2m3_pos_cnt),
        .neg_lane_cnt_out    (e2m3_neg_cnt)
    );

    VX_tcu_v2_fp6_e2m3_unpack #(
        .LANES (LANES)
    ) u_fp6_e2m3_neg_dut (
        .data_in             (sym_fp6_neg_data),
        .bit_packed_mode     (sym_bit_packed_mode),
        .lane_mask           (sym_lane_mask),
        .unpacked_out        (e2m3_neg_unp),
        .raw_fp6_out         (),
        .raw_exp_out         (),
        .raw_man_out         (),
        .sig_u1p3_out        (),
        .subnorm_lzc_out     (),
        .is_pos_zero         (),
        .is_neg_zero         (),
        .is_subnormal_out    (),
        .is_normal_out       (),
        .is_max_mag          (),
        .nonzero_count       (),
        .all_lanes_zero      (),
        .class_code_out      (),
        .slot_upper_err_out  (),
        .any_slot_err_out    (),
        .lane_min_exp_out    (),
        .lane_max_exp_out    (),
        .hist_zero_cnt       (),
        .hist_subnorm_cnt    (),
        .hist_norm_cnt       (),
        .hist_max_cnt        (),
        .norm_sig_u1p3_out   (),
        .lane_fp32_equiv_out (),
        .is_exact_int_out    (),
        .pos_lane_cnt_out    (),
        .neg_lane_cnt_out    ()
    );

    tcu_v2_fp_unpacked_t [LANES-1:0] e3m2_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] e3m2_neg_unp;
    logic [LANES-1:0][5:0]           e3m2_raw;
    logic [LANES-1:0][2:0]           e3m2_exp;
    logic [LANES-1:0][1:0]           e3m2_man;
    logic [LANES-1:0][2:0]           e3m2_raw_sig;
    logic [LANES-1:0][2:0]           e3m2_norm_sig;
    logic [LANES-1:0][1:0]           e3m2_lzc;
    logic [LANES-1:0]                e3m2_pz, e3m2_nz, e3m2_sub, e3m2_norm, e3m2_max;
    logic [$clog2(LANES+1)-1:0]      e3m2_nz_cnt;
    logic                            e3m2_all_z;
    logic [LANES-1:0][2:0]           e3m2_cls;
    logic [LANES-1:0]                e3m2_slot_err;
    logic                            e3m2_any_slot_err;
    logic signed [EXP_W-1:0]         e3m2_min_e, e3m2_max_e;
    logic [3:0]                      e3m2_hz, e3m2_hs, e3m2_hn, e3m2_hx;
    logic [LANES-1:0][31:0]          e3m2_fp32;
    logic [LANES-1:0]                e3m2_exact_int;
    logic [3:0]                      e3m2_pos_cnt, e3m2_neg_cnt;

    VX_tcu_v2_fp6_e3m2_unpack #(
        .LANES (LANES)
    ) u_fp6_e3m2_dut (
        .data_in             (sym_data_b),
        .bit_packed_mode     (sym_bit_packed_mode),
        .lane_mask           (sym_lane_mask),
        .unpacked_out        (e3m2_unp),
        .raw_fp6_out         (e3m2_raw),
        .raw_exp_out         (e3m2_exp),
        .raw_man_out         (e3m2_man),
        .sig_u1p2_out        (e3m2_raw_sig),
        .norm_sig_u1p2_out   (e3m2_norm_sig),
        .subnorm_lzc_out     (e3m2_lzc),
        .is_pos_zero         (e3m2_pz),
        .is_neg_zero         (e3m2_nz),
        .is_subnormal_out    (e3m2_sub),
        .is_normal_out       (e3m2_norm),
        .is_max_mag          (e3m2_max),
        .nonzero_count       (e3m2_nz_cnt),
        .all_lanes_zero      (e3m2_all_z),
        .class_code_out      (e3m2_cls),
        .slot_upper_err_out  (e3m2_slot_err),
        .any_slot_err_out    (e3m2_any_slot_err),
        .lane_min_exp_out    (e3m2_min_e),
        .lane_max_exp_out    (e3m2_max_e),
        .hist_zero_cnt       (e3m2_hz),
        .hist_subnorm_cnt    (e3m2_hs),
        .hist_norm_cnt       (e3m2_hn),
        .hist_max_cnt        (e3m2_hx),
        .lane_fp32_equiv_out (e3m2_fp32),
        .is_exact_int_out    (e3m2_exact_int),
        .pos_lane_cnt_out    (e3m2_pos_cnt),
        .neg_lane_cnt_out    (e3m2_neg_cnt)
    );

    VX_tcu_v2_fp6_e3m2_unpack #(
        .LANES (LANES)
    ) u_fp6_e3m2_neg_dut (
        .data_in             (sym_fp6_neg_data),
        .bit_packed_mode     (sym_bit_packed_mode),
        .lane_mask           (sym_lane_mask),
        .unpacked_out        (e3m2_neg_unp),
        .raw_fp6_out         (),
        .raw_exp_out         (),
        .raw_man_out         (),
        .sig_u1p2_out        (),
        .norm_sig_u1p2_out   (),
        .subnorm_lzc_out     (),
        .is_pos_zero         (),
        .is_neg_zero         (),
        .is_subnormal_out    (),
        .is_normal_out       (),
        .is_max_mag          (),
        .nonzero_count       (),
        .all_lanes_zero      (),
        .class_code_out      (),
        .slot_upper_err_out  (),
        .any_slot_err_out    (),
        .lane_min_exp_out    (),
        .lane_max_exp_out    (),
        .hist_zero_cnt       (),
        .hist_subnorm_cnt    (),
        .hist_norm_cnt       (),
        .hist_max_cnt        (),
        .lane_fp32_equiv_out (),
        .is_exact_int_out    (),
        .pos_lane_cnt_out    (),
        .neg_lane_cnt_out    ()
    );

    // -------------------------------------------------------------------------
    // 3. Instantiate MX Scale Decoders (A & B) and Block Alignment Unit
    // -------------------------------------------------------------------------
    tcu_v2_scale_decoded_t   sc_a_dec, sc_b_dec;
    logic signed [EXP_W-1:0] sc_a_exp, sc_b_exp, sc_a_norm_exp, sc_b_norm_exp;
    logic [3:0]              sc_a_mant, sc_b_mant, sc_a_norm_mant, sc_b_norm_mant;
    logic [1:0]              sc_a_lzc, sc_b_lzc;
    logic                    sc_a_zero, sc_b_zero, sc_a_nan, sc_b_nan;
    logic                    sc_a_sub, sc_b_sub, sc_a_unity, sc_b_unity;
    logic                    sc_a_pow2, sc_b_pow2, sc_a_inv, sc_b_inv;
    logic [31:0]             sc_a_fp32, sc_b_fp32;

    VX_tcu_v2_mx_scale_decode #(
        .EXP_W (EXP_W)
    ) u_scale_a_dut (
        .scale_fmt              (sym_scale_fmt_a),
        .scale_raw              (sym_scale_a_raw),
        .decoded_out            (sc_a_dec),
        .exp_delta_out          (sc_a_exp),
        .mant_u1p3_out          (sc_a_mant),
        .norm_mant_u1p3_out     (sc_a_norm_mant),
        .norm_exp_delta_out     (sc_a_norm_exp),
        .mant_lzc_out           (sc_a_lzc),
        .is_zero_out            (sc_a_zero),
        .is_nan_out             (sc_a_nan),
        .is_subnormal_out       (sc_a_sub),
        .is_unity_out           (sc_a_unity),
        .is_max_finite_out      (),
        .is_min_pos_out         (),
        .is_power_of_two_out    (sc_a_pow2),
        .invalid_encoding_out   (sc_a_inv),
        .scale_class_out        (),
        .scale_as_fp32_out      (sc_a_fp32),
        .recip_approx_fp32_out  (),
        .bias_adjusted_raw_out  (),
        .is_gt_unity_out        (),
        .is_lt_unity_out        (),
        .e4m3_to_ue8m0_floor_out(),
        .e4m3_to_ue8m0_ceil_out (),
        .scale_bf16_equiv_out   ()
    );

    VX_tcu_v2_mx_scale_decode #(
        .EXP_W (EXP_W)
    ) u_scale_b_dut (
        .scale_fmt              (sym_scale_fmt_b),
        .scale_raw              (sym_scale_b_raw),
        .decoded_out            (sc_b_dec),
        .exp_delta_out          (sc_b_exp),
        .mant_u1p3_out          (sc_b_mant),
        .norm_mant_u1p3_out     (sc_b_norm_mant),
        .norm_exp_delta_out     (sc_b_norm_exp),
        .mant_lzc_out           (sc_b_lzc),
        .is_zero_out            (sc_b_zero),
        .is_nan_out             (sc_b_nan),
        .is_subnormal_out       (sc_b_sub),
        .is_unity_out           (sc_b_unity),
        .is_max_finite_out      (),
        .is_min_pos_out         (),
        .is_power_of_two_out    (sc_b_pow2),
        .invalid_encoding_out   (sc_b_inv),
        .scale_class_out        (),
        .scale_as_fp32_out      (sc_b_fp32),
        .recip_approx_fp32_out  (),
        .bias_adjusted_raw_out  (),
        .is_gt_unity_out        (),
        .is_lt_unity_out        (),
        .e4m3_to_ue8m0_floor_out(),
        .e4m3_to_ue8m0_ceil_out (),
        .scale_bf16_equiv_out   ()
    );

    logic signed [EXP_W-1:0] blk_comb_exp;
    logic [7:0]              blk_comb_mant_u2p6;
    logic [7:0]              blk_comb_mant_norm;
    logic                    blk_is_zero;
    logic                    blk_is_nan;
    logic                    blk_exp_ovf;
    logic                    blk_exp_unf;
    logic                    blk_is_unity;
    logic                    blk_is_pow2;
    logic [5:0]              blk_size;
    logic                    blk_is_k16;
    logic                    blk_is_k32;
    logic                    blk_mismatch;
    logic [31:0]             blk_fp32;
    logic [7:0]              blk_e4m3_byte;

    VX_tcu_v2_mx_block_align #(
        .EXP_W (EXP_W)
    ) u_block_align_dut (
        .scale_a                        (sc_a_dec),
        .scale_b                        (sc_b_dec),
        .fmt_a                          (sym_fmt_a),
        .fmt_b                          (sym_fmt_b),
        .expected_scale_fmt             (sym_expected_scale_fmt),
        .enable_subnorm_norm            (sym_enable_subnorm_norm),
        .comb_exp_out                   (blk_comb_exp),
        .comb_mant_u2p6_out             (blk_comb_mant_u2p6),
        .comb_mant_norm_u1p7_out        (blk_comb_mant_norm),
        .comb_is_zero_out               (blk_is_zero),
        .comb_is_nan_out                (blk_is_nan),
        .comb_exp_ovf_out               (blk_exp_ovf),
        .comb_exp_unf_out               (blk_exp_unf),
        .comb_is_unity_out              (blk_is_unity),
        .comb_is_pow2_out               (blk_is_pow2),
        .block_size_out                 (blk_size),
        .is_k16_block_out               (blk_is_k16),
        .is_k32_block_out               (blk_is_k32),
        .scale_mismatch_out             (blk_mismatch),
        .comb_scale_fp32_out            (blk_fp32),
        .mant_lzc_out                   (),
        .scale_a_gt_b_out               (),
        .scale_exp_diff_out             (),
        .comb_scale_ue8m0_approx_out    (),
        .comb_scale_e4m3_exp_hint_out   (),
        .comb_requires_fp32_subnorm_out (),
        .comb_scale_e4m3_quant_out      (),
        .comb_scale_e4m3_byte_out       (blk_e4m3_byte),
        .comb_scale_round_inexact_out   (),
        .comb_both_e4m3_subnorm_out     (),
        .comb_any_e4m3_subnorm_out      ()
    );

    assign formal_ok_out = !blk_is_nan && !fp4_all_z && !e2m3_all_z && !e3m2_all_z;

    // -------------------------------------------------------------------------
    // Formal Invariants & Reachability Covers
    // -------------------------------------------------------------------------
`ifdef FORMAL
    always @(posedge clk) begin
        // --- FP4 E2M1 Exhaustive Algebraic Properties ---
        assert (fp4_nv_out == sym_is_nvfp4);
        assert ((4'(fp4_nz_cnt) + fp4_hz) == 4'(LANES));
        assert ((fp4_hs + fp4_hn + fp4_hx) == 4'(fp4_nz_cnt));
        assert ((fp4_pos_cnt + fp4_neg_cnt) == 4'(fp4_nz_cnt));
        assert (fp4_all_z == (fp4_nz_cnt == '0));
        if (!fp4_all_z) begin
            assert (fp4_min_e <= fp4_max_e);
        end

        for (int i = 0; i < LANES; ++i) begin
            // No Inf or NaN ever emitted for FP4
            assert (!fp4_unp[i].is_inf);
            assert (!fp4_unp[i].is_nan);
            assert (!tcu_v2_fp32_is_inf(fp4_fp32[i]));
            assert (!tcu_v2_fp32_is_nan(fp4_fp32[i]));

            // Zero detection iff lane masked off or magnitude bits are zero
            assert (fp4_unp[i].is_zero == ((!sym_lane_mask[i]) || (fp4_nib[i][2:0] == 3'b000)));
            assert (fp4_any_z[i] == fp4_unp[i].is_zero);
            assert ((fp4_is_pz[i] && fp4_is_nz[i]) == 1'b0);
            assert ((fp4_is_sub[i] && fp4_is_norm[i]) == 1'b0);
            assert ((fp4_is_sub[i] && fp4_unp[i].is_zero) == 1'b0);

            // Sign-bit negation symmetry on active lanes
            if (sym_lane_mask[i]) begin
                assert (fp4_neg_unp[i].sign == ~fp4_unp[i].sign);
                assert (fp4_neg_unp[i].exp == fp4_unp[i].exp);
                assert (fp4_neg_unp[i].sig == fp4_unp[i].sig);
                assert (fp4_neg_unp[i].is_zero == fp4_unp[i].is_zero);
                assert (fp4_neg_unp[i].is_subnormal == fp4_unp[i].is_subnormal);
                assert (fp4_neg_nib[i][2:0] == fp4_nib[i][2:0]);
                assert (fp4_neg_fp32[i][30:0] == fp4_fp32[i][30:0]);
                assert (fp4_neg_fp32[i][31] == ~fp4_fp32[i][31]);
                assert ($signed(fp4_neg_q84[i]) == -$signed(fp4_q84[i]));
            end else begin
                assert (fp4_unp[i].is_zero);
                assert (!fp4_unp[i].sign);
            end

            // Subnormal & normal normalization invariants
            if (fp4_is_sub[i]) begin
                assert (fp4_raw_exp[i] == 2'b00);
                assert (fp4_raw_man[i] == 1'b1);
                assert (fp4_norm_sig[i] == 2'b01);
                assert (fp4_unp[i].exp == $signed(EXP_W'(0)));
                assert (fp4_half[i]);
            end
            if (fp4_is_norm[i]) begin
                assert (fp4_norm_sig[i][1] == 1'b1);
            end
        end

        // --- FP6 E2M3 Exhaustive Algebraic Properties ---
        assert ((4'(e2m3_nz_cnt) + e2m3_hz) == 4'(LANES));
        assert ((e2m3_hs + e2m3_hn + e2m3_hx) == 4'(e2m3_nz_cnt));
        assert ((e2m3_pos_cnt + e2m3_neg_cnt) == 4'(e2m3_nz_cnt));
        assert (e2m3_all_z == (e2m3_nz_cnt == '0));
        assert (e2m3_any_slot_err == (|e2m3_slot_err));
        if (!e2m3_all_z) begin
            assert (e2m3_min_e <= e2m3_max_e);
        end

        for (int i = 0; i < LANES; ++i) begin
            // No Inf or NaN emitted for FP6 E2M3
            assert (!e2m3_unp[i].is_inf);
            assert (!e2m3_unp[i].is_nan);
            assert (!tcu_v2_fp32_is_inf(e2m3_fp32[i]));
            assert (!tcu_v2_fp32_is_nan(e2m3_fp32[i]));

            // Zero iff masked or magnitude==0
            assert (e2m3_unp[i].is_zero == ((!sym_lane_mask[i]) || (e2m3_raw[i][4:0] == 5'd0)));
            assert (!(e2m3_pz[i] && e2m3_nz[i]));
            assert (!(e2m3_sub[i] && e2m3_norm[i]));

            // Sign negation symmetry
            if (sym_lane_mask[i]) begin
                assert (e2m3_neg_unp[i].sign == ~e2m3_unp[i].sign);
                assert (e2m3_neg_unp[i].exp == e2m3_unp[i].exp);
                assert (e2m3_neg_unp[i].sig == e2m3_unp[i].sig);
                assert (e2m3_neg_unp[i].is_zero == e2m3_unp[i].is_zero);
                assert (e2m3_neg_unp[i].is_subnormal == e2m3_unp[i].is_subnormal);
            end

            // Subnormal normalization invariant: norm_sig MSB is 1 when subnormal
            if (e2m3_sub[i]) begin
                assert (e2m3_exp[i] == 2'b00);
                assert (e2m3_man[i] != 3'b000);
                assert (e2m3_norm_sig[i][3] == 1'b1);
                assert (e2m3_lzc[i] >= 2'd1 && e2m3_lzc[i] <= 2'd3);
            end else if (e2m3_norm[i]) begin
                assert (e2m3_raw_sig[i][3] == 1'b1);
                assert (e2m3_norm_sig[i][3] == 1'b1);
                assert (e2m3_lzc[i] == 2'd0);
            end
        end

        // --- FP6 E3M2 Exhaustive Algebraic Properties ---
        assert ((4'(e3m2_nz_cnt) + e3m2_hz) == 4'(LANES));
        assert ((e3m2_hs + e3m2_hn + e3m2_hx) == 4'(e3m2_nz_cnt));
        assert ((e3m2_pos_cnt + e3m2_neg_cnt) == 4'(e3m2_nz_cnt));
        assert (e3m2_all_z == (e3m2_nz_cnt == '0));
        assert (e3m2_any_slot_err == (|e3m2_slot_err));
        if (!e3m2_all_z) begin
            assert (e3m2_min_e <= e3m2_max_e);
        end

        for (int i = 0; i < LANES; ++i) begin
            assert (!e3m2_unp[i].is_inf);
            assert (!e3m2_unp[i].is_nan);
            assert (!tcu_v2_fp32_is_inf(e3m2_fp32[i]));
            assert (!tcu_v2_fp32_is_nan(e3m2_fp32[i]));

            assert (e3m2_unp[i].is_zero == ((!sym_lane_mask[i]) || (e3m2_raw[i][4:0] == 5'd0)));
            assert (!(e3m2_pz[i] && e3m2_nz[i]));
            assert (!(e3m2_sub[i] && e3m2_norm[i]));

            if (sym_lane_mask[i]) begin
                assert (e3m2_neg_unp[i].sign == ~e3m2_unp[i].sign);
                assert (e3m2_neg_unp[i].exp == e3m2_unp[i].exp);
                assert (e3m2_neg_unp[i].sig == e3m2_unp[i].sig);
                assert (e3m2_neg_unp[i].is_zero == e3m2_unp[i].is_zero);
                assert (e3m2_neg_unp[i].is_subnormal == e3m2_unp[i].is_subnormal);
            end

            if (e3m2_sub[i]) begin
                assert (e3m2_exp[i] == 3'b000);
                assert (e3m2_man[i] != 2'b00);
                assert (e3m2_norm_sig[i][2] == 1'b1);
                assert (e3m2_lzc[i] >= 2'd1 && e3m2_lzc[i] <= 2'd2);
            end else if (e3m2_norm[i]) begin
                assert (e3m2_raw_sig[i][2] == 1'b1);
                assert (e3m2_norm_sig[i][2] == 1'b1);
                assert (e3m2_lzc[i] == 2'd0);
            end
        end

        // --- MX Scale Decoder Algebraic Properties ---
        // UE8M0: 0xFF -> is_nan, all other values -> finite pow2
        if (sym_scale_fmt_a == TCU_V2_SCALE_UE8M0) begin
            assert (sc_a_nan == (sym_scale_a_raw == 8'hFF));
            assert (!sc_a_zero);
            assert (!sc_a_sub);
            if (sym_scale_a_raw != 8'hFF) begin
                assert (sc_a_pow2);
                assert (sc_a_mant == 4'b1000);
                assert (sc_a_unity == (sym_scale_a_raw == 8'h7F));
            end
        end

        // E4M3 scale: 0x7F and any negative (0x80..0xFF, incl 0xFF) -> is_nan
        if (sym_scale_fmt_a == TCU_V2_SCALE_E4M3) begin
            if ((sym_scale_a_raw == 8'h7F) || (sym_scale_a_raw == 8'hFF) || sym_scale_a_raw[7]) begin
                assert (sc_a_nan);
                assert (sc_a_inv);
            end
            assert (sc_a_zero == (sym_scale_a_raw == 8'h00));
            if (sc_a_sub) begin
                assert (sc_a_norm_mant[3] == 1'b1);
                assert (sc_a_lzc >= 2'd1 && sc_a_lzc <= 2'd3);
            end
        end

        if (sc_a_nan) begin
            assert (tcu_v2_fp32_is_nan(sc_a_fp32));
        end else if (sc_a_zero) begin
            assert (tcu_v2_fp32_is_zero(sc_a_fp32));
        end

        // --- MX Block Align Properties ---
        // Scale NaN dominates combined block scale regardless of other scale
        if (sc_a_nan || sc_b_nan) begin
            assert (blk_is_nan);
            assert (!blk_is_zero);
            assert (tcu_v2_fp32_is_nan(blk_fp32));
            assert (blk_e4m3_byte == 8'h7F);
        end

        // Zero propagation when neither scale is NaN
        if (!sc_a_nan && !sc_b_nan && (sc_a_zero || sc_b_zero)) begin
            assert (blk_is_zero);
            assert (!blk_is_nan);
            assert (tcu_v2_fp32_is_zero(blk_fp32));
        end

        // Normalized combined u1.7 mantissa has leading 1 at bit 7 when subnorm norm is enabled
        if (!blk_is_nan && !blk_is_zero && sym_enable_subnorm_norm) begin
            assert (blk_comb_mant_norm[7] == 1'b1);
        end

        // Block granule size matches format spec (16 for NVFP4, 32 for MXFP4/MXFP6)
        if ((sym_fmt_a == TCU_V2_FMT_NVFP4_E2M1) || (sym_fmt_b == TCU_V2_FMT_NVFP4_E2M1)) begin
            assert (blk_is_k16);
            assert (!blk_is_k32);
            assert (blk_size == 6'd16);
        end

        // --- Reachability Cover Statements ---
        cover (fp4_is_sub[0] && fp4_is_norm[1] && fp4_is_max[2] && fp4_is_nz[3]);
        cover (e2m3_sub[0] && e2m3_norm[1] && e2m3_max[2]);
        cover (e3m2_sub[0] && e3m2_norm[1] && e3m2_max[2]);
        cover ((sym_scale_fmt_a == TCU_V2_SCALE_UE8M0) && (sym_scale_a_raw == 8'hFF) && blk_is_nan);
        cover ((sym_scale_fmt_a == TCU_V2_SCALE_E4M3) && (sym_scale_a_raw == 8'h7F) && blk_is_nan);
        cover ((sym_scale_fmt_a == TCU_V2_SCALE_E4M3) && sc_a_sub &&
               (sym_scale_fmt_b == TCU_V2_SCALE_E4M3) && sc_b_sub &&
               sym_enable_subnorm_norm && !blk_is_nan && !blk_is_zero);
        cover (blk_is_unity && !blk_mismatch && (blk_size == 6'd16));
        cover (blk_is_pow2 && !blk_mismatch && (blk_size == 6'd32));
    end
`endif

endmodule
