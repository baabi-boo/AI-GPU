// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_bank_array #(
    parameter int NUM_BANKS       = VX_tmem_pkg::TMEM_NUM_BANKS,        // 32
    parameter int BANK_DEPTH      = VX_tmem_pkg::TMEM_BANK_DEPTH_WORDS, // 1024 (32*1024*8B = 256 KiB)
    parameter int LANES           = 8                                   // concurrent request lanes per port
) (
    input  logic                                clk,
    input  logic                                reset,
    // Read Port A (e.g., LD / MMA A)
    input  logic [LANES-1:0]                    rd_a_valid,
    output logic [LANES-1:0]                    rd_a_ready,
    input  logic [LANES-1:0][6:0]               rd_a_row,
    input  logic [LANES-1:0][8:0]               rd_a_col,
    input  VX_tmem_pkg::tmem_swizzle_e          rd_a_swizzle,
    output logic [LANES-1:0]                    rd_a_rsp_valid,
    output logic [LANES-1:0][63:0]              rd_a_rsp_data,
    output logic [LANES-1:0]                    rd_a_ecc_ce,
    output logic [LANES-1:0]                    rd_a_ecc_ue,
    // Read Port B (e.g., MMA B / C)
    input  logic [LANES-1:0]                    rd_b_valid,
    output logic [LANES-1:0]                    rd_b_ready,
    input  logic [LANES-1:0][6:0]               rd_b_row,
    input  logic [LANES-1:0][8:0]               rd_b_col,
    input  VX_tmem_pkg::tmem_swizzle_e          rd_b_swizzle,
    output logic [LANES-1:0]                    rd_b_rsp_valid,
    output logic [LANES-1:0][63:0]              rd_b_rsp_data,
    output logic [LANES-1:0]                    rd_b_ecc_ce,
    output logic [LANES-1:0]                    rd_b_ecc_ue,
    // Write Port (ST / MMA D)
    input  logic [LANES-1:0]                    wr_valid,
    output logic [LANES-1:0]                    wr_ready,
    input  logic [LANES-1:0][6:0]               wr_row,
    input  logic [LANES-1:0][8:0]               wr_col,
    input  VX_tmem_pkg::tmem_swizzle_e          wr_swizzle,
    input  logic [LANES-1:0][63:0]              wr_data,
    input  logic [LANES-1:0][7:0]               wr_be,
    // ECC fault injection & scrub controls
    input  logic                                ecc_inj_en,
    input  logic [4:0]                          ecc_inj_bank,
    input  logic [71:0]                         ecc_inj_mask,
    input  logic                                scrub_en,
    // Status & telemetry
    output logic [5:0]                          rd_a_conflict_ways,
    output logic [5:0]                          rd_b_conflict_ways,
    output logic [5:0]                          wr_conflict_ways,
    output logic [31:0]                         ecc_ce_count,
    output logic [31:0]                         ecc_ue_count
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(NUM_BANKS == 32, ("TMEM bank array requires 32 banks"))
    `STATIC_ASSERT(BANK_DEPTH == 1024, ("TMEM bank array requires 1024 words/bank"))
    `STATIC_ASSERT(LANES >= 1 && LANES <= 32, ("LANES must be in [1, 32]"))
    `STATIC_ASSERT(tmem_geometry_consistent(), ("TMEM package geometry mismatch"))

    // -------------------------------------------------------------------------
    // 1. Multi-Mode Swizzle Address Translators (Port A, Port B, Write Port)
    // -------------------------------------------------------------------------
    logic [LANES-1:0]                        swz_a_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    swz_a_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  swz_a_word_addr;
    logic [LANES-1:0]                        swz_a_half_sel;
    logic [LANES-1:0]                        swz_a_oob;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        swz_a_inv_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        swz_a_inv_col;
    logic [LANES-1:0]                        swz_a_bijection_ok;
    logic [31:0]                             swz_a_ops_count;

    VX_tmem_swizzle_addr #(
        .LANES (LANES)
    ) u_swizzle_rd_a (
        .clk               (clk),
        .reset             (reset),
        .pipe_en           (1'b0),
        .valid_in          (rd_a_valid),
        .row_in            (rd_a_row),
        .col_in            (rd_a_col),
        .swizzle_mode      (rd_a_swizzle),
        .inv_enable        (1'b0),
        .inv_bank_in       ('0),
        .inv_word_in       ('0),
        .inv_half_in       ('0),
        .valid_out         (swz_a_valid),
        .bank_id_out       (swz_a_bank_id),
        .word_addr_out     (swz_a_word_addr),
        .half_sel_out      (swz_a_half_sel),
        .addr_oob_out      (swz_a_oob),
        .inv_row_out       (swz_a_inv_row),
        .inv_col_out       (swz_a_inv_col),
        .bijection_ok_out  (swz_a_bijection_ok),
        .swizzle_ops_count (swz_a_ops_count)
    );
    `UNUSED_VAR (swz_a_half_sel)
    `UNUSED_VAR (swz_a_oob)
    `UNUSED_VAR (swz_a_inv_row)
    `UNUSED_VAR (swz_a_inv_col)
    `UNUSED_VAR (swz_a_bijection_ok)
    `UNUSED_VAR (swz_a_ops_count)

    logic [LANES-1:0]                        swz_b_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    swz_b_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  swz_b_word_addr;
    logic [LANES-1:0]                        swz_b_half_sel;
    logic [LANES-1:0]                        swz_b_oob;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        swz_b_inv_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        swz_b_inv_col;
    logic [LANES-1:0]                        swz_b_bijection_ok;
    logic [31:0]                             swz_b_ops_count;

    VX_tmem_swizzle_addr #(
        .LANES (LANES)
    ) u_swizzle_rd_b (
        .clk               (clk),
        .reset             (reset),
        .pipe_en           (1'b0),
        .valid_in          (rd_b_valid),
        .row_in            (rd_b_row),
        .col_in            (rd_b_col),
        .swizzle_mode      (rd_b_swizzle),
        .inv_enable        (1'b0),
        .inv_bank_in       ('0),
        .inv_word_in       ('0),
        .inv_half_in       ('0),
        .valid_out         (swz_b_valid),
        .bank_id_out       (swz_b_bank_id),
        .word_addr_out     (swz_b_word_addr),
        .half_sel_out      (swz_b_half_sel),
        .addr_oob_out      (swz_b_oob),
        .inv_row_out       (swz_b_inv_row),
        .inv_col_out       (swz_b_inv_col),
        .bijection_ok_out  (swz_b_bijection_ok),
        .swizzle_ops_count (swz_b_ops_count)
    );
    `UNUSED_VAR (swz_b_half_sel)
    `UNUSED_VAR (swz_b_oob)
    `UNUSED_VAR (swz_b_inv_row)
    `UNUSED_VAR (swz_b_inv_col)
    `UNUSED_VAR (swz_b_bijection_ok)
    `UNUSED_VAR (swz_b_ops_count)

    logic [LANES-1:0]                        swz_w_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    swz_w_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  swz_w_word_addr;
    logic [LANES-1:0]                        swz_w_half_sel;
    logic [LANES-1:0]                        swz_w_oob;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        swz_w_inv_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        swz_w_inv_col;
    logic [LANES-1:0]                        swz_w_bijection_ok;
    logic [31:0]                             swz_w_ops_count;

    VX_tmem_swizzle_addr #(
        .LANES (LANES)
    ) u_swizzle_wr (
        .clk               (clk),
        .reset             (reset),
        .pipe_en           (1'b0),
        .valid_in          (wr_valid),
        .row_in            (wr_row),
        .col_in            (wr_col),
        .swizzle_mode      (wr_swizzle),
        .inv_enable        (1'b0),
        .inv_bank_in       ('0),
        .inv_word_in       ('0),
        .inv_half_in       ('0),
        .valid_out         (swz_w_valid),
        .bank_id_out       (swz_w_bank_id),
        .word_addr_out     (swz_w_word_addr),
        .half_sel_out      (swz_w_half_sel),
        .addr_oob_out      (swz_w_oob),
        .inv_row_out       (swz_w_inv_row),
        .inv_col_out       (swz_w_inv_col),
        .bijection_ok_out  (swz_w_bijection_ok),
        .swizzle_ops_count (swz_w_ops_count)
    );
    `UNUSED_VAR (swz_w_oob)
    `UNUSED_VAR (swz_w_inv_row)
    `UNUSED_VAR (swz_w_inv_col)
    `UNUSED_VAR (swz_w_bijection_ok)
    `UNUSED_VAR (swz_w_ops_count)

    // -------------------------------------------------------------------------
    // 2. Bank Power & Clock-Gating Controller + Bank Status Wires
    // -------------------------------------------------------------------------
    logic [NUM_BANKS-1:0]                              bank_pwr_on;
    logic [NUM_BANKS-1:0]                              bank_clk_en;
    logic [NUM_BANKS-1:0]                              bank_ret_sleep;
    logic [NUM_BANKS-1:0]                              bank_waking;
    logic [NUM_BANKS-1:0]                              active_bank_mask;
    logic [5:0]                                        active_bank_count;
    logic [31:0]                                       total_sleep_cycles;
    logic [31:0]                                       total_wake_events;

    logic [NUM_BANKS-1:0]                              bank_rd_a_valid;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]        bank_rd_a_addr;
    logic [NUM_BANKS-1:0]                              bank_rd_a_rsp_valid;
    logic [NUM_BANKS-1:0][TMEM_ECC_DATA_W-1:0]         bank_rd_a_rsp_data;
    logic [NUM_BANKS-1:0]                              bank_rd_a_ecc_ce;
    logic [NUM_BANKS-1:0]                              bank_rd_a_ecc_ue;
    logic [NUM_BANKS-1:0][TMEM_ECC_PARITY_W-1:0]       bank_rd_a_syndrome;

    logic [NUM_BANKS-1:0]                              bank_rd_b_valid;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]        bank_rd_b_addr;
    logic [NUM_BANKS-1:0]                              bank_rd_b_rsp_valid;
    logic [NUM_BANKS-1:0][TMEM_ECC_DATA_W-1:0]         bank_rd_b_rsp_data;
    logic [NUM_BANKS-1:0]                              bank_rd_b_ecc_ce;
    logic [NUM_BANKS-1:0]                              bank_rd_b_ecc_ue;
    logic [NUM_BANKS-1:0][TMEM_ECC_PARITY_W-1:0]       bank_rd_b_syndrome;

    logic [NUM_BANKS-1:0]                              bank_wr_valid;
    logic [NUM_BANKS-1:0]                              bank_wr_ready;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]        bank_wr_addr;
    logic [NUM_BANKS-1:0][TMEM_ECC_DATA_W-1:0]         bank_wr_data;
    logic [NUM_BANKS-1:0][TMEM_BANK_WIDTH_BYTES-1:0]   bank_wr_be;

    logic [NUM_BANKS-1:0]                              bank_scrub_req_valid;
    logic [NUM_BANKS-1:0]                              bank_scrub_req_ready;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]        bank_scrub_req_addr;
    logic [NUM_BANKS-1:0]                              bank_scrub_rsp_valid;
    logic [NUM_BANKS-1:0]                              bank_scrub_rsp_ce;
    logic [NUM_BANKS-1:0]                              bank_scrub_rsp_ue;
    logic [NUM_BANKS-1:0][TMEM_ECC_PARITY_W-1:0]       bank_scrub_rsp_syndrome;
    logic [NUM_BANKS-1:0]                              bank_scrub_wb_issued;

    logic [NUM_BANKS-1:0]                              bank_rmw_active;
    logic [NUM_BANKS-1:0][TMEM_BANK_ADDR_W-1:0]        bank_rmw_addr;
    logic [NUM_BANKS-1:0][TMEM_ECC_DATA_W-1:0]         bank_rmw_merged_data;
    logic [NUM_BANKS-1:0]                              bank_rmw_commit_valid;
    logic [NUM_BANKS-1:0][31:0]                        bank_rmw_count;

    // Keep banks awake when auto-sleep is disabled or whenever traffic/scrubbing targets them
    logic [NUM_BANKS-1:0] rd_a_wake_req;
    logic [NUM_BANKS-1:0] rd_b_wake_req;
    logic [NUM_BANKS-1:0] wr_wake_req;

    always_comb begin
        rd_a_wake_req = '0;
        rd_b_wake_req = '0;
        wr_wake_req   = '0;
        for (int l = 0; l < LANES; ++l) begin
            if (swz_a_valid[l]) begin
                rd_a_wake_req[swz_a_bank_id[l]] = 1'b1;
            end
            if (swz_b_valid[l]) begin
                rd_b_wake_req[swz_b_bank_id[l]] = 1'b1;
            end
            if (swz_w_valid[l]) begin
                wr_wake_req[swz_w_bank_id[l]] = 1'b1;
            end
        end
    end

    VX_tmem_bank_power_ctrl #(
        .NUM_BANKS      (NUM_BANKS),
        .IDLE_SLEEP_CYC (64),
        .WAKE_LATENCY   (1)
    ) u_power_ctrl (
        .clk                         (clk),
        .reset                       (reset),
        .auto_sleep_en               (1'b0),
        .force_wake_mask             ({NUM_BANKS{1'b1}}),
        .bank_rd_a_act               (rd_a_wake_req | bank_rd_a_valid),
        .bank_rd_b_act               (rd_b_wake_req | bank_rd_b_valid),
        .bank_wr_act                 (wr_wake_req | bank_wr_valid),
        .bank_rmw_act                (bank_rmw_active),
        .bank_scrub_act              (bank_scrub_req_valid),
        .bank_pwr_on                 (bank_pwr_on),
        .bank_clk_en                 (bank_clk_en),
        .bank_retention_sleep        (bank_ret_sleep),
        .bank_waking                 (bank_waking),
        .active_bank_mask_out        (active_bank_mask),
        .active_bank_count_out       (active_bank_count),
        .total_bank_sleep_cycles_out (total_sleep_cycles),
        .total_bank_wake_events_out  (total_wake_events)
    );
    `UNUSED_VAR (bank_clk_en)
    `UNUSED_VAR (bank_ret_sleep)
    `UNUSED_VAR (bank_waking)
    `UNUSED_VAR (active_bank_mask)
    `UNUSED_VAR (active_bank_count)
    `UNUSED_VAR (total_sleep_cycles)
    `UNUSED_VAR (total_wake_events)

    // -------------------------------------------------------------------------
    // 3. Bank-Conflict Detectors & Wavefront Serializers (Port A, Port B, Write)
    // -------------------------------------------------------------------------
    logic [LANES-1:0]                        grant_a_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    grant_a_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  grant_a_word_addr;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]   grant_a_unused_data;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0] grant_a_unused_be;
    logic [LANES-1:0]                        grant_a_unused_half;
    logic [LANES-1:0]                        grant_a_lane_valid;
    logic                                    rd_a_conflict_det;
    logic                                    rd_a_ser_busy;
    logic [31:0]                             rd_a_conflict_cyc;

    VX_tmem_bank_conflict #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS),
        .IS_WRITE  (0)
    ) u_conflict_rd_a (
        .clk                   (clk),
        .reset                 (reset),
        .req_valid             (swz_a_valid),
        .req_ready             (rd_a_ready),
        .req_bank_id           (swz_a_bank_id),
        .req_word_addr         (swz_a_word_addr),
        .req_wr_data           ('0),
        .req_wr_be             ('0),
        .req_half_sel          (swz_a_half_sel),
        .bank_ready_mask       (bank_pwr_on),
        .grant_valid           (grant_a_valid),
        .grant_bank_id         (grant_a_bank_id),
        .grant_word_addr       (grant_a_word_addr),
        .grant_wr_data         (grant_a_unused_data),
        .grant_wr_be           (grant_a_unused_be),
        .grant_half_sel        (grant_a_unused_half),
        .grant_lane_idx_valid  (grant_a_lane_valid),
        .conflict_ways_out     (rd_a_conflict_ways),
        .conflict_detected_out (rd_a_conflict_det),
        .serializer_busy_out   (rd_a_ser_busy),
        .conflict_cycles_count (rd_a_conflict_cyc)
    );
    `UNUSED_VAR (grant_a_unused_data)
    `UNUSED_VAR (grant_a_unused_be)
    `UNUSED_VAR (grant_a_unused_half)
    `UNUSED_VAR (grant_a_lane_valid)
    `UNUSED_VAR (rd_a_conflict_det)
    `UNUSED_VAR (rd_a_ser_busy)
    `UNUSED_VAR (rd_a_conflict_cyc)

    logic [LANES-1:0]                        grant_b_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    grant_b_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  grant_b_word_addr;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]   grant_b_unused_data;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0] grant_b_unused_be;
    logic [LANES-1:0]                        grant_b_unused_half;
    logic [LANES-1:0]                        grant_b_lane_valid;
    logic                                    rd_b_conflict_det;
    logic                                    rd_b_ser_busy;
    logic [31:0]                             rd_b_conflict_cyc;

    VX_tmem_bank_conflict #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS),
        .IS_WRITE  (0)
    ) u_conflict_rd_b (
        .clk                   (clk),
        .reset                 (reset),
        .req_valid             (swz_b_valid),
        .req_ready             (rd_b_ready),
        .req_bank_id           (swz_b_bank_id),
        .req_word_addr         (swz_b_word_addr),
        .req_wr_data           ('0),
        .req_wr_be             ('0),
        .req_half_sel          (swz_b_half_sel),
        .bank_ready_mask       (bank_pwr_on),
        .grant_valid           (grant_b_valid),
        .grant_bank_id         (grant_b_bank_id),
        .grant_word_addr       (grant_b_word_addr),
        .grant_wr_data         (grant_b_unused_data),
        .grant_wr_be           (grant_b_unused_be),
        .grant_half_sel        (grant_b_unused_half),
        .grant_lane_idx_valid  (grant_b_lane_valid),
        .conflict_ways_out     (rd_b_conflict_ways),
        .conflict_detected_out (rd_b_conflict_det),
        .serializer_busy_out   (rd_b_ser_busy),
        .conflict_cycles_count (rd_b_conflict_cyc)
    );
    `UNUSED_VAR (grant_b_unused_data)
    `UNUSED_VAR (grant_b_unused_be)
    `UNUSED_VAR (grant_b_unused_half)
    `UNUSED_VAR (grant_b_lane_valid)
    `UNUSED_VAR (rd_b_conflict_det)
    `UNUSED_VAR (rd_b_ser_busy)
    `UNUSED_VAR (rd_b_conflict_cyc)

    logic [LANES-1:0]                        grant_w_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    grant_w_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  grant_w_word_addr;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0]   grant_w_data;
    logic [LANES-1:0][TMEM_BANK_WIDTH_BYTES-1:0] grant_w_be;
    logic [LANES-1:0]                        grant_w_half_sel;
    logic [LANES-1:0]                        grant_w_lane_valid;
    logic                                    wr_conflict_det;
    logic                                    wr_ser_busy;
    logic [31:0]                             wr_conflict_cyc;

    VX_tmem_bank_conflict #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS),
        .IS_WRITE  (1)
    ) u_conflict_wr (
        .clk                   (clk),
        .reset                 (reset),
        .req_valid             (swz_w_valid),
        .req_ready             (wr_ready),
        .req_bank_id           (swz_w_bank_id),
        .req_word_addr         (swz_w_word_addr),
        .req_wr_data           (wr_data),
        .req_wr_be             (wr_be),
        .req_half_sel          (swz_w_half_sel),
        .bank_ready_mask       (bank_wr_ready),
        .grant_valid           (grant_w_valid),
        .grant_bank_id         (grant_w_bank_id),
        .grant_word_addr       (grant_w_word_addr),
        .grant_wr_data         (grant_w_data),
        .grant_wr_be           (grant_w_be),
        .grant_half_sel        (grant_w_half_sel),
        .grant_lane_idx_valid  (grant_w_lane_valid),
        .conflict_ways_out     (wr_conflict_ways),
        .conflict_detected_out (wr_conflict_det),
        .serializer_busy_out   (wr_ser_busy),
        .conflict_cycles_count (wr_conflict_cyc)
    );
    `UNUSED_VAR (grant_w_half_sel)
    `UNUSED_VAR (grant_w_lane_valid)
    `UNUSED_VAR (wr_conflict_det)
    `UNUSED_VAR (wr_ser_busy)
    `UNUSED_VAR (wr_conflict_cyc)

    // -------------------------------------------------------------------------
    // 4. Read & Write Crossbars
    // -------------------------------------------------------------------------
    logic [LANES-1:0]                    xbar_a_rsp_valid;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0] xbar_a_rsp_data;
    logic [LANES-1:0]                    xbar_a_ecc_ce;
    logic [LANES-1:0]                    xbar_a_ecc_ue;
    logic [3:0]                          xbar_a_coal_cyc;
    logic [31:0]                         xbar_a_coal_tot;
    logic [31:0]                         xbar_a_reads_tot;

    VX_tmem_rd_xbar #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS),
        .BANK_LAT  (1)
    ) u_rd_xbar_a (
        .clk                        (clk),
        .reset                      (reset),
        .lane_req_valid             (grant_a_valid),
        .lane_req_bank_id           (grant_a_bank_id),
        .lane_req_word_addr         (grant_a_word_addr),
        .bank_rd_valid              (bank_rd_a_valid),
        .bank_rd_addr               (bank_rd_a_addr),
        .bank_rsp_valid             (bank_rd_a_rsp_valid),
        .bank_rsp_data              (bank_rd_a_rsp_data),
        .bank_rsp_ecc_ce            (bank_rd_a_ecc_ce),
        .bank_rsp_ecc_ue            (bank_rd_a_ecc_ue),
        .lane_rsp_valid             (xbar_a_rsp_valid),
        .lane_rsp_data              (xbar_a_rsp_data),
        .lane_rsp_ecc_ce            (xbar_a_ecc_ce),
        .lane_rsp_ecc_ue            (xbar_a_ecc_ue),
        .coalesced_reads_this_cycle (xbar_a_coal_cyc),
        .total_coalesced_reads      (xbar_a_coal_tot),
        .total_bank_reads_issued    (xbar_a_reads_tot)
    );
    `UNUSED_VAR (xbar_a_coal_cyc)
    `UNUSED_VAR (xbar_a_coal_tot)
    `UNUSED_VAR (xbar_a_reads_tot)

    logic [LANES-1:0]                    xbar_b_rsp_valid;
    logic [LANES-1:0][TMEM_ECC_DATA_W-1:0] xbar_b_rsp_data;
    logic [LANES-1:0]                    xbar_b_ecc_ce;
    logic [LANES-1:0]                    xbar_b_ecc_ue;
    logic [3:0]                          xbar_b_coal_cyc;
    logic [31:0]                         xbar_b_coal_tot;
    logic [31:0]                         xbar_b_reads_tot;

    VX_tmem_rd_xbar #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS),
        .BANK_LAT  (1)
    ) u_rd_xbar_b (
        .clk                        (clk),
        .reset                      (reset),
        .lane_req_valid             (grant_b_valid),
        .lane_req_bank_id           (grant_b_bank_id),
        .lane_req_word_addr         (grant_b_word_addr),
        .bank_rd_valid              (bank_rd_b_valid),
        .bank_rd_addr               (bank_rd_b_addr),
        .bank_rsp_valid             (bank_rd_b_rsp_valid),
        .bank_rsp_data              (bank_rd_b_rsp_data),
        .bank_rsp_ecc_ce            (bank_rd_b_ecc_ce),
        .bank_rsp_ecc_ue            (bank_rd_b_ecc_ue),
        .lane_rsp_valid             (xbar_b_rsp_valid),
        .lane_rsp_data              (xbar_b_rsp_data),
        .lane_rsp_ecc_ce            (xbar_b_ecc_ce),
        .lane_rsp_ecc_ue            (xbar_b_ecc_ue),
        .coalesced_reads_this_cycle (xbar_b_coal_cyc),
        .total_coalesced_reads      (xbar_b_coal_tot),
        .total_bank_reads_issued    (xbar_b_reads_tot)
    );
    `UNUSED_VAR (xbar_b_coal_cyc)
    `UNUSED_VAR (xbar_b_coal_tot)
    `UNUSED_VAR (xbar_b_reads_tot)

    logic [LANES-1:0]     wr_xbar_accepted;
    logic [LANES-1:0]     wr_xbar_rejected;
    logic [NUM_BANKS-1:0] wr_xbar_be_merged;
    logic [31:0]          wr_xbar_issued_tot;
    logic [31:0]          wr_xbar_merged_tot;

    VX_tmem_wr_xbar #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS)
    ) u_wr_xbar (
        .clk                      (clk),
        .reset                    (reset),
        .lane_wr_valid            (grant_w_valid),
        .lane_wr_bank_id          (grant_w_bank_id),
        .lane_wr_word_addr        (grant_w_word_addr),
        .lane_wr_data             (grant_w_data),
        .lane_wr_be               (grant_w_be),
        .bank_wr_ready            (bank_wr_ready),
        .bank_wr_valid            (bank_wr_valid),
        .bank_wr_addr             (bank_wr_addr),
        .bank_wr_data             (bank_wr_data),
        .bank_wr_be               (bank_wr_be),
        .lane_wr_accepted         (wr_xbar_accepted),
        .lane_wr_rejected         (wr_xbar_rejected),
        .bank_be_merged_mask      (wr_xbar_be_merged),
        .total_bank_writes_issued (wr_xbar_issued_tot),
        .total_merged_writes      (wr_xbar_merged_tot)
    );
    `UNUSED_VAR (wr_xbar_accepted)
    `UNUSED_VAR (wr_xbar_rejected)
    `UNUSED_VAR (wr_xbar_be_merged)
    `UNUSED_VAR (wr_xbar_issued_tot)
    `UNUSED_VAR (wr_xbar_merged_tot)

    // -------------------------------------------------------------------------
    // 5. 32 x 8 KiB ECC-Protected SRAM Banks (256 KiB Total)
    // -------------------------------------------------------------------------
    for (genvar g_b = 0; g_b < NUM_BANKS; ++g_b) begin : g_tmem_banks
        logic bank_inj_en;
        assign bank_inj_en = ecc_inj_en && (ecc_inj_bank == TMEM_BANK_ID_W'(g_b));

        VX_tmem_sram_bank #(
            .BANK_ID    (g_b),
            .BANK_DEPTH (BANK_DEPTH)
        ) u_sram_bank (
            .clk               (clk),
            .reset             (reset),
            .bank_pwr_on       (bank_pwr_on[g_b]),
            .rd_a_valid        (bank_rd_a_valid[g_b]),
            .rd_a_addr         (bank_rd_a_addr[g_b]),
            .rd_a_rsp_valid    (bank_rd_a_rsp_valid[g_b]),
            .rd_a_rsp_data     (bank_rd_a_rsp_data[g_b]),
            .rd_a_ecc_ce       (bank_rd_a_ecc_ce[g_b]),
            .rd_a_ecc_ue       (bank_rd_a_ecc_ue[g_b]),
            .rd_a_syndrome     (bank_rd_a_syndrome[g_b]),
            .rd_b_valid        (bank_rd_b_valid[g_b]),
            .rd_b_addr         (bank_rd_b_addr[g_b]),
            .rd_b_rsp_valid    (bank_rd_b_rsp_valid[g_b]),
            .rd_b_rsp_data     (bank_rd_b_rsp_data[g_b]),
            .rd_b_ecc_ce       (bank_rd_b_ecc_ce[g_b]),
            .rd_b_ecc_ue       (bank_rd_b_ecc_ue[g_b]),
            .rd_b_syndrome     (bank_rd_b_syndrome[g_b]),
            .wr_valid          (bank_wr_valid[g_b]),
            .wr_ready          (bank_wr_ready[g_b]),
            .wr_addr           (bank_wr_addr[g_b]),
            .wr_data           (bank_wr_data[g_b]),
            .wr_be             (bank_wr_be[g_b]),
            .ecc_inj_en        (bank_inj_en),
            .ecc_inj_mask      (ecc_inj_mask),
            .scrub_req_valid   (bank_scrub_req_valid[g_b]),
            .scrub_req_ready   (bank_scrub_req_ready[g_b]),
            .scrub_req_addr    (bank_scrub_req_addr[g_b]),
            .scrub_rsp_valid   (bank_scrub_rsp_valid[g_b]),
            .scrub_rsp_ce      (bank_scrub_rsp_ce[g_b]),
            .scrub_rsp_ue      (bank_scrub_rsp_ue[g_b]),
            .scrub_rsp_syndrome(bank_scrub_rsp_syndrome[g_b]),
            .scrub_wb_issued   (bank_scrub_wb_issued[g_b]),
            .rmw_active        (bank_rmw_active[g_b]),
            .rmw_addr          (bank_rmw_addr[g_b]),
            .rmw_merged_data   (bank_rmw_merged_data[g_b]),
            .rmw_commit_valid  (bank_rmw_commit_valid[g_b]),
            .rmw_count_out     (bank_rmw_count[g_b])
        );
    end
    `UNUSED_VAR (bank_rmw_count)

    // -------------------------------------------------------------------------
    // 6. Write-to-Read Hazard Forwarding & Bypass Buffer
    // -------------------------------------------------------------------------
    logic [LANES-1:0] rd_a_byp_hit;
    logic [LANES-1:0] rd_b_byp_hit;
    logic [31:0]      total_byp_hits;

    VX_tmem_rw_bypass #(
        .LANES     (LANES),
        .NUM_BANKS (NUM_BANKS)
    ) u_rw_bypass (
        .clk                   (clk),
        .reset                 (reset),
        .rd_a_req_valid        (grant_a_valid),
        .rd_a_req_bank_id      (grant_a_bank_id),
        .rd_a_req_word_addr    (grant_a_word_addr),
        .rd_b_req_valid        (grant_b_valid),
        .rd_b_req_bank_id      (grant_b_bank_id),
        .rd_b_req_word_addr    (grant_b_word_addr),
        .bank_wr_valid         (bank_wr_valid),
        .bank_wr_addr          (bank_wr_addr),
        .bank_wr_data          (bank_wr_data),
        .bank_wr_be            (bank_wr_be),
        .bank_rmw_active       (bank_rmw_active),
        .bank_rmw_addr         (bank_rmw_addr),
        .bank_rmw_merged_data  (bank_rmw_merged_data),
        .bank_rmw_commit_valid (bank_rmw_commit_valid),
        .sram_rd_a_rsp_valid   (xbar_a_rsp_valid),
        .sram_rd_a_rsp_data    (xbar_a_rsp_data),
        .sram_rd_a_ecc_ce      (xbar_a_ecc_ce),
        .sram_rd_a_ecc_ue      (xbar_a_ecc_ue),
        .sram_rd_b_rsp_valid   (xbar_b_rsp_valid),
        .sram_rd_b_rsp_data    (xbar_b_rsp_data),
        .sram_rd_b_ecc_ce      (xbar_b_ecc_ce),
        .sram_rd_b_ecc_ue      (xbar_b_ecc_ue),
        .final_rd_a_rsp_valid  (rd_a_rsp_valid),
        .final_rd_a_rsp_data   (rd_a_rsp_data),
        .final_rd_a_ecc_ce     (rd_a_ecc_ce),
        .final_rd_a_ecc_ue     (rd_a_ecc_ue),
        .final_rd_b_rsp_valid  (rd_b_rsp_valid),
        .final_rd_b_rsp_data   (rd_b_rsp_data),
        .final_rd_b_ecc_ce     (rd_b_ecc_ce),
        .final_rd_b_ecc_ue     (rd_b_ecc_ue),
        .rd_a_bypass_hit       (rd_a_byp_hit),
        .rd_b_bypass_hit       (rd_b_byp_hit),
        .total_bypass_hits_out (total_byp_hits)
    );
    `UNUSED_VAR (rd_a_byp_hit)
    `UNUSED_VAR (rd_b_byp_hit)
    `UNUSED_VAR (total_byp_hits)

    // -------------------------------------------------------------------------
    // 7. Background Patrol ECC Scrubber & Saturating Error Telemetry
    // -------------------------------------------------------------------------
    logic [31:0]      scrub_ops_cnt;
    logic [31:0]      scrub_wb_cnt;
    tmem_ecc_status_t ecc_status_struct;

    VX_tmem_ecc_scrubber #(
        .NUM_BANKS  (NUM_BANKS),
        .BANK_DEPTH (BANK_DEPTH)
    ) u_ecc_scrubber (
        .clk                     (clk),
        .reset                   (reset),
        .scrub_en                (scrub_en),
        .bank_scrub_ready        (bank_scrub_req_ready),
        .bank_scrub_req_valid    (bank_scrub_req_valid),
        .bank_scrub_req_addr     (bank_scrub_req_addr),
        .bank_scrub_rsp_valid    (bank_scrub_rsp_valid),
        .bank_scrub_rsp_ce       (bank_scrub_rsp_ce),
        .bank_scrub_rsp_ue       (bank_scrub_rsp_ue),
        .bank_scrub_rsp_syndrome (bank_scrub_rsp_syndrome),
        .bank_scrub_wb_issued    (bank_scrub_wb_issued),
        .bank_rd_a_rsp_valid     (bank_rd_a_rsp_valid),
        .bank_rd_a_ce            (bank_rd_a_ecc_ce),
        .bank_rd_a_ue            (bank_rd_a_ecc_ue),
        .bank_rd_a_addr          (bank_rd_a_addr),
        .bank_rd_a_syndrome      (bank_rd_a_syndrome),
        .bank_rd_b_rsp_valid     (bank_rd_b_rsp_valid),
        .bank_rd_b_ce            (bank_rd_b_ecc_ce),
        .bank_rd_b_ue            (bank_rd_b_ecc_ue),
        .bank_rd_b_addr          (bank_rd_b_addr),
        .bank_rd_b_syndrome      (bank_rd_b_syndrome),
        .ecc_ce_count_out        (ecc_ce_count),
        .ecc_ue_count_out        (ecc_ue_count),
        .scrub_ops_count_out     (scrub_ops_cnt),
        .scrub_wb_count_out      (scrub_wb_cnt),
        .ecc_status_out          (ecc_status_struct)
    );
    `UNUSED_VAR (scrub_ops_cnt)
    `UNUSED_VAR (scrub_wb_cnt)
    `UNUSED_VAR (ecc_status_struct)

endmodule
