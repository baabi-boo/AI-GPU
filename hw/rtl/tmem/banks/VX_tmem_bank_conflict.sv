// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_bank_conflict #(
    parameter int LANES     = 8,
    parameter int NUM_BANKS = VX_tmem_pkg::TMEM_NUM_BANKS,
    parameter int IS_WRITE  = 0
) (
    input  logic                                               clk,
    input  logic                                               reset,
    // Incoming lane requests (already swizzle-translated to bank_id + word_addr)
    input  logic [LANES-1:0]                                   req_valid,
    output logic [LANES-1:0]                                   req_ready,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]  req_bank_id,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] req_word_addr,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]  req_wr_data,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_WIDTH_BYTES-1:0] req_wr_be,
    input  logic [LANES-1:0]                                   req_half_sel,
    // Downstream bank availability mask (e.g., power/RMW ready)
    input  logic [NUM_BANKS-1:0]                               bank_ready_mask,
    // Conflict-free issued wavefront toward crossbar
    output logic [LANES-1:0]                                   grant_valid,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]  grant_bank_id,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] grant_word_addr,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]  grant_wr_data,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_WIDTH_BYTES-1:0] grant_wr_be,
    output logic [LANES-1:0]                                   grant_half_sel,
    output logic [LANES-1:0]                                   grant_lane_idx_valid,
    // Conflict telemetry
    output logic [5:0]                                         conflict_ways_out,
    output logic                                               conflict_detected_out,
    output logic                                               serializer_busy_out,
    output logic [31:0]                                        conflict_cycles_count
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(LANES >= 1 && LANES <= 32, ("LANES must be in [1, 32]"))
    `STATIC_ASSERT(NUM_BANKS == 32, ("Expected 32 banks"))

    // Deferred lane buffer holds ungranted lanes from the current wavefront until drained
    logic [LANES-1:0]                             buf_valid_q;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]         buf_bank_id_q;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]       buf_word_addr_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        buf_wr_data_q;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0]  buf_wr_be_q;
    logic [LANES-1:0]                             buf_half_sel_q;

    // Rotating priority pointer ensures starvation-free fairness across deferred lanes
    localparam int LANE_W = `CLOG2(LANES);
    logic [LANE_W-1:0]                            prio_ptr_q;
    logic [31:0]                                  conflict_cycles_q;
    logic [31:0]                                  wavefronts_accepted_q;
    logic [31:0]                                  wavefronts_serialized_q;
    logic [31:0]                                  total_lanes_granted_q;
    logic [31:0]                                  total_lanes_coalesced_q;
    logic [31:0]                                  bank_stall_cycles_q;
    logic [5:0]                                   max_ways_observed_q;
    logic [7:0][31:0]                             ways_histogram_q;

    // Active candidate vector: either buffered deferred lanes or fresh incoming requests
    logic                                         has_deferred;
    logic [LANES-1:0]                             cand_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]         cand_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]       cand_word_addr;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        cand_wr_data;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0]  cand_wr_be;
    logic [LANES-1:0]                             cand_half_sel;

    assign has_deferred = |buf_valid_q;

    always_comb begin
        if (has_deferred) begin
            cand_valid     = buf_valid_q;
            cand_bank_id   = buf_bank_id_q;
            cand_word_addr = buf_word_addr_q;
            cand_wr_data   = buf_wr_data_q;
            cand_wr_be     = buf_wr_be_q;
            cand_half_sel  = buf_half_sel_q;
        end else begin
            cand_valid     = req_valid;
            cand_bank_id   = req_bank_id;
            cand_word_addr = req_word_addr;
            cand_wr_data   = req_wr_data;
            cand_wr_be     = req_wr_be;
            cand_half_sel  = req_half_sel;
        end
    end

    // Compute per-bank hit counts across the candidate wavefront
    logic [NUM_BANKS-1:0][5:0]                    bank_hit_count;
    logic [5:0]                                   max_bank_hits;
    logic [5:0]                                   distinct_banks_hit;
    logic [5:0]                                   active_cand_count;

    always_comb begin
        distinct_banks_hit = 6'd0;
        active_cand_count  = 6'd0;

        for (int l = 0; l < LANES; ++l) begin
            if (cand_valid[l]) begin
                active_cand_count = active_cand_count + 6'd1;
            end
        end

        for (int b = 0; b < NUM_BANKS; ++b) begin
            bank_hit_count[b] = 6'd0;

            for (int l = 0; l < LANES; ++l) begin
                if (cand_valid[l] && (cand_bank_id[l] == 5'(b))) begin
                    bank_hit_count[b] = bank_hit_count[b] + 6'd1;
                end
            end

            if (bank_hit_count[b] > 6'd0) begin
                distinct_banks_hit = distinct_banks_hit + 6'd1;
            end
        end

        max_bank_hits = 6'd0;
        for (int b = 0; b < NUM_BANKS; ++b) begin
            if (bank_hit_count[b] > max_bank_hits) begin
                max_bank_hits = bank_hit_count[b];
            end
        end
    end

    `UNUSED_VAR (distinct_banks_hit)
    `UNUSED_VAR (active_cand_count)

    // Coalescing / serialization rules:
    // - For READ ports (IS_WRITE == 0): lanes targeting the SAME bank AND SAME word_addr
    //   broadcast-coalesce into 1 bank read and are granted together on the same cycle.
    //   Lanes targeting the SAME bank with DIFFERENT word_addr conflict and serialize.
    // - For WRITE ports (IS_WRITE == 1): lanes targeting the SAME bank AND SAME word_addr
    //   with DISJOINT byte-enables merge in the write crossbar and are granted together;
    //   overlapping byte-enables or different word_addr on the same bank conflict and serialize.
    logic [LANES-1:0]                             comb_grant;
    logic [LANES-1:0]                             comb_defer;
    logic [LANES-1:0]                             comb_bank_not_ready;
    logic [NUM_BANKS-1:0]                         bank_claimed;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]   bank_claimed_word;
    logic [NUM_BANKS-1:0][TMEM_BANK_WIDTH_BYTES-1:0] bank_claimed_be;
    logic                                         any_defer;
    logic                                         any_bank_not_ready;
    logic [5:0]                                   granted_lanes_cycle;
    logic [5:0]                                   coalesced_lanes_cycle;

    always_comb begin
        comb_grant            = '0;
        comb_bank_not_ready   = '0;
        bank_claimed          = '0;
        bank_claimed_word     = '0;
        bank_claimed_be       = '0;
        granted_lanes_cycle   = 6'd0;
        coalesced_lanes_cycle = 6'd0;

        for (int offset = 0; offset < LANES; ++offset) begin
            int idx;
            logic [TMEM_BANK_ID_W-1:0]        b_id;
            logic [TMEM_BANK_ADDR_W-1:0]      w_addr;
            logic [TMEM_BANK_WIDTH_BYTES-1:0] w_be;
            logic                             can_coalesce_rd;
            logic                             can_merge_wr;

            idx             = (int'(prio_ptr_q) + offset) % LANES;
            b_id            = cand_bank_id[idx];
            w_addr          = cand_word_addr[idx];
            w_be            = cand_wr_be[idx];
            can_coalesce_rd = (IS_WRITE == 0);
            can_merge_wr    = (IS_WRITE != 0) && ((bank_claimed_be[b_id] & w_be) == 8'd0);

            if (cand_valid[idx]) begin
                if (!bank_ready_mask[b_id]) begin
                    comb_bank_not_ready[idx] = 1'b1;
                end else if (!bank_claimed[b_id]) begin
                    comb_grant[idx]         = 1'b1;
                    bank_claimed[b_id]      = 1'b1;
                    bank_claimed_word[b_id] = w_addr;
                    bank_claimed_be[b_id]   = w_be;
                    granted_lanes_cycle     = granted_lanes_cycle + 6'd1;
                end else if (bank_claimed_word[b_id] == w_addr) begin
                    if (can_coalesce_rd || can_merge_wr) begin
                        comb_grant[idx]           = 1'b1;
                        bank_claimed_be[b_id]     = bank_claimed_be[b_id] | w_be;
                        granted_lanes_cycle       = granted_lanes_cycle + 6'd1;
                        coalesced_lanes_cycle     = coalesced_lanes_cycle + 6'd1;
                    end
                end
            end
        end
    end

    assign comb_defer         = cand_valid & (~comb_grant);
    assign any_defer          = |comb_defer;
    assign any_bank_not_ready = |comb_bank_not_ready;

    // Ready backpressure: accept new request wavefront only when deferred buffer is empty.
    always_comb begin
        if (has_deferred) begin
            req_ready = {LANES{1'b0}};
        end else begin
            req_ready = {LANES{1'b1}};
        end
    end

    // Estimate remaining serialization cycles for active wavefront
    logic [5:0] deferred_lane_count;
    always_comb begin
        deferred_lane_count = 6'd0;
        for (int l = 0; l < LANES; ++l) begin
            if (comb_defer[l]) begin
                deferred_lane_count = deferred_lane_count + 6'd1;
            end
        end
    end
    `UNUSED_VAR (deferred_lane_count)

    always_ff @(posedge clk) begin
        if (reset) begin
            buf_valid_q             <= '0;
            buf_bank_id_q           <= '0;
            buf_word_addr_q         <= '0;
            buf_wr_data_q           <= '0;
            buf_wr_be_q             <= '0;
            buf_half_sel_q          <= '0;
            prio_ptr_q              <= '0;
            conflict_cycles_q       <= 32'd0;
            wavefronts_accepted_q   <= 32'd0;
            wavefronts_serialized_q <= 32'd0;
            total_lanes_granted_q   <= 32'd0;
            total_lanes_coalesced_q <= 32'd0;
            bank_stall_cycles_q     <= 32'd0;
            max_ways_observed_q     <= 6'd0;
            ways_histogram_q        <= '0;
        end else begin
            if (has_deferred) begin
                buf_valid_q <= comb_defer;
                if (!any_defer) begin
                    prio_ptr_q <= prio_ptr_q + LANE_W'(1);
                end
            end else if (|req_valid) begin
                wavefronts_accepted_q <= wavefronts_accepted_q + 32'd1;
                buf_valid_q           <= comb_defer;
                buf_bank_id_q         <= req_bank_id;
                buf_word_addr_q       <= req_word_addr;
                buf_wr_data_q         <= req_wr_data;
                buf_wr_be_q           <= req_wr_be;
                buf_half_sel_q        <= req_half_sel;
                if (any_defer) begin
                    prio_ptr_q              <= prio_ptr_q + LANE_W'(1);
                    wavefronts_serialized_q <= wavefronts_serialized_q + 32'd1;
                end
                if (max_bank_hits <= 6'd7) begin
                    ways_histogram_q[max_bank_hits[2:0]] <= ways_histogram_q[max_bank_hits[2:0]] + 32'd1;
                end else begin
                    ways_histogram_q[7] <= ways_histogram_q[7] + 32'd1;
                end
            end else begin
                buf_valid_q <= '0;
            end

            if (any_defer) begin
                conflict_cycles_q <= conflict_cycles_q + 32'd1;
            end
            if (any_bank_not_ready) begin
                bank_stall_cycles_q <= bank_stall_cycles_q + 32'd1;
            end
            total_lanes_granted_q   <= total_lanes_granted_q + {26'd0, granted_lanes_cycle};
            total_lanes_coalesced_q <= total_lanes_coalesced_q + {26'd0, coalesced_lanes_cycle};
            if (max_bank_hits > max_ways_observed_q) begin
                max_ways_observed_q <= max_bank_hits;
            end
        end
    end

    `UNUSED_VAR (wavefronts_accepted_q)
    `UNUSED_VAR (wavefronts_serialized_q)
    `UNUSED_VAR (total_lanes_granted_q)
    `UNUSED_VAR (total_lanes_coalesced_q)
    `UNUSED_VAR (bank_stall_cycles_q)
    `UNUSED_VAR (max_ways_observed_q)
    `UNUSED_VAR (ways_histogram_q)

    assign grant_valid           = comb_grant;
    assign grant_bank_id         = cand_bank_id;
    assign grant_word_addr       = cand_word_addr;
    assign grant_wr_data         = cand_wr_data;
    assign grant_wr_be           = cand_wr_be;
    assign grant_half_sel        = cand_half_sel;
    assign grant_lane_idx_valid  = comb_grant;

    // Report raw max bank collision degree across the candidate wavefront
    assign conflict_ways_out     = max_bank_hits;
    assign conflict_detected_out = (max_bank_hits > 6'd1);
    assign serializer_busy_out   = has_deferred;
    assign conflict_cycles_count = conflict_cycles_q;

endmodule
