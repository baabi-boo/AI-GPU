// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tcu_v2_ctrl_regfile #(
    parameter int NUM_PIPES = 1
) (
    input  logic                                clk,
    input  logic                                reset,
    input  logic                                cfg_wr_valid,
    input  logic [7:0]                          cfg_wr_addr,
    input  logic [31:0]                         cfg_wr_data,
    input  logic                                cfg_rd_valid,
    input  logic [7:0]                          cfg_rd_addr,
    output logic                                cfg_rd_rsp_valid,
    output logic [31:0]                         cfg_rd_rsp_data,
    input  VX_tcu_v2_pkg::tcu_v2_perf_cnt_t     perf_cnt_in,
    input  logic                                fault_sticky_in,
    input  logic [3:0]                          syndrome_code_in,
    input  logic [7:0]                          syndrome_row_in,
    input  logic [7:0]                          syndrome_group_in,
    input  logic [VX_tcu_v2_pkg::TCU_V2_DESC_ID_W-1:0] syndrome_desc_id_in,
    input  logic                                decomp_valid_in,
    input  logic                                decomp_illegal_in,
    input  logic [15:0]                         decomp_active_elems_in,
    output logic [1:0]                          swizzle_mode_out,
    output logic                                fault_clear_pulse_out,
    output logic                                perf_clear_pulse_out,
    output logic                                watchdog_clear_pulse_out,
    output logic                                commit_fence_req_out,
    output logic                                split_n_mode_out,
    output logic                                local_cta_rank_out,
    output logic [8:0]                          dbl_buf_stride_out,
    output logic [31:0]                         ctrl_reg_writes_out
);

    import VX_tcu_v2_pkg::*;

    localparam logic [7:0] ADDR_CTRL_CFG       = 8'h00;
    localparam logic [7:0] ADDR_TMEM_STRIDE    = 8'h04;
    localparam logic [7:0] ADDR_FAULT_STATUS   = 8'h08;
    localparam logic [7:0] ADDR_FAULT_CLEAR    = 8'h0C;
    localparam logic [7:0] ADDR_PERF_ACTIVE    = 8'h10;
    localparam logic [7:0] ADDR_PERF_STALL     = 8'h14;
    localparam logic [7:0] ADDR_PERF_CTA_WAIT  = 8'h18;
    localparam logic [7:0] ADDR_PERF_ISSUED    = 8'h1C;
    localparam logic [7:0] ADDR_PERF_RETIRED   = 8'h20;
    localparam logic [7:0] ADDR_PERF_DESCS     = 8'h24;
    localparam logic [7:0] ADDR_PERF_SPARSE    = 8'h28;
    localparam logic [7:0] ADDR_PERF_SP_FAULT  = 8'h2C;
    localparam logic [7:0] ADDR_GEOM_CAPS      = 8'h30;
    localparam logic [7:0] ADDR_SHADOW_SYND    = 8'h34;
    localparam logic [7:0] ADDR_CTRL_STATS     = 8'h38;
    localparam logic [7:0] ADDR_ARCH_ID        = 8'h3C;
    localparam logic [7:0] ADDR_DECOMP_STATUS  = 8'h40;

    logic [1:0]     swizzle_mode_r;
    logic           split_n_mode_r;
    logic           local_cta_rank_r;
    logic           cfg_lock_r;
    logic [8:0]     dbl_buf_stride_r;
    logic           fault_clear_r;
    logic           perf_clear_r;
    logic           wdt_clear_r;
    logic           fence_req_r;
    logic           rd_rsp_valid_r;
    logic [31:0]    rd_rsp_data_r;
    logic [31:0]    ctrl_wr_cnt_r;
    logic [31:0]    ctrl_rd_cnt_r;
    logic [31:0]    shadow_syndrome_r;
    logic           decomp_seen_r;
    logic           decomp_illegal_sticky_r;
    logic [15:0]    decomp_last_active_r;

    logic [31:0]    rd_mux_comb;

    always_comb begin
        rd_mux_comb = 32'd0;
        case (cfg_rd_addr)
            ADDR_CTRL_CFG: begin
                rd_mux_comb = {27'd0, cfg_lock_r, local_cta_rank_r, split_n_mode_r, swizzle_mode_r};
            end
            ADDR_TMEM_STRIDE: begin
                rd_mux_comb = {23'd0, dbl_buf_stride_r};
            end
            ADDR_FAULT_STATUS: begin
                rd_mux_comb = {syndrome_desc_id_in, syndrome_row_in, syndrome_group_in,
                               3'd0, fault_sticky_in, syndrome_code_in};
            end
            ADDR_PERF_ACTIVE:   rd_mux_comb = perf_cnt_in.active_cycles;
            ADDR_PERF_STALL:    rd_mux_comb = perf_cnt_in.stall_cycles;
            ADDR_PERF_CTA_WAIT: rd_mux_comb = perf_cnt_in.cta_wait_cycles;
            ADDR_PERF_ISSUED:   rd_mux_comb = perf_cnt_in.uops_issued;
            ADDR_PERF_RETIRED:  rd_mux_comb = perf_cnt_in.uops_retired;
            ADDR_PERF_DESCS:    rd_mux_comb = perf_cnt_in.descs_completed;
            ADDR_PERF_SPARSE:   rd_mux_comb = perf_cnt_in.sparse_uops;
            ADDR_PERF_SP_FAULT: rd_mux_comb = perf_cnt_in.sparse_faults;
            ADDR_GEOM_CAPS: begin
                rd_mux_comb = {8'(NUM_PIPES), 8'(TCU_V2_ARRAY_M),
                               8'(TCU_V2_ARRAY_N), 8'(TCU_V2_ARRAY_K)};
            end
            ADDR_SHADOW_SYND:   rd_mux_comb = shadow_syndrome_r;
            ADDR_CTRL_STATS:    rd_mux_comb = {ctrl_rd_cnt_r[15:0], ctrl_wr_cnt_r[15:0]};
            ADDR_ARCH_ID:       rd_mux_comb = 32'h5443_5532;
            ADDR_DECOMP_STATUS: rd_mux_comb = {decomp_last_active_r, 14'd0,
                                               decomp_illegal_sticky_r, decomp_seen_r};
            default:            rd_mux_comb = 32'd0;
        endcase
    end

    `UNUSED_VAR (cfg_wr_data)

    always_ff @(posedge clk) begin
        if (reset) begin
            swizzle_mode_r          <= 2'd1;
            split_n_mode_r          <= 1'b0;
            local_cta_rank_r        <= 1'b0;
            cfg_lock_r              <= 1'b0;
            dbl_buf_stride_r        <= 9'd32;
            fault_clear_r           <= 1'b0;
            perf_clear_r            <= 1'b0;
            wdt_clear_r             <= 1'b0;
            fence_req_r             <= 1'b0;
            rd_rsp_valid_r          <= 1'b0;
            rd_rsp_data_r           <= 32'd0;
            ctrl_wr_cnt_r           <= 32'd0;
            ctrl_rd_cnt_r           <= 32'd0;
            shadow_syndrome_r       <= 32'd0;
            decomp_seen_r           <= 1'b0;
            decomp_illegal_sticky_r <= 1'b0;
            decomp_last_active_r    <= 16'd0;
        end else begin
            fault_clear_r <= 1'b0;
            perf_clear_r  <= 1'b0;
            wdt_clear_r   <= 1'b0;
            fence_req_r   <= 1'b0;

            if (fault_sticky_in && (shadow_syndrome_r == 32'd0)) begin
                shadow_syndrome_r <= {syndrome_desc_id_in, syndrome_row_in, syndrome_group_in,
                                      3'd0, fault_sticky_in, syndrome_code_in};
            end

            if (decomp_valid_in) begin
                decomp_seen_r        <= 1'b1;
                decomp_last_active_r <= decomp_active_elems_in;
                if (decomp_illegal_in) begin
                    decomp_illegal_sticky_r <= 1'b1;
                end
            end

            rd_rsp_valid_r <= cfg_rd_valid;
            if (cfg_rd_valid) begin
                rd_rsp_data_r <= rd_mux_comb;
                ctrl_rd_cnt_r <= ctrl_rd_cnt_r + 32'd1;
            end

            if (cfg_wr_valid) begin
                ctrl_wr_cnt_r <= ctrl_wr_cnt_r + 32'd1;
                case (cfg_wr_addr)
                    ADDR_CTRL_CFG: begin
                        if (!cfg_lock_r) begin
                            swizzle_mode_r   <= cfg_wr_data[1:0];
                            split_n_mode_r   <= cfg_wr_data[2];
                            local_cta_rank_r <= cfg_wr_data[3];
                            cfg_lock_r       <= cfg_wr_data[4];
                        end
                    end
                    ADDR_TMEM_STRIDE: begin
                        if (!cfg_lock_r) begin
                            dbl_buf_stride_r <= cfg_wr_data[8:0];
                        end
                    end
                    ADDR_FAULT_CLEAR: begin
                        fault_clear_r <= cfg_wr_data[0];
                        perf_clear_r  <= cfg_wr_data[1];
                        wdt_clear_r   <= cfg_wr_data[2];
                        fence_req_r   <= cfg_wr_data[3];
                        if (cfg_wr_data[0]) begin
                            shadow_syndrome_r       <= 32'd0;
                            decomp_illegal_sticky_r <= 1'b0;
                        end
                    end
                    default: begin
                        swizzle_mode_r <= swizzle_mode_r;
                    end
                endcase
            end
        end
    end

    assign cfg_rd_rsp_valid         = rd_rsp_valid_r;
    assign cfg_rd_rsp_data          = rd_rsp_data_r;
    assign swizzle_mode_out         = swizzle_mode_r;
    assign fault_clear_pulse_out    = fault_clear_r;
    assign perf_clear_pulse_out     = perf_clear_r;
    assign watchdog_clear_pulse_out = wdt_clear_r;
    assign commit_fence_req_out     = fence_req_r;
    assign split_n_mode_out         = split_n_mode_r;
    assign local_cta_rank_out       = local_cta_rank_r;
    assign dbl_buf_stride_out       = dbl_buf_stride_r;
    assign ctrl_reg_writes_out      = ctrl_wr_cnt_r;

endmodule
