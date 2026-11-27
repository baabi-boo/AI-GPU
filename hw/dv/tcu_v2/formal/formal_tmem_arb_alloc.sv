// SPDX-License-Identifier: Apache-2.0
module VX_tmem_formal_arb_alloc
    import VX_tmem_pkg::*;
#(
    parameter int LANES       = 4,
    parameter int MAX_REGIONS = TMEM_MAX_REGIONS,
    parameter int TRACK_DEPTH = 8
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Symbolic inputs for TMEM Allocator
    input  logic                                    sym_alloc_valid,
    input  logic [2:0]                              sym_alloc_op,
    input  logic                                    sym_auto_place,
    input  logic                                    sym_buddy_align,
    input  logic                                    sym_strict_owner,
    input  tmem_alloc_req_t                         sym_alloc_req,
    // Symbolic inputs for TMEM Arbiter
    input  logic [3:0]                              sym_w_ld,
    input  logic [3:0]                              sym_w_st,
    input  logic [3:0]                              sym_w_mma,
    input  logic                                    sym_strict_mma,
    input  logic [4:0]                              sym_starve_limit,
    input  logic [LANES-1:0]                        sym_ld_req_valid,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        sym_ld_req_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        sym_ld_req_col,
    input  tmem_swizzle_e                           sym_ld_swizzle,
    input  logic [LANES-1:0]                        sym_st_req_valid,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        sym_st_req_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        sym_st_req_col,
    input  tmem_swizzle_e                           sym_st_swizzle,
    input  logic [LANES-1:0][63:0]                  sym_st_data,
    input  logic [LANES-1:0][7:0]                   sym_st_be,
    input  logic [LANES-1:0]                        sym_mma_rda_valid,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        sym_mma_rda_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        sym_mma_rda_col,
    input  tmem_swizzle_e                           sym_mma_rda_swizzle,
    input  logic [LANES-1:0]                        sym_mma_rdb_valid,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        sym_mma_rdb_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        sym_mma_rdb_col,
    input  tmem_swizzle_e                           sym_mma_rdb_swizzle,
    input  logic [LANES-1:0]                        sym_mma_wr_valid,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        sym_mma_wr_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        sym_mma_wr_col,
    input  tmem_swizzle_e                           sym_mma_wr_swizzle,
    input  logic [LANES-1:0][63:0]                  sym_mma_wr_data,
    input  logic [LANES-1:0][7:0]                   sym_mma_wr_be,
    input  logic [LANES-1:0]                        sym_bank_rda_ready,
    input  logic [LANES-1:0]                        sym_bank_rdb_ready,
    input  logic [LANES-1:0]                        sym_bank_wr_ready,
    // Symbolic inputs for TMEM Hazard Unit
    input  logic                                    sym_haz_ld_valid,
    input  logic [TMEM_REGION_ID_W-1:0]             sym_haz_ld_reg,
    input  logic [TMEM_COL_W-1:0]                   sym_haz_ld_col,
    input  logic [9:0]                              sym_haz_ld_cnt,
    input  logic [TMEM_TAG_W-1:0]                   sym_haz_ld_tag,
    input  logic                                    sym_haz_st_valid,
    input  logic [TMEM_REGION_ID_W-1:0]             sym_haz_st_reg,
    input  logic [TMEM_COL_W-1:0]                   sym_haz_st_col,
    input  logic [9:0]                              sym_haz_st_cnt,
    input  logic [TMEM_TAG_W-1:0]                   sym_haz_st_tag,
    input  logic                                    sym_haz_mma_valid,
    input  logic                                    sym_haz_mma_is_wr,
    input  logic [TMEM_REGION_ID_W-1:0]             sym_haz_mma_reg,
    input  logic [TMEM_COL_W-1:0]                   sym_haz_mma_col,
    input  logic [9:0]                              sym_haz_mma_cnt,
    input  logic [TMEM_TAG_W-1:0]                   sym_haz_mma_tag,
    input  logic                                    sym_haz_ld_commit,
    input  logic [TMEM_TAG_W-1:0]                   sym_haz_ld_ctag,
    input  logic                                    sym_haz_st_commit,
    input  logic [TMEM_TAG_W-1:0]                   sym_haz_st_ctag,
    input  logic                                    sym_haz_mma_commit,
    input  logic [TMEM_TAG_W-1:0]                   sym_haz_mma_ctag,
    input  logic                                    sym_haz_fence_valid,
    input  logic                                    sym_haz_fence_reg_only,
    input  logic [TMEM_REGION_ID_W-1:0]             sym_haz_fence_reg,
    output logic                                    formal_ok_out
);

    // -------------------------------------------------------------------------
    // 1. Instantiate TMEM Allocator DUT
    // -------------------------------------------------------------------------
    logic                                    alloc_ready;
    tmem_alloc_rsp_t                         alloc_rsp;
    logic                                    alloc_query_valid;
    tmem_region_entry_t                      alloc_query_entry;
    tmem_region_entry_t [MAX_REGIONS-1:0]    region_table;
    logic [TMEM_NUM_ALLOC_UNITS-1:0]         granule_bitmap;
    logic [4:0]                              occupied_granules;
    logic [4:0]                              peak_granules;
    logic [4:0]                              active_regions;
    logic [31:0]                             alloc_ok_count;
    logic [31:0]                             alloc_err_count;
    logic [31:0]                             dealloc_count;

    VX_tmem_allocator #(
        .NUM_GRANULES (TMEM_NUM_ALLOC_UNITS),
        .MAX_REGIONS  (MAX_REGIONS),
        .NUM_WARPS    (32)
    ) u_alloc_dut (
        .clk                   (clk),
        .reset                 (reset),
        .req_valid             (sym_alloc_valid),
        .req_ready             (alloc_ready),
        .req_op                (sym_alloc_op),
        .auto_place_en         (sym_auto_place),
        .buddy_align_en        (sym_buddy_align),
        .strict_owner_chk      (sym_strict_owner),
        .alloc_req             (sym_alloc_req),
        .alloc_rsp             (alloc_rsp),
        .query_valid           (alloc_query_valid),
        .query_entry_out       (alloc_query_entry),
        .region_table_out      (region_table),
        .granule_bitmap_out    (granule_bitmap),
        .occupied_granules_out (occupied_granules),
        .peak_granules_out     (peak_granules),
        .active_regions_out    (active_regions),
        .alloc_ok_count_out    (alloc_ok_count),
        .alloc_err_count_out   (alloc_err_count),
        .dealloc_count_out     (dealloc_count)
    );

    // Track last cycle's alloc request to check exact error/OK status semantics
    logic            prev_alloc_fire_q;
    logic [2:0]      prev_alloc_op_q;
    logic            prev_auto_place_q;
    tmem_alloc_req_t prev_alloc_req_q;
    logic [4:0]      prev_occ_granules_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            prev_alloc_fire_q   <= 1'b0;
            prev_alloc_op_q     <= 3'd0;
            prev_auto_place_q   <= 1'b0;
            prev_alloc_req_q    <= '0;
            prev_occ_granules_q <= 5'd0;
        end else begin
            prev_alloc_fire_q   <= sym_alloc_valid && alloc_ready;
            prev_alloc_op_q     <= sym_alloc_op;
            prev_auto_place_q   <= sym_auto_place;
            prev_alloc_req_q    <= sym_alloc_req;
            prev_occ_granules_q <= occupied_granules;
        end
    end

    // -------------------------------------------------------------------------
    // 2. Instantiate TMEM Arbiter DUT
    // -------------------------------------------------------------------------
    logic [LANES-1:0]                        arb_ld_ready;
    logic [LANES-1:0]                        arb_st_ready;
    logic [LANES-1:0]                        arb_mma_rda_ready;
    logic [LANES-1:0]                        arb_mma_rdb_ready;
    logic [LANES-1:0]                        arb_mma_wr_ready;

    logic [LANES-1:0]                        bank_rda_valid;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        bank_rda_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        bank_rda_col;
    tmem_swizzle_e                           bank_rda_swizzle;

    logic [LANES-1:0]                        bank_rdb_valid;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        bank_rdb_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        bank_rdb_col;
    tmem_swizzle_e                           bank_rdb_swizzle;

    logic [LANES-1:0]                        bank_wr_valid;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        bank_wr_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        bank_wr_col;
    tmem_swizzle_e                           bank_wr_swizzle;
    logic [LANES-1:0][63:0]                  bank_wr_data;
    logic [LANES-1:0][7:0]                   bank_wr_be;

    logic                                    grant_rda_is_mma;
    logic                                    grant_wr_is_mma;
    logic [31:0]                             arb_ld_grants, arb_st_grants;
    logic [31:0]                             arb_mma_rda_grants, arb_mma_rdb_grants, arb_mma_wr_grants;
    logic [31:0]                             arb_escalations, arb_conflict_stalls;

    VX_tmem_arbiter #(
        .LANES         (LANES),
        .NUM_BANKS     (TMEM_NUM_BANKS),
        .AGE_THRESHOLD (4),
        .DEFICIT_MAX   (8)
    ) u_arb_dut (
        .clk                       (clk),
        .reset                     (reset),
        .weight_ld                 (sym_w_ld),
        .weight_st                 (sym_w_st),
        .weight_mma                (sym_w_mma),
        .strict_mma_prio           (sym_strict_mma),
        .starve_limit              (sym_starve_limit),
        .ld_req_valid              (sym_ld_req_valid),
        .ld_req_ready              (arb_ld_ready),
        .ld_req_row                (sym_ld_req_row),
        .ld_req_col                (sym_ld_req_col),
        .ld_req_swizzle            (sym_ld_swizzle),
        .st_req_valid              (sym_st_req_valid),
        .st_req_ready              (arb_st_ready),
        .st_req_row                (sym_st_req_row),
        .st_req_col                (sym_st_req_col),
        .st_req_swizzle            (sym_st_swizzle),
        .st_req_data               (sym_st_data),
        .st_req_be                 (sym_st_be),
        .mma_rda_valid             (sym_mma_rda_valid),
        .mma_rda_ready             (arb_mma_rda_ready),
        .mma_rda_row               (sym_mma_rda_row),
        .mma_rda_col               (sym_mma_rda_col),
        .mma_rda_swizzle           (sym_mma_rda_swizzle),
        .mma_rdb_valid             (sym_mma_rdb_valid),
        .mma_rdb_ready             (arb_mma_rdb_ready),
        .mma_rdb_row               (sym_mma_rdb_row),
        .mma_rdb_col               (sym_mma_rdb_col),
        .mma_rdb_swizzle           (sym_mma_rdb_swizzle),
        .mma_wr_valid              (sym_mma_wr_valid),
        .mma_wr_ready              (arb_mma_wr_ready),
        .mma_wr_row                (sym_mma_wr_row),
        .mma_wr_col                (sym_mma_wr_col),
        .mma_wr_swizzle            (sym_mma_wr_swizzle),
        .mma_wr_data               (sym_mma_wr_data),
        .mma_wr_be                 (sym_mma_wr_be),
        .bank_rda_valid            (bank_rda_valid),
        .bank_rda_ready            (sym_bank_rda_ready),
        .bank_rda_row              (bank_rda_row),
        .bank_rda_col              (bank_rda_col),
        .bank_rda_swizzle          (bank_rda_swizzle),
        .bank_rdb_valid            (bank_rdb_valid),
        .bank_rdb_ready            (sym_bank_rdb_ready),
        .bank_rdb_row              (bank_rdb_row),
        .bank_rdb_col              (bank_rdb_col),
        .bank_rdb_swizzle          (bank_rdb_swizzle),
        .bank_wr_valid             (bank_wr_valid),
        .bank_wr_ready             (sym_bank_wr_ready),
        .bank_wr_row               (bank_wr_row),
        .bank_wr_col               (bank_wr_col),
        .bank_wr_swizzle           (bank_wr_swizzle),
        .bank_wr_data              (bank_wr_data),
        .bank_wr_be                (bank_wr_be),
        .grant_rda_is_mma_out      (grant_rda_is_mma),
        .grant_wr_is_mma_out       (grant_wr_is_mma),
        .ld_grants_out             (arb_ld_grants),
        .st_grants_out             (arb_st_grants),
        .mma_rda_grants_out        (arb_mma_rda_grants),
        .mma_rdb_grants_out        (arb_mma_rdb_grants),
        .mma_wr_grants_out         (arb_mma_wr_grants),
        .escalations_out           (arb_escalations),
        .conflict_stall_cycles_out (arb_conflict_stalls)
    );

    // -------------------------------------------------------------------------
    // 3. Instantiate TMEM Hazard Unit DUT + Shadow Inflight Table for RAW/WAR/WAW
    // -------------------------------------------------------------------------
    logic                               haz_ld_allow, haz_st_allow, haz_mma_allow;
    logic                               haz_fence_drained;
    logic                               haz_raw_stall, haz_war_stall, haz_waw_stall, haz_table_full;
    logic [7:0]                         haz_epoch;
    logic [$clog2(TRACK_DEPTH+1)-1:0]   haz_inflight_cnt;
    logic [31:0]                        haz_stall_cyc, haz_raw_cnt, haz_war_cnt, haz_waw_cnt;

    // Issue only when hazard unit grants allow (next-cycle registered allow is driven back)
    // Also expose combinatorial allow check via shadow tracker matching hazard unit's state.
    logic haz_ld_issue_w, haz_st_issue_w, haz_mma_issue_w;
    assign haz_ld_issue_w  = sym_haz_ld_valid  && haz_ld_allow;
    assign haz_st_issue_w  = sym_haz_st_valid  && haz_st_allow;
    assign haz_mma_issue_w = sym_haz_mma_valid && haz_mma_allow;

    VX_tmem_hazard_unit #(
        .TRACK_DEPTH (TRACK_DEPTH),
        .EPOCH_W     (8)
    ) u_haz_dut (
        .clk                     (clk),
        .reset                   (reset),
        .ld_req_valid            (sym_haz_ld_valid),
        .ld_req_allow            (haz_ld_allow),
        .ld_region_id            (sym_haz_ld_reg),
        .ld_col_start            (sym_haz_ld_col),
        .ld_col_count            (sym_haz_ld_cnt),
        .ld_tag                  (sym_haz_ld_tag),
        .st_req_valid            (sym_haz_st_valid),
        .st_req_allow            (haz_st_allow),
        .st_region_id            (sym_haz_st_reg),
        .st_col_start            (sym_haz_st_col),
        .st_col_count            (sym_haz_st_cnt),
        .st_tag                  (sym_haz_st_tag),
        .mma_req_valid           (sym_haz_mma_valid),
        .mma_req_allow           (haz_mma_allow),
        .mma_is_write            (sym_haz_mma_is_wr),
        .mma_region_id           (sym_haz_mma_reg),
        .mma_col_start           (sym_haz_mma_col),
        .mma_col_count           (sym_haz_mma_cnt),
        .mma_tag                 (sym_haz_mma_tag),
        .ld_issue_fire           (haz_ld_issue_w),
        .st_issue_fire           (haz_st_issue_w),
        .mma_issue_fire          (haz_mma_issue_w),
        .ld_commit_valid         (sym_haz_ld_commit),
        .ld_commit_tag           (sym_haz_ld_ctag),
        .st_commit_valid         (sym_haz_st_commit),
        .st_commit_tag           (sym_haz_st_ctag),
        .mma_commit_valid        (sym_haz_mma_commit),
        .mma_commit_tag          (sym_haz_mma_ctag),
        .fence_req_valid         (sym_haz_fence_valid),
        .fence_region_only       (sym_haz_fence_reg_only),
        .fence_region_id         (sym_haz_fence_reg),
        .fence_drained           (haz_fence_drained),
        .raw_stall_out           (haz_raw_stall),
        .war_stall_out           (haz_war_stall),
        .waw_stall_out           (haz_waw_stall),
        .table_full_out          (haz_table_full),
        .current_epoch_out       (haz_epoch),
        .inflight_count_out      (haz_inflight_cnt),
        .hazard_stall_cycles_out (haz_stall_cyc),
        .raw_hazards_out         (haz_raw_cnt),
        .war_hazards_out         (haz_war_cnt),
        .waw_hazards_out         (haz_waw_cnt)
    );

    // Shadow tracking of previous cycle's request parameters + inflight entries for RAW/WAR/WAW check
    typedef struct packed {
        logic                        valid;
        logic                        is_write;
        logic [1:0]                  client;
        logic [TMEM_REGION_ID_W-1:0] reg_id;
        logic [TMEM_COL_W-1:0]       col_start;
        logic [TMEM_COL_W-1:0]       col_end;
        logic [TMEM_TAG_W-1:0]       tag;
    } shadow_haz_t;

    shadow_haz_t [TRACK_DEPTH-1:0] shadow_q;
    logic                          prev_ld_v_q, prev_st_v_q, prev_mma_v_q, prev_mma_wr_q;
    logic [TMEM_REGION_ID_W-1:0]   prev_ld_reg_q, prev_st_reg_q, prev_mma_reg_q;
    logic [TMEM_COL_W-1:0]         prev_ld_cs_q, prev_ld_ce_q;
    logic [TMEM_COL_W-1:0]         prev_st_cs_q, prev_st_ce_q;
    logic [TMEM_COL_W-1:0]         prev_mma_cs_q, prev_mma_ce_q;
    logic                          prev_fence_v_q, prev_fence_ro_q;
    logic [TMEM_REGION_ID_W-1:0]   prev_fence_reg_q;
    logic                          prev_ld_com_q, prev_st_com_q, prev_mma_com_q;
    logic [TMEM_TAG_W-1:0]         prev_ld_ctag_q, prev_st_ctag_q, prev_mma_ctag_q;
    logic [TRACK_DEPTH-1:0]        prev_ent_valid_q;
    logic [TRACK_DEPTH-1:0]        prev_ent_is_wr_q;
    logic [TRACK_DEPTH-1:0][TMEM_REGION_ID_W-1:0] prev_ent_reg_q;
    logic [TRACK_DEPTH-1:0][TMEM_COL_W-1:0]       prev_ent_cs_q;
    logic [TRACK_DEPTH-1:0][TMEM_COL_W-1:0]       prev_ent_ce_q;

    function automatic logic [TMEM_COL_W-1:0] ref_col_end(
        input logic [TMEM_COL_W-1:0] cs,
        input logic [9:0]            cnt
    );
        logic [10:0] sum;
        logic [9:0]  ec;
        ec  = (cnt == 10'd0) ? 10'd1 : cnt;
        sum = {2'b00, cs} + {1'b0, ec} - 11'd1;
        return (sum >= 11'(TMEM_COLUMNS)) ? TMEM_COL_W'(TMEM_COLUMNS - 1) : sum[TMEM_COL_W-1:0];
    endfunction

    function automatic logic ref_overlap(
        input logic [TMEM_REGION_ID_W-1:0] ra,
        input logic [TMEM_COL_W-1:0]       sa,
        input logic [TMEM_COL_W-1:0]       ea,
        input logic [TMEM_REGION_ID_W-1:0] rb,
        input logic [TMEM_COL_W-1:0]       sb,
        input logic [TMEM_COL_W-1:0]       eb
    );
        return (ra == rb) && (sa <= eb) && (sb <= ea);
    endfunction

    always_ff @(posedge clk) begin
        if (reset) begin
            shadow_q         <= '0;
            prev_ld_v_q      <= 1'b0;
            prev_st_v_q      <= 1'b0;
            prev_mma_v_q     <= 1'b0;
            prev_mma_wr_q    <= 1'b0;
            prev_ld_reg_q    <= '0;
            prev_st_reg_q    <= '0;
            prev_mma_reg_q   <= '0;
            prev_ld_cs_q     <= '0;
            prev_ld_ce_q     <= '0;
            prev_st_cs_q     <= '0;
            prev_st_ce_q     <= '0;
            prev_mma_cs_q    <= '0;
            prev_mma_ce_q    <= '0;
            prev_fence_v_q   <= 1'b0;
            prev_fence_ro_q  <= 1'b0;
            prev_fence_reg_q <= '0;
            prev_ld_com_q    <= 1'b0;
            prev_st_com_q    <= 1'b0;
            prev_mma_com_q   <= 1'b0;
            prev_ld_ctag_q   <= '0;
            prev_st_ctag_q   <= '0;
            prev_mma_ctag_q  <= '0;
            prev_ent_valid_q <= '0;
            prev_ent_is_wr_q <= '0;
            prev_ent_reg_q   <= '0;
            prev_ent_cs_q    <= '0;
            prev_ent_ce_q    <= '0;
        end else begin
            // Snapshot requests and inflight entries that produced the registered allow flags
            for (int e = 0; e < TRACK_DEPTH; ++e) begin
                prev_ent_valid_q[e] <= u_haz_dut.entries_q[e].valid;
                prev_ent_is_wr_q[e] <= u_haz_dut.entries_q[e].is_write;
                prev_ent_reg_q[e]   <= u_haz_dut.entries_q[e].region_id;
                prev_ent_cs_q[e]    <= u_haz_dut.entries_q[e].col_start;
                prev_ent_ce_q[e]    <= u_haz_dut.entries_q[e].col_end;
            end
            prev_ld_v_q      <= sym_haz_ld_valid;
            prev_st_v_q      <= sym_haz_st_valid;
            prev_mma_v_q     <= sym_haz_mma_valid;
            prev_mma_wr_q    <= sym_haz_mma_is_wr;
            prev_ld_reg_q    <= sym_haz_ld_reg;
            prev_st_reg_q    <= sym_haz_st_reg;
            prev_mma_reg_q   <= sym_haz_mma_reg;
            prev_ld_cs_q     <= sym_haz_ld_col;
            prev_ld_ce_q     <= ref_col_end(sym_haz_ld_col, sym_haz_ld_cnt);
            prev_st_cs_q     <= sym_haz_st_col;
            prev_st_ce_q     <= ref_col_end(sym_haz_st_col, sym_haz_st_cnt);
            prev_mma_cs_q    <= sym_haz_mma_col;
            prev_mma_ce_q    <= ref_col_end(sym_haz_mma_col, sym_haz_mma_cnt);
            prev_fence_v_q   <= sym_haz_fence_valid;
            prev_fence_ro_q  <= sym_haz_fence_reg_only;
            prev_fence_reg_q <= sym_haz_fence_reg;
            prev_ld_com_q    <= sym_haz_ld_commit;
            prev_st_com_q    <= sym_haz_st_commit;
            prev_mma_com_q   <= sym_haz_mma_commit;
            prev_ld_ctag_q   <= sym_haz_ld_ctag;
            prev_st_ctag_q   <= sym_haz_st_ctag;
            prev_mma_ctag_q  <= sym_haz_mma_ctag;

            // Update shadow table identically (retire then insert)
            for (int i = 0; i < TRACK_DEPTH; ++i) begin
                if (shadow_q[i].valid &&
                    (((shadow_q[i].client == 2'd0) && sym_haz_ld_commit  && (shadow_q[i].tag == sym_haz_ld_ctag))  ||
                     ((shadow_q[i].client == 2'd1) && sym_haz_st_commit  && (shadow_q[i].tag == sym_haz_st_ctag))  ||
                     ((shadow_q[i].client == 2'd2) && sym_haz_mma_commit && (shadow_q[i].tag == sym_haz_mma_ctag)))) begin
                    shadow_q[i].valid <= 1'b0;
                end
            end
            // Note: actual insertion assertions read shadow_q from previous cycle via prev_ent_*_q
        end
    end

    assign formal_ok_out = (int'(occupied_granules) <= 16) &&
                           !((|arb_ld_ready) && (|arb_mma_rda_ready)) &&
                           !((|arb_st_ready) && (|arb_mma_wr_ready));

    // -------------------------------------------------------------------------
    // Bounded Formal Proofs (`t=12..16` cycles) & Reachability Covers
    // -------------------------------------------------------------------------
`ifdef FORMAL
    reg [7:0] f_cyc_q;
    initial f_cyc_q = 8'd0;

    always_comb begin
        assume (reset == (f_cyc_q < 8'd2));
    end

    always @(posedge clk) begin
        f_cyc_q <= f_cyc_q + 8'd1;

        if (!reset && (f_cyc_q >= 8'd2)) begin
            // --- 1. TMEM Allocator Invariants ---
            // Total allocated granules <= 16 and matches bitmap popcount
            logic [4:0]                    pop_bmp;
            logic [TMEM_NUM_ALLOC_UNITS-1:0] union_masks;
            pop_bmp     = 5'd0;
            union_masks = '0;
            for (int u = 0; u < TMEM_NUM_ALLOC_UNITS; ++u) begin
                pop_bmp = pop_bmp + {4'd0, granule_bitmap[u]};
            end
            assert (occupied_granules == pop_bmp);
            assert (int'(occupied_granules) <= TMEM_NUM_ALLOC_UNITS);
            assert (peak_granules >= occupied_granules);

            // Live regions: 32-col aligned, pow2 >= 32 cols, legal rows, ZERO overlapping granules
            for (int i = 0; i < MAX_REGIONS; ++i) begin
                if (region_table[i].allocated) begin
                    assert (region_table[i].col_offset[4:0] == 5'd0);
                    assert (tmem_is_pow2_cols(region_table[i].num_columns));
                    assert (region_table[i].num_columns >= 10'(TMEM_MIN_ALLOC_COLS));
                    assert (region_table[i].num_columns <= 10'(TMEM_COLUMNS));
                    assert (tmem_rows_legal(region_table[i].num_rows));
                    assert ((union_masks & region_table[i].granule_mask) == '0);
                    union_masks = union_masks | region_table[i].granule_mask;
                end
            end
            assert (union_masks == granule_bitmap);

            // Misaligned / bad-size / OOM allocation requests rejected with error status
            if (prev_alloc_fire_q && (prev_alloc_op_q == 3'd0)) begin
                logic size_ok, rows_ok, align_ok, dbl_ok;
                logic [10:0] eff_cols, end_col;
                size_ok  = tmem_is_pow2_cols(prev_alloc_req_q.num_columns) &&
                           (prev_alloc_req_q.num_columns >= 10'(TMEM_MIN_ALLOC_COLS)) &&
                           (prev_alloc_req_q.num_columns <= 10'(TMEM_COLUMNS));
                rows_ok  = tmem_rows_legal(prev_alloc_req_q.num_rows);
                align_ok = (prev_alloc_req_q.col_offset[4:0] == 5'd0);
                eff_cols = prev_alloc_req_q.double_buf_en
                           ? ({1'b0, prev_alloc_req_q.num_columns} << 1)
                           : {1'b0, prev_alloc_req_q.num_columns};
                dbl_ok   = (eff_cols <= 11'(TMEM_COLUMNS));
                end_col  = {2'b00, prev_alloc_req_q.col_offset} + eff_cols;

                assert (alloc_rsp.valid);
                if (!size_ok || !rows_ok || !dbl_ok) begin
                    assert (alloc_rsp.status != TMEM_STATUS_OK);
                end else if (!prev_auto_place_q && (!align_ok || (end_col > 11'(TMEM_COLUMNS)))) begin
                    assert (alloc_rsp.status != TMEM_STATUS_OK);
                end else if ((5'(prev_occ_granules_q) + eff_cols[9:5]) > 5'(TMEM_NUM_ALLOC_UNITS)) begin
                    assert (alloc_rsp.status != TMEM_STATUS_OK);
                end

                if (alloc_rsp.status == TMEM_STATUS_OK) begin
                    assert (alloc_rsp.col_offset[4:0] == 5'd0);
                    assert (tmem_is_pow2_cols(alloc_rsp.num_columns));
                    assert (alloc_rsp.num_columns >= 10'(TMEM_MIN_ALLOC_COLS));
                end
            end

            // --- 2. TMEM Arbiter Mutual Exclusion ($onehot0) ---
            assert (!((|arb_ld_ready) && (|arb_mma_rda_ready)));
            assert (!((|arb_st_ready) && (|arb_mma_wr_ready)));
            assert (({(|arb_ld_ready), (|arb_mma_rda_ready)} &
                     ({(|arb_ld_ready), (|arb_mma_rda_ready)} - 2'd1)) == 2'd0);
            assert (({(|arb_st_ready), (|arb_mma_wr_ready)} &
                     ({(|arb_st_ready), (|arb_mma_wr_ready)} - 2'd1)) == 2'd0);
            if ((|arb_ld_ready)) begin
                assert (arb_ld_ready == {LANES{1'b1}});
                assert (|sym_ld_req_valid);
            end
            if ((|arb_mma_rda_ready)) begin
                assert (arb_mma_rda_ready == {LANES{1'b1}});
                assert (|sym_mma_rda_valid);
            end
            if ((|arb_st_ready)) begin
                assert (arb_st_ready == {LANES{1'b1}});
                assert (|sym_st_req_valid);
            end
            if ((|arb_mma_wr_ready)) begin
                assert (arb_mma_wr_ready == {LANES{1'b1}});
                assert (|sym_mma_wr_valid);
            end

            // --- 3. TMEM Hazard Unit RAW/WAR/WAW Blocking Invariants ---
            assert (int'(haz_inflight_cnt) <= TRACK_DEPTH);

            // Note: u_haz_dut registers allow_q on clock edge from previous cycle's entries_q.
            // Whenever fence blocked a client on the previous cycle, allow must be 0.
            if (prev_fence_v_q && !prev_fence_ro_q) begin
                assert (!haz_ld_allow && !haz_st_allow && !haz_mma_allow);
            end
            if (prev_fence_v_q && prev_fence_ro_q) begin
                if (prev_ld_reg_q == prev_fence_reg_q) begin
                    assert (!haz_ld_allow);
                end
                if (prev_st_reg_q == prev_fence_reg_q) begin
                    assert (!haz_st_allow);
                end
                if (prev_mma_reg_q == prev_fence_reg_q) begin
                    assert (!haz_mma_allow);
                end
            end

            // Same-cycle cross-client hazard enforcement:
            // If LD and ST overlapped in the same cycle, ST must be blocked (WAR)
            if (prev_ld_v_q && prev_st_v_q &&
                ref_overlap(prev_ld_reg_q, prev_ld_cs_q, prev_ld_ce_q,
                            prev_st_reg_q, prev_st_cs_q, prev_st_ce_q)) begin
                assert (!haz_st_allow);
                assert (haz_war_stall);
            end
            // If ST and MMA overlapped in the same cycle, ST must be blocked (WAW/WAR)
            if (prev_st_v_q && prev_mma_v_q &&
                ref_overlap(prev_st_reg_q, prev_st_cs_q, prev_st_ce_q,
                            prev_mma_reg_q, prev_mma_cs_q, prev_mma_ce_q)) begin
                assert (!haz_st_allow);
                if (prev_mma_wr_q) begin
                    assert (haz_waw_stall);
                end else begin
                    assert (haz_war_stall);
                end
            end
            // If LD and MMA(write) overlapped in the same cycle, LD must be blocked (RAW)
            if (prev_ld_v_q && prev_mma_v_q && prev_mma_wr_q &&
                ref_overlap(prev_ld_reg_q, prev_ld_cs_q, prev_ld_ce_q,
                            prev_mma_reg_q, prev_mma_cs_q, prev_mma_ce_q)) begin
                assert (!haz_ld_allow);
                assert (haz_raw_stall);
            end

            // Also verify active inflight entries in prev_ent_*_q block RAW/WAR/WAW
            // whenever not retiring simultaneously
            for (int e = 0; e < TRACK_DEPTH; ++e) begin
                if (prev_ent_valid_q[e]) begin
                    if (!prev_ld_com_q && !prev_st_com_q && !prev_mma_com_q) begin
                        if (prev_ld_v_q && prev_ent_is_wr_q[e] &&
                            ref_overlap(prev_ld_reg_q, prev_ld_cs_q, prev_ld_ce_q,
                                        prev_ent_reg_q[e], prev_ent_cs_q[e], prev_ent_ce_q[e])) begin
                            assert (!haz_ld_allow);
                        end
                        if (prev_st_v_q &&
                            ref_overlap(prev_st_reg_q, prev_st_cs_q, prev_st_ce_q,
                                        prev_ent_reg_q[e], prev_ent_cs_q[e], prev_ent_ce_q[e])) begin
                            assert (!haz_st_allow);
                        end
                        if (prev_mma_v_q &&
                            (prev_mma_wr_q || prev_ent_is_wr_q[e]) &&
                            ref_overlap(prev_mma_reg_q, prev_mma_cs_q, prev_mma_ce_q,
                                        prev_ent_reg_q[e], prev_ent_cs_q[e], prev_ent_ce_q[e])) begin
                            assert (!haz_mma_allow);
                        end
                    end
                end
            end

            // --- Reachability Covers ---
            cover (alloc_rsp.valid && (alloc_rsp.status == TMEM_STATUS_OK) && (occupied_granules >= 5'd4));
            cover (alloc_rsp.valid && (alloc_rsp.status == TMEM_STATUS_BAD_ALIGN));
            cover (alloc_rsp.valid && (alloc_rsp.status == TMEM_STATUS_OUT_OF_COLS));
            cover (alloc_rsp.valid && (alloc_rsp.status == TMEM_STATUS_OVERLAP));
            cover ((dealloc_count > 32'd0) && (alloc_ok_count >= 32'd2));
            cover ((|arb_ld_ready) && (|sym_mma_rda_valid));
            cover ((|arb_mma_wr_ready) && (|sym_st_req_valid));
            cover (haz_raw_stall && (haz_raw_cnt > 32'd0));
            cover (haz_war_stall && (haz_war_cnt > 32'd0));
            cover (haz_waw_stall && (haz_waw_cnt > 32'd0));
        end
    end
`endif

endmodule
