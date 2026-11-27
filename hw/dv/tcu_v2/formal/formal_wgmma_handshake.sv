// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_formal_wgmma_handshake
    import VX_tcu_v2_pkg::*;
#(
    parameter int DESC_DEPTH   = 4,
    parameter int NUM_BARRIERS = 4,
    parameter int WATCHDOG_LIM = 8
) (
    input  logic                                clk,
    input  logic                                reset,
    // Symbolic inputs for WGMMA descriptor queue
    input  logic                                sym_q_flush,
    input  logic                                sym_q_enq_valid,
    input  tcu_v2_wgmma_desc_t                  sym_q_enq_desc,
    input  logic                                sym_q_deq_ready,
    // Symbolic inputs for barrier unit
    input  logic                                sym_bar_cmd_valid,
    input  logic [2:0]                          sym_bar_cmd_op,
    input  logic [TCU_V2_BARRIER_ID_W-1:0]      sym_bar_cmd_id,
    input  logic [15:0]                         sym_bar_cmd_count,
    input  logic                                sym_bar_cmd_phase,
    input  logic                                sym_bar_wait_valid,
    input  logic [TCU_V2_BARRIER_ID_W-1:0]      sym_bar_wait_id,
    input  logic                                sym_bar_wait_phase,
    // Symbolic inputs for 2-CTA pair sync (two cross-coupled peer instances)
    input  logic                                sym_cta0_req_valid,
    input  logic                                sym_cta1_req_valid,
    input  logic                                sym_cta_pair_en,
    input  logic                                sym_cta_split_n,
    input  logic [TCU_V2_BARRIER_ID_W-1:0]      sym_cta_bar_id,
    input  logic                                sym_cta_phase,
    input  logic                                sym_cta0_release,
    input  logic                                sym_cta1_release,
    output logic                                formal_ok_out
);

    localparam int CNT_W = $clog2(DESC_DEPTH + 1);

    // -------------------------------------------------------------------------
    // 1. WGMMA Descriptor Queue DUT + Shadow Reference Model
    // -------------------------------------------------------------------------
    logic                           q_enq_ready;
    logic                           q_deq_valid;
    tcu_v2_wgmma_desc_t             q_deq_desc;
    tcu_v2_wgmma_desc_t             q_peek_desc;
    logic                           q_peek_valid;
    logic                           q_empty;
    logic                           q_full;
    logic [CNT_W-1:0]               q_occupancy;
    logic [CNT_W-1:0]               q_credits;
    logic                           q_reject_pulse;
    logic [TCU_V2_DESC_ID_W-1:0]    q_reject_id;
    logic [31:0]                    q_acc_cnt;
    logic [31:0]                    q_rej_cnt;
    logic [31:0]                    q_flu_cnt;

    VX_tcu_v2_wgmma_desc_q #(
        .DEPTH (DESC_DEPTH)
    ) u_desc_q_dut (
        .clk                (clk),
        .reset              (reset),
        .flush              (sym_q_flush),
        .enq_valid          (sym_q_enq_valid),
        .enq_ready          (q_enq_ready),
        .enq_desc           (sym_q_enq_desc),
        .deq_ready          (sym_q_deq_ready),
        .deq_valid          (q_deq_valid),
        .deq_desc           (q_deq_desc),
        .peek_desc          (q_peek_desc),
        .peek_valid         (q_peek_valid),
        .empty              (q_empty),
        .full               (q_full),
        .occupancy          (q_occupancy),
        .credits_avail      (q_credits),
        .reject_pulse       (q_reject_pulse),
        .reject_desc_id     (q_reject_id),
        .total_accepted_cnt (q_acc_cnt),
        .total_rejected_cnt (q_rej_cnt),
        .total_flushed_cnt  (q_flu_cnt)
    );

    // Independent shadow FIFO model & legality helper
    function automatic logic ref_desc_acceptable(
        input tcu_v2_wgmma_desc_t d
    );
        logic fmt_ok;
        logic bounds_ok;
        logic dim_ok;
        logic scale_ok;
        fmt_ok    = tcu_v2_desc_is_legal(d);
        bounds_ok = (int'(d.tmem_a_row) < 128) && (int'(d.tmem_b_row) < 128) &&
                    (int'(d.tmem_c_row) < 128) && (int'(d.tmem_d_row) < 128) &&
                    (int'(d.tmem_a_col) < 512) && (int'(d.tmem_b_col) < 512) &&
                    (int'(d.tmem_c_col) < 512) && (int'(d.tmem_d_col) < 512);
        dim_ok    = (d.tile_m >= 16'(TCU_V2_ARRAY_M)) && (d.tile_n >= 16'(TCU_V2_ARRAY_N)) &&
                    (d.tile_k >= 16'(TCU_V2_ARRAY_K)) &&
                    ((d.tile_m % 16'(TCU_V2_ARRAY_M)) == 16'd0) &&
                    ((d.tile_n % 16'(TCU_V2_ARRAY_N)) == 16'd0) &&
                    ((d.tile_k % 16'(TCU_V2_ARRAY_K)) == 16'd0);
        if (tcu_v2_fmt_is_mx(d.fmt_a) || tcu_v2_fmt_is_mx(d.fmt_b)) begin
            scale_ok = (d.scale_fmt != TCU_V2_SCALE_NONE);
        end else begin
            scale_ok = (d.scale_fmt == TCU_V2_SCALE_NONE);
        end
        return fmt_ok && bounds_ok && dim_ok && scale_ok;
    endfunction

    tcu_v2_wgmma_desc_t [DESC_DEPTH-1:0] ref_fifo_q;
    logic [$clog2(DESC_DEPTH)-1:0]       ref_wptr_q, ref_rptr_q;
    logic [CNT_W-1:0]                    ref_cnt_q;
    logic [31:0]                         ref_acc_q, ref_rej_q, ref_flu_q;
    logic                                ref_rej_pulse_q;
    logic [TCU_V2_DESC_ID_W-1:0]         ref_rej_id_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            ref_fifo_q      <= '0;
            ref_wptr_q      <= '0;
            ref_rptr_q      <= '0;
            ref_cnt_q       <= '0;
            ref_acc_q       <= 32'd0;
            ref_rej_q       <= 32'd0;
            ref_flu_q       <= 32'd0;
            ref_rej_pulse_q <= 1'b0;
            ref_rej_id_q    <= '0;
        end else if (sym_q_flush) begin
            ref_wptr_q      <= '0;
            ref_rptr_q      <= '0;
            ref_cnt_q       <= '0;
            ref_rej_pulse_q <= 1'b0;
            ref_flu_q       <= ref_flu_q + 32'(ref_cnt_q);
        end else begin
            logic legal_in;
            logic do_push;
            logic do_pop;
            legal_in        = ref_desc_acceptable(sym_q_enq_desc);
            do_push         = sym_q_enq_valid && q_enq_ready && legal_in;
            do_pop          = q_deq_valid && sym_q_deq_ready;
            ref_rej_pulse_q <= 1'b0;

            if (sym_q_enq_valid && q_enq_ready && !legal_in) begin
                ref_rej_pulse_q <= 1'b1;
                ref_rej_id_q    <= sym_q_enq_desc.desc_id;
                ref_rej_q       <= ref_rej_q + 32'd1;
            end
            if (do_push) begin
                ref_fifo_q[ref_wptr_q] <= sym_q_enq_desc;
                ref_wptr_q             <= ref_wptr_q + 1'b1;
                ref_acc_q              <= ref_acc_q + 32'd1;
            end
            if (do_pop) begin
                ref_rptr_q <= ref_rptr_q + 1'b1;
            end
            case ({do_push, do_pop})
                2'b10:   ref_cnt_q <= ref_cnt_q + CNT_W'(1);
                2'b01:   ref_cnt_q <= ref_cnt_q - CNT_W'(1);
                default: ref_cnt_q <= ref_cnt_q;
            endcase
        end
    end

    // -------------------------------------------------------------------------
    // 2. Hardware Barrier Unit DUT + Phase Tracking
    // -------------------------------------------------------------------------
    logic                           bar_cmd_ready;
    logic                           bar_wait_pass;
    logic                           bar_wakeup_valid;
    logic [TCU_V2_BARRIER_ID_W-1:0] bar_wakeup_id;
    logic                           bar_wakeup_phase;
    logic                           bar_status_valid;
    logic                           bar_status_phase;
    logic [15:0]                    bar_status_arr;
    logic [15:0]                    bar_status_tx;
    logic [NUM_BARRIERS-1:0]        bar_active_mask;
    logic [NUM_BARRIERS-1:0]        bar_phase_vec;
    logic                           bar_stall;
    logic [31:0]                    bar_flips_cnt;
    logic [31:0]                    bar_stall_cycles;

    logic [1:0]                     bar_cmd_id_bounded;
    logic [1:0]                     bar_wait_id_bounded;
    assign bar_cmd_id_bounded  = sym_bar_cmd_id[1:0];
    assign bar_wait_id_bounded = sym_bar_wait_id[1:0];

    VX_tcu_v2_barrier_unit #(
        .NUM_BARRIERS (NUM_BARRIERS)
    ) u_barrier_dut (
        .clk                   (clk),
        .reset                 (reset),
        .cmd_valid             (sym_bar_cmd_valid),
        .cmd_ready             (bar_cmd_ready),
        .cmd_op                (sym_bar_cmd_op),
        .cmd_bar_id            ({2'b00, bar_cmd_id_bounded}),
        .cmd_count             (sym_bar_cmd_count),
        .cmd_phase             (sym_bar_cmd_phase),
        .wait_valid            (sym_bar_wait_valid),
        .wait_bar_id           ({2'b00, bar_wait_id_bounded}),
        .wait_phase            (sym_bar_wait_phase),
        .wait_pass_out         (bar_wait_pass),
        .wakeup_valid_out      (bar_wakeup_valid),
        .wakeup_bar_id_out     (bar_wakeup_id),
        .wakeup_phase_out      (bar_wakeup_phase),
        .status_bar_id         ({2'b00, bar_cmd_id_bounded}),
        .status_valid_out      (bar_status_valid),
        .status_phase_out      (bar_status_phase),
        .status_arrive_rem_out (bar_status_arr),
        .status_tx_rem_out     (bar_status_tx),
        .bar_active_mask_out   (bar_active_mask),
        .bar_phase_vec_out     (bar_phase_vec),
        .bar_stall_out         (bar_stall),
        .phase_flips_cnt_out   (bar_flips_cnt),
        .wait_stall_cycles_out (bar_stall_cycles)
    );

    // Shadow state for barrier slot 0 phase toggle verification
    logic        bar0_init_q;
    logic        bar0_phase_q;
    logic [15:0] bar0_arr_init_q;
    logic [15:0] bar0_arr_rem_q;
    logic [15:0] bar0_tx_rem_q;
    logic        bar0_expect_flip_q;
    logic        bar0_expected_new_phase_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            bar0_init_q               <= 1'b0;
            bar0_phase_q              <= 1'b0;
            bar0_arr_init_q           <= 16'd0;
            bar0_arr_rem_q            <= 16'd0;
            bar0_tx_rem_q             <= 16'd0;
            bar0_expect_flip_q        <= 1'b0;
            bar0_expected_new_phase_q <= 1'b0;
        end else begin
            bar0_expect_flip_q <= 1'b0;
            if (sym_bar_cmd_valid && bar_cmd_ready && (bar_cmd_id_bounded == 2'd0)) begin
                if (sym_bar_cmd_op == 3'd1) begin
                    bar0_init_q     <= 1'b1;
                    bar0_phase_q    <= sym_bar_cmd_phase;
                    bar0_arr_init_q <= (sym_bar_cmd_count == 16'd0) ? 16'd1 : sym_bar_cmd_count;
                    bar0_arr_rem_q  <= (sym_bar_cmd_count == 16'd0) ? 16'd1 : sym_bar_cmd_count;
                    bar0_tx_rem_q   <= 16'd0;
                end else if ((sym_bar_cmd_op == 3'd2) && bar0_init_q) begin
                    logic [15:0] dec;
                    logic [15:0] next_arr;
                    dec      = (sym_bar_cmd_count == 16'd0) ? 16'd1 : sym_bar_cmd_count;
                    next_arr = (dec >= bar0_arr_rem_q) ? 16'd0 : (bar0_arr_rem_q - dec);
                    if ((next_arr == 16'd0) && (bar0_tx_rem_q == 16'd0)) begin
                        bar0_phase_q              <= !bar0_phase_q;
                        bar0_arr_rem_q            <= bar0_arr_init_q;
                        bar0_expect_flip_q        <= 1'b1;
                        bar0_expected_new_phase_q <= !bar0_phase_q;
                    end else begin
                        bar0_arr_rem_q <= next_arr;
                    end
                end else if ((sym_bar_cmd_op == 3'd3) && bar0_init_q) begin
                    bar0_tx_rem_q <= bar0_tx_rem_q + sym_bar_cmd_count;
                end else if ((sym_bar_cmd_op == 3'd4) && bar0_init_q) begin
                    logic [15:0] next_tx;
                    next_tx = (sym_bar_cmd_count >= bar0_tx_rem_q) ? 16'd0 : (bar0_tx_rem_q - sym_bar_cmd_count);
                    if ((bar0_arr_rem_q == 16'd0) && (next_tx == 16'd0)) begin
                        bar0_phase_q              <= !bar0_phase_q;
                        bar0_arr_rem_q            <= bar0_arr_init_q;
                        bar0_expect_flip_q        <= 1'b1;
                        bar0_expected_new_phase_q <= !bar0_phase_q;
                    end else begin
                        bar0_tx_rem_q <= next_tx;
                    end
                end else if (sym_bar_cmd_op == 3'd5) begin
                    bar0_init_q     <= 1'b0;
                    bar0_phase_q    <= 1'b0;
                    bar0_arr_init_q <= 16'd0;
                    bar0_arr_rem_q  <= 16'd0;
                    bar0_tx_rem_q   <= 16'd0;
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // 3. Cross-Coupled 2-CTA Peer Sync Pair (CTA 0 <-> CTA 1)
    // -------------------------------------------------------------------------
    logic                           cta0_req_ready, cta1_req_ready;
    logic                           cta0_exec_open, cta1_exec_open;
    logic                           cta0_m_half, cta1_m_half;
    logic                           cta0_n_half, cta1_n_half;
    logic                           cta0_busy, cta1_busy;
    logic                           cta0_stall, cta1_stall;
    logic                           cta0_wdt, cta1_wdt;
    logic [31:0]                    cta0_pair_cnt, cta1_pair_cnt;

    logic                           cta0_to_1_valid, cta0_to_1_ready;
    logic [TCU_V2_BARRIER_ID_W-1:0] cta0_to_1_bar_id;
    logic                           cta0_to_1_phase;

    logic                           cta1_to_0_valid, cta1_to_0_ready;
    logic [TCU_V2_BARRIER_ID_W-1:0] cta1_to_0_bar_id;
    logic                           cta1_to_0_phase;

    VX_tcu_v2_cta_pair_sync #(
        .WATCHDOG_LIMIT (WATCHDOG_LIM)
    ) u_cta0_dut (
        .clk                  (clk),
        .reset                (reset),
        .req_valid            (sym_cta0_req_valid),
        .req_ready            (cta0_req_ready),
        .cta_pair_en          (sym_cta_pair_en),
        .split_n_mode         (sym_cta_split_n),
        .local_cta_rank       (1'b0),
        .desc_id_in           (8'h10),
        .bar_id_in            (sym_cta_bar_id),
        .phase_in             (sym_cta_phase),
        .peer_done_release    (sym_cta0_release),
        .exec_gate_open_out   (cta0_exec_open),
        .exec_m_half_sel_out  (cta0_m_half),
        .exec_n_half_sel_out  (cta0_n_half),
        .sync_busy_out        (cta0_busy),
        .sync_stall_out       (cta0_stall),
        .watchdog_timeout_out (cta0_wdt),
        .watchdog_clear       (1'b0),
        .cta_sync_out_valid   (cta0_to_1_valid),
        .cta_sync_out_ready   (cta0_to_1_ready),
        .cta_sync_out_bar_id  (cta0_to_1_bar_id),
        .cta_sync_out_phase   (cta0_to_1_phase),
        .cta_sync_in_valid    (cta1_to_0_valid),
        .cta_sync_in_ready    (cta1_to_0_ready),
        .cta_sync_in_bar_id   (cta1_to_0_bar_id),
        .cta_sync_in_phase    (cta1_to_0_phase),
        .pair_sync_count_out  (cta0_pair_cnt),
        .sync_wait_cycles_out ()
    );

    VX_tcu_v2_cta_pair_sync #(
        .WATCHDOG_LIMIT (WATCHDOG_LIM)
    ) u_cta1_dut (
        .clk                  (clk),
        .reset                (reset),
        .req_valid            (sym_cta1_req_valid),
        .req_ready            (cta1_req_ready),
        .cta_pair_en          (sym_cta_pair_en),
        .split_n_mode         (sym_cta_split_n),
        .local_cta_rank       (1'b1),
        .desc_id_in           (8'h11),
        .bar_id_in            (sym_cta_bar_id),
        .phase_in             (sym_cta_phase),
        .peer_done_release    (sym_cta1_release),
        .exec_gate_open_out   (cta1_exec_open),
        .exec_m_half_sel_out  (cta1_m_half),
        .exec_n_half_sel_out  (cta1_n_half),
        .sync_busy_out        (cta1_busy),
        .sync_stall_out       (cta1_stall),
        .watchdog_timeout_out (cta1_wdt),
        .watchdog_clear       (1'b0),
        .cta_sync_out_valid   (cta1_to_0_valid),
        .cta_sync_out_ready   (cta1_to_0_ready),
        .cta_sync_out_bar_id  (cta1_to_0_bar_id),
        .cta_sync_out_phase   (cta1_to_0_phase),
        .cta_sync_in_valid    (cta0_to_1_valid),
        .cta_sync_in_ready    (cta0_to_1_ready),
        .cta_sync_in_bar_id   (cta0_to_1_bar_id),
        .cta_sync_in_phase    (cta0_to_1_phase),
        .pair_sync_count_out  (cta1_pair_cnt),
        .sync_wait_cycles_out ()
    );

    logic [31:0] prev_cta0_pair_cnt_q, prev_cta1_pair_cnt_q;
    logic        cta_both_entered_pair_q;
    logic        cta0_lat_pair_q, cta1_lat_pair_q;
    logic        cta0_lat_split_n_q, cta1_lat_split_n_q;
    logic [4:0]  cta_pair_wait_cyc_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            prev_cta0_pair_cnt_q    <= 32'd0;
            prev_cta1_pair_cnt_q    <= 32'd0;
            cta_both_entered_pair_q <= 1'b0;
            cta0_lat_pair_q         <= 1'b0;
            cta1_lat_pair_q         <= 1'b0;
            cta0_lat_split_n_q      <= 1'b0;
            cta1_lat_split_n_q      <= 1'b0;
            cta_pair_wait_cyc_q     <= 5'd0;
        end else begin
            prev_cta0_pair_cnt_q <= cta0_pair_cnt;
            prev_cta1_pair_cnt_q <= cta1_pair_cnt;
            if (sym_cta0_req_valid && cta0_req_ready) begin
                cta0_lat_pair_q    <= sym_cta_pair_en;
                cta0_lat_split_n_q <= sym_cta_split_n;
            end
            if (sym_cta1_req_valid && cta1_req_ready) begin
                cta1_lat_pair_q    <= sym_cta_pair_en;
                cta1_lat_split_n_q <= sym_cta_split_n;
            end
            if (sym_cta0_req_valid && cta0_req_ready &&
                sym_cta1_req_valid && cta1_req_ready && sym_cta_pair_en) begin
                cta_both_entered_pair_q <= 1'b1;
                cta_pair_wait_cyc_q     <= 5'd0;
            end else if (cta_both_entered_pair_q) begin
                if (cta0_exec_open && cta1_exec_open) begin
                    cta_both_entered_pair_q <= 1'b0;
                    cta_pair_wait_cyc_q     <= 5'd0;
                end else if (cta_pair_wait_cyc_q != 5'd31) begin
                    cta_pair_wait_cyc_q <= cta_pair_wait_cyc_q + 5'd1;
                end
            end
        end
    end

    assign formal_ok_out = !cta0_wdt && !cta1_wdt && !q_full;

    // -------------------------------------------------------------------------
    // Bounded Formal Proofs (`t=12..16` cycles) & Reachability Covers
    // -------------------------------------------------------------------------
`ifdef FORMAL
    reg [7:0] f_cyc_q;
    initial f_cyc_q = 8'd0;

    always_comb begin
        assume (reset == (f_cyc_q < 8'd2));
    end

    always @(posedge clk) begin
        f_cyc_q <= f_cyc_q + 8'd1;

        if (!reset && (f_cyc_q >= 8'd2)) begin
            // 1. WGMMA Descriptor Queue Invariants
            assert (q_occupancy <= CNT_W'(DESC_DEPTH));
            assert ((q_occupancy + q_credits) == CNT_W'(DESC_DEPTH));
            assert (q_empty == (q_occupancy == '0));
            assert (q_full == (q_occupancy == CNT_W'(DESC_DEPTH)));
            assert (!(q_empty && q_full));
            assert (q_deq_valid == !q_empty);
            assert (q_peek_valid == q_deq_valid);
            assert (q_peek_desc == q_deq_desc);

            // Exact match against shadow FIFO model (proves illegal descriptors never corrupt queue)
            assert (q_occupancy == ref_cnt_q);
            assert (q_acc_cnt == ref_acc_q);
            assert (q_rej_cnt == ref_rej_q);
            assert (q_flu_cnt == ref_flu_q);
            assert (q_reject_pulse == ref_rej_pulse_q);
            if (q_reject_pulse) begin
                assert (q_reject_id == ref_rej_id_q);
            end
            if (!q_empty) begin
                assert (q_deq_desc == ref_fifo_q[ref_rptr_q]);
            end

            // 2. Barrier Unit Invariants
            assert (bar_active_mask[0] == bar0_init_q);
            assert (bar_phase_vec[0] == bar0_phase_q);
            if (bar_cmd_id_bounded == 2'd0) begin
                assert (bar_status_valid == bar0_init_q);
                assert (bar_status_phase == bar0_phase_q);
                assert (bar_status_arr == bar0_arr_rem_q);
                assert (bar_status_tx == bar0_tx_rem_q);
            end
            if (bar0_expect_flip_q) begin
                assert (bar_wakeup_valid);
                assert (bar_wakeup_id == 4'd0);
                assert (bar_wakeup_phase == bar0_expected_new_phase_q);
            end
            assert (bar_stall == (sym_bar_wait_valid && !bar_wait_pass));

            // 3. 2-CTA Peer Sync Invariants
            assert (cta0_pair_cnt >= prev_cta0_pair_cnt_q);
            assert (cta1_pair_cnt >= prev_cta1_pair_cnt_q);
            // Exclusive half selection in paired mode
            if (cta0_exec_open && cta1_exec_open &&
                cta0_lat_pair_q && cta1_lat_pair_q &&
                (cta0_lat_split_n_q == cta1_lat_split_n_q)) begin
                if (!cta0_lat_split_n_q) begin
                    assert (cta0_m_half != cta1_m_half);
                end else begin
                    assert (cta0_n_half != cta1_n_half);
                end
            end
            // If both CTAs entered paired sync simultaneously, neither deadlocks or times out
            if (cta_both_entered_pair_q) begin
                assert (!cta0_wdt && !cta1_wdt);
                assert (cta_pair_wait_cyc_q <= 5'd3);
            end

            // --- Reachability Covers ---
            cover (q_full && (q_acc_cnt >= 32'(DESC_DEPTH)));
            cover (q_reject_pulse && (q_rej_cnt >= 32'd1) && (q_occupancy == ref_cnt_q));
            cover ((q_flu_cnt > 32'd0) && q_empty);
            cover (bar_wakeup_valid && (bar_flips_cnt >= 32'd1));
            cover (bar_wakeup_valid && (bar_flips_cnt >= 32'd2));
            cover (cta0_exec_open && cta1_exec_open && (cta0_pair_cnt >= 32'd1) && (cta1_pair_cnt >= 32'd1));
            cover (!cta0_busy && !cta1_busy && (cta0_pair_cnt >= 32'd1) && (cta1_pair_cnt >= 32'd1));
        end
    end
`endif

endmodule
