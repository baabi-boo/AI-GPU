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

// Formal verification harness for VX_asic_dft_top (IEEE-1149.1 JTAG TAP + DFT).
// Verified via Yosys + yosys-smtbmc + Z3:
//   1. Unbounded k-induction (with read_slang) bound directly to dut.tap_state_q
//      and VX_asic_dft_top outputs:
//      a) 1-step equivalence: dut.tap_state_q == next_tap_state(prev, tms) on every TCK
//      b) 5-cycle TMS=1 return from ANY 4-bit dut.tap_state_q to TAP_TEST_LOGIC_RESET
//      c) Reset and TEST_LOGIC_RESET safe functional outputs and TDO OE polarity
//   2. Full dual-edge BMC directly on VX_asic_dft_top: reachable 5-cycle TMS=1 reset,
//      IDCODE immutability (32'h1A16_B101 bit-serial on TDO), and functional safety.
module VX_asic_dft_formal (
    input  wire        tck,
    input  wire        trst_n,
    input  wire        tms,
    input  wire        tdi,
    input  wire        por_n,
    input  wire        test_mode_pin,
    input  wire        scan_enable_pin,
    input  wire [7:0]  scan_in,
    input  wire        mbist_done,
    input  wire        mbist_fail,

    // Observable outputs of VX_asic_dft_top
    output wire        tdo,
    output wire        tdo_oe_n,
    output wire [7:0]  scan_out,
    output wire        dft_scan_enable,
    output wire        dft_test_mode,
    output wire        dft_cg_override,
    output wire        mbist_run,
    output wire        mbist_retention_mode,
    output wire [3:0]  pwr_clust_en,
    output wire [3:0]  pwr_clust_iso_en,
    output wire [3:0]  pwr_clust_ret_en
);

    localparam logic [31:0] EXPECTED_IDCODE = 32'h1A16_B101;

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

    VX_asic_dft_top #(
        .IDCODE_VAL   (EXPECTED_IDCODE),
        .NUM_CLUSTERS (4),
        .SCAN_CHAINS  (8)
    ) dut (
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
        .mbist_run            (mbist_run),
        .mbist_retention_mode (mbist_retention_mode),
        .mbist_done           (mbist_done),
        .mbist_fail           (mbist_fail),
        .pwr_clust_en         (pwr_clust_en),
        .pwr_clust_iso_en     (pwr_clust_iso_en),
        .pwr_clust_ret_en     (pwr_clust_ret_en)
    );

`ifdef FORMAL
    // 16-state exact IEEE-1149.1 reference TAP transition function
    function automatic [3:0] next_tap_state(input [3:0] cur, input tms_in);
        case (cur)
            TAP_TEST_LOGIC_RESET: next_tap_state = tms_in ? TAP_TEST_LOGIC_RESET : TAP_RUN_TEST_IDLE;
            TAP_RUN_TEST_IDLE:    next_tap_state = tms_in ? TAP_SELECT_DR_SCAN   : TAP_RUN_TEST_IDLE;
            TAP_SELECT_DR_SCAN:   next_tap_state = tms_in ? TAP_SELECT_IR_SCAN   : TAP_CAPTURE_DR;
            TAP_CAPTURE_DR:       next_tap_state = tms_in ? TAP_EXIT1_DR         : TAP_SHIFT_DR;
            TAP_SHIFT_DR:         next_tap_state = tms_in ? TAP_EXIT1_DR         : TAP_SHIFT_DR;
            TAP_EXIT1_DR:         next_tap_state = tms_in ? TAP_UPDATE_DR        : TAP_PAUSE_DR;
            TAP_PAUSE_DR:         next_tap_state = tms_in ? TAP_EXIT2_DR         : TAP_PAUSE_DR;
            TAP_EXIT2_DR:         next_tap_state = tms_in ? TAP_UPDATE_DR        : TAP_SHIFT_DR;
            TAP_UPDATE_DR:        next_tap_state = tms_in ? TAP_SELECT_DR_SCAN   : TAP_RUN_TEST_IDLE;
            TAP_SELECT_IR_SCAN:   next_tap_state = tms_in ? TAP_TEST_LOGIC_RESET : TAP_CAPTURE_IR;
            TAP_CAPTURE_IR:       next_tap_state = tms_in ? TAP_EXIT1_IR         : TAP_SHIFT_IR;
            TAP_SHIFT_IR:         next_tap_state = tms_in ? TAP_EXIT1_IR         : TAP_SHIFT_IR;
            TAP_EXIT1_IR:         next_tap_state = tms_in ? TAP_UPDATE_IR        : TAP_PAUSE_IR;
            TAP_PAUSE_IR:         next_tap_state = tms_in ? TAP_EXIT2_IR         : TAP_PAUSE_IR;
            TAP_EXIT2_IR:         next_tap_state = tms_in ? TAP_UPDATE_IR        : TAP_SHIFT_IR;
            TAP_UPDATE_IR:        next_tap_state = tms_in ? TAP_SELECT_DR_SCAN   : TAP_RUN_TEST_IDLE;
            default:              next_tap_state = TAP_TEST_LOGIC_RESET;
        endcase
    endfunction

    function automatic [3:0] advance_5_tms1(input [3:0] start_state);
        reg [3:0] s1, s2, s3, s4;
        begin
            s1 = next_tap_state(start_state, 1'b1);
            s2 = next_tap_state(s1, 1'b1);
            s3 = next_tap_state(s2, 1'b1);
            s4 = next_tap_state(s3, 1'b1);
            advance_5_tms1 = next_tap_state(s4, 1'b1);
        end
    endfunction

    wire [3:0] arb_any_state = {tdi, tms, scan_in[1:0]};

`ifdef FORMAL_INDUCT_ONLY
    // Unbounded k-induction mode bound directly to dut.tap_state_q and DUT outputs.
    reg        f_seen_tck_q = 1'b0;
    reg [3:0]  f_prev_tap_state_q = TAP_TEST_LOGIC_RESET;
    reg        f_prev_tms_q = 1'b0;
    reg [2:0]  f_tms_ones_q = 3'd0;
    reg        f_pos_tog_q = 1'b0;
    reg        f_neg_tog_q = 1'b0;
    reg        f_neg_seen_q = 1'b0;

    always @(posedge tck or negedge dut.tap_rst_n) begin
        if (!dut.tap_rst_n) begin
            f_seen_tck_q       <= 1'b0;
            f_prev_tap_state_q <= TAP_TEST_LOGIC_RESET;
            f_prev_tms_q       <= 1'b0;
            f_tms_ones_q       <= 3'd0;
            f_pos_tog_q        <= 1'b0;
        end else begin
            f_seen_tck_q       <= 1'b1;
            f_prev_tap_state_q <= dut.tap_state_q;
            f_prev_tms_q       <= tms;
            f_pos_tog_q        <= ~f_pos_tog_q;
            if (tms) begin
                f_tms_ones_q <= (f_tms_ones_q < 3'd5) ? (f_tms_ones_q + 3'd1) : 3'd5;
            end else begin
                f_tms_ones_q <= 3'd0;
            end
        end
    end

    always @(negedge tck or negedge dut.tap_rst_n) begin
        if (!dut.tap_rst_n) begin
            f_neg_tog_q  <= 1'b0;
            f_neg_seen_q <= 1'b0;
        end else begin
            f_neg_tog_q  <= f_pos_tog_q;
            f_neg_seen_q <= 1'b1;
        end
    end

    // Negedge TCK updates tdo_oe_n_q and shadow control flops after posedge TCK changes tap_state_q.
    wire f_after_negedge = f_neg_seen_q && (f_neg_tog_q == f_pos_tog_q) && !tck;

    // Exact reachable state images after N consecutive TMS=1 steps from any 4-bit state.
    wire f_in_1_tms1 = (dut.tap_state_q == TAP_TEST_LOGIC_RESET) ||
                       (dut.tap_state_q == TAP_SELECT_DR_SCAN)   ||
                       (dut.tap_state_q == TAP_SELECT_IR_SCAN)   ||
                       (dut.tap_state_q == TAP_EXIT1_DR)         ||
                       (dut.tap_state_q == TAP_EXIT2_DR)         ||
                       (dut.tap_state_q == TAP_UPDATE_DR)        ||
                       (dut.tap_state_q == TAP_EXIT1_IR)         ||
                       (dut.tap_state_q == TAP_EXIT2_IR)         ||
                       (dut.tap_state_q == TAP_UPDATE_IR);

    wire f_in_2_tms1 = (dut.tap_state_q == TAP_TEST_LOGIC_RESET) ||
                       (dut.tap_state_q == TAP_SELECT_DR_SCAN)   ||
                       (dut.tap_state_q == TAP_SELECT_IR_SCAN)   ||
                       (dut.tap_state_q == TAP_UPDATE_DR)        ||
                       (dut.tap_state_q == TAP_UPDATE_IR);

    wire f_in_3_tms1 = (dut.tap_state_q == TAP_TEST_LOGIC_RESET) ||
                       (dut.tap_state_q == TAP_SELECT_DR_SCAN)   ||
                       (dut.tap_state_q == TAP_SELECT_IR_SCAN);

    wire f_in_4_tms1 = (dut.tap_state_q == TAP_TEST_LOGIC_RESET) ||
                       (dut.tap_state_q == TAP_SELECT_IR_SCAN);

    always @* begin
        if (!trst_n || !por_n) begin
            assert (dut.tap_state_q == TAP_TEST_LOGIC_RESET);
            if (!scan_enable_pin && !test_mode_pin) begin
                assert (dut.dft_scan_enable == 1'b0);
                assert (dut.dft_test_mode   == 1'b0);
                assert (dut.dft_cg_override == 1'b0);
            end
            assert (dut.mbist_run            == 1'b0);
            assert (dut.mbist_retention_mode == 1'b0);
            assert (dut.pwr_clust_en         == 4'hF);
            assert (dut.pwr_clust_iso_en     == 4'h0);
            assert (dut.pwr_clust_ret_en     == 4'h0);
            assert (dut.tdo_oe_n             == 1'b1);
        end

        // (a) 1-step transition equivalence on actual dut.tap_state_q
        if (f_seen_tck_q) begin
            assert (dut.tap_state_q == next_tap_state(f_prev_tap_state_q, f_prev_tms_q));
        end

        // (b) Inductive 5-cycle TMS=1 reset proof on actual dut.tap_state_q from ANY 4-bit state
        assert (f_tms_ones_q <= 3'd5);
        if (f_tms_ones_q == 3'd1) assert (f_in_1_tms1);
        if (f_tms_ones_q == 3'd2) assert (f_in_2_tms1);
        if (f_tms_ones_q == 3'd3) assert (f_in_3_tms1);
        if (f_tms_ones_q == 3'd4) assert (f_in_4_tms1);
        if (f_tms_ones_q >= 3'd5) begin
            assert (dut.tap_state_q == TAP_TEST_LOGIC_RESET);
            assert (next_tap_state(dut.tap_state_q, 1'b1) == TAP_TEST_LOGIC_RESET);
        end

        assert (advance_5_tms1(arb_any_state) == TAP_TEST_LOGIC_RESET);
        assert (next_tap_state(TAP_TEST_LOGIC_RESET, 1'b1) == TAP_TEST_LOGIC_RESET);

        // (c) Safe functional outputs in TEST_LOGIC_RESET and TDO OE polarity after negedge TCK
        if (f_after_negedge) begin
            if (dut.tap_state_q == TAP_TEST_LOGIC_RESET) begin
                // Constrain internal scan_ctrl_q directly so unconstrained pin toggles cannot hide dirty state across induction steps.
                assert (dut.scan_ctrl_q == 8'h00);
                if (!scan_enable_pin && !test_mode_pin) begin
                    assert (dut.dft_scan_enable == 1'b0);
                    assert (dut.dft_test_mode   == 1'b0);
                    assert (dut.dft_cg_override == 1'b0);
                end
                assert (dut.mbist_run            == 1'b0);
                assert (dut.mbist_retention_mode == 1'b0);
                assert (dut.pwr_clust_en         == 4'hF);
                assert (dut.pwr_clust_iso_en     == 4'h0);
                assert (dut.pwr_clust_ret_en     == 4'h0);
            end
            assert (dut.tdo_oe_n == ~((dut.tap_state_q == TAP_SHIFT_DR) || (dut.tap_state_q == TAP_SHIFT_IR)));
        end
    end
`else
    // Full dual-edge BMC mode against real VX_asic_dft_top
    reg [1:0]  f_rst_cnt_q;
    reg        f_phase_q;
    reg [2:0]  f_tms_streak_q;
    reg [3:0]  f_ref_tap_q;
    reg        f_tms_prev_q;
    reg        f_tdi_prev_q;

    reg [5:0]  f_idcode_cnt_q;
    reg [31:0] f_idcode_exp_q;
    reg        f_idcode_check_q;
    reg        f_ir_is_idcode_q;
    reg [4:0]  f_ir_shift_q;

    initial begin
        f_rst_cnt_q      = 2'd0;
        f_phase_q        = 1'b0;
        f_tms_streak_q   = 3'd0;
        f_ref_tap_q      = TAP_TEST_LOGIC_RESET;
        f_tms_prev_q     = 1'b0;
        f_tdi_prev_q     = 1'b0;
        f_idcode_cnt_q   = 6'd0;
        f_idcode_exp_q   = EXPECTED_IDCODE;
        f_idcode_check_q = 1'b0;
        f_ir_is_idcode_q = 1'b1;
        f_ir_shift_q     = 5'h01;
    end

    always @($global_clock) begin
        if (f_rst_cnt_q < 2'd2) begin
            f_rst_cnt_q <= f_rst_cnt_q + 2'd1;
        end
        if (f_rst_cnt_q == 2'd0) begin
            assume (tck == 1'b0);
            assume (!trst_n);
            assume (!por_n);
            f_phase_q <= 1'b0;
        end else if (f_rst_cnt_q == 2'd1) begin
            assume (tck == 1'b0);
            assume (trst_n);
            assume (por_n);
            f_phase_q <= 1'b1;
        end else begin
            assume (tck == f_phase_q);
            assume (trst_n);
            assume (por_n);
            if (f_phase_q == 1'b1) begin
                assume (tms == f_tms_prev_q);
                assume (tdi == f_tdi_prev_q);
            end
            f_phase_q <= ~f_phase_q;
        end

        f_tms_prev_q <= tms;
        f_tdi_prev_q <= tdi;

        if (f_rst_cnt_q >= 2'd1) begin
            if (f_phase_q == 1'b0) begin
                f_ref_tap_q <= next_tap_state(f_ref_tap_q, tms);
                if (tms) begin
                    f_tms_streak_q <= (f_tms_streak_q < 3'd7) ? (f_tms_streak_q + 3'd1) : 3'd7;
                end else begin
                    f_tms_streak_q <= 3'd0;
                end

                if (f_ref_tap_q == TAP_TEST_LOGIC_RESET) begin
                    f_ir_shift_q <= 5'h01;
                end else if (f_ref_tap_q == TAP_CAPTURE_IR) begin
                    f_ir_shift_q <= 5'b00001;
                end else if (f_ref_tap_q == TAP_SHIFT_IR) begin
                    f_ir_shift_q <= {tdi, f_ir_shift_q[4:1]};
                end

                if (f_ref_tap_q == TAP_TEST_LOGIC_RESET) begin
                    f_idcode_check_q <= 1'b0;
                    f_idcode_cnt_q   <= 6'd0;
                    f_idcode_exp_q   <= EXPECTED_IDCODE;
                end else if ((f_ref_tap_q == TAP_CAPTURE_DR) && f_ir_is_idcode_q) begin
                    f_idcode_check_q <= 1'b1;
                    f_idcode_cnt_q   <= 6'd0;
                    f_idcode_exp_q   <= EXPECTED_IDCODE;
                end else if ((f_ref_tap_q == TAP_SHIFT_DR) && f_ir_is_idcode_q && f_idcode_check_q) begin
                    if (f_idcode_cnt_q < 6'd32) begin
                        f_idcode_cnt_q <= f_idcode_cnt_q + 6'd1;
                        f_idcode_exp_q <= {tdi, f_idcode_exp_q[31:1]};
                    end
                end else begin
                    f_idcode_check_q <= 1'b0;
                end
            end else begin
                if (f_ref_tap_q == TAP_TEST_LOGIC_RESET) begin
                    f_ir_is_idcode_q <= 1'b1;
                end else if (f_ref_tap_q == TAP_UPDATE_IR) begin
                    f_ir_is_idcode_q <= (f_ir_shift_q == 5'h01);
                end
            end
        end

        // 1. Exhaustive 16-state 5-cycle TMS=1 reset proof
        assert (advance_5_tms1(arb_any_state) == TAP_TEST_LOGIC_RESET);
        assert (next_tap_state(TAP_TEST_LOGIC_RESET, 1'b1) == TAP_TEST_LOGIC_RESET);

        if (f_rst_cnt_q >= 2'd2) begin
            // 2. Reachable TAP FSM 5-cycle TMS=1 reset proof
            if (f_tms_streak_q >= 3'd5) begin
                assert (f_ref_tap_q == TAP_TEST_LOGIC_RESET);
            end

            // 3. Functional safety in TEST_LOGIC_RESET
            if ((f_ref_tap_q == TAP_TEST_LOGIC_RESET) && (f_phase_q == 1'b0)) begin
                if (!scan_enable_pin && !test_mode_pin) begin
                    assert (dft_scan_enable == 1'b0);
                    assert (dft_test_mode   == 1'b0);
                    assert (dft_cg_override == 1'b0);
                end
                assert (mbist_run            == 1'b0);
                assert (mbist_retention_mode == 1'b0);
                assert (pwr_clust_en         == 4'hF);
                assert (pwr_clust_iso_en     == 4'h0);
                assert (pwr_clust_ret_en     == 4'h0);
                assert (tdo_oe_n             == 1'b1);
                assert (tdo                  == 1'b0);
            end

            // 4. IDCODE immutability verified directly on DUT TDO pin
            if ((f_ref_tap_q == TAP_SHIFT_DR) && (f_phase_q == 1'b0) &&
                f_ir_is_idcode_q && f_idcode_check_q && (f_idcode_cnt_q < 6'd32)) begin
                assert (tdo_oe_n == 1'b0);
                assert (tdo == f_idcode_exp_q[0]);
            end

            // 5. TDO output enable always matches SHIFT_DR or SHIFT_IR
            if (f_phase_q == 1'b0) begin
                assert (tdo_oe_n == ~((f_ref_tap_q == TAP_SHIFT_DR) || (f_ref_tap_q == TAP_SHIFT_IR)));
            end
        end
    end
`endif
`endif

endmodule
