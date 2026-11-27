// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_formal_sparse_legality
    import VX_tcu_v2_pkg::*;
#(
    parameter int ARRAY_M = 2,
    parameter int ARRAY_K = 2
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Symbolic inputs for validator standalone proof
    input  logic                                    sym_val_valid,
    input  logic                                    sym_val_sparse_en,
    input  tcu_v2_fmt_e                             sym_val_fmt,
    input  logic [TCU_V2_DESC_ID_W-1:0]             sym_val_desc_id,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]      sym_val_meta,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      sym_val_a_tile,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      sym_val_a_cand,
    input  logic                                    sym_val_fault_clear,
    // Symbolic inputs for compressor -> validator -> selector roundtrip chain
    input  logic                                    sym_comp_valid,
    input  tcu_v2_fmt_e                             sym_comp_fmt,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      sym_dense_lo,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]      sym_dense_hi,
    input  logic                                    sym_sel_fault_suppress,
    output logic                                    formal_ok_out
);

    localparam int GROUPS_PER_ROW = ARRAY_K * 4;

    // -------------------------------------------------------------------------
    // 1. Standalone Sparse Validator DUT (tests arbitrary unconstrained metadata)
    // -------------------------------------------------------------------------
    logic                               val_valid_out;
    logic                               val_fault_det;
    logic                               val_fault_sticky;
    logic                               val_fmt_illegal;
    logic [ARRAY_M-1:0][ARRAY_K*4-1:0]  val_err_mask;
    logic [TCU_V2_DESC_ID_W-1:0]        val_desc_id_out;
    logic [7:0]                         val_syn_row;
    logic [7:0]                         val_syn_grp;
    tcu_v2_sparse_meta4_t               val_syn_meta;
    logic [TCU_V2_DESC_ID_W-1:0]        val_syn_desc_id;
    logic [3:0]                         val_syn_code;
    logic [15:0]                        val_chk_tiles;
    logic [15:0]                        val_flt_events;

    VX_tcu_v2_sparse_validator #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_val_standalone (
        .clk                   (clk),
        .reset                 (reset),
        .valid_in              (sym_val_valid),
        .sparse_en             (sym_val_sparse_en),
        .fmt_a                 (sym_val_fmt),
        .desc_id_in            (sym_val_desc_id),
        .sparse_meta_in        (sym_val_meta),
        .a_tile_in             (sym_val_a_tile),
        .a_sparse_cand_in      (sym_val_a_cand),
        .fault_clear           (sym_val_fault_clear),
        .comp_meta_valid       (1'b0),
        .comp_meta_in          ('0),
        .val_valid_out         (val_valid_out),
        .fault_detected_out    (val_fault_det),
        .fault_sticky_out      (val_fault_sticky),
        .fmt_illegal_out       (val_fmt_illegal),
        .group_err_mask_out    (val_err_mask),
        .val_desc_id_out       (val_desc_id_out),
        .syndrome_row_out      (val_syn_row),
        .syndrome_group_out    (val_syn_grp),
        .syndrome_meta_out     (val_syn_meta),
        .syndrome_desc_id_out  (val_syn_desc_id),
        .syndrome_code_out     (val_syn_code),
        .checked_tiles_out     (val_chk_tiles),
        .fault_events_out      (val_flt_events),
        .comp_mismatch_cnt_out ()
    );

    // -------------------------------------------------------------------------
    // 2. Pipeline Chain: Compressor -> Validator -> Selector
    // -------------------------------------------------------------------------
    logic                               comp_ready_in;
    logic                               comp_valid_out;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] comp_data_out;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] comp_meta_out;
    logic                               comp_prune_loss;
    logic [15:0]                        comp_pruned_grps;
    logic [15:0]                        comp_exact_grps;

    VX_tcu_v2_sparse_compressor #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_compressor (
        .clk                  (clk),
        .reset                (reset),
        .valid_in             (sym_comp_valid),
        .ready_in             (comp_ready_in),
        .fmt_a                (sym_comp_fmt),
        .dense_lo_in          (sym_dense_lo),
        .dense_hi_in          (sym_dense_hi),
        .valid_out            (comp_valid_out),
        .ready_out            (1'b1),
        .compressed_out       (comp_data_out),
        .meta_out             (comp_meta_out),
        .prune_loss_out       (comp_prune_loss),
        .pruned_groups_out    (comp_pruned_grps),
        .exact_2_4_groups_out (comp_exact_grps)
    );

    // Latch compressor inputs alongside 1-cycle compressor output for exact validator/selector pairing
    logic                               comp_in_fire_w;
    tcu_v2_fmt_e                        lat_comp_fmt_q;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] lat_dense_lo_q;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] lat_dense_hi_q;

    assign comp_in_fire_w = sym_comp_valid && comp_ready_in;

    always_ff @(posedge clk) begin
        if (reset) begin
            lat_comp_fmt_q <= TCU_V2_FMT_FP16;
            lat_dense_lo_q <= '0;
            lat_dense_hi_q <= '0;
        end else if (comp_in_fire_w) begin
            lat_comp_fmt_q <= sym_comp_fmt;
            lat_dense_lo_q <= sym_dense_lo;
            lat_dense_hi_q <= sym_dense_hi;
        end
    end

    logic                               chain_val_valid;
    logic                               chain_val_fault;
    logic                               chain_val_fmt_illegal;
    logic [ARRAY_M-1:0][ARRAY_K*4-1:0]  chain_val_err_mask;
    tcu_v2_fmt_e                        val_lat_fmt_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            val_lat_fmt_q <= TCU_V2_FMT_FP16;
        end else if (comp_valid_out) begin
            val_lat_fmt_q <= lat_comp_fmt_q;
        end
    end

    VX_tcu_v2_sparse_validator #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_val_from_comp (
        .clk                   (clk),
        .reset                 (reset),
        .valid_in              (comp_valid_out),
        .sparse_en             (1'b1),
        .fmt_a                 (lat_comp_fmt_q),
        .desc_id_in            (8'hA5),
        .sparse_meta_in        (comp_meta_out),
        .a_tile_in             (lat_dense_lo_q),
        .a_sparse_cand_in      (lat_dense_hi_q),
        .fault_clear           (1'b0),
        .comp_meta_valid       (1'b1),
        .comp_meta_in          (comp_meta_out),
        .val_valid_out         (chain_val_valid),
        .fault_detected_out    (chain_val_fault),
        .fault_sticky_out      (),
        .fmt_illegal_out       (chain_val_fmt_illegal),
        .group_err_mask_out    (chain_val_err_mask),
        .val_desc_id_out       (),
        .syndrome_row_out      (),
        .syndrome_group_out    (),
        .syndrome_meta_out     (),
        .syndrome_desc_id_out  (),
        .syndrome_code_out     (),
        .checked_tiles_out     (),
        .fault_events_out      (),
        .comp_mismatch_cnt_out ()
    );

    logic                               sel_ready_in;
    logic                               sel_valid_out;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] sel_a_out;
    logic                               sel_fault_masked;
    logic [15:0]                        sel_active_lanes;

    VX_tcu_v2_sparse_selector #(
        .ARRAY_M (ARRAY_M),
        .ARRAY_K (ARRAY_K)
    ) u_selector_from_comp (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (comp_valid_out),
        .ready_in          (sel_ready_in),
        .sparse_en         (1'b1),
        .fault_suppress    (sym_sel_fault_suppress),
        .fmt_a             (lat_comp_fmt_q),
        .a_tile_in         (lat_dense_lo_q),
        .a_sparse_cand_in  (lat_dense_hi_q),
        .sparse_meta_in    (comp_meta_out),
        .group_err_mask_in ('0),
        .valid_out         (sel_valid_out),
        .ready_out         (1'b1),
        .a_selected_out    (sel_a_out),
        .fault_masked_out  (sel_fault_masked),
        .active_lanes_out  (sel_active_lanes)
    );

    // Latch compressor outputs 1 cycle to align with selector's registered output
    tcu_v2_fmt_e                        sel_lat_fmt_q;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] sel_lat_lo_q;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] sel_lat_hi_q;
    logic [ARRAY_M-1:0][ARRAY_K*32-1:0] sel_lat_comp_q;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] sel_lat_meta_q;
    logic                               sel_lat_prune_loss_q;
    logic                               sel_lat_suppress_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            sel_lat_fmt_q        <= TCU_V2_FMT_FP16;
            sel_lat_lo_q         <= '0;
            sel_lat_hi_q         <= '0;
            sel_lat_comp_q       <= '0;
            sel_lat_meta_q       <= '0;
            sel_lat_prune_loss_q <= 1'b0;
            sel_lat_suppress_q   <= 1'b0;
        end else if (comp_valid_out && sel_ready_in) begin
            sel_lat_fmt_q        <= lat_comp_fmt_q;
            sel_lat_lo_q         <= lat_dense_lo_q;
            sel_lat_hi_q         <= lat_dense_hi_q;
            sel_lat_comp_q       <= comp_data_out;
            sel_lat_meta_q       <= comp_meta_out;
            sel_lat_prune_loss_q <= comp_prune_loss;
            sel_lat_suppress_q   <= sym_sel_fault_suppress;
        end
    end

    // Reference combinational expectations for standalone validator (1-cycle pipeline alignment)
    function automatic logic ref_fmt_sparse_ok(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8:       return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic [GROUPS_PER_ROW-1:0] ref_active_groups(
        input tcu_v2_fmt_e fmt
    );
        logic [GROUPS_PER_ROW-1:0] mask;
        mask = '0;
        case (fmt)
            TCU_V2_FMT_TF32: begin
                for (int g = 0; g < (ARRAY_K / 2); ++g) begin
                    mask[g] = 1'b1;
                end
            end
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16: begin
                for (int g = 0; g < ARRAY_K; ++g) begin
                    mask[g] = 1'b1;
                end
            end
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8: begin
                for (int g = 0; g < (ARRAY_K * 2); ++g) begin
                    mask[g] = 1'b1;
                end
            end
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: begin
                mask = {GROUPS_PER_ROW{1'b1}};
            end
            default: mask = '0;
        endcase
        return mask;
    endfunction

    logic                               ref_val_exp_fault_q;
    logic                               ref_val_exp_fmt_ill_q;
    logic [ARRAY_M-1:0][ARRAY_K*4-1:0]  ref_val_exp_err_mask_q;
    logic                               ref_val_sticky_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            ref_val_exp_fault_q    <= 1'b0;
            ref_val_exp_fmt_ill_q  <= 1'b0;
            ref_val_exp_err_mask_q <= '0;
            ref_val_sticky_q       <= 1'b0;
        end else begin
            logic                               exp_ill;
            logic [ARRAY_M-1:0][ARRAY_K*4-1:0]  exp_mask;
            logic [GROUPS_PER_ROW-1:0]          act_grps;
            logic                               exp_flt;

            exp_ill  = sym_val_valid && sym_val_sparse_en && !ref_fmt_sparse_ok(sym_val_fmt);
            act_grps = ref_active_groups(sym_val_fmt);
            exp_mask = '0;
            for (int m = 0; m < ARRAY_M; ++m) begin
                for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                    tcu_v2_sparse_meta4_t pm;
                    pm = tcu_v2_sparse_meta4_t'(sym_val_meta[m][g*4 +: 4]);
                    if (sym_val_valid && sym_val_sparse_en && act_grps[g] && !(pm.idx0 < pm.idx1)) begin
                        exp_mask[m][g] = 1'b1;
                    end
                end
            end
            exp_flt = sym_val_valid && sym_val_sparse_en && (exp_ill || (exp_mask != '0));

            ref_val_exp_fmt_ill_q  <= exp_ill;
            ref_val_exp_err_mask_q <= exp_mask;
            ref_val_exp_fault_q    <= exp_flt;
            if (sym_val_fault_clear) begin
                ref_val_sticky_q <= exp_flt;
            end else if (exp_flt) begin
                ref_val_sticky_q <= 1'b1;
            end
        end
    end

    assign formal_ok_out = !val_fault_det && !chain_val_fault && !sel_fault_masked;

    // -------------------------------------------------------------------------
    // Formal Invariants & Reachability Covers
    // -------------------------------------------------------------------------
`ifdef FORMAL
    reg [7:0] f_cyc_q;
    reg       f_past_valid_q;
    initial f_cyc_q        = 8'd0;
    initial f_past_valid_q = 1'b0;

    always_comb begin
        assume (reset == (f_cyc_q < 8'd2));
    end

    always @(posedge clk) begin
        f_cyc_q <= f_cyc_q + 8'd1;
        if (reset) begin
            f_past_valid_q <= 1'b1;
        end else if (f_past_valid_q) begin
            // 1. Standalone validator accepts iff idx0 < idx1 across every active group and fmt is legal
            assert (val_fmt_illegal == ref_val_exp_fmt_ill_q);
            assert (val_err_mask == ref_val_exp_err_mask_q);
            assert (val_fault_det == ref_val_exp_fault_q);
            assert (val_fault_sticky == ref_val_sticky_q);
            if (val_valid_out && !val_fmt_illegal) begin
                assert (!val_fault_det == (val_err_mask == '0));
            end

            // 2. Compressor ALWAYS produces metadata accepted by validator for any sparse-capable format
            if (chain_val_valid && ref_fmt_sparse_ok(val_lat_fmt_q)) begin
                assert (!chain_val_fmt_illegal);
                assert (!chain_val_fault);
                assert (chain_val_err_mask == '0);
            end

            // 3. Exact 2:4 recovery across compressor -> selector for ANY 4-element input with <= 2 non-zeros
            if (sel_valid_out && !sel_lat_suppress_q) begin
                assert (!sel_fault_masked);
                if (sel_lat_fmt_q == TCU_V2_FMT_FP16) begin
                    // Check every group (m, k) of 4 x 16-bit elements
                    for (int m = 0; m < ARRAY_M; ++m) begin
                        for (int k = 0; k < ARRAY_K; ++k) begin
                            logic [3:0][15:0] elems;
                            logic [2:0]       nz_cnt;
                            logic [15:0]      sel0, sel1;
                            tcu_v2_sparse_meta4_t pm;
                            elems[0] = sel_lat_lo_q[m][k*32 +: 16];
                            elems[1] = sel_lat_lo_q[m][k*32 + 16 +: 16];
                            elems[2] = sel_lat_hi_q[m][k*32 +: 16];
                            elems[3] = sel_lat_hi_q[m][k*32 + 16 +: 16];
                            pm       = tcu_v2_sparse_meta4_t'(sel_lat_meta_q[m][k*4 +: 4]);
                            sel0     = sel_a_out[m][k*32 +: 16];
                            sel1     = sel_a_out[m][k*32 + 16 +: 16];

                            // Ascending index order invariant
                            assert (pm.idx0 < pm.idx1);
                            // Selector matches compressor output
                            assert (sel0 == sel_lat_comp_q[m][k*32 +: 16]);
                            assert (sel1 == sel_lat_comp_q[m][k*32 + 16 +: 16]);
                            assert (sel0 == elems[pm.idx0]);
                            assert (sel1 == elems[pm.idx1]);

                            // Count non-zero FP16 elements (exp/man != 0)
                            nz_cnt = 3'd0;
                            for (int e = 0; e < 4; ++e) begin
                                if (elems[e][14:0] != 15'd0) begin
                                    nz_cnt = nz_cnt + 3'd1;
                                end
                            end

                            // If <= 2 non-zeros, every non-zero element is preserved in ascending order
                            if (nz_cnt <= 3'd2) begin
                                if ((elems[0][14:0] != 15'd0)) begin
                                    assert ((sel0 == elems[0]) || (sel1 == elems[0]));
                                end
                                if ((elems[1][14:0] != 15'd0)) begin
                                    assert ((sel0 == elems[1]) || (sel1 == elems[1]));
                                end
                                if ((elems[2][14:0] != 15'd0)) begin
                                    assert ((sel0 == elems[2]) || (sel1 == elems[2]));
                                end
                                if ((elems[3][14:0] != 15'd0)) begin
                                    assert ((sel0 == elems[3]) || (sel1 == elems[3]));
                                end
                            end
                        end
                    end
                end else if (sel_lat_fmt_q == TCU_V2_FMT_MXFP4_E2M1) begin
                    // Check every group (m, k, q) of 4 x 4-bit FP4 nibbles (8 nibbles/word)
                    for (int m = 0; m < ARRAY_M; ++m) begin
                        for (int k = 0; k < ARRAY_K; ++k) begin
                            for (int q = 0; q < 4; ++q) begin
                                logic [3:0][3:0] elems;
                                logic [2:0]      nz_cnt;
                                logic [3:0]      sel0, sel1;
                                tcu_v2_sparse_meta4_t pm;
                                int grp_idx;
                                grp_idx  = 4 * k + q;
                                elems[0] = sel_lat_lo_q[m][k*32 + q*8 +: 4];
                                elems[1] = sel_lat_lo_q[m][k*32 + q*8 + 4 +: 4];
                                elems[2] = sel_lat_hi_q[m][k*32 + q*8 +: 4];
                                elems[3] = sel_lat_hi_q[m][k*32 + q*8 + 4 +: 4];
                                pm       = tcu_v2_sparse_meta4_t'(sel_lat_meta_q[m][grp_idx*4 +: 4]);
                                sel0     = sel_a_out[m][k*32 + q*8 +: 4];
                                sel1     = sel_a_out[m][k*32 + q*8 + 4 +: 4];

                                assert (pm.idx0 < pm.idx1);
                                assert (sel0 == sel_lat_comp_q[m][k*32 + q*8 +: 4]);
                                assert (sel1 == sel_lat_comp_q[m][k*32 + q*8 + 4 +: 4]);
                                assert (sel0 == elems[pm.idx0]);
                                assert (sel1 == elems[pm.idx1]);

                                nz_cnt = 3'd0;
                                for (int e = 0; e < 4; ++e) begin
                                    if (elems[e][2:0] != 3'd0) begin
                                        nz_cnt = nz_cnt + 3'd1;
                                    end
                                end
                                if (nz_cnt <= 3'd2) begin
                                    if (elems[0][2:0] != 3'd0) begin
                                        assert ((sel0 == elems[0]) || (sel1 == elems[0]));
                                    end
                                    if (elems[1][2:0] != 3'd0) begin
                                        assert ((sel0 == elems[1]) || (sel1 == elems[1]));
                                    end
                                    if (elems[2][2:0] != 3'd0) begin
                                        assert ((sel0 == elems[2]) || (sel1 == elems[2]));
                                    end
                                    if (elems[3][2:0] != 3'd0) begin
                                        assert ((sel0 == elems[3]) || (sel1 == elems[3]));
                                    end
                                end
                            end
                        end
                    end
                end
            end

            // --- Reachability Covers ---
            cover (val_valid_out && !val_fault_det && (val_chk_tiles > 16'd0));
            cover (val_valid_out && val_fault_det && (val_syn_code == 4'd1));
            cover (val_valid_out && val_fault_det && (val_syn_code == 4'd2));
            cover (val_valid_out && val_fault_det && val_fmt_illegal);
            cover (sel_valid_out && !sel_lat_suppress_q && !sel_lat_prune_loss_q &&
                   (sel_lat_fmt_q == TCU_V2_FMT_FP16) && (sel_a_out != '0));
            cover (sel_valid_out && !sel_lat_suppress_q && !sel_lat_prune_loss_q &&
                   (sel_lat_fmt_q == TCU_V2_FMT_MXFP4_E2M1) && (sel_a_out != '0));
            cover (sel_valid_out && sel_lat_prune_loss_q && (sel_lat_fmt_q == TCU_V2_FMT_FP16));
            cover (sel_valid_out && !sel_lat_suppress_q && (sel_lat_fmt_q == TCU_V2_FMT_INT8));
        end
    end
`endif

endmodule
