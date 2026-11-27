// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_swizzle_addr #(
    parameter int LANES = 8
) (
    input  logic                                            clk,
    input  logic                                            reset,
    input  logic                                            pipe_en,
    input  logic [LANES-1:0]                                valid_in,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_ROW_W-1:0]   row_in,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_COL_W-1:0]   col_in,
    input  VX_tmem_pkg::tmem_swizzle_e                      swizzle_mode,
    input  logic                                            inv_enable,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]   inv_bank_in,
    input  logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] inv_word_in,
    input  logic [LANES-1:0]                                inv_half_in,
    output logic [LANES-1:0]                                valid_out,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ID_W-1:0]   bank_id_out,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_BANK_ADDR_W-1:0] word_addr_out,
    output logic [LANES-1:0]                                half_sel_out,
    output logic [LANES-1:0]                                addr_oob_out,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_ROW_W-1:0]   inv_row_out,
    output logic [LANES-1:0][VX_tmem_pkg::TMEM_COL_W-1:0]   inv_col_out,
    output logic [LANES-1:0]                                bijection_ok_out,
    output logic [31:0]                                     swizzle_ops_count
);
    import VX_tmem_pkg::*;

    `STATIC_ASSERT(LANES >= 1, ("LANES must be at least 1"))
    `STATIC_ASSERT(TMEM_NUM_BANKS == 32, ("Expected 32 banks"))
    `STATIC_ASSERT(TMEM_BANK_DEPTH_WORDS == 1024, ("Expected 1024 words per bank"))

    // Combinational forward swizzle, inverse swizzle, and bounds checking per lane
    logic [LANES-1:0]                        comb_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    comb_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  comb_word_addr;
    logic [LANES-1:0]                        comb_half_sel;
    logic [LANES-1:0]                        comb_addr_oob;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        comb_inv_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        comb_inv_col;
    logic [LANES-1:0]                        comb_bijection_ok;

    function automatic logic [4:0] compute_swizzle_mask(
        input logic [TMEM_ROW_W-1:0] row,
        input tmem_swizzle_e         mode
    );
        logic [4:0] mask;
        logic       unused_row_zero;
        unused_row_zero = &{1'b0, row[6:5]};
        if (unused_row_zero) begin
            mask = 5'd0;
        end else begin
            case (mode)
                TMEM_SWIZZLE_NONE: mask = 5'd0;
                TMEM_SWIZZLE_32B:  mask = {2'b00, row[2:0]};
                TMEM_SWIZZLE_64B:  mask = {1'b0, row[3:0]};
                TMEM_SWIZZLE_128B: mask = row[4:0];
                default:           mask = 5'd0;
            endcase
        end
        return mask;
    endfunction

    function automatic logic [4:0] compute_forward_bank(
        input logic [TMEM_ROW_W-1:0] row,
        input logic [TMEM_COL_W-1:0] col,
        input tmem_swizzle_e         mode
    );
        logic [4:0] base_bank;
        logic [4:0] xor_mask;
        logic       unused_col_zero;
        unused_col_zero = &{1'b0, col[8:5]};
        base_bank       = col[4:0];
        xor_mask        = compute_swizzle_mask(row, mode);
        if (unused_col_zero) begin
            return base_bank;
        end else begin
            return base_bank ^ xor_mask;
        end
    endfunction

    function automatic logic [TMEM_COL_W-1:0] compute_inverse_col(
        input logic [TMEM_BANK_ADDR_W-1:0] word_addr,
        input logic [TMEM_BANK_ID_W-1:0]   bank_id,
        input logic                        half_sel,
        input tmem_swizzle_e               mode
    );
        logic [TMEM_ROW_W-1:0] row_rec;
        logic [4:0]            xor_mask;
        logic [4:0]            col_low;
        row_rec  = word_addr[9:3];
        xor_mask = compute_swizzle_mask(row_rec, mode);
        col_low  = bank_id ^ xor_mask;
        return {word_addr[2:0], half_sel, col_low};
    endfunction

    // Linear cell addressing, granule classification, and atom alignment per lane
    logic [LANES-1:0][15:0] lane_linear_cell_idx;
    logic [LANES-1:0][17:0] lane_byte_offset;
    logic [LANES-1:0][4:0]  lane_swizzle_atom_id;
    logic [LANES-1:0][3:0]  lane_alloc_granule_id;
    logic [LANES-1:0][1:0]  lane_col_tile_quad;
    logic [LANES-1:0][2:0]  lane_row_stripe_id;
    logic [LANES-1:0]       lane_is_even_row;
    logic [LANES-1:0]       lane_is_even_col;
    logic [LANES-1:0]       lane_is_64b_aligned;

    for (genvar g_i = 0; g_i < LANES; ++g_i) begin : g_swizzle_lane
        logic [TMEM_ROW_W-1:0]       lane_row;
        logic [TMEM_COL_W-1:0]       lane_col;
        logic [TMEM_BANK_ID_W-1:0]   fwd_bank;
        logic [TMEM_BANK_ADDR_W-1:0] fwd_word;
        logic                        fwd_half;
        logic                        row_oob;
        logic                        col_oob;
        logic                        bank_oob;
        logic                        word_oob;
        logic [TMEM_ROW_W-1:0]       rev_row_from_inv;
        logic [TMEM_COL_W-1:0]       rev_col_from_inv;
        logic [TMEM_COL_W-1:0]       roundtrip_col;
        logic [TMEM_ROW_W-1:0]       roundtrip_row;
        logic [TMEM_BANK_ID_W-1:0]   inv_target_bank;
        logic [TMEM_BANK_ADDR_W-1:0] inv_target_word;
        logic                        inv_target_half;

        always_comb begin
            lane_row = row_in[g_i];
            lane_col = col_in[g_i];

            fwd_bank = compute_forward_bank(lane_row, lane_col, swizzle_mode);
            fwd_word = {lane_row[6:0], lane_col[8:6]};
            fwd_half = lane_col[5];

            // Bounds checks against configured TMEM capacity constants
            row_oob  = ({1'b0, lane_row} >= 8'(TMEM_LANES_ROWS));
            col_oob  = ({1'b0, lane_col} >= 10'(TMEM_COLUMNS));
            bank_oob = ({1'b0, fwd_bank} >= 6'(TMEM_NUM_BANKS));
            word_oob = ({1'b0, fwd_word} >= 11'(TMEM_BANK_DEPTH_WORDS));

            // Select either external physical address or internal forward mapping for inverse check
            if (inv_enable) begin
                inv_target_bank = inv_bank_in[g_i];
                inv_target_word = inv_word_in[g_i];
                inv_target_half = inv_half_in[g_i];
            end else begin
                inv_target_bank = fwd_bank;
                inv_target_word = fwd_word;
                inv_target_half = fwd_half;
            end

            rev_row_from_inv = inv_target_word[9:3];
            rev_col_from_inv = compute_inverse_col(
                inv_target_word,
                inv_target_bank,
                inv_target_half,
                swizzle_mode
            );

            roundtrip_row = fwd_word[9:3];
            roundtrip_col = compute_inverse_col(fwd_word, fwd_bank, fwd_half, swizzle_mode);

            comb_valid[g_i]        = valid_in[g_i];
            comb_bank_id[g_i]      = fwd_bank;
            comb_word_addr[g_i]    = fwd_word;
            comb_half_sel[g_i]     = fwd_half;
            comb_addr_oob[g_i]     = row_oob || col_oob || bank_oob || word_oob;
            comb_inv_row[g_i]      = rev_row_from_inv;
            comb_inv_col[g_i]      = rev_col_from_inv;
            comb_bijection_ok[g_i] = (roundtrip_row == lane_row) &&
                                     (roundtrip_col == lane_col) &&
                                     (fwd_bank == tmem_swizzled_bank(lane_row, lane_col, swizzle_mode)) &&
                                     (fwd_word == tmem_bank_word_addr(lane_row, lane_col)) &&
                                     (fwd_half == tmem_cell_half_sel(lane_col));

            lane_linear_cell_idx[g_i]  = {lane_row, lane_col};
            lane_byte_offset[g_i]      = {lane_row, lane_col, 2'b00};
            lane_alloc_granule_id[g_i] = lane_col[8:5];
            lane_col_tile_quad[g_i]    = lane_col[8:7];
            lane_row_stripe_id[g_i]    = lane_row[6:4];
            lane_is_even_row[g_i]      = ~lane_row[0];
            lane_is_even_col[g_i]      = ~lane_col[0];
            lane_is_64b_aligned[g_i]   = (lane_col[0] == 1'b0);

            case (swizzle_mode)
                TMEM_SWIZZLE_NONE: lane_swizzle_atom_id[g_i] = 5'd0;
                TMEM_SWIZZLE_32B:  lane_swizzle_atom_id[g_i] = {2'b00, lane_row[2:0]};
                TMEM_SWIZZLE_64B:  lane_swizzle_atom_id[g_i] = {1'b0, lane_row[3:0]};
                TMEM_SWIZZLE_128B: lane_swizzle_atom_id[g_i] = lane_row[4:0];
                default:           lane_swizzle_atom_id[g_i] = 5'd0;
            endcase
        end
    end

    `UNUSED_VAR (lane_linear_cell_idx)
    `UNUSED_VAR (lane_byte_offset)
    `UNUSED_VAR (lane_swizzle_atom_id)
    `UNUSED_VAR (lane_alloc_granule_id)
    `UNUSED_VAR (lane_col_tile_quad)
    `UNUSED_VAR (lane_row_stripe_id)
    `UNUSED_VAR (lane_is_even_row)
    `UNUSED_VAR (lane_is_even_col)
    `UNUSED_VAR (lane_is_64b_aligned)

    // Cross-lane uniqueness, stride regularity, and multi-mode conflict-free verification
    logic [LANES-1:0][LANES-1:0] bank_collision_matrix;
    logic [LANES-1:0][LANES-1:0] word_match_matrix;
    logic [LANES-1:0]            lane_shares_bank;
    logic [LANES-1:0]            lane_shares_word;
    logic [3:0]                  distinct_banks_count;
    logic [3:0]                  distinct_granules_count;
    logic                        wavefront_conflict_free;
    logic                        wavefront_contiguous_cols;
    logic                        wavefront_unit_row_stride;
    logic                        wavefront_same_row;
    logic                        wavefront_same_col;
    logic                        wavefront_all_in_bounds;

    // Evaluate all 4 swizzle modes in parallel for advisory optimal-mode recommendation
    logic [3:0][LANES-1:0][TMEM_BANK_ID_W-1:0] alt_mode_bank;
    logic [3:0][3:0]                           alt_mode_max_hits;
    tmem_swizzle_e                             recommended_swizzle_mode;

    for (genvar g_m = 0; g_m < 4; ++g_m) begin : g_alt_mode_eval
        for (genvar g_l = 0; g_l < LANES; ++g_l) begin : g_alt_lane
            always_comb begin
                alt_mode_bank[g_m][g_l] = compute_forward_bank(
                    row_in[g_l],
                    col_in[g_l],
                    tmem_swizzle_e'(g_m)
                );
            end
        end

        always_comb begin
            logic [3:0] best_hits;
            best_hits = 4'd0;
            for (int b = 0; b < TMEM_NUM_BANKS; ++b) begin
                logic [3:0] hit_cnt;
                hit_cnt = 4'd0;
                for (int l = 0; l < LANES; ++l) begin
                    if (valid_in[l] && (alt_mode_bank[g_m][l] == TMEM_BANK_ID_W'(b))) begin
                        hit_cnt = hit_cnt + 4'd1;
                    end
                end
                if (hit_cnt > best_hits) begin
                    best_hits = hit_cnt;
                end
            end
            alt_mode_max_hits[g_m] = best_hits;
        end
    end

    always_comb begin
        logic [3:0] min_conflict;
        recommended_swizzle_mode = TMEM_SWIZZLE_NONE;
        min_conflict             = alt_mode_max_hits[0];
        for (int m = 1; m < 4; ++m) begin
            if (alt_mode_max_hits[m] < min_conflict) begin
                min_conflict             = alt_mode_max_hits[m];
                recommended_swizzle_mode = tmem_swizzle_e'(m);
            end
        end
    end
    `UNUSED_VAR (recommended_swizzle_mode)

    for (genvar g_r = 0; g_r < LANES; ++g_r) begin : g_diag_row
        for (genvar g_c = 0; g_c < LANES; ++g_c) begin : g_diag_col
            assign bank_collision_matrix[g_r][g_c] = (g_r != g_c) &&
                                                     comb_valid[g_r] &&
                                                     comb_valid[g_c] &&
                                                     (comb_bank_id[g_r] == comb_bank_id[g_c]);
            assign word_match_matrix[g_r][g_c]     = bank_collision_matrix[g_r][g_c] &&
                                                     (comb_word_addr[g_r] == comb_word_addr[g_c]);
        end
        assign lane_shares_bank[g_r] = |bank_collision_matrix[g_r];
        assign lane_shares_word[g_r] = |word_match_matrix[g_r];
    end

    always_comb begin
        logic [TMEM_NUM_BANKS-1:0]       bank_hit_bitmap;
        logic [TMEM_NUM_ALLOC_UNITS-1:0] granule_hit_bitmap;

        bank_hit_bitmap         = '0;
        granule_hit_bitmap      = '0;
        distinct_banks_count    = 4'd0;
        distinct_granules_count = 4'd0;

        for (int l = 0; l < LANES; ++l) begin
            if (comb_valid[l]) begin
                bank_hit_bitmap[comb_bank_id[l]]      = 1'b1;
                granule_hit_bitmap[col_in[l][8:5]]    = 1'b1;
            end
        end
        for (int b = 0; b < TMEM_NUM_BANKS; ++b) begin
            if (bank_hit_bitmap[b]) begin
                distinct_banks_count = distinct_banks_count + 4'd1;
            end
        end
        for (int g = 0; g < TMEM_NUM_ALLOC_UNITS; ++g) begin
            if (granule_hit_bitmap[g]) begin
                distinct_granules_count = distinct_granules_count + 4'd1;
            end
        end

        wavefront_conflict_free   = ~(|(lane_shares_bank & (~lane_shares_word)));
        wavefront_contiguous_cols = 1'b1;
        wavefront_unit_row_stride = 1'b1;
        wavefront_same_row        = 1'b1;
        wavefront_same_col        = 1'b1;
        wavefront_all_in_bounds   = ~(|(comb_valid & comb_addr_oob));

        for (int l = 1; l < LANES; ++l) begin
            if (comb_valid[l] && comb_valid[l-1]) begin
                if (({1'b0, col_in[l]} != ({1'b0, col_in[l-1]} + 10'd1)) || (row_in[l] != row_in[l-1])) begin
                    wavefront_contiguous_cols = 1'b0;
                end
                if (({1'b0, row_in[l]} != ({1'b0, row_in[l-1]} + 8'd1)) || (col_in[l] != col_in[l-1])) begin
                    wavefront_unit_row_stride = 1'b0;
                end
                if (row_in[l] != row_in[l-1]) begin
                    wavefront_same_row = 1'b0;
                end
                if (col_in[l] != col_in[l-1]) begin
                    wavefront_same_col = 1'b0;
                end
            end
        end
    end

    `UNUSED_VAR (distinct_banks_count)
    `UNUSED_VAR (distinct_granules_count)
    `UNUSED_VAR (wavefront_conflict_free)
    `UNUSED_VAR (wavefront_contiguous_cols)
    `UNUSED_VAR (wavefront_unit_row_stride)
    `UNUSED_VAR (wavefront_same_row)
    `UNUSED_VAR (wavefront_same_col)
    `UNUSED_VAR (wavefront_all_in_bounds)

    // Optional registered output stage when pipe_en is asserted
    logic [LANES-1:0]                        reg_valid;
    logic [LANES-1:0][TMEM_BANK_ID_W-1:0]    reg_bank_id;
    logic [LANES-1:0][TMEM_BANK_ADDR_W-1:0]  reg_word_addr;
    logic [LANES-1:0]                        reg_half_sel;
    logic [LANES-1:0]                        reg_addr_oob;
    logic [LANES-1:0][TMEM_ROW_W-1:0]        reg_inv_row;
    logic [LANES-1:0][TMEM_COL_W-1:0]        reg_inv_col;
    logic [LANES-1:0]                        reg_bijection_ok;
    logic [31:0]                             ops_cnt_q;
    logic [3:0][31:0]                        swizzle_mode_hist_q;
    logic [31:0]                             oob_events_q;
    logic [31:0]                             bijection_fail_q;

    function automatic logic [3:0] count_active_lanes(
        input logic [LANES-1:0] mask
    );
        logic [3:0] total;
        total = 4'd0;
        for (int idx = 0; idx < LANES; ++idx) begin
            if (mask[idx]) begin
                total = total + 4'd1;
            end
        end
        return total;
    endfunction

    always_ff @(posedge clk) begin
        if (reset) begin
            reg_valid           <= '0;
            reg_bank_id         <= '0;
            reg_word_addr       <= '0;
            reg_half_sel        <= '0;
            reg_addr_oob        <= '0;
            reg_inv_row         <= '0;
            reg_inv_col         <= '0;
            reg_bijection_ok    <= '0;
            ops_cnt_q           <= 32'd0;
            swizzle_mode_hist_q <= '0;
            oob_events_q        <= 32'd0;
            bijection_fail_q    <= 32'd0;
        end else begin
            reg_valid        <= comb_valid;
            reg_bank_id      <= comb_bank_id;
            reg_word_addr    <= comb_word_addr;
            reg_half_sel     <= comb_half_sel;
            reg_addr_oob     <= comb_addr_oob;
            reg_inv_row      <= comb_inv_row;
            reg_inv_col      <= comb_inv_col;
            reg_bijection_ok <= comb_bijection_ok;
            if (|valid_in) begin
                ops_cnt_q <= ops_cnt_q + {28'd0, count_active_lanes(valid_in)};
                swizzle_mode_hist_q[swizzle_mode] <= swizzle_mode_hist_q[swizzle_mode] + 32'd1;
            end
            if (|(comb_valid & comb_addr_oob)) begin
                oob_events_q <= oob_events_q + 32'd1;
            end
            if (|(comb_valid & (~comb_bijection_ok))) begin
                bijection_fail_q <= bijection_fail_q + 32'd1;
            end
        end
    end
    `UNUSED_VAR (swizzle_mode_hist_q)
    `UNUSED_VAR (oob_events_q)
    `UNUSED_VAR (bijection_fail_q)

    always_comb begin
        if (pipe_en) begin
            valid_out        = reg_valid;
            bank_id_out      = reg_bank_id;
            word_addr_out    = reg_word_addr;
            half_sel_out     = reg_half_sel;
            addr_oob_out     = reg_addr_oob;
            inv_row_out      = reg_inv_row;
            inv_col_out      = reg_inv_col;
            bijection_ok_out = reg_bijection_ok;
        end else begin
            valid_out        = comb_valid;
            bank_id_out      = comb_bank_id;
            word_addr_out    = comb_word_addr;
            half_sel_out     = comb_half_sel;
            addr_oob_out     = comb_addr_oob;
            inv_row_out      = comb_inv_row;
            inv_col_out      = comb_inv_col;
            bijection_ok_out = comb_bijection_ok;
        end
    end

    assign swizzle_ops_count = ops_cnt_q;

endmodule
