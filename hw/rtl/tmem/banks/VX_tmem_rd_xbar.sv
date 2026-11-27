// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_rd_xbar #(
    parameter int LANES      = 8,
    parameter int NUM_BANKS  = VX_tmem_pkg::TMEM_NUM_BANKS,
    parameter int BANK_LAT   = 1
) (
    input  logic                                               clk,
    input  logic                                               reset,
    // Granted lane read requests from conflict serializer
    input  logic [LANES-1:0]                                   lane_req_valid,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]  lane_req_bank_id,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] lane_req_word_addr,
    // Bank-side read requests (to 32 banks)
    output logic [NUM_BANKS-1:0]                               bank_rd_valid,
    output logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_rd_addr,
    // Bank-side read responses (1 cycle after bank_rd_valid when BANK_LAT=1)
    input  logic [NUM_BANKS-1:0]                               bank_rsp_valid,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] bank_rsp_data,
    input  logic [NUM_BANKS-1:0]                               bank_rsp_ecc_ce,
    input  logic [NUM_BANKS-1:0]                               bank_rsp_ecc_ue,
    // Lane-side demultiplexed read responses
    output logic [LANES-1:0]                                   lane_rsp_valid,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] lane_rsp_data,
    output logic [LANES-1:0]                                   lane_rsp_ecc_ce,
    output logic [LANES-1:0]                                   lane_rsp_ecc_ue,
    // Broadcast coalescing and bandwidth telemetry
    output logic [3:0]                                         coalesced_reads_this_cycle,
    output logic [31:0]                                        total_coalesced_reads,
    output logic [31:0]                                        total_bank_reads_issued
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(LANES >= 1 && LANES <= 32, ("LANES must be in [1, 32]"))
    `STATIC_ASSERT(NUM_BANKS == 32, ("Expected 32 banks"))
    `STATIC_ASSERT(BANK_LAT >= 1, ("BANK_LAT must be >= 1"))

    // Pairwise lane broadcast-match matrix: lane_same_target[i][j] indicates lanes i and j
    // address the exact same physical bank and 64-bit word on this cycle.
    logic [LANES-1:0][LANES-1:0]                  lane_same_target;
    logic [LANES-1:0]                             lane_is_primary_leader;
    logic [LANES-1:0]                             lane_is_coalesced_follower;
    logic [LANES-1:0][3:0]                        lane_leader_idx;
    logic [NUM_BANKS-1:0][LANES-1:0]              bank_lane_hit_vec;
    logic [NUM_BANKS-1:0][3:0]                    bank_fanout_count;
    logic [NUM_BANKS-1:0]                         comb_bank_rd_valid;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]   comb_bank_rd_addr;
    logic [NUM_BANKS-1:0]                         comb_bank_multi_hit;
    logic [NUM_BANKS-1:0]                         comb_bank_addr_conflict;
    logic [3:0]                                   comb_coalesce_saved;
    logic [3:0]                                   comb_bank_rd_count;
    logic [3:0]                                   comb_lane_req_count;
    logic [3:0]                                   comb_max_fanout;

    for (genvar g_i = 0; g_i < LANES; ++g_i) begin : g_match_row
        for (genvar g_j = 0; g_j < LANES; ++g_j) begin : g_match_col
            assign lane_same_target[g_i][g_j] = lane_req_valid[g_i] &&
                                                lane_req_valid[g_j] &&
                                                (lane_req_bank_id[g_i] == lane_req_bank_id[g_j]) &&
                                                (lane_req_word_addr[g_i] == lane_req_word_addr[g_j]);
        end

        always_comb begin
            logic       has_earlier_match;
            logic [3:0] first_match_lane;
            has_earlier_match = 1'b0;
            first_match_lane  = 4'(g_i);
            for (int k = 0; k < g_i; ++k) begin
                if (lane_same_target[g_i][k] && !has_earlier_match) begin
                    has_earlier_match = 1'b1;
                    first_match_lane  = 4'(k);
                end
            end
            lane_is_primary_leader[g_i]     = lane_req_valid[g_i] && !has_earlier_match;
            lane_is_coalesced_follower[g_i] = lane_req_valid[g_i] && has_earlier_match;
            lane_leader_idx[g_i]            = first_match_lane;
        end
    end

    // Bank-centric request arbiter & address mux across the LANES inputs
    for (genvar g_b = 0; g_b < NUM_BANKS; ++g_b) begin : g_bank_mux
        always_comb begin
            bank_lane_hit_vec[g_b]       = '0;
            bank_fanout_count[g_b]       = 4'd0;
            comb_bank_rd_valid[g_b]      = 1'b0;
            comb_bank_rd_addr[g_b]       = '0;
            comb_bank_multi_hit[g_b]     = 1'b0;
            comb_bank_addr_conflict[g_b] = 1'b0;

            for (int l = 0; l < LANES; ++l) begin
                if (lane_req_valid[l] && (lane_req_bank_id[l] == TMEM_BANK_ID_W'(g_b))) begin
                    bank_lane_hit_vec[g_b][l] = 1'b1;
                    bank_fanout_count[g_b]    = bank_fanout_count[g_b] + 4'd1;
                    if (!comb_bank_rd_valid[g_b]) begin
                        comb_bank_rd_valid[g_b] = 1'b1;
                        comb_bank_rd_addr[g_b]  = lane_req_word_addr[l];
                    end else if (comb_bank_rd_addr[g_b] == lane_req_word_addr[l]) begin
                        comb_bank_multi_hit[g_b] = 1'b1;
                    end else begin
                        comb_bank_addr_conflict[g_b] = 1'b1;
                    end
                end
            end
        end
    end

    always_comb begin
        comb_coalesce_saved = 4'd0;
        comb_bank_rd_count  = 4'd0;
        comb_lane_req_count = 4'd0;
        comb_max_fanout     = 4'd0;

        for (int l = 0; l < LANES; ++l) begin
            if (lane_req_valid[l]) begin
                comb_lane_req_count = comb_lane_req_count + 4'd1;
            end
            if (lane_is_coalesced_follower[l]) begin
                comb_coalesce_saved = comb_coalesce_saved + 4'd1;
            end
        end

        for (int b = 0; b < NUM_BANKS; ++b) begin
            if (comb_bank_rd_valid[b]) begin
                comb_bank_rd_count = comb_bank_rd_count + 4'd1;
            end
            if (bank_fanout_count[b] > comb_max_fanout) begin
                comb_max_fanout = bank_fanout_count[b];
            end
        end
    end

    assign bank_rd_valid = comb_bank_rd_valid;
    assign bank_rd_addr  = comb_bank_rd_addr;

    // Pipeline delay alignment for lane -> bank mapping and coalescing metadata
    logic [BANK_LAT-1:0][LANES-1:0]                       pipe_valid_q;
    logic [BANK_LAT-1:0][LANES-1:0][TMEM_BANK_ID_W-1:0]   pipe_bank_q;
    logic [BANK_LAT-1:0][LANES-1:0][TMEM_BANK_ADDR_W-1:0] pipe_word_q;
    logic [BANK_LAT-1:0][LANES-1:0]                       pipe_follower_q;
    logic [BANK_LAT-1:0][LANES-1:0][3:0]                  pipe_leader_q;
    logic [31:0]                                          coalesced_total_q;
    logic [31:0]                                          bank_reads_total_q;
    logic [31:0]                                          lane_reads_total_q;
    logic [31:0]                                          rsp_delivered_total_q;
    logic [31:0]                                          addr_conflict_err_q;
    logic [3:0]                                           peak_fanout_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            pipe_valid_q          <= '0;
            pipe_bank_q           <= '0;
            pipe_word_q           <= '0;
            pipe_follower_q       <= '0;
            pipe_leader_q         <= '0;
            coalesced_total_q     <= 32'd0;
            bank_reads_total_q    <= 32'd0;
            lane_reads_total_q    <= 32'd0;
            rsp_delivered_total_q <= 32'd0;
            addr_conflict_err_q   <= 32'd0;
            peak_fanout_q         <= 4'd0;
        end else begin
            pipe_valid_q[0]    <= lane_req_valid;
            pipe_bank_q[0]     <= lane_req_bank_id;
            pipe_word_q[0]     <= lane_req_word_addr;
            pipe_follower_q[0] <= lane_is_coalesced_follower;
            pipe_leader_q[0]   <= lane_leader_idx;
            for (int s = 1; s < BANK_LAT; ++s) begin
                pipe_valid_q[s]    <= pipe_valid_q[s-1];
                pipe_bank_q[s]     <= pipe_bank_q[s-1];
                pipe_word_q[s]     <= pipe_word_q[s-1];
                pipe_follower_q[s] <= pipe_follower_q[s-1];
                pipe_leader_q[s]   <= pipe_leader_q[s-1];
            end
            coalesced_total_q  <= coalesced_total_q + {28'd0, comb_coalesce_saved};
            bank_reads_total_q <= bank_reads_total_q + {28'd0, comb_bank_rd_count};
            lane_reads_total_q <= lane_reads_total_q + {28'd0, comb_lane_req_count};
            if (|comb_bank_addr_conflict) begin
                addr_conflict_err_q <= addr_conflict_err_q + 32'd1;
            end
            if (comb_max_fanout > peak_fanout_q) begin
                peak_fanout_q <= comb_max_fanout;
            end
            for (int l = 0; l < LANES; ++l) begin
                if (lane_rsp_valid[l]) begin
                    rsp_delivered_total_q <= rsp_delivered_total_q + 32'd1;
                end
            end
        end
    end

    // Response crossbar: demultiplex 32 bank responses back to all active lanes,
    // broadcasting shared words to coalesced follower lanes.
    logic [LANES-1:0]                      aligned_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]  aligned_bank_id;
    logic [LANES-1:0]                      aligned_follower;
    logic [LANES-1:0][3:0]                 aligned_leader;
    logic [LANES-1:0]                      rsp_mismatch_err;
    logic [LANES-1:0]                      rsp_ce_delivered;
    logic [LANES-1:0]                      rsp_ue_delivered;

    assign aligned_valid    = pipe_valid_q[BANK_LAT-1];
    assign aligned_bank_id  = pipe_bank_q[BANK_LAT-1];
    assign aligned_follower = pipe_follower_q[BANK_LAT-1];
    assign aligned_leader   = pipe_leader_q[BANK_LAT-1];

    `UNUSED_VAR (lane_is_primary_leader)
    `UNUSED_VAR (bank_lane_hit_vec)
    `UNUSED_VAR (comb_bank_multi_hit)
    `UNUSED_VAR (pipe_word_q)
    `UNUSED_VAR (aligned_follower)
    `UNUSED_VAR (aligned_leader)
    `UNUSED_VAR (lane_reads_total_q)
    `UNUSED_VAR (rsp_delivered_total_q)
    `UNUSED_VAR (addr_conflict_err_q)
    `UNUSED_VAR (peak_fanout_q)
    `UNUSED_VAR (rsp_mismatch_err)
    `UNUSED_VAR (rsp_ce_delivered)
    `UNUSED_VAR (rsp_ue_delivered)

    for (genvar g_l = 0; g_l < LANES; ++g_l) begin : g_rsp_demux
        logic [TMEM_BANK_ID_W-1:0] src_bank;

        always_comb begin
            src_bank              = aligned_bank_id[g_l];
            lane_rsp_valid[g_l]   = aligned_valid[g_l] && bank_rsp_valid[src_bank];
            lane_rsp_data[g_l]    = bank_rsp_data[src_bank];
            lane_rsp_ecc_ce[g_l]  = aligned_valid[g_l] && bank_rsp_valid[src_bank] && bank_rsp_ecc_ce[src_bank];
            lane_rsp_ecc_ue[g_l]  = aligned_valid[g_l] && bank_rsp_valid[src_bank] && bank_rsp_ecc_ue[src_bank];
            rsp_mismatch_err[g_l] = aligned_valid[g_l] && !bank_rsp_valid[src_bank];
            rsp_ce_delivered[g_l] = lane_rsp_ecc_ce[g_l];
            rsp_ue_delivered[g_l] = lane_rsp_ecc_ue[g_l];
        end
    end

    assign coalesced_reads_this_cycle = comb_coalesce_saved;
    assign total_coalesced_reads      = coalesced_total_q;
    assign total_bank_reads_issued    = bank_reads_total_q;

endmodule
