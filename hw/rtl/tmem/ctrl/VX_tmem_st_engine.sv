// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_st_engine
    import VX_tmem_pkg::*;
#(
    parameter int LANES      = 8,
    parameter int DESC_DEPTH = 4
) (
    input  logic                                clk,
    input  logic                                reset,
    // Incoming tmem.st descriptor + payload beat interface
    input  logic                                st_req_valid,
    output logic                                st_req_ready,
    input  logic [TMEM_TAG_W-1:0]               st_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         st_req_region_id,
    input  logic [4:0]                          st_req_warp_id,
    input  logic [TMEM_ROW_W-1:0]               st_req_row_base,
    input  logic [TMEM_COL_W-1:0]               st_req_col_base,
    input  logic [7:0]                          st_req_num_rows,
    input  logic [9:0]                          st_req_num_cols,
    input  logic                                st_req_col_major,
    input  logic                                st_req_cell32_mode,
    input  logic [LANES-1:0][63:0]              st_req_data,
    input  logic [LANES-1:0][7:0]               st_req_be,
    input  logic                                st_req_last,
    // Region table & hazard/bounds coordination
    input  tmem_region_entry_t [TMEM_MAX_REGIONS-1:0] region_table_in,
    input  logic                                hazard_allow,
    input  logic                                bounds_fault_in,
    output logic                                hazard_issue_fire,
    output logic [TMEM_REGION_ID_W-1:0]         hazard_issue_region_id,
    output logic [4:0]                          hazard_issue_warp_id,
    output logic                                hazard_commit_valid,
    output logic [TMEM_TAG_W-1:0]               hazard_commit_tag,
    output logic [TMEM_REGION_ID_W-1:0]         hazard_commit_region_id,
    output logic [4:0]                          hazard_commit_warp_id,
    output logic                                hazard_chk_valid,
    output logic [TMEM_REGION_ID_W-1:0]         hazard_chk_region_id,
    output logic [TMEM_COL_W-1:0]               hazard_chk_col_start,
    output logic [9:0]                          hazard_chk_col_count,
    output logic [TMEM_TAG_W-1:0]               hazard_chk_tag,
    // Arbiter-facing LANES=8 write port requests
    output logic [LANES-1:0]                    bank_wr_valid,
    input  logic [LANES-1:0]                    bank_wr_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_wr_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]    bank_wr_col,
    output tmem_swizzle_e                       bank_wr_swizzle,
    output logic [LANES-1:0][63:0]              bank_wr_data,
    output logic [LANES-1:0][7:0]               bank_wr_be,
    // Store completion pulse & status output
    output logic                                st_ack_valid,
    input  logic                                st_ack_ready,
    output logic [TMEM_TAG_W-1:0]               st_ack_tag,
    output logic [4:0]                          st_ack_warp_id,
    output tmem_status_e                        st_ack_status,
    // Telemetry
    output logic [31:0]                         st_beats_out,
    output logic [31:0]                         st_oob_faults_out
);

    typedef enum logic [1:0] {
        ST_IDLE   = 2'd0,
        ST_ISSUE  = 2'd1,
        ST_WAIT   = 2'd2,
        ST_FAULT  = 2'd3
    } st_state_e;

    typedef struct packed {
        logic [TMEM_TAG_W-1:0]       tag;
        logic [TMEM_REGION_ID_W-1:0] region_id;
        logic [4:0]                  warp_id;
        logic [TMEM_ROW_W-1:0]       row_base;
        logic [TMEM_COL_W-1:0]       col_base;
        logic [7:0]                  num_rows;
        logic [9:0]                  num_cols;
        logic                        col_major;
        logic                        cell32_mode;
        logic [LANES-1:0][63:0]      data;
        logic [LANES-1:0][7:0]       be;
        logic                        last;
        logic                        bounds_fault;
    } st_beat_t;

    st_beat_t [DESC_DEPTH-1:0]          beat_q_mem_q;
    logic [$clog2(DESC_DEPTH)-1:0]      beat_q_head_q, beat_q_tail_q;
    logic [$clog2(DESC_DEPTH+1)-1:0]    beat_q_cnt_q;

    st_state_e                          state_q, state_d;
    st_beat_t                           active_beat_q, active_beat_d;
    logic [7:0]                         cur_row_off_q, cur_row_off_d;
    logic [9:0]                         cur_col_off_q, cur_col_off_d;
    logic                               stream_active_q, stream_active_d;

    logic [LANES-1:0]                   bank_wr_valid_q, bank_wr_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   bank_wr_row_q, bank_wr_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0]   bank_wr_col_q, bank_wr_col_d;
    tmem_swizzle_e                      bank_wr_swizzle_q, bank_wr_swizzle_d;
    logic [LANES-1:0][63:0]             bank_wr_data_q, bank_wr_data_d;
    logic [LANES-1:0][7:0]              bank_wr_be_q, bank_wr_be_d;

    logic                               st_ack_valid_q, st_ack_valid_d;
    logic [TMEM_TAG_W-1:0]              st_ack_tag_q, st_ack_tag_d;
    logic [4:0]                         st_ack_warp_id_q, st_ack_warp_id_d;
    tmem_status_e                       st_ack_status_q, st_ack_status_d;

    logic                               hazard_issue_fire_q, hazard_issue_fire_d;
    logic [TMEM_REGION_ID_W-1:0]        hazard_issue_region_id_q, hazard_issue_region_id_d;
    logic [4:0]                         hazard_issue_warp_id_q, hazard_issue_warp_id_d;
    logic                               hazard_commit_valid_q, hazard_commit_valid_d;
    logic [TMEM_TAG_W-1:0]              hazard_commit_tag_q, hazard_commit_tag_d;
    logic [TMEM_REGION_ID_W-1:0]        hazard_commit_region_id_q, hazard_commit_region_id_d;
    logic [4:0]                         hazard_commit_warp_id_q, hazard_commit_warp_id_d;
    logic [31:0]                        st_beats_q, st_beats_d;
    logic [31:0]                        st_oob_faults_q, st_oob_faults_d;

    logic                               beat_q_empty;
    logic                               beat_q_full;
    logic                               beat_pop;
    logic                               beat_push;
    st_beat_t                           beat_head_item;

    tmem_region_entry_t                 cur_reg_tmp;
    logic                               perm_ok_tmp;
    logic                               ack_slot_free_tmp;
    logic [LANES-1:0]                   next_wr_valid_tmp;
    logic [9:0]                         rem_cols_tmp;
    logic [7:0]                         rem_rows_tmp;
    logic [9:0]                         step_cols_tmp;
    logic [7:0]                         step_rows_tmp;
    logic                               tile_last_beat_tmp;
    logic [LANES-1:0]                   wr_v_tmp;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   wr_r_tmp;
    logic [LANES-1:0][TMEM_COL_W-1:0]   wr_c_tmp;
    logic [LANES-1:0][63:0]             wr_d_tmp;
    logic [LANES-1:0][7:0]              wr_b_tmp;
    tmem_region_entry_t                 act_reg_tmp;
    logic [TMEM_COL_W-1:0]              eff_col_base_tmp;
    logic [8:0]                         lane_r_tmp;
    logic [10:0]                        lane_c_tmp;
    logic                               hs_tmp;

    assign beat_q_empty   = (beat_q_cnt_q == '0);
    assign beat_q_full    = (beat_q_cnt_q == ($clog2(DESC_DEPTH+1))'(DESC_DEPTH));
    assign st_req_ready   = !beat_q_full && !reset;
    assign beat_push      = st_req_valid && st_req_ready;
    assign beat_head_item = beat_q_mem_q[beat_q_head_q];

    assign hazard_chk_valid     = !beat_q_empty && (state_q == ST_IDLE) && !stream_active_q;
    assign hazard_chk_region_id = hazard_issue_fire_q ? active_beat_q.region_id : beat_head_item.region_id;
    assign hazard_chk_col_start = hazard_issue_fire_q ? active_beat_q.col_base  : beat_head_item.col_base;
    assign hazard_chk_col_count = hazard_issue_fire_q ? active_beat_q.num_cols  : beat_head_item.num_cols;
    assign hazard_chk_tag       = hazard_issue_fire_q ? active_beat_q.tag       : beat_head_item.tag;

    // Validate region allocation, owner permission, and tile bounds
    function automatic logic check_st_permitted(
        input tmem_region_entry_t reg_entry,
        input st_beat_t           b
    );
        logic [8:0]  eff_rows;
        logic [10:0] eff_cols;
        logic [8:0]  row_end;
        logic [10:0] col_end;
        logic [10:0] reg_col_start;
        logic [10:0] reg_cols_eff;
        logic [10:0] reg_col_end;
        logic        owner_ok;
        logic        unused_zero;

        eff_rows      = (b.num_rows == 8'd0) ? 9'd1 : {1'b0, b.num_rows};
        eff_cols      = (b.num_cols == 10'd0) ? 11'd1 : {1'b0, b.num_cols};
        row_end       = {2'b00, b.row_base} + eff_rows;
        col_end       = {2'b00, b.col_base} + eff_cols;
        reg_col_start = {2'b00, reg_entry.col_offset};
        reg_cols_eff  = reg_entry.double_buf_en
                        ? ({1'b0, reg_entry.num_columns} << 1)
                        : {1'b0, reg_entry.num_columns};
        reg_col_end   = reg_col_start + reg_cols_eff;
        owner_ok      = (reg_entry.owner_warp == b.warp_id);
        unused_zero   = &{1'b0, reg_entry, b};

        return !unused_zero &&
               reg_entry.allocated &&
               owner_ok &&
               (row_end <= {1'b0, reg_entry.num_rows}) &&
               ({2'b00, b.col_base} >= reg_col_start) &&
               (col_end <= reg_col_end);
    endfunction

    // Align 32-bit cell data and byte enables into low/high half of 64-bit bank word
    function automatic logic [63:0] pack_cell_data(
        input logic [63:0] raw_data,
        input logic        cell32_mode,
        input logic        half_sel
    );
        if (!cell32_mode) begin
            return raw_data;
        end else if (half_sel) begin
            return {raw_data[31:0], 32'd0};
        end else begin
            return {32'd0, raw_data[31:0]};
        end
    endfunction

    function automatic logic [7:0] pack_cell_be(
        input logic [7:0] raw_be,
        input logic       cell32_mode,
        input logic       half_sel
    );
        if (!cell32_mode) begin
            return raw_be;
        end else if (half_sel) begin
            return {raw_be[3:0], 4'h0};
        end else begin
            return {4'h0, raw_be[3:0]};
        end
    endfunction

    // Store FSM & write beat generator
    always_comb begin
        state_d               = state_q;
        active_beat_d         = active_beat_q;
        cur_row_off_d         = cur_row_off_q;
        cur_col_off_d         = cur_col_off_q;
        stream_active_d       = stream_active_q;

        bank_wr_valid_d       = bank_wr_valid_q;
        bank_wr_row_d         = bank_wr_row_q;
        bank_wr_col_d         = bank_wr_col_q;
        bank_wr_swizzle_d     = bank_wr_swizzle_q;
        bank_wr_data_d        = bank_wr_data_q;
        bank_wr_be_d          = bank_wr_be_q;

        st_ack_valid_d        = st_ack_valid_q;
        st_ack_tag_d          = st_ack_tag_q;
        st_ack_warp_id_d      = st_ack_warp_id_q;
        st_ack_status_d       = st_ack_status_q;

        hazard_issue_fire_d       = 1'b0;
        hazard_issue_region_id_d  = beat_head_item.region_id;
        hazard_issue_warp_id_d    = beat_head_item.warp_id;
        hazard_commit_valid_d     = 1'b0;
        hazard_commit_tag_d       = active_beat_q.tag;
        hazard_commit_region_id_d = active_beat_q.region_id;
        hazard_commit_warp_id_d   = active_beat_q.warp_id;
        st_beats_d                = st_beats_q;
        st_oob_faults_d           = st_oob_faults_q;
        beat_pop                  = 1'b0;

        wr_v_tmp              = '0;
        wr_r_tmp              = '0;
        wr_c_tmp              = '0;
        wr_d_tmp              = '0;
        wr_b_tmp              = '0;
        act_reg_tmp           = region_table_in[active_beat_q.region_id];
        eff_col_base_tmp      = active_beat_q.col_base;
        lane_r_tmp            = 9'd0;
        lane_c_tmp            = 11'd0;
        hs_tmp                = 1'b0;

        if (st_ack_valid_q && st_ack_ready) begin
            st_ack_valid_d = 1'b0;
        end

        next_wr_valid_tmp = bank_wr_valid_q;
        for (int l = 0; l < LANES; ++l) begin
            if (bank_wr_valid_q[l] && bank_wr_ready[l]) begin
                next_wr_valid_tmp[l] = 1'b0;
            end
        end
        bank_wr_valid_d = next_wr_valid_tmp;

        cur_reg_tmp       = region_table_in[beat_head_item.region_id];
        perm_ok_tmp       = check_st_permitted(cur_reg_tmp, beat_head_item) && !beat_head_item.bounds_fault;
        ack_slot_free_tmp = (!st_ack_valid_q || st_ack_ready);

        rem_cols_tmp  = (active_beat_q.num_cols > cur_col_off_q)
                        ? (active_beat_q.num_cols - cur_col_off_q) : 10'd0;
        rem_rows_tmp  = (active_beat_q.num_rows > cur_row_off_q)
                        ? (active_beat_q.num_rows - cur_row_off_q) : 8'd0;
        step_cols_tmp = active_beat_q.col_major
                        ? 10'd1
                        : ((rem_cols_tmp >= 10'(LANES)) ? 10'(LANES) : rem_cols_tmp);
        step_rows_tmp = active_beat_q.col_major
                        ? ((rem_rows_tmp >= 8'(LANES)) ? 8'(LANES) : rem_rows_tmp)
                        : 8'd1;

        if (active_beat_q.col_major) begin
            tile_last_beat_tmp = ((cur_row_off_q + step_rows_tmp) >= active_beat_q.num_rows) &&
                                 ((cur_col_off_q + 10'd1) >= active_beat_q.num_cols);
        end else begin
            tile_last_beat_tmp = ((cur_col_off_q + step_cols_tmp) >= active_beat_q.num_cols) &&
                                 ((cur_row_off_q + 8'd1) >= active_beat_q.num_rows);
        end

        case (state_q)
            ST_IDLE: begin
                if (!beat_q_empty && ack_slot_free_tmp) begin
                    if (!perm_ok_tmp) begin
                        beat_pop        = 1'b1;
                        active_beat_d   = beat_head_item;
                        stream_active_d = 1'b0;
                        state_d         = ST_FAULT;
                        st_oob_faults_d = st_oob_faults_q + 32'd1;
                    end else if (stream_active_q || hazard_allow) begin
                        beat_pop      = 1'b1;
                        active_beat_d = beat_head_item;
                        if (!stream_active_q) begin
                            cur_row_off_d            = 8'd0;
                            cur_col_off_d            = 10'd0;
                            stream_active_d          = 1'b1;
                            hazard_issue_fire_d      = 1'b1;
                            hazard_issue_region_id_d = beat_head_item.region_id;
                            hazard_issue_warp_id_d   = beat_head_item.warp_id;
                        end
                        state_d = ST_ISSUE;
                    end
                end
            end

            ST_ISSUE: begin
                if (bank_wr_valid_q == '0) begin
                    if (act_reg_tmp.double_buf_en && !act_reg_tmp.active_buf &&
                        ({2'b00, active_beat_q.col_base} < ({2'b00, act_reg_tmp.col_offset} + {1'b0, act_reg_tmp.num_columns}))) begin
                        // Store into back buffer when double-buffered and caller targets base offset
                        eff_col_base_tmp = active_beat_q.col_base +
                                           act_reg_tmp.num_columns[TMEM_COL_W-1:0];
                    end

                    for (int l = 0; l < LANES; ++l) begin
                        if (active_beat_q.col_major) begin
                            lane_r_tmp = {2'b00, active_beat_q.row_base} +
                                         {1'b0, cur_row_off_q} + 9'(l);
                            lane_c_tmp = {2'b00, eff_col_base_tmp} + {1'b0, cur_col_off_q};
                            hs_tmp     = tmem_cell_half_sel(lane_c_tmp[TMEM_COL_W-1:0]);
                            if ((({1'b0, cur_row_off_q} + 9'(l)) < {1'b0, active_beat_q.num_rows}) &&
                                (lane_r_tmp < 9'(TMEM_LANES_ROWS)) &&
                                (lane_c_tmp < 11'(TMEM_COLUMNS)) &&
                                (active_beat_q.be[l] != 8'h00)) begin
                                wr_v_tmp[l] = 1'b1;
                                wr_r_tmp[l] = lane_r_tmp[TMEM_ROW_W-1:0];
                                wr_c_tmp[l] = lane_c_tmp[TMEM_COL_W-1:0];
                                wr_d_tmp[l] = pack_cell_data(active_beat_q.data[l],
                                                             active_beat_q.cell32_mode, hs_tmp);
                                wr_b_tmp[l] = pack_cell_be(active_beat_q.be[l],
                                                           active_beat_q.cell32_mode, hs_tmp);
                            end
                        end else begin
                            lane_r_tmp = {2'b00, active_beat_q.row_base} + {1'b0, cur_row_off_q};
                            lane_c_tmp = {2'b00, eff_col_base_tmp} +
                                         {1'b0, cur_col_off_q} + 11'(l);
                            hs_tmp     = tmem_cell_half_sel(lane_c_tmp[TMEM_COL_W-1:0]);
                            if ((({1'b0, cur_col_off_q} + 11'(l)) < {1'b0, active_beat_q.num_cols}) &&
                                (lane_r_tmp < 9'(TMEM_LANES_ROWS)) &&
                                (lane_c_tmp < 11'(TMEM_COLUMNS)) &&
                                (active_beat_q.be[l] != 8'h00)) begin
                                wr_v_tmp[l] = 1'b1;
                                wr_r_tmp[l] = lane_r_tmp[TMEM_ROW_W-1:0];
                                wr_c_tmp[l] = lane_c_tmp[TMEM_COL_W-1:0];
                                wr_d_tmp[l] = pack_cell_data(active_beat_q.data[l],
                                                             active_beat_q.cell32_mode, hs_tmp);
                                wr_b_tmp[l] = pack_cell_be(active_beat_q.be[l],
                                                           active_beat_q.cell32_mode, hs_tmp);
                            end
                        end
                    end

                    bank_wr_valid_d   = wr_v_tmp;
                    bank_wr_row_d     = wr_r_tmp;
                    bank_wr_col_d     = wr_c_tmp;
                    bank_wr_swizzle_d = act_reg_tmp.swizzle;
                    bank_wr_data_d    = wr_d_tmp;
                    bank_wr_be_d      = wr_b_tmp;
                    state_d           = ST_WAIT;
                end
            end

            ST_WAIT: begin
                if (next_wr_valid_tmp == '0) begin
                    st_beats_d = st_beats_q + 32'd1;
                    if (active_beat_q.last || tile_last_beat_tmp) begin
                        st_ack_valid_d            = 1'b1;
                        st_ack_tag_d              = active_beat_q.tag;
                        st_ack_warp_id_d          = active_beat_q.warp_id;
                        st_ack_status_d           = TMEM_STATUS_OK;
                        hazard_commit_valid_d     = 1'b1;
                        hazard_commit_tag_d       = active_beat_q.tag;
                        hazard_commit_region_id_d = active_beat_q.region_id;
                        hazard_commit_warp_id_d   = active_beat_q.warp_id;
                        stream_active_d           = 1'b0;
                        cur_row_off_d             = 8'd0;
                        cur_col_off_d             = 10'd0;
                        state_d                   = ST_IDLE;
                    end else begin
                        if (active_beat_q.col_major) begin
                            if ((cur_row_off_q + step_rows_tmp) >= active_beat_q.num_rows) begin
                                cur_row_off_d = 8'd0;
                                cur_col_off_d = cur_col_off_q + 10'd1;
                            end else begin
                                cur_row_off_d = cur_row_off_q + step_rows_tmp;
                            end
                        end else begin
                            if ((cur_col_off_q + step_cols_tmp) >= active_beat_q.num_cols) begin
                                cur_col_off_d = 10'd0;
                                cur_row_off_d = cur_row_off_q + 8'd1;
                            end else begin
                                cur_col_off_d = cur_col_off_q + step_cols_tmp;
                            end
                        end
                        state_d = ST_IDLE;
                    end
                end
            end

            ST_FAULT: begin
                if (ack_slot_free_tmp) begin
                    st_ack_valid_d   = 1'b1;
                    st_ack_tag_d     = active_beat_q.tag;
                    st_ack_warp_id_d = active_beat_q.warp_id;
                    st_ack_status_d  = TMEM_STATUS_NOT_ALLOCED;
                    state_d          = ST_IDLE;
                end
            end

            default: begin
                state_d = ST_IDLE;
            end
        endcase
    end

    `UNUSED_VAR (act_reg_tmp)

    always_ff @(posedge clk) begin
        if (reset) begin
            beat_q_mem_q          <= '0;
            beat_q_head_q         <= '0;
            beat_q_tail_q         <= '0;
            beat_q_cnt_q          <= '0;

            state_q               <= ST_IDLE;
            active_beat_q         <= '0;
            cur_row_off_q         <= 8'd0;
            cur_col_off_q         <= 10'd0;
            stream_active_q       <= 1'b0;

            bank_wr_valid_q       <= '0;
            bank_wr_row_q         <= '0;
            bank_wr_col_q         <= '0;
            bank_wr_swizzle_q     <= TMEM_SWIZZLE_NONE;
            bank_wr_data_q        <= '0;
            bank_wr_be_q          <= '0;

            st_ack_valid_q        <= 1'b0;
            st_ack_tag_q          <= '0;
            st_ack_warp_id_q      <= '0;
            st_ack_status_q       <= TMEM_STATUS_OK;

            hazard_issue_fire_q       <= 1'b0;
            hazard_issue_region_id_q  <= '0;
            hazard_issue_warp_id_q    <= '0;
            hazard_commit_valid_q     <= 1'b0;
            hazard_commit_tag_q       <= '0;
            hazard_commit_region_id_q <= '0;
            hazard_commit_warp_id_q   <= '0;
            st_beats_q                <= 32'd0;
            st_oob_faults_q           <= 32'd0;
        end else begin
            if (beat_push) begin
                beat_q_mem_q[beat_q_tail_q].tag          <= st_req_tag;
                beat_q_mem_q[beat_q_tail_q].region_id    <= st_req_region_id;
                beat_q_mem_q[beat_q_tail_q].warp_id      <= st_req_warp_id;
                beat_q_mem_q[beat_q_tail_q].row_base     <= st_req_row_base;
                beat_q_mem_q[beat_q_tail_q].col_base     <= st_req_col_base;
                beat_q_mem_q[beat_q_tail_q].num_rows     <= st_req_num_rows;
                beat_q_mem_q[beat_q_tail_q].num_cols     <= st_req_num_cols;
                beat_q_mem_q[beat_q_tail_q].col_major    <= st_req_col_major;
                beat_q_mem_q[beat_q_tail_q].cell32_mode  <= st_req_cell32_mode;
                beat_q_mem_q[beat_q_tail_q].data         <= st_req_data;
                beat_q_mem_q[beat_q_tail_q].be           <= st_req_be;
                beat_q_mem_q[beat_q_tail_q].last         <= st_req_last;
                beat_q_mem_q[beat_q_tail_q].bounds_fault <= bounds_fault_in;
                beat_q_tail_q <= beat_q_tail_q + 1;
            end
            if (beat_pop) begin
                beat_q_head_q <= beat_q_head_q + 1;
            end
            case ({beat_push, beat_pop})
                2'b10:   beat_q_cnt_q <= beat_q_cnt_q + 1;
                2'b01:   beat_q_cnt_q <= beat_q_cnt_q - 1;
                default: beat_q_cnt_q <= beat_q_cnt_q;
            endcase

            state_q               <= state_d;
            active_beat_q         <= active_beat_d;
            cur_row_off_q         <= cur_row_off_d;
            cur_col_off_q         <= cur_col_off_d;
            stream_active_q       <= stream_active_d;

            bank_wr_valid_q       <= bank_wr_valid_d;
            bank_wr_row_q         <= bank_wr_row_d;
            bank_wr_col_q         <= bank_wr_col_d;
            bank_wr_swizzle_q     <= bank_wr_swizzle_d;
            bank_wr_data_q        <= bank_wr_data_d;
            bank_wr_be_q          <= bank_wr_be_d;

            st_ack_valid_q        <= st_ack_valid_d;
            st_ack_tag_q          <= st_ack_tag_d;
            st_ack_warp_id_q      <= st_ack_warp_id_d;
            st_ack_status_q       <= st_ack_status_d;

            hazard_issue_fire_q       <= hazard_issue_fire_d;
            hazard_issue_region_id_q  <= hazard_issue_region_id_d;
            hazard_issue_warp_id_q    <= hazard_issue_warp_id_d;
            hazard_commit_valid_q     <= hazard_commit_valid_d;
            hazard_commit_tag_q       <= hazard_commit_tag_d;
            hazard_commit_region_id_q <= hazard_commit_region_id_d;
            hazard_commit_warp_id_q   <= hazard_commit_warp_id_d;
            st_beats_q                <= st_beats_d;
            st_oob_faults_q           <= st_oob_faults_d;
        end
    end

    assign bank_wr_valid       = bank_wr_valid_q;
    assign bank_wr_row         = bank_wr_row_q;
    assign bank_wr_col         = bank_wr_col_q;
    assign bank_wr_swizzle     = bank_wr_swizzle_q;
    assign bank_wr_data        = bank_wr_data_q;
    assign bank_wr_be          = bank_wr_be_q;

    assign st_ack_valid        = st_ack_valid_q;
    assign st_ack_tag          = st_ack_tag_q;
    assign st_ack_warp_id      = st_ack_warp_id_q;
    assign st_ack_status       = st_ack_status_q;

    assign hazard_issue_fire       = hazard_issue_fire_q;
    assign hazard_issue_region_id  = hazard_issue_region_id_q;
    assign hazard_issue_warp_id    = hazard_issue_warp_id_q;
    assign hazard_commit_valid     = hazard_commit_valid_q;
    assign hazard_commit_tag       = hazard_commit_tag_q;
    assign hazard_commit_region_id = hazard_commit_region_id_q;
    assign hazard_commit_warp_id   = hazard_commit_warp_id_q;
    assign st_beats_out            = st_beats_q;
    assign st_oob_faults_out       = st_oob_faults_q;

endmodule
