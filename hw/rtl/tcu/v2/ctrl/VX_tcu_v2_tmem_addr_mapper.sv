// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_tmem_addr_mapper #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                req_valid,
    output logic                                req_ready,
    input  VX_tcu_v2_pkg::tcu_v2_tmem_req_t     tmem_req_in,
    input  logic [1:0]                          swizzle_override_en,
    input  logic [1:0]                          swizzle_override_mode,
    output logic                                mapped_valid,
    input  logic                                mapped_ready,
    output VX_tcu_v2_pkg::tcu_v2_tmem_req_t     mapped_req_out,
    output logic [4:0]                          phys_bank_id_out,
    output logic [9:0]                          phys_word_addr_out,
    output logic                                phys_half_sel_out,
    output logic                                conflict_warn_out,
    output logic                                bounds_err_out,
    output logic [31:0]                         mapped_cnt_out,
    output logic [31:0]                         bank_conflict_cnt_out
);

    import VX_tcu_v2_pkg::*;

    function automatic logic [4:0] swizzle_bank_map(
        input logic [TCU_V2_TMEM_ROW_W-1:0] row,
        input logic [TCU_V2_TMEM_COL_W-1:0] col,
        input logic [1:0]                   mode
    );
        logic [4:0] base_b;
        base_b = col[4:0];
        `UNUSED_VAR (row)
        `UNUSED_VAR (col)
        case (mode)
            2'd0:    return base_b;
            2'd1:    return base_b ^ {2'b00, row[2:0]};
            2'd2:    return base_b ^ {1'b0, row[3:0]};
            2'd3:    return base_b ^ row[4:0];
            default: return base_b;
        endcase
    endfunction

    tcu_v2_tmem_req_t                   eff_req_comb;
    logic [1:0]                         eff_swizzle_comb;
    logic [4:0]                         bank_id_comb;
    logic [9:0]                         word_addr_comb;
    logic                               half_sel_comb;
    logic                               bounds_err_comb;
    logic                               conflict_comb;

    logic                               valid_r;
    tcu_v2_tmem_req_t                   mapped_req_r;
    logic [4:0]                         phys_bank_r;
    logic [9:0]                         phys_word_r;
    logic                               phys_half_r;
    logic                               conflict_r;
    logic                               bounds_err_r;
    logic [4:0]                         prev_bank_r;
    logic                               prev_valid_r;
    logic [31:0]                        mapped_cnt_r;
    logic [31:0]                        conflict_cnt_r;
    logic [31:0]                        bounds_err_cnt_r;
    logic [3:0][31:0]                   swizzle_mode_cnt_r;
    logic [3:0][31:0]                   operand_sel_cnt_r;
    logic [3:0][4:0]                    bank_hist_r;
    logic [3:0]                         bank_hist_valid_r;

    always_comb begin
        logic [9:0] end_col_ext;
        eff_req_comb              = tmem_req_in;
        eff_swizzle_comb          = swizzle_override_en[0] ? swizzle_override_mode : tmem_req_in.swizzle_mode;
        eff_req_comb.swizzle_mode = eff_swizzle_comb;

        bank_id_comb   = swizzle_bank_map(tmem_req_in.row, tmem_req_in.col, eff_swizzle_comb);
        word_addr_comb = {tmem_req_in.row[6:0], tmem_req_in.col[8:6]};
        half_sel_comb  = tmem_req_in.col[5];

        end_col_ext     = {1'b0, tmem_req_in.col} + {2'b00, tmem_req_in.col_count};
        bounds_err_comb = (end_col_ext > 10'd512) || (tmem_req_in.col_count == 8'd0);
        conflict_comb   = prev_valid_r && (bank_id_comb == prev_bank_r);
    end

    `UNUSED_PARAM (ARRAY_M)
    `UNUSED_PARAM (ARRAY_N)
    `UNUSED_PARAM (ARRAY_K)
    `UNUSED_VAR (swizzle_override_en)
    `UNUSED_VAR (bounds_err_cnt_r)
    `UNUSED_VAR (swizzle_mode_cnt_r)
    `UNUSED_VAR (operand_sel_cnt_r)
    `UNUSED_VAR (bank_hist_r)
    `UNUSED_VAR (bank_hist_valid_r)

    assign req_ready = (!valid_r || mapped_ready);

    always_ff @(posedge clk) begin
        if (reset) begin
            valid_r            <= 1'b0;
            mapped_req_r       <= '0;
            phys_bank_r        <= 5'd0;
            phys_word_r        <= 10'd0;
            phys_half_r        <= 1'b0;
            conflict_r         <= 1'b0;
            bounds_err_r       <= 1'b0;
            prev_bank_r        <= 5'd0;
            prev_valid_r       <= 1'b0;
            mapped_cnt_r       <= 32'd0;
            conflict_cnt_r     <= 32'd0;
            bounds_err_cnt_r   <= 32'd0;
            swizzle_mode_cnt_r <= '0;
            operand_sel_cnt_r  <= '0;
            bank_hist_r        <= '0;
            bank_hist_valid_r  <= 4'd0;
        end else if (req_ready) begin
            valid_r <= req_valid;
            if (req_valid) begin
                mapped_req_r <= eff_req_comb;
                phys_bank_r  <= bank_id_comb;
                phys_word_r  <= word_addr_comb;
                phys_half_r  <= half_sel_comb;
                conflict_r   <= conflict_comb;
                bounds_err_r <= bounds_err_comb;
                prev_bank_r  <= bank_id_comb;
                prev_valid_r <= 1'b1;
                mapped_cnt_r <= mapped_cnt_r + 32'd1;
                swizzle_mode_cnt_r[eff_swizzle_comb]    <= swizzle_mode_cnt_r[eff_swizzle_comb] + 32'd1;
                operand_sel_cnt_r[tmem_req_in.operand_sel] <= operand_sel_cnt_r[tmem_req_in.operand_sel] + 32'd1;
                bank_hist_r[0]       <= bank_id_comb;
                bank_hist_r[3:1]     <= bank_hist_r[2:0];
                bank_hist_valid_r    <= {bank_hist_valid_r[2:0], 1'b1};
                if (conflict_comb) begin
                    conflict_cnt_r <= conflict_cnt_r + 32'd1;
                end
                if (bounds_err_comb) begin
                    bounds_err_cnt_r <= bounds_err_cnt_r + 32'd1;
                end
            end
        end
    end

    assign mapped_valid          = valid_r;
    assign mapped_req_out        = mapped_req_r;
    assign phys_bank_id_out      = phys_bank_r;
    assign phys_word_addr_out    = phys_word_r;
    assign phys_half_sel_out     = phys_half_r;
    assign conflict_warn_out     = conflict_r;
    assign bounds_err_out        = bounds_err_r;
    assign mapped_cnt_out        = mapped_cnt_r;
    assign bank_conflict_cnt_out = conflict_cnt_r;

endmodule
