// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_rw_bypass #(
    parameter int LANES     = 8,
    parameter int NUM_BANKS = VX_tmem_pkg::TMEM_NUM_BANKS
) (
    input  logic                                               clk,
    input  logic                                               reset,
    // Active read requests issued in cycle T (Port A & Port B)
    input  logic [LANES-1:0]                                   rd_a_req_valid,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]  rd_a_req_bank_id,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] rd_a_req_word_addr,
    input  logic [LANES-1:0]                                   rd_b_req_valid,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]  rd_b_req_bank_id,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] rd_b_req_word_addr,
    // Bank-level writes occurring in cycle T (full or partial BE)
    input  logic [NUM_BANKS-1:0]                               bank_wr_valid,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_wr_addr,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] bank_wr_data,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_WIDTH_BYTES-1:0] bank_wr_be,
    // In-flight RMW pipeline state from each bank (committing in cycle T or T+1)
    input  logic [NUM_BANKS-1:0]                               bank_rmw_active,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_rmw_addr,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] bank_rmw_merged_data,
    input  logic [NUM_BANKS-1:0]                               bank_rmw_commit_valid,
    // SRAM read responses arriving in cycle T+1 (post-ECC decode)
    input  logic [LANES-1:0]                                   sram_rd_a_rsp_valid,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] sram_rd_a_rsp_data,
    input  logic [LANES-1:0]                                   sram_rd_a_ecc_ce,
    input  logic [LANES-1:0]                                   sram_rd_a_ecc_ue,
    input  logic [LANES-1:0]                                   sram_rd_b_rsp_valid,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] sram_rd_b_rsp_data,
    input  logic [LANES-1:0]                                   sram_rd_b_ecc_ce,
    input  logic [LANES-1:0]                                   sram_rd_b_ecc_ue,
    // Final hazard-resolved read responses in cycle T+1
    output logic [LANES-1:0]                                   final_rd_a_rsp_valid,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] final_rd_a_rsp_data,
    output logic [LANES-1:0]                                   final_rd_a_ecc_ce,
    output logic [LANES-1:0]                                   final_rd_a_ecc_ue,
    output logic [LANES-1:0]                                   final_rd_b_rsp_valid,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_ECC_DATA_W-1:0] final_rd_b_rsp_data,
    output logic [LANES-1:0]                                   final_rd_b_ecc_ce,
    output logic [LANES-1:0]                                   final_rd_b_ecc_ue,
    // Forwarding telemetry
    output logic [LANES-1:0]                                   rd_a_bypass_hit,
    output logic [LANES-1:0]                                   rd_b_bypass_hit,
    output logic [31:0]                                        total_bypass_hits_out
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(LANES >= 1 && LANES <= 32, ("LANES must be in [1, 32]"))
    `STATIC_ASSERT(NUM_BANKS == 32, ("Expected 32 banks"))

    function automatic logic [TMEM_ECC_DATA_W-1:0] apply_byte_overlay(
        input logic [TMEM_ECC_DATA_W-1:0]       base_data,
        input logic [TMEM_ECC_DATA_W-1:0]       fwd_data,
        input logic [TMEM_BANK_WIDTH_BYTES-1:0] fwd_be
    );
        logic [TMEM_ECC_DATA_W-1:0] out_word;
        out_word = base_data;
        for (int b = 0; b < TMEM_BANK_WIDTH_BYTES; ++b) begin
            if (fwd_be[b]) begin
                out_word[b*8 +: 8] = fwd_data[b*8 +: 8];
            end
        end
        return out_word;
    endfunction

    // Cycle T-1 write history per bank (recent commit buffer) plus Cycle T write forwarding
    // and Cycle T/T+1 RMW pipeline forwarding.
    logic [NUM_BANKS-1:0]                              prev_wr_valid_q;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]        prev_wr_addr_q;
    logic [NUM_BANKS-1:0][TMEM_ECC_DATA_W-1:0]         prev_wr_data_q;
    logic [NUM_BANKS-1:0][TMEM_BANK_WIDTH_BYTES-1:0]   prev_wr_be_q;

    // Cycle T capture for Port A & Port B reads
    logic [LANES-1:0]                             a_d1_valid_q;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]         a_d1_bank_q;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]       a_d1_word_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        a_d1_fwd_data_q;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0]  a_d1_fwd_be_q;
    logic [LANES-1:0]                             a_d1_rmw_hit_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        a_d1_rmw_data_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        a_d1_prev_data_q;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0]  a_d1_prev_be_q;

    logic [LANES-1:0]                             b_d1_valid_q;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]         b_d1_bank_q;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]       b_d1_word_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        b_d1_fwd_data_q;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0]  b_d1_fwd_be_q;
    logic [LANES-1:0]                             b_d1_rmw_hit_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        b_d1_rmw_data_q;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]        b_d1_prev_data_q;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0]  b_d1_prev_be_q;

    logic [31:0]                                  bypass_hits_q;
    logic [31:0]                                  bypass_a_hits_q;
    logic [31:0]                                  bypass_b_hits_q;
    logic [31:0]                                  bypass_rmw_hits_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            prev_wr_valid_q  <= '0;
            prev_wr_addr_q   <= '0;
            prev_wr_data_q   <= '0;
            prev_wr_be_q     <= '0;
            a_d1_valid_q     <= '0;
            a_d1_bank_q      <= '0;
            a_d1_word_q      <= '0;
            a_d1_fwd_data_q  <= '0;
            a_d1_fwd_be_q    <= '0;
            a_d1_rmw_hit_q   <= '0;
            a_d1_rmw_data_q  <= '0;
            a_d1_prev_data_q <= '0;
            a_d1_prev_be_q   <= '0;
            b_d1_valid_q     <= '0;
            b_d1_bank_q      <= '0;
            b_d1_word_q      <= '0;
            b_d1_fwd_data_q  <= '0;
            b_d1_fwd_be_q    <= '0;
            b_d1_rmw_hit_q   <= '0;
            b_d1_rmw_data_q  <= '0;
            b_d1_prev_data_q <= '0;
            b_d1_prev_be_q   <= '0;
        end else begin
            prev_wr_valid_q <= bank_wr_valid;
            prev_wr_addr_q  <= bank_wr_addr;
            prev_wr_data_q  <= bank_wr_data;
            prev_wr_be_q    <= bank_wr_be;

            for (int l = 0; l < LANES; ++l) begin
                logic [TMEM_BANK_ID_W-1:0]   a_b;
                logic [TMEM_BANK_ADDR_W-1:0] a_w;
                logic [TMEM_BANK_ID_W-1:0]   b_b;
                logic [TMEM_BANK_ADDR_W-1:0] b_w;

                a_b = rd_a_req_bank_id[l];
                a_w = rd_a_req_word_addr[l];
                a_d1_valid_q[l] <= rd_a_req_valid[l];
                a_d1_bank_q[l]  <= a_b;
                a_d1_word_q[l]  <= a_w;

                if (rd_a_req_valid[l] && prev_wr_valid_q[a_b] && (prev_wr_addr_q[a_b] == a_w)) begin
                    a_d1_prev_data_q[l] <= prev_wr_data_q[a_b];
                    a_d1_prev_be_q[l]   <= prev_wr_be_q[a_b];
                end else begin
                    a_d1_prev_data_q[l] <= '0;
                    a_d1_prev_be_q[l]   <= '0;
                end

                if (rd_a_req_valid[l] && bank_wr_valid[a_b] && (bank_wr_addr[a_b] == a_w)) begin
                    a_d1_fwd_data_q[l] <= bank_wr_data[a_b];
                    a_d1_fwd_be_q[l]   <= bank_wr_be[a_b];
                end else begin
                    a_d1_fwd_data_q[l] <= '0;
                    a_d1_fwd_be_q[l]   <= '0;
                end

                if (rd_a_req_valid[l] && bank_rmw_active[a_b] && (bank_rmw_addr[a_b] == a_w)) begin
                    a_d1_rmw_hit_q[l]  <= 1'b1;
                    a_d1_rmw_data_q[l] <= bank_rmw_merged_data[a_b];
                end else begin
                    a_d1_rmw_hit_q[l]  <= 1'b0;
                    a_d1_rmw_data_q[l] <= '0;
                end

                b_b = rd_b_req_bank_id[l];
                b_w = rd_b_req_word_addr[l];
                b_d1_valid_q[l] <= rd_b_req_valid[l];
                b_d1_bank_q[l]  <= b_b;
                b_d1_word_q[l]  <= b_w;

                if (rd_b_req_valid[l] && prev_wr_valid_q[b_b] && (prev_wr_addr_q[b_b] == b_w)) begin
                    b_d1_prev_data_q[l] <= prev_wr_data_q[b_b];
                    b_d1_prev_be_q[l]   <= prev_wr_be_q[b_b];
                end else begin
                    b_d1_prev_data_q[l] <= '0;
                    b_d1_prev_be_q[l]   <= '0;
                end

                if (rd_b_req_valid[l] && bank_wr_valid[b_b] && (bank_wr_addr[b_b] == b_w)) begin
                    b_d1_fwd_data_q[l] <= bank_wr_data[b_b];
                    b_d1_fwd_be_q[l]   <= bank_wr_be[b_b];
                end else begin
                    b_d1_fwd_data_q[l] <= '0;
                    b_d1_fwd_be_q[l]   <= '0;
                end

                if (rd_b_req_valid[l] && bank_rmw_active[b_b] && (bank_rmw_addr[b_b] == b_w)) begin
                    b_d1_rmw_hit_q[l]  <= 1'b1;
                    b_d1_rmw_data_q[l] <= bank_rmw_merged_data[b_b];
                end else begin
                    b_d1_rmw_hit_q[l]  <= 1'b0;
                    b_d1_rmw_data_q[l] <= '0;
                end
            end
        end
    end

    logic [4:0] hits_this_cycle;
    logic [4:0] a_hits_this_cycle;
    logic [4:0] b_hits_this_cycle;
    logic [4:0] rmw_hits_this_cycle;

    always_comb begin
        hits_this_cycle     = 5'd0;
        a_hits_this_cycle   = 5'd0;
        b_hits_this_cycle   = 5'd0;
        rmw_hits_this_cycle = 5'd0;

        for (int l = 0; l < LANES; ++l) begin
            logic [TMEM_ECC_DATA_W-1:0] a_word;
            logic [TMEM_ECC_DATA_W-1:0] b_word;
            logic                       a_t1_rmw;
            logic                       b_t1_rmw;
            logic                       a_hit;
            logic                       b_hit;
            logic                       a_full_fwd;
            logic                       b_full_fwd;

            // Port A forwarding priority order (oldest -> newest):
            //   1) SRAM read data
            //   2) Cycle T-1 write overlay (if partial)
            //   3) Cycle T RMW state
            //   4) Cycle T direct write overlay
            //   5) Cycle T+1 completing RMW commit
            a_word     = sram_rd_a_rsp_data[l];
            a_t1_rmw   = a_d1_valid_q[l] && bank_rmw_commit_valid[a_d1_bank_q[l]] &&
                         (bank_rmw_addr[a_d1_bank_q[l]] == a_d1_word_q[l]);
            a_full_fwd = (&a_d1_fwd_be_q[l]) || a_d1_rmw_hit_q[l] || a_t1_rmw;

            if (|a_d1_prev_be_q[l]) begin
                a_word = apply_byte_overlay(a_word, a_d1_prev_data_q[l], a_d1_prev_be_q[l]);
            end
            if (a_d1_rmw_hit_q[l]) begin
                a_word = a_d1_rmw_data_q[l];
            end
            if (|a_d1_fwd_be_q[l]) begin
                a_word = apply_byte_overlay(a_word, a_d1_fwd_data_q[l], a_d1_fwd_be_q[l]);
            end
            if (a_t1_rmw) begin
                a_word = bank_rmw_merged_data[a_d1_bank_q[l]];
            end

            a_hit = sram_rd_a_rsp_valid[l] &&
                    ((|a_d1_fwd_be_q[l]) || a_d1_rmw_hit_q[l] || a_t1_rmw || (|a_d1_prev_be_q[l]));
            rd_a_bypass_hit[l]      = a_hit;
            final_rd_a_rsp_valid[l] = sram_rd_a_rsp_valid[l];
            final_rd_a_rsp_data[l]  = a_word;
            final_rd_a_ecc_ce[l]    = a_full_fwd ? 1'b0 : sram_rd_a_ecc_ce[l];
            final_rd_a_ecc_ue[l]    = a_full_fwd ? 1'b0 : sram_rd_a_ecc_ue[l];

            // Port B forwarding priority order (oldest -> newest)
            b_word     = sram_rd_b_rsp_data[l];
            b_t1_rmw   = b_d1_valid_q[l] && bank_rmw_commit_valid[b_d1_bank_q[l]] &&
                         (bank_rmw_addr[b_d1_bank_q[l]] == b_d1_word_q[l]);
            b_full_fwd = (&b_d1_fwd_be_q[l]) || b_d1_rmw_hit_q[l] || b_t1_rmw;

            if (|b_d1_prev_be_q[l]) begin
                b_word = apply_byte_overlay(b_word, b_d1_prev_data_q[l], b_d1_prev_be_q[l]);
            end
            if (b_d1_rmw_hit_q[l]) begin
                b_word = b_d1_rmw_data_q[l];
            end
            if (|b_d1_fwd_be_q[l]) begin
                b_word = apply_byte_overlay(b_word, b_d1_fwd_data_q[l], b_d1_fwd_be_q[l]);
            end
            if (b_t1_rmw) begin
                b_word = bank_rmw_merged_data[b_d1_bank_q[l]];
            end

            b_hit = sram_rd_b_rsp_valid[l] &&
                    ((|b_d1_fwd_be_q[l]) || b_d1_rmw_hit_q[l] || b_t1_rmw || (|b_d1_prev_be_q[l]));
            rd_b_bypass_hit[l]      = b_hit;
            final_rd_b_rsp_valid[l] = sram_rd_b_rsp_valid[l];
            final_rd_b_rsp_data[l]  = b_word;
            final_rd_b_ecc_ce[l]    = b_full_fwd ? 1'b0 : sram_rd_b_ecc_ce[l];
            final_rd_b_ecc_ue[l]    = b_full_fwd ? 1'b0 : sram_rd_b_ecc_ue[l];

            if (a_hit) begin
                hits_this_cycle   = hits_this_cycle + 5'd1;
                a_hits_this_cycle = a_hits_this_cycle + 5'd1;
            end
            if (b_hit) begin
                hits_this_cycle   = hits_this_cycle + 5'd1;
                b_hits_this_cycle = b_hits_this_cycle + 5'd1;
            end
            if ((sram_rd_a_rsp_valid[l] && (a_d1_rmw_hit_q[l] || a_t1_rmw)) ||
                (sram_rd_b_rsp_valid[l] && (b_d1_rmw_hit_q[l] || b_t1_rmw))) begin
                rmw_hits_this_cycle = rmw_hits_this_cycle + 5'd1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            bypass_hits_q     <= 32'd0;
            bypass_a_hits_q   <= 32'd0;
            bypass_b_hits_q   <= 32'd0;
            bypass_rmw_hits_q <= 32'd0;
        end else begin
            bypass_hits_q     <= bypass_hits_q + {27'd0, hits_this_cycle};
            bypass_a_hits_q   <= bypass_a_hits_q + {27'd0, a_hits_this_cycle};
            bypass_b_hits_q   <= bypass_b_hits_q + {27'd0, b_hits_this_cycle};
            bypass_rmw_hits_q <= bypass_rmw_hits_q + {27'd0, rmw_hits_this_cycle};
        end
    end

    `UNUSED_VAR (bypass_a_hits_q)
    `UNUSED_VAR (bypass_b_hits_q)
    `UNUSED_VAR (bypass_rmw_hits_q)

    assign total_bypass_hits_out = bypass_hits_q;

endmodule
