// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_barrier_unit #(
    parameter int NUM_BARRIERS = VX_tcu_v2_pkg::TCU_V2_MAX_BARRIERS
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            cmd_valid,
    output logic                                            cmd_ready,
    input  logic [2:0]                                      cmd_op,
    input  logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0]   cmd_bar_id,
    input  logic [15:0]                                     cmd_count,
    input  logic                                            cmd_phase,
    input  logic                                            wait_valid,
    input  logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0]   wait_bar_id,
    input  logic                                            wait_phase,
    output logic                                            wait_pass_out,
    output logic                                            wakeup_valid_out,
    output logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0]   wakeup_bar_id_out,
    output logic                                            wakeup_phase_out,
    input  logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0]   status_bar_id,
    output logic                                            status_valid_out,
    output logic                                            status_phase_out,
    output logic [15:0]                                     status_arrive_rem_out,
    output logic [15:0]                                     status_tx_rem_out,
    output logic [NUM_BARRIERS-1:0]                         bar_active_mask_out,
    output logic [NUM_BARRIERS-1:0]                         bar_phase_vec_out,
    output logic                                            bar_stall_out,
    output logic [31:0]                                     phase_flips_cnt_out,
    output logic [31:0]                                     wait_stall_cycles_out
);

    import VX_tcu_v2_pkg::*;

    localparam logic [2:0] BAR_OP_NOP         = 3'd0;
    localparam logic [2:0] BAR_OP_INIT        = 3'd1;
    localparam logic [2:0] BAR_OP_ARRIVE      = 3'd2;
    localparam logic [2:0] BAR_OP_EXPECT_TX   = 3'd3;
    localparam logic [2:0] BAR_OP_COMPLETE_TX = 3'd4;
    localparam logic [2:0] BAR_OP_RESET_SLOT  = 3'd5;

    typedef struct packed {
        logic        initialized;
        logic        phase;
        logic        last_wakeup_phase;
        logic [15:0] arrive_init;
        logic [15:0] arrive_rem;
        logic [15:0] tx_rem;
        logic [15:0] epoch_count;
        logic [15:0] arrive_events;
        logic [15:0] tx_events;
    } barrier_slot_t;

    typedef struct packed {
        logic                           valid;
        logic [TCU_V2_BARRIER_ID_W-1:0] bar_id;
        logic                           new_phase;
        logic [15:0]                    epoch;
    } wakeup_hist_t;

    localparam int WAKEUP_HIST_DEPTH = 4;
    localparam int BAR_IDX_W         = (NUM_BARRIERS > 1) ? $clog2(NUM_BARRIERS) : 1;

    barrier_slot_t [NUM_BARRIERS-1:0]   slots_r;
    wakeup_hist_t [WAKEUP_HIST_DEPTH-1:0] wakeup_hist_r;
    logic [1:0]                         wakeup_hist_ptr_r;
    logic                               wakeup_valid_r;
    logic [TCU_V2_BARRIER_ID_W-1:0]     wakeup_bar_id_r;
    logic                               wakeup_phase_r;
    logic [31:0]                        phase_flips_r;
    logic [31:0]                        wait_stall_cycles_r;
    logic [31:0]                        uninit_cmd_err_r;
    logic [31:0]                        tx_underflow_err_r;
    logic [31:0]                        oob_id_err_r;
    logic [31:0]                        arrive_total_r;
    logic [31:0]                        tx_complete_total_r;

    logic                               cmd_id_valid_w;
    logic                               wait_id_valid_w;
    logic                               status_id_valid_w;
    logic [BAR_IDX_W-1:0]               cmd_idx_w;
    logic [BAR_IDX_W-1:0]               wait_idx_w;
    logic [BAR_IDX_W-1:0]               status_idx_w;
    logic                               wait_match_w;
    logic                               wait_bypass_flip_w;
    logic                               cmd_fire_w;
    logic [NUM_BARRIERS-1:0]            zero_pending_vec_w;

    assign cmd_id_valid_w    = (int'(cmd_bar_id) < NUM_BARRIERS);
    assign wait_id_valid_w   = (int'(wait_bar_id) < NUM_BARRIERS);
    assign status_id_valid_w = (int'(status_bar_id) < NUM_BARRIERS);
    assign cmd_idx_w         = cmd_id_valid_w ? BAR_IDX_W'(cmd_bar_id) : '0;
    assign wait_idx_w        = wait_id_valid_w ? BAR_IDX_W'(wait_bar_id) : '0;
    assign status_idx_w      = status_id_valid_w ? BAR_IDX_W'(status_bar_id) : '0;

    assign cmd_ready  = 1'b1;
    assign cmd_fire_w = cmd_valid && cmd_ready;

    always_comb begin
        logic [15:0] dec_amt;
        logic [15:0] rem_after;
        logic [15:0] tx_after;
        logic        eff_phase;

        dec_amt            = 16'd0;
        rem_after          = 16'd0;
        tx_after           = 16'd0;
        eff_phase          = 1'b0;
        wait_bypass_flip_w = 1'b0;

        if (cmd_fire_w && cmd_id_valid_w && wait_id_valid_w && (cmd_bar_id == wait_bar_id)) begin
            if ((cmd_op == BAR_OP_ARRIVE) && slots_r[cmd_idx_w].initialized) begin
                dec_amt   = (cmd_count == 16'd0) ? 16'd1 : cmd_count;
                rem_after = (dec_amt >= slots_r[cmd_idx_w].arrive_rem) ? 16'd0 :
                            (slots_r[cmd_idx_w].arrive_rem - dec_amt);
                if ((rem_after == 16'd0) && (slots_r[cmd_idx_w].tx_rem == 16'd0)) begin
                    wait_bypass_flip_w = 1'b1;
                end
            end else if ((cmd_op == BAR_OP_COMPLETE_TX) && slots_r[cmd_idx_w].initialized) begin
                tx_after = (cmd_count >= slots_r[cmd_idx_w].tx_rem) ? 16'd0 :
                           (slots_r[cmd_idx_w].tx_rem - cmd_count);
                if ((slots_r[cmd_idx_w].arrive_rem == 16'd0) && (tx_after == 16'd0)) begin
                    wait_bypass_flip_w = 1'b1;
                end
            end
        end

        wait_match_w = 1'b1;
        if (wait_valid) begin
            if (wait_id_valid_w && slots_r[wait_idx_w].initialized) begin
                eff_phase    = wait_bypass_flip_w ? !slots_r[wait_idx_w].phase : slots_r[wait_idx_w].phase;
                wait_match_w = (eff_phase != wait_phase);
            end else begin
                wait_match_w = 1'b0;
            end
        end
    end

    always_comb begin
        for (int b = 0; b < NUM_BARRIERS; ++b) begin
            bar_active_mask_out[b] = slots_r[b].initialized;
            bar_phase_vec_out[b]   = slots_r[b].phase;
            zero_pending_vec_w[b]  = slots_r[b].initialized &&
                                     (slots_r[b].arrive_rem == 16'd0) &&
                                     (slots_r[b].tx_rem == 16'd0);
        end
    end

    `UNUSED_VAR (zero_pending_vec_w)
    `UNUSED_VAR (wakeup_hist_r)
    `UNUSED_VAR (uninit_cmd_err_r)
    `UNUSED_VAR (tx_underflow_err_r)
    `UNUSED_VAR (oob_id_err_r)
    `UNUSED_VAR (arrive_total_r)
    `UNUSED_VAR (tx_complete_total_r)

    assign wait_pass_out         = wait_match_w;
    assign bar_stall_out         = wait_valid && !wait_match_w;
    assign wakeup_valid_out      = wakeup_valid_r;
    assign wakeup_bar_id_out     = wakeup_bar_id_r;
    assign wakeup_phase_out      = wakeup_phase_r;
    assign status_valid_out      = status_id_valid_w ? slots_r[status_idx_w].initialized : 1'b0;
    assign status_phase_out      = status_id_valid_w ? slots_r[status_idx_w].phase : 1'b0;
    assign status_arrive_rem_out = status_id_valid_w ? slots_r[status_idx_w].arrive_rem : 16'd0;
    assign status_tx_rem_out     = status_id_valid_w ? slots_r[status_idx_w].tx_rem : 16'd0;
    assign phase_flips_cnt_out   = phase_flips_r;
    assign wait_stall_cycles_out = wait_stall_cycles_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            wakeup_valid_r      <= 1'b0;
            wakeup_bar_id_r     <= '0;
            wakeup_phase_r      <= 1'b0;
            phase_flips_r       <= 32'd0;
            wait_stall_cycles_r <= 32'd0;
            uninit_cmd_err_r    <= 32'd0;
            tx_underflow_err_r  <= 32'd0;
            oob_id_err_r        <= 32'd0;
            arrive_total_r      <= 32'd0;
            tx_complete_total_r <= 32'd0;
            wakeup_hist_ptr_r   <= 2'd0;
            for (int b = 0; b < NUM_BARRIERS; ++b) begin
                slots_r[b] <= '0;
            end
            for (int h = 0; h < WAKEUP_HIST_DEPTH; ++h) begin
                wakeup_hist_r[h] <= '0;
            end
        end else begin
            wakeup_valid_r <= 1'b0;

            if (bar_stall_out) begin
                wait_stall_cycles_r <= wait_stall_cycles_r + 32'd1;
            end

            if (cmd_fire_w) begin
                if (!cmd_id_valid_w) begin
                    oob_id_err_r <= oob_id_err_r + 32'd1;
                end else begin
                    logic [15:0] next_arr;
                    logic [15:0] next_tx;
                    logic        next_phase;
                    logic        did_flip;

                    next_arr   = slots_r[cmd_idx_w].arrive_rem;
                    next_tx    = slots_r[cmd_idx_w].tx_rem;
                    next_phase = slots_r[cmd_idx_w].phase;
                    did_flip   = 1'b0;

                    case (cmd_op)
                        BAR_OP_INIT: begin
                            slots_r[cmd_idx_w].initialized       <= 1'b1;
                            slots_r[cmd_idx_w].phase             <= cmd_phase;
                            slots_r[cmd_idx_w].last_wakeup_phase <= cmd_phase;
                            slots_r[cmd_idx_w].arrive_init       <= (cmd_count == 16'd0) ? 16'd1 : cmd_count;
                            slots_r[cmd_idx_w].arrive_rem        <= (cmd_count == 16'd0) ? 16'd1 : cmd_count;
                            slots_r[cmd_idx_w].tx_rem            <= 16'd0;
                            slots_r[cmd_idx_w].epoch_count       <= 16'd0;
                            slots_r[cmd_idx_w].arrive_events     <= 16'd0;
                            slots_r[cmd_idx_w].tx_events         <= 16'd0;
                        end

                        BAR_OP_ARRIVE: begin
                            if (slots_r[cmd_idx_w].initialized) begin
                                logic [15:0] dec_amt;
                                dec_amt = (cmd_count == 16'd0) ? 16'd1 : cmd_count;
                                arrive_total_r <= arrive_total_r + 32'(dec_amt);
                                slots_r[cmd_idx_w].arrive_events <= slots_r[cmd_idx_w].arrive_events + 16'd1;
                                if (dec_amt >= next_arr) begin
                                    next_arr = 16'd0;
                                end else begin
                                    next_arr = next_arr - dec_amt;
                                end
                                if ((next_arr == 16'd0) && (next_tx == 16'd0)) begin
                                    next_phase = !next_phase;
                                    next_arr   = slots_r[cmd_idx_w].arrive_init;
                                    did_flip   = 1'b1;
                                end
                                slots_r[cmd_idx_w].arrive_rem <= next_arr;
                                slots_r[cmd_idx_w].phase      <= next_phase;
                            end else begin
                                uninit_cmd_err_r <= uninit_cmd_err_r + 32'd1;
                            end
                        end

                        BAR_OP_EXPECT_TX: begin
                            if (slots_r[cmd_idx_w].initialized) begin
                                slots_r[cmd_idx_w].tx_rem <= next_tx + cmd_count;
                            end else begin
                                uninit_cmd_err_r <= uninit_cmd_err_r + 32'd1;
                            end
                        end

                        BAR_OP_COMPLETE_TX: begin
                            if (slots_r[cmd_idx_w].initialized) begin
                                tx_complete_total_r <= tx_complete_total_r + 32'(cmd_count);
                                slots_r[cmd_idx_w].tx_events <= slots_r[cmd_idx_w].tx_events + 16'd1;
                                if (cmd_count > next_tx) begin
                                    tx_underflow_err_r <= tx_underflow_err_r + 32'd1;
                                    next_tx            = 16'd0;
                                end else begin
                                    next_tx = next_tx - cmd_count;
                                end
                                if ((next_arr == 16'd0) && (next_tx == 16'd0)) begin
                                    next_phase = !next_phase;
                                    next_arr   = slots_r[cmd_idx_w].arrive_init;
                                    did_flip   = 1'b1;
                                end
                                slots_r[cmd_idx_w].tx_rem     <= next_tx;
                                slots_r[cmd_idx_w].arrive_rem <= next_arr;
                                slots_r[cmd_idx_w].phase      <= next_phase;
                            end else begin
                                uninit_cmd_err_r <= uninit_cmd_err_r + 32'd1;
                            end
                        end

                        BAR_OP_RESET_SLOT: begin
                            slots_r[cmd_idx_w] <= '0;
                        end

                        BAR_OP_NOP: begin
                            slots_r[cmd_idx_w] <= slots_r[cmd_idx_w];
                        end

                        default: begin
                            slots_r[cmd_idx_w] <= slots_r[cmd_idx_w];
                        end
                    endcase

                    if (did_flip) begin
                        wakeup_valid_r                         <= 1'b1;
                        wakeup_bar_id_r                        <= cmd_bar_id;
                        wakeup_phase_r                         <= next_phase;
                        phase_flips_r                          <= phase_flips_r + 32'd1;
                        slots_r[cmd_idx_w].last_wakeup_phase   <= next_phase;
                        slots_r[cmd_idx_w].epoch_count         <= slots_r[cmd_idx_w].epoch_count + 16'd1;
                        wakeup_hist_r[wakeup_hist_ptr_r].valid     <= 1'b1;
                        wakeup_hist_r[wakeup_hist_ptr_r].bar_id    <= cmd_bar_id;
                        wakeup_hist_r[wakeup_hist_ptr_r].new_phase <= next_phase;
                        wakeup_hist_r[wakeup_hist_ptr_r].epoch     <= slots_r[cmd_idx_w].epoch_count + 16'd1;
                        wakeup_hist_ptr_r                          <= wakeup_hist_ptr_r + 2'd1;
                    end
                end
            end
        end
    end

endmodule
