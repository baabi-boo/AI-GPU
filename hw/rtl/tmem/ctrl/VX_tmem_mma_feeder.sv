// SPDX-License-Identifier: Apache-2.0
module VX_tmem_mma_feeder
    import VX_tmem_pkg::*;
#(
    parameter int LANES = 8
) (
    input  logic                                clk,
    input  logic                                reset,
    // Incoming MMA TMEM operand / drain request (MMA_RD_A, MMA_RD_B, MMA_RD_C, MMA_WR_D)
    input  logic                                mma_req_valid,
    output logic                                mma_req_ready,
    input  tmem_op_e                            mma_req_op,
    input  logic [TMEM_TAG_W-1:0]               mma_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         mma_req_region_id,
    input  logic [4:0]                          mma_req_warp_id,
    input  logic [TMEM_ROW_W-1:0]               mma_req_row,
    input  logic [TMEM_COL_W-1:0]               mma_req_col,
    input  tmem_swizzle_e                       mma_req_swizzle,
    input  logic [7:0]                          mma_req_col_count,
    input  logic                                mma_req_ping_pong_sel,
    input  logic [LANES-1:0][63:0]              mma_req_wr_data,
    input  logic [LANES-1:0][7:0]               mma_req_wr_be,
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
    output logic                                hazard_chk_is_write,
    output logic [TMEM_REGION_ID_W-1:0]         hazard_chk_region_id,
    output logic [TMEM_COL_W-1:0]               hazard_chk_col_start,
    output logic [9:0]                          hazard_chk_col_count,
    output logic [TMEM_TAG_W-1:0]               hazard_chk_tag,
    // Arbiter-facing Read Port A (MMA_RD_A)
    output logic [LANES-1:0]                    bank_rda_valid,
    input  logic [LANES-1:0]                    bank_rda_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_rda_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]    bank_rda_col,
    output tmem_swizzle_e                       bank_rda_swizzle,
    // Arbiter-facing Read Port B (MMA_RD_B / MMA_RD_C)
    output logic [LANES-1:0]                    bank_rdb_valid,
    input  logic [LANES-1:0]                    bank_rdb_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_rdb_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]    bank_rdb_col,
    output tmem_swizzle_e                       bank_rdb_swizzle,
    // Arbiter-facing Write Port (MMA_WR_D)
    output logic [LANES-1:0]                    bank_wr_valid,
    input  logic [LANES-1:0]                    bank_wr_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]    bank_wr_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]    bank_wr_col,
    output tmem_swizzle_e                       bank_wr_swizzle,
    output logic [LANES-1:0][63:0]              bank_wr_data,
    output logic [LANES-1:0][7:0]               bank_wr_be,
    // Bank Array Read Responses
    input  logic [LANES-1:0]                    bank_rda_rsp_valid,
    input  logic [LANES-1:0][63:0]              bank_rda_rsp_data,
    input  logic [LANES-1:0]                    bank_rda_ecc_ce,
    input  logic [LANES-1:0]                    bank_rda_ecc_ue,
    input  logic [LANES-1:0]                    bank_rdb_rsp_valid,
    input  logic [LANES-1:0][63:0]              bank_rdb_rsp_data,
    input  logic [LANES-1:0]                    bank_rdb_ecc_ce,
    input  logic [LANES-1:0]                    bank_rdb_ecc_ue,
    // MMA response / completion output (registered)
    output logic                                mma_rsp_valid,
    input  logic                                mma_rsp_ready,
    output tmem_op_e                            mma_rsp_op,
    output logic [TMEM_TAG_W-1:0]               mma_rsp_tag,
    output tmem_status_e                        mma_rsp_status,
    output logic [LANES-1:0][63:0]              mma_rsp_data,
    output logic [LANES-1:0]                    mma_rsp_lane_mask,
    output logic                                mma_rsp_ecc_ce,
    output logic                                mma_rsp_ecc_ue,
    // Double-buffer ping-pong & telemetry
    output logic [TMEM_MAX_REGIONS-1:0]         ping_pong_ptr_out,
    output logic [31:0]                         mma_rd_beats_out,
    output logic [31:0]                         mma_wr_beats_out
);

    typedef enum logic [2:0] {
        MMA_IDLE      = 3'd0,
        MMA_ISSUE_RDA = 3'd1,
        MMA_WAIT_RDA  = 3'd2,
        MMA_ISSUE_RDB = 3'd3,
        MMA_WAIT_RDB  = 3'd4,
        MMA_ISSUE_WR  = 3'd5,
        MMA_WAIT_WR   = 3'd6,
        MMA_FAULT     = 3'd7
    } mma_state_e;

    typedef struct packed {
        tmem_op_e                    op;
        logic [TMEM_TAG_W-1:0]       tag;
        logic [TMEM_REGION_ID_W-1:0] region_id;
        logic [4:0]                  warp_id;
        logic [TMEM_ROW_W-1:0]       row;
        logic [TMEM_COL_W-1:0]       col;
        tmem_swizzle_e               swizzle;
        logic [7:0]                  col_count;
        logic                        ping_pong_sel;
        logic [LANES-1:0][63:0]      wr_data;
        logic [LANES-1:0][7:0]       wr_be;
    } mma_req_latched_t;

    mma_state_e                         state_q, state_d;
    mma_req_latched_t                   req_q, req_d;
    logic [TMEM_MAX_REGIONS-1:0]        ping_pong_ptr_q, ping_pong_ptr_d;
    logic [LANES-1:0]                   pending_lanes_q, pending_lanes_d;
    logic [LANES-1:0]                   beat_lane_mask_q, beat_lane_mask_d;
    logic [LANES-1:0][63:0]             rsp_buf_q, rsp_buf_d;
    logic                               rsp_ce_q, rsp_ce_d;
    logic                               rsp_ue_q, rsp_ue_d;

    logic [LANES-1:0]                   bank_rda_valid_q, bank_rda_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   bank_rda_row_q, bank_rda_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0]   bank_rda_col_q, bank_rda_col_d;
    tmem_swizzle_e                      bank_rda_swizzle_q, bank_rda_swizzle_d;

    logic [LANES-1:0]                   bank_rdb_valid_q, bank_rdb_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   bank_rdb_row_q, bank_rdb_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0]   bank_rdb_col_q, bank_rdb_col_d;
    tmem_swizzle_e                      bank_rdb_swizzle_q, bank_rdb_swizzle_d;

    logic [LANES-1:0]                   bank_wr_valid_q, bank_wr_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   bank_wr_row_q, bank_wr_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0]   bank_wr_col_q, bank_wr_col_d;
    tmem_swizzle_e                      bank_wr_swizzle_q, bank_wr_swizzle_d;
    logic [LANES-1:0][63:0]             bank_wr_data_q, bank_wr_data_d;
    logic [LANES-1:0][7:0]              bank_wr_be_q, bank_wr_be_d;

    logic                               mma_rsp_valid_q, mma_rsp_valid_d;
    tmem_op_e                           mma_rsp_op_q, mma_rsp_op_d;
    logic [TMEM_TAG_W-1:0]              mma_rsp_tag_q, mma_rsp_tag_d;
    tmem_status_e                       mma_rsp_status_q, mma_rsp_status_d;
    logic [LANES-1:0][63:0]             mma_rsp_data_q, mma_rsp_data_d;
    logic [LANES-1:0]                   mma_rsp_lane_mask_q, mma_rsp_lane_mask_d;
    logic                               mma_rsp_ecc_ce_q, mma_rsp_ecc_ce_d;
    logic                               mma_rsp_ecc_ue_q, mma_rsp_ecc_ue_d;

    logic                               hazard_issue_fire_q, hazard_issue_fire_d;
    logic [TMEM_REGION_ID_W-1:0]        hazard_issue_region_id_q, hazard_issue_region_id_d;
    logic [4:0]                         hazard_issue_warp_id_q, hazard_issue_warp_id_d;
    logic                               hazard_commit_valid_q, hazard_commit_valid_d;
    logic [TMEM_TAG_W-1:0]              hazard_commit_tag_q, hazard_commit_tag_d;
    logic [TMEM_REGION_ID_W-1:0]        hazard_commit_region_id_q, hazard_commit_region_id_d;
    logic [4:0]                         hazard_commit_warp_id_q, hazard_commit_warp_id_d;
    logic [31:0]                        mma_rd_beats_q, mma_rd_beats_d;
    logic [31:0]                        mma_wr_beats_q, mma_wr_beats_d;

    logic                               rsp_slot_free_tmp;
    tmem_region_entry_t                 cur_reg_tmp;
    logic                               req_bounds_ok_tmp;
    logic [LANES-1:0]                   next_rda_valid_tmp;
    logic [LANES-1:0]                   next_rdb_valid_tmp;
    logic [LANES-1:0]                   next_wr_valid_tmp;
    logic [7:0]                         eff_cols_tmp;
    tmem_region_entry_t                 act_reg_tmp;
    logic [TMEM_COL_W-1:0]              base_c_tmp;
    logic [LANES-1:0]                   v_mask_tmp;
    logic [LANES-1:0][TMEM_ROW_W-1:0]   r_vec_tmp;
    logic [LANES-1:0][TMEM_COL_W-1:0]   c_vec_tmp;
    logic [10:0]                        c_ext_tmp;
    logic [LANES-1:0]                   next_p_tmp;

    // Resolve double-buffered effective column coordinate for MMA operand
    function automatic logic [TMEM_COL_W-1:0] resolve_ping_pong_col(
        input tmem_region_entry_t    reg_entry,
        input logic [TMEM_COL_W-1:0] base_col,
        input logic                  ptr_sel
    );
        logic [10:0] sum;
        logic        unused_zero;
        unused_zero = &{1'b0, reg_entry};
        if (!unused_zero && reg_entry.double_buf_en && ptr_sel &&
            ({2'b00, base_col} < ({2'b00, reg_entry.col_offset} + {1'b0, reg_entry.num_columns}))) begin
            sum = {2'b00, base_col} + {1'b0, reg_entry.num_columns};
            return (sum < 11'(TMEM_COLUMNS)) ? sum[TMEM_COL_W-1:0] : base_col;
        end else begin
            return base_col;
        end
    endfunction

    // Validate MMA access against live region table
    function automatic logic mma_req_legal(
        input tmem_region_entry_t    reg_entry,
        input tmem_op_e              op,
        input logic [TMEM_ROW_W-1:0] row,
        input logic [TMEM_COL_W-1:0] col,
        input logic [7:0]            col_cnt
    );
        logic        op_ok;
        logic [10:0] eff_cnt;
        logic [10:0] end_col;
        logic [10:0] reg_start;
        logic [10:0] reg_cols_eff;
        logic [10:0] reg_end;
        logic        unused_zero;

        op_ok = (op == TMEM_OP_MMA_RD_A) || (op == TMEM_OP_MMA_RD_B) ||
                (op == TMEM_OP_MMA_RD_C) || (op == TMEM_OP_MMA_WR_D);
        eff_cnt      = (col_cnt == 8'd0) ? 11'd1 : {3'b000, col_cnt};
        end_col      = {2'b00, col} + eff_cnt;
        reg_start    = {2'b00, reg_entry.col_offset};
        reg_cols_eff = reg_entry.double_buf_en
                       ? ({1'b0, reg_entry.num_columns} << 1)
                       : {1'b0, reg_entry.num_columns};
        reg_end      = reg_start + reg_cols_eff;
        unused_zero  = &{1'b0, reg_entry};

        return !unused_zero && op_ok && reg_entry.allocated &&
               ({1'b0, row} < reg_entry.num_rows) &&
               ({2'b00, col} >= reg_start) &&
               (end_col <= reg_end);
    endfunction

    // Ready to accept new MMA request when idle and response slot is available
    assign mma_req_ready = !reset && (state_q == MMA_IDLE) &&
                           (!mma_rsp_valid_q || mma_rsp_ready) &&
                           hazard_allow;

    assign hazard_chk_valid     = mma_req_valid && (state_q == MMA_IDLE) &&
                                  (!mma_rsp_valid_q || mma_rsp_ready);
    assign hazard_chk_is_write  = hazard_issue_fire_q
                                  ? (req_q.op == TMEM_OP_MMA_WR_D)
                                  : (mma_req_op == TMEM_OP_MMA_WR_D);
    assign hazard_chk_region_id = hazard_issue_fire_q ? req_q.region_id : mma_req_region_id;
    assign hazard_chk_col_start = hazard_issue_fire_q ? req_q.col       : mma_req_col;
    assign hazard_chk_col_count = hazard_issue_fire_q
                                  ? {2'b00, req_q.col_count}
                                  : {2'b00, mma_req_col_count};
    assign hazard_chk_tag       = hazard_issue_fire_q ? req_q.tag       : mma_req_tag;

    // Main MMA feeder & drain FSM
    always_comb begin
        state_d               = state_q;
        req_d                 = req_q;
        ping_pong_ptr_d       = ping_pong_ptr_q;
        pending_lanes_d       = pending_lanes_q;
        beat_lane_mask_d      = beat_lane_mask_q;
        rsp_buf_d             = rsp_buf_q;
        rsp_ce_d              = rsp_ce_q;
        rsp_ue_d              = rsp_ue_q;

        bank_rda_valid_d      = bank_rda_valid_q;
        bank_rda_row_d        = bank_rda_row_q;
        bank_rda_col_d        = bank_rda_col_q;
        bank_rda_swizzle_d    = bank_rda_swizzle_q;

        bank_rdb_valid_d      = bank_rdb_valid_q;
        bank_rdb_row_d        = bank_rdb_row_q;
        bank_rdb_col_d        = bank_rdb_col_q;
        bank_rdb_swizzle_d    = bank_rdb_swizzle_q;

        bank_wr_valid_d       = bank_wr_valid_q;
        bank_wr_row_d         = bank_wr_row_q;
        bank_wr_col_d         = bank_wr_col_q;
        bank_wr_swizzle_d     = bank_wr_swizzle_q;
        bank_wr_data_d        = bank_wr_data_q;
        bank_wr_be_d          = bank_wr_be_q;

        mma_rsp_valid_d       = mma_rsp_valid_q;
        mma_rsp_op_d          = mma_rsp_op_q;
        mma_rsp_tag_d         = mma_rsp_tag_q;
        mma_rsp_status_d      = mma_rsp_status_q;
        mma_rsp_data_d        = mma_rsp_data_q;
        mma_rsp_lane_mask_d   = mma_rsp_lane_mask_q;
        mma_rsp_ecc_ce_d      = mma_rsp_ecc_ce_q;
        mma_rsp_ecc_ue_d      = mma_rsp_ecc_ue_q;

        hazard_issue_fire_d       = 1'b0;
        hazard_issue_region_id_d  = mma_req_region_id;
        hazard_issue_warp_id_d    = mma_req_warp_id;
        hazard_commit_valid_d     = 1'b0;
        hazard_commit_tag_d       = req_q.tag;
        hazard_commit_region_id_d = req_q.region_id;
        hazard_commit_warp_id_d   = req_q.warp_id;
        mma_rd_beats_d            = mma_rd_beats_q;
        mma_wr_beats_d            = mma_wr_beats_q;

        act_reg_tmp           = region_table_in[req_q.region_id];
        base_c_tmp            = '0;
        v_mask_tmp            = '0;
        r_vec_tmp             = '0;
        c_vec_tmp             = '0;
        c_ext_tmp             = 11'd0;
        next_p_tmp            = pending_lanes_q;

        if (mma_rsp_valid_q && mma_rsp_ready) begin
            mma_rsp_valid_d = 1'b0;
        end

        next_rda_valid_tmp = bank_rda_valid_q;
        next_rdb_valid_tmp = bank_rdb_valid_q;
        next_wr_valid_tmp  = bank_wr_valid_q;
        for (int l = 0; l < LANES; ++l) begin
            if (bank_rda_valid_q[l] && bank_rda_ready[l]) begin
                next_rda_valid_tmp[l] = 1'b0;
            end
            if (bank_rdb_valid_q[l] && bank_rdb_ready[l]) begin
                next_rdb_valid_tmp[l] = 1'b0;
            end
            if (bank_wr_valid_q[l] && bank_wr_ready[l]) begin
                next_wr_valid_tmp[l] = 1'b0;
            end
        end
        bank_rda_valid_d = next_rda_valid_tmp;
        bank_rdb_valid_d = next_rdb_valid_tmp;
        bank_wr_valid_d  = next_wr_valid_tmp;

        rsp_slot_free_tmp = (!mma_rsp_valid_q || mma_rsp_ready);
        cur_reg_tmp       = region_table_in[mma_req_region_id];
        req_bounds_ok_tmp = mma_req_legal(cur_reg_tmp, mma_req_op, mma_req_row,
                                          mma_req_col, mma_req_col_count) && !bounds_fault_in;
        eff_cols_tmp      = (req_q.col_count == 8'd0) ? 8'd1 :
                            ((req_q.col_count > 8'(LANES)) ? 8'(LANES) : req_q.col_count);

        case (state_q)
            MMA_IDLE: begin
                if (mma_req_valid && rsp_slot_free_tmp && hazard_allow) begin
                    req_d.op            = mma_req_op;
                    req_d.tag           = mma_req_tag;
                    req_d.region_id     = mma_req_region_id;
                    req_d.warp_id       = mma_req_warp_id;
                    req_d.row           = mma_req_row;
                    req_d.col           = mma_req_col;
                    req_d.swizzle       = mma_req_swizzle;
                    req_d.col_count     = mma_req_col_count;
                    req_d.ping_pong_sel = mma_req_ping_pong_sel;
                    req_d.wr_data       = mma_req_wr_data;
                    req_d.wr_be         = mma_req_wr_be;

                    if (!req_bounds_ok_tmp) begin
                        state_d = MMA_FAULT;
                    end else begin
                        hazard_issue_fire_d                = 1'b1;
                        hazard_issue_region_id_d           = mma_req_region_id;
                        hazard_issue_warp_id_d             = mma_req_warp_id;
                        ping_pong_ptr_d[mma_req_region_id] = mma_req_ping_pong_sel;
                        case (mma_req_op)
                            TMEM_OP_MMA_RD_A: state_d = MMA_ISSUE_RDA;
                            TMEM_OP_MMA_RD_B,
                            TMEM_OP_MMA_RD_C: state_d = MMA_ISSUE_RDB;
                            TMEM_OP_MMA_WR_D: state_d = MMA_ISSUE_WR;
                            default:          state_d = MMA_FAULT;
                        endcase
                    end
                end
            end

            MMA_ISSUE_RDA: begin
                if (bank_rda_valid_q == '0) begin
                    base_c_tmp = resolve_ping_pong_col(act_reg_tmp, req_q.col, req_q.ping_pong_sel);
                    for (int l = 0; l < LANES; ++l) begin
                        if (8'(l) < eff_cols_tmp) begin
                            c_ext_tmp = {2'b00, base_c_tmp} + 11'(l);
                            if (c_ext_tmp < 11'(TMEM_COLUMNS)) begin
                                v_mask_tmp[l] = 1'b1;
                                r_vec_tmp[l]  = req_q.row;
                                c_vec_tmp[l]  = c_ext_tmp[TMEM_COL_W-1:0];
                            end
                        end
                    end

                    bank_rda_valid_d   = v_mask_tmp;
                    bank_rda_row_d     = r_vec_tmp;
                    bank_rda_col_d     = c_vec_tmp;
                    bank_rda_swizzle_d = req_q.swizzle;
                    pending_lanes_d    = v_mask_tmp;
                    beat_lane_mask_d   = v_mask_tmp;
                    rsp_buf_d          = '0;
                    rsp_ce_d           = 1'b0;
                    rsp_ue_d           = 1'b0;
                    state_d            = MMA_WAIT_RDA;
                end
            end

            MMA_WAIT_RDA: begin
                next_p_tmp = pending_lanes_q;
                for (int l = 0; l < LANES; ++l) begin
                    if (pending_lanes_q[l] && bank_rda_rsp_valid[l]) begin
                        next_p_tmp[l] = 1'b0;
                        rsp_buf_d[l]  = bank_rda_rsp_data[l];
                        rsp_ce_d      = rsp_ce_d | bank_rda_ecc_ce[l];
                        rsp_ue_d      = rsp_ue_d | bank_rda_ecc_ue[l];
                    end
                end
                pending_lanes_d = next_p_tmp;

                if (next_p_tmp == '0) begin
                    mma_rsp_valid_d       = 1'b1;
                    mma_rsp_op_d          = req_q.op;
                    mma_rsp_tag_d         = req_q.tag;
                    mma_rsp_status_d      = rsp_ue_d ? TMEM_STATUS_ECC_UE : TMEM_STATUS_OK;
                    mma_rsp_data_d        = rsp_buf_d;
                    mma_rsp_lane_mask_d   = beat_lane_mask_q;
                    mma_rsp_ecc_ce_d      = rsp_ce_d;
                    mma_rsp_ecc_ue_d      = rsp_ue_d;
                    hazard_commit_valid_d     = 1'b1;
                    hazard_commit_tag_d       = req_q.tag;
                    hazard_commit_region_id_d = req_q.region_id;
                    hazard_commit_warp_id_d   = req_q.warp_id;
                    mma_rd_beats_d            = mma_rd_beats_q + 32'd1;
                    state_d                   = MMA_IDLE;
                end
            end

            MMA_ISSUE_RDB: begin
                if (bank_rdb_valid_q == '0) begin
                    base_c_tmp = resolve_ping_pong_col(act_reg_tmp, req_q.col, req_q.ping_pong_sel);
                    for (int l = 0; l < LANES; ++l) begin
                        if (8'(l) < eff_cols_tmp) begin
                            c_ext_tmp = {2'b00, base_c_tmp} + 11'(l);
                            if (c_ext_tmp < 11'(TMEM_COLUMNS)) begin
                                v_mask_tmp[l] = 1'b1;
                                r_vec_tmp[l]  = req_q.row;
                                c_vec_tmp[l]  = c_ext_tmp[TMEM_COL_W-1:0];
                            end
                        end
                    end

                    bank_rdb_valid_d   = v_mask_tmp;
                    bank_rdb_row_d     = r_vec_tmp;
                    bank_rdb_col_d     = c_vec_tmp;
                    bank_rdb_swizzle_d = req_q.swizzle;
                    pending_lanes_d    = v_mask_tmp;
                    beat_lane_mask_d   = v_mask_tmp;
                    rsp_buf_d          = '0;
                    rsp_ce_d           = 1'b0;
                    rsp_ue_d           = 1'b0;
                    state_d            = MMA_WAIT_RDB;
                end
            end

            MMA_WAIT_RDB: begin
                next_p_tmp = pending_lanes_q;
                for (int l = 0; l < LANES; ++l) begin
                    if (pending_lanes_q[l] && bank_rdb_rsp_valid[l]) begin
                        next_p_tmp[l] = 1'b0;
                        rsp_buf_d[l]  = bank_rdb_rsp_data[l];
                        rsp_ce_d      = rsp_ce_d | bank_rdb_ecc_ce[l];
                        rsp_ue_d      = rsp_ue_d | bank_rdb_ecc_ue[l];
                    end
                end
                pending_lanes_d = next_p_tmp;

                if (next_p_tmp == '0) begin
                    mma_rsp_valid_d       = 1'b1;
                    mma_rsp_op_d          = req_q.op;
                    mma_rsp_tag_d         = req_q.tag;
                    mma_rsp_status_d      = rsp_ue_d ? TMEM_STATUS_ECC_UE : TMEM_STATUS_OK;
                    mma_rsp_data_d        = rsp_buf_d;
                    mma_rsp_lane_mask_d   = beat_lane_mask_q;
                    mma_rsp_ecc_ce_d      = rsp_ce_d;
                    mma_rsp_ecc_ue_d      = rsp_ue_d;
                    hazard_commit_valid_d     = 1'b1;
                    hazard_commit_tag_d       = req_q.tag;
                    hazard_commit_region_id_d = req_q.region_id;
                    hazard_commit_warp_id_d   = req_q.warp_id;
                    mma_rd_beats_d            = mma_rd_beats_q + 32'd1;
                    state_d                   = MMA_IDLE;
                end
            end

            MMA_ISSUE_WR: begin
                if (bank_wr_valid_q == '0) begin
                    base_c_tmp = resolve_ping_pong_col(act_reg_tmp, req_q.col, req_q.ping_pong_sel);
                    for (int l = 0; l < LANES; ++l) begin
                        if ((8'(l) < eff_cols_tmp) && (req_q.wr_be[l] != 8'h00)) begin
                            c_ext_tmp = {2'b00, base_c_tmp} + 11'(l);
                            if (c_ext_tmp < 11'(TMEM_COLUMNS)) begin
                                v_mask_tmp[l] = 1'b1;
                                r_vec_tmp[l]  = req_q.row;
                                c_vec_tmp[l]  = c_ext_tmp[TMEM_COL_W-1:0];
                            end
                        end
                    end

                    bank_wr_valid_d   = v_mask_tmp;
                    bank_wr_row_d     = r_vec_tmp;
                    bank_wr_col_d     = c_vec_tmp;
                    bank_wr_swizzle_d = req_q.swizzle;
                    bank_wr_data_d    = req_q.wr_data;
                    bank_wr_be_d      = req_q.wr_be;
                    beat_lane_mask_d  = v_mask_tmp;
                    state_d           = MMA_WAIT_WR;
                end
            end

            MMA_WAIT_WR: begin
                if (next_wr_valid_tmp == '0) begin
                    mma_rsp_valid_d       = 1'b1;
                    mma_rsp_op_d          = req_q.op;
                    mma_rsp_tag_d         = req_q.tag;
                    mma_rsp_status_d      = TMEM_STATUS_OK;
                    mma_rsp_data_d        = '0;
                    mma_rsp_lane_mask_d   = beat_lane_mask_q;
                    mma_rsp_ecc_ce_d      = 1'b0;
                    mma_rsp_ecc_ue_d      = 1'b0;
                    hazard_commit_valid_d     = 1'b1;
                    hazard_commit_tag_d       = req_q.tag;
                    hazard_commit_region_id_d = req_q.region_id;
                    hazard_commit_warp_id_d   = req_q.warp_id;
                    mma_wr_beats_d            = mma_wr_beats_q + 32'd1;
                    state_d                   = MMA_IDLE;
                end
            end

            MMA_FAULT: begin
                if (rsp_slot_free_tmp) begin
                    mma_rsp_valid_d     = 1'b1;
                    mma_rsp_op_d        = req_q.op;
                    mma_rsp_tag_d       = req_q.tag;
                    mma_rsp_status_d    = TMEM_STATUS_NOT_ALLOCED;
                    mma_rsp_data_d      = '0;
                    mma_rsp_lane_mask_d = '0;
                    mma_rsp_ecc_ce_d    = 1'b0;
                    mma_rsp_ecc_ue_d    = 1'b0;
                    state_d             = MMA_IDLE;
                end
            end

            default: begin
                state_d = MMA_IDLE;
            end
        endcase
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            state_q               <= MMA_IDLE;
            req_q                 <= '0;
            ping_pong_ptr_q       <= '0;
            pending_lanes_q       <= '0;
            beat_lane_mask_q      <= '0;
            rsp_buf_q             <= '0;
            rsp_ce_q              <= 1'b0;
            rsp_ue_q              <= 1'b0;

            bank_rda_valid_q      <= '0;
            bank_rda_row_q        <= '0;
            bank_rda_col_q        <= '0;
            bank_rda_swizzle_q    <= TMEM_SWIZZLE_NONE;

            bank_rdb_valid_q      <= '0;
            bank_rdb_row_q        <= '0;
            bank_rdb_col_q        <= '0;
            bank_rdb_swizzle_q    <= TMEM_SWIZZLE_NONE;

            bank_wr_valid_q       <= '0;
            bank_wr_row_q         <= '0;
            bank_wr_col_q         <= '0;
            bank_wr_swizzle_q     <= TMEM_SWIZZLE_NONE;
            bank_wr_data_q        <= '0;
            bank_wr_be_q          <= '0;

            mma_rsp_valid_q       <= 1'b0;
            mma_rsp_op_q          <= TMEM_OP_NOP;
            mma_rsp_tag_q         <= '0;
            mma_rsp_status_q      <= TMEM_STATUS_OK;
            mma_rsp_data_q        <= '0;
            mma_rsp_lane_mask_q   <= '0;
            mma_rsp_ecc_ce_q      <= 1'b0;
            mma_rsp_ecc_ue_q      <= 1'b0;

            hazard_issue_fire_q       <= 1'b0;
            hazard_issue_region_id_q  <= '0;
            hazard_issue_warp_id_q    <= '0;
            hazard_commit_valid_q     <= 1'b0;
            hazard_commit_tag_q       <= '0;
            hazard_commit_region_id_q <= '0;
            hazard_commit_warp_id_q   <= '0;
            mma_rd_beats_q            <= 32'd0;
            mma_wr_beats_q            <= 32'd0;
        end else begin
            state_q               <= state_d;
            req_q                 <= req_d;
            ping_pong_ptr_q       <= ping_pong_ptr_d;
            pending_lanes_q       <= pending_lanes_d;
            beat_lane_mask_q      <= beat_lane_mask_d;
            rsp_buf_q             <= rsp_buf_d;
            rsp_ce_q              <= rsp_ce_d;
            rsp_ue_q              <= rsp_ue_d;

            bank_rda_valid_q      <= bank_rda_valid_d;
            bank_rda_row_q        <= bank_rda_row_d;
            bank_rda_col_q        <= bank_rda_col_d;
            bank_rda_swizzle_q    <= bank_rda_swizzle_d;

            bank_rdb_valid_q      <= bank_rdb_valid_d;
            bank_rdb_row_q        <= bank_rdb_row_d;
            bank_rdb_col_q        <= bank_rdb_col_d;
            bank_rdb_swizzle_q    <= bank_rdb_swizzle_d;

            bank_wr_valid_q       <= bank_wr_valid_d;
            bank_wr_row_q         <= bank_wr_row_d;
            bank_wr_col_q         <= bank_wr_col_d;
            bank_wr_swizzle_q     <= bank_wr_swizzle_d;
            bank_wr_data_q        <= bank_wr_data_d;
            bank_wr_be_q          <= bank_wr_be_d;

            mma_rsp_valid_q       <= mma_rsp_valid_d;
            mma_rsp_op_q          <= mma_rsp_op_d;
            mma_rsp_tag_q         <= mma_rsp_tag_d;
            mma_rsp_status_q      <= mma_rsp_status_d;
            mma_rsp_data_q        <= mma_rsp_data_d;
            mma_rsp_lane_mask_q   <= mma_rsp_lane_mask_d;
            mma_rsp_ecc_ce_q      <= mma_rsp_ecc_ce_d;
            mma_rsp_ecc_ue_q      <= mma_rsp_ecc_ue_d;

            hazard_issue_fire_q       <= hazard_issue_fire_d;
            hazard_issue_region_id_q  <= hazard_issue_region_id_d;
            hazard_issue_warp_id_q    <= hazard_issue_warp_id_d;
            hazard_commit_valid_q     <= hazard_commit_valid_d;
            hazard_commit_tag_q       <= hazard_commit_tag_d;
            hazard_commit_region_id_q <= hazard_commit_region_id_d;
            hazard_commit_warp_id_q   <= hazard_commit_warp_id_d;
            mma_rd_beats_q            <= mma_rd_beats_d;
            mma_wr_beats_q            <= mma_wr_beats_d;
        end
    end

    assign bank_rda_valid      = bank_rda_valid_q;
    assign bank_rda_row        = bank_rda_row_q;
    assign bank_rda_col        = bank_rda_col_q;
    assign bank_rda_swizzle    = bank_rda_swizzle_q;

    assign bank_rdb_valid      = bank_rdb_valid_q;
    assign bank_rdb_row        = bank_rdb_row_q;
    assign bank_rdb_col        = bank_rdb_col_q;
    assign bank_rdb_swizzle    = bank_rdb_swizzle_q;

    assign bank_wr_valid       = bank_wr_valid_q;
    assign bank_wr_row         = bank_wr_row_q;
    assign bank_wr_col         = bank_wr_col_q;
    assign bank_wr_swizzle     = bank_wr_swizzle_q;
    assign bank_wr_data        = bank_wr_data_q;
    assign bank_wr_be          = bank_wr_be_q;

    assign mma_rsp_valid       = mma_rsp_valid_q;
    assign mma_rsp_op          = mma_rsp_op_q;
    assign mma_rsp_tag         = mma_rsp_tag_q;
    assign mma_rsp_status      = mma_rsp_status_q;
    assign mma_rsp_data        = mma_rsp_data_q;
    assign mma_rsp_lane_mask   = mma_rsp_lane_mask_q;
    assign mma_rsp_ecc_ce      = mma_rsp_ecc_ce_q;
    assign mma_rsp_ecc_ue      = mma_rsp_ecc_ue_q;

    assign hazard_issue_fire       = hazard_issue_fire_q;
    assign hazard_issue_region_id  = hazard_issue_region_id_q;
    assign hazard_issue_warp_id    = hazard_issue_warp_id_q;
    assign hazard_commit_valid     = hazard_commit_valid_q;
    assign hazard_commit_tag       = hazard_commit_tag_q;
    assign hazard_commit_region_id = hazard_commit_region_id_q;
    assign hazard_commit_warp_id   = hazard_commit_warp_id_q;
    assign ping_pong_ptr_out       = ping_pong_ptr_q;
    assign mma_rd_beats_out        = mma_rd_beats_q;
    assign mma_wr_beats_out        = mma_wr_beats_q;

endmodule
