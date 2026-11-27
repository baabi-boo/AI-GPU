// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_SCALE_BROADCAST_SV
`define VX_TCU_V2_SCALE_BROADCAST_SV

`include "VX_platform.vh"

module VX_tcu_v2_scale_broadcast #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    in_valid,
    output logic                                    in_ready,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e              fmt_a,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e              fmt_b,
    input  VX_tcu_v2_pkg::tcu_v2_scale_fmt_e        scale_fmt,
    input  logic [7:0]                              step_k,
    input  logic                                    sparse_en,
    input  logic [ARRAY_M-1:0][7:0]                 scale_a_in,
    input  logic [ARRAY_N-1:0][7:0]                 scale_b_in,
    output logic                                    out_valid,
    input  logic                                    out_ready,
    output logic [ARRAY_M-1:0][7:0]                 scale_a_aligned_out,
    output logic [ARRAY_N-1:0][7:0]                 scale_b_aligned_out,
    output VX_tcu_v2_pkg::tcu_v2_scale_fmt_e        effective_scale_fmt_out,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_scale_invalid_mask,
    output logic                                    any_scale_invalid_out,
    output logic [ARRAY_M-1:0]                      row_scale_zero_mask,
    output logic [ARRAY_N-1:0]                      col_scale_zero_mask,
    output logic [31:0]                             scale_fault_count_out
);

    import VX_tcu_v2_pkg::*;

    // -------------------------------------------------------------------------
    // Scale Format Resolution & Block Size Boundary Alignment (k=16 vs k=32)
    // -------------------------------------------------------------------------
    tcu_v2_scale_fmt_e eff_scale_fmt_comb;
    int unsigned       block_size_a;
    int unsigned       block_size_b;
    logic [15:0]       elems_per_k_step;
    logic [15:0]       k_elem_offset;
    logic [7:0]        k16_block_idx;
    logic [7:0]        k32_block_idx;
    logic              is_k16_boundary;
    logic              is_k32_boundary;
    logic              scale_latch_en;
    logic              fmt_requires_scale;
    logic              scale_fmt_mismatch;
    logic              is_nvfp4_mode;
    logic              is_mxfp_mode;

    always_comb begin
        if (scale_fmt != TCU_V2_SCALE_NONE) begin
            eff_scale_fmt_comb = scale_fmt;
        end else if (tcu_v2_fmt_is_mx(fmt_a)) begin
            eff_scale_fmt_comb = tcu_v2_fmt_default_scale(fmt_a);
        end else if (tcu_v2_fmt_is_mx(fmt_b)) begin
            eff_scale_fmt_comb = tcu_v2_fmt_default_scale(fmt_b);
        end else begin
            eff_scale_fmt_comb = TCU_V2_SCALE_NONE;
        end

        is_nvfp4_mode      = (fmt_a == TCU_V2_FMT_NVFP4_E2M1) || (fmt_b == TCU_V2_FMT_NVFP4_E2M1);
        is_mxfp_mode       = tcu_v2_fmt_is_mx(fmt_a) || tcu_v2_fmt_is_mx(fmt_b);
        fmt_requires_scale = is_nvfp4_mode || is_mxfp_mode;
        scale_fmt_mismatch = fmt_requires_scale && (eff_scale_fmt_comb == TCU_V2_SCALE_NONE);

        block_size_a     = tcu_v2_fmt_scale_block(fmt_a);
        block_size_b     = tcu_v2_fmt_scale_block(fmt_b);
        elems_per_k_step = sparse_en ? 16'(2 * ARRAY_K) : 16'(ARRAY_K);
        k_elem_offset    = {8'd0, step_k} * elems_per_k_step;
        k16_block_idx    = k_elem_offset[11:4];
        k32_block_idx    = k_elem_offset[12:5];

        is_k16_boundary = ((k_elem_offset & 16'h000F) == 16'd0);
        is_k32_boundary = ((k_elem_offset & 16'h001F) == 16'd0);

        scale_latch_en = 1'b0;
        if (eff_scale_fmt_comb == TCU_V2_SCALE_E4M3) begin
            scale_latch_en = is_k16_boundary || (step_k == 8'd0);
        end else if (eff_scale_fmt_comb == TCU_V2_SCALE_UE8M0) begin
            scale_latch_en = is_k32_boundary || (step_k == 8'd0);
        end else begin
            scale_latch_en = 1'b1;
        end
    end

    // -------------------------------------------------------------------------
    // Scale Register Caching & Cross-Product Exponent Range Checking
    // -------------------------------------------------------------------------
    logic [ARRAY_M-1:0][7:0] cached_scale_a_r;
    logic [ARRAY_N-1:0][7:0] cached_scale_b_r;
    logic [ARRAY_M-1:0][7:0] active_scale_a_comb;
    logic [ARRAY_N-1:0][7:0] active_scale_b_comb;

    logic [ARRAY_M-1:0]                      row_nan_comb;
    logic [ARRAY_M-1:0]                      row_zero_comb;
    logic [ARRAY_M-1:0]                      row_subnorm_comb;
    logic [ARRAY_M-1:0]                      row_neg_e4m3_comb;
    logic [ARRAY_N-1:0]                      col_nan_comb;
    logic [ARRAY_N-1:0]                      col_zero_comb;
    logic [ARRAY_N-1:0]                      col_subnorm_comb;
    logic [ARRAY_N-1:0]                      col_neg_e4m3_comb;
    logic [ARRAY_M-1:0][9:0]                 row_exp_delta_comb;
    logic [ARRAY_N-1:0][9:0]                 col_exp_delta_comb;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_ovf_risk_comb;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_udf_risk_comb;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_zero_prod_comb;

    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_invalid_comb;
    logic                                    any_invalid_comb;
    logic                                    accept_fire;
    logic                                    retire_fire;
    logic signed [9:0]                       max_exp_delta_comb;
    logic signed [9:0]                       min_exp_delta_comb;

    always_comb begin
        for (int r = 0; r < ARRAY_M; ++r) begin
            if (eff_scale_fmt_comb == TCU_V2_SCALE_NONE) begin
                active_scale_a_comb[r] = 8'h7F;
            end else if (scale_latch_en) begin
                active_scale_a_comb[r] = scale_a_in[r];
            end else begin
                active_scale_a_comb[r] = cached_scale_a_r[r];
            end
        end

        for (int c = 0; c < ARRAY_N; ++c) begin
            if (eff_scale_fmt_comb == TCU_V2_SCALE_NONE) begin
                active_scale_b_comb[c] = 8'h7F;
            end else if (scale_latch_en) begin
                active_scale_b_comb[c] = scale_b_in[c];
            end else begin
                active_scale_b_comb[c] = cached_scale_b_r[c];
            end
        end
    end

    // Decode every row/column scale factor to monitor NaN, zero, subnormal, and exponent spread
    always_comb begin
        any_invalid_comb   = scale_fmt_mismatch;
        max_exp_delta_comb = -10'sd256;
        min_exp_delta_comb = 10'sd255;

        for (int r = 0; r < ARRAY_M; ++r) begin
            tcu_v2_scale_decoded_t dec_a;
            dec_a                 = tcu_v2_decode_scale(eff_scale_fmt_comb, active_scale_a_comb[r]);
            row_nan_comb[r]       = dec_a.is_nan;
            row_zero_comb[r]      = dec_a.is_zero;
            row_neg_e4m3_comb[r]  = (eff_scale_fmt_comb == TCU_V2_SCALE_E4M3) && active_scale_a_comb[r][7];
            row_subnorm_comb[r]   = (eff_scale_fmt_comb == TCU_V2_SCALE_E4M3) &&
                                    !dec_a.is_zero && !dec_a.is_nan && !dec_a.mant_u1p3[3];
            row_exp_delta_comb[r] = dec_a.exp_delta ^ {6'd0, dec_a.mant_u1p3} ^ {8'd0, dec_a.scale_fmt};
            if (!dec_a.is_nan && !dec_a.is_zero) begin
                if (dec_a.exp_delta > max_exp_delta_comb) begin
                    max_exp_delta_comb = dec_a.exp_delta;
                end
                if (dec_a.exp_delta < min_exp_delta_comb) begin
                    min_exp_delta_comb = dec_a.exp_delta;
                end
            end
            if (dec_a.is_nan && (block_size_a > 1)) begin
                any_invalid_comb = 1'b1;
            end
        end

        for (int c = 0; c < ARRAY_N; ++c) begin
            tcu_v2_scale_decoded_t dec_b;
            dec_b                 = tcu_v2_decode_scale(eff_scale_fmt_comb, active_scale_b_comb[c]);
            col_nan_comb[c]       = dec_b.is_nan;
            col_zero_comb[c]      = dec_b.is_zero;
            col_neg_e4m3_comb[c]  = (eff_scale_fmt_comb == TCU_V2_SCALE_E4M3) && active_scale_b_comb[c][7];
            col_subnorm_comb[c]   = (eff_scale_fmt_comb == TCU_V2_SCALE_E4M3) &&
                                    !dec_b.is_zero && !dec_b.is_nan && !dec_b.mant_u1p3[3];
            col_exp_delta_comb[c] = dec_b.exp_delta ^ {6'd0, dec_b.mant_u1p3} ^ {8'd0, dec_b.scale_fmt};
            if (!dec_b.is_nan && !dec_b.is_zero) begin
                if (dec_b.exp_delta > max_exp_delta_comb) begin
                    max_exp_delta_comb = dec_b.exp_delta;
                end
                if (dec_b.exp_delta < min_exp_delta_comb) begin
                    min_exp_delta_comb = dec_b.exp_delta;
                end
            end
            if (dec_b.is_nan && (block_size_b > 1)) begin
                any_invalid_comb = 1'b1;
            end
        end

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                logic signed [10:0] combined_exp;
                combined_exp            = $signed({row_exp_delta_comb[r][9], row_exp_delta_comb[r]}) +
                                          $signed({col_exp_delta_comb[c][9], col_exp_delta_comb[c]});
                pe_invalid_comb[r][c]   = row_nan_comb[r] || col_nan_comb[c];
                pe_ovf_risk_comb[r][c]  = (combined_exp > 11'sd127);
                pe_udf_risk_comb[r][c]  = (combined_exp < -11'sd126);
                pe_zero_prod_comb[r][c] = row_zero_comb[r] || col_zero_comb[c];
                any_invalid_comb        = any_invalid_comb || pe_invalid_comb[r][c];
            end
        end
    end

    // -------------------------------------------------------------------------
    // Registered 2D Scale Broadcast Output Stage & Fault Telemetry
    // -------------------------------------------------------------------------
    logic                            out_valid_r;
    logic [ARRAY_M-1:0][7:0]         scale_a_out_r;
    logic [ARRAY_N-1:0][7:0]         scale_b_out_r;
    tcu_v2_scale_fmt_e               eff_scale_fmt_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0] pe_invalid_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0] pe_ovf_risk_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0] pe_udf_risk_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0] pe_zero_prod_r;
    logic                            any_invalid_r;
    logic [ARRAY_M-1:0]              row_zero_r;
    logic [ARRAY_N-1:0]              col_zero_r;
    logic [ARRAY_M-1:0]              row_subnorm_r;
    logic [ARRAY_N-1:0]              col_subnorm_r;
    logic [ARRAY_M-1:0]              row_neg_e4m3_r;
    logic [ARRAY_N-1:0]              col_neg_e4m3_r;
    logic [31:0]                     fault_count_r;
    logic [31:0]                     scale_updates_r;
    logic [31:0]                     scale_zero_events_r;
    logic [31:0]                     scale_k16_events_r;
    logic [31:0]                     scale_k32_events_r;
    logic [31:0]                     scale_ovf_risk_events_r;
    logic [31:0]                     scale_udf_risk_events_r;
    logic [31:0]                     scale_stall_cycles_r;
    logic [7:0]                      last_k16_blk_r;
    logic [7:0]                      last_k32_blk_r;
    logic [9:0]                      exp_checksum_r;
    logic signed [9:0]               exp_spread_r;

    assign in_ready    = !out_valid_r || out_ready;
    assign accept_fire = in_valid && in_ready;
    assign retire_fire = out_valid_r && out_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            out_valid_r             <= 1'b0;
            cached_scale_a_r        <= '0;
            cached_scale_b_r        <= '0;
            scale_a_out_r           <= '0;
            scale_b_out_r           <= '0;
            eff_scale_fmt_r         <= TCU_V2_SCALE_NONE;
            pe_invalid_r            <= '0;
            pe_ovf_risk_r           <= '0;
            pe_udf_risk_r           <= '0;
            pe_zero_prod_r          <= '0;
            any_invalid_r           <= 1'b0;
            row_zero_r              <= '0;
            col_zero_r              <= '0;
            row_subnorm_r           <= '0;
            col_subnorm_r           <= '0;
            row_neg_e4m3_r          <= '0;
            col_neg_e4m3_r          <= '0;
            fault_count_r           <= 32'd0;
            scale_updates_r         <= 32'd0;
            scale_zero_events_r     <= 32'd0;
            scale_k16_events_r      <= 32'd0;
            scale_k32_events_r      <= 32'd0;
            scale_ovf_risk_events_r <= 32'd0;
            scale_udf_risk_events_r <= 32'd0;
            scale_stall_cycles_r    <= 32'd0;
            last_k16_blk_r          <= 8'd0;
            last_k32_blk_r          <= 8'd0;
            exp_checksum_r          <= 10'd0;
            exp_spread_r            <= 10'sd0;
        end else begin
            if (out_valid_r && !out_ready) begin
                scale_stall_cycles_r <= scale_stall_cycles_r + 32'd1;
            end
            if (accept_fire) begin
                if (scale_latch_en) begin
                    cached_scale_a_r <= scale_a_in;
                    cached_scale_b_r <= scale_b_in;
                    scale_updates_r  <= scale_updates_r + 32'd1;
                    if (eff_scale_fmt_comb == TCU_V2_SCALE_E4M3) begin
                        scale_k16_events_r <= scale_k16_events_r + 32'd1;
                    end else if (eff_scale_fmt_comb == TCU_V2_SCALE_UE8M0) begin
                        scale_k32_events_r <= scale_k32_events_r + 32'd1;
                    end
                end
                scale_a_out_r   <= active_scale_a_comb;
                scale_b_out_r   <= active_scale_b_comb;
                eff_scale_fmt_r <= eff_scale_fmt_comb;
                pe_invalid_r    <= pe_invalid_comb;
                pe_ovf_risk_r   <= pe_ovf_risk_comb;
                pe_udf_risk_r   <= pe_udf_risk_comb;
                pe_zero_prod_r  <= pe_zero_prod_comb;
                any_invalid_r   <= any_invalid_comb;
                row_zero_r      <= row_zero_comb;
                col_zero_r      <= col_zero_comb;
                row_subnorm_r   <= row_subnorm_comb;
                col_subnorm_r   <= col_subnorm_comb;
                row_neg_e4m3_r  <= row_neg_e4m3_comb;
                col_neg_e4m3_r  <= col_neg_e4m3_comb;
                last_k16_blk_r  <= k16_block_idx;
                last_k32_blk_r  <= k32_block_idx;
                out_valid_r     <= 1'b1;
                exp_checksum_r  <= row_exp_delta_comb[0] ^ col_exp_delta_comb[0];
                exp_spread_r    <= max_exp_delta_comb - min_exp_delta_comb;

                if (any_invalid_comb) begin
                    fault_count_r <= fault_count_r + 32'd1;
                end
                if ((|row_zero_comb) || (|col_zero_comb)) begin
                    scale_zero_events_r <= scale_zero_events_r + 32'd1;
                end
                if (|pe_ovf_risk_comb) begin
                    scale_ovf_risk_events_r <= scale_ovf_risk_events_r + 32'd1;
                end
                if (|pe_udf_risk_comb) begin
                    scale_udf_risk_events_r <= scale_udf_risk_events_r + 32'd1;
                end
            end else if (retire_fire) begin
                out_valid_r <= 1'b0;
            end
        end
    end

    `UNUSED_PARAM (ARRAY_K)
    `UNUSED_VAR (row_exp_delta_comb)
    `UNUSED_VAR (col_exp_delta_comb)
    `UNUSED_VAR (pe_ovf_risk_r)
    `UNUSED_VAR (pe_udf_risk_r)
    `UNUSED_VAR (pe_zero_prod_r)
    `UNUSED_VAR (row_subnorm_r)
    `UNUSED_VAR (col_subnorm_r)
    `UNUSED_VAR (row_neg_e4m3_r)
    `UNUSED_VAR (col_neg_e4m3_r)
    `UNUSED_VAR (scale_updates_r)
    `UNUSED_VAR (scale_zero_events_r)
    `UNUSED_VAR (scale_k16_events_r)
    `UNUSED_VAR (scale_k32_events_r)
    `UNUSED_VAR (scale_ovf_risk_events_r)
    `UNUSED_VAR (scale_udf_risk_events_r)
    `UNUSED_VAR (scale_stall_cycles_r)
    `UNUSED_VAR (last_k16_blk_r)
    `UNUSED_VAR (last_k32_blk_r)
    `UNUSED_VAR (exp_checksum_r)
    `UNUSED_VAR (exp_spread_r)
    `UNUSED_VAR (k_elem_offset)

    assign out_valid               = out_valid_r;
    assign scale_a_aligned_out     = scale_a_out_r;
    assign scale_b_aligned_out     = scale_b_out_r;
    assign effective_scale_fmt_out = eff_scale_fmt_r;
    assign pe_scale_invalid_mask   = pe_invalid_r;
    assign any_scale_invalid_out   = any_invalid_r;
    assign row_scale_zero_mask     = row_zero_r;
    assign col_scale_zero_mask     = col_zero_r;
    assign scale_fault_count_out   = fault_count_r;

endmodule

`endif // VX_TCU_V2_SCALE_BROADCAST_SV
