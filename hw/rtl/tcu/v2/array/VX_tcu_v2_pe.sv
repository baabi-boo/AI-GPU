// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_PE_SV
`define VX_TCU_V2_PE_SV

`include "VX_platform.vh"

module VX_tcu_v2_pe #(
    parameter int LANES           = VX_tcu_v2_pkg::TCU_V2_ARRAY_K,
    parameter int TAG_QUEUE_DEPTH = 8
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                valid_in,
    output logic                                ready_in,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e          fmt_a,
    input  VX_tcu_v2_pkg::tcu_v2_fmt_e          fmt_b,
    input  VX_tcu_v2_pkg::tcu_v2_scale_fmt_e    scale_fmt,
    input  VX_tcu_v2_pkg::tcu_v2_rm_e           rm,
    input  logic [LANES*32-1:0]                 a_in,
    input  logic [LANES*32-1:0]                 b_in,
    input  logic [7:0]                          scale_a_in,
    input  logic [7:0]                          scale_b_in,
    input  logic [31:0]                         c_in,
    input  logic                                accum_en,
    input  logic                                int_saturate,
    input  logic                                systolic_pass_en,
    output logic [LANES*32-1:0]                 a_pass_out,
    output logic [LANES*32-1:0]                 b_pass_out,
    output logic [7:0]                          scale_a_pass_out,
    output logic [7:0]                          scale_b_pass_out,
    output logic                                pass_valid_out,
    output logic                                valid_out,
    input  logic                                ready_out,
    output logic [31:0]                         d_out,
    output VX_tcu_v2_pkg::tcu_v2_fp_flags_t     flags_out,
    output logic                                pe_busy,
    output logic [31:0]                         pe_ops_done
);

    import VX_tcu_v2_pkg::*;

    localparam int TAG_PTR_W   = (TAG_QUEUE_DEPTH > 1) ? $clog2(TAG_QUEUE_DEPTH) : 1;
    localparam int TAG_CNT_W   = $clog2(TAG_QUEUE_DEPTH + 1);
    localparam int FP46_RAW_W  = LANES * 8;
    localparam int FP816_RAW_W = LANES * 32;

    typedef struct packed {
        logic        use_fp46;
        logic        is_int_op;
        logic        fmt_invalid;
        logic        scale_invalid;
        tcu_v2_fmt_e fmt_a_q;
        tcu_v2_fmt_e fmt_b_q;
    } pe_tag_entry_t;

    // -------------------------------------------------------------------------
    // Format Classification, Scale Legality, and Operand Activity Detection
    // -------------------------------------------------------------------------
    logic a_is_fp4;
    logic a_is_fp6;
    logic b_is_fp4;
    logic b_is_fp6;
    logic a_is_fp46;
    logic b_is_fp46;
    logic a_is_int;
    logic b_is_int;
    logic a_supported_fp816;
    logic b_supported_fp816;
    logic use_fp46_path;
    logic use_fp816_path;
    logic is_int_mode;
    logic fmt_pair_invalid;
    logic a_all_lanes_zero;
    logic b_all_lanes_zero;
    logic scale_a_is_nan;
    logic scale_b_is_nan;
    logic scale_pair_invalid;
    logic [LANES-1:0] a_lane_nz_mask;
    logic [LANES-1:0] b_lane_nz_mask;
    logic [3:0]       a_active_lane_cnt;
    logic [3:0]       b_active_lane_cnt;
    tcu_v2_scale_decoded_t dec_sa;
    tcu_v2_scale_decoded_t dec_sb;

    always_comb begin

        a_is_fp4 = tcu_v2_fmt_is_fp4(fmt_a);
        a_is_fp6 = tcu_v2_fmt_is_fp6(fmt_a);
        b_is_fp4 = tcu_v2_fmt_is_fp4(fmt_b);
        b_is_fp6 = tcu_v2_fmt_is_fp6(fmt_b);

        a_is_fp46 = a_is_fp4 || a_is_fp6;
        b_is_fp46 = b_is_fp4 || b_is_fp6;

        a_is_int = (fmt_a == TCU_V2_FMT_INT8);
        b_is_int = (fmt_b == TCU_V2_FMT_INT8);

        a_supported_fp816 = tcu_v2_fmt_is_fp8(fmt_a) ||
                            (fmt_a == TCU_V2_FMT_BF16) ||
                            (fmt_a == TCU_V2_FMT_FP16) ||
                            (fmt_a == TCU_V2_FMT_TF32) ||
                            a_is_int;

        b_supported_fp816 = tcu_v2_fmt_is_fp8(fmt_b) ||
                            (fmt_b == TCU_V2_FMT_BF16) ||
                            (fmt_b == TCU_V2_FMT_FP16) ||
                            (fmt_b == TCU_V2_FMT_TF32) ||
                            b_is_int;

        use_fp46_path  = a_is_fp46 || b_is_fp46;
        use_fp816_path = !use_fp46_path;
        is_int_mode    = a_is_int && b_is_int;

        if (use_fp46_path) begin
            fmt_pair_invalid = !(a_is_fp46 && b_is_fp46);
        end else begin
            fmt_pair_invalid = !(a_supported_fp816 && b_supported_fp816) || (a_is_int != b_is_int);
        end

        dec_sa = tcu_v2_decode_scale(scale_fmt, scale_a_in);
        dec_sb = tcu_v2_decode_scale(scale_fmt, scale_b_in);

        scale_a_is_nan     = dec_sa.is_nan;
        scale_b_is_nan     = dec_sb.is_nan;
        scale_pair_invalid = (scale_a_is_nan || scale_b_is_nan) && !is_int_mode;

        a_all_lanes_zero  = 1'b1;
        b_all_lanes_zero  = 1'b1;
        a_active_lane_cnt = 4'd0;
        b_active_lane_cnt = 4'd0;
        for (int ln = 0; ln < LANES; ++ln) begin
            a_lane_nz_mask[ln] = (a_in[ln*32 +: 32] != 32'd0);
            b_lane_nz_mask[ln] = (b_in[ln*32 +: 32] != 32'd0);
            if (a_lane_nz_mask[ln]) begin
                a_all_lanes_zero  = 1'b0;
                a_active_lane_cnt = a_active_lane_cnt + 4'd1;
            end
            if (b_lane_nz_mask[ln]) begin
                b_all_lanes_zero  = 1'b0;
                b_active_lane_cnt = b_active_lane_cnt + 4'd1;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Operand Packing for Active FEDP Datapath
    // -------------------------------------------------------------------------

    logic [FP46_RAW_W-1:0]  fp46_a_raw;
    logic [FP46_RAW_W-1:0]  fp46_b_raw;
    logic [7:0]             fp46_scale_a;
    logic [7:0]             fp46_scale_b;
    logic [31:0]            fp46_c_in;
    logic                   fp46_accum_en;
    tcu_v2_fmt_e            fp46_fmt_a;
    tcu_v2_fmt_e            fp46_fmt_b;
    tcu_v2_scale_fmt_e      fp46_scale_fmt;
    tcu_v2_rm_e             fp46_rm;

    logic [FP816_RAW_W-1:0] fp816_a_raw;
    logic [FP816_RAW_W-1:0] fp816_b_raw;
    logic [7:0]             fp816_scale_a;
    logic [7:0]             fp816_scale_b;
    logic [31:0]            fp816_c_in;
    logic                   fp816_accum_en;
    logic                   fp816_int_sat;
    tcu_v2_fmt_e            fp816_fmt_a;
    tcu_v2_fmt_e            fp816_fmt_b;
    tcu_v2_scale_fmt_e      fp816_scale_fmt;
    tcu_v2_rm_e             fp816_rm;

    logic                   fp46_valid_in;
    logic                   fp46_ready_in;
    logic                   fp46_valid_out;
    logic                   fp46_ready_out;
    logic [31:0]            fp46_d_out;
    tcu_v2_fp_flags_t       fp46_flags_out;

    logic                   fp816_valid_in;
    logic                   fp816_ready_in;
    logic                   fp816_valid_out;
    logic                   fp816_ready_out;
    logic [31:0]            fp816_d_out;
    tcu_v2_fp_flags_t       fp816_flags_out;

    logic                   tag_q_full;
    logic                   tag_q_empty;
    logic                   accept_fire;
    logic                   retire_fire;

    always_comb begin
        fp46_a_raw     = '0;
        fp46_b_raw     = '0;
        fp46_scale_a   = 8'd0;
        fp46_scale_b   = 8'd0;
        fp46_c_in      = 32'd0;
        fp46_accum_en  = 1'b0;
        fp46_fmt_a     = TCU_V2_FMT_MXFP4_E2M1;
        fp46_fmt_b     = TCU_V2_FMT_MXFP4_E2M1;
        fp46_scale_fmt = TCU_V2_SCALE_NONE;
        fp46_rm        = TCU_V2_RM_RNE;

        fp816_a_raw     = '0;
        fp816_b_raw     = '0;
        fp816_scale_a   = 8'd0;
        fp816_scale_b   = 8'd0;
        fp816_c_in      = 32'd0;
        fp816_accum_en  = 1'b0;
        fp816_int_sat   = 1'b0;
        fp816_fmt_a     = TCU_V2_FMT_BF16;
        fp816_fmt_b     = TCU_V2_FMT_BF16;
        fp816_scale_fmt = TCU_V2_SCALE_NONE;
        fp816_rm        = TCU_V2_RM_RNE;

        if (valid_in && !tag_q_full && !fmt_pair_invalid) begin
            if (use_fp46_path) begin
                for (int lane = 0; lane < LANES; ++lane) begin
                    if (a_is_fp4) begin
                        fp46_a_raw[lane*8 +: 8] = {4'b0000, a_in[lane*32 +: 4]};
                    end else begin
                        fp46_a_raw[lane*8 +: 8] = {2'b00, a_in[lane*32 +: 6]};
                    end
                    if (b_is_fp4) begin
                        fp46_b_raw[lane*8 +: 8] = {4'b0000, b_in[lane*32 +: 4]};
                    end else begin
                        fp46_b_raw[lane*8 +: 8] = {2'b00, b_in[lane*32 +: 6]};
                    end
                end
                fp46_scale_a   = scale_a_in;
                fp46_scale_b   = scale_b_in;
                fp46_c_in      = c_in;
                fp46_accum_en  = accum_en;
                fp46_fmt_a     = fmt_a;
                fp46_fmt_b     = fmt_b;
                fp46_scale_fmt = scale_fmt;
                fp46_rm        = rm;
            end else begin
                for (int lane = 0; lane < LANES; ++lane) begin
                    case (fmt_a)
                        TCU_V2_FMT_FP8_E4M3,
                        TCU_V2_FMT_FP8_E5M2,
                        TCU_V2_FMT_MXFP8_E4M3,
                        TCU_V2_FMT_MXFP8_E5M2,
                        TCU_V2_FMT_INT8: begin
                            fp816_a_raw[lane*32 +: 32] = {24'd0, a_in[lane*32 +: 8]};
                        end
                        TCU_V2_FMT_FP16,
                        TCU_V2_FMT_BF16: begin
                            fp816_a_raw[lane*32 +: 32] = {16'd0, a_in[lane*32 +: 16]};
                        end
                        default: begin
                            fp816_a_raw[lane*32 +: 32] = a_in[lane*32 +: 32];
                        end
                    endcase

                    case (fmt_b)
                        TCU_V2_FMT_FP8_E4M3,
                        TCU_V2_FMT_FP8_E5M2,
                        TCU_V2_FMT_MXFP8_E4M3,
                        TCU_V2_FMT_MXFP8_E5M2,
                        TCU_V2_FMT_INT8: begin
                            fp816_b_raw[lane*32 +: 32] = {24'd0, b_in[lane*32 +: 8]};
                        end
                        TCU_V2_FMT_FP16,
                        TCU_V2_FMT_BF16: begin
                            fp816_b_raw[lane*32 +: 32] = {16'd0, b_in[lane*32 +: 16]};
                        end
                        default: begin
                            fp816_b_raw[lane*32 +: 32] = b_in[lane*32 +: 32];
                        end
                    endcase
                end
                fp816_scale_a   = scale_a_in;
                fp816_scale_b   = scale_b_in;
                fp816_c_in      = c_in;
                fp816_accum_en  = accum_en;
                fp816_int_sat   = int_saturate;
                fp816_fmt_a     = fmt_a;
                fp816_fmt_b     = fmt_b;
                fp816_scale_fmt = scale_fmt;
                fp816_rm        = rm;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Handshake Routing & Inflight Format Tag Queue
    // -------------------------------------------------------------------------
    pe_tag_entry_t [TAG_QUEUE_DEPTH-1:0] tag_mem_r;
    logic [TAG_PTR_W-1:0]                tag_wr_ptr_r;
    logic [TAG_PTR_W-1:0]                tag_rd_ptr_r;
    logic [TAG_CNT_W-1:0]                tag_count_r;
    logic                                fault_valid_r;
    logic [31:0]                         fault_payload_r;
    tcu_v2_fp_flags_t                    fault_flags_r;
    logic [31:0]                         ops_done_r;
    logic [31:0]                         fp46_ops_r;
    logic [31:0]                         fp816_ops_r;
    logic [31:0]                         zero_lane_cycles_r;
    logic [31:0]                         stall_in_cycles_r;
    logic [31:0]                         stall_out_cycles_r;

    pe_tag_entry_t tag_head;
    logic          head_is_fp46;
    logic          head_is_invalid;
    logic          head_scale_invalid;
    logic          selected_unit_ready;
    logic          out_skid_ready;

    assign tag_q_full  = (tag_count_r == TAG_CNT_W'(TAG_QUEUE_DEPTH));
    assign tag_q_empty = (tag_count_r == TAG_CNT_W'(0));
    assign tag_head    = tag_mem_r[tag_rd_ptr_r];

    assign head_is_fp46       = tag_head.use_fp46;
    assign head_is_invalid    = tag_head.fmt_invalid;
    assign head_scale_invalid = tag_head.scale_invalid;

    always_comb begin
        if (fmt_pair_invalid) begin
            selected_unit_ready = !fault_valid_r;
        end else if (use_fp46_path) begin
            selected_unit_ready = fp46_ready_in;
        end else begin
            selected_unit_ready = fp816_ready_in;
        end

        ready_in = !tag_q_full && selected_unit_ready;

        fp46_valid_in  = valid_in && !tag_q_full && use_fp46_path  && !fmt_pair_invalid;
        fp816_valid_in = valid_in && !tag_q_full && use_fp816_path && !fmt_pair_invalid;
    end

    assign accept_fire = valid_in && ready_in;

    always_ff @(posedge clk) begin
        if (reset) begin
            tag_wr_ptr_r       <= '0;
            tag_rd_ptr_r       <= '0;
            tag_count_r        <= '0;
            fault_valid_r      <= 1'b0;
            fault_payload_r    <= TCU_V2_CANONICAL_QNAN;
            fault_flags_r      <= '0;
            ops_done_r         <= 32'd0;
            fp46_ops_r         <= 32'd0;
            fp816_ops_r        <= 32'd0;
            zero_lane_cycles_r <= 32'd0;
            stall_in_cycles_r  <= 32'd0;
            stall_out_cycles_r <= 32'd0;
            for (int idx = 0; idx < TAG_QUEUE_DEPTH; ++idx) begin
                tag_mem_r[idx] <= '0;
            end
        end else begin
            if (valid_in && !ready_in) begin
                stall_in_cycles_r <= stall_in_cycles_r + 32'd1;
            end
            if (valid_out && !ready_out) begin
                stall_out_cycles_r <= stall_out_cycles_r + 32'd1;
            end

            if (accept_fire) begin
                tag_mem_r[tag_wr_ptr_r].use_fp46      <= use_fp46_path;
                tag_mem_r[tag_wr_ptr_r].is_int_op     <= is_int_mode;
                tag_mem_r[tag_wr_ptr_r].fmt_invalid   <= fmt_pair_invalid;
                tag_mem_r[tag_wr_ptr_r].scale_invalid <= scale_pair_invalid;
                tag_mem_r[tag_wr_ptr_r].fmt_a_q       <= fmt_a;
                tag_mem_r[tag_wr_ptr_r].fmt_b_q       <= fmt_b;
                tag_wr_ptr_r <= (tag_wr_ptr_r == TAG_PTR_W'(TAG_QUEUE_DEPTH - 1)) ? '0 : (tag_wr_ptr_r + TAG_PTR_W'(1));
                if (a_all_lanes_zero || b_all_lanes_zero) begin
                    zero_lane_cycles_r <= zero_lane_cycles_r + 32'd1;
                end
            end

            if (retire_fire) begin
                tag_rd_ptr_r <= (tag_rd_ptr_r == TAG_PTR_W'(TAG_QUEUE_DEPTH - 1)) ? '0 : (tag_rd_ptr_r + TAG_PTR_W'(1));
                ops_done_r   <= ops_done_r + 32'd1;
                if (head_is_fp46) begin
                    fp46_ops_r <= fp46_ops_r + 32'd1;
                end else begin
                    fp816_ops_r <= fp816_ops_r + 32'd1;
                end
            end

            case ({accept_fire, retire_fire})
                2'b10:   tag_count_r <= tag_count_r + TAG_CNT_W'(1);
                2'b01:   tag_count_r <= tag_count_r - TAG_CNT_W'(1);
                default: tag_count_r <= tag_count_r;
            endcase

            if (accept_fire && fmt_pair_invalid) begin
                fault_valid_r   <= 1'b1;
                fault_payload_r <= is_int_mode ? 32'd0 : TCU_V2_CANONICAL_QNAN;
                fault_flags_r   <= '{nv: 1'b1, dz: 1'b0, of: 1'b0, uf: 1'b0, nx: 1'b0};
            end else if (retire_fire && head_is_invalid) begin
                fault_valid_r <= 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // FP4 / FP6 Fused-Exponent Dot-Product Unit
    // -------------------------------------------------------------------------
    VX_tcu_v2_fp4_fp6_fedp_unit #(
        .LANES (LANES)
    ) u_fp4_fp6_fedp (
        .clk         (clk),
        .reset       (reset),
        .valid_in    (fp46_valid_in),
        .ready_in    (fp46_ready_in),
        .fmt_a       (fp46_fmt_a),
        .fmt_b       (fp46_fmt_b),
        .scale_fmt   (fp46_scale_fmt),
        .rm          (fp46_rm),
        .a_raw       (fp46_a_raw),
        .b_raw       (fp46_b_raw),
        .scale_a_raw (fp46_scale_a),
        .scale_b_raw (fp46_scale_b),
        .c_fp32      (fp46_c_in),
        .accum_en    (fp46_accum_en),
        .valid_out   (fp46_valid_out),
        .ready_out   (fp46_ready_out),
        .d_fp32      (fp46_d_out),
        .flags_out   (fp46_flags_out)
    );

    // -------------------------------------------------------------------------
    // FP8 / BF16 / FP16 / TF32 / INT8 Dot-Product Unit
    // -------------------------------------------------------------------------
    VX_tcu_v2_fp8_bf16_fedp_unit #(
        .LANES (LANES)
    ) u_fp8_bf16_fedp (
        .clk          (clk),
        .reset        (reset),
        .valid_in     (fp816_valid_in),
        .ready_in     (fp816_ready_in),
        .fmt_a        (fp816_fmt_a),
        .fmt_b        (fp816_fmt_b),
        .scale_fmt    (fp816_scale_fmt),
        .rm           (fp816_rm),
        .a_raw        (fp816_a_raw),
        .b_raw        (fp816_b_raw),
        .scale_a_raw  (fp816_scale_a),
        .scale_b_raw  (fp816_scale_b),
        .c_in         (fp816_c_in),
        .accum_en     (fp816_accum_en),
        .int_saturate (fp816_int_sat),
        .valid_out    (fp816_valid_out),
        .ready_out    (fp816_ready_out),
        .d_out        (fp816_d_out),
        .flags_out    (fp816_flags_out)
    );

    // -------------------------------------------------------------------------
    // Output Result Arbitration, Canonical Sanitizing & Output Elastic Register
    // -------------------------------------------------------------------------
    logic [31:0]      selected_d;
    tcu_v2_fp_flags_t selected_flags;
    logic             selected_valid;
    logic             d_is_nan;
    logic [31:0]      sanitized_d;

    logic             out_buf_valid_r;
    logic [31:0]      out_buf_d_r;
    tcu_v2_fp_flags_t out_buf_flags_r;

    always_comb begin
        fp46_ready_out  = 1'b0;
        fp816_ready_out = 1'b0;
        selected_valid  = 1'b0;
        selected_d      = 32'd0;
        selected_flags  = '0;

        if (!tag_q_empty) begin
            if (head_is_invalid) begin
                selected_valid = fault_valid_r;
                selected_d     = fault_payload_r;
                selected_flags = fault_flags_r;
            end else if (head_is_fp46) begin
                selected_valid = fp46_valid_out;
                selected_d     = fp46_d_out;
                selected_flags = fp46_flags_out;
                fp46_ready_out = out_skid_ready;
            end else begin
                selected_valid  = fp816_valid_out;
                selected_d      = fp816_d_out;
                selected_flags  = fp816_flags_out;
                fp816_ready_out = out_skid_ready;
            end
        end

        if (head_scale_invalid) begin
            selected_flags.nv = 1'b1;
        end

        d_is_nan    = !tag_head.is_int_op && tcu_v2_fp32_is_nan(selected_d);
        sanitized_d = d_is_nan ? TCU_V2_CANONICAL_QNAN : selected_d;
    end

    assign out_skid_ready = !out_buf_valid_r || ready_out;
    assign retire_fire    = selected_valid && out_skid_ready;

    always_ff @(posedge clk) begin
        if (reset) begin
            out_buf_valid_r <= 1'b0;
            out_buf_d_r     <= 32'd0;
            out_buf_flags_r <= '0;
        end else if (selected_valid && out_skid_ready) begin
            out_buf_valid_r <= 1'b1;
            out_buf_d_r     <= sanitized_d;
            out_buf_flags_r <= selected_flags;
        end else if (out_buf_valid_r && ready_out) begin
            out_buf_valid_r <= 1'b0;
        end
    end

    assign valid_out = out_buf_valid_r;
    assign d_out     = out_buf_d_r;
    assign flags_out = out_buf_flags_r;

    // -------------------------------------------------------------------------
    // Local A/B/Scale Systolic Pass-Through Registers
    // -------------------------------------------------------------------------
    logic [LANES*32-1:0] a_pass_r;
    logic [LANES*32-1:0] b_pass_r;
    logic [7:0]          scale_a_pass_r;
    logic [7:0]          scale_b_pass_r;
    logic                pass_valid_r;
    tcu_v2_fmt_e         fmt_a_pass_r;
    tcu_v2_fmt_e         fmt_b_pass_r;

    always_ff @(posedge clk) begin
        if (reset) begin
            a_pass_r       <= '0;
            b_pass_r       <= '0;
            scale_a_pass_r <= 8'd0;
            scale_b_pass_r <= 8'd0;
            pass_valid_r   <= 1'b0;
            fmt_a_pass_r   <= TCU_V2_FMT_FP32;
            fmt_b_pass_r   <= TCU_V2_FMT_FP32;
        end else if (systolic_pass_en) begin
            pass_valid_r <= accept_fire;
            if (accept_fire) begin
                a_pass_r       <= a_in;
                b_pass_r       <= b_in;
                scale_a_pass_r <= scale_a_in;
                scale_b_pass_r <= scale_b_in;
                fmt_a_pass_r   <= fmt_a;
                fmt_b_pass_r   <= fmt_b;
            end
        end
    end

    `UNUSED_VAR (dec_sa)
    `UNUSED_VAR (dec_sb)
    `UNUSED_VAR (tag_head)
    `UNUSED_VAR (fmt_a_pass_r)
    `UNUSED_VAR (fmt_b_pass_r)
    `UNUSED_VAR (fp46_ops_r)
    `UNUSED_VAR (fp816_ops_r)
    `UNUSED_VAR (zero_lane_cycles_r)
    `UNUSED_VAR (stall_in_cycles_r)
    `UNUSED_VAR (stall_out_cycles_r)
    `UNUSED_VAR (a_active_lane_cnt)
    `UNUSED_VAR (b_active_lane_cnt)

    assign a_pass_out       = a_pass_r;
    assign b_pass_out       = b_pass_r;
    assign scale_a_pass_out = scale_a_pass_r;
    assign scale_b_pass_out = scale_b_pass_r;
    assign pass_valid_out   = pass_valid_r;
    assign pe_busy          = !tag_q_empty || pass_valid_r || out_buf_valid_r;
    assign pe_ops_done      = ops_done_r;

endmodule

`endif // VX_TCU_V2_PE_SV
