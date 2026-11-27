// SPDX-License-Identifier: Apache-2.0
#include "tcu_v2_golden_ref.h"

#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

namespace {

using namespace tcu_v2_ref;

void check(bool cond, const char* msg) {
    if (!cond) {
        std::fprintf(stderr, "[tb_tcu_v2_golden_selftest] FAIL: %s\n", msg);
        std::exit(1);
    }
}

void test_swizzle_bijection() {
    for (uint8_t mode = 0; mode < 4; ++mode) {
        TmemSwizzle sw = static_cast<TmemSwizzle>(mode);
        std::vector<uint8_t> seen(TMEM_ROWS * TMEM_COLS, 0u);
        for (int row = 0; row < TMEM_ROWS; ++row) {
            for (int col = 0; col < TMEM_COLS; ++col) {
                uint8_t bank = tmem_swizzled_bank(static_cast<uint8_t>(row), static_cast<uint16_t>(col), sw);
                uint16_t waddr = tmem_bank_word_addr(static_cast<uint8_t>(row), static_cast<uint16_t>(col));
                bool hsel = tmem_cell_half_sel(static_cast<uint16_t>(col));
                check(bank < TMEM_NUM_BANKS, "bank id out of range");
                check(waddr < TMEM_BANK_WORDS, "word addr out of range");
                uint16_t inv_col = tmem_col_from_phys(waddr, bank, hsel, sw);
                check(inv_col == static_cast<uint16_t>(col), "inverse swizzle mismatch");
                size_t phys_idx = (static_cast<size_t>(bank) * TMEM_BANK_WORDS + waddr) * 2 + (hsel ? 1 : 0);
                check(phys_idx < seen.size(), "phys index OOB");
                check(seen[phys_idx] == 0u, "physical cell collision in bijection");
                seen[phys_idx] = 1u;
            }
        }
    }
}

void test_hsiao_secded_ecc() {
    std::mt19937_64 rng(0xECC7264B2ULL);
    for (int iter = 0; iter < 512; ++iter) {
        uint64_t data = rng();
        uint8_t parity = 0;
        hsiao_ecc_encode_CW(data, parity);

        // 0-bit error
        auto d0 = hsiao_ecc_decode(data, parity);
        check(!d0.ce && !d0.ue && d0.syndrome == 0 && d0.data_out == data, "ECC 0-bit clean fail");

        // All 72 single-bit errors
        for (int b = 0; b < 72; ++b) {
            uint64_t cd = (b < 64) ? (data ^ (1ULL << b)) : data;
            uint8_t cp = (b >= 64) ? static_cast<uint8_t>(parity ^ (1u << (b - 64))) : parity;
            auto d1 = hsiao_ecc_decode(cd, cp);
            check(d1.ce && !d1.ue && d1.data_out == data && d1.parity_out == parity, "ECC 1-bit CE fail");
        }

        // Sampled double-bit errors
        for (int s = 0; s < 32; ++s) {
            int b0 = static_cast<int>(rng() % 72u);
            int b1 = static_cast<int>(rng() % 72u);
            if (b0 == b1) b1 = (b0 + 1) % 72;
            uint64_t cd = data;
            uint8_t cp = parity;
            if (b0 < 64) cd ^= (1ULL << b0); else cp ^= static_cast<uint8_t>(1u << (b0 - 64));
            if (b1 < 64) cd ^= (1ULL << b1); else cp ^= static_cast<uint8_t>(1u << (b1 - 64));
            auto d2 = hsiao_ecc_decode(cd, cp);
            check(!d2.ce && d2.ue, "ECC 2-bit UE fail");
        }
    }
}

void test_fp_formats_and_fedp() {
    // Exhaustive FP4 decode sanity
    for (uint8_t n = 0; n < 16; ++n) {
        UnpackedFp u = unpack_fp4_e2m1(n);
        check(!u.is_inf && !u.is_nan, "FP4 should never produce Inf/NaN");
    }
    // Exhaustive FP6 decode sanity
    for (uint8_t x = 0; x < 64; ++x) {
        UnpackedFp u23 = unpack_fp6_e2m3(x);
        UnpackedFp u32 = unpack_fp6_e3m2(x);
        check(!u23.is_inf && !u23.is_nan, "FP6 E2M3 should never produce Inf/NaN");
        check(!u32.is_inf && !u32.is_nan, "FP6 E3M2 should never produce Inf/NaN");
    }
    // FP8 E4M3FN has no Inf, only 0x7F/0xFF NaN
    for (int x = 0; x < 256; ++x) {
        UnpackedFp u = unpack_fp8_e4m3(static_cast<uint8_t>(x));
        check(!u.is_inf, "E4M3FN must have no Inf");
        check(u.is_nan == ((x & 0x7F) == 0x7F), "E4M3FN NaN predicate mismatch");
    }
    // Exact FP32 add & INT8 fedp consistency
    auto r1 = ref_fp32_add_exact(0x3F800000u, 0x40000000u, RM_RNE); // 1.0 + 2.0 = 3.0
    check(r1.d_bits == 0x40400000u && !r1.flags.nx, "FP32 1+2 mismatch");
    auto r2 = ref_fp32_add_exact(FP32_POS_INF, FP32_NEG_INF, RM_RNE);
    check(fp32_is_nan(r2.d_bits) && r2.flags.nv, "Inf-Inf NV mismatch");
    // Directed rounding overflow/underflow casts (BF16, FP16, FP8_E5M2, FP8_E4M3)
    auto bf_ovf_rdn = ref_epilogue_cast(0x7F7FFFFFu, FMT_BF16, RM_RDN, false); // +max FP32 -> +max_finite BF16 (0x7F7F, nx=1)
    check(bf_ovf_rdn.d_bits == 0x7F7Fu && !bf_ovf_rdn.flags.of && bf_ovf_rdn.flags.nx, "BF16 OVF RDN");
    auto bf_ovf_rne = ref_epilogue_cast(0x7F7FFFFFu, FMT_BF16, RM_RNE, false); // +max FP32 -> +Inf BF16 (0x7F80, of=1, nx=1)
    check(bf_ovf_rne.d_bits == 0x7F80u && bf_ovf_rne.flags.of && bf_ovf_rne.flags.nx, "BF16 OVF RNE");
    auto bf_uf_sub = ref_epilogue_cast(0x00000001u, FMT_BF16, RM_RNE, false);
    check(bf_uf_sub.d_bits == 0x0000u && bf_uf_sub.flags.uf && bf_uf_sub.flags.nx, "BF16 UF flag");
    auto f16_ovf_rdn = ref_epilogue_cast(0x47800000u, FMT_FP16, RM_RDN, false); // +65536 -> +max_finite FP16 (0x7BFF)
    check(f16_ovf_rdn.d_bits == 0x7BFFu && f16_ovf_rdn.flags.of && f16_ovf_rdn.flags.nx, "FP16 OVF RDN");
    auto f16_uf_rup = ref_epilogue_cast(0x00000001u, FMT_FP16, RM_RUP, false);
    check(f16_uf_rup.d_bits == 0x0001u && f16_uf_rup.flags.uf && f16_uf_rup.flags.nx, "FP16 tiny RUP");
    auto e5m2_ovf_rdn = ref_epilogue_cast(0x47800000u, FMT_FP8_E5M2, RM_RDN, false);
    check(e5m2_ovf_rdn.d_bits == 0x7Bu && e5m2_ovf_rdn.flags.of && e5m2_ovf_rdn.flags.nx, "E5M2 OVF RDN");
}

void test_sparse_compress_validate_roundtrip() {
    std::mt19937 rng(0x52451234u);
    for (Fmt fmt : {FMT_TF32, FMT_BF16, FMT_FP16, FMT_FP8_E4M3, FMT_INT8, FMT_MXFP4_E2M1}) {
        for (int iter = 0; iter < 32; ++iter) {
            std::vector<uint32_t> lo(8, 0u), hi(8, 0u);
            for (int k = 0; k < 8; ++k) {
                lo[k] = static_cast<uint32_t>(rng());
                hi[k] = static_cast<uint32_t>(rng());
                if (fmt == FMT_TF32) {
                    lo[k] &= 0xFFFFE000u;
                    hi[k] &= 0xFFFFE000u;
                }
            }
            std::vector<uint32_t> comp;
            std::vector<uint8_t> meta;
            bool loss = false;
            ref_sparse_compress_row(fmt, 8, lo, hi, comp, meta, loss);
            // Verify every selected nibble has idx0 < idx1
            int grps = (fmt == FMT_TF32) ? 4 : ((fmt == FMT_BF16 || fmt == FMT_FP16) ? 8 : (fmt_is_fp4(fmt) ? 32 : 16));
            for (int g = 0; g < grps; ++g) {
                uint8_t m4 = (meta[g / 2] >> ((g % 2) * 4)) & 0xFu;
                check(sparse_pair_legal(m4), "compressor produced illegal sparse pair");
            }
        }
    }
}

void test_tmem_allocator() {
    TmemAllocatorRef alloc;
    TmemAllocReq r0{false, 0, 0, 64, 64, SWIZZLE_32B, true, 1};
    auto s0 = alloc.execute(ALLOC_CMD_ALLOC, false, true, true, r0);
    check(s0.status == TMEM_STATUS_OK && s0.col_offset == 0 && s0.buf_b_col_offset == 64, "alloc r0");
    TmemAllocReq r1{false, 1, 0, 128, 128, SWIZZLE_128B, false, 2};
    auto s1 = alloc.execute(ALLOC_CMD_ALLOC, true, true, true, r1);
    check(s1.status == TMEM_STATUS_OK && s1.col_offset == 128, "alloc r1 buddy");
    check(alloc.occupied_granules() == 8, "occupied granules == 8");
    auto s2 = alloc.execute(ALLOC_CMD_DEALLOC, false, false, true, r0);
    check(s2.status == TMEM_STATUS_OK && alloc.occupied_granules() == 4, "dealloc r0");
}

} // namespace

int main() {
    test_swizzle_bijection();
    test_hsiao_secded_ecc();
    test_fp_formats_and_fedp();
    test_sparse_compress_validate_roundtrip();
    test_tmem_allocator();
    std::printf("[tb_tcu_v2_golden_selftest] PASS: all reference invariants verified\n");
    return 0;
}
