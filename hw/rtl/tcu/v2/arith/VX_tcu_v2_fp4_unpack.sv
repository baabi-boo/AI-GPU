// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_fp4_unpack import VX_tcu_v2_pkg::*; #(
    parameter int LANES = TCU_V2_MAX_LANES
) (
    input  logic [LANES*8-1:0]                       data_in,
    input  logic                                     packed_nibble_mode,
    input  logic                                     use_upper_nibble,
    input  logic                                     is_nvfp4,
    input  logic [LANES-1:0]                         lane_mask,
    output tcu_v2_fp_unpacked_t [LANES-1:0]          unpacked_out,
    output logic [LANES-1:0][3:0]                    raw_nibble_out,
    output logic [LANES-1:0][1:0]                    raw_exp_out,
    output logic [LANES-1:0]                         raw_man_out,
    output logic [LANES-1:0][1:0]                    norm_sig_out,
    output logic [LANES-1:0]                         is_pos_zero,
    output logic [LANES-1:0]                         is_neg_zero,
    output logic [LANES-1:0]                         is_max_mag,
    output logic [LANES-1:0]                         is_subnormal_out,
    output logic [LANES-1:0]                         is_normal_out,
    output logic [LANES-1:0]                         any_zero_vec,
    output logic [$clog2(LANES+1)-1:0]               nonzero_count,
    output logic                                     all_lanes_zero,
    output logic                                     fmt_is_nvfp4_out,
    output logic [LANES-1:0][2:0]                    class_code_out,
    output logic [LANES-1:0]                         is_half_mag_out,
    output logic [LANES-1:0]                         is_one_mag_out,
    output logic [LANES-1:0]                         is_integer_val_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        lane_min_exp_out,
    output logic signed [TCU_V2_FP_EXP_W-1:0]        lane_max_exp_out,
    output logic [LANES-1:0]                         pair_both_zero_out,
    output logic [LANES-1:0]                         pair_sign_match_out,
    output logic [3:0]                               hist_bin_zero_cnt,
    output logic [3:0]                               hist_bin_sub_cnt,
    output logic [3:0]                               hist_bin_norm_cnt,
    output logic [3:0]                               hist_bin_sat_cnt,
    output logic [LANES-1:0][31:0]                   lane_fp32_equiv_out,
    output logic [LANES-1:0][7:0]                    lane_q8_4_fixed_out,
    output logic [3:0]                               pos_lane_cnt_out,
    output logic [3:0]                               neg_lane_cnt_out
);

    localparam int FP4_BIAS        = 1;
    localparam int FP4_EXP_W       = 2;
    localparam int FP4_MAN_W       = 1;
    localparam int EXP_EXT_W       = TCU_V2_FP_EXP_W;
    localparam int SIG_EXT_W       = TCU_V2_FP_SIG_W;
    localparam int PAIR_COUNT      = (LANES + 1) / 2;

    localparam logic [2:0] CLS_POS_ZERO = 3'd0;
    localparam logic [2:0] CLS_NEG_ZERO = 3'd1;
    localparam logic [2:0] CLS_SUBNORM  = 3'd2;
    localparam logic [2:0] CLS_NORM_LO  = 3'd3;
    localparam logic [2:0] CLS_NORM_MID = 3'd4;
    localparam logic [2:0] CLS_NORM_MAX = 3'd5;

    function automatic logic [3:0] decode_nibble_from_slot(
        input logic [7:0] slot_byte,
        input logic       upper_sel
    );
        if (upper_sel) begin
            return slot_byte[7:4];
        end else begin
            return slot_byte[3:0];
        end
    endfunction

    function automatic logic [2:0] classify_fp4_nibble(
        input logic       masked_en,
        input logic       sign_b,
        input logic [1:0] exp_b,
        input logic       man_b
    );
        if (!masked_en || ((exp_b == 2'b00) && (man_b == 1'b0))) begin
            return sign_b && masked_en ? CLS_NEG_ZERO : CLS_POS_ZERO;
        end else if (exp_b == 2'b00) begin
            return CLS_SUBNORM;
        end else if (exp_b == 2'b01) begin
            return CLS_NORM_LO;
        end else if (exp_b == 2'b10) begin
            return CLS_NORM_MID;
        end else if (man_b == 1'b1) begin
            return CLS_NORM_MAX;
        end else begin
            return CLS_NORM_MID;
        end
    endfunction

    function automatic logic is_fp4_exact_integer(
        input logic       active_en,
        input logic [1:0] exp_b,
        input logic       man_b
    );
        if (!active_en) begin
            return 1'b1;
        end else if (exp_b == 2'b00) begin
            return (man_b == 1'b0);
        end else if (exp_b == 2'b01) begin
            return (man_b == 1'b0);
        end else if (exp_b == 2'b10) begin
            return 1'b1;
        end else begin
            return 1'b1;
        end
    endfunction

    function automatic logic [31:0] fp4_nibble_to_fp32(
        input logic       active_en,
        input logic [3:0] nib
    );
        logic       s;
        logic [1:0] e;
        logic       m;
        logic [7:0] fp32_e;
        logic [22:0] fp32_m;
        s = nib[3];
        e = nib[2:1];
        m = nib[0];
        if (!active_en) begin
            return TCU_V2_FP32_POS_ZERO;
        end else if ((e == 2'b00) && (m == 1'b0)) begin
            return {s, 31'd0};
        end else if (e == 2'b00) begin
            // +/-0.5 -> biased exp 126, mantissa 0
            return {s, 8'd126, 23'd0};
        end else begin
            fp32_e = 8'd127 + ({6'd0, e} - 8'd1);
            fp32_m = {m, 22'd0};
            return {s, fp32_e, fp32_m};
        end
    endfunction

    // Convert E2M1 value into signed Q4.4 fixed-point (exact for all 16 FP4 encodings, max +/-6.0).
    function automatic logic [7:0] fp4_to_signed_q4_4(
        input logic       active_en,
        input logic [3:0] nib
    );
        logic       s;
        logic [1:0] e;
        logic       m;
        logic [7:0] mag;
        s = nib[3];
        e = nib[2:1];
        m = nib[0];
        if (!active_en || ((e == 2'b00) && (m == 1'b0))) begin
            return 8'd0;
        end else if (e == 2'b00) begin
            mag = 8'd8; // 0.5 * 16 = 8
        end else if (e == 2'b01) begin
            mag = m ? 8'd24 : 8'd16; // 1.5 or 1.0
        end else if (e == 2'b10) begin
            mag = m ? 8'd48 : 8'd32; // 3.0 or 2.0
        end else begin
            mag = m ? 8'd96 : 8'd64; // 6.0 or 4.0
        end
        return s ? ((~mag) + 8'd1) : mag;
    endfunction

    logic [PAIR_COUNT-1:0][7:0]         packed_bytes;
    logic [LANES-1:0][3:0]              selected_nibbles;
    logic [LANES-1:0]                   lane_nz;
    logic signed [LANES-1:0][EXP_EXT_W-1:0] lane_norm_exps;

    assign fmt_is_nvfp4_out = is_nvfp4;

    for (genvar p = 0; p < PAIR_COUNT; ++p) begin : g_pair_extract
        assign packed_bytes[p] = data_in[p*8 +: 8];
    end

    for (genvar i = 0; i < LANES; ++i) begin : g_fp4_lanes
        logic [7:0] lane_byte;
        logic [3:0] nibble_slot;
        logic [3:0] nibble_packed;
        logic [3:0] eff_nibble;

        logic       sign_bit;
        logic [1:0] exp_field;
        logic       man_field;

        logic       field_exp_zero;
        logic       field_man_zero;
        logic       lane_is_zero;
        logic       lane_is_subnorm;
        logic       lane_is_normal;
        logic       lane_is_max;

        logic signed [EXP_EXT_W-1:0] unbiased_exp;
        logic signed [EXP_EXT_W-1:0] norm_eff_exp;
        logic [SIG_EXT_W-1:0]        aligned_sig;
        logic [1:0]                  compact_sig;
        logic [2:0]                  cls_code;
        logic                        is_half_val;
        logic                        is_one_val;
        logic                        is_int_val;

        tcu_v2_fp_unpacked_t         lane_pkg;

        assign lane_byte   = data_in[i*8 +: 8];
        assign nibble_slot = decode_nibble_from_slot(lane_byte, use_upper_nibble);

        if ((i / 2) < PAIR_COUNT) begin : g_pair_sel
            if ((i % 2) == 0) begin : g_even_nibble
                assign nibble_packed = packed_bytes[i/2][3:0];
            end else begin : g_odd_nibble
                assign nibble_packed = packed_bytes[i/2][7:4];
            end
        end else begin : g_pair_zero
            assign nibble_packed = 4'b0000;
        end

        always_comb begin
            if (!lane_mask[i]) begin
                eff_nibble = 4'b0000;
            end else if (packed_nibble_mode) begin
                eff_nibble = nibble_packed;
            end else begin
                eff_nibble = nibble_slot;
            end
        end

        assign sign_bit  = eff_nibble[3];
        assign exp_field = eff_nibble[2:1];
        assign man_field = eff_nibble[0];

        assign field_exp_zero = (exp_field == 2'b00);
        assign field_man_zero = (man_field == 1'b0);

        assign lane_is_zero    = (!lane_mask[i]) || (field_exp_zero && field_man_zero);
        assign lane_is_subnorm = lane_mask[i] && field_exp_zero && !field_man_zero;
        assign lane_is_normal  = lane_mask[i] && !field_exp_zero;
        assign lane_is_max     = lane_mask[i] && (exp_field == 2'b11) && (man_field == 1'b1);

        assign is_half_val = lane_is_subnorm;
        assign is_one_val  = lane_mask[i] && (exp_field == 2'b01) && (man_field == 1'b0);
        assign is_int_val  = is_fp4_exact_integer(lane_mask[i], exp_field, man_field);
        assign cls_code    = classify_fp4_nibble(lane_mask[i], sign_bit, exp_field, man_field);

        // E2M1 unbiased exponent mapping:
        // exp_field == 00, man == 1 -> value +/-0.5 (0.1 * 2^(1-1) = 1.0 * 2^-1)
        // exp_field == 01..11       -> value (-1)^S * (1.M) * 2^(exp - 1)
        always_comb begin
            if (lane_is_zero) begin
                unbiased_exp = '0;
                norm_eff_exp = '0;
                aligned_sig  = '0;
                compact_sig  = 2'b00;
            end else if (lane_is_subnorm) begin
                unbiased_exp = $signed(EXP_EXT_W'(1 - FP4_BIAS));
                norm_eff_exp = $signed(EXP_EXT_W'(-1));
                aligned_sig  = {1'b0, man_field, {(SIG_EXT_W-2){1'b0}}};
                compact_sig  = {1'b0, man_field};
            end else begin
                unbiased_exp = $signed({{(EXP_EXT_W-FP4_EXP_W){1'b0}}, exp_field})
                             - $signed(EXP_EXT_W'(FP4_BIAS));
                norm_eff_exp = unbiased_exp;
                aligned_sig  = {1'b1, man_field, {(SIG_EXT_W-2){1'b0}}};
                compact_sig  = {1'b1, man_field};
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

        assign selected_nibbles[i]    = eff_nibble;
        assign unpacked_out[i]        = lane_pkg;
        assign raw_nibble_out[i]      = eff_nibble;
        assign raw_exp_out[i]         = exp_field;
        assign raw_man_out[i]         = man_field;
        assign norm_sig_out[i]        = compact_sig;
        assign is_pos_zero[i]         = lane_is_zero && !lane_pkg.sign;
        assign is_neg_zero[i]         = lane_is_zero && lane_pkg.sign;
        assign is_max_mag[i]          = lane_is_max;
        assign is_subnormal_out[i]    = lane_is_subnorm;
        assign is_normal_out[i]       = lane_is_normal;
        assign any_zero_vec[i]        = lane_is_zero;
        assign lane_nz[i]             = !lane_is_zero;
        assign class_code_out[i]      = cls_code;
        assign is_half_mag_out[i]     = is_half_val;
        assign is_one_mag_out[i]      = is_one_val;
        assign is_integer_val_out[i]  = is_int_val;
        assign lane_norm_exps[i]      = norm_eff_exp;
        assign lane_fp32_equiv_out[i] = fp4_nibble_to_fp32(lane_mask[i], eff_nibble);
        assign lane_q8_4_fixed_out[i] = fp4_to_signed_q4_4(lane_mask[i], eff_nibble);
    end

    // Track paired lane sign agreement and joint-zero sparsity across adjacent elements.
    for (genvar j = 0; j < LANES; ++j) begin : g_pair_diag
        if ((j % 2) == 0 && (j + 1 < LANES)) begin : g_even_pair
            assign pair_both_zero_out[j]  = any_zero_vec[j] && any_zero_vec[j+1];
            assign pair_sign_match_out[j] = (selected_nibbles[j][3] == selected_nibbles[j+1][3]);
        end else if ((j % 2) == 1) begin : g_odd_pair
            assign pair_both_zero_out[j]  = any_zero_vec[j-1] && any_zero_vec[j];
            assign pair_sign_match_out[j] = (selected_nibbles[j-1][3] == selected_nibbles[j][3]);
        end else begin : g_tail_pair
            assign pair_both_zero_out[j]  = any_zero_vec[j];
            assign pair_sign_match_out[j] = 1'b1;
        end
    end

    // Compute active non-zero count, sign polarity counts, histogram bins, and min/max dynamic range exponents.
    always_comb begin
        logic [$clog2(LANES+1)-1:0] cnt_acc;
        logic [3:0]                 bin_zero;
        logic [3:0]                 bin_sub;
        logic [3:0]                 bin_norm;
        logic [3:0]                 bin_sat;
        logic [3:0]                 pos_cnt;
        logic [3:0]                 neg_cnt;
        logic signed [EXP_EXT_W-1:0] min_e;
        logic signed [EXP_EXT_W-1:0] max_e;
        logic                       seen_nz;

        cnt_acc  = '0;
        bin_zero = 4'd0;
        bin_sub  = 4'd0;
        bin_norm = 4'd0;
        bin_sat  = 4'd0;
        pos_cnt  = 4'd0;
        neg_cnt  = 4'd0;
        min_e    = $signed(EXP_EXT_W'(127));
        max_e    = $signed(EXP_EXT_W'(-128));
        seen_nz  = 1'b0;

        for (int k = 0; k < LANES; ++k) begin
            if (lane_nz[k]) begin
                cnt_acc = cnt_acc + {{($clog2(LANES+1)-1){1'b0}}, 1'b1};
                if (selected_nibbles[k][3]) begin
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
                    bin_sub = bin_sub + 4'd1;
                end else if (is_max_mag[k]) begin
                    bin_sat = bin_sat + 4'd1;
                end else begin
                    bin_norm = bin_norm + 4'd1;
                end
            end else begin
                bin_zero = bin_zero + 4'd1;
            end
        end

        nonzero_count     = cnt_acc;
        all_lanes_zero    = !seen_nz;
        lane_min_exp_out  = seen_nz ? min_e : '0;
        lane_max_exp_out  = seen_nz ? max_e : '0;
        hist_bin_zero_cnt = bin_zero;
        hist_bin_sub_cnt  = bin_sub;
        hist_bin_norm_cnt = bin_norm;
        hist_bin_sat_cnt  = bin_sat;
        pos_lane_cnt_out  = pos_cnt;
        neg_lane_cnt_out  = neg_cnt;
    end

    `STATIC_ASSERT((FP4_EXP_W == 2) && (FP4_MAN_W == 1) && (FP4_BIAS == 1), ("Invalid FP4 E2M1 format constants"))

endmodule
