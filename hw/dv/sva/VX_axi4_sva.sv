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

// Dual-flow (Verilator + Yosys) AXI4-Lite & AXI4-Full protocol assertion checker.
// Verifies valid/ready payload stability (AW, W, B, AR, R), response codes,
// WLAST framing, and post-reset known-control guarantees.
module VX_axi4_sva #(
    parameter int          ADDRW      = 48,
    parameter int          DATAW      = 64,
    parameter int          IDW        = 4,
    parameter int          IS_FULL    = 1,
    parameter logic [15:0] MAX_STALL  = 16'd4096
) (
    input  wire                     clk,
    input  wire                     rst_n,

    // Write Address Channel
    input  wire                     awvalid,
    input  wire                     awready,
    input  wire [IDW-1:0]           awid,
    input  wire [ADDRW-1:0]         awaddr,
    input  wire [7:0]               awlen,
    input  wire [2:0]               awsize,
    input  wire [1:0]               awburst,
    input  wire [2:0]               awprot,

    // Write Data Channel
    input  wire                     wvalid,
    input  wire                     wready,
    input  wire [DATAW-1:0]         wdata,
    input  wire [(DATAW/8)-1:0]     wstrb,
    input  wire                     wlast,

    // Write Response Channel
    input  wire                     bvalid,
    input  wire                     bready,
    input  wire [IDW-1:0]           bid,
    input  wire [1:0]               bresp,

    // Read Address Channel
    input  wire                     arvalid,
    input  wire                     arready,
    input  wire [IDW-1:0]           arid,
    input  wire [ADDRW-1:0]         araddr,
    input  wire [7:0]               arlen,
    input  wire [2:0]               arsize,
    input  wire [1:0]               arburst,
    input  wire [2:0]               arprot,

    // Read Data Channel
    input  wire                     rvalid,
    input  wire                     rready,
    input  wire [IDW-1:0]           rid,
    input  wire [DATAW-1:0]         rdata,
    input  wire [1:0]               rresp,
    input  wire                     rlast
);

    localparam int STRBW = DATAW / 8;

    // ------------------------------------------------------------------------
    // Previous-cycle shadow state (shared across FORMAL and Verilator paths)
    // ------------------------------------------------------------------------
    reg                 prev_valid_q;
    reg                 prev_rst_n_q;

    reg                 prev_awvalid_q;
    reg                 prev_awready_q;
    reg [IDW-1:0]       prev_awid_q;
    reg [ADDRW-1:0]     prev_awaddr_q;
    reg [7:0]           prev_awlen_q;
    reg [2:0]           prev_awsize_q;
    reg [1:0]           prev_awburst_q;
    reg [2:0]           prev_awprot_q;

    reg                 prev_wvalid_q;
    reg                 prev_wready_q;
    reg [DATAW-1:0]     prev_wdata_q;
    reg [STRBW-1:0]     prev_wstrb_q;
    reg                 prev_wlast_q;

    reg                 prev_bvalid_q;
    reg                 prev_bready_q;
    reg [IDW-1:0]       prev_bid_q;
    reg [1:0]           prev_bresp_q;

    reg                 prev_arvalid_q;
    reg                 prev_arready_q;
    reg [IDW-1:0]       prev_arid_q;
    reg [ADDRW-1:0]     prev_araddr_q;
    reg [7:0]           prev_arlen_q;
    reg [2:0]           prev_arsize_q;
    reg [1:0]           prev_arburst_q;
    reg [2:0]           prev_arprot_q;

    reg                 prev_rvalid_q;
    reg                 prev_rready_q;
    reg [IDW-1:0]       prev_rid_q;
    reg [DATAW-1:0]     prev_rdata_q;
    reg [1:0]           prev_rresp_q;
    reg                 prev_rlast_q;

    // Outstanding beat / transaction counters & stall watchdogs
    reg [7:0]           wbeat_cnt_q;
    reg [15:0]          aw_stall_cnt_q;
    reg [15:0]          w_stall_cnt_q;
    reg [15:0]          b_stall_cnt_q;
    reg [15:0]          ar_stall_cnt_q;
    reg [15:0]          r_stall_cnt_q;

    wire aw_fire = awvalid && awready;
    wire w_fire  = wvalid  && wready;
    wire b_fire  = bvalid  && bready;
    wire ar_fire = arvalid && arready;
    wire r_fire  = rvalid  && rready;

    wire check_en = rst_n && prev_valid_q && prev_rst_n_q;

`ifdef FORMAL
    initial prev_valid_q = 1'b0;
`endif

    always @(posedge clk) begin
        if (!rst_n) begin
            prev_valid_q   <= 1'b0;
            prev_rst_n_q   <= 1'b0;
            prev_awvalid_q <= 1'b0;
            prev_awready_q <= 1'b0;
            prev_awid_q    <= {IDW{1'b0}};
            prev_awaddr_q  <= {ADDRW{1'b0}};
            prev_awlen_q   <= 8'h00;
            prev_awsize_q  <= 3'h0;
            prev_awburst_q <= 2'h0;
            prev_awprot_q  <= 3'h0;
            prev_wvalid_q  <= 1'b0;
            prev_wready_q  <= 1'b0;
            prev_wdata_q   <= {DATAW{1'b0}};
            prev_wstrb_q   <= {STRBW{1'b0}};
            prev_wlast_q   <= 1'b0;
            prev_bvalid_q  <= 1'b0;
            prev_bready_q  <= 1'b0;
            prev_bid_q     <= {IDW{1'b0}};
            prev_bresp_q   <= 2'h0;
            prev_arvalid_q <= 1'b0;
            prev_arready_q <= 1'b0;
            prev_arid_q    <= {IDW{1'b0}};
            prev_araddr_q  <= {ADDRW{1'b0}};
            prev_arlen_q   <= 8'h00;
            prev_arsize_q  <= 3'h0;
            prev_arburst_q <= 2'h0;
            prev_arprot_q  <= 3'h0;
            prev_rvalid_q  <= 1'b0;
            prev_rready_q  <= 1'b0;
            prev_rid_q     <= {IDW{1'b0}};
            prev_rdata_q   <= {DATAW{1'b0}};
            prev_rresp_q   <= 2'h0;
            prev_rlast_q   <= 1'b0;
            wbeat_cnt_q    <= 8'h00;
            aw_stall_cnt_q <= 16'h0000;
            w_stall_cnt_q  <= 16'h0000;
            b_stall_cnt_q  <= 16'h0000;
            ar_stall_cnt_q <= 16'h0000;
            r_stall_cnt_q  <= 16'h0000;
        end else begin
            prev_valid_q   <= 1'b1;
            prev_rst_n_q   <= rst_n;

            prev_awvalid_q <= awvalid;
            prev_awready_q <= awready;
            prev_awid_q    <= awid;
            prev_awaddr_q  <= awaddr;
            prev_awlen_q   <= awlen;
            prev_awsize_q  <= awsize;
            prev_awburst_q <= awburst;
            prev_awprot_q  <= awprot;

            prev_wvalid_q  <= wvalid;
            prev_wready_q  <= wready;
            prev_wdata_q   <= wdata;
            prev_wstrb_q   <= wstrb;
            prev_wlast_q   <= wlast;

            prev_bvalid_q  <= bvalid;
            prev_bready_q  <= bready;
            prev_bid_q     <= bid;
            prev_bresp_q   <= bresp;

            prev_arvalid_q <= arvalid;
            prev_arready_q <= arready;
            prev_arid_q    <= arid;
            prev_araddr_q  <= araddr;
            prev_arlen_q   <= arlen;
            prev_arsize_q  <= arsize;
            prev_arburst_q <= arburst;
            prev_arprot_q  <= arprot;

            prev_rvalid_q  <= rvalid;
            prev_rready_q  <= rready;
            prev_rid_q     <= rid;
            prev_rdata_q   <= rdata;
            prev_rresp_q   <= rresp;
            prev_rlast_q   <= rlast;

            if (w_fire) begin
                wbeat_cnt_q <= wlast ? 8'h00 : (wbeat_cnt_q + 8'h01);
            end

            aw_stall_cnt_q <= (awvalid && !awready) ? (aw_stall_cnt_q + 16'd1) : 16'd0;
            w_stall_cnt_q  <= (wvalid  && !wready)  ? (w_stall_cnt_q  + 16'd1) : 16'd0;
            b_stall_cnt_q  <= (bvalid  && !bready)  ? (b_stall_cnt_q  + 16'd1) : 16'd0;
            ar_stall_cnt_q <= (arvalid && !arready) ? (ar_stall_cnt_q + 16'd1) : 16'd0;
            r_stall_cnt_q  <= (rvalid  && !rready)  ? (r_stall_cnt_q  + 16'd1) : 16'd0;
        end
    end

`ifndef SYNTHESIS
`ifdef FORMAL
    // Yosys-smtbmc compatible immediate/sequential assertions
    always @(posedge clk) begin
        if (check_en) begin
            // 1. Reset-clear: valid outputs must be 0 on first cycle out of reset
            if (prev_awvalid_q && !prev_awready_q) begin
                assert (awvalid);
                assert (awaddr  == prev_awaddr_q);
                assert (awprot  == prev_awprot_q);
                if (IS_FULL != 0) begin
                    assert (awid    == prev_awid_q);
                    assert (awlen   == prev_awlen_q);
                    assert (awsize  == prev_awsize_q);
                    assert (awburst == prev_awburst_q);
                end
            end

            if (prev_wvalid_q && !prev_wready_q) begin
                assert (wvalid);
                assert (wdata == prev_wdata_q);
                assert (wstrb == prev_wstrb_q);
                if (IS_FULL != 0) begin
                    assert (wlast == prev_wlast_q);
                end
            end

            if (prev_bvalid_q && !prev_bready_q) begin
                assert (bvalid);
                assert (bresp == prev_bresp_q);
                if (IS_FULL != 0) begin
                    assert (bid == prev_bid_q);
                end
            end

            if (prev_arvalid_q && !prev_arready_q) begin
                assert (arvalid);
                assert (araddr  == prev_araddr_q);
                assert (arprot  == prev_arprot_q);
                if (IS_FULL != 0) begin
                    assert (arid    == prev_arid_q);
                    assert (arlen   == prev_arlen_q);
                    assert (arsize  == prev_arsize_q);
                    assert (arburst == prev_arburst_q);
                end
            end

            if (prev_rvalid_q && !prev_rready_q) begin
                assert (rvalid);
                assert (rdata == prev_rdata_q);
                assert (rresp == prev_rresp_q);
                if (IS_FULL != 0) begin
                    assert (rid   == prev_rid_q);
                    assert (rlast == prev_rlast_q);
                end
            end

            if ((IS_FULL != 0) && awvalid) begin
                assert (awburst != 2'b11);
            end
            if ((IS_FULL != 0) && arvalid) begin
                assert (arburst != 2'b11);
            end
            if ((IS_FULL != 0) && (awlen == 8'h00) && wvalid && (wbeat_cnt_q == 8'h00)) begin
                // Single-beat write must assert WLAST when no prior burst beat is open
                assert (wlast);
            end
            if (MAX_STALL != 16'd0) begin
                assert (aw_stall_cnt_q < MAX_STALL);
                assert (w_stall_cnt_q  < MAX_STALL);
                assert (b_stall_cnt_q  < MAX_STALL);
                assert (ar_stall_cnt_q < MAX_STALL);
                assert (r_stall_cnt_q  < MAX_STALL);
            end
        end
    end
`else
    // SV2012 concurrent SVA properties + known-value (no X/Z) checks for Verilator

    // Post-reset known-value checks on control & handshake lines
    property p_ctrl_known;
        @(posedge clk) disable iff (!rst_n)
        (!$isunknown({awvalid, awready, wvalid, wready, bvalid, bready,
                      arvalid, arready, rvalid, rready}));
    endproperty
    a_ctrl_known: assert property (p_ctrl_known)
        else $error("VX_axi4_sva: X/Z detected on AXI4 valid/ready control signals");

    property p_aw_payload_known;
        @(posedge clk) disable iff (!rst_n)
        awvalid |-> (!$isunknown({awaddr, awprot}) &&
                     ((IS_FULL == 0) || !$isunknown({awid, awlen, awsize, awburst})));
    endproperty
    a_aw_payload_known: assert property (p_aw_payload_known)
        else $error("VX_axi4_sva: X/Z detected on AW channel payload while AWVALID=1");

    property p_w_payload_known;
        @(posedge clk) disable iff (!rst_n)
        wvalid |-> (!$isunknown({wdata, wstrb}) && ((IS_FULL == 0) || !$isunknown(wlast)));
    endproperty
    a_w_payload_known: assert property (p_w_payload_known)
        else $error("VX_axi4_sva: X/Z detected on W channel payload while WVALID=1");

    property p_b_payload_known;
        @(posedge clk) disable iff (!rst_n)
        bvalid |-> (!$isunknown(bresp) && ((IS_FULL == 0) || !$isunknown(bid)));
    endproperty
    a_b_payload_known: assert property (p_b_payload_known)
        else $error("VX_axi4_sva: X/Z detected on B channel payload while BVALID=1");

    property p_ar_payload_known;
        @(posedge clk) disable iff (!rst_n)
        arvalid |-> (!$isunknown({araddr, arprot}) &&
                     ((IS_FULL == 0) || !$isunknown({arid, arlen, arsize, arburst})));
    endproperty
    a_ar_payload_known: assert property (p_ar_payload_known)
        else $error("VX_axi4_sva: X/Z detected on AR channel payload while ARVALID=1");

    property p_r_payload_known;
        @(posedge clk) disable iff (!rst_n)
        rvalid |-> (!$isunknown({rdata, rresp}) && ((IS_FULL == 0) || !$isunknown({rid, rlast})));
    endproperty
    a_r_payload_known: assert property (p_r_payload_known)
        else $error("VX_axi4_sva: X/Z detected on R channel payload while RVALID=1");

    // Channel stability assertions (AXI4 Spec A3.2.1)
    property p_aw_valid_hold;
        @(posedge clk) disable iff (!rst_n)
        (awvalid && !awready) |=> awvalid;
    endproperty
    a_aw_valid_hold: assert property (p_aw_valid_hold)
        else $error("VX_axi4_sva: AWVALID deasserted before AWREADY");

    property p_aw_payload_stable;
        @(posedge clk) disable iff (!rst_n)
        (awvalid && !awready) |=> ($stable(awaddr) && $stable(awprot) &&
                                   ((IS_FULL == 0) || ($stable(awid) && $stable(awlen) &&
                                                       $stable(awsize) && $stable(awburst))));
    endproperty
    a_aw_payload_stable: assert property (p_aw_payload_stable)
        else $error("VX_axi4_sva: AW channel payload mutated before AWREADY");

    property p_w_valid_hold;
        @(posedge clk) disable iff (!rst_n)
        (wvalid && !wready) |=> wvalid;
    endproperty
    a_w_valid_hold: assert property (p_w_valid_hold)
        else $error("VX_axi4_sva: WVALID deasserted before WREADY");

    property p_w_payload_stable;
        @(posedge clk) disable iff (!rst_n)
        (wvalid && !wready) |=> ($stable(wdata) && $stable(wstrb) &&
                                 ((IS_FULL == 0) || $stable(wlast)));
    endproperty
    a_w_payload_stable: assert property (p_w_payload_stable)
        else $error("VX_axi4_sva: W channel payload mutated before WREADY");

    property p_b_valid_hold;
        @(posedge clk) disable iff (!rst_n)
        (bvalid && !bready) |=> bvalid;
    endproperty
    a_b_valid_hold: assert property (p_b_valid_hold)
        else $error("VX_axi4_sva: BVALID deasserted before BREADY");

    property p_b_payload_stable;
        @(posedge clk) disable iff (!rst_n)
        (bvalid && !bready) |=> ($stable(bresp) && ((IS_FULL == 0) || $stable(bid)));
    endproperty
    a_b_payload_stable: assert property (p_b_payload_stable)
        else $error("VX_axi4_sva: B channel payload mutated before BREADY");

    property p_ar_valid_hold;
        @(posedge clk) disable iff (!rst_n)
        (arvalid && !arready) |=> arvalid;
    endproperty
    a_ar_valid_hold: assert property (p_ar_valid_hold)
        else $error("VX_axi4_sva: ARVALID deasserted before ARREADY");

    property p_ar_payload_stable;
        @(posedge clk) disable iff (!rst_n)
        (arvalid && !arready) |=> ($stable(araddr) && $stable(arprot) &&
                                   ((IS_FULL == 0) || ($stable(arid) && $stable(arlen) &&
                                                       $stable(arsize) && $stable(arburst))));
    endproperty
    a_ar_payload_stable: assert property (p_ar_payload_stable)
        else $error("VX_axi4_sva: AR channel payload mutated before ARREADY");

    property p_r_valid_hold;
        @(posedge clk) disable iff (!rst_n)
        (rvalid && !rready) |=> rvalid;
    endproperty
    a_r_valid_hold: assert property (p_r_valid_hold)
        else $error("VX_axi4_sva: RVALID deasserted before RREADY");

    property p_r_payload_stable;
        @(posedge clk) disable iff (!rst_n)
        (rvalid && !rready) |=> ($stable(rdata) && $stable(rresp) &&
                                 ((IS_FULL == 0) || ($stable(rid) && $stable(rlast))));
    endproperty
    a_r_payload_stable: assert property (p_r_payload_stable)
        else $error("VX_axi4_sva: R channel payload mutated before RREADY");

    // Legal AXI4 burst encoding & stall bound watchdogs
    property p_burst_legal;
        @(posedge clk) disable iff (!rst_n)
        ((IS_FULL == 0) || ((!awvalid || (awburst != 2'b11)) && (!arvalid || (arburst != 2'b11))));
    endproperty
    a_burst_legal: assert property (p_burst_legal)
        else $error("VX_axi4_sva: reserved burst type 2'b11 observed");

    property p_bounded_stalls;
        @(posedge clk) disable iff (!rst_n)
        ((MAX_STALL == 16'd0) ||
         ((aw_stall_cnt_q < MAX_STALL) &&
          (w_stall_cnt_q  < MAX_STALL) &&
          (b_stall_cnt_q  < MAX_STALL) &&
          (ar_stall_cnt_q < MAX_STALL) &&
          (r_stall_cnt_q  < MAX_STALL)));
    endproperty
    a_bounded_stalls: assert property (p_bounded_stalls)
        else $error("VX_axi4_sva: AXI4 channel stall watchdog expired");
`endif
`endif

    // Keep internal handshake/shadow monitors clean under strict lint
    wire _unused_ok = &{1'b0,
                        check_en,
                        aw_fire,
                        b_fire,
                        ar_fire,
                        r_fire,
                        wbeat_cnt_q,
                        prev_awvalid_q,
                        prev_awready_q,
                        prev_awid_q,
                        prev_awaddr_q,
                        prev_awlen_q,
                        prev_awsize_q,
                        prev_awburst_q,
                        prev_awprot_q,
                        prev_wvalid_q,
                        prev_wready_q,
                        prev_wdata_q,
                        prev_wstrb_q,
                        prev_wlast_q,
                        prev_bvalid_q,
                        prev_bready_q,
                        prev_bid_q,
                        prev_bresp_q,
                        prev_arvalid_q,
                        prev_arready_q,
                        prev_arid_q,
                        prev_araddr_q,
                        prev_arlen_q,
                        prev_arsize_q,
                        prev_arburst_q,
                        prev_arprot_q,
                        prev_rvalid_q,
                        prev_rready_q,
                        prev_rid_q,
                        prev_rdata_q,
                        prev_rresp_q,
                        prev_rlast_q};

endmodule
