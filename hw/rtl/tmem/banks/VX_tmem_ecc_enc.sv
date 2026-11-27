// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_ecc_enc #(
    parameter int PIPE_STAGES = 0
) (
    input  logic                                      clk,
    input  logic                                      reset,
    input  logic                                      valid_in,
    input  logic [VX_tmem_pkg::TMEM_ECC_DATA_W-1:0]   data_in,
    input  logic                                      fault_inj_en,
    input  logic [VX_tmem_pkg::TMEM_ECC_CODE_W-1:0]   fault_inj_mask,
    output logic                                      valid_out,
    output logic [VX_tmem_pkg::TMEM_ECC_PARITY_W-1:0] parity_out,
    output logic [VX_tmem_pkg::TMEM_ECC_CODE_W-1:0]   codeword_out,
    output logic                                      inj_active_out
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(TMEM_ECC_DATA_W == 64, ("Hsiao(72,64) requires 64 data bits"))
    `STATIC_ASSERT(TMEM_ECC_PARITY_W == 8, ("Hsiao(72,64) requires 8 parity bits"))
    `STATIC_ASSERT(TMEM_ECC_CODE_W == 72, ("Hsiao(72,64) requires 72 codeword bits"))
    `STATIC_ASSERT((PIPE_STAGES == 0) || (PIPE_STAGES == 1), ("PIPE_STAGES must be 0 or 1"))

    // Balanced multi-level XOR reduction tree over 64-bit masked data:
    // Level 1 reduces 32 pairs (2-input XORs)
    // Level 2 reduces 16 nibbles (2-input XORs over Level 1)
    // Level 3 reduces 4 quads (4-input XORs over Level 2)
    // Level 4 reduces 4 quadrant bits -> 1 parity bit
    logic [TMEM_ECC_PARITY_W-1:0][31:0] xor_lvl1_pair;
    logic [TMEM_ECC_PARITY_W-1:0][15:0] xor_lvl2_nibble;
    logic [TMEM_ECC_PARITY_W-1:0][3:0]  xor_lvl3_quad;
    logic [TMEM_ECC_PARITY_W-1:0]       raw_parity;
    logic [TMEM_ECC_PARITY_W-1:0]       data_byte_parity;
    logic [TMEM_ECC_PARITY_W-1:0]       overall_byte_par;
    logic [TMEM_ECC_PARITY_W-1:0]       parity_by_pkg_fn;
    logic                               parity_check_match;
    logic [TMEM_ECC_CODE_W-1:0]         clean_codeword;
    logic [TMEM_ECC_CODE_W-1:0]         eff_inj_mask;
    logic [TMEM_ECC_CODE_W-1:0]         injected_codeword;
    logic [TMEM_ECC_PARITY_W-1:0]       injected_parity;
    logic [TMEM_ECC_DATA_W-1:0]         injected_data;

    // Precompute per-byte parity of input data and output data
    for (genvar g_byte = 0; g_byte < TMEM_BANK_WIDTH_BYTES; ++g_byte) begin : g_byte_par
        logic [7:0] in_byte_slice;
        logic [7:0] out_byte_slice;

        always_comb begin
            in_byte_slice            = data_in[g_byte*8 +: 8];
            out_byte_slice           = injected_data[g_byte*8 +: 8];
            data_byte_parity[g_byte] = ^in_byte_slice;
            overall_byte_par[g_byte] = ^out_byte_slice;
        end
    end

    `UNUSED_VAR (data_byte_parity)
    `UNUSED_VAR (overall_byte_par)

    for (genvar g_p = 0; g_p < TMEM_ECC_PARITY_W; ++g_p) begin : g_parity_bit
        logic [TMEM_ECC_DATA_W-1:0] masked_data;

        always_comb begin
            masked_data = data_in & TMEM_HSIAO_P_MATRIX[g_p];
            for (int pair_i = 0; pair_i < 32; ++pair_i) begin
                xor_lvl1_pair[g_p][pair_i] = ^masked_data[pair_i*2 +: 2];
            end
            for (int nib_i = 0; nib_i < 16; ++nib_i) begin
                xor_lvl2_nibble[g_p][nib_i] = ^xor_lvl1_pair[g_p][nib_i*2 +: 2];
            end
            for (int q_i = 0; q_i < 4; ++q_i) begin
                xor_lvl3_quad[g_p][q_i] = ^xor_lvl2_nibble[g_p][q_i*4 +: 4];
            end
            raw_parity[g_p] = ^xor_lvl3_quad[g_p];
        end
    end

    // Fault-injection classification (single-bit vs double-bit vs multi-bit diagnostics)
    logic       inj_valid;
    logic [6:0] inj_bit_weight;
    logic       inj_targets_data;
    logic       inj_targets_parity;
    logic       inj_is_single_bit;
    logic       inj_is_double_bit;
    logic       inj_is_multi_bit;
    logic [6:0] inj_first_bit_idx;
    logic [6:0] inj_last_bit_idx;
    logic       clean_all_zero;

    function automatic logic [6:0] popcount_72(
        input logic [TMEM_ECC_CODE_W-1:0] vec
    );
        logic [6:0] total_ones;
        total_ones = 7'd0;
        for (int b = 0; b < TMEM_ECC_CODE_W; ++b) begin
            if (vec[b]) begin
                total_ones = total_ones + 7'd1;
            end
        end
        return total_ones;
    endfunction

    always_comb begin
        clean_codeword     = {raw_parity, data_in};
        parity_by_pkg_fn   = tmem_ecc_parity(data_in);
        parity_check_match = (raw_parity == parity_by_pkg_fn);
        clean_all_zero     = (data_in == 64'd0) && (raw_parity == 8'd0);

        eff_inj_mask       = fault_inj_en ? fault_inj_mask : {TMEM_ECC_CODE_W{1'b0}};
        injected_codeword  = clean_codeword ^ eff_inj_mask;
        injected_data      = injected_codeword[TMEM_ECC_DATA_W-1:0];
        injected_parity    = injected_codeword[TMEM_ECC_CODE_W-1:TMEM_ECC_DATA_W];

        inj_valid          = valid_in && fault_inj_en && (|fault_inj_mask);
        inj_bit_weight     = popcount_72(eff_inj_mask);
        inj_targets_data   = fault_inj_en && (|eff_inj_mask[TMEM_ECC_DATA_W-1:0]);
        inj_targets_parity = fault_inj_en && (|eff_inj_mask[TMEM_ECC_CODE_W-1:TMEM_ECC_DATA_W]);
        inj_is_single_bit  = inj_valid && (inj_bit_weight == 7'd1);
        inj_is_double_bit  = inj_valid && (inj_bit_weight == 7'd2);
        inj_is_multi_bit   = inj_valid && (inj_bit_weight > 7'd2);

        inj_first_bit_idx = 7'd0;
        inj_last_bit_idx  = 7'd0;
        for (int b = 0; b < TMEM_ECC_CODE_W; ++b) begin
            if (eff_inj_mask[b]) begin
                inj_last_bit_idx = 7'(b);
            end
        end
        for (int b = TMEM_ECC_CODE_W - 1; b >= 0; --b) begin
            if (eff_inj_mask[b]) begin
                inj_first_bit_idx = 7'(b);
            end
        end
    end

    `UNUSED_VAR (parity_check_match)
    `UNUSED_VAR (clean_all_zero)
    `UNUSED_VAR (inj_bit_weight)
    `UNUSED_VAR (inj_targets_data)
    `UNUSED_VAR (inj_targets_parity)
    `UNUSED_VAR (inj_is_single_bit)
    `UNUSED_VAR (inj_is_double_bit)
    `UNUSED_VAR (inj_is_multi_bit)
    `UNUSED_VAR (inj_first_bit_idx)
    `UNUSED_VAR (inj_last_bit_idx)

    // Optional output pipeline register and encoder telemetry counters
    logic [31:0] enc_ops_q;
    logic [31:0] enc_inj_q;
    logic [31:0] enc_sbe_inj_q;
    logic [31:0] enc_dbe_inj_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            enc_ops_q     <= 32'd0;
            enc_inj_q     <= 32'd0;
            enc_sbe_inj_q <= 32'd0;
            enc_dbe_inj_q <= 32'd0;
        end else begin
            if (valid_in) begin
                enc_ops_q <= enc_ops_q + 32'd1;
            end
            if (inj_valid) begin
                enc_inj_q <= enc_inj_q + 32'd1;
            end
            if (inj_is_single_bit) begin
                enc_sbe_inj_q <= enc_sbe_inj_q + 32'd1;
            end
            if (inj_is_double_bit) begin
                enc_dbe_inj_q <= enc_dbe_inj_q + 32'd1;
            end
        end
    end

    `UNUSED_VAR (enc_ops_q)
    `UNUSED_VAR (enc_inj_q)
    `UNUSED_VAR (enc_sbe_inj_q)
    `UNUSED_VAR (enc_dbe_inj_q)

    if (PIPE_STAGES == 0) begin : g_comb_out
        assign valid_out      = valid_in;
        assign parity_out     = injected_parity;
        assign codeword_out   = injected_codeword;
        assign inj_active_out = inj_valid;
    end else begin : g_reg_out
        logic                         valid_q;
        logic [TMEM_ECC_PARITY_W-1:0] parity_q;
        logic [TMEM_ECC_CODE_W-1:0]   codeword_q;
        logic                         inj_active_q;

        always_ff @(posedge clk) begin
            if (reset) begin
                valid_q      <= 1'b0;
                parity_q     <= '0;
                codeword_q   <= '0;
                inj_active_q <= 1'b0;
            end else begin
                valid_q      <= valid_in;
                parity_q     <= injected_parity;
                codeword_q   <= injected_codeword;
                inj_active_q <= inj_valid;
            end
        end

        assign valid_out      = valid_q;
        assign parity_out     = parity_q;
        assign codeword_out   = codeword_q;
        assign inj_active_out = inj_active_q;
    end

endmodule
