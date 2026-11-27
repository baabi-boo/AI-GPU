// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_ld_engine
    import VX_tmem_pkg::*;
#(
    parameter int LANES      = 8,
    parameter int DESC_DEPTH = 4
) (
    input  logic                                clk,
    input  logic                                reset,
    // Incoming tmem.ld descriptor interface
    input  logic                                ld_desc_valid,
    output logic                                ld_desc_ready,
    input  logic [TMEM_TAG_W-1:0]               ld_desc_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_desc_region_id,
    input  logic [4:0]                          ld_desc_warp_id,
    input  logic [TMEM_ROW_W-1:0]               ld_desc_row_base,
    input  logic [TMEM_COL_W-1:0]               ld_desc_col_base,
    input  logic [7:0]                          ld_desc_num_rows,
    input  logic [9:0]                          ld_desc_num_cols,
    input  logic [1:0]                          ld_desc_elem_bytes, // 0:1B, 1:2B, 2:4B, 3:8B
    input  logic                                ld_desc_col_major,
    input  logic [2:0]                          ld_desc_subbyte_shift,
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
    // Arbiter-facing LANES=8 read port requests
    output logic [LANES-1:0]                    bank_rd_valid,
    input  logic [LANES-1:0]                    bank_rd_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_rd_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]    bank_rd_col,
    output tmem_swizzle_e                       bank_rd_swizzle,
    // Bank array read response channel
    input  logic [LANES-1:0]                    bank_rsp_valid,
    input  logic [LANES-1:0][63:0]              bank_rsp_data,
    input  logic [LANES-1:0]                    bank_rsp_ecc_ce,
    input  logic [LANES-1:0]                    bank_rsp_ecc_ue,
    // Reassembled warp/register output channel
    output logic                                ld_rsp_valid,
    input  logic                                ld_rsp_ready,
    output logic [TMEM_TAG_W-1:0]               ld_rsp_tag,
    output logic [4:0]                          ld_rsp_warp_id,
    output tmem_status_e                        ld_rsp_status,
    output logic [LANES-1:0][63:0]              ld_rsp_data,
    output logic [LANES-1:0]                    ld_rsp_lane_mask,
    output logic                                ld_rsp_last,
    output logic                                ld_rsp_ecc_ce,
    output logic                                ld_rsp_ecc_ue,
    // Telemetry
    output logic [31:0]                         ld_beats_out,
    output logic [31:0]                         ld_oob_faults_out
);

    typedef enum logic [1:0] {
        LD_IDLE     = 2'd0,
        LD_ISSUE    = 2'd1,
        LD_WAIT_RSP = 2'd2,
        LD_FAULT    = 2'd3
    } ld_state_e;

    typedef struct packed {
        logic [TMEM_TAG_W-1:0]       tag;
        logic [TMEM_REGION_ID_W-1:0] region_id;
        logic [4:0]                  warp_id;
        logic [TMEM_ROW_W-1:0]       row_base;
        logic [TMEM_COL_W-1:0]       col_base;
        logic [7:0]                  num_rows;
        logic [9:0]                  num_cols;
        logic [1:0]                  elem_bytes;
        logic                        col_major;
        logic [2:0]                  subbyte_shift;
        logic                        bounds_fault;
    } ld_desc_t;

    // Small descriptor input queue
    ld_desc_t [DESC_DEPTH-1:0]          desc_q_mem_q;
    logic [$clog2(DESC_DEPTH)-1:0]      desc_q_head_q, desc_q_tail_q;
    logic [$clog2(DESC_DEPTH+1)-1:0]    desc_q_cnt_q;

    ld_state_e                          state_q, state_d;
    ld_desc_t                           active_desc_q, active_desc_d;
    logic [7:0]                         cur_row_off_q, cur_row_off_d;
    logic [9:0]                         cur_col_off_q, cur_col_off_d;
    logic [LANES-1:0]                   pending_lanes_q, pending_lanes_d;
    logic [LANES-1:0]                   beat_lane_mask_q, beat_lane_mask_d;
    logic [LANES-1:0][63:0]             rsp_accum_data_q, rsp_accum_data_d;
    logic [LANES-1:0]                   rsp_half_sel_q, rsp_half_sel_d;
    logic                               rsp_ecc_ce_q, rsp_ecc_ce_d;
    logic                               rsp_ecc_ue_q, rsp_ecc_ue_d;

    // Registered output channels
    logic [LANES-1:0]                   bank_rd_valid_q, bank_rd_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   bank_rd_row_q, bank_rd_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0]   bank_rd_col_q, bank_rd_col_d;
    tmem_swizzle_e                      bank_rd_swizzle_q, bank_rd_swizzle_d;

    logic                               ld_rsp_valid_q, ld_rsp_valid_d;
    logic [TMEM_TAG_W-1:0]              ld_rsp_tag_q, ld_rsp_tag_d;
    logic [4:0]                         ld_rsp_warp_id_q, ld_rsp_warp_id_d;
    tmem_status_e                       ld_rsp_status_q, ld_rsp_status_d;
    logic [LANES-1:0][63:0]             ld_rsp_data_q, ld_rsp_data_d;
    logic [LANES-1:0]                   ld_rsp_lane_mask_q, ld_rsp_lane_mask_d;
    logic                               ld_rsp_last_q, ld_rsp_last_d;
    logic                               ld_rsp_ecc_ce_q, ld_rsp_ecc_ce_d;
    logic                               ld_rsp_ecc_ue_q, ld_rsp_ecc_ue_d;

    logic                               hazard_issue_fire_q, hazard_issue_fire_d;
    logic [TMEM_REGION_ID_W-1:0]        hazard_issue_region_id_q, hazard_issue_region_id_d;
    logic [4:0]                         hazard_issue_warp_id_q, hazard_issue_warp_id_d;
    logic                               hazard_commit_valid_q, hazard_commit_valid_d;
    logic [TMEM_TAG_W-1:0]              hazard_commit_tag_q, hazard_commit_tag_d;
    logic [TMEM_REGION_ID_W-1:0]        hazard_commit_region_id_q, hazard_commit_region_id_d;
    logic [4:0]                         hazard_commit_warp_id_q, hazard_commit_warp_id_d;
    logic [31:0]                        ld_beats_q, ld_beats_d;
    logic [31:0]                        ld_oob_faults_q, ld_oob_faults_d;

    logic                               desc_q_empty;
    logic                               desc_q_full;
    logic                               desc_pop;
    logic                               desc_push;
    ld_desc_t                           desc_head_item;

    logic [9:0]                         rem_cols_tmp;
    logic [7:0]                         rem_rows_tmp;
    logic [9:0]                         step_cols_tmp;
    logic [7:0]                         step_rows_tmp;
    logic                               beat_is_last_tmp;
    tmem_region_entry_t                 cur_reg_tmp;
    logic                               reg_bounds_ok_tmp;
    logic                               next_beat_ready_tmp;
    logic [LANES-1:0]                   req_v_tmp;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   req_r_tmp;
    logic [LANES-1:0][TMEM_COL_W-1:0]   req_c_tmp;
    logic [LANES-1:0]                   req_hs_tmp;
    tmem_region_entry_t                 act_reg_tmp;
    logic [TMEM_COL_W-1:0]              eff_col_base_tmp;
    logic [8:0]                         lane_r_tmp;
    logic [10:0]                        lane_c_tmp;
    logic [LANES-1:0]                   next_pending_tmp;

    assign desc_q_empty   = (desc_q_cnt_q == '0);
    assign desc_q_full    = (desc_q_cnt_q == ($clog2(DESC_DEPTH+1))'(DESC_DEPTH));
    assign ld_desc_ready  = !desc_q_full && !reset;
    assign desc_push      = ld_desc_valid && ld_desc_ready;
    assign desc_head_item = desc_q_mem_q[desc_q_head_q];

    assign hazard_chk_valid     = !desc_q_empty && (state_q == LD_IDLE);
    assign hazard_chk_region_id = hazard_issue_fire_q ? active_desc_q.region_id : desc_head_item.region_id;
    assign hazard_chk_col_start = hazard_issue_fire_q ? active_desc_q.col_base  : desc_head_item.col_base;
    assign hazard_chk_col_count = hazard_issue_fire_q ? active_desc_q.num_cols  : desc_head_item.num_cols;
    assign hazard_chk_tag       = hazard_issue_fire_q ? active_desc_q.tag       : desc_head_item.tag;

    // Sub-word / byte-lane extraction helper from 64-bit bank response
    function automatic logic [63:0] extract_lane_word(
        input logic [63:0] raw_word,
        input logic        half_sel,
        input logic [1:0]  elem_bytes,
        input logic [2:0]  subbyte_shift
    );
        logic [63:0] shifted;
        logic [31:0] half32;
        half32  = half_sel ? raw_word[63:32] : raw_word[31:0];
        shifted = raw_word >> ({3'd0, subbyte_shift} * 6'd8);
        case (elem_bytes)
            2'd0:    return {56'd0, shifted[7:0]};
            2'd1:    return {48'd0, shifted[15:0]};
            2'd2:    return {32'd0, half32};
            default: return raw_word ^ (shifted & 64'd0);
        endcase
    endfunction

    // Check descriptor bounds against live region table
    function automatic logic check_desc_in_region(
        input tmem_region_entry_t reg_entry,
        input ld_desc_t           d
    );
        logic [8:0]  eff_rows;
        logic [10:0] eff_cols;
        logic [8:0]  row_end;
        logic [10:0] col_end;
        logic [10:0] reg_col_start;
        logic [10:0] reg_cols_eff;
        logic [10:0] reg_col_end;
        logic        unused_zero;

        eff_rows      = (d.num_rows == 8'd0) ? 9'd1 : {1'b0, d.num_rows};
        eff_cols      = (d.num_cols == 10'd0) ? 11'd1 : {1'b0, d.num_cols};
        row_end       = {2'b00, d.row_base} + eff_rows;
        col_end       = {2'b00, d.col_base} + eff_cols;
        reg_col_start = {2'b00, reg_entry.col_offset};
        reg_cols_eff  = reg_entry.double_buf_en
                        ? ({1'b0, reg_entry.num_columns} << 1)
                        : {1'b0, reg_entry.num_columns};
        reg_col_end   = reg_col_start + reg_cols_eff;
        unused_zero   = &{1'b0, reg_entry, d};

        return !unused_zero &&
               reg_entry.allocated &&
               (row_end <= {1'b0, reg_entry.num_rows}) &&
               ({2'b00, d.col_base} >= reg_col_start) &&
               (col_end <= reg_col_end);
    endfunction

    // Compute beat step sizes and whether current beat completes the tile
    always_comb begin
        state_d               = state_q;
        active_desc_d         = active_desc_q;
        cur_row_off_d         = cur_row_off_q;
        cur_col_off_d         = cur_col_off_q;
        pending_lanes_d       = pending_lanes_q;
        beat_lane_mask_d      = beat_lane_mask_q;
        rsp_accum_data_d      = rsp_accum_data_q;
        rsp_half_sel_d        = rsp_half_sel_q;
        rsp_ecc_ce_d          = rsp_ecc_ce_q;
        rsp_ecc_ue_d          = rsp_ecc_ue_q;

        bank_rd_valid_d       = bank_rd_valid_q;
        bank_rd_row_d         = bank_rd_row_q;
        bank_rd_col_d         = bank_rd_col_q;
        bank_rd_swizzle_d     = bank_rd_swizzle_q;

        ld_rsp_valid_d        = ld_rsp_valid_q;
        ld_rsp_tag_d          = ld_rsp_tag_q;
        ld_rsp_warp_id_d      = ld_rsp_warp_id_q;
        ld_rsp_status_d       = ld_rsp_status_q;
        ld_rsp_data_d         = ld_rsp_data_q;
        ld_rsp_lane_mask_d    = ld_rsp_lane_mask_q;
        ld_rsp_last_d         = ld_rsp_last_q;
        ld_rsp_ecc_ce_d       = ld_rsp_ecc_ce_q;
        ld_rsp_ecc_ue_d       = ld_rsp_ecc_ue_q;

        hazard_issue_fire_d      = 1'b0;
        hazard_issue_region_id_d = desc_head_item.region_id;
        hazard_issue_warp_id_d   = desc_head_item.warp_id;
        hazard_commit_valid_d    = 1'b0;
        hazard_commit_tag_d      = active_desc_q.tag;
        hazard_commit_region_id_d = active_desc_q.region_id;
        hazard_commit_warp_id_d   = active_desc_q.warp_id;
        ld_beats_d               = ld_beats_q;
        ld_oob_faults_d          = ld_oob_faults_q;
        desc_pop                 = 1'b0;

        req_v_tmp             = '0;
        req_r_tmp             = '0;
        req_c_tmp             = '0;
        req_hs_tmp            = '0;
        act_reg_tmp           = region_table_in[active_desc_q.region_id];
        eff_col_base_tmp      = active_desc_q.col_base;
        lane_r_tmp            = 9'd0;
        lane_c_tmp            = 11'd0;
        next_pending_tmp      = pending_lanes_q;

        // Clear consumed output response
        if (ld_rsp_valid_q && ld_rsp_ready) begin
            ld_rsp_valid_d = 1'b0;
        end

        // Clear accepted read request lanes
        for (int l = 0; l < LANES; ++l) begin
            if (bank_rd_valid_q[l] && bank_rd_ready[l]) begin
                bank_rd_valid_d[l] = 1'b0;
            end
        end

        cur_reg_tmp       = region_table_in[desc_head_item.region_id];
        reg_bounds_ok_tmp = check_desc_in_region(cur_reg_tmp, desc_head_item) && !desc_head_item.bounds_fault;

        rem_cols_tmp     = (active_desc_q.num_cols > cur_col_off_q)
                           ? (active_desc_q.num_cols - cur_col_off_q) : 10'd0;
        rem_rows_tmp     = (active_desc_q.num_rows > cur_row_off_q)
                           ? (active_desc_q.num_rows - cur_row_off_q) : 8'd0;
        step_cols_tmp    = active_desc_q.col_major
                           ? 10'd1
                           : ((rem_cols_tmp >= 10'(LANES)) ? 10'(LANES) : rem_cols_tmp);
        step_rows_tmp    = active_desc_q.col_major
                           ? ((rem_rows_tmp >= 8'(LANES)) ? 8'(LANES) : rem_rows_tmp)
                           : 8'd1;

        if (active_desc_q.col_major) begin
            beat_is_last_tmp = ((cur_row_off_q + step_rows_tmp) >= active_desc_q.num_rows) &&
                               ((cur_col_off_q + 10'd1) >= active_desc_q.num_cols);
        end else begin
            beat_is_last_tmp = ((cur_col_off_q + step_cols_tmp) >= active_desc_q.num_cols) &&
                               ((cur_row_off_q + 8'd1) >= active_desc_q.num_rows);
        end

        next_beat_ready_tmp = (!ld_rsp_valid_q || ld_rsp_ready);

        case (state_q)
            LD_IDLE: begin
                if (!desc_q_empty && next_beat_ready_tmp) begin
                    if (!reg_bounds_ok_tmp) begin
                        desc_pop        = 1'b1;
                        active_desc_d   = desc_head_item;
                        state_d         = LD_FAULT;
                        ld_oob_faults_d = ld_oob_faults_q + 32'd1;
                    end else if (hazard_allow) begin
                        desc_pop                 = 1'b1;
                        active_desc_d            = desc_head_item;
                        cur_row_off_d            = 8'd0;
                        cur_col_off_d            = 10'd0;
                        hazard_issue_fire_d      = 1'b1;
                        hazard_issue_region_id_d = desc_head_item.region_id;
                        hazard_issue_warp_id_d   = desc_head_item.warp_id;
                        state_d                  = LD_ISSUE;
                    end
                end
            end

            LD_ISSUE: begin
                if ((~|bank_rd_valid_q) && next_beat_ready_tmp) begin
                    if (act_reg_tmp.double_buf_en && act_reg_tmp.active_buf &&
                        ({2'b00, active_desc_q.col_base} < ({2'b00, act_reg_tmp.col_offset} + {1'b0, act_reg_tmp.num_columns}))) begin
                        eff_col_base_tmp = active_desc_q.col_base +
                                           act_reg_tmp.num_columns[TMEM_COL_W-1:0];
                    end

                    for (int l = 0; l < LANES; ++l) begin
                        if (active_desc_q.col_major) begin
                            lane_r_tmp = {2'b00, active_desc_q.row_base} +
                                         {1'b0, cur_row_off_q} + 9'(l);
                            lane_c_tmp = {2'b00, eff_col_base_tmp} + {1'b0, cur_col_off_q};
                            if ((({1'b0, cur_row_off_q} + 9'(l)) < {1'b0, active_desc_q.num_rows}) &&
                                (lane_r_tmp < 9'(TMEM_LANES_ROWS)) &&
                                (lane_c_tmp < 11'(TMEM_COLUMNS))) begin
                                req_v_tmp[l]  = 1'b1;
                                req_r_tmp[l]  = lane_r_tmp[TMEM_ROW_W-1:0];
                                req_c_tmp[l]  = lane_c_tmp[TMEM_COL_W-1:0];
                                req_hs_tmp[l] = tmem_cell_half_sel(lane_c_tmp[TMEM_COL_W-1:0]);
                            end
                        end else begin
                            lane_r_tmp = {2'b00, active_desc_q.row_base} + {1'b0, cur_row_off_q};
                            lane_c_tmp = {2'b00, eff_col_base_tmp} +
                                         {1'b0, cur_col_off_q} + 11'(l);
                            if ((({1'b0, cur_col_off_q} + 11'(l)) < {1'b0, active_desc_q.num_cols}) &&
                                (lane_r_tmp < 9'(TMEM_LANES_ROWS)) &&
                                (lane_c_tmp < 11'(TMEM_COLUMNS))) begin
                                req_v_tmp[l]  = 1'b1;
                                req_r_tmp[l]  = lane_r_tmp[TMEM_ROW_W-1:0];
                                req_c_tmp[l]  = lane_c_tmp[TMEM_COL_W-1:0];
                                req_hs_tmp[l] = tmem_cell_half_sel(lane_c_tmp[TMEM_COL_W-1:0]);
                            end
                        end
                    end

                    bank_rd_valid_d   = req_v_tmp;
                    bank_rd_row_d     = req_r_tmp;
                    bank_rd_col_d     = req_c_tmp;
                    bank_rd_swizzle_d = act_reg_tmp.swizzle;
                    pending_lanes_d   = req_v_tmp;
                    beat_lane_mask_d  = req_v_tmp;
                    rsp_half_sel_d    = req_hs_tmp;
                    rsp_accum_data_d  = '0;
                    rsp_ecc_ce_d      = 1'b0;
                    rsp_ecc_ue_d      = 1'b0;
                    state_d           = LD_WAIT_RSP;
                end
            end

            LD_WAIT_RSP: begin
                next_pending_tmp = pending_lanes_q;
                for (int l = 0; l < LANES; ++l) begin
                    if (pending_lanes_q[l] && bank_rsp_valid[l]) begin
                        next_pending_tmp[l] = 1'b0;
                        rsp_accum_data_d[l] = extract_lane_word(
                            bank_rsp_data[l],
                            rsp_half_sel_q[l],
                            active_desc_q.elem_bytes,
                            active_desc_q.subbyte_shift
                        );
                        rsp_ecc_ce_d = rsp_ecc_ce_d | bank_rsp_ecc_ce[l];
                        rsp_ecc_ue_d = rsp_ecc_ue_d | bank_rsp_ecc_ue[l];
                    end
                end
                pending_lanes_d = next_pending_tmp;

                if (next_pending_tmp == '0) begin
                    ld_rsp_valid_d     = 1'b1;
                    ld_rsp_tag_d       = active_desc_q.tag;
                    ld_rsp_warp_id_d   = active_desc_q.warp_id;
                    ld_rsp_status_d    = rsp_ecc_ue_d ? TMEM_STATUS_ECC_UE : TMEM_STATUS_OK;
                    ld_rsp_data_d      = rsp_accum_data_d;
                    ld_rsp_lane_mask_d = beat_lane_mask_q;
                    ld_rsp_last_d      = beat_is_last_tmp;
                    ld_rsp_ecc_ce_d    = rsp_ecc_ce_d;
                    ld_rsp_ecc_ue_d    = rsp_ecc_ue_d;
                    ld_beats_d         = ld_beats_q + 32'd1;

                    if (beat_is_last_tmp) begin
                        hazard_commit_valid_d     = 1'b1;
                        hazard_commit_tag_d       = active_desc_q.tag;
                        hazard_commit_region_id_d = active_desc_q.region_id;
                        hazard_commit_warp_id_d   = active_desc_q.warp_id;
                        state_d                   = LD_IDLE;
                    end else begin
                        if (active_desc_q.col_major) begin
                            if ((cur_row_off_q + step_rows_tmp) >= active_desc_q.num_rows) begin
                                cur_row_off_d = 8'd0;
                                cur_col_off_d = cur_col_off_q + 10'd1;
                            end else begin
                                cur_row_off_d = cur_row_off_q + step_rows_tmp;
                            end
                        end else begin
                            if ((cur_col_off_q + step_cols_tmp) >= active_desc_q.num_cols) begin
                                cur_col_off_d = 10'd0;
                                cur_row_off_d = cur_row_off_q + 8'd1;
                            end else begin
                                cur_col_off_d = cur_col_off_q + step_cols_tmp;
                            end
                        end
                        state_d = LD_ISSUE;
                    end
                end
            end

            LD_FAULT: begin
                if (next_beat_ready_tmp) begin
                    ld_rsp_valid_d     = 1'b1;
                    ld_rsp_tag_d       = active_desc_q.tag;
                    ld_rsp_warp_id_d   = active_desc_q.warp_id;
                    ld_rsp_status_d    = TMEM_STATUS_NOT_ALLOCED;
                    ld_rsp_data_d      = '0;
                    ld_rsp_lane_mask_d = '0;
                    ld_rsp_last_d      = 1'b1;
                    ld_rsp_ecc_ce_d    = 1'b0;
                    ld_rsp_ecc_ue_d    = 1'b0;
                    state_d            = LD_IDLE;
                end
            end

            default: begin
                state_d = LD_IDLE;
            end
        endcase
    end

    `UNUSED_VAR (act_reg_tmp)

    // Descriptor FIFO & FSM state registers
    always_ff @(posedge clk) begin
        if (reset) begin
            desc_q_mem_q          <= '0;
            desc_q_head_q         <= '0;
            desc_q_tail_q         <= '0;
            desc_q_cnt_q          <= '0;

            state_q               <= LD_IDLE;
            active_desc_q         <= '0;
            cur_row_off_q         <= 8'd0;
            cur_col_off_q         <= 10'd0;
            pending_lanes_q       <= '0;
            beat_lane_mask_q      <= '0;
            rsp_accum_data_q      <= '0;
            rsp_half_sel_q        <= '0;
            rsp_ecc_ce_q          <= 1'b0;
            rsp_ecc_ue_q          <= 1'b0;

            bank_rd_valid_q       <= '0;
            bank_rd_row_q         <= '0;
            bank_rd_col_q         <= '0;
            bank_rd_swizzle_q     <= TMEM_SWIZZLE_NONE;

            ld_rsp_valid_q        <= 1'b0;
            ld_rsp_tag_q          <= '0;
            ld_rsp_warp_id_q      <= '0;
            ld_rsp_status_q       <= TMEM_STATUS_OK;
            ld_rsp_data_q         <= '0;
            ld_rsp_lane_mask_q    <= '0;
            ld_rsp_last_q         <= 1'b0;
            ld_rsp_ecc_ce_q       <= 1'b0;
            ld_rsp_ecc_ue_q       <= 1'b0;

            hazard_issue_fire_q      <= 1'b0;
            hazard_issue_region_id_q <= '0;
            hazard_issue_warp_id_q   <= '0;
            hazard_commit_valid_q    <= 1'b0;
            hazard_commit_tag_q      <= '0;
            hazard_commit_region_id_q <= '0;
            hazard_commit_warp_id_q   <= '0;
            ld_beats_q               <= 32'd0;
            ld_oob_faults_q          <= 32'd0;
        end else begin
            if (desc_push) begin
                desc_q_mem_q[desc_q_tail_q].tag           <= ld_desc_tag;
                desc_q_mem_q[desc_q_tail_q].region_id     <= ld_desc_region_id;
                desc_q_mem_q[desc_q_tail_q].warp_id       <= ld_desc_warp_id;
                desc_q_mem_q[desc_q_tail_q].row_base      <= ld_desc_row_base;
                desc_q_mem_q[desc_q_tail_q].col_base      <= ld_desc_col_base;
                desc_q_mem_q[desc_q_tail_q].num_rows      <= ld_desc_num_rows;
                desc_q_mem_q[desc_q_tail_q].num_cols      <= ld_desc_num_cols;
                desc_q_mem_q[desc_q_tail_q].elem_bytes    <= ld_desc_elem_bytes;
                desc_q_mem_q[desc_q_tail_q].col_major     <= ld_desc_col_major;
                desc_q_mem_q[desc_q_tail_q].subbyte_shift <= ld_desc_subbyte_shift;
                desc_q_mem_q[desc_q_tail_q].bounds_fault  <= bounds_fault_in;
                desc_q_tail_q <= desc_q_tail_q + 1;
            end
            if (desc_pop) begin
                desc_q_head_q <= desc_q_head_q + 1;
            end
            case ({desc_push, desc_pop})
                2'b10:   desc_q_cnt_q <= desc_q_cnt_q + 1;
                2'b01:   desc_q_cnt_q <= desc_q_cnt_q - 1;
                default: desc_q_cnt_q <= desc_q_cnt_q;
            endcase

            state_q               <= state_d;
            active_desc_q         <= active_desc_d;
            cur_row_off_q         <= cur_row_off_d;
            cur_col_off_q         <= cur_col_off_d;
            pending_lanes_q       <= pending_lanes_d;
            beat_lane_mask_q      <= beat_lane_mask_d;
            rsp_accum_data_q      <= rsp_accum_data_d;
            rsp_half_sel_q        <= rsp_half_sel_d;
            rsp_ecc_ce_q          <= rsp_ecc_ce_d;
            rsp_ecc_ue_q          <= rsp_ecc_ue_d;

            bank_rd_valid_q       <= bank_rd_valid_d;
            bank_rd_row_q         <= bank_rd_row_d;
            bank_rd_col_q         <= bank_rd_col_d;
            bank_rd_swizzle_q     <= bank_rd_swizzle_d;

            ld_rsp_valid_q        <= ld_rsp_valid_d;
            ld_rsp_tag_q          <= ld_rsp_tag_d;
            ld_rsp_warp_id_q      <= ld_rsp_warp_id_d;
            ld_rsp_status_q       <= ld_rsp_status_d;
            ld_rsp_data_q         <= ld_rsp_data_d;
            ld_rsp_lane_mask_q    <= ld_rsp_lane_mask_d;
            ld_rsp_last_q         <= ld_rsp_last_d;
            ld_rsp_ecc_ce_q       <= ld_rsp_ecc_ce_d;
            ld_rsp_ecc_ue_q       <= ld_rsp_ecc_ue_d;

            hazard_issue_fire_q       <= hazard_issue_fire_d;
            hazard_issue_region_id_q  <= hazard_issue_region_id_d;
            hazard_issue_warp_id_q    <= hazard_issue_warp_id_d;
            hazard_commit_valid_q     <= hazard_commit_valid_d;
            hazard_commit_tag_q       <= hazard_commit_tag_d;
            hazard_commit_region_id_q <= hazard_commit_region_id_d;
            hazard_commit_warp_id_q   <= hazard_commit_warp_id_d;
            ld_beats_q                <= ld_beats_d;
            ld_oob_faults_q           <= ld_oob_faults_d;
        end
    end

    assign bank_rd_valid       = bank_rd_valid_q;
    assign bank_rd_row         = bank_rd_row_q;
    assign bank_rd_col         = bank_rd_col_q;
    assign bank_rd_swizzle     = bank_rd_swizzle_q;

    assign ld_rsp_valid        = ld_rsp_valid_q;
    assign ld_rsp_tag          = ld_rsp_tag_q;
    assign ld_rsp_warp_id      = ld_rsp_warp_id_q;
    assign ld_rsp_status       = ld_rsp_status_q;
    assign ld_rsp_data         = ld_rsp_data_q;
    assign ld_rsp_lane_mask    = ld_rsp_lane_mask_q;
    assign ld_rsp_last         = ld_rsp_last_q;
    assign ld_rsp_ecc_ce       = ld_rsp_ecc_ce_q;
    assign ld_rsp_ecc_ue       = ld_rsp_ecc_ue_q;

    assign hazard_issue_fire       = hazard_issue_fire_q;
    assign hazard_issue_region_id  = hazard_issue_region_id_q;
    assign hazard_issue_warp_id    = hazard_issue_warp_id_q;
    assign hazard_commit_valid     = hazard_commit_valid_q;
    assign hazard_commit_tag       = hazard_commit_tag_q;
    assign hazard_commit_region_id = hazard_commit_region_id_q;
    assign hazard_commit_warp_id   = hazard_commit_warp_id_q;
    assign ld_beats_out            = ld_beats_q;
    assign ld_oob_faults_out       = ld_oob_faults_q;

endmodule
