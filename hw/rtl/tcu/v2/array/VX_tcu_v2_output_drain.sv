// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_OUTPUT_DRAIN_SV
`define VX_TCU_V2_OUTPUT_DRAIN_SV

`include "VX_platform.vh"

module VX_tcu_v2_output_drain #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Handshake with Accumulator Tile Bank (Inactive Drain Bank)
    input  logic                                    bank_valid,
    output logic                                    bank_ack,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   bank_tile_in,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t         bank_flags_in,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t              bank_uop_in,
    input  logic [ARRAY_N-1:0][31:0]                bank_bias_in,
    // Downstream Epilogue Pipeline Interface
    output logic                                    epilogue_valid,
    input  logic                                    epilogue_ready,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   epilogue_tile_out,
    output logic [ARRAY_N-1:0][31:0]                epilogue_bias_out,
    output VX_tcu_v2_pkg::tcu_v2_uop_t              epilogue_uop_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         epilogue_flags_out,
    output logic [$clog2(ARRAY_M+1)-1:0]            drain_row_idx_out,
    output logic                                    drain_active_out,
    output logic [31:0]                             tiles_drained_out
);

    import VX_tcu_v2_pkg::*;

    localparam int ROW_W = $clog2(ARRAY_M + 1);

    typedef enum logic [2:0] {
        DRAIN_IDLE     = 3'd0,
        DRAIN_PRECHECK = 3'd1,
        DRAIN_STREAM   = 3'd2,
        DRAIN_SKID     = 3'd3,
        DRAIN_COMMIT   = 3'd4
    } drain_state_e;

    // -------------------------------------------------------------------------
    // Dual-Slot Staging Queue & Row-by-Row Sanitization / Telemetry Registers
    // -------------------------------------------------------------------------
    drain_state_e                          state_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] stage_tile_r;
    logic [ARRAY_N-1:0][31:0]              stage_bias_r;
    tcu_v2_uop_t                           stage_uop_r;
    tcu_v2_fp_flags_t                      stage_flags_r;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] shadow_tile_r;
    logic [ARRAY_N-1:0][31:0]              shadow_bias_r;
    tcu_v2_uop_t                           shadow_uop_r;
    tcu_v2_fp_flags_t                      shadow_flags_r;
    logic                                  shadow_valid_r;

    logic [ROW_W-1:0]                      row_ptr_r;
    logic                                  bank_ack_r;
    logic                                  epilogue_valid_r;
    logic [31:0]                           tiles_drained_r;
    logic [31:0]                           shadow_hits_r;
    logic [31:0]                           rows_streamed_r;
    logic [31:0]                           drain_stall_cycles_r;
    logic [31:0]                           nan_elems_sanitized_r;
    logic [31:0]                           inf_elems_seen_r;
    logic [31:0]                           zero_elems_seen_r;
    logic [31:0]                           subnorm_elems_seen_r;
    logic [31:0]                           drain_busy_cycles_r;
    logic [ARRAY_N-1:0][31:0]              row_checksum_r;
    logic [ARRAY_M-1:0]                    row_has_nan_r;
    logic [ARRAY_M-1:0]                    row_has_inf_r;
    logic [ARRAY_M-1:0]                    row_all_zero_r;
    logic [ARRAY_M-1:0]                    row_has_subnorm_r;

    logic                                  epilogue_fire;
    logic                                  is_int_tile;
    logic [ARRAY_N-1:0][31:0]              active_row_slice;
    logic [ARRAY_N-1:0][31:0]              sanitized_row_slice;
    logic                                  row_nan_found;
    logic                                  row_inf_found;
    logic                                  row_subnorm_found;
    logic                                  row_all_zero_found;
    logic [3:0]                            row_nan_count;
    logic [3:0]                            row_inf_count;
    logic [3:0]                            row_zero_count;
    logic [3:0]                            row_subnorm_count;

    assign epilogue_fire = epilogue_valid_r && epilogue_ready;
    assign is_int_tile   = tcu_v2_fmt_is_int(stage_uop_r.fmt_a) && tcu_v2_fmt_is_int(stage_uop_r.fmt_b);

    // Inspect and canonicalize NaN payloads along the drained row
    always_comb begin
        active_row_slice    = '0;
        sanitized_row_slice = '0;
        row_nan_found       = 1'b0;
        row_inf_found       = 1'b0;
        row_subnorm_found   = 1'b0;
        row_all_zero_found  = 1'b1;
        row_nan_count       = 4'd0;
        row_inf_count       = 4'd0;
        row_zero_count      = 4'd0;
        row_subnorm_count   = 4'd0;

        if (int'(row_ptr_r) < ARRAY_M) begin
            active_row_slice = stage_tile_r[row_ptr_r[$clog2(ARRAY_M)-1:0]];
        end

        for (int c = 0; c < ARRAY_N; ++c) begin
            if (!is_int_tile && tcu_v2_fp32_is_nan(active_row_slice[c])) begin
                sanitized_row_slice[c] = TCU_V2_CANONICAL_QNAN;
                row_nan_found          = 1'b1;
                row_all_zero_found     = 1'b0;
                row_nan_count          = row_nan_count + 4'd1;
            end else begin
                sanitized_row_slice[c] = active_row_slice[c];
                if (!is_int_tile && tcu_v2_fp32_is_inf(active_row_slice[c])) begin
                    row_inf_found      = 1'b1;
                    row_all_zero_found = 1'b0;
                    row_inf_count      = row_inf_count + 4'd1;
                end else if (!is_int_tile && tcu_v2_fp32_is_subnormal(active_row_slice[c])) begin
                    row_subnorm_found  = 1'b1;
                    row_all_zero_found = 1'b0;
                    row_subnorm_count  = row_subnorm_count + 4'd1;
                end else if ((is_int_tile && (active_row_slice[c] == 32'd0)) ||
                             (!is_int_tile && tcu_v2_fp32_is_zero(active_row_slice[c]))) begin
                    row_zero_count = row_zero_count + 4'd1;
                end else begin
                    row_all_zero_found = 1'b0;
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Non-Blocking Tile Latching, Shadow Prefetch, and Row Drain Sequencer
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (reset) begin
            state_r               <= DRAIN_IDLE;
            stage_tile_r          <= '0;
            stage_bias_r          <= '0;
            stage_uop_r           <= '0;
            stage_flags_r         <= '0;
            shadow_tile_r         <= '0;
            shadow_bias_r         <= '0;
            shadow_uop_r          <= '0;
            shadow_flags_r        <= '0;
            shadow_valid_r        <= 1'b0;
            row_ptr_r             <= '0;
            bank_ack_r            <= 1'b0;
            epilogue_valid_r      <= 1'b0;
            tiles_drained_r       <= 32'd0;
            shadow_hits_r         <= 32'd0;
            rows_streamed_r       <= 32'd0;
            drain_stall_cycles_r  <= 32'd0;
            nan_elems_sanitized_r <= 32'd0;
            inf_elems_seen_r      <= 32'd0;
            zero_elems_seen_r     <= 32'd0;
            subnorm_elems_seen_r  <= 32'd0;
            drain_busy_cycles_r   <= 32'd0;
            row_checksum_r        <= '0;
            row_has_nan_r         <= '0;
            row_has_inf_r         <= '0;
            row_all_zero_r        <= '0;
            row_has_subnorm_r     <= '0;
        end else begin
            bank_ack_r <= 1'b0;

            if (state_r != DRAIN_IDLE) begin
                drain_busy_cycles_r <= drain_busy_cycles_r + 32'd1;
            end
            if (epilogue_valid_r && !epilogue_ready) begin
                drain_stall_cycles_r <= drain_stall_cycles_r + 32'd1;
            end

            // Prefetch next bank into shadow buffer while streaming current tile
            if ((state_r == DRAIN_STREAM || state_r == DRAIN_COMMIT) &&
                bank_valid && !shadow_valid_r && !bank_ack_r) begin
                shadow_tile_r  <= bank_tile_in;
                shadow_bias_r  <= bank_bias_in;
                shadow_uop_r   <= bank_uop_in;
                shadow_flags_r <= bank_flags_in;
                shadow_valid_r <= 1'b1;
                bank_ack_r     <= 1'b1;
            end

            case (state_r)
                DRAIN_IDLE: begin
                    epilogue_valid_r <= 1'b0;
                    if (shadow_valid_r) begin
                        stage_tile_r      <= shadow_tile_r;
                        stage_bias_r      <= shadow_bias_r;
                        stage_uop_r       <= shadow_uop_r;
                        stage_flags_r     <= shadow_flags_r;
                        shadow_valid_r    <= 1'b0;
                        shadow_hits_r     <= shadow_hits_r + 32'd1;
                        row_ptr_r         <= '0;
                        row_checksum_r    <= '0;
                        row_has_nan_r     <= '0;
                        row_has_inf_r     <= '0;
                        row_all_zero_r    <= '0;
                        row_has_subnorm_r <= '0;
                        state_r           <= DRAIN_PRECHECK;
                    end else if (bank_valid && !bank_ack_r) begin
                        stage_tile_r      <= bank_tile_in;
                        stage_bias_r      <= bank_bias_in;
                        stage_uop_r       <= bank_uop_in;
                        stage_flags_r     <= bank_flags_in;
                        row_ptr_r         <= '0;
                        row_checksum_r    <= '0;
                        row_has_nan_r     <= '0;
                        row_has_inf_r     <= '0;
                        row_all_zero_r    <= '0;
                        row_has_subnorm_r <= '0;
                        bank_ack_r        <= 1'b1;
                        state_r           <= DRAIN_PRECHECK;
                    end
                end

                DRAIN_PRECHECK: begin
                    if (stage_uop_r.fmt_d == TCU_V2_FMT_FP32 || stage_uop_r.fmt_d == TCU_V2_FMT_I32) begin
                        state_r <= DRAIN_STREAM;
                    end else begin
                        state_r <= DRAIN_STREAM;
                    end
                end

                DRAIN_STREAM: begin
                    if (int'(row_ptr_r) < ARRAY_M) begin
                        stage_tile_r[row_ptr_r[$clog2(ARRAY_M)-1:0]]      <= sanitized_row_slice;
                        row_has_nan_r[row_ptr_r[$clog2(ARRAY_M)-1:0]]     <= row_nan_found;
                        row_has_inf_r[row_ptr_r[$clog2(ARRAY_M)-1:0]]     <= row_inf_found;
                        row_all_zero_r[row_ptr_r[$clog2(ARRAY_M)-1:0]]    <= row_all_zero_found;
                        row_has_subnorm_r[row_ptr_r[$clog2(ARRAY_M)-1:0]] <= row_subnorm_found;
                    end
                    row_checksum_r        <= row_checksum_r ^ sanitized_row_slice;
                    rows_streamed_r       <= rows_streamed_r + 32'd1;
                    nan_elems_sanitized_r <= nan_elems_sanitized_r + {28'd0, row_nan_count};
                    inf_elems_seen_r      <= inf_elems_seen_r + {28'd0, row_inf_count};
                    zero_elems_seen_r     <= zero_elems_seen_r + {28'd0, row_zero_count};
                    subnorm_elems_seen_r  <= subnorm_elems_seen_r + {28'd0, row_subnorm_count};

                    if (row_ptr_r < ROW_W'(ARRAY_M - 1)) begin
                        row_ptr_r <= row_ptr_r + ROW_W'(1);
                    end else begin
                        if (epilogue_ready) begin
                            epilogue_valid_r <= 1'b1;
                            state_r          <= DRAIN_COMMIT;
                        end else begin
                            state_r <= DRAIN_SKID;
                        end
                    end
                end

                DRAIN_SKID: begin
                    epilogue_valid_r <= 1'b1;
                    state_r          <= DRAIN_COMMIT;
                end

                DRAIN_COMMIT: begin
                    if (epilogue_fire) begin
                        epilogue_valid_r <= 1'b0;
                        tiles_drained_r  <= tiles_drained_r + 32'd1;
                        if (shadow_valid_r) begin
                            stage_tile_r      <= shadow_tile_r;
                            stage_bias_r      <= shadow_bias_r;
                            stage_uop_r       <= shadow_uop_r;
                            stage_flags_r     <= shadow_flags_r;
                            shadow_valid_r    <= 1'b0;
                            shadow_hits_r     <= shadow_hits_r + 32'd1;
                            row_ptr_r         <= '0;
                            row_checksum_r    <= '0;
                            row_has_nan_r     <= '0;
                            row_has_inf_r     <= '0;
                            row_all_zero_r    <= '0;
                            row_has_subnorm_r <= '0;
                            state_r           <= DRAIN_PRECHECK;
                        end else if (bank_valid && !bank_ack_r) begin
                            stage_tile_r      <= bank_tile_in;
                            stage_bias_r      <= bank_bias_in;
                            stage_uop_r       <= bank_uop_in;
                            stage_flags_r     <= bank_flags_in;
                            row_ptr_r         <= '0;
                            row_checksum_r    <= '0;
                            row_has_nan_r     <= '0;
                            row_has_inf_r     <= '0;
                            row_all_zero_r    <= '0;
                            row_has_subnorm_r <= '0;
                            bank_ack_r        <= 1'b1;
                            state_r           <= DRAIN_PRECHECK;
                        end else begin
                            state_r <= DRAIN_IDLE;
                        end
                    end
                end

                default: begin
                    state_r <= DRAIN_IDLE;
                end
            endcase
        end
    end

    `UNUSED_VAR (shadow_hits_r)
    `UNUSED_VAR (rows_streamed_r)
    `UNUSED_VAR (drain_stall_cycles_r)
    `UNUSED_VAR (nan_elems_sanitized_r)
    `UNUSED_VAR (inf_elems_seen_r)
    `UNUSED_VAR (zero_elems_seen_r)
    `UNUSED_VAR (subnorm_elems_seen_r)
    `UNUSED_VAR (drain_busy_cycles_r)
    `UNUSED_VAR (row_checksum_r)
    `UNUSED_VAR (row_has_nan_r)
    `UNUSED_VAR (row_has_inf_r)
    `UNUSED_VAR (row_all_zero_r)
    `UNUSED_VAR (row_has_subnorm_r)

    assign bank_ack           = bank_ack_r;
    assign epilogue_valid     = epilogue_valid_r;
    assign epilogue_tile_out  = stage_tile_r;
    assign epilogue_bias_out  = stage_bias_r;
    assign epilogue_uop_out   = stage_uop_r;
    assign epilogue_flags_out = stage_flags_r;
    assign drain_row_idx_out  = row_ptr_r;
    assign drain_active_out   = (state_r != DRAIN_IDLE) || shadow_valid_r;
    assign tiles_drained_out  = tiles_drained_r;

endmodule

`endif // VX_TCU_V2_OUTPUT_DRAIN_SV
