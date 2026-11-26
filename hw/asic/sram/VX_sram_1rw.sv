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

// Single-port synchronous SRAM wrapper with foundry macro hook, MBIST mux, and power gating.
module VX_sram_1rw #(
    parameter int DEPTH       = 1024,
    parameter int DATAW       = 32,
    parameter int WRENW       = 4,
    parameter int BYTE_W      = 8,
    parameter int HAS_BIST    = 1,
    parameter int ADDRW       = (DEPTH > 1) ? $clog2(DEPTH) : 1
) (
    input  wire                 clk,
    input  wire                 rst_n,

    // Functional port (active-high request/write enables)
    input  wire                 ce,
    input  wire                 we,
    input  wire [WRENW-1:0]     wmask,
    input  wire [ADDRW-1:0]     addr,
    input  wire [DATAW-1:0]     wdata,
    output wire [DATAW-1:0]     rdata,

    // MBIST bypass collar
    input  wire                 bist_en,
    input  wire                 bist_ce,
    input  wire                 bist_we,
    input  wire [WRENW-1:0]     bist_wmask,
    input  wire [ADDRW-1:0]     bist_addr,
    input  wire [DATAW-1:0]     bist_wdata,

    // SRAM power-gating and retention controls
    input  wire                 sleep,
    input  wire                 sd,
    input  wire                 ret
);

    wire             eff_ce;
    wire             eff_we;
    wire [WRENW-1:0] eff_wmask;
    wire [ADDRW-1:0] eff_addr;
    wire [DATAW-1:0] eff_wdata;
    wire             pwr_block;

    assign pwr_block = sd | sleep;

    generate
        if (HAS_BIST != 0) begin : g_bist_mux
            assign eff_ce    = (bist_en ? bist_ce    : ce) & ~pwr_block;
            assign eff_we    = bist_en  ? bist_we    : we;
            assign eff_wmask = bist_en  ? bist_wmask : wmask;
            assign eff_addr  = bist_en  ? bist_addr  : addr;
            assign eff_wdata = bist_en  ? bist_wdata : wdata;
        end else begin : g_no_bist
            wire unused_bist = bist_en ^ bist_ce ^ bist_we
                             ^ (^bist_wmask) ^ (^bist_addr) ^ (^bist_wdata);
            assign eff_ce    = ce & ~pwr_block;
            assign eff_we    = we;
            assign eff_wmask = wmask;
            assign eff_addr  = addr;
            assign eff_wdata = wdata;
        end
    endgenerate

    generate
        if ((DEPTH < 1) || ((WRENW * BYTE_W) != DATAW)) begin : g_bad_params
`ifndef SYNTHESIS
            initial begin
                $error("VX_sram_1rw: invalid params DEPTH=%0d WRENW=%0d BYTE_W=%0d DATAW=%0d",
                       DEPTH, WRENW, BYTE_W, DATAW);
            end
`endif
        end
    endgenerate

`ifdef ASIC_SRAM_MACROS
    // Foundry 1RW macro black-box hook: replace or bind per compiled cut
    wire [DATAW-1:0] macro_rdata;
    wire             macro_ceb;
    wire             macro_web;
    wire [DATAW-1:0] macro_bweb;

    assign macro_ceb = ~eff_ce;
    assign macro_web = ~(eff_ce & eff_we);

    genvar bm;
    generate
        for (bm = 0; bm < WRENW; bm = bm + 1) begin : g_bweb
            assign macro_bweb[bm * BYTE_W +: BYTE_W] = {BYTE_W{~eff_wmask[bm]}};
        end
    endgenerate

    VX_sram_1rw_macro #(
        .DEPTH  (DEPTH),
        .DATAW  (DATAW),
        .WRENW  (WRENW),
        .BYTE_W (BYTE_W),
        .ADDRW  (ADDRW)
    ) u_macro (
        .CLK   (clk),
        .CEB   (macro_ceb),
        .WEB   (macro_web),
        .BWEB  (macro_bweb),
        .A     (eff_addr),
        .D     (eff_wdata),
        .Q     (macro_rdata),
        .SLP   (sleep),
        .SD    (sd),
        .RET   (ret)
    );

    wire unused_rst_macro = rst_n;
    assign rdata = (!rst_n || pwr_block) ? {DATAW{1'b0}} : macro_rdata;
`else
    // Behavioral simulation and FPGA/open-source synthesis array fallback
    reg [DATAW-1:0] mem [0:DEPTH-1];
    reg [DATAW-1:0] rdata_q;
    wire            unused_ret = ret;

    always @(posedge clk) begin
        if (eff_ce && !eff_we && !pwr_block) begin
            rdata_q <= mem[eff_addr];
        end
    end

    always @(posedge clk) begin
        if (eff_ce && eff_we && !pwr_block) begin
            for (int wi = 0; wi < WRENW; wi = wi + 1) begin
                if (eff_wmask[wi]) begin
                    mem[eff_addr][wi * BYTE_W +: BYTE_W] <= eff_wdata[wi * BYTE_W +: BYTE_W];
                end
            end
        end
    end

    assign rdata = (!rst_n || pwr_block) ? {DATAW{1'b0}} : rdata_q;
`endif

endmodule
