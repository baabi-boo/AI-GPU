// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_ARRAY_CTRL_SV
`define VX_TCU_V2_ARRAY_CTRL_SV

`include "VX_platform.vh"

module VX_tcu_v2_array_ctrl #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N
) (
    input  logic                            clk,
    input  logic                            reset,
    // Upstream UOP Dispatch Handshake
    input  logic                            uop_valid,
    output logic                            uop_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t      uop_in,
    // Operand Double-Buffer Coordination
    output logic                            dbuf_load_valid,
    input  logic                            dbuf_load_ready,
    output logic                            dbuf_swap_req,
    input  logic                            dbuf_swap_ack,
    input  logic                            dbuf_exec_valid,
    output logic                            dbuf_exec_ready,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t      dbuf_exec_uop,
    // Scale Fabric & PE Array Issue Coordination
    output logic                            issue_valid,
    input  logic                            issue_ready,
    input  logic                            pe_wb_valid,
    output logic                            pe_wb_ready,
    // Accumulator Tile Bank Coordination
    output logic                            acc_preload_valid,
    output logic                            acc_preload_use_c,
    output logic                            acc_preload_is_int,
    output logic                            acc_rmw_fwd_valid,
    output logic                            acc_wb_valid,
    input  logic                            acc_wb_ready,
    output logic                            acc_swap_req,
    input  logic                            acc_swap_ack,
    // Downstream Status Inputs
    input  logic                            skew_busy,
    input  logic                            array_busy,
    input  logic                            acc_busy,
    input  logic                            drain_active,
    input  logic                            epilogue_busy,
    // Top-Level Telemetry Outputs
    output logic                            busy,
    output logic [31:0]                     active_cycles_out,
    output logic [31:0]                     stall_cycles_out,
    output logic [31:0]                     k_steps_done_out
);

    import VX_tcu_v2_pkg::*;

    typedef enum logic [2:0] {
        CTRL_IDLE       = 3'd0,
        CTRL_ISSUE      = 3'd1,
        CTRL_WAIT_WB    = 3'd2,
        CTRL_BANK_SWAP  = 3'd3,
        CTRL_DRAIN_WAIT = 3'd4,
        CTRL_FAULT      = 3'd5
    } ctrl_state_e;

    typedef enum logic [2:0] {
        FAULT_NONE        = 3'd0,
        FAULT_ILLEGAL_FMT = 3'd1,
        FAULT_ILLEGAL_RM  = 3'd2,
        FAULT_ILLEGAL_ACT = 3'd3,
        FAULT_K_SEQ       = 3'd4,
        FAULT_SCALE_FMT   = 3'd5
    } ctrl_fault_code_e;

    // -------------------------------------------------------------------------
    // Sequencer Registers, Descriptor Context & Telemetry Counters
    // -------------------------------------------------------------------------
    ctrl_state_e      state_r;
    ctrl_fault_code_e fault_code_r;
    tcu_v2_uop_t      active_uop_r;
    logic [7:0]       expected_k_r;
    logic [7:0]       active_desc_id_r;
    logic [3:0]       active_step_m_r;
    logic [3:0]       active_step_n_r;
    logic             accum_active_r;
    logic             rmw_fwd_r;
    logic             swap_pending_r;

    logic [31:0]      active_cycles_r;
    logic [31:0]      idle_cycles_r;
    logic [31:0]      stall_cycles_r;
    logic [31:0]      issue_stall_cycles_r;
    logic [31:0]      wb_stall_cycles_r;
    logic [31:0]      k_steps_done_r;
    logic [31:0]      tiles_completed_r;
    logic [31:0]      uops_dispatched_r;
    logic [31:0]      sparse_uops_r;
    logic [31:0]      bias_uops_r;
    logic [31:0]      accum_uops_r;
    logic [31:0]      rmw_fwd_cycles_r;
    logic [31:0]      bank_swap_cycles_r;
    logic [31:0]      fault_count_r;
    logic [31:0]      watchdog_cycles_r;
    logic [31:0]      max_tile_latency_r;
    logic [31:0]      cur_tile_cycles_r;
    logic [7:0]       last_completed_desc_r;

    logic             uop_in_meta_parity;
    logic             active_uop_parity;
    logic             is_int_uop;
    logic             uop_in_fmt_ok;
    logic             uop_in_scale_ok;
    logic             uop_in_rm_ok;
    logic             uop_in_act_ok;
    logic             uop_in_legal;
    logic             can_accept_uop;
    logic             k_seq_continuous;
    logic             k_seq_order_ok;
    logic             any_pipeline_busy;
    logic             dbuf_swap_needed;

    assign is_int_uop    = tcu_v2_fmt_is_int(dbuf_exec_uop.fmt_a) && tcu_v2_fmt_is_int(dbuf_exec_uop.fmt_b);
    assign uop_in_fmt_ok = (tcu_v2_fmt_bitwidth(uop_in.fmt_a) != 0) &&
                           (tcu_v2_fmt_bitwidth(uop_in.fmt_b) != 0) &&
                           (tcu_v2_fmt_bitwidth(uop_in.fmt_d) != 0);
    assign uop_in_scale_ok = !(tcu_v2_fmt_is_mx(uop_in.fmt_a) || tcu_v2_fmt_is_mx(uop_in.fmt_b)) ||
                             (uop_in.scale_fmt != TCU_V2_SCALE_NONE);
    assign uop_in_rm_ok    = (uop_in.rm <= TCU_V2_RM_RMM);
    assign uop_in_act_ok   = (uop_in.act <= TCU_V2_ACT_GELU);
    assign uop_in_legal    = uop_in_fmt_ok && uop_in_rm_ok && uop_in_act_ok && uop_in_scale_ok;
    assign can_accept_uop  = dbuf_load_ready && (state_r != CTRL_FAULT);

    assign uop_ready       = can_accept_uop;
    assign dbuf_load_valid = uop_valid && (state_r != CTRL_FAULT) && uop_in_legal;

    assign k_seq_continuous = !dbuf_exec_uop.is_first_k &&
                              accum_active_r &&
                              (dbuf_exec_uop.desc_id == active_desc_id_r) &&
                              (dbuf_exec_uop.step_m == active_step_m_r) &&
                              (dbuf_exec_uop.step_n == active_step_n_r);

    assign k_seq_order_ok = dbuf_exec_uop.is_first_k ||
                            (k_seq_continuous && (dbuf_exec_uop.step_k == expected_k_r));

    assign dbuf_swap_needed = dbuf_exec_valid && !k_seq_order_ok && accum_active_r;

    assign any_pipeline_busy = (state_r != CTRL_IDLE) ||
                               dbuf_exec_valid ||
                               skew_busy ||
                               array_busy ||
                               acc_busy ||
                               drain_active ||
                               epilogue_busy;

    assign uop_in_meta_parity = ^uop_in;
    assign active_uop_parity  = ^active_uop_r;

    // -------------------------------------------------------------------------
    // Main K-Tile Sequencer & Double-Buffer / Accumulator Bank Handoff FSM
    // -------------------------------------------------------------------------
    always_comb begin
        dbuf_exec_ready    = 1'b0;
        dbuf_swap_req      = 1'b0;
        issue_valid        = 1'b0;
        pe_wb_ready        = 1'b0;
        acc_preload_valid  = 1'b0;
        acc_preload_use_c  = 1'b0;
        acc_preload_is_int = 1'b0;
        acc_rmw_fwd_valid  = rmw_fwd_r;
        acc_wb_valid       = 1'b0;
        acc_swap_req       = 1'b0;

        case (state_r)
            CTRL_IDLE,
            CTRL_ISSUE: begin
                if (dbuf_exec_valid) begin
                    acc_preload_valid  = dbuf_exec_uop.is_first_k;
                    acc_preload_use_c  = dbuf_exec_uop.accum_en && dbuf_exec_uop.is_first_k;
                    acc_preload_is_int = is_int_uop;
                    issue_valid        = 1'b1;
                    dbuf_exec_ready    = issue_ready;
                end
            end

            CTRL_WAIT_WB: begin
                pe_wb_ready  = acc_wb_ready;
                acc_wb_valid = pe_wb_valid;
                if (pe_wb_valid && acc_wb_ready && active_uop_r.is_last_k) begin
                    acc_swap_req = 1'b1;
                end
            end

            CTRL_BANK_SWAP: begin
                acc_swap_req = !swap_pending_r;
                if (dbuf_swap_needed) begin
                    dbuf_swap_req = 1'b0;
                end
            end

            CTRL_DRAIN_WAIT: begin
                if (!drain_active && !epilogue_busy) begin
                    dbuf_swap_req = 1'b0;
                end
            end

            default: begin
                dbuf_exec_ready = 1'b0;
            end
        endcase
    end

    // -------------------------------------------------------------------------
    // Sequential State Transitions, K-Step Verification & Telemetry Counters
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (reset) begin
            state_r               <= CTRL_IDLE;
            fault_code_r          <= FAULT_NONE;
            active_uop_r          <= '0;
            expected_k_r          <= 8'd0;
            active_desc_id_r      <= 8'd0;
            active_step_m_r       <= 4'd0;
            active_step_n_r       <= 4'd0;
            accum_active_r        <= 1'b0;
            rmw_fwd_r             <= 1'b0;
            swap_pending_r        <= 1'b0;
            active_cycles_r       <= 32'd0;
            idle_cycles_r         <= 32'd0;
            stall_cycles_r        <= 32'd0;
            issue_stall_cycles_r  <= 32'd0;
            wb_stall_cycles_r     <= 32'd0;
            k_steps_done_r        <= 32'd0;
            tiles_completed_r     <= 32'd0;
            uops_dispatched_r     <= 32'd0;
            sparse_uops_r         <= 32'd0;
            bias_uops_r           <= 32'd0;
            accum_uops_r          <= 32'd0;
            rmw_fwd_cycles_r      <= 32'd0;
            bank_swap_cycles_r    <= 32'd0;
            fault_count_r         <= 32'd0;
            watchdog_cycles_r     <= 32'd0;
            max_tile_latency_r    <= 32'd0;
            cur_tile_cycles_r     <= 32'd0;
            last_completed_desc_r <= 8'd0;
        end else begin
            if (any_pipeline_busy) begin
                active_cycles_r <= active_cycles_r + 32'd1;
            end else begin
                idle_cycles_r <= idle_cycles_r + 32'd1;
            end
            if ((uop_valid && !uop_ready) || (issue_valid && !issue_ready) || (pe_wb_valid && !acc_wb_ready)) begin
                stall_cycles_r <= stall_cycles_r + 32'd1;
            end
            if (issue_valid && !issue_ready) begin
                issue_stall_cycles_r <= issue_stall_cycles_r + 32'd1;
            end
            if (pe_wb_valid && !acc_wb_ready) begin
                wb_stall_cycles_r <= wb_stall_cycles_r + 32'd1;
            end
            if (rmw_fwd_r) begin
                rmw_fwd_cycles_r <= rmw_fwd_cycles_r + 32'd1;
            end
            if (accum_active_r) begin
                cur_tile_cycles_r <= cur_tile_cycles_r + 32'd1;
            end
            if (uop_valid && can_accept_uop) begin
                if (!uop_in_legal) begin
                    fault_count_r <= fault_count_r + 32'd1;
                    if (!uop_in_fmt_ok) begin
                        fault_code_r <= FAULT_ILLEGAL_FMT;
                    end else if (!uop_in_scale_ok) begin
                        fault_code_r <= FAULT_SCALE_FMT;
                    end else if (!uop_in_rm_ok) begin
                        fault_code_r <= FAULT_ILLEGAL_RM;
                    end else begin
                        fault_code_r <= FAULT_ILLEGAL_ACT;
                    end
                end else begin
                    uops_dispatched_r <= uops_dispatched_r + 32'd1;
                    if (uop_in.sparse_en) begin
                        sparse_uops_r <= sparse_uops_r + 32'd1;
                    end
                    if (uop_in.bias_en && uop_in.is_last_k) begin
                        bias_uops_r <= bias_uops_r + 32'd1;
                    end
                    if (uop_in.accum_en) begin
                        accum_uops_r <= accum_uops_r + 32'd1;
                    end
                end
            end

            case (state_r)
                CTRL_IDLE,
                CTRL_ISSUE: begin
                    rmw_fwd_r         <= 1'b0;
                    swap_pending_r    <= 1'b0;
                    watchdog_cycles_r <= 32'd0;
                    if (dbuf_exec_valid && issue_ready) begin
                        active_uop_r     <= dbuf_exec_uop;
                        active_desc_id_r <= dbuf_exec_uop.desc_id;
                        active_step_m_r  <= dbuf_exec_uop.step_m;
                        active_step_n_r  <= dbuf_exec_uop.step_n;
                        accum_active_r   <= 1'b1;
                        expected_k_r     <= dbuf_exec_uop.step_k + 8'd1;
                        rmw_fwd_r        <= k_seq_continuous;
                        if (dbuf_exec_uop.is_first_k) begin
                            cur_tile_cycles_r <= 32'd1;
                        end
                        if (!k_seq_order_ok) begin
                            fault_code_r  <= FAULT_K_SEQ;
                            fault_count_r <= fault_count_r + 32'd1;
                        end
                        state_r <= CTRL_WAIT_WB;
                    end else if (!dbuf_exec_valid) begin
                        state_r <= CTRL_IDLE;
                    end
                end

                CTRL_WAIT_WB: begin
                    watchdog_cycles_r <= watchdog_cycles_r + 32'd1;
                    if (pe_wb_valid && acc_wb_ready) begin
                        k_steps_done_r    <= k_steps_done_r + 32'd1;
                        rmw_fwd_r         <= 1'b0;
                        watchdog_cycles_r <= 32'd0;
                        if (active_uop_r.is_last_k) begin
                            accum_active_r        <= 1'b0;
                            expected_k_r          <= 8'd0;
                            tiles_completed_r     <= tiles_completed_r + 32'd1;
                            last_completed_desc_r <= active_desc_id_r;
                            if (cur_tile_cycles_r > max_tile_latency_r) begin
                                max_tile_latency_r <= cur_tile_cycles_r;
                            end
                            cur_tile_cycles_r <= 32'd0;
                            if (acc_swap_ack) begin
                                state_r <= dbuf_exec_valid ? CTRL_ISSUE : CTRL_IDLE;
                            end else begin
                                swap_pending_r <= 1'b0;
                                state_r        <= CTRL_BANK_SWAP;
                            end
                        end else begin
                            state_r <= CTRL_ISSUE;
                        end
                    end
                end

                CTRL_BANK_SWAP: begin
                    bank_swap_cycles_r <= bank_swap_cycles_r + 32'd1;
                    if (acc_swap_ack) begin
                        swap_pending_r <= 1'b1;
                        state_r        <= dbuf_exec_valid ? CTRL_ISSUE : CTRL_IDLE;
                    end
                end

                CTRL_DRAIN_WAIT: begin
                    if (!drain_active && !epilogue_busy) begin
                        state_r <= CTRL_IDLE;
                    end
                end

                default: begin
                    state_r <= CTRL_IDLE;
                end
            endcase
        end
    end

    `UNUSED_PARAM (ARRAY_M)
    `UNUSED_PARAM (ARRAY_N)
    `UNUSED_VAR (fault_code_r)
    `UNUSED_VAR (dbuf_swap_ack)
    `UNUSED_VAR (uop_in_meta_parity)
    `UNUSED_VAR (active_uop_parity)
    `UNUSED_VAR (idle_cycles_r)
    `UNUSED_VAR (issue_stall_cycles_r)
    `UNUSED_VAR (wb_stall_cycles_r)
    `UNUSED_VAR (tiles_completed_r)
    `UNUSED_VAR (uops_dispatched_r)
    `UNUSED_VAR (sparse_uops_r)
    `UNUSED_VAR (bias_uops_r)
    `UNUSED_VAR (accum_uops_r)
    `UNUSED_VAR (rmw_fwd_cycles_r)
    `UNUSED_VAR (bank_swap_cycles_r)
    `UNUSED_VAR (fault_count_r)
    `UNUSED_VAR (watchdog_cycles_r)
    `UNUSED_VAR (max_tile_latency_r)
    `UNUSED_VAR (last_completed_desc_r)

    assign busy              = any_pipeline_busy;
    assign active_cycles_out = active_cycles_r;
    assign stall_cycles_out  = stall_cycles_r;
    assign k_steps_done_out  = k_steps_done_r;

endmodule

`endif // VX_TCU_V2_ARRAY_CTRL_SV
