// SPDX-License-Identifier: Apache-2.0
#include "VVX_tcu_tmem_cluster_slice.h"
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

constexpr int NUM_PIPES = 2;
constexpr int ARR_M     = 4;
constexpr int ARR_N     = 4;
constexpr int ARR_K     = 8;
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

TmemAllocRsp unpack_alloc_rsp(uint64_t v) {
    TmemAllocRsp rsp;
    size_t b = 0;
    auto get = [&](size_t w) -> uint64_t {
        uint64_t mask = (w == 64) ? ~0ULL : ((1ULL << w) - 1ULL);
        uint64_t val = (v >> b) & mask;
        b += w;
        return val;
    };
    rsp.buf_b_col_offset = static_cast<uint16_t>(get(9));
    rsp.num_columns = static_cast<uint16_t>(get(10));
    rsp.col_offset = static_cast<uint16_t>(get(9));
    rsp.region_id = static_cast<uint8_t>(get(4));
    rsp.status = static_cast<TmemStatus>(get(3));
    rsp.valid = get(1) != 0;
    return rsp;
}

class ClusterSliceDriver {
public:
    explicit ClusterSliceDriver(VVX_tcu_tmem_cluster_slice* dut) : dut_(dut) {}

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
        dut_->pipe_region_id_cfg = 0x10u; // pipe 0 -> region 0, pipe 1 -> region 1
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

    TmemAllocRsp alloc_region(uint8_t op, bool auto_place, const TmemAllocReq& req) {
        dut_->tmem_alloc_valid = 1;
        dut_->tmem_alloc_op = op;
        dut_->tmem_alloc_auto_place = auto_place ? 1 : 0;
        dut_->tmem_alloc_buddy_align = 1;
        dut_->tmem_alloc_strict_owner = 1;
        dut_->tmem_alloc_req = pack_alloc_req(req);
        while (!dut_->tmem_alloc_ready) tick();
        tick();
        dut_->tmem_alloc_valid = 0;
        TmemAllocRsp rsp = unpack_alloc_rsp(dut_->tmem_alloc_rsp);
        int guard = 0;
        while (!rsp.valid) {
            tick();
            rsp = unpack_alloc_rsp(dut_->tmem_alloc_rsp);
            if (++guard > 20) {
                std::fprintf(stderr, "[tb_cluster_slice] FAIL: alloc timeout\n");
                std::exit(1);
            }
        }
        return rsp;
    }

    void tmem_store(uint8_t tag, uint8_t reg_id, uint8_t warp, uint8_t row, uint16_t col,
                    const std::array<uint64_t, 8>& data) {
        dut_->tmem_st_req_valid = 1;
        dut_->tmem_st_req_tag = tag;
        dut_->tmem_st_req_region_id = reg_id;
        dut_->tmem_st_req_warp_id = warp;
        dut_->tmem_st_req_row_base = row;
        dut_->tmem_st_req_col_base = col;
        dut_->tmem_st_req_num_rows = 1;
        dut_->tmem_st_req_num_cols = 8;
        dut_->tmem_st_req_col_major = 0;
        dut_->tmem_st_req_cell32_mode = 1;
        for (int l = 0; l < 8; ++l) {
            dut_->tmem_st_req_data[2 * l] = static_cast<uint32_t>(data[l] & 0xFFFFFFFFULL);
            dut_->tmem_st_req_data[2 * l + 1] = static_cast<uint32_t>(data[l] >> 32);
        }
        dut_->tmem_st_req_be = ~0ULL;
        dut_->tmem_st_req_last = 1;
        while (!(dut_->tmem_st_req_valid && dut_->tmem_st_req_ready)) tick();
        tick();
        dut_->tmem_st_req_valid = 0;
        int guard = 0;
        while (!dut_->tmem_st_ack_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_cluster_slice] FAIL: st ack timeout\n");
                std::exit(1);
            }
        }
        if (dut_->tmem_st_ack_status != TMEM_STATUS_OK) {
            std::fprintf(stderr, "[tb_cluster_slice] FAIL: st status=%u\n", dut_->tmem_st_ack_status);
            std::exit(1);
        }
        tick();
    }

    std::array<uint64_t, 8> tmem_load(uint8_t tag, uint8_t reg_id, uint8_t warp, uint8_t row, uint16_t col) {
        dut_->tmem_ld_desc_valid = 1;
        dut_->tmem_ld_desc_tag = tag;
        dut_->tmem_ld_desc_region_id = reg_id;
        dut_->tmem_ld_desc_warp_id = warp;
        dut_->tmem_ld_desc_row_base = row;
        dut_->tmem_ld_desc_col_base = col;
        dut_->tmem_ld_desc_num_rows = 1;
        dut_->tmem_ld_desc_num_cols = 8;
        dut_->tmem_ld_desc_elem_bytes = 2;
        dut_->tmem_ld_desc_col_major = 0;
        dut_->tmem_ld_desc_subbyte_shift = 0;
        while (!(dut_->tmem_ld_desc_valid && dut_->tmem_ld_desc_ready)) tick();
        tick();
        dut_->tmem_ld_desc_valid = 0;
        int guard = 0;
        while (!dut_->tmem_ld_rsp_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_cluster_slice] FAIL: ld rsp timeout\n");
                std::exit(1);
            }
        }
        std::array<uint64_t, 8> out{};
        for (int l = 0; l < 8; ++l) {
            out[l] = static_cast<uint64_t>(dut_->tmem_ld_rsp_data[2 * l]) |
                     (static_cast<uint64_t>(dut_->tmem_ld_rsp_data[2 * l + 1]) << 32);
        }
        tick();
        return out;
    }

    void tmem_fence(uint8_t tag, uint8_t reg_id, uint8_t warp) {
        dut_->tmem_wait_req_valid = 1;
        dut_->tmem_wait_req_op = TMEM_OP_FENCE;
        dut_->tmem_wait_req_tag = tag;
        dut_->tmem_wait_req_region_id = reg_id;
        dut_->tmem_wait_req_warp_id = warp;
        dut_->tmem_wait_req_scope_warp = 1;
        dut_->tmem_wait_req_barrier_id = 0;
        dut_->tmem_wait_req_barrier_phase = 0;
        while (!dut_->tmem_wait_req_ready) tick();
        tick();
        dut_->tmem_wait_req_valid = 0;
        int guard = 0;
        while (!dut_->tmem_wait_rsp_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_cluster_slice] FAIL: fence timeout\n");
                std::exit(1);
            }
        }
        tick();
    }

    void run_2cta_coop_wgmma(const WgmmaDesc& d0, const WgmmaDesc& d1,
                             const std::vector<uint32_t>& a_p0, const std::vector<uint32_t>& b_p0,
                             const std::vector<uint32_t>& a_p1, const std::vector<uint32_t>& b_p1,
                             const std::vector<uint8_t>& sa, const std::vector<uint8_t>& sb,
                             const std::vector<uint32_t>& c_tile, const std::vector<uint32_t>& bias) {
        // Pack 2 descriptors (223 bits each -> offsets 0 and 223)
        wide_zero<15>(dut_->desc_in.data());
        pack_desc_wide_at<15>(dut_->desc_in.data(), 0, d0);
        pack_desc_wide_at<15>(dut_->desc_in.data(), 223, d1);

        // Pack 2 pipe tile inputs
        for (int r = 0; r < ARR_M; ++r) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->ext_a_tile_in[r * ARR_K + k] = a_p0[r * ARR_K + k];
                dut_->ext_a_tile_in[ARR_M * ARR_K + r * ARR_K + k] = a_p1[r * ARR_K + k];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->ext_b_tile_in[c * ARR_K + k] = b_p0[c * ARR_K + k];
                dut_->ext_b_tile_in[ARR_N * ARR_K + c * ARR_K + k] = b_p1[c * ARR_K + k];
            }
        }
        uint64_t sa_pack = 0, sb_pack = 0;
        for (int r = 0; r < ARR_M; ++r) {
            sa_pack |= (static_cast<uint64_t>(sa[r]) << (r * 8));
            sa_pack |= (static_cast<uint64_t>(sa[r]) << ((ARR_M + r) * 8));
        }
        for (int c = 0; c < ARR_N; ++c) {
            sb_pack |= (static_cast<uint64_t>(sb[c]) << (c * 8));
            sb_pack |= (static_cast<uint64_t>(sb[c]) << ((ARR_N + c) * 8));
        }
        dut_->ext_scale_a_in = sa_pack;
        dut_->ext_scale_b_in = sb_pack;
        for (int r = 0; r < ARR_M; ++r) {
            for (int c = 0; c < ARR_N; ++c) {
                dut_->ext_c_tile_in[r * ARR_N + c] = c_tile[r * ARR_N + c];
                dut_->ext_c_tile_in[ARR_M * ARR_N + r * ARR_N + c] = c_tile[r * ARR_N + c];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            dut_->ext_bias_in[c] = bias[c];
            dut_->ext_bias_in[ARR_N + c] = bias[c];
        }

        uint8_t desc_sent = 0;
        std::array<uint32_t, 2> tiles_sent = {0, 0};
        std::array<uint32_t, 2> tiles_got  = {0, 0};
        uint32_t exp_uops0 = uops_for_desc(d0, ARR_M, ARR_N, ARR_K);
        uint32_t exp_uops1 = uops_for_desc(d1, ARR_M, ARR_N, ARR_K);
        uint32_t exp_outs0 = ((d0.tile_m + ARR_M - 1) / ARR_M) * ((d0.tile_n + ARR_N - 1) / ARR_N);
        uint32_t exp_outs1 = ((d1.tile_m + ARR_M - 1) / ARR_M) * ((d1.tile_n + ARR_N - 1) / ARR_N);
        uint8_t done_got = 0;
        std::array<std::vector<uint32_t>, 2> got_tiles;
        got_tiles[0].assign(ARR_M * ARR_N, 0u);
        got_tiles[1].assign(ARR_M * ARR_N, 0u);

        int guard = 0;
        while (tiles_got[0] < exp_outs0 || tiles_got[1] < exp_outs1 || done_got != 0x3u) {
            dut_->desc_valid = static_cast<uint8_t>((~desc_sent) & 0x3u);
            uint8_t tv = 0;
            if (tiles_sent[0] < exp_uops0) tv |= 0x1u;
            if (tiles_sent[1] < exp_uops1) tv |= 0x2u;
            dut_->ext_tile_in_valid = tv;
            dut_->tile_out_ready = 0x3u;

            dut_->clk = 0;
            dut_->eval();

            for (int p = 0; p < NUM_PIPES; ++p) {
                if (((dut_->desc_valid >> p) & 1u) && ((dut_->desc_ready >> p) & 1u)) {
                    desc_sent |= (1u << p);
                }
                if (((dut_->ext_tile_in_valid >> p) & 1u) && ((dut_->ext_tile_in_ready >> p) & 1u)) {
                    ++tiles_sent[p];
                }
                if (((dut_->tile_out_valid >> p) & 1u) && ((dut_->tile_out_ready >> p) & 1u)) {
                    for (int r = 0; r < ARR_M; ++r) {
                        for (int c = 0; c < ARR_N; ++c) {
                            got_tiles[p][r * ARR_N + c] = dut_->d_tile_out[p * ARR_M * ARR_N + r * ARR_N + c];
                        }
                    }
                    ++tiles_got[p];
                    guard = 0;
                }
                if ((dut_->desc_done_valid >> p) & 1u) {
                    done_got |= (1u << p);
                }
            }

            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            if (++guard > 3000) {
                std::fprintf(stderr,
                             "[tb_cluster_slice] FAIL: 2-CTA coop WGMMA timeout (desc=%u t_sent=%u/%u t_got=%u/%u exp_out=%u/%u done=%u)\n",
                             desc_sent, tiles_sent[0], tiles_sent[1], tiles_got[0], tiles_got[1], exp_outs0, exp_outs1, done_got);
                std::exit(1);
            }
        }
        dut_->desc_valid = 0;
        dut_->ext_tile_in_valid = 0;
        for (int i = 0; i < 4; ++i) tick();

        FpFlags f0{}, f1{};
        auto exp0 = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d0, a_p0, b_p0, sa, sb, c_tile, bias, true, true, f0);
        auto exp1 = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d1, a_p1, b_p1, sa, sb, c_tile, bias, true, true, f1);
        if (got_tiles[0] != exp0 || got_tiles[1] != exp1) {
            std::fprintf(stderr, "[tb_cluster_slice] FAIL: 2-CTA tile mismatch p0(%s vs %s) p1(%s vs %s)\n",
                         hex32(got_tiles[0][0]).c_str(), hex32(exp0[0]).c_str(),
                         hex32(got_tiles[1][0]).c_str(), hex32(exp1[0]).c_str());
            std::exit(1);
        }
        ++tests_passed_;
    }

    void run_tmem_routed_wgmma(const WgmmaDesc& d0, const std::vector<uint8_t>& sa,
                               const std::vector<uint8_t>& sb, const std::vector<uint32_t>& bias) {
        dut_->tmem_mma_route_en = 1;
        wide_zero<15>(dut_->desc_in.data());
        pack_desc_wide_at<15>(dut_->desc_in.data(), 0, d0);
        uint64_t sa_pack = 0, sb_pack = 0;
        for (int r = 0; r < ARR_M; ++r) sa_pack |= (static_cast<uint64_t>(sa[r]) << (r * 8));
        for (int c = 0; c < ARR_N; ++c) sb_pack |= (static_cast<uint64_t>(sb[c]) << (c * 8));
        dut_->ext_scale_a_in = sa_pack;
        dut_->ext_scale_b_in = sb_pack;
        for (int c = 0; c < ARR_N; ++c) dut_->ext_bias_in[c] = bias[c];

        uint32_t exp_outs = ((d0.tile_m + ARR_M - 1) / ARR_M) * ((d0.tile_n + ARR_N - 1) / ARR_N);
        bool desc_sent = false, done_got = false;
        uint32_t tiles_got = 0;
        std::vector<uint32_t> got_tile(ARR_M * ARR_N, 0u);
        int guard = 0;
        while (tiles_got < exp_outs || !done_got) {
            dut_->desc_valid = desc_sent ? 0 : 1;
            dut_->ext_tile_in_valid = 0;
            dut_->tile_out_ready = 0x3u;

            dut_->clk = 0;
            dut_->eval();
            if ((dut_->desc_valid & 1u) && (dut_->desc_ready & 1u)) desc_sent = true;
            if ((dut_->tile_out_valid & 1u) && (dut_->tile_out_ready & 1u)) {
                for (int r = 0; r < ARR_M; ++r) {
                    for (int c = 0; c < ARR_N; ++c) {
                        got_tile[r * ARR_N + c] = dut_->d_tile_out[r * ARR_N + c];
                    }
                }
                ++tiles_got;
                guard = 0;
            }
            if (dut_->desc_done_valid & 1u) done_got = true;
            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            if (++guard > 3000) {
                std::fprintf(stderr, "[tb_cluster_slice] FAIL: tmem_mma_route_en=1 timeout (got=%u/%u done=%d)\n",
                             tiles_got, exp_outs, done_got);
                std::exit(1);
            }
        }
        dut_->desc_valid = 0;
        for (int i = 0; i < 4; ++i) tick();
        dut_->tmem_mma_route_en = 0;
        // Verify non-trivial routed output (all elements finite non-zero)
        for (uint32_t v : got_tile) {
            if (v == 0u || fp32_is_nan(v)) {
                std::fprintf(stderr, "[tb_cluster_slice] FAIL: tmem_mma_route_en=1 unexpected element %s\n",
                             hex32(v).c_str());
                std::exit(1);
            }
        }
        ++tests_passed_;
    }

    uint64_t tests_passed() const { return tests_passed_; }
    uint64_t cycles() const { return cycles_; }

private:
    VVX_tcu_tmem_cluster_slice* dut_;
    uint64_t cycles_ = 0;
    uint64_t tests_passed_ = 0;
};

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tcu_tmem_cluster_slice>();
    ClusterSliceDriver drv(dut.get());
    drv.reset();

    // 1. Allocate two TMEM regions (region 0 for pipe 0/warp 1, region 1 for pipe 1/warp 2)
    TmemAllocReq r0{false, 0, 0, 64, 64, SWIZZLE_32B, true, 1};
    auto rsp0 = drv.alloc_region(ALLOC_CMD_ALLOC, false, r0);
    if (rsp0.status != TMEM_STATUS_OK) {
        std::fprintf(stderr, "[tb_cluster_slice] FAIL: alloc r0 st=%u\n", rsp0.status);
        return 1;
    }
    TmemAllocReq r1{false, 1, 0, 64, 64, SWIZZLE_64B, false, 2};
    auto rsp1 = drv.alloc_region(ALLOC_CMD_ALLOC, true, r1);
    if (rsp1.status != TMEM_STATUS_OK) {
        std::fprintf(stderr, "[tb_cluster_slice] FAIL: alloc r1 st=%u\n", rsp1.status);
        return 1;
    }

    // 2. Store & Fence & Load through TMEM slice ports
    std::array<uint64_t, 8> pat{};
    for (int l = 0; l < 8; ++l) pat[l] = 0x3F800000ULL + static_cast<uint64_t>(l * 0x1000u);
    drv.tmem_store(0x01u, 0, 1, 0, 0, pat);
    drv.tmem_fence(0x02u, 0, 1);
    auto flip0 = drv.alloc_region(ALLOC_CMD_FLIP_BUF, false, r0);
    if (flip0.status != TMEM_STATUS_OK) {
        std::fprintf(stderr, "[tb_cluster_slice] FAIL: flip r0 st=%u\n", flip0.status);
        return 1;
    }
    auto got_ld = drv.tmem_load(0x03u, 0, 1, 0, 0);
    if ((got_ld[0] & 0xFFFFFFFFULL) != (pat[0] & 0xFFFFFFFFULL)) {
        std::fprintf(stderr, "[tb_cluster_slice] FAIL: TMEM load roundtrip mismatch got=%s exp=%s\n",
                     hex64(got_ld[0]).c_str(), hex64(pat[0]).c_str());
        return 1;
    }

    // 3. 2-CTA Cooperative WGMMA across both TCU pipes synchronized via direct cross-link ring
    WgmmaDesc d0;
    d0.desc_id = 0x10u;
    d0.fmt_a = FMT_MXFP4_E2M1;
    d0.fmt_b = FMT_MXFP4_E2M1;
    d0.fmt_c = FMT_FP32;
    d0.fmt_d = FMT_FP32;
    d0.scale_fmt = SCALE_UE8M0;
    d0.rm = RM_RNE;
    d0.act = ACT_RELU;
    d0.cta_pair_en = true;
    d0.accum_en = true;
    d0.bias_en = true;
    d0.tmem_wb_en = true;
    d0.barrier_id = 2;
    d0.barrier_phase = true;
    d0.tile_m = 16;
    d0.tile_n = 8;
    d0.tile_k = 8;
    d0.tmem_a_col = 0;
    d0.tmem_b_col = 16;
    d0.tmem_c_col = 32;
    d0.tmem_d_col = 48;

    WgmmaDesc d1 = d0;
    d1.desc_id = 0x11u;
    d1.tmem_a_col = rsp1.col_offset;
    d1.tmem_b_col = rsp1.col_offset + 16;
    d1.tmem_c_col = rsp1.col_offset + 32;
    d1.tmem_d_col = rsp1.col_offset + 48;

    std::vector<uint32_t> a0(ARR_M * ARR_K, 0x04u); // 2.0 in FP4
    std::vector<uint32_t> b0(ARR_N * ARR_K, 0x02u); // 1.0 in FP4
    std::vector<uint32_t> a1(ARR_M * ARR_K, 0x0Au); // -1.0 in FP4
    std::vector<uint32_t> b1(ARR_N * ARR_K, 0x04u); // 2.0 in FP4
    std::vector<uint8_t> sa(ARR_M, 0x7Fu);
    std::vector<uint8_t> sb(ARR_N, 0x7Fu);
    std::vector<uint32_t> c_tile(ARR_M * ARR_N, 0x3F800000u);
    std::vector<uint32_t> bias(ARR_N, 0x40000000u); // +2.0

    drv.run_2cta_coop_wgmma(d0, d1, a0, b0, a1, b1, sa, sb, c_tile, bias);

    // 3.5 End-to-end tmem_mma_route_en=1 routed multi-beat gather/scatter WGMMA
    {
        // Pre-load A, B, C rows into region 0 (SWIZZLE_32B) with 1.0f (BF16/FP32)
        std::array<uint64_t, 8> ab_pat{}, c_pat{};
        for (int l = 0; l < 8; ++l) {
            ab_pat[l] = 0x3F803F803F803F80ULL; // BF16 1.0
            c_pat[l]  = 0x3F8000003F800000ULL; // FP32 1.0
        }
        for (int row = 0; row < ARR_M; ++row) {
            drv.tmem_store(static_cast<uint8_t>(0x40 + row), 0, 1, static_cast<uint8_t>(row), 0, ab_pat);
            drv.tmem_store(static_cast<uint8_t>(0x50 + row), 0, 1, static_cast<uint8_t>(row), 16, ab_pat);
            drv.tmem_store(static_cast<uint8_t>(0x60 + row), 0, 1, static_cast<uint8_t>(row), 32, c_pat);
        }
        drv.tmem_fence(0x6Fu, 0, 1);

        WgmmaDesc dr = d0;
        dr.desc_id = 0x22u;
        dr.fmt_a = FMT_BF16;
        dr.fmt_b = FMT_BF16;
        dr.scale_fmt = SCALE_NONE;
        dr.cta_pair_en = false;
        dr.accum_en = true;
        dr.bias_en = true;
        dr.tmem_wb_en = false;
        drv.run_tmem_routed_wgmma(dr, sa, sb, bias);
    }

    // 4. Verify TMEM ECC + telemetry clean
    if (dut->tmem_deadlock_fault_out || dut->tmem_ecc_ue_count_out != 0) {
        std::fprintf(stderr, "[tb_cluster_slice] FAIL: unexpected cluster fault dl=%d ue=%u\n",
                     dut->tmem_deadlock_fault_out, dut->tmem_ecc_ue_count_out);
        return 1;
    }

    std::printf("[tb_cluster_slice] PASS: tests=%llu cycles=%llu\n",
                static_cast<unsigned long long>(drv.tests_passed()),
                static_cast<unsigned long long>(drv.cycles()));
    return 0;
}
