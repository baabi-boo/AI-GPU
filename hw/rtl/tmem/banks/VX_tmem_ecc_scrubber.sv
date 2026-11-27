// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_ecc_scrubber #(
    parameter int NUM_BANKS  = VX_tmem_pkg::TMEM_NUM_BANKS,
    parameter int BANK_DEPTH = VX_tmem_pkg::TMEM_BANK_DEPTH_WORDS
) (
    input  logic                                               clk,
    input  logic                                               reset,
    // Patrol scrub control
    input  logic                                               scrub_en,
    // Bank idle/ready status from each bank
    input  logic [NUM_BANKS-1:0]                               bank_scrub_ready,
    // Scrub read requests issued per bank
    output logic [NUM_BANKS-1:0]                               bank_scrub_req_valid,
    output logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_scrub_req_addr,
    // Scrub read responses & writeback notifications from each bank
    input  logic [NUM_BANKS-1:0]                               bank_scrub_rsp_valid,
    input  logic [NUM_BANKS-1:0]                               bank_scrub_rsp_ce,
    input  logic [NUM_BANKS-1:0]                               bank_scrub_rsp_ue,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0] bank_scrub_rsp_syndrome,
    input  logic [NUM_BANKS-1:0]                               bank_scrub_wb_issued,
    // Live datapath ECC error events (Port A and Port B across all banks)
    input  logic [NUM_BANKS-1:0]                               bank_rd_a_rsp_valid,
    input  logic [NUM_BANKS-1:0]                               bank_rd_a_ce,
    input  logic [NUM_BANKS-1:0]                               bank_rd_a_ue,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_rd_a_addr,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0] bank_rd_a_syndrome,
    input  logic [NUM_BANKS-1:0]                               bank_rd_b_rsp_valid,
    input  logic [NUM_BANKS-1:0]                               bank_rd_b_ce,
    input  logic [NUM_BANKS-1:0]                               bank_rd_b_ue,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] bank_rd_b_addr,
    input  logic [NUM_BANKS-1:0][VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0] bank_rd_b_syndrome,
    // Aggregated saturating ECC counters & last-error telemetry
    output logic [31:0]                                        ecc_ce_count_out,
    output logic [31:0]                                        ecc_ue_count_out,
    output logic [31:0]                                        scrub_ops_count_out,
    output logic [31:0]                                        scrub_wb_count_out,
    output VX_tmem_pkg::tmem_ecc_status_t                      ecc_status_out
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(NUM_BANKS == 32, ("Expected 32 banks"))
    `STATIC_ASSERT(BANK_DEPTH == 1024, ("Expected 1024 words per bank"))

    // Saturating 32-bit increment helper
    function automatic logic [31:0] sat_add_32(
        input logic [31:0] base_val,
        input logic [6:0]  inc_val
    );
        logic [32:0] sum_ext;
        sum_ext = {1'b0, base_val} + {26'd0, inc_val};
        if (sum_ext[32]) begin
            return 32'hFFFF_FFFF;
        end else begin
            return sum_ext[31:0];
        end
    endfunction

    // Patrol pointer stepping sequentially across (bank_ptr_q, word_ptr_q),
    // with opportunistic skip to the next ready bank if the primary bank is busy.
    logic [TMEM_BANK_ID_W-1:0]   bank_ptr_q;
    logic [TMEM_BANK_ADDR_W-1:0] word_ptr_q;
    logic [TMEM_BANK_ADDR_W-1:0] inflight_scrub_word_q;
    logic [TMEM_BANK_ID_W-1:0]   inflight_scrub_bank_q;
    logic [TMEM_BANK_ID_W-1:0]   selected_scrub_bank;
    logic                        selected_scrub_valid;
    logic                        scrub_sweep_wrap_pulse;

    // Per-bank scrub word cursors allow each bank to make forward progress independently
    // when some banks are busy on active MMA/LD/ST traffic.
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0] bank_word_cursor_q;
    logic [NUM_BANKS-1:0][15:0]                 bank_ce_hist_q;
    logic [NUM_BANKS-1:0][15:0]                 bank_ue_hist_q;
    logic [NUM_BANKS-1:0]                       bank_scrub_done_epoch_q;

    // Track 1-cycle delayed Port A / Port B word addresses so last-error address matches rsp cycle
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0] rd_a_addr_d1_q;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0] rd_b_addr_d1_q;

    // Round-robin search starting from bank_ptr_q for an idle bank ready to scrub
    always_comb begin
        selected_scrub_valid = 1'b0;
        selected_scrub_bank  = bank_ptr_q;

        for (int offset = 0; offset < NUM_BANKS; ++offset) begin
            logic [TMEM_BANK_ID_W-1:0] cand_bank;
            cand_bank = bank_ptr_q + TMEM_BANK_ID_W'(offset);
            if (scrub_en && !selected_scrub_valid && bank_scrub_ready[cand_bank]) begin
                selected_scrub_valid = 1'b1;
                selected_scrub_bank  = cand_bank;
            end
        end
    end

    always_comb begin
        bank_scrub_req_valid = '0;
        bank_scrub_req_addr  = '0;
        if (selected_scrub_valid) begin
            bank_scrub_req_valid[selected_scrub_bank] = 1'b1;
            bank_scrub_req_addr[selected_scrub_bank]  = bank_word_cursor_q[selected_scrub_bank];
        end
    end

    // Aggregate CE and UE events across Port A, Port B, and Scrub responses across all 32 banks
    logic [6:0]                   ce_events_cycle;
    logic [6:0]                   ue_events_cycle;
    logic [5:0]                   scrub_wb_cycle;
    logic [NUM_BANKS-1:0]         bank_ce_pulse;
    logic [NUM_BANKS-1:0]         bank_ue_pulse;
    logic                         any_ce_cycle;
    logic                         any_ue_cycle;
    logic [TMEM_BANK_ID_W-1:0]    err_bank_comb;
    logic [TMEM_BANK_ADDR_W-1:0]  err_word_comb;
    logic [TMEM_ECC_PARITY_W-1:0] err_syndrome_comb;
    logic [2:0]                   err_source_port_comb;

    always_comb begin
        ce_events_cycle      = 7'd0;
        ue_events_cycle      = 7'd0;
        scrub_wb_cycle       = 6'd0;
        bank_ce_pulse        = '0;
        bank_ue_pulse        = '0;
        any_ce_cycle         = 1'b0;
        any_ue_cycle         = 1'b0;
        err_bank_comb        = '0;
        err_word_comb        = '0;
        err_syndrome_comb    = '0;
        err_source_port_comb = 3'd0;

        for (int b = 0; b < NUM_BANKS; ++b) begin
            if (bank_rd_a_rsp_valid[b]) begin
                if (bank_rd_a_ce[b]) begin
                    ce_events_cycle      = ce_events_cycle + 7'd1;
                    bank_ce_pulse[b]     = 1'b1;
                    any_ce_cycle         = 1'b1;
                    err_bank_comb        = TMEM_BANK_ID_W'(b);
                    err_word_comb        = rd_a_addr_d1_q[b];
                    err_syndrome_comb    = bank_rd_a_syndrome[b];
                    err_source_port_comb = 3'd1;
                end
                if (bank_rd_a_ue[b]) begin
                    ue_events_cycle      = ue_events_cycle + 7'd1;
                    bank_ue_pulse[b]     = 1'b1;
                    any_ue_cycle         = 1'b1;
                    err_bank_comb        = TMEM_BANK_ID_W'(b);
                    err_word_comb        = rd_a_addr_d1_q[b];
                    err_syndrome_comb    = bank_rd_a_syndrome[b];
                    err_source_port_comb = 3'd1;
                end
            end

            if (bank_rd_b_rsp_valid[b]) begin
                if (bank_rd_b_ce[b]) begin
                    ce_events_cycle      = ce_events_cycle + 7'd1;
                    bank_ce_pulse[b]     = 1'b1;
                    any_ce_cycle         = 1'b1;
                    err_bank_comb        = TMEM_BANK_ID_W'(b);
                    err_word_comb        = rd_b_addr_d1_q[b];
                    err_syndrome_comb    = bank_rd_b_syndrome[b];
                    err_source_port_comb = 3'd2;
                end
                if (bank_rd_b_ue[b]) begin
                    ue_events_cycle      = ue_events_cycle + 7'd1;
                    bank_ue_pulse[b]     = 1'b1;
                    any_ue_cycle         = 1'b1;
                    err_bank_comb        = TMEM_BANK_ID_W'(b);
                    err_word_comb        = rd_b_addr_d1_q[b];
                    err_syndrome_comb    = bank_rd_b_syndrome[b];
                    err_source_port_comb = 3'd2;
                end
            end

            if (bank_scrub_rsp_valid[b]) begin
                if (bank_scrub_rsp_ce[b]) begin
                    ce_events_cycle      = ce_events_cycle + 7'd1;
                    bank_ce_pulse[b]     = 1'b1;
                    any_ce_cycle         = 1'b1;
                    err_bank_comb        = TMEM_BANK_ID_W'(b);
                    err_word_comb        = inflight_scrub_word_q;
                    err_syndrome_comb    = bank_scrub_rsp_syndrome[b];
                    err_source_port_comb = 3'd4;
                end
                if (bank_scrub_rsp_ue[b]) begin
                    ue_events_cycle      = ue_events_cycle + 7'd1;
                    bank_ue_pulse[b]     = 1'b1;
                    any_ue_cycle         = 1'b1;
                    err_bank_comb        = TMEM_BANK_ID_W'(b);
                    err_word_comb        = inflight_scrub_word_q;
                    err_syndrome_comb    = bank_scrub_rsp_syndrome[b];
                    err_source_port_comb = 3'd4;
                end
            end

            if (bank_scrub_wb_issued[b]) begin
                scrub_wb_cycle = scrub_wb_cycle + 6'd1;
            end
        end
    end

    logic [31:0]                  ce_count_q;
    logic [31:0]                  ue_count_q;
    logic [31:0]                  scrub_ops_q;
    logic [31:0]                  scrub_wb_q;
    logic [31:0]                  scrub_epoch_count_q;
    logic                         ce_seen_q;
    logic                         ue_seen_q;
    logic [TMEM_BANK_ID_W-1:0]    last_err_bank_q;
    logic [TMEM_BANK_ADDR_W-1:0]  last_err_word_q;
    logic [TMEM_ECC_PARITY_W-1:0] last_err_syndrome_q;
    logic [2:0]                   last_err_port_q;

    assign scrub_sweep_wrap_pulse = (&bank_scrub_done_epoch_q);

    always_ff @(posedge clk) begin
        if (reset) begin
            bank_ptr_q              <= '0;
            word_ptr_q              <= '0;
            inflight_scrub_word_q   <= '0;
            inflight_scrub_bank_q   <= '0;
            bank_word_cursor_q      <= '0;
            bank_ce_hist_q          <= '0;
            bank_ue_hist_q          <= '0;
            bank_scrub_done_epoch_q <= '0;
            rd_a_addr_d1_q          <= '0;
            rd_b_addr_d1_q          <= '0;
            ce_count_q              <= 32'd0;
            ue_count_q              <= 32'd0;
            scrub_ops_q             <= 32'd0;
            scrub_wb_q              <= 32'd0;
            scrub_epoch_count_q     <= 32'd0;
            ce_seen_q               <= 1'b0;
            ue_seen_q               <= 1'b0;
            last_err_bank_q         <= '0;
            last_err_word_q         <= '0;
            last_err_syndrome_q     <= '0;
            last_err_port_q         <= 3'd0;
        end else begin
            rd_a_addr_d1_q <= bank_rd_a_addr;
            rd_b_addr_d1_q <= bank_rd_b_addr;

            if (selected_scrub_valid) begin
                inflight_scrub_word_q <= bank_word_cursor_q[selected_scrub_bank];
                inflight_scrub_bank_q <= selected_scrub_bank;
                scrub_ops_q           <= sat_add_32(scrub_ops_q, 7'd1);
                bank_ptr_q            <= selected_scrub_bank + TMEM_BANK_ID_W'(1);

                if (bank_word_cursor_q[selected_scrub_bank] == TMEM_BANK_ADDR_W'(BANK_DEPTH - 1)) begin
                    bank_word_cursor_q[selected_scrub_bank]      <= '0;
                    bank_scrub_done_epoch_q[selected_scrub_bank] <= 1'b1;
                end else begin
                    bank_word_cursor_q[selected_scrub_bank] <= bank_word_cursor_q[selected_scrub_bank] + TMEM_BANK_ADDR_W'(1);
                end

                if (word_ptr_q == TMEM_BANK_ADDR_W'(BANK_DEPTH - 1)) begin
                    word_ptr_q <= '0;
                end else begin
                    word_ptr_q <= word_ptr_q + TMEM_BANK_ADDR_W'(1);
                end
            end

            if (scrub_sweep_wrap_pulse) begin
                bank_scrub_done_epoch_q <= '0;
                scrub_epoch_count_q     <= scrub_epoch_count_q + 32'd1;
            end

            for (int b = 0; b < NUM_BANKS; ++b) begin
                if (bank_ce_pulse[b] && (bank_ce_hist_q[b] != 16'hFFFF)) begin
                    bank_ce_hist_q[b] <= bank_ce_hist_q[b] + 16'd1;
                end
                if (bank_ue_pulse[b] && (bank_ue_hist_q[b] != 16'hFFFF)) begin
                    bank_ue_hist_q[b] <= bank_ue_hist_q[b] + 16'd1;
                end
            end

            if (|ce_events_cycle) begin
                ce_count_q <= sat_add_32(ce_count_q, ce_events_cycle);
            end
            if (|ue_events_cycle) begin
                ue_count_q <= sat_add_32(ue_count_q, ue_events_cycle);
            end
            if (|scrub_wb_cycle) begin
                scrub_wb_q <= sat_add_32(scrub_wb_q, {1'b0, scrub_wb_cycle});
            end

            if (any_ce_cycle || any_ue_cycle) begin
                ce_seen_q           <= ce_seen_q || any_ce_cycle;
                ue_seen_q           <= ue_seen_q || any_ue_cycle;
                last_err_bank_q     <= err_bank_comb;
                last_err_word_q     <= err_word_comb;
                last_err_syndrome_q <= err_syndrome_comb;
                last_err_port_q     <= err_source_port_comb;
            end
        end
    end

    `UNUSED_VAR (inflight_scrub_bank_q)
    `UNUSED_VAR (bank_ce_hist_q)
    `UNUSED_VAR (bank_ue_hist_q)
    `UNUSED_VAR (scrub_epoch_count_q)
    `UNUSED_VAR (last_err_port_q)

    assign ecc_ce_count_out    = ce_count_q;
    assign ecc_ue_count_out    = ue_count_q;
    assign scrub_ops_count_out = scrub_ops_q;
    assign scrub_wb_count_out  = scrub_wb_q;

    always_comb begin
        ecc_status_out.ce_detected    = ce_seen_q;
        ecc_status_out.ue_detected    = ue_seen_q;
        ecc_status_out.last_bank_id   = last_err_bank_q;
        ecc_status_out.last_word_addr = last_err_word_q;
        ecc_status_out.last_syndrome  = last_err_syndrome_q;
        ecc_status_out.ce_total       = ce_count_q;
        ecc_status_out.ue_total       = ue_count_q;
    end

endmodule
