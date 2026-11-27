// SPDX-License-Identifier: Apache-2.0
#include "VVX_tcu_v2_cluster_sva_wrap.h"
#include "tcu_v2_golden_ref.h"
#include <verilated.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>

double sc_time_stamp() { return 0.0; }

namespace {

using namespace tcu_v2_ref;

constexpr int ARR_M      = 4;
constexpr int ARR_N      = 4;
constexpr int ARR_K      = 8;
constexpr int NUM_PIPES  = 2;
constexpr int TMEM_LANES = 8;

template <size_t NW>
void pack_desc_wide_at(uint32_t* dst, size_t bit_offset, const WgmmaDesc& d) {
    size_t bit = bit_offset;
    auto put = [&](size_t w, uint64_t val) {
        wide_set_bits(dst, NW, bit, w, val);
        bit += w;
    };
    put(32, d.clamp_max_fp32);
    put(32, d.clamp_min_fp32);
    put(9, d.tmem_d_col);
    put(7, d.tmem_d_row);
    put(9, d.tmem_c_col);
    put(7, d.tmem_c_row);
    put(9, d.tmem_b_col);
    put(7, d.tmem_b_row);
    put(9, d.tmem_a_col);
    put(7, d.tmem_a_row);
    put(16, d.tile_k);
    put(16, d.tile_n);
    put(16, d.tile_m);
    put(1, d.barrier_phase ? 1u : 0u);
    put(4, d.barrier_id);
    put(1, d.tmem_wb_en ? 1u : 0u);
    put(1, d.int_saturate ? 1u : 0u);
    put(1, d.bias_en ? 1u : 0u);
    put(1, d.accum_en ? 1u : 0u);
    put(1, d.cta_pair_en ? 1u : 0u);
    put(1, d.sparse_en ? 1u : 0u);
    put(3, d.act);
    put(3, d.rm);
    put(2, d.scale_fmt);
    put(5, d.fmt_d);
    put(5, d.fmt_c);
    put(5, d.fmt_b);
    put(5, d.fmt_a);
    put(8, d.desc_id);
}

uint64_t pack_alloc_req(const TmemAllocReq& r) {
    uint64_t v = 0;
    size_t b = 0;
    auto put = [&](size_t w, uint64_t val) {
        uint64_t mask = (w == 64) ? ~0ULL : ((1ULL << w) - 1ULL);
        v |= ((val & mask) << b);
        b += w;
    };
    put(5, r.owner_warp);
    put(1, r.double_buf_en ? 1u : 0u);
    put(2, r.swizzle);
    put(8, r.num_rows);
    put(10, r.num_columns);
    put(9, r.col_offset);
    put(4, r.region_id);
    put(1, r.is_dealloc ? 1u : 0u);
    return v;
}

class EpilogueSvaDriver {
public:
    explicit EpilogueSvaDriver(VVX_tcu_v2_cluster_sva_wrap* dut) : dut_(dut) {}

    void reset() {
        dut_->reset = 1;
        dut_->desc_valid = 0;
        dut_->ext_tile_in_valid = 0;
        dut_->tile_out_ready = 0x3;
        dut_->tcu_cfg_wr_valid = 0;
        dut_->tcu_cfg_wr_addr = 0;
        dut_->tcu_cfg_wr_data = 0;
        dut_->tcu_cfg_rd_valid = 0;
        dut_->tcu_cfg_rd_addr = 0;
        wide_zero<15>(dut_->desc_in.data());
        wide_zero<64>(dut_->ext_a_tile_in.data());
        wide_zero<64>(dut_->ext_b_tile_in.data());
        wide_zero<64>(dut_->ext_a_sparse_cand_in.data());
        wide_zero<32>(dut_->ext_sparse_meta_in.data());
        dut_->ext_scale_a_in = 0;
        dut_->ext_scale_b_in = 0;
        wide_zero<32>(dut_->ext_c_tile_in.data());
        wide_zero<8>(dut_->ext_bias_in.data());

        dut_->tmem_alloc_valid = 0;
        dut_->tmem_alloc_op = 0;
        dut_->tmem_alloc_auto_place = 0;
        dut_->tmem_alloc_buddy_align = 0;
        dut_->tmem_alloc_strict_owner = 1;
        dut_->tmem_alloc_req = 0;

        dut_->tmem_ld_desc_valid = 0;
        dut_->tmem_ld_desc_tag = 0;
        dut_->tmem_ld_desc_region_id = 0;
        dut_->tmem_ld_desc_warp_id = 0;
        dut_->tmem_ld_desc_row_base = 0;
        dut_->tmem_ld_desc_col_base = 0;
        dut_->tmem_ld_desc_num_rows = 0;
        dut_->tmem_ld_desc_num_cols = 0;
        dut_->tmem_ld_desc_elem_bytes = 2;
        dut_->tmem_ld_desc_col_major = 0;
        dut_->tmem_ld_desc_subbyte_shift = 0;
        dut_->tmem_ld_xform_en = 0;
        dut_->tmem_ld_xform_mode = 0;
        dut_->tmem_ld_xform_fmt = 0;
        dut_->tmem_ld_xform_tile8x8 = 0;
        dut_->tmem_ld_xform_unpack32 = 0;
        dut_->tmem_ld_rsp_ready = 1;

        dut_->tmem_st_req_valid = 0;
        dut_->tmem_st_req_tag = 0;
        dut_->tmem_st_req_region_id = 0;
        dut_->tmem_st_req_warp_id = 0;
        dut_->tmem_st_req_row_base = 0;
        dut_->tmem_st_req_col_base = 0;
        dut_->tmem_st_req_num_rows = 0;
        dut_->tmem_st_req_num_cols = 0;
        dut_->tmem_st_req_col_major = 0;
        dut_->tmem_st_req_cell32_mode = 0;
        wide_zero<16>(dut_->tmem_st_req_data.data());
        dut_->tmem_st_req_be = 0;
        dut_->tmem_st_req_last = 0;
        dut_->tmem_st_ack_ready = 1;

        dut_->tmem_wait_req_valid = 0;
        dut_->tmem_wait_req_op = TMEM_OP_NOP;
        dut_->tmem_wait_req_tag = 0;
        dut_->tmem_wait_req_region_id = 0;
        dut_->tmem_wait_req_warp_id = 0;
        dut_->tmem_wait_req_scope_warp = 0;
        dut_->tmem_wait_req_barrier_id = 0;
        dut_->tmem_wait_req_barrier_phase = 0;
        dut_->tmem_wait_rsp_ready = 1;

        dut_->tmem_mma_route_en = 0;
        dut_->pipe_region_id_cfg = 0x10u;
        dut_->pipe_warp_id_cfg = (2u << 5) | 1u;
        dut_->pipe_ping_pong_cfg = 0;
        dut_->cfg_weight_ld = 1;
        dut_->cfg_weight_st = 1;
        dut_->cfg_weight_mma = 2;
        dut_->cfg_strict_mma_prio = 0;
        dut_->cfg_starve_limit = 8;
        dut_->ecc_inj_en = 0;
        dut_->ecc_inj_bank = 0;
        wide_zero<3>(dut_->ecc_inj_mask.data());
        dut_->scrub_en = 0;
        dut_->perf_clear = 0;

        for (int i = 0; i < 8; ++i) tick();
        dut_->reset = 0;
        tick();
    }

    void tick() {
        dut_->clk = 0;
        dut_->eval();
        dut_->clk = 1;
        dut_->eval();
        ++cycles_;
    }

    void run_epilogue_case(const WgmmaDesc& desc, const std::vector<uint32_t>& a_tile,
                           const std::vector<uint32_t>& b_tile, const std::vector<uint8_t>& sa,
                           const std::vector<uint8_t>& sb, const std::vector<uint32_t>& c_tile,
                           const std::vector<uint32_t>& bias, const std::string& tag) {
        wide_zero<15>(dut_->desc_in.data());
        pack_desc_wide_at<15>(dut_->desc_in.data(), 0, desc);

        for (int r = 0; r < ARR_M; ++r) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->ext_a_tile_in[r * ARR_K + k] = a_tile[r * ARR_K + k];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->ext_b_tile_in[c * ARR_K + k] = b_tile[c * ARR_K + k];
            }
        }
        uint64_t sa_p = 0, sb_p = 0;
        for (int r = 0; r < ARR_M; ++r) sa_p |= (static_cast<uint64_t>(sa[r]) << (r * 8));
        for (int c = 0; c < ARR_N; ++c) sb_p |= (static_cast<uint64_t>(sb[c]) << (c * 8));
        dut_->ext_scale_a_in = sa_p;
        dut_->ext_scale_b_in = sb_p;
        for (int r = 0; r < ARR_M; ++r) {
            for (int c = 0; c < ARR_N; ++c) {
                dut_->ext_c_tile_in[r * ARR_N + c] = c_tile[r * ARR_N + c];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            dut_->ext_bias_in[c] = bias[c];
        }

        uint32_t exp_uops = uops_for_desc(desc, ARR_M, ARR_N, ARR_K);
        uint32_t exp_outs = ((desc.tile_m + ARR_M - 1) / ARR_M) * ((desc.tile_n + ARR_N - 1) / ARR_N);
        bool desc_sent = false;
        uint32_t tiles_sent = 0;
        uint32_t tiles_got = 0;
        bool done_got = false;
        std::vector<uint32_t> got_tile(ARR_M * ARR_N, 0u);
        FpFlags got_flags{};
        int guard = 0;

        while (tiles_got < exp_outs || !done_got) {
            dut_->desc_valid = desc_sent ? 0 : 1;
            dut_->ext_tile_in_valid = (tiles_sent < exp_uops) ? 1 : 0;
            dut_->tile_out_ready = 0x3;

            dut_->clk = 0;
            dut_->eval();

            if ((dut_->desc_valid & 1u) && (dut_->desc_ready & 1u)) desc_sent = true;
            if ((dut_->ext_tile_in_valid & 1u) && (dut_->ext_tile_in_ready & 1u)) ++tiles_sent;
            if ((dut_->tile_out_valid & 1u) && (dut_->tile_out_ready & 1u)) {
                for (int r = 0; r < ARR_M; ++r) {
                    for (int c = 0; c < ARR_N; ++c) {
                        got_tile[r * ARR_N + c] = dut_->d_tile_out[r * ARR_N + c];
                    }
                }
                got_flags = FpFlags::unpack(static_cast<uint8_t>(dut_->flags_out & 0x1Fu));
                ++tiles_got;
                guard = 0;
            }
            if (dut_->desc_done_valid & 1u) done_got = true;

            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            if (++guard > 3000) {
                std::fprintf(stderr, "[tb_epilogue_and_sva] FAIL: timeout on %s (sent=%u/%u got=%u/%u done=%d)\n",
                             tag.c_str(), tiles_sent, exp_uops, tiles_got, exp_outs, done_got);
                std::exit(1);
            }
        }
        dut_->desc_valid = 0;
        dut_->ext_tile_in_valid = 0;
        for (int i = 0; i < 4; ++i) tick();

        FpFlags fexp{};
        auto exp = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, desc, a_tile, b_tile, sa, sb, c_tile, bias,
                                      true, true, fexp);
        if (got_tile != exp || !(got_flags == fexp)) {
            std::fprintf(stderr, "[tb_epilogue_and_sva] MISMATCH %s: got[0]=%s exp[0]=%s got_f=0x%02x exp_f=0x%02x\n",
                         tag.c_str(), hex32(got_tile[0]).c_str(), hex32(exp[0]).c_str(),
                         got_flags.pack(), fexp.pack());
            std::exit(1);
        }
        ++checks_;
    }

    void exercise_tmem_sva_paths() {
        TmemAllocReq r0{false, 0, 0, 64, 64, SWIZZLE_128B, true, 1};
        dut_->tmem_alloc_valid = 1;
        dut_->tmem_alloc_op = ALLOC_CMD_ALLOC;
        dut_->tmem_alloc_auto_place = 0;
        dut_->tmem_alloc_buddy_align = 1;
        dut_->tmem_alloc_strict_owner = 1;
        dut_->tmem_alloc_req = pack_alloc_req(r0);
        while (!dut_->tmem_alloc_ready) tick();
        tick();
        dut_->tmem_alloc_valid = 0;
        for (int i = 0; i < 4; ++i) tick();

        // Store + Fence + Load under SVA monitors
        dut_->tmem_st_req_valid = 1;
        dut_->tmem_st_req_tag = 0x20u;
        dut_->tmem_st_req_region_id = 0;
        dut_->tmem_st_req_warp_id = 1;
        dut_->tmem_st_req_row_base = 3;
        dut_->tmem_st_req_col_base = 0;
        dut_->tmem_st_req_num_rows = 1;
        dut_->tmem_st_req_num_cols = 8;
        dut_->tmem_st_req_cell32_mode = 1;
        for (int l = 0; l < TMEM_LANES; ++l) {
            dut_->tmem_st_req_data[2 * l] = 0x5A5A0000u + l;
            dut_->tmem_st_req_data[2 * l + 1] = 0u;
        }
        dut_->tmem_st_req_be = ~0ULL;
        dut_->tmem_st_req_last = 1;
        while (!(dut_->tmem_st_req_valid && dut_->tmem_st_req_ready)) tick();
        tick();
        dut_->tmem_st_req_valid = 0;
        while (!dut_->tmem_st_ack_valid) tick();
        tick();

        // Flip double buffer so active_buf points to the newly stored bank
        dut_->tmem_alloc_valid = 1;
        dut_->tmem_alloc_op = ALLOC_CMD_FLIP_BUF;
        dut_->tmem_alloc_auto_place = 0;
        dut_->tmem_alloc_buddy_align = 0;
        dut_->tmem_alloc_strict_owner = 1;
        dut_->tmem_alloc_req = pack_alloc_req(r0);
        while (!dut_->tmem_alloc_ready) tick();
        tick();
        dut_->tmem_alloc_valid = 0;
        for (int i = 0; i < 4; ++i) tick();

        dut_->tmem_ld_desc_valid = 1;
        dut_->tmem_ld_desc_tag = 0x21u;
        dut_->tmem_ld_desc_region_id = 0;
        dut_->tmem_ld_desc_warp_id = 1;
        dut_->tmem_ld_desc_row_base = 3;
        dut_->tmem_ld_desc_col_base = 0;
        dut_->tmem_ld_desc_num_rows = 1;
        dut_->tmem_ld_desc_num_cols = 8;
        dut_->tmem_ld_desc_elem_bytes = 2;
        while (!(dut_->tmem_ld_desc_valid && dut_->tmem_ld_desc_ready)) tick();
        tick();
        dut_->tmem_ld_desc_valid = 0;
        while (!dut_->tmem_ld_rsp_valid) tick();
        if (dut_->tmem_ld_rsp_data[0] != 0x5A5A0000u) {
            std::fprintf(stderr, "[tb_epilogue_and_sva] FAIL: TMEM SVA roundtrip mismatch got=%08x\n",
                         static_cast<unsigned>(dut_->tmem_ld_rsp_data[0]));
            std::exit(1);
        }
        tick();
        ++checks_;
    }

    uint64_t checks() const { return checks_; }
    uint64_t cycles() const { return cycles_; }

private:
    VVX_tcu_v2_cluster_sva_wrap* dut_;
    uint64_t cycles_ = 0;
    uint64_t checks_ = 0;
};

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tcu_v2_cluster_sva_wrap>();
    EpilogueSvaDriver drv(dut.get());
    drv.reset();

    // Exercise epilogue combinations (Bias + ReLU/Clamp/SiLU/GELU + Cast BF16/FP16/FP8_E4M3/FP8_E5M2/INT8)
    struct EpiCase {
        Fmt fa, fb, fd;
        ActMode act;
        bool bias;
        const char* name;
    };
    const std::array<EpiCase, 8> cases = {{
        {FMT_BF16, FMT_BF16, FMT_BF16,     ACT_RELU,  true,  "sva_bf16_relu"},
        {FMT_FP16, FMT_FP16, FMT_FP16,     ACT_CLAMP, true,  "sva_fp16_clamp"},
        {FMT_BF16, FMT_BF16, FMT_FP8_E4M3, ACT_SILU,  true,  "sva_e4m3_silu"},
        {FMT_BF16, FMT_BF16, FMT_FP8_E5M2, ACT_GELU,  false, "sva_e5m2_gelu"},
        {FMT_TF32, FMT_TF32, FMT_FP32,     ACT_SILU,  true,  "sva_tf32_silu"},
        {FMT_TF32, FMT_TF32, FMT_BF16,     ACT_GELU,  true,  "sva_tf32_gelu"},
        {FMT_INT8, FMT_INT8, FMT_I32,      ACT_RELU,  true,  "sva_int8_relu"},
        {FMT_INT8, FMT_INT8, FMT_INT8,     ACT_CLAMP, true,  "sva_int8_clamp"}
    }};

    for (size_t i = 0; i < cases.size(); ++i) {
        const auto& cs = cases[i];
        WgmmaDesc d;
        d.desc_id = static_cast<uint8_t>(i + 1);
        d.fmt_a = cs.fa;
        d.fmt_b = cs.fb;
        d.fmt_c = FMT_FP32;
        d.fmt_d = cs.fd;
        d.scale_fmt = SCALE_NONE;
        d.rm = RM_RNE;
        d.act = cs.act;
        d.accum_en = true;
        d.bias_en = cs.bias;
        d.int_saturate = true;
        d.tile_m = 16;
        d.tile_n = 8;
        d.tile_k = 8;
        d.clamp_min_fp32 = (cs.fa == FMT_INT8) ? static_cast<uint32_t>(-4) : 0xBF800000u;
        d.clamp_max_fp32 = (cs.fa == FMT_INT8) ? static_cast<uint32_t>(12) : 0x41000000u;

        uint32_t aval = (cs.fa == FMT_INT8) ? 0x02u : ((cs.fa == FMT_FP16) ? 0x3C003C00u : ((cs.fa == FMT_TF32) ? 0x3F800000u : 0x3F803F80u));
        uint32_t bval = (cs.fb == FMT_INT8) ? 0xFFu : ((cs.fb == FMT_FP16) ? 0x40004000u : ((cs.fb == FMT_TF32) ? 0x40000000u : 0xBF80BF80u));
        std::vector<uint32_t> a_tile(ARR_M * ARR_K, aval);
        std::vector<uint32_t> b_tile(ARR_N * ARR_K, bval);
        std::vector<uint8_t> sa(ARR_M, 0u), sb(ARR_N, 0u);
        std::vector<uint32_t> c_tile(ARR_M * ARR_N, (cs.fa == FMT_INT8) ? 10u : 0x3F800000u);
        std::vector<uint32_t> bias(ARR_N, (cs.fa == FMT_INT8) ? 3u : 0x3F000000u);

        drv.run_epilogue_case(d, a_tile, b_tile, sa, sb, c_tile, bias, cs.name);
    }

    // Directed-rounding cast edge checks (BF16 underflow flag + FP16/E5M2/BF16 RDN/RUP overflow & tininess)
    {
        struct CastEdge {
            Fmt fd;
            RoundMode rm;
            uint32_t c_val;
            const char* name;
        };
        const std::array<CastEdge, 5> edges = {{
            {FMT_BF16,     RM_RNE, 0x00000001u, "cast_bf16_uf_flag"},     // FP32 subnormal -> BF16 0 with uf=1, nx=1
            {FMT_BF16,     RM_RDN, 0x7F7FFFFFu, "cast_bf16_ovf_rdn"},     // +max FP32 -> +max_finite BF16 (0x7F7F)
            {FMT_FP16,     RM_RDN, 0x47800000u, "cast_fp16_ovf_rdn"},     // +65536 -> +max_finite FP16 (0x7BFF)
            {FMT_FP16,     RM_RUP, 0x00000001u, "cast_fp16_tiny_rup"},    // +2^-149 -> smallest FP16 subnormal (0x0001)
            {FMT_FP8_E5M2, RM_RDN, 0x47800000u, "cast_e5m2_ovf_rdn"}      // +65536 -> +max_finite E5M2 (0x7B)
        }};
        for (size_t i = 0; i < edges.size(); ++i) {
            WgmmaDesc d;
            d.desc_id = static_cast<uint8_t>(0x50u + i);
            d.fmt_a = FMT_BF16;
            d.fmt_b = FMT_BF16;
            d.fmt_c = FMT_FP32;
            d.fmt_d = edges[i].fd;
            d.scale_fmt = SCALE_NONE;
            d.rm = edges[i].rm;
            d.act = ACT_NONE;
            d.accum_en = true;
            d.bias_en = false;
            d.tile_m = 16;
            d.tile_n = 8;
            d.tile_k = 8;
            std::vector<uint32_t> az(ARR_M * ARR_K, 0u);
            std::vector<uint32_t> bz(ARR_N * ARR_K, 0u);
            std::vector<uint8_t> sa(ARR_M, 0u), sb(ARR_N, 0u);
            std::vector<uint32_t> ct(ARR_M * ARR_N, edges[i].c_val);
            std::vector<uint32_t> bi(ARR_N, 0u);
            drv.run_epilogue_case(d, az, bz, sa, sb, ct, bi, edges[i].name);
        }
    }

    drv.exercise_tmem_sva_paths();

    std::printf("[tb_epilogue_and_sva] PASS: checks=%llu cycles=%llu (0 SVA assertion failures)\n",
                static_cast<unsigned long long>(drv.checks()),
                static_cast<unsigned long long>(drv.cycles()));
    return 0;
}
