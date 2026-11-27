// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_tile_prefetch_ctrl #(
    parameter int ARRAY_M = VX_tcu_v2_pkg::TCU_V2_ARRAY_M,
    parameter int ARRAY_N = VX_tcu_v2_pkg::TCU_V2_ARRAY_N,
    parameter int ARRAY_K = VX_tcu_v2_pkg::TCU_V2_ARRAY_K
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                tile_in_valid,
    output logic                                tile_in_ready,
    input  logic                                uop_is_sparse,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  a_tile_in,
    input  logic [ARRAY_N-1:0][ARRAY_K*32-1:0]  b_tile_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  a_cand_in,
    input  logic [ARRAY_M-1:0][ARRAY_K*16-1:0]  meta_in,
    input  logic [ARRAY_M-1:0][7:0]             scale_a_in,
    input  logic [ARRAY_N-1:0][7:0]             scale_b_in,
    input  logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] c_tile_in,
    input  logic [ARRAY_N-1:0][31:0]            bias_in,
    output logic                                tile_out_valid,
    input  logic                                tile_out_ready,
    output logic                                buf_sel_out,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  a_tile_out,
    output logic [ARRAY_N-1:0][ARRAY_K*32-1:0]  b_tile_out,
    output logic [ARRAY_M-1:0][ARRAY_K*32-1:0]  a_cand_out,
    output logic [ARRAY_M-1:0][ARRAY_K*16-1:0]  meta_out,
    output logic [ARRAY_M-1:0][7:0]             scale_a_out,
    output logic [ARRAY_N-1:0][7:0]             scale_b_out,
    output logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] c_tile_out,
    output logic [ARRAY_N-1:0][31:0]            bias_out,
    output logic [1:0]                          occupancy_out,
    output logic [31:0]                         pingpong_swaps_out,
    output logic [31:0]                         stall_cycles_out
);

    typedef struct packed {
        logic                                  valid;
        logic                                  is_sparse;
        logic [ARRAY_M-1:0][ARRAY_K*32-1:0]    a_tile;
        logic [ARRAY_N-1:0][ARRAY_K*32-1:0]    b_tile;
        logic [ARRAY_M-1:0][ARRAY_K*32-1:0]    a_cand;
        logic [ARRAY_M-1:0][ARRAY_K*16-1:0]    meta;
        logic [ARRAY_M-1:0][7:0]               scale_a;
        logic [ARRAY_N-1:0][7:0]               scale_b;
        logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] c_tile;
        logic [ARRAY_N-1:0][31:0]              bias;
    } tile_buf_slot_t;

    tile_buf_slot_t [1:0]   slots_r;
    logic                   wr_idx_r;
    logic                   rd_idx_r;
    logic [1:0]             count_r;
    logic [31:0]            swaps_cnt_r;
    logic [31:0]            stall_cnt_r;
    logic [31:0]            sparse_tiles_r;
    logic [31:0]            dense_tiles_r;

    logic                   do_push_w;
    logic                   do_pop_w;

    assign tile_in_ready  = (count_r != 2'd2);
    assign tile_out_valid = (count_r != 2'd0) && slots_r[rd_idx_r].valid;
    assign buf_sel_out    = rd_idx_r;
    assign a_tile_out     = slots_r[rd_idx_r].a_tile;
    assign b_tile_out     = slots_r[rd_idx_r].b_tile;
    assign a_cand_out     = slots_r[rd_idx_r].a_cand;
    assign meta_out       = slots_r[rd_idx_r].meta;
    assign scale_a_out    = slots_r[rd_idx_r].scale_a;
    assign scale_b_out    = slots_r[rd_idx_r].scale_b;
    assign c_tile_out     = slots_r[rd_idx_r].c_tile;
    assign bias_out       = slots_r[rd_idx_r].bias;
    assign occupancy_out  = count_r;

    assign do_push_w = tile_in_valid && tile_in_ready;
    assign do_pop_w  = tile_out_valid && tile_out_ready;

    `UNUSED_VAR (slots_r)
    `UNUSED_VAR (sparse_tiles_r)
    `UNUSED_VAR (dense_tiles_r)

    assign pingpong_swaps_out = swaps_cnt_r;
    assign stall_cycles_out   = stall_cnt_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            wr_idx_r       <= 1'b0;
            rd_idx_r       <= 1'b0;
            count_r        <= 2'd0;
            swaps_cnt_r    <= 32'd0;
            stall_cnt_r    <= 32'd0;
            sparse_tiles_r <= 32'd0;
            dense_tiles_r  <= 32'd0;
            for (int s = 0; s < 2; ++s) begin
                slots_r[s].valid     <= 1'b0;
                slots_r[s].is_sparse <= 1'b0;
                for (int m = 0; m < ARRAY_M; ++m) begin
                    slots_r[s].a_tile[m]  <= '0;
                    slots_r[s].a_cand[m]  <= '0;
                    slots_r[s].meta[m]    <= '0;
                    slots_r[s].scale_a[m] <= 8'd0;
                    slots_r[s].c_tile[m]  <= '0;
                end
                for (int n = 0; n < ARRAY_N; ++n) begin
                    slots_r[s].b_tile[n]  <= '0;
                    slots_r[s].scale_b[n] <= 8'd0;
                    slots_r[s].bias[n]    <= 32'd0;
                end
            end
        end else begin
            if (tile_out_valid && !tile_out_ready) begin
                stall_cnt_r <= stall_cnt_r + 32'd1;
            end

            if (do_push_w) begin
                slots_r[wr_idx_r].valid     <= 1'b1;
                slots_r[wr_idx_r].is_sparse <= uop_is_sparse;
                slots_r[wr_idx_r].a_tile    <= a_tile_in;
                slots_r[wr_idx_r].b_tile    <= b_tile_in;
                slots_r[wr_idx_r].a_cand    <= a_cand_in;
                slots_r[wr_idx_r].meta      <= meta_in;
                slots_r[wr_idx_r].scale_a   <= scale_a_in;
                slots_r[wr_idx_r].scale_b   <= scale_b_in;
                slots_r[wr_idx_r].c_tile    <= c_tile_in;
                slots_r[wr_idx_r].bias      <= bias_in;
                wr_idx_r                    <= !wr_idx_r;
                if (uop_is_sparse) begin
                    sparse_tiles_r <= sparse_tiles_r + 32'd1;
                end else begin
                    dense_tiles_r <= dense_tiles_r + 32'd1;
                end
            end

            if (do_pop_w) begin
                slots_r[rd_idx_r].valid <= 1'b0;
                rd_idx_r                <= !rd_idx_r;
                swaps_cnt_r             <= swaps_cnt_r + 32'd1;
            end

            case ({do_push_w, do_pop_w})
                2'b10:   count_r <= count_r + 2'd1;
                2'b01:   count_r <= count_r - 2'd1;
                default: count_r <= count_r;
            endcase
        end
    end

endmodule
