// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_perf_mon #(
    parameter int NUM_PIPES = 1
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                clear_counters,
    input  logic                                array_busy,
    input  logic                                pipe_stall,
    input  logic                                tmem_stall,
    input  logic                                barrier_stall,
    input  logic                                cta_sync_stall,
    input  logic                                uop_issue_fire,
    input  logic                                uop_issue_sparse,
    input  logic                                uop_retire_fire,
    input  logic                                desc_done_fire,
    input  logic                                sparse_fault_pulse,
    input  logic                                fp_flags_valid,
    input  VX_tcu_v2_pkg::tcu_v2_fp_flags_t     fp_flags_in,
    input  logic [NUM_PIPES-1:0]                pipe_active_mask,
    output VX_tcu_v2_pkg::tcu_v2_perf_cnt_t     perf_cnt_out,
    output logic [31:0]                         dense_ops_cnt_out,
    output logic [31:0]                         sparse_ops_cnt_out,
    output logic [31:0]                         tmem_stall_cycles_out,
    output logic [31:0]                         barrier_stall_cycles_out,
    output logic [31:0]                         fp_nv_cnt_out,
    output logic [31:0]                         fp_of_cnt_out,
    output logic [31:0]                         fp_uf_cnt_out,
    output logic [31:0]                         fp_nx_cnt_out,
    output logic [NUM_PIPES-1:0][31:0]          pipe_busy_cycles_out
);

    import VX_tcu_v2_pkg::*;

    tcu_v2_perf_cnt_t               perf_r;
    logic [31:0]                    dense_ops_r;
    logic [31:0]                    sparse_ops_r;
    logic [31:0]                    tmem_stall_r;
    logic [31:0]                    barrier_stall_r;
    logic [31:0]                    pipe_stall_r;
    logic [31:0]                    idle_cycles_r;
    logic [31:0]                    total_cycles_r;
    logic [31:0]                    fp_nv_r;
    logic [31:0]                    fp_dz_r;
    logic [31:0]                    fp_of_r;
    logic [31:0]                    fp_uf_r;
    logic [31:0]                    fp_nx_r;
    logic [31:0]                    window_cycles_r;
    logic [31:0]                    window_uops_r;
    logic [31:0]                    last_window_uops_r;
    logic [31:0]                    peak_window_uops_r;
    logic [NUM_PIPES-1:0][31:0]     pipe_busy_r;

    localparam logic [31:0] PMU_WINDOW_PERIOD = 32'd1024;

    function automatic logic [31:0] sat_inc32(
        input logic [31:0] val
    );
        return (val == 32'hFFFF_FFFF) ? val : (val + 32'd1);
    endfunction

    always_ff @(posedge clk) begin
        if (reset || clear_counters) begin
            perf_r             <= '0;
            dense_ops_r        <= 32'd0;
            sparse_ops_r       <= 32'd0;
            tmem_stall_r       <= 32'd0;
            barrier_stall_r    <= 32'd0;
            pipe_stall_r       <= 32'd0;
            idle_cycles_r      <= 32'd0;
            total_cycles_r     <= 32'd0;
            fp_nv_r            <= 32'd0;
            fp_dz_r            <= 32'd0;
            fp_of_r            <= 32'd0;
            fp_uf_r            <= 32'd0;
            fp_nx_r            <= 32'd0;
            window_cycles_r    <= 32'd0;
            window_uops_r      <= 32'd0;
            last_window_uops_r <= 32'd0;
            peak_window_uops_r <= 32'd0;
            pipe_busy_r        <= '0;
        end else begin
            total_cycles_r <= sat_inc32(total_cycles_r);

            if (array_busy) begin
                perf_r.active_cycles <= sat_inc32(perf_r.active_cycles);
            end else if (!pipe_stall && !tmem_stall && !barrier_stall && !cta_sync_stall) begin
                idle_cycles_r <= sat_inc32(idle_cycles_r);
            end

            if (pipe_stall) begin
                pipe_stall_r <= sat_inc32(pipe_stall_r);
            end

            if (pipe_stall || tmem_stall || barrier_stall) begin
                perf_r.stall_cycles <= sat_inc32(perf_r.stall_cycles);
            end

            if (tmem_stall) begin
                tmem_stall_r <= sat_inc32(tmem_stall_r);
            end

            if (barrier_stall) begin
                barrier_stall_r <= sat_inc32(barrier_stall_r);
            end

            if (cta_sync_stall) begin
                perf_r.cta_wait_cycles <= sat_inc32(perf_r.cta_wait_cycles);
            end

            if (uop_issue_fire) begin
                perf_r.uops_issued <= sat_inc32(perf_r.uops_issued);
                if (uop_issue_sparse) begin
                    perf_r.sparse_uops <= sat_inc32(perf_r.sparse_uops);
                    sparse_ops_r       <= sat_inc32(sparse_ops_r);
                end else begin
                    dense_ops_r <= sat_inc32(dense_ops_r);
                end
            end

            if (uop_retire_fire) begin
                perf_r.uops_retired <= sat_inc32(perf_r.uops_retired);
            end

            if (desc_done_fire) begin
                perf_r.descs_completed <= sat_inc32(perf_r.descs_completed);
            end

            if (sparse_fault_pulse) begin
                perf_r.sparse_faults <= sat_inc32(perf_r.sparse_faults);
            end

            if ((window_cycles_r + 32'd1) >= PMU_WINDOW_PERIOD) begin
                logic [31:0] next_win_uops;
                next_win_uops      = window_uops_r + {31'd0, uop_issue_fire};
                last_window_uops_r <= next_win_uops;
                if (next_win_uops > peak_window_uops_r) begin
                    peak_window_uops_r <= next_win_uops;
                end
                window_cycles_r <= 32'd0;
                window_uops_r   <= 32'd0;
            end else begin
                window_cycles_r <= window_cycles_r + 32'd1;
                if (uop_issue_fire) begin
                    window_uops_r <= window_uops_r + 32'd1;
                end
            end

            if (fp_flags_valid) begin
                if (fp_flags_in.nv) begin
                    fp_nv_r <= sat_inc32(fp_nv_r);
                end
                if (fp_flags_in.dz) begin
                    fp_dz_r <= sat_inc32(fp_dz_r);
                end
                if (fp_flags_in.of) begin
                    fp_of_r <= sat_inc32(fp_of_r);
                end
                if (fp_flags_in.uf) begin
                    fp_uf_r <= sat_inc32(fp_uf_r);
                end
                if (fp_flags_in.nx) begin
                    fp_nx_r <= sat_inc32(fp_nx_r);
                end
            end

            for (int p = 0; p < NUM_PIPES; ++p) begin
                if (pipe_active_mask[p]) begin
                    pipe_busy_r[p] <= sat_inc32(pipe_busy_r[p]);
                end
            end
        end
    end

    `UNUSED_VAR (pipe_stall_r)
    `UNUSED_VAR (idle_cycles_r)
    `UNUSED_VAR (total_cycles_r)
    `UNUSED_VAR (last_window_uops_r)
    `UNUSED_VAR (peak_window_uops_r)
    `UNUSED_VAR (fp_dz_r)

    assign perf_cnt_out             = perf_r;
    assign dense_ops_cnt_out        = dense_ops_r;
    assign sparse_ops_cnt_out       = sparse_ops_r;
    assign tmem_stall_cycles_out    = tmem_stall_r;
    assign barrier_stall_cycles_out = barrier_stall_r;
    assign fp_nv_cnt_out            = fp_nv_r;
    assign fp_of_cnt_out            = fp_of_r;
    assign fp_uf_cnt_out            = fp_uf_r;
    assign fp_nx_cnt_out            = fp_nx_r;
    assign pipe_busy_cycles_out     = pipe_busy_r;

endmodule
