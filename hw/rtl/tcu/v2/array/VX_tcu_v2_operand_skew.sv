// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_OPERAND_SKEW_SV
`define VX_TCU_V2_OPERAND_SKEW_SV

`include "VX_platform.vh"

module VX_tcu_v2_operand_skew #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    systolic_mode,
    input  logic                                    in_valid,
    output logic                                    in_ready,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      a_tile_in,
    input  logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      b_tile_in,
    input  logic [ARRAY_M-1:0][7:0]                 scale_a_in,
    input  logic [ARRAY_N-1:0][7:0]                 scale_b_in,
    output logic [ARRAY_M-1:0]                      a_row_valid_out,
    input  logic [ARRAY_M-1:0]                      a_row_ready_in,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      a_row_out,
    output logic [ARRAY_M-1:0][7:0]                 scale_a_row_out,
    output logic [ARRAY_N-1:0]                      b_col_valid_out,
    input  logic [ARRAY_N-1:0]                      b_col_ready_in,
    output logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      b_col_out,
    output logic [ARRAY_N-1:0][7:0]                 scale_b_col_out,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0]         d_valid_in,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0]         d_ready_out,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   d_elem_in,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t [ARRAY_M-1:0][ARRAY_N-1:0] flags_elem_in,
    output logic                                    deskew_valid_out,
    input  logic                                    deskew_ready_in,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   d_tile_deskew_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_deskew_out,
    output logic                                    skew_busy_out
);

    import VX_tcu_v2_pkg::*;

    localparam int A_PAYLOAD_W = ARRAY_K * 32 + 8;
    localparam int B_PAYLOAD_W = ARRAY_K * 32 + 8;
    localparam int D_PAYLOAD_W = 32 + $bits(tcu_v2_fp_flags_t);
    localparam int MAX_DIAG    = (ARRAY_M - 1) + (ARRAY_N - 1);

    // -------------------------------------------------------------------------
    // Broadcast Staging Register & Ready Aggregation (Loop-Free)
    // -------------------------------------------------------------------------
    logic a_all_ready;
    logic b_all_ready;
    logic fire_in;

    logic [ARRAY_M-1:0]              a_lane_busy;
    logic [ARRAY_N-1:0]              b_lane_busy;
    logic [ARRAY_M-1:0][ARRAY_N-1:0] d_lane_busy;

    logic                               bcast_valid_r;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] bcast_a_r;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0] bcast_b_r;
    logic [ARRAY_M-1:0][7:0]            bcast_scale_a_r;
    logic [ARRAY_N-1:0][7:0]            bcast_scale_b_r;
    logic                               bcast_advance;

    // Input systolic hold register for row 0 / col 0 synchronization
    logic                               sys0_valid_r;
    logic [ARRAY_K*32-1:0]              sys0_a_r;
    logic [7:0]                         sys0_scale_a_r;
    logic [ARRAY_K*32-1:0]              sys0_b_r;
    logic [7:0]                         sys0_scale_b_r;

    // Output deskew elastic hold register for synchronized tile delivery
    logic                                    deskew_hold_valid_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   deskew_hold_data_r;
    tcu_v2_fp_flags_t                        deskew_hold_flags_r;
    logic                                    deskew_stage_ready;

    always_comb begin
        a_all_ready = 1'b1;
        b_all_ready = 1'b1;
        for (int r = 0; r < ARRAY_M; ++r) begin
            a_all_ready = a_all_ready && a_row_ready_in[r];
        end
        for (int c = 0; c < ARRAY_N; ++c) begin
            b_all_ready = b_all_ready && b_col_ready_in[c];
        end

        bcast_advance = a_all_ready && b_all_ready;

        if (systolic_mode) begin
            in_ready = (!sys0_valid_r || (a_row_ready_in[0] && b_col_ready_in[0]));
        end else begin
            in_ready = !bcast_valid_r || bcast_advance;
        end
    end

    assign fire_in            = in_valid && in_ready;
    assign deskew_stage_ready = !deskew_hold_valid_r || deskew_ready_in;

    always_ff @(posedge clk) begin
        if (reset) begin
            bcast_valid_r   <= 1'b0;
            bcast_a_r       <= '0;
            bcast_b_r       <= '0;
            bcast_scale_a_r <= '0;
            bcast_scale_b_r <= '0;
            sys0_valid_r    <= 1'b0;
            sys0_a_r        <= '0;
            sys0_scale_a_r  <= 8'd0;
            sys0_b_r        <= '0;
            sys0_scale_b_r  <= 8'd0;
        end else if (!systolic_mode) begin
            sys0_valid_r <= 1'b0;
            if (fire_in) begin
                bcast_valid_r   <= 1'b1;
                bcast_a_r       <= a_tile_in;
                bcast_b_r       <= b_tile_in;
                bcast_scale_a_r <= scale_a_in;
                bcast_scale_b_r <= scale_b_in;
            end else if (bcast_valid_r && bcast_advance) begin
                bcast_valid_r <= 1'b0;
            end
        end else begin
            bcast_valid_r <= 1'b0;
            if (fire_in) begin
                sys0_valid_r   <= 1'b1;
                sys0_a_r       <= a_tile_in[0];
                sys0_scale_a_r <= scale_a_in[0];
                sys0_b_r       <= b_tile_in[0];
                sys0_scale_b_r <= scale_b_in[0];
            end else if (sys0_valid_r && a_row_ready_in[0] && b_col_ready_in[0]) begin
                sys0_valid_r <= 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Row-wise A Skew Shift Registers (Row r Delayed by r Cycles in Systolic)
    // -------------------------------------------------------------------------
    for (genvar r = 0; r < ARRAY_M; ++r) begin : g_skew_a_rows
        localparam int SKEW_DEPTH = (r == 0) ? 1 : r;
        logic [SKEW_DEPTH-1:0][A_PAYLOAD_W-1:0] a_pipe_r;
        logic [SKEW_DEPTH-1:0]                  a_valid_r;
        logic                                   row_advance;

        assign row_advance = a_row_ready_in[r] || !a_valid_r[SKEW_DEPTH - 1];

        always_ff @(posedge clk) begin
            if (reset) begin
                a_valid_r <= '0;
                for (int d = 0; d < SKEW_DEPTH; ++d) begin
                    a_pipe_r[d] <= '0;
                end
            end else if (systolic_mode && (r > 0) && row_advance) begin
                a_valid_r[0] <= fire_in;
                if (fire_in) begin
                    a_pipe_r[0] <= {scale_a_in[r], a_tile_in[r]};
                end
                for (int d = 1; d < SKEW_DEPTH; ++d) begin
                    a_valid_r[d] <= a_valid_r[d - 1];
                    a_pipe_r[d]  <= a_pipe_r[d - 1];
                end
            end else if (!systolic_mode || (r == 0)) begin
                a_valid_r <= '0;
            end
        end

        always_comb begin
            if (!systolic_mode) begin
                a_row_valid_out[r] = bcast_valid_r;
                a_row_out[r]       = bcast_a_r[r];
                scale_a_row_out[r] = bcast_scale_a_r[r];
                a_lane_busy[r]     = bcast_valid_r;
            end else if (r == 0) begin
                a_row_valid_out[r] = sys0_valid_r;
                a_row_out[r]       = sys0_a_r;
                scale_a_row_out[r] = sys0_scale_a_r;
                a_lane_busy[r]     = sys0_valid_r;
            end else begin
                a_row_valid_out[r]                 = a_valid_r[SKEW_DEPTH - 1];
                {scale_a_row_out[r], a_row_out[r]} = a_pipe_r[SKEW_DEPTH - 1];
                a_lane_busy[r]                     = |a_valid_r;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Column-wise B Skew Shift Registers (Col c Delayed by c Cycles in Systolic)
    // -------------------------------------------------------------------------
    for (genvar c = 0; c < ARRAY_N; ++c) begin : g_skew_b_cols
        localparam int SKEW_DEPTH_B = (c == 0) ? 1 : c;
        logic [SKEW_DEPTH_B-1:0][B_PAYLOAD_W-1:0] b_pipe_r;
        logic [SKEW_DEPTH_B-1:0]                  b_valid_r;
        logic                                     col_advance;

        assign col_advance = b_col_ready_in[c] || !b_valid_r[SKEW_DEPTH_B - 1];

        always_ff @(posedge clk) begin
            if (reset) begin
                b_valid_r <= '0;
                for (int d = 0; d < SKEW_DEPTH_B; ++d) begin
                    b_pipe_r[d] <= '0;
                end
            end else if (systolic_mode && (c > 0) && col_advance) begin
                b_valid_r[0] <= fire_in;
                if (fire_in) begin
                    b_pipe_r[0] <= {scale_b_in[c], b_tile_in[c]};
                end
                for (int d = 1; d < SKEW_DEPTH_B; ++d) begin
                    b_valid_r[d] <= b_valid_r[d - 1];
                    b_pipe_r[d]  <= b_pipe_r[d - 1];
                end
            end else if (!systolic_mode || (c == 0)) begin
                b_valid_r <= '0;
            end
        end

        always_comb begin
            if (!systolic_mode) begin
                b_col_valid_out[c] = bcast_valid_r;
                b_col_out[c]       = bcast_b_r[c];
                scale_b_col_out[c] = bcast_scale_b_r[c];
                b_lane_busy[c]     = bcast_valid_r;
            end else if (c == 0) begin
                b_col_valid_out[c] = sys0_valid_r;
                b_col_out[c]       = sys0_b_r;
                scale_b_col_out[c] = sys0_scale_b_r;
                b_lane_busy[c]     = sys0_valid_r;
            end else begin
                b_col_valid_out[c]                 = b_valid_r[SKEW_DEPTH_B - 1];
                {scale_b_col_out[c], b_col_out[c]} = b_pipe_r[SKEW_DEPTH_B - 1];
                b_lane_busy[c]                     = |b_valid_r;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Output Deskew Alignment Matrix & Wavefront Telemetry
    // -------------------------------------------------------------------------
    logic [ARRAY_M-1:0][ARRAY_N-1:0]                deskew_elem_valid;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]          deskew_elem_data;
    tcu_v2_fp_flags_t [ARRAY_M-1:0][ARRAY_N-1:0]    deskew_elem_flags;
    logic                                           all_deskew_valid;

    for (genvar r = 0; r < ARRAY_M; ++r) begin : g_deskew_rows
        for (genvar c = 0; c < ARRAY_N; ++c) begin : g_deskew_cols
            localparam int COMP_DELAY = MAX_DIAG - (r + c);
            localparam int PIPE_LEN   = (COMP_DELAY == 0) ? 1 : COMP_DELAY;

            logic [PIPE_LEN-1:0][D_PAYLOAD_W-1:0] d_pipe_r;
            logic [PIPE_LEN-1:0]                  d_pipe_valid_r;
            logic                                 elem_advance;

            assign elem_advance = deskew_stage_ready || !d_pipe_valid_r[PIPE_LEN - 1];

            always_ff @(posedge clk) begin
                if (reset) begin
                    d_pipe_valid_r <= '0;
                    for (int s = 0; s < PIPE_LEN; ++s) begin
                        d_pipe_r[s] <= '0;
                    end
                end else if (systolic_mode && (COMP_DELAY > 0) && elem_advance) begin
                    d_pipe_valid_r[0] <= d_valid_in[r][c];
                    if (d_valid_in[r][c]) begin
                        d_pipe_r[0] <= {flags_elem_in[r][c], d_elem_in[r][c]};
                    end
                    for (int s = 1; s < PIPE_LEN; ++s) begin
                        d_pipe_valid_r[s] <= d_pipe_valid_r[s - 1];
                        d_pipe_r[s]       <= d_pipe_r[s - 1];
                    end
                end else if (!systolic_mode || (COMP_DELAY == 0)) begin
                    d_pipe_valid_r <= '0;
                end
            end

            always_comb begin
                if (!systolic_mode || (COMP_DELAY == 0)) begin
                    deskew_elem_valid[r][c] = d_valid_in[r][c];
                    deskew_elem_data[r][c]  = d_elem_in[r][c];
                    deskew_elem_flags[r][c] = flags_elem_in[r][c];
                    d_ready_out[r][c]       = deskew_stage_ready && all_deskew_valid;
                    d_lane_busy[r][c]       = 1'b0;
                end else begin
                    deskew_elem_valid[r][c] = d_pipe_valid_r[PIPE_LEN - 1];
                    {deskew_elem_flags[r][c], deskew_elem_data[r][c]} = d_pipe_r[PIPE_LEN - 1];
                    d_ready_out[r][c]       = elem_advance;
                    d_lane_busy[r][c]       = |d_pipe_valid_r;
                end
            end
        end
    end

    tcu_v2_fp_flags_t flags_or_comb;
    logic             busy_comb;
    logic             any_deskew_valid;
    logic             deskew_partial_skew;
    logic [31:0]      wave_issued_cnt_r;
    logic [31:0]      wave_retired_cnt_r;
    logic [31:0]      skew_align_wait_r;
    logic [31:0]      bcast_cycles_r;
    logic [31:0]      systolic_cycles_r;
    logic [31:0]      deskew_bp_cycles_r;

    always_comb begin
        all_deskew_valid = 1'b1;
        any_deskew_valid = 1'b0;
        flags_or_comb    = '0;
        busy_comb        = (|a_lane_busy) || (|b_lane_busy) || deskew_hold_valid_r;

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                all_deskew_valid = all_deskew_valid && deskew_elem_valid[r][c];
                any_deskew_valid = any_deskew_valid || deskew_elem_valid[r][c];
                if (deskew_elem_valid[r][c]) begin
                    flags_or_comb = tcu_v2_flags_or(flags_or_comb, deskew_elem_flags[r][c]);
                end
                busy_comb = busy_comb || d_lane_busy[r][c];
            end
        end
        deskew_partial_skew = any_deskew_valid && !all_deskew_valid;
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            deskew_hold_valid_r <= 1'b0;
            deskew_hold_data_r  <= '0;
            deskew_hold_flags_r <= '0;
            wave_issued_cnt_r   <= 32'd0;
            wave_retired_cnt_r  <= 32'd0;
            skew_align_wait_r   <= 32'd0;
            bcast_cycles_r      <= 32'd0;
            systolic_cycles_r   <= 32'd0;
            deskew_bp_cycles_r  <= 32'd0;
        end else begin
            if (all_deskew_valid && deskew_stage_ready) begin
                deskew_hold_valid_r <= 1'b1;
                deskew_hold_data_r  <= deskew_elem_data;
                deskew_hold_flags_r <= flags_or_comb;
            end else if (deskew_hold_valid_r && deskew_ready_in) begin
                deskew_hold_valid_r <= 1'b0;
            end

            if (fire_in) begin
                wave_issued_cnt_r <= wave_issued_cnt_r + 32'd1;
                if (systolic_mode) begin
                    systolic_cycles_r <= systolic_cycles_r + 32'd1;
                end else begin
                    bcast_cycles_r <= bcast_cycles_r + 32'd1;
                end
            end
            if (deskew_hold_valid_r && deskew_ready_in) begin
                wave_retired_cnt_r <= wave_retired_cnt_r + 32'd1;
            end
            if (deskew_hold_valid_r && !deskew_ready_in) begin
                deskew_bp_cycles_r <= deskew_bp_cycles_r + 32'd1;
            end
            if (deskew_partial_skew) begin
                skew_align_wait_r <= skew_align_wait_r + 32'd1;
            end
        end
    end

    `UNUSED_VAR (wave_issued_cnt_r)
    `UNUSED_VAR (wave_retired_cnt_r)
    `UNUSED_VAR (skew_align_wait_r)
    `UNUSED_VAR (bcast_cycles_r)
    `UNUSED_VAR (systolic_cycles_r)
    `UNUSED_VAR (deskew_bp_cycles_r)

    assign deskew_valid_out  = deskew_hold_valid_r;
    assign d_tile_deskew_out = deskew_hold_data_r;
    assign flags_deskew_out  = deskew_hold_flags_r;
    assign skew_busy_out     = busy_comb;

endmodule

`endif // VX_TCU_V2_OPERAND_SKEW_SV
