// SPDX-License-Identifier: Apache-2.0
module VX_tmem_wait_barrier
    import VX_tmem_pkg::*;
#(
    parameter int MAX_REGIONS     = TMEM_MAX_REGIONS,
    parameter int NUM_WARPS       = 32,
    parameter int NUM_BARRIERS    = 16,
    parameter int TIMEOUT_CYCLES  = 4096
) (
    input  logic                                clk,
    input  logic                                reset,
    // Async operation launch & retirement tracking (3 independent parallel client channels)
    input  logic                                ld_launch_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_launch_region_id,
    input  logic [4:0]                          ld_launch_warp_id,
    input  logic                                st_launch_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         st_launch_region_id,
    input  logic [4:0]                          st_launch_warp_id,
    input  logic                                mma_launch_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         mma_launch_region_id,
    input  logic [4:0]                          mma_launch_warp_id,
    input  logic                                ld_retire_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         ld_retire_region_id,
    input  logic [4:0]                          ld_retire_warp_id,
    input  logic                                st_retire_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         st_retire_region_id,
    input  logic [4:0]                          st_retire_warp_id,
    input  logic                                mma_retire_valid,
    input  logic [TMEM_REGION_ID_W-1:0]         mma_retire_region_id,
    input  logic [4:0]                          mma_retire_warp_id,
    // Hazard unit drained status
    input  logic                                hazard_drained,
    // Wait / Fence request channel
    input  logic                                wait_req_valid,
    output logic                                wait_req_ready,
    input  tmem_op_e                            wait_req_op,
    input  logic [TMEM_TAG_W-1:0]               wait_req_tag,
    input  logic [TMEM_REGION_ID_W-1:0]         wait_req_region_id,
    input  logic [4:0]                          wait_req_warp_id,
    input  logic                                wait_req_scope_warp, // 1=per-warp, 0=per-region
    input  logic [TMEM_BARRIER_ID_W-1:0]        wait_req_barrier_id,
    input  logic                                wait_req_barrier_phase,
    // 2-CTA peer barrier arrival input
    input  logic                                peer_bar_valid,
    output logic                                peer_bar_ready,
    input  logic [TMEM_BARRIER_ID_W-1:0]        peer_bar_id,
    input  logic                                peer_bar_phase,
    // Local barrier wakeup broadcast output
    output logic                                bar_wakeup_valid,
    output logic [TMEM_BARRIER_ID_W-1:0]        bar_wakeup_id,
    output logic                                bar_wakeup_phase,
    // Wait / Fence completion response (registered)
    output logic                                wait_rsp_valid,
    input  logic                                wait_rsp_ready,
    output tmem_op_e                            wait_rsp_op,
    output logic [TMEM_TAG_W-1:0]               wait_rsp_tag,
    output tmem_status_e                        wait_rsp_status,
    output logic                                deadlock_fault_out,
    // Per-region / per-warp counters & telemetry
    output logic [MAX_REGIONS-1:0][7:0]         region_outstanding_out,
    output logic [NUM_WARPS-1:0][7:0]           warp_outstanding_out,
    output logic [7:0]                          current_epoch_out,
    output logic [31:0]                         wait_cycles_out,
    output logic [31:0]                         fence_completed_out,
    output logic [31:0]                         timeout_faults_out
);

    typedef enum logic [1:0] {
        WB_IDLE = 2'd0,
        WB_WAIT = 2'd1,
        WB_DONE = 2'd2
    } wb_state_e;

    typedef struct packed {
        tmem_op_e                     op;
        logic [TMEM_TAG_W-1:0]        tag;
        logic [TMEM_REGION_ID_W-1:0]  region_id;
        logic [4:0]                   warp_id;
        logic                         scope_warp;
        logic [TMEM_BARRIER_ID_W-1:0] barrier_id;
        logic                         barrier_phase;
    } wait_desc_t;

    wb_state_e                              state_q, state_d;
    wait_desc_t                             active_wait_q, active_wait_d;
    logic [MAX_REGIONS-1:0][7:0]            reg_cnt_q, reg_cnt_d;
    logic [NUM_WARPS-1:0][7:0]              warp_cnt_q, warp_cnt_d;
    logic [NUM_BARRIERS-1:0]                local_bar_phase_q, local_bar_phase_d;
    logic [NUM_BARRIERS-1:0]                peer_bar_phase_q, peer_bar_phase_d;
    logic [7:0]                             epoch_q, epoch_d;
    logic [15:0]                            wait_timer_q, wait_timer_d;
    logic                                   timed_out_q, timed_out_d;

    logic                                   bar_wakeup_valid_q, bar_wakeup_valid_d;
    logic [TMEM_BARRIER_ID_W-1:0]           bar_wakeup_id_q, bar_wakeup_id_d;
    logic                                   bar_wakeup_phase_q, bar_wakeup_phase_d;

    logic                                   wait_rsp_valid_q, wait_rsp_valid_d;
    tmem_op_e                               wait_rsp_op_q, wait_rsp_op_d;
    logic [TMEM_TAG_W-1:0]                  wait_rsp_tag_q, wait_rsp_tag_d;
    tmem_status_e                           wait_rsp_status_q, wait_rsp_status_d;
    logic                                   deadlock_fault_q, deadlock_fault_d;

    logic [31:0]                            wait_cycles_q, wait_cycles_d;
    logic [31:0]                            fence_completed_q, fence_completed_d;
    logic [31:0]                            timeout_faults_q, timeout_faults_d;

    assign wait_req_ready = !reset && (state_q == WB_IDLE) && (!wait_rsp_valid_q || wait_rsp_ready);
    assign peer_bar_ready = !reset;

    // Outstanding op tracking, wait/fence resolution, and barrier phase synchronization
    always_comb begin
        logic        cond_met;
        logic        total_zero;
        logic        region_zero;
        logic        warp_zero;
        logic        barrier_matched;
        logic [15:0] total_outstanding;

        state_d            = state_q;
        active_wait_d      = active_wait_q;
        reg_cnt_d          = reg_cnt_q;
        warp_cnt_d         = warp_cnt_q;
        local_bar_phase_d  = local_bar_phase_q;
        peer_bar_phase_d   = peer_bar_phase_q;
        epoch_d            = epoch_q;
        wait_timer_d       = wait_timer_q;
        timed_out_d        = timed_out_q;

        bar_wakeup_valid_d = 1'b0;
        bar_wakeup_id_d    = bar_wakeup_id_q;
        bar_wakeup_phase_d = bar_wakeup_phase_q;

        wait_rsp_valid_d   = wait_rsp_valid_q;
        wait_rsp_op_d      = wait_rsp_op_q;
        wait_rsp_tag_d     = wait_rsp_tag_q;
        wait_rsp_status_d  = wait_rsp_status_q;
        deadlock_fault_d   = deadlock_fault_q;

        wait_cycles_d      = wait_cycles_q;
        fence_completed_d  = fence_completed_q;
        timeout_faults_d   = timeout_faults_q;

        if (wait_rsp_valid_q && wait_rsp_ready) begin
            wait_rsp_valid_d = 1'b0;
        end

        // Atomically accumulate all simultaneous launches & retirements per region
        for (int r = 0; r < MAX_REGIONS; ++r) begin
            logic signed [3:0] reg_delta;
            logic signed [9:0] reg_next;
            reg_delta = 4'sd0;
            if (ld_launch_valid && (int'(ld_launch_region_id) == r)) begin
                reg_delta = reg_delta + 4'sd1;
            end
            if (st_launch_valid && (int'(st_launch_region_id) == r)) begin
                reg_delta = reg_delta + 4'sd1;
            end
            if (mma_launch_valid && (int'(mma_launch_region_id) == r)) begin
                reg_delta = reg_delta + 4'sd1;
            end
            if (ld_retire_valid && (int'(ld_retire_region_id) == r)) begin
                reg_delta = reg_delta - 4'sd1;
            end
            if (st_retire_valid && (int'(st_retire_region_id) == r)) begin
                reg_delta = reg_delta - 4'sd1;
            end
            if (mma_retire_valid && (int'(mma_retire_region_id) == r)) begin
                reg_delta = reg_delta - 4'sd1;
            end
            reg_next = $signed({2'b00, reg_cnt_q[r]}) + {{6{reg_delta[3]}}, reg_delta};
            if (reg_next <= 10'sd0) begin
                reg_cnt_d[r] = 8'd0;
            end else if (reg_next >= 10'sd255) begin
                reg_cnt_d[r] = 8'hFF;
            end else begin
                reg_cnt_d[r] = reg_next[7:0];
            end
        end

        // Atomically accumulate all simultaneous launches & retirements per warp
        for (int w = 0; w < NUM_WARPS; ++w) begin
            logic signed [3:0] warp_delta;
            logic signed [9:0] warp_next;
            warp_delta = 4'sd0;
            if (ld_launch_valid && (int'(ld_launch_warp_id) == w)) begin
                warp_delta = warp_delta + 4'sd1;
            end
            if (st_launch_valid && (int'(st_launch_warp_id) == w)) begin
                warp_delta = warp_delta + 4'sd1;
            end
            if (mma_launch_valid && (int'(mma_launch_warp_id) == w)) begin
                warp_delta = warp_delta + 4'sd1;
            end
            if (ld_retire_valid && (int'(ld_retire_warp_id) == w)) begin
                warp_delta = warp_delta - 4'sd1;
            end
            if (st_retire_valid && (int'(st_retire_warp_id) == w)) begin
                warp_delta = warp_delta - 4'sd1;
            end
            if (mma_retire_valid && (int'(mma_retire_warp_id) == w)) begin
                warp_delta = warp_delta - 4'sd1;
            end
            warp_next = $signed({2'b00, warp_cnt_q[w]}) + {{6{warp_delta[3]}}, warp_delta};
            if (warp_next <= 10'sd0) begin
                warp_cnt_d[w] = 8'd0;
            end else if (warp_next >= 10'sd255) begin
                warp_cnt_d[w] = 8'hFF;
            end else begin
                warp_cnt_d[w] = warp_next[7:0];
            end
        end

        if (ld_retire_valid || st_retire_valid || mma_retire_valid) begin
            epoch_d = epoch_q +
                      {6'd0, {1'b0, ld_retire_valid} + {1'b0, st_retire_valid} + {1'b0, mma_retire_valid}};
        end

        // Record incoming peer CTA barrier arrival phase
        if (peer_bar_valid && peer_bar_ready) begin
            peer_bar_phase_d[peer_bar_id] = peer_bar_phase;
        end

        total_outstanding = 16'd0;
        for (int r = 0; r < MAX_REGIONS; ++r) begin
            total_outstanding = total_outstanding + {8'd0, reg_cnt_d[r]};
        end

        total_zero      = (total_outstanding == 16'd0) && hazard_drained;
        region_zero     = (reg_cnt_d[active_wait_q.region_id] == 8'd0);
        warp_zero       = (warp_cnt_d[active_wait_q.warp_id] == 8'd0);
        barrier_matched = (peer_bar_phase_d[active_wait_q.barrier_id] ==
                           active_wait_q.barrier_phase);

        case (state_q)
            WB_IDLE: begin
                wait_timer_d = 16'd0;
                timed_out_d  = 1'b0;
                if (wait_req_valid && wait_req_ready) begin
                    active_wait_d.op            = wait_req_op;
                    active_wait_d.tag           = wait_req_tag;
                    active_wait_d.region_id     = wait_req_region_id;
                    active_wait_d.warp_id       = wait_req_warp_id;
                    active_wait_d.scope_warp    = wait_req_scope_warp;
                    active_wait_d.barrier_id    = wait_req_barrier_id;
                    active_wait_d.barrier_phase = wait_req_barrier_phase;
                    local_bar_phase_d[wait_req_barrier_id] = wait_req_barrier_phase;
                    state_d = WB_WAIT;
                end
            end

            WB_WAIT: begin
                if (active_wait_q.op == TMEM_OP_FENCE) begin
                    cond_met = active_wait_q.scope_warp
                               ? (warp_zero && hazard_drained)
                               : (active_wait_q.region_id == 4'd0 ? total_zero : (region_zero && hazard_drained));
                end else begin
                    // TMEM_OP_WAIT checks scoped outstanding ops + barrier phase match
                    cond_met = (active_wait_q.scope_warp ? warp_zero : region_zero) &&
                               (barrier_matched || (active_wait_q.barrier_id == 4'd0));
                end

                if (cond_met) begin
                    timed_out_d = 1'b0;
                    state_d     = WB_DONE;
                end else if (wait_timer_q >= 16'(TIMEOUT_CYCLES)) begin
                    timed_out_d      = 1'b1;
                    deadlock_fault_d = 1'b1;
                    timeout_faults_d = timeout_faults_q + 32'd1;
                    state_d          = WB_DONE;
                end else begin
                    wait_timer_d  = wait_timer_q + 16'd1;
                    wait_cycles_d = wait_cycles_q + 32'd1;
                end
            end

            WB_DONE: begin
                if (!wait_rsp_valid_q || wait_rsp_ready) begin
                    wait_rsp_valid_d   = 1'b1;
                    wait_rsp_op_d      = active_wait_q.op;
                    wait_rsp_tag_d     = active_wait_q.tag;
                    wait_rsp_status_d  = timed_out_q ? TMEM_STATUS_FULL : TMEM_STATUS_OK;
                    bar_wakeup_valid_d = ~timed_out_q;
                    bar_wakeup_id_d    = active_wait_q.barrier_id;
                    bar_wakeup_phase_d = active_wait_q.barrier_phase;
                    fence_completed_d  = fence_completed_q + 32'd1;
                    state_d            = WB_IDLE;
                end
            end

            default: begin
                state_d = WB_IDLE;
            end
        endcase
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            state_q            <= WB_IDLE;
            active_wait_q      <= '0;
            reg_cnt_q          <= '0;
            warp_cnt_q         <= '0;
            local_bar_phase_q  <= '0;
            peer_bar_phase_q   <= '0;
            epoch_q            <= 8'd0;
            wait_timer_q       <= 16'd0;
            timed_out_q        <= 1'b0;
            bar_wakeup_valid_q <= 1'b0;
            bar_wakeup_id_q    <= '0;
            bar_wakeup_phase_q <= 1'b0;
            wait_rsp_valid_q   <= 1'b0;
            wait_rsp_op_q      <= TMEM_OP_NOP;
            wait_rsp_tag_q     <= '0;
            wait_rsp_status_q  <= TMEM_STATUS_OK;
            deadlock_fault_q   <= 1'b0;
            wait_cycles_q      <= 32'd0;
            fence_completed_q  <= 32'd0;
            timeout_faults_q   <= 32'd0;
        end else begin
            state_q            <= state_d;
            active_wait_q      <= active_wait_d;
            reg_cnt_q          <= reg_cnt_d;
            warp_cnt_q         <= warp_cnt_d;
            local_bar_phase_q  <= local_bar_phase_d;
            peer_bar_phase_q   <= peer_bar_phase_d;
            epoch_q            <= epoch_d;
            wait_timer_q       <= wait_timer_d;
            timed_out_q        <= timed_out_d;
            bar_wakeup_valid_q <= bar_wakeup_valid_d;
            bar_wakeup_id_q    <= bar_wakeup_id_d;
            bar_wakeup_phase_q <= bar_wakeup_phase_d;
            wait_rsp_valid_q   <= wait_rsp_valid_d;
            wait_rsp_op_q      <= wait_rsp_op_d;
            wait_rsp_tag_q     <= wait_rsp_tag_d;
            wait_rsp_status_q  <= wait_rsp_status_d;
            deadlock_fault_q   <= deadlock_fault_d;
            wait_cycles_q      <= wait_cycles_d;
            fence_completed_q  <= fence_completed_d;
            timeout_faults_q   <= timeout_faults_d;
        end
    end

    assign bar_wakeup_valid       = bar_wakeup_valid_q;
    assign bar_wakeup_id          = bar_wakeup_id_q;
    assign bar_wakeup_phase       = bar_wakeup_phase_q;
    assign wait_rsp_valid         = wait_rsp_valid_q;
    assign wait_rsp_op            = wait_rsp_op_q;
    assign wait_rsp_tag           = wait_rsp_tag_q;
    assign wait_rsp_status        = wait_rsp_status_q;
    assign deadlock_fault_out     = deadlock_fault_q;
    assign region_outstanding_out = reg_cnt_q;
    assign warp_outstanding_out   = warp_cnt_q;
    assign current_epoch_out      = epoch_q;
    assign wait_cycles_out        = wait_cycles_q;
    assign fence_completed_out    = fence_completed_q;
    assign timeout_faults_out     = timeout_faults_q;

endmodule
