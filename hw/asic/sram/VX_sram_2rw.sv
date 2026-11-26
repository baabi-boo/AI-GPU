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

// True dual-port (2RW) synchronous SRAM wrapper with collision warning assertion, MBIST, and power gating.
module VX_sram_2rw #(
    parameter int DEPTH       = 1024,
    parameter int DATAW       = 32,
    parameter int WRENW       = 4,
    parameter int BYTE_W      = 8,
    parameter int HAS_BIST    = 1,
    parameter int ADDRW       = (DEPTH > 1) ? $clog2(DEPTH) : 1
) (
    input  wire                 clk,
    input  wire                 rst_n,

    // Port A
    input  wire                 ce_a,
    input  wire                 we_a,
    input  wire [WRENW-1:0]     wmask_a,
    input  wire [ADDRW-1:0]     addr_a,
    input  wire [DATAW-1:0]     wdata_a,
    output wire [DATAW-1:0]     rdata_a,

    // Port B
    input  wire                 ce_b,
    input  wire                 we_b,
    input  wire [WRENW-1:0]     wmask_b,
    input  wire [ADDRW-1:0]     addr_b,
    input  wire [DATAW-1:0]     wdata_b,
    output wire [DATAW-1:0]     rdata_b,

    // MBIST bypass collar
    input  wire                 bist_en,
    input  wire                 bist_ce_a,
    input  wire                 bist_we_a,
    input  wire [WRENW-1:0]     bist_wmask_a,
    input  wire [ADDRW-1:0]     bist_addr_a,
    input  wire [DATAW-1:0]     bist_wdata_a,
    input  wire                 bist_ce_b,
    input  wire                 bist_we_b,
    input  wire [WRENW-1:0]     bist_wmask_b,
    input  wire [ADDRW-1:0]     bist_addr_b,
    input  wire [DATAW-1:0]     bist_wdata_b,

    // SRAM power-gating and retention controls
    input  wire                 sleep,
    input  wire                 sd,
    input  wire                 ret
);

    wire             eff_ce_a;
    wire             eff_we_a;
    wire [WRENW-1:0] eff_wmask_a;
    wire [ADDRW-1:0] eff_addr_a;
    wire [DATAW-1:0] eff_wdata_a;

    wire             eff_ce_b;
    wire             eff_we_b;
    wire [WRENW-1:0] eff_wmask_b;
    wire [ADDRW-1:0] eff_addr_b;
    wire [DATAW-1:0] eff_wdata_b;

    wire             pwr_block;

    assign pwr_block = sd | sleep;

    generate
        if (HAS_BIST != 0) begin : g_bist_mux
            assign eff_ce_a    = (bist_en ? bist_ce_a    : ce_a) & ~pwr_block;
            assign eff_we_a    = bist_en  ? bist_we_a    : we_a;
            assign eff_wmask_a = bist_en  ? bist_wmask_a : wmask_a;
            assign eff_addr_a  = bist_en  ? bist_addr_a  : addr_a;
            assign eff_wdata_a = bist_en  ? bist_wdata_a : wdata_a;

            assign eff_ce_b    = (bist_en ? bist_ce_b    : ce_b) & ~pwr_block;
            assign eff_we_b    = bist_en  ? bist_we_b    : we_b;
            assign eff_wmask_b = bist_en  ? bist_wmask_b : wmask_b;
            assign eff_addr_b  = bist_en  ? bist_addr_b  : addr_b;
            assign eff_wdata_b = bist_en  ? bist_wdata_b : wdata_b;
        end else begin : g_no_bist
            wire unused_bist = bist_en ^ bist_ce_a ^ bist_we_a ^ bist_ce_b ^ bist_we_b
                             ^ (^bist_wmask_a) ^ (^bist_addr_a) ^ (^bist_wdata_a)
                             ^ (^bist_wmask_b) ^ (^bist_addr_b) ^ (^bist_wdata_b);
            assign eff_ce_a    = ce_a & ~pwr_block;
            assign eff_we_a    = we_a;
            assign eff_wmask_a = wmask_a;
            assign eff_addr_a  = addr_a;
            assign eff_wdata_a = wdata_a;

            assign eff_ce_b    = ce_b & ~pwr_block;
            assign eff_we_b    = we_b;
            assign eff_wmask_b = wmask_b;
            assign eff_addr_b  = addr_b;
            assign eff_wdata_b = wdata_b;
        end
    endgenerate

    generate
        if ((DEPTH < 1) || ((WRENW * BYTE_W) != DATAW)) begin : g_bad_params
`ifndef SYNTHESIS
            initial begin
                $error("VX_sram_2rw: invalid params DEPTH=%0d WRENW=%0d BYTE_W=%0d DATAW=%0d",
                       DEPTH, WRENW, BYTE_W, DATAW);
            end
`endif
        end
    endgenerate

`ifndef SYNTHESIS
    // Collision warning assertion for simultaneous same-address access with write
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No collision check while asynchronously held in reset
        end else if (!pwr_block && eff_ce_a && eff_ce_b && (eff_addr_a == eff_addr_b)) begin
            if (eff_we_a && eff_we_b && ((eff_wmask_a & eff_wmask_b) != {WRENW{1'b0}})) begin
                $warning("VX_sram_2rw: Simultaneous write-write collision at addr=0x%0h (wmask_a=0x%0h, wmask_b=0x%0h)",
                         eff_addr_a, eff_wmask_a, eff_wmask_b);
            end else if (eff_we_a || eff_we_b) begin
                $warning("VX_sram_2rw: Simultaneous read-write collision at addr=0x%0h (we_a=%0b, we_b=%0b)",
                         eff_addr_a, eff_we_a, eff_we_b);
            end
        end
    end
`endif

`ifdef ASIC_SRAM_MACROS
    wire [DATAW-1:0] macro_rdata_a;
    wire [DATAW-1:0] macro_rdata_b;
    wire             macro_ceba;
    wire             macro_weba;
    wire [DATAW-1:0] macro_bweba;
    wire             macro_cebb;
    wire             macro_webb;
    wire [DATAW-1:0] macro_bwebb;

    assign macro_ceba = ~eff_ce_a;
    assign macro_weba = ~(eff_ce_a & eff_we_a);
    assign macro_cebb = ~eff_ce_b;
    assign macro_webb = ~(eff_ce_b & eff_we_b);

    genvar bm;
    generate
        for (bm = 0; bm < WRENW; bm = bm + 1) begin : g_bweb
            assign macro_bweba[bm * BYTE_W +: BYTE_W] = {BYTE_W{~eff_wmask_a[bm]}};
            assign macro_bwebb[bm * BYTE_W +: BYTE_W] = {BYTE_W{~eff_wmask_b[bm]}};
        end
    endgenerate

    VX_sram_2rw_macro #(
        .DEPTH  (DEPTH),
        .DATAW  (DATAW),
        .WRENW  (WRENW),
        .BYTE_W (BYTE_W),
        .ADDRW  (ADDRW)
    ) u_macro (
        .CLKA  (clk),
        .CEBA  (macro_ceba),
        .WEBA  (macro_weba),
        .BWEBA (macro_bweba),
        .AA    (eff_addr_a),
        .DA    (eff_wdata_a),
        .QA    (macro_rdata_a),
        .CLKB  (clk),
        .CEBB  (macro_cebb),
        .WEBB  (macro_webb),
        .BWEBB (macro_bwebb),
        .AB    (eff_addr_b),
        .DB    (eff_wdata_b),
        .QB    (macro_rdata_b),
        .SLP   (sleep),
        .SD    (sd),
        .RET   (ret)
    );

    assign rdata_a = (!rst_n || pwr_block) ? {DATAW{1'b0}} : macro_rdata_a;
    assign rdata_b = (!rst_n || pwr_block) ? {DATAW{1'b0}} : macro_rdata_b;
`else
    // Behavioral simulation and FPGA/open-source synthesis array fallback
    // Port A updates before Port B on colliding byte lanes if both write simultaneously.
    reg [DATAW-1:0] mem [0:DEPTH-1];
    reg [DATAW-1:0] rdata_a_q;
    reg [DATAW-1:0] rdata_b_q;
    wire            unused_ret = ret;

    always @(posedge clk) begin
        if (eff_ce_a && eff_we_a && !pwr_block) begin
            for (int wi = 0; wi < WRENW; wi = wi + 1) begin
                if (eff_wmask_a[wi]) begin
                    mem[eff_addr_a][wi * BYTE_W +: BYTE_W] <= eff_wdata_a[wi * BYTE_W +: BYTE_W];
                end
            end
        end
        if (eff_ce_b && eff_we_b && !pwr_block) begin
            for (int wi = 0; wi < WRENW; wi = wi + 1) begin
                if (eff_wmask_b[wi]) begin
                    mem[eff_addr_b][wi * BYTE_W +: BYTE_W] <= eff_wdata_b[wi * BYTE_W +: BYTE_W];
                end
            end
        end
    end

    always @(posedge clk) begin
        if (eff_ce_a && !eff_we_a && !pwr_block) begin
            rdata_a_q <= mem[eff_addr_a];
        end
        if (eff_ce_b && !eff_we_b && !pwr_block) begin
            rdata_b_q <= mem[eff_addr_b];
        end
    end

    assign rdata_a = (!rst_n || pwr_block) ? {DATAW{1'b0}} : rdata_a_q;
    assign rdata_b = (!rst_n || pwr_block) ? {DATAW{1'b0}} : rdata_b_q;
`endif

endmodule
