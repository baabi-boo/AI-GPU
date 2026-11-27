// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_SYSTOLIC_TOP_SV
`define VX_TCU_V2_SYSTOLIC_TOP_SV

`include "VX_platform.vh"

module VX_tcu_v2_systolic_top #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                    clk,
    input  logic                                    reset,
    input  logic                                    uop_valid,
    output logic                                    uop_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t              uop_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      a_tile_in,
    input  logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      b_tile_in,
    input  logic [ARRAY_M-1:0][7:0]                 scale_a_in,
    input  logic [ARRAY_N-1:0][7:0]                 scale_b_in,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   c_tile_in,
    input  logic [ARRAY_N-1:0][31:0]                bias_in,
    output logic                                    out_valid,
    input  logic                                    out_ready,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   d_tile_out,
    output logic [7:0]                              out_desc_id,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t         flags_out,
    output logic                                    busy,
    output logic [31:0]                             active_cycles_out
);

    import VX_tcu_v2_pkg::*;

    localparam logic SYSTOLIC_MODE_DEFAULT = 1'b0;

    // -------------------------------------------------------------------------
    // Interconnect Wires Across Staging, Scale Fabric, PE Array, and Epilogue
    // -------------------------------------------------------------------------
    logic                                    dbuf_load_valid;
    logic                                    dbuf_load_ready;
    logic                                    dbuf_exec_valid;
    logic                                    dbuf_exec_ready;
    tcu_v2_uop_t                             dbuf_exec_uop;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      dbuf_a_tile;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      dbuf_b_tile;
    logic [ARRAY_M-1:0][7:0]                 dbuf_scale_a;
    logic [ARRAY_N-1:0][7:0]                 dbuf_scale_b;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   dbuf_c_tile;
    logic [ARRAY_N-1:0][31:0]                dbuf_bias;
    logic                                    dbuf_swap_req;
    logic                                    dbuf_swap_ack;
    logic                                    dbuf_wr_bank;
    logic                                    dbuf_rd_bank;
    logic [1:0]                              dbuf_banks_full;
    logic                                    dbuf_busy;
    logic [31:0]                             dbuf_prefetch_hits;

    logic                                    ctrl_issue_valid;
    logic                                    ctrl_issue_ready;
    logic                                    ctrl_pe_wb_valid;
    logic                                    ctrl_pe_wb_ready;
    logic                                    ctrl_acc_preload_valid;
    logic                                    ctrl_acc_preload_use_c;
    logic                                    ctrl_acc_preload_is_int;
    logic                                    ctrl_acc_rmw_fwd_valid;
    logic                                    ctrl_acc_wb_valid;
    logic                                    ctrl_acc_wb_ready;
    logic                                    ctrl_acc_swap_req;
    logic                                    ctrl_acc_swap_ack;
    logic [31:0]                             ctrl_stall_cycles;
    logic [31:0]                             ctrl_k_steps_done;

    logic                                    scale_out_valid;
    logic                                    scale_out_ready;
    logic [ARRAY_M-1:0][7:0]                 scale_a_aligned;
    logic [ARRAY_N-1:0][7:0]                 scale_b_aligned;
    tcu_v2_scale_fmt_e                       eff_scale_fmt;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_scale_invalid_mask;
    logic                                    any_scale_invalid;
    logic [ARRAY_M-1:0]                      row_scale_zero_mask;
    logic [ARRAY_N-1:0]                      col_scale_zero_mask;
    logic [31:0]                             scale_fault_count;

    logic                                    skew_in_valid;
    logic                                    skew_in_ready;
    logic [ARRAY_M-1:0]                      skew_a_row_valid;
    logic [ARRAY_M-1:0]                      skew_a_row_ready;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      skew_a_row_data;
    logic [ARRAY_M-1:0][7:0]                 skew_a_row_scale;
    logic [ARRAY_N-1:0]                      skew_b_col_valid;
    logic [ARRAY_N-1:0]                      skew_b_col_ready;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      skew_b_col_data;
    logic [ARRAY_N-1:0][7:0]                 skew_b_col_scale;
    logic                                    skew_busy;

    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_out_valid;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]         pe_out_ready;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   pe_out_data;
    tcu_v2_fp_flags_t [ARRAY_M-1:0][ARRAY_N-1:0] pe_out_flags;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   acc_c_read_tile;
    logic                                    acc_drain_valid;
    logic                                    acc_drain_ack;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   acc_drain_tile;
    tcu_v2_fp_flags_t                        acc_drain_flags;
    tcu_v2_uop_t                             acc_drain_uop;
    logic [ARRAY_N-1:0][31:0]                acc_drain_bias;
    logic                                    acc_active_bank;
    logic                                    acc_busy;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   deskew_tile_out;
    tcu_v2_fp_flags_t                        deskew_flags_out;

    // -------------------------------------------------------------------------
    // Issue Payload Staging Across Scale Alignment Latency (1-Cycle Match)
    // -------------------------------------------------------------------------
    tcu_v2_uop_t                             issue_uop_r;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      issue_a_tile_r;
    logic [ARRAY_N-1:0][ARRAY_K*32-1:0]      issue_b_tile_r;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   issue_c_tile_r;
    logic [ARRAY_N-1:0][31:0]                issue_bias_r;
    logic                                    issue_stage_valid_r;

    // Inflight active micro-op FIFO alongside the PE array for writeback metadata
    localparam int WB_META_DEPTH = 8;
    localparam int WB_PTR_W      = $clog2(WB_META_DEPTH);
    localparam int WB_CNT_W      = $clog2(WB_META_DEPTH + 1);

    tcu_v2_uop_t                                 wb_uop_q_r [WB_META_DEPTH];
    logic [WB_META_DEPTH-1:0][ARRAY_N-1:0][31:0] wb_bias_q_r;
    logic [WB_META_DEPTH-1:0]                    wb_scale_inv_q_r;
    logic [WB_PTR_W-1:0]                         wb_wr_ptr_r;
    logic [WB_PTR_W-1:0]                         wb_rd_ptr_r;
    logic [WB_CNT_W-1:0]                         wb_count_r;
    logic                                        wb_q_full;
    logic                                        wb_q_empty;

    // Top-level per-format invocation counters, exception counters & checksum monitor
    logic [31:0] top_uops_in_r;
    logic [31:0] top_tiles_out_r;
    logic [31:0] top_fp46_uops_r;
    logic [31:0] top_fp8_uops_r;
    logic [31:0] top_bf16_uops_r;
    logic [31:0] top_int_uops_r;
    logic [31:0] top_nv_events_r;
    logic [31:0] top_of_events_r;
    logic [31:0] top_uf_events_r;
    logic [31:0] top_nx_events_r;
    logic [31:0] top_out_checksum_r;
    logic [31:0] top_pe_ops_total;

    assign wb_q_full  = (wb_count_r == WB_CNT_W'(WB_META_DEPTH));
    assign wb_q_empty = (wb_count_r == WB_CNT_W'(0));

    logic issue_to_scale_ready;
    logic issue_stage_ready;
    logic scale_in_valid;
    assign issue_stage_ready = !wb_q_full && (!issue_stage_valid_r || skew_in_ready);
    assign ctrl_issue_ready  = issue_to_scale_ready && issue_stage_ready;
    assign scale_in_valid    = ctrl_issue_valid && issue_stage_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            issue_stage_valid_r <= 1'b0;
            issue_uop_r         <= '0;
            issue_a_tile_r      <= '0;
            issue_b_tile_r      <= '0;
            issue_c_tile_r      <= '0;
            issue_bias_r        <= '0;
        end else if (ctrl_issue_valid && ctrl_issue_ready) begin
            issue_stage_valid_r <= 1'b1;
            issue_uop_r         <= dbuf_exec_uop;
            issue_a_tile_r      <= dbuf_a_tile;
            issue_b_tile_r      <= dbuf_b_tile;
            issue_c_tile_r      <= acc_c_read_tile;
            issue_bias_r        <= dbuf_bias;
        end else if (scale_out_valid && skew_in_ready) begin
            issue_stage_valid_r <= 1'b0;
        end
    end

    assign skew_in_valid   = scale_out_valid && issue_stage_valid_r;
    assign scale_out_ready = skew_in_ready;

    logic wb_q_push;
    logic wb_q_pop;
    assign wb_q_push = skew_in_valid && skew_in_ready;
    assign wb_q_pop  = ctrl_pe_wb_valid && ctrl_pe_wb_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            wb_wr_ptr_r      <= '0;
            wb_rd_ptr_r      <= '0;
            wb_count_r       <= '0;
            wb_scale_inv_q_r <= '0;
            for (int q = 0; q < WB_META_DEPTH; ++q) begin
                wb_uop_q_r[q]  <= '0;
                wb_bias_q_r[q] <= '0;
            end
        end else begin
            if (wb_q_push) begin
                wb_uop_q_r[wb_wr_ptr_r]       <= issue_uop_r;
                wb_bias_q_r[wb_wr_ptr_r]      <= issue_bias_r;
                wb_scale_inv_q_r[wb_wr_ptr_r] <= any_scale_invalid;
                wb_wr_ptr_r <= (wb_wr_ptr_r == WB_PTR_W'(WB_META_DEPTH - 1)) ? '0 : (wb_wr_ptr_r + WB_PTR_W'(1));
            end
            if (wb_q_pop) begin
                wb_rd_ptr_r <= (wb_rd_ptr_r == WB_PTR_W'(WB_META_DEPTH - 1)) ? '0 : (wb_rd_ptr_r + WB_PTR_W'(1));
            end
            case ({wb_q_push, wb_q_pop})
                2'b10:   wb_count_r <= wb_count_r + WB_CNT_W'(1);
                2'b01:   wb_count_r <= wb_count_r - WB_CNT_W'(1);
                default: wb_count_r <= wb_count_r;
            endcase
        end
    end

    // Track array dispatch mix, exception counts, and output tile checksum for diagnostics
    logic [31:0] out_tile_xor_comb;
    always_comb begin
        out_tile_xor_comb = 32'd0;
        for (int r = 0; r < ARRAY_M; ++r) begin
            for (int c = 0; c < ARRAY_N; ++c) begin
                out_tile_xor_comb = out_tile_xor_comb ^ d_tile_out[r][c];
            end
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            top_uops_in_r      <= 32'd0;
            top_tiles_out_r    <= 32'd0;
            top_fp46_uops_r    <= 32'd0;
            top_fp8_uops_r     <= 32'd0;
            top_bf16_uops_r    <= 32'd0;
            top_int_uops_r     <= 32'd0;
            top_nv_events_r    <= 32'd0;
            top_of_events_r    <= 32'd0;
            top_uf_events_r    <= 32'd0;
            top_nx_events_r    <= 32'd0;
            top_out_checksum_r <= 32'd0;
        end else begin
            if (uop_valid && uop_ready) begin
                top_uops_in_r <= top_uops_in_r + 32'd1;
                if (tcu_v2_fmt_is_fp4(uop_in.fmt_a) || tcu_v2_fmt_is_fp6(uop_in.fmt_a)) begin
                    top_fp46_uops_r <= top_fp46_uops_r + 32'd1;
                end else if (tcu_v2_fmt_is_fp8(uop_in.fmt_a)) begin
                    top_fp8_uops_r <= top_fp8_uops_r + 32'd1;
                end else if (tcu_v2_fmt_is_int(uop_in.fmt_a)) begin
                    top_int_uops_r <= top_int_uops_r + 32'd1;
                end else begin
                    top_bf16_uops_r <= top_bf16_uops_r + 32'd1;
                end
            end
            if (out_valid && out_ready) begin
                top_tiles_out_r    <= top_tiles_out_r + 32'd1;
                top_out_checksum_r <= top_out_checksum_r ^ out_tile_xor_comb;
                if (flags_out.nv) begin
                    top_nv_events_r <= top_nv_events_r + 32'd1;
                end
                if (flags_out.of) begin
                    top_of_events_r <= top_of_events_r + 32'd1;
                end
                if (flags_out.uf) begin
                    top_uf_events_r <= top_uf_events_r + 32'd1;
                end
                if (flags_out.nx) begin
                    top_nx_events_r <= top_nx_events_r + 32'd1;
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // 1. Double-Buffered Operand Staging Buffer
    // -------------------------------------------------------------------------
    VX_tcu_v2_operand_dbuf #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_operand_dbuf (
        .clk               (clk),
        .reset             (reset),
        .load_valid        (dbuf_load_valid),
        .load_ready        (dbuf_load_ready),
        .load_uop          (uop_in),
        .load_a_tile       (a_tile_in),
        .load_b_tile       (b_tile_in),
        .load_scale_a      (scale_a_in),
        .load_scale_b      (scale_b_in),
        .load_c_tile       (c_tile_in),
        .load_bias         (bias_in),
        .exec_valid        (dbuf_exec_valid),
        .exec_ready        (dbuf_exec_ready),
        .exec_uop          (dbuf_exec_uop),
        .exec_a_tile       (dbuf_a_tile),
        .exec_b_tile       (dbuf_b_tile),
        .exec_scale_a      (dbuf_scale_a),
        .exec_scale_b      (dbuf_scale_b),
        .exec_c_tile       (dbuf_c_tile),
        .exec_bias         (dbuf_bias),
        .swap_req          (dbuf_swap_req),
        .swap_ack          (dbuf_swap_ack),
        .wr_bank_idx       (dbuf_wr_bank),
        .rd_bank_idx       (dbuf_rd_bank),
        .banks_full_mask   (dbuf_banks_full),
        .dbuf_busy         (dbuf_busy),
        .prefetch_hits_out (dbuf_prefetch_hits)
    );

    // -------------------------------------------------------------------------
    // 2. Microscale Broadcast & Alignment Fabric
    // -------------------------------------------------------------------------
    VX_tcu_v2_scale_broadcast #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_scale_broadcast (
        .clk                     (clk),
        .reset                   (reset),
        .in_valid                (scale_in_valid),
        .in_ready                (issue_to_scale_ready),
        .fmt_a                   (dbuf_exec_uop.fmt_a),
        .fmt_b                   (dbuf_exec_uop.fmt_b),
        .scale_fmt               (dbuf_exec_uop.scale_fmt),
        .step_k                  (dbuf_exec_uop.step_k),
        .sparse_en               (dbuf_exec_uop.sparse_en),
        .scale_a_in              (dbuf_scale_a),
        .scale_b_in              (dbuf_scale_b),
        .out_valid               (scale_out_valid),
        .out_ready               (scale_out_ready),
        .scale_a_aligned_out     (scale_a_aligned),
        .scale_b_aligned_out     (scale_b_aligned),
        .effective_scale_fmt_out (eff_scale_fmt),
        .pe_scale_invalid_mask   (pe_scale_invalid_mask),
        .any_scale_invalid_out   (any_scale_invalid),
        .row_scale_zero_mask     (row_scale_zero_mask),
        .col_scale_zero_mask     (col_scale_zero_mask),
        .scale_fault_count_out   (scale_fault_count)
    );

    // -------------------------------------------------------------------------
    // 3. Diagonal Operand Skew & Output Deskew Pipelines
    // -------------------------------------------------------------------------
    VX_tcu_v2_operand_skew #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N),
        .ARRAY_K (ARRAY_K)
    ) u_operand_skew (
        .clk               (clk),
        .reset             (reset),
        .systolic_mode     (SYSTOLIC_MODE_DEFAULT),
        .in_valid          (skew_in_valid),
        .in_ready          (skew_in_ready),
        .a_tile_in         (issue_a_tile_r),
        .b_tile_in         (issue_b_tile_r),
        .scale_a_in        (scale_a_aligned),
        .scale_b_in        (scale_b_aligned),
        .a_row_valid_out   (skew_a_row_valid),
        .a_row_ready_in    (skew_a_row_ready),
        .a_row_out         (skew_a_row_data),
        .scale_a_row_out   (skew_a_row_scale),
        .b_col_valid_out   (skew_b_col_valid),
        .b_col_ready_in    (skew_b_col_ready),
        .b_col_out         (skew_b_col_data),
        .scale_b_col_out   (skew_b_col_scale),
        .d_valid_in        (pe_out_valid),
        .d_ready_out       (pe_out_ready),
        .d_elem_in         (pe_out_data),
        .flags_elem_in     (pe_out_flags),
        .deskew_valid_out  (ctrl_pe_wb_valid),
        .deskew_ready_in   (ctrl_pe_wb_ready),
        .d_tile_deskew_out (deskew_tile_out),
        .flags_deskew_out  (deskew_flags_out),
        .skew_busy_out     (skew_busy)
    );

    // -------------------------------------------------------------------------
    // 4. 2D Array of ARRAY_M PE Rows (Each Row Has ARRAY_N Unified PEs)
    // -------------------------------------------------------------------------
    logic [ARRAY_M:0][ARRAY_N-1:0][ARRAY_K*32-1:0] b_vert_chain;
    logic [ARRAY_M:0][ARRAY_N-1:0][7:0]            scale_b_vert_chain;
    logic [ARRAY_M:0][ARRAY_N-1:0]                 b_vert_valid_chain;

    logic [ARRAY_M-1:0][ARRAY_N-1:0][ARRAY_K*32-1:0] row_b_in;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][7:0]            row_scale_b_in;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]                 row_col_valid_in;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]                 row_col_ready_out;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][ARRAY_K*32-1:0] row_b_pass_out;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][7:0]            row_scale_b_pass_out;
    logic [ARRAY_M-1:0][ARRAY_N-1:0]                 row_b_pass_valid;

    logic [ARRAY_M-1:0]                              row_all_valid;
    logic [ARRAY_M-1:0]                              row_busy;
    logic [ARRAY_M-1:0][31:0]                        row_ops_done;
    tcu_v2_fp_flags_t [ARRAY_M-1:0]                  row_flags_or;

    assign b_vert_chain[0]       = skew_b_col_data;
    assign scale_b_vert_chain[0] = skew_b_col_scale;
    assign b_vert_valid_chain[0] = skew_b_col_valid;

    always_comb begin
        top_pe_ops_total = 32'd0;
        for (int r_idx = 0; r_idx < ARRAY_M; ++r_idx) begin
            top_pe_ops_total = top_pe_ops_total + row_ops_done[r_idx];
        end
        for (int c = 0; c < ARRAY_N; ++c) begin
            if (SYSTOLIC_MODE_DEFAULT) begin
                skew_b_col_ready[c] = row_col_ready_out[0][c];
            end else begin
                logic col_rdy_all;
                col_rdy_all = 1'b1;
                for (int r_idx = 0; r_idx < ARRAY_M; ++r_idx) begin
                    col_rdy_all = col_rdy_all && row_col_ready_out[r_idx][c];
                end
                skew_b_col_ready[c] = col_rdy_all;
            end
        end
    end

    for (genvar r = 0; r < ARRAY_M; ++r) begin : g_pe_rows
        always_comb begin
            if (SYSTOLIC_MODE_DEFAULT) begin
                row_b_in[r]         = b_vert_chain[r];
                row_scale_b_in[r]   = scale_b_vert_chain[r];
                row_col_valid_in[r] = b_vert_valid_chain[r];
            end else begin
                row_b_in[r]         = skew_b_col_data;
                row_scale_b_in[r]   = skew_b_col_scale;
                row_col_valid_in[r] = skew_b_col_valid;
            end
        end

        assign b_vert_chain[r + 1]       = row_b_pass_out[r];
        assign scale_b_vert_chain[r + 1] = row_scale_b_pass_out[r];
        assign b_vert_valid_chain[r + 1] = row_b_pass_valid[r];

        VX_tcu_v2_pe_row #(
            .ARRAY_N         (ARRAY_N),
            .ARRAY_K         (ARRAY_K),
            .TAG_QUEUE_DEPTH (8)
        ) u_pe_row (
            .clk                   (clk),
            .reset                 (reset),
            .row_valid_in          (skew_a_row_valid[r]),
            .row_ready_in          (skew_a_row_ready[r]),
            .col_valid_in          (row_col_valid_in[r]),
            .col_ready_in          (row_col_ready_out[r]),
            .fmt_a                 (issue_uop_r.fmt_a),
            .fmt_b                 (issue_uop_r.fmt_b),
            .scale_fmt             (eff_scale_fmt),
            .rm                    (issue_uop_r.rm),
            .systolic_mode         (SYSTOLIC_MODE_DEFAULT),
            .a_row_in              (skew_a_row_data[r]),
            .scale_a_row_in        (skew_a_row_scale[r]),
            .b_cols_in             (row_b_in[r]),
            .scale_b_cols_in       (row_scale_b_in[r]),
            .c_cols_in             (issue_c_tile_r[r]),
            .accum_en              (issue_uop_r.accum_en || !issue_uop_r.is_first_k),
            .int_saturate          (issue_uop_r.int_saturate),
            .b_cols_pass_out       (row_b_pass_out[r]),
            .scale_b_cols_pass_out (row_scale_b_pass_out[r]),
            .b_pass_valid_out      (row_b_pass_valid[r]),
            .valid_out             (pe_out_valid[r]),
            .ready_out             (pe_out_ready[r]),
            .d_cols_out            (pe_out_data[r]),
            .flags_cols_out        (pe_out_flags[r]),
            .row_flags_or_out      (row_flags_or[r]),
            .row_all_valid_out     (row_all_valid[r]),
            .row_busy_out          (row_busy[r]),
            .row_ops_done_out      (row_ops_done[r])
        );
    end

    // -------------------------------------------------------------------------
    // 5. Double-Buffered Accumulator Tile Bank (with RMW Forwarding)
    // -------------------------------------------------------------------------
    tcu_v2_fp_flags_t wb_flags_with_scale;
    always_comb begin
        wb_flags_with_scale = deskew_flags_out;
        if (!wb_q_empty && wb_scale_inv_q_r[wb_rd_ptr_r]) begin
            wb_flags_with_scale.nv = 1'b1;
        end
    end

    VX_tcu_v2_acc_tile_bank #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N)
    ) u_acc_tile_bank (
        .clk              (clk),
        .reset            (reset),
        .preload_valid    (ctrl_acc_preload_valid),
        .preload_use_c    (ctrl_acc_preload_use_c),
        .preload_is_int   (ctrl_acc_preload_is_int),
        .c_tile_preload   (dbuf_c_tile),
        .rmw_fwd_valid    (ctrl_acc_rmw_fwd_valid),
        .rmw_fwd_tile     (deskew_tile_out),
        .c_read_tile_out  (acc_c_read_tile),
        .wb_valid         (ctrl_acc_wb_valid),
        .wb_ready         (ctrl_acc_wb_ready),
        .wb_tile_in       (deskew_tile_out),
        .wb_flags_in      (wb_flags_with_scale),
        .wb_uop_in        (wb_uop_q_r[wb_rd_ptr_r]),
        .wb_bias_in       (wb_bias_q_r[wb_rd_ptr_r]),
        .swap_req         (ctrl_acc_swap_req),
        .swap_ack         (ctrl_acc_swap_ack),
        .drain_bank_valid (acc_drain_valid),
        .drain_bank_ack   (acc_drain_ack),
        .drain_tile_out   (acc_drain_tile),
        .drain_flags_out  (acc_drain_flags),
        .drain_uop_out    (acc_drain_uop),
        .drain_bias_out   (acc_drain_bias),
        .active_bank_idx  (acc_active_bank),
        .acc_busy_out     (acc_busy)
    );

    // -------------------------------------------------------------------------
    // 6. Output Drain Sequencer & Epilogue Pipeline (Bias -> Act -> Cast)
    // -------------------------------------------------------------------------
    logic                                    drain_to_bias_valid;
    logic                                    drain_to_bias_ready;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   drain_to_bias_tile;
    logic [ARRAY_N-1:0][31:0]                drain_to_bias_bias;
    tcu_v2_uop_t                             drain_to_bias_uop;
    tcu_v2_fp_flags_t                        drain_to_bias_flags;
    logic [$clog2(ARRAY_M+1)-1:0]            drain_row_idx;
    logic                                    drain_active;
    logic [31:0]                             tiles_drained;

    logic                                    bias_to_act_valid;
    logic                                    bias_to_act_ready;
    tcu_v2_uop_t                             bias_to_act_uop;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   bias_to_act_tile;
    tcu_v2_fp_flags_t                        bias_to_act_flags;

    logic                                    act_to_cast_valid;
    logic                                    act_to_cast_ready;
    tcu_v2_uop_t                             act_to_cast_uop;
    logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0]   act_to_cast_tile;
    tcu_v2_fp_flags_t                        act_to_cast_flags;

    VX_tcu_v2_output_drain #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N)
    ) u_output_drain (
        .clk                (clk),
        .reset              (reset),
        .bank_valid         (acc_drain_valid),
        .bank_ack           (acc_drain_ack),
        .bank_tile_in       (acc_drain_tile),
        .bank_flags_in      (acc_drain_flags),
        .bank_uop_in        (acc_drain_uop),
        .bank_bias_in       (acc_drain_bias),
        .epilogue_valid     (drain_to_bias_valid),
        .epilogue_ready     (drain_to_bias_ready),
        .epilogue_tile_out  (drain_to_bias_tile),
        .epilogue_bias_out  (drain_to_bias_bias),
        .epilogue_uop_out   (drain_to_bias_uop),
        .epilogue_flags_out (drain_to_bias_flags),
        .drain_row_idx_out  (drain_row_idx),
        .drain_active_out   (drain_active),
        .tiles_drained_out  (tiles_drained)
    );

    VX_tcu_v2_epilogue_bias #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N)
    ) u_epilogue_bias (
        .clk       (clk),
        .reset     (reset),
        .in_valid  (drain_to_bias_valid),
        .in_ready  (drain_to_bias_ready),
        .uop_in    (drain_to_bias_uop),
        .tile_in   (drain_to_bias_tile),
        .bias_in   (drain_to_bias_bias),
        .flags_in  (drain_to_bias_flags),
        .out_valid (bias_to_act_valid),
        .out_ready (bias_to_act_ready),
        .uop_out   (bias_to_act_uop),
        .tile_out  (bias_to_act_tile),
        .flags_out (bias_to_act_flags)
    );

    VX_tcu_v2_epilogue_act #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N)
    ) u_epilogue_act (
        .clk       (clk),
        .reset     (reset),
        .in_valid  (bias_to_act_valid),
        .in_ready  (bias_to_act_ready),
        .uop_in    (bias_to_act_uop),
        .tile_in   (bias_to_act_tile),
        .flags_in  (bias_to_act_flags),
        .out_valid (act_to_cast_valid),
        .out_ready (act_to_cast_ready),
        .uop_out   (act_to_cast_uop),
        .tile_out  (act_to_cast_tile),
        .flags_out (act_to_cast_flags)
    );

    VX_tcu_v2_epilogue_cast #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N)
    ) u_epilogue_cast (
        .clk            (clk),
        .reset          (reset),
        .in_valid       (act_to_cast_valid),
        .in_ready       (act_to_cast_ready),
        .uop_in         (act_to_cast_uop),
        .tile_in        (act_to_cast_tile),
        .flags_in       (act_to_cast_flags),
        .dyn_scale_fp32 (32'h3F80_0000),
        .dyn_scale_en   (1'b0),
        .out_valid      (out_valid),
        .out_ready      (out_ready),
        .d_tile_out     (d_tile_out),
        .out_desc_id    (out_desc_id),
        .flags_out      (flags_out)
    );

    // -------------------------------------------------------------------------
    // 7. Array Sequencer Controller
    // -------------------------------------------------------------------------
    logic array_any_busy;
    logic epilogue_any_busy;

    assign array_any_busy    = (|row_busy) || !wb_q_empty || issue_stage_valid_r;
    assign epilogue_any_busy = drain_to_bias_valid || bias_to_act_valid || act_to_cast_valid || out_valid;

    VX_tcu_v2_array_ctrl #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_N (ARRAY_N)
    ) u_array_ctrl (
        .clk                (clk),
        .reset              (reset),
        .uop_valid          (uop_valid),
        .uop_ready          (uop_ready),
        .uop_in             (uop_in),
        .dbuf_load_valid    (dbuf_load_valid),
        .dbuf_load_ready    (dbuf_load_ready),
        .dbuf_swap_req      (dbuf_swap_req),
        .dbuf_swap_ack      (dbuf_swap_ack),
        .dbuf_exec_valid    (dbuf_exec_valid),
        .dbuf_exec_ready    (dbuf_exec_ready),
        .dbuf_exec_uop      (dbuf_exec_uop),
        .issue_valid        (ctrl_issue_valid),
        .issue_ready        (ctrl_issue_ready),
        .pe_wb_valid        (ctrl_pe_wb_valid),
        .pe_wb_ready        (ctrl_pe_wb_ready),
        .acc_preload_valid  (ctrl_acc_preload_valid),
        .acc_preload_use_c  (ctrl_acc_preload_use_c),
        .acc_preload_is_int (ctrl_acc_preload_is_int),
        .acc_rmw_fwd_valid  (ctrl_acc_rmw_fwd_valid),
        .acc_wb_valid       (ctrl_acc_wb_valid),
        .acc_wb_ready       (ctrl_acc_wb_ready),
        .acc_swap_req       (ctrl_acc_swap_req),
        .acc_swap_ack       (ctrl_acc_swap_ack),
        .skew_busy          (skew_busy),
        .array_busy         (array_any_busy),
        .acc_busy           (acc_busy),
        .drain_active       (drain_active),
        .epilogue_busy      (epilogue_any_busy),
        .busy               (busy),
        .active_cycles_out  (active_cycles_out),
        .stall_cycles_out   (ctrl_stall_cycles),
        .k_steps_done_out   (ctrl_k_steps_done)
    );

    // Tie off auxiliary telemetry signals cleanly
    logic [31:0] top_scale_stall_r;
    logic [31:0] top_skew_stall_r;
    logic [31:0] top_drain_stall_r;
    logic [31:0] top_epilogue_stall_r;
    logic [31:0] top_out_bp_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            top_scale_stall_r    <= 32'd0;
            top_skew_stall_r     <= 32'd0;
            top_drain_stall_r    <= 32'd0;
            top_epilogue_stall_r <= 32'd0;
            top_out_bp_r         <= 32'd0;
        end else begin
            if (scale_out_valid && !scale_out_ready) begin
                top_scale_stall_r <= top_scale_stall_r + 32'd1;
            end
            if (skew_in_valid && !skew_in_ready) begin
                top_skew_stall_r <= top_skew_stall_r + 32'd1;
            end
            if (drain_to_bias_valid && !drain_to_bias_ready) begin
                top_drain_stall_r <= top_drain_stall_r + 32'd1;
            end
            if (bias_to_act_valid && !bias_to_act_ready) begin
                top_epilogue_stall_r <= top_epilogue_stall_r + 32'd1;
            end
            if (out_valid && !out_ready) begin
                top_out_bp_r <= top_out_bp_r + 32'd1;
            end
        end
    end

    `UNUSED_VAR (dbuf_wr_bank)
    `UNUSED_VAR (dbuf_rd_bank)
    `UNUSED_VAR (dbuf_banks_full)
    `UNUSED_VAR (dbuf_busy)
    `UNUSED_VAR (dbuf_prefetch_hits)
    `UNUSED_VAR (ctrl_stall_cycles)
    `UNUSED_VAR (ctrl_k_steps_done)
    `UNUSED_VAR (pe_scale_invalid_mask)
    `UNUSED_VAR (row_scale_zero_mask)
    `UNUSED_VAR (col_scale_zero_mask)
    `UNUSED_VAR (scale_fault_count)
    `UNUSED_VAR (b_vert_chain)
    `UNUSED_VAR (scale_b_vert_chain)
    `UNUSED_VAR (b_vert_valid_chain)
    `UNUSED_VAR (row_all_valid)
    `UNUSED_VAR (top_pe_ops_total)
    `UNUSED_VAR (row_flags_or)
    `UNUSED_VAR (acc_active_bank)
    `UNUSED_VAR (drain_row_idx)
    `UNUSED_VAR (tiles_drained)
    `UNUSED_VAR (top_uops_in_r)
    `UNUSED_VAR (top_tiles_out_r)
    `UNUSED_VAR (top_fp46_uops_r)
    `UNUSED_VAR (top_fp8_uops_r)
    `UNUSED_VAR (top_bf16_uops_r)
    `UNUSED_VAR (top_int_uops_r)
    `UNUSED_VAR (top_nv_events_r)
    `UNUSED_VAR (top_of_events_r)
    `UNUSED_VAR (top_uf_events_r)
    `UNUSED_VAR (top_nx_events_r)
    `UNUSED_VAR (top_out_checksum_r)
    `UNUSED_VAR (top_scale_stall_r)
    `UNUSED_VAR (top_skew_stall_r)
    `UNUSED_VAR (top_drain_stall_r)
    `UNUSED_VAR (top_epilogue_stall_r)
    `UNUSED_VAR (top_out_bp_r)

endmodule

`endif // VX_TCU_V2_SYSTOLIC_TOP_SV
