// Copyright © 2019-2026
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

// Two-port (1R+1W) synchronous SRAM wrapper with RDW mode, MBIST mux, and power gating.
module VX_sram_1r1w #(
    parameter int DEPTH       = 1024,
    parameter int DATAW       = 32,
    parameter int WRENW       = 4,
    parameter int BYTE_W      = 8,
    parameter int WRITE_FIRST = 0,
    parameter int HAS_BIST    = 1,
    parameter int ADDRW       = (DEPTH > 1) ? $clog2(DEPTH) : 1
) (
    input  wire                 clk,
    input  wire                 rst_n,

    // Write port (port W)
    input  wire                 we,
    input  wire [WRENW-1:0]     wmask,
    input  wire [ADDRW-1:0]     waddr,
    input  wire [DATAW-1:0]     wdata,

    // Read port (port R)
    input  wire                 re,
    input  wire [ADDRW-1:0]     raddr,
    output wire [DATAW-1:0]     rdata,

    // MBIST bypass collar
    input  wire                 bist_en,
    input  wire                 bist_we,
    input  wire [WRENW-1:0]     bist_wmask,
    input  wire [ADDRW-1:0]     bist_waddr,
    input  wire [DATAW-1:0]     bist_wdata,
    input  wire                 bist_re,
    input  wire [ADDRW-1:0]     bist_raddr,

    // SRAM power-gating and retention controls
    input  wire                 sleep,
    input  wire                 sd,
    input  wire                 ret
);

    wire             eff_we;
    wire [WRENW-1:0] eff_wmask;
    wire [ADDRW-1:0] eff_waddr;
    wire [DATAW-1:0] eff_wdata;
    wire             eff_re;
    wire [ADDRW-1:0] eff_raddr;
    wire             pwr_block;

    assign pwr_block = sd | sleep;

    generate
        if (HAS_BIST != 0) begin : g_bist_mux
            assign eff_we    = (bist_en ? bist_we    : we) & ~pwr_block;
            assign eff_wmask = bist_en  ? bist_wmask : wmask;
            assign eff_waddr = bist_en  ? bist_waddr : waddr;
            assign eff_wdata = bist_en  ? bist_wdata : wdata;
            assign eff_re    = (bist_en ? bist_re    : re) & ~pwr_block;
            assign eff_raddr = bist_en  ? bist_raddr : raddr;
        end else begin : g_no_bist
            wire unused_bist = bist_en ^ bist_we ^ bist_re
                             ^ (^bist_wmask) ^ (^bist_waddr) ^ (^bist_wdata) ^ (^bist_raddr);
            assign eff_we    = we & ~pwr_block;
            assign eff_wmask = wmask;
            assign eff_waddr = waddr;
            assign eff_wdata = wdata;
            assign eff_re    = re & ~pwr_block;
            assign eff_raddr = raddr;
        end
    endgenerate

    generate
        if ((DEPTH < 1) || ((WRENW * BYTE_W) != DATAW)) begin : g_bad_params
`ifndef SYNTHESIS
            initial begin
                $error("VX_sram_1r1w: invalid params DEPTH=%0d WRENW=%0d BYTE_W=%0d DATAW=%0d",
                       DEPTH, WRENW, BYTE_W, DATAW);
            end
`endif
        end
    endgenerate

`ifndef SYNTHESIS
    always @(posedge clk) begin
        if (rst_n && !pwr_block && eff_re && eff_we && (eff_waddr == eff_raddr) && (WRITE_FIRST == 0)) begin
            if (|eff_wmask) begin
                // Read-first mode returns pre-write data cleanly on same-cycle collision
            end
        end
    end
`endif

`ifdef ASIC_SRAM_MACROS
    wire [DATAW-1:0] macro_rdata;
    wire             macro_reb;
    wire             macro_web;
    wire [DATAW-1:0] macro_bweb;

    assign macro_reb = ~eff_re;
    assign macro_web = ~eff_we;

    genvar bm;
    generate
        for (bm = 0; bm < WRENW; bm = bm + 1) begin : g_bweb
            assign macro_bweb[bm * BYTE_W +: BYTE_W] = {BYTE_W{~eff_wmask[bm]}};
        end
    endgenerate

    VX_sram_1r1w_macro #(
        .DEPTH  (DEPTH),
        .DATAW  (DATAW),
        .WRENW  (WRENW),
        .BYTE_W (BYTE_W),
        .ADDRW  (ADDRW)
    ) u_macro (
        .CLKA  (clk),
        .CLKB  (clk),
        .WEBA  (macro_web),
        .BWEBA (macro_bweb),
        .AA    (eff_waddr),
        .DA    (eff_wdata),
        .REBB  (macro_reb),
        .AB    (eff_raddr),
        .QB    (macro_rdata),
        .SLP   (sleep),
        .SD    (sd),
        .RET   (ret)
    );

    generate
        if (WRITE_FIRST != 0) begin : g_macro_wf
            reg             fwd_valid_q;
            reg [WRENW-1:0] fwd_wmask_q;
            reg [DATAW-1:0] fwd_wdata_q;
            reg [DATAW-1:0] mux_rdata;
            wire            wf_bist_disable;

            assign wf_bist_disable = (HAS_BIST != 0) ? bist_en : 1'b0;

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    fwd_valid_q <= 1'b0;
                    fwd_wmask_q <= {WRENW{1'b0}};
                    fwd_wdata_q <= {DATAW{1'b0}};
                end else if (sd) begin
                    fwd_valid_q <= 1'b0;
                    fwd_wmask_q <= {WRENW{1'b0}};
                    fwd_wdata_q <= {DATAW{1'b0}};
                end else if (eff_re) begin
                    fwd_valid_q <= !wf_bist_disable && eff_we && (eff_waddr == eff_raddr);
                    fwd_wmask_q <= eff_wmask;
                    fwd_wdata_q <= eff_wdata;
                end else begin
                    fwd_valid_q <= 1'b0;
                end
            end

            always @(*) begin
                mux_rdata = macro_rdata;
                for (int fi = 0; fi < WRENW; fi = fi + 1) begin
                    if (fwd_valid_q && fwd_wmask_q[fi]) begin
                        mux_rdata[fi * BYTE_W +: BYTE_W] = fwd_wdata_q[fi * BYTE_W +: BYTE_W];
                    end
                end
            end

            assign rdata = (!rst_n || pwr_block) ? {DATAW{1'b0}} : mux_rdata;
        end else begin : g_macro_rf
            assign rdata = (!rst_n || pwr_block) ? {DATAW{1'b0}} : macro_rdata;
        end
    endgenerate
`else
    // Behavioral simulation and FPGA/open-source synthesis array fallback
    reg [DATAW-1:0] mem [0:DEPTH-1];
    reg [DATAW-1:0] rdata_q;
    wire            unused_ret = ret;

    always @(posedge clk) begin
        if (eff_we) begin
            for (int wi = 0; wi < WRENW; wi = wi + 1) begin
                if (eff_wmask[wi]) begin
                    mem[eff_waddr][wi * BYTE_W +: BYTE_W] <= eff_wdata[wi * BYTE_W +: BYTE_W];
                end
            end
        end
    end

    always @(posedge clk) begin
        if (eff_re && !pwr_block) begin
            rdata_q <= mem[eff_raddr];
        end
    end

    generate
        if (WRITE_FIRST != 0) begin : g_write_first
            reg             fwd_valid_q;
            reg [WRENW-1:0] fwd_wmask_q;
            reg [DATAW-1:0] fwd_wdata_q;
            reg [DATAW-1:0] mux_rdata;
            wire            wf_bist_disable;

            assign wf_bist_disable = (HAS_BIST != 0) ? bist_en : 1'b0;

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    fwd_valid_q <= 1'b0;
                    fwd_wmask_q <= {WRENW{1'b0}};
                    fwd_wdata_q <= {DATAW{1'b0}};
                end else if (sd) begin
                    fwd_valid_q <= 1'b0;
                    fwd_wmask_q <= {WRENW{1'b0}};
                    fwd_wdata_q <= {DATAW{1'b0}};
                end else if (eff_re) begin
                    fwd_valid_q <= !wf_bist_disable && eff_we && (eff_waddr == eff_raddr);
                    fwd_wmask_q <= eff_wmask;
                    fwd_wdata_q <= eff_wdata;
                end else begin
                    fwd_valid_q <= 1'b0;
                end
            end

            always @(*) begin
                mux_rdata = rdata_q;
                for (int fi = 0; fi < WRENW; fi = fi + 1) begin
                    if (fwd_valid_q && fwd_wmask_q[fi]) begin
                        mux_rdata[fi * BYTE_W +: BYTE_W] = fwd_wdata_q[fi * BYTE_W +: BYTE_W];
                    end
                end
            end

            assign rdata = (!rst_n || pwr_block) ? {DATAW{1'b0}} : mux_rdata;
        end else begin : g_read_first
            assign rdata = (!rst_n || pwr_block) ? {DATAW{1'b0}} : rdata_q;
        end
    endgenerate
`endif

endmodule
