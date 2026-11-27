// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_OPERAND_DBUF_SV
`define VX_TCU_V2_OPERAND_DBUF_SV

`include "VX_platform.vh"

module VX_tcu_v2_operand_dbuf #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Producer Load Side (Next K-Tile Ingestion)
    input  logic                                    load_valid,
    output logic                                    load_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t              load_uop,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      load_a_tile,
    input  logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      load_b_tile,
    input  logic [ARRAY_M-1:0][7:0]                 load_scale_a,
    input  logic [ARRAY_N-1:0][7:0]                 load_scale_b,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   load_c_tile,
    input  logic [ARRAY_N-1:0][31:0]                load_bias,
    // Consumer Compute Side (Active K-Tile Execution)
    output logic                                    exec_valid,
    input  logic                                    exec_ready,
    output VX_tcu_v2_pkg::tcu_v2_uop_t              exec_uop,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      exec_a_tile,
    output logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      exec_b_tile,
    output logic [ARRAY_M-1:0][7:0]                 exec_scale_a,
    output logic [ARRAY_N-1:0][7:0]                 exec_scale_b,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   exec_c_tile,
    output logic [ARRAY_N-1:0][31:0]                exec_bias,
    // Controller Coordination & Status
    input  logic                                    swap_req,
    output logic                                    swap_ack,
    output logic                                    wr_bank_idx,
    output logic                                    rd_bank_idx,
    output logic [1:0]                              banks_full_mask,
    output logic                                    dbuf_busy,
    output logic [31:0]                             prefetch_hits_out
);

    import VX_tcu_v2_pkg::*;

    localparam int NUM_BANKS = 2;

    typedef enum logic [1:0] {
        DBUF_EMPTY  = 2'd0,
        DBUF_LOADED = 2'd1,
        DBUF_ACTIVE = 2'd2,
        DBUF_STALE  = 2'd3
    } dbuf_bank_state_e;

    // -------------------------------------------------------------------------
    // Input Skid Staging Register + Dual Ping-Pong Storage Banks
    // -------------------------------------------------------------------------
    logic                                    skid_valid_r;
    tcu_v2_uop_t                             skid_uop_r;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      skid_a_tile_r;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      skid_b_tile_r;
    logic [ARRAY_M-1:0][7:0]                 skid_scale_a_r;
    logic [ARRAY_N-1:0][7:0]                 skid_scale_b_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   skid_c_tile_r;
    logic [ARRAY_N-1:0][31:0]                skid_bias_r;

    tcu_v2_uop_t                                          uop_bank_r [NUM_BANKS];
    logic [NUM_BANKS-1:0][ARRAY_M-1:0][ARRAY_K*32-1:0]    a_bank_r;
    logic [NUM_BANKS-1:0][ARRAY_N-1:0][ARRAY_K*32-1:0]    b_bank_r;
    logic [NUM_BANKS-1:0][ARRAY_M-1:0][7:0]               scale_a_bank_r;
    logic [NUM_BANKS-1:0][ARRAY_N-1:0][7:0]               scale_b_bank_r;
    logic [NUM_BANKS-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0] c_bank_r;
    logic [NUM_BANKS-1:0][ARRAY_N-1:0][31:0]              bias_bank_r;

    dbuf_bank_state_e                  bank_state_r [NUM_BANKS];
    logic [NUM_BANKS-1:0]              bank_valid_r;
    logic [NUM_BANKS-1:0]              bank_locked_r;
    logic [NUM_BANKS-1:0]              bank_c_loaded_r;
    logic [NUM_BANKS-1:0]              bank_bias_loaded_r;
    logic [NUM_BANKS-1:0]              bank_sparse_r;
    logic [NUM_BANKS-1:0]              bank_first_k_r;
    logic [NUM_BANKS-1:0]              bank_last_k_r;
    logic [NUM_BANKS-1:0][ARRAY_M-1:0] bank_a_nonzero_r;
    logic [NUM_BANKS-1:0][ARRAY_N-1:0] bank_b_nonzero_r;
    logic [NUM_BANKS-1:0][31:0]        bank_parity_r;
    logic [NUM_BANKS-1:0][15:0]        bank_age_r;

    logic                 wr_ptr_r;
    logic                 rd_ptr_r;
    logic                 swap_ack_r;
    logic [31:0]          prefetch_hits_r;
    logic [31:0]          total_loads_r;
    logic [31:0]          total_execs_r;
    logic [31:0]          backpressure_cycles_r;
    logic [31:0]          dual_full_cycles_r;
    logic [31:0]          starvation_cycles_r;
    logic [31:0]          skid_captures_r;
    logic [31:0]          swap_requests_r;

    logic                 bank_wr_ready;
    logic                 stage_load_valid;
    tcu_v2_uop_t          stage_uop;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0]    stage_a_tile;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0]    stage_b_tile;
    logic [ARRAY_M-1:0][7:0]               stage_scale_a;
    logic [ARRAY_N-1:0][7:0]               stage_scale_b;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] stage_c_tile;
    logic [ARRAY_N-1:0][31:0]              stage_bias;

    logic                 load_fire;
    logic                 exec_fire;
    logic                 can_swap;
    logic                 concurrent_overlap;
    logic                 fmt_load_valid;
    logic [ARRAY_M-1:0]   load_a_nz_comb;
    logic [ARRAY_N-1:0]   load_b_nz_comb;
    logic [31:0]          load_parity_comb;

    // Input skid buffer isolates producer ready from dual-bank full status
    assign bank_wr_ready = !bank_valid_r[wr_ptr_r];
    assign load_ready    = !skid_valid_r;

    always_comb begin
        if (skid_valid_r) begin
            stage_load_valid = 1'b1;
            stage_uop        = skid_uop_r;
            stage_a_tile     = skid_a_tile_r;
            stage_b_tile     = skid_b_tile_r;
            stage_scale_a    = skid_scale_a_r;
            stage_scale_b    = skid_scale_b_r;
            stage_c_tile     = skid_c_tile_r;
            stage_bias       = skid_bias_r;
        end else begin
            stage_load_valid = load_valid;
            stage_uop        = load_uop;
            stage_a_tile     = load_a_tile;
            stage_b_tile     = load_b_tile;
            stage_scale_a    = load_scale_a;
            stage_scale_b    = load_scale_b;
            stage_c_tile     = load_c_tile;
            stage_bias       = load_bias;
        end
    end

    assign exec_valid         = bank_valid_r[rd_ptr_r];
    assign load_fire          = stage_load_valid && bank_wr_ready;
    assign exec_fire          = exec_valid && exec_ready;
    assign can_swap           = swap_req && !bank_locked_r[rd_ptr_r];
    assign concurrent_overlap = load_fire && exec_valid;
    assign fmt_load_valid     = (tcu_v2_fmt_bitwidth(stage_uop.fmt_a) != 0) &&
                                (tcu_v2_fmt_bitwidth(stage_uop.fmt_b) != 0);

    // Compute per-row/column non-zero occupancy & parity digest on tile load
    always_comb begin
        load_parity_comb = {24'd0, stage_uop.desc_id} ^ {24'd0, stage_uop.step_k};
        for (int r = 0; r < ARRAY_M; ++r) begin
            load_a_nz_comb[r] = (stage_a_tile[r] != '0);
            load_parity_comb  = load_parity_comb ^ stage_a_tile[r][31:0] ^ {24'd0, stage_scale_a[r]};
        end
        for (int c = 0; c < ARRAY_N; ++c) begin
            load_b_nz_comb[c] = (stage_b_tile[c] != '0);
            load_parity_comb  = load_parity_comb ^ stage_b_tile[c][31:0] ^ {24'd0, stage_scale_b[c]};
        end
    end

    // -------------------------------------------------------------------------
    // Sequential Ping-Pong Bank Management & Telemetry Counters
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (reset) begin
            skid_valid_r          <= 1'b0;
            skid_uop_r            <= '0;
            skid_a_tile_r         <= '0;
            skid_b_tile_r         <= '0;
            skid_scale_a_r        <= '0;
            skid_scale_b_r        <= '0;
            skid_c_tile_r         <= '0;
            skid_bias_r           <= '0;
            wr_ptr_r              <= 1'b0;
            rd_ptr_r              <= 1'b0;
            bank_valid_r          <= 2'b00;
            bank_locked_r         <= 2'b00;
            bank_c_loaded_r       <= 2'b00;
            bank_bias_loaded_r    <= 2'b00;
            bank_sparse_r         <= 2'b00;
            bank_first_k_r        <= 2'b00;
            bank_last_k_r         <= 2'b00;
            bank_a_nonzero_r      <= '0;
            bank_b_nonzero_r      <= '0;
            bank_parity_r         <= '0;
            bank_age_r            <= '0;
            swap_ack_r            <= 1'b0;
            prefetch_hits_r       <= 32'd0;
            total_loads_r         <= 32'd0;
            total_execs_r         <= 32'd0;
            backpressure_cycles_r <= 32'd0;
            dual_full_cycles_r    <= 32'd0;
            starvation_cycles_r   <= 32'd0;
            skid_captures_r       <= 32'd0;
            swap_requests_r       <= 32'd0;
            for (int bk = 0; bk < NUM_BANKS; ++bk) begin
                bank_state_r[bk]   <= DBUF_EMPTY;
                uop_bank_r[bk]     <= '0;
                a_bank_r[bk]       <= '0;
                b_bank_r[bk]       <= '0;
                scale_a_bank_r[bk] <= '0;
                scale_b_bank_r[bk] <= '0;
                c_bank_r[bk]       <= '0;
                bias_bank_r[bk]    <= '0;
            end
        end else begin
            swap_ack_r <= 1'b0;

            if (load_valid && !load_ready) begin
                backpressure_cycles_r <= backpressure_cycles_r + 32'd1;
            end
            if (&bank_valid_r) begin
                dual_full_cycles_r <= dual_full_cycles_r + 32'd1;
            end
            if (!exec_valid && exec_ready) begin
                starvation_cycles_r <= starvation_cycles_r + 32'd1;
            end
            if (swap_req) begin
                swap_requests_r <= swap_requests_r + 32'd1;
            end

            for (int bk = 0; bk < NUM_BANKS; ++bk) begin
                if (bank_valid_r[bk]) begin
                    bank_age_r[bk] <= bank_age_r[bk] + 16'd1;
                end else begin
                    bank_age_r[bk] <= 16'd0;
                end
            end

            // Skid buffer capture when both banks are occupied
            if (load_valid && load_ready && !bank_wr_ready) begin
                skid_valid_r    <= 1'b1;
                skid_uop_r      <= load_uop;
                skid_a_tile_r   <= load_a_tile;
                skid_b_tile_r   <= load_b_tile;
                skid_scale_a_r  <= load_scale_a;
                skid_scale_b_r  <= load_scale_b;
                skid_c_tile_r   <= load_c_tile;
                skid_bias_r     <= load_bias;
                skid_captures_r <= skid_captures_r + 32'd1;
            end else if (skid_valid_r && bank_wr_ready) begin
                skid_valid_r <= 1'b0;
            end

            if (load_fire) begin
                uop_bank_r[wr_ptr_r]       <= stage_uop;
                a_bank_r[wr_ptr_r]         <= stage_a_tile;
                b_bank_r[wr_ptr_r]         <= stage_b_tile;
                scale_a_bank_r[wr_ptr_r]   <= stage_scale_a;
                scale_b_bank_r[wr_ptr_r]   <= stage_scale_b;
                bank_sparse_r[wr_ptr_r]    <= stage_uop.sparse_en;
                bank_first_k_r[wr_ptr_r]   <= stage_uop.is_first_k;
                bank_last_k_r[wr_ptr_r]    <= stage_uop.is_last_k;
                bank_a_nonzero_r[wr_ptr_r] <= load_a_nz_comb;
                bank_b_nonzero_r[wr_ptr_r] <= load_b_nz_comb;
                bank_parity_r[wr_ptr_r]    <= load_parity_comb;
                bank_age_r[wr_ptr_r]       <= 16'd0;
                total_loads_r              <= total_loads_r + 32'd1;

                if (stage_uop.is_first_k && stage_uop.accum_en) begin
                    c_bank_r[wr_ptr_r]        <= stage_c_tile;
                    bank_c_loaded_r[wr_ptr_r] <= 1'b1;
                end else begin
                    c_bank_r[wr_ptr_r]        <= '0;
                    bank_c_loaded_r[wr_ptr_r] <= 1'b0;
                end

                if (stage_uop.is_last_k && stage_uop.bias_en) begin
                    bias_bank_r[wr_ptr_r]        <= stage_bias;
                    bank_bias_loaded_r[wr_ptr_r] <= 1'b1;
                end else begin
                    bias_bank_r[wr_ptr_r]        <= '0;
                    bank_bias_loaded_r[wr_ptr_r] <= 1'b0;
                end

                bank_valid_r[wr_ptr_r] <= 1'b1;
                bank_state_r[wr_ptr_r] <= DBUF_LOADED;
                wr_ptr_r               <= ~wr_ptr_r;

                if (concurrent_overlap) begin
                    prefetch_hits_r <= prefetch_hits_r + 32'd1;
                end
            end

            if (exec_fire) begin
                bank_valid_r[rd_ptr_r]       <= 1'b0;
                bank_locked_r[rd_ptr_r]      <= 1'b0;
                bank_c_loaded_r[rd_ptr_r]    <= 1'b0;
                bank_bias_loaded_r[rd_ptr_r] <= 1'b0;
                bank_first_k_r[rd_ptr_r]     <= 1'b0;
                bank_last_k_r[rd_ptr_r]      <= 1'b0;
                bank_state_r[rd_ptr_r]       <= DBUF_EMPTY;
                rd_ptr_r                     <= ~rd_ptr_r;
                total_execs_r                <= total_execs_r + 32'd1;
            end else if (exec_valid && !exec_ready) begin
                bank_locked_r[rd_ptr_r] <= 1'b1;
                bank_state_r[rd_ptr_r]  <= DBUF_ACTIVE;
            end

            if (can_swap && !exec_fire) begin
                bank_state_r[rd_ptr_r] <= DBUF_STALE;
                rd_ptr_r               <= ~rd_ptr_r;
                swap_ack_r             <= 1'b1;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Active Read Bank Multiplexing & Telemetry Outputs
    // -------------------------------------------------------------------------
    `UNUSED_VAR (fmt_load_valid)
    `UNUSED_VAR (bank_state_r[0])
    `UNUSED_VAR (bank_state_r[1])
    `UNUSED_VAR (bank_c_loaded_r)
    `UNUSED_VAR (bank_bias_loaded_r)
    `UNUSED_VAR (bank_sparse_r)
    `UNUSED_VAR (bank_first_k_r)
    `UNUSED_VAR (bank_last_k_r)
    `UNUSED_VAR (bank_a_nonzero_r)
    `UNUSED_VAR (bank_b_nonzero_r)
    `UNUSED_VAR (bank_parity_r)
    `UNUSED_VAR (bank_age_r)
    `UNUSED_VAR (total_loads_r)
    `UNUSED_VAR (total_execs_r)
    `UNUSED_VAR (backpressure_cycles_r)
    `UNUSED_VAR (dual_full_cycles_r)
    `UNUSED_VAR (starvation_cycles_r)
    `UNUSED_VAR (skid_captures_r)
    `UNUSED_VAR (swap_requests_r)

    assign exec_uop     = uop_bank_r[rd_ptr_r];
    assign exec_a_tile  = a_bank_r[rd_ptr_r];
    assign exec_b_tile  = b_bank_r[rd_ptr_r];
    assign exec_scale_a = scale_a_bank_r[rd_ptr_r];
    assign exec_scale_b = scale_b_bank_r[rd_ptr_r];
    assign exec_c_tile  = c_bank_r[rd_ptr_r];
    assign exec_bias    = bias_bank_r[rd_ptr_r];

    assign swap_ack          = swap_ack_r;
    assign wr_bank_idx       = wr_ptr_r;
    assign rd_bank_idx       = rd_ptr_r;
    assign banks_full_mask   = bank_valid_r;
    assign dbuf_busy         = (|bank_valid_r) || skid_valid_r;
    assign prefetch_hits_out = prefetch_hits_r;

endmodule

`endif // VX_TCU_V2_OPERAND_DBUF_SV
