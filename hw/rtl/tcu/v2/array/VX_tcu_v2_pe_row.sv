// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_PE_ROW_SV
`define VX_TCU_V2_PE_ROW_SV

`include "VX_platform.vh"

module VX_tcu_v2_pe_row #(
    parameter int ARRAY_N         = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K         = VX_tcu_v2_pkg::TCU_V2_ARRAY_K,
    parameter int TAG_QUEUE_DEPTH = 8
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    row_valid_in,
    output logic                                    row_ready_in,
    input  logic [ARRAY_N-1:0]                      col_valid_in,
    output logic [ARRAY_N-1:0]                      col_ready_in,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e              fmt_a,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e              fmt_b,
    input  VX_tcu_v2_pkg::tcu_v2_scale_fmt_e        scale_fmt,
    input  VX_tcu_v2_pkg::tcu_v2_rm_e               rm,
    input  logic                                    systolic_mode,
    input  logic [ARRAY_K*32-1:0]                   a_row_in,
    input  logic [7:0]                              scale_a_row_in,
    input  logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      b_cols_in,
    input  logic [ARRAY_N-1:0][7:0]                 scale_b_cols_in,
    input  logic [ARRAY_N-1:0][31:0]                c_cols_in,
    input  logic                                    accum_en,
    input  logic                                    int_saturate,
    output logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      b_cols_pass_out,
    output logic [ARRAY_N-1:0][7:0]                 scale_b_cols_pass_out,
    output logic [ARRAY_N-1:0]                      b_pass_valid_out,
    output logic [ARRAY_N-1:0]                      valid_out,
    input  logic [ARRAY_N-1:0]                      ready_out,
    output logic [ARRAY_N-1:0][31:0]                d_cols_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t [ARRAY_N-1:0] flags_cols_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         row_flags_or_out,
    output logic                                    row_all_valid_out,
    output logic                                    row_busy_out,
    output logic [31:0]                             row_ops_done_out
);

    import VX_tcu_v2_pkg::*;

    // -------------------------------------------------------------------------
    // Horizontal A/Scale Systolic Chain & Broadcast Muxing
    // -------------------------------------------------------------------------
    logic [ARRAY_N:0][ARRAY_K*32-1:0] a_chain;
    logic [ARRAY_N:0][7:0]            scale_a_chain;
    logic [ARRAY_N:0]                 a_valid_chain;

    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] pe_a_in;
    logic [ARRAY_N-1:0][7:0]            pe_scale_a_in;
    logic [ARRAY_N-1:0]                 pe_valid_in;
    logic [ARRAY_N-1:0]                 pe_ready_in;

    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] pe_a_pass;
    logic [ARRAY_N-1:0][7:0]            pe_scale_a_pass;
    logic [ARRAY_N-1:0]                 pe_pass_valid;

    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] pe_b_pass;
    logic [ARRAY_N-1:0][7:0]            pe_scale_b_pass;

    logic [ARRAY_N-1:0]                 pe_valid_out;
    logic [ARRAY_N-1:0]                 pe_busy;
    logic [ARRAY_N-1:0][31:0]           pe_ops_done;
    tcu_v2_fp_flags_t [ARRAY_N-1:0]     pe_flags_out;

    // Inter-column systolic pipeline registers for A and scale_a
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] a_stage_r;
    logic [ARRAY_N-1:0][7:0]            scale_a_stage_r;
    logic [ARRAY_N-1:0]                 a_stage_valid_r;

    // Vertical B pass-through staging registers per column
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] b_stage_r;
    logic [ARRAY_N-1:0][7:0]            scale_b_stage_r;
    logic [ARRAY_N-1:0]                 b_stage_valid_r;

    // Per-column exception telemetry masks, NaN/Inf monitors, and row stall counters
    logic [ARRAY_N-1:0] col_nv_mask_r;
    logic [ARRAY_N-1:0] col_dz_mask_r;
    logic [ARRAY_N-1:0] col_of_mask_r;
    logic [ARRAY_N-1:0] col_uf_mask_r;
    logic [ARRAY_N-1:0] col_nx_mask_r;
    logic [ARRAY_N-1:0] col_nan_out_r;
    logic [ARRAY_N-1:0] col_inf_out_r;
    logic [ARRAY_N-1:0] col_zero_out_r;
    logic [ARRAY_N-1:0] col_b_nz_mask_r;
    logic [ARRAY_N-1:0] col_c_nz_mask_r;
    logic               row_a_nz_r;
    logic [31:0]        row_stall_cycles_r;
    logic [31:0]        row_fire_cycles_r;
    logic [31:0]        row_retire_cycles_r;
    logic [31:0]        row_backpressure_r;
    logic [31:0]        row_d_checksum_r;
    logic [31:0]        row_col_skews_r;
    logic [31:0]        row_accum_cycles_r;
    logic [31:0]        row_sat_cycles_r;

    assign a_chain[0]       = a_row_in;
    assign scale_a_chain[0] = scale_a_row_in;
    assign a_valid_chain[0] = row_valid_in;

    // Ready signals strictly independent of valid signals to avoid combinational loops
    logic all_cols_ready;
    logic any_col_busy;
    logic all_cols_valid_in;
    logic any_col_valid_in;

    always_comb begin
        all_cols_ready    = 1'b1;
        any_col_busy      = 1'b0;
        all_cols_valid_in = 1'b1;
        any_col_valid_in  = 1'b0;

        for (int c = 0; c < ARRAY_N; ++c) begin
            all_cols_ready    = all_cols_ready && pe_ready_in[c];
            any_col_busy      = any_col_busy || pe_busy[c] || a_stage_valid_r[c] || b_stage_valid_r[c];
            all_cols_valid_in = all_cols_valid_in && col_valid_in[c];
            any_col_valid_in  = any_col_valid_in || col_valid_in[c];
        end

        if (systolic_mode) begin
            row_ready_in = pe_ready_in[0];
        end else begin
            row_ready_in = all_cols_ready;
        end
    end

    for (genvar col = 0; col < ARRAY_N; ++col) begin : g_pe_cols
        logic col_stall;
        logic col_accept;
        logic stage_advance;

        assign col_stall     = !pe_ready_in[col];
        assign stage_advance = !col_stall;

        // Horizontal A input: synchronous broadcast vs staged systolic chain
        always_comb begin
            if (systolic_mode) begin
                pe_a_in[col]       = a_chain[col];
                pe_scale_a_in[col] = scale_a_chain[col];
                pe_valid_in[col]   = a_valid_chain[col] && col_valid_in[col];
            end else begin
                pe_a_in[col]       = a_row_in;
                pe_scale_a_in[col] = scale_a_row_in;
                pe_valid_in[col]   = row_valid_in && all_cols_valid_in;
            end
        end

        assign col_ready_in[col] = systolic_mode ? pe_ready_in[col] : all_cols_ready;
        assign col_accept        = pe_valid_in[col] && pe_ready_in[col];

        always_ff @(posedge clk) begin
            if (reset) begin
                a_stage_r[col]       <= '0;
                scale_a_stage_r[col] <= 8'd0;
                a_stage_valid_r[col] <= 1'b0;
                b_stage_r[col]       <= '0;
                scale_b_stage_r[col] <= 8'd0;
                b_stage_valid_r[col] <= 1'b0;
            end else if (systolic_mode && stage_advance) begin
                a_stage_valid_r[col] <= col_accept;
                b_stage_valid_r[col] <= col_accept;
                if (col_accept) begin
                    a_stage_r[col]       <= pe_a_pass[col];
                    scale_a_stage_r[col] <= pe_scale_a_pass[col];
                    b_stage_r[col]       <= pe_b_pass[col];
                    scale_b_stage_r[col] <= pe_scale_b_pass[col];
                end
            end else if (!systolic_mode) begin
                a_stage_valid_r[col] <= 1'b0;
                b_stage_valid_r[col] <= 1'b0;
            end
        end

        assign a_chain[col + 1]           = a_stage_r[col];
        assign scale_a_chain[col + 1]     = scale_a_stage_r[col];
        assign a_valid_chain[col + 1]     = a_stage_valid_r[col] && pe_pass_valid[col];

        assign b_cols_pass_out[col]       = b_stage_r[col];
        assign scale_b_cols_pass_out[col] = scale_b_stage_r[col];
        assign b_pass_valid_out[col]      = b_stage_valid_r[col];

        VX_tcu_v2_pe #(
            .LANES           (ARRAY_K),
            .TAG_QUEUE_DEPTH (TAG_QUEUE_DEPTH)
        ) u_pe (
            .clk              (clk),
            .reset            (reset),
            .valid_in         (pe_valid_in[col]),
            .ready_in         (pe_ready_in[col]),
            .fmt_a            (fmt_a),
            .fmt_b            (fmt_b),
            .scale_fmt        (scale_fmt),
            .rm               (rm),
            .a_in             (pe_a_in[col]),
            .b_in             (b_cols_in[col]),
            .scale_a_in       (pe_scale_a_in[col]),
            .scale_b_in       (scale_b_cols_in[col]),
            .c_in             (c_cols_in[col]),
            .accum_en         (accum_en),
            .int_saturate     (int_saturate),
            .systolic_pass_en (systolic_mode && stage_advance),
            .a_pass_out       (pe_a_pass[col]),
            .b_pass_out       (pe_b_pass[col]),
            .scale_a_pass_out (pe_scale_a_pass[col]),
            .scale_b_pass_out (pe_scale_b_pass[col]),
            .pass_valid_out   (pe_pass_valid[col]),
            .valid_out        (pe_valid_out[col]),
            .ready_out        (ready_out[col]),
            .d_out            (d_cols_out[col]),
            .flags_out        (pe_flags_out[col]),
            .pe_busy          (pe_busy[col]),
            .pe_ops_done      (pe_ops_done[col])
        );
    end

    // -------------------------------------------------------------------------
    // Per-Row Exception Telemetry, Activity Counters & Flag OR-Reduction
    // -------------------------------------------------------------------------
    tcu_v2_fp_flags_t flags_or_comb;
    logic [31:0]      ops_sum_comb;
    logic [31:0]      d_xor_comb;
    logic             row_any_fire;
    logic             row_any_stall;
    logic             row_any_retire;
    logic             row_any_bp;
    logic             row_is_int;
    logic             row_skew_mismatch;

    assign row_is_int        = tcu_v2_fmt_is_int(fmt_a) && tcu_v2_fmt_is_int(fmt_b);
    assign row_skew_mismatch = any_col_valid_in && !all_cols_valid_in;

    always_comb begin
        flags_or_comb  = '0;
        ops_sum_comb   = 32'd0;
        d_xor_comb     = 32'd0;
        row_any_fire   = 1'b0;
        row_any_stall  = 1'b0;
        row_any_retire = 1'b0;
        row_any_bp     = 1'b0;

        for (int c = 0; c < ARRAY_N; ++c) begin
            if (pe_valid_out[c]) begin
                flags_or_comb = tcu_v2_flags_or(flags_or_comb, pe_flags_out[c]);
                d_xor_comb    = d_xor_comb ^ d_cols_out[c];
            end
            if (pe_valid_in[c] && pe_ready_in[c]) begin
                row_any_fire = 1'b1;
            end
            if (pe_valid_in[c] && !pe_ready_in[c]) begin
                row_any_stall = 1'b1;
            end
            if (pe_valid_out[c] && ready_out[c]) begin
                row_any_retire = 1'b1;
            end
            if (pe_valid_out[c] && !ready_out[c]) begin
                row_any_bp = 1'b1;
            end
            ops_sum_comb = ops_sum_comb + pe_ops_done[c];
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            col_nv_mask_r       <= '0;
            col_dz_mask_r       <= '0;
            col_of_mask_r       <= '0;
            col_uf_mask_r       <= '0;
            col_nx_mask_r       <= '0;
            col_nan_out_r       <= '0;
            col_inf_out_r       <= '0;
            col_zero_out_r      <= '0;
            col_b_nz_mask_r     <= '0;
            col_c_nz_mask_r     <= '0;
            row_a_nz_r          <= 1'b0;
            row_stall_cycles_r  <= 32'd0;
            row_fire_cycles_r   <= 32'd0;
            row_retire_cycles_r <= 32'd0;
            row_backpressure_r  <= 32'd0;
            row_d_checksum_r    <= 32'd0;
            row_col_skews_r     <= 32'd0;
            row_accum_cycles_r  <= 32'd0;
            row_sat_cycles_r    <= 32'd0;
        end else begin
            if (row_any_fire) begin
                row_a_nz_r <= (a_row_in != '0);
                for (int c = 0; c < ARRAY_N; ++c) begin
                    col_b_nz_mask_r[c] <= (b_cols_in[c] != '0);
                    col_c_nz_mask_r[c] <= (c_cols_in[c] != 32'd0);
                end
                if (accum_en) begin
                    row_accum_cycles_r <= row_accum_cycles_r + 32'd1;
                end
                if (int_saturate) begin
                    row_sat_cycles_r <= row_sat_cycles_r + 32'd1;
                end
            end
            for (int c = 0; c < ARRAY_N; ++c) begin
                if (pe_valid_out[c] && ready_out[c]) begin
                    col_nv_mask_r[c]  <= pe_flags_out[c].nv;
                    col_dz_mask_r[c]  <= pe_flags_out[c].dz;
                    col_of_mask_r[c]  <= pe_flags_out[c].of;
                    col_uf_mask_r[c]  <= pe_flags_out[c].uf;
                    col_nx_mask_r[c]  <= pe_flags_out[c].nx;
                    col_nan_out_r[c]  <= !row_is_int && tcu_v2_fp32_is_nan(d_cols_out[c]);
                    col_inf_out_r[c]  <= !row_is_int && tcu_v2_fp32_is_inf(d_cols_out[c]);
                    col_zero_out_r[c] <= row_is_int ? (d_cols_out[c] == 32'd0) : tcu_v2_fp32_is_zero(d_cols_out[c]);
                end
            end
            if (row_any_fire) begin
                row_fire_cycles_r <= row_fire_cycles_r + 32'd1;
            end
            if (row_any_stall) begin
                row_stall_cycles_r <= row_stall_cycles_r + 32'd1;
            end
            if (row_any_retire) begin
                row_retire_cycles_r <= row_retire_cycles_r + 32'd1;
                row_d_checksum_r    <= row_d_checksum_r ^ d_xor_comb;
            end
            if (row_any_bp) begin
                row_backpressure_r <= row_backpressure_r + 32'd1;
            end
            if (row_skew_mismatch) begin
                row_col_skews_r <= row_col_skews_r + 32'd1;
            end
        end
    end

    `UNUSED_VAR (a_chain)
    `UNUSED_VAR (scale_a_chain)
    `UNUSED_VAR (a_valid_chain)
    `UNUSED_VAR (col_nv_mask_r)
    `UNUSED_VAR (col_dz_mask_r)
    `UNUSED_VAR (col_of_mask_r)
    `UNUSED_VAR (col_uf_mask_r)
    `UNUSED_VAR (col_nx_mask_r)
    `UNUSED_VAR (col_nan_out_r)
    `UNUSED_VAR (col_inf_out_r)
    `UNUSED_VAR (col_zero_out_r)
    `UNUSED_VAR (col_b_nz_mask_r)
    `UNUSED_VAR (col_c_nz_mask_r)
    `UNUSED_VAR (row_a_nz_r)
    `UNUSED_VAR (row_stall_cycles_r)
    `UNUSED_VAR (row_fire_cycles_r)
    `UNUSED_VAR (row_retire_cycles_r)
    `UNUSED_VAR (row_backpressure_r)
    `UNUSED_VAR (row_d_checksum_r)
    `UNUSED_VAR (row_col_skews_r)
    `UNUSED_VAR (row_accum_cycles_r)
    `UNUSED_VAR (row_sat_cycles_r)

    assign valid_out         = pe_valid_out;
    assign flags_cols_out    = pe_flags_out;
    assign row_flags_or_out  = flags_or_comb;
    assign row_all_valid_out = &pe_valid_out;
    assign row_busy_out      = any_col_busy;
    assign row_ops_done_out  = ops_sum_comb;

endmodule

`endif // VX_TCU_V2_PE_ROW_SV
