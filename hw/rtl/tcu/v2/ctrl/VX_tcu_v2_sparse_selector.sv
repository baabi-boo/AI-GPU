// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_sparse_selector #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            valid_in,
    output logic                                            ready_in,
    input  logic                                            sparse_en,
    input  logic                                            fault_suppress,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e                      fmt_a,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]              a_tile_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]              a_sparse_cand_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]              sparse_meta_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*4-1:0]               group_err_mask_in,
    output logic                                            valid_out,
    input  logic                                            ready_out,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]              a_selected_out,
    output logic                                            fault_masked_out,
    output logic [15:0]                                     active_lanes_out
);

    import VX_tcu_v2_pkg::*;

    localparam int GROUPS_PER_ROW = ARRAY_K * 4;
    localparam int ROW_BITS       = ARRAY_K * 32;

    function automatic logic [15:0] select_pair16(
        input logic [3:0][15:0]      cands,
        input tcu_v2_sparse_meta4_t  meta,
        input logic                  pick_hi,
        input logic                  suppress
    );
        logic [1:0] sel;
        if (suppress || !tcu_v2_sparse_pair_legal(meta)) begin
            return 16'd0;
        end
        sel = pick_hi ? meta.idx1 : meta.idx0;
        return cands[sel];
    endfunction

    function automatic logic [7:0] select_pair8(
        input logic [3:0][7:0]       cands,
        input tcu_v2_sparse_meta4_t  meta,
        input logic                  pick_hi,
        input logic                  suppress
    );
        logic [1:0] sel;
        if (suppress || !tcu_v2_sparse_pair_legal(meta)) begin
            return 8'd0;
        end
        sel = pick_hi ? meta.idx1 : meta.idx0;
        return cands[sel];
    endfunction

    function automatic logic [5:0] select_pair6(
        input logic [3:0][5:0]       cands,
        input tcu_v2_sparse_meta4_t  meta,
        input logic                  pick_hi,
        input logic                  suppress
    );
        logic [1:0] sel;
        if (suppress || !tcu_v2_sparse_pair_legal(meta)) begin
            return 6'd0;
        end
        sel = pick_hi ? meta.idx1 : meta.idx0;
        return cands[sel];
    endfunction

    function automatic logic [3:0] select_pair4(
        input logic [3:0][3:0]       cands,
        input tcu_v2_sparse_meta4_t  meta,
        input logic                  pick_hi,
        input logic                  suppress
    );
        logic [1:0] sel;
        if (suppress || !tcu_v2_sparse_pair_legal(meta)) begin
            return 4'd0;
        end
        sel = pick_hi ? meta.idx1 : meta.idx0;
        return cands[sel];
    endfunction

    function automatic logic [31:0] select_pair32(
        input logic [3:0][31:0]      cands,
        input tcu_v2_sparse_meta4_t  meta,
        input logic                  pick_hi,
        input logic                  suppress
    );
        logic [1:0] sel;
        if (suppress || !tcu_v2_sparse_pair_legal(meta)) begin
            return 32'd0;
        end
        sel = pick_hi ? meta.idx1 : meta.idx0;
        return cands[sel];
    endfunction

    function automatic logic [ROW_BITS-1:0] select_row_tf32(
        input logic [ROW_BITS-1:0]       row_lo,
        input logic [ROW_BITS-1:0]       row_hi,
        input logic [ARRAY_K*16-1:0]     row_meta,
        input logic [GROUPS_PER_ROW-1:0] row_err,
        input logic                      global_suppress
    );
        logic [ROW_BITS-1:0] res;
        res = '0;
        for (int g = 0; g < (ARRAY_K / 2); ++g) begin
            logic [3:0][31:0]     cands;
            tcu_v2_sparse_meta4_t meta;
            logic                 sup;
            cands[0] = row_lo[(2 * g) * 32 +: 32];
            cands[1] = row_lo[(2 * g + 1) * 32 +: 32];
            cands[2] = row_hi[(2 * g) * 32 +: 32];
            cands[3] = row_hi[(2 * g + 1) * 32 +: 32];
            meta     = tcu_v2_sparse_meta4_t'(row_meta[g*4 +: 4]);
            sup      = global_suppress || row_err[g];
            res[(2 * g) * 32 +: 32]     = select_pair32(cands, meta, 1'b0, sup);
            res[(2 * g + 1) * 32 +: 32] = select_pair32(cands, meta, 1'b1, sup);
        end
        return res;
    endfunction

    function automatic logic [ROW_BITS-1:0] select_row_16b(
        input logic [ROW_BITS-1:0]       row_lo,
        input logic [ROW_BITS-1:0]       row_hi,
        input logic [ARRAY_K*16-1:0]     row_meta,
        input logic [GROUPS_PER_ROW-1:0] row_err,
        input logic                      global_suppress
    );
        logic [ROW_BITS-1:0] res;
        res = '0;
        for (int k = 0; k < ARRAY_K; ++k) begin
            logic [3:0][15:0]     cands;
            tcu_v2_sparse_meta4_t meta;
            logic                 sup;
            cands[0] = row_lo[k*32 +: 16];
            cands[1] = row_lo[k*32 + 16 +: 16];
            cands[2] = row_hi[k*32 +: 16];
            cands[3] = row_hi[k*32 + 16 +: 16];
            meta     = tcu_v2_sparse_meta4_t'(row_meta[k*4 +: 4]);
            sup      = global_suppress || row_err[k];
            res[k*32 +: 16]      = select_pair16(cands, meta, 1'b0, sup);
            res[k*32 + 16 +: 16] = select_pair16(cands, meta, 1'b1, sup);
        end
        return res;
    endfunction

    function automatic logic [ROW_BITS-1:0] select_row_8b(
        input logic [ROW_BITS-1:0]       row_lo,
        input logic [ROW_BITS-1:0]       row_hi,
        input logic [ARRAY_K*16-1:0]     row_meta,
        input logic [GROUPS_PER_ROW-1:0] row_err,
        input logic                      global_suppress
    );
        logic [ROW_BITS-1:0] res;
        res = '0;
        for (int k = 0; k < ARRAY_K; ++k) begin
            logic [3:0][7:0]      cands_lo;
            logic [3:0][7:0]      cands_hi;
            tcu_v2_sparse_meta4_t meta_lo;
            tcu_v2_sparse_meta4_t meta_hi;
            logic                 sup_lo;
            logic                 sup_hi;
            int                   g_lo;
            int                   g_hi;

            g_lo = 2 * k;
            g_hi = 2 * k + 1;

            cands_lo[0] = row_lo[k*32 +: 8];
            cands_lo[1] = row_lo[k*32 + 8 +: 8];
            cands_lo[2] = row_hi[k*32 +: 8];
            cands_lo[3] = row_hi[k*32 + 8 +: 8];

            cands_hi[0] = row_lo[k*32 + 16 +: 8];
            cands_hi[1] = row_lo[k*32 + 24 +: 8];
            cands_hi[2] = row_hi[k*32 + 16 +: 8];
            cands_hi[3] = row_hi[k*32 + 24 +: 8];

            meta_lo = tcu_v2_sparse_meta4_t'(row_meta[g_lo*4 +: 4]);
            meta_hi = tcu_v2_sparse_meta4_t'(row_meta[g_hi*4 +: 4]);
            sup_lo  = global_suppress || row_err[g_lo];
            sup_hi  = global_suppress || row_err[g_hi];

            res[k*32 +: 8]      = select_pair8(cands_lo, meta_lo, 1'b0, sup_lo);
            res[k*32 + 8 +: 8]  = select_pair8(cands_lo, meta_lo, 1'b1, sup_lo);
            res[k*32 + 16 +: 8] = select_pair8(cands_hi, meta_hi, 1'b0, sup_hi);
            res[k*32 + 24 +: 8] = select_pair8(cands_hi, meta_hi, 1'b1, sup_hi);
        end
        return res;
    endfunction

    function automatic logic [ROW_BITS-1:0] select_row_6b(
        input logic [ROW_BITS-1:0]       row_lo,
        input logic [ROW_BITS-1:0]       row_hi,
        input logic [ARRAY_K*16-1:0]     row_meta,
        input logic [GROUPS_PER_ROW-1:0] row_err,
        input logic                      global_suppress
    );
        logic [ROW_BITS-1:0] res;
        res = '0;
        for (int k = 0; k < ARRAY_K; ++k) begin
            logic [3:0][5:0]      cands_lo;
            logic [3:0][5:0]      cands_hi;
            tcu_v2_sparse_meta4_t meta_lo;
            tcu_v2_sparse_meta4_t meta_hi;
            logic                 sup_lo;
            logic                 sup_hi;
            int                   g_lo;
            int                   g_hi;

            g_lo = 2 * k;
            g_hi = 2 * k + 1;

            cands_lo[0] = row_lo[k*32 +: 6];
            cands_lo[1] = row_lo[k*32 + 8 +: 6];
            cands_lo[2] = row_hi[k*32 +: 6];
            cands_lo[3] = row_hi[k*32 + 8 +: 6];

            cands_hi[0] = row_lo[k*32 + 16 +: 6];
            cands_hi[1] = row_lo[k*32 + 24 +: 6];
            cands_hi[2] = row_hi[k*32 + 16 +: 6];
            cands_hi[3] = row_hi[k*32 + 24 +: 6];

            meta_lo = tcu_v2_sparse_meta4_t'(row_meta[g_lo*4 +: 4]);
            meta_hi = tcu_v2_sparse_meta4_t'(row_meta[g_hi*4 +: 4]);
            sup_lo  = global_suppress || row_err[g_lo];
            sup_hi  = global_suppress || row_err[g_hi];

            res[k*32 +: 6]      = select_pair6(cands_lo, meta_lo, 1'b0, sup_lo);
            res[k*32 + 8 +: 6]  = select_pair6(cands_lo, meta_lo, 1'b1, sup_lo);
            res[k*32 + 16 +: 6] = select_pair6(cands_hi, meta_hi, 1'b0, sup_hi);
            res[k*32 + 24 +: 6] = select_pair6(cands_hi, meta_hi, 1'b1, sup_hi);
        end
        return res;
    endfunction

    function automatic logic [ROW_BITS-1:0] select_row_4b(
        input logic [ROW_BITS-1:0]       row_lo,
        input logic [ROW_BITS-1:0]       row_hi,
        input logic [ARRAY_K*16-1:0]     row_meta,
        input logic [GROUPS_PER_ROW-1:0] row_err,
        input logic                      global_suppress
    );
        logic [ROW_BITS-1:0] res;
        res = '0;
        for (int k = 0; k < ARRAY_K; ++k) begin
            for (int q = 0; q < 4; ++q) begin
                logic [3:0][3:0]      cands_q;
                tcu_v2_sparse_meta4_t meta_q;
                logic                 sup_q;
                int                   grp_idx;

                grp_idx    = 4 * k + q;
                cands_q[0] = row_lo[k*32 + q*8 +: 4];
                cands_q[1] = row_lo[k*32 + q*8 + 4 +: 4];
                cands_q[2] = row_hi[k*32 + q*8 +: 4];
                cands_q[3] = row_hi[k*32 + q*8 + 4 +: 4];

                meta_q = tcu_v2_sparse_meta4_t'(row_meta[grp_idx*4 +: 4]);
                sup_q  = global_suppress || row_err[grp_idx];

                res[k*32 + q*8 +: 4]     = select_pair4(cands_q, meta_q, 1'b0, sup_q);
                res[k*32 + q*8 + 4 +: 4] = select_pair4(cands_q, meta_q, 1'b1, sup_q);
            end
        end
        return res;
    endfunction

    logic [ARRAY_M-1:0][ROW_BITS-1:0] a_selected_comb;
    logic                             fault_masked_comb;
    logic [15:0]                      active_lanes_comb;

    always_comb begin
        fault_masked_comb = 1'b0;
        a_selected_comb   = a_tile_in;

        if (sparse_en) begin
            fault_masked_comb = fault_suppress || (group_err_mask_in != '0);
            for (int m = 0; m < ARRAY_M; ++m) begin
                case (fmt_a)
                    TCU_V2_FMT_TF32: begin
                        a_selected_comb[m] = select_row_tf32(
                            a_tile_in[m], a_sparse_cand_in[m],
                            sparse_meta_in[m], group_err_mask_in[m], fault_suppress
                        );
                    end
                    TCU_V2_FMT_FP16,
                    TCU_V2_FMT_BF16: begin
                        a_selected_comb[m] = select_row_16b(
                            a_tile_in[m], a_sparse_cand_in[m],
                            sparse_meta_in[m], group_err_mask_in[m], fault_suppress
                        );
                    end
                    TCU_V2_FMT_FP8_E4M3,
                    TCU_V2_FMT_FP8_E5M2,
                    TCU_V2_FMT_MXFP8_E4M3,
                    TCU_V2_FMT_MXFP8_E5M2,
                    TCU_V2_FMT_INT8: begin
                        a_selected_comb[m] = select_row_8b(
                            a_tile_in[m], a_sparse_cand_in[m],
                            sparse_meta_in[m], group_err_mask_in[m], fault_suppress
                        );
                    end
                    TCU_V2_FMT_MXFP6_E2M3,
                    TCU_V2_FMT_MXFP6_E3M2: begin
                        a_selected_comb[m] = select_row_6b(
                            a_tile_in[m], a_sparse_cand_in[m],
                            sparse_meta_in[m], group_err_mask_in[m], fault_suppress
                        );
                    end
                    TCU_V2_FMT_MXFP4_E2M1,
                    TCU_V2_FMT_NVFP4_E2M1: begin
                        a_selected_comb[m] = select_row_4b(
                            a_tile_in[m], a_sparse_cand_in[m],
                            sparse_meta_in[m], group_err_mask_in[m], fault_suppress
                        );
                    end
                    default: begin
                        a_selected_comb[m] = fault_suppress ? '0 : a_tile_in[m];
                    end
                endcase
            end
        end else if (fault_suppress) begin
            a_selected_comb   = '0;
            fault_masked_comb = 1'b1;
        end

        case (fmt_a)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_I32:        active_lanes_comb = 16'(ARRAY_M * ARRAY_K);
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16:       active_lanes_comb = 16'(ARRAY_M * ARRAY_K * 2);
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8:       active_lanes_comb = 16'(ARRAY_M * ARRAY_K * 4);
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: active_lanes_comb = 16'(ARRAY_M * ARRAY_K * 8);
            default:               active_lanes_comb = 16'd0;
        endcase
    end

    logic                               valid_r;
    logic [ARRAY_M-1:0][ROW_BITS-1:0]   a_selected_r;
    logic                               fault_masked_r;
    logic [15:0]                        active_lanes_r;
    logic [31:0]                        dense_bypass_cnt_r;
    logic [31:0]                        sparse_select_cnt_r;
    logic [31:0]                        fault_suppress_cnt_r;
    logic [31:0]                        group_masked_cnt_r;
    logic [ARRAY_M-1:0]                 row_has_err_w;

    always_comb begin
        for (int m = 0; m < ARRAY_M; ++m) begin
            row_has_err_w[m] = (group_err_mask_in[m] != '0);
        end
    end

    assign ready_in = !valid_r || ready_out;

    always_ff @(posedge clk) begin
        if (reset) begin
            valid_r              <= 1'b0;
            a_selected_r         <= '0;
            fault_masked_r       <= 1'b0;
            active_lanes_r       <= 16'd0;
            dense_bypass_cnt_r   <= 32'd0;
            sparse_select_cnt_r  <= 32'd0;
            fault_suppress_cnt_r <= 32'd0;
            group_masked_cnt_r   <= 32'd0;
        end else if (ready_in) begin
            valid_r <= valid_in;
            if (valid_in) begin
                a_selected_r   <= a_selected_comb;
                fault_masked_r <= fault_masked_comb;
                active_lanes_r <= active_lanes_comb;
                if (fault_masked_comb) begin
                    fault_suppress_cnt_r <= fault_suppress_cnt_r + 32'd1;
                end
                if (sparse_en) begin
                    sparse_select_cnt_r <= sparse_select_cnt_r + 32'd1;
                    if (row_has_err_w != '0) begin
                        group_masked_cnt_r <= group_masked_cnt_r + 32'd1;
                    end
                end else begin
                    dense_bypass_cnt_r <= dense_bypass_cnt_r + 32'd1;
                end
            end
        end
    end

    `UNUSED_VAR (dense_bypass_cnt_r)
    `UNUSED_VAR (sparse_select_cnt_r)
    `UNUSED_VAR (fault_suppress_cnt_r)
    `UNUSED_VAR (group_masked_cnt_r)

    assign valid_out        = valid_r;
    assign a_selected_out   = a_selected_r;
    assign fault_masked_out = fault_masked_r;
    assign active_lanes_out = active_lanes_r;

endmodule
