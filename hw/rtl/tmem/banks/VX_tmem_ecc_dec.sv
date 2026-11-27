// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_ecc_dec #(
    parameter int PIPE_STAGES = 0
) (
    input  logic                                      clk,
    input  logic                                      reset,
    input  logic                                      valid_in,
    input  logic [VX_tmem_pkg::TMEM_ECC_CODE_W-1:0]   codeword_in,
    output logic                                      valid_out,
    output logic [VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]   data_out,
    output logic [VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0] parity_out,
    output logic [VX_tmem_pkg::TMEM_ECC_CODE_W-1:0]   codeword_out,
    output logic [VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0] syndrome_out,
    output logic                                      ce_out,
    output logic                                      ue_out,
    output logic                                      err_in_parity_out,
    output logic [6:0]                                err_bit_idx_out
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(TMEM_ECC_DATA_W == 64, ("Hsiao(72,64) requires 64 data bits"))
    `STATIC_ASSERT(TMEM_ECC_PARITY_W == 8, ("Hsiao(72,64) requires 8 parity bits"))
    `STATIC_ASSERT(TMEM_ECC_CODE_W == 72, ("Hsiao(72,64) requires 72 codeword bits"))
    `STATIC_ASSERT((PIPE_STAGES == 0) || (PIPE_STAGES == 1), ("PIPE_STAGES must be 0 or 1"))

    // Extract stored data and parity fields from 72-bit codeword
    logic [TMEM_ECC_DATA_W-1:0]         raw_data;
    logic [TMEM_ECC_PARITY_W-1:0]       raw_parity;
    logic [TMEM_ECC_PARITY_W-1:0]       recomputed_parity;
    logic [TMEM_ECC_PARITY_W-1:0]       syndrome;
    logic [TMEM_ECC_PARITY_W-1:0][31:0] xor_lvl1_pair;
    logic [TMEM_ECC_PARITY_W-1:0][15:0] xor_lvl2_nibble;
    logic [TMEM_ECC_PARITY_W-1:0][3:0]  xor_lvl3_quad;

    assign raw_data   = codeword_in[TMEM_ECC_DATA_W-1:0];
    assign raw_parity = codeword_in[TMEM_ECC_CODE_W-1:TMEM_ECC_DATA_W];

    // Balanced multi-level XOR reduction tree for each of the 8 syndrome bits
    for (genvar g_p = 0; g_p < TMEM_ECC_PARITY_W; ++g_p) begin : g_syndrome_gen
        logic [TMEM_ECC_DATA_W-1:0] masked_data;

        always_comb begin
            masked_data = raw_data & TMEM_HSIAO_P_MATRIX[g_p];
            for (int pair_i = 0; pair_i < 32; ++pair_i) begin
                xor_lvl1_pair[g_p][pair_i] = ^masked_data[pair_i*2 +: 2];
            end
            for (int nib_i = 0; nib_i < 16; ++nib_i) begin
                xor_lvl2_nibble[g_p][nib_i] = ^xor_lvl1_pair[g_p][nib_i*2 +: 2];
            end
            for (int q_i = 0; q_i < 4; ++q_i) begin
                xor_lvl3_quad[g_p][q_i] = ^xor_lvl2_nibble[g_p][q_i*4 +: 4];
            end
            recomputed_parity[g_p] = ^xor_lvl3_quad[g_p];
            syndrome[g_p]          = raw_parity[g_p] ^ recomputed_parity[g_p];
        end
    end

    // Match syndrome against all 64 data columns and 8 parity columns of Hsiao H-matrix
    logic [TMEM_ECC_DATA_W-1:0]   data_bit_match;
    logic [TMEM_ECC_PARITY_W-1:0] parity_bit_match;
    logic [3:0]                   syndrome_weight;
    logic                         syndrome_nonzero;
    logic                         syndrome_odd_weight;
    logic                         syndrome_wt_is_1;
    logic                         syndrome_wt_is_3_or_5;
    logic                         syndrome_wt_is_even_nz;
    logic                         any_data_match;
    logic                         any_parity_match;
    logic                         any_col_match;
    logic [TMEM_ECC_DATA_W-1:0]   corr_data;
    logic [TMEM_ECC_PARITY_W-1:0] corr_parity;
    logic [TMEM_ECC_CODE_W-1:0]   corr_codeword;
    logic [TMEM_ECC_PARITY_W-1:0] verify_syndrome;
    logic                         comb_ce;
    logic                         comb_ue;
    logic                         comb_err_in_parity;
    logic [6:0]                   comb_err_bit_idx;

    for (genvar g_d = 0; g_d < TMEM_ECC_DATA_W; ++g_d) begin : g_match_data_col
        localparam logic [TMEM_ECC_PARITY_W-1:0] COL_SIG = {
            TMEM_HSIAO_P_MATRIX[7][g_d],
            TMEM_HSIAO_P_MATRIX[6][g_d],
            TMEM_HSIAO_P_MATRIX[5][g_d],
            TMEM_HSIAO_P_MATRIX[4][g_d],
            TMEM_HSIAO_P_MATRIX[3][g_d],
            TMEM_HSIAO_P_MATRIX[2][g_d],
            TMEM_HSIAO_P_MATRIX[1][g_d],
            TMEM_HSIAO_P_MATRIX[0][g_d]
        };
        assign data_bit_match[g_d] = (syndrome == COL_SIG);
    end

    for (genvar g_q = 0; g_q < TMEM_ECC_PARITY_W; ++g_q) begin : g_match_parity_col
        localparam logic [TMEM_ECC_PARITY_W-1:0] PAR_SIG = (8'h01 << g_q);
        assign parity_bit_match[g_q] = (syndrome == PAR_SIG);
    end

    // Hierarchical priority encoder over the 64 data + 8 parity bit match lines
    logic [7:0]                   byte_match_any;
    logic [7:0][2:0]              byte_match_local_idx;
    logic [2:0]                   data_match_byte_idx;
    logic [2:0]                   data_match_bit_in_byte;
    logic [2:0]                   parity_match_idx;

    for (genvar g_b = 0; g_b < 8; ++g_b) begin : g_byte_match_enc
        always_comb begin
            byte_match_any[g_b]       = |data_bit_match[g_b*8 +: 8];
            byte_match_local_idx[g_b] = 3'd0;
            for (int k = 0; k < 8; ++k) begin
                if (data_bit_match[g_b*8 + k]) begin
                    byte_match_local_idx[g_b] = 3'(k);
                end
            end
        end
    end

    function automatic logic [3:0] popcount_8(
        input logic [TMEM_ECC_PARITY_W-1:0] vec
    );
        logic [3:0] cnt;
        cnt = 4'd0;
        for (int b = 0; b < TMEM_ECC_PARITY_W; ++b) begin
            if (vec[b]) begin
                cnt = cnt + 4'd1;
            end
        end
        return cnt;
    endfunction

    always_comb begin
        syndrome_weight        = popcount_8(syndrome);
        syndrome_nonzero       = |syndrome;
        syndrome_odd_weight    = ^syndrome;
        syndrome_wt_is_1       = (syndrome_weight == 4'd1);
        syndrome_wt_is_3_or_5  = (syndrome_weight == 4'd3) || (syndrome_weight == 4'd5);
        syndrome_wt_is_even_nz = syndrome_nonzero && !syndrome_odd_weight;
        any_data_match         = |byte_match_any;
        any_parity_match       = |parity_bit_match;
        any_col_match          = any_data_match || any_parity_match;

        // Single-bit error: non-zero odd-weight syndrome matching one of the 72 H columns.
        // Double-bit (or multi-bit) error: non-zero even-weight syndrome, OR odd-weight syndrome
        // not matching any valid single-bit H column.
        comb_ce            = valid_in && syndrome_nonzero && syndrome_odd_weight && any_col_match;
        comb_ue            = valid_in && syndrome_nonzero && ((!syndrome_odd_weight) || (!any_col_match));
        comb_err_in_parity = comb_ce && any_parity_match;

        if (comb_ce) begin
            corr_data   = raw_data ^ data_bit_match;
            corr_parity = raw_parity ^ parity_bit_match;
        end else begin
            corr_data   = raw_data;
            corr_parity = raw_parity;
        end
        corr_codeword = {corr_parity, corr_data};

        data_match_byte_idx    = 3'd0;
        data_match_bit_in_byte = 3'd0;
        for (int b = 0; b < 8; ++b) begin
            if (byte_match_any[b]) begin
                data_match_byte_idx    = 3'(b);
                data_match_bit_in_byte = byte_match_local_idx[b];
            end
        end

        parity_match_idx = 3'd0;
        for (int q = 0; q < TMEM_ECC_PARITY_W; ++q) begin
            if (parity_bit_match[q]) begin
                parity_match_idx = 3'(q);
            end
        end

        if (!comb_ce) begin
            comb_err_bit_idx = 7'd0;
        end else if (any_parity_match) begin
            comb_err_bit_idx = 7'(TMEM_ECC_DATA_W) + {4'd0, parity_match_idx};
        end else begin
            comb_err_bit_idx = {1'b0, data_match_byte_idx, data_match_bit_in_byte};
        end

        verify_syndrome = tmem_ecc_syndrome(corr_codeword);
    end

    `UNUSED_VAR (syndrome_wt_is_1)
    `UNUSED_VAR (syndrome_wt_is_3_or_5)
    `UNUSED_VAR (syndrome_wt_is_even_nz)
    `UNUSED_VAR (verify_syndrome)

    // Decoder event counters for diagnostics
    logic [31:0] dec_ops_q;
    logic [31:0] dec_ce_q;
    logic [31:0] dec_ue_q;
    logic [31:0] dec_par_ce_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            dec_ops_q    <= 32'd0;
            dec_ce_q     <= 32'd0;
            dec_ue_q     <= 32'd0;
            dec_par_ce_q <= 32'd0;
        end else begin
            if (valid_in) begin
                dec_ops_q <= dec_ops_q + 32'd1;
            end
            if (comb_ce) begin
                dec_ce_q <= dec_ce_q + 32'd1;
            end
            if (comb_ue) begin
                dec_ue_q <= dec_ue_q + 32'd1;
            end
            if (comb_err_in_parity) begin
                dec_par_ce_q <= dec_par_ce_q + 32'd1;
            end
        end
    end

    `UNUSED_VAR (dec_ops_q)
    `UNUSED_VAR (dec_ce_q)
    `UNUSED_VAR (dec_ue_q)
    `UNUSED_VAR (dec_par_ce_q)

    if (PIPE_STAGES == 0) begin : g_comb_out
        assign valid_out         = valid_in;
        assign data_out          = corr_data;
        assign parity_out        = corr_parity;
        assign codeword_out      = corr_codeword;
        assign syndrome_out      = syndrome;
        assign ce_out            = comb_ce;
        assign ue_out            = comb_ue;
        assign err_in_parity_out = comb_err_in_parity;
        assign err_bit_idx_out   = comb_err_bit_idx;
    end else begin : g_reg_out
        logic                         valid_q;
        logic [TMEM_ECC_DATA_W-1:0]   data_q;
        logic [TMEM_ECC_PARITY_W-1:0] parity_q;
        logic [TMEM_ECC_CODE_W-1:0]   codeword_q;
        logic [TMEM_ECC_PARITY_W-1:0] syndrome_q;
        logic                         ce_q;
        logic                         ue_q;
        logic                         err_in_parity_q;
        logic [6:0]                   err_bit_idx_q;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_q         <= 1'b0;
                data_q          <= '0;
                parity_q        <= '0;
                codeword_q      <= '0;
                syndrome_q      <= '0;
                ce_q            <= 1'b0;
                ue_q            <= 1'b0;
                err_in_parity_q <= 1'b0;
                err_bit_idx_q   <= 7'd0;
            end else begin
                valid_q         <= valid_in;
                data_q          <= corr_data;
                parity_q        <= corr_parity;
                codeword_q      <= corr_codeword;
                syndrome_q      <= syndrome;
                ce_q            <= comb_ce;
                ue_q            <= comb_ue;
                err_in_parity_q <= comb_err_in_parity;
                err_bit_idx_q   <= comb_err_bit_idx;
            end
        end

        assign valid_out         = valid_q;
        assign data_out          = data_q;
        assign parity_out        = parity_q;
        assign codeword_out      = codeword_q;
        assign syndrome_out      = syndrome_q;
        assign ce_out            = ce_q;
        assign ue_out            = ue_q;
        assign err_in_parity_out = err_in_parity_q;
        assign err_bit_idx_out   = err_bit_idx_q;
    end

endmodule
