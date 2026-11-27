// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_int8_dot_acc #(
    parameter int   LANES   = 8,
    parameter logic OUT_REG = 1'b1
) (
    input  logic                         clk,
    input  logic                         reset,
    input  logic                         enable,
    input  logic                         valid_in,
    input  logic signed [LANES-1:0][7:0] a_int8_in,
    input  logic signed [LANES-1:0][7:0] b_int8_in,
    input  logic signed [31:0]           c_int32_in,
    input  logic                         accum_en,
    input  logic                         int_saturate,
    output logic                         valid_out,
    output logic [31:0]                  d_int32_out,
    output logic signed [35:0]           exact_sum_s36_out,
    output logic [LANES-1:0][15:0]       lane_prod_s16_out,
    output logic                         overflow_out,
    output logic                         sat_pos_out,
    output logic                         sat_neg_out,
    output logic                         zero_sum_out,
    output logic [31:0]                  abs_sum_u32_out
);
    import VX_tcu_v2_pkg::*;

    localparam int PROD_W   = 16;
    localparam int SUM_W    = 36;
    localparam int NUM_OPS  = LANES + 1;
    localparam int TREE_LVL = $clog2(NUM_OPS) + 1;
    localparam int TREE_W   = 1 << TREE_LVL;

    // -------------------------------------------------------------------------
    // Helper: 8x8 Signed Radix-4 Booth Partial-Product Multiplier (16-bit exact)
    // -------------------------------------------------------------------------
    function automatic logic signed [15:0] mul_s8_radix4_booth(
        input logic signed [7:0] op_a,
        input logic signed [7:0] op_b
    );
        logic signed [8:0]  mcand_s9;
        logic [9:0]         mplier_ext;
        logic signed [17:0] accum_s18;
        logic [2:0]         booth_grp;
        logic signed [9:0]  mcand_s10;
        logic signed [9:0]  pp_mag_s10;
        logic signed [17:0] pp_shifted_s18;
        begin
            mcand_s9   = $signed({op_a[7], op_a});
            mcand_s10  = $signed({mcand_s9[8], mcand_s9});
            mplier_ext = {op_b[7], op_b, 1'b0};
            accum_s18  = 18'sd0;
            for (int g = 0; g < 4; ++g) begin
                booth_grp = mplier_ext[2*g +: 3];
                case (booth_grp)
                    3'b001,
                    3'b010:  pp_mag_s10 = mcand_s10;
                    3'b011:  pp_mag_s10 = mcand_s10 <<< 1;
                    3'b100:  pp_mag_s10 = -(mcand_s10 <<< 1);
                    3'b101,
                    3'b110:  pp_mag_s10 = -mcand_s10;
                    default: pp_mag_s10 = 10'sd0;
                endcase
                pp_shifted_s18 = $signed({{8{pp_mag_s10[9]}}, pp_mag_s10}) <<< (2 * g);
                accum_s18      = accum_s18 + pp_shifted_s18;
            end
            return $signed(accum_s18[15:0]);
        end
    endfunction

    // -------------------------------------------------------------------------
    // Exact 8x8 Signed Multipliers and Sign-Extension to Wide 36-bit Frame
    // -------------------------------------------------------------------------
    logic signed [LANES-1:0][PROD_W-1:0]  prod_s16;
    logic [LANES-1:0][PROD_W-1:0]         comb_lane_prod_u16;
    logic signed [NUM_OPS-1:0][SUM_W-1:0] ext_terms_s36;

    for (genvar i = 0; i < LANES; ++i) begin : g_int8_mul
        logic signed [7:0]  a_elem;
        logic signed [7:0]  b_elem;

        assign a_elem                = a_int8_in[i];
        assign b_elem                = b_int8_in[i];
        assign prod_s16[i]           = mul_s8_radix4_booth(a_elem, b_elem);
        assign comb_lane_prod_u16[i] = prod_s16[i];
        assign ext_terms_s36[i]      = $signed({{(SUM_W - PROD_W){prod_s16[i][PROD_W-1]}}, prod_s16[i]});
    end

    logic signed [31:0] c_masked_s32;
    assign c_masked_s32         = accum_en ? c_int32_in : 32'sd0;
    assign ext_terms_s36[LANES] = $signed({{(SUM_W - 32){c_masked_s32[31]}}, c_masked_s32});

    // -------------------------------------------------------------------------
    // Packed 4:2 / 3:2 Carry-Save Reduction & Final Wide 36-bit Sum
    // -------------------------------------------------------------------------
    function automatic void int_csa_3to2(
        input  logic [SUM_W-1:0] x_in,
        input  logic [SUM_W-1:0] y_in,
        input  logic [SUM_W-1:0] z_in,
        output logic [SUM_W-1:0] sum_out,
        output logic [SUM_W-1:0] carry_out
    );
        logic [SUM_W-1:0] s_v;
        logic [SUM_W-2:0] c_v;
        begin
            s_v       = x_in ^ y_in ^ z_in;
            c_v       = (x_in[SUM_W-2:0] & y_in[SUM_W-2:0]) |
                        ((x_in[SUM_W-2:0] ^ y_in[SUM_W-2:0]) & z_in[SUM_W-2:0]);
            sum_out   = s_v;
            carry_out = {c_v, 1'b0};
        end
    endfunction

    function automatic void int_csa_4to2(
        input  logic [SUM_W-1:0] x_in,
        input  logic [SUM_W-1:0] y_in,
        input  logic [SUM_W-1:0] z_in,
        input  logic [SUM_W-1:0] d_in,
        output logic [SUM_W-1:0] sum_out,
        output logic [SUM_W-1:0] carry_out
    );
        logic [SUM_W-1:0] s1_v;
        logic [SUM_W-2:0] co_v;
        logic [SUM_W-1:0] ci_v;
        logic [SUM_W-1:0] s2_v;
        logic [SUM_W-2:0] cr_v;
        begin
            s1_v      = x_in ^ y_in ^ z_in;
            co_v      = (x_in[SUM_W-2:0] & y_in[SUM_W-2:0]) |
                        (y_in[SUM_W-2:0] & z_in[SUM_W-2:0]) |
                        (x_in[SUM_W-2:0] & z_in[SUM_W-2:0]);
            ci_v      = {co_v, 1'b0};
            s2_v      = s1_v ^ d_in ^ ci_v;
            cr_v      = (s1_v[SUM_W-2:0] & d_in[SUM_W-2:0]) |
                        (d_in[SUM_W-2:0] & ci_v[SUM_W-2:0]) |
                        (s1_v[SUM_W-2:0] & ci_v[SUM_W-2:0]);
            sum_out   = s2_v;
            carry_out = {cr_v, 1'b0};
        end
    endfunction

    logic [SUM_W-1:0]        csa_sum_final;
    logic [SUM_W-1:0]        csa_carry_final;
    logic signed [SUM_W-1:0] comb_exact_sum;

    if (LANES == 8) begin : g_int8_csa9
        logic [SUM_W-1:0] s1_lo;
        logic [SUM_W-1:0] c1_lo;
        logic [SUM_W-1:0] s1_hi;
        logic [SUM_W-1:0] c1_hi;
        logic [SUM_W-1:0] s2_mid;
        logic [SUM_W-1:0] c2_mid;

        always_comb begin
            int_csa_4to2(ext_terms_s36[0], ext_terms_s36[1], ext_terms_s36[2], ext_terms_s36[3], s1_lo, c1_lo);
            int_csa_4to2(ext_terms_s36[4], ext_terms_s36[5], ext_terms_s36[6], ext_terms_s36[7], s1_hi, c1_hi);
            int_csa_4to2(s1_lo, c1_lo, s1_hi, c1_hi, s2_mid, c2_mid);
            int_csa_3to2(s2_mid, c2_mid, ext_terms_s36[8], csa_sum_final, csa_carry_final);
            comb_exact_sum = $signed(csa_sum_final) + $signed(csa_carry_final);
        end
    end else begin : g_int8_tree_generic
        logic [TREE_LVL:0][TREE_W-1:0][SUM_W-1:0] sum_tree;

        for (genvar k = 0; k < TREE_W; ++k) begin : g_sum_init
            if (k < NUM_OPS) begin : g_active_op
                assign sum_tree[0][k] = ext_terms_s36[k];
            end else begin : g_pad_op
                assign sum_tree[0][k] = {SUM_W{1'b0}};
            end
        end

        for (genvar lvl = 0; lvl < TREE_LVL; ++lvl) begin : g_sum_lvl
            localparam int NODES = TREE_W >> (lvl + 1);
            for (genvar j = 0; j < NODES; ++j) begin : g_sum_node
                logic signed [SUM_W-1:0] left_val;
                logic signed [SUM_W-1:0] right_val;
                logic signed [SUM_W-1:0] node_sum;

                assign left_val          = $signed(sum_tree[lvl][2*j]);
                assign right_val         = $signed(sum_tree[lvl][2*j+1]);
                assign node_sum          = left_val + right_val;
                assign sum_tree[lvl+1][j] = node_sum;
            end
            for (genvar j = NODES; j < TREE_W; ++j) begin : g_sum_unused
                assign sum_tree[lvl+1][j] = {SUM_W{1'b0}};
            end
        end

        assign csa_sum_final   = sum_tree[TREE_LVL][0];
        assign csa_carry_final = {SUM_W{1'b0}};
        assign comb_exact_sum  = $signed(sum_tree[TREE_LVL][0]);
    end

    `UNUSED_VAR (csa_sum_final)
    `UNUSED_VAR (csa_carry_final)

    logic [3:0] comb_pos_prod_cnt;
    logic [3:0] comb_neg_prod_cnt;
    logic       comb_c_contributed;

    always_comb begin
        comb_pos_prod_cnt  = 4'd0;
        comb_neg_prod_cnt  = 4'd0;
        comb_c_contributed = accum_en && (c_int32_in != 32'sd0);
        for (int idx = 0; idx < LANES; ++idx) begin
            if (prod_s16[idx][PROD_W-1]) begin
                comb_neg_prod_cnt = comb_neg_prod_cnt + 4'd1;
            end else if (prod_s16[idx] != 16'd0) begin
                comb_pos_prod_cnt = comb_pos_prod_cnt + 4'd1;
            end
        end
    end

    `UNUSED_VAR (comb_pos_prod_cnt)
    `UNUSED_VAR (comb_neg_prod_cnt)
    `UNUSED_VAR (comb_c_contributed)

    // -------------------------------------------------------------------------
    // Signed INT32 Range Check, Overflow Detection, and Saturation / Wraparound
    // -------------------------------------------------------------------------
    logic                    comb_gt_max;
    logic                    comb_lt_min;
    logic                    comb_overflow;
    logic                    comb_zero_sum;
    logic [31:0]             comb_d_int32;
    logic [31:0]             comb_abs_u32;

    assign comb_gt_max    = (comb_exact_sum > $signed({4'b0000, TCU_V2_INT32_MAX}));
    assign comb_lt_min    = (comb_exact_sum < $signed({4'b1111, TCU_V2_INT32_MIN}));
    assign comb_overflow  = comb_gt_max || comb_lt_min;
    assign comb_zero_sum  = (comb_exact_sum == 36'sd0);

    always_comb begin
        if (int_saturate && comb_gt_max) begin
            comb_d_int32 = TCU_V2_INT32_MAX;
        end else if (int_saturate && comb_lt_min) begin
            comb_d_int32 = TCU_V2_INT32_MIN;
        end else begin
            comb_d_int32 = comb_exact_sum[31:0];
        end

        if (comb_d_int32[31]) begin
            comb_abs_u32 = (~comb_d_int32) + 32'd1;
        end else begin
            comb_abs_u32 = comb_d_int32;
        end
    end

    // -------------------------------------------------------------------------
    // Optional Pipeline Register Stage
    // -------------------------------------------------------------------------
    if (OUT_REG) begin : g_out_reg
        logic                    valid_r;
        logic [31:0]             d_int32_r;
        logic signed [35:0]      exact_sum_r;
        logic [LANES-1:0][15:0]  lane_prod_s16_r;
        logic                    overflow_r;
        logic                    sat_pos_r;
        logic                    sat_neg_r;
        logic                    zero_sum_r;
        logic [31:0]             abs_sum_u32_r;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_r         <= 1'b0;
                d_int32_r       <= 32'd0;
                exact_sum_r     <= 36'sd0;
                lane_prod_s16_r <= '0;
                overflow_r      <= 1'b0;
                sat_pos_r       <= 1'b0;
                sat_neg_r       <= 1'b0;
                zero_sum_r      <= 1'b1;
                abs_sum_u32_r   <= 32'd0;
            end else if (enable) begin
                valid_r         <= valid_in;
                d_int32_r       <= comb_d_int32;
                exact_sum_r     <= comb_exact_sum;
                lane_prod_s16_r <= comb_lane_prod_u16;
                overflow_r      <= comb_overflow;
                sat_pos_r       <= int_saturate && comb_gt_max;
                sat_neg_r       <= int_saturate && comb_lt_min;
                zero_sum_r      <= comb_zero_sum;
                abs_sum_u32_r   <= comb_abs_u32;
            end
        end

        assign valid_out         = valid_r;
        assign d_int32_out       = d_int32_r;
        assign exact_sum_s36_out = exact_sum_r;
        assign lane_prod_s16_out = lane_prod_s16_r;
        assign overflow_out      = overflow_r;
        assign sat_pos_out       = sat_pos_r;
        assign sat_neg_out       = sat_neg_r;
        assign zero_sum_out      = zero_sum_r;
        assign abs_sum_u32_out   = abs_sum_u32_r;
    end else begin : g_out_comb
        `UNUSED_VAR (clk)
        `UNUSED_VAR (reset)
        `UNUSED_VAR (enable)

        assign valid_out         = valid_in;
        assign d_int32_out       = comb_d_int32;
        assign exact_sum_s36_out = comb_exact_sum;
        assign lane_prod_s16_out = comb_lane_prod_u16;
        assign overflow_out      = comb_overflow;
        assign sat_pos_out       = int_saturate && comb_gt_max;
        assign sat_neg_out       = int_saturate && comb_lt_min;
        assign zero_sum_out      = comb_zero_sum;
        assign abs_sum_u32_out   = comb_abs_u32;
    end

endmodule
