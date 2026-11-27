// SPDX-License-Identifier: Apache-2.0
module VX_tmem_perf_mon
    import VX_tmem_pkg::*;
#(
    parameter int LANES = 8
) (
    input  logic                        clk,
    input  logic                        reset,
    input  logic                        clear_counters,
    // Bank port activity inputs
    input  logic [LANES-1:0]            rd_a_fire,
    input  logic [LANES-1:0]            rd_b_fire,
    input  logic [LANES-1:0]            wr_fire,
    input  logic [5:0]                  rd_a_conflict_ways,
    input  logic [5:0]                  rd_b_conflict_ways,
    input  logic [5:0]                  wr_conflict_ways,
    // Controller subunit telemetry inputs
    input  logic                        arb_conflict_stall,
    input  logic                        hazard_stall,
    input  logic                        wait_stall,
    input  logic                        alloc_fire,
    input  logic                        dealloc_fire,
    input  logic                        scrub_fire,
    input  logic [4:0]                  occupied_granules_in,
    input  logic [31:0]                 ecc_ce_total_in,
    input  logic [31:0]                 ecc_ue_total_in,
    input  logic [31:0]                 oob_fault_total_in,
    // Registered telemetry outputs
    output tmem_perf_cnt_t              perf_cnt_out,
    output logic [31:0]                 rd_a_beats_out,
    output logic [31:0]                 rd_b_beats_out,
    output logic [31:0]                 wr_beats_out,
    output logic [31:0]                 hazard_stall_cycles_out,
    output logic [4:0]                  alloc_util_peak_out,
    output logic [31:0]                 ecc_ce_snap_out,
    output logic [31:0]                 ecc_ue_snap_out,
    output logic [31:0]                 oob_faults_snap_out,
    output logic [31:0]                 active_cycles_out
);

    tmem_perf_cnt_t perf_cnt_q, perf_cnt_d;
    logic [31:0]    rd_a_beats_q, rd_a_beats_d;
    logic [31:0]    rd_b_beats_q, rd_b_beats_d;
    logic [31:0]    wr_beats_q, wr_beats_d;
    logic [31:0]    hazard_stall_cycles_q, hazard_stall_cycles_d;
    logic [4:0]     alloc_util_peak_q, alloc_util_peak_d;
    logic [31:0]    ecc_ce_snap_q, ecc_ce_snap_d;
    logic [31:0]    ecc_ue_snap_q, ecc_ue_snap_d;
    logic [31:0]    oob_faults_snap_q, oob_faults_snap_d;
    logic [31:0]    active_cycles_q, active_cycles_d;

    function automatic logic [3:0] popcount_lanes(
        input logic [LANES-1:0] mask
    );
        logic [3:0] cnt;
        cnt = 4'd0;
        for (int i = 0; i < LANES; ++i) begin
            cnt = cnt + {3'd0, mask[i]};
        end
        return cnt;
    endfunction

    always_comb begin
        logic [3:0] rda_lanes;
        logic [3:0] rdb_lanes;
        logic [3:0] wr_lanes;
        logic       any_conflict;
        logic       any_activity;

        rda_lanes    = popcount_lanes(rd_a_fire);
        rdb_lanes    = popcount_lanes(rd_b_fire);
        wr_lanes     = popcount_lanes(wr_fire);
        any_conflict = arb_conflict_stall ||
                       (rd_a_conflict_ways > 6'd1) ||
                       (rd_b_conflict_ways > 6'd1) ||
                       (wr_conflict_ways > 6'd1);
        any_activity = (rda_lanes != 4'd0) || (rdb_lanes != 4'd0) || (wr_lanes != 4'd0) ||
                       hazard_stall || wait_stall || alloc_fire || dealloc_fire || scrub_fire;

        if (clear_counters) begin
            perf_cnt_d            = '0;
            rd_a_beats_d          = 32'd0;
            rd_b_beats_d          = 32'd0;
            wr_beats_d            = 32'd0;
            hazard_stall_cycles_d = 32'd0;
            alloc_util_peak_d     = occupied_granules_in;
            ecc_ce_snap_d         = ecc_ce_total_in;
            ecc_ue_snap_d         = ecc_ue_total_in;
            oob_faults_snap_d     = oob_fault_total_in;
            active_cycles_d       = 32'd0;
        end else begin
            perf_cnt_d.rd_a_ops          = perf_cnt_q.rd_a_ops + ((rda_lanes != 4'd0) ? 32'd1 : 32'd0);
            perf_cnt_d.rd_b_ops          = perf_cnt_q.rd_b_ops + ((rdb_lanes != 4'd0) ? 32'd1 : 32'd0);
            perf_cnt_d.wr_ops            = perf_cnt_q.wr_ops   + ((wr_lanes  != 4'd0) ? 32'd1 : 32'd0);
            perf_cnt_d.conflict_cycles   = perf_cnt_q.conflict_cycles + (any_conflict ? 32'd1 : 32'd0);
            perf_cnt_d.fence_wait_cycles = perf_cnt_q.fence_wait_cycles + (wait_stall ? 32'd1 : 32'd0);
            perf_cnt_d.alloc_ops         = perf_cnt_q.alloc_ops   + (alloc_fire ? 32'd1 : 32'd0);
            perf_cnt_d.dealloc_ops       = perf_cnt_q.dealloc_ops + (dealloc_fire ? 32'd1 : 32'd0);
            perf_cnt_d.scrub_ops         = perf_cnt_q.scrub_ops   + (scrub_fire ? 32'd1 : 32'd0);

            rd_a_beats_d          = rd_a_beats_q + {28'd0, rda_lanes};
            rd_b_beats_d          = rd_b_beats_q + {28'd0, rdb_lanes};
            wr_beats_d            = wr_beats_q   + {28'd0, wr_lanes};
            hazard_stall_cycles_d = hazard_stall_cycles_q + (hazard_stall ? 32'd1 : 32'd0);
            alloc_util_peak_d     = (occupied_granules_in > alloc_util_peak_q)
                                    ? occupied_granules_in : alloc_util_peak_q;
            ecc_ce_snap_d         = ecc_ce_total_in;
            ecc_ue_snap_d         = ecc_ue_total_in;
            oob_faults_snap_d     = oob_fault_total_in;
            active_cycles_d       = active_cycles_q + (any_activity ? 32'd1 : 32'd0);
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            perf_cnt_q            <= '0;
            rd_a_beats_q          <= 32'd0;
            rd_b_beats_q          <= 32'd0;
            wr_beats_q            <= 32'd0;
            hazard_stall_cycles_q <= 32'd0;
            alloc_util_peak_q     <= 5'd0;
            ecc_ce_snap_q         <= 32'd0;
            ecc_ue_snap_q         <= 32'd0;
            oob_faults_snap_q     <= 32'd0;
            active_cycles_q       <= 32'd0;
        end else begin
            perf_cnt_q            <= perf_cnt_d;
            rd_a_beats_q          <= rd_a_beats_d;
            rd_b_beats_q          <= rd_b_beats_d;
            wr_beats_q            <= wr_beats_d;
            hazard_stall_cycles_q <= hazard_stall_cycles_d;
            alloc_util_peak_q     <= alloc_util_peak_d;
            ecc_ce_snap_q         <= ecc_ce_snap_d;
            ecc_ue_snap_q         <= ecc_ue_snap_d;
            oob_faults_snap_q     <= oob_faults_snap_d;
            active_cycles_q       <= active_cycles_d;
        end
    end

    assign perf_cnt_out            = perf_cnt_q;
    assign rd_a_beats_out          = rd_a_beats_q;
    assign rd_b_beats_out          = rd_b_beats_q;
    assign wr_beats_out            = wr_beats_q;
    assign hazard_stall_cycles_out = hazard_stall_cycles_q;
    assign alloc_util_peak_out     = alloc_util_peak_q;
    assign ecc_ce_snap_out         = ecc_ce_snap_q;
    assign ecc_ue_snap_out         = ecc_ue_snap_q;
    assign oob_faults_snap_out     = oob_faults_snap_q;
    assign active_cycles_out       = active_cycles_q;

endmodule
