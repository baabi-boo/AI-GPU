// SPDX-License-Identifier: Apache-2.0
#include "VVX_tcu_v2_top.h"
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

constexpr int ARR_M = 4;
constexpr int ARR_N = 4;
constexpr int ARR_K = 8;

// Pack tcu_v2_wgmma_desc_t (LSB to MSB, matching VX_tcu_v2_pkg.sv)
template <size_t NW>
void pack_desc_wide(uint32_t* dst, const WgmmaDesc& d) {
    wide_zero<NW>(dst);
    size_t bit = 0;
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

struct TileFeed {
    std::vector<uint32_t> a_tile;
    std::vector<uint32_t> b_tile;
    std::vector<uint32_t> a_cand;
    std::vector<uint8_t>  meta_bytes; // ARR_M * ARR_K
    std::vector<uint8_t>  scale_a;
    std::vector<uint8_t>  scale_b;
    std::vector<uint32_t> c_tile;
    std::vector<uint32_t> bias;
};

class SparseWgmmaDriver {
public:
    explicit SparseWgmmaDriver(VVX_tcu_v2_top* dut) : dut_(dut) {}

    void reset() {
        dut_->reset = 1;
        dut_->desc_valid = 0;
        dut_->tile_in_valid = 0;
        dut_->tmem_req_ready = 1;
        dut_->tile_out_ready = 1;
        dut_->cta_sync_out_ready = 1;
        dut_->cta_sync_in_valid = 0;
        dut_->cta_sync_in_bar_id = 0;
        dut_->cta_sync_in_phase = 0;
        dut_->cfg_wr_valid = 0;
        dut_->cfg_wr_addr = 0;
        dut_->cfg_wr_data = 0;
        dut_->cfg_rd_valid = 0;
        dut_->cfg_rd_addr = 0;
        wide_zero<8>(dut_->desc_in.data());
        wide_zero<ARR_M * ARR_K>(dut_->a_tile_in.data());
        wide_zero<ARR_N * ARR_K>(dut_->b_tile_in.data());
        wide_zero<ARR_M * ARR_K>(dut_->a_sparse_cand_in.data());
        wide_zero<16>(dut_->sparse_meta_in.data());
        dut_->scale_a_in = 0;
        dut_->scale_b_in = 0;
        wide_zero<ARR_M * ARR_N>(dut_->c_tile_in.data());
        wide_zero<ARR_N>(dut_->bias_in.data());
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

    void set_tile_inputs(const TileFeed& tf) {
        for (int r = 0; r < ARR_M; ++r) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->a_tile_in[r * ARR_K + k] = tf.a_tile[static_cast<size_t>(r * ARR_K + k)];
                dut_->a_sparse_cand_in[r * ARR_K + k] = tf.a_cand[static_cast<size_t>(r * ARR_K + k)];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->b_tile_in[c * ARR_K + k] = tf.b_tile[static_cast<size_t>(c * ARR_K + k)];
            }
        }
        wide_zero<16>(dut_->sparse_meta_in.data());
        size_t meta_bytes_per_row = static_cast<size_t>(ARR_K * 2);
        for (int r = 0; r < ARR_M; ++r) {
            for (size_t b = 0; b < meta_bytes_per_row; ++b) {
                size_t idx = static_cast<size_t>(r) * meta_bytes_per_row + b;
                uint8_t mv = (idx < tf.meta_bytes.size()) ? tf.meta_bytes[idx] : 0u;
                wide_set_bits(dut_->sparse_meta_in.data(), 16, idx * 8, 8, mv);
            }
        }
        uint32_t sa = 0, sb = 0;
        for (int r = 0; r < ARR_M; ++r) sa |= (static_cast<uint32_t>(tf.scale_a[r]) << (r * 8));
        for (int c = 0; c < ARR_N; ++c) sb |= (static_cast<uint32_t>(tf.scale_b[c]) << (c * 8));
        dut_->scale_a_in = sa;
        dut_->scale_b_in = sb;
        for (int r = 0; r < ARR_M; ++r) {
            for (int c = 0; c < ARR_N; ++c) {
                dut_->c_tile_in[r * ARR_N + c] = tf.c_tile[static_cast<size_t>(r * ARR_N + c)];
            }
        }
        for (int c = 0; c < ARR_N; ++c) dut_->bias_in[c] = tf.bias[c];
    }

    struct RunResult {
        std::vector<uint32_t> d_tile;
        uint8_t out_desc_id = 0;
        FpFlags flags{};
        bool saw_desc_done = false;
        uint8_t done_id = 0;
        bool saw_sparse_fault = false;
        bool saw_cta_out = false;
        int tmem_reqs = 0;
    };

    RunResult run_single_desc(const WgmmaDesc& desc, const TileFeed& tf,
                              bool drive_peer_cta_ack, const std::string& tag) {
        RunResult rr;
        bool desc_sent = false;
        uint32_t exp_uops = uops_for_desc(desc, ARR_M, ARR_N, ARR_K);
        uint32_t exp_outs = ((desc.tile_m + ARR_M - 1) / ARR_M) * ((desc.tile_n + ARR_N - 1) / ARR_N);
        uint32_t tiles_sent = 0;
        uint32_t tiles_got = 0;
        bool peer_ack_sent = !desc.cta_pair_en;
        int guard = 0;

        while (tiles_got < exp_outs || !rr.saw_desc_done) {
            dut_->desc_valid = desc_sent ? 0 : 1;
            pack_desc_wide<8>(dut_->desc_in.data(), desc);

            dut_->tile_in_valid = (tiles_sent < exp_uops) ? 1 : 0;
            set_tile_inputs(tf);

            dut_->tmem_req_ready = 1;
            dut_->tile_out_ready = 1;
            dut_->cta_sync_out_ready = 1;

            if (desc.cta_pair_en && drive_peer_cta_ack && !peer_ack_sent && rr.saw_cta_out) {
                dut_->cta_sync_in_valid = 1;
                dut_->cta_sync_in_bar_id = desc.barrier_id;
                dut_->cta_sync_in_phase = desc.barrier_phase ? 1 : 0;
            } else {
                dut_->cta_sync_in_valid = 0;
            }

            dut_->clk = 0;
            dut_->eval();

            if (dut_->desc_valid && dut_->desc_ready) {
                desc_sent = true;
            }
            if (dut_->tile_in_valid && dut_->tile_in_ready) {
                ++tiles_sent;
            }
            if (dut_->tmem_req_valid && dut_->tmem_req_ready) {
                ++rr.tmem_reqs;
            }
            if (dut_->cta_sync_out_valid && dut_->cta_sync_out_ready) {
                rr.saw_cta_out = true;
            }
            if (dut_->cta_sync_in_valid && dut_->cta_sync_in_ready) {
                peer_ack_sent = true;
            }
            if (dut_->tile_out_valid && dut_->tile_out_ready) {
                rr.d_tile.resize(ARR_M * ARR_N);
                for (int r = 0; r < ARR_M; ++r) {
                    for (int c = 0; c < ARR_N; ++c) {
                        rr.d_tile[r * ARR_N + c] = dut_->d_tile_out[r * ARR_N + c];
                    }
                }
                rr.out_desc_id = static_cast<uint8_t>(dut_->out_desc_id & 0xFFu);
                rr.flags = FpFlags::unpack(static_cast<uint8_t>(dut_->flags_out & 0x1Fu));
                ++tiles_got;
                guard = 0;
            }
            if (dut_->desc_done_valid) {
                if (tiles_got < exp_outs) {
                    std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: premature desc_done on %s (got=%u/%u)\n",
                                 tag.c_str(), tiles_got, exp_outs);
                    std::exit(1);
                }
                rr.saw_desc_done = true;
                rr.done_id = static_cast<uint8_t>(dut_->desc_done_id & 0xFFu);
            }
            if (dut_->sparse_fault) {
                rr.saw_sparse_fault = true;
            }

            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            ++guard;
            if (guard > 3000) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: timeout on %s (desc_sent=%d tiles_sent=%u/%u tiles_got=%u/%u done=%d cta_out=%d)\n",
                             tag.c_str(), desc_sent, tiles_sent, exp_uops, tiles_got, exp_outs, rr.saw_desc_done, rr.saw_cta_out);
                std::exit(1);
            }
        }
        dut_->desc_valid = 0;
        dut_->tile_in_valid = 0;
        dut_->cta_sync_in_valid = 0;
        for (int i = 0; i < 4; ++i) tick();
        ++tests_passed_;
        return rr;
    }

    // Check descriptor queue illegal-descriptor rejection
    void test_desc_rejection() {
        WgmmaDesc bad;
        bad.desc_id = 0xAAu;
        bad.fmt_a = FMT_MXFP4_E2M1;
        bad.fmt_b = FMT_MXFP4_E2M1;
        bad.scale_fmt = SCALE_NONE; // illegal: MX format with SCALE_NONE!
        bad.tile_m = 16;
        bad.tile_n = 8;
        bad.tile_k = 8;

        dut_->desc_valid = 1;
        pack_desc_wide<8>(dut_->desc_in.data(), bad);
        tick();
        dut_->desc_valid = 0;
        for (int i = 0; i < 6; ++i) tick();
        if (dut_->desc_done_valid) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: illegal descriptor should have been rejected\n");
            std::exit(1);
        }
        ++tests_passed_;
    }

    void csr_write(uint8_t addr, uint32_t data) {
        dut_->cfg_wr_valid = 1;
        dut_->cfg_wr_addr = addr;
        dut_->cfg_wr_data = data;
        tick();
        dut_->cfg_wr_valid = 0;
    }

    uint32_t csr_read(uint8_t addr) {
        dut_->cfg_rd_valid = 1;
        dut_->cfg_rd_addr = addr;
        tick();
        dut_->cfg_rd_valid = 0;
        int guard = 0;
        while (!dut_->cfg_rd_rsp_valid) {
            if (++guard > 10) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: CSR read timeout addr=0x%02x\n", addr);
                std::exit(1);
            }
            tick();
        }
        return dut_->cfg_rd_rsp_data;
    }

    std::vector<RunResult> run_multi_uop_desc(const WgmmaDesc& desc, const std::vector<TileFeed>& feeds,
                                              const std::string& tag) {
        std::vector<RunResult> outs;
        bool desc_sent = false;
        size_t tile_idx = 0;
        bool done_seen = false;
        uint8_t done_id = 0;
        size_t exp_out_tiles = ((desc.tile_m + ARR_M - 1) / ARR_M) * ((desc.tile_n + ARR_N - 1) / ARR_N);
        int guard = 0;

        while (outs.size() < exp_out_tiles || !done_seen) {
            dut_->desc_valid = desc_sent ? 0 : 1;
            pack_desc_wide<8>(dut_->desc_in.data(), desc);

            if (tile_idx < feeds.size()) {
                dut_->tile_in_valid = 1;
                set_tile_inputs(feeds[tile_idx]);
            } else {
                dut_->tile_in_valid = 0;
            }
            dut_->tmem_req_ready = 1;
            dut_->tile_out_ready = 1;
            dut_->cta_sync_out_ready = 1;
            dut_->cta_sync_in_valid = 0;

            dut_->clk = 0;
            dut_->eval();

            if (dut_->desc_valid && dut_->desc_ready) desc_sent = true;
            if (dut_->tile_in_valid && dut_->tile_in_ready) ++tile_idx;
            if (dut_->tile_out_valid && dut_->tile_out_ready) {
                RunResult rr;
                rr.d_tile.resize(ARR_M * ARR_N);
                for (int r = 0; r < ARR_M; ++r) {
                    for (int c = 0; c < ARR_N; ++c) {
                        rr.d_tile[r * ARR_N + c] = dut_->d_tile_out[r * ARR_N + c];
                    }
                }
                rr.out_desc_id = static_cast<uint8_t>(dut_->out_desc_id & 0xFFu);
                rr.flags = FpFlags::unpack(static_cast<uint8_t>(dut_->flags_out & 0x1Fu));
                outs.push_back(rr);
            }
            if (dut_->desc_done_valid) {
                if (outs.size() < exp_out_tiles) {
                    std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: premature desc_done on %s (got=%zu/%zu tiles)\n",
                                 tag.c_str(), outs.size(), exp_out_tiles);
                    std::exit(1);
                }
                done_seen = true;
                done_id = static_cast<uint8_t>(dut_->desc_done_id & 0xFFu);
            }

            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            if (++guard > 5000) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: timeout multi-uop %s (tiles=%zu/%zu out=%zu/%zu done=%d)\n",
                             tag.c_str(), tile_idx, feeds.size(), outs.size(), exp_out_tiles, done_seen);
                std::exit(1);
            }
        }
        (void)done_id;
        dut_->desc_valid = 0;
        dut_->tile_in_valid = 0;
        for (int i = 0; i < 4; ++i) tick();
        ++tests_passed_;
        return outs;
    }

    uint64_t tests_passed() const { return tests_passed_; }
    uint64_t cycles() const { return cycles_; }

private:
    VVX_tcu_v2_top* dut_;
    uint64_t cycles_ = 0;
    uint64_t tests_passed_ = 0;
};

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tcu_v2_top>();
    SparseWgmmaDriver drv(dut.get());
    drv.reset();

    // 1. Illegal descriptor rejection check
    drv.test_desc_rejection();

    // 2. Dense BF16 single-tile WGMMA with TMEM writeback req generation & descriptor retirement
    {
        WgmmaDesc d;
        d.desc_id = 1;
        d.fmt_a = FMT_BF16;
        d.fmt_b = FMT_BF16;
        d.fmt_c = FMT_FP32;
        d.fmt_d = FMT_FP32;
        d.scale_fmt = SCALE_NONE;
        d.rm = RM_RNE;
        d.act = ACT_RELU;
        d.sparse_en = false;
        d.cta_pair_en = false;
        d.accum_en = true;
        d.bias_en = true;
        d.tmem_wb_en = true;
        d.tile_m = 16;
        d.tile_n = 8;
        d.tile_k = 8;

        TileFeed tf;
        tf.a_tile.assign(ARR_M * ARR_K, 0x3F803F80u);
        tf.b_tile.assign(ARR_N * ARR_K, 0x40004000u);
        tf.a_cand.assign(ARR_M * ARR_K, 0u);
        tf.meta_bytes.assign(ARR_M * ARR_K * 2, 0u);
        tf.scale_a.assign(ARR_M, 0u);
        tf.scale_b.assign(ARR_N, 0u);
        tf.c_tile.assign(ARR_M * ARR_N, 0x3F800000u);
        tf.bias.assign(ARR_N, 0x3F000000u);

        auto rr = drv.run_single_desc(d, tf, false, "dense_bf16_wb");
        if (rr.out_desc_id != 1 || rr.done_id != 1 || rr.saw_sparse_fault || rr.tmem_reqs < 4) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL dense_bf16_wb: id=%u done=%u flt=%d reqs=%d\n",
                         rr.out_desc_id, rr.done_id, rr.saw_sparse_fault, rr.tmem_reqs);
            return 1;
        }
        FpFlags fexp{};
        auto exp = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d, tf.a_tile, tf.b_tile,
                                      tf.scale_a, tf.scale_b, tf.c_tile, tf.bias,
                                      true, true, fexp);
        if (rr.d_tile != exp) {
            std::fprintf(stderr, "[tb_sparse_wgmma] MISMATCH dense_bf16_wb: got[0]=%s exp[0]=%s\n",
                         hex32(rr.d_tile[0]).c_str(), hex32(exp[0]).c_str());
            return 1;
        }
    }

    // 3. Valid 2:4 Structured Sparse BF16 WGMMA (with 2-CTA peer barrier sync)
    {
        WgmmaDesc d;
        d.desc_id = 2;
        d.fmt_a = FMT_BF16;
        d.fmt_b = FMT_BF16;
        d.fmt_c = FMT_FP32;
        d.fmt_d = FMT_FP32;
        d.scale_fmt = SCALE_NONE;
        d.rm = RM_RNE;
        d.act = ACT_NONE;
        d.sparse_en = true;
        d.cta_pair_en = true;
        d.accum_en = false;
        d.bias_en = false;
        d.tmem_wb_en = false;
        d.barrier_id = 3;
        d.barrier_phase = true;
        d.tile_m = 16;
        d.tile_n = 8;
        d.tile_k = 16; // sparse 2x K-step

        TileFeed tf;
        tf.a_tile.assign(ARR_M * ARR_K, 0x3F803F80u); // 1.0, 1.0
        tf.a_cand.assign(ARR_M * ARR_K, 0x40004000u); // 2.0, 2.0
        tf.b_tile.assign(ARR_N * ARR_K, 0x3F803F80u); // 1.0
        // Pick indices (idx0=1, idx1=2) => nibble 0x9 (idx1=2, idx0=1) across every group
        tf.meta_bytes.assign(ARR_M * ARR_K * 2, 0x99u);
        tf.scale_a.assign(ARR_M, 0u);
        tf.scale_b.assign(ARR_N, 0u);
        tf.c_tile.assign(ARR_M * ARR_N, 0u);
        tf.bias.assign(ARR_N, 0u);

        auto rr = drv.run_single_desc(d, tf, true, "sparse_bf16_cta_pair");
        if (!rr.saw_cta_out || rr.saw_sparse_fault || rr.out_desc_id != 2) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL sparse_bf16_cta_pair: cta=%d flt=%d id=%u\n",
                         rr.saw_cta_out, rr.saw_sparse_fault, rr.out_desc_id);
            return 1;
        }
        std::vector<uint32_t> sel_a(ARR_M * ARR_K, 0u);
        for (int r = 0; r < ARR_M; ++r) {
            std::vector<uint32_t> r_tile(tf.a_tile.begin() + r * ARR_K, tf.a_tile.begin() + (r + 1) * ARR_K);
            std::vector<uint32_t> r_cand(tf.a_cand.begin() + r * ARR_K, tf.a_cand.begin() + (r + 1) * ARR_K);
            std::vector<uint8_t>  r_meta(tf.meta_bytes.begin() + r * ARR_K * 2, tf.meta_bytes.begin() + (r + 1) * ARR_K * 2);
            uint32_t err_mask = 0;
            bool ok = ref_sparse_validate_row(d.fmt_a, ARR_K, r_tile, r_cand, r_meta, err_mask);
            if (!ok || err_mask != 0) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL ref sparse validate row %d\n", r);
                return 1;
            }
            auto sel_row = ref_sparse_select_row(d.fmt_a, ARR_K, true, false, r_tile, r_cand, r_meta, err_mask);
            for (int k = 0; k < ARR_K; ++k) sel_a[r * ARR_K + k] = sel_row[k];
        }
        FpFlags fexp{};
        auto exp = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d, sel_a, tf.b_tile,
                                      tf.scale_a, tf.scale_b, tf.c_tile, tf.bias,
                                      true, true, fexp);
        if (rr.d_tile != exp) {
            std::fprintf(stderr, "[tb_sparse_wgmma] MISMATCH sparse_bf16: got[0]=%s exp[0]=%s\n",
                         hex32(rr.d_tile[0]).c_str(), hex32(exp[0]).c_str());
            return 1;
        }
    }

    // 4. Illegal 2:4 Sparse Metadata Injection followed immediately by Valid Dense Tile
    //    (Verifies same-cycle validator/selector suppression does not leak into next tile)
    {
        WgmmaDesc d;
        d.desc_id = 3;
        d.fmt_a = FMT_FP8_E4M3;
        d.fmt_b = FMT_FP8_E4M3;
        d.fmt_c = FMT_FP32;
        d.fmt_d = FMT_FP32;
        d.scale_fmt = SCALE_NONE;
        d.sparse_en = true;
        d.cta_pair_en = false;
        d.accum_en = false;
        d.tile_m = 16;
        d.tile_n = 8;
        d.tile_k = 16;

        TileFeed tf;
        tf.a_tile.assign(ARR_M * ARR_K, 0x38383838u);
        tf.a_cand.assign(ARR_M * ARR_K, 0x40404040u);
        tf.b_tile.assign(ARR_N * ARR_K, 0x38383838u);
        tf.meta_bytes.assign(ARR_M * ARR_K * 2, 0x00u); // idx0=0, idx1=0 => ILLEGAL!
        tf.scale_a.assign(ARR_M, 0u);
        tf.scale_b.assign(ARR_N, 0u);
        tf.c_tile.assign(ARR_M * ARR_N, 0u);
        tf.bias.assign(ARR_N, 0u);

        auto rr = drv.run_single_desc(d, tf, false, "sparse_illegal_meta");
        if (!rr.saw_sparse_fault) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: illegal sparse metadata did not trigger sparse_fault\n");
            return 1;
        }
        for (uint32_t v : rr.d_tile) {
            if (v != 0u) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: fault-suppressed tile had non-zero output %s\n",
                             hex32(v).c_str());
                return 1;
            }
        }

        // Follow immediately with a valid dense BF16 tile (must NOT be suppressed!)
        WgmmaDesc dv;
        dv.desc_id = 4;
        dv.fmt_a = FMT_BF16;
        dv.fmt_b = FMT_BF16;
        dv.fmt_c = FMT_FP32;
        dv.fmt_d = FMT_FP32;
        dv.scale_fmt = SCALE_NONE;
        dv.sparse_en = false;
        dv.accum_en = false;
        dv.tile_m = 16;
        dv.tile_n = 8;
        dv.tile_k = 8;
        TileFeed tf_v;
        tf_v.a_tile.assign(ARR_M * ARR_K, 0x3F803F80u);
        tf_v.b_tile.assign(ARR_N * ARR_K, 0x3F803F80u);
        tf_v.a_cand.assign(ARR_M * ARR_K, 0u);
        tf_v.meta_bytes.assign(ARR_M * ARR_K * 2, 0u);
        tf_v.scale_a.assign(ARR_M, 0u);
        tf_v.scale_b.assign(ARR_N, 0u);
        tf_v.c_tile.assign(ARR_M * ARR_N, 0u);
        tf_v.bias.assign(ARR_N, 0u);
        auto rr_v = drv.run_single_desc(dv, tf_v, false, "post_fault_valid_dense");
        for (uint32_t v : rr_v.d_tile) {
            if (v != 0x41000000u) { // 8.0f
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: post-fault valid dense tile corrupted: got=%s exp=0x41000000\n",
                             hex32(v).c_str());
                return 1;
            }
        }

        // Clear sticky fault status via CSR ADDR_FAULT_CLEAR (0x0C) before Test 5
        drv.csr_write(0x0Cu, 0x1u);
        drv.tick();
        drv.tick();
        if (dut->sparse_fault) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: sticky sparse_fault did not clear via CSR 0x0C\n");
            return 1;
        }
    }

    // 5. FP4 8-nibble Sparse WGMMA across full 4-group/word metadata
    {
        WgmmaDesc d;
        d.desc_id = 5;
        d.fmt_a = FMT_MXFP4_E2M1;
        d.fmt_b = FMT_MXFP4_E2M1;
        d.fmt_c = FMT_FP32;
        d.fmt_d = FMT_FP32;
        d.scale_fmt = SCALE_UE8M0;
        d.rm = RM_RNE;
        d.sparse_en = true;
        d.accum_en = false;
        d.tile_m = 16;
        d.tile_n = 8;
        d.tile_k = 16;

        TileFeed tf;
        // Pack distinct nibbles in upper 16b vs lower 16b: 0x05325002 / 0x07000701
        // Group 0: (2, 0, 1, 0) -> idx 0,2 => meta=0x8 -> (2, 1) (1.0, 0.5)
        // Group 1: (2, 3, 7, 0) -> idx 1,2 => meta=0x9 -> (3, 7) (1.5, 6.0)
        // Group 2: (5, 0, 0, 0) -> idx 0,1 => meta=0x4 -> (5, 0) (3.0, 0.0)
        // Group 3: (0, 5, 0, 7) -> idx 1,3 => meta=0xD -> (5, 7) (3.0, 6.0)
        // Per-word meta = 0xD498 -> lo byte 0x98, hi byte 0xD4
        tf.a_tile.assign(ARR_M * ARR_K, 0x05325002u);
        tf.a_cand.assign(ARR_M * ARR_K, 0x07000701u);
        tf.b_tile.assign(ARR_N * ARR_K, 0x00000002u); // lane 0 = 1.0, lanes 1..7 = 0.0
        tf.meta_bytes.assign(ARR_M * ARR_K * 2, 0u);
        for (int r = 0; r < ARR_M; ++r) {
            for (int k = 0; k < ARR_K; ++k) {
                tf.meta_bytes[(r * ARR_K + k) * 2 + 0] = 0x98u;
                tf.meta_bytes[(r * ARR_K + k) * 2 + 1] = 0xD4u;
            }
        }
        tf.scale_a.assign(ARR_M, 0x7Fu);
        tf.scale_b.assign(ARR_N, 0x7Fu);
        tf.c_tile.assign(ARR_M * ARR_N, 0u);
        tf.bias.assign(ARR_N, 0u);

        auto rr = drv.run_single_desc(d, tf, false, "sparse_fp4_8nibble");
        if (rr.saw_sparse_fault) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: valid 8-nibble FP4 sparse raised fault\n");
            return 1;
        }
        // Check decompressor valid & non-illegal telemetry via CSR ADDR_DECOMP_STATUS (0x40)
        uint32_t decomp_st = drv.csr_read(0x40u);
        if ((decomp_st & 0x1u) == 0u || (decomp_st & 0x2u) != 0u) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: ADDR_DECOMP_STATUS unexpected=0x%08x\n", decomp_st);
            return 1;
        }
        // Verify selected A tile matches reference row selection (no upper-16b duplication!)
        std::vector<uint32_t> sel_a(ARR_M * ARR_K, 0u);
        for (int r = 0; r < ARR_M; ++r) {
            std::vector<uint32_t> r_tile(tf.a_tile.begin() + r * ARR_K, tf.a_tile.begin() + (r + 1) * ARR_K);
            std::vector<uint32_t> r_cand(tf.a_cand.begin() + r * ARR_K, tf.a_cand.begin() + (r + 1) * ARR_K);
            std::vector<uint8_t>  r_meta(tf.meta_bytes.begin() + r * ARR_K * 2, tf.meta_bytes.begin() + (r + 1) * ARR_K * 2);
            uint32_t err_mask = 0;
            bool ok = ref_sparse_validate_row(d.fmt_a, ARR_K, r_tile, r_cand, r_meta, err_mask);
            if (!ok || err_mask != 0) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: ref FP4 sparse validate failed\n");
                return 1;
            }
            auto sel_row = ref_sparse_select_row(d.fmt_a, ARR_K, true, false, r_tile, r_cand, r_meta, err_mask);
            for (int k = 0; k < ARR_K; ++k) sel_a[r * ARR_K + k] = sel_row[k];
        }
        FpFlags fexp{};
        auto exp = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d, sel_a, tf.b_tile,
                                      tf.scale_a, tf.scale_b, tf.c_tile, tf.bias, true, true, fexp);
        if (rr.d_tile != exp) {
            std::fprintf(stderr, "[tb_sparse_wgmma] MISMATCH sparse_fp4_8nibble: got[0]=%s exp[0]=%s\n",
                         hex32(rr.d_tile[0]).c_str(), hex32(exp[0]).c_str());
            return 1;
        }
    }

    // 6. Multi-M/N (8 output tiles) & Multi-K-step (2 K-steps) WGMMA with bias_en=1
    //    (Verifies multi-tile retirement ordering and last-K bias application)
    {
        WgmmaDesc d;
        d.desc_id = 6;
        d.fmt_a = FMT_BF16;
        d.fmt_b = FMT_BF16;
        d.fmt_c = FMT_FP32;
        d.fmt_d = FMT_FP32;
        d.scale_fmt = SCALE_NONE;
        d.rm = RM_RNE;
        d.act = ACT_NONE;
        d.sparse_en = false;
        d.accum_en = true;
        d.bias_en = true;
        d.tile_m = 16; // 4 output rows * 4 steps_m = 16 -> with ARR_M=4, steps_m = 4
        d.tile_n = 8;  // with ARR_N=4, steps_n = 2 -> total 8 output tiles!
        d.tile_k = 16; // with ARR_K=8, steps_k = 2 -> total 16 uops!

        std::vector<TileFeed> feeds;
        std::vector<std::vector<uint32_t>> exp_outputs;
        for (int sm = 0; sm < 4; ++sm) {
            for (int sn = 0; sn < 2; ++sn) {
                std::vector<uint32_t> acc_c(ARR_M * ARR_N, 0x3F800000u); // 1.0f
                FpFlags fexp{};
                for (int sk = 0; sk < 2; ++sk) {
                    TileFeed tf;
                    uint32_t aval = (sk == 0) ? 0x3F803F80u : 0x40004000u; // 1.0 then 2.0
                    tf.a_tile.assign(ARR_M * ARR_K, aval);
                    tf.b_tile.assign(ARR_N * ARR_K, 0x3F803F80u); // 1.0
                    tf.a_cand.assign(ARR_M * ARR_K, 0u);
                    tf.meta_bytes.assign(ARR_M * ARR_K * 2, 0u);
                    tf.scale_a.assign(ARR_M, 0u);
                    tf.scale_b.assign(ARR_N, 0u);
                    tf.c_tile = acc_c;
                    tf.bias.assign(ARR_N, 0x40400000u); // +3.0f
                    feeds.push_back(tf);
                    acc_c = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d, tf.a_tile, tf.b_tile,
                                               tf.scale_a, tf.scale_b, acc_c, tf.bias,
                                               sk == 0, sk == 1, fexp);
                }
                exp_outputs.push_back(acc_c);
            }
        }
        auto outs = drv.run_multi_uop_desc(d, feeds, "multi_mn_multi_k_bias");
        if (outs.size() != exp_outputs.size()) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: multi_mn_multi_k output count %zu != %zu\n",
                         outs.size(), exp_outputs.size());
            return 1;
        }
        for (size_t i = 0; i < outs.size(); ++i) {
            if (outs[i].d_tile != exp_outputs[i]) {
                std::fprintf(stderr, "[tb_sparse_wgmma] MISMATCH multi_mn_multi_k tile=%zu got[0]=%s exp[0]=%s\n",
                             i, hex32(outs[i].d_tile[0]).c_str(), hex32(exp_outputs[i][0]).c_str());
                return 1;
            }
        }
    }

    // 7. CSR write/readback test on VX_tcu_v2_ctrl_regfile (ARCH_ID 0x3C + CTRL_CFG 0x00)
    {
        uint32_t arch_id = drv.csr_read(0x3Cu);
        if (arch_id != 0x54435532u) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: ARCH_ID=0x%08x exp=0x54435532\n", arch_id);
            return 1;
        }
        drv.csr_write(0x00u, 0x02u); // swizzle_mode = 2
        uint32_t cfg = drv.csr_read(0x00u);
        if ((cfg & 0x3u) != 0x2u) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: CTRL_CFG readback=0x%08x\n", cfg);
            return 1;
        }
    }

    // 8. Multi-pipe credit-return stress (10 sequential single-tile descriptors across NUM_PIPES=2 > CREDITS_INIT=4)
    {
        for (int iter = 0; iter < 10; ++iter) {
            WgmmaDesc d;
            d.desc_id = static_cast<uint8_t>(0x30 + iter);
            d.fmt_a = FMT_BF16;
            d.fmt_b = FMT_BF16;
            d.fmt_c = FMT_FP32;
            d.fmt_d = FMT_FP32;
            d.scale_fmt = SCALE_NONE;
            d.accum_en = false;
            d.tile_m = 16;
            d.tile_n = 8;
            d.tile_k = 8;
            TileFeed tf;
            tf.a_tile.assign(ARR_M * ARR_K, 0x3F803F80u);
            tf.b_tile.assign(ARR_N * ARR_K, 0x3F803F80u);
            tf.a_cand.assign(ARR_M * ARR_K, 0u);
            tf.meta_bytes.assign(ARR_M * ARR_K * 2, 0u);
            tf.scale_a.assign(ARR_M, 0u);
            tf.scale_b.assign(ARR_N, 0u);
            tf.c_tile.assign(ARR_M * ARR_N, 0u);
            tf.bias.assign(ARR_N, 0u);
            auto rr = drv.run_single_desc(d, tf, false, "pipe_credit_stress_" + std::to_string(iter));
            if (rr.d_tile[0] != 0x41000000u) {
                std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: credit stress iter=%d got=%s\n",
                             iter, hex32(rr.d_tile[0]).c_str());
                return 1;
            }
        }
    }

    // 9. Mixed integer x floating-point descriptor rejection check
    {
        WgmmaDesc bad_mix;
        bad_mix.desc_id = 0x7Eu;
        bad_mix.fmt_a = FMT_INT8;
        bad_mix.fmt_b = FMT_FP8_E4M3;
        bad_mix.fmt_c = FMT_FP32;
        bad_mix.fmt_d = FMT_FP32;
        bad_mix.scale_fmt = SCALE_NONE;
        bad_mix.tile_m = 16;
        bad_mix.tile_n = 8;
        bad_mix.tile_k = 8;

        pack_desc_wide<8>(dut_->desc_in.data(), bad_mix);
        dut_->desc_valid = 1;
        bool saw_reject = false;
        for (int cyc = 0; cyc < 8; ++cyc) {
            dut_->clk = 0;
            dut_->eval();
            if (dut_->desc_valid && dut_->desc_ready) {
                dut_->clk = 1;
                dut_->eval();
                dut_->desc_valid = 0;
            } else {
                dut_->clk = 1;
                dut_->eval();
            }
            if (dut_->desc_reject) {
                saw_reject = true;
                break;
            }
        }
        dut_->desc_valid = 0;
        if (!saw_reject) {
            std::fprintf(stderr, "[tb_sparse_wgmma] FAIL: mixed INT8 x FP8_E4M3 descriptor was not rejected\n");
            return 1;
        }
        for (int i = 0; i < 4; ++i) drv.tick();
    }

    std::printf("[tb_sparse_wgmma] PASS: tests=%llu cycles=%llu\n",
                static_cast<unsigned long long>(drv.tests_passed()),
                static_cast<unsigned long long>(drv.cycles()));
    return 0;
}
