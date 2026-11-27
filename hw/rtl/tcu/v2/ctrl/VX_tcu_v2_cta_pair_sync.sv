// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_cta_pair_sync #(
    parameter int WATCHDOG_LIMIT = 4096
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                req_valid,
    output logic                                req_ready,
    input  logic                                cta_pair_en,
    input  logic                                split_n_mode,
    input  logic                                local_cta_rank,
    input  logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] desc_id_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0] bar_id_in,
    input  logic                                phase_in,
    input  logic                                peer_done_release,
    output logic                                exec_gate_open_out,
    output logic                                exec_m_half_sel_out,
    output logic                                exec_n_half_sel_out,
    output logic                                sync_busy_out,
    output logic                                sync_stall_out,
    output logic                                watchdog_timeout_out,
    input  logic                                watchdog_clear,
    output logic                                cta_sync_out_valid,
    input  logic                                cta_sync_out_ready,
    output logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0] cta_sync_out_bar_id,
    output logic                                cta_sync_out_phase,
    input  logic                                cta_sync_in_valid,
    output logic                                cta_sync_in_ready,
    input  logic [VX_tcu_v2_pkg::TCU_V2_BARRIER_ID_W-1:0] cta_sync_in_bar_id,
    input  logic                                cta_sync_in_phase,
    output logic [31:0]                         pair_sync_count_out,
    output logic [31:0]                         sync_wait_cycles_out
);

    import VX_tcu_v2_pkg::*;

    typedef enum logic [2:0] {
        CTA_IDLE        = 3'd0,
        CTA_SEND_ARRIVE = 3'd1,
        CTA_WAIT_PEER   = 3'd2,
        CTA_EXEC_ACTIVE = 3'd3,
        CTA_BYPASS_EXEC = 3'd4,
        CTA_TIMEOUT     = 3'd5
    } cta_state_e;

    cta_state_e                         state_r;
    logic [TCU_V2_DESC_ID_W-1:0]        active_desc_id_r;
    logic [TCU_V2_BARRIER_ID_W-1:0]     active_bar_id_r;
    logic                               active_phase_r;
    logic                               split_n_r;
    logic                               local_rank_r;
    logic                               out_sent_r;
    logic                               in_seen_r;
    logic [31:0]                        watchdog_cnt_r;
    logic                               watchdog_timeout_r;
    logic [31:0]                        pair_sync_cnt_r;
    logic [31:0]                        sync_wait_cycles_r;
    logic [31:0]                        phase_mismatch_cnt_r;

    localparam int MAX_QUEUED = 2;

    typedef struct packed {
        logic                           valid;
        logic [TCU_V2_BARRIER_ID_W-1:0] bar_id;
        logic                           phase;
    } peer_pend_t;

    peer_pend_t [MAX_QUEUED-1:0]        early_peer_r;

    logic                               early_hit_w;
    logic                               early_hit_idx_w;
    logic                               early_free_w;
    logic                               early_free_idx_w;
    logic                               in_match_active_w;
    logic                               out_fire_w;
    logic                               in_fire_w;

    always_comb begin
        early_hit_w      = 1'b0;
        early_hit_idx_w  = 1'b0;
        early_free_w     = 1'b0;
        early_free_idx_w = 1'b0;

        for (int i = 0; i < MAX_QUEUED; ++i) begin
            if (early_peer_r[i].valid &&
                (early_peer_r[i].bar_id == active_bar_id_r) &&
                (early_peer_r[i].phase == active_phase_r)) begin
                if (!early_hit_w) begin
                    early_hit_w     = 1'b1;
                    early_hit_idx_w = i[0];
                end
            end else if (!early_peer_r[i].valid && !early_free_w) begin
                early_free_w     = 1'b1;
                early_free_idx_w = i[0];
            end
        end
    end

    assign in_match_active_w = cta_sync_in_valid &&
                               (cta_sync_in_bar_id == active_bar_id_r) &&
                               (cta_sync_in_phase == active_phase_r);

    assign cta_sync_out_valid  = (state_r == CTA_SEND_ARRIVE) || ((state_r == CTA_WAIT_PEER) && !out_sent_r);
    assign cta_sync_out_bar_id = active_bar_id_r;
    assign cta_sync_out_phase  = active_phase_r;

    assign cta_sync_in_ready = (((state_r == CTA_WAIT_PEER) || (state_r == CTA_SEND_ARRIVE)) &&
                                in_match_active_w) ||
                               early_free_w;

    assign out_fire_w = cta_sync_out_valid && cta_sync_out_ready;
    assign in_fire_w  = cta_sync_in_valid && cta_sync_in_ready;

    `UNUSED_VAR (active_desc_id_r)
    `UNUSED_VAR (phase_mismatch_cnt_r)

    assign req_ready            = (state_r == CTA_IDLE);
    assign exec_gate_open_out   = (state_r == CTA_EXEC_ACTIVE) || (state_r == CTA_BYPASS_EXEC);
    assign exec_m_half_sel_out  = !split_n_r ? local_rank_r : 1'b0;
    assign exec_n_half_sel_out  = split_n_r ? local_rank_r : 1'b0;
    assign sync_busy_out        = (state_r != CTA_IDLE);
    assign sync_stall_out       = (state_r == CTA_SEND_ARRIVE) || (state_r == CTA_WAIT_PEER);
    assign watchdog_timeout_out = watchdog_timeout_r;
    assign pair_sync_count_out  = pair_sync_cnt_r;
    assign sync_wait_cycles_out = sync_wait_cycles_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            state_r              <= CTA_IDLE;
            active_desc_id_r     <= '0;
            active_bar_id_r      <= '0;
            active_phase_r       <= 1'b0;
            split_n_r            <= 1'b0;
            local_rank_r         <= 1'b0;
            out_sent_r           <= 1'b0;
            in_seen_r            <= 1'b0;
            watchdog_cnt_r       <= 32'd0;
            watchdog_timeout_r   <= 1'b0;
            pair_sync_cnt_r      <= 32'd0;
            sync_wait_cycles_r   <= 32'd0;
            phase_mismatch_cnt_r <= 32'd0;
            for (int i = 0; i < MAX_QUEUED; ++i) begin
                early_peer_r[i] <= '0;
            end
        end else begin
            if (watchdog_clear) begin
                watchdog_timeout_r <= 1'b0;
                watchdog_cnt_r     <= 32'd0;
            end

            if (sync_stall_out) begin
                sync_wait_cycles_r <= sync_wait_cycles_r + 32'd1;
            end

            case (state_r)
                CTA_IDLE: begin
                    out_sent_r     <= 1'b0;
                    in_seen_r      <= 1'b0;
                    watchdog_cnt_r <= 32'd0;

                    if (in_fire_w && early_free_w) begin
                        early_peer_r[early_free_idx_w].valid  <= 1'b1;
                        early_peer_r[early_free_idx_w].bar_id <= cta_sync_in_bar_id;
                        early_peer_r[early_free_idx_w].phase  <= cta_sync_in_phase;
                    end

                    if (req_valid) begin
                        active_desc_id_r <= desc_id_in;
                        active_bar_id_r  <= bar_id_in;
                        active_phase_r   <= phase_in;
                        split_n_r        <= split_n_mode;
                        local_rank_r     <= local_cta_rank;
                        if (cta_pair_en) begin
                            state_r <= CTA_SEND_ARRIVE;
                        end else begin
                            state_r <= CTA_BYPASS_EXEC;
                        end
                    end
                end

                CTA_SEND_ARRIVE: begin
                    watchdog_cnt_r <= watchdog_cnt_r + 32'd1;

                    if (in_fire_w) begin
                        if (in_match_active_w) begin
                            in_seen_r <= 1'b1;
                        end else begin
                            phase_mismatch_cnt_r <= phase_mismatch_cnt_r + 32'd1;
                            if (early_free_w) begin
                                early_peer_r[early_free_idx_w].valid  <= 1'b1;
                                early_peer_r[early_free_idx_w].bar_id <= cta_sync_in_bar_id;
                                early_peer_r[early_free_idx_w].phase  <= cta_sync_in_phase;
                            end
                        end
                    end

                    if (early_hit_w) begin
                        early_peer_r[early_hit_idx_w].valid <= 1'b0;
                        in_seen_r                           <= 1'b1;
                    end

                    if (out_fire_w) begin
                        out_sent_r <= 1'b1;
                        if (in_seen_r || early_hit_w || (in_fire_w && in_match_active_w)) begin
                            state_r         <= CTA_EXEC_ACTIVE;
                            pair_sync_cnt_r <= pair_sync_cnt_r + 32'd1;
                        end else begin
                            state_r <= CTA_WAIT_PEER;
                        end
                    end else if (watchdog_cnt_r >= 32'(WATCHDOG_LIMIT)) begin
                        watchdog_timeout_r <= 1'b1;
                        state_r            <= CTA_TIMEOUT;
                    end
                end

                CTA_WAIT_PEER: begin
                    watchdog_cnt_r <= watchdog_cnt_r + 32'd1;

                    if (in_fire_w && !in_match_active_w) begin
                        phase_mismatch_cnt_r <= phase_mismatch_cnt_r + 32'd1;
                        if (early_free_w) begin
                            early_peer_r[early_free_idx_w].valid  <= 1'b1;
                            early_peer_r[early_free_idx_w].bar_id <= cta_sync_in_bar_id;
                            early_peer_r[early_free_idx_w].phase  <= cta_sync_in_phase;
                        end
                    end

                    if (early_hit_w) begin
                        early_peer_r[early_hit_idx_w].valid <= 1'b0;
                        in_seen_r                           <= 1'b1;
                        state_r                             <= CTA_EXEC_ACTIVE;
                        pair_sync_cnt_r                     <= pair_sync_cnt_r + 32'd1;
                    end else if (in_fire_w && in_match_active_w) begin
                        in_seen_r       <= 1'b1;
                        state_r         <= CTA_EXEC_ACTIVE;
                        pair_sync_cnt_r <= pair_sync_cnt_r + 32'd1;
                    end else if (watchdog_cnt_r >= 32'(WATCHDOG_LIMIT)) begin
                        watchdog_timeout_r <= 1'b1;
                        state_r            <= CTA_TIMEOUT;
                    end
                end

                CTA_EXEC_ACTIVE: begin
                    if (in_fire_w && early_free_w) begin
                        early_peer_r[early_free_idx_w].valid  <= 1'b1;
                        early_peer_r[early_free_idx_w].bar_id <= cta_sync_in_bar_id;
                        early_peer_r[early_free_idx_w].phase  <= cta_sync_in_phase;
                    end

                    if (peer_done_release) begin
                        state_r <= CTA_IDLE;
                    end
                end

                CTA_BYPASS_EXEC: begin
                    if (in_fire_w && early_free_w) begin
                        early_peer_r[early_free_idx_w].valid  <= 1'b1;
                        early_peer_r[early_free_idx_w].bar_id <= cta_sync_in_bar_id;
                        early_peer_r[early_free_idx_w].phase  <= cta_sync_in_phase;
                    end

                    if (peer_done_release) begin
                        state_r <= CTA_IDLE;
                    end
                end

                CTA_TIMEOUT: begin
                    if (watchdog_clear || peer_done_release) begin
                        watchdog_timeout_r <= 1'b0;
                        state_r            <= CTA_IDLE;
                    end
                end

                default: begin
                    state_r <= CTA_IDLE;
                end
            endcase
        end
    end

endmodule
