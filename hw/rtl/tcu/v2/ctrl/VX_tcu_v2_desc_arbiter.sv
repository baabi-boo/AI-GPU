// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_desc_arbiter #(
    parameter int NUM_QUEUES = 2
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic [NUM_QUEUES-1:0]                           req_valid,
    output logic [NUM_QUEUES-1:0]                           req_ready,
    input  VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t [NUM_QUEUES-1:0] req_desc,
    input  logic [NUM_QUEUES-1:0][3:0]                      req_prio,
    output logic                                            grant_valid,
    input  logic                                            grant_ready,
    output VX_tcu_v2_pkg::tcu_v2_wgmma_desc_t               grant_desc,
    output logic [$clog2(NUM_QUEUES > 1 ? NUM_QUEUES : 2)-1:0] grant_qid,
    output logic [NUM_QUEUES-1:0][31:0]                     qid_grant_cnt_out,
    output logic [31:0]                                     arb_conflict_cnt_out
);

    import VX_tcu_v2_pkg::*;

    localparam int QID_W = $clog2(NUM_QUEUES > 1 ? NUM_QUEUES : 2);

    logic [QID_W-1:0]           rr_ptr_r;
    logic [NUM_QUEUES-1:0][7:0] age_r;
    logic [NUM_QUEUES-1:0][31:0] qid_grant_cnt_r;
    logic [31:0]                arb_conflict_cnt_r;

    logic                       any_valid_w;
    logic                       multi_valid_w;
    logic [QID_W-1:0]           winner_w;
    logic [NUM_QUEUES-1:0]      grant_oh_w;
    logic                       grant_fire_w;

    always_comb begin
        logic [7:0] best_score;
        logic [7:0] score;
        logic [2:0] req_cnt;
        logic       found_first;
        int         idx;

        any_valid_w   = 1'b0;
        multi_valid_w = 1'b0;
        winner_w      = rr_ptr_r;
        best_score    = 8'd0;
        score         = 8'd0;
        req_cnt       = 3'd0;
        found_first   = 1'b0;
        idx           = 0;

        for (int q = 0; q < NUM_QUEUES; ++q) begin
            if (req_valid[q]) begin
                any_valid_w = 1'b1;
                req_cnt     = req_cnt + 3'd1;
            end
        end
        multi_valid_w = (req_cnt > 3'd1);

        if (any_valid_w) begin
            for (int off = 0; off < NUM_QUEUES; ++off) begin
                idx   = (int'(rr_ptr_r) + off) % NUM_QUEUES;
                score = {4'd0, req_prio[idx]} + age_r[idx];
                if (req_valid[idx] && (!found_first || (score > best_score))) begin
                    found_first = 1'b1;
                    best_score  = score;
                    winner_w    = QID_W'(idx[QID_W-1:0]);
                end
            end
        end

        grant_oh_w = '0;
        if (any_valid_w && grant_ready) begin
            grant_oh_w[winner_w] = 1'b1;
        end
    end

    assign grant_valid          = any_valid_w;
    assign grant_desc           = req_desc[winner_w];
    assign grant_qid            = winner_w;
    assign req_ready            = grant_oh_w;
    assign grant_fire_w         = grant_valid && grant_ready;
    assign qid_grant_cnt_out    = qid_grant_cnt_r;
    assign arb_conflict_cnt_out = arb_conflict_cnt_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            rr_ptr_r           <= '0;
            arb_conflict_cnt_r <= 32'd0;
            for (int q = 0; q < NUM_QUEUES; ++q) begin
                age_r[q]           <= 8'd0;
                qid_grant_cnt_r[q] <= 32'd0;
            end
        end else begin
            if (grant_fire_w) begin
                qid_grant_cnt_r[winner_w] <= qid_grant_cnt_r[winner_w] + 32'd1;
                if (multi_valid_w) begin
                    arb_conflict_cnt_r <= arb_conflict_cnt_r + 32'd1;
                end
                if ((int'(winner_w) + 1) >= NUM_QUEUES) begin
                    rr_ptr_r <= '0;
                end else begin
                    rr_ptr_r <= winner_w + QID_W'(1);
                end
            end

            for (int q = 0; q < NUM_QUEUES; ++q) begin
                if (grant_oh_w[q]) begin
                    age_r[q] <= 8'd0;
                end else if (req_valid[q]) begin
                    if (age_r[q] != 8'hFF) begin
                        age_r[q] <= age_r[q] + 8'd1;
                    end
                end else begin
                    age_r[q] <= 8'd0;
                end
            end
        end
    end

endmodule
