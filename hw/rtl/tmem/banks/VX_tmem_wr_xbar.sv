// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_wr_xbar #(
    parameter int LANES     = 8,
    parameter int NUM_BANKS = VX_tmem_pkg::TMEM_NUM_BANKS
) (
    input  logic                                               clk,
    input  logic                                               reset,
    // Granted lane write requests from conflict serializer
    input  logic [LANES-1:0]                                   lane_wr_valid,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]  lane_wr_bank_id,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] lane_wr_word_addr,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]  lane_wr_data,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_WIDTH_BYTES-1:0] lane_wr_be,
    // Bank-side ready mask (from bank power/RMW state)
    input  logic [NUM_BANKS-1:0]                               bank_wr_ready,
    // Bank-side write outputs (to 32 banks)
    output logic [NUM_BANKS-1:0]                               bank_wr_valid,
    output logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_wr_addr,
    output logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] bank_wr_data,
    output logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_WIDTH_BYTES-1:0] bank_wr_be,
    // Per-lane acceptance & collision feedback
    output logic [LANES-1:0]                                   lane_wr_accepted,
    output logic [LANES-1:0]                                   lane_wr_rejected,
    output logic [NUM_BANKS-1:0]                               bank_be_merged_mask,
    output logic [31:0]                                        total_bank_writes_issued,
    output logic [31:0]                                        total_merged_writes
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(LANES >= 1 && LANES <= 32, ("LANES must be in [1, 32]"))
    `STATIC_ASSERT(NUM_BANKS == 32, ("Expected 32 banks"))

    // Per-bank structured lane-hit analysis:
    // Each bank inspects all LANES write ports independently, identifies the anchor
    // (lowest-indexed valid non-zero-BE lane targeting it), checks whether subsequent
    // lanes targeting the same bank have matching word_addr and disjoint byte enables,
    // and merges all compatible byte lanes byte-by-byte.
    logic [NUM_BANKS-1:0][LANES-1:0]                    bank_lane_target;
    logic [NUM_BANKS-1:0][LANES-1:0]                    bank_lane_compatible;
    logic [NUM_BANKS-1:0][LANES-1:0]                    bank_lane_collision;
    logic [NUM_BANKS-1:0][LANES-1:0]                    bank_lane_be_overlap;
    logic [NUM_BANKS-1:0][LANES-1:0]                    bank_lane_addr_mismatch;
    logic [NUM_BANKS-1:0]                               comb_bank_wr_valid;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]         comb_bank_wr_addr;
    logic [NUM_BANKS-1:0][TMEM_ECC_DATA_W-1:0]          comb_bank_wr_data;
    logic [NUM_BANKS-1:0][TMEM_BANK_WIDTH_BYTES-1:0]    comb_bank_wr_be;
    logic [NUM_BANKS-1:0]                               comb_bank_merged;
    logic [NUM_BANKS-1:0]                               comb_bank_partial_wr;
    logic [NUM_BANKS-1:0]                               comb_bank_full_wr;
    logic [NUM_BANKS-1:0][3:0]                          comb_bank_contrib_cnt;
    logic [LANES-1:0]                                   comb_lane_accepted;
    logic [LANES-1:0]                                   comb_lane_rejected;
    logic [3:0]                                         comb_wr_issued_cnt;
    logic [3:0]                                         comb_wr_merged_cnt;
    logic [3:0]                                         comb_wr_rejected_cnt;
    logic [3:0]                                         comb_wr_full_cnt;
    logic [3:0]                                         comb_wr_partial_cnt;

    for (genvar g_b = 0; g_b < NUM_BANKS; ++g_b) begin : g_bank_wr_arb
        always_comb begin
            logic                               anchor_found;
            logic [TMEM_BANK_ADDR_W-1:0]        anchor_addr;
            logic [TMEM_BANK_WIDTH_BYTES-1:0]   accum_be;
            logic [TMEM_ECC_DATA_W-1:0]         accum_data;
            logic [3:0]                         contributors;

            bank_lane_target[g_b]        = '0;
            bank_lane_compatible[g_b]    = '0;
            bank_lane_collision[g_b]     = '0;
            bank_lane_be_overlap[g_b]    = '0;
            bank_lane_addr_mismatch[g_b] = '0;
            anchor_found                 = 1'b0;
            anchor_addr                  = '0;
            accum_be                     = '0;
            accum_data                   = '0;
            contributors                 = 4'd0;

            for (int l = 0; l < LANES; ++l) begin
                logic                             is_target;
                logic [TMEM_BANK_WIDTH_BYTES-1:0] l_be;
                logic [TMEM_ECC_DATA_W-1:0]       l_data;
                logic [TMEM_BANK_ADDR_W-1:0]      l_addr;

                is_target = lane_wr_valid[l] && (lane_wr_bank_id[l] == TMEM_BANK_ID_W'(g_b));
                l_be      = lane_wr_be[l];
                l_data    = lane_wr_data[l];
                l_addr    = lane_wr_word_addr[l];

                if (is_target) begin
                    bank_lane_target[g_b][l] = 1'b1;
                    if (!bank_wr_ready[g_b]) begin
                        bank_lane_collision[g_b][l] = 1'b1;
                    end else if (l_be == 8'd0) begin
                        bank_lane_compatible[g_b][l] = 1'b1;
                    end else if (!anchor_found) begin
                        anchor_found                 = 1'b1;
                        anchor_addr                  = l_addr;
                        accum_be                     = l_be;
                        contributors                 = 4'd1;
                        bank_lane_compatible[g_b][l] = 1'b1;
                        for (int byte_i = 0; byte_i < TMEM_BANK_WIDTH_BYTES; ++byte_i) begin
                            if (l_be[byte_i]) begin
                                accum_data[byte_i*8 +: 8] = l_data[byte_i*8 +: 8];
                            end
                        end
                    end else if ((l_addr == anchor_addr) && ((accum_be & l_be) == 8'd0)) begin
                        accum_be                     = accum_be | l_be;
                        contributors                 = contributors + 4'd1;
                        bank_lane_compatible[g_b][l] = 1'b1;
                        for (int byte_i = 0; byte_i < TMEM_BANK_WIDTH_BYTES; ++byte_i) begin
                            if (l_be[byte_i]) begin
                                accum_data[byte_i*8 +: 8] = l_data[byte_i*8 +: 8];
                            end
                        end
                    end else begin
                        bank_lane_collision[g_b][l] = 1'b1;
                        if (l_addr != anchor_addr) begin
                            bank_lane_addr_mismatch[g_b][l] = 1'b1;
                        end
                        if ((accum_be & l_be) != 8'd0) begin
                            bank_lane_be_overlap[g_b][l] = 1'b1;
                        end
                    end
                end
            end

            comb_bank_wr_valid[g_b]    = anchor_found;
            comb_bank_wr_addr[g_b]     = anchor_addr;
            comb_bank_wr_data[g_b]     = accum_data;
            comb_bank_wr_be[g_b]       = accum_be;
            comb_bank_merged[g_b]      = (contributors > 4'd1);
            comb_bank_partial_wr[g_b]  = anchor_found && !(&accum_be);
            comb_bank_full_wr[g_b]     = anchor_found && (&accum_be);
            comb_bank_contrib_cnt[g_b] = contributors;
        end
    end

    // Reduce per-bank accept/reject decisions back to per-lane feedback
    always_comb begin
        comb_lane_accepted   = '0;
        comb_lane_rejected   = '0;
        comb_wr_issued_cnt   = 4'd0;
        comb_wr_merged_cnt   = 4'd0;
        comb_wr_rejected_cnt = 4'd0;
        comb_wr_full_cnt     = 4'd0;
        comb_wr_partial_cnt  = 4'd0;

        for (int l = 0; l < LANES; ++l) begin
            logic [TMEM_BANK_ID_W-1:0] b_id;
            b_id = lane_wr_bank_id[l];
            if (lane_wr_valid[l]) begin
                if (bank_lane_compatible[b_id][l]) begin
                    comb_lane_accepted[l] = 1'b1;
                end
                if (bank_lane_collision[b_id][l]) begin
                    comb_lane_rejected[l] = 1'b1;
                    comb_wr_rejected_cnt  = comb_wr_rejected_cnt + 4'd1;
                end
            end
        end

        for (int b = 0; b < NUM_BANKS; ++b) begin
            if (comb_bank_wr_valid[b]) begin
                comb_wr_issued_cnt = comb_wr_issued_cnt + 4'd1;
            end
            if (comb_bank_merged[b]) begin
                comb_wr_merged_cnt = comb_wr_merged_cnt + 4'd1;
            end
            if (comb_bank_full_wr[b]) begin
                comb_wr_full_cnt = comb_wr_full_cnt + 4'd1;
            end
            if (comb_bank_partial_wr[b]) begin
                comb_wr_partial_cnt = comb_wr_partial_cnt + 4'd1;
            end
        end
    end

    `UNUSED_VAR (bank_lane_target)
    `UNUSED_VAR (bank_lane_be_overlap)
    `UNUSED_VAR (bank_lane_addr_mismatch)
    `UNUSED_VAR (comb_bank_contrib_cnt)

    assign bank_wr_valid       = comb_bank_wr_valid;
    assign bank_wr_addr        = comb_bank_wr_addr;
    assign bank_wr_data        = comb_bank_wr_data;
    assign bank_wr_be          = comb_bank_wr_be;
    assign lane_wr_accepted    = comb_lane_accepted;
    assign lane_wr_rejected    = comb_lane_rejected;
    assign bank_be_merged_mask = comb_bank_merged;

    logic [31:0] wr_issued_total_q;
    logic [31:0] wr_merged_total_q;
    logic [31:0] wr_rejected_total_q;
    logic [31:0] wr_full_total_q;
    logic [31:0] wr_partial_total_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            wr_issued_total_q   <= 32'd0;
            wr_merged_total_q   <= 32'd0;
            wr_rejected_total_q <= 32'd0;
            wr_full_total_q     <= 32'd0;
            wr_partial_total_q  <= 32'd0;
        end else begin
            wr_issued_total_q   <= wr_issued_total_q + {28'd0, comb_wr_issued_cnt};
            wr_merged_total_q   <= wr_merged_total_q + {28'd0, comb_wr_merged_cnt};
            wr_rejected_total_q <= wr_rejected_total_q + {28'd0, comb_wr_rejected_cnt};
            wr_full_total_q     <= wr_full_total_q + {28'd0, comb_wr_full_cnt};
            wr_partial_total_q  <= wr_partial_total_q + {28'd0, comb_wr_partial_cnt};
        end
    end

    `UNUSED_VAR (wr_rejected_total_q)
    `UNUSED_VAR (wr_full_total_q)
    `UNUSED_VAR (wr_partial_total_q)

    assign total_bank_writes_issued = wr_issued_total_q;
    assign total_merged_writes      = wr_merged_total_q;

endmodule
