// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_bank_power_ctrl #(
    parameter int NUM_BANKS       = VX_tmem_pkg::TMEM_NUM_BANKS,
    parameter int IDLE_SLEEP_CYC  = 32,
    parameter int WAKE_LATENCY    = 1
) (
    input  logic                   clk,
    input  logic                   reset,
    // Dynamic power management policy control
    input  logic                   auto_sleep_en,
    input  logic [NUM_BANKS-1:0]   force_wake_mask,
    // Per-bank activity inputs (Port A, Port B, Write, RMW, Scrub)
    input  logic [NUM_BANKS-1:0]   bank_rd_a_act,
    input  logic [NUM_BANKS-1:0]   bank_rd_b_act,
    input  logic [NUM_BANKS-1:0]   bank_wr_act,
    input  logic [NUM_BANKS-1:0]   bank_rmw_act,
    input  logic [NUM_BANKS-1:0]   bank_scrub_act,
    // Per-bank power & clock-gate outputs
    output logic [NUM_BANKS-1:0]   bank_pwr_on,
    output logic [NUM_BANKS-1:0]   bank_clk_en,
    output logic [NUM_BANKS-1:0]   bank_retention_sleep,
    output logic [NUM_BANKS-1:0]   bank_waking,
    // Active-bank & sleep-cycle telemetry
    output logic [NUM_BANKS-1:0]   active_bank_mask_out,
    output logic [5:0]             active_bank_count_out,
    output logic [31:0]            total_bank_sleep_cycles_out,
    output logic [31:0]            total_bank_wake_events_out
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(NUM_BANKS == 32, ("Expected 32 banks"))
    `STATIC_ASSERT(IDLE_SLEEP_CYC >= 2, ("IDLE_SLEEP_CYC must be >= 2"))
    `STATIC_ASSERT(WAKE_LATENCY >= 1, ("WAKE_LATENCY must be >= 1"))

    typedef enum logic [1:0] {
        PWR_ACTIVE = 2'd0,
        PWR_SLEEP  = 2'd1,
        PWR_WAKING = 2'd2
    } bank_pwr_state_e;

    localparam int IDLE_CNT_W = `CLOG2(IDLE_SLEEP_CYC + 1);
    localparam int WAKE_CNT_W = `CLOG2(WAKE_LATENCY + 1);

    logic [NUM_BANKS-1:0][1:0]            pwr_state_q;
    logic [NUM_BANKS-1:0][IDLE_CNT_W-1:0] idle_cnt_q;
    logic [NUM_BANKS-1:0][WAKE_CNT_W-1:0] wake_cnt_q;
    logic [NUM_BANKS-1:0][15:0]           bank_active_cyc_q;
    logic [NUM_BANKS-1:0][15:0]           bank_sleep_cyc_q;
    logic [NUM_BANKS-1:0][7:0]            bank_wake_count_q;
    logic [NUM_BANKS-1:0]                 any_bank_act;
    logic [NUM_BANKS-1:0]                 comb_pwr_on;
    logic [NUM_BANKS-1:0]                 comb_clk_en;
    logic [NUM_BANKS-1:0]                 comb_ret_sleep;
    logic [NUM_BANKS-1:0]                 comb_waking;
    logic [NUM_BANKS-1:0]                 wake_event_pulse;
    logic [NUM_BANKS-1:0]                 sleep_entry_pulse;

    // Group-level (4-bank quad and 8-bank octant) power summary for hierarchical clock gating
    logic [7:0]                           quad_active_any;
    logic [7:0]                           quad_all_sleeping;
    logic [7:0]                           quad_clk_en;
    logic [3:0]                           octant_active_any;
    logic [3:0]                           octant_all_sleeping;

    for (genvar g_b = 0; g_b < NUM_BANKS; ++g_b) begin : g_bank_pwr
        bank_pwr_state_e       cur_state;
        bank_pwr_state_e       nxt_state;
        logic [IDLE_CNT_W-1:0] nxt_idle_cnt;
        logic [WAKE_CNT_W-1:0] nxt_wake_cnt;
        logic                  wake_trigger;

        always_comb begin
            any_bank_act[g_b] = bank_rd_a_act[g_b] ||
                                bank_rd_b_act[g_b] ||
                                bank_wr_act[g_b]   ||
                                bank_rmw_act[g_b]  ||
                                bank_scrub_act[g_b];

            cur_state              = bank_pwr_state_e'(pwr_state_q[g_b]);
            nxt_state              = cur_state;
            nxt_idle_cnt           = idle_cnt_q[g_b];
            nxt_wake_cnt           = wake_cnt_q[g_b];
            wake_trigger           = any_bank_act[g_b] || force_wake_mask[g_b] || !auto_sleep_en;
            wake_event_pulse[g_b]  = 1'b0;
            sleep_entry_pulse[g_b] = 1'b0;

            case (cur_state)
                PWR_ACTIVE: begin
                    if (wake_trigger) begin
                        nxt_idle_cnt = '0;
                    end else if (idle_cnt_q[g_b] >= IDLE_CNT_W'(IDLE_SLEEP_CYC - 1)) begin
                        nxt_state              = PWR_SLEEP;
                        nxt_idle_cnt           = '0;
                        sleep_entry_pulse[g_b] = 1'b1;
                    end else begin
                        nxt_idle_cnt = idle_cnt_q[g_b] + IDLE_CNT_W'(1);
                    end
                end

                PWR_SLEEP: begin
                    if (wake_trigger) begin
                        wake_event_pulse[g_b] = 1'b1;
                        if (WAKE_LATENCY <= 1) begin
                            nxt_state    = PWR_ACTIVE;
                            nxt_wake_cnt = '0;
                        end else begin
                            nxt_state    = PWR_WAKING;
                            nxt_wake_cnt = WAKE_CNT_W'(WAKE_LATENCY - 1);
                        end
                    end
                end

                PWR_WAKING: begin
                    if ((WAKE_LATENCY <= 2) || (wake_cnt_q[g_b] == '0) || (wake_cnt_q[g_b] == WAKE_CNT_W'(1))) begin
                        nxt_state    = PWR_ACTIVE;
                        nxt_wake_cnt = '0;
                    end else begin
                        nxt_wake_cnt = wake_cnt_q[g_b] - WAKE_CNT_W'(1);
                    end
                end

                default: begin
                    nxt_state    = PWR_ACTIVE;
                    nxt_idle_cnt = '0;
                    nxt_wake_cnt = '0;
                end
            endcase

            comb_pwr_on[g_b]    = (cur_state == PWR_ACTIVE);
            comb_clk_en[g_b]    = (cur_state != PWR_SLEEP) || wake_trigger;
            comb_ret_sleep[g_b] = (cur_state == PWR_SLEEP);
            comb_waking[g_b]    = (cur_state == PWR_WAKING);
        end

        always_ff @(posedge clk) begin
            if (reset) begin
                pwr_state_q[g_b]       <= PWR_ACTIVE;
                idle_cnt_q[g_b]        <= '0;
                wake_cnt_q[g_b]        <= '0;
                bank_active_cyc_q[g_b] <= 16'd0;
                bank_sleep_cyc_q[g_b]  <= 16'd0;
                bank_wake_count_q[g_b] <= 8'd0;
            end else begin
                pwr_state_q[g_b] <= nxt_state;
                idle_cnt_q[g_b]  <= nxt_idle_cnt;
                wake_cnt_q[g_b]  <= nxt_wake_cnt;
                if (any_bank_act[g_b] && (bank_active_cyc_q[g_b] != 16'hFFFF)) begin
                    bank_active_cyc_q[g_b] <= bank_active_cyc_q[g_b] + 16'd1;
                end
                if (comb_ret_sleep[g_b] && (bank_sleep_cyc_q[g_b] != 16'hFFFF)) begin
                    bank_sleep_cyc_q[g_b] <= bank_sleep_cyc_q[g_b] + 16'd1;
                end
                if (wake_event_pulse[g_b] && (bank_wake_count_q[g_b] != 8'hFF)) begin
                    bank_wake_count_q[g_b] <= bank_wake_count_q[g_b] + 8'd1;
                end
            end
        end
    end

    for (genvar g_q = 0; g_q < 8; ++g_q) begin : g_quad_pwr
        always_comb begin
            quad_active_any[g_q]   = |comb_pwr_on[g_q*4 +: 4];
            quad_all_sleeping[g_q] = &comb_ret_sleep[g_q*4 +: 4];
            quad_clk_en[g_q]       = |comb_clk_en[g_q*4 +: 4];
        end
    end

    for (genvar g_o = 0; g_o < 4; ++g_o) begin : g_octant_pwr
        always_comb begin
            octant_active_any[g_o]   = |comb_pwr_on[g_o*8 +: 8];
            octant_all_sleeping[g_o] = &comb_ret_sleep[g_o*8 +: 8];
        end
    end

    `UNUSED_VAR (bank_active_cyc_q)
    `UNUSED_VAR (bank_sleep_cyc_q)
    `UNUSED_VAR (bank_wake_count_q)
    `UNUSED_VAR (quad_active_any)
    `UNUSED_VAR (quad_all_sleeping)
    `UNUSED_VAR (quad_clk_en)
    `UNUSED_VAR (octant_active_any)
    `UNUSED_VAR (octant_all_sleeping)

    // Telemetry counters: sleep-bank-cycles saved, sleep entries, wake-up transitions, and activity density
    logic [5:0]  active_banks_cycle;
    logic [5:0]  sleeping_banks_cycle;
    logic [5:0]  waking_banks_cycle;
    logic [5:0]  wake_events_cycle;
    logic [5:0]  sleep_entries_cycle;
    logic [5:0]  clk_enabled_banks_cycle;
    logic [31:0] sleep_cycles_q;
    logic [31:0] wake_events_q;
    logic [31:0] sleep_entries_q;
    logic [31:0] active_bank_cycles_q;
    logic [31:0] clk_gated_cycles_q;

    always_comb begin
        active_banks_cycle      = 6'd0;
        sleeping_banks_cycle    = 6'd0;
        waking_banks_cycle      = 6'd0;
        wake_events_cycle       = 6'd0;
        sleep_entries_cycle     = 6'd0;
        clk_enabled_banks_cycle = 6'd0;

        for (int b = 0; b < NUM_BANKS; ++b) begin
            if (comb_pwr_on[b]) begin
                active_banks_cycle = active_banks_cycle + 6'd1;
            end
            if (comb_ret_sleep[b]) begin
                sleeping_banks_cycle = sleeping_banks_cycle + 6'd1;
            end
            if (comb_waking[b]) begin
                waking_banks_cycle = waking_banks_cycle + 6'd1;
            end
            if (wake_event_pulse[b]) begin
                wake_events_cycle = wake_events_cycle + 6'd1;
            end
            if (sleep_entry_pulse[b]) begin
                sleep_entries_cycle = sleep_entries_cycle + 6'd1;
            end
            if (comb_clk_en[b]) begin
                clk_enabled_banks_cycle = clk_enabled_banks_cycle + 6'd1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            sleep_cycles_q       <= 32'd0;
            wake_events_q        <= 32'd0;
            sleep_entries_q      <= 32'd0;
            active_bank_cycles_q <= 32'd0;
            clk_gated_cycles_q   <= 32'd0;
        end else begin
            sleep_cycles_q       <= sleep_cycles_q + {26'd0, sleeping_banks_cycle};
            wake_events_q        <= wake_events_q + {26'd0, wake_events_cycle};
            sleep_entries_q      <= sleep_entries_q + {26'd0, sleep_entries_cycle};
            active_bank_cycles_q <= active_bank_cycles_q + {26'd0, active_banks_cycle};
            clk_gated_cycles_q   <= clk_gated_cycles_q + (32'd32 - {26'd0, clk_enabled_banks_cycle});
        end
    end

    `UNUSED_VAR (waking_banks_cycle)
    `UNUSED_VAR (sleep_entries_q)
    `UNUSED_VAR (active_bank_cycles_q)
    `UNUSED_VAR (clk_gated_cycles_q)

    assign bank_pwr_on                 = comb_pwr_on;
    assign bank_clk_en                 = comb_clk_en;
    assign bank_retention_sleep        = comb_ret_sleep;
    assign bank_waking                 = comb_waking;
    assign active_bank_mask_out        = comb_pwr_on;
    assign active_bank_count_out       = active_banks_cycle;
    assign total_bank_sleep_cycles_out = sleep_cycles_q;
    assign total_bank_wake_events_out  = wake_events_q;

endmodule
