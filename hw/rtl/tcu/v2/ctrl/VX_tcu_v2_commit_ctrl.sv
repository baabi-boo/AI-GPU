// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_commit_ctrl #(
    parameter int DEPTH = VX_tcu_v2_pkg::TCU_V2_DESC_Q_DEPTH
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                enq_valid,
    output logic                                enq_ready,
    input  logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] enq_desc_id,
    input  logic                                enq_tmem_wb_en,
    input  logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0] enq_barrier_id,
    input  logic                                enq_barrier_phase,
    input  logic [15:0]                         enq_uop_total,
    input  logic                                uop_wb_valid,
    input  logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] uop_wb_desc_id,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t     uop_wb_flags,
    input  logic                                fence_req,
    output logic                                fence_done,
    output logic                                commit_valid,
    input  logic                                commit_ready,
    output logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] commit_desc_id,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t     commit_flags,
    output logic                                commit_bar_arrive,
    output logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0] commit_bar_id,
    output logic                                commit_bar_phase,
    output logic                                rob_empty,
    output logic                                rob_full,
    output logic [$clog2(DEPTH+1)-1:0]          rob_count,
    output logic [31:0]                         committed_cnt_out,
    output logic [31:0]                         fence_cycles_out
);

    import VX_tcu_v2_pkg::*;

    localparam int PTR_W = $clog2(DEPTH);
    localparam int CNT_W = $clog2(DEPTH + 1);

    typedef struct packed {
        logic                           valid;
        logic                           complete;
        logic                           tmem_wb_en;
        logic [TCU_V2_DESC_ID_W-1:0]    desc_id;
        logic [TCU_V2_BARRIER_ID_W-1:0] barrier_id;
        logic                           barrier_phase;
        logic [15:0]                    uop_total;
        logic [15:0]                    uop_done;
        logic [31:0]                    enq_cycle;
        tcu_v2_fp_flags_t               acc_flags;
    } rob_entry_t;

    rob_entry_t [DEPTH-1:0]     rob_r;
    logic [PTR_W-1:0]           head_r;
    logic [PTR_W-1:0]           tail_r;
    logic [CNT_W-1:0]           count_r;
    logic [CNT_W-1:0]           peak_rob_cnt_r;
    logic [31:0]                cycle_cnt_r;
    logic [31:0]                committed_cnt_r;
    logic [31:0]                fence_cycles_r;
    logic [31:0]                last_latency_r;
    logic [31:0]                max_latency_r;
    logic [31:0]                bar_arrive_cnt_r;
    logic                       fence_active_r;

    logic                       do_enq_w;
    logic                       do_commit_w;
    logic                       head_ready_w;

    `UNUSED_VAR (peak_rob_cnt_r)
    `UNUSED_VAR (last_latency_r)
    `UNUSED_VAR (max_latency_r)
    `UNUSED_VAR (bar_arrive_cnt_r)

    assign rob_empty    = (count_r == '0);
    assign rob_full     = (count_r == CNT_W'(DEPTH));
    assign rob_count    = count_r;
    assign enq_ready    = !rob_full && !fence_active_r;
    assign head_ready_w = !rob_empty && rob_r[head_r].valid && rob_r[head_r].complete;

    assign commit_valid      = head_ready_w;
    assign commit_desc_id    = rob_r[head_r].desc_id;
    assign commit_flags      = rob_r[head_r].acc_flags;
    assign commit_bar_arrive = head_ready_w && rob_r[head_r].tmem_wb_en;
    assign commit_bar_id     = rob_r[head_r].barrier_id;
    assign commit_bar_phase  = rob_r[head_r].barrier_phase;
    assign fence_done        = fence_active_r && rob_empty;
    assign committed_cnt_out = committed_cnt_r;
    assign fence_cycles_out  = fence_cycles_r;

    assign do_enq_w    = enq_valid && enq_ready;
    assign do_commit_w = commit_valid && commit_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            head_r           <= '0;
            tail_r           <= '0;
            count_r          <= '0;
            peak_rob_cnt_r   <= '0;
            cycle_cnt_r      <= 32'd0;
            committed_cnt_r  <= 32'd0;
            fence_cycles_r   <= 32'd0;
            last_latency_r   <= 32'd0;
            max_latency_r    <= 32'd0;
            bar_arrive_cnt_r <= 32'd0;
            fence_active_r   <= 1'b0;
            for (int i = 0; i < DEPTH; ++i) begin
                rob_r[i] <= '0;
            end
        end else begin
            cycle_cnt_r <= cycle_cnt_r + 32'd1;

            if (fence_req && !rob_empty) begin
                fence_active_r <= 1'b1;
            end else if (fence_active_r && rob_empty) begin
                fence_active_r <= 1'b0;
            end

            if (fence_active_r && !rob_empty) begin
                fence_cycles_r <= fence_cycles_r + 32'd1;
            end

            if (uop_wb_valid) begin
                for (int i = 0; i < DEPTH; ++i) begin
                    if (rob_r[i].valid && (rob_r[i].desc_id == uop_wb_desc_id)) begin
                        logic [15:0] next_done;
                        next_done              = rob_r[i].uop_done + 16'd1;
                        rob_r[i].uop_done     <= next_done;
                        rob_r[i].acc_flags    <= tcu_v2_flags_or(rob_r[i].acc_flags, uop_wb_flags);
                        if (next_done >= rob_r[i].uop_total) begin
                            rob_r[i].complete <= 1'b1;
                        end
                    end
                end
            end

            if (do_enq_w) begin
                rob_r[tail_r].valid         <= 1'b1;
                rob_r[tail_r].complete      <= (enq_uop_total == 16'd0);
                rob_r[tail_r].tmem_wb_en    <= enq_tmem_wb_en;
                rob_r[tail_r].desc_id       <= enq_desc_id;
                rob_r[tail_r].barrier_id    <= enq_barrier_id;
                rob_r[tail_r].barrier_phase <= enq_barrier_phase;
                rob_r[tail_r].uop_total     <= (enq_uop_total == 16'd0) ? 16'd1 : enq_uop_total;
                rob_r[tail_r].uop_done      <= 16'd0;
                rob_r[tail_r].enq_cycle     <= cycle_cnt_r;
                rob_r[tail_r].acc_flags     <= '0;
                tail_r                      <= tail_r + PTR_W'(1);
            end

            if (do_commit_w) begin
                logic [31:0] lat;
                lat = cycle_cnt_r - rob_r[head_r].enq_cycle;
                last_latency_r         <= lat;
                if (lat > max_latency_r) begin
                    max_latency_r <= lat;
                end
                if (rob_r[head_r].tmem_wb_en) begin
                    bar_arrive_cnt_r <= bar_arrive_cnt_r + 32'd1;
                end
                rob_r[head_r].valid    <= 1'b0;
                rob_r[head_r].complete <= 1'b0;
                head_r                 <= head_r + PTR_W'(1);
                committed_cnt_r        <= committed_cnt_r + 32'd1;
            end

            case ({do_enq_w, do_commit_w})
                2'b10: begin
                    count_r <= count_r + CNT_W'(1);
                    if ((count_r + CNT_W'(1)) > peak_rob_cnt_r) begin
                        peak_rob_cnt_r <= count_r + CNT_W'(1);
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

endmodule
