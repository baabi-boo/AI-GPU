// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TCU_V2_PKG_SV
`define VX_TCU_V2_PKG_SV

package VX_tcu_v2_pkg;

    // -------------------------------------------------------------------------
    // Geometry and Arithmetic Pipeline Localparams
    // -------------------------------------------------------------------------
    localparam int TCU_V2_ARRAY_M         = 16;
    localparam int TCU_V2_ARRAY_N         = 8;
    localparam int TCU_V2_ARRAY_K         = 8;
    localparam int TCU_V2_PE_RATIO        = 1;
    localparam int TCU_V2_BLOCKS_PER_CORE = 4;
    localparam int TCU_V2_WARP_THREADS    = 32;
    localparam int TCU_V2_MAX_WARPS       = 32;
    localparam int TCU_V2_DESC_Q_DEPTH    = 16;
    localparam int TCU_V2_MAX_BARRIERS    = 16;
    localparam int TCU_V2_CTA_PAIR_MAX    = 2;

    localparam int TCU_V2_FP_EXP_W        = 10;
    localparam int TCU_V2_FP_SIG_W        = 24;
    localparam int TCU_V2_WIDE_ACC_W      = 48;
    localparam int TCU_V2_SCALE_W         = 8;
    localparam int TCU_V2_DESC_ID_W       = 8;
    localparam int TCU_V2_TMEM_ROW_W      = 7;
    localparam int TCU_V2_TMEM_COL_W      = 9;
    localparam int TCU_V2_BARRIER_ID_W    = 4;
    localparam int TCU_V2_SPARSE_PAIR_W   = 4;
    localparam int TCU_V2_ELEM_LANE_W     = 32;
    localparam int TCU_V2_MAX_LANES       = 8;

    localparam logic [31:0] TCU_V2_CANONICAL_QNAN = 32'h7FC0_0000;
    localparam logic [31:0] TCU_V2_FP32_POS_INF   = 32'h7F80_0000;
    localparam logic [31:0] TCU_V2_FP32_NEG_INF   = 32'hFF80_0000;
    localparam logic [31:0] TCU_V2_FP32_POS_ZERO  = 32'h0000_0000;
    localparam logic [31:0] TCU_V2_FP32_NEG_ZERO  = 32'h8000_0000;

    localparam logic [31:0] TCU_V2_INT32_MAX      = 32'h7FFF_FFFF;
    localparam logic [31:0] TCU_V2_INT32_MIN      = 32'h8000_0000;

    // -------------------------------------------------------------------------
    // Numeric, Scale, Rounding, and Epilogue Enumerations
    // -------------------------------------------------------------------------
    typedef enum logic [4:0] {
        TCU_V2_FMT_FP32       = 5'd0,
        TCU_V2_FMT_TF32       = 5'd1,
        TCU_V2_FMT_FP16       = 5'd2,
        TCU_V2_FMT_BF16       = 5'd3,
        TCU_V2_FMT_FP8_E4M3   = 5'd4,
        TCU_V2_FMT_FP8_E5M2   = 5'd5,
        TCU_V2_FMT_MXFP8_E4M3 = 5'd8,
        TCU_V2_FMT_MXFP8_E5M2 = 5'd9,
        TCU_V2_FMT_MXFP4_E2M1 = 5'd10,
        TCU_V2_FMT_NVFP4_E2M1 = 5'd11,
        TCU_V2_FMT_MXFP6_E2M3 = 5'd12,
        TCU_V2_FMT_MXFP6_E3M2 = 5'd13,
        TCU_V2_FMT_I32        = 5'd16,
        TCU_V2_FMT_INT8       = 5'd17
    } tcu_v2_fmt_e;

    typedef enum logic [1:0] {
        TCU_V2_SCALE_NONE  = 2'd0,
        TCU_V2_SCALE_UE8M0 = 2'd1,
        TCU_V2_SCALE_E4M3  = 2'd2
    } tcu_v2_scale_fmt_e;

    typedef enum logic [2:0] {
        TCU_V2_RM_RNE = 3'd0,
        TCU_V2_RM_RTZ = 3'd1,
        TCU_V2_RM_RDN = 3'd2,
        TCU_V2_RM_RUP = 3'd3,
        TCU_V2_RM_RMM = 3'd4
    } tcu_v2_rm_e;

    typedef enum logic [2:0] {
        TCU_V2_ACT_NONE  = 3'd0,
        TCU_V2_ACT_RELU  = 3'd1,
        TCU_V2_ACT_CLAMP = 3'd2,
        TCU_V2_ACT_SILU  = 3'd3,
        TCU_V2_ACT_GELU  = 3'd4
    } tcu_v2_act_e;

    typedef enum logic [1:0] {
        TCU_V2_PIPE_IDLE     = 2'd0,
        TCU_V2_PIPE_ACTIVE   = 2'd1,
        TCU_V2_PIPE_CTA_WAIT = 2'd2,
        TCU_V2_PIPE_FAULT    = 2'd3
    } tcu_v2_pipe_state_e;

    // -------------------------------------------------------------------------
    // Packed Arithmetic, Descriptor, Micro-Op, and Telemetry Structs
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic                              sign;
        logic signed [TCU_V2_FP_EXP_W-1:0] exp;
        logic [TCU_V2_FP_SIG_W-1:0]        sig;
        logic                              is_zero;
        logic                              is_inf;
        logic                              is_nan;
        logic                              is_subnormal;
    } tcu_v2_fp_unpacked_t;

    typedef struct packed {
        tcu_v2_scale_fmt_e                 scale_fmt;
        logic                              is_zero;
        logic                              is_nan;
        logic signed [TCU_V2_FP_EXP_W-1:0] exp_delta;
        logic [3:0]                        mant_u1p3;
    } tcu_v2_scale_decoded_t;

    typedef struct packed {
        logic nv;
        logic dz;
        logic of;
        logic uf;
        logic nx;
    } tcu_v2_fp_flags_t;

    typedef struct packed {
        logic [1:0] idx1;
        logic [1:0] idx0;
    } tcu_v2_sparse_meta4_t;

    typedef struct packed {
        logic [TCU_V2_DESC_ID_W-1:0]    desc_id;
        tcu_v2_fmt_e                    fmt_a;
        tcu_v2_fmt_e                    fmt_b;
        tcu_v2_fmt_e                    fmt_c;
        tcu_v2_fmt_e                    fmt_d;
        tcu_v2_scale_fmt_e              scale_fmt;
        tcu_v2_rm_e                     rm;
        tcu_v2_act_e                    act;
        logic                           sparse_en;
        logic                           cta_pair_en;
        logic                           accum_en;
        logic                           bias_en;
        logic                           int_saturate;
        logic                           tmem_wb_en;
        logic [TCU_V2_BARRIER_ID_W-1:0] barrier_id;
        logic                           barrier_phase;
        logic [15:0]                    tile_m;
        logic [15:0]                    tile_n;
        logic [15:0]                    tile_k;
        logic [TCU_V2_TMEM_ROW_W-1:0]   tmem_a_row;
        logic [TCU_V2_TMEM_COL_W-1:0]   tmem_a_col;
        logic [TCU_V2_TMEM_ROW_W-1:0]   tmem_b_row;
        logic [TCU_V2_TMEM_COL_W-1:0]   tmem_b_col;
        logic [TCU_V2_TMEM_ROW_W-1:0]   tmem_c_row;
        logic [TCU_V2_TMEM_COL_W-1:0]   tmem_c_col;
        logic [TCU_V2_TMEM_ROW_W-1:0]   tmem_d_row;
        logic [TCU_V2_TMEM_COL_W-1:0]   tmem_d_col;
        logic [31:0]                    clamp_min_fp32;
        logic [31:0]                    clamp_max_fp32;
    } tcu_v2_wgmma_desc_t;

    typedef struct packed {
        logic [TCU_V2_DESC_ID_W-1:0]    desc_id;
        logic [3:0]                     step_m;
        logic [3:0]                     step_n;
        logic [7:0]                     step_k;
        tcu_v2_fmt_e                    fmt_a;
        tcu_v2_fmt_e                    fmt_b;
        tcu_v2_fmt_e                    fmt_d;
        tcu_v2_scale_fmt_e              scale_fmt;
        tcu_v2_rm_e                     rm;
        tcu_v2_act_e                    act;
        logic                           is_first_k;
        logic                           is_last_k;
        logic                           accum_en;
        logic                           bias_en;
        logic                           sparse_en;
        logic                           int_saturate;
        logic [31:0]                    clamp_min_fp32;
        logic [31:0]                    clamp_max_fp32;
    } tcu_v2_uop_t;

    typedef struct packed {
        logic                         valid;
        logic                         is_write;
        logic [TCU_V2_DESC_ID_W-1:0]  desc_id;
        logic [1:0]                   operand_sel;
        logic [TCU_V2_TMEM_ROW_W-1:0] row;
        logic [TCU_V2_TMEM_COL_W-1:0] col;
        logic [1:0]                   swizzle_mode;
        logic [7:0]                   col_count;
    } tcu_v2_tmem_req_t;

    typedef struct packed {
        tcu_v2_pipe_state_e          state;
        logic                        desc_q_empty;
        logic                        desc_q_full;
        logic [4:0]                  desc_q_count;
        logic                        array_busy;
        logic                        cta_sync_pending;
        logic                        sparse_fault_latched;
        logic [TCU_V2_DESC_ID_W-1:0] active_desc_id;
    } tcu_v2_pipe_status_t;

    typedef struct packed {
        logic [31:0] active_cycles;
        logic [31:0] stall_cycles;
        logic [31:0] cta_wait_cycles;
        logic [31:0] uops_issued;
        logic [31:0] uops_retired;
        logic [31:0] descs_completed;
        logic [31:0] sparse_uops;
        logic [31:0] sparse_faults;
    } tcu_v2_perf_cnt_t;

    // -------------------------------------------------------------------------
    // Format Property Query Functions
    // -------------------------------------------------------------------------
    function automatic int unsigned tcu_v2_fmt_bitwidth(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_I32:        return 32;
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16:       return 16;
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_INT8:       return 8;
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2: return 6;
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: return 4;
            default:               return 0;
        endcase
    endfunction

    function automatic int unsigned tcu_v2_fmt_exp_bits(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_BF16:       return 8;
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E5M2: return 5;
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_MXFP8_E4M3: return 4;
            TCU_V2_FMT_MXFP6_E3M2: return 3;
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: return 2;
            default:               return 0;
        endcase
    endfunction

    function automatic int unsigned tcu_v2_fmt_man_bits(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32:       return 23;
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP16:       return 10;
            TCU_V2_FMT_BF16:       return 7;
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP6_E2M3: return 3;
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP6_E3M2: return 2;
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: return 1;
            default:               return 0;
        endcase
    endfunction

    function automatic int unsigned tcu_v2_fmt_bias(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_BF16:       return 127;
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E5M2: return 15;
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_MXFP8_E4M3: return 7;
            TCU_V2_FMT_MXFP6_E3M2: return 3;
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: return 1;
            default:               return 0;
        endcase
    endfunction

    function automatic logic tcu_v2_fmt_is_mx(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2: return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic tcu_v2_fmt_is_fp4(
        input tcu_v2_fmt_e fmt
    );
        return (fmt == TCU_V2_FMT_MXFP4_E2M1) || (fmt == TCU_V2_FMT_NVFP4_E2M1);
    endfunction

    function automatic logic tcu_v2_fmt_is_fp6(
        input tcu_v2_fmt_e fmt
    );
        return (fmt == TCU_V2_FMT_MXFP6_E2M3) || (fmt == TCU_V2_FMT_MXFP6_E3M2);
    endfunction

    function automatic logic tcu_v2_fmt_is_fp8(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2: return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic tcu_v2_fmt_is_int(
        input tcu_v2_fmt_e fmt
    );
        return (fmt == TCU_V2_FMT_I32) || (fmt == TCU_V2_FMT_INT8);
    endfunction

    function automatic logic tcu_v2_fmt_has_inf(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E5M2: return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic logic tcu_v2_fmt_has_nan(
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
            TCU_V2_FMT_MXFP8_E5M2: return 1'b1;
            default:               return 1'b0;
        endcase
    endfunction

    function automatic int unsigned tcu_v2_fmt_scale_block(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2: return 32;
            TCU_V2_FMT_NVFP4_E2M1: return 16;
            default:               return 1;
        endcase
    endfunction

    function automatic tcu_v2_scale_fmt_e tcu_v2_fmt_default_scale(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2: return TCU_V2_SCALE_UE8M0;
            TCU_V2_FMT_NVFP4_E2M1: return TCU_V2_SCALE_E4M3;
            default:               return TCU_V2_SCALE_NONE;
        endcase
    endfunction

    function automatic int unsigned tcu_v2_fmt_elems_per_word32(
        input tcu_v2_fmt_e fmt
    );
        case (fmt)
            TCU_V2_FMT_FP32,
            TCU_V2_FMT_TF32,
            TCU_V2_FMT_I32:        return 1;
            TCU_V2_FMT_FP16,
            TCU_V2_FMT_BF16:       return 2;
            TCU_V2_FMT_FP8_E4M3,
            TCU_V2_FMT_FP8_E5M2,
            TCU_V2_FMT_MXFP8_E4M3,
            TCU_V2_FMT_MXFP8_E5M2,
            TCU_V2_FMT_MXFP6_E2M3,
            TCU_V2_FMT_MXFP6_E3M2,
            TCU_V2_FMT_INT8:       return 4;
            TCU_V2_FMT_MXFP4_E2M1,
            TCU_V2_FMT_NVFP4_E2M1: return 8;
            default:               return 0;
        endcase
    endfunction

    // -------------------------------------------------------------------------
    // Structured 2:4 Sparsity, IEEE-754 Helpers, and Constants Checkers
    // -------------------------------------------------------------------------
    function automatic logic tcu_v2_sparse_pair_legal(
        input tcu_v2_sparse_meta4_t meta
    );
        return (meta.idx0 < meta.idx1);
    endfunction

    function automatic logic tcu_v2_fp32_is_nan(
        input logic [31:0] val
    );
        logic sign_unused;
        sign_unused = val[31];
        return ((val[30:23] == 8'hFF) && (val[22:0] != 23'd0)) &&
               ((sign_unused == 1'b0) || (sign_unused == 1'b1));
    endfunction

    function automatic logic tcu_v2_fp32_is_inf(
        input logic [31:0] val
    );
        logic sign_unused;
        sign_unused = val[31];
        return ((val[30:23] == 8'hFF) && (val[22:0] == 23'd0)) &&
               ((sign_unused == 1'b0) || (sign_unused == 1'b1));
    endfunction

    function automatic logic tcu_v2_fp32_is_zero(
        input logic [31:0] val
    );
        logic sign_unused;
        sign_unused = val[31];
        return (val[30:0] == 31'd0) &&
               ((sign_unused == 1'b0) || (sign_unused == 1'b1));
    endfunction

    function automatic logic tcu_v2_fp32_is_subnormal(
        input logic [31:0] val
    );
        logic sign_unused;
        sign_unused = val[31];
        return ((val[30:23] == 8'd0) && (val[22:0] != 23'd0)) &&
               ((sign_unused == 1'b0) || (sign_unused == 1'b1));
    endfunction

    function automatic logic [31:0] tcu_v2_fp32_canonical_special(
        input logic       is_nan,
        input logic       is_inf,
        input logic       sign
    );
        if (is_nan) begin
            return TCU_V2_CANONICAL_QNAN;
        end else if (is_inf) begin
            return sign ? TCU_V2_FP32_NEG_INF : TCU_V2_FP32_POS_INF;
        end else begin
            return sign ? TCU_V2_FP32_NEG_ZERO : TCU_V2_FP32_POS_ZERO;
        end
    endfunction

    function automatic logic [31:0] tcu_v2_int32_sat_bound(
        input logic is_negative
    );
        return is_negative ? TCU_V2_INT32_MIN : TCU_V2_INT32_MAX;
    endfunction

    function automatic tcu_v2_fp_flags_t tcu_v2_flags_or(
        input tcu_v2_fp_flags_t a,
        input tcu_v2_fp_flags_t b
    );
        tcu_v2_fp_flags_t res;
        res.nv = a.nv | b.nv;
        res.dz = a.dz | b.dz;
        res.of = a.of | b.of;
        res.uf = a.uf | b.uf;
        res.nx = a.nx | b.nx;
        return res;
    endfunction

    function automatic tcu_v2_fp_unpacked_t tcu_v2_unpack_fp32(
        input logic [31:0] val
    );
        tcu_v2_fp_unpacked_t u;
        logic [7:0] exp_raw;
        logic [22:0] man_raw;
        exp_raw = val[30:23];
        man_raw = val[22:0];
        u.sign = val[31];
        u.is_zero = (exp_raw == 8'd0) && (man_raw == 23'd0);
        u.is_subnormal = (exp_raw == 8'd0) && (man_raw != 23'd0);
        u.is_inf = (exp_raw == 8'hFF) && (man_raw == 23'd0);
        u.is_nan = (exp_raw == 8'hFF) && (man_raw != 23'd0);
        if (u.is_zero || u.is_inf || u.is_nan) begin
            u.exp = '0;
            u.sig = {1'b0, man_raw};
        end else if (u.is_subnormal) begin
            u.exp = $signed(10'd1) - $signed(10'd127);
            u.sig = {1'b0, man_raw};
        end else begin
            u.exp = $signed({2'b00, exp_raw}) - $signed(10'd127);
            u.sig = {1'b1, man_raw};
        end
        return u;
    endfunction

    function automatic tcu_v2_scale_decoded_t tcu_v2_decode_scale(
        input tcu_v2_scale_fmt_e scale_fmt,
        input logic [7:0]        scale_raw
    );
        tcu_v2_scale_decoded_t d;
        logic [3:0] e4;
        logic [2:0] m3;
        d.scale_fmt = scale_fmt;
        d.is_zero   = 1'b0;
        d.is_nan    = 1'b0;
        d.exp_delta = '0;
        d.mant_u1p3 = 4'b1000;
        case (scale_fmt)
            TCU_V2_SCALE_NONE: begin
                d.exp_delta = '0;
                d.mant_u1p3 = 4'b1000;
            end
            TCU_V2_SCALE_UE8M0: begin
                if (scale_raw == 8'hFF) begin
                    d.is_nan = 1'b1;
                end else begin
                    d.exp_delta = $signed({2'b00, scale_raw}) - $signed(10'd127);
                end
            end
            TCU_V2_SCALE_E4M3: begin
                e4 = scale_raw[6:3];
                m3 = scale_raw[2:0];
                if (scale_raw[7]) begin
                    d.is_nan = 1'b1;
                end else if ((e4 == 4'hF) && (m3 == 3'h7)) begin
                    d.is_nan = 1'b1;
                end else if ((e4 == 4'd0) && (m3 == 3'd0)) begin
                    d.is_zero = 1'b1;
                    d.mant_u1p3 = 4'b0000;
                end else if (e4 == 4'd0) begin
                    d.exp_delta = $signed(10'd1) - $signed(10'd7);
                    d.mant_u1p3 = {1'b0, m3};
                end else begin
                    d.exp_delta = $signed({6'b000000, e4}) - $signed(10'd7);
                    d.mant_u1p3 = {1'b1, m3};
                end
            end
            default: begin
                d.exp_delta = '0;
            end
        endcase
        return d;
    endfunction

    function automatic logic tcu_v2_desc_is_legal(
        input tcu_v2_wgmma_desc_t desc
    );
        logic fmt_ok;
        logic dim_ok;
        logic scale_ok;
        logic meta_ok;
        logic unused_ok;
        fmt_ok = (tcu_v2_fmt_bitwidth(desc.fmt_a) != 0) &&
                 (tcu_v2_fmt_bitwidth(desc.fmt_b) != 0) &&
                 (tcu_v2_fmt_bitwidth(desc.fmt_c) != 0) &&
                 (tcu_v2_fmt_bitwidth(desc.fmt_d) != 0) &&
                 (desc.fmt_a != TCU_V2_FMT_FP32) && (desc.fmt_a != TCU_V2_FMT_I32) &&
                 (desc.fmt_b != TCU_V2_FMT_FP32) && (desc.fmt_b != TCU_V2_FMT_I32) &&
                 (tcu_v2_fmt_is_int(desc.fmt_a) == tcu_v2_fmt_is_int(desc.fmt_b));
        dim_ok = (desc.tile_m != 16'd0) && ((desc.tile_m % 16'd16) == 16'd0) &&
                 (desc.tile_n != 16'd0) && ((desc.tile_n % 16'd8) == 16'd0) &&
                 (desc.tile_k != 16'd0) && ((desc.tile_k % 16'd8) == 16'd0);
        if (tcu_v2_fmt_is_mx(desc.fmt_a) || tcu_v2_fmt_is_mx(desc.fmt_b)) begin
            scale_ok = (desc.scale_fmt != TCU_V2_SCALE_NONE);
        end else begin
            scale_ok = (desc.scale_fmt == TCU_V2_SCALE_NONE);
        end
        meta_ok = (desc.rm <= TCU_V2_RM_RMM) &&
                  (desc.act <= TCU_V2_ACT_GELU) &&
                  (int'(desc.barrier_id) < TCU_V2_MAX_BARRIERS);
        unused_ok = ^{desc.desc_id, desc.sparse_en, desc.cta_pair_en, desc.accum_en,
                      desc.bias_en, desc.int_saturate, desc.tmem_wb_en,
                      desc.barrier_phase, desc.tmem_a_row, desc.tmem_a_col,
                      desc.tmem_b_row, desc.tmem_b_col, desc.tmem_c_row,
                      desc.tmem_c_col, desc.tmem_d_row, desc.tmem_d_col,
                      desc.clamp_min_fp32, desc.clamp_max_fp32};
        return (fmt_ok && dim_ok && scale_ok && meta_ok) || (unused_ok && 1'b0);
    endfunction

    function automatic int unsigned tcu_v2_uop_count_for_desc(
        input tcu_v2_wgmma_desc_t desc,
        input int                 array_m = TCU_V2_ARRAY_M,
        input int                 array_n = TCU_V2_ARRAY_N,
        input int                 array_k = TCU_V2_ARRAY_K
    );
        int unsigned steps_m;
        int unsigned steps_n;
        int unsigned steps_k;
        int unsigned k_step_elems;
        logic        unused_desc;
        k_step_elems = desc.sparse_en ? (2 * array_k) : array_k;
        steps_m = (int'(desc.tile_m) + array_m - 1) / array_m;
        steps_n = (int'(desc.tile_n) + array_n - 1) / array_n;
        steps_k = (int'(desc.tile_k) + k_step_elems - 1) / k_step_elems;
        unused_desc = ^desc;
        return (steps_m * steps_n * steps_k) + (unused_desc ? 0 : 0);
    endfunction

    function automatic int unsigned tcu_v2_output_tile_count_for_desc(
        input tcu_v2_wgmma_desc_t desc,
        input int                 array_m = TCU_V2_ARRAY_M,
        input int                 array_n = TCU_V2_ARRAY_N
    );
        int unsigned steps_m;
        int unsigned steps_n;
        logic        unused_desc;
        steps_m = (int'(desc.tile_m) + array_m - 1) / array_m;
        steps_n = (int'(desc.tile_n) + array_n - 1) / array_n;
        unused_desc = ^desc;
        return (steps_m * steps_n) + (unused_desc ? 0 : 0);
    endfunction

    function automatic logic tcu_v2_arch_params_valid();
        return (TCU_V2_PE_RATIO == 1) &&
               (TCU_V2_BLOCKS_PER_CORE == 4) &&
               (TCU_V2_WARP_THREADS == 32) &&
               (TCU_V2_MAX_WARPS == 32) &&
               (TCU_V2_DESC_Q_DEPTH == 16) &&
               (TCU_V2_MAX_BARRIERS == 16) &&
               (TCU_V2_CTA_PAIR_MAX == 2) &&
               (TCU_V2_WIDE_ACC_W == 48) &&
               (TCU_V2_SCALE_W == 8) &&
               (TCU_V2_SPARSE_PAIR_W == 4) &&
               (TCU_V2_ELEM_LANE_W == 32) &&
               (TCU_V2_MAX_LANES == 8);
    endfunction

endpackage

`endif // VX_TCU_V2_PKG_SV
