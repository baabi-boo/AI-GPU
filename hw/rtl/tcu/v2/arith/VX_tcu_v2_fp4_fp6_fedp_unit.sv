// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp4_fp6_fedp_unit #(
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
    input  logic [LANES*8-1:0]          a_raw,
    input  logic [LANES*8-1:0]          b_raw,
    input  logic [7:0]                  scale_a_raw,
    input  logic [7:0]                  scale_b_raw,
    input  logic [31:0]                 c_fp32,
    input  logic                        accum_en,
    output logic                        valid_out,
    input  logic                        ready_out,
    output logic [31:0]                 d_fp32,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t flags_out
);

    import VX_tcu_v2_pkg::*;

    localparam int EXP_W = TCU_V2_FP_EXP_W;
    localparam int SIG_W = TCU_V2_FP_SIG_W;
    localparam int ACC_W = TCU_V2_WIDE_ACC_W;
    localparam int LZC_W = $clog2(ACC_W);
    localparam int SH_W  = $clog2(ACC_W + 1);

    // -------------------------------------------------------------------------
    // Pipeline Handshake & Stage Enable Control
    // -------------------------------------------------------------------------
    logic pipe_s0_valid_q;
    logic pipe_s1_valid_q;
    logic pipe_s2_valid_q;

    logic stall_out;
    logic stage2_en;
    logic stage1_en;
    logic stage0_en;

    assign stall_out = pipe_s2_valid_q && !ready_out;
    assign stage2_en = !stall_out;
    assign stage1_en = stage2_en;
    assign stage0_en = (!pipe_s0_valid_q) || stage1_en;
    assign ready_in  = stage0_en;

    // -------------------------------------------------------------------------
    // Stage 0 Combinational: Format Classification, Unpack & Scale Decode
    // -------------------------------------------------------------------------
    logic s0_a_is_nvfp4;
    logic s0_b_is_nvfp4;
    logic s0_a_is_fp4;
    logic s0_b_is_fp4;
    logic s0_a_is_e2m3;
    logic s0_b_is_e2m3;
    logic s0_a_is_e3m2;
    logic s0_b_is_e3m2;
    logic s0_fmt_valid;
    logic [LANES-1:0] s0_lane_mask;

    assign s0_a_is_nvfp4 = (fmt_a == TCU_V2_FMT_NVFP4_E2M1);
    assign s0_b_is_nvfp4 = (fmt_b == TCU_V2_FMT_NVFP4_E2M1);
    assign s0_a_is_fp4   = tcu_v2_fmt_is_fp4(fmt_a);
    assign s0_b_is_fp4   = tcu_v2_fmt_is_fp4(fmt_b);
    assign s0_a_is_e2m3  = (fmt_a == TCU_V2_FMT_MXFP6_E2M3);
    assign s0_b_is_e2m3  = (fmt_b == TCU_V2_FMT_MXFP6_E2M3);
    assign s0_a_is_e3m2  = (fmt_a == TCU_V2_FMT_MXFP6_E3M2);
    assign s0_b_is_e3m2  = (fmt_b == TCU_V2_FMT_MXFP6_E3M2);
    assign s0_fmt_valid  = (s0_a_is_fp4 || s0_a_is_e2m3 || s0_a_is_e3m2) &&
                           (s0_b_is_fp4 || s0_b_is_e2m3 || s0_b_is_e3m2);
    assign s0_lane_mask  = {LANES{1'b1}};

    // Unpacked A & B FP4 streams
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_fp4_a_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_fp4_b_unp;
    logic [LANES-1:0][3:0]           s0_fp4_a_nib;
    logic [LANES-1:0][3:0]           s0_fp4_b_nib;
    logic [LANES-1:0][1:0]           s0_fp4_a_rexp;
    logic [LANES-1:0][1:0]           s0_fp4_b_rexp;
    logic [LANES-1:0]                s0_fp4_a_rman;
    logic [LANES-1:0]                s0_fp4_b_rman;
    logic [LANES-1:0][1:0]           s0_fp4_a_nsig;
    logic [LANES-1:0][1:0]           s0_fp4_b_nsig;
    logic [LANES-1:0]                s0_fp4_a_pz;
    logic [LANES-1:0]                s0_fp4_b_pz;
    logic [LANES-1:0]                s0_fp4_a_nz;
    logic [LANES-1:0]                s0_fp4_b_nz;
    logic [LANES-1:0]                s0_fp4_a_max;
    logic [LANES-1:0]                s0_fp4_b_max;
    logic [LANES-1:0]                s0_fp4_a_sub;
    logic [LANES-1:0]                s0_fp4_b_sub;
    logic [LANES-1:0]                s0_fp4_a_norm;
    logic [LANES-1:0]                s0_fp4_b_norm;
    logic [LANES-1:0]                s0_fp4_a_anyz;
    logic [LANES-1:0]                s0_fp4_b_anyz;
    logic [$clog2(LANES+1)-1:0]      s0_fp4_a_nzc;
    logic [$clog2(LANES+1)-1:0]      s0_fp4_b_nzc;
    logic                            s0_fp4_a_allz;
    logic                            s0_fp4_b_allz;
    logic                            s0_fp4_a_nv;
    logic                            s0_fp4_b_nv;
    logic [LANES-1:0][2:0]           s0_fp4_a_cls;
    logic [LANES-1:0][2:0]           s0_fp4_b_cls;
    logic [LANES-1:0]                s0_fp4_a_half;
    logic [LANES-1:0]                s0_fp4_b_half;
    logic [LANES-1:0]                s0_fp4_a_one;
    logic [LANES-1:0]                s0_fp4_b_one;
    logic [LANES-1:0]                s0_fp4_a_int;
    logic [LANES-1:0]                s0_fp4_b_int;
    logic signed [EXP_W-1:0]         s0_fp4_a_mine;
    logic signed [EXP_W-1:0]         s0_fp4_b_mine;
    logic signed [EXP_W-1:0]         s0_fp4_a_maxe;
    logic signed [EXP_W-1:0]         s0_fp4_b_maxe;
    logic [LANES-1:0]                s0_fp4_a_pzero;
    logic [LANES-1:0]                s0_fp4_b_pzero;
    logic [LANES-1:0]                s0_fp4_a_psign;
    logic [LANES-1:0]                s0_fp4_b_psign;
    logic [3:0]                      s0_fp4_a_hb0;
    logic [3:0]                      s0_fp4_a_hb1;
    logic [3:0]                      s0_fp4_a_hb2;
    logic [3:0]                      s0_fp4_a_hb3;
    logic [3:0]                      s0_fp4_b_hb0;
    logic [3:0]                      s0_fp4_b_hb1;
    logic [3:0]                      s0_fp4_b_hb2;
    logic [3:0]                      s0_fp4_b_hb3;
    logic [LANES-1:0][31:0]          s0_fp4_a_fp32;
    logic [LANES-1:0][31:0]          s0_fp4_b_fp32;
    logic [LANES-1:0][7:0]           s0_fp4_a_q84;
    logic [LANES-1:0][7:0]           s0_fp4_b_q84;
    logic [3:0]                      s0_fp4_a_pcnt;
    logic [3:0]                      s0_fp4_a_ncnt;
    logic [3:0]                      s0_fp4_b_pcnt;
    logic [3:0]                      s0_fp4_b_ncnt;

    VX_tcu_v2_fp4_unpack #(
        .LANES (LANES)
    ) u_fp4_unpack_a (
        .data_in             (a_raw),
        .packed_nibble_mode  (1'b0),
        .use_upper_nibble    (1'b0),
        .is_nvfp4            (s0_a_is_nvfp4),
        .lane_mask           (s0_lane_mask),
        .unpacked_out        (s0_fp4_a_unp),
        .raw_nibble_out      (s0_fp4_a_nib),
        .raw_exp_out         (s0_fp4_a_rexp),
        .raw_man_out         (s0_fp4_a_rman),
        .norm_sig_out        (s0_fp4_a_nsig),
        .is_pos_zero         (s0_fp4_a_pz),
        .is_neg_zero         (s0_fp4_a_nz),
        .is_max_mag          (s0_fp4_a_max),
        .is_subnormal_out    (s0_fp4_a_sub),
        .is_normal_out       (s0_fp4_a_norm),
        .any_zero_vec        (s0_fp4_a_anyz),
        .nonzero_count       (s0_fp4_a_nzc),
        .all_lanes_zero      (s0_fp4_a_allz),
        .fmt_is_nvfp4_out    (s0_fp4_a_nv),
        .class_code_out      (s0_fp4_a_cls),
        .is_half_mag_out     (s0_fp4_a_half),
        .is_one_mag_out      (s0_fp4_a_one),
        .is_integer_val_out  (s0_fp4_a_int),
        .lane_min_exp_out    (s0_fp4_a_mine),
        .lane_max_exp_out    (s0_fp4_a_maxe),
        .pair_both_zero_out  (s0_fp4_a_pzero),
        .pair_sign_match_out (s0_fp4_a_psign),
        .hist_bin_zero_cnt   (s0_fp4_a_hb0),
        .hist_bin_sub_cnt    (s0_fp4_a_hb1),
        .hist_bin_norm_cnt   (s0_fp4_a_hb2),
        .hist_bin_sat_cnt    (s0_fp4_a_hb3),
        .lane_fp32_equiv_out (s0_fp4_a_fp32),
        .lane_q8_4_fixed_out (s0_fp4_a_q84),
        .pos_lane_cnt_out    (s0_fp4_a_pcnt),
        .neg_lane_cnt_out    (s0_fp4_a_ncnt)
    );

    VX_tcu_v2_fp4_unpack #(
        .LANES (LANES)
    ) u_fp4_unpack_b (
        .data_in             (b_raw),
        .packed_nibble_mode  (1'b0),
        .use_upper_nibble    (1'b0),
        .is_nvfp4            (s0_b_is_nvfp4),
        .lane_mask           (s0_lane_mask),
        .unpacked_out        (s0_fp4_b_unp),
        .raw_nibble_out      (s0_fp4_b_nib),
        .raw_exp_out         (s0_fp4_b_rexp),
        .raw_man_out         (s0_fp4_b_rman),
        .norm_sig_out        (s0_fp4_b_nsig),
        .is_pos_zero         (s0_fp4_b_pz),
        .is_neg_zero         (s0_fp4_b_nz),
        .is_max_mag          (s0_fp4_b_max),
        .is_subnormal_out    (s0_fp4_b_sub),
        .is_normal_out       (s0_fp4_b_norm),
        .any_zero_vec        (s0_fp4_b_anyz),
        .nonzero_count       (s0_fp4_b_nzc),
        .all_lanes_zero      (s0_fp4_b_allz),
        .fmt_is_nvfp4_out    (s0_fp4_b_nv),
        .class_code_out      (s0_fp4_b_cls),
        .is_half_mag_out     (s0_fp4_b_half),
        .is_one_mag_out      (s0_fp4_b_one),
        .is_integer_val_out  (s0_fp4_b_int),
        .lane_min_exp_out    (s0_fp4_b_mine),
        .lane_max_exp_out    (s0_fp4_b_maxe),
        .pair_both_zero_out  (s0_fp4_b_pzero),
        .pair_sign_match_out (s0_fp4_b_psign),
        .hist_bin_zero_cnt   (s0_fp4_b_hb0),
        .hist_bin_sub_cnt    (s0_fp4_b_hb1),
        .hist_bin_norm_cnt   (s0_fp4_b_hb2),
        .hist_bin_sat_cnt    (s0_fp4_b_hb3),
        .lane_fp32_equiv_out (s0_fp4_b_fp32),
        .lane_q8_4_fixed_out (s0_fp4_b_q84),
        .pos_lane_cnt_out    (s0_fp4_b_pcnt),
        .neg_lane_cnt_out    (s0_fp4_b_ncnt)
    );

    // Unpacked A & B FP6 E2M3 streams
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_e2m3_a_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_e2m3_b_unp;
    logic [LANES-1:0][5:0]           s0_e2m3_a_raw6;
    logic [LANES-1:0][5:0]           s0_e2m3_b_raw6;
    logic [LANES-1:0][1:0]           s0_e2m3_a_rexp;
    logic [LANES-1:0][1:0]           s0_e2m3_b_rexp;
    logic [LANES-1:0][2:0]           s0_e2m3_a_rman;
    logic [LANES-1:0][2:0]           s0_e2m3_b_rman;
    logic [LANES-1:0][3:0]           s0_e2m3_a_sig;
    logic [LANES-1:0][3:0]           s0_e2m3_b_sig;
    logic [LANES-1:0][1:0]           s0_e2m3_a_lzc;
    logic [LANES-1:0][1:0]           s0_e2m3_b_lzc;
    logic [LANES-1:0]                s0_e2m3_a_pz;
    logic [LANES-1:0]                s0_e2m3_b_pz;
    logic [LANES-1:0]                s0_e2m3_a_nz;
    logic [LANES-1:0]                s0_e2m3_b_nz;
    logic [LANES-1:0]                s0_e2m3_a_sub;
    logic [LANES-1:0]                s0_e2m3_b_sub;
    logic [LANES-1:0]                s0_e2m3_a_norm;
    logic [LANES-1:0]                s0_e2m3_b_norm;
    logic [LANES-1:0]                s0_e2m3_a_max;
    logic [LANES-1:0]                s0_e2m3_b_max;
    logic [$clog2(LANES+1)-1:0]      s0_e2m3_a_nzc;
    logic [$clog2(LANES+1)-1:0]      s0_e2m3_b_nzc;
    logic                            s0_e2m3_a_allz;
    logic                            s0_e2m3_b_allz;
    logic [LANES-1:0][2:0]           s0_e2m3_a_cls;
    logic [LANES-1:0][2:0]           s0_e2m3_b_cls;
    logic [LANES-1:0]                s0_e2m3_a_serr;
    logic [LANES-1:0]                s0_e2m3_b_serr;
    logic                            s0_e2m3_a_anyserr;
    logic                            s0_e2m3_b_anyserr;
    logic signed [EXP_W-1:0]         s0_e2m3_a_mine;
    logic signed [EXP_W-1:0]         s0_e2m3_b_mine;
    logic signed [EXP_W-1:0]         s0_e2m3_a_maxe;
    logic signed [EXP_W-1:0]         s0_e2m3_b_maxe;
    logic [3:0]                      s0_e2m3_a_hb0;
    logic [3:0]                      s0_e2m3_a_hb1;
    logic [3:0]                      s0_e2m3_a_hb2;
    logic [3:0]                      s0_e2m3_a_hb3;
    logic [3:0]                      s0_e2m3_b_hb0;
    logic [3:0]                      s0_e2m3_b_hb1;
    logic [3:0]                      s0_e2m3_b_hb2;
    logic [3:0]                      s0_e2m3_b_hb3;
    logic [LANES-1:0][3:0]           s0_e2m3_a_nsig;
    logic [LANES-1:0][3:0]           s0_e2m3_b_nsig;
    logic [LANES-1:0][31:0]          s0_e2m3_a_fp32;
    logic [LANES-1:0][31:0]          s0_e2m3_b_fp32;
    logic [LANES-1:0]                s0_e2m3_a_int;
    logic [LANES-1:0]                s0_e2m3_b_int;
    logic [3:0]                      s0_e2m3_a_pcnt;
    logic [3:0]                      s0_e2m3_a_ncnt;
    logic [3:0]                      s0_e2m3_b_pcnt;
    logic [3:0]                      s0_e2m3_b_ncnt;

    VX_tcu_v2_fp6_e2m3_unpack #(
        .LANES (LANES)
    ) u_fp6_e2m3_unpack_a (
        .data_in             (a_raw),
        .bit_packed_mode     (1'b0),
        .lane_mask           (s0_lane_mask),
        .unpacked_out        (s0_e2m3_a_unp),
        .raw_fp6_out         (s0_e2m3_a_raw6),
        .raw_exp_out         (s0_e2m3_a_rexp),
        .raw_man_out         (s0_e2m3_a_rman),
        .sig_u1p3_out        (s0_e2m3_a_sig),
        .subnorm_lzc_out     (s0_e2m3_a_lzc),
        .is_pos_zero         (s0_e2m3_a_pz),
        .is_neg_zero         (s0_e2m3_a_nz),
        .is_subnormal_out    (s0_e2m3_a_sub),
        .is_normal_out       (s0_e2m3_a_norm),
        .is_max_mag          (s0_e2m3_a_max),
        .nonzero_count       (s0_e2m3_a_nzc),
        .all_lanes_zero      (s0_e2m3_a_allz),
        .class_code_out      (s0_e2m3_a_cls),
        .slot_upper_err_out  (s0_e2m3_a_serr),
        .any_slot_err_out    (s0_e2m3_a_anyserr),
        .lane_min_exp_out    (s0_e2m3_a_mine),
        .lane_max_exp_out    (s0_e2m3_a_maxe),
        .hist_zero_cnt       (s0_e2m3_a_hb0),
        .hist_subnorm_cnt    (s0_e2m3_a_hb1),
        .hist_norm_cnt       (s0_e2m3_a_hb2),
        .hist_max_cnt        (s0_e2m3_a_hb3),
        .norm_sig_u1p3_out   (s0_e2m3_a_nsig),
        .lane_fp32_equiv_out (s0_e2m3_a_fp32),
        .is_exact_int_out    (s0_e2m3_a_int),
        .pos_lane_cnt_out    (s0_e2m3_a_pcnt),
        .neg_lane_cnt_out    (s0_e2m3_a_ncnt)
    );

    VX_tcu_v2_fp6_e2m3_unpack #(
        .LANES (LANES)
    ) u_fp6_e2m3_unpack_b (
        .data_in             (b_raw),
        .bit_packed_mode     (1'b0),
        .lane_mask           (s0_lane_mask),
        .unpacked_out        (s0_e2m3_b_unp),
        .raw_fp6_out         (s0_e2m3_b_raw6),
        .raw_exp_out         (s0_e2m3_b_rexp),
        .raw_man_out         (s0_e2m3_b_rman),
        .sig_u1p3_out        (s0_e2m3_b_sig),
        .subnorm_lzc_out     (s0_e2m3_b_lzc),
        .is_pos_zero         (s0_e2m3_b_pz),
        .is_neg_zero         (s0_e2m3_b_nz),
        .is_subnormal_out    (s0_e2m3_b_sub),
        .is_normal_out       (s0_e2m3_b_norm),
        .is_max_mag          (s0_e2m3_b_max),
        .nonzero_count       (s0_e2m3_b_nzc),
        .all_lanes_zero      (s0_e2m3_b_allz),
        .class_code_out      (s0_e2m3_b_cls),
        .slot_upper_err_out  (s0_e2m3_b_serr),
        .any_slot_err_out    (s0_e2m3_b_anyserr),
        .lane_min_exp_out    (s0_e2m3_b_mine),
        .lane_max_exp_out    (s0_e2m3_b_maxe),
        .hist_zero_cnt       (s0_e2m3_b_hb0),
        .hist_subnorm_cnt    (s0_e2m3_b_hb1),
        .hist_norm_cnt       (s0_e2m3_b_hb2),
        .hist_max_cnt        (s0_e2m3_b_hb3),
        .norm_sig_u1p3_out   (s0_e2m3_b_nsig),
        .lane_fp32_equiv_out (s0_e2m3_b_fp32),
        .is_exact_int_out    (s0_e2m3_b_int),
        .pos_lane_cnt_out    (s0_e2m3_b_pcnt),
        .neg_lane_cnt_out    (s0_e2m3_b_ncnt)
    );

    // Unpacked A & B FP6 E3M2 streams
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_e3m2_a_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_e3m2_b_unp;
    logic [LANES-1:0][5:0]           s0_e3m2_a_raw6;
    logic [LANES-1:0][5:0]           s0_e3m2_b_raw6;
    logic [LANES-1:0][2:0]           s0_e3m2_a_rexp;
    logic [LANES-1:0][2:0]           s0_e3m2_b_rexp;
    logic [LANES-1:0][1:0]           s0_e3m2_a_rman;
    logic [LANES-1:0][1:0]           s0_e3m2_b_rman;
    logic [LANES-1:0][2:0]           s0_e3m2_a_sig;
    logic [LANES-1:0][2:0]           s0_e3m2_b_sig;
    logic [LANES-1:0][2:0]           s0_e3m2_a_nsig;
    logic [LANES-1:0][2:0]           s0_e3m2_b_nsig;
    logic [LANES-1:0][1:0]           s0_e3m2_a_lzc;
    logic [LANES-1:0][1:0]           s0_e3m2_b_lzc;
    logic [LANES-1:0]                s0_e3m2_a_pz;
    logic [LANES-1:0]                s0_e3m2_b_pz;
    logic [LANES-1:0]                s0_e3m2_a_nz;
    logic [LANES-1:0]                s0_e3m2_b_nz;
    logic [LANES-1:0]                s0_e3m2_a_sub;
    logic [LANES-1:0]                s0_e3m2_b_sub;
    logic [LANES-1:0]                s0_e3m2_a_norm;
    logic [LANES-1:0]                s0_e3m2_b_norm;
    logic [LANES-1:0]                s0_e3m2_a_max;
    logic [LANES-1:0]                s0_e3m2_b_max;
    logic [$clog2(LANES+1)-1:0]      s0_e3m2_a_nzc;
    logic [$clog2(LANES+1)-1:0]      s0_e3m2_b_nzc;
    logic                            s0_e3m2_a_allz;
    logic                            s0_e3m2_b_allz;
    logic [LANES-1:0][2:0]           s0_e3m2_a_cls;
    logic [LANES-1:0][2:0]           s0_e3m2_b_cls;
    logic [LANES-1:0]                s0_e3m2_a_serr;
    logic [LANES-1:0]                s0_e3m2_b_serr;
    logic                            s0_e3m2_a_anyserr;
    logic                            s0_e3m2_b_anyserr;
    logic signed [EXP_W-1:0]         s0_e3m2_a_mine;
    logic signed [EXP_W-1:0]         s0_e3m2_b_mine;
    logic signed [EXP_W-1:0]         s0_e3m2_a_maxe;
    logic signed [EXP_W-1:0]         s0_e3m2_b_maxe;
    logic [3:0]                      s0_e3m2_a_hb0;
    logic [3:0]                      s0_e3m2_a_hb1;
    logic [3:0]                      s0_e3m2_a_hb2;
    logic [3:0]                      s0_e3m2_a_hb3;
    logic [3:0]                      s0_e3m2_b_hb0;
    logic [3:0]                      s0_e3m2_b_hb1;
    logic [3:0]                      s0_e3m2_b_hb2;
    logic [3:0]                      s0_e3m2_b_hb3;
    logic [LANES-1:0][31:0]          s0_e3m2_a_fp32;
    logic [LANES-1:0][31:0]          s0_e3m2_b_fp32;
    logic [LANES-1:0]                s0_e3m2_a_int;
    logic [LANES-1:0]                s0_e3m2_b_int;
    logic [3:0]                      s0_e3m2_a_pcnt;
    logic [3:0]                      s0_e3m2_a_ncnt;
    logic [3:0]                      s0_e3m2_b_pcnt;
    logic [3:0]                      s0_e3m2_b_ncnt;

    VX_tcu_v2_fp6_e3m2_unpack #(
        .LANES (LANES)
    ) u_fp6_e3m2_unpack_a (
        .data_in             (a_raw),
        .bit_packed_mode     (1'b0),
        .lane_mask           (s0_lane_mask),
        .unpacked_out        (s0_e3m2_a_unp),
        .raw_fp6_out         (s0_e3m2_a_raw6),
        .raw_exp_out         (s0_e3m2_a_rexp),
        .raw_man_out         (s0_e3m2_a_rman),
        .sig_u1p2_out        (s0_e3m2_a_sig),
        .norm_sig_u1p2_out   (s0_e3m2_a_nsig),
        .subnorm_lzc_out     (s0_e3m2_a_lzc),
        .is_pos_zero         (s0_e3m2_a_pz),
        .is_neg_zero         (s0_e3m2_a_nz),
        .is_subnormal_out    (s0_e3m2_a_sub),
        .is_normal_out       (s0_e3m2_a_norm),
        .is_max_mag          (s0_e3m2_a_max),
        .nonzero_count       (s0_e3m2_a_nzc),
        .all_lanes_zero      (s0_e3m2_a_allz),
        .class_code_out      (s0_e3m2_a_cls),
        .slot_upper_err_out  (s0_e3m2_a_serr),
        .any_slot_err_out    (s0_e3m2_a_anyserr),
        .lane_min_exp_out    (s0_e3m2_a_mine),
        .lane_max_exp_out    (s0_e3m2_a_maxe),
        .hist_zero_cnt       (s0_e3m2_a_hb0),
        .hist_subnorm_cnt    (s0_e3m2_a_hb1),
        .hist_norm_cnt       (s0_e3m2_a_hb2),
        .hist_max_cnt        (s0_e3m2_a_hb3),
        .lane_fp32_equiv_out (s0_e3m2_a_fp32),
        .is_exact_int_out    (s0_e3m2_a_int),
        .pos_lane_cnt_out    (s0_e3m2_a_pcnt),
        .neg_lane_cnt_out    (s0_e3m2_a_ncnt)
    );

    VX_tcu_v2_fp6_e3m2_unpack #(
        .LANES (LANES)
    ) u_fp6_e3m2_unpack_b (
        .data_in             (b_raw),
        .bit_packed_mode     (1'b0),
        .lane_mask           (s0_lane_mask),
        .unpacked_out        (s0_e3m2_b_unp),
        .raw_fp6_out         (s0_e3m2_b_raw6),
        .raw_exp_out         (s0_e3m2_b_rexp),
        .raw_man_out         (s0_e3m2_b_rman),
        .sig_u1p2_out        (s0_e3m2_b_sig),
        .norm_sig_u1p2_out   (s0_e3m2_b_nsig),
        .subnorm_lzc_out     (s0_e3m2_b_lzc),
        .is_pos_zero         (s0_e3m2_b_pz),
        .is_neg_zero         (s0_e3m2_b_nz),
        .is_subnormal_out    (s0_e3m2_b_sub),
        .is_normal_out       (s0_e3m2_b_norm),
        .is_max_mag          (s0_e3m2_b_max),
        .nonzero_count       (s0_e3m2_b_nzc),
        .all_lanes_zero      (s0_e3m2_b_allz),
        .class_code_out      (s0_e3m2_b_cls),
        .slot_upper_err_out  (s0_e3m2_b_serr),
        .any_slot_err_out    (s0_e3m2_b_anyserr),
        .lane_min_exp_out    (s0_e3m2_b_mine),
        .lane_max_exp_out    (s0_e3m2_b_maxe),
        .hist_zero_cnt       (s0_e3m2_b_hb0),
        .hist_subnorm_cnt    (s0_e3m2_b_hb1),
        .hist_norm_cnt       (s0_e3m2_b_hb2),
        .hist_max_cnt        (s0_e3m2_b_hb3),
        .lane_fp32_equiv_out (s0_e3m2_b_fp32),
        .is_exact_int_out    (s0_e3m2_b_int),
        .pos_lane_cnt_out    (s0_e3m2_b_pcnt),
        .neg_lane_cnt_out    (s0_e3m2_b_ncnt)
    );

    // Select active unpacked operands for A and B based on fmt_a / fmt_b
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_sel_a_unp;
    tcu_v2_fp_unpacked_t [LANES-1:0] s0_sel_b_unp;

    always_comb begin
        if (s0_a_is_e2m3) begin
            s0_sel_a_unp = s0_e2m3_a_unp;
        end else if (s0_a_is_e3m2) begin
            s0_sel_a_unp = s0_e3m2_a_unp;
        end else begin
            s0_sel_a_unp = s0_fp4_a_unp;
        end

        if (s0_b_is_e2m3) begin
            s0_sel_b_unp = s0_e2m3_b_unp;
        end else if (s0_b_is_e3m2) begin
            s0_sel_b_unp = s0_e3m2_b_unp;
        end else begin
            s0_sel_b_unp = s0_fp4_b_unp;
        end
    end

    // Microscale Decoders (A and B) + Block Align
    tcu_v2_scale_decoded_t   s0_scale_a_dec;
    tcu_v2_scale_decoded_t   s0_scale_b_dec;
    logic signed [EXP_W-1:0] s0_scale_a_ed;
    logic signed [EXP_W-1:0] s0_scale_b_ed;
    logic [3:0]              s0_scale_a_mant;
    logic [3:0]              s0_scale_b_mant;
    logic [3:0]              s0_scale_a_nmant;
    logic [3:0]              s0_scale_b_nmant;
    logic signed [EXP_W-1:0] s0_scale_a_ned;
    logic signed [EXP_W-1:0] s0_scale_b_ned;
    logic [1:0]              s0_scale_a_lzc;
    logic [1:0]              s0_scale_b_lzc;
    logic                    s0_scale_a_zero;
    logic                    s0_scale_b_zero;
    logic                    s0_scale_a_nan;
    logic                    s0_scale_b_nan;
    logic                    s0_scale_a_sub;
    logic                    s0_scale_b_sub;
    logic                    s0_scale_a_unity;
    logic                    s0_scale_b_unity;
    logic                    s0_scale_a_maxf;
    logic                    s0_scale_b_maxf;
    logic                    s0_scale_a_minp;
    logic                    s0_scale_b_minp;
    logic                    s0_scale_a_pow2;
    logic                    s0_scale_b_pow2;
    logic                    s0_scale_a_inv;
    logic                    s0_scale_b_inv;
    logic [2:0]              s0_scale_a_cls;
    logic [2:0]              s0_scale_b_cls;
    logic [31:0]             s0_scale_a_fp32;
    logic [31:0]             s0_scale_b_fp32;
    logic [31:0]             s0_scale_a_rec;
    logic [31:0]             s0_scale_b_rec;
    logic [7:0]              s0_scale_a_braw;
    logic [7:0]              s0_scale_b_braw;
    logic                    s0_scale_a_gt1;
    logic                    s0_scale_b_gt1;
    logic                    s0_scale_a_lt1;
    logic                    s0_scale_b_lt1;
    logic [7:0]              s0_scale_a_ue_flr;
    logic [7:0]              s0_scale_b_ue_flr;
    logic [7:0]              s0_scale_a_ue_ceil;
    logic [7:0]              s0_scale_b_ue_ceil;
    logic [15:0]             s0_scale_a_bf16;
    logic [15:0]             s0_scale_b_bf16;

    VX_tcu_v2_mx_scale_decode #(
        .EXP_W (EXP_W)
    ) u_scale_decode_a (
        .scale_fmt              (scale_fmt),
        .scale_raw              (scale_a_raw),
        .decoded_out            (s0_scale_a_dec),
        .exp_delta_out          (s0_scale_a_ed),
        .mant_u1p3_out          (s0_scale_a_mant),
        .norm_mant_u1p3_out     (s0_scale_a_nmant),
        .norm_exp_delta_out     (s0_scale_a_ned),
        .mant_lzc_out           (s0_scale_a_lzc),
        .is_zero_out            (s0_scale_a_zero),
        .is_nan_out             (s0_scale_a_nan),
        .is_subnormal_out       (s0_scale_a_sub),
        .is_unity_out           (s0_scale_a_unity),
        .is_max_finite_out      (s0_scale_a_maxf),
        .is_min_pos_out         (s0_scale_a_minp),
        .is_power_of_two_out    (s0_scale_a_pow2),
        .invalid_encoding_out   (s0_scale_a_inv),
        .scale_class_out        (s0_scale_a_cls),
        .scale_as_fp32_out      (s0_scale_a_fp32),
        .recip_approx_fp32_out  (s0_scale_a_rec),
        .bias_adjusted_raw_out  (s0_scale_a_braw),
        .is_gt_unity_out        (s0_scale_a_gt1),
        .is_lt_unity_out        (s0_scale_a_lt1),
        .e4m3_to_ue8m0_floor_out(s0_scale_a_ue_flr),
        .e4m3_to_ue8m0_ceil_out (s0_scale_a_ue_ceil),
        .scale_bf16_equiv_out   (s0_scale_a_bf16)
    );

    VX_tcu_v2_mx_scale_decode #(
        .EXP_W (EXP_W)
    ) u_scale_decode_b (
        .scale_fmt              (scale_fmt),
        .scale_raw              (scale_b_raw),
        .decoded_out            (s0_scale_b_dec),
        .exp_delta_out          (s0_scale_b_ed),
        .mant_u1p3_out          (s0_scale_b_mant),
        .norm_mant_u1p3_out     (s0_scale_b_nmant),
        .norm_exp_delta_out     (s0_scale_b_ned),
        .mant_lzc_out           (s0_scale_b_lzc),
        .is_zero_out            (s0_scale_b_zero),
        .is_nan_out             (s0_scale_b_nan),
        .is_subnormal_out       (s0_scale_b_sub),
        .is_unity_out           (s0_scale_b_unity),
        .is_max_finite_out      (s0_scale_b_maxf),
        .is_min_pos_out         (s0_scale_b_minp),
        .is_power_of_two_out    (s0_scale_b_pow2),
        .invalid_encoding_out   (s0_scale_b_inv),
        .scale_class_out        (s0_scale_b_cls),
        .scale_as_fp32_out      (s0_scale_b_fp32),
        .recip_approx_fp32_out  (s0_scale_b_rec),
        .bias_adjusted_raw_out  (s0_scale_b_braw),
        .is_gt_unity_out        (s0_scale_b_gt1),
        .is_lt_unity_out        (s0_scale_b_lt1),
        .e4m3_to_ue8m0_floor_out(s0_scale_b_ue_flr),
        .e4m3_to_ue8m0_ceil_out (s0_scale_b_ue_ceil),
        .scale_bf16_equiv_out   (s0_scale_b_bf16)
    );

    logic signed [EXP_W-1:0] s0_comb_scale_exp;
    logic [7:0]              s0_comb_scale_u2p6;
    logic [7:0]              s0_comb_scale_u1p7;
    logic                    s0_comb_scale_zero;
    logic                    s0_comb_scale_nan;
    logic                    s0_comb_scale_ovf;
    logic                    s0_comb_scale_unf;
    logic                    s0_comb_scale_unity;
    logic                    s0_comb_scale_pow2;
    logic [5:0]              s0_block_size;
    logic                    s0_is_k16;
    logic                    s0_is_k32;
    logic                    s0_scale_mismatch;
    logic [31:0]             s0_comb_scale_fp32;
    logic [3:0]              s0_comb_scale_lzc;
    logic                    s0_scale_a_gt_b;
    logic signed [EXP_W-1:0] s0_scale_exp_diff;
    logic [7:0]              s0_comb_ue8m0_approx;
    logic [3:0]              s0_comb_e4m3_hint;
    logic                    s0_comb_req_subnorm;
    logic [3:0]              s0_comb_e4m3_quant;
    logic [7:0]              s0_comb_e4m3_byte;
    logic                    s0_comb_scale_inexact;
    logic                    s0_comb_both_subn;
    logic                    s0_comb_any_subn;

    VX_tcu_v2_mx_block_align #(
        .EXP_W (EXP_W)
    ) u_block_align (
        .scale_a                        (s0_scale_a_dec),
        .scale_b                        (s0_scale_b_dec),
        .fmt_a                          (fmt_a),
        .fmt_b                          (fmt_b),
        .expected_scale_fmt             (scale_fmt),
        .enable_subnorm_norm            (1'b1),
        .comb_exp_out                   (s0_comb_scale_exp),
        .comb_mant_u2p6_out             (s0_comb_scale_u2p6),
        .comb_mant_norm_u1p7_out        (s0_comb_scale_u1p7),
        .comb_is_zero_out               (s0_comb_scale_zero),
        .comb_is_nan_out                (s0_comb_scale_nan),
        .comb_exp_ovf_out               (s0_comb_scale_ovf),
        .comb_exp_unf_out               (s0_comb_scale_unf),
        .comb_is_unity_out              (s0_comb_scale_unity),
        .comb_is_pow2_out               (s0_comb_scale_pow2),
        .block_size_out                 (s0_block_size),
        .is_k16_block_out               (s0_is_k16),
        .is_k32_block_out               (s0_is_k32),
        .scale_mismatch_out             (s0_scale_mismatch),
        .comb_scale_fp32_out            (s0_comb_scale_fp32),
        .mant_lzc_out                   (s0_comb_scale_lzc),
        .scale_a_gt_b_out               (s0_scale_a_gt_b),
        .scale_exp_diff_out             (s0_scale_exp_diff),
        .comb_scale_ue8m0_approx_out    (s0_comb_ue8m0_approx),
        .comb_scale_e4m3_exp_hint_out   (s0_comb_e4m3_hint),
        .comb_requires_fp32_subnorm_out (s0_comb_req_subnorm),
        .comb_scale_e4m3_quant_out      (s0_comb_e4m3_quant),
        .comb_scale_e4m3_byte_out       (s0_comb_e4m3_byte),
        .comb_scale_round_inexact_out   (s0_comb_scale_inexact),
        .comb_both_e4m3_subnorm_out     (s0_comb_both_subn),
        .comb_any_e4m3_subnorm_out      (s0_comb_any_subn)
    );

    // Unpack C FP32 accumulator operand
    tcu_v2_fp_unpacked_t s0_c_unp;
    assign s0_c_unp = tcu_v2_unpack_fp32(c_fp32);

    // -------------------------------------------------------------------------
    // Stage 0 -> Stage 1 Pipeline Registers (Unpacked Operands + Combined Scale)
    // -------------------------------------------------------------------------
    tcu_v2_fmt_e                     s1_fmt_a_q;
    tcu_v2_fmt_e                     s1_fmt_b_q;
    tcu_v2_rm_e                      s1_rm_q;
    logic                            s1_fmt_valid_q;
    logic                            s1_accum_en_q;
    tcu_v2_fp_unpacked_t [LANES-1:0] s1_fp4_a_q;
    tcu_v2_fp_unpacked_t [LANES-1:0] s1_fp4_b_q;
    tcu_v2_fp_unpacked_t [LANES-1:0] s1_sel_a_q;
    tcu_v2_fp_unpacked_t [LANES-1:0] s1_sel_b_q;
    tcu_v2_fp_unpacked_t             s1_c_unp_q;
    logic signed [EXP_W-1:0]         s1_scale_exp_q;
    logic [7:0]                      s1_scale_u1p7_q;
    logic                            s1_scale_zero_q;
    logic                            s1_scale_nan_q;
    logic                            s1_scale_ovf_q;
    logic                            s1_scale_unf_q;
    logic [7:0]                      s1_scale_a_raw_q;
    logic [7:0]                      s1_scale_b_raw_q;
    tcu_v2_scale_fmt_e               s1_scale_fmt_q;
    logic                            s1_scale_mismatch_q;
    logic [31:0]                     s1_c_fp32_raw_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            pipe_s0_valid_q     <= 1'b0;
            s1_fmt_a_q          <= TCU_V2_FMT_MXFP4_E2M1;
            s1_fmt_b_q          <= TCU_V2_FMT_MXFP4_E2M1;
            s1_rm_q             <= TCU_V2_RM_RNE;
            s1_fmt_valid_q      <= 1'b0;
            s1_accum_en_q       <= 1'b0;
            s1_fp4_a_q          <= '0;
            s1_fp4_b_q          <= '0;
            s1_sel_a_q          <= '0;
            s1_sel_b_q          <= '0;
            s1_c_unp_q          <= '0;
            s1_scale_exp_q      <= '0;
            s1_scale_u1p7_q     <= 8'd0;
            s1_scale_zero_q     <= 1'b0;
            s1_scale_nan_q      <= 1'b0;
            s1_scale_ovf_q      <= 1'b0;
            s1_scale_unf_q      <= 1'b0;
            s1_scale_a_raw_q    <= 8'd0;
            s1_scale_b_raw_q    <= 8'd0;
            s1_scale_fmt_q      <= TCU_V2_SCALE_NONE;
            s1_scale_mismatch_q <= 1'b0;
            s1_c_fp32_raw_q     <= 32'd0;
        end else if (stage0_en) begin
            pipe_s0_valid_q <= valid_in;
            if (valid_in) begin
                s1_fmt_a_q          <= fmt_a;
                s1_fmt_b_q          <= fmt_b;
                s1_rm_q             <= rm;
                s1_fmt_valid_q      <= s0_fmt_valid;
                s1_accum_en_q       <= accum_en;
                s1_fp4_a_q          <= s0_fp4_a_unp;
                s1_fp4_b_q          <= s0_fp4_b_unp;
                s1_sel_a_q          <= s0_sel_a_unp;
                s1_sel_b_q          <= s0_sel_b_unp;
                s1_c_unp_q          <= s0_c_unp;
                s1_scale_exp_q      <= s0_comb_scale_exp;
                s1_scale_u1p7_q     <= s0_comb_scale_u1p7;
                s1_scale_zero_q     <= s0_comb_scale_zero;
                s1_scale_nan_q      <= s0_comb_scale_nan;
                s1_scale_ovf_q      <= s0_comb_scale_ovf;
                s1_scale_unf_q      <= s0_comb_scale_unf;
                s1_scale_a_raw_q    <= scale_a_raw;
                s1_scale_b_raw_q    <= scale_b_raw;
                s1_scale_fmt_q      <= scale_fmt;
                s1_scale_mismatch_q <= s0_scale_mismatch;
                s1_c_fp32_raw_q     <= c_fp32;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Stage 1: FP4 & FP6 Lane Multipliers + Lane Mux/Scaling + Wide Alignment
    // -------------------------------------------------------------------------
    logic                                s1_fp4_vout;
    logic [LANES-1:0]                    s1_fp4_sign;
    logic signed [LANES-1:0][EXP_W-1:0]  s1_fp4_exp;
    logic [LANES-1:0][3:0]               s1_fp4_mant;
    logic [LANES-1:0]                    s1_fp4_zero;
    logic [LANES-1:0]                    s1_fp4_negz;
    logic [LANES-1:0]                    s1_fp4_posz;
    logic [LANES-1:0]                    s1_fp4_carry;
    logic [LANES-1:0]                    s1_fp4_subnp;
    logic [LANES-1:0]                    s1_fp4_int;
    logic [LANES-1:0][31:0]              s1_fp4_fp32;
    logic [$clog2(LANES+1)-1:0]          s1_fp4_act;
    logic signed [EXP_W-1:0]             s1_fp4_mine;
    logic signed [EXP_W-1:0]             s1_fp4_maxe;
    logic                                s1_fp4_allz;
    logic [3:0]                          s1_fp4_pcnt;
    logic [3:0]                          s1_fp4_ncnt;

    VX_tcu_v2_fp4_mul_lane #(
        .LANES    (LANES),
        .PIPE_REG (0)
    ) u_fp4_mul_lane (
        .clk                   (clk),
        .reset                 (reset),
        .enable                (stage1_en),
        .valid_in              (pipe_s0_valid_q),
        .a_in                  (s1_fp4_a_q),
        .b_in                  (s1_fp4_b_q),
        .valid_out             (s1_fp4_vout),
        .prod_sign_out         (s1_fp4_sign),
        .prod_exp_out          (s1_fp4_exp),
        .prod_mant_u1p3_out    (s1_fp4_mant),
        .prod_is_zero_out      (s1_fp4_zero),
        .prod_neg_zero_out     (s1_fp4_negz),
        .prod_pos_zero_out     (s1_fp4_posz),
        .prod_has_carry_out    (s1_fp4_carry),
        .prod_subnorm_pair_out (s1_fp4_subnp),
        .prod_is_exact_int_out (s1_fp4_int),
        .prod_fp32_equiv_out   (s1_fp4_fp32),
        .active_lanes_out      (s1_fp4_act),
        .min_prod_exp_out      (s1_fp4_mine),
        .max_prod_exp_out      (s1_fp4_maxe),
        .all_prod_zero_out     (s1_fp4_allz),
        .pos_prod_cnt_out      (s1_fp4_pcnt),
        .neg_prod_cnt_out      (s1_fp4_ncnt)
    );

    logic                                s1_fp6_vout;
    logic [LANES-1:0]                    s1_fp6_sign;
    logic signed [LANES-1:0][EXP_W-1:0]  s1_fp6_exp;
    logic [LANES-1:0][7:0]               s1_fp6_mant;
    logic [LANES-1:0]                    s1_fp6_zero;
    logic [LANES-1:0]                    s1_fp6_negz;
    logic [LANES-1:0]                    s1_fp6_posz;
    logic [LANES-1:0]                    s1_fp6_carry;
    logic [LANES-1:0]                    s1_fp6_subna;
    logic [LANES-1:0]                    s1_fp6_int;
    logic [LANES-1:0][31:0]              s1_fp6_fp32;
    logic [$clog2(LANES+1)-1:0]          s1_fp6_act;
    logic signed [EXP_W-1:0]             s1_fp6_mine;
    logic signed [EXP_W-1:0]             s1_fp6_maxe;
    logic                                s1_fp6_allz;
    logic                                s1_fp6_mixed;
    logic                                s1_fp6_e2m3;
    logic                                s1_fp6_e3m2;
    logic [3:0]                          s1_fp6_pcnt;
    logic [3:0]                          s1_fp6_ncnt;

    VX_tcu_v2_fp6_mul_lane #(
        .LANES    (LANES),
        .PIPE_REG (0)
    ) u_fp6_mul_lane (
        .clk                   (clk),
        .reset                 (reset),
        .enable                (stage1_en),
        .valid_in              (pipe_s0_valid_q),
        .fmt_a                 (s1_fmt_a_q),
        .fmt_b                 (s1_fmt_b_q),
        .a_in                  (s1_sel_a_q),
        .b_in                  (s1_sel_b_q),
        .valid_out             (s1_fp6_vout),
        .prod_sign_out         (s1_fp6_sign),
        .prod_exp_out          (s1_fp6_exp),
        .prod_mant_u1p7_out    (s1_fp6_mant),
        .prod_is_zero_out      (s1_fp6_zero),
        .prod_neg_zero_out     (s1_fp6_negz),
        .prod_pos_zero_out     (s1_fp6_posz),
        .prod_has_carry_out    (s1_fp6_carry),
        .prod_subnorm_any_out  (s1_fp6_subna),
        .prod_is_exact_int_out (s1_fp6_int),
        .prod_fp32_equiv_out   (s1_fp6_fp32),
        .active_lanes_out      (s1_fp6_act),
        .min_prod_exp_out      (s1_fp6_mine),
        .max_prod_exp_out      (s1_fp6_maxe),
        .all_prod_zero_out     (s1_fp6_allz),
        .is_mixed_mode_out     (s1_fp6_mixed),
        .is_e2m3_mode_out      (s1_fp6_e2m3),
        .is_e3m2_mode_out      (s1_fp6_e3m2),
        .pos_prod_cnt_out      (s1_fp6_pcnt),
        .neg_prod_cnt_out      (s1_fp6_ncnt)
    );

    logic [LANES-1:0]                    s1_scaled_sign;
    logic signed [LANES-1:0][EXP_W-1:0]  s1_scaled_exp;
    logic [LANES-1:0][SIG_W-1:0]         s1_scaled_sig;
    logic [LANES-1:0]                    s1_scaled_zero;
    logic [LANES-1:0]                    s1_scaled_negz;
    logic [LANES-1:0]                    s1_scaled_nan;
    logic [LANES-1:0]                    s1_scaled_inf;
    logic [LANES-1:0]                    s1_scaled_uf;
    logic [LANES-1:0]                    s1_scaled_of;
    logic [LANES-1:0]                    s1_scaled_subn;
    logic [LANES-1:0][31:0]              s1_scaled_fp32;
    logic [LANES-1:0]                    s1_scaled_exint;
    logic [LANES-1:0][15:0]              s1_scaled_u2p14;
    logic                                s1_any_lane_nan;
    logic                                s1_any_lane_inf;
    logic                                s1_any_lane_uf;
    logic                                s1_any_lane_of;
    logic                                s1_all_lanes_zero;
    logic                                s1_all_lanes_negz;
    logic                                s1_use_fp6_path;
    logic                                s1_illegal_fmt;
    logic [$clog2(LANES+1)-1:0]          s1_active_scaled;
    logic signed [EXP_W-1:0]             s1_min_scaled_exp;
    logic signed [EXP_W-1:0]             s1_max_scaled_exp;
    logic [3:0]                          s1_scaled_pcnt;
    logic [3:0]                          s1_scaled_ncnt;
    logic signed [EXP_W-1:0]             s1_scaled_exp_span;

    VX_tcu_v2_mx_lane_select #(
        .LANES (LANES),
        .SIG_W (SIG_W),
        .EXP_W (EXP_W)
    ) u_lane_select (
        .fmt_a                     (s1_fmt_a_q),
        .fmt_b                     (s1_fmt_b_q),
        .lane_enable_mask          ({LANES{1'b1}}),
        .fp4_sign_in               (s1_fp4_sign),
        .fp4_exp_in                (s1_fp4_exp),
        .fp4_mant_u1p3_in          (s1_fp4_mant),
        .fp4_zero_in               (s1_fp4_zero),
        .fp4_neg_zero_in           (s1_fp4_negz),
        .fp6_sign_in               (s1_fp6_sign),
        .fp6_exp_in                (s1_fp6_exp),
        .fp6_mant_u1p7_in          (s1_fp6_mant),
        .fp6_zero_in               (s1_fp6_zero),
        .fp6_neg_zero_in           (s1_fp6_negz),
        .scale_comb_exp_in         (s1_scale_exp_q),
        .scale_comb_mant_u1p7_in   (s1_scale_u1p7_q),
        .scale_comb_is_zero_in     (s1_scale_zero_q),
        .scale_comb_is_nan_in      (s1_scale_nan_q),
        .scale_comb_exp_ovf_in     (s1_scale_ovf_q),
        .scale_comb_exp_unf_in     (s1_scale_unf_q),
        .lane_sign_out             (s1_scaled_sign),
        .lane_exp_out              (s1_scaled_exp),
        .lane_sig_u1p23_out        (s1_scaled_sig),
        .lane_is_zero_out          (s1_scaled_zero),
        .lane_is_neg_zero_out      (s1_scaled_negz),
        .lane_is_nan_out           (s1_scaled_nan),
        .lane_is_inf_out           (s1_scaled_inf),
        .lane_underflow_out        (s1_scaled_uf),
        .lane_overflow_out         (s1_scaled_of),
        .lane_subnormal_fp32_out   (s1_scaled_subn),
        .lane_fp32_equiv_out       (s1_scaled_fp32),
        .lane_scaled_exact_int_out (s1_scaled_exint),
        .lane_scaled_raw_u2p14_out (s1_scaled_u2p14),
        .any_lane_nan_out          (s1_any_lane_nan),
        .any_lane_inf_out          (s1_any_lane_inf),
        .any_lane_uf_out           (s1_any_lane_uf),
        .any_lane_of_out           (s1_any_lane_of),
        .all_lanes_zero_out        (s1_all_lanes_zero),
        .all_lanes_neg_zero_out    (s1_all_lanes_negz),
        .use_fp6_path_out          (s1_use_fp6_path),
        .illegal_fmt_combo_out     (s1_illegal_fmt),
        .active_scaled_lanes_out   (s1_active_scaled),
        .min_scaled_exp_out        (s1_min_scaled_exp),
        .max_scaled_exp_out        (s1_max_scaled_exp),
        .pos_scaled_cnt_out        (s1_scaled_pcnt),
        .neg_scaled_cnt_out        (s1_scaled_ncnt),
        .scaled_exp_span_out       (s1_scaled_exp_span)
    );

    logic signed [EXP_W-1:0]       s1_align_max_exp;
    logic [LANES:0][ACC_W-1:0]     s1_aligned_terms;
    logic [LANES:0]                s1_sticky_vec;
    logic                          s1_align_all_zero;
    logic [LANES:0][SH_W-1:0]      s1_shift_dbg;
    logic [LANES:0]                s1_overshift_vec;
    logic [LANES:0]                s1_exact_align_vec;
    logic [$clog2(LANES+2)-1:0]    s1_active_term_cnt;
    logic                          s1_c_dominates;
    logic                          s1_any_prod_dom;
    logic signed [EXP_W-1:0]       s1_min_act_exp;
    logic signed [EXP_W-1:0]       s1_exp_spread;
    logic [LANES:0]                s1_term_negated;
    logic [LANES:0]                s1_tiny_subulp;
    logic [3:0]                    s1_win_idx;
    logic signed [EXP_W-1:0]       s1_c_norm_exp;
    logic [SIG_W-1:0]              s1_c_norm_sig;
    logic [LANES:0]                s1_prod_exact_al;
    logic                          s1_align_pos_sticky;
    logic                          s1_align_neg_sticky;
    logic signed [EXP_W-1:0]       s1_lane_max_exp;
    logic [LANES-1:0][ACC_W-1:0]   s1_lane_aligned_terms;
    logic                          s1_lanes_all_zero_al;
    logic                          s1_c_eff_zero_al;
    logic                          s1_c_eff_sign_al;

    VX_tcu_v2_mx_fedp_align #(
        .LANES (LANES),
        .EXP_W (EXP_W),
        .SIG_W (SIG_W),
        .ACC_W (ACC_W)
    ) u_fedp_align (
        .lane_sign_in            (s1_scaled_sign),
        .lane_exp_in             (s1_scaled_exp),
        .lane_sig_in             (s1_scaled_sig),
        .lane_is_zero_in         (s1_scaled_zero),
        .c_sign_in               (s1_c_unp_q.sign),
        .c_exp_in                (s1_c_unp_q.exp),
        .c_sig_in                (s1_c_unp_q.sig),
        .c_is_zero_in            (s1_c_unp_q.is_zero),
        .c_is_subnormal_in       (s1_c_unp_q.is_subnormal),
        .accum_en                (s1_accum_en_q),
        .max_exp_out             (s1_align_max_exp),
        .aligned_terms_out       (s1_aligned_terms),
        .sticky_vec_out          (s1_sticky_vec),
        .all_terms_zero_out      (s1_align_all_zero),
        .shift_dist_dbg_out      (s1_shift_dbg),
        .overshift_vec_out       (s1_overshift_vec),
        .exact_align_vec_out     (s1_exact_align_vec),
        .active_term_count_out   (s1_active_term_cnt),
        .c_dominates_out         (s1_c_dominates),
        .any_prod_dominates_out  (s1_any_prod_dom),
        .min_active_exp_out      (s1_min_act_exp),
        .exp_spread_out          (s1_exp_spread),
        .term_negated_out        (s1_term_negated),
        .tiny_subulp_sticky_out  (s1_tiny_subulp),
        .max_exp_winner_idx_out  (s1_win_idx),
        .c_norm_exp_out          (s1_c_norm_exp),
        .c_norm_sig_out          (s1_c_norm_sig),
        .prod_exact_aligned_out  (s1_prod_exact_al),
        .pos_sticky_out          (s1_align_pos_sticky),
        .neg_sticky_out          (s1_align_neg_sticky),
        .lane_max_exp_out        (s1_lane_max_exp),
        .lane_aligned_terms_out  (s1_lane_aligned_terms),
        .lanes_all_zero_out      (s1_lanes_all_zero_al),
        .c_eff_zero_out          (s1_c_eff_zero_al),
        .c_eff_sign_out          (s1_c_eff_sign_al)
    );

    // Stage 1 special-case exception pre-computation (NaN, Inf, Signed Zero)
    logic s1_c_is_nan;
    logic s1_c_is_snan;
    logic s1_c_is_inf;
    logic s1_c_is_zero;
    logic s1_c_sign;
    logic s1_any_lane_negz;
    logic s1_spec_is_nan;
    logic s1_spec_is_inf;
    logic s1_spec_inf_sign;
    logic s1_spec_invalid_op;
    logic s1_spec_zero_sign;

    assign s1_c_is_nan     = s1_accum_en_q && s1_c_unp_q.is_nan;
    assign s1_c_is_snan    = s1_c_is_nan && !s1_c_unp_q.sig[22];
    assign s1_c_is_inf     = s1_accum_en_q && s1_c_unp_q.is_inf;
    assign s1_c_is_zero    = (!s1_accum_en_q) || s1_c_unp_q.is_zero;
    assign s1_c_sign       = s1_accum_en_q ? s1_c_unp_q.sign : 1'b0;
    assign s1_any_lane_negz = |(s1_scaled_zero & s1_scaled_negz);

    always_comb begin
        s1_spec_invalid_op = (!s1_fmt_valid_q) || s1_illegal_fmt || s1_c_is_snan ||
                             (s1_any_lane_inf && s1_c_is_inf && (s1_scaled_sign[0] != s1_c_sign));
        s1_spec_is_nan     = s1_scale_nan_q || s1_any_lane_nan || s1_c_is_nan || s1_spec_invalid_op;
        s1_spec_is_inf     = (!s1_spec_is_nan) && (s1_c_is_inf || s1_any_lane_inf);
        s1_spec_inf_sign   = s1_c_is_inf ? s1_c_sign : s1_scaled_sign[0];

        if (s1_all_lanes_zero && s1_c_is_zero) begin
            if (s1_accum_en_q) begin
                s1_spec_zero_sign = (s1_rm_q == TCU_V2_RM_RDN) ?
                                    (s1_any_lane_negz || s1_c_sign) :
                                    (s1_all_lanes_negz && s1_c_sign);
            end else begin
                s1_spec_zero_sign = (s1_rm_q == TCU_V2_RM_RDN) ?
                                    s1_any_lane_negz :
                                    s1_all_lanes_negz;
            end
        end else begin
            s1_spec_zero_sign = (s1_rm_q == TCU_V2_RM_RDN);
        end
    end

    // -------------------------------------------------------------------------
    // Stage 1 -> Stage 2 Pipeline Registers (Aligned Terms + Exception Metadata)
    // -------------------------------------------------------------------------
    tcu_v2_rm_e                  s2_rm_q;
    logic [LANES:0][ACC_W-1:0]   s2_aligned_terms_q;
    logic [LANES:0]              s2_sticky_vec_q;
    logic [LANES:0]              s2_term_sign_q;
    logic [LANES-1:0][ACC_W-1:0] s2_lane_terms_q;
    logic signed [EXP_W-1:0]     s2_lane_max_exp_q;
    logic                        s2_lanes_all_zero_q;
    logic                        s2_c_eff_zero_q;
    logic                        s2_c_eff_sign_q;
    logic signed [EXP_W-1:0]     s2_c_norm_exp_q;
    logic [SIG_W-1:0]            s2_c_norm_sig_q;
    logic signed [EXP_W-1:0]     s2_max_exp_q;
    logic                        s2_align_all_zero_q;
    logic                        s2_spec_is_nan_q;
    logic                        s2_spec_is_inf_q;
    logic                        s2_spec_inf_sign_q;
    logic                        s2_spec_invalid_op_q;
    logic                        s2_spec_zero_sign_q;
    logic                        s2_c_bypass_zero_q;
    logic [31:0]                 s2_c_fp32_raw_q;
    logic                        s2_all_lanes_zero_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            pipe_s1_valid_q      <= 1'b0;
            s2_rm_q              <= TCU_V2_RM_RNE;
            s2_aligned_terms_q   <= '0;
            s2_sticky_vec_q      <= '0;
            s2_term_sign_q       <= '0;
            s2_lane_terms_q      <= '0;
            s2_lane_max_exp_q    <= '0;
            s2_lanes_all_zero_q  <= 1'b1;
            s2_c_eff_zero_q      <= 1'b1;
            s2_c_eff_sign_q      <= 1'b0;
            s2_c_norm_exp_q      <= '0;
            s2_c_norm_sig_q      <= '0;
            s2_max_exp_q         <= '0;
            s2_align_all_zero_q  <= 1'b1;
            s2_spec_is_nan_q     <= 1'b0;
            s2_spec_is_inf_q     <= 1'b0;
            s2_spec_inf_sign_q   <= 1'b0;
            s2_spec_invalid_op_q <= 1'b0;
            s2_spec_zero_sign_q  <= 1'b0;
            s2_c_bypass_zero_q   <= 1'b0;
            s2_c_fp32_raw_q      <= 32'd0;
            s2_all_lanes_zero_q  <= 1'b1;
        end else if (stage1_en) begin
            pipe_s1_valid_q <= pipe_s0_valid_q;
            if (pipe_s0_valid_q) begin
                s2_rm_q              <= s1_rm_q;
                s2_aligned_terms_q   <= s1_aligned_terms;
                s2_sticky_vec_q      <= s1_sticky_vec;
                s2_term_sign_q       <= {s1_c_sign, s1_scaled_sign};
                s2_lane_terms_q      <= s1_lane_aligned_terms;
                s2_lane_max_exp_q    <= s1_lane_max_exp;
                s2_lanes_all_zero_q  <= s1_lanes_all_zero_al;
                s2_c_eff_zero_q      <= s1_c_eff_zero_al;
                s2_c_eff_sign_q      <= s1_c_eff_sign_al;
                s2_c_norm_exp_q      <= s1_c_norm_exp;
                s2_c_norm_sig_q      <= s1_c_norm_sig;
                s2_max_exp_q         <= s1_align_max_exp;
                s2_align_all_zero_q  <= s1_align_all_zero;
                s2_spec_is_nan_q     <= s1_spec_is_nan;
                s2_spec_is_inf_q     <= s1_spec_is_inf;
                s2_spec_inf_sign_q   <= s1_spec_inf_sign;
                s2_spec_invalid_op_q <= s1_spec_invalid_op;
                s2_spec_zero_sign_q  <= s1_spec_zero_sign;
                s2_c_bypass_zero_q   <= s1_all_lanes_zero && s1_accum_en_q && !s1_c_is_zero && !s1_spec_is_nan && !s1_spec_is_inf;
                s2_c_fp32_raw_q      <= s1_c_fp32_raw_q;
                s2_all_lanes_zero_q  <= s1_all_lanes_zero;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Stage 2: CSA Tree Reduction -> LZA Normalization -> FP32 Rounding
    // -------------------------------------------------------------------------
    logic [ACC_W-1:0] s2_csa_sum_vec;
    logic [ACC_W-1:0] s2_csa_carry_vec;
    logic [ACC_W-1:0] s2_csa_signed_sum;
    logic [ACC_W-1:0] s2_csa_mag;
    logic             s2_csa_sign;
    logic             s2_csa_is_zero;
    logic                    s2_csa_sticky;
    logic                    s2_csa_pos_sticky;
    logic                    s2_csa_neg_sticky;
    logic                    s2_csa_sticky_sign;
    logic                    s2_csa_exact_cancel;
    logic                    s2_csa_pos_present;
    logic                    s2_csa_neg_present;
    logic [3:0]              s2_csa_nz_cnt;
    logic                    s2_csa_ovf_guard;
    logic [ACC_W-1:0]        s2_csa_pos_psum;
    logic [ACC_W-1:0]        s2_csa_neg_psum;
    logic                    s2_csa_stk_par;
    logic [3:0]              s2_csa_stk_cnt;
    logic [ACC_W-1:0]        s2_csa_prod_sum;
    logic                    s2_csa_prod_sgn;
    logic                    s2_csa_prod_zero;
    logic                    s2_csa_c_flip;
    logic signed [EXP_W-1:0] s2_csa_eff_max_exp;

    VX_tcu_v2_mx_csa_tree #(
        .LANES (LANES),
        .ACC_W (ACC_W),
        .EXP_W (EXP_W),
        .SIG_W (SIG_W)
    ) u_csa_tree (
        .terms_in               (s2_aligned_terms_q),
        .sticky_in              (s2_sticky_vec_q),
        .term_sign_in           (s2_term_sign_q),
        .lane_terms_in          (s2_lane_terms_q),
        .lane_max_exp_in        (s2_lane_max_exp_q),
        .lanes_all_zero_in      (s2_lanes_all_zero_q),
        .c_eff_zero_in          (s2_c_eff_zero_q),
        .c_eff_sign_in          (s2_c_eff_sign_q),
        .c_norm_exp_in          (s2_c_norm_exp_q),
        .c_norm_sig_in          (s2_c_norm_sig_q),
        .sum_vec_out            (s2_csa_sum_vec),
        .carry_vec_out          (s2_csa_carry_vec),
        .signed_sum_out         (s2_csa_signed_sum),
        .mag_out                (s2_csa_mag),
        .sign_out               (s2_csa_sign),
        .is_zero_out            (s2_csa_is_zero),
        .sticky_out             (s2_csa_sticky),
        .pos_sticky_out         (s2_csa_pos_sticky),
        .neg_sticky_out         (s2_csa_neg_sticky),
        .sticky_sign_out        (s2_csa_sticky_sign),
        .exact_cancel_out       (s2_csa_exact_cancel),
        .pos_terms_present_out  (s2_csa_pos_present),
        .neg_terms_present_out  (s2_csa_neg_present),
        .nonzero_terms_cnt_out  (s2_csa_nz_cnt),
        .sum_overflow_guard_out (s2_csa_ovf_guard),
        .pos_partial_sum_out    (s2_csa_pos_psum),
        .neg_partial_sum_out    (s2_csa_neg_psum),
        .sticky_parity_out      (s2_csa_stk_par),
        .sticky_count_out       (s2_csa_stk_cnt),
        .prod_only_sum_out      (s2_csa_prod_sum),
        .prod_only_sign_out     (s2_csa_prod_sgn),
        .prod_only_zero_out     (s2_csa_prod_zero),
        .c_flipped_sign_out     (s2_csa_c_flip),
        .eff_max_exp_out        (s2_csa_eff_max_exp)
    );

    logic [23:0]             s2_norm_sig;
    logic signed [EXP_W-1:0] s2_norm_exp;
    logic                    s2_norm_g;
    logic                    s2_norm_r;
    logic                    s2_norm_s;
    logic                    s2_norm_sign;
    logic                    s2_norm_zero;
    logic                    s2_norm_subnorm;
    logic                    s2_norm_ovf_pre;
    logic                    s2_norm_tiny_flush;
    logic                    s2_norm_msb_ok;
    logic [LZC_W-1:0]        s2_norm_lzc;
    logic [5:0]              s2_norm_sub_shamt;
    logic                    s2_norm_carry_gr;
    logic                    s2_norm_cancel_sh;
    logic [5:0]              s2_norm_eff_shamt;
    logic [5:0]              s2_norm_tzc;
    logic                    s2_norm_pow2;
    logic                    s2_norm_rwin_nz;
    logic                    s2_norm_sub_bdr;

    VX_tcu_v2_mx_lza_norm #(
        .ACC_W (ACC_W),
        .EXP_W (EXP_W)
    ) u_lza_norm (
        .mag_in                   (s2_csa_mag),
        .sign_in                  (s2_csa_sign),
        .max_exp_in               (s2_csa_eff_max_exp),
        .sticky_in                (s2_csa_sticky),
        .pos_sticky_in            (s2_csa_pos_sticky),
        .neg_sticky_in            (s2_csa_neg_sticky),
        .all_zero_in              (s2_align_all_zero_q || s2_csa_is_zero),
        .norm_sig_u1p23_out       (s2_norm_sig),
        .norm_exp_out             (s2_norm_exp),
        .guard_bit_out            (s2_norm_g),
        .round_bit_out            (s2_norm_r),
        .sticky_bit_out           (s2_norm_s),
        .norm_sign_out            (s2_norm_sign),
        .is_zero_out              (s2_norm_zero),
        .is_subnormal_out         (s2_norm_subnorm),
        .is_overflow_pre_out      (s2_norm_ovf_pre),
        .is_tiny_flush_out        (s2_norm_tiny_flush),
        .norm_msb_ok_out          (s2_norm_msb_ok),
        .lzc_out                  (s2_norm_lzc),
        .subnorm_shamt_out        (s2_norm_sub_shamt),
        .had_carry_growth_out     (s2_norm_carry_gr),
        .had_cancel_shift_out     (s2_norm_cancel_sh),
        .effective_shift_mag_out  (s2_norm_eff_shamt),
        .trailing_zero_cnt_out    (s2_norm_tzc),
        .is_exact_pow2_mag_out    (s2_norm_pow2),
        .norm_round_window_nz_out (s2_norm_rwin_nz),
        .subnorm_border_out       (s2_norm_sub_bdr)
    );

    logic                    s2_eff_zero_sign;
    logic [31:0]             s2_rounded_fp32;
    tcu_v2_fp_flags_t        s2_rounded_flags;
    logic                    s2_rnd_up;
    logic                    s2_rnd_carry;
    logic                    s2_rnd_sub_promo;
    logic                    s2_res_nan;
    logic                    s2_res_inf;
    logic                    s2_res_zero;
    logic                    s2_res_subnorm;
    logic                    s2_tie_half;
    logic                    s2_tie_even;
    logic                    s2_ovf_clamp;
    logic [7:0]              s2_final_bexp;
    logic [22:0]             s2_final_man;
    logic [15:0]             s2_fp16_down;
    logic [15:0]             s2_bf16_down;
    logic                    s2_ulp_lsb;
    logic                    s2_sub_tiny;
    logic                    s2_exact_norm;

    assign s2_eff_zero_sign = s2_align_all_zero_q ? s2_spec_zero_sign_q :
                              (s2_csa_exact_cancel ? (s2_rm_q == TCU_V2_RM_RDN) : s2_norm_sign);

    VX_tcu_v2_mx_fp32_round #(
        .EXP_W (EXP_W)
    ) u_fp32_round (
        .rm                     (s2_rm_q),
        .sign_in                (s2_norm_sign),
        .norm_exp_in            (s2_norm_exp),
        .norm_sig_u1p23_in      (s2_norm_sig),
        .guard_in               (s2_norm_g),
        .round_in               (s2_norm_r),
        .sticky_in              (s2_norm_s),
        .is_zero_in             (s2_norm_zero),
        .is_subnormal_in        (s2_norm_subnorm),
        .is_nan_in              (s2_spec_is_nan_q),
        .is_inf_in              (s2_spec_is_inf_q),
        .inf_sign_in            (s2_spec_inf_sign_q),
        .zero_sign_in           (s2_eff_zero_sign),
        .invalid_op_in          (s2_spec_invalid_op_q),
        .pre_uf_in              (s2_norm_tiny_flush),
        .pre_of_in              (s2_norm_ovf_pre),
        .fp32_out               (s2_rounded_fp32),
        .flags_out              (s2_rounded_flags),
        .rounded_up_out         (s2_rnd_up),
        .carry_realign_out      (s2_rnd_carry),
        .subnorm_promoted_out   (s2_rnd_sub_promo),
        .result_is_nan_out      (s2_res_nan),
        .result_is_inf_out      (s2_res_inf),
        .result_is_zero_out     (s2_res_zero),
        .result_is_subnorm_out  (s2_res_subnorm),
        .tie_exact_half_out     (s2_tie_half),
        .tie_broken_even_out    (s2_tie_even),
        .ovf_clamped_max_out    (s2_ovf_clamp),
        .final_biased_exp_out   (s2_final_bexp),
        .final_mantissa_out     (s2_final_man),
        .fp16_downcast_out      (s2_fp16_down),
        .bf16_downcast_out      (s2_bf16_down),
        .ulp_parity_lsb_out     (s2_ulp_lsb),
        .subnormal_tininess_out (s2_sub_tiny),
        .exact_normal_out       (s2_exact_norm)
    );

    // -------------------------------------------------------------------------
    // Stage 2 -> Output Registered Boundary (with exact C passthrough on 0*scale)
    // -------------------------------------------------------------------------
    logic [31:0]      s2_final_d_fp32;
    tcu_v2_fp_flags_t s2_final_flags;

    always_comb begin
        if (s2_c_bypass_zero_q) begin
            s2_final_d_fp32 = s2_c_fp32_raw_q;
            s2_final_flags  = '0;
        end else begin
            s2_final_d_fp32 = s2_rounded_fp32;
            s2_final_flags  = s2_rounded_flags;
        end
    end

    logic [31:0]      d_fp32_q;
    tcu_v2_fp_flags_t flags_out_q;
    logic [31:0]      perf_valid_ops_q;
    logic [31:0]      perf_zero_skips_q;
    logic [31:0]      perf_stall_cycles_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            pipe_s2_valid_q     <= 1'b0;
            d_fp32_q            <= 32'd0;
            flags_out_q         <= '0;
            perf_valid_ops_q    <= 32'd0;
            perf_zero_skips_q   <= 32'd0;
            perf_stall_cycles_q <= 32'd0;
        end else begin
            if (stall_out) begin
                perf_stall_cycles_q <= perf_stall_cycles_q + 32'd1;
            end
            if (stage2_en) begin
                pipe_s2_valid_q <= pipe_s1_valid_q;
                if (pipe_s1_valid_q) begin
                    d_fp32_q         <= s2_final_d_fp32;
                    flags_out_q      <= s2_final_flags;
                    perf_valid_ops_q <= perf_valid_ops_q + 32'd1;
                    if (s2_all_lanes_zero_q) begin
                        perf_zero_skips_q <= perf_zero_skips_q + 32'd1;
                    end
                end
            end
        end
    end

    assign valid_out = pipe_s2_valid_q;
    assign d_fp32    = d_fp32_q;
    assign flags_out = flags_out_q;

    `UNUSED_VAR (s0_fp4_a_nib)
    `UNUSED_VAR (s0_fp4_b_nib)
    `UNUSED_VAR (s0_fp4_a_rexp)
    `UNUSED_VAR (s0_fp4_b_rexp)
    `UNUSED_VAR (s0_fp4_a_rman)
    `UNUSED_VAR (s0_fp4_b_rman)
    `UNUSED_VAR (s0_fp4_a_nsig)
    `UNUSED_VAR (s0_fp4_b_nsig)
    `UNUSED_VAR (s0_fp4_a_pz)
    `UNUSED_VAR (s0_fp4_b_pz)
    `UNUSED_VAR (s0_fp4_a_nz)
    `UNUSED_VAR (s0_fp4_b_nz)
    `UNUSED_VAR (s0_fp4_a_max)
    `UNUSED_VAR (s0_fp4_b_max)
    `UNUSED_VAR (s0_fp4_a_sub)
    `UNUSED_VAR (s0_fp4_b_sub)
    `UNUSED_VAR (s0_fp4_a_norm)
    `UNUSED_VAR (s0_fp4_b_norm)
    `UNUSED_VAR (s0_fp4_a_anyz)
    `UNUSED_VAR (s0_fp4_b_anyz)
    `UNUSED_VAR (s0_fp4_a_nzc)
    `UNUSED_VAR (s0_fp4_b_nzc)
    `UNUSED_VAR (s0_fp4_a_allz)
    `UNUSED_VAR (s0_fp4_b_allz)
    `UNUSED_VAR (s0_fp4_a_nv)
    `UNUSED_VAR (s0_fp4_b_nv)
    `UNUSED_VAR (s0_fp4_a_cls)
    `UNUSED_VAR (s0_fp4_b_cls)
    `UNUSED_VAR (s0_fp4_a_half)
    `UNUSED_VAR (s0_fp4_b_half)
    `UNUSED_VAR (s0_fp4_a_one)
    `UNUSED_VAR (s0_fp4_b_one)
    `UNUSED_VAR (s0_fp4_a_int)
    `UNUSED_VAR (s0_fp4_b_int)
    `UNUSED_VAR (s0_fp4_a_mine)
    `UNUSED_VAR (s0_fp4_b_mine)
    `UNUSED_VAR (s0_fp4_a_maxe)
    `UNUSED_VAR (s0_fp4_b_maxe)
    `UNUSED_VAR (s0_fp4_a_pzero)
    `UNUSED_VAR (s0_fp4_b_pzero)
    `UNUSED_VAR (s0_fp4_a_psign)
    `UNUSED_VAR (s0_fp4_b_psign)
    `UNUSED_VAR (s0_fp4_a_hb0)
    `UNUSED_VAR (s0_fp4_a_hb1)
    `UNUSED_VAR (s0_fp4_a_hb2)
    `UNUSED_VAR (s0_fp4_a_hb3)
    `UNUSED_VAR (s0_fp4_b_hb0)
    `UNUSED_VAR (s0_fp4_b_hb1)
    `UNUSED_VAR (s0_fp4_b_hb2)
    `UNUSED_VAR (s0_fp4_b_hb3)
    `UNUSED_VAR (s0_fp4_a_fp32)
    `UNUSED_VAR (s0_fp4_b_fp32)
    `UNUSED_VAR (s0_fp4_a_q84)
    `UNUSED_VAR (s0_fp4_b_q84)
    `UNUSED_VAR (s0_fp4_a_pcnt)
    `UNUSED_VAR (s0_fp4_a_ncnt)
    `UNUSED_VAR (s0_fp4_b_pcnt)
    `UNUSED_VAR (s0_fp4_b_ncnt)
    `UNUSED_VAR (s0_e2m3_a_raw6)
    `UNUSED_VAR (s0_e2m3_b_raw6)
    `UNUSED_VAR (s0_e2m3_a_rexp)
    `UNUSED_VAR (s0_e2m3_b_rexp)
    `UNUSED_VAR (s0_e2m3_a_rman)
    `UNUSED_VAR (s0_e2m3_b_rman)
    `UNUSED_VAR (s0_e2m3_a_sig)
    `UNUSED_VAR (s0_e2m3_b_sig)
    `UNUSED_VAR (s0_e2m3_a_lzc)
    `UNUSED_VAR (s0_e2m3_b_lzc)
    `UNUSED_VAR (s0_e2m3_a_pz)
    `UNUSED_VAR (s0_e2m3_b_pz)
    `UNUSED_VAR (s0_e2m3_a_nz)
    `UNUSED_VAR (s0_e2m3_b_nz)
    `UNUSED_VAR (s0_e2m3_a_sub)
    `UNUSED_VAR (s0_e2m3_b_sub)
    `UNUSED_VAR (s0_e2m3_a_norm)
    `UNUSED_VAR (s0_e2m3_b_norm)
    `UNUSED_VAR (s0_e2m3_a_max)
    `UNUSED_VAR (s0_e2m3_b_max)
    `UNUSED_VAR (s0_e2m3_a_nzc)
    `UNUSED_VAR (s0_e2m3_b_nzc)
    `UNUSED_VAR (s0_e2m3_a_allz)
    `UNUSED_VAR (s0_e2m3_b_allz)
    `UNUSED_VAR (s0_e2m3_a_cls)
    `UNUSED_VAR (s0_e2m3_b_cls)
    `UNUSED_VAR (s0_e2m3_a_serr)
    `UNUSED_VAR (s0_e2m3_b_serr)
    `UNUSED_VAR (s0_e2m3_a_anyserr)
    `UNUSED_VAR (s0_e2m3_b_anyserr)
    `UNUSED_VAR (s0_e2m3_a_mine)
    `UNUSED_VAR (s0_e2m3_b_mine)
    `UNUSED_VAR (s0_e2m3_a_maxe)
    `UNUSED_VAR (s0_e2m3_b_maxe)
    `UNUSED_VAR (s0_e2m3_a_hb0)
    `UNUSED_VAR (s0_e2m3_a_hb1)
    `UNUSED_VAR (s0_e2m3_a_hb2)
    `UNUSED_VAR (s0_e2m3_a_hb3)
    `UNUSED_VAR (s0_e2m3_b_hb0)
    `UNUSED_VAR (s0_e2m3_b_hb1)
    `UNUSED_VAR (s0_e2m3_b_hb2)
    `UNUSED_VAR (s0_e2m3_b_hb3)
    `UNUSED_VAR (s0_e2m3_a_nsig)
    `UNUSED_VAR (s0_e2m3_b_nsig)
    `UNUSED_VAR (s0_e2m3_a_fp32)
    `UNUSED_VAR (s0_e2m3_b_fp32)
    `UNUSED_VAR (s0_e2m3_a_int)
    `UNUSED_VAR (s0_e2m3_b_int)
    `UNUSED_VAR (s0_e2m3_a_pcnt)
    `UNUSED_VAR (s0_e2m3_a_ncnt)
    `UNUSED_VAR (s0_e2m3_b_pcnt)
    `UNUSED_VAR (s0_e2m3_b_ncnt)
    `UNUSED_VAR (s0_e3m2_a_raw6)
    `UNUSED_VAR (s0_e3m2_b_raw6)
    `UNUSED_VAR (s0_e3m2_a_rexp)
    `UNUSED_VAR (s0_e3m2_b_rexp)
    `UNUSED_VAR (s0_e3m2_a_rman)
    `UNUSED_VAR (s0_e3m2_b_rman)
    `UNUSED_VAR (s0_e3m2_a_sig)
    `UNUSED_VAR (s0_e3m2_b_sig)
    `UNUSED_VAR (s0_e3m2_a_nsig)
    `UNUSED_VAR (s0_e3m2_b_nsig)
    `UNUSED_VAR (s0_e3m2_a_lzc)
    `UNUSED_VAR (s0_e3m2_b_lzc)
    `UNUSED_VAR (s0_e3m2_a_pz)
    `UNUSED_VAR (s0_e3m2_b_pz)
    `UNUSED_VAR (s0_e3m2_a_nz)
    `UNUSED_VAR (s0_e3m2_b_nz)
    `UNUSED_VAR (s0_e3m2_a_sub)
    `UNUSED_VAR (s0_e3m2_b_sub)
    `UNUSED_VAR (s0_e3m2_a_norm)
    `UNUSED_VAR (s0_e3m2_b_norm)
    `UNUSED_VAR (s0_e3m2_a_max)
    `UNUSED_VAR (s0_e3m2_b_max)
    `UNUSED_VAR (s0_e3m2_a_nzc)
    `UNUSED_VAR (s0_e3m2_b_nzc)
    `UNUSED_VAR (s0_e3m2_a_allz)
    `UNUSED_VAR (s0_e3m2_b_allz)
    `UNUSED_VAR (s0_e3m2_a_cls)
    `UNUSED_VAR (s0_e3m2_b_cls)
    `UNUSED_VAR (s0_e3m2_a_serr)
    `UNUSED_VAR (s0_e3m2_b_serr)
    `UNUSED_VAR (s0_e3m2_a_anyserr)
    `UNUSED_VAR (s0_e3m2_b_anyserr)
    `UNUSED_VAR (s0_e3m2_a_mine)
    `UNUSED_VAR (s0_e3m2_b_mine)
    `UNUSED_VAR (s0_e3m2_a_maxe)
    `UNUSED_VAR (s0_e3m2_b_maxe)
    `UNUSED_VAR (s0_e3m2_a_hb0)
    `UNUSED_VAR (s0_e3m2_a_hb1)
    `UNUSED_VAR (s0_e3m2_a_hb2)
    `UNUSED_VAR (s0_e3m2_a_hb3)
    `UNUSED_VAR (s0_e3m2_b_hb0)
    `UNUSED_VAR (s0_e3m2_b_hb1)
    `UNUSED_VAR (s0_e3m2_b_hb2)
    `UNUSED_VAR (s0_e3m2_b_hb3)
    `UNUSED_VAR (s0_e3m2_a_fp32)
    `UNUSED_VAR (s0_e3m2_b_fp32)
    `UNUSED_VAR (s0_e3m2_a_int)
    `UNUSED_VAR (s0_e3m2_b_int)
    `UNUSED_VAR (s0_e3m2_a_pcnt)
    `UNUSED_VAR (s0_e3m2_a_ncnt)
    `UNUSED_VAR (s0_e3m2_b_pcnt)
    `UNUSED_VAR (s0_e3m2_b_ncnt)
    `UNUSED_VAR (s0_scale_a_ed)
    `UNUSED_VAR (s0_scale_b_ed)
    `UNUSED_VAR (s0_scale_a_mant)
    `UNUSED_VAR (s0_scale_b_mant)
    `UNUSED_VAR (s0_scale_a_nmant)
    `UNUSED_VAR (s0_scale_b_nmant)
    `UNUSED_VAR (s0_scale_a_ned)
    `UNUSED_VAR (s0_scale_b_ned)
    `UNUSED_VAR (s0_scale_a_lzc)
    `UNUSED_VAR (s0_scale_b_lzc)
    `UNUSED_VAR (s0_scale_a_zero)
    `UNUSED_VAR (s0_scale_b_zero)
    `UNUSED_VAR (s0_scale_a_nan)
    `UNUSED_VAR (s0_scale_b_nan)
    `UNUSED_VAR (s0_scale_a_sub)
    `UNUSED_VAR (s0_scale_b_sub)
    `UNUSED_VAR (s0_scale_a_unity)
    `UNUSED_VAR (s0_scale_b_unity)
    `UNUSED_VAR (s0_scale_a_maxf)
    `UNUSED_VAR (s0_scale_b_maxf)
    `UNUSED_VAR (s0_scale_a_minp)
    `UNUSED_VAR (s0_scale_b_minp)
    `UNUSED_VAR (s0_scale_a_pow2)
    `UNUSED_VAR (s0_scale_b_pow2)
    `UNUSED_VAR (s0_scale_a_inv)
    `UNUSED_VAR (s0_scale_b_inv)
    `UNUSED_VAR (s0_scale_a_cls)
    `UNUSED_VAR (s0_scale_b_cls)
    `UNUSED_VAR (s0_scale_a_fp32)
    `UNUSED_VAR (s0_scale_b_fp32)
    `UNUSED_VAR (s0_scale_a_rec)
    `UNUSED_VAR (s0_scale_b_rec)
    `UNUSED_VAR (s0_scale_a_braw)
    `UNUSED_VAR (s0_scale_b_braw)
    `UNUSED_VAR (s0_scale_a_gt1)
    `UNUSED_VAR (s0_scale_b_gt1)
    `UNUSED_VAR (s0_scale_a_lt1)
    `UNUSED_VAR (s0_scale_b_lt1)
    `UNUSED_VAR (s0_scale_a_ue_flr)
    `UNUSED_VAR (s0_scale_b_ue_flr)
    `UNUSED_VAR (s0_scale_a_ue_ceil)
    `UNUSED_VAR (s0_scale_b_ue_ceil)
    `UNUSED_VAR (s0_scale_a_bf16)
    `UNUSED_VAR (s0_scale_b_bf16)
    `UNUSED_VAR (s0_comb_scale_u2p6)
    `UNUSED_VAR (s0_comb_scale_unity)
    `UNUSED_VAR (s0_comb_scale_pow2)
    `UNUSED_VAR (s0_block_size)
    `UNUSED_VAR (s0_is_k16)
    `UNUSED_VAR (s0_is_k32)
    `UNUSED_VAR (s0_scale_mismatch)
    `UNUSED_VAR (s0_comb_scale_fp32)
    `UNUSED_VAR (s0_comb_scale_lzc)
    `UNUSED_VAR (s0_scale_a_gt_b)
    `UNUSED_VAR (s0_scale_exp_diff)
    `UNUSED_VAR (s0_comb_ue8m0_approx)
    `UNUSED_VAR (s0_comb_e4m3_hint)
    `UNUSED_VAR (s0_comb_req_subnorm)
    `UNUSED_VAR (s0_comb_e4m3_quant)
    `UNUSED_VAR (s0_comb_e4m3_byte)
    `UNUSED_VAR (s0_comb_scale_inexact)
    `UNUSED_VAR (s0_comb_both_subn)
    `UNUSED_VAR (s0_comb_any_subn)
    `UNUSED_VAR (s1_scale_a_raw_q)
    `UNUSED_VAR (s1_scale_b_raw_q)
    `UNUSED_VAR (s1_scale_fmt_q)
    `UNUSED_VAR (s1_scale_mismatch_q)
    `UNUSED_VAR (s1_fp4_vout)
    `UNUSED_VAR (s1_fp4_posz)
    `UNUSED_VAR (s1_fp4_carry)
    `UNUSED_VAR (s1_fp4_subnp)
    `UNUSED_VAR (s1_fp4_int)
    `UNUSED_VAR (s1_fp4_fp32)
    `UNUSED_VAR (s1_fp4_act)
    `UNUSED_VAR (s1_fp4_mine)
    `UNUSED_VAR (s1_fp4_maxe)
    `UNUSED_VAR (s1_fp4_allz)
    `UNUSED_VAR (s1_fp4_pcnt)
    `UNUSED_VAR (s1_fp4_ncnt)
    `UNUSED_VAR (s1_fp6_vout)
    `UNUSED_VAR (s1_fp6_posz)
    `UNUSED_VAR (s1_fp6_carry)
    `UNUSED_VAR (s1_fp6_subna)
    `UNUSED_VAR (s1_fp6_int)
    `UNUSED_VAR (s1_fp6_fp32)
    `UNUSED_VAR (s1_fp6_act)
    `UNUSED_VAR (s1_fp6_mine)
    `UNUSED_VAR (s1_fp6_maxe)
    `UNUSED_VAR (s1_fp6_allz)
    `UNUSED_VAR (s1_fp6_mixed)
    `UNUSED_VAR (s1_fp6_e2m3)
    `UNUSED_VAR (s1_fp6_e3m2)
    `UNUSED_VAR (s1_fp6_pcnt)
    `UNUSED_VAR (s1_fp6_ncnt)
    `UNUSED_VAR (s1_scaled_nan)
    `UNUSED_VAR (s1_scaled_inf)
    `UNUSED_VAR (s1_scaled_uf)
    `UNUSED_VAR (s1_scaled_of)
    `UNUSED_VAR (s1_scaled_subn)
    `UNUSED_VAR (s1_scaled_fp32)
    `UNUSED_VAR (s1_scaled_exint)
    `UNUSED_VAR (s1_scaled_u2p14)
    `UNUSED_VAR (s1_any_lane_uf)
    `UNUSED_VAR (s1_any_lane_of)
    `UNUSED_VAR (s1_use_fp6_path)
    `UNUSED_VAR (s1_active_scaled)
    `UNUSED_VAR (s1_min_scaled_exp)
    `UNUSED_VAR (s1_max_scaled_exp)
    `UNUSED_VAR (s1_scaled_pcnt)
    `UNUSED_VAR (s1_scaled_ncnt)
    `UNUSED_VAR (s1_scaled_exp_span)
    `UNUSED_VAR (s1_shift_dbg)
    `UNUSED_VAR (s1_overshift_vec)
    `UNUSED_VAR (s1_exact_align_vec)
    `UNUSED_VAR (s1_active_term_cnt)
    `UNUSED_VAR (s1_c_dominates)
    `UNUSED_VAR (s1_any_prod_dom)
    `UNUSED_VAR (s1_min_act_exp)
    `UNUSED_VAR (s1_exp_spread)
    `UNUSED_VAR (s1_term_negated)
    `UNUSED_VAR (s1_tiny_subulp)
    `UNUSED_VAR (s1_win_idx)
    `UNUSED_VAR (s1_prod_exact_al)
    `UNUSED_VAR (s1_align_pos_sticky)
    `UNUSED_VAR (s1_align_neg_sticky)
    `UNUSED_VAR (s2_max_exp_q)
    `UNUSED_VAR (s2_csa_sum_vec)
    `UNUSED_VAR (s2_csa_carry_vec)
    `UNUSED_VAR (s2_csa_signed_sum)
    `UNUSED_VAR (s2_csa_sticky_sign)
    `UNUSED_VAR (s2_csa_pos_present)
    `UNUSED_VAR (s2_csa_neg_present)
    `UNUSED_VAR (s2_csa_nz_cnt)
    `UNUSED_VAR (s2_csa_ovf_guard)
    `UNUSED_VAR (s2_csa_pos_psum)
    `UNUSED_VAR (s2_csa_neg_psum)
    `UNUSED_VAR (s2_csa_stk_par)
    `UNUSED_VAR (s2_csa_stk_cnt)
    `UNUSED_VAR (s2_csa_prod_sum)
    `UNUSED_VAR (s2_csa_prod_sgn)
    `UNUSED_VAR (s2_csa_prod_zero)
    `UNUSED_VAR (s2_csa_c_flip)
    `UNUSED_VAR (s2_norm_msb_ok)
    `UNUSED_VAR (s2_norm_lzc)
    `UNUSED_VAR (s2_norm_sub_shamt)
    `UNUSED_VAR (s2_norm_carry_gr)
    `UNUSED_VAR (s2_norm_cancel_sh)
    `UNUSED_VAR (s2_norm_eff_shamt)
    `UNUSED_VAR (s2_norm_tzc)
    `UNUSED_VAR (s2_norm_pow2)
    `UNUSED_VAR (s2_norm_rwin_nz)
    `UNUSED_VAR (s2_norm_sub_bdr)
    `UNUSED_VAR (s2_rnd_up)
    `UNUSED_VAR (s2_rnd_carry)
    `UNUSED_VAR (s2_rnd_sub_promo)
    `UNUSED_VAR (s2_res_nan)
    `UNUSED_VAR (s2_res_inf)
    `UNUSED_VAR (s2_res_zero)
    `UNUSED_VAR (s2_res_subnorm)
    `UNUSED_VAR (s2_tie_half)
    `UNUSED_VAR (s2_tie_even)
    `UNUSED_VAR (s2_ovf_clamp)
    `UNUSED_VAR (s2_final_bexp)
    `UNUSED_VAR (s2_final_man)
    `UNUSED_VAR (s2_fp16_down)
    `UNUSED_VAR (s2_bf16_down)
    `UNUSED_VAR (s2_ulp_lsb)
    `UNUSED_VAR (s2_sub_tiny)
    `UNUSED_VAR (s2_exact_norm)
    `UNUSED_VAR (perf_valid_ops_q)
    `UNUSED_VAR (perf_zero_skips_q)
    `UNUSED_VAR (perf_stall_cycles_q)

    `STATIC_ASSERT(LANES >= 1, ("VX_tcu_v2_fp4_fp6_fedp_unit requires LANES >= 1"))

endmodule
