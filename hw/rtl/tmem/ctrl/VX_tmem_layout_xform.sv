// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_layout_xform
    import VX_tmem_pkg::*;
#(
    parameter int LANES = 8
) (
    input  logic                                clk,
    input  logic                                reset,
    // Transform command & payload input
    input  logic                                in_valid,
    output logic                                in_ready,
    input  logic [2:0]                          xform_mode,
    input  logic [2:0]                          elem_fmt,
    input  logic                                tile_8x8_mode,
    input  logic                                unpack_to_32b,
    input  logic [TMEM_TAG_W-1:0]               in_tag,
    input  logic [LANES-1:0][63:0]              in_data,
    // Transformed output (registered boundary)
    output logic                                out_valid,
    input  logic                                out_ready,
    output logic [TMEM_TAG_W-1:0]               out_tag,
    output logic [LANES-1:0][63:0]              out_data,
    output logic [31:0]                         xform_ops_out
);

    // Transform operation modes
    localparam logic [2:0] XFORM_PASS         = 3'd0;
    localparam logic [2:0] XFORM_TRANSPOSE_4X4 = 3'd1;
    localparam logic [2:0] XFORM_TRANSPOSE_8X8 = 3'd2;
    localparam logic [2:0] XFORM_PACK         = 3'd3;
    localparam logic [2:0] XFORM_UNPACK       = 3'd4;
    localparam logic [2:0] XFORM_TRANS_UNPACK = 3'd5;

    // Element format encodings
    localparam logic [2:0] FMT_FP32 = 3'd0;
    localparam logic [2:0] FMT_BF16 = 3'd1;
    localparam logic [2:0] FMT_FP8  = 3'd2;
    localparam logic [2:0] FMT_FP6  = 3'd3;
    localparam logic [2:0] FMT_FP4  = 3'd4;

    typedef enum logic [1:0] {
        XF_IDLE     = 2'd0,
        XF_COLLECT8 = 2'd1,
        XF_DRAIN8   = 2'd2
    } xf_state_e;

    xf_state_e                  state_q, state_d;
    logic [7:0][7:0][31:0]      tile_buf_q, tile_buf_d;
    logic [2:0]                 row_idx_q, row_idx_d;
    logic [2:0]                 saved_mode_q, saved_mode_d;
    logic [2:0]                 saved_fmt_q, saved_fmt_d;
    logic                       saved_unpack_q, saved_unpack_d;
    logic [TMEM_TAG_W-1:0]      saved_tag_q, saved_tag_d;

    logic                       out_valid_q, out_valid_d;
    logic [TMEM_TAG_W-1:0]      out_tag_q, out_tag_d;
    logic [LANES-1:0][63:0]     out_data_q, out_data_d;
    logic [31:0]                xform_ops_q, xform_ops_d;

    logic                        out_slot_free_tmp;
    logic [LANES-1:0][63:0]      res_vec_tmp;
    logic [LANES-1:0][63:0]      t4_tmp;
    logic [LANES-1:0][63:0]      col_vec_tmp;
    logic [63:0]                 raw_el_tmp;
    `UNUSED_PARAM (FMT_FP32)
    // Unpack sub-word elements from a 64-bit lane into low-32-bit slots
    function automatic logic [63:0] unpack_lane64(
        input logic [63:0] raw64,
        input logic [2:0]  fmt,
        input logic        expand32
    );
        logic [63:0] res;
        res = 64'd0;
        case (fmt)
            FMT_FP4: begin
                if (expand32) begin
                    res = {28'd0, raw64[7:4], 28'd0, raw64[3:0]};
                end else begin
                    res = {12'd0, raw64[15:12], 12'd0, raw64[11:8],
                           12'd0, raw64[7:4],   12'd0, raw64[3:0]};
                end
            end
            FMT_FP6: begin
                if (expand32) begin
                    res = {26'd0, raw64[11:6], 26'd0, raw64[5:0]};
                end else begin
                    res = {32'd0,
                           2'b00, raw64[23:18],
                           2'b00, raw64[17:12],
                           2'b00, raw64[11:6],
                           2'b00, raw64[5:0]};
                end
            end
            FMT_FP8: begin
                if (expand32) begin
                    res = {24'd0, raw64[15:8], 24'd0, raw64[7:0]};
                end else begin
                    res = {8'd0, raw64[31:24], 8'd0, raw64[23:16],
                           8'd0, raw64[15:8],  8'd0, raw64[7:0]};
                end
            end
            FMT_BF16: begin
                if (expand32) begin
                    res = {raw64[31:16], 16'd0, raw64[15:0], 16'd0};
                end else begin
                    res = raw64;
                end
            end
            FMT_FP32: begin
                res = raw64;
            end
            default: begin
                res = raw64;
            end
        endcase
        return res;
    endfunction

    // Pack unpacked slots back into dense 64-bit TMEM representation
    function automatic logic [63:0] pack_lane64(
        input logic [63:0] raw64,
        input logic [2:0]  fmt,
        input logic        from32
    );
        logic [63:0] res;
        res = 64'd0;
        case (fmt)
            FMT_FP4: begin
                if (from32) begin
                    res = {56'd0, raw64[35:32], raw64[3:0]};
                end else begin
                    res = {48'd0, raw64[51:48], raw64[35:32], raw64[19:16], raw64[3:0]};
                end
            end
            FMT_FP6: begin
                if (from32) begin
                    res = {52'd0, raw64[37:32], raw64[5:0]};
                end else begin
                    res = {40'd0, raw64[29:24], raw64[21:16], raw64[13:8], raw64[5:0]};
                end
            end
            FMT_FP8: begin
                if (from32) begin
                    res = {48'd0, raw64[39:32], raw64[7:0]};
                end else begin
                    res = {32'd0, raw64[55:48], raw64[39:32], raw64[23:16], raw64[7:0]};
                end
            end
            FMT_BF16: begin
                if (from32) begin
                    res = {32'd0, raw64[63:48], raw64[31:16]};
                end else begin
                    res = raw64;
                end
            end
            FMT_FP32: begin
                res = raw64;
            end
            default: begin
                res = raw64;
            end
        endcase
        return res;
    endfunction

    // Combinational 4x4 32-bit tile transpose across low 32-bit halves of lanes 0..3 / 4..7
    function automatic logic [LANES-1:0][63:0] transpose_4x4_pair(
        input logic [LANES-1:0][63:0] src
    );
        logic [LANES-1:0][63:0] dst;
        dst = '0;
        dst[0] = {src[1][31:0],  src[0][31:0]};
        dst[1] = {src[3][31:0],  src[2][31:0]};
        dst[2] = {src[1][63:32], src[0][63:32]};
        dst[3] = {src[3][63:32], src[2][63:32]};
        dst[4] = {src[5][31:0],  src[4][31:0]};
        dst[5] = {src[7][31:0],  src[6][31:0]};
        dst[6] = {src[5][63:32], src[4][63:32]};
        dst[7] = {src[7][63:32], src[6][63:32]};
        return dst;
    endfunction

    assign in_ready = !reset &&
                      ((state_q == XF_COLLECT8) ||
                       ((state_q == XF_IDLE) && (!out_valid_q || out_ready)));

    // Layout transformation FSM and datapath
    always_comb begin
        state_d        = state_q;
        tile_buf_d     = tile_buf_q;
        row_idx_d      = row_idx_q;
        saved_mode_d   = saved_mode_q;
        saved_fmt_d    = saved_fmt_q;
        saved_unpack_d = saved_unpack_q;
        saved_tag_d    = saved_tag_q;

        out_valid_d    = out_valid_q;
        out_tag_d      = out_tag_q;
        out_data_d     = out_data_q;
        xform_ops_d    = xform_ops_q;

        res_vec_tmp    = in_data;
        t4_tmp         = in_data;
        col_vec_tmp    = '0;
        raw_el_tmp     = 64'd0;

        if (out_valid_q && out_ready) begin
            out_valid_d = 1'b0;
        end
        out_slot_free_tmp = (!out_valid_q || out_ready);

        case (state_q)
            XF_IDLE: begin
                if (in_valid && out_slot_free_tmp) begin
                    if (tile_8x8_mode || (xform_mode == XFORM_TRANSPOSE_8X8)) begin
                        // Capture row 0 of 8x8 32-bit tile (using low 32 bits of each of 8 lanes)
                        for (int c = 0; c < 8; ++c) begin
                            tile_buf_d[0][c] = in_data[c][31:0];
                        end
                        row_idx_d      = 3'd1;
                        saved_mode_d   = xform_mode;
                        saved_fmt_d    = elem_fmt;
                        saved_unpack_d = unpack_to_32b;
                        saved_tag_d    = in_tag;
                        state_d        = XF_COLLECT8;
                    end else begin
                        res_vec_tmp = in_data;

                        case (xform_mode)
                            XFORM_PASS: begin
                                res_vec_tmp = in_data;
                            end
                            XFORM_TRANSPOSE_4X4: begin
                                res_vec_tmp = transpose_4x4_pair(in_data);
                            end
                            XFORM_PACK: begin
                                for (int l = 0; l < LANES; ++l) begin
                                    res_vec_tmp[l] = pack_lane64(in_data[l], elem_fmt, unpack_to_32b);
                                end
                            end
                            XFORM_UNPACK: begin
                                for (int l = 0; l < LANES; ++l) begin
                                    res_vec_tmp[l] = unpack_lane64(in_data[l], elem_fmt, unpack_to_32b);
                                end
                            end
                            XFORM_TRANS_UNPACK: begin
                                t4_tmp = transpose_4x4_pair(in_data);
                                for (int l = 0; l < LANES; ++l) begin
                                    res_vec_tmp[l] = unpack_lane64(t4_tmp[l], elem_fmt, unpack_to_32b);
                                end
                            end
                            default: begin
                                res_vec_tmp = in_data;
                            end
                        endcase

                        out_valid_d = 1'b1;
                        out_tag_d   = in_tag;
                        out_data_d  = res_vec_tmp;
                        xform_ops_d = xform_ops_q + 32'd1;
                    end
                end
            end

            XF_COLLECT8: begin
                if (in_valid) begin
                    for (int c = 0; c < 8; ++c) begin
                        tile_buf_d[row_idx_q][c] = in_data[c][31:0];
                    end
                    if (row_idx_q == 3'd7) begin
                        row_idx_d = 3'd0;
                        state_d   = XF_DRAIN8;
                    end else begin
                        row_idx_d = row_idx_q + 3'd1;
                    end
                end
            end

            XF_DRAIN8: begin
                if (out_slot_free_tmp) begin
                    col_vec_tmp = '0;
                    for (int r = 0; r < 8; ++r) begin
                        raw_el_tmp = {32'd0, tile_buf_q[r][row_idx_q]};
                        if (saved_mode_q == XFORM_TRANS_UNPACK) begin
                            col_vec_tmp[r] = unpack_lane64(raw_el_tmp, saved_fmt_q, saved_unpack_q);
                        end else begin
                            col_vec_tmp[r] = raw_el_tmp;
                        end
                    end

                    out_valid_d = 1'b1;
                    out_tag_d   = saved_tag_q;
                    out_data_d  = col_vec_tmp;

                    if (row_idx_q == 3'd7) begin
                        row_idx_d   = 3'd0;
                        xform_ops_d = xform_ops_q + 32'd1;
                        state_d     = XF_IDLE;
                    end else begin
                        row_idx_d = row_idx_q + 3'd1;
                    end
                end
            end

            default: begin
                state_d = XF_IDLE;
            end
        endcase
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            state_q        <= XF_IDLE;
            tile_buf_q     <= '0;
            row_idx_q      <= 3'd0;
            saved_mode_q   <= 3'd0;
            saved_fmt_q    <= 3'd0;
            saved_unpack_q <= 1'b0;
            saved_tag_q    <= '0;
            out_valid_q    <= 1'b0;
            out_tag_q      <= '0;
            out_data_q     <= '0;
            xform_ops_q    <= 32'd0;
        end else begin
            state_q        <= state_d;
            tile_buf_q     <= tile_buf_d;
            row_idx_q      <= row_idx_d;
            saved_mode_q   <= saved_mode_d;
            saved_fmt_q    <= saved_fmt_d;
            saved_unpack_q <= saved_unpack_d;
            saved_tag_q    <= saved_tag_d;
            out_valid_q    <= out_valid_d;
            out_tag_q      <= out_tag_d;
            out_data_q     <= out_data_d;
            xform_ops_q    <= xform_ops_d;
        end
    end

    assign out_valid     = out_valid_q;
    assign out_tag       = out_tag_q;
    assign out_data      = out_data_q;
    assign xform_ops_out = xform_ops_q;

endmodule
