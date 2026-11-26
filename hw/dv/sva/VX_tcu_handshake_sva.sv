// Copyright (c) 2018-2026 Georgia Tech Vortex & AI-GPU Project
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Dual-flow (Verilator + Yosys) protocol checker for Vortex TCU / functional-unit
// valid/ready handshakes, UUID/tag conservation, and bounded latency watchdog.
module VX_tcu_handshake_sva #(
    parameter int          TAG_W        = 44,
    parameter int          MAX_INFLIGHT = 64,
    parameter logic [15:0] MAX_LATENCY  = 16'd1024,
    parameter logic [15:0] MAX_STALL    = 16'd1024,
    parameter int          FIFO_DEPTH   = 64
) (
    input  wire                 clk,
    input  wire                 reset,

    // Upstream execute/request valid-ready handshake
    input  wire                 req_valid,
    input  wire                 req_ready,
    input  wire [TAG_W-1:0]     req_tag,
    input  wire                 req_wb,

    // Downstream result/commit valid-ready handshake
    input  wire                 rsp_valid,
    input  wire                 rsp_ready,
    input  wire [TAG_W-1:0]     rsp_tag,
    input  wire                 rsp_wb
);

    localparam int PTR_W = (FIFO_DEPTH > 1) ? $clog2(FIFO_DEPTH) : 1;
    localparam int CNT_W = $clog2(FIFO_DEPTH + 1);
    localparam [CNT_W-1:0] FIFO_DEPTH_CAP   = CNT_W'(FIFO_DEPTH);
    localparam [CNT_W-1:0] MAX_INFLIGHT_CAP = (MAX_INFLIGHT >= FIFO_DEPTH)
                                            ? CNT_W'(FIFO_DEPTH)
                                            : CNT_W'(MAX_INFLIGHT);

    wire req_fire = req_valid && req_ready && req_wb;
    wire rsp_fire = rsp_valid && rsp_ready && rsp_wb;

    // ------------------------------------------------------------------------
    // Shadow in-order tag/UUID scoreboard FIFO + latency watchdog counters
    // ------------------------------------------------------------------------
    reg [TAG_W-1:0] tag_fifo [0:FIFO_DEPTH-1];
    reg [15:0]      age_fifo [0:FIFO_DEPTH-1];
    reg [PTR_W-1:0] wptr_q;
    reg [PTR_W-1:0] rptr_q;
    reg [CNT_W-1:0] inflight_q;
    reg [31:0]      cycle_q;
    reg [15:0]      req_stall_cnt_q;
    reg [15:0]      rsp_stall_cnt_q;

    reg             prev_valid_q;
    reg             prev_reset_q;
    reg             prev_req_valid_q;
    reg             prev_req_ready_q;
    reg [TAG_W-1:0] prev_req_tag_q;
    reg             prev_req_wb_q;
    reg             prev_rsp_valid_q;
    reg             prev_rsp_ready_q;
    reg [TAG_W-1:0] prev_rsp_tag_q;
    reg             prev_rsp_wb_q;

    wire [CNT_W-1:0] inflight_next = inflight_q
                                   + (req_fire ? CNT_W'(1) : CNT_W'(0))
                                   - (rsp_fire ? CNT_W'(1) : CNT_W'(0));

    wire [TAG_W-1:0] expected_rsp_tag = tag_fifo[rptr_q];
    wire [15:0]      oldest_age       = cycle_q[15:0] - age_fifo[rptr_q];

    wire check_en = !reset && prev_valid_q && !prev_reset_q;

    integer idx;

`ifdef FORMAL
    initial prev_valid_q = 1'b0;
`endif

    always @(posedge clk) begin
        if (reset) begin
            prev_valid_q     <= 1'b0;
            prev_reset_q     <= 1'b1;
            prev_req_valid_q <= 1'b0;
            prev_req_ready_q <= 1'b0;
            prev_req_tag_q   <= {TAG_W{1'b0}};
            prev_req_wb_q    <= 1'b0;
            prev_rsp_valid_q <= 1'b0;
            prev_rsp_ready_q <= 1'b0;
            prev_rsp_tag_q   <= {TAG_W{1'b0}};
            prev_rsp_wb_q    <= 1'b0;

            wptr_q           <= {PTR_W{1'b0}};
            rptr_q           <= {PTR_W{1'b0}};
            inflight_q       <= {CNT_W{1'b0}};
            cycle_q          <= 32'h0;
            req_stall_cnt_q  <= 16'h0;
            rsp_stall_cnt_q  <= 16'h0;
            for (idx = 0; idx < FIFO_DEPTH; idx = idx + 1) begin
                tag_fifo[idx] <= {TAG_W{1'b0}};
                age_fifo[idx] <= 16'h0;
            end
        end else begin
            prev_valid_q     <= 1'b1;
            prev_reset_q     <= reset;
            prev_req_valid_q <= req_valid;
            prev_req_ready_q <= req_ready;
            prev_req_tag_q   <= req_tag;
            prev_req_wb_q    <= req_wb;
            prev_rsp_valid_q <= rsp_valid;
            prev_rsp_ready_q <= rsp_ready;
            prev_rsp_tag_q   <= rsp_tag;
            prev_rsp_wb_q    <= rsp_wb;

            cycle_q          <= cycle_q + 32'd1;
            req_stall_cnt_q  <= (req_valid && !req_ready) ? (req_stall_cnt_q + 16'd1) : 16'd0;
            rsp_stall_cnt_q  <= (rsp_valid && !rsp_ready) ? (rsp_stall_cnt_q + 16'd1) : 16'd0;

            if (req_fire) begin
                tag_fifo[wptr_q] <= req_tag;
                age_fifo[wptr_q] <= cycle_q[15:0];
                wptr_q           <= (wptr_q == PTR_W'(FIFO_DEPTH - 1)) ? {PTR_W{1'b0}} : (wptr_q + PTR_W'(1));
            end
            if (rsp_fire) begin
                rptr_q <= (rptr_q == PTR_W'(FIFO_DEPTH - 1)) ? {PTR_W{1'b0}} : (rptr_q + PTR_W'(1));
            end
            inflight_q <= inflight_next;
        end
    end

`ifndef SYNTHESIS
`ifdef FORMAL
    always @(posedge clk) begin
        if (check_en) begin
            // Handshake stability
            if (prev_req_valid_q && !prev_req_ready_q) begin
                assert (req_valid);
                assert (req_tag == prev_req_tag_q);
                assert (req_wb  == prev_req_wb_q);
            end
            if (prev_rsp_valid_q && !prev_rsp_ready_q) begin
                assert (rsp_valid);
                assert (rsp_tag == prev_rsp_tag_q);
                assert (rsp_wb  == prev_rsp_wb_q);
            end

            // Tag / UUID conservation & no spurious/underflow responses
            if (rsp_fire) begin
                assert (inflight_q > {CNT_W{1'b0}});
                assert (rsp_tag == expected_rsp_tag);
            end

            // Inflight capacity bound
            assert (inflight_q <= MAX_INFLIGHT_CAP);
            assert (!(req_fire && !rsp_fire && (inflight_q == FIFO_DEPTH_CAP)));

            // Bounded latency and handshake stall watchdogs
            if ((MAX_LATENCY != 16'd0) && (inflight_q > {CNT_W{1'b0}})) begin
                assert (oldest_age <= MAX_LATENCY);
            end
            if (MAX_STALL != 16'd0) begin
                assert (req_stall_cnt_q < MAX_STALL);
                assert (rsp_stall_cnt_q < MAX_STALL);
            end
        end
    end
`else
    // Known control & payload checks
    property p_ctrl_known;
        @(posedge clk) disable iff (reset)
        (!$isunknown({req_valid, req_ready, rsp_valid, rsp_ready}));
    endproperty
    a_ctrl_known: assert property (p_ctrl_known)
        else $error("VX_tcu_handshake_sva: X/Z on valid/ready signals");

    property p_req_known;
        @(posedge clk) disable iff (reset)
        req_valid |-> !$isunknown({req_tag, req_wb});
    endproperty
    a_req_known: assert property (p_req_known)
        else $error("VX_tcu_handshake_sva: X/Z on request tag/wb while req_valid=1");

    property p_rsp_known;
        @(posedge clk) disable iff (reset)
        rsp_valid |-> !$isunknown({rsp_tag, rsp_wb});
    endproperty
    a_rsp_known: assert property (p_rsp_known)
        else $error("VX_tcu_handshake_sva: X/Z on response tag/wb while rsp_valid=1");

    // Valid/ready stability
    property p_req_stable;
        @(posedge clk) disable iff (reset)
        (req_valid && !req_ready) |=> (req_valid && $stable(req_tag) && $stable(req_wb));
    endproperty
    a_req_stable: assert property (p_req_stable)
        else $error("VX_tcu_handshake_sva: req_valid/payload unstable before req_ready");

    property p_rsp_stable;
        @(posedge clk) disable iff (reset)
        (rsp_valid && !rsp_ready) |=> (rsp_valid && $stable(rsp_tag) && $stable(rsp_wb));
    endproperty
    a_rsp_stable: assert property (p_rsp_stable)
        else $error("VX_tcu_handshake_sva: rsp_valid/payload unstable before rsp_ready");

    // UUID / tag conservation (no underflow, exact FIFO tag match)
    property p_no_spurious_rsp;
        @(posedge clk) disable iff (reset)
        rsp_fire |-> (inflight_q > {CNT_W{1'b0}});
    endproperty
    a_no_spurious_rsp: assert property (p_no_spurious_rsp)
        else $error("VX_tcu_handshake_sva: response retired when inflight_q==0");

    property p_tag_conserved;
        @(posedge clk) disable iff (reset)
        (rsp_fire && (inflight_q > {CNT_W{1'b0}})) |-> (rsp_tag == expected_rsp_tag);
    endproperty
    a_tag_conserved: assert property (p_tag_conserved)
        else $error("VX_tcu_handshake_sva: tag mismatch expected=0x%0h got=0x%0h", expected_rsp_tag, rsp_tag);

    property p_inflight_bounded;
        @(posedge clk) disable iff (reset)
        ((inflight_q <= MAX_INFLIGHT_CAP) &&
         !(req_fire && !rsp_fire && (inflight_q == FIFO_DEPTH_CAP)));
    endproperty
    a_inflight_bounded: assert property (p_inflight_bounded)
        else $error("VX_tcu_handshake_sva: inflight TCU credit overflow");

    // Bounded latency & stall watchdogs
    property p_bounded_latency;
        @(posedge clk) disable iff (reset)
        ((MAX_LATENCY == 16'd0) || (inflight_q == {CNT_W{1'b0}}) || (oldest_age <= MAX_LATENCY));
    endproperty
    a_bounded_latency: assert property (p_bounded_latency)
        else $error("VX_tcu_handshake_sva: TCU completion latency watchdog expired (%0d > %0d)", oldest_age, MAX_LATENCY);

    property p_bounded_stalls;
        @(posedge clk) disable iff (reset)
        ((MAX_STALL == 16'd0) || ((req_stall_cnt_q < MAX_STALL) && (rsp_stall_cnt_q < MAX_STALL)));
    endproperty
    a_bounded_stalls: assert property (p_bounded_stalls)
        else $error("VX_tcu_handshake_sva: TCU handshake stall watchdog expired");
`endif
`endif

    wire _unused_ok = &{1'b0,
                        check_en,
                        expected_rsp_tag,
                        oldest_age,
                        prev_req_valid_q,
                        prev_req_ready_q,
                        prev_req_tag_q,
                        prev_req_wb_q,
                        prev_rsp_valid_q,
                        prev_rsp_ready_q,
                        prev_rsp_tag_q,
                        prev_rsp_wb_q};

endmodule
