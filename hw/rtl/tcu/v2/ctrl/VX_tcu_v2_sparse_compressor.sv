// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_sparse_compressor #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                valid_in,
    output logic                                ready_in,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e          fmt_a,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  dense_lo_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  dense_hi_in,
    output logic                                valid_out,
    input  logic                                ready_out,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  compressed_out,
    output logic [ARRAY_M-1:0][ARRAY_K*16-1:0]  meta_out,
    output logic                                prune_loss_out,
    output logic [15:0]                         pruned_groups_out,
    output logic [15:0]                         exact_2_4_groups_out
);

    import VX_tcu_v2_pkg::*;

    localparam int GROUPS_PER_ROW = ARRAY_K * 4;
    localparam int ROW_BITS       = ARRAY_K * 32;

    typedef struct packed {
        tcu_v2_sparse_meta4_t meta;
        logic                 prune_loss;
        logic                 exact_2_4;
    } comp_pick_t;

    function automatic logic [31:0] mag_key(
        input tcu_v2_fmt_e fmt,
        input logic [31:0] raw
    );
        logic [7:0] s8;
        logic       unused_sign;
        unused_sign = raw[31];
        case (fmt)
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP32: begin
                return unused_sign ? {1'b0, raw[30:0]} : {1'b0, raw[30:0]};
            end
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16: begin
                return {17'd0, raw[14:0]};
            end
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2: begin
                return {25'd0, raw[6:0]};
            end
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2: begin
                return {27'd0, raw[4:0]};
            end
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: begin
                return {29'd0, raw[2:0]};
            end
            TCU_V2_FMT_INT8: begin
                s8 = raw[7:0];
                if (s8[7]) begin
                    return {24'd0, (~s8 + 8'd1)};
                end else begin
                    return {24'd0, s8};
                end
            end
            default: begin
                return {1'b0, raw[30:0]};
            end
        endcase
    endfunction

    function automatic comp_pick_t pick_top2_from_4(
        input logic [3:0][31:0] mags
    );
        comp_pick_t res;
        logic [3:0] nonzero;
        logic [2:0] nz_cnt;
        logic [1:0] max_idx;
        logic [1:0] sec_idx;
        logic [31:0] max_val;
        logic [31:0] sec_val;
        logic [1:0] idx_a;
        logic [1:0] idx_b;

        nz_cnt = 3'd0;
        for (int i = 0; i < 4; ++i) begin
            nonzero[i] = (mags[i] != 32'd0);
            if (nonzero[i]) begin
                nz_cnt = nz_cnt + 3'd1;
            end
        end

        max_idx = 2'd0;
        max_val = mags[0];
        for (int i = 1; i < 4; ++i) begin
            if (mags[i] > max_val) begin
                max_val = mags[i];
                max_idx = 2'(i);
            end
        end

        sec_idx = (max_idx == 2'd0) ? 2'd1 : 2'd0;
        sec_val = mags[sec_idx];
        for (int i = 0; i < 4; ++i) begin
            if (2'(i) != max_idx) begin
                if ((mags[i] > sec_val) || ((mags[i] == sec_val) && (2'(i) < sec_idx))) begin
                    sec_val = mags[i];
                    sec_idx = 2'(i);
                end
            end
        end

        if (nz_cnt == 3'd0) begin
            idx_a = 2'd0;
            idx_b = 2'd1;
        end else if (nz_cnt == 3'd1) begin
            if (max_idx == 2'd0) begin
                idx_a = 2'd0;
                idx_b = 2'd1;
            end else begin
                idx_a = 2'd0;
                idx_b = max_idx;
            end
        end else begin
            if (max_idx < sec_idx) begin
                idx_a = max_idx;
                idx_b = sec_idx;
            end else begin
                idx_a = sec_idx;
                idx_b = max_idx;
            end
        end

        res.meta.idx0  = idx_a;
        res.meta.idx1  = idx_b;
        res.prune_loss = (nz_cnt > 3'd2);
        res.exact_2_4  = (nz_cnt <= 3'd2);
        return res;
    endfunction

    logic [ARRAY_M-1:0][ROW_BITS-1:0]   comp_comb;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] meta_comb;
    logic                              prune_loss_comb;
    logic [15:0]                       pruned_groups_comb;
    logic [15:0]                       exact_groups_comb;

    always_comb begin
        comp_comb          = '0;
        meta_comb          = '0;
        prune_loss_comb    = 1'b0;
        pruned_groups_comb = 16'd0;
        exact_groups_comb  = 16'd0;

        for (int m = 0; m < ARRAY_M; ++m) begin
            logic [3:0][31:0] elems;
            logic [3:0][31:0] mags;
            comp_pick_t       pk;
            logic [3:0][31:0] elems_lo;
            logic [3:0][31:0] elems_hi;
            logic [3:0][31:0] mags_lo;
            logic [3:0][31:0] mags_hi;
            comp_pick_t       pk_lo;
            comp_pick_t       pk_hi;
            logic [3:0][31:0] elems_q;
            logic [3:0][31:0] mags_q;
            comp_pick_t       pk_q;
            int               grp_idx;

            elems    = '0;
            mags     = '0;
            pk       = '0;
            elems_lo = '0;
            elems_hi = '0;
            mags_lo  = '0;
            mags_hi  = '0;
            pk_lo    = '0;
            pk_hi    = '0;
            elems_q  = '0;
            mags_q   = '0;
            pk_q     = '0;
            grp_idx  = 0;

            case (fmt_a)
                TCU_V2_FMT_TF32: begin
                    for (int g = 0; g < (ARRAY_K / 2); ++g) begin
                        elems[0] = dense_lo_in[m][(2 * g) * 32 +: 32];
                        elems[1] = dense_lo_in[m][(2 * g + 1) * 32 +: 32];
                        elems[2] = dense_hi_in[m][(2 * g) * 32 +: 32];
                        elems[3] = dense_hi_in[m][(2 * g + 1) * 32 +: 32];
                        for (int i = 0; i < 4; ++i) begin
                            mags[i] = mag_key(fmt_a, elems[i]);
                        end
                        pk = pick_top2_from_4(mags);
                        comp_comb[m][(2 * g) * 32 +: 32]     = elems[pk.meta.idx0];
                        comp_comb[m][(2 * g + 1) * 32 +: 32] = elems[pk.meta.idx1];
                        meta_comb[m][g*4 +: 4]               = pk.meta;
                        if (pk.prune_loss) begin
                            prune_loss_comb    = 1'b1;
                            pruned_groups_comb = pruned_groups_comb + 16'd1;
                        end
                        if (pk.exact_2_4) begin
                            exact_groups_comb = exact_groups_comb + 16'd1;
                        end
                    end
                end
                TCU_V2_FMT_FP16,
                TCU_V2_FMT_BF16: begin
                    for (int k = 0; k < ARRAY_K; ++k) begin
                        elems[0] = {16'd0, dense_lo_in[m][k*32 +: 16]};
                        elems[1] = {16'd0, dense_lo_in[m][k*32 + 16 +: 16]};
                        elems[2] = {16'd0, dense_hi_in[m][k*32 +: 16]};
                        elems[3] = {16'd0, dense_hi_in[m][k*32 + 16 +: 16]};
                        for (int i = 0; i < 4; ++i) begin
                            mags[i] = mag_key(fmt_a, elems[i]);
                        end
                        pk = pick_top2_from_4(mags);
                        comp_comb[m][k*32 +: 16]      = elems[pk.meta.idx0][15:0];
                        comp_comb[m][k*32 + 16 +: 16] = elems[pk.meta.idx1][15:0];
                        meta_comb[m][k*4 +: 4]        = pk.meta;
                        if (pk.prune_loss) begin
                            prune_loss_comb    = 1'b1;
                            pruned_groups_comb = pruned_groups_comb + 16'd1;
                        end
                        if (pk.exact_2_4) begin
                            exact_groups_comb = exact_groups_comb + 16'd1;
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
                        elems_lo[0] = {24'd0, dense_lo_in[m][k*32 +: 8]};
                        elems_lo[1] = {24'd0, dense_lo_in[m][k*32 + 8 +: 8]};
                        elems_lo[2] = {24'd0, dense_hi_in[m][k*32 +: 8]};
                        elems_lo[3] = {24'd0, dense_hi_in[m][k*32 + 8 +: 8]};

                        elems_hi[0] = {24'd0, dense_lo_in[m][k*32 + 16 +: 8]};
                        elems_hi[1] = {24'd0, dense_lo_in[m][k*32 + 24 +: 8]};
                        elems_hi[2] = {24'd0, dense_hi_in[m][k*32 + 16 +: 8]};
                        elems_hi[3] = {24'd0, dense_hi_in[m][k*32 + 24 +: 8]};

                        for (int i = 0; i < 4; ++i) begin
                            mags_lo[i] = mag_key(fmt_a, elems_lo[i]);
                            mags_hi[i] = mag_key(fmt_a, elems_hi[i]);
                        end
                        pk_lo = pick_top2_from_4(mags_lo);
                        pk_hi = pick_top2_from_4(mags_hi);

                        comp_comb[m][k*32 +: 8]      = elems_lo[pk_lo.meta.idx0][7:0];
                        comp_comb[m][k*32 + 8 +: 8]  = elems_lo[pk_lo.meta.idx1][7:0];
                        comp_comb[m][k*32 + 16 +: 8] = elems_hi[pk_hi.meta.idx0][7:0];
                        comp_comb[m][k*32 + 24 +: 8] = elems_hi[pk_hi.meta.idx1][7:0];

                        meta_comb[m][(2*k)*4 +: 4]   = pk_lo.meta;
                        meta_comb[m][(2*k+1)*4 +: 4] = pk_hi.meta;

                        if (pk_lo.prune_loss || pk_hi.prune_loss) begin
                            prune_loss_comb = 1'b1;
                        end
                        pruned_groups_comb = pruned_groups_comb
                                           + {15'd0, pk_lo.prune_loss}
                                           + {15'd0, pk_hi.prune_loss};
                        exact_groups_comb  = exact_groups_comb
                                           + {15'd0, pk_lo.exact_2_4}
                                           + {15'd0, pk_hi.exact_2_4};
                    end
                end
                TCU_V2_FMT_MXFP4_E2M1,
                TCU_V2_FMT_NVFP4_E2M1: begin
                    for (int k = 0; k < ARRAY_K; ++k) begin
                        for (int q = 0; q < 4; ++q) begin
                            grp_idx    = 4 * k + q;
                            elems_q[0] = {28'd0, dense_lo_in[m][k*32 + q*8 +: 4]};
                            elems_q[1] = {28'd0, dense_lo_in[m][k*32 + q*8 + 4 +: 4]};
                            elems_q[2] = {28'd0, dense_hi_in[m][k*32 + q*8 +: 4]};
                            elems_q[3] = {28'd0, dense_hi_in[m][k*32 + q*8 + 4 +: 4]};

                            for (int i = 0; i < 4; ++i) begin
                                mags_q[i] = mag_key(fmt_a, elems_q[i]);
                            end
                            pk_q = pick_top2_from_4(mags_q);

                            comp_comb[m][k*32 + q*8 +: 4]     = elems_q[pk_q.meta.idx0][3:0];
                            comp_comb[m][k*32 + q*8 + 4 +: 4] = elems_q[pk_q.meta.idx1][3:0];
                            meta_comb[m][grp_idx*4 +: 4]      = pk_q.meta;

                            if (pk_q.prune_loss) begin
                                prune_loss_comb = 1'b1;
                            end
                            pruned_groups_comb = pruned_groups_comb + {15'd0, pk_q.prune_loss};
                            exact_groups_comb  = exact_groups_comb + {15'd0, pk_q.exact_2_4};
                        end
                    end
                end
                default: begin
                    comp_comb[m] = dense_lo_in[m];
                    for (int g = 0; g < GROUPS_PER_ROW; ++g) begin
                        meta_comb[m][g*4 +: 4] = 4'b0100;
                    end
                end
            endcase
        end
    end

    logic                               valid_r;
    logic [ARRAY_M-1:0][ROW_BITS-1:0]   compressed_r;
    logic [ARRAY_M-1:0][ARRAY_K*16-1:0] meta_r;
    logic                               prune_loss_r;
    logic [15:0]                        pruned_groups_r;
    logic [15:0]                        exact_groups_r;

    assign ready_in = !valid_r || ready_out;

    always_ff @(posedge clk) begin
        if (reset) begin
            valid_r         <= 1'b0;
            compressed_r    <= '0;
            meta_r          <= '0;
            prune_loss_r    <= 1'b0;
            pruned_groups_r <= 16'd0;
            exact_groups_r  <= 16'd0;
        end else if (ready_in) begin
            valid_r <= valid_in;
            if (valid_in) begin
                compressed_r    <= comp_comb;
                meta_r          <= meta_comb;
                prune_loss_r    <= prune_loss_comb;
                pruned_groups_r <= pruned_groups_comb;
                exact_groups_r  <= exact_groups_comb;
            end
        end
    end

    assign valid_out            = valid_r;
    assign compressed_out       = compressed_r;
    assign meta_out             = meta_r;
    assign prune_loss_out       = prune_loss_r;
    assign pruned_groups_out    = pruned_groups_r;
    assign exact_2_4_groups_out = exact_groups_r;

endmodule
