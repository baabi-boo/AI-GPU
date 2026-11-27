// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_wgmma_desc_q #(
    parameter int DEPTH = VX_tcu_v2_pkg::TCU_V2_DESC_Q_DEPTH
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                flush,
    input  logic                                enq_valid,
    output logic                                enq_ready,
    input  VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t   enq_desc,
    input  logic                                deq_ready,
    output logic                                deq_valid,
    output VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t   deq_desc,
    output VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t   peek_desc,
    output logic                                peek_valid,
    output logic                                empty,
    output logic                                full,
    output logic [$clog2(DEPTH+1)-1:0]          occupancy,
    output logic [$clog2(DEPTH+1)-1:0]          credits_avail,
    output logic                                reject_pulse,
    output logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] reject_desc_id,
    output logic [31:0]                         total_accepted_cnt,
    output logic [31:0]                         total_rejected_cnt,
    output logic [31:0]                         total_flushed_cnt
);

    import VX_tcu_v2_pkg::*;

    localparam int PTR_W = $clog2(DEPTH);
    localparam int CNT_W = $clog2(DEPTH + 1);

    tcu_v2_wgmma_desc_t [DEPTH-1:0] mem_r;
    logic [PTR_W-1:0]               wr_ptr_r;
    logic [PTR_W-1:0]               rd_ptr_r;
    logic [CNT_W-1:0]               count_r;

    logic [31:0]                    accepted_cnt_r;
    logic [31:0]                    rejected_cnt_r;
    logic [31:0]                    flushed_cnt_r;
    logic                           reject_pulse_r;
    logic [TCU_V2_DESC_ID_W-1:0]    reject_desc_id_r;

    logic                           desc_legal_w;
    logic                           tmem_bounds_ok_w;
    logic                           tile_nonempty_w;
    logic                           tile_align_ok_w;
    logic                           scale_match_ok_w;
    logic                           can_accept_w;
    logic                           do_push_w;
    logic                           do_pop_w;

    logic [CNT_W-1:0]               peak_occupancy_r;
    logic [31:0]                    sparse_enq_cnt_r;
    logic [31:0]                    cta_pair_enq_cnt_r;
    logic [31:0]                    illegal_fmt_cnt_r;
    logic [31:0]                    illegal_dim_cnt_r;
    logic [31:0]                    illegal_tmem_cnt_r;
    logic [31:0]                    illegal_scale_cnt_r;

    always_comb begin
        desc_legal_w = tcu_v2_desc_is_legal(enq_desc);

        tmem_bounds_ok_w = (int'(enq_desc.tmem_a_row) < 128) &&
                           (int'(enq_desc.tmem_b_row) < 128) &&
                           (int'(enq_desc.tmem_c_row) < 128) &&
                           (int'(enq_desc.tmem_d_row) < 128) &&
                           (int'(enq_desc.tmem_a_col) < 512) &&
                           (int'(enq_desc.tmem_b_col) < 512) &&
                           (int'(enq_desc.tmem_c_col) < 512) &&
                           (int'(enq_desc.tmem_d_col) < 512);

        tile_nonempty_w = (enq_desc.tile_m >= 16'(TCU_V2_ARRAY_M)) &&
                          (enq_desc.tile_n >= 16'(TCU_V2_ARRAY_N)) &&
                          (enq_desc.tile_k >= 16'(TCU_V2_ARRAY_K));

        tile_align_ok_w = ((enq_desc.tile_m % 16'(TCU_V2_ARRAY_M)) == 16'd0) &&
                          ((enq_desc.tile_n % 16'(TCU_V2_ARRAY_N)) == 16'd0) &&
                          ((enq_desc.tile_k % 16'(TCU_V2_ARRAY_K)) == 16'd0);

        if (tcu_v2_fmt_is_mx(enq_desc.fmt_a) || tcu_v2_fmt_is_mx(enq_desc.fmt_b)) begin
            scale_match_ok_w = (enq_desc.scale_fmt != TCU_V2_SCALE_NONE);
        end else begin
            scale_match_ok_w = (enq_desc.scale_fmt == TCU_V2_SCALE_NONE);
        end

        can_accept_w = desc_legal_w && tmem_bounds_ok_w && tile_nonempty_w &&
                       tile_align_ok_w && scale_match_ok_w;
    end

    `UNUSED_VAR (peak_occupancy_r)
    `UNUSED_VAR (sparse_enq_cnt_r)
    `UNUSED_VAR (cta_pair_enq_cnt_r)
    `UNUSED_VAR (illegal_fmt_cnt_r)
    `UNUSED_VAR (illegal_dim_cnt_r)
    `UNUSED_VAR (illegal_tmem_cnt_r)
    `UNUSED_VAR (illegal_scale_cnt_r)

    assign empty         = (count_r == '0);
    assign full          = (count_r == CNT_W'(DEPTH));
    assign occupancy     = count_r;
    assign credits_avail = CNT_W'(DEPTH) - count_r;

    assign enq_ready  = !flush && (!full || deq_ready);
    assign deq_valid  = !empty;
    assign deq_desc   = mem_r[rd_ptr_r];
    assign peek_desc  = mem_r[rd_ptr_r];
    assign peek_valid = !empty;

    assign do_pop_w  = !flush && deq_valid && deq_ready;
    assign do_push_w = !flush && enq_valid && enq_ready && can_accept_w;

    always_ff @(posedge clk) begin
        if (reset) begin
            wr_ptr_r            <= '0;
            rd_ptr_r            <= '0;
            count_r             <= '0;
            accepted_cnt_r      <= 32'd0;
            rejected_cnt_r      <= 32'd0;
            flushed_cnt_r       <= 32'd0;
            reject_pulse_r      <= 1'b0;
            reject_desc_id_r    <= '0;
            peak_occupancy_r    <= '0;
            sparse_enq_cnt_r    <= 32'd0;
            cta_pair_enq_cnt_r  <= 32'd0;
            illegal_fmt_cnt_r   <= 32'd0;
            illegal_dim_cnt_r   <= 32'd0;
            illegal_tmem_cnt_r  <= 32'd0;
            illegal_scale_cnt_r <= 32'd0;
            for (int i = 0; i < DEPTH; ++i) begin
                mem_r[i] <= '0;
            end
        end else if (flush) begin
            wr_ptr_r         <= '0;
            rd_ptr_r         <= '0;
            count_r          <= '0;
            reject_pulse_r   <= 1'b0;
            flushed_cnt_r    <= flushed_cnt_r + 32'(count_r);
        end else begin
            reject_pulse_r <= 1'b0;

            if (enq_valid && enq_ready && !can_accept_w) begin
                reject_pulse_r   <= 1'b1;
                reject_desc_id_r <= enq_desc.desc_id;
                rejected_cnt_r   <= rejected_cnt_r + 32'd1;
                if (!desc_legal_w) begin
                    illegal_fmt_cnt_r <= illegal_fmt_cnt_r + 32'd1;
                end
                if (!tile_nonempty_w || !tile_align_ok_w) begin
                    illegal_dim_cnt_r <= illegal_dim_cnt_r + 32'd1;
                end
                if (!tmem_bounds_ok_w) begin
                    illegal_tmem_cnt_r <= illegal_tmem_cnt_r + 32'd1;
                end
                if (!scale_match_ok_w) begin
                    illegal_scale_cnt_r <= illegal_scale_cnt_r + 32'd1;
                end
            end

            if (do_push_w) begin
                mem_r[wr_ptr_r] <= enq_desc;
                wr_ptr_r        <= wr_ptr_r + PTR_W'(1);
                accepted_cnt_r  <= accepted_cnt_r + 32'd1;
                if (enq_desc.sparse_en) begin
                    sparse_enq_cnt_r <= sparse_enq_cnt_r + 32'd1;
                end
                if (enq_desc.cta_pair_en) begin
                    cta_pair_enq_cnt_r <= cta_pair_enq_cnt_r + 32'd1;
                end
            end

            if (do_pop_w) begin
                rd_ptr_r <= rd_ptr_r + PTR_W'(1);
            end

            case ({do_push_w, do_pop_w})
                2'b10: begin
                    count_r <= count_r + CNT_W'(1);
                    if ((count_r + CNT_W'(1)) > peak_occupancy_r) begin
                        peak_occupancy_r <= count_r + CNT_W'(1);
                    end
                end
                2'b01: begin
                    count_r <= count_r - CNT_W'(1);
                end
                default: begin
                    count_r <= count_r;
                end
            endcase
        end
    end

    assign reject_pulse       = reject_pulse_r;
    assign reject_desc_id     = reject_desc_id_r;
    assign total_accepted_cnt = accepted_cnt_r;
    assign total_rejected_cnt = rejected_cnt_r;
    assign total_flushed_cnt  = flushed_cnt_r;

endmodule
