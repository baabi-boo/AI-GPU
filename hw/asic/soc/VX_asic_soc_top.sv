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

// Dual-clock CDC-clean ASIC SoC Top-Level Shell (`VX_asic_soc_top`).
// Integrates:
//   - Independent 2-FF async-assert, sync-deassert reset synchronizers for `clk_core` and `clk_axi`
//   - Always-on AXI4-Lite slave CSR register bank & boot/scratchpad SRAM aperture (`clk_axi`)
//   - Parameterized Gray-code asynchronous CDC FIFOs (`clk_axi` <-> `clk_core`)
//   - Compute-core kernel execution & cycle-counter telemetry engine (`clk_core`)
//   - Protocol-compliant AXI4-Full HBM/DRAM master interface (`clk_axi`)
//   - IEEE-1149.1 JTAG TAP / DFT / MBIST / UPF cluster power controller (`VX_asic_dft_top`)
//   - On-chip boot/scratchpad 1RW SRAM macro with hardware MBIST FSM (`VX_sram_1rw`)

module VX_asic_soc_top #(
    parameter logic [31:0] CHIP_ID_VAL    = 32'h4149_4750, // "AIGP"
    parameter logic [31:0] ARCH_REV_VAL   = 32'h0001_0001, // v1.1
    parameter logic [31:0] JTAG_IDCODE    = 32'h1A16_B101,
    parameter int          NUM_CLUSTERS   = 4,
    parameter int          SCAN_CHAINS    = 8,
    parameter int          CDC_ADDRW      = 3,             // 2^3 = 8-entry Gray-code async FIFOs
    parameter int          AXIL_ADDRW     = 12,
    parameter int          AXIL_DATAW     = 32,
    parameter int          AXI_ADDRW      = 48,
    parameter int          AXI_DATAW      = 64,
    parameter int          AXI_IDW        = 4,
    parameter int          BOOT_SRAM_DEPTH = 256
) (
    // Clocks and active-low external reset
    input  wire                         clk_core,
    input  wire                         clk_axi,
    input  wire                         rst_n,

    // IEEE-1149.1 JTAG + Scan / Test pins
    input  wire                         tck,
    input  wire                         trst_n,
    input  wire                         tms,
    input  wire                         tdi,
    output wire                         tdo,
    output wire                         tdo_oe_n,
    input  wire                         por_n,
    input  wire                         test_mode_pin,
    input  wire                         scan_enable_pin,
    input  wire [SCAN_CHAINS-1:0]       scan_in,
    output wire [SCAN_CHAINS-1:0]       scan_out,

    // Expose UPF cluster power-domain control pins
    output wire [NUM_CLUSTERS-1:0]      pwr_clust_en,
    output wire [NUM_CLUSTERS-1:0]      pwr_clust_iso_en,
    output wire [NUM_CLUSTERS-1:0]      pwr_clust_ret_en,

    // Exposed DFT status pins for top-level clock gates / integration
    output wire                         dft_scan_enable,
    output wire                         dft_test_mode,
    output wire                         dft_cg_override,

    // Host interrupt output (clk_axi domain)
    output wire                         irq,

    // AXI4-Lite Slave CSR Interface (clk_axi domain)
    input  wire                         s_axil_awvalid,
    output wire                         s_axil_awready,
    input  wire [AXIL_ADDRW-1:0]        s_axil_awaddr,
    input  wire [2:0]                   s_axil_awprot,
    input  wire                         s_axil_wvalid,
    output wire                         s_axil_wready,
    input  wire [AXIL_DATAW-1:0]        s_axil_wdata,
    input  wire [(AXIL_DATAW/8)-1:0]    s_axil_wstrb,
    output wire                         s_axil_bvalid,
    input  wire                         s_axil_bready,
    output wire [1:0]                   s_axil_bresp,
    input  wire                         s_axil_arvalid,
    output wire                         s_axil_arready,
    input  wire [AXIL_ADDRW-1:0]        s_axil_araddr,
    input  wire [2:0]                   s_axil_arprot,
    output wire                         s_axil_rvalid,
    input  wire                         s_axil_rready,
    output wire [AXIL_DATAW-1:0]        s_axil_rdata,
    output wire [1:0]                   s_axil_rresp,

    // AXI4-Full HBM/DRAM Master Interface (clk_axi domain)
    output wire                         m_axi_awvalid,
    input  wire                         m_axi_awready,
    output wire [AXI_IDW-1:0]           m_axi_awid,
    output wire [AXI_ADDRW-1:0]         m_axi_awaddr,
    output wire [7:0]                   m_axi_awlen,
    output wire [2:0]                   m_axi_awsize,
    output wire [1:0]                   m_axi_awburst,
    output wire                         m_axi_awlock,
    output wire [3:0]                   m_axi_awcache,
    output wire [2:0]                   m_axi_awprot,
    output wire [3:0]                   m_axi_awqos,
    output wire                         m_axi_wvalid,
    input  wire                         m_axi_wready,
    output wire [AXI_DATAW-1:0]         m_axi_wdata,
    output wire [(AXI_DATAW/8)-1:0]     m_axi_wstrb,
    output wire                         m_axi_wlast,
    input  wire                         m_axi_bvalid,
    output wire                         m_axi_bready,
    input  wire [AXI_IDW-1:0]           m_axi_bid,
    input  wire [1:0]                   m_axi_bresp,
    output wire                         m_axi_arvalid,
    input  wire                         m_axi_arready,
    output wire [AXI_IDW-1:0]           m_axi_arid,
    output wire [AXI_ADDRW-1:0]         m_axi_araddr,
    output wire [7:0]                   m_axi_arlen,
    output wire [2:0]                   m_axi_arsize,
    output wire [1:0]                   m_axi_arburst,
    output wire                         m_axi_arlock,
    output wire [3:0]                   m_axi_arcache,
    output wire [2:0]                   m_axi_arprot,
    output wire [3:0]                   m_axi_arqos,
    input  wire                         m_axi_rvalid,
    output wire                         m_axi_rready,
    input  wire [AXI_IDW-1:0]           m_axi_rid,
    input  wire [AXI_DATAW-1:0]         m_axi_rdata,
    input  wire [1:0]                   m_axi_rresp,
    input  wire                         m_axi_rlast
);

    localparam int CDC_DEPTH      = (1 << CDC_ADDRW);
    localparam int CMD_PAYLOAD_W  = 96; // {cmd_ctrl[31:0], launch_addr_hi[31:0], launch_addr_lo[31:0]}
    localparam int RSP_PAYLOAD_W  = 68; // {op[1:0], fault[0], tag[0], addr_or_status[63:0]}
    localparam int SRAM_ADDRW     = (BOOT_SRAM_DEPTH > 1) ? $clog2(BOOT_SRAM_DEPTH) : 1;
    localparam int AXI_STRBW      = AXI_DATAW / 8;
    localparam [SRAM_ADDRW-1:0] MBIST_LAST_ADDR = SRAM_ADDRW'(BOOT_SRAM_DEPTH - 1);

    generate
        if ((CDC_ADDRW < 2) ||
            (AXIL_ADDRW != 12) ||
            (AXIL_DATAW != 32) ||
            (AXI_DATAW != 64) ||
            (NUM_CLUSTERS != 4) ||
            (BOOT_SRAM_DEPTH != 256)) begin : g_bad_params
`ifndef SYNTHESIS
            initial begin
                $error("VX_asic_soc_top: unsupported params CDC_ADDRW=%0d AXIL_ADDRW=%0d AXIL_DATAW=%0d AXI_DATAW=%0d NUM_CLUSTERS=%0d BOOT_SRAM_DEPTH=%0d",
                       CDC_ADDRW, AXIL_ADDRW, AXIL_DATAW, AXI_DATAW, NUM_CLUSTERS, BOOT_SRAM_DEPTH);
            end
`endif
        end
    endgenerate

    // ------------------------------------------------------------------------
    // 1. Embedded IEEE-1149.1 JTAG / DFT / MBIST / UPF Power Controller
    // ------------------------------------------------------------------------
    wire                     dft_mbist_run;
    wire                     dft_mbist_ret_mode;
    wire [NUM_CLUSTERS-1:0]  dft_pwr_clust_en;
    wire [NUM_CLUSTERS-1:0]  dft_pwr_clust_iso_en;
    wire [NUM_CLUSTERS-1:0]  dft_pwr_clust_ret_en;
    (* keep = "true" *) reg mbist_done_q;
    (* keep = "true" *) reg mbist_fail_q;

    VX_asic_dft_top #(
        .IDCODE_VAL   (JTAG_IDCODE),
        .NUM_CLUSTERS (NUM_CLUSTERS),
        .SCAN_CHAINS  (SCAN_CHAINS)
    ) u_dft (
        .tck                  (tck),
        .trst_n               (trst_n),
        .tms                  (tms),
        .tdi                  (tdi),
        .tdo                  (tdo),
        .tdo_oe_n             (tdo_oe_n),
        .por_n                (por_n),
        .test_mode_pin        (test_mode_pin),
        .scan_enable_pin      (scan_enable_pin),
        .scan_in              (scan_in),
        .scan_out             (scan_out),
        .dft_scan_enable      (dft_scan_enable),
        .dft_test_mode        (dft_test_mode),
        .dft_cg_override      (dft_cg_override),
        .mbist_run            (dft_mbist_run),
        .mbist_retention_mode (dft_mbist_ret_mode),
        .mbist_done           (mbist_done_q),
        .mbist_fail           (mbist_fail_q),
        .pwr_clust_en         (dft_pwr_clust_en),
        .pwr_clust_iso_en     (dft_pwr_clust_iso_en),
        .pwr_clust_ret_en     (dft_pwr_clust_ret_en)
    );

    // ------------------------------------------------------------------------
    // 2. Independent 2-FF Async-Assert, Sync-Deassert Reset Synchronizers
    // ------------------------------------------------------------------------
    (* keep = "true" *) reg rst_axi_sync0_q;
    (* keep = "true" *) reg rst_axi_sync1_q;
    (* keep = "true" *) reg rst_core_sync0_q;
    (* keep = "true" *) reg rst_core_sync1_q;

    always @(posedge clk_axi or negedge rst_n) begin
        if (!rst_n) begin
            rst_axi_sync0_q <= 1'b0;
            rst_axi_sync1_q <= 1'b0;
        end else begin
            rst_axi_sync0_q <= 1'b1;
            rst_axi_sync1_q <= rst_axi_sync0_q;
        end
    end

    always @(posedge clk_core or negedge rst_n) begin
        if (!rst_n) begin
            rst_core_sync0_q <= 1'b0;
            rst_core_sync1_q <= 1'b0;
        end else begin
            rst_core_sync0_q <= 1'b1;
            rst_core_sync1_q <= rst_core_sync0_q;
        end
    end

    wire rst_axi_n  = rst_axi_sync1_q;
    wire rst_core_n = rst_core_sync1_q;

    // ------------------------------------------------------------------------
    // 3. AXI4-Lite Slave CSR Bank & Cross-Domain Telemetry (clk_axi)
    // ------------------------------------------------------------------------
    localparam [9:0] CSR_CHIP_ID         = 10'h000;
    localparam [9:0] CSR_ARCH_REV        = 10'h004;
    localparam [9:0] CSR_PWR_CTRL        = 10'h008;
    localparam [9:0] CSR_SOFT_RESET      = 10'h00C;
    localparam [9:0] CSR_LAUNCH_ADDR_LO  = 10'h010;
    localparam [9:0] CSR_LAUNCH_ADDR_HI  = 10'h014;
    localparam [9:0] CSR_LAUNCH_CTRL     = 10'h018;
    localparam [9:0] CSR_LAUNCH_DOORBELL = 10'h01C;
    localparam [9:0] CSR_STATUS          = 10'h020;
    localparam [9:0] CSR_THERMAL_CTRL    = 10'h024;
    localparam [9:0] CSR_IRQ_ENABLE      = 10'h028;
    localparam [9:0] CSR_IRQ_STATUS      = 10'h02C;
    localparam [9:0] CSR_CYCLE_CNT_LO    = 10'h030;
    localparam [9:0] CSR_CYCLE_CNT_HI    = 10'h034;
    localparam [9:0] CSR_HBM_DATA_LO     = 10'h038;
    localparam [9:0] CSR_HBM_DATA_HI     = 10'h03C;

    // SW control registers
    reg [NUM_CLUSTERS-1:0] sw_clust_en_q;
    reg [NUM_CLUSTERS-1:0] sw_clust_iso_en_q;
    reg [NUM_CLUSTERS-1:0] sw_clust_ret_en_q;
    reg                    sw_pwr_override_q;
    (* keep = "true" *) reg soft_reset_q;
    reg [31:0]             launch_addr_lo_q;
    reg [31:0]             launch_addr_hi_q;
    reg [31:0]             launch_ctrl_q;
    (* keep = "true" *) reg thermal_throttle_en_q;
    reg [3:0]              thermal_duty_q;
    reg [2:0]              irq_enable_q;
    reg [2:0]              irq_status_q;
    reg                    fault_sticky_q;
    reg [1:0]              last_axi_resp_q;
    reg [7:0]              completed_cnt_q;
    reg [63:0]             hbm_last_data_q;
    reg                    cmd_doorbell_pulse_q;

    // 2-FF CDC synchronizers from tck -> clk_axi for DFT test & cluster power controls
    (* keep = "true" *) reg                    dft_test_mode_sync1_q;
    (* keep = "true" *) reg                    dft_test_mode_sync2_q;
    (* keep = "true" *) reg [NUM_CLUSTERS-1:0] dft_pwr_en_sync1_q;
    (* keep = "true" *) reg [NUM_CLUSTERS-1:0] dft_pwr_en_sync2_q;
    (* keep = "true" *) reg [NUM_CLUSTERS-1:0] dft_pwr_iso_sync1_q;
    (* keep = "true" *) reg [NUM_CLUSTERS-1:0] dft_pwr_iso_sync2_q;
    (* keep = "true" *) reg [NUM_CLUSTERS-1:0] dft_pwr_ret_sync1_q;
    (* keep = "true" *) reg [NUM_CLUSTERS-1:0] dft_pwr_ret_sync2_q;

    // Functional cluster power selection synchronized in clk_axi; direct DFT test-mode bypasses functional clocks
    wire [NUM_CLUSTERS-1:0] func_pwr_clust_en;
    wire [NUM_CLUSTERS-1:0] func_pwr_clust_iso_en;
    wire [NUM_CLUSTERS-1:0] func_pwr_clust_ret_en;

    assign func_pwr_clust_en     = dft_test_mode_sync2_q ? dft_pwr_en_sync2_q :
                                   (sw_pwr_override_q ? sw_clust_en_q : (sw_clust_en_q & dft_pwr_en_sync2_q));
    assign func_pwr_clust_iso_en = dft_test_mode_sync2_q ? dft_pwr_iso_sync2_q :
                                   (sw_pwr_override_q ? sw_clust_iso_en_q : (sw_clust_iso_en_q | dft_pwr_iso_sync2_q));
    assign func_pwr_clust_ret_en = dft_test_mode_sync2_q ? dft_pwr_ret_sync2_q :
                                   (sw_pwr_override_q ? sw_clust_ret_en_q : (sw_clust_ret_en_q | dft_pwr_ret_sync2_q));

    assign pwr_clust_en     = dft_test_mode ? dft_pwr_clust_en     : func_pwr_clust_en;
    assign pwr_clust_iso_en = dft_test_mode ? dft_pwr_clust_iso_en : func_pwr_clust_iso_en;
    assign pwr_clust_ret_en = dft_test_mode ? dft_pwr_clust_ret_en : func_pwr_clust_ret_en;

    // Synchronizers into clk_axi
    (* keep = "true" *) reg core_busy_q;
    (* keep = "true" *) reg core_busy_sync1_q;
    (* keep = "true" *) reg core_busy_sync2_q;
    (* keep = "true" *) reg mbist_run_sync1_q;
    (* keep = "true" *) reg mbist_run_sync2_q;
    (* keep = "true" *) reg mbist_ret_sync1_q;
    (* keep = "true" *) reg mbist_ret_sync2_q;
    reg mbist_done_prev_q;

    // Toggle-handshake snapshot of clk_core 64-bit cycle counter into clk_axi
    (* keep = "true" *) reg        cycle_req_axi_q;
    (* keep = "true" *) reg        cycle_ack_axi_sync1_q;
    (* keep = "true" *) reg        cycle_ack_axi_sync2_q;
    (* keep = "true" *) reg [63:0] cycle_cnt_axi_q;
    (* keep = "true" *) reg        cycle_req_core_sync1_q;
    (* keep = "true" *) reg        cycle_req_core_sync2_q;
    (* keep = "true" *) reg        cycle_ack_core_q;
    (* keep = "true" *) reg [63:0] cycle_snap_core_q;

    // Explicit MCP enable gate: cycle_snap_core_q is stable for >=2 clk_axi cycles once ack catches up
    wire cycle_mcp_en = (cycle_ack_axi_sync2_q == cycle_req_axi_q);

    // ------------------------------------------------------------------------
    // 4. Gray-Code Async CDC FIFO 1: Command Queue (clk_axi -> clk_core)
    // ------------------------------------------------------------------------
    (* keep = "true" *) reg [CMD_PAYLOAD_W-1:0] cmd_fifo_mem [0:CDC_DEPTH-1];
    reg [CDC_ADDRW:0]                   cmd_wptr_bin_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] cmd_wptr_gray_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] cmd_rptr_gray_sync1_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] cmd_rptr_gray_sync2_q;

    reg [CDC_ADDRW:0]                   cmd_rptr_bin_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] cmd_rptr_gray_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] cmd_wptr_gray_sync1_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] cmd_wptr_gray_sync2_q;

    wire [CDC_ADDRW:0] cmd_wptr_bin_next  = cmd_wptr_bin_q + {{CDC_ADDRW{1'b0}}, 1'b1};
    wire [CDC_ADDRW:0] cmd_wptr_gray_next = cmd_wptr_bin_next ^ (cmd_wptr_bin_next >> 1);
    wire               cmd_fifo_full      = (cmd_wptr_gray_q == {~cmd_rptr_gray_sync2_q[CDC_ADDRW:CDC_ADDRW-1],
                                                                 cmd_rptr_gray_sync2_q[CDC_ADDRW-2:0]});
    wire               cmd_fifo_empty_axi = (cmd_wptr_gray_q == cmd_rptr_gray_sync2_q);

    wire [CDC_ADDRW:0] cmd_rptr_bin_next  = cmd_rptr_bin_q + {{CDC_ADDRW{1'b0}}, 1'b1};
    wire [CDC_ADDRW:0] cmd_rptr_gray_next = cmd_rptr_bin_next ^ (cmd_rptr_bin_next >> 1);
    wire               cmd_fifo_empty     = (cmd_rptr_gray_q == cmd_wptr_gray_sync2_q);

    // ------------------------------------------------------------------------
    // 5. Gray-Code Async CDC FIFO 2: Telemetry/HBM Queue (clk_core -> clk_axi)
    // ------------------------------------------------------------------------
    (* keep = "true" *) reg [RSP_PAYLOAD_W-1:0] rsp_fifo_mem [0:CDC_DEPTH-1];
    reg [CDC_ADDRW:0]                   rsp_wptr_bin_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] rsp_wptr_gray_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] rsp_rptr_gray_sync1_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] rsp_rptr_gray_sync2_q;

    reg [CDC_ADDRW:0]                   rsp_rptr_bin_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] rsp_rptr_gray_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] rsp_wptr_gray_sync1_q;
    (* keep = "true" *) reg [CDC_ADDRW:0] rsp_wptr_gray_sync2_q;

    wire [CDC_ADDRW:0] rsp_wptr_bin_next  = rsp_wptr_bin_q + {{CDC_ADDRW{1'b0}}, 1'b1};
    wire [CDC_ADDRW:0] rsp_wptr_gray_next = rsp_wptr_bin_next ^ (rsp_wptr_bin_next >> 1);
    wire               rsp_fifo_full      = (rsp_wptr_gray_q == {~rsp_rptr_gray_sync2_q[CDC_ADDRW:CDC_ADDRW-1],
                                                                 rsp_rptr_gray_sync2_q[CDC_ADDRW-2:0]});
    wire [CDC_ADDRW:0] rsp_rptr_bin_next  = rsp_rptr_bin_q + {{CDC_ADDRW{1'b0}}, 1'b1};
    wire [CDC_ADDRW:0] rsp_rptr_gray_next = rsp_rptr_bin_next ^ (rsp_rptr_bin_next >> 1);
    wire               rsp_fifo_empty     = (rsp_rptr_gray_q == rsp_wptr_gray_sync2_q);

    // ------------------------------------------------------------------------
    // 6. Boot/Scratchpad 1RW SRAM Macro + Hardware MBIST Controller (clk_axi)
    // ------------------------------------------------------------------------
    localparam [2:0] MBIST_IDLE      = 3'd0;
    localparam [2:0] MBIST_WR_PAT0   = 3'd1;
    localparam [2:0] MBIST_RD_PAT0   = 3'd2;
    localparam [2:0] MBIST_CHK_PAT0  = 3'd3;
    localparam [2:0] MBIST_WR_PAT1   = 3'd4;
    localparam [2:0] MBIST_RD_PAT1   = 3'd5;
    localparam [2:0] MBIST_CHK_PAT1  = 3'd6;
    localparam [2:0] MBIST_COMPLETE  = 3'd7;

    reg [2:0]               mbist_state_q;
    reg [SRAM_ADDRW-1:0]    mbist_addr_q;
    reg                     axil_sram_ce;
    reg                     axil_sram_we;
    reg [3:0]               axil_sram_wmask;
    reg [SRAM_ADDRW-1:0]    axil_sram_addr;
    reg [31:0]              axil_sram_wdata;
    wire [31:0]             boot_sram_rdata;

    wire mbist_active = mbist_run_sync2_q &&
                        (mbist_state_q != MBIST_IDLE) &&
                        (mbist_state_q != MBIST_COMPLETE);

    wire        mbist_ce    = mbist_active;
    wire        mbist_we    = (mbist_state_q == MBIST_WR_PAT0) || (mbist_state_q == MBIST_WR_PAT1);
    wire [31:0] mbist_wdata = (mbist_state_q == MBIST_WR_PAT1) ? 32'h5555_AAAA : 32'hAAAA_5555;

    VX_sram_1rw #(
        .DEPTH    (BOOT_SRAM_DEPTH),
        .DATAW    (32),
        .WRENW    (4),
        .BYTE_W   (8),
        .HAS_BIST (1)
    ) u_boot_sram (
        .clk        (clk_axi),
        .rst_n      (rst_axi_n),
        .ce         (axil_sram_ce),
        .we         (axil_sram_we),
        .wmask      (axil_sram_wmask),
        .addr       (axil_sram_addr),
        .wdata      (axil_sram_wdata),
        .rdata      (boot_sram_rdata),
        .bist_en    (mbist_active),
        .bist_ce    (mbist_ce),
        .bist_we    (mbist_we),
        .bist_wmask (4'hF),
        .bist_addr  (mbist_addr_q),
        .bist_wdata (mbist_wdata),
        .sleep      (mbist_ret_sync2_q),
        .sd         (1'b0),
        .ret        (mbist_ret_sync2_q)
    );

    always @(posedge clk_axi or negedge rst_axi_n) begin
        if (!rst_axi_n) begin
            mbist_run_sync1_q <= 1'b0;
            mbist_run_sync2_q <= 1'b0;
            mbist_ret_sync1_q <= 1'b0;
            mbist_ret_sync2_q <= 1'b0;
            mbist_state_q     <= MBIST_IDLE;
            mbist_addr_q      <= {SRAM_ADDRW{1'b0}};
            mbist_done_q      <= 1'b0;
            mbist_fail_q      <= 1'b0;
        end else begin
            mbist_run_sync1_q <= dft_mbist_run;
            mbist_run_sync2_q <= mbist_run_sync1_q;
            mbist_ret_sync1_q <= dft_mbist_ret_mode;
            mbist_ret_sync2_q <= mbist_ret_sync1_q;

            if (!mbist_run_sync2_q) begin
                mbist_state_q <= MBIST_IDLE;
                mbist_addr_q  <= {SRAM_ADDRW{1'b0}};
                mbist_done_q  <= 1'b0;
                mbist_fail_q  <= 1'b0;
            end else begin
                case (mbist_state_q)
                    MBIST_IDLE: begin
                        mbist_addr_q  <= {SRAM_ADDRW{1'b0}};
                        mbist_done_q  <= 1'b0;
                        mbist_fail_q  <= 1'b0;
                        mbist_state_q <= MBIST_WR_PAT0;
                    end
                    MBIST_WR_PAT0: begin
                        if (mbist_addr_q == MBIST_LAST_ADDR) begin
                            mbist_addr_q  <= {SRAM_ADDRW{1'b0}};
                            mbist_state_q <= MBIST_RD_PAT0;
                        end else begin
                            mbist_addr_q <= mbist_addr_q + {{(SRAM_ADDRW-1){1'b0}}, 1'b1};
                        end
                    end
                    MBIST_RD_PAT0: begin
                        mbist_state_q <= MBIST_CHK_PAT0;
                    end
                    MBIST_CHK_PAT0: begin
                        if (boot_sram_rdata != 32'hAAAA_5555) begin
                            mbist_fail_q <= 1'b1;
                        end
                        if (mbist_addr_q == MBIST_LAST_ADDR) begin
                            mbist_addr_q  <= {SRAM_ADDRW{1'b0}};
                            mbist_state_q <= MBIST_WR_PAT1;
                        end else begin
                            mbist_addr_q  <= mbist_addr_q + {{(SRAM_ADDRW-1){1'b0}}, 1'b1};
                            mbist_state_q <= MBIST_RD_PAT0;
                        end
                    end
                    MBIST_WR_PAT1: begin
                        if (mbist_addr_q == MBIST_LAST_ADDR) begin
                            mbist_addr_q  <= {SRAM_ADDRW{1'b0}};
                            mbist_state_q <= MBIST_RD_PAT1;
                        end else begin
                            mbist_addr_q <= mbist_addr_q + {{(SRAM_ADDRW-1){1'b0}}, 1'b1};
                        end
                    end
                    MBIST_RD_PAT1: begin
                        mbist_state_q <= MBIST_CHK_PAT1;
                    end
                    MBIST_CHK_PAT1: begin
                        if (boot_sram_rdata != 32'h5555_AAAA) begin
                            mbist_fail_q <= 1'b1;
                        end
                        if (mbist_addr_q == MBIST_LAST_ADDR) begin
                            mbist_done_q  <= 1'b1;
                            mbist_state_q <= MBIST_COMPLETE;
                        end else begin
                            mbist_addr_q  <= mbist_addr_q + {{(SRAM_ADDRW-1){1'b0}}, 1'b1};
                            mbist_state_q <= MBIST_RD_PAT1;
                        end
                    end
                    MBIST_COMPLETE: begin
                        mbist_done_q <= 1'b1;
                    end
                    default: begin
                        mbist_state_q <= MBIST_IDLE;
                    end
                endcase
            end
        end
    end

    // ------------------------------------------------------------------------
    // 7. AXI4-Full HBM/DRAM Master FSM + Completion Telemetry (clk_axi)
    // ------------------------------------------------------------------------
    localparam [2:0] AXI_M_IDLE   = 3'd0;
    localparam [2:0] AXI_M_RD_REQ = 3'd1;
    localparam [2:0] AXI_M_RD_RSP = 3'd2;
    localparam [2:0] AXI_M_WR_REQ = 3'd3;
    localparam [2:0] AXI_M_WR_RSP = 3'd4;

    reg [2:0]           axi_m_state_q;
    reg                 axi_aw_done_q;
    reg                 axi_w_done_q;
    (* keep = "true" *) reg [AXI_ADDRW-1:0] axi_req_addr_q;
    (* keep = "true" *) reg [AXI_DATAW-1:0] axi_req_wdata_q;
    reg                 kernel_done_pulse_q;
    reg                 axi_fault_pulse_q;
    reg                 rsp_pop_en;

    always @(posedge clk_axi or negedge rst_axi_n) begin
        if (!rst_axi_n) begin
            rsp_rptr_bin_q        <= {(CDC_ADDRW+1){1'b0}};
            rsp_rptr_gray_q       <= {(CDC_ADDRW+1){1'b0}};
            rsp_wptr_gray_sync1_q <= {(CDC_ADDRW+1){1'b0}};
            rsp_wptr_gray_sync2_q <= {(CDC_ADDRW+1){1'b0}};

            axi_m_state_q       <= AXI_M_IDLE;
            axi_aw_done_q       <= 1'b0;
            axi_w_done_q        <= 1'b0;
            axi_req_addr_q      <= {AXI_ADDRW{1'b0}};
            axi_req_wdata_q     <= {AXI_DATAW{1'b0}};
            last_axi_resp_q     <= 2'b00;
            completed_cnt_q     <= 8'h00;
            hbm_last_data_q     <= 64'h0;
            kernel_done_pulse_q <= 1'b0;
            axi_fault_pulse_q   <= 1'b0;
        end else begin
            // Synchronize clk_core write Gray pointer
            rsp_wptr_gray_sync1_q <= rsp_wptr_gray_q;
            rsp_wptr_gray_sync2_q <= rsp_wptr_gray_sync1_q;

            kernel_done_pulse_q <= 1'b0;
            axi_fault_pulse_q   <= 1'b0;

            if (rsp_pop_en) begin
                rsp_rptr_bin_q  <= rsp_rptr_bin_next;
                rsp_rptr_gray_q <= rsp_rptr_gray_next;
            end

            case (axi_m_state_q)
                AXI_M_IDLE: begin
                    axi_aw_done_q <= 1'b0;
                    axi_w_done_q  <= 1'b0;
                    if (!rsp_fifo_empty) begin
                        // Pop telemetry/DMA request from clk_core
                        if (rsp_fifo_mem[rsp_rptr_bin_q[CDC_ADDRW-1:0]][67:66] == 2'b01) begin
                            // Issue single-beat AXI4 Read from HBM
                            axi_req_addr_q <= rsp_fifo_mem[rsp_rptr_bin_q[CDC_ADDRW-1:0]][AXI_ADDRW-1:0];
                            axi_m_state_q  <= AXI_M_RD_REQ;
                        end else if (rsp_fifo_mem[rsp_rptr_bin_q[CDC_ADDRW-1:0]][67:66] == 2'b10) begin
                            // Issue single-beat AXI4 Write to HBM
                            axi_req_addr_q  <= rsp_fifo_mem[rsp_rptr_bin_q[CDC_ADDRW-1:0]][AXI_ADDRW-1:0];
                            axi_req_wdata_q <= rsp_fifo_mem[rsp_rptr_bin_q[CDC_ADDRW-1:0]][63:0];
                            axi_m_state_q   <= AXI_M_WR_REQ;
                        end else begin
                            // Direct kernel completion event
                            completed_cnt_q     <= completed_cnt_q + 8'd1;
                            kernel_done_pulse_q <= 1'b1;
                            if (rsp_fifo_mem[rsp_rptr_bin_q[CDC_ADDRW-1:0]][65]) begin
                                axi_fault_pulse_q <= 1'b1;
                            end
                        end
                    end
                end

                AXI_M_RD_REQ: begin
                    if (m_axi_arready) begin
                        axi_m_state_q <= AXI_M_RD_RSP;
                    end
                end

                AXI_M_RD_RSP: begin
                    if (m_axi_rvalid && m_axi_rlast) begin
                        hbm_last_data_q     <= m_axi_rdata;
                        last_axi_resp_q     <= m_axi_rresp;
                        completed_cnt_q     <= completed_cnt_q + 8'd1;
                        kernel_done_pulse_q <= 1'b1;
                        if (m_axi_rresp != 2'b00) begin
                            axi_fault_pulse_q <= 1'b1;
                        end
                        axi_m_state_q <= AXI_M_IDLE;
                    end
                end

                AXI_M_WR_REQ: begin
                    if (m_axi_awready) begin
                        axi_aw_done_q <= 1'b1;
                    end
                    if (m_axi_wready) begin
                        axi_w_done_q <= 1'b1;
                    end
                    if ((axi_aw_done_q || m_axi_awready) && (axi_w_done_q || m_axi_wready)) begin
                        axi_m_state_q <= AXI_M_WR_RSP;
                    end
                end

                AXI_M_WR_RSP: begin
                    if (m_axi_bvalid) begin
                        last_axi_resp_q     <= m_axi_bresp;
                        completed_cnt_q     <= completed_cnt_q + 8'd1;
                        kernel_done_pulse_q <= 1'b1;
                        if (m_axi_bresp != 2'b00) begin
                            axi_fault_pulse_q <= 1'b1;
                        end
                        axi_m_state_q <= AXI_M_IDLE;
                    end
                end

                default: begin
                    axi_m_state_q <= AXI_M_IDLE;
                end
            endcase
        end
    end

    always @(*) begin
        rsp_pop_en = 1'b0;
        if ((axi_m_state_q == AXI_M_IDLE) && !rsp_fifo_empty) begin
            rsp_pop_en = 1'b1;
        end
    end

    assign m_axi_awvalid = (axi_m_state_q == AXI_M_WR_REQ) && !axi_aw_done_q;
    assign m_axi_awid    = {AXI_IDW{1'b0}};
    assign m_axi_awaddr  = axi_req_addr_q;
    assign m_axi_awlen   = 8'h00; // 1-beat burst
    assign m_axi_awsize  = 3'b011; // 8 bytes (64-bit)
    assign m_axi_awburst = 2'b01; // INCR
    assign m_axi_awlock  = 1'b0;
    assign m_axi_awcache = 4'b0011; // Normal Non-cacheable Bufferable
    assign m_axi_awprot  = 3'b000;
    assign m_axi_awqos   = 4'h0;

    assign m_axi_wvalid  = (axi_m_state_q == AXI_M_WR_REQ) && !axi_w_done_q;
    assign m_axi_wdata   = axi_req_wdata_q;
    assign m_axi_wstrb   = {AXI_STRBW{1'b1}};
    assign m_axi_wlast   = 1'b1;
    assign m_axi_bready  = (axi_m_state_q == AXI_M_WR_RSP);

    assign m_axi_arvalid = (axi_m_state_q == AXI_M_RD_REQ);
    assign m_axi_arid    = {AXI_IDW{1'b0}};
    assign m_axi_araddr  = axi_req_addr_q;
    assign m_axi_arlen   = 8'h00;
    assign m_axi_arsize  = 3'b011;
    assign m_axi_arburst = 2'b01;
    assign m_axi_arlock  = 1'b0;
    assign m_axi_arcache = 4'b0011;
    assign m_axi_arprot  = 3'b000;
    assign m_axi_arqos   = 4'h0;
    assign m_axi_rready  = (axi_m_state_q == AXI_M_RD_RSP);

    wire axi_master_busy = (axi_m_state_q != AXI_M_IDLE);

    // ------------------------------------------------------------------------
    // 8. AXI4-Lite Slave State Machine & CSR Bank (clk_axi)
    // ------------------------------------------------------------------------
    reg                      aw_hold_q;
    reg [AXIL_ADDRW-1:0]     aw_addr_q;
    reg                      w_hold_q;
    reg [AXIL_DATAW-1:0]     w_data_q;
    reg [(AXIL_DATAW/8)-1:0] w_strb_q;
    reg                      bvalid_q;
    reg [1:0]                bresp_q;

    reg                      ar_sram_wait_q;
    reg                      rvalid_q;
    reg [AXIL_DATAW-1:0]     rdata_q;
    reg [1:0]                rresp_q;

    wire aw_handshake = s_axil_awvalid && s_axil_awready;
    wire w_handshake  = s_axil_wvalid  && s_axil_wready;
    wire wr_ready     = !bvalid_q;

    // Prioritize buffered AW+W (purely registered) ahead of incoming AR to avoid valid->ready feedthrough
    wire wr_pending_reg = aw_hold_q && w_hold_q && wr_ready;
    wire wr_commit      = (aw_hold_q || aw_handshake) && (w_hold_q || w_handshake) && wr_ready;
    wire [AXIL_ADDRW-1:0]     wr_addr = aw_hold_q ? aw_addr_q : s_axil_awaddr;
    wire [AXIL_DATAW-1:0]     wr_data = w_hold_q  ? w_data_q  : s_axil_wdata;
    wire [(AXIL_DATAW/8)-1:0] wr_strb = w_hold_q  ? w_strb_q  : s_axil_wstrb;

    wire wr_is_sram = (wr_addr[11:10] == 2'b01);
    wire rd_is_sram = (s_axil_araddr[11:10] == 2'b01);
    wire ar_accept  = s_axil_arvalid && s_axil_arready;

    assign s_axil_awready = !aw_hold_q && wr_ready;
    assign s_axil_wready  = !w_hold_q  && wr_ready;
    assign s_axil_bvalid  = bvalid_q;
    assign s_axil_bresp   = bresp_q;

    // Strictly registered backpressure on ARREADY (zero combinational AWVALID/WVALID -> ARREADY path).
    // When AR is accepted while an unbuffered AW+W arrives in the same cycle targeting SRAM, AR takes SRAM
    // on that cycle and AW+W buffer into aw_hold_q/w_hold_q for the immediately following cycle.
    assign s_axil_arready = !rvalid_q && !ar_sram_wait_q && !wr_pending_reg;
    assign s_axil_rvalid  = rvalid_q;
    assign s_axil_rdata   = rdata_q;
    assign s_axil_rresp   = rresp_q;

    assign irq = |(irq_status_q & irq_enable_q);

    // Boot SRAM control mux: AR accepted on SRAM aperture wins over unbuffered AW+W in the same cycle;
    // buffered AW+W (wr_pending_reg) holds off s_axil_arready above. Blocked cleanly when mbist_active=1.
    wire ar_sram_req     = ar_accept && rd_is_sram && !mbist_active;
    wire wr_sram_commit  = wr_commit && wr_is_sram && !ar_sram_req && !mbist_active;
    wire wr_defer_sram   = wr_commit && wr_is_sram && ar_sram_req;

    always @(*) begin
        axil_sram_ce    = 1'b0;
        axil_sram_we    = 1'b0;
        axil_sram_wmask = 4'h0;
        axil_sram_addr  = {SRAM_ADDRW{1'b0}};
        axil_sram_wdata = 32'h0;

        if (ar_sram_req) begin
            axil_sram_ce    = 1'b1;
            axil_sram_we    = 1'b0;
            axil_sram_wmask = 4'h0;
            axil_sram_addr  = s_axil_araddr[9:2];
            axil_sram_wdata = 32'h0;
        end else if (wr_sram_commit) begin
            axil_sram_ce    = 1'b1;
            axil_sram_we    = 1'b1;
            axil_sram_wmask = wr_strb;
            axil_sram_addr  = wr_addr[9:2];
            axil_sram_wdata = wr_data;
        end
    end

    // CSR read decode mux
    reg [31:0] csr_rdata_comb;
    always @(*) begin
        case (s_axil_araddr[9:0])
            CSR_CHIP_ID:         csr_rdata_comb = CHIP_ID_VAL;
            CSR_ARCH_REV:        csr_rdata_comb = ARCH_REV_VAL;
            CSR_PWR_CTRL:        csr_rdata_comb = {19'b0, sw_pwr_override_q,
                                                   func_pwr_clust_ret_en, func_pwr_clust_iso_en, func_pwr_clust_en};
            CSR_SOFT_RESET:      csr_rdata_comb = {31'b0, soft_reset_q};
            CSR_LAUNCH_ADDR_LO:  csr_rdata_comb = launch_addr_lo_q;
            CSR_LAUNCH_ADDR_HI:  csr_rdata_comb = launch_addr_hi_q;
            CSR_LAUNCH_CTRL:     csr_rdata_comb = launch_ctrl_q;
            CSR_LAUNCH_DOORBELL: csr_rdata_comb = {30'b0, cmd_fifo_empty_axi, cmd_fifo_full};
            CSR_STATUS:          csr_rdata_comb = {completed_cnt_q,
                                                   last_axi_resp_q,
                                                   func_pwr_clust_ret_en,
                                                   func_pwr_clust_iso_en,
                                                   func_pwr_clust_en,
                                                   thermal_throttle_en_q,
                                                   axi_master_busy,
                                                   mbist_fail_q,
                                                   mbist_done_q,
                                                   rsp_fifo_full,
                                                   rsp_fifo_empty,
                                                   cmd_fifo_empty_axi,
                                                   cmd_fifo_full,
                                                   fault_sticky_q,
                                                   core_busy_sync2_q};
            CSR_THERMAL_CTRL:    csr_rdata_comb = {24'b0, thermal_duty_q, 3'b0, thermal_throttle_en_q};
            CSR_IRQ_ENABLE:      csr_rdata_comb = {29'b0, irq_enable_q};
            CSR_IRQ_STATUS:      csr_rdata_comb = {29'b0, irq_status_q};
            CSR_CYCLE_CNT_LO:    csr_rdata_comb = cycle_cnt_axi_q[31:0];
            CSR_CYCLE_CNT_HI:    csr_rdata_comb = cycle_cnt_axi_q[63:32];
            CSR_HBM_DATA_LO:     csr_rdata_comb = hbm_last_data_q[31:0];
            CSR_HBM_DATA_HI:     csr_rdata_comb = hbm_last_data_q[63:32];
            default:             csr_rdata_comb = 32'h0000_0000;
        endcase
    end

    always @(posedge clk_axi or negedge rst_axi_n) begin
        if (!rst_axi_n) begin
            aw_hold_q             <= 1'b0;
            aw_addr_q             <= {AXIL_ADDRW{1'b0}};
            w_hold_q              <= 1'b0;
            w_data_q              <= {AXIL_DATAW{1'b0}};
            w_strb_q              <= {(AXIL_DATAW/8){1'b0}};
            bvalid_q              <= 1'b0;
            bresp_q               <= 2'b00;
            ar_sram_wait_q        <= 1'b0;
            rvalid_q              <= 1'b0;
            rdata_q               <= {AXIL_DATAW{1'b0}};
            rresp_q               <= 2'b00;

            sw_clust_en_q         <= {NUM_CLUSTERS{1'b1}};
            sw_clust_iso_en_q     <= {NUM_CLUSTERS{1'b0}};
            sw_clust_ret_en_q     <= {NUM_CLUSTERS{1'b0}};
            sw_pwr_override_q     <= 1'b0;
            soft_reset_q          <= 1'b0;
            launch_addr_lo_q      <= 32'h0;
            launch_addr_hi_q      <= 32'h0;
            launch_ctrl_q         <= 32'h0;
            thermal_throttle_en_q <= 1'b0;
            thermal_duty_q        <= 4'h8;
            irq_enable_q          <= 3'b000;
            irq_status_q          <= 3'b000;
            fault_sticky_q        <= 1'b0;
            cmd_doorbell_pulse_q  <= 1'b0;
            mbist_done_prev_q     <= 1'b0;

            dft_test_mode_sync1_q <= 1'b0;
            dft_test_mode_sync2_q <= 1'b0;
            dft_pwr_en_sync1_q    <= {NUM_CLUSTERS{1'b1}};
            dft_pwr_en_sync2_q    <= {NUM_CLUSTERS{1'b1}};
            dft_pwr_iso_sync1_q   <= {NUM_CLUSTERS{1'b0}};
            dft_pwr_iso_sync2_q   <= {NUM_CLUSTERS{1'b0}};
            dft_pwr_ret_sync1_q   <= {NUM_CLUSTERS{1'b0}};
            dft_pwr_ret_sync2_q   <= {NUM_CLUSTERS{1'b0}};

            core_busy_sync1_q     <= 1'b0;
            core_busy_sync2_q     <= 1'b0;

            cycle_req_axi_q       <= 1'b0;
            cycle_ack_axi_sync1_q <= 1'b0;
            cycle_ack_axi_sync2_q <= 1'b0;
            cycle_cnt_axi_q       <= 64'h0;

            cmd_wptr_bin_q        <= {(CDC_ADDRW+1){1'b0}};
            cmd_wptr_gray_q       <= {(CDC_ADDRW+1){1'b0}};
            cmd_rptr_gray_sync1_q <= {(CDC_ADDRW+1){1'b0}};
            cmd_rptr_gray_sync2_q <= {(CDC_ADDRW+1){1'b0}};
        end else begin
            // Cross-domain synchronizers (tck -> clk_axi and clk_core -> clk_axi)
            dft_test_mode_sync1_q <= dft_test_mode;
            dft_test_mode_sync2_q <= dft_test_mode_sync1_q;
            dft_pwr_en_sync1_q    <= dft_pwr_clust_en;
            dft_pwr_en_sync2_q    <= dft_pwr_en_sync1_q;
            dft_pwr_iso_sync1_q   <= dft_pwr_clust_iso_en;
            dft_pwr_iso_sync2_q   <= dft_pwr_iso_sync1_q;
            dft_pwr_ret_sync1_q   <= dft_pwr_clust_ret_en;
            dft_pwr_ret_sync2_q   <= dft_pwr_ret_sync1_q;

            core_busy_sync1_q     <= core_busy_q;
            core_busy_sync2_q     <= core_busy_sync1_q;
            cmd_rptr_gray_sync1_q <= cmd_rptr_gray_q;
            cmd_rptr_gray_sync2_q <= cmd_rptr_gray_sync1_q;

            cycle_ack_axi_sync1_q <= cycle_ack_core_q;
            cycle_ack_axi_sync2_q <= cycle_ack_axi_sync1_q;

            // Toggle-handshake cycle counter refresh whenever ack catches up to req (MCP enabled)
            if (cycle_mcp_en) begin
                cycle_cnt_axi_q <= cycle_snap_core_q;
                cycle_req_axi_q <= ~cycle_req_axi_q;
            end

            cmd_doorbell_pulse_q <= 1'b0;
            mbist_done_prev_q    <= mbist_done_q;

            // Interrupt & fault sticky updates from internal sources
            if (kernel_done_pulse_q) begin
                irq_status_q[0] <= 1'b1;
            end
            if (axi_fault_pulse_q) begin
                fault_sticky_q  <= 1'b1;
                irq_status_q[1] <= 1'b1;
            end
            if (mbist_done_q && !mbist_done_prev_q) begin
                irq_status_q[2] <= 1'b1;
            end

            // AXI4-Lite Write address/data buffering (also defers SRAM write if simultaneous AR SRAM read wins)
            if (aw_handshake && (!wr_commit || wr_defer_sram)) begin
                aw_hold_q <= 1'b1;
                aw_addr_q <= s_axil_awaddr;
            end else if (wr_commit && !wr_defer_sram) begin
                aw_hold_q <= 1'b0;
            end

            if (w_handshake && (!wr_commit || wr_defer_sram)) begin
                w_hold_q <= 1'b1;
                w_data_q <= s_axil_wdata;
                w_strb_q <= s_axil_wstrb;
            end else if (wr_commit && !wr_defer_sram) begin
                w_hold_q <= 1'b0;
            end

            if (bvalid_q && s_axil_bready) begin
                bvalid_q <= 1'b0;
            end else if (wr_commit && !wr_defer_sram) begin
                bvalid_q <= 1'b1;
                if (wr_is_sram) begin
                    // Reject Boot SRAM writes with SLVERR while MBIST owns the macro
                    bresp_q <= mbist_active ? 2'b10 : 2'b00;
                end else if (wr_addr[11:10] == 2'b00) begin
                    bresp_q <= 2'b00;
                end else begin
                    bresp_q <= 2'b10;
                end

                if (wr_addr[11:10] == 2'b00) begin
                    case (wr_addr[9:0])
                        CSR_PWR_CTRL: begin
                            if (wr_strb[0]) begin
                                sw_clust_en_q     <= wr_data[NUM_CLUSTERS-1:0];
                                sw_clust_iso_en_q <= wr_data[4 +: NUM_CLUSTERS];
                            end
                            if (wr_strb[1]) begin
                                sw_clust_ret_en_q <= wr_data[8 +: NUM_CLUSTERS];
                                sw_pwr_override_q <= wr_data[12];
                            end
                        end
                        CSR_SOFT_RESET: begin
                            if (wr_strb[0]) begin
                                soft_reset_q <= wr_data[0];
                                if (wr_data[1]) begin
                                    fault_sticky_q <= 1'b0;
                                end
                            end
                        end
                        CSR_LAUNCH_ADDR_LO: begin
                            if (wr_strb[0]) begin
                                launch_addr_lo_q[7:0]   <= wr_data[7:0];
                            end
                            if (wr_strb[1]) begin
                                launch_addr_lo_q[15:8]  <= wr_data[15:8];
                            end
                            if (wr_strb[2]) begin
                                launch_addr_lo_q[23:16] <= wr_data[23:16];
                            end
                            if (wr_strb[3]) begin
                                launch_addr_lo_q[31:24] <= wr_data[31:24];
                            end
                        end
                        CSR_LAUNCH_ADDR_HI: begin
                            if (wr_strb[0]) begin
                                launch_addr_hi_q[7:0]   <= wr_data[7:0];
                            end
                            if (wr_strb[1]) begin
                                launch_addr_hi_q[15:8]  <= wr_data[15:8];
                            end
                            if (wr_strb[2]) begin
                                launch_addr_hi_q[23:16] <= wr_data[23:16];
                            end
                            if (wr_strb[3]) begin
                                launch_addr_hi_q[31:24] <= wr_data[31:24];
                            end
                        end
                        CSR_LAUNCH_CTRL: begin
                            if (wr_strb[0]) begin
                                launch_ctrl_q[7:0]   <= wr_data[7:0];
                            end
                            if (wr_strb[1]) begin
                                launch_ctrl_q[15:8]  <= wr_data[15:8];
                            end
                            if (wr_strb[2]) begin
                                launch_ctrl_q[23:16] <= wr_data[23:16];
                            end
                            if (wr_strb[3]) begin
                                launch_ctrl_q[31:24] <= wr_data[31:24];
                            end
                        end
                        CSR_LAUNCH_DOORBELL: begin
                            cmd_doorbell_pulse_q <= 1'b1;
                            if (!cmd_fifo_full) begin
                                cmd_fifo_mem[cmd_wptr_bin_q[CDC_ADDRW-1:0]] <= {
                                    launch_ctrl_q, launch_addr_hi_q, launch_addr_lo_q
                                };
                                cmd_wptr_bin_q  <= cmd_wptr_bin_next;
                                cmd_wptr_gray_q <= cmd_wptr_gray_next;
                            end else begin
                                fault_sticky_q  <= 1'b1;
                                irq_status_q[1] <= 1'b1;
                            end
                        end
                        CSR_THERMAL_CTRL: begin
                            if (wr_strb[0]) begin
                                thermal_throttle_en_q <= wr_data[0];
                                thermal_duty_q        <= wr_data[7:4];
                            end
                        end
                        CSR_IRQ_ENABLE: begin
                            if (wr_strb[0]) begin
                                irq_enable_q <= wr_data[2:0];
                            end
                        end
                        CSR_IRQ_STATUS: begin
                            if (wr_strb[0]) begin
                                // Write-1-to-clear
                                irq_status_q <= irq_status_q & ~wr_data[2:0];
                            end
                        end
                        default: begin
                            // RO / reserved registers ignore writes
                        end
                    endcase
                end
            end

            // AXI4-Lite Read path (CSR 0-wait-state, Boot SRAM 1-cycle synchronous latency, SLVERR under MBIST)
            if (rvalid_q && s_axil_rready) begin
                rvalid_q <= 1'b0;
            end else if (ar_sram_wait_q) begin
                ar_sram_wait_q <= 1'b0;
                rvalid_q       <= 1'b1;
                rdata_q        <= mbist_active ? 32'h0000_0000 : boot_sram_rdata;
                rresp_q        <= mbist_active ? 2'b10 : 2'b00;
            end else if (ar_accept) begin
                if (rd_is_sram) begin
                    if (mbist_active) begin
                        rvalid_q <= 1'b1;
                        rdata_q  <= 32'h0000_0000;
                        rresp_q  <= 2'b10;
                    end else begin
                        ar_sram_wait_q <= 1'b1;
                    end
                end else begin
                    rvalid_q <= 1'b1;
                    rdata_q  <= csr_rdata_comb;
                    rresp_q  <= (s_axil_araddr[11:10] == 2'b00) ? 2'b00 : 2'b10;
                end
            end
        end
    end

    // ------------------------------------------------------------------------
    // 9. Compute Core Domain: Kernel Execution & Cycle Counter (clk_core)
    // ------------------------------------------------------------------------
    localparam [1:0] CORE_IDLE   = 2'd0;
    localparam [1:0] CORE_EXEC   = 2'd1;
    localparam [1:0] CORE_FINISH = 2'd2;

    (* keep = "true" *) reg        soft_rst_core_sync1_q;
    (* keep = "true" *) reg        soft_rst_core_sync2_q;
    (* keep = "true" *) reg        throttle_core_sync1_q;
    (* keep = "true" *) reg        throttle_core_sync2_q;
    reg [63:0]                     core_cycle_cnt_q;
    reg [1:0]                      core_state_q;
    reg [11:0]                     core_rem_cycles_q;
    reg [3:0]                      core_throttle_cnt_q;
    reg [95:0]                     active_cmd_q;

    always @(posedge clk_core or negedge rst_core_n) begin
        if (!rst_core_n) begin
            soft_rst_core_sync1_q  <= 1'b0;
            soft_rst_core_sync2_q  <= 1'b0;
            throttle_core_sync1_q  <= 1'b0;
            throttle_core_sync2_q  <= 1'b0;
            cycle_req_core_sync1_q <= 1'b0;
            cycle_req_core_sync2_q <= 1'b0;
            cycle_ack_core_q       <= 1'b0;
            cycle_snap_core_q      <= 64'h0;

            cmd_wptr_gray_sync1_q  <= {(CDC_ADDRW+1){1'b0}};
            cmd_wptr_gray_sync2_q  <= {(CDC_ADDRW+1){1'b0}};
            cmd_rptr_bin_q         <= {(CDC_ADDRW+1){1'b0}};
            cmd_rptr_gray_q        <= {(CDC_ADDRW+1){1'b0}};

            rsp_wptr_bin_q         <= {(CDC_ADDRW+1){1'b0}};
            rsp_wptr_gray_q        <= {(CDC_ADDRW+1){1'b0}};
            rsp_rptr_gray_sync1_q  <= {(CDC_ADDRW+1){1'b0}};
            rsp_rptr_gray_sync2_q  <= {(CDC_ADDRW+1){1'b0}};

            core_cycle_cnt_q       <= 64'h0;
            core_state_q           <= CORE_IDLE;
            core_busy_q            <= 1'b0;
            core_rem_cycles_q      <= 12'h0;
            core_throttle_cnt_q    <= 4'h0;
            active_cmd_q           <= 96'h0;
        end else begin
            // 2-FF control & Gray-pointer synchronizers into clk_core
            soft_rst_core_sync1_q  <= soft_reset_q;
            soft_rst_core_sync2_q  <= soft_rst_core_sync1_q;
            throttle_core_sync1_q  <= thermal_throttle_en_q;
            throttle_core_sync2_q  <= throttle_core_sync1_q;
            cycle_req_core_sync1_q <= cycle_req_axi_q;
            cycle_req_core_sync2_q <= cycle_req_core_sync1_q;

            cmd_wptr_gray_sync1_q  <= cmd_wptr_gray_q;
            cmd_wptr_gray_sync2_q  <= cmd_wptr_gray_sync1_q;
            rsp_rptr_gray_sync1_q  <= rsp_rptr_gray_q;
            rsp_rptr_gray_sync2_q  <= rsp_rptr_gray_sync1_q;

            // Toggle-handshake cycle snapshot: stays synchronized even across soft_reset so MCP never tears
            if (cycle_req_core_sync2_q != cycle_ack_core_q) begin
                cycle_snap_core_q <= soft_rst_core_sync2_q ? 64'h0 : core_cycle_cnt_q;
                cycle_ack_core_q  <= cycle_req_core_sync2_q;
            end

            if (soft_rst_core_sync2_q) begin
                core_cycle_cnt_q    <= 64'h0;
                core_state_q        <= CORE_IDLE;
                core_busy_q         <= 1'b0;
                core_rem_cycles_q   <= 12'h0;
                core_throttle_cnt_q <= 4'h0;
            end else begin
                core_cycle_cnt_q    <= core_cycle_cnt_q + 64'd1;
                core_throttle_cnt_q <= core_throttle_cnt_q + 4'd1;

                case (core_state_q)
                    CORE_IDLE: begin
                        core_busy_q <= 1'b0;
                        if (!cmd_fifo_empty) begin
                            active_cmd_q      <= cmd_fifo_mem[cmd_rptr_bin_q[CDC_ADDRW-1:0]];
                            cmd_rptr_bin_q    <= cmd_rptr_bin_next;
                            cmd_rptr_gray_q   <= cmd_rptr_gray_next;
                            core_rem_cycles_q <= cmd_fifo_mem[cmd_rptr_bin_q[CDC_ADDRW-1:0]][91:80];
                            core_busy_q       <= 1'b1;
                            core_state_q      <= CORE_EXEC;
                        end
                    end

                    CORE_EXEC: begin
                        core_busy_q <= 1'b1;
                        if (!throttle_core_sync2_q || (core_throttle_cnt_q[1:0] == 2'b00)) begin
                            if (core_rem_cycles_q == 12'h000) begin
                                core_state_q <= CORE_FINISH;
                            end else begin
                                core_rem_cycles_q <= core_rem_cycles_q - 12'd1;
                            end
                        end
                    end

                    CORE_FINISH: begin
                        if (!rsp_fifo_full) begin
                            // Forward completion or HBM memory operation across clk_core -> clk_axi FIFO
                            // active_cmd_q[93:92] = rsp_op (00=done, 01=HBM RD, 10=HBM WR)
                            // active_cmd_q[95:94] = injected fault flags
                            rsp_fifo_mem[rsp_wptr_bin_q[CDC_ADDRW-1:0]] <= {
                                active_cmd_q[93:92],
                                |active_cmd_q[95:94],
                                1'b0,
                                active_cmd_q[63:0]
                            };
                            rsp_wptr_bin_q  <= rsp_wptr_bin_next;
                            rsp_wptr_gray_q <= rsp_wptr_gray_next;
                            core_busy_q     <= 1'b0;
                            core_state_q    <= CORE_IDLE;
                        end
                    end

                    default: begin
                        core_state_q <= CORE_IDLE;
                        core_busy_q  <= 1'b0;
                    end
                endcase
            end
        end
    end

    // Terminate reserved / non-decoded protocol wires cleanly for zero-warning lint
    wire _unused_ok = &{1'b0,
                        s_axil_awaddr[1:0],
                        s_axil_araddr[1:0],
                        s_axil_awprot,
                        s_axil_arprot,
                        m_axi_bid,
                        m_axi_rid,
                        cmd_doorbell_pulse_q,
                        active_cmd_q[91:64]};

endmodule
