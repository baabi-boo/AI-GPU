// SPDX-License-Identifier: Apache-2.0
module VX_tcu_v2_sva_monitors
    import VX_tcu_v2_pkg::*;
#(
    parameter int NUM_TCU_PIPES = 2,
    parameter int ARRAY_M       = TCU_V2_ARRAY_M,
    parameter int ARRAY_N       = TCU_V2_ARRAY_N,
    parameter int ARRAY_K       = TCU_V2_ARRAY_K,
    parameter int MAX_STALL_CYC = 2048
) (
    input  logic                                                        clk,
    input  logic                                                        reset,
    // Descriptor submission channels (per pipe)
    input  logic [NUM_TCU_PIPES-1:0]                                    desc_valid,
    input  logic [NUM_TCU_PIPES-1:0]                                    desc_ready,
    input  tcu_v2_wgmma_desc_t [NUM_TCU_PIPES-1:0]                      desc_in,
    // Tile operand input channels (per pipe)
    input  logic [NUM_TCU_PIPES-1:0]                                    ext_tile_in_valid,
    input  logic [NUM_TCU_PIPES-1:0]                                    ext_tile_in_ready,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_K*16-1:0]       ext_sparse_meta_in,
    // Tile output channels (per pipe)
    input  logic [NUM_TCU_PIPES-1:0]                                    tile_out_valid,
    input  logic [NUM_TCU_PIPES-1:0]                                    tile_out_ready,
    input  logic [NUM_TCU_PIPES-1:0][ARRAY_M-1:0][ARRAY_N-1:0][31:0]    d_tile_out,
    input  logic [NUM_TCU_PIPES-1:0][7:0]                               out_desc_id,
    input  tcu_v2_fp_flags_t [NUM_TCU_PIPES-1:0]                        flags_out,
    // Descriptor completion, sparse fault, and PMU telemetry
    input  logic [NUM_TCU_PIPES-1:0]                                    desc_done_valid,
    input  logic [NUM_TCU_PIPES-1:0][7:0]                               desc_done_id,
    input  logic [NUM_TCU_PIPES-1:0]                                    sparse_fault_out,
    input  tcu_v2_perf_cnt_t [NUM_TCU_PIPES-1:0]                        tcu_perf_cnt_out,
    // Internal TMEM MMA bridge & CTA barrier handshake visibility
    input  logic                                                        tmem_mma_req_valid,
    input  logic                                                        tmem_mma_req_ready,
    input  logic [NUM_TCU_PIPES-1:0]                                    cta_sync_out_valid,
    input  logic [NUM_TCU_PIPES-1:0]                                    cta_sync_out_ready,
    input  logic [NUM_TCU_PIPES-1:0][TCU_V2_BARRIER_ID_W-1:0]           cta_sync_out_bar_id,
    input  logic [NUM_TCU_PIPES-1:0]                                    cta_sync_out_phase,
    input  logic [NUM_TCU_PIPES-1:0]                                    cta_sync_in_valid,
    input  logic [NUM_TCU_PIPES-1:0]                                    cta_sync_in_ready,
    input  logic [NUM_TCU_PIPES-1:0][TCU_V2_BARRIER_ID_W-1:0]           cta_sync_in_bar_id,
    input  logic [NUM_TCU_PIPES-1:0]                                    cta_sync_in_phase,
    // Optional counter-clear strobe for PMU monotonicity guard
    input  logic                                                        perf_clear
);

    localparam int DESC_CREDIT_CAP = TCU_V2_DESC_Q_DEPTH + 4;
    localparam int TILE_CREDIT_CAP = 32;

    // -------------------------------------------------------------------------
    // Helper Functions: Format Legality & 2:4 Sparse Metadata Inspection
    // -------------------------------------------------------------------------
    function automatic logic is_supported_input_fmt(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8:       return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic is_supported_accum_fmt(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_I32:        return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic is_supported_output_fmt(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_I32,
            TCU_V2_FMT_INT8:       return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic is_sparse_capable_fmt(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8:       return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic desc_meta_fields_known_and_bounded(
        input tcu_v2_wgmma_desc_t d
    );
        logic fmt_ok;
        logic scale_ok;
        logic rm_ok;
        logic act_ok;
        logic bar_ok;
        logic dim_ok;
        logic fields_ok;
        fmt_ok    = is_supported_input_fmt(d.fmt_a) &&
                    is_supported_input_fmt(d.fmt_b) &&
                    is_supported_accum_fmt(d.fmt_c) &&
                    is_supported_output_fmt(d.fmt_d);
        scale_ok  = (d.scale_fmt <= TCU_V2_SCALE_E4M3);
        rm_ok     = (d.rm <= TCU_V2_RM_RMM);
        act_ok    = (d.act <= TCU_V2_ACT_GELU);
        bar_ok    = (int'(d.barrier_id) < TCU_V2_MAX_BARRIERS);
        dim_ok    = (d.tile_m != 16'd0) && (d.tile_n != 16'd0) && (d.tile_k != 16'd0);
        fields_ok = !$isunknown(d);
        return fmt_ok && scale_ok && rm_ok && act_ok && bar_ok && dim_ok && fields_ok;
    endfunction

    function automatic logic sparse_tile_meta_all_legal(
        input tcu_v2_fmt_e                             fmt,
        input logic [ARRAY_M-1:0][ARRAY_K*16-1:0]      meta_tile
    );
        int active_groups;
        logic all_ok;
        all_ok = 1'b1;
        case (fmt)
            TCU_V2_FMT_TF32:       active_groups = ARRAY_K / 2;
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16:       active_groups = ARRAY_K;
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: active_groups = ARRAY_K * 4;
            default:               active_groups = ARRAY_K * 2;
        endcase
        for (int m = 0; m < ARRAY_M; ++m) begin
            for (int g = 0; g < active_groups; ++g) begin
                tcu_v2_sparse_meta4_t pair_meta;
                pair_meta = tcu_v2_sparse_meta4_t'(meta_tile[m][g*4 +: 4]);
                if (!tcu_v2_sparse_pair_legal(pair_meta)) begin
                    all_ok = 1'b0;
                end
            end
        end
        return all_ok;
    endfunction

    // -------------------------------------------------------------------------
    // Shared Cluster-Level Bridge & Reset-Quiet History Registers
    // -------------------------------------------------------------------------
    logic       prev_valid_q;
    logic       prev_reset_q;
    logic       prev_perf_clear_q;
    logic       prev_tmem_mma_req_valid_q;
    logic       prev_tmem_mma_req_ready_q;
    logic [15:0] tmem_mma_stall_cnt_q;

    always_ff @(posedge clk) begin
        if (reset) begin
            prev_valid_q              <= 1'b0;
            prev_reset_q              <= 1'b1;
            prev_perf_clear_q         <= 1'b0;
            prev_tmem_mma_req_valid_q <= 1'b0;
            prev_tmem_mma_req_ready_q <= 1'b0;
            tmem_mma_stall_cnt_q      <= 16'd0;
        end else begin
            prev_valid_q              <= 1'b1;
            prev_reset_q              <= reset;
            prev_perf_clear_q         <= perf_clear;
            prev_tmem_mma_req_valid_q <= tmem_mma_req_valid;
            prev_tmem_mma_req_ready_q <= tmem_mma_req_ready;
            if (tmem_mma_req_valid && !tmem_mma_req_ready) begin
                if (tmem_mma_stall_cnt_q != 16'hFFFF) begin
                    tmem_mma_stall_cnt_q <= tmem_mma_stall_cnt_q + 16'd1;
                end
            end else begin
                tmem_mma_stall_cnt_q <= 16'd0;
            end
        end
    end

    // Shared TMEM MMA request channel checks
    always_ff @(posedge clk) begin
        if (!reset && prev_valid_q && !prev_reset_q) begin
            assert (!$isunknown({tmem_mma_req_valid, tmem_mma_req_ready, perf_clear}))
                else $error("VX_tcu_v2_sva_monitors: X/Z on shared bridge control signals");

            if (prev_tmem_mma_req_valid_q && !prev_tmem_mma_req_ready_q) begin
                assert (tmem_mma_req_valid)
                    else $error("VX_tcu_v2_sva_monitors: tmem_mma_req_valid dropped before ready");
            end

            if (MAX_STALL_CYC > 0) begin
                assert (int'(tmem_mma_stall_cnt_q) < MAX_STALL_CYC)
                    else $error("VX_tcu_v2_sva_monitors: tmem_mma_req stall exceeded %0d cycles", MAX_STALL_CYC);
            end
        end
    end

`ifdef ASSERTIONS
    property p_tmem_mma_req_stable;
        @(posedge clk) disable iff (reset)
        (tmem_mma_req_valid && !tmem_mma_req_ready) |=> tmem_mma_req_valid;
    endproperty
    a_tmem_mma_req_stable: assert property (p_tmem_mma_req_stable)
        else $error("VX_tcu_v2_sva_monitors: SVA tmem_mma_req_valid dropped while stalled");
`endif

    // -------------------------------------------------------------------------
    // Per-Pipe Protocol, Credit Conservation, Sparse Fault, and PMU Monitors
    // -------------------------------------------------------------------------
    for (genvar p = 0; p < NUM_TCU_PIPES; ++p) begin : g_pipe_sva
        logic                               prev_desc_valid_q;
        logic                               prev_desc_ready_q;
        tcu_v2_wgmma_desc_t                 prev_desc_q;

        logic                               prev_tile_in_valid_q;
        logic                               prev_tile_in_ready_q;

        logic                               prev_tile_out_valid_q;
        logic                               prev_tile_out_ready_q;
        logic [ARRAY_M-1:0][ARRAY_N-1:0][31:0] prev_d_tile_q;
        logic [7:0]                         prev_out_desc_id_q;
        tcu_v2_fp_flags_t                   prev_flags_out_q;

        logic                               prev_cta_out_valid_q;
        logic                               prev_cta_out_ready_q;
        logic [TCU_V2_BARRIER_ID_W-1:0]     prev_cta_out_bar_id_q;
        logic                               prev_cta_out_phase_q;

        logic                               prev_cta_in_valid_q;
        logic                               prev_cta_in_ready_q;
        logic [TCU_V2_BARRIER_ID_W-1:0]     prev_cta_in_bar_id_q;
        logic                               prev_cta_in_phase_q;

        tcu_v2_perf_cnt_t                   prev_perf_cnt_q;
        logic                               prev_sparse_fault_q;

        // Credit & inflight tracking (descriptors and tiles)
        logic signed [15:0]                 desc_inflight_q;
        logic signed [15:0]                 tile_inflight_q;
        logic [15:0]                        desc_stall_cnt_q;
        logic [15:0]                        tile_out_stall_cnt_q;
        logic [15:0]                        cta_stall_cnt_q;
        logic [31:0]                        legal_desc_cnt_q;
        logic [31:0]                        illegal_desc_cnt_q;
        logic [31:0]                        sparse_desc_cnt_q;
        logic [31:0]                        cta_pair_desc_cnt_q;
        logic [31:0]                        tile_in_fire_cnt_q;
        logic [31:0]                        tile_out_fire_cnt_q;
        logic                               last_desc_sparse_q;
        tcu_v2_fmt_e                        last_desc_fmt_a_q;
        logic                               sparse_meta_err_seen_q;

        logic desc_fire_w;
        logic desc_done_fire_w;
        logic tile_in_fire_w;
        logic tile_out_fire_w;
        logic cta_out_fire_w;
        logic cta_in_fire_w;
        logic desc_legal_w;
        logic desc_fields_valid_w;
        logic sparse_meta_legal_w;

        assign desc_fire_w        = desc_valid[p] && desc_ready[p];
        assign desc_done_fire_w   = desc_done_valid[p];
        assign tile_in_fire_w     = ext_tile_in_valid[p] && ext_tile_in_ready[p];
        assign tile_out_fire_w    = tile_out_valid[p] && tile_out_ready[p];
        assign cta_out_fire_w     = cta_sync_out_valid[p] && cta_sync_out_ready[p];
        assign cta_in_fire_w      = cta_sync_in_valid[p] && cta_sync_in_ready[p];
        assign desc_legal_w       = tcu_v2_desc_is_legal(desc_in[p]);
        assign desc_fields_valid_w = desc_meta_fields_known_and_bounded(desc_in[p]);
        assign sparse_meta_legal_w = sparse_tile_meta_all_legal(last_desc_fmt_a_q, ext_sparse_meta_in[p]);

        always_ff @(posedge clk) begin
            if (reset) begin
                prev_desc_valid_q     <= 1'b0;
                prev_desc_ready_q     <= 1'b0;
                prev_desc_q           <= '0;
                prev_tile_in_valid_q  <= 1'b0;
                prev_tile_in_ready_q  <= 1'b0;
                prev_tile_out_valid_q <= 1'b0;
                prev_tile_out_ready_q <= 1'b0;
                prev_d_tile_q         <= '0;
                prev_out_desc_id_q    <= 8'd0;
                prev_flags_out_q      <= '0;
                prev_cta_out_valid_q  <= 1'b0;
                prev_cta_out_ready_q  <= 1'b0;
                prev_cta_out_bar_id_q <= '0;
                prev_cta_out_phase_q  <= 1'b0;
                prev_cta_in_valid_q   <= 1'b0;
                prev_cta_in_ready_q   <= 1'b0;
                prev_cta_in_bar_id_q  <= '0;
                prev_cta_in_phase_q   <= 1'b0;
                prev_perf_cnt_q       <= '0;
                prev_sparse_fault_q   <= 1'b0;
                desc_inflight_q       <= 16'sd0;
                tile_inflight_q       <= 16'sd0;
                desc_stall_cnt_q      <= 16'd0;
                tile_out_stall_cnt_q  <= 16'd0;
                cta_stall_cnt_q       <= 16'd0;
                legal_desc_cnt_q      <= 32'd0;
                illegal_desc_cnt_q    <= 32'd0;
                sparse_desc_cnt_q     <= 32'd0;
                cta_pair_desc_cnt_q   <= 32'd0;
                tile_in_fire_cnt_q    <= 32'd0;
                tile_out_fire_cnt_q   <= 32'd0;
                last_desc_sparse_q    <= 1'b0;
                last_desc_fmt_a_q     <= TCU_V2_FMT_FP16;
                sparse_meta_err_seen_q <= 1'b0;
            end else begin
                prev_desc_valid_q     <= desc_valid[p];
                prev_desc_ready_q     <= desc_ready[p];
                prev_desc_q           <= desc_in[p];
                prev_tile_in_valid_q  <= ext_tile_in_valid[p];
                prev_tile_in_ready_q  <= ext_tile_in_ready[p];
                prev_tile_out_valid_q <= tile_out_valid[p];
                prev_tile_out_ready_q <= tile_out_ready[p];
                prev_d_tile_q         <= d_tile_out[p];
                prev_out_desc_id_q    <= out_desc_id[p];
                prev_flags_out_q      <= flags_out[p];
                prev_cta_out_valid_q  <= cta_sync_out_valid[p];
                prev_cta_out_ready_q  <= cta_sync_out_ready[p];
                prev_cta_out_bar_id_q <= cta_sync_out_bar_id[p];
                prev_cta_out_phase_q  <= cta_sync_out_phase[p];
                prev_cta_in_valid_q   <= cta_sync_in_valid[p];
                prev_cta_in_ready_q   <= cta_sync_in_ready[p];
                prev_cta_in_bar_id_q  <= cta_sync_in_bar_id[p];
                prev_cta_in_phase_q   <= cta_sync_in_phase[p];
                prev_perf_cnt_q       <= tcu_perf_cnt_out[p];
                prev_sparse_fault_q   <= sparse_fault_out[p];

                // Track descriptor credit accounting (only legal descriptors enter the pipe)
                if (desc_fire_w) begin
                    if (desc_legal_w) begin
                        legal_desc_cnt_q  <= legal_desc_cnt_q + 32'd1;
                        last_desc_sparse_q <= desc_in[p].sparse_en;
                        last_desc_fmt_a_q <= desc_in[p].fmt_a;
                        if (desc_in[p].sparse_en) begin
                            sparse_desc_cnt_q <= sparse_desc_cnt_q + 32'd1;
                        end
                        if (desc_in[p].cta_pair_en) begin
                            cta_pair_desc_cnt_q <= cta_pair_desc_cnt_q + 32'd1;
                        end
                    end else begin
                        illegal_desc_cnt_q <= illegal_desc_cnt_q + 32'd1;
                    end
                end

                case ({(desc_fire_w && desc_legal_w), desc_done_fire_w})
                    2'b10:   desc_inflight_q <= desc_inflight_q + 16'sd1;
                    2'b01:   desc_inflight_q <= desc_inflight_q - 16'sd1;
                    default: desc_inflight_q <= desc_inflight_q;
                endcase

                if (tile_in_fire_w) begin
                    tile_in_fire_cnt_q <= tile_in_fire_cnt_q + 32'd1;
                    if (last_desc_sparse_q && !sparse_meta_legal_w) begin
                        sparse_meta_err_seen_q <= 1'b1;
                    end
                end
                if (tile_out_fire_w) begin
                    tile_out_fire_cnt_q <= tile_out_fire_cnt_q + 32'd1;
                end

                case ({tile_in_fire_w, tile_out_fire_w})
                    2'b10:   tile_inflight_q <= tile_inflight_q + 16'sd1;
                    2'b01:   tile_inflight_q <= tile_inflight_q - 16'sd1;
                    default: tile_inflight_q <= tile_inflight_q;
                endcase

                if (desc_valid[p] && !desc_ready[p]) begin
                    if (desc_stall_cnt_q != 16'hFFFF) begin
                        desc_stall_cnt_q <= desc_stall_cnt_q + 16'd1;
                    end
                end else begin
                    desc_stall_cnt_q <= 16'd0;
                end

                if (tile_out_valid[p] && !tile_out_ready[p]) begin
                    if (tile_out_stall_cnt_q != 16'hFFFF) begin
                        tile_out_stall_cnt_q <= tile_out_stall_cnt_q + 16'd1;
                    end
                end else begin
                    tile_out_stall_cnt_q <= 16'd0;
                end

                if (cta_sync_out_valid[p] && !cta_sync_out_ready[p]) begin
                    if (cta_stall_cnt_q != 16'hFFFF) begin
                        cta_stall_cnt_q <= cta_stall_cnt_q + 16'd1;
                    end
                end else begin
                    cta_stall_cnt_q <= 16'd0;
                end
            end
        end

        // ---------------------------------------------------------------------
        // Immediate Clocked Assertions (Verilator --assert & Formal Safe)
        // ---------------------------------------------------------------------
        always_ff @(posedge clk) begin
            if (!reset) begin
                // 1. No X/Z on control signals
                assert (!$isunknown({
                    desc_valid[p], desc_ready[p],
                    ext_tile_in_valid[p], ext_tile_in_ready[p],
                    tile_out_valid[p], tile_out_ready[p],
                    desc_done_valid[p], sparse_fault_out[p],
                    cta_sync_out_valid[p], cta_sync_out_ready[p],
                    cta_sync_in_valid[p], cta_sync_in_ready[p]
                })) else $error("VX_tcu_v2_sva_monitors[pipe %0d]: X/Z on control signals", p);

                if (desc_valid[p]) begin
                    assert (!$isunknown(desc_in[p]))
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: X/Z on desc_in payload", p);
                end

                if (tile_out_valid[p]) begin
                    assert (!$isunknown({d_tile_out[p], out_desc_id[p], flags_out[p]}))
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: X/Z on tile_out payload", p);
                end

                if (desc_done_valid[p]) begin
                    assert (!$isunknown(desc_done_id[p]))
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: X/Z on desc_done_id", p);
                end

                // 2. Legal format IDs & barrier ID bounds on valid descriptor submission
                if (desc_valid[p] && desc_legal_w) begin
                    assert (desc_fields_valid_w)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: legal descriptor failed format/barrier bounds", p);
                    if (desc_in[p].sparse_en) begin
                        assert (is_sparse_capable_fmt(desc_in[p].fmt_a))
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: sparse_en set with unsupported fmt_a=%0d", p, desc_in[p].fmt_a);
                    end
                end

                // 3. CTA sync barrier ID bounds & X/Z check when active
                if (cta_sync_out_valid[p]) begin
                    assert (!$isunknown({cta_sync_out_bar_id[p], cta_sync_out_phase[p]}))
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: X/Z on cta_sync_out", p);
                    assert (int'(cta_sync_out_bar_id[p]) < TCU_V2_MAX_BARRIERS)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_out_bar_id OOB (%0d)", p, cta_sync_out_bar_id[p]);
                end
                if (cta_sync_in_valid[p]) begin
                    assert (!$isunknown({cta_sync_in_bar_id[p], cta_sync_in_phase[p]}))
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: X/Z on cta_sync_in", p);
                    assert (int'(cta_sync_in_bar_id[p]) < TCU_V2_MAX_BARRIERS)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_in_bar_id OOB (%0d)", p, cta_sync_in_bar_id[p]);
                end

                // 4. Protocol stability across stalled handshakes
                if (prev_valid_q && !prev_reset_q) begin
                    if (prev_desc_valid_q && !prev_desc_ready_q) begin
                        assert (desc_valid[p])
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: desc_valid dropped before desc_ready", p);
                        assert (desc_in[p] == prev_desc_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: desc_in mutated while stalled", p);
                    end

                    if (prev_tile_in_valid_q && !prev_tile_in_ready_q) begin
                        assert (ext_tile_in_valid[p])
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: ext_tile_in_valid dropped before ready", p);
                    end

                    if (prev_tile_out_valid_q && !prev_tile_out_ready_q) begin
                        assert (tile_out_valid[p])
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: tile_out_valid dropped before ready", p);
                        assert (d_tile_out[p] == prev_d_tile_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: d_tile_out mutated while stalled", p);
                        assert (out_desc_id[p] == prev_out_desc_id_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: out_desc_id mutated while stalled", p);
                        assert (flags_out[p] == prev_flags_out_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: flags_out mutated while stalled", p);
                    end

                    if (prev_cta_out_valid_q && !prev_cta_out_ready_q) begin
                        assert (cta_sync_out_valid[p])
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_out_valid dropped before ready", p);
                        assert (cta_sync_out_bar_id[p] == prev_cta_out_bar_id_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_out_bar_id mutated while stalled", p);
                        assert (cta_sync_out_phase[p] == prev_cta_out_phase_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_out_phase mutated while stalled", p);
                    end

                    if (prev_cta_in_valid_q && !prev_cta_in_ready_q) begin
                        assert (cta_sync_in_valid[p])
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_in_valid dropped before ready", p);
                        assert (cta_sync_in_bar_id[p] == prev_cta_in_bar_id_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_in_bar_id mutated while stalled", p);
                        assert (cta_sync_in_phase[p] == prev_cta_in_phase_q)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_in_phase mutated while stalled", p);
                    end

                    // 5. Non-decreasing active cycles & performance counters (unless perf_clear)
                    if (!perf_clear && !prev_perf_clear_q) begin
                        assert (tcu_perf_cnt_out[p].active_cycles >= prev_perf_cnt_q.active_cycles)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: active_cycles decreased", p);
                        assert (tcu_perf_cnt_out[p].stall_cycles >= prev_perf_cnt_q.stall_cycles)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: stall_cycles decreased", p);
                        assert (tcu_perf_cnt_out[p].cta_wait_cycles >= prev_perf_cnt_q.cta_wait_cycles)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_wait_cycles decreased", p);
                        assert (tcu_perf_cnt_out[p].uops_issued >= prev_perf_cnt_q.uops_issued)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: uops_issued decreased", p);
                        assert (tcu_perf_cnt_out[p].uops_retired >= prev_perf_cnt_q.uops_retired)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: uops_retired decreased", p);
                        assert (tcu_perf_cnt_out[p].descs_completed >= prev_perf_cnt_q.descs_completed)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: descs_completed decreased", p);
                        assert (tcu_perf_cnt_out[p].sparse_uops >= prev_perf_cnt_q.sparse_uops)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: sparse_uops decreased", p);
                        assert (tcu_perf_cnt_out[p].sparse_faults >= prev_perf_cnt_q.sparse_faults)
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: sparse_faults decreased", p);
                    end

                    // 6. Sparse fault accuracy & sticky consistency
                    assert (tcu_perf_cnt_out[p].uops_retired <= tcu_perf_cnt_out[p].uops_issued)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: uops_retired > uops_issued", p);

                    if (sparse_fault_out[p] && !prev_sparse_fault_q) begin
                        assert ((tcu_perf_cnt_out[p].sparse_faults > 32'd0) || sparse_meta_err_seen_q ||
                                (tcu_perf_cnt_out[p].cta_wait_cycles > 32'd0))
                            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: sparse_fault asserted without fault cause", p);
                    end
                end

                // 7. Zero unexpected overflow/underflow of internal credits
                assert (desc_inflight_q >= 16'sd0)
                    else $error("VX_tcu_v2_sva_monitors[pipe %0d]: descriptor credit underflow (%0d)", p, desc_inflight_q);
                assert (desc_inflight_q <= 16'(DESC_CREDIT_CAP))
                    else $error("VX_tcu_v2_sva_monitors[pipe %0d]: descriptor credit overflow (%0d)", p, desc_inflight_q);

                assert (tile_inflight_q >= 16'sd0)
                    else $error("VX_tcu_v2_sva_monitors[pipe %0d]: tile credit underflow (%0d)", p, tile_inflight_q);
                assert (tile_inflight_q <= 16'(TILE_CREDIT_CAP))
                    else $error("VX_tcu_v2_sva_monitors[pipe %0d]: tile credit overflow (%0d)", p, tile_inflight_q);

                if (MAX_STALL_CYC > 0) begin
                    assert (int'(desc_stall_cnt_q) < MAX_STALL_CYC)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: desc handshake stalled >= %0d cycles", p, MAX_STALL_CYC);
                    assert (int'(tile_out_stall_cnt_q) < MAX_STALL_CYC)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: tile_out handshake stalled >= %0d cycles", p, MAX_STALL_CYC);
                    assert (int'(cta_stall_cnt_q) < MAX_STALL_CYC)
                        else $error("VX_tcu_v2_sva_monitors[pipe %0d]: cta_sync_out handshake stalled >= %0d cycles", p, MAX_STALL_CYC);
                end
            end
        end

        // ---------------------------------------------------------------------
        // Concurrent SVA Properties (Verilator 5.050 --assert Compatible)
        // ---------------------------------------------------------------------
`ifdef ASSERTIONS
        property p_desc_ctrl_known;
            @(posedge clk) disable iff (reset)
            !$isunknown({desc_valid[p], desc_ready[p]});
        endproperty
        a_desc_ctrl_known: assert property (p_desc_ctrl_known)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA X/Z on desc valid/ready", p);

        property p_desc_valid_stable;
            @(posedge clk) disable iff (reset)
            (desc_valid[p] && !desc_ready[p]) |=> (desc_valid[p] && $stable(desc_in[p]));
        endproperty
        a_desc_valid_stable: assert property (p_desc_valid_stable)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA desc_valid/payload unstable", p);

        property p_tile_in_valid_stable;
            @(posedge clk) disable iff (reset)
            (ext_tile_in_valid[p] && !ext_tile_in_ready[p]) |=> ext_tile_in_valid[p];
        endproperty
        a_tile_in_valid_stable: assert property (p_tile_in_valid_stable)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA ext_tile_in_valid unstable", p);

        property p_tile_out_valid_stable;
            @(posedge clk) disable iff (reset)
            (tile_out_valid[p] && !tile_out_ready[p]) |=>
                (tile_out_valid[p] && $stable(d_tile_out[p]) && $stable(out_desc_id[p]) && $stable(flags_out[p]));
        endproperty
        a_tile_out_valid_stable: assert property (p_tile_out_valid_stable)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA tile_out_valid/payload unstable", p);

        property p_cta_out_stable;
            @(posedge clk) disable iff (reset)
            (cta_sync_out_valid[p] && !cta_sync_out_ready[p]) |=>
                (cta_sync_out_valid[p] && $stable(cta_sync_out_bar_id[p]) && $stable(cta_sync_out_phase[p]));
        endproperty
        a_cta_out_stable: assert property (p_cta_out_stable)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA cta_sync_out unstable", p);

        property p_cta_bar_id_bounded;
            @(posedge clk) disable iff (reset)
            cta_sync_out_valid[p] |-> (int'(cta_sync_out_bar_id[p]) < TCU_V2_MAX_BARRIERS);
        endproperty
        a_cta_bar_id_bounded: assert property (p_cta_bar_id_bounded)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA CTA barrier ID out of bounds", p);

        property p_perf_active_monotonic;
            @(posedge clk) disable iff (reset)
            (!perf_clear && !prev_perf_clear_q && prev_valid_q && !prev_reset_q) |->
                (tcu_perf_cnt_out[p].active_cycles >= prev_perf_cnt_q.active_cycles);
        endproperty
        a_perf_active_monotonic: assert property (p_perf_active_monotonic)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA active_cycles decreased", p);

        property p_desc_credit_bounds;
            @(posedge clk) disable iff (reset)
            ((desc_inflight_q >= 16'sd0) && (desc_inflight_q <= 16'(DESC_CREDIT_CAP)));
        endproperty
        a_desc_credit_bounds: assert property (p_desc_credit_bounds)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA descriptor credit out of range", p);

        property p_tile_credit_bounds;
            @(posedge clk) disable iff (reset)
            ((tile_inflight_q >= 16'sd0) && (tile_inflight_q <= 16'(TILE_CREDIT_CAP)));
        endproperty
        a_tile_credit_bounds: assert property (p_tile_credit_bounds)
            else $error("VX_tcu_v2_sva_monitors[pipe %0d]: SVA tile credit out of range", p);
`endif

        logic _unused_pipe_mon;
        assign _unused_pipe_mon = &{1'b0,
            cta_out_fire_w, cta_in_fire_w,
            legal_desc_cnt_q, illegal_desc_cnt_q,
            sparse_desc_cnt_q, cta_pair_desc_cnt_q,
            tile_in_fire_cnt_q, tile_out_fire_cnt_q
        };
    end

endmodule
