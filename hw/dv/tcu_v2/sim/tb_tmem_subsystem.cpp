// SPDX-License-Identifier: Apache-2.0
#include "VVX_tmem_top.h"
#include "tcu_v2_golden_ref.h"
#include <verilated.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <string>
#include <vector>

double sc_time_stamp() { return 0.0; }

namespace {

using namespace tcu_v2_ref;

constexpr int LANES = 8;

// Pack tmem_alloc_req_t (32 bits total):
// owner_warp[4:0], double_buf_en, swizzle[1:0], num_rows[7:0], num_columns[9:0], col_offset[8:0], region_id[3:0], is_dealloc
// Width = 1+4+9+10+8+2+1+5 = 40 bits (VlWide<2> or uint64_t!)
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

class TmemDriver {
public:
    explicit TmemDriver(VVX_tmem_top* dut) : dut_(dut) {}

    void reset() {
        dut_->reset = 1;
        dut_->alloc_valid = 0;
        dut_->alloc_op = 0;
        dut_->alloc_auto_place = 0;
        dut_->alloc_buddy_align = 0;
        dut_->alloc_strict_owner = 1;
        dut_->alloc_req = 0;

        dut_->ld_desc_valid = 0;
        dut_->ld_desc_tag = 0;
        dut_->ld_desc_region_id = 0;
        dut_->ld_desc_warp_id = 0;
        dut_->ld_desc_row_base = 0;
        dut_->ld_desc_col_base = 0;
        dut_->ld_desc_num_rows = 0;
        dut_->ld_desc_num_cols = 0;
        dut_->ld_desc_elem_bytes = 2;
        dut_->ld_desc_col_major = 0;
        dut_->ld_desc_subbyte_shift = 0;
        dut_->ld_xform_en = 0;
        dut_->ld_xform_mode = 0;
        dut_->ld_xform_fmt = 0;
        dut_->ld_xform_tile8x8 = 0;
        dut_->ld_xform_unpack32 = 0;
        dut_->ld_rsp_ready = 1;

        dut_->st_req_valid = 0;
        dut_->st_req_tag = 0;
        dut_->st_req_region_id = 0;
        dut_->st_req_warp_id = 0;
        dut_->st_req_row_base = 0;
        dut_->st_req_col_base = 0;
        dut_->st_req_num_rows = 0;
        dut_->st_req_num_cols = 0;
        dut_->st_req_col_major = 0;
        dut_->st_req_cell32_mode = 0;
        wide_zero<16>(dut_->st_req_data.data());
        dut_->st_req_be = 0;
        dut_->st_req_last = 0;
        dut_->st_ack_ready = 1;

        dut_->mma_req_valid = 0;
        dut_->mma_req_op = TMEM_OP_NOP;
        dut_->mma_req_tag = 0;
        dut_->mma_req_region_id = 0;
        dut_->mma_req_warp_id = 0;
        dut_->mma_req_row = 0;
        dut_->mma_req_col = 0;
        dut_->mma_req_swizzle = SWIZZLE_NONE;
        dut_->mma_req_col_count = 0;
        dut_->mma_req_ping_pong_sel = 0;
        wide_zero<16>(dut_->mma_req_wr_data.data());
        dut_->mma_req_wr_be = 0;
        dut_->mma_rsp_ready = 1;

        dut_->wait_req_valid = 0;
        dut_->wait_req_op = TMEM_OP_NOP;
        dut_->wait_req_tag = 0;
        dut_->wait_req_region_id = 0;
        dut_->wait_req_warp_id = 0;
        dut_->wait_req_scope_warp = 0;
        dut_->wait_req_barrier_id = 0;
        dut_->wait_req_barrier_phase = 0;
        dut_->peer_bar_valid = 0;
        dut_->peer_bar_id = 0;
        dut_->peer_bar_phase = 0;
        dut_->wait_rsp_ready = 1;

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
        alloc_ref_.reset();
    }

    void tick() {
        dut_->clk = 0;
        dut_->eval();
        dut_->clk = 1;
        dut_->eval();
        ++cycles_;
    }

    TmemAllocRsp do_alloc_cmd(uint8_t op, bool auto_place, bool buddy, bool strict_owner,
                              const TmemAllocReq& req, const std::string& tag) {
        dut_->alloc_valid = 1;
        dut_->alloc_op = op;
        dut_->alloc_auto_place = auto_place ? 1 : 0;
        dut_->alloc_buddy_align = buddy ? 1 : 0;
        dut_->alloc_strict_owner = strict_owner ? 1 : 0;
        dut_->alloc_req = pack_alloc_req(req);
        while (!dut_->alloc_ready) tick();
        tick();
        dut_->alloc_valid = 0;
        // Registered alloc_rsp appears after tick
        int guard = 0;
        TmemAllocRsp got = unpack_alloc_rsp(dut_->alloc_rsp);
        while (!got.valid) {
            tick();
            got = unpack_alloc_rsp(dut_->alloc_rsp);
            if (++guard > 20) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: alloc timeout on %s\n", tag.c_str());
                std::exit(1);
            }
        }
        TmemAllocRsp exp = alloc_ref_.execute(op, auto_place, buddy, strict_owner, req);
        if (got.status != exp.status ||
            (exp.status == TMEM_STATUS_OK && (got.col_offset != exp.col_offset ||
                                              got.buf_b_col_offset != exp.buf_b_col_offset ||
                                              got.region_id != exp.region_id))) {
            std::fprintf(stderr,
                         "[tb_tmem_subsystem] ALLOC MISMATCH %s: got(st=%u id=%u col=%u bb=%u) exp(st=%u id=%u col=%u bb=%u)\n",
                         tag.c_str(), got.status, got.region_id, got.col_offset, got.buf_b_col_offset,
                         exp.status, exp.region_id, exp.col_offset, exp.buf_b_col_offset);
            std::exit(1);
        }
        ++checks_;
        return got;
    }

    void do_store(uint8_t tag, uint8_t reg_id, uint8_t warp, uint8_t row, uint16_t col,
                  uint8_t nrows, uint16_t ncols, bool col_major, bool cell32,
                  const std::array<uint64_t, 8>& data, const std::array<uint8_t, 8>& be,
                  TmemStatus exp_status) {
        dut_->st_req_valid = 1;
        dut_->st_req_tag = tag;
        dut_->st_req_region_id = reg_id;
        dut_->st_req_warp_id = warp;
        dut_->st_req_row_base = row;
        dut_->st_req_col_base = col;
        dut_->st_req_num_rows = nrows;
        dut_->st_req_num_cols = ncols;
        dut_->st_req_col_major = col_major ? 1 : 0;
        dut_->st_req_cell32_mode = cell32 ? 1 : 0;
        uint64_t be_pack = 0;
        for (int l = 0; l < LANES; ++l) {
            dut_->st_req_data[2 * l] = static_cast<uint32_t>(data[l] & 0xFFFFFFFFULL);
            dut_->st_req_data[2 * l + 1] = static_cast<uint32_t>(data[l] >> 32);
            be_pack |= (static_cast<uint64_t>(be[l]) << (l * 8));
        }
        dut_->st_req_be = be_pack;
        dut_->st_req_last = 1;

        int guard = 0;
        while (!(dut_->st_req_valid && dut_->st_req_ready)) {
            tick();
            if (++guard > 200) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: store accept timeout\n");
                std::exit(1);
            }
        }
        tick();
        dut_->st_req_valid = 0;

        guard = 0;
        while (!dut_->st_ack_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: store ack timeout\n");
                std::exit(1);
            }
        }
        if (dut_->st_ack_status != exp_status || dut_->st_ack_tag != tag) {
            std::fprintf(stderr, "[tb_tmem_subsystem] STORE ACK MISMATCH: got st=%u tag=%u exp st=%u tag=%u\n",
                         dut_->st_ack_status, dut_->st_ack_tag, exp_status, tag);
            std::exit(1);
        }
        tick();
        ++checks_;
    }

    struct LdResult {
        TmemStatus status = TMEM_STATUS_OK;
        std::array<uint64_t, 8> data{};
        uint8_t lane_mask = 0;
        bool ecc_ce = false;
        bool ecc_ue = false;
    };

    LdResult do_load(uint8_t tag, uint8_t reg_id, uint8_t warp, uint8_t row, uint16_t col,
                     uint8_t nrows, uint16_t ncols, uint8_t elem_bytes, bool col_major,
                     bool xform_en, uint8_t xform_mode, uint8_t xform_fmt) {
        dut_->ld_desc_valid = 1;
        dut_->ld_desc_tag = tag;
        dut_->ld_desc_region_id = reg_id;
        dut_->ld_desc_warp_id = warp;
        dut_->ld_desc_row_base = row;
        dut_->ld_desc_col_base = col;
        dut_->ld_desc_num_rows = nrows;
        dut_->ld_desc_num_cols = ncols;
        dut_->ld_desc_elem_bytes = elem_bytes;
        dut_->ld_desc_col_major = col_major ? 1 : 0;
        dut_->ld_desc_subbyte_shift = 0;
        dut_->ld_xform_en = xform_en ? 1 : 0;
        dut_->ld_xform_mode = xform_mode;
        dut_->ld_xform_fmt = xform_fmt;
        dut_->ld_xform_tile8x8 = 0;
        dut_->ld_xform_unpack32 = 0;

        int guard = 0;
        while (!(dut_->ld_desc_valid && dut_->ld_desc_ready)) {
            tick();
            if (++guard > 200) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: load desc timeout\n");
                std::exit(1);
            }
        }
        tick();
        dut_->ld_desc_valid = 0;

        LdResult res;
        guard = 0;
        while (!dut_->ld_rsp_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: load rsp timeout tag=0x%02x checks=%llu\n",
                             tag, static_cast<unsigned long long>(checks_));
                std::exit(1);
            }
        }
        res.status = static_cast<TmemStatus>(dut_->ld_rsp_status);
        res.lane_mask = static_cast<uint8_t>(dut_->ld_rsp_lane_mask & 0xFFu);
        res.ecc_ce = dut_->ld_rsp_ecc_ce != 0;
        res.ecc_ue = dut_->ld_rsp_ecc_ue != 0;
        for (int l = 0; l < LANES; ++l) {
            uint64_t lo = dut_->ld_rsp_data[2 * l];
            uint64_t hi = dut_->ld_rsp_data[2 * l + 1];
            res.data[l] = lo | (hi << 32);
        }
        tick();
        ++checks_;
        return res;
    }

    LdResult do_mma(TmemOp op, uint8_t tag, uint8_t reg_id, uint8_t warp, uint8_t row, uint16_t col,
                    TmemSwizzle swizzle, uint8_t col_cnt, bool pp_sel,
                    const std::array<uint64_t, 8>& wr_data, const std::array<uint8_t, 8>& wr_be) {
        dut_->mma_req_valid = 1;
        dut_->mma_req_op = op;
        dut_->mma_req_tag = tag;
        dut_->mma_req_region_id = reg_id;
        dut_->mma_req_warp_id = warp;
        dut_->mma_req_row = row;
        dut_->mma_req_col = col;
        dut_->mma_req_swizzle = swizzle;
        dut_->mma_req_col_count = col_cnt;
        dut_->mma_req_ping_pong_sel = pp_sel ? 1 : 0;
        uint64_t be_pack = 0;
        for (int l = 0; l < LANES; ++l) {
            dut_->mma_req_wr_data[2 * l] = static_cast<uint32_t>(wr_data[l] & 0xFFFFFFFFULL);
            dut_->mma_req_wr_data[2 * l + 1] = static_cast<uint32_t>(wr_data[l] >> 32);
            be_pack |= (static_cast<uint64_t>(wr_be[l]) << (l * 8));
        }
        dut_->mma_req_wr_be = be_pack;

        int guard = 0;
        while (!(dut_->mma_req_valid && dut_->mma_req_ready)) {
            tick();
            if (++guard > 200) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: mma req timeout\n");
                std::exit(1);
            }
        }
        tick();
        dut_->mma_req_valid = 0;

        LdResult res;
        guard = 0;
        while (!dut_->mma_rsp_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: mma rsp timeout\n");
                std::exit(1);
            }
        }
        res.status = static_cast<TmemStatus>(dut_->mma_rsp_status);
        res.lane_mask = static_cast<uint8_t>(dut_->mma_rsp_lane_mask & 0xFFu);
        res.ecc_ce = dut_->mma_rsp_ecc_ce != 0;
        res.ecc_ue = dut_->mma_rsp_ecc_ue != 0;
        for (int l = 0; l < LANES; ++l) {
            uint64_t lo = dut_->mma_rsp_data[2 * l];
            uint64_t hi = dut_->mma_rsp_data[2 * l + 1];
            res.data[l] = lo | (hi << 32);
        }
        tick();
        ++checks_;
        return res;
    }

    void do_fence(uint8_t tag, uint8_t reg_id, uint8_t warp, bool scope_warp) {
        dut_->wait_req_valid = 1;
        dut_->wait_req_op = TMEM_OP_FENCE;
        dut_->wait_req_tag = tag;
        dut_->wait_req_region_id = reg_id;
        dut_->wait_req_warp_id = warp;
        dut_->wait_req_scope_warp = scope_warp ? 1 : 0;
        dut_->wait_req_barrier_id = 0;
        dut_->wait_req_barrier_phase = 0;
        while (!dut_->wait_req_ready) tick();
        tick();
        dut_->wait_req_valid = 0;
        int guard = 0;
        while (!dut_->wait_rsp_valid) {
            tick();
            if (++guard > 400) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: fence timeout\n");
                std::exit(1);
            }
        }
        if (dut_->wait_rsp_status != TMEM_STATUS_OK) {
            std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: fence status=%u\n", dut_->wait_rsp_status);
            std::exit(1);
        }
        tick();
        ++checks_;
    }

    void set_ecc_inj(bool en, uint8_t bank, uint64_t data_mask, uint8_t parity_mask) {
        dut_->ecc_inj_en = en ? 1 : 0;
        dut_->ecc_inj_bank = bank;
        dut_->ecc_inj_mask[0] = static_cast<uint32_t>(data_mask & 0xFFFFFFFFULL);
        dut_->ecc_inj_mask[1] = static_cast<uint32_t>(data_mask >> 32);
        dut_->ecc_inj_mask[2] = static_cast<uint32_t>(parity_mask);
    }

    uint64_t checks() const { return checks_; }
    uint64_t cycles() const { return cycles_; }
    VVX_tmem_top* dut() { return dut_; }

private:
    VVX_tmem_top* dut_;
    TmemAllocatorRef alloc_ref_;
    uint64_t cycles_ = 0;
    uint64_t checks_ = 0;
};

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tmem_top>();
    TmemDriver drv(dut.get());
    drv.reset();

    // 1. Verify Allocator: explicit alloc, overlap rejection, auto-place, buddy alignment, query, flip, dealloc
    TmemAllocReq r0{false, 0, 0, 64, 64, SWIZZLE_32B, true, 1};
    drv.do_alloc_cmd(ALLOC_CMD_ALLOC, false, true, true, r0, "alloc_r0_dbl");

    // Overlapping allocation must fail with OVERLAP
    TmemAllocReq r_ovl{false, 1, 32, 32, 32, SWIZZLE_NONE, false, 1};
    drv.do_alloc_cmd(ALLOC_CMD_ALLOC, false, false, true, r_ovl, "alloc_r_ovl");

    // Auto-place 64 columns with buddy alignment (r0 takes cols [0..127], so auto-place picks 128)
    TmemAllocReq r1{false, 1, 0, 64, 128, SWIZZLE_128B, false, 2};
    drv.do_alloc_cmd(ALLOC_CMD_ALLOC, true, true, true, r1, "alloc_r1_auto");

    // Bad size (non-power-of-two columns = 48)
    TmemAllocReq r_bad{false, 2, 0, 48, 32, SWIZZLE_NONE, false, 1};
    drv.do_alloc_cmd(ALLOC_CMD_ALLOC, false, false, true, r_bad, "alloc_bad_size");

    // 2. Store & Load with Swizzle Modes + 32-bit cell packing + Bounds Check
    // Region 1 is at col=128..191, rows=0..127, SWIZZLE_128B, owner_warp=2
    std::array<uint64_t, 8> pat{};
    std::array<uint8_t, 8> all_be{};
    for (int l = 0; l < LANES; ++l) {
        pat[l] = 0x1122334400000000ULL | static_cast<uint64_t>(0xCAFE0000u + l);
        all_be[l] = 0xFFu;
    }
    drv.do_store(0x10u, 1, 2, 5, 128, 1, 8, false, true, pat, all_be, TMEM_STATUS_OK);
    drv.do_fence(0x11u, 1, 2, true);

    auto ld1 = drv.do_load(0x12u, 1, 2, 5, 128, 1, 8, 2, false, false, 0, 0);
    if (ld1.status != TMEM_STATUS_OK) {
        std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: load status=%u\n", ld1.status);
        return 1;
    }
    for (int l = 0; l < LANES; ++l) {
        uint32_t got32 = static_cast<uint32_t>(ld1.data[l] & 0xFFFFFFFFULL);
        uint32_t exp32 = static_cast<uint32_t>(pat[l] & 0xFFFFFFFFULL);
        if (got32 != exp32) {
            std::fprintf(stderr, "[tb_tmem_subsystem] LOAD MISMATCH lane=%d got=%s exp=%s\n",
                         l, hex32(got32).c_str(), hex32(exp32).c_str());
            return 1;
        }
    }

    // 3. Cross-warp store protection & out-of-bounds fault enforcement
    drv.do_store(0x13u, 1, 5 /* wrong warp */, 5, 128, 1, 8, false, true, pat, all_be, TMEM_STATUS_NOT_ALLOCED);
    drv.do_store(0x14u, 1, 2, 5, 190 /* OOB col */, 1, 8, false, true, pat, all_be, TMEM_STATUS_NOT_ALLOCED);

    // 4. SECDED Hsiao(72,64) ECC Single-Bit Error Correction (CE) and Double-Bit Detection (UE)
    // Target bank for (row=6, col=128) under SWIZZLE_128B:
    uint8_t tgt_bank = tmem_swizzled_bank(6, 128, SWIZZLE_128B);
    drv.set_ecc_inj(true, tgt_bank, (1ULL << 17), 0u); // 1-bit flip in data
    drv.do_store(0x20u, 1, 2, 6, 128, 1, 8, false, false, pat, all_be, TMEM_STATUS_OK);
    drv.set_ecc_inj(false, 0, 0ULL, 0u);

    auto ld_ce = drv.do_load(0x21u, 1, 2, 6, 128, 1, 8, 3, false, false, 0, 0);
    if (ld_ce.status != TMEM_STATUS_OK || !ld_ce.ecc_ce || ld_ce.ecc_ue || ld_ce.data[0] != pat[0]) {
        std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: ECC CE check st=%u ce=%d ue=%d got=%s exp=%s\n",
                     ld_ce.status, ld_ce.ecc_ce, ld_ce.ecc_ue,
                     hex64(ld_ce.data[0]).c_str(), hex64(pat[0]).c_str());
        return 1;
    }

    // Inject double-bit error -> must report UE and TMEM_STATUS_ECC_UE
    uint8_t tgt_bank7 = tmem_swizzled_bank(7, 128, SWIZZLE_128B);
    drv.set_ecc_inj(true, tgt_bank7, (1ULL << 3) | (1ULL << 29), 0u);
    drv.do_store(0x22u, 1, 2, 7, 128, 1, 8, false, false, pat, all_be, TMEM_STATUS_OK);
    drv.set_ecc_inj(false, 0, 0ULL, 0u);

    auto ld_ue = drv.do_load(0x23u, 1, 2, 7, 128, 1, 8, 3, false, false, 0, 0);
    if (ld_ue.status != TMEM_STATUS_ECC_UE || !ld_ue.ecc_ue) {
        std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: ECC UE check st=%u ue=%d\n",
                     ld_ue.status, ld_ue.ecc_ue);
        return 1;
    }

    // 5. MMA Read/Write Port + Double-Buffered Region Flip & Scrubber Sweep
    // Region 0 (double-buffered, cols 0..63 front, 64..127 back)
    std::array<uint64_t, 8> mma_d{};
    for (int l = 0; l < LANES; ++l) mma_d[l] = 0xDEADBEEF00000000ULL | static_cast<uint64_t>(l + 1);
    auto mwr = drv.do_mma(TMEM_OP_MMA_WR_D, 0x30u, 0, 1, 0, 0, SWIZZLE_32B, 8, false, mma_d, all_be);
    if (mwr.status != TMEM_STATUS_OK) {
        std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: mma_wr status=%u\n", mwr.status);
        return 1;
    }
    auto mrd = drv.do_mma(TMEM_OP_MMA_RD_A, 0x31u, 0, 1, 0, 0, SWIZZLE_32B, 8, false, {}, {});
    if (mrd.status != TMEM_STATUS_OK || mrd.data[0] != mma_d[0]) {
        std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: mma_rd_a st=%u got=%s exp=%s\n",
                     mrd.status, hex64(mrd.data[0]).c_str(), hex64(mma_d[0]).c_str());
        return 1;
    }

    // 5.5 Double-buffered region Buffer B (buf_b_col_offset) Store & Load bounds check
    {
        std::array<uint64_t, 8> pat_b{};
        for (int l = 0; l < LANES; ++l) {
            pat_b[l] = 0xBEEF000012340000ULL | static_cast<uint64_t>(0x100u + l);
        }
        // r0: col_offset=0, num_columns=64, double_buf_en=1 -> Buffer B at col=64..127
        drv.do_store(0x28u, 0, 1, 2, 64 /* Buffer B */, 1, 8, false, true, pat_b, all_be, TMEM_STATUS_OK);
        drv.do_fence(0x29u, 0, 1, true);
        auto ld_b = drv.do_load(0x2Au, 0, 1, 2, 64 /* Buffer B */, 1, 8, 2, false, false, 0, 0);
        if (ld_b.status != TMEM_STATUS_OK ||
            (ld_b.data[0] & 0xFFFFFFFFULL) != (pat_b[0] & 0xFFFFFFFFULL)) {
            std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: Buffer B LD/ST st=%u got=%s exp=%s\n",
                         ld_b.status, hex64(ld_b.data[0]).c_str(), hex64(pat_b[0]).c_str());
            return 1;
        }
    }

    // 5.6 Concurrent LD + ST launch/retire + FENCE tracking
    {
        dut->st_req_valid = 1;
        dut->st_req_tag = 0x35u;
        dut->st_req_region_id = 1;
        dut->st_req_warp_id = 2;
        dut->st_req_row_base = 8;
        dut->st_req_col_base = 128;
        dut->st_req_num_rows = 1;
        dut->st_req_num_cols = 8;
        dut->st_req_col_major = 0;
        dut->st_req_cell32_mode = 1;
        for (int l = 0; l < LANES; ++l) {
            dut->st_req_data[2 * l] = 0xFACE0000u + static_cast<uint32_t>(l);
            dut->st_req_data[2 * l + 1] = 0u;
        }
        dut->st_req_be = ~0ULL;
        dut->st_req_last = 1;

        dut->ld_desc_valid = 1;
        dut->ld_desc_tag = 0x36u;
        dut->ld_desc_region_id = 1;
        dut->ld_desc_warp_id = 2;
        dut->ld_desc_row_base = 5;
        dut->ld_desc_col_base = 128;
        dut->ld_desc_num_rows = 1;
        dut->ld_desc_num_cols = 8;
        dut->ld_desc_elem_bytes = 2;
        dut->ld_desc_col_major = 0;
        dut->ld_desc_subbyte_shift = 0;

        bool st_sent = false, ld_sent = false;
        bool st_acked = false, ld_rsped = false;
        int guard = 0;
        while (!st_acked || !ld_rsped) {
            dut->clk = 0;
            dut->eval();
            if (dut->st_req_valid && dut->st_req_ready) st_sent = true;
            if (dut->ld_desc_valid && dut->ld_desc_ready) ld_sent = true;
            if (dut->st_ack_valid && dut->st_ack_ready) {
                if (dut->st_ack_status != TMEM_STATUS_OK) {
                    std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: conc st status=%u\n", dut->st_ack_status);
                    return 1;
                }
                st_acked = true;
            }
            if (dut->ld_rsp_valid && dut->ld_rsp_ready) {
                if (dut->ld_rsp_status != TMEM_STATUS_OK) {
                    std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: conc ld status=%u\n", dut->ld_rsp_status);
                    return 1;
                }
                ld_rsped = true;
            }
            dut->clk = 1;
            dut->eval();
            if (st_sent) dut->st_req_valid = 0;
            if (ld_sent) dut->ld_desc_valid = 0;
            if (++guard > 500) {
                std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: concurrent LD+ST timeout (st_sent=%d ld_sent=%d st_ack=%d ld_rsp=%d)\n",
                             st_sent, ld_sent, st_acked, ld_rsped);
                return 1;
            }
        }
        // Now FENCE on region 1/warp 2 must complete cleanly (zero leaked outstanding counts!)
        drv.do_fence(0x37u, 1, 2, true);
    }

    // 5.7 Patrol scrub CE followed immediately by same-address overwrite
    {
        std::array<uint64_t, 8> old_pat{}, new_pat{};
        for (int l = 0; l < LANES; ++l) {
            old_pat[l] = 0x1111000000001111ULL + static_cast<uint64_t>(l);
            new_pat[l] = 0x9999888877776666ULL + static_cast<uint64_t>(l);
        }
        uint8_t b_scrub = tmem_swizzled_bank(0, 128, SWIZZLE_128B);
        drv.set_ecc_inj(true, b_scrub, (1ULL << 5), 0u);
        drv.do_store(0x38u, 1, 2, 0, 128, 1, 8, false, false, old_pat, all_be, TMEM_STATUS_OK);
        drv.set_ecc_inj(false, 0, 0ULL, 0u);

        // Enable patrol scrub and concurrently overwrite row=0, col=128 with new_pat
        dut->scrub_en = 1;
        for (int i = 0; i < 4; ++i) drv.tick();
        drv.do_store(0x39u, 1, 2, 0, 128, 1, 8, false, false, new_pat, all_be, TMEM_STATUS_OK);
        for (int i = 0; i < 8; ++i) drv.tick();
        dut->scrub_en = 0;
        drv.do_fence(0x3Au, 1, 2, true);
        auto ld_new = drv.do_load(0x3Bu, 1, 2, 0, 128, 1, 8, 3, false, false, 0, 0);
        if (ld_new.status != TMEM_STATUS_OK || ld_new.data[0] != new_pat[0]) {
            std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: scrub overwrite race got=%s exp=%s\n",
                         hex64(ld_new.data[0]).c_str(), hex64(new_pat[0]).c_str());
            return 1;
        }
    }

    // 5.7b Stale scrub_wb_addr_q write coincident with new CE on a different word address
    {
        // Region 1 (SWIZZLE_128B, col=128): row=1..2 map to distinct word addresses in the same bank
        // as row=0 after bank swizzle; inject CE at row=1 and row=2, scrub row=1 to completion,
        // then overwrite row=1 while scrubber sweeps row=2 and verify row=2 is healed.
        std::array<uint64_t, 8> ce_pat{}, clean_pat{};
        for (int l = 0; l < LANES; ++l) {
            ce_pat[l]    = 0x2222333344445555ULL + static_cast<uint64_t>(l);
            clean_pat[l] = 0xAAAABBBBCCCCDDDDULL + static_cast<uint64_t>(l);
        }
        uint8_t b_r1 = tmem_swizzled_bank(1, 128, SWIZZLE_128B);
        uint8_t b_r2 = tmem_swizzled_bank(2, 128, SWIZZLE_128B);
        drv.set_ecc_inj(true, b_r1, (1ULL << 7), 0u);
        drv.do_store(0x3Cu, 1, 2, 1, 128, 1, 8, false, false, ce_pat, all_be, TMEM_STATUS_OK);
        drv.set_ecc_inj(true, b_r2, (1ULL << 9), 0u);
        drv.do_store(0x3Du, 1, 2, 2, 128, 1, 8, false, false, ce_pat, all_be, TMEM_STATUS_OK);
        drv.set_ecc_inj(false, 0, 0ULL, 0u);
        drv.do_fence(0x3Eu, 1, 2, true);

        dut->scrub_en = 1;
        for (int i = 0; i < 64; ++i) {
            drv.tick();
            if ((i % 4) == 0) {
                drv.do_store(0x3Fu, 1, 2, 1, 128, 1, 8, false, false, clean_pat, all_be, TMEM_STATUS_OK);
            }
        }
        dut->scrub_en = 0;
        drv.do_fence(0x40u, 1, 2, true);
        auto ld_healed = drv.do_load(0x41u, 1, 2, 2, 128, 1, 8, 3, false, false, 0, 0);
        if (ld_healed.status != TMEM_STATUS_OK || ld_healed.data[0] != ce_pat[0]) {
            std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: stale scrub race corrupted row=2 got=%s exp=%s\n",
                         hex64(ld_healed.data[0]).c_str(), hex64(ce_pat[0]).c_str());
            return 1;
        }
    }

    // 5.8 Conflict cycles non-inflation check while arbiter is idle
    {
        uint32_t c0 = dut->perf_cnt_out[3]; // conflict_cycles field
        for (int i = 0; i < 32; ++i) drv.tick();
        uint32_t c1 = dut->perf_cnt_out[3];
        if (c1 != c0) {
            std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: conflict_cycles inflated while idle (%u -> %u)\n", c0, c1);
            return 1;
        }
    }

    // Flip buffer on region 0 and verify clean dealloc
    drv.do_alloc_cmd(ALLOC_CMD_FLIP_BUF, false, false, true, r0, "flip_r0");
    drv.do_alloc_cmd(ALLOC_CMD_DEALLOC, false, false, true, r0, "dealloc_r0");
    drv.do_alloc_cmd(ALLOC_CMD_DEALLOC, false, false, true, r1, "dealloc_r1");

    // Enable patrol ECC scrubber for 64 cycles and verify zero deadlock/hang
    drv.dut()->scrub_en = 1;
    for (int i = 0; i < 64; ++i) drv.tick();
    drv.dut()->scrub_en = 0;

    if (drv.dut()->ecc_ce_count_out == 0 || drv.dut()->ecc_ue_count_out == 0) {
        std::fprintf(stderr, "[tb_tmem_subsystem] FAIL: expected non-zero ECC CE/UE telemetry (ce=%u ue=%u)\n",
                     drv.dut()->ecc_ce_count_out, drv.dut()->ecc_ue_count_out);
        return 1;
    }

    std::printf("[tb_tmem_subsystem] PASS: checks=%llu cycles=%llu ce=%u ue=%u\n",
                static_cast<unsigned long long>(drv.checks()),
                static_cast<unsigned long long>(drv.cycles()),
                drv.dut()->ecc_ce_count_out,
                drv.dut()->ecc_ue_count_out);
    return 0;
}
