// SPDX-License-Identifier: Apache-2.0
module VX_tmem_hazard_unit
    import VX_tmem_pkg::*;
#(
    parameter int TRACK_DEPTH  = 16,
    parameter int EPOCH_W      = 8
) (
    input  logic                                clk,
    input  logic                                reset,
    // Incoming transaction issue checks (LD, ST, MMA)
    input  logic                                ld_req_valid,
    output logic                                ld_req_allow,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_region_id,
    input  logic [TMEM_COL_W-1:0]               ld_col_start,
    input  logic [9:0]                          ld_col_count,
    input  logic [TMEM_TAG_W-1:0]               ld_tag,

    input  logic                                st_req_valid,
    output logic                                st_req_allow,
    input  logic [TMEM_REGION_ID_W-1:0]         st_region_id,
    input  logic [TMEM_COL_W-1:0]               st_col_start,
    input  logic [9:0]                          st_col_count,
    input  logic [TMEM_TAG_W-1:0]               st_tag,

    input  logic                                mma_req_valid,
    output logic                                mma_req_allow,
    input  logic                                mma_is_write,
    input  logic [TMEM_REGION_ID_W-1:0]         mma_region_id,
    input  logic [TMEM_COL_W-1:0]               mma_col_start,
    input  logic [9:0]                          mma_col_count,
    input  logic [TMEM_TAG_W-1:0]               mma_tag,

    // Issue commit strobes (when the client actually accepts/launches)
    input  logic                                ld_issue_fire,
    input  logic                                st_issue_fire,
    input  logic                                mma_issue_fire,
    // Completion retirement strobes (by client + tag)
    input  logic                                ld_commit_valid,
    input  logic [TMEM_TAG_W-1:0]               ld_commit_tag,
    input  logic                                st_commit_valid,
    input  logic [TMEM_TAG_W-1:0]               st_commit_tag,
    input  logic                                mma_commit_valid,
    input  logic [TMEM_TAG_W-1:0]               mma_commit_tag,
    // Fence draining interface
    input  logic                                fence_req_valid,
    input  logic                                fence_region_only,
    input  logic [TMEM_REGION_ID_W-1:0]         fence_region_id,
    output logic                                fence_drained,
    // Registered hazard & stall telemetry
    output logic                                raw_stall_out,
    output logic                                war_stall_out,
    output logic                                waw_stall_out,
    output logic                                table_full_out,
    output logic [EPOCH_W-1:0]                  current_epoch_out,
    output logic [$clog2(TRACK_DEPTH+1)-1:0]    inflight_count_out,
    output logic [31:0]                         hazard_stall_cycles_out,
    output logic [31:0]                         raw_hazards_out,
    output logic [31:0]                         war_hazards_out,
    output logic [31:0]                         waw_hazards_out
);

    localparam logic [1:0] CLIENT_LD  = 2'd0;
    localparam logic [1:0] CLIENT_ST  = 2'd1;
    localparam logic [1:0] CLIENT_MMA = 2'd2;

    typedef struct packed {
        logic                         valid;
        logic                         is_write;
        logic [1:0]                   client_id;
        logic [TMEM_REGION_ID_W-1:0]  region_id;
        logic [TMEM_COL_W-1:0]        col_start;
        logic [TMEM_COL_W-1:0]        col_end;
        logic [TMEM_TAG_W-1:0]        tag;
        logic [EPOCH_W-1:0]           epoch;
    } haz_entry_t;

    haz_entry_t [TRACK_DEPTH-1:0]     entries_q, entries_d;
    logic [EPOCH_W-1:0]               epoch_q, epoch_d;
    logic [$clog2(TRACK_DEPTH+1)-1:0] inflight_q, inflight_d;

    logic        ld_allow_q, ld_allow_d;
    logic        st_allow_q, st_allow_d;
    logic        mma_allow_q, mma_allow_d;
    logic        fence_drained_q, fence_drained_d;

    logic        raw_stall_q, raw_stall_d;
    logic        war_stall_q, war_stall_d;
    logic        waw_stall_q, waw_stall_d;
    logic        table_full_q, table_full_d;
    logic [31:0] hazard_stall_cycles_q, hazard_stall_cycles_d;
    logic [31:0] raw_hazards_q, raw_hazards_d;
    logic [31:0] war_hazards_q, war_hazards_d;
    logic [31:0] waw_hazards_q, waw_hazards_d;

    // Combinational conflict detectors
    logic        ld_raw_hit, ld_war_hit, ld_waw_hit;
    logic        st_raw_hit, st_war_hit, st_waw_hit;
    logic        mma_raw_hit, mma_war_hit, mma_waw_hit;
    logic        fence_blocking_all;
    logic        fence_blocking_ld;
    logic        fence_blocking_st;
    logic        fence_blocking_mma;
    logic        any_free_slot;
    logic [2:0]  free_count_avail;

    logic [TMEM_COL_W-1:0]            ld_end_tmp, st_end_tmp, mma_end_tmp;
    logic [4:0]                       free_cnt_tmp;
    logic                             region_busy_tmp, any_busy_tmp;
    logic                             retiring_i_tmp;
    logic [EPOCH_W-1:0]               next_ep_tmp;
    logic                             inserted_mma_tmp, inserted_ld_tmp, inserted_st_tmp;
    logic [$clog2(TRACK_DEPTH+1)-1:0] cnt_acc_tmp;

    // Inclusive column end helper clamped to TMEM_COLUMNS - 1
    function automatic logic [TMEM_COL_W-1:0] calc_col_end(
        input logic [TMEM_COL_W-1:0] col_start,
        input logic [9:0]            col_count
    );
        logic [10:0] sum;
        logic [9:0]  eff_cnt;
        eff_cnt = (col_count == 10'd0) ? 10'd1 : col_count;
        sum     = {2'b00, col_start} + {1'b0, eff_cnt} - 11'd1;
        if (sum >= 11'(TMEM_COLUMNS)) begin
            return TMEM_COL_W'(TMEM_COLUMNS - 1);
        end else begin
            return sum[TMEM_COL_W-1:0];
        end
    endfunction

    // Range overlap checker in same region
    function automatic logic ranges_conflict(
        input logic [TMEM_REGION_ID_W-1:0] reg_a,
        input logic [TMEM_COL_W-1:0]       start_a,
        input logic [TMEM_COL_W-1:0]       end_a,
        input logic [TMEM_REGION_ID_W-1:0] reg_b,
        input logic [TMEM_COL_W-1:0]       start_b,
        input logic [TMEM_COL_W-1:0]       end_b
    );
        return (reg_a == reg_b) && (start_a <= end_b) && (start_b <= end_a);
    endfunction

    // Check incoming requests against active entries_q (plus same-cycle retire bypass)
    always_comb begin
        ld_end_tmp  = calc_col_end(ld_col_start, ld_col_count);
        st_end_tmp  = calc_col_end(st_col_start, st_col_count);
        mma_end_tmp = calc_col_end(mma_col_start, mma_col_count);

        ld_raw_hit  = 1'b0;
        ld_war_hit  = 1'b0;
        ld_waw_hit  = 1'b0;
        st_raw_hit  = 1'b0;
        st_war_hit  = 1'b0;
        st_waw_hit  = 1'b0;
        mma_raw_hit = 1'b0;
        mma_war_hit = 1'b0;
        mma_waw_hit = 1'b0;

        free_cnt_tmp    = 5'd0;
        region_busy_tmp = 1'b0;
        any_busy_tmp    = 1'b0;
        retiring_i_tmp  = 1'b0;

        for (int i = 0; i < TRACK_DEPTH; ++i) begin
            retiring_i_tmp = entries_q[i].valid &&
                             (((entries_q[i].client_id == CLIENT_LD)  && ld_commit_valid  &&
                               (entries_q[i].tag == ld_commit_tag))  ||
                              ((entries_q[i].client_id == CLIENT_ST)  && st_commit_valid  &&
                               (entries_q[i].tag == st_commit_tag))  ||
                              ((entries_q[i].client_id == CLIENT_MMA) && mma_commit_valid &&
                               (entries_q[i].tag == mma_commit_tag)));

            if (!entries_q[i].valid || retiring_i_tmp) begin
                free_cnt_tmp = free_cnt_tmp + 5'd1;
            end else begin
                any_busy_tmp = 1'b1;
                if (entries_q[i].region_id == fence_region_id) begin
                    region_busy_tmp = 1'b1;
                end

                // LD is always a read
                if (ld_req_valid &&
                    ranges_conflict(ld_region_id, ld_col_start, ld_end_tmp,
                                    entries_q[i].region_id, entries_q[i].col_start,
                                    entries_q[i].col_end)) begin
                    if (entries_q[i].is_write) begin
                        ld_raw_hit = 1'b1;
                    end
                end

                // ST is always a write
                if (st_req_valid &&
                    ranges_conflict(st_region_id, st_col_start, st_end_tmp,
                                    entries_q[i].region_id, entries_q[i].col_start,
                                    entries_q[i].col_end)) begin
                    if (entries_q[i].is_write) begin
                        st_waw_hit = 1'b1;
                    end else begin
                        st_war_hit = 1'b1;
                    end
                end

                // MMA can be read or write
                if (mma_req_valid &&
                    ranges_conflict(mma_region_id, mma_col_start, mma_end_tmp,
                                    entries_q[i].region_id, entries_q[i].col_start,
                                    entries_q[i].col_end)) begin
                    if (!mma_is_write && entries_q[i].is_write) begin
                        mma_raw_hit = 1'b1;
                    end else if (mma_is_write && entries_q[i].is_write) begin
                        mma_waw_hit = 1'b1;
                    end else if (mma_is_write && !entries_q[i].is_write) begin
                        mma_war_hit = 1'b1;
                    end
                end
            end
        end

        // Same-cycle cross-client priority serialization if two requests overlap in same cycle
        if (ld_req_valid && st_req_valid &&
            ranges_conflict(ld_region_id, ld_col_start, ld_end_tmp,
                            st_region_id, st_col_start, st_end_tmp)) begin
            // Allow LD first; hold ST for WAR avoidance
            st_war_hit = 1'b1;
        end
        if (st_req_valid && mma_req_valid &&
            ranges_conflict(st_region_id, st_col_start, st_end_tmp,
                            mma_region_id, mma_col_start, mma_end_tmp)) begin
            // Give MMA precedence over ST on same-cycle collision
            if (mma_is_write) begin
                st_waw_hit = 1'b1;
            end else begin
                st_war_hit = 1'b1;
            end
        end
        if (ld_req_valid && mma_req_valid && mma_is_write &&
            ranges_conflict(ld_region_id, ld_col_start, ld_end_tmp,
                            mma_region_id, mma_col_start, mma_end_tmp)) begin
            ld_raw_hit = 1'b1;
        end

        any_free_slot      = (free_cnt_tmp != 5'd0);
        free_count_avail   = (free_cnt_tmp >= 5'd3) ? 3'd3 : free_cnt_tmp[2:0];
        fence_blocking_all = fence_req_valid && !fence_region_only;
        fence_blocking_ld  = fence_blocking_all ||
                             (fence_req_valid && fence_region_only && (ld_region_id == fence_region_id));
        fence_blocking_st  = fence_blocking_all ||
                             (fence_req_valid && fence_region_only && (st_region_id == fence_region_id));
        fence_blocking_mma = fence_blocking_all ||
                             (fence_req_valid && fence_region_only && (mma_region_id == fence_region_id));

        fence_drained_d = fence_req_valid ? (fence_region_only ? ~region_busy_tmp : ~any_busy_tmp) : ~any_busy_tmp;

        // Priority slot allocation if multiple clients issue simultaneously near table full
        mma_allow_d = mma_req_valid && any_free_slot && !fence_blocking_mma &&
                      !(mma_raw_hit || mma_war_hit || mma_waw_hit);
        ld_allow_d  = ld_req_valid && !fence_blocking_ld &&
                      !(ld_raw_hit || ld_war_hit || ld_waw_hit) &&
                      (free_count_avail >= (mma_allow_d ? 3'd2 : 3'd1));
        st_allow_d  = st_req_valid && !fence_blocking_st &&
                      !(st_raw_hit || st_war_hit || st_waw_hit) &&
                      (free_count_avail >= ((3'({2'b00, mma_allow_d}) +
                                             3'({2'b00, ld_allow_d})) + 3'd1));

        raw_stall_d  = ld_raw_hit | st_raw_hit | mma_raw_hit;
        war_stall_d  = ld_war_hit | st_war_hit | mma_war_hit;
        waw_stall_d  = ld_waw_hit | st_waw_hit | mma_waw_hit;
        table_full_d = !any_free_slot && (ld_req_valid || st_req_valid || mma_req_valid);
    end

    // Next-state tracker table updates: retire first, then insert issued transactions
    always_comb begin
        entries_d        = entries_q;
        next_ep_tmp      = epoch_q;
        inserted_mma_tmp = 1'b0;
        inserted_ld_tmp  = 1'b0;
        inserted_st_tmp  = 1'b0;
        cnt_acc_tmp      = '0;

        // 1) Retire matching entries
        for (int i = 0; i < TRACK_DEPTH; ++i) begin
            if (entries_d[i].valid) begin
                if (((entries_d[i].client_id == CLIENT_LD)  && ld_commit_valid  &&
                     (entries_d[i].tag == ld_commit_tag))  ||
                    ((entries_d[i].client_id == CLIENT_ST)  && st_commit_valid  &&
                     (entries_d[i].tag == st_commit_tag))  ||
                    ((entries_d[i].client_id == CLIENT_MMA) && mma_commit_valid &&
                     (entries_d[i].tag == mma_commit_tag))) begin
                    entries_d[i] = '0;
                end
            end
        end

        // 2) Insert MMA issue if fired
        if (mma_issue_fire) begin
            for (int i = 0; i < TRACK_DEPTH; ++i) begin
                if (!entries_d[i].valid && !inserted_mma_tmp) begin
                    entries_d[i].valid     = 1'b1;
                    entries_d[i].is_write  = mma_is_write;
                    entries_d[i].client_id = CLIENT_MMA;
                    entries_d[i].region_id = mma_region_id;
                    entries_d[i].col_start = mma_col_start;
                    entries_d[i].col_end   = mma_end_tmp;
                    entries_d[i].tag       = mma_tag;
                    entries_d[i].epoch     = next_ep_tmp;
                    inserted_mma_tmp       = 1'b1;
                end
            end
            next_ep_tmp = next_ep_tmp + EPOCH_W'(1);
        end

        // 3) Insert LD issue if fired
        if (ld_issue_fire) begin
            for (int i = 0; i < TRACK_DEPTH; ++i) begin
                if (!entries_d[i].valid && !inserted_ld_tmp) begin
                    entries_d[i].valid     = 1'b1;
                    entries_d[i].is_write  = 1'b0;
                    entries_d[i].client_id = CLIENT_LD;
                    entries_d[i].region_id = ld_region_id;
                    entries_d[i].col_start = ld_col_start;
                    entries_d[i].col_end   = ld_end_tmp;
                    entries_d[i].tag       = ld_tag;
                    entries_d[i].epoch     = next_ep_tmp;
                    inserted_ld_tmp        = 1'b1;
                end
            end
            next_ep_tmp = next_ep_tmp + EPOCH_W'(1);
        end

        // 4) Insert ST issue if fired
        if (st_issue_fire) begin
            for (int i = 0; i < TRACK_DEPTH; ++i) begin
                if (!entries_d[i].valid && !inserted_st_tmp) begin
                    entries_d[i].valid     = 1'b1;
                    entries_d[i].is_write  = 1'b1;
                    entries_d[i].client_id = CLIENT_ST;
                    entries_d[i].region_id = st_region_id;
                    entries_d[i].col_start = st_col_start;
                    entries_d[i].col_end   = st_end_tmp;
                    entries_d[i].tag       = st_tag;
                    entries_d[i].epoch     = next_ep_tmp;
                    inserted_st_tmp        = 1'b1;
                end
            end
            next_ep_tmp = next_ep_tmp + EPOCH_W'(1);
        end

        epoch_d = next_ep_tmp;

        for (int i = 0; i < TRACK_DEPTH; ++i) begin
            if (entries_d[i].valid) begin
                cnt_acc_tmp = cnt_acc_tmp + 1;
            end
        end
        inflight_d = cnt_acc_tmp;

        hazard_stall_cycles_d = hazard_stall_cycles_q +
                                ((raw_stall_d || war_stall_d || waw_stall_d || table_full_d)
                                 ? 32'd1 : 32'd0);
        raw_hazards_d = raw_hazards_q + (raw_stall_d ? 32'd1 : 32'd0);
        war_hazards_d = war_hazards_q + (war_stall_d ? 32'd1 : 32'd0);
        waw_hazards_d = waw_hazards_q + (waw_stall_d ? 32'd1 : 32'd0);
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            entries_q             <= '0;
            epoch_q               <= '0;
            inflight_q            <= '0;
            ld_allow_q            <= 1'b0;
            st_allow_q            <= 1'b0;
            mma_allow_q           <= 1'b0;
            fence_drained_q       <= 1'b1;
            raw_stall_q           <= 1'b0;
            war_stall_q           <= 1'b0;
            waw_stall_q           <= 1'b0;
            table_full_q          <= 1'b0;
            hazard_stall_cycles_q <= 32'd0;
            raw_hazards_q         <= 32'd0;
            war_hazards_q         <= 32'd0;
            waw_hazards_q         <= 32'd0;
        end else begin
            entries_q             <= entries_d;
            epoch_q               <= epoch_d;
            inflight_q            <= inflight_d;
            ld_allow_q            <= ld_allow_d;
            st_allow_q            <= st_allow_d;
            mma_allow_q           <= mma_allow_d;
            fence_drained_q       <= fence_drained_d;
            raw_stall_q           <= raw_stall_d;
            war_stall_q           <= war_stall_d;
            waw_stall_q           <= waw_stall_d;
            table_full_q          <= table_full_d;
            hazard_stall_cycles_q <= hazard_stall_cycles_d;
            raw_hazards_q         <= raw_hazards_d;
            war_hazards_q         <= war_hazards_d;
            waw_hazards_q         <= waw_hazards_d;
        end
    end

    assign ld_req_allow            = ld_allow_q;
    assign st_req_allow            = st_allow_q;
    assign mma_req_allow           = mma_allow_q;
    assign fence_drained           = fence_drained_q;
    assign raw_stall_out           = raw_stall_q;
    assign war_stall_out           = war_stall_q;
    assign waw_stall_out           = waw_stall_q;
    assign table_full_out          = table_full_q;
    assign current_epoch_out       = epoch_q;
    assign inflight_count_out      = inflight_q;
    assign hazard_stall_cycles_out = hazard_stall_cycles_q;
    assign raw_hazards_out         = raw_hazards_q;
    assign war_hazards_out         = war_hazards_q;
    assign waw_hazards_out         = waw_hazards_q;

endmodule
