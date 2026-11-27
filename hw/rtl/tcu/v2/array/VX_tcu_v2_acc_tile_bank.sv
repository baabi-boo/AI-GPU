// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_ACC_TILE_BANK_SV
`define VX_TCU_V2_ACC_TILE_BANK_SV

`include "VX_platform.vh"

module VX_tcu_v2_acc_tile_bank #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Preload / Zero-Init Control for Active Compute Bank
    input  logic                                    preload_valid,
    input  logic                                    preload_use_c,
    input  logic                                    preload_is_int,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   c_tile_preload,
    // Read-Modify-Write Feedback Port to PE Array
    input  logic                                    rmw_fwd_valid,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   rmw_fwd_tile,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   c_read_tile_out,
    // Writeback Commit Port from PE Array Outputs
    input  logic                                    wb_valid,
    output logic                                    wb_ready,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   wb_tile_in,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t         wb_flags_in,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t              wb_uop_in,
    input  logic [ARRAY_N-1:0][31:0]                wb_bias_in,
    // Bank Swap Handshake with Controller & Drain Unit
    input  logic                                    swap_req,
    output logic                                    swap_ack,
    output logic                                    drain_bank_valid,
    input  logic                                    drain_bank_ack,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   drain_tile_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         drain_flags_out,
    output VX_tcu_v2_pkg::tcu_v2_uop_t              drain_uop_out,
    output logic [ARRAY_N-1:0][31:0]                drain_bias_out,
    output logic                                    active_bank_idx,
    output logic                                    acc_busy_out
);

    import VX_tcu_v2_pkg::*;

    localparam int NUM_BANKS = 2;

    typedef enum logic [1:0] {
        BANK_EMPTY   = 2'd0,
        BANK_ACCUM   = 2'd1,
        BANK_DRAIN   = 2'd2,
        BANK_STALLED = 2'd3
    } acc_bank_state_e;

    // -------------------------------------------------------------------------
    // Dual Accumulator Tile Register Banks & Per-Element Validity Bitmasks
    // -------------------------------------------------------------------------
    logic [NUM_BANKS-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0] tile_mem_r;
    tcu_v2_fp_flags_t                                     flags_mem_r [NUM_BANKS];
    tcu_v2_uop_t                                          meta_mem_r  [NUM_BANKS];
    logic [NUM_BANKS-1:0][ARRAY_N-1:0][31:0]              bias_mem_r;

    acc_bank_state_e      bank_state_r [NUM_BANKS];
    logic [NUM_BANKS-1:0] bank_has_drain_r;
    logic [NUM_BANKS-1:0] bank_is_int_r;
    logic [NUM_BANKS-1:0][ARRAY_M-1:0][ARRAY_N-1:0] elem_valid_r;
    logic [NUM_BANKS-1:0][ARRAY_M-1:0]              row_nonzero_r;
    logic [NUM_BANKS-1:0][ARRAY_N-1:0]              col_nonzero_r;
    logic [NUM_BANKS-1:0][7:0]  bank_desc_id_r;
    logic [NUM_BANKS-1:0][7:0]  bank_k_steps_r;
    logic [NUM_BANKS-1:0]       bank_nan_seen_r;
    logic [NUM_BANKS-1:0]       bank_inf_seen_r;
    logic [NUM_BANKS-1:0][31:0] bank_checksum_r;
    logic [NUM_BANKS-1:0][31:0] bank_bias_sum_r;
    logic [NUM_BANKS-1:0][7:0]  bank_max_exp_r;
    logic [NUM_BANKS-1:0][7:0]  bank_min_exp_r;

    logic                 active_ptr_r;
    logic                 drain_ptr_r;
    logic                 swap_ack_r;
    logic                 active_preloaded_r;
    logic [31:0]          wb_commits_r;
    logic [31:0]          bank_swaps_r;
    logic [31:0]          rmw_fwd_hits_r;
    logic [31:0]          c_preloads_r;
    logic [31:0]          zero_inits_r;
    logic [31:0]          swap_stall_cycles_r;
    logic [31:0]          drain_wait_cycles_r;

    logic                 can_swap;
    logic                 wb_fire;
    logic                 wb_is_int_fmt;
    logic                 wb_any_nan_comb;
    logic                 wb_any_inf_comb;
    logic [ARRAY_M-1:0]   wb_row_nz_comb;
    logic [ARRAY_N-1:0]   wb_col_nz_comb;
    logic [31:0]          wb_xor_checksum_comb;
    logic [31:0]          wb_bias_xor_comb;
    logic [7:0]           wb_max_exp_comb;
    logic [7:0]           wb_min_exp_comb;

    assign wb_is_int_fmt = tcu_v2_fmt_is_int(wb_uop_in.fmt_a) && tcu_v2_fmt_is_int(wb_uop_in.fmt_b);

    // -------------------------------------------------------------------------
    // Writeback Tile Inspection (NaN/Inf Detection, Exponent Spread & Parity)
    // -------------------------------------------------------------------------
    always_comb begin
        wb_any_nan_comb      = 1'b0;
        wb_any_inf_comb      = 1'b0;
        wb_row_nz_comb       = '0;
        wb_col_nz_comb       = '0;
        wb_xor_checksum_comb = 32'd0;
        wb_bias_xor_comb     = 32'd0;
        wb_max_exp_comb      = 8'd0;
        wb_min_exp_comb      = 8'hFF;

        for (int c = 0; c < ARRAY_N; ++c) begin
            wb_bias_xor_comb = wb_bias_xor_comb ^ wb_bias_in[c];
        end

        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                logic [7:0] elem_exp;
                elem_exp             = wb_tile_in[r][c][30:23];
                wb_xor_checksum_comb = wb_xor_checksum_comb ^ wb_tile_in[r][c];
                if (wb_tile_in[r][c] != 32'd0) begin
                    wb_row_nz_comb[r] = 1'b1;
                    wb_col_nz_comb[c] = 1'b1;
                end
                if (!wb_is_int_fmt) begin
                    if (tcu_v2_fp32_is_nan(wb_tile_in[r][c])) begin
                        wb_any_nan_comb = 1'b1;
                    end else if (tcu_v2_fp32_is_inf(wb_tile_in[r][c])) begin
                        wb_any_inf_comb = 1'b1;
                    end else if (!tcu_v2_fp32_is_zero(wb_tile_in[r][c])) begin
                        if (elem_exp > wb_max_exp_comb) begin
                            wb_max_exp_comb = elem_exp;
                        end
                        if (elem_exp < wb_min_exp_comb) begin
                            wb_min_exp_comb = elem_exp;
                        end
                    end
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Forwarding & Preload Multiplexing for Read-Modify-Write C Operand
    // -------------------------------------------------------------------------
    always_comb begin
        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                if (rmw_fwd_valid) begin
                    c_read_tile_out[r][c] = rmw_fwd_tile[r][c];
                end else if (preload_valid) begin
                    if (preload_use_c) begin
                        c_read_tile_out[r][c] = c_tile_preload[r][c];
                    end else begin
                        c_read_tile_out[r][c] = preload_is_int ? 32'd0 : TCU_V2_FP32_POS_ZERO;
                    end
                end else if (elem_valid_r[active_ptr_r][r][c]) begin
                    c_read_tile_out[r][c] = tile_mem_r[active_ptr_r][r][c];
                end else begin
                    c_read_tile_out[r][c] = bank_is_int_r[active_ptr_r] ? 32'd0 : TCU_V2_FP32_POS_ZERO;
                end
            end
        end
    end

    // Swap is allowed when the target inactive bank is not pending drain
    assign can_swap = swap_req && !bank_has_drain_r[~active_ptr_r];
    assign wb_ready = !bank_has_drain_r[active_ptr_r];
    assign wb_fire  = wb_valid && wb_ready;

    // -------------------------------------------------------------------------
    // Sequential Bank State Machine & Double-Buffered Accumulator Storage
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (reset) begin
            active_ptr_r        <= 1'b0;
            drain_ptr_r         <= 1'b1;
            bank_has_drain_r    <= 2'b00;
            bank_is_int_r       <= 2'b00;
            elem_valid_r        <= '0;
            row_nonzero_r       <= '0;
            col_nonzero_r       <= '0;
            bank_desc_id_r      <= '0;
            bank_k_steps_r      <= '0;
            bank_nan_seen_r     <= 2'b00;
            bank_inf_seen_r     <= 2'b00;
            bank_checksum_r     <= '0;
            bank_bias_sum_r     <= '0;
            bank_max_exp_r      <= '0;
            bank_min_exp_r      <= '0;
            swap_ack_r          <= 1'b0;
            active_preloaded_r  <= 1'b0;
            wb_commits_r        <= 32'd0;
            bank_swaps_r        <= 32'd0;
            rmw_fwd_hits_r      <= 32'd0;
            c_preloads_r        <= 32'd0;
            zero_inits_r        <= 32'd0;
            swap_stall_cycles_r <= 32'd0;
            drain_wait_cycles_r <= 32'd0;
            for (int bk = 0; bk < NUM_BANKS; ++bk) begin
                bank_state_r[bk] <= BANK_EMPTY;
                tile_mem_r[bk]   <= '0;
                flags_mem_r[bk]  <= '0;
                meta_mem_r[bk]   <= '0;
                bias_mem_r[bk]   <= '0;
            end
        end else begin
            swap_ack_r <= 1'b0;

            if (rmw_fwd_valid) begin
                rmw_fwd_hits_r <= rmw_fwd_hits_r + 32'd1;
            end

            if (bank_has_drain_r[drain_ptr_r] && !drain_bank_ack) begin
                drain_wait_cycles_r <= drain_wait_cycles_r + 32'd1;
            end

            if (swap_req && !can_swap) begin
                swap_stall_cycles_r         <= swap_stall_cycles_r + 32'd1;
                bank_state_r[~active_ptr_r] <= BANK_STALLED;
            end

            if (preload_valid && !wb_fire) begin
                for (int r = 0; r < ARRAY_M; ++r) begin
                    for (int c = 0; c < ARRAY_N; ++c) begin
                        if (preload_use_c) begin
                            tile_mem_r[active_ptr_r][r][c] <= c_tile_preload[r][c];
                        end else begin
                            tile_mem_r[active_ptr_r][r][c] <= preload_is_int ? 32'd0 : TCU_V2_FP32_POS_ZERO;
                        end
                        elem_valid_r[active_ptr_r][r][c] <= 1'b1;
                    end
                end
                flags_mem_r[active_ptr_r]     <= '0;
                bank_is_int_r[active_ptr_r]   <= preload_is_int;
                bank_k_steps_r[active_ptr_r]  <= 8'd0;
                bank_nan_seen_r[active_ptr_r] <= 1'b0;
                bank_inf_seen_r[active_ptr_r] <= 1'b0;
                bank_max_exp_r[active_ptr_r]  <= 8'd0;
                bank_min_exp_r[active_ptr_r]  <= 8'hFF;
                bank_state_r[active_ptr_r]    <= BANK_ACCUM;
                active_preloaded_r            <= 1'b1;
                if (preload_use_c) begin
                    c_preloads_r <= c_preloads_r + 32'd1;
                end else begin
                    zero_inits_r <= zero_inits_r + 32'd1;
                end
            end

            if (wb_fire) begin
                tile_mem_r[active_ptr_r]      <= wb_tile_in;
                elem_valid_r[active_ptr_r]    <= '1;
                row_nonzero_r[active_ptr_r]   <= wb_row_nz_comb;
                col_nonzero_r[active_ptr_r]   <= wb_col_nz_comb;
                bank_desc_id_r[active_ptr_r]  <= wb_uop_in.desc_id;
                bank_checksum_r[active_ptr_r] <= wb_xor_checksum_comb;
                bank_bias_sum_r[active_ptr_r] <= wb_bias_xor_comb;
                bank_max_exp_r[active_ptr_r]  <= wb_max_exp_comb;
                bank_min_exp_r[active_ptr_r]  <= wb_min_exp_comb;
                if (wb_uop_in.is_first_k) begin
                    flags_mem_r[active_ptr_r]     <= wb_flags_in;
                    bank_k_steps_r[active_ptr_r]  <= 8'd1;
                    bank_nan_seen_r[active_ptr_r] <= wb_any_nan_comb;
                    bank_inf_seen_r[active_ptr_r] <= wb_any_inf_comb;
                end else begin
                    flags_mem_r[active_ptr_r]     <= tcu_v2_flags_or(flags_mem_r[active_ptr_r], wb_flags_in);
                    bank_k_steps_r[active_ptr_r]  <= bank_k_steps_r[active_ptr_r] + 8'd1;
                    bank_nan_seen_r[active_ptr_r] <= bank_nan_seen_r[active_ptr_r] || wb_any_nan_comb;
                    bank_inf_seen_r[active_ptr_r] <= bank_inf_seen_r[active_ptr_r] || wb_any_inf_comb;
                end
                meta_mem_r[active_ptr_r]    <= wb_uop_in;
                bias_mem_r[active_ptr_r]    <= wb_bias_in;
                bank_is_int_r[active_ptr_r] <= wb_is_int_fmt;
                bank_state_r[active_ptr_r]  <= BANK_ACCUM;
                active_preloaded_r          <= 1'b1;
                wb_commits_r                <= wb_commits_r + 32'd1;
            end

            if (drain_bank_ack && bank_has_drain_r[drain_ptr_r]) begin
                bank_has_drain_r[drain_ptr_r] <= 1'b0;
                elem_valid_r[drain_ptr_r]     <= '0;
                row_nonzero_r[drain_ptr_r]    <= '0;
                col_nonzero_r[drain_ptr_r]    <= '0;
                bank_state_r[drain_ptr_r]     <= BANK_EMPTY;
            end

            if (can_swap) begin
                bank_has_drain_r[active_ptr_r] <= 1'b1;
                bank_state_r[active_ptr_r]     <= BANK_DRAIN;
                drain_ptr_r                    <= active_ptr_r;
                active_ptr_r                   <= ~active_ptr_r;
                active_preloaded_r             <= 1'b0;
                swap_ack_r                     <= 1'b1;
                bank_swaps_r                   <= bank_swaps_r + 32'd1;
            end
        end
    end

    `UNUSED_VAR (bank_state_r[0])
    `UNUSED_VAR (bank_state_r[1])
    `UNUSED_VAR (row_nonzero_r)
    `UNUSED_VAR (col_nonzero_r)
    `UNUSED_VAR (bank_desc_id_r)
    `UNUSED_VAR (bank_k_steps_r)
    `UNUSED_VAR (bank_nan_seen_r)
    `UNUSED_VAR (bank_inf_seen_r)
    `UNUSED_VAR (bank_checksum_r)
    `UNUSED_VAR (bank_bias_sum_r)
    `UNUSED_VAR (bank_max_exp_r)
    `UNUSED_VAR (bank_min_exp_r)
    `UNUSED_VAR (wb_commits_r)
    `UNUSED_VAR (bank_swaps_r)
    `UNUSED_VAR (rmw_fwd_hits_r)
    `UNUSED_VAR (c_preloads_r)
    `UNUSED_VAR (zero_inits_r)
    `UNUSED_VAR (swap_stall_cycles_r)
    `UNUSED_VAR (drain_wait_cycles_r)

    assign swap_ack         = swap_ack_r;
    assign drain_bank_valid = bank_has_drain_r[drain_ptr_r];
    assign drain_tile_out   = tile_mem_r[drain_ptr_r];
    assign drain_flags_out  = flags_mem_r[drain_ptr_r];
    assign drain_uop_out    = meta_mem_r[drain_ptr_r];
    assign drain_bias_out   = bias_mem_r[drain_ptr_r];
    assign active_bank_idx  = active_ptr_r;
    assign acc_busy_out     = (|bank_has_drain_r) || active_preloaded_r;

endmodule

`endif // VX_TCU_V2_ACC_TILE_BANK_SV
