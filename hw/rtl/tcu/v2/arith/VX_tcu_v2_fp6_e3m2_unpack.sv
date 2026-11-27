// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp6_e3m2_unpack import VX_tcu_v2_pkg::*; #(
    parameter int LANES = TCU_V2_MAX_LANES
) (
    input  logic [LANES*8-1:0]                       data_in,
    input  logic                                     bit_packed_mode,
    input  logic [LANES-1:0]                         lane_mask,
    output tcu_v2_fp_unpacked_t [LANES-1:0]          unpacked_out,
    output logic [LANES-1:0][5:0]                    raw_fp6_out,
    output logic [LANES-1:0][2:0]                    raw_exp_out,
    output logic [LANES-1:0][1:0]                    raw_man_out,
    output logic [LANES-1:0][2:0]                    sig_u1p2_out,
    output logic [LANES-1:0][2:0]                    norm_sig_u1p2_out,
    output logic [LANES-1:0][1:0]                    subnorm_lzc_out,
    output logic [LANES-1:0]                         is_pos_zero,
    output logic [LANES-1:0]                         is_neg_zero,
    output logic [LANES-1:0]                         is_subnormal_out,
    output logic [LANES-1:0]                         is_normal_out,
    output logic [LANES-1:0]                         is_max_mag,
    output logic [$clog2(LANES+1)-1:0]               nonzero_count,
    output logic                                     all_lanes_zero,
    output logic [LANES-1:0][2:0]                    class_code_out,
    output logic [LANES-1:0]                         slot_upper_err_out,
    output logic                                     any_slot_err_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        lane_min_exp_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        lane_max_exp_out,
    output logic [3:0]                               hist_zero_cnt,
    output logic [3:0]                               hist_subnorm_cnt,
    output logic [3:0]                               hist_norm_cnt,
    output logic [3:0]                               hist_max_cnt,
    output logic [LANES-1:0][31:0]                   lane_fp32_equiv_out,
    output logic [LANES-1:0]                         is_exact_int_out,
    output logic [3:0]                               pos_lane_cnt_out,
    output logic [3:0]                               neg_lane_cnt_out
);

    localparam int FP6_E3M2_BIAS = 3;
    localparam int FP6_E3M2_EXPW = 3;
    localparam int FP6_E3M2_MANW = 2;
    localparam int EXP_EXT_W     = TCU_V2_FP_EXP_W;
    localparam int SIG_EXT_W     = TCU_V2_FP_SIG_W;
    localparam int PACK_BITS_MAX = LANES * 6;

    localparam logic [2:0] E3M2_CLS_POS_ZERO = 3'd0;
    localparam logic [2:0] E3M2_CLS_NEG_ZERO = 3'd1;
    localparam logic [2:0] E3M2_CLS_SUB_TINY = 3'd2;
    localparam logic [2:0] E3M2_CLS_SUB_MID  = 3'd3;
    localparam logic [2:0] E3M2_CLS_NORM_LO  = 3'd4;
    localparam logic [2:0] E3M2_CLS_NORM_HI  = 3'd5;
    localparam logic [2:0] E3M2_CLS_NORM_MAX = 3'd6;

    function automatic logic [1:0] compute_lzc2(
        input logic [1:0] mant2
    );
        if (mant2[1]) begin
            return 2'd1;
        end else if (mant2[0]) begin
            return 2'd2;
        end else begin
            return 2'd0;
        end
    endfunction

    function automatic logic [2:0] classify_e3m2(
        input logic       active_en,
        input logic       sign_b,
        input logic [2:0] exp_b,
        input logic [1:0] man_b
    );
        if (!active_en || ((exp_b == 3'b000) && (man_b == 2'b00))) begin
            return (sign_b && active_en) ? E3M2_CLS_NEG_ZERO : E3M2_CLS_POS_ZERO;
        end else if (exp_b == 3'b000) begin
            return man_b[1] ? E3M2_CLS_SUB_MID : E3M2_CLS_SUB_TINY;
        end else if ((exp_b == 3'b111) && (man_b == 2'b11)) begin
            return E3M2_CLS_NORM_MAX;
        end else if (exp_b >= 3'b100) begin
            return E3M2_CLS_NORM_HI;
        end else begin
            return E3M2_CLS_NORM_LO;
        end
    endfunction

    function automatic logic [5:0] extract_bitpacked_6(
        input logic [PACK_BITS_MAX-1:0] stream_vec,
        input logic [$clog2(LANES)-1:0] lane_idx
    );
        return stream_vec[int'(lane_idx) * 6 +: 6];
    endfunction

    function automatic logic e3m2_is_exact_int(
        input logic       active_en,
        input logic [2:0] exp_b,
        input logic [1:0] man_b
    );
        if (!active_en || ((exp_b == 3'b000) && (man_b == 2'b00))) begin
            return 1'b1;
        end else if (exp_b < 3'd3) begin
            return 1'b0;
        end else if (exp_b == 3'd3) begin
            return (man_b == 2'b00);
        end else if (exp_b == 3'd4) begin
            return (man_b[0] == 1'b0);
        end else begin
            return 1'b1;
        end
    endfunction

    function automatic logic [31:0] e3m2_to_fp32(
        input logic       active_en,
        input logic       sign_b,
        input logic       is_zero_b,
        input logic signed [EXP_EXT_W-1:0] norm_exp_b,
        input logic [2:0] norm_sig_b
    );
        logic signed [EXP_EXT_W-1:0] fp32_e;
        if (!active_en) begin
            return TCU_V2_FP32_POS_ZERO;
        end else if (is_zero_b || !norm_sig_b[2]) begin
            return {sign_b, 31'd0};
        end else begin
            fp32_e = norm_exp_b + $signed(EXP_EXT_W'(127));
            if (fp32_e <= 0) begin
                return {sign_b, 31'd0};
            end else if (fp32_e >= 255) begin
                return sign_b ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
            end else begin
                return {sign_b, fp32_e[7:0], norm_sig_b[1:0], 21'd0};
            end
        end
    endfunction

    logic [PACK_BITS_MAX-1:0]               packed_stream;
    logic [LANES-1:0]                       lane_nz;
    logic [LANES-1:0]                       lane_signs;
    logic signed [LANES-1:0][EXP_EXT_W-1:0] lane_norm_exps;

    assign packed_stream = data_in[PACK_BITS_MAX-1:0];

    for (genvar i = 0; i < LANES; ++i) begin : g_fp6_e3m2_lanes
        logic [7:0] slot_byte;
        logic [5:0] slot_low6;
        logic [5:0] stream_bits;
        logic [5:0] eff_fp6;

        logic       sign_bit;
        logic [2:0] exp_field;
        logic [1:0] man_field;

        logic       exp_is_zero;
        logic       man_is_zero;
        logic       lane_is_zero;
        logic       lane_is_subnorm;
        logic       lane_is_normal;
        logic       lane_is_max;

        logic [2:0] raw_sig_3b;
        logic [1:0] lzc_val;
        logic [2:0] norm_sig_3b;
        logic signed [EXP_EXT_W-1:0] unbiased_exp;
        logic signed [EXP_EXT_W-1:0] norm_eff_exp;
        logic [SIG_EXT_W-1:0]        aligned_sig;
        logic [2:0]                  cls_code;

        tcu_v2_fp_unpacked_t         lane_pkg;

        assign slot_byte   = data_in[i*8 +: 8];
        assign slot_low6   = slot_byte[5:0];
        assign stream_bits = extract_bitpacked_6(packed_stream, i[$clog2(LANES)-1:0]);

        always_comb begin
            if (!lane_mask[i]) begin
                eff_fp6 = 6'b000000;
            end else if (bit_packed_mode) begin
                eff_fp6 = stream_bits;
            end else begin
                eff_fp6 = slot_low6;
            end
        end

        assign sign_bit  = eff_fp6[5];
        assign exp_field = eff_fp6[4:2];
        assign man_field = eff_fp6[1:0];

        assign exp_is_zero = (exp_field == 3'b000);
        assign man_is_zero = (man_field == 2'b00);

        assign lane_is_zero    = (!lane_mask[i]) || (exp_is_zero && man_is_zero);
        assign lane_is_subnorm = lane_mask[i] && exp_is_zero && !man_is_zero;
        assign lane_is_normal  = lane_mask[i] && !exp_is_zero;
        assign lane_is_max     = lane_mask[i] && (exp_field == 3'b111) && (man_field == 2'b11);

        assign lzc_val  = lane_is_subnorm ? compute_lzc2(man_field) : 2'd0;
        assign cls_code = classify_e3m2(lane_mask[i], sign_bit, exp_field, man_field);

        // E3M2 bias = 3:
        //   Normal:    val = (-1)^S * (1.M) * 2^(E - 3), E in {1..7} -> exp in {-2..+4}
        //   Subnormal: val = (-1)^S * (0.M) * 2^(1 - 3) = (-1)^S * (0.M) * 2^-2
        always_comb begin
            if (lane_is_zero) begin
                raw_sig_3b   = 3'b000;
                norm_sig_3b  = 3'b000;
                unbiased_exp = '0;
                norm_eff_exp = '0;
                aligned_sig  = '0;
            end else if (lane_is_subnorm) begin
                raw_sig_3b   = {1'b0, man_field};
                norm_sig_3b  = raw_sig_3b << lzc_val;
                unbiased_exp = $signed(EXP_EXT_W'(1 - FP6_E3M2_BIAS));
                norm_eff_exp = $signed(EXP_EXT_W'(1 - FP6_E3M2_BIAS))
                             - $signed({{(EXP_EXT_W-2){1'b0}}, lzc_val});
                aligned_sig  = {1'b0, man_field, {(SIG_EXT_W-3){1'b0}}};
            end else begin
                raw_sig_3b   = {1'b1, man_field};
                norm_sig_3b  = {1'b1, man_field};
                unbiased_exp = $signed({{(EXP_EXT_W-FP6_E3M2_EXPW){1'b0}}, exp_field})
                             - $signed(EXP_EXT_W'(FP6_E3M2_BIAS));
                norm_eff_exp = unbiased_exp;
                aligned_sig  = {1'b1, man_field, {(SIG_EXT_W-3){1'b0}}};
            end
        end

        always_comb begin
            lane_pkg              = '0;
            lane_pkg.sign         = lane_mask[i] ? sign_bit : 1'b0;
            lane_pkg.exp          = unbiased_exp;
            lane_pkg.sig          = aligned_sig;
            lane_pkg.is_zero      = lane_is_zero;
            lane_pkg.is_inf       = 1'b0;
            lane_pkg.is_nan       = 1'b0;
            lane_pkg.is_subnormal = lane_is_subnorm;
        end

        assign unpacked_out[i]        = lane_pkg;
        assign raw_fp6_out[i]         = eff_fp6;
        assign raw_exp_out[i]         = exp_field;
        assign raw_man_out[i]         = man_field;
        assign sig_u1p2_out[i]        = raw_sig_3b;
        assign norm_sig_u1p2_out[i]   = norm_sig_3b;
        assign subnorm_lzc_out[i]     = lzc_val;
        assign is_pos_zero[i]         = lane_is_zero && !lane_pkg.sign;
        assign is_neg_zero[i]         = lane_is_zero && lane_pkg.sign;
        assign is_subnormal_out[i]    = lane_is_subnorm;
        assign is_normal_out[i]       = lane_is_normal;
        assign is_max_mag[i]          = lane_is_max;
        assign lane_nz[i]             = !lane_is_zero;
        assign lane_signs[i]          = lane_pkg.sign;
        assign class_code_out[i]      = cls_code;
        assign lane_norm_exps[i]      = norm_eff_exp;
        assign slot_upper_err_out[i]  = !bit_packed_mode && lane_mask[i] && (|slot_byte[7:6]);
        assign is_exact_int_out[i]    = e3m2_is_exact_int(lane_mask[i], exp_field, man_field);
        assign lane_fp32_equiv_out[i] = e3m2_to_fp32(lane_mask[i], lane_pkg.sign, lane_is_zero, norm_eff_exp, norm_sig_3b);
    end

    assign any_slot_err_out = |slot_upper_err_out;

    always_comb begin
        logic [$clog2(LANES+1)-1:0] cnt_acc;
        logic [3:0]                 c_zero;
        logic [3:0]                 c_sub;
        logic [3:0]                 c_norm;
        logic [3:0]                 c_max;
        logic [3:0]                 pos_cnt;
        logic [3:0]                 neg_cnt;
        logic signed [EXP_EXT_W-1:0] min_e;
        logic signed [EXP_EXT_W-1:0] max_e;
        logic                       seen_nz;

        cnt_acc = '0;
        c_zero  = 4'd0;
        c_sub   = 4'd0;
        c_norm  = 4'd0;
        c_max   = 4'd0;
        pos_cnt = 4'd0;
        neg_cnt = 4'd0;
        min_e   = $signed(EXP_EXT_W'(127));
        max_e   = $signed(EXP_EXT_W'(-128));
        seen_nz = 1'b0;

        for (int k = 0; k < LANES; ++k) begin
            if (lane_nz[k]) begin
                cnt_acc = cnt_acc + {{($clog2(LANES+1)-1){1'b0}}, 1'b1};
                if (lane_signs[k]) begin
                    neg_cnt = neg_cnt + 4'd1;
                end else begin
                    pos_cnt = pos_cnt + 4'd1;
                end
                if (!seen_nz) begin
                    min_e   = lane_norm_exps[k];
                    max_e   = lane_norm_exps[k];
                    seen_nz = 1'b1;
                end else begin
                    if ($signed(lane_norm_exps[k]) < $signed(min_e)) begin
                        min_e = lane_norm_exps[k];
                    end
                    if ($signed(lane_norm_exps[k]) > $signed(max_e)) begin
                        max_e = lane_norm_exps[k];
                    end
                end
                if (is_subnormal_out[k]) begin
                    c_sub = c_sub + 4'd1;
                end else if (is_max_mag[k]) begin
                    c_max = c_max + 4'd1;
                end else begin
                    c_norm = c_norm + 4'd1;
                end
            end else begin
                c_zero = c_zero + 4'd1;
            end
        end

        nonzero_count    = cnt_acc;
        all_lanes_zero   = !seen_nz;
        lane_min_exp_out = seen_nz ? min_e : '0;
        lane_max_exp_out = seen_nz ? max_e : '0;
        hist_zero_cnt    = c_zero;
        hist_subnorm_cnt = c_sub;
        hist_norm_cnt    = c_norm;
        hist_max_cnt     = c_max;
        pos_lane_cnt_out = pos_cnt;
        neg_lane_cnt_out = neg_cnt;
    end

    `STATIC_ASSERT((FP6_E3M2_EXPW == 3) && (FP6_E3M2_MANW == 2) && (FP6_E3M2_BIAS == 3), ("Invalid FP6 E3M2 format constants"))

endmodule
