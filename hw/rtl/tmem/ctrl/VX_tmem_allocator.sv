// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_allocator
    import VX_tmem_pkg::*;
#(
    parameter int NUM_GRANULES = TMEM_NUM_ALLOC_UNITS,
    parameter int MAX_REGIONS  = TMEM_MAX_REGIONS,
    parameter int NUM_WARPS    = 32
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Allocation / deallocation / query command interface
    input  logic                                    req_valid,
    output logic                                    req_ready,
    input  logic [2:0]                              req_op,
    input  logic                                    auto_place_en,
    input  logic                                    buddy_align_en,
    input  logic                                    strict_owner_chk,
    input  tmem_alloc_req_t                         alloc_req,
    // Command response interface (registered output boundary)
    output tmem_alloc_rsp_t                         alloc_rsp,
    output logic                                    query_valid,
    output tmem_region_entry_t                      query_entry_out,
    // Live region table & bitmap export
    output tmem_region_entry_t [MAX_REGIONS-1:0]    region_table_out,
    output logic [NUM_GRANULES-1:0]                 granule_bitmap_out,
    // Occupancy & telemetry counters
    output logic [4:0]                              occupied_granules_out,
    output logic [4:0]                              peak_granules_out,
    output logic [4:0]                              active_regions_out,
    output logic [31:0]                             alloc_ok_count_out,
    output logic [31:0]                             alloc_err_count_out,
    output logic [31:0]                             dealloc_count_out
);

    // Command opcode encoding for req_op
    localparam logic [2:0] ALLOC_OP_ALLOC       = 3'd0;
    localparam logic [2:0] ALLOC_OP_DEALLOC     = 3'd1;
    localparam logic [2:0] ALLOC_OP_QUERY       = 3'd2;
    localparam logic [2:0] ALLOC_OP_RESET_OWNER = 3'd3;
    localparam logic [2:0] ALLOC_OP_FLIP_BUF    = 3'd4;

    localparam int WARP_ID_W = $clog2(NUM_WARPS);

    tmem_region_entry_t [MAX_REGIONS-1:0] region_table_q;
    tmem_region_entry_t [MAX_REGIONS-1:0] region_table_d;
    logic [NUM_GRANULES-1:0]              granule_bitmap_q;
    logic [NUM_GRANULES-1:0]              granule_bitmap_d;

    tmem_alloc_rsp_t                      alloc_rsp_q;
    tmem_alloc_rsp_t                      alloc_rsp_d;
    logic                                 query_valid_q;
    logic                                 query_valid_d;
    tmem_region_entry_t                   query_entry_q;
    tmem_region_entry_t                   query_entry_d;

    logic [4:0]                           occupied_granules_q;
    logic [4:0]                           peak_granules_q;
    logic [4:0]                           active_regions_q;
    logic [31:0]                          alloc_ok_count_q;
    logic [31:0]                          alloc_err_count_q;
    logic [31:0]                          dealloc_count_q;

    logic [31:0]                          alloc_ok_count_d;
    logic [31:0]                          alloc_err_count_d;
    logic [31:0]                          dealloc_count_d;

    // Combinational placement and validation signals
    logic                                 size_pow2_ok;
    logic                                 rows_ok;
    logic                                 align_ok;
    logic [10:0]                          effective_cols_req;
    logic [4:0]                           units_needed;
    logic                                 dbl_buf_cols_ok;
    logic                                 auto_found;
    logic [3:0]                           auto_start_unit;
    logic [NUM_GRANULES-1:0]              auto_mask;
    logic [TMEM_COL_W-1:0]                chosen_col_offset;
    logic [NUM_GRANULES-1:0]              chosen_granule_mask;
    logic                                 free_region_found;
    logic [TMEM_REGION_ID_W-1:0]          free_region_id;
    logic [TMEM_REGION_ID_W-1:0]          target_region_id;
    logic                                 target_id_is_free;
    logic [NUM_GRANULES-1:0]              reset_owner_clear_mask;
    logic [4:0]                           next_occupied_granules;
    logic [4:0]                           next_active_regions;
    logic [4:0]                           u_end_tmp;
    logic                                 aligned_u_tmp;
    logic                                 fit_u_tmp;
    logic [NUM_GRANULES-1:0]              cand_mask_tmp;
    logic [10:0]                          end_col_chk_tmp;
    logic                                 explicit_buddy_ok_tmp;
    logic                                 explicit_overlap_tmp;
    tmem_status_e                         st_code_tmp;
    logic [10:0]                          buf_b_ext_tmp;
    logic [4:0]                           freed_cnt_tmp;

    `UNUSED_PARAM (WARP_ID_W)

    logic                                 req_id_in_range;
    logic                                 target_id_in_range;

    // Popcount helper for 16-bit bitmaps/masks
    function automatic logic [4:0] count_bits16(
        input logic [NUM_GRANULES-1:0] vec
    );
        logic [4:0] acc;
        acc = 5'd0;
        for (int i = 0; i < NUM_GRANULES; ++i) begin
            acc = acc + {4'd0, vec[i]};
        end
        return acc;
    endfunction

    // Single-cycle ready unless reset is asserted
    assign req_ready = ~reset;

    // Decode requested footprint and scan granule bitmap for buddy/first-fit placement
    always_comb begin
        size_pow2_ok       = tmem_is_pow2_cols(alloc_req.num_columns) &&
                             (alloc_req.num_columns >= 10'(TMEM_MIN_ALLOC_COLS)) &&
                             (alloc_req.num_columns <= 10'(TMEM_COLUMNS));
        rows_ok            = tmem_rows_legal(alloc_req.num_rows);
        align_ok           = (alloc_req.col_offset[4:0] == 5'd0);
        effective_cols_req = alloc_req.double_buf_en
                             ? ({1'b0, alloc_req.num_columns} << 1)
                             : {1'b0, alloc_req.num_columns};
        dbl_buf_cols_ok    = (effective_cols_req <= 11'(TMEM_COLUMNS));
        units_needed       = effective_cols_req[9:5];

        req_id_in_range = (int'(alloc_req.region_id) < MAX_REGIONS);

        // Find lowest free region slot if caller wants auto ID or validation
        free_region_found = 1'b0;
        free_region_id    = '0;
        for (int r = MAX_REGIONS - 1; r >= 0; --r) begin
            if (!region_table_q[r].allocated) begin
                free_region_found = 1'b1;
                free_region_id    = TMEM_REGION_ID_W'(r);
            end
        end

        if (auto_place_en && (!req_id_in_range || region_table_q[alloc_req.region_id].allocated) &&
            free_region_found) begin
            target_region_id = free_region_id;
        end else begin
            target_region_id = alloc_req.region_id;
        end
        target_id_in_range = (int'(target_region_id) < MAX_REGIONS);
        target_id_is_free  = target_id_in_range && !region_table_q[target_region_id].allocated;

        // Buddy / first-fit search across 16 column granules (lowest unit wins)
        auto_found      = 1'b0;
        auto_start_unit = 4'd0;
        auto_mask       = '0;
        u_end_tmp       = 5'd0;
        aligned_u_tmp   = 1'b0;
        fit_u_tmp       = 1'b0;
        cand_mask_tmp   = '0;

        if (size_pow2_ok && dbl_buf_cols_ok && (units_needed != 5'd0)) begin
            for (int u = NUM_GRANULES - 1; u >= 0; --u) begin
                u_end_tmp     = 5'(u) + units_needed;
                aligned_u_tmp = (!buddy_align_en) || ((5'(u) & (units_needed - 5'd1)) == 5'd0);
                cand_mask_tmp = '0;
                fit_u_tmp     = 1'b0;

                if (aligned_u_tmp && (u_end_tmp <= 5'(NUM_GRANULES))) begin
                    fit_u_tmp = 1'b1;
                    for (int k = 0; k < NUM_GRANULES; ++k) begin
                        if ((5'(k) >= 5'(u)) && (5'(k) < u_end_tmp)) begin
                            cand_mask_tmp[k] = 1'b1;
                            if (granule_bitmap_q[k]) begin
                                fit_u_tmp = 1'b0;
                            end
                        end
                    end
                end

                if (fit_u_tmp) begin
                    auto_found      = 1'b1;
                    auto_start_unit = 4'(u);
                    auto_mask       = cand_mask_tmp;
                end
            end
        end

        // Explicit placement mask computation
        if (auto_place_en) begin
            chosen_col_offset   = {auto_start_unit, 5'd0};
            chosen_granule_mask = auto_mask;
        end else begin
            chosen_col_offset = alloc_req.col_offset;
            if (effective_cols_req <= 11'(TMEM_COLUMNS)) begin
                chosen_granule_mask = tmem_alloc_granule_mask(
                    alloc_req.col_offset,
                    effective_cols_req[9:0]
                );
            end else begin
                chosen_granule_mask = '0;
            end
        end

        // Precompute mask of granules owned by alloc_req.owner_warp for RESET_OWNER
        reset_owner_clear_mask = '0;
        for (int r = 0; r < MAX_REGIONS; ++r) begin
            if (region_table_q[r].allocated &&
                (region_table_q[r].owner_warp == alloc_req.owner_warp)) begin
                reset_owner_clear_mask = reset_owner_clear_mask | region_table_q[r].granule_mask;
            end
        end
    end

    // Next-state command execution FSM (single-cycle deterministic commit)
    always_comb begin
        region_table_d    = region_table_q;
        granule_bitmap_d  = granule_bitmap_q;
        alloc_rsp_d       = '0;
        query_valid_d     = 1'b0;
        query_entry_d     = query_entry_q;
        alloc_ok_count_d  = alloc_ok_count_q;
        alloc_err_count_d = alloc_err_count_q;
        dealloc_count_d   = dealloc_count_q;

        end_col_chk_tmp       = 11'd0;
        explicit_buddy_ok_tmp = 1'b0;
        explicit_overlap_tmp  = 1'b0;
        st_code_tmp           = TMEM_STATUS_OK;
        buf_b_ext_tmp         = 11'd0;
        freed_cnt_tmp         = 5'd0;

        if (req_valid && req_ready) begin
            case (req_op)
                ALLOC_OP_ALLOC: begin
                    end_col_chk_tmp       = {2'b00, alloc_req.col_offset} + effective_cols_req;
                    explicit_buddy_ok_tmp = (!buddy_align_en) ||
                                            (({1'b0, alloc_req.col_offset[8:5]} &
                                              (units_needed - 5'd1)) == 5'd0);
                    explicit_overlap_tmp  = |(chosen_granule_mask & granule_bitmap_q);
                    st_code_tmp           = TMEM_STATUS_OK;

                    if (!size_pow2_ok || !rows_ok || !dbl_buf_cols_ok) begin
                        st_code_tmp = TMEM_STATUS_BAD_SIZE;
                    end else if (!auto_place_en && (!align_ok || !explicit_buddy_ok_tmp)) begin
                        st_code_tmp = TMEM_STATUS_BAD_ALIGN;
                    end else if (!auto_place_en && (end_col_chk_tmp > 11'(TMEM_COLUMNS))) begin
                        st_code_tmp = TMEM_STATUS_BAD_SIZE;
                    end else if (!target_id_is_free || !free_region_found) begin
                        st_code_tmp = TMEM_STATUS_FULL;
                    end else if (auto_place_en && !auto_found) begin
                        st_code_tmp = TMEM_STATUS_OUT_OF_COLS;
                    end else if (!auto_place_en && explicit_overlap_tmp) begin
                        st_code_tmp = TMEM_STATUS_OVERLAP;
                    end

                    alloc_rsp_d.valid       = 1'b1;
                    alloc_rsp_d.status      = st_code_tmp;
                    alloc_rsp_d.region_id   = target_region_id;
                    alloc_rsp_d.num_columns = alloc_req.num_columns;

                    if (st_code_tmp == TMEM_STATUS_OK) begin
                        buf_b_ext_tmp = {2'b00, chosen_col_offset} +
                                        {1'b0, alloc_req.num_columns};

                        region_table_d[target_region_id].allocated     = 1'b1;
                        region_table_d[target_region_id].active_buf    = 1'b0;
                        region_table_d[target_region_id].double_buf_en = alloc_req.double_buf_en;
                        region_table_d[target_region_id].region_id     = target_region_id;
                        region_table_d[target_region_id].col_offset    = chosen_col_offset;
                        region_table_d[target_region_id].num_columns   = alloc_req.num_columns;
                        region_table_d[target_region_id].num_rows      = alloc_req.num_rows;
                        region_table_d[target_region_id].swizzle       = alloc_req.swizzle;
                        region_table_d[target_region_id].owner_warp    = alloc_req.owner_warp;
                        region_table_d[target_region_id].granule_mask  = chosen_granule_mask;

                        granule_bitmap_d = granule_bitmap_q | chosen_granule_mask;

                        alloc_rsp_d.col_offset       = chosen_col_offset;
                        alloc_rsp_d.buf_b_col_offset = (alloc_req.double_buf_en &&
                                                        (buf_b_ext_tmp < 11'(TMEM_COLUMNS)))
                                                       ? buf_b_ext_tmp[TMEM_COL_W-1:0]
                                                       : chosen_col_offset;
                        alloc_ok_count_d = alloc_ok_count_q + 32'd1;
                    end else begin
                        alloc_rsp_d.col_offset       = '0;
                        alloc_rsp_d.buf_b_col_offset = '0;
                        alloc_err_count_d            = alloc_err_count_q + 32'd1;
                    end
                end

                ALLOC_OP_DEALLOC: begin
                    alloc_rsp_d.valid     = 1'b1;
                    alloc_rsp_d.region_id = alloc_req.region_id;

                    if (!req_id_in_range || !region_table_q[alloc_req.region_id].allocated) begin
                        alloc_rsp_d.status = TMEM_STATUS_NOT_ALLOCED;
                        alloc_err_count_d  = alloc_err_count_q + 32'd1;
                    end else if (strict_owner_chk &&
                                 (region_table_q[alloc_req.region_id].owner_warp !=
                                  alloc_req.owner_warp)) begin
                        alloc_rsp_d.status = TMEM_STATUS_NOT_ALLOCED;
                        alloc_err_count_d  = alloc_err_count_q + 32'd1;
                    end else begin
                        alloc_rsp_d.status      = TMEM_STATUS_OK;
                        alloc_rsp_d.col_offset  = region_table_q[alloc_req.region_id].col_offset;
                        alloc_rsp_d.num_columns = region_table_q[alloc_req.region_id].num_columns;

                        granule_bitmap_d = granule_bitmap_q &
                                           ~region_table_q[alloc_req.region_id].granule_mask;
                        region_table_d[alloc_req.region_id] = '0;
                        dealloc_count_d = dealloc_count_q + 32'd1;
                    end
                end

                ALLOC_OP_QUERY: begin
                    alloc_rsp_d.valid     = 1'b1;
                    alloc_rsp_d.region_id = alloc_req.region_id;
                    query_valid_d         = 1'b1;
                    query_entry_d         = req_id_in_range ? region_table_q[alloc_req.region_id] : '0;

                    if (!req_id_in_range || !region_table_q[alloc_req.region_id].allocated) begin
                        alloc_rsp_d.status = TMEM_STATUS_NOT_ALLOCED;
                    end else begin
                        buf_b_ext_tmp = {2'b00, region_table_q[alloc_req.region_id].col_offset} +
                                        {1'b0, region_table_q[alloc_req.region_id].num_columns};
                        alloc_rsp_d.status           = TMEM_STATUS_OK;
                        alloc_rsp_d.col_offset       = region_table_q[alloc_req.region_id].col_offset;
                        alloc_rsp_d.num_columns      = region_table_q[alloc_req.region_id].num_columns;
                        alloc_rsp_d.buf_b_col_offset = (region_table_q[alloc_req.region_id].double_buf_en &&
                                                        (buf_b_ext_tmp < 11'(TMEM_COLUMNS)))
                                                       ? buf_b_ext_tmp[TMEM_COL_W-1:0]
                                                       : region_table_q[alloc_req.region_id].col_offset;
                    end
                end

                ALLOC_OP_RESET_OWNER: begin
                    freed_cnt_tmp = 5'd0;
                    for (int r = 0; r < MAX_REGIONS; ++r) begin
                        if (region_table_q[r].allocated &&
                            (region_table_q[r].owner_warp == alloc_req.owner_warp)) begin
                            region_table_d[r] = '0;
                            freed_cnt_tmp     = freed_cnt_tmp + 5'd1;
                        end
                    end
                    granule_bitmap_d      = granule_bitmap_q & ~reset_owner_clear_mask;
                    alloc_rsp_d.valid     = 1'b1;
                    alloc_rsp_d.status    = TMEM_STATUS_OK;
                    alloc_rsp_d.region_id = alloc_req.region_id;
                    dealloc_count_d       = dealloc_count_q + {27'd0, freed_cnt_tmp};
                end

                ALLOC_OP_FLIP_BUF: begin
                    alloc_rsp_d.valid     = 1'b1;
                    alloc_rsp_d.region_id = alloc_req.region_id;
                    if (!req_id_in_range || !region_table_q[alloc_req.region_id].allocated) begin
                        alloc_rsp_d.status = TMEM_STATUS_NOT_ALLOCED;
                        alloc_err_count_d  = alloc_err_count_q + 32'd1;
                    end else if (!region_table_q[alloc_req.region_id].double_buf_en) begin
                        alloc_rsp_d.status = TMEM_STATUS_BAD_SIZE;
                        alloc_err_count_d  = alloc_err_count_q + 32'd1;
                    end else begin
                        buf_b_ext_tmp = {2'b00, region_table_q[alloc_req.region_id].col_offset} +
                                        {1'b0, region_table_q[alloc_req.region_id].num_columns};
                        region_table_d[alloc_req.region_id].active_buf =
                            ~region_table_q[alloc_req.region_id].active_buf;
                        alloc_rsp_d.status           = TMEM_STATUS_OK;
                        alloc_rsp_d.col_offset       = region_table_q[alloc_req.region_id].col_offset;
                        alloc_rsp_d.num_columns      = region_table_q[alloc_req.region_id].num_columns;
                        alloc_rsp_d.buf_b_col_offset = (buf_b_ext_tmp < 11'(TMEM_COLUMNS))
                                                       ? buf_b_ext_tmp[TMEM_COL_W-1:0]
                                                       : region_table_q[alloc_req.region_id].col_offset;
                    end
                end

                default: begin
                    alloc_rsp_d.valid  = 1'b1;
                    alloc_rsp_d.status = TMEM_STATUS_BAD_SIZE;
                    alloc_err_count_d  = alloc_err_count_q + 32'd1;
                end
            endcase
        end

        // Recompute next occupancy and active region counts
        next_occupied_granules = count_bits16(granule_bitmap_d);
        next_active_regions    = 5'd0;
        for (int r = 0; r < MAX_REGIONS; ++r) begin
            if (region_table_d[r].allocated) begin
                next_active_regions = next_active_regions + 5'd1;
            end
        end
    end

    // Sequential state and watermark update
    always_ff @(posedge clk) begin
        if (reset) begin
            region_table_q      <= '0;
            granule_bitmap_q    <= '0;
            alloc_rsp_q         <= '0;
            query_valid_q       <= 1'b0;
            query_entry_q       <= '0;
            occupied_granules_q <= 5'd0;
            peak_granules_q     <= 5'd0;
            active_regions_q    <= 5'd0;
            alloc_ok_count_q    <= 32'd0;
            alloc_err_count_q   <= 32'd0;
            dealloc_count_q     <= 32'd0;
        end else begin
            region_table_q      <= region_table_d;
            granule_bitmap_q    <= granule_bitmap_d;
            alloc_rsp_q         <= alloc_rsp_d;
            query_valid_q       <= query_valid_d;
            query_entry_q       <= query_entry_d;
            occupied_granules_q <= next_occupied_granules;
            active_regions_q    <= next_active_regions;
            alloc_ok_count_q    <= alloc_ok_count_d;
            alloc_err_count_q   <= alloc_err_count_d;
            dealloc_count_q     <= dealloc_count_d;
            if (next_occupied_granules > peak_granules_q) begin
                peak_granules_q <= next_occupied_granules;
            end
        end
    end

    // Unused fields of alloc_req when not applicable
    `UNUSED_VAR (alloc_req)

    // Registered output assignments
    assign alloc_rsp             = alloc_rsp_q;
    assign query_valid           = query_valid_q;
    assign query_entry_out       = query_entry_q;
    assign region_table_out      = region_table_q;
    assign granule_bitmap_out    = granule_bitmap_q;
    assign occupied_granules_out = occupied_granules_q;
    assign peak_granules_out     = peak_granules_q;
    assign active_regions_out    = active_regions_q;
    assign alloc_ok_count_out    = alloc_ok_count_q;
    assign alloc_err_count_out   = alloc_err_count_q;
    assign dealloc_count_out     = dealloc_count_q;

endmodule
