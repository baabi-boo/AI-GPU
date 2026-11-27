// SPDX-License-Identifier: Apache-2.0
module VX_tmem_bounds_chk
    import VX_tmem_pkg::*;
#(
    parameter int MAX_REGIONS = TMEM_MAX_REGIONS
) (
    input  logic                                clk,
    input  logic                                reset,
    input  tmem_region_entry_t [MAX_REGIONS-1:0] region_table_in,
    input  logic                                strict_owner_en,
    // LD coordinate check
    input  logic                                ld_chk_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_chk_region_id,
    input  logic [4:0]                          ld_chk_warp_id,
    input  logic [TMEM_ROW_W-1:0]               ld_chk_row,
    input  logic [TMEM_COL_W-1:0]               ld_chk_col,
    input  logic [7:0]                          ld_chk_num_rows,
    input  logic [9:0]                          ld_chk_num_cols,
    // ST coordinate check
    input  logic                                st_chk_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         st_chk_region_id,
    input  logic [4:0]                          st_chk_warp_id,
    input  logic [TMEM_ROW_W-1:0]               st_chk_row,
    input  logic [TMEM_COL_W-1:0]               st_chk_col,
    input  logic [7:0]                          st_chk_num_rows,
    input  logic [9:0]                          st_chk_num_cols,
    // MMA coordinate check
    input  logic                                mma_chk_valid,
    input  logic                                mma_chk_is_write,
    input  logic [TMEM_REGION_ID_W-1:0]         mma_chk_region_id,
    input  logic [4:0]                          mma_chk_warp_id,
    input  logic [TMEM_ROW_W-1:0]               mma_chk_row,
    input  logic [TMEM_COL_W-1:0]               mma_chk_col,
    input  logic [7:0]                          mma_chk_num_cols,
    // Combinational enqueue-time fault outputs (aligned with valid requests)
    output logic                                ld_comb_fault_out,
    output logic                                st_comb_fault_out,
    output logic                                mma_comb_fault_out,
    // Fault syndrome & telemetry outputs (registered)
    output logic                                ld_fault_out,
    output logic                                st_fault_out,
    output logic                                mma_fault_out,
    output logic                                any_fault_out,
    output logic [1:0]                          fault_client_out,
    output logic [2:0]                          fault_reason_out,
    output logic [TMEM_REGION_ID_W-1:0]         fault_region_id_out,
    output logic [4:0]                          fault_warp_id_out,
    output logic [TMEM_ROW_W-1:0]               fault_row_out,
    output logic [TMEM_COL_W-1:0]               fault_col_out,
    output logic [31:0]                         total_faults_out,
    output logic [31:0]                         ld_fault_cnt_out,
    output logic [31:0]                         st_fault_cnt_out,
    output logic [31:0]                         mma_fault_cnt_out
);

    // Fault reason codes
    localparam logic [2:0] REASON_NONE       = 3'd0;
    localparam logic [2:0] REASON_UNALLOC    = 3'd1;
    localparam logic [2:0] REASON_OWNER_MISM = 3'd2;
    localparam logic [2:0] REASON_ROW_OOB    = 3'd3;
    localparam logic [2:0] REASON_COL_OOB    = 3'd4;
    localparam logic [2:0] REASON_ZERO_SPAN  = 3'd5;

    // Client IDs for syndrome reporting
    localparam logic [1:0] CLI_LD  = 2'd0;
    localparam logic [1:0] CLI_ST  = 2'd1;
    localparam logic [1:0] CLI_MMA = 2'd2;

    logic                        ld_fault_q, ld_fault_d;
    logic                        st_fault_q, st_fault_d;
    logic                        mma_fault_q, mma_fault_d;
    logic                        any_fault_q, any_fault_d;
    logic [1:0]                  fault_client_q, fault_client_d;
    logic [2:0]                  fault_reason_q, fault_reason_d;
    logic [TMEM_REGION_ID_W-1:0] fault_region_id_q, fault_region_id_d;
    logic [4:0]                  fault_warp_id_q, fault_warp_id_d;
    logic [TMEM_ROW_W-1:0]       fault_row_q, fault_row_d;
    logic [TMEM_COL_W-1:0]       fault_col_q, fault_col_d;
    logic [31:0]                 total_faults_q, total_faults_d;
    logic [31:0]                 ld_fault_cnt_q, ld_fault_cnt_d;
    logic [31:0]                 st_fault_cnt_q, st_fault_cnt_d;
    logic [31:0]                 mma_fault_cnt_q, mma_fault_cnt_d;

    // Evaluate access legality and classify specific fault reason
    function automatic logic [2:0] classify_access_fault(
        input tmem_region_entry_t    reg_entry,
        input logic                  check_owner,
        input logic [4:0]            warp_id,
        input logic [TMEM_ROW_W-1:0] row,
        input logic [TMEM_COL_W-1:0] col,
        input logic [7:0]            num_rows,
        input logic [9:0]            num_cols
    );
        logic [8:0]  row_end;
        logic [10:0] col_end;
        logic [10:0] reg_start;
        logic [10:0] reg_cols_eff;
        logic [10:0] reg_end;
        logic        unused_zero;

        row_end      = {2'b00, row} + {1'b0, num_rows};
        col_end      = {2'b00, col} + {1'b0, num_cols};
        reg_start    = {2'b00, reg_entry.col_offset};
        reg_cols_eff = reg_entry.double_buf_en
                       ? ({1'b0, reg_entry.num_columns} << 1)
                       : {1'b0, reg_entry.num_columns};
        reg_end      = reg_start + reg_cols_eff;
        unused_zero  = &{1'b0, reg_entry};

        if (unused_zero || !reg_entry.allocated) begin
            return REASON_UNALLOC;
        end else if ((num_rows == 8'd0) || (num_cols == 10'd0)) begin
            return REASON_ZERO_SPAN;
        end else if (check_owner && (reg_entry.owner_warp != warp_id)) begin
            return REASON_OWNER_MISM;
        end else if (row_end > {1'b0, reg_entry.num_rows}) begin
            return REASON_ROW_OOB;
        end else if (({2'b00, col} < reg_start) || (col_end > reg_end)) begin
            return REASON_COL_OOB;
        end else begin
            return REASON_NONE;
        end
    endfunction

    // Combinational bounds checking across all three clients
    always_comb begin
        logic [2:0] ld_reason;
        logic [2:0] st_reason;
        logic [2:0] mma_reason;

        ld_reason  = REASON_NONE;
        st_reason  = REASON_NONE;
        mma_reason = REASON_NONE;

        if (ld_chk_valid) begin
            ld_reason = classify_access_fault(
                region_table_in[ld_chk_region_id],
                strict_owner_en,
                ld_chk_warp_id,
                ld_chk_row,
                ld_chk_col,
                ld_chk_num_rows,
                ld_chk_num_cols
            );
        end

        if (st_chk_valid) begin
            // Store operations always enforce warp ownership against cross-CTA corruption
            st_reason = classify_access_fault(
                region_table_in[st_chk_region_id],
                1'b1,
                st_chk_warp_id,
                st_chk_row,
                st_chk_col,
                st_chk_num_rows,
                st_chk_num_cols
            );
        end

        if (mma_chk_valid) begin
            mma_reason = classify_access_fault(
                region_table_in[mma_chk_region_id],
                strict_owner_en || mma_chk_is_write,
                mma_chk_warp_id,
                mma_chk_row,
                mma_chk_col,
                8'd1,
                {2'b00, mma_chk_num_cols}
            );
        end

        ld_fault_d        = (ld_reason  != REASON_NONE);
        st_fault_d        = (st_reason  != REASON_NONE);
        mma_fault_d       = (mma_reason != REASON_NONE);
        any_fault_d       = ld_fault_d | st_fault_d | mma_fault_d;

        fault_client_d    = fault_client_q;
        fault_reason_d    = fault_reason_q;
        fault_region_id_d = fault_region_id_q;
        fault_warp_id_d   = fault_warp_id_q;
        fault_row_d       = fault_row_q;
        fault_col_d       = fault_col_q;

        if (st_fault_d) begin
            fault_client_d    = CLI_ST;
            fault_reason_d    = st_reason;
            fault_region_id_d = st_chk_region_id;
            fault_warp_id_d   = st_chk_warp_id;
            fault_row_d       = st_chk_row;
            fault_col_d       = st_chk_col;
        end else if (mma_fault_d) begin
            fault_client_d    = CLI_MMA;
            fault_reason_d    = mma_reason;
            fault_region_id_d = mma_chk_region_id;
            fault_warp_id_d   = mma_chk_warp_id;
            fault_row_d       = mma_chk_row;
            fault_col_d       = mma_chk_col;
        end else if (ld_fault_d) begin
            fault_client_d    = CLI_LD;
            fault_reason_d    = ld_reason;
            fault_region_id_d = ld_chk_region_id;
            fault_warp_id_d   = ld_chk_warp_id;
            fault_row_d       = ld_chk_row;
            fault_col_d       = ld_chk_col;
        end

        ld_fault_cnt_d  = ld_fault_cnt_q  + (ld_fault_d  ? 32'd1 : 32'd0);
        st_fault_cnt_d  = st_fault_cnt_q  + (st_fault_d  ? 32'd1 : 32'd0);
        mma_fault_cnt_d = mma_fault_cnt_q + (mma_fault_d ? 32'd1 : 32'd0);
        total_faults_d  = total_faults_q  +
                          ({31'd0, ld_fault_d} + {31'd0, st_fault_d} + {31'd0, mma_fault_d});
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            ld_fault_q        <= 1'b0;
            st_fault_q        <= 1'b0;
            mma_fault_q       <= 1'b0;
            any_fault_q       <= 1'b0;
            fault_client_q    <= 2'd0;
            fault_reason_q    <= REASON_NONE;
            fault_region_id_q <= '0;
            fault_warp_id_q   <= 5'd0;
            fault_row_q       <= '0;
            fault_col_q       <= '0;
            total_faults_q    <= 32'd0;
            ld_fault_cnt_q    <= 32'd0;
            st_fault_cnt_q    <= 32'd0;
            mma_fault_cnt_q   <= 32'd0;
        end else begin
            ld_fault_q        <= ld_fault_d;
            st_fault_q        <= st_fault_d;
            mma_fault_q       <= mma_fault_d;
            any_fault_q       <= any_fault_d;
            fault_client_q    <= fault_client_d;
            fault_reason_q    <= fault_reason_d;
            fault_region_id_q <= fault_region_id_d;
            fault_warp_id_q   <= fault_warp_id_d;
            fault_row_q       <= fault_row_d;
            fault_col_q       <= fault_col_d;
            total_faults_q    <= total_faults_d;
            ld_fault_cnt_q    <= ld_fault_cnt_d;
            st_fault_cnt_q    <= st_fault_cnt_d;
            mma_fault_cnt_q   <= mma_fault_cnt_d;
        end
    end

    assign ld_comb_fault_out   = ld_fault_d;
    assign st_comb_fault_out   = st_fault_d;
    assign mma_comb_fault_out  = mma_fault_d;
    assign ld_fault_out        = ld_fault_q;
    assign st_fault_out        = st_fault_q;
    assign mma_fault_out       = mma_fault_q;
    assign any_fault_out       = any_fault_q;
    assign fault_client_out    = fault_client_q;
    assign fault_reason_out    = fault_reason_q;
    assign fault_region_id_out = fault_region_id_q;
    assign fault_warp_id_out   = fault_warp_id_q;
    assign fault_row_out       = fault_row_q;
    assign fault_col_out       = fault_col_q;
    assign total_faults_out    = total_faults_q;
    assign ld_fault_cnt_out    = ld_fault_cnt_q;
    assign st_fault_cnt_out    = st_fault_cnt_q;
    assign mma_fault_cnt_out   = mma_fault_cnt_q;

endmodule
