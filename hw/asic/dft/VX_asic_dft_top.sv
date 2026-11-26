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

// IEEE-1149.1 JTAG TAP controller + DFT + MBIST + Power-Domain Control Wrapper.
// Exposes IDCODE (32'h1A16_B101), BYPASS, SCAN_CTRL, MBIST_CTRL, and PWR_CTRL.
module VX_asic_dft_top #(
    parameter logic [31:0] IDCODE_VAL  = 32'h1A16_B101,
    parameter int          NUM_CLUSTERS = 4,
    parameter int          SCAN_CHAINS  = 8
) (
    // JTAG IEEE-1149.1 pins
    input  wire                     tck,
    input  wire                     trst_n,
    input  wire                     tms,
    input  wire                     tdi,
    output wire                     tdo,
    output wire                     tdo_oe_n,

    // Always-on reset & DFT mode pins
    input  wire                     por_n,
    input  wire                     test_mode_pin,
    input  wire                     scan_enable_pin,

    // Scan-chain stub / boundary pass-through ports
    input  wire [SCAN_CHAINS-1:0]   scan_in,
    output wire [SCAN_CHAINS-1:0]   scan_out,

    // DFT / clock-gating control outputs
    output wire                     dft_scan_enable,
    output wire                     dft_test_mode,
    output wire                     dft_cg_override,

    // MBIST collar controls and status inputs (from SRAM BIST engines)
    output wire                     mbist_run,
    output wire                     mbist_retention_mode,
    input  wire                     mbist_done,
    input  wire                     mbist_fail,

    // Power-domain control outputs (to PMU / UPF switches & isolation)
    output wire [NUM_CLUSTERS-1:0]  pwr_clust_en,
    output wire [NUM_CLUSTERS-1:0]  pwr_clust_iso_en,
    output wire [NUM_CLUSTERS-1:0]  pwr_clust_ret_en
);

    // ------------------------------------------------------------------------
    // IEEE-1149.1 16-state TAP FSM encoding
    // ------------------------------------------------------------------------
    localparam [3:0] TAP_TEST_LOGIC_RESET = 4'h0;
    localparam [3:0] TAP_RUN_TEST_IDLE    = 4'h1;
    localparam [3:0] TAP_SELECT_DR_SCAN   = 4'h2;
    localparam [3:0] TAP_CAPTURE_DR       = 4'h3;
    localparam [3:0] TAP_SHIFT_DR         = 4'h4;
    localparam [3:0] TAP_EXIT1_DR         = 4'h5;
    localparam [3:0] TAP_PAUSE_DR         = 4'h6;
    localparam [3:0] TAP_EXIT2_DR         = 4'h7;
    localparam [3:0] TAP_UPDATE_DR        = 4'h8;
    localparam [3:0] TAP_SELECT_IR_SCAN   = 4'h9;
    localparam [3:0] TAP_CAPTURE_IR       = 4'hA;
    localparam [3:0] TAP_SHIFT_IR         = 4'hB;
    localparam [3:0] TAP_EXIT1_IR         = 4'hC;
    localparam [3:0] TAP_PAUSE_IR         = 4'hD;
    localparam [3:0] TAP_EXIT2_IR         = 4'hE;
    localparam [3:0] TAP_UPDATE_IR        = 4'hF;

    // 5-bit JTAG IR opcodes
    localparam [4:0] IR_IDCODE    = 5'h01;
    localparam [4:0] IR_SCAN_CTRL = 5'h08;
    localparam [4:0] IR_MBIST_CTRL= 5'h09;
    localparam [4:0] IR_PWR_CTRL  = 5'h0A;
    localparam [4:0] IR_BYPASS    = 5'h1F;

    // DR widths:
    //   IDCODE     : 32b
    //   SCAN_CTRL  : 8b  -> [0]=scan_en, [1]=test_mode, [2]=cg_override, [7:3]=rsvd
    //   MBIST_CTRL : 8b  -> wr: [0]=run, [1]=ret_mode; rd: [3]=fail, [2]=done, [1]=ret_mode, [0]=run
    //   PWR_CTRL   : 12b -> [3:0]=clust_en, [7:4]=clust_iso_en, [11:8]=clust_ret_en (max 4 clusters)
    //   BYPASS     : 1b
    localparam int DR_MAX_W = 32;

    generate
        if ((NUM_CLUSTERS < 1) || (NUM_CLUSTERS > 4) || (SCAN_CHAINS < 1)) begin : g_bad_params
`ifndef SYNTHESIS
            initial begin
                $error("VX_asic_dft_top: invalid params NUM_CLUSTERS=%0d SCAN_CHAINS=%0d",
                       NUM_CLUSTERS, SCAN_CHAINS);
            end
`endif
        end
    endgenerate

    wire tap_rst_n;
    assign tap_rst_n = trst_n & por_n;

    reg [3:0] tap_state_q;
    reg [3:0] tap_state_d;

    // TAP next-state transition table
    always @(*) begin
        case (tap_state_q)
            TAP_TEST_LOGIC_RESET: tap_state_d = tms ? TAP_TEST_LOGIC_RESET : TAP_RUN_TEST_IDLE;
            TAP_RUN_TEST_IDLE:    tap_state_d = tms ? TAP_SELECT_DR_SCAN   : TAP_RUN_TEST_IDLE;
            TAP_SELECT_DR_SCAN:   tap_state_d = tms ? TAP_SELECT_IR_SCAN   : TAP_CAPTURE_DR;
            TAP_CAPTURE_DR:       tap_state_d = tms ? TAP_EXIT1_DR         : TAP_SHIFT_DR;
            TAP_SHIFT_DR:         tap_state_d = tms ? TAP_EXIT1_DR         : TAP_SHIFT_DR;
            TAP_EXIT1_DR:         tap_state_d = tms ? TAP_UPDATE_DR        : TAP_PAUSE_DR;
            TAP_PAUSE_DR:         tap_state_d = tms ? TAP_EXIT2_DR         : TAP_PAUSE_DR;
            TAP_EXIT2_DR:         tap_state_d = tms ? TAP_UPDATE_DR        : TAP_SHIFT_DR;
            TAP_UPDATE_DR:        tap_state_d = tms ? TAP_SELECT_DR_SCAN   : TAP_RUN_TEST_IDLE;
            TAP_SELECT_IR_SCAN:   tap_state_d = tms ? TAP_TEST_LOGIC_RESET : TAP_CAPTURE_IR;
            TAP_CAPTURE_IR:       tap_state_d = tms ? TAP_EXIT1_IR         : TAP_SHIFT_IR;
            TAP_SHIFT_IR:         tap_state_d = tms ? TAP_EXIT1_IR         : TAP_SHIFT_IR;
            TAP_EXIT1_IR:         tap_state_d = tms ? TAP_UPDATE_IR        : TAP_PAUSE_IR;
            TAP_PAUSE_IR:         tap_state_d = tms ? TAP_EXIT2_IR         : TAP_PAUSE_IR;
            TAP_EXIT2_IR:         tap_state_d = tms ? TAP_UPDATE_IR        : TAP_SHIFT_IR;
            TAP_UPDATE_IR:        tap_state_d = tms ? TAP_SELECT_DR_SCAN   : TAP_RUN_TEST_IDLE;
            default:              tap_state_d = TAP_TEST_LOGIC_RESET;
        endcase
    end

    always @(posedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            tap_state_q <= TAP_TEST_LOGIC_RESET;
        end else begin
            tap_state_q <= tap_state_d;
        end
    end

    // ------------------------------------------------------------------------
    // Instruction Register (IR)
    // ------------------------------------------------------------------------
    reg [4:0] ir_shift_q;
    reg [4:0] ir_hold_q;

    always @(posedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            ir_shift_q <= IR_IDCODE;
        end else if (tap_state_q == TAP_TEST_LOGIC_RESET) begin
            ir_shift_q <= IR_IDCODE;
        end else if (tap_state_q == TAP_CAPTURE_IR) begin
            ir_shift_q <= 5'b00001;
        end else if (tap_state_q == TAP_SHIFT_IR) begin
            ir_shift_q <= {tdi, ir_shift_q[4:1]};
        end
    end

    always @(negedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            ir_hold_q <= IR_IDCODE;
        end else if (tap_state_q == TAP_TEST_LOGIC_RESET) begin
            ir_hold_q <= IR_IDCODE;
        end else if (tap_state_q == TAP_UPDATE_IR) begin
            ir_hold_q <= ir_shift_q;
        end
    end

    // ------------------------------------------------------------------------
    // 2-FF CDC Synchronizers for MBIST Status Inputs (clk_axi -> tck)
    // ------------------------------------------------------------------------
    (* keep = "true" *) reg mbist_done_tck_sync1_q;
    (* keep = "true" *) reg mbist_done_tck_sync2_q;
    (* keep = "true" *) reg mbist_fail_tck_sync1_q;
    (* keep = "true" *) reg mbist_fail_tck_sync2_q;

    always @(posedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            mbist_done_tck_sync1_q <= 1'b0;
            mbist_done_tck_sync2_q <= 1'b0;
            mbist_fail_tck_sync1_q <= 1'b0;
            mbist_fail_tck_sync2_q <= 1'b0;
        end else begin
            mbist_done_tck_sync1_q <= mbist_done;
            mbist_done_tck_sync2_q <= mbist_done_tck_sync1_q;
            mbist_fail_tck_sync1_q <= mbist_fail;
            mbist_fail_tck_sync2_q <= mbist_fail_tck_sync1_q;
        end
    end

    // ------------------------------------------------------------------------
    // Data Registers (DR) and Shadow Control Registers
    // ------------------------------------------------------------------------
    reg [DR_MAX_W-1:0]                  dr_shift_q;
    (* keep = "true" *) reg [7:0]       scan_ctrl_q;
    (* keep = "true" *) reg [7:0]       mbist_ctrl_q;
    (* keep = "true" *) reg [11:0]      pwr_ctrl_q;

    wire [7:0] mbist_status_vec;
    assign mbist_status_vec = {4'b0000, mbist_fail_tck_sync2_q, mbist_done_tck_sync2_q, mbist_ctrl_q[1:0]};

    always @(posedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            dr_shift_q <= {DR_MAX_W{1'b0}};
        end else if (tap_state_q == TAP_TEST_LOGIC_RESET) begin
            dr_shift_q <= IDCODE_VAL;
        end else if (tap_state_q == TAP_CAPTURE_DR) begin
            case (ir_hold_q)
                IR_IDCODE:     dr_shift_q <= IDCODE_VAL;
                IR_SCAN_CTRL:  dr_shift_q <= {{(DR_MAX_W-8){1'b0}}, scan_ctrl_q};
                IR_MBIST_CTRL: dr_shift_q <= {{(DR_MAX_W-8){1'b0}}, mbist_status_vec};
                IR_PWR_CTRL:   dr_shift_q <= {{(DR_MAX_W-12){1'b0}}, pwr_ctrl_q};
                IR_BYPASS:     dr_shift_q <= {DR_MAX_W{1'b0}};
                default:       dr_shift_q <= {DR_MAX_W{1'b0}};
            endcase
        end else if (tap_state_q == TAP_SHIFT_DR) begin
            case (ir_hold_q)
                IR_IDCODE:     dr_shift_q <= {tdi, dr_shift_q[31:1]};
                IR_SCAN_CTRL:  dr_shift_q <= {{(DR_MAX_W-8){1'b0}}, tdi, dr_shift_q[7:1]};
                IR_MBIST_CTRL: dr_shift_q <= {{(DR_MAX_W-8){1'b0}}, tdi, dr_shift_q[7:1]};
                IR_PWR_CTRL:   dr_shift_q <= {{(DR_MAX_W-12){1'b0}}, tdi, dr_shift_q[11:1]};
                IR_BYPASS:     dr_shift_q <= {{(DR_MAX_W-1){1'b0}}, tdi};
                default:       dr_shift_q <= {{(DR_MAX_W-1){1'b0}}, tdi};
            endcase
        end
    end

    // Update shadow control registers on falling edge of TCK in UPDATE_DR
    always @(negedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            scan_ctrl_q  <= 8'h00;
            mbist_ctrl_q <= 8'h00;
            // Default: all clusters powered on, isolation disabled, retention disabled
            pwr_ctrl_q   <= 12'h00F;
        end else if (tap_state_q == TAP_TEST_LOGIC_RESET) begin
            scan_ctrl_q  <= 8'h00;
            mbist_ctrl_q <= 8'h00;
            pwr_ctrl_q   <= 12'h00F;
        end else if (tap_state_q == TAP_UPDATE_DR) begin
            case (ir_hold_q)
                IR_SCAN_CTRL:  scan_ctrl_q  <= dr_shift_q[7:0];
                IR_MBIST_CTRL: mbist_ctrl_q <= dr_shift_q[7:0];
                IR_PWR_CTRL:   pwr_ctrl_q   <= dr_shift_q[11:0];
                IR_IDCODE,
                IR_BYPASS: begin
                    // Non-mutating instructions
                end
                default: begin
                    // Unimplemented opcodes behave as BYPASS
                end
            endcase
        end
    end

    // ------------------------------------------------------------------------
    // TDO output register (updates on negedge TCK per IEEE-1149.1)
    // ------------------------------------------------------------------------
    reg tdo_q;
    reg tdo_oe_n_q;

    wire shift_active;
    assign shift_active = (tap_state_q == TAP_SHIFT_DR) || (tap_state_q == TAP_SHIFT_IR);

    always @(negedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            tdo_q      <= 1'b0;
            tdo_oe_n_q <= 1'b1;
        end else begin
            tdo_oe_n_q <= ~shift_active;
            if (tap_state_q == TAP_SHIFT_IR) begin
                tdo_q <= ir_shift_q[0];
            end else if (tap_state_q == TAP_SHIFT_DR) begin
                tdo_q <= dr_shift_q[0];
            end else begin
                tdo_q <= 1'b0;
            end
        end
    end

    assign tdo      = tdo_q;
    assign tdo_oe_n = tdo_oe_n_q;

    // ------------------------------------------------------------------------
    // Exposed DFT / MBIST / Power-Domain controls and scan-chain bypass
    // ------------------------------------------------------------------------
    assign dft_scan_enable      = scan_enable_pin | scan_ctrl_q[0];
    assign dft_test_mode        = test_mode_pin   | scan_ctrl_q[1];
    assign dft_cg_override      = test_mode_pin   | scan_ctrl_q[2];

    assign mbist_run            = mbist_ctrl_q[0];
    assign mbist_retention_mode = mbist_ctrl_q[1];

    genvar ci;
    generate
        for (ci = 0; ci < NUM_CLUSTERS; ci = ci + 1) begin : g_pwr_ctrl
            if (ci < 4) begin : g_mapped
                assign pwr_clust_en[ci]     = pwr_ctrl_q[ci];
                assign pwr_clust_iso_en[ci] = pwr_ctrl_q[4 + ci];
                assign pwr_clust_ret_en[ci] = pwr_ctrl_q[8 + ci];
            end else begin : g_ext
                assign pwr_clust_en[ci]     = pwr_ctrl_q[3];
                assign pwr_clust_iso_en[ci] = pwr_ctrl_q[7];
                assign pwr_clust_ret_en[ci] = pwr_ctrl_q[11];
            end
        end
    endgenerate

    // Scan chain boundary registers (placeholder bypass flops when scan_enable active)
    reg [SCAN_CHAINS-1:0] scan_pipe_q;
    always @(posedge tck or negedge tap_rst_n) begin
        if (!tap_rst_n) begin
            scan_pipe_q <= {SCAN_CHAINS{1'b0}};
        end else if (dft_scan_enable) begin
            scan_pipe_q <= scan_in;
        end
    end
    assign scan_out = scan_pipe_q;

    // Upper control bits reserved for future JTAG shadow fields (read back via CAPTURE_DR)
    wire _unused_ok = &{1'b0, scan_ctrl_q[7:3], mbist_ctrl_q[7:2]};

endmodule
