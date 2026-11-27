// SPDX-License-Identifier: Apache-2.0
module VX_tmem_sva_monitors
    import VX_tmem_pkg::*;
#(
    parameter int NUM_BANKS     = TMEM_NUM_BANKS,
    parameter int LANES         = 8,
    parameter int MAX_REGIONS   = TMEM_MAX_REGIONS,
    parameter int MAX_STALL_CYC = 2048
) (
    input  logic                                clk,
    input  logic                                reset,
    // Allocation & live region table visibility
    input  logic                                alloc_valid,
    input  logic                                alloc_ready,
    input  logic [2:0]                          alloc_op,
    input  tmem_alloc_req_t                     alloc_req,
    input  tmem_alloc_rsp_t                     alloc_rsp,
    input  tmem_region_entry_t [MAX_REGIONS-1:0] region_table,
    input  logic [TMEM_NUM_ALLOC_UNITS-1:0]     granule_bitmap,
    input  logic [4:0]                          occupied_granules,
    input  logic [4:0]                          peak_granules,
    // Decoupled Load interface
    input  logic                                ld_desc_valid,
    input  logic                                ld_desc_ready,
    input  logic [TMEM_TAG_W-1:0]               ld_desc_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_desc_region_id,
    input  logic [TMEM_ROW_W-1:0]               ld_desc_row_base,
    input  logic [TMEM_COL_W-1:0]               ld_desc_col_base,
    input  logic                                ld_rsp_valid,
    input  logic                                ld_rsp_ready,
    input  logic [TMEM_TAG_W-1:0]               ld_rsp_tag,
    input  tmem_status_e                        ld_rsp_status,
    input  logic [LANES-1:0][63:0]              ld_rsp_data,
    input  logic [LANES-1:0]                    ld_rsp_lane_mask,
    input  logic                                ld_rsp_last,
    input  logic                                ld_rsp_ecc_ce,
    input  logic                                ld_rsp_ecc_ue,
    // Decoupled Store interface
    input  logic                                st_req_valid,
    input  logic                                st_req_ready,
    input  logic [TMEM_TAG_W-1:0]               st_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         st_req_region_id,
    input  logic [TMEM_ROW_W-1:0]               st_req_row_base,
    input  logic [TMEM_COL_W-1:0]               st_req_col_base,
    input  logic [LANES-1:0][63:0]              st_req_data,
    input  logic [LANES-1:0][7:0]               st_req_be,
    input  logic                                st_ack_valid,
    input  logic                                st_ack_ready,
    input  logic [TMEM_TAG_W-1:0]               st_ack_tag,
    input  tmem_status_e                        st_ack_status,
    // Wait / Fence interface
    input  logic                                wait_req_valid,
    input  logic                                wait_req_ready,
    input  tmem_op_e                            wait_req_op,
    input  logic [TMEM_TAG_W-1:0]               wait_req_tag,
    input  logic                                wait_rsp_valid,
    input  logic                                wait_rsp_ready,
    input  tmem_op_e                            wait_rsp_op,
    input  logic [TMEM_TAG_W-1:0]               wait_rsp_tag,
    input  tmem_status_e                        wait_rsp_status,
    // Bank array & arbiter interface visibility
    input  logic [LANES-1:0]                    bank_rda_valid,
    input  logic [LANES-1:0]                    bank_rda_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_rda_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]    bank_rda_col,
    input  tmem_swizzle_e                       bank_rda_swizzle,
    input  logic [LANES-1:0]                    bank_rdb_valid,
    input  logic [LANES-1:0]                    bank_rdb_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_rdb_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]    bank_rdb_col,
    input  tmem_swizzle_e                       bank_rdb_swizzle,
    input  logic [LANES-1:0]                    bank_wr_valid,
    input  logic [LANES-1:0]                    bank_wr_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_wr_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]    bank_wr_col,
    input  tmem_swizzle_e                       bank_wr_swizzle,
    // Arbiter grant mutual exclusion & ECC counters
    input  logic [LANES-1:0]                    arb_ld_ready,
    input  logic [LANES-1:0]                    arb_mma_rda_ready,
    input  logic [LANES-1:0]                    arb_st_ready,
    input  logic [LANES-1:0]                    arb_mma_wr_ready,
    input  logic [LANES-1:0]                    bank_rda_rsp_valid,
    input  logic [LANES-1:0]                    bank_rda_ecc_ce,
    input  logic [LANES-1:0]                    bank_rda_ecc_ue,
    input  logic [LANES-1:0]                    bank_rdb_rsp_valid,
    input  logic [LANES-1:0]                    bank_rdb_ecc_ce,
    input  logic [LANES-1:0]                    bank_rdb_ecc_ue,
    input  logic [31:0]                         ecc_ce_count,
    input  logic [31:0]                         ecc_ue_count,
    input  tmem_perf_cnt_t                      perf_cnt_out,
    input  logic                                perf_clear
);

    // -------------------------------------------------------------------------
    // Combinational Structural & Swizzle Helper Checks
    // -------------------------------------------------------------------------
    logic                                   regions_overlap_w;
    logic                                   regions_align_ok_w;
    logic                                   regions_pow2_ok_w;
    logic                                   regions_rows_ok_w;
    logic [TMEM_NUM_ALLOC_UNITS-1:0]        expected_bitmap_w;
    logic [4:0]                             expected_occ_cnt_w;
    logic                                   swizzle_range_ok_w;
    logic                                   arb_rda_mutex_ok_w;
    logic                                   arb_wr_mutex_ok_w;
    logic                                   ecc_mutex_ok_w;

    always_comb begin
        logic [TMEM_NUM_ALLOC_UNITS-1:0] reg_mask;
        logic [9:0]                      i_cols;
        logic [9:0]                      j_cols;
        logic [TMEM_BANK_ID_W-1:0]       b_a;
        logic [TMEM_BANK_ID_W-1:0]       b_b;
        logic [TMEM_BANK_ID_W-1:0]       b_w;

        reg_mask           = '0;
        i_cols             = 10'd0;
        j_cols             = 10'd0;
        b_a                = '0;
        b_b                = '0;
        b_w                = '0;
        regions_overlap_w  = 1'b0;
        regions_align_ok_w = 1'b1;
        regions_pow2_ok_w  = 1'b1;
        regions_rows_ok_w  = 1'b1;
        expected_bitmap_w  = '0;
        expected_occ_cnt_w = 5'd0;

        for (int i = 0; i < MAX_REGIONS; ++i) begin
            if (region_table[i].allocated) begin
                if (region_table[i].col_offset[4:0] != 5'd0) begin
                    regions_align_ok_w = 1'b0;
                end
                if (!tmem_is_pow2_cols(region_table[i].num_columns) ||
                    (region_table[i].num_columns < 10'(TMEM_MIN_ALLOC_COLS)) ||
                    (region_table[i].num_columns > 10'(TMEM_COLUMNS))) begin
                    regions_pow2_ok_w = 1'b0;
                end
                if (!tmem_rows_legal(region_table[i].num_rows)) begin
                    regions_rows_ok_w = 1'b0;
                end
                reg_mask = region_table[i].granule_mask;
                if ((expected_bitmap_w & reg_mask) != '0) begin
                    regions_overlap_w = 1'b1;
                end
                expected_bitmap_w = expected_bitmap_w | reg_mask;

                for (int j = i + 1; j < MAX_REGIONS; ++j) begin
                    if (region_table[j].allocated) begin
                        i_cols = region_table[i].double_buf_en
                                 ? (region_table[i].num_columns << 1)
                                 : region_table[i].num_columns;
                        j_cols = region_table[j].double_buf_en
                                 ? (region_table[j].num_columns << 1)
                                 : region_table[j].num_columns;
                        if (tmem_region_overlaps(
                                region_table[i].col_offset, i_cols,
                                region_table[j].col_offset, j_cols
                            )) begin
                            regions_overlap_w = 1'b1;
                        end
                    end
                end
            end
        end

        for (int u = 0; u < TMEM_NUM_ALLOC_UNITS; ++u) begin
            if (granule_bitmap[u]) begin
                expected_occ_cnt_w = expected_occ_cnt_w + 5'd1;
            end
        end

        swizzle_range_ok_w = 1'b1;
        for (int l = 0; l < LANES; ++l) begin
            b_a = tmem_swizzled_bank(bank_rda_row[l], bank_rda_col[l], bank_rda_swizzle);
            b_b = tmem_swizzled_bank(bank_rdb_row[l], bank_rdb_col[l], bank_rdb_swizzle);
            b_w = tmem_swizzled_bank(bank_wr_row[l],  bank_wr_col[l],  bank_wr_swizzle);
            if (bank_rda_valid[l] && (int'(b_a) >= NUM_BANKS)) begin
                swizzle_range_ok_w = 1'b0;
            end
            if (bank_rdb_valid[l] && (int'(b_b) >= NUM_BANKS)) begin
                swizzle_range_ok_w = 1'b0;
            end
            if (bank_wr_valid[l] && (int'(b_w) >= NUM_BANKS)) begin
                swizzle_range_ok_w = 1'b0;
            end
        end

        // Arbiter mutual exclusion across shared Read Port A and Write Port
        arb_rda_mutex_ok_w = !((|arb_ld_ready) && (|arb_mma_rda_ready));
        arb_wr_mutex_ok_w  = !((|arb_st_ready) && (|arb_mma_wr_ready));

        // SECDED CE/UE mutual exclusion on every response lane
        ecc_mutex_ok_w = !(ld_rsp_valid && ld_rsp_ecc_ce && ld_rsp_ecc_ue);
        for (int l = 0; l < LANES; ++l) begin
            if (bank_rda_rsp_valid[l] && bank_rda_ecc_ce[l] && bank_rda_ecc_ue[l]) begin
                ecc_mutex_ok_w = 1'b0;
            end
            if (bank_rdb_rsp_valid[l] && bank_rdb_ecc_ce[l] && bank_rdb_ecc_ue[l]) begin
                ecc_mutex_ok_w = 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // History Registers for Valid-Ready Stability & Counter Monotonicity
    // -------------------------------------------------------------------------
    logic                        prev_valid_q;
    logic                        prev_reset_q;
    logic                        prev_perf_clear_q;

    logic                        prev_alloc_valid_q;
    logic                        prev_alloc_ready_q;
    logic [2:0]                  prev_alloc_op_q;
    tmem_alloc_req_t             prev_alloc_req_q;

    logic                        prev_ld_desc_valid_q;
    logic                        prev_ld_desc_ready_q;
    logic [TMEM_TAG_W-1:0]       prev_ld_desc_tag_q;
    logic [TMEM_REGION_ID_W-1:0] prev_ld_desc_region_q;
    logic [TMEM_ROW_W-1:0]       prev_ld_desc_row_q;
    logic [TMEM_COL_W-1:0]       prev_ld_desc_col_q;

    logic                        prev_ld_rsp_valid_q;
    logic                        prev_ld_rsp_ready_q;
    logic [TMEM_TAG_W-1:0]       prev_ld_rsp_tag_q;
    tmem_status_e                prev_ld_rsp_status_q;
    logic [LANES-1:0][63:0]      prev_ld_rsp_data_q;
    logic [LANES-1:0]            prev_ld_rsp_mask_q;
    logic                        prev_ld_rsp_last_q;

    logic                        prev_st_req_valid_q;
    logic                        prev_st_req_ready_q;
    logic [TMEM_TAG_W-1:0]       prev_st_req_tag_q;
    logic [TMEM_REGION_ID_W-1:0] prev_st_req_region_q;
    logic [TMEM_ROW_W-1:0]       prev_st_req_row_q;
    logic [TMEM_COL_W-1:0]       prev_st_req_col_q;
    logic [LANES-1:0][63:0]      prev_st_req_data_q;
    logic [LANES-1:0][7:0]       prev_st_req_be_q;

    logic                        prev_st_ack_valid_q;
    logic                        prev_st_ack_ready_q;
    logic [TMEM_TAG_W-1:0]       prev_st_ack_tag_q;
    tmem_status_e                prev_st_ack_status_q;

    logic                        prev_wait_req_valid_q;
    logic                        prev_wait_req_ready_q;
    tmem_op_e                    prev_wait_req_op_q;
    logic [TMEM_TAG_W-1:0]       prev_wait_req_tag_q;

    logic                        prev_wait_rsp_valid_q;
    logic                        prev_wait_rsp_ready_q;
    tmem_op_e                    prev_wait_rsp_op_q;
    logic [TMEM_TAG_W-1:0]       prev_wait_rsp_tag_q;
    tmem_status_e                prev_wait_rsp_status_q;

    logic [LANES-1:0]            prev_bank_rda_valid_q;
    logic [LANES-1:0]            prev_bank_rda_ready_q;
    logic [LANES-1:0][TMEM_ROW_W-1:0] prev_bank_rda_row_q;
    logic [LANES-1:0][TMEM_COL_W-1:0] prev_bank_rda_col_q;

    logic [LANES-1:0]            prev_bank_rdb_valid_q;
    logic [LANES-1:0]            prev_bank_rdb_ready_q;
    logic [LANES-1:0][TMEM_ROW_W-1:0] prev_bank_rdb_row_q;
    logic [LANES-1:0][TMEM_COL_W-1:0] prev_bank_rdb_col_q;

    logic [LANES-1:0]            prev_bank_wr_valid_q;
    logic [LANES-1:0]            prev_bank_wr_ready_q;
    logic [LANES-1:0][TMEM_ROW_W-1:0] prev_bank_wr_row_q;
    logic [LANES-1:0][TMEM_COL_W-1:0] prev_bank_wr_col_q;

    logic [31:0]                 prev_ecc_ce_count_q;
    logic [31:0]                 prev_ecc_ue_count_q;
    tmem_perf_cnt_t              prev_perf_cnt_q;
    logic [4:0]                  prev_peak_granules_q;

    logic [15:0]                 ld_stall_cnt_q;
    logic [15:0]                 st_stall_cnt_q;
    logic [15:0]                 wait_stall_cnt_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            prev_valid_q          <= 1'b0;
            prev_reset_q          <= 1'b1;
            prev_perf_clear_q     <= 1'b0;
            prev_alloc_valid_q    <= 1'b0;
            prev_alloc_ready_q    <= 1'b0;
            prev_alloc_op_q       <= 3'd0;
            prev_alloc_req_q      <= '0;
            prev_ld_desc_valid_q  <= 1'b0;
            prev_ld_desc_ready_q  <= 1'b0;
            prev_ld_desc_tag_q    <= '0;
            prev_ld_desc_region_q <= '0;
            prev_ld_desc_row_q    <= '0;
            prev_ld_desc_col_q    <= '0;
            prev_ld_rsp_valid_q   <= 1'b0;
            prev_ld_rsp_ready_q   <= 1'b0;
            prev_ld_rsp_tag_q     <= '0;
            prev_ld_rsp_status_q  <= TMEM_STATUS_OK;
            prev_ld_rsp_data_q    <= '0;
            prev_ld_rsp_mask_q    <= '0;
            prev_ld_rsp_last_q    <= 1'b0;
            prev_st_req_valid_q   <= 1'b0;
            prev_st_req_ready_q   <= 1'b0;
            prev_st_req_tag_q     <= '0;
            prev_st_req_region_q  <= '0;
            prev_st_req_row_q     <= '0;
            prev_st_req_col_q     <= '0;
            prev_st_req_data_q    <= '0;
            prev_st_req_be_q      <= '0;
            prev_st_ack_valid_q   <= 1'b0;
            prev_st_ack_ready_q   <= 1'b0;
            prev_st_ack_tag_q     <= '0;
            prev_st_ack_status_q  <= TMEM_STATUS_OK;
            prev_wait_req_valid_q <= 1'b0;
            prev_wait_req_ready_q <= 1'b0;
            prev_wait_req_op_q    <= TMEM_OP_NOP;
            prev_wait_req_tag_q   <= '0;
            prev_wait_rsp_valid_q <= 1'b0;
            prev_wait_rsp_ready_q <= 1'b0;
            prev_wait_rsp_op_q    <= TMEM_OP_NOP;
            prev_wait_rsp_tag_q   <= '0;
            prev_wait_rsp_status_q <= TMEM_STATUS_OK;
            prev_bank_rda_valid_q <= '0;
            prev_bank_rda_ready_q <= '0;
            prev_bank_rda_row_q   <= '0;
            prev_bank_rda_col_q   <= '0;
            prev_bank_rdb_valid_q <= '0;
            prev_bank_rdb_ready_q <= '0;
            prev_bank_rdb_row_q   <= '0;
            prev_bank_rdb_col_q   <= '0;
            prev_bank_wr_valid_q  <= '0;
            prev_bank_wr_ready_q  <= '0;
            prev_bank_wr_row_q    <= '0;
            prev_bank_wr_col_q    <= '0;
            prev_ecc_ce_count_q   <= 32'd0;
            prev_ecc_ue_count_q   <= 32'd0;
            prev_perf_cnt_q       <= '0;
            prev_peak_granules_q  <= 5'd0;
            ld_stall_cnt_q        <= 16'd0;
            st_stall_cnt_q        <= 16'd0;
            wait_stall_cnt_q      <= 16'd0;
        end else begin
            prev_valid_q          <= 1'b1;
            prev_reset_q          <= reset;
            prev_perf_clear_q     <= perf_clear;
            prev_alloc_valid_q    <= alloc_valid;
            prev_alloc_ready_q    <= alloc_ready;
            prev_alloc_op_q       <= alloc_op;
            prev_alloc_req_q      <= alloc_req;
            prev_ld_desc_valid_q  <= ld_desc_valid;
            prev_ld_desc_ready_q  <= ld_desc_ready;
            prev_ld_desc_tag_q    <= ld_desc_tag;
            prev_ld_desc_region_q <= ld_desc_region_id;
            prev_ld_desc_row_q    <= ld_desc_row_base;
            prev_ld_desc_col_q    <= ld_desc_col_base;
            prev_ld_rsp_valid_q   <= ld_rsp_valid;
            prev_ld_rsp_ready_q   <= ld_rsp_ready;
            prev_ld_rsp_tag_q     <= ld_rsp_tag;
            prev_ld_rsp_status_q  <= ld_rsp_status;
            prev_ld_rsp_data_q    <= ld_rsp_data;
            prev_ld_rsp_mask_q    <= ld_rsp_lane_mask;
            prev_ld_rsp_last_q    <= ld_rsp_last;
            prev_st_req_valid_q   <= st_req_valid;
            prev_st_req_ready_q   <= st_req_ready;
            prev_st_req_tag_q     <= st_req_tag;
            prev_st_req_region_q  <= st_req_region_id;
            prev_st_req_row_q     <= st_req_row_base;
            prev_st_req_col_q     <= st_req_col_base;
            prev_st_req_data_q    <= st_req_data;
            prev_st_req_be_q      <= st_req_be;
            prev_st_ack_valid_q   <= st_ack_valid;
            prev_st_ack_ready_q   <= st_ack_ready;
            prev_st_ack_tag_q     <= st_ack_tag;
            prev_st_ack_status_q  <= st_ack_status;
            prev_wait_req_valid_q <= wait_req_valid;
            prev_wait_req_ready_q <= wait_req_ready;
            prev_wait_req_op_q    <= wait_req_op;
            prev_wait_req_tag_q   <= wait_req_tag;
            prev_wait_rsp_valid_q <= wait_rsp_valid;
            prev_wait_rsp_ready_q <= wait_rsp_ready;
            prev_wait_rsp_op_q    <= wait_rsp_op;
            prev_wait_rsp_tag_q   <= wait_rsp_tag;
            prev_wait_rsp_status_q <= wait_rsp_status;
            prev_bank_rda_valid_q <= bank_rda_valid;
            prev_bank_rda_ready_q <= bank_rda_ready;
            prev_bank_rda_row_q   <= bank_rda_row;
            prev_bank_rda_col_q   <= bank_rda_col;
            prev_bank_rdb_valid_q <= bank_rdb_valid;
            prev_bank_rdb_ready_q <= bank_rdb_ready;
            prev_bank_rdb_row_q   <= bank_rdb_row;
            prev_bank_rdb_col_q   <= bank_rdb_col;
            prev_bank_wr_valid_q  <= bank_wr_valid;
            prev_bank_wr_ready_q  <= bank_wr_ready;
            prev_bank_wr_row_q    <= bank_wr_row;
            prev_bank_wr_col_q    <= bank_wr_col;
            prev_ecc_ce_count_q   <= ecc_ce_count;
            prev_ecc_ue_count_q   <= ecc_ue_count;
            prev_perf_cnt_q       <= perf_cnt_out;
            prev_peak_granules_q  <= peak_granules;

            if (ld_rsp_valid && !ld_rsp_ready) begin
                if (ld_stall_cnt_q != 16'hFFFF) begin
                    ld_stall_cnt_q <= ld_stall_cnt_q + 16'd1;
                end
            end else begin
                ld_stall_cnt_q <= 16'd0;
            end

            if (st_ack_valid && !st_ack_ready) begin
                if (st_stall_cnt_q != 16'hFFFF) begin
                    st_stall_cnt_q <= st_stall_cnt_q + 16'd1;
                end
            end else begin
                st_stall_cnt_q <= 16'd0;
            end

            if (wait_rsp_valid && !wait_rsp_ready) begin
                if (wait_stall_cnt_q != 16'hFFFF) begin
                    wait_stall_cnt_q <= wait_stall_cnt_q + 16'd1;
                end
            end else begin
                wait_stall_cnt_q <= 16'd0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Immediate Clocked Assertions (Verilator --assert & Formal Safe)
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!reset) begin
            // 1. Control signal knownness (no X/Z)
            assert (!$isunknown({
                alloc_valid, alloc_ready,
                ld_desc_valid, ld_desc_ready, ld_rsp_valid, ld_rsp_ready,
                st_req_valid, st_req_ready, st_ack_valid, st_ack_ready,
                wait_req_valid, wait_req_ready, wait_rsp_valid, wait_rsp_ready
            })) else $error("VX_tmem_sva_monitors: X/Z on TMEM top-level valid/ready controls");

            assert (!$isunknown({
                bank_rda_valid, bank_rda_ready,
                bank_rdb_valid, bank_rdb_ready,
                bank_wr_valid, bank_wr_ready,
                arb_ld_ready, arb_mma_rda_ready,
                arb_st_ready, arb_mma_wr_ready
            })) else $error("VX_tmem_sva_monitors: X/Z on TMEM bank/arbiter controls");

            // 2. Allocator invariants across ALL live regions
            assert (regions_align_ok_w)
                else $error("VX_tmem_sva_monitors: live region col_offset not 32-column aligned");
            assert (regions_pow2_ok_w)
                else $error("VX_tmem_sva_monitors: live region num_columns not power-of-two >= 32");
            assert (regions_rows_ok_w)
                else $error("VX_tmem_sva_monitors: live region num_rows not in {32, 64, 128}");
            assert (!regions_overlap_w)
                else $error("VX_tmem_sva_monitors: overlapping live TMEM regions detected");
            assert (granule_bitmap == expected_bitmap_w)
                else $error("VX_tmem_sva_monitors: granule_bitmap disagrees with live region masks");
            assert (occupied_granules == expected_occ_cnt_w)
                else $error("VX_tmem_sva_monitors: occupied_granules mismatch (%0d != %0d)",
                            occupied_granules, expected_occ_cnt_w);
            assert (int'(occupied_granules) <= TMEM_NUM_ALLOC_UNITS)
                else $error("VX_tmem_sva_monitors: occupied_granules exceeded 16");
            assert (peak_granules >= occupied_granules)
                else $error("VX_tmem_sva_monitors: peak_granules < occupied_granules");

            if (alloc_rsp.valid && (alloc_rsp.status == TMEM_STATUS_OK)) begin
                assert (!$isunknown({alloc_rsp.region_id, alloc_rsp.buf_b_col_offset}))
                    else $error("VX_tmem_sva_monitors: X/Z on OK alloc_rsp fields");
                assert (alloc_rsp.col_offset[4:0] == 5'd0)
                    else $error("VX_tmem_sva_monitors: OK alloc_rsp col_offset misaligned (%0d)", alloc_rsp.col_offset);
                assert (alloc_rsp.buf_b_col_offset[4:0] == 5'd0)
                    else $error("VX_tmem_sva_monitors: OK alloc_rsp buf_b_col_offset misaligned (%0d)", alloc_rsp.buf_b_col_offset);
                if (alloc_rsp.num_columns != 10'd0) begin
                    assert (tmem_is_pow2_cols(alloc_rsp.num_columns))
                        else $error("VX_tmem_sva_monitors: OK alloc_rsp num_columns not pow2 (%0d)", alloc_rsp.num_columns);
                end
            end

            // 3. Bank swizzle range [0..31]
            assert (swizzle_range_ok_w)
                else $error("VX_tmem_sva_monitors: swizzled bank ID outside [0..31]");

            // 4. Arbiter mutual exclusion
            assert (arb_rda_mutex_ok_w)
                else $error("VX_tmem_sva_monitors: Read Port A granted to both LD and MMA simultaneously");
            assert (arb_wr_mutex_ok_w)
                else $error("VX_tmem_sva_monitors: Write Port granted to both ST and MMA simultaneously");

            // 5. SECDED CE/UE mutual exclusion (!(ce && ue))
            assert (ecc_mutex_ok_w)
                else $error("VX_tmem_sva_monitors: SECDED CE and UE asserted simultaneously");

            // 6. Handshake stability and monotonic ECC/perf counters
            if (prev_valid_q && !prev_reset_q) begin
                if (prev_alloc_valid_q && !prev_alloc_ready_q) begin
                    assert (alloc_valid && (alloc_op == prev_alloc_op_q) && (alloc_req == prev_alloc_req_q))
                        else $error("VX_tmem_sva_monitors: alloc request mutated while stalled");
                end

                if (prev_ld_desc_valid_q && !prev_ld_desc_ready_q) begin
                    assert (ld_desc_valid && (ld_desc_tag == prev_ld_desc_tag_q) &&
                            (ld_desc_region_id == prev_ld_desc_region_q) &&
                            (ld_desc_row_base == prev_ld_desc_row_q) &&
                            (ld_desc_col_base == prev_ld_desc_col_q))
                        else $error("VX_tmem_sva_monitors: ld_desc mutated while stalled");
                end

                if (prev_ld_rsp_valid_q && !prev_ld_rsp_ready_q) begin
                    assert (ld_rsp_valid && (ld_rsp_tag == prev_ld_rsp_tag_q) &&
                            (ld_rsp_status == prev_ld_rsp_status_q) &&
                            (ld_rsp_data == prev_ld_rsp_data_q) &&
                            (ld_rsp_lane_mask == prev_ld_rsp_mask_q) &&
                            (ld_rsp_last == prev_ld_rsp_last_q))
                        else $error("VX_tmem_sva_monitors: ld_rsp mutated while stalled");
                end

                if (prev_st_req_valid_q && !prev_st_req_ready_q) begin
                    assert (st_req_valid && (st_req_tag == prev_st_req_tag_q) &&
                            (st_req_region_id == prev_st_req_region_q) &&
                            (st_req_row_base == prev_st_req_row_q) &&
                            (st_req_col_base == prev_st_req_col_q) &&
                            (st_req_data == prev_st_req_data_q) &&
                            (st_req_be == prev_st_req_be_q))
                        else $error("VX_tmem_sva_monitors: st_req mutated while stalled");
                end

                if (prev_st_ack_valid_q && !prev_st_ack_ready_q) begin
                    assert (st_ack_valid && (st_ack_tag == prev_st_ack_tag_q) &&
                            (st_ack_status == prev_st_ack_status_q))
                        else $error("VX_tmem_sva_monitors: st_ack mutated while stalled");
                end

                if (prev_wait_req_valid_q && !prev_wait_req_ready_q) begin
                    assert (wait_req_valid && (wait_req_op == prev_wait_req_op_q) &&
                            (wait_req_tag == prev_wait_req_tag_q))
                        else $error("VX_tmem_sva_monitors: wait_req mutated while stalled");
                end

                if (prev_wait_rsp_valid_q && !prev_wait_rsp_ready_q) begin
                    assert (wait_rsp_valid && (wait_rsp_op == prev_wait_rsp_op_q) &&
                            (wait_rsp_tag == prev_wait_rsp_tag_q) &&
                            (wait_rsp_status == prev_wait_rsp_status_q))
                        else $error("VX_tmem_sva_monitors: wait_rsp mutated while stalled");
                end

                for (int l = 0; l < LANES; ++l) begin
                    if (prev_bank_rda_valid_q[l] && !prev_bank_rda_ready_q[l]) begin
                        assert (bank_rda_valid[l] && (bank_rda_row[l] == prev_bank_rda_row_q[l]) &&
                                (bank_rda_col[l] == prev_bank_rda_col_q[l]))
                            else $error("VX_tmem_sva_monitors: bank_rda[%0d] mutated while stalled", l);
                    end
                    if (prev_bank_rdb_valid_q[l] && !prev_bank_rdb_ready_q[l]) begin
                        assert (bank_rdb_valid[l] && (bank_rdb_row[l] == prev_bank_rdb_row_q[l]) &&
                                (bank_rdb_col[l] == prev_bank_rdb_col_q[l]))
                            else $error("VX_tmem_sva_monitors: bank_rdb[%0d] mutated while stalled", l);
                    end
                    if (prev_bank_wr_valid_q[l] && !prev_bank_wr_ready_q[l]) begin
                        assert (bank_wr_valid[l] && (bank_wr_row[l] == prev_bank_wr_row_q[l]) &&
                                (bank_wr_col[l] == prev_bank_wr_col_q[l]))
                            else $error("VX_tmem_sva_monitors: bank_wr[%0d] mutated while stalled", l);
                    end
                end

                // Monotonic ECC counters & peak watermark
                assert (ecc_ce_count >= prev_ecc_ce_count_q)
                    else $error("VX_tmem_sva_monitors: ecc_ce_count decreased");
                assert (ecc_ue_count >= prev_ecc_ue_count_q)
                    else $error("VX_tmem_sva_monitors: ecc_ue_count decreased");
                assert (peak_granules >= prev_peak_granules_q)
                    else $error("VX_tmem_sva_monitors: peak_granules decreased");

                if (!perf_clear && !prev_perf_clear_q) begin
                    assert (perf_cnt_out.rd_a_ops >= prev_perf_cnt_q.rd_a_ops)
                        else $error("VX_tmem_sva_monitors: perf rd_a_ops decreased");
                    assert (perf_cnt_out.rd_b_ops >= prev_perf_cnt_q.rd_b_ops)
                        else $error("VX_tmem_sva_monitors: perf rd_b_ops decreased");
                    assert (perf_cnt_out.wr_ops >= prev_perf_cnt_q.wr_ops)
                        else $error("VX_tmem_sva_monitors: perf wr_ops decreased");
                    assert (perf_cnt_out.conflict_cycles >= prev_perf_cnt_q.conflict_cycles)
                        else $error("VX_tmem_sva_monitors: perf conflict_cycles decreased");
                    assert (perf_cnt_out.fence_wait_cycles >= prev_perf_cnt_q.fence_wait_cycles)
                        else $error("VX_tmem_sva_monitors: perf fence_wait_cycles decreased");
                    assert (perf_cnt_out.alloc_ops >= prev_perf_cnt_q.alloc_ops)
                        else $error("VX_tmem_sva_monitors: perf alloc_ops decreased");
                    assert (perf_cnt_out.dealloc_ops >= prev_perf_cnt_q.dealloc_ops)
                        else $error("VX_tmem_sva_monitors: perf dealloc_ops decreased");
                    assert (perf_cnt_out.scrub_ops >= prev_perf_cnt_q.scrub_ops)
                        else $error("VX_tmem_sva_monitors: perf scrub_ops decreased");
                end
            end

            if (MAX_STALL_CYC > 0) begin
                assert (int'(ld_stall_cnt_q) < MAX_STALL_CYC)
                    else $error("VX_tmem_sva_monitors: ld_rsp stalled >= %0d cycles", MAX_STALL_CYC);
                assert (int'(st_stall_cnt_q) < MAX_STALL_CYC)
                    else $error("VX_tmem_sva_monitors: st_ack stalled >= %0d cycles", MAX_STALL_CYC);
                assert (int'(wait_stall_cnt_q) < MAX_STALL_CYC)
                    else $error("VX_tmem_sva_monitors: wait_rsp stalled >= %0d cycles", MAX_STALL_CYC);
            end
        end
    end

    // -------------------------------------------------------------------------
    // Concurrent SVA Properties (Verilator 5.050 --assert Compatible)
    // -------------------------------------------------------------------------
`ifdef ASSERTIONS
    property p_tmem_no_overlap;
        @(posedge clk) disable iff (reset)
        !regions_overlap_w;
    endproperty
    a_tmem_no_overlap: assert property (p_tmem_no_overlap)
        else $error("VX_tmem_sva_monitors: SVA overlapping live regions");

    property p_tmem_alloc_align_pow2_rows;
        @(posedge clk) disable iff (reset)
        (regions_align_ok_w && regions_pow2_ok_w && regions_rows_ok_w);
    endproperty
    a_tmem_alloc_align_pow2_rows: assert property (p_tmem_alloc_align_pow2_rows)
        else $error("VX_tmem_sva_monitors: SVA region alignment/pow2/rows invariant violated");

    property p_tmem_arb_mutex;
        @(posedge clk) disable iff (reset)
        (arb_rda_mutex_ok_w && arb_wr_mutex_ok_w);
    endproperty
    a_tmem_arb_mutex: assert property (p_tmem_arb_mutex)
        else $error("VX_tmem_sva_monitors: SVA arbiter mutual exclusion violated");

    property p_tmem_secded_mutex;
        @(posedge clk) disable iff (reset)
        ecc_mutex_ok_w;
    endproperty
    a_tmem_secded_mutex: assert property (p_tmem_secded_mutex)
        else $error("VX_tmem_sva_monitors: SVA SECDED CE/UE mutual exclusion violated");

    property p_tmem_ld_desc_stable;
        @(posedge clk) disable iff (reset)
        (ld_desc_valid && !ld_desc_ready) |=> (ld_desc_valid && $stable(ld_desc_tag) && $stable(ld_desc_region_id));
    endproperty
    a_tmem_ld_desc_stable: assert property (p_tmem_ld_desc_stable)
        else $error("VX_tmem_sva_monitors: SVA ld_desc unstable before ready");

    property p_tmem_ld_rsp_stable;
        @(posedge clk) disable iff (reset)
        (ld_rsp_valid && !ld_rsp_ready) |=> (ld_rsp_valid && $stable(ld_rsp_tag) && $stable(ld_rsp_data));
    endproperty
    a_tmem_ld_rsp_stable: assert property (p_tmem_ld_rsp_stable)
        else $error("VX_tmem_sva_monitors: SVA ld_rsp unstable before ready");

    property p_tmem_st_req_stable;
        @(posedge clk) disable iff (reset)
        (st_req_valid && !st_req_ready) |=> (st_req_valid && $stable(st_req_tag) && $stable(st_req_data));
    endproperty
    a_tmem_st_req_stable: assert property (p_tmem_st_req_stable)
        else $error("VX_tmem_sva_monitors: SVA st_req unstable before ready");

    property p_tmem_st_ack_stable;
        @(posedge clk) disable iff (reset)
        (st_ack_valid && !st_ack_ready) |=> (st_ack_valid && $stable(st_ack_tag) && $stable(st_ack_status));
    endproperty
    a_tmem_st_ack_stable: assert property (p_tmem_st_ack_stable)
        else $error("VX_tmem_sva_monitors: SVA st_ack unstable before ready");

    property p_tmem_ecc_monotonic;
        @(posedge clk) disable iff (reset)
        (prev_valid_q && !prev_reset_q) |->
            ((ecc_ce_count >= prev_ecc_ce_count_q) && (ecc_ue_count >= prev_ecc_ue_count_q));
    endproperty
    a_tmem_ecc_monotonic: assert property (p_tmem_ecc_monotonic)
        else $error("VX_tmem_sva_monitors: SVA ECC counter decreased");
`endif

endmodule
