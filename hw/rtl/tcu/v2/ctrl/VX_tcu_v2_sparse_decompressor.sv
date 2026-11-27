// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_sparse_decompressor #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                valid_in,
    output logic                                ready_in,
    input  logic                                sparse_en,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e          fmt_a,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  compressed_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]  meta_in,
    output logic                                valid_out,
    input  logic                                ready_out,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  dense_lo_out,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  dense_hi_out,
    output logic [ARRAY_M-1:0][ARRAY_K*8-1:0]   occupancy_mask_out,
    output logic [15:0]                         active_elem_cnt_out,
    output logic                                meta_illegal_out
);

    import VX_tcu_v2_pkg::*;

    localparam int GROUPS_PER_ROW = ARRAY_K * 4;
    localparam int ROW_BITS       = ARRAY_K * 32;

    logic [ARRAY_M-1:0][ROW_BITS-1:0]   lo_comb;
    logic [ARRAY_M-1:0][ROW_BITS-1:0]   hi_comb;
    logic [ARRAY_M-1:0][ARRAY_K*8-1:0]  occ_comb;
    logic [15:0]                        active_cnt_comb;
    logic                               meta_illegal_comb;

    always_comb begin
        tcu_v2_sparse_meta4_t meta;
        logic                 legal;
        logic [31:0]          e0_32;
        logic [31:0]          e1_32;
        logic [15:0]          e0_16;
        logic [15:0]          e1_16;
        logic [7:0]           e0_8;
        logic [7:0]           e1_8;
        logic [3:0]           e0_4;
        logic [3:0]           e1_4;

        lo_comb           = '0;
        hi_comb           = '0;
        occ_comb          = '0;
        active_cnt_comb   = 16'd0;
        meta_illegal_comb = 1'b0;

        meta  = '0;
        legal = 1'b0;
        e0_32 = 32'd0;
        e1_32 = 32'd0;
        e0_16 = 16'd0;
        e1_16 = 16'd0;
        e0_8  = 8'd0;
        e1_8  = 8'd0;
        e0_4  = 4'd0;
        e1_4  = 4'd0;

        if (!sparse_en) begin
            lo_comb  = compressed_in;
            hi_comb  = '0;
            occ_comb = {ARRAY_M{{ARRAY_K*8{1'b1}}}};
            active_cnt_comb = 16'(ARRAY_M * ARRAY_K);
        end else begin
            for (int m = 0; m < ARRAY_M; ++m) begin
                case (fmt_a)
                    TCU_V2_FMT_TF32: begin
                        for (int g = 0; g < (ARRAY_K / 2); ++g) begin
                            meta  = tcu_v2_sparse_meta4_t'(meta_in[m][g*4 +: 4]);
                            legal = tcu_v2_sparse_pair_legal(meta);
                            e0_32 = compressed_in[m][(2 * g) * 32 +: 32];
                            e1_32 = compressed_in[m][(2 * g + 1) * 32 +: 32];
                            if (!legal) begin
                                meta_illegal_comb = 1'b1;
                            end else begin
                                occ_comb[m][g*4 + int'(meta.idx0)] = 1'b1;
                                occ_comb[m][g*4 + int'(meta.idx1)] = 1'b1;
                                active_cnt_comb                    = active_cnt_comb + 16'd2;
                                case (meta.idx0)
                                    2'd0:    lo_comb[m][(2 * g) * 32 +: 32]     = e0_32;
                                    2'd1:    lo_comb[m][(2 * g + 1) * 32 +: 32] = e0_32;
                                    2'd2:    hi_comb[m][(2 * g) * 32 +: 32]     = e0_32;
                                    default: hi_comb[m][(2 * g + 1) * 32 +: 32] = e0_32;
                                endcase
                                case (meta.idx1)
                                    2'd0:    lo_comb[m][(2 * g) * 32 +: 32]     = e1_32;
                                    2'd1:    lo_comb[m][(2 * g + 1) * 32 +: 32] = e1_32;
                                    2'd2:    hi_comb[m][(2 * g) * 32 +: 32]     = e1_32;
                                    default: hi_comb[m][(2 * g + 1) * 32 +: 32] = e1_32;
                                endcase
                            end
                        end
                    end

                    TCU_V2_FMT_FP16,
                    TCU_V2_FMT_BF16: begin
                        for (int k = 0; k < ARRAY_K; ++k) begin
                            meta  = tcu_v2_sparse_meta4_t'(meta_in[m][k*4 +: 4]);
                            legal = tcu_v2_sparse_pair_legal(meta);
                            e0_16 = compressed_in[m][k*32 +: 16];
                            e1_16 = compressed_in[m][k*32 + 16 +: 16];
                            if (!legal) begin
                                meta_illegal_comb = 1'b1;
                            end else begin
                                occ_comb[m][k*4 + int'(meta.idx0)] = 1'b1;
                                occ_comb[m][k*4 + int'(meta.idx1)] = 1'b1;
                                active_cnt_comb              = active_cnt_comb + 16'd2;
                                case (meta.idx0)
                                    2'd0:    lo_comb[m][k*32 +: 16]      = e0_16;
                                    2'd1:    lo_comb[m][k*32 + 16 +: 16] = e0_16;
                                    2'd2:    hi_comb[m][k*32 +: 16]      = e0_16;
                                    default: hi_comb[m][k*32 + 16 +: 16] = e0_16;
                                endcase
                                case (meta.idx1)
                                    2'd0:    lo_comb[m][k*32 +: 16]      = e1_16;
                                    2'd1:    lo_comb[m][k*32 + 16 +: 16] = e1_16;
                                    2'd2:    hi_comb[m][k*32 +: 16]      = e1_16;
                                    default: hi_comb[m][k*32 + 16 +: 16] = e1_16;
                                endcase
                            end
                        end
                    end

                    TCU_V2_FMT_FP8_E4M3,
                    TCU_V2_FMT_FP8_E5M2,
                    TCU_V2_FMT_MXFP8_E4M3,
                    TCU_V2_FMT_MXFP8_E5M2,
                    TCU_V2_FMT_MXFP6_E2M3,
                    TCU_V2_FMT_MXFP6_E3M2,
                    TCU_V2_FMT_INT8: begin
                        for (int k = 0; k < ARRAY_K; ++k) begin
                            int g_lo;
                            int g_hi;
                            g_lo = 2 * k;
                            g_hi = 2 * k + 1;

                            meta  = tcu_v2_sparse_meta4_t'(meta_in[m][g_lo*4 +: 4]);
                            legal = tcu_v2_sparse_pair_legal(meta);
                            e0_8  = compressed_in[m][k*32 +: 8];
                            e1_8  = compressed_in[m][k*32 + 8 +: 8];
                            if (!legal) begin
                                meta_illegal_comb = 1'b1;
                            end else begin
                                occ_comb[m][g_lo*2]     = 1'b1;
                                occ_comb[m][g_lo*2 + 1] = 1'b1;
                                active_cnt_comb         = active_cnt_comb + 16'd2;
                                case (meta.idx0)
                                    2'd0:    lo_comb[m][k*32 +: 8]     = e0_8;
                                    2'd1:    lo_comb[m][k*32 + 8 +: 8] = e0_8;
                                    2'd2:    hi_comb[m][k*32 +: 8]     = e0_8;
                                    default: hi_comb[m][k*32 + 8 +: 8] = e0_8;
                                endcase
                                case (meta.idx1)
                                    2'd0:    lo_comb[m][k*32 +: 8]     = e1_8;
                                    2'd1:    lo_comb[m][k*32 + 8 +: 8] = e1_8;
                                    2'd2:    hi_comb[m][k*32 +: 8]     = e1_8;
                                    default: hi_comb[m][k*32 + 8 +: 8] = e1_8;
                                endcase
                            end

                            meta  = tcu_v2_sparse_meta4_t'(meta_in[m][g_hi*4 +: 4]);
                            legal = tcu_v2_sparse_pair_legal(meta);
                            e0_8  = compressed_in[m][k*32 + 16 +: 8];
                            e1_8  = compressed_in[m][k*32 + 24 +: 8];
                            if (!legal) begin
                                meta_illegal_comb = 1'b1;
                            end else begin
                                occ_comb[m][g_hi*2]     = 1'b1;
                                occ_comb[m][g_hi*2 + 1] = 1'b1;
                                active_cnt_comb         = active_cnt_comb + 16'd2;
                                case (meta.idx0)
                                    2'd0:    lo_comb[m][k*32 + 16 +: 8] = e0_8;
                                    2'd1:    lo_comb[m][k*32 + 24 +: 8] = e0_8;
                                    2'd2:    hi_comb[m][k*32 + 16 +: 8] = e0_8;
                                    default: hi_comb[m][k*32 + 24 +: 8] = e0_8;
                                endcase
                                case (meta.idx1)
                                    2'd0:    lo_comb[m][k*32 + 16 +: 8] = e1_8;
                                    2'd1:    lo_comb[m][k*32 + 24 +: 8] = e1_8;
                                    2'd2:    hi_comb[m][k*32 + 16 +: 8] = e1_8;
                                    default: hi_comb[m][k*32 + 24 +: 8] = e1_8;
                                endcase
                            end
                        end
                    end

                    TCU_V2_FMT_MXFP4_E2M1,
                    TCU_V2_FMT_NVFP4_E2M1: begin
                        for (int k = 0; k < ARRAY_K; ++k) begin
                            for (int q = 0; q < 4; ++q) begin
                                int grp_idx;
                                grp_idx = 4 * k + q;

                                meta  = tcu_v2_sparse_meta4_t'(meta_in[m][grp_idx*4 +: 4]);
                                legal = tcu_v2_sparse_pair_legal(meta);
                                e0_4  = compressed_in[m][k*32 + q*8 +: 4];
                                e1_4  = compressed_in[m][k*32 + q*8 + 4 +: 4];
                                if (!legal) begin
                                    meta_illegal_comb = 1'b1;
                                end else begin
                                    occ_comb[m][grp_idx*2]     = 1'b1;
                                    occ_comb[m][grp_idx*2 + 1] = 1'b1;
                                    active_cnt_comb            = active_cnt_comb + 16'd2;
                                    case (meta.idx0)
                                        2'd0:    lo_comb[m][k*32 + q*8 +: 4]     = e0_4;
                                        2'd1:    lo_comb[m][k*32 + q*8 + 4 +: 4] = e0_4;
                                        2'd2:    hi_comb[m][k*32 + q*8 +: 4]     = e0_4;
                                        default: hi_comb[m][k*32 + q*8 + 4 +: 4] = e0_4;
                                    endcase
                                    case (meta.idx1)
                                        2'd0:    lo_comb[m][k*32 + q*8 +: 4]     = e1_4;
                                        2'd1:    lo_comb[m][k*32 + q*8 + 4 +: 4] = e1_4;
                                        2'd2:    hi_comb[m][k*32 + q*8 +: 4]     = e1_4;
                                        default: hi_comb[m][k*32 + q*8 + 4 +: 4] = e1_4;
                                    endcase
                                end
                            end
                        end
                    end

                    default: begin
                        lo_comb[m] = compressed_in[m];
                    end
                endcase
            end
        end
    end

    logic                               valid_r;
    logic [ARRAY_M-1:0][ROW_BITS-1:0]   lo_r;
    logic [ARRAY_M-1:0][ROW_BITS-1:0]   hi_r;
    logic [ARRAY_M-1:0][ARRAY_K*8-1:0]  occ_r;
    logic [15:0]                        active_cnt_r;
    logic                               meta_illegal_r;

    `UNUSED_VAR (GROUPS_PER_ROW)

    assign ready_in = !valid_r || ready_out;

    always_ff @(posedge clk) begin
        if (reset) begin
            valid_r        <= 1'b0;
            lo_r           <= '0;
            hi_r           <= '0;
            occ_r          <= '0;
            active_cnt_r   <= 16'd0;
            meta_illegal_r <= 1'b0;
        end else if (ready_in) begin
            valid_r <= valid_in;
            if (valid_in) begin
                lo_r           <= lo_comb;
                hi_r           <= hi_comb;
                occ_r          <= occ_comb;
                active_cnt_r   <= active_cnt_comb;
                meta_illegal_r <= meta_illegal_comb;
            end
        end
    end

    assign valid_out           = valid_r;
    assign dense_lo_out        = lo_r;
    assign dense_hi_out        = hi_r;
    assign occupancy_mask_out  = occ_r;
    assign active_elem_cnt_out = active_cnt_r;
    assign meta_illegal_out    = meta_illegal_r;

endmodule
