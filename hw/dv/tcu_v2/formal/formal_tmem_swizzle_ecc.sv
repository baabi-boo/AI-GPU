// SPDX-License-Identifier: Apache-2.0
module VX_tmem_formal_swizzle_ecc
    import VX_tmem_pkg::*;
#(
    parameter int LANES = 8
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Symbolic inputs for exhaustive swizzle bijection proof
    input  logic [TMEM_ROW_W-1:0]                   sym_row_a,
    input  logic [TMEM_COL_W-1:0]                   sym_col_a,
    input  logic [TMEM_ROW_W-1:0]                   sym_row_b,
    input  logic [TMEM_COL_W-1:0]                   sym_col_b,
    input  tmem_swizzle_e                           sym_swizzle_mode,
    input  logic [LANES-1:0]                        sym_valid_lanes,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        sym_rows_vec,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        sym_cols_vec,
    // Symbolic inputs for SECDED(72,64) ECC proof
    input  logic [TMEM_ECC_DATA_W-1:0]              sym_ecc_data,
    input  logic [6:0]                              sym_err_bit_1,
    input  logic [6:0]                              sym_err_bit_2,
    input  logic [1:0]                              sym_err_mode, // 0=0bit, 1=1bit, 2=2bit
    output logic                                    formal_ok_out
);

    // -------------------------------------------------------------------------
    // 1. Instantiate Dual Swizzle Address Translators (Lane 0 = A, Lane 1 = B)
    // -------------------------------------------------------------------------
    logic [LANES-1:0][TMEM_ROW_W-1:0]       swz_rows_in;
    logic [LANES-1:0][TMEM_COL_W-1:0]       swz_cols_in;
    logic [LANES-1:0]                       swz_valid_out;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]   swz_bank_out;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0] swz_word_out;
    logic [LANES-1:0]                       swz_half_out;
    logic [LANES-1:0]                       swz_oob_out;
    logic [LANES-1:0][TMEM_ROW_W-1:0]       swz_inv_row_out;
    logic [LANES-1:0][TMEM_COL_W-1:0]       swz_inv_col_out;
    logic [LANES-1:0]                       swz_bijection_ok_out;
    logic [31:0]                            swz_ops_count;

    always_comb begin
        swz_rows_in    = sym_rows_vec;
        swz_cols_in    = sym_cols_vec;
        swz_rows_in[0] = sym_row_a;
        swz_cols_in[0] = sym_col_a;
        swz_rows_in[1] = sym_row_b;
        swz_cols_in[1] = sym_col_b;
    end

    VX_tmem_swizzle_addr #(
        .LANES (LANES)
    ) u_swizzle_dut (
        .clk               (clk),
        .reset             (reset),
        .pipe_en           (1'b0),
        .valid_in          (sym_valid_lanes | {{(LANES-2){1'b0}}, 2'b11}),
        .row_in            (swz_rows_in),
        .col_in            (swz_cols_in),
        .swizzle_mode      (sym_swizzle_mode),
        .inv_enable        (1'b0),
        .inv_bank_in       ('0),
        .inv_word_in       ('0),
        .inv_half_in       ('0),
        .valid_out         (swz_valid_out),
        .bank_id_out       (swz_bank_out),
        .word_addr_out     (swz_word_out),
        .half_sel_out      (swz_half_out),
        .addr_oob_out      (swz_oob_out),
        .inv_row_out       (swz_inv_row_out),
        .inv_col_out       (swz_inv_col_out),
        .bijection_ok_out  (swz_bijection_ok_out),
        .swizzle_ops_count (swz_ops_count)
    );

    // -------------------------------------------------------------------------
    // 2. Instantiate SECDED(72,64) Encoder & 3 Parallel Decoders (0-bit, 1-bit, 2-bit)
    // -------------------------------------------------------------------------
    logic                         enc_valid_out;
    logic [TMEM_ECC_PARITY_W-1:0] enc_parity_out;
    logic [TMEM_ECC_CODE_W-1:0]   enc_codeword_out;
    logic                         enc_inj_active_out;

    VX_tmem_ecc_enc #(
        .PIPE_STAGES (0)
    ) u_ecc_enc_dut (
        .clk            (clk),
        .reset          (reset),
        .valid_in       (1'b1),
        .data_in        (sym_ecc_data),
        .fault_inj_en   (1'b0),
        .fault_inj_mask (72'd0),
        .valid_out      (enc_valid_out),
        .parity_out     (enc_parity_out),
        .codeword_out   (enc_codeword_out),
        .inj_active_out (enc_inj_active_out)
    );

    // Construct explicit 0-bit, 1-bit, and 2-bit error masks over [0..71]
    logic [TMEM_ECC_CODE_W-1:0] mask_0bit;
    logic [TMEM_ECC_CODE_W-1:0] mask_1bit;
    logic [TMEM_ECC_CODE_W-1:0] mask_2bit;
    logic [TMEM_ECC_CODE_W-1:0] mask_muxed;
    logic [6:0]                 bit1_bounded;
    logic [6:0]                 bit2_bounded;

    assign bit1_bounded = (sym_err_bit_1 < 7'd72) ? sym_err_bit_1 : (sym_err_bit_1 - 7'd72);
    assign bit2_bounded = (sym_err_bit_2 < 7'd72) ? sym_err_bit_2 : (sym_err_bit_2 - 7'd72);
    assign mask_0bit    = 72'd0;
    assign mask_1bit    = (72'd1 << bit1_bounded);
    assign mask_2bit    = (72'd1 << bit1_bounded) | (72'd1 << bit2_bounded);

    always_comb begin
        case (sym_err_mode)
            2'd0:    mask_muxed = mask_0bit;
            2'd1:    mask_muxed = mask_1bit;
            default: mask_muxed = mask_2bit;
        endcase
    end

    // Also instantiate encoder with fault injection active to verify fault_inj_en path
    logic [TMEM_ECC_CODE_W-1:0]   enc_inj_codeword;
    logic                         enc_inj_flag;
    VX_tmem_ecc_enc #(
        .PIPE_STAGES (0)
    ) u_ecc_enc_inj_dut (
        .clk            (clk),
        .reset          (reset),
        .valid_in       (1'b1),
        .data_in        (sym_ecc_data),
        .fault_inj_en   (1'b1),
        .fault_inj_mask (mask_muxed),
        .valid_out      (),
        .parity_out     (),
        .codeword_out   (enc_inj_codeword),
        .inj_active_out (enc_inj_flag)
    );

    // Decoder 0: clean 0-bit flip codeword
    logic                         dec0_valid;
    logic [TMEM_ECC_DATA_W-1:0]   dec0_data;
    logic [TMEM_ECC_PARITY_W-1:0] dec0_parity;
    logic [TMEM_ECC_CODE_W-1:0]   dec0_cw;
    logic [TMEM_ECC_PARITY_W-1:0] dec0_syn;
    logic                         dec0_ce, dec0_ue, dec0_eip;
    logic [6:0]                   dec0_idx;

    VX_tmem_ecc_dec #(
        .PIPE_STAGES (0)
    ) u_ecc_dec_0bit (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (1'b1),
        .codeword_in       (enc_codeword_out),
        .valid_out         (dec0_valid),
        .data_out          (dec0_data),
        .parity_out        (dec0_parity),
        .codeword_out      (dec0_cw),
        .syndrome_out      (dec0_syn),
        .ce_out            (dec0_ce),
        .ue_out            (dec0_ue),
        .err_in_parity_out (dec0_eip),
        .err_bit_idx_out   (dec0_idx)
    );

    // Decoder 1: single-bit flip at ANY bit [0..71]
    logic                         dec1_valid;
    logic [TMEM_ECC_DATA_W-1:0]   dec1_data;
    logic [TMEM_ECC_PARITY_W-1:0] dec1_parity;
    logic [TMEM_ECC_CODE_W-1:0]   dec1_cw;
    logic [TMEM_ECC_PARITY_W-1:0] dec1_syn;
    logic                         dec1_ce, dec1_ue, dec1_eip;
    logic [6:0]                   dec1_idx;

    VX_tmem_ecc_dec #(
        .PIPE_STAGES (0)
    ) u_ecc_dec_1bit (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (1'b1),
        .codeword_in       (enc_codeword_out ^ mask_1bit),
        .valid_out         (dec1_valid),
        .data_out          (dec1_data),
        .parity_out        (dec1_parity),
        .codeword_out      (dec1_cw),
        .syndrome_out      (dec1_syn),
        .ce_out            (dec1_ce),
        .ue_out            (dec1_ue),
        .err_in_parity_out (dec1_eip),
        .err_bit_idx_out   (dec1_idx)
    );

    // Decoder 2: double-bit flip at ANY distinct (bit1 != bit2) in [0..71]
    logic                         dec2_valid;
    logic [TMEM_ECC_DATA_W-1:0]   dec2_data;
    logic [TMEM_ECC_PARITY_W-1:0] dec2_parity;
    logic [TMEM_ECC_CODE_W-1:0]   dec2_cw;
    logic [TMEM_ECC_PARITY_W-1:0] dec2_syn;
    logic                         dec2_ce, dec2_ue, dec2_eip;
    logic [6:0]                   dec2_idx;

    VX_tmem_ecc_dec #(
        .PIPE_STAGES (0)
    ) u_ecc_dec_2bit (
        .clk               (clk),
        .reset             (reset),
        .valid_in          (1'b1),
        .codeword_in       (enc_codeword_out ^ mask_2bit),
        .valid_out         (dec2_valid),
        .data_out          (dec2_data),
        .parity_out        (dec2_parity),
        .codeword_out      (dec2_cw),
        .syndrome_out      (dec2_syn),
        .ce_out            (dec2_ce),
        .ue_out            (dec2_ue),
        .err_in_parity_out (dec2_eip),
        .err_bit_idx_out   (dec2_idx)
    );

    assign formal_ok_out = (&swz_bijection_ok_out) && !dec0_ce && !dec0_ue &&
                           dec1_ce && !dec1_ue && (dec1_data == sym_ecc_data);

    // -------------------------------------------------------------------------
    // Exhaustive Symbolic Formal Proofs & Reachability Covers
    // -------------------------------------------------------------------------
`ifdef FORMAL
    always @(posedge clk) begin
        // --- 1. TMEM Swizzle Address Bijection & Range Proofs ---
        for (int l = 0; l < LANES; ++l) begin
            // Range [0..31] and no OOB for valid 7-bit row / 9-bit col
            if (l < 2) begin
                assert (swz_valid_out[l]);
            end else begin
                assert (swz_valid_out[l] == sym_valid_lanes[l]);
            end
            assert (!swz_oob_out[l]);
            assert (int'(swz_bank_out[l]) < TMEM_NUM_BANKS);
            assert (int'(swz_word_out[l]) < TMEM_BANK_DEPTH_WORDS);
            assert (swz_bijection_ok_out[l]);

            // Exact forward-then-inverse roundtrip for ALL (row, col, mode)
            assert (swz_inv_row_out[l] == swz_rows_in[l]);
            assert (swz_inv_col_out[l] == swz_cols_in[l]);
            assert (swz_bank_out[l] == tmem_swizzled_bank(swz_rows_in[l], swz_cols_in[l], sym_swizzle_mode));
        end

        // Same-row distinct col_low bijection:
        // For ANY row [0..127], ANY mode [0..3], ANY col_a[4:0] != col_b[4:0],
        // swizzled_bank(row, col_a, mode) != swizzled_bank(row, col_b, mode)
        if ((sym_row_a == sym_row_b) && (sym_col_a[4:0] != sym_col_b[4:0])) begin
            assert (swz_bank_out[0] != swz_bank_out[1]);
        end

        // Full 65,536-cell physical coordinate bijection:
        // Distinct logical (row, col) NEVER collide on physical (bank_id, word_addr, half_sel)
        if ((sym_row_a != sym_row_b) || (sym_col_a != sym_col_b)) begin
            assert ((swz_bank_out[0] != swz_bank_out[1]) ||
                    (swz_word_out[0] != swz_word_out[1]) ||
                    (swz_half_out[0] != swz_half_out[1]));
        end

        // --- 2. SECDED(72,64) ECC Proofs ---
        assert (enc_valid_out);
        assert (!enc_inj_active_out);
        assert (enc_codeword_out == {enc_parity_out, sym_ecc_data});
        assert (enc_inj_codeword == (enc_codeword_out ^ mask_muxed));
        assert (enc_inj_flag == (mask_muxed != 72'd0));

        // 0-bit error: data_out == data_in, ce=0, ue=0, syndrome=0
        assert (dec0_valid);
        assert (dec0_data == sym_ecc_data);
        assert (dec0_parity == enc_parity_out);
        assert (dec0_cw == enc_codeword_out);
        assert (dec0_syn == 8'd0);
        assert (!dec0_ce && !dec0_ue && !dec0_eip);
        assert (dec0_idx == 7'd0);

        // 1-bit error at ANY bit [0..71]: data_out == data_in, ce=1, ue=0, exact bit index
        assert (dec1_valid);
        assert (dec1_data == sym_ecc_data);
        assert (dec1_parity == enc_parity_out);
        assert (dec1_cw == enc_codeword_out);
        assert (dec1_ce == 1'b1);
        assert (dec1_ue == 1'b0);
        assert (dec1_syn != 8'd0);
        dec1_err_in_parity_match: assert (dec1_eip == (bit1_bounded >= 7'd64));
        assert (dec1_idx == bit1_bounded);

        // 2-bit error at ANY distinct (b1 != b2) in [0..71]: ue=1, ce=0
        if (bit1_bounded != bit2_bounded) begin
            assert (dec2_valid);
            assert (dec2_ue == 1'b1);
            assert (dec2_ce == 1'b0);
            assert (dec2_syn != 8'd0);
            assert (!(dec2_ce && dec2_ue));
        end

        // --- Reachability Covers ---
        cover ((sym_swizzle_mode == TMEM_SWIZZLE_NONE) && (sym_row_a != sym_row_b) && (swz_bank_out[0] == swz_bank_out[1]));
        cover ((sym_swizzle_mode == TMEM_SWIZZLE_32B)  && (sym_row_a[2:0] != 3'd0) && (swz_bank_out[0] != sym_col_a[4:0]));
        cover ((sym_swizzle_mode == TMEM_SWIZZLE_64B)  && (sym_row_a[3] == 1'b1) && (swz_bank_out[0] != sym_col_a[4:0]));
        cover ((sym_swizzle_mode == TMEM_SWIZZLE_128B) && (sym_row_a[4] == 1'b1) && (swz_bank_out[0] != sym_col_a[4:0]));
        cover ((bit1_bounded < 7'd64) && dec1_ce && !dec1_eip && (dec1_data == sym_ecc_data));
        cover ((bit1_bounded >= 7'd64) && dec1_ce && dec1_eip && (dec1_data == sym_ecc_data));
        cover ((bit1_bounded != bit2_bounded) && dec2_ue && !dec2_ce && (sym_ecc_data != 64'd0));
        cover ((sym_err_mode == 2'd2) && enc_inj_flag);
    end
`endif

endmodule
