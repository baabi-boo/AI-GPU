// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_pipe_sched #(
    parameter int NUM_PIPES     = 4,
    parameter int CREDITS_INIT  = 4,
    parameter int STARVE_LIMIT  = 16
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic [NUM_PIPES-1:0]                pipe_req_valid,
    output logic [NUM_PIPES-1:0]                pipe_req_ready,
    input  logic [NUM_PIPES-1:0]                pipe_hazard_stall,
    input  logic [NUM_PIPES-1:0]                pipe_barrier_wait,
    input  VX_tcu_v2_pkg::tcu_v2_uop_t [NUM_PIPES-1:0] pipe_uop_in,
    input  logic [NUM_PIPES-1:0]                credit_return,
    output logic                                issue_valid,
    input  logic                                issue_ready,
    output logic [$clog2(NUM_PIPES > 1 ? NUM_PIPES : 2)-1:0] issue_pipe_id,
    output VX_tcu_v2_pkg::tcu_v2_uop_t          issue_uop_out,
    output logic [NUM_PIPES-1:0][3:0]           pipe_credits_out,
    output logic [NUM_PIPES-1:0][7:0]           pipe_age_out,
    output logic [NUM_PIPES-1:0]                pipe_starved_out,
    output logic [31:0]                         total_issues_cnt_out,
    output logic [31:0]                         arb_stall_cnt_out
);

    import VX_tcu_v2_pkg::*;

    localparam int PIPE_W = $clog2(NUM_PIPES > 1 ? NUM_PIPES : 2);

    logic [NUM_PIPES-1:0][3:0]  credits_r;
    logic [NUM_PIPES-1:0][3:0]  min_credits_r;
    logic [NUM_PIPES-1:0][7:0]  age_r;
    logic [NUM_PIPES-1:0][31:0] pipe_grant_cnt_r;
    logic [NUM_PIPES-1:0][31:0] pipe_haz_stall_cnt_r;
    logic [NUM_PIPES-1:0][31:0] pipe_bar_stall_cnt_r;
    logic [NUM_PIPES-1:0][31:0] pipe_starve_cnt_r;
    logic [PIPE_W-1:0]          rr_ptr_r;
    logic [PIPE_W-1:0]          last_grant_pipe_r;
    logic [31:0]                total_issues_r;
    logic [31:0]                arb_stall_r;
    logic [31:0]                starve_override_cnt_r;
    logic [31:0]                credit_zero_stall_r;

    logic [NUM_PIPES-1:0]       eligible_w;
    logic [NUM_PIPES-1:0]       starved_w;
    logic [NUM_PIPES-1:0]       no_credit_stall_w;
    logic                       any_eligible_w;
    logic                       any_starved_w;
    logic                       any_no_credit_w;
    logic [PIPE_W-1:0]          sel_pipe_w;
    logic [NUM_PIPES-1:0]       grant_oh_w;
    logic                       issue_fire_w;

    always_comb begin
        logic [7:0] max_age;
        logic       found;
        int         idx;

        any_eligible_w  = 1'b0;
        any_starved_w   = 1'b0;
        any_no_credit_w = 1'b0;
        max_age         = 8'd0;
        found           = 1'b0;
        idx             = 0;

        for (int p = 0; p < NUM_PIPES; ++p) begin
            eligible_w[p] = pipe_req_valid[p] &&
                            (credits_r[p] != 4'd0) &&
                            !pipe_hazard_stall[p] &&
                            !pipe_barrier_wait[p];
            no_credit_stall_w[p] = pipe_req_valid[p] &&
                                   (credits_r[p] == 4'd0) &&
                                   !pipe_hazard_stall[p] &&
                                   !pipe_barrier_wait[p];
            starved_w[p]  = eligible_w[p] && (age_r[p] >= 8'(STARVE_LIMIT));
            if (eligible_w[p]) begin
                any_eligible_w = 1'b1;
            end
            if (starved_w[p]) begin
                any_starved_w = 1'b1;
            end
            if (no_credit_stall_w[p]) begin
                any_no_credit_w = 1'b1;
            end
        end

        sel_pipe_w = rr_ptr_r;
        if (any_starved_w) begin
            for (int offset = 0; offset < NUM_PIPES; ++offset) begin
                idx = (int'(rr_ptr_r) + offset) % NUM_PIPES;
                if (starved_w[idx] && (age_r[idx] >= max_age)) begin
                    max_age    = age_r[idx];
                    sel_pipe_w = PIPE_W'(idx[PIPE_W-1:0]);
                end
            end
        end else if (any_eligible_w) begin
            for (int offset = 0; offset < NUM_PIPES; ++offset) begin
                idx = (int'(rr_ptr_r) + offset) % NUM_PIPES;
                if (!found && eligible_w[idx]) begin
                    found      = 1'b1;
                    sel_pipe_w = PIPE_W'(idx[PIPE_W-1:0]);
                end
            end
        end

        grant_oh_w = '0;
        if (any_eligible_w && issue_ready) begin
            grant_oh_w[sel_pipe_w] = 1'b1;
        end
    end

    `UNUSED_VAR (min_credits_r)
    `UNUSED_VAR (pipe_grant_cnt_r)
    `UNUSED_VAR (pipe_haz_stall_cnt_r)
    `UNUSED_VAR (pipe_bar_stall_cnt_r)
    `UNUSED_VAR (pipe_starve_cnt_r)
    `UNUSED_VAR (last_grant_pipe_r)
    `UNUSED_VAR (starve_override_cnt_r)
    `UNUSED_VAR (credit_zero_stall_r)

    assign issue_valid   = any_eligible_w;
    assign issue_pipe_id = sel_pipe_w;
    assign issue_uop_out = pipe_uop_in[sel_pipe_w];
    assign issue_fire_w  = issue_valid && issue_ready;

    assign pipe_req_ready       = grant_oh_w;
    assign pipe_credits_out     = credits_r;
    assign pipe_age_out         = age_r;
    assign pipe_starved_out     = starved_w;
    assign total_issues_cnt_out = total_issues_r;
    assign arb_stall_cnt_out    = arb_stall_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            rr_ptr_r              <= '0;
            last_grant_pipe_r     <= '0;
            total_issues_r        <= 32'd0;
            arb_stall_r           <= 32'd0;
            starve_override_cnt_r <= 32'd0;
            credit_zero_stall_r   <= 32'd0;
            for (int p = 0; p < NUM_PIPES; ++p) begin
                credits_r[p]            <= 4'(CREDITS_INIT);
                min_credits_r[p]        <= 4'(CREDITS_INIT);
                age_r[p]                <= 8'd0;
                pipe_grant_cnt_r[p]     <= 32'd0;
                pipe_haz_stall_cnt_r[p] <= 32'd0;
                pipe_bar_stall_cnt_r[p] <= 32'd0;
                pipe_starve_cnt_r[p]    <= 32'd0;
            end
        end else begin
            if (any_no_credit_w && !any_eligible_w) begin
                credit_zero_stall_r <= credit_zero_stall_r + 32'd1;
            end

            if (issue_fire_w) begin
                total_issues_r    <= total_issues_r + 32'd1;
                last_grant_pipe_r <= sel_pipe_w;
                if (any_starved_w) begin
                    starve_override_cnt_r <= starve_override_cnt_r + 32'd1;
                end
                if ((int'(sel_pipe_w) + 1) >= NUM_PIPES) begin
                    rr_ptr_r <= '0;
                end else begin
                    rr_ptr_r <= sel_pipe_w + PIPE_W'(1);
                end
            end else if (any_eligible_w && !issue_ready) begin
                arb_stall_r <= arb_stall_r + 32'd1;
            end

            for (int p = 0; p < NUM_PIPES; ++p) begin
                logic take_credit;
                logic ret_credit;
                logic [3:0] next_cred;

                take_credit = grant_oh_w[p] && pipe_uop_in[p].is_last_k;
                ret_credit  = credit_return[p];
                next_cred   = credits_r[p];

                case ({take_credit, ret_credit})
                    2'b10: begin
                        if (credits_r[p] != 4'd0) begin
                            next_cred = credits_r[p] - 4'd1;
                        end
                    end
                    2'b01: begin
                        if (credits_r[p] != 4'hF) begin
                            next_cred = credits_r[p] + 4'd1;
                        end
                    end
                    default: begin
                        next_cred = credits_r[p];
                    end
                endcase

                credits_r[p] <= next_cred;
                if (next_cred < min_credits_r[p]) begin
                    min_credits_r[p] <= next_cred;
                end

                if (grant_oh_w[p]) begin
                    pipe_grant_cnt_r[p] <= pipe_grant_cnt_r[p] + 32'd1;
                    age_r[p]            <= 8'd0;
                end else if (pipe_req_valid[p]) begin
                    if (age_r[p] != 8'hFF) begin
                        age_r[p] <= age_r[p] + 8'd1;
                    end
                    if (starved_w[p]) begin
                        pipe_starve_cnt_r[p] <= pipe_starve_cnt_r[p] + 32'd1;
                    end
                end else begin
                    age_r[p] <= 8'd0;
                end

                if (pipe_req_valid[p] && pipe_hazard_stall[p]) begin
                    pipe_haz_stall_cnt_r[p] <= pipe_haz_stall_cnt_r[p] + 32'd1;
                end
                if (pipe_req_valid[p] && pipe_barrier_wait[p]) begin
                    pipe_bar_stall_cnt_r[p] <= pipe_bar_stall_cnt_r[p] + 32'd1;
                end
            end
        end
    end

endmodule
