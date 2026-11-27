// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_sram_bank #(
    parameter int BANK_ID    = 0,
    parameter int BANK_DEPTH = VX_tmem_pkg::TMEM_BANK_DEPTH_WORDS
) (
    input  logic                                       clk,
    input  logic                                       reset,
    // Bank power-gating control
    input  logic                                       bank_pwr_on,
    // Read Port A
    input  logic                                       rd_a_valid,
    input  logic [VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0]   rd_a_addr,
    output logic                                       rd_a_rsp_valid,
    output logic [VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]    rd_a_rsp_data,
    output logic                                       rd_a_ecc_ce,
    output logic                                       rd_a_ecc_ue,
    output logic [VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0]  rd_a_syndrome,
    // Read Port B
    input  logic                                       rd_b_valid,
    input  logic [VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0]   rd_b_addr,
    output logic                                       rd_b_rsp_valid,
    output logic [VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]    rd_b_rsp_data,
    output logic                                       rd_b_ecc_ce,
    output logic                                       rd_b_ecc_ue,
    output logic [VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0]  rd_b_syndrome,
    // Write Port (supports full-word 8-byte write and partial-BE RMW)
    input  logic                                       wr_valid,
    output logic                                       wr_ready,
    input  logic [VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0]   wr_addr,
    input  logic [VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]    wr_data,
    input  logic [VX_tmem_pkg::TMEM_BANK_WIDTH_BYTES-1:0] wr_be,
    // Fault injection hook
    input  logic                                       ecc_inj_en,
    input  logic [VX_tmem_pkg::TMEM_ECC_CODE_W-1:0]    ecc_inj_mask,
    // Patrol scrub read/writeback interface
    input  logic                                       scrub_req_valid,
    output logic                                       scrub_req_ready,
    input  logic [VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0]   scrub_req_addr,
    output logic                                       scrub_rsp_valid,
    output logic                                       scrub_rsp_ce,
    output logic                                       scrub_rsp_ue,
    output logic [VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0]  scrub_rsp_syndrome,
    output logic                                       scrub_wb_issued,
    // Hazard & bypass visibility for external forwarding unit
    output logic                                       rmw_active,
    output logic [VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0]   rmw_addr,
    output logic [VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]    rmw_merged_data,
    output logic                                       rmw_commit_valid,
    output logic [31:0]                                rmw_count_out
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(BANK_DEPTH == 1024, ("Bank depth must be 1024 words (8 KiB)"))
    `STATIC_ASSERT(TMEM_ECC_CODE_W == 72, ("Codeword width must be 72 bits"))
    `UNUSED_PARAM (BANK_ID)

    // RMW FSM for partial byte-enable writes and patrol scrub corrective writebacks
    typedef enum logic [1:0] {
        RMW_IDLE     = 2'd0,
        RMW_WAIT_RD  = 2'd1,
        RMW_COMMIT   = 2'd2,
        RMW_SCRUB_WB = 2'd3
    } rmw_state_e;

    rmw_state_e                             rmw_state_q;
    rmw_state_e                             rmw_state_n;
    logic [TMEM_BANK_ADDR_W-1:0]            rmw_addr_q;
    logic [TMEM_ECC_DATA_W-1:0]             rmw_wr_data_q;
    logic [TMEM_BANK_WIDTH_BYTES-1:0]       rmw_wr_be_q;
    logic                                   rmw_inj_en_q;
    logic [TMEM_ECC_CODE_W-1:0]             rmw_inj_mask_q;
    logic [31:0]                            rmw_count_q;

    // Pending scrub address, read tracking, and per-bank telemetry counters
    logic                                   scrub_rd_issued;
    logic                                   scrub_rd_q;
    logic [TMEM_BANK_ADDR_W-1:0]            scrub_addr_q;
    logic                                   scrub_wb_pending_q;
    logic [TMEM_BANK_ADDR_W-1:0]            scrub_wb_addr_q;
    logic [TMEM_ECC_DATA_W-1:0]             scrub_wb_data_q;

    logic [31:0]                            rd_a_ops_q;
    logic [31:0]                            rd_b_ops_q;
    logic [31:0]                            wr_full_ops_q;
    logic [31:0]                            scrub_wb_ops_q;
    logic [31:0]                            bank_ce_events_q;
    logic [31:0]                            bank_ue_events_q;
    logic [TMEM_BANK_ADDR_W-1:0]            last_wr_addr_q;
    logic [TMEM_ECC_DATA_W-1:0]             last_wr_data_q;
    logic                                   last_wr_valid_q;

    // Helper: merge old 64-bit word with new write bytes according to wr_be
    function automatic logic [TMEM_ECC_DATA_W-1:0] merge_bytes64(
        input logic [TMEM_ECC_DATA_W-1:0]       old_data,
        input logic [TMEM_ECC_DATA_W-1:0]       new_data,
        input logic [TMEM_BANK_WIDTH_BYTES-1:0] byte_en
    );
        logic [TMEM_ECC_DATA_W-1:0] merged;
        merged = old_data;
        for (int b = 0; b < TMEM_BANK_WIDTH_BYTES; ++b) begin
            if (byte_en[b]) begin
                merged[b*8 +: 8] = new_data[b*8 +: 8];
            end
        end
        return merged;
    endfunction

    logic is_full_write;
    logic is_partial_write;
    logic sram_write_en;
    logic [TMEM_BANK_ADDR_W-1:0] sram_write_addr;
    logic [TMEM_ECC_CODE_W-1:0]  sram_write_codeword;

    assign is_full_write    = wr_valid && (&wr_be);
    assign is_partial_write = wr_valid && (|wr_be) && !(&wr_be);

    // Bank write ready when power is on and not stalled in an active RMW sequence
    assign wr_ready        = bank_pwr_on && (rmw_state_q == RMW_IDLE);
    // Scrub accepted only when bank is idle on Port B and no active RMW or pending write
    assign scrub_req_ready = bank_pwr_on && (rmw_state_q == RMW_IDLE) && !wr_valid && !rd_b_valid && !scrub_wb_pending_q;

    // Port A, Port B, and RMW/Scrub read channels backed by three mirror-written
    // VX_dp_ram banks (1024 x 72b each) to guarantee non-blocking 2R1W + RMW/scrub
    // execution with single-cycle synchronous read latency and deterministic bypass.
    logic                        ram_a_rd_en;
    logic [TMEM_BANK_ADDR_W-1:0] ram_a_rd_addr;
    logic [TMEM_ECC_CODE_W-1:0]  ram_a_rd_codeword;

    logic                        ram_b_rd_en;
    logic [TMEM_BANK_ADDR_W-1:0] ram_b_rd_addr;
    logic [TMEM_ECC_CODE_W-1:0]  ram_b_rd_codeword;

    logic                        ram_rmw_rd_en;
    logic [TMEM_BANK_ADDR_W-1:0] ram_rmw_rd_addr;
    logic [TMEM_ECC_CODE_W-1:0]  ram_rmw_rd_codeword;

    assign ram_a_rd_en   = bank_pwr_on && rd_a_valid;
    assign ram_a_rd_addr = rd_a_addr;

    assign ram_b_rd_en   = bank_pwr_on && rd_b_valid;
    assign ram_b_rd_addr = rd_b_addr;

    assign scrub_rd_issued = scrub_req_valid && scrub_req_ready;
    assign ram_rmw_rd_en   = bank_pwr_on && ((is_partial_write && wr_ready) || scrub_rd_issued);
    assign ram_rmw_rd_addr = (is_partial_write && wr_ready) ? wr_addr : scrub_req_addr;

    // ECC encoder instance for writes (full-word, RMW commit, and scrub writeback)
    logic [TMEM_ECC_DATA_W-1:0]   enc_data_in;
    logic                         enc_valid_in;
    logic                         enc_inj_en;
    logic [TMEM_ECC_CODE_W-1:0]   enc_inj_mask;
    logic [TMEM_ECC_CODE_W-1:0]   enc_codeword_out;
    logic [TMEM_ECC_PARITY_W-1:0] enc_parity_out;
    logic                         enc_valid_out;
    logic                         enc_inj_active;

    VX_tmem_ecc_enc #(
        .PIPE_STAGES (0)
    ) u_ecc_enc (
        .clk            (clk),
        .reset          (reset),
        .valid_in       (enc_valid_in),
        .data_in        (enc_data_in),
        .fault_inj_en   (enc_inj_en),
        .fault_inj_mask (enc_inj_mask),
        .valid_out      (enc_valid_out),
        .parity_out     (enc_parity_out),
        .codeword_out   (enc_codeword_out),
        .inj_active_out (enc_inj_active)
    );
    `UNUSED_VAR (enc_parity_out)
    `UNUSED_VAR (enc_valid_out)
    `UNUSED_VAR (enc_inj_active)

    // Registered read pipeline + same-cycle write-to-read bypass registers
    logic                        rd_a_valid_q;
    logic                        rd_a_bypass_q;
    logic [TMEM_ECC_CODE_W-1:0]  rd_a_bypass_cw_q;
    logic                        rd_b_valid_q;
    logic                        rd_b_bypass_q;
    logic [TMEM_ECC_CODE_W-1:0]  rd_b_bypass_cw_q;
    logic                        rmw_bypass_q;
    logic [TMEM_ECC_CODE_W-1:0]  rmw_bypass_cw_q;

    // Three synchronized VX_dp_ram arrays (1024 x 72b, initialized to valid zero ECC codeword)
    localparam logic [TMEM_ECC_CODE_W-1:0] ZERO_ECC_CODEWORD = {TMEM_ECC_CODE_W{1'b0}};

    VX_dp_ram #(
        .DATAW       (TMEM_ECC_CODE_W),
        .SIZE        (BANK_DEPTH),
        .WRENW       (1),
        .OUT_REG     (1),
        .RDW_MODE    ("W"),
        .RESET_RAM   (1),
        .INIT_ENABLE (1),
        .INIT_VALUE  (ZERO_ECC_CODEWORD)
    ) u_sram_port_a (
        .clk   (clk),
        .reset (reset),
        .read  (ram_a_rd_en),
        .write (sram_write_en),
        .wren  (1'b1),
        .waddr (sram_write_addr),
        .wdata (sram_write_codeword),
        .raddr (ram_a_rd_addr),
        .rdata (ram_a_rd_codeword)
    );

    VX_dp_ram #(
        .DATAW       (TMEM_ECC_CODE_W),
        .SIZE        (BANK_DEPTH),
        .WRENW       (1),
        .OUT_REG     (1),
        .RDW_MODE    ("W"),
        .RESET_RAM   (1),
        .INIT_ENABLE (1),
        .INIT_VALUE  (ZERO_ECC_CODEWORD)
    ) u_sram_port_b (
        .clk   (clk),
        .reset (reset),
        .read  (ram_b_rd_en),
        .write (sram_write_en),
        .wren  (1'b1),
        .waddr (sram_write_addr),
        .wdata (sram_write_codeword),
        .raddr (ram_b_rd_addr),
        .rdata (ram_b_rd_codeword)
    );

    VX_dp_ram #(
        .DATAW       (TMEM_ECC_CODE_W),
        .SIZE        (BANK_DEPTH),
        .WRENW       (1),
        .OUT_REG     (1),
        .RDW_MODE    ("W"),
        .RESET_RAM   (1),
        .INIT_ENABLE (1),
        .INIT_VALUE  (ZERO_ECC_CODEWORD)
    ) u_sram_port_rmw (
        .clk   (clk),
        .reset (reset),
        .read  (ram_rmw_rd_en),
        .write (sram_write_en),
        .wren  (1'b1),
        .waddr (sram_write_addr),
        .wdata (sram_write_codeword),
        .raddr (ram_rmw_rd_addr),
        .rdata (ram_rmw_rd_codeword)
    );

    // ECC decoders for Port A, Port B, and RMW/Scrub read port
    logic [TMEM_ECC_CODE_W-1:0]   dec_a_codeword_in;
    logic [TMEM_ECC_DATA_W-1:0]   dec_a_data_out;
    logic [TMEM_ECC_PARITY_W-1:0] dec_a_parity_out;
    logic [TMEM_ECC_CODE_W-1:0]   dec_a_cw_out;
    logic [TMEM_ECC_PARITY_W-1:0] dec_a_syndrome_out;
    logic                         dec_a_valid_out;
    logic                         dec_a_ce_out;
    logic                         dec_a_ue_out;
    logic                         dec_a_err_par;
    logic [6:0]                   dec_a_err_idx;

    logic [TMEM_ECC_CODE_W-1:0]   dec_b_codeword_in;
    logic [TMEM_ECC_DATA_W-1:0]   dec_b_data_out;
    logic [TMEM_ECC_PARITY_W-1:0] dec_b_parity_out;
    logic [TMEM_ECC_CODE_W-1:0]   dec_b_cw_out;
    logic [TMEM_ECC_PARITY_W-1:0] dec_b_syndrome_out;
    logic                         dec_b_valid_out;
    logic                         dec_b_ce_out;
    logic                         dec_b_ue_out;
    logic                         dec_b_err_par;
    logic [6:0]                   dec_b_err_idx;

    logic [TMEM_ECC_CODE_W-1:0]   dec_rmw_codeword_in;
    logic [TMEM_ECC_DATA_W-1:0]   dec_rmw_data_out;
    logic [TMEM_ECC_PARITY_W-1:0] dec_rmw_parity_out;
    logic [TMEM_ECC_CODE_W-1:0]   dec_rmw_cw_out;
    logic [TMEM_ECC_PARITY_W-1:0] dec_rmw_syndrome_out;
    logic                         dec_rmw_valid_out;
    logic                         dec_rmw_ce_out;
    logic                         dec_rmw_ue_out;
    logic                         dec_rmw_err_par;
    logic [6:0]                   dec_rmw_err_idx;

    assign dec_a_codeword_in   = rd_a_bypass_q ? rd_a_bypass_cw_q : ram_a_rd_codeword;
    assign dec_b_codeword_in   = rd_b_bypass_q ? rd_b_bypass_cw_q : ram_b_rd_codeword;
    assign dec_rmw_codeword_in = rmw_bypass_q  ? rmw_bypass_cw_q  : ram_rmw_rd_codeword;

    VX_tmem_ecc_dec #(
        .PIPE_STAGES (0)
    ) u_ecc_dec_a (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (rd_a_valid_q),
        .codeword_in       (dec_a_codeword_in),
        .valid_out         (dec_a_valid_out),
        .data_out          (dec_a_data_out),
        .parity_out        (dec_a_parity_out),
        .codeword_out      (dec_a_cw_out),
        .syndrome_out      (dec_a_syndrome_out),
        .ce_out            (dec_a_ce_out),
        .ue_out            (dec_a_ue_out),
        .err_in_parity_out (dec_a_err_par),
        .err_bit_idx_out   (dec_a_err_idx)
    );
    `UNUSED_VAR (dec_a_parity_out)
    `UNUSED_VAR (dec_a_cw_out)
    `UNUSED_VAR (dec_a_err_par)
    `UNUSED_VAR (dec_a_err_idx)

    VX_tmem_ecc_dec #(
        .PIPE_STAGES (0)
    ) u_ecc_dec_b (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (rd_b_valid_q),
        .codeword_in       (dec_b_codeword_in),
        .valid_out         (dec_b_valid_out),
        .data_out          (dec_b_data_out),
        .parity_out        (dec_b_parity_out),
        .codeword_out      (dec_b_cw_out),
        .syndrome_out      (dec_b_syndrome_out),
        .ce_out            (dec_b_ce_out),
        .ue_out            (dec_b_ue_out),
        .err_in_parity_out (dec_b_err_par),
        .err_bit_idx_out   (dec_b_err_idx)
    );
    `UNUSED_VAR (dec_b_parity_out)
    `UNUSED_VAR (dec_b_cw_out)
    `UNUSED_VAR (dec_b_err_par)
    `UNUSED_VAR (dec_b_err_idx)

    VX_tmem_ecc_dec #(
        .PIPE_STAGES (0)
    ) u_ecc_dec_rmw (
        .clk               (clk),
        .reset             (reset),
        .valid_in          ((rmw_state_q == RMW_COMMIT) || scrub_rd_q),
        .codeword_in       (dec_rmw_codeword_in),
        .valid_out         (dec_rmw_valid_out),
        .data_out          (dec_rmw_data_out),
        .parity_out        (dec_rmw_parity_out),
        .codeword_out      (dec_rmw_cw_out),
        .syndrome_out      (dec_rmw_syndrome_out),
        .ce_out            (dec_rmw_ce_out),
        .ue_out            (dec_rmw_ue_out),
        .err_in_parity_out (dec_rmw_err_par),
        .err_bit_idx_out   (dec_rmw_err_idx)
    );
    `UNUSED_VAR (dec_rmw_valid_out)
    `UNUSED_VAR (dec_rmw_parity_out)
    `UNUSED_VAR (dec_rmw_cw_out)
    `UNUSED_VAR (dec_rmw_err_par)
    `UNUSED_VAR (dec_rmw_err_idx)

    // Write-port multiplexer & RMW state machine
    logic [TMEM_ECC_DATA_W-1:0] merged_rmw_word;

    always_comb begin
        merged_rmw_word = merge_bytes64(dec_rmw_data_out, rmw_wr_data_q, rmw_wr_be_q);

        rmw_state_n        = rmw_state_q;
        sram_write_en      = 1'b0;
        sram_write_addr    = wr_addr;
        enc_valid_in       = 1'b0;
        enc_data_in        = wr_data;
        enc_inj_en         = 1'b0;
        enc_inj_mask       = '0;
        scrub_wb_issued    = 1'b0;

        case (rmw_state_q)
            RMW_IDLE: begin
                if (bank_pwr_on && is_full_write) begin
                    sram_write_en   = 1'b1;
                    sram_write_addr = wr_addr;
                    enc_valid_in    = 1'b1;
                    enc_data_in     = wr_data;
                    enc_inj_en      = ecc_inj_en;
                    enc_inj_mask    = ecc_inj_mask;
                end else if (bank_pwr_on && is_partial_write) begin
                    rmw_state_n = RMW_COMMIT;
                end else if (bank_pwr_on && scrub_wb_pending_q) begin
                    sram_write_en   = 1'b1;
                    sram_write_addr = scrub_wb_addr_q;
                    enc_valid_in    = 1'b1;
                    enc_data_in     = scrub_wb_data_q;
                    enc_inj_en      = 1'b0;
                    enc_inj_mask    = '0;
                    scrub_wb_issued = 1'b1;
                end
            end

            RMW_WAIT_RD: begin
                rmw_state_n = RMW_COMMIT;
            end

            RMW_COMMIT: begin
                sram_write_en   = 1'b1;
                sram_write_addr = rmw_addr_q;
                enc_valid_in    = 1'b1;
                enc_data_in     = merged_rmw_word;
                enc_inj_en      = rmw_inj_en_q;
                enc_inj_mask    = rmw_inj_mask_q;
                rmw_state_n     = RMW_IDLE;
            end

            RMW_SCRUB_WB: begin
                sram_write_en   = 1'b1;
                sram_write_addr = scrub_wb_addr_q;
                enc_valid_in    = 1'b1;
                enc_data_in     = scrub_wb_data_q;
                scrub_wb_issued = 1'b1;
                rmw_state_n     = RMW_IDLE;
            end

            default: begin
                rmw_state_n = RMW_IDLE;
            end
        endcase

        sram_write_codeword = enc_codeword_out;
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            rmw_state_q        <= RMW_IDLE;
            rmw_addr_q         <= '0;
            rmw_wr_data_q      <= '0;
            rmw_wr_be_q        <= '0;
            rmw_inj_en_q       <= 1'b0;
            rmw_inj_mask_q     <= '0;
            rmw_count_q        <= 32'd0;
            rd_a_valid_q       <= 1'b0;
            rd_a_bypass_q      <= 1'b0;
            rd_a_bypass_cw_q   <= '0;
            rd_b_valid_q       <= 1'b0;
            rd_b_bypass_q      <= 1'b0;
            rd_b_bypass_cw_q   <= '0;
            rmw_bypass_q       <= 1'b0;
            rmw_bypass_cw_q    <= '0;
            scrub_rd_q         <= 1'b0;
            scrub_addr_q       <= '0;
            scrub_wb_pending_q <= 1'b0;
            scrub_wb_addr_q    <= '0;
            scrub_wb_data_q    <= '0;
            rd_a_ops_q         <= 32'd0;
            rd_b_ops_q         <= 32'd0;
            wr_full_ops_q      <= 32'd0;
            scrub_wb_ops_q     <= 32'd0;
            bank_ce_events_q   <= 32'd0;
            bank_ue_events_q   <= 32'd0;
            last_wr_addr_q     <= '0;
            last_wr_data_q     <= '0;
            last_wr_valid_q    <= 1'b0;
        end else begin
            rmw_state_q <= rmw_state_n;

            if ((rmw_state_q == RMW_IDLE) && bank_pwr_on && is_partial_write) begin
                rmw_addr_q     <= wr_addr;
                rmw_wr_data_q  <= wr_data;
                rmw_wr_be_q    <= wr_be;
                rmw_inj_en_q   <= ecc_inj_en;
                rmw_inj_mask_q <= ecc_inj_mask;
            end

            if (rmw_state_q == RMW_COMMIT) begin
                rmw_count_q <= rmw_count_q + 32'd1;
            end

            if (ram_a_rd_en) begin
                rd_a_ops_q <= rd_a_ops_q + 32'd1;
            end
            if (ram_b_rd_en) begin
                rd_b_ops_q <= rd_b_ops_q + 32'd1;
            end
            if ((rmw_state_q == RMW_IDLE) && bank_pwr_on && is_full_write) begin
                wr_full_ops_q <= wr_full_ops_q + 32'd1;
            end
            if (scrub_wb_issued) begin
                scrub_wb_ops_q <= scrub_wb_ops_q + 32'd1;
            end
            if (sram_write_en) begin
                last_wr_valid_q <= 1'b1;
                last_wr_addr_q  <= sram_write_addr;
                last_wr_data_q  <= enc_data_in;
            end

            if ((dec_a_valid_out && dec_a_ce_out) ||
                (dec_b_valid_out && dec_b_ce_out) ||
                (scrub_rd_q && dec_rmw_ce_out)) begin
                bank_ce_events_q <= bank_ce_events_q + 32'd1;
            end
            if ((dec_a_valid_out && dec_a_ue_out) ||
                (dec_b_valid_out && dec_b_ue_out) ||
                (scrub_rd_q && dec_rmw_ue_out)) begin
                bank_ue_events_q <= bank_ue_events_q + 32'd1;
            end

            // Track 1-cycle synchronous read valid and same-cycle write bypass
            rd_a_valid_q     <= ram_a_rd_en;
            rd_a_bypass_q    <= ram_a_rd_en && sram_write_en && (ram_a_rd_addr == sram_write_addr);
            rd_a_bypass_cw_q <= sram_write_codeword;

            rd_b_valid_q     <= ram_b_rd_en;
            rd_b_bypass_q    <= ram_b_rd_en && sram_write_en && (ram_b_rd_addr == sram_write_addr);
            rd_b_bypass_cw_q <= sram_write_codeword;

            rmw_bypass_q     <= ram_rmw_rd_en && sram_write_en && (ram_rmw_rd_addr == sram_write_addr);
            rmw_bypass_cw_q  <= sram_write_codeword;

            // Patrol scrub read -> response -> optional corrective writeback latch.
            // Invalidate pending scrub writeback if a normal write commits to that address,
            // and suppress latching a stale scrub correction if a normal write commits to scrub_addr_q.
            scrub_rd_q   <= scrub_rd_issued;
            scrub_addr_q <= scrub_req_addr;

            if (scrub_wb_issued ||
                (scrub_wb_pending_q && sram_write_en && !scrub_wb_issued && (sram_write_addr == scrub_wb_addr_q))) begin
                scrub_wb_pending_q <= 1'b0;
            end
            if (scrub_rd_q && dec_rmw_ce_out && !dec_rmw_ue_out &&
                !(sram_write_en && !scrub_wb_issued && (sram_write_addr == scrub_addr_q))) begin
                scrub_wb_pending_q <= 1'b1;
                scrub_wb_addr_q    <= scrub_addr_q;
                scrub_wb_data_q    <= dec_rmw_data_out;
            end
        end
    end

    `UNUSED_VAR (rd_a_ops_q)
    `UNUSED_VAR (rd_b_ops_q)
    `UNUSED_VAR (wr_full_ops_q)
    `UNUSED_VAR (scrub_wb_ops_q)
    `UNUSED_VAR (bank_ce_events_q)
    `UNUSED_VAR (bank_ue_events_q)
    `UNUSED_VAR (last_wr_addr_q)
    `UNUSED_VAR (last_wr_data_q)
    `UNUSED_VAR (last_wr_valid_q)

    assign rd_a_rsp_valid     = dec_a_valid_out;
    assign rd_a_rsp_data      = dec_a_data_out;
    assign rd_a_ecc_ce        = dec_a_ce_out;
    assign rd_a_ecc_ue        = dec_a_ue_out;
    assign rd_a_syndrome      = dec_a_syndrome_out;

    assign rd_b_rsp_valid     = dec_b_valid_out;
    assign rd_b_rsp_data      = dec_b_data_out;
    assign rd_b_ecc_ce        = dec_b_ce_out;
    assign rd_b_ecc_ue        = dec_b_ue_out;
    assign rd_b_syndrome      = dec_b_syndrome_out;

    assign scrub_rsp_valid    = scrub_rd_q;
    assign scrub_rsp_ce       = scrub_rd_q && dec_rmw_ce_out;
    assign scrub_rsp_ue       = scrub_rd_q && dec_rmw_ue_out;
    assign scrub_rsp_syndrome = dec_rmw_syndrome_out;

    assign rmw_active         = (rmw_state_q == RMW_COMMIT) || (rmw_state_q == RMW_WAIT_RD);
    assign rmw_addr           = rmw_addr_q;
    assign rmw_merged_data    = merged_rmw_word;
    assign rmw_commit_valid   = (rmw_state_q == RMW_COMMIT);
    assign rmw_count_out      = rmw_count_q;

endmodule
