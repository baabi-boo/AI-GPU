// SPDX-License-Identifier: Apache-2.0
#include "VVX_tcu_v2_fp4_fp6_fedp_unit.h"
#include "tcu_v2_golden_ref.h"
#include <verilated.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <memory>
#include <random>
#include <string>
#include <vector>

double sc_time_stamp() { return 0.0; }

namespace {

using namespace tcu_v2_ref;

constexpr int LANES = 8;

struct Fp46Vector {
    Fmt fmt_a = FMT_MXFP4_E2M1;
    Fmt fmt_b = FMT_MXFP4_E2M1;
    ScaleFmt scale_fmt = SCALE_UE8M0;
    RoundMode rm = RM_RNE;
    std::vector<uint8_t> a;
    std::vector<uint8_t> b;
    uint8_t scale_a = 0x7Fu;
    uint8_t scale_b = 0x7Fu;
    uint32_t c_fp32 = 0u;
    bool accum_en = true;
    std::string tag;
};

class Fp46Driver {
public:
    explicit Fp46Driver(VVX_tcu_v2_fp4_fp6_fedp_unit* dut) : dut_(dut) {}

    void reset() {
        dut_->reset = 1;
        dut_->valid_in = 0;
        dut_->ready_out = 1;
        dut_->fmt_a = FMT_MXFP4_E2M1;
        dut_->fmt_b = FMT_MXFP4_E2M1;
        dut_->scale_fmt = SCALE_NONE;
        dut_->rm = RM_RNE;
        dut_->a_raw = 0;
        dut_->b_raw = 0;
        dut_->scale_a_raw = 0;
        dut_->scale_b_raw = 0;
        dut_->c_fp32 = 0;
        dut_->accum_en = 0;
        for (int i = 0; i < 6; ++i) tick();
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

    uint64_t pack_lanes(const std::vector<uint8_t>& v) {
        uint64_t packed = 0;
        for (int i = 0; i < LANES; ++i) {
            uint64_t b = (i < static_cast<int>(v.size())) ? v[i] : 0u;
            packed |= (b & 0xFFULL) << (i * 8);
        }
        return packed;
    }

    void drive_and_check_stream(const std::vector<Fp46Vector>& vecs, bool inject_stall, uint32_t seed) {
        std::mt19937 rng(seed);
        std::deque<std::pair<Fp46Vector, FedpResult>> expected_q;
        size_t idx = 0;
        int idle_guard = 0;

        while (idx < vecs.size() || !expected_q.empty()) {
            bool stall_out = inject_stall && ((rng() % 5u) == 0u);
            dut_->ready_out = stall_out ? 0 : 1;

            bool offer_in = (idx < vecs.size()) && (!inject_stall || ((rng() % 4u) != 0u));
            if (offer_in) {
                const auto& v = vecs[idx];
                dut_->valid_in = 1;
                dut_->fmt_a = v.fmt_a;
                dut_->fmt_b = v.fmt_b;
                dut_->scale_fmt = v.scale_fmt;
                dut_->rm = v.rm;
                dut_->a_raw = pack_lanes(v.a);
                dut_->b_raw = pack_lanes(v.b);
                dut_->scale_a_raw = v.scale_a;
                dut_->scale_b_raw = v.scale_b;
                dut_->c_fp32 = v.c_fp32;
                dut_->accum_en = v.accum_en ? 1 : 0;
            } else {
                dut_->valid_in = 0;
            }

            dut_->clk = 0;
            dut_->eval();

            bool fire_in = dut_->valid_in && dut_->ready_in;
            bool fire_out = dut_->valid_out && dut_->ready_out;

            if (fire_in) {
                const auto& v = vecs[idx];
                FedpResult exp = ref_fp4_fp6_fedp(v.fmt_a, v.fmt_b, v.scale_fmt, v.rm,
                                                  v.a, v.b, v.scale_a, v.scale_b,
                                                  v.c_fp32, v.accum_en);
                expected_q.emplace_back(v, exp);
                ++idx;
                idle_guard = 0;
            }

            if (fire_out) {
                if (expected_q.empty()) {
                    std::fprintf(stderr, "[tb_fp4_fp6_fedp] FAIL: spurious valid_out at cycle %llu\n",
                                 static_cast<unsigned long long>(cycles_));
                    std::exit(1);
                }
                auto [v, exp] = expected_q.front();
                expected_q.pop_front();
                uint32_t got_d = dut_->d_fp32;
                FpFlags got_f = FpFlags::unpack(static_cast<uint8_t>(dut_->flags_out & 0x1Fu));
                check_result(v, exp, got_d, got_f);
                ++checked_;
                idle_guard = 0;
            }

            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            ++idle_guard;
            if (idle_guard > 2000) {
                std::fprintf(stderr, "[tb_fp4_fp6_fedp] FAIL: pipeline deadlock at idx=%zu pending=%zu\n",
                             idx, expected_q.size());
                std::exit(1);
            }
        }
        dut_->valid_in = 0;
        dut_->ready_out = 1;
        tick();
    }

    uint64_t checked() const { return checked_; }
    uint64_t cycles() const { return cycles_; }
    uint64_t mismatches() const { return mismatches_; }

private:
    void check_result(const Fp46Vector& v, const FedpResult& exp, uint32_t got_d, FpFlags got_f) {
        bool d_match = (got_d == exp.d_bits) || (fp32_is_nan(got_d) && fp32_is_nan(exp.d_bits));
        if (!d_match || !(got_f == exp.flags)) {
            std::fprintf(stderr,
                         "[tb_fp4_fp6_fedp] MISMATCH tag=%s fmtA=%u fmtB=%u sfmt=%u rm=%u "
                         "sa=0x%02x sb=0x%02x c=%s acc=%d | got_d=%s exp_d=%s | got_f=0x%02x exp_f=0x%02x\n",
                         v.tag.c_str(), v.fmt_a, v.fmt_b, v.scale_fmt, v.rm,
                         v.scale_a, v.scale_b, hex32(v.c_fp32).c_str(), v.accum_en ? 1 : 0,
                         hex32(got_d).c_str(), hex32(exp.d_bits).c_str(),
                         got_f.pack(), exp.flags.pack());
            ++mismatches_;
            std::exit(1);
        }
    }

    VVX_tcu_v2_fp4_fp6_fedp_unit* dut_;
    uint64_t cycles_ = 0;
    uint64_t checked_ = 0;
    uint64_t mismatches_ = 0;
};

std::vector<Fp46Vector> build_exhaustive_fp4_pairs() {
    std::vector<Fp46Vector> out;
    // Exhaustive 16x16 FP4 nibble pair coverage packed across 8 lanes (32 vectors cover all 256 pairs)
    for (int base = 0; base < 256; base += LANES) {
        Fp46Vector v;
        v.fmt_a = FMT_MXFP4_E2M1;
        v.fmt_b = FMT_MXFP4_E2M1;
        v.scale_fmt = SCALE_UE8M0;
        v.rm = RM_RNE;
        v.scale_a = 0x7Fu;
        v.scale_b = 0x7Fu;
        v.c_fp32 = FP32_POS_ZERO;
        v.accum_en = false;
        v.a.resize(LANES);
        v.b.resize(LANES);
        for (int l = 0; l < LANES; ++l) {
            int p = base + l;
            v.a[l] = static_cast<uint8_t>((p >> 4) & 0xFu);
            v.b[l] = static_cast<uint8_t>(p & 0xFu);
        }
        v.tag = "fp4_pair_" + std::to_string(base);
        out.push_back(v);
    }
    // Single-lane isolation over all 16 FP4 encodings with positive and negative signs
    for (uint8_t na = 0; na < 16; ++na) {
        for (uint8_t nb = 0; nb < 16; ++nb) {
            Fp46Vector v;
            v.fmt_a = FMT_NVFP4_E2M1;
            v.fmt_b = FMT_NVFP4_E2M1;
            v.scale_fmt = SCALE_E4M3;
            v.rm = RM_RNE;
            v.scale_a = 0x38u; // 1.0 in E4M3
            v.scale_b = 0x38u;
            v.c_fp32 = 0x3F800000u; // 1.0f
            v.accum_en = true;
            v.a.assign(LANES, 0u);
            v.b.assign(LANES, 0u);
            v.a[0] = na;
            v.b[0] = nb;
            v.tag = "nvfp4_single_" + std::to_string(na) + "_" + std::to_string(nb);
            out.push_back(v);
        }
    }
    return out;
}

std::vector<Fp46Vector> build_fp6_and_mixed_vectors(std::mt19937& rng) {
    std::vector<Fp46Vector> out;
    const std::array<std::pair<Fmt, Fmt>, 7> combos = {{
        {FMT_MXFP6_E2M3, FMT_MXFP6_E2M3},
        {FMT_MXFP6_E3M2, FMT_MXFP6_E3M2},
        {FMT_MXFP6_E2M3, FMT_MXFP6_E3M2},
        {FMT_MXFP6_E3M2, FMT_MXFP6_E2M3},
        {FMT_MXFP4_E2M1, FMT_MXFP6_E2M3},
        {FMT_MXFP6_E3M2, FMT_MXFP4_E2M1},
        {FMT_NVFP4_E2M1, FMT_MXFP6_E2M3}
    }};

    for (const auto& [fa, fb] : combos) {
        // Subnormal + max finite + zero cancellation tests
        for (int s = 0; s < 16; ++s) {
            Fp46Vector v;
            v.fmt_a = fa;
            v.fmt_b = fb;
            v.scale_fmt = (fa == FMT_NVFP4_E2M1 || fb == FMT_NVFP4_E2M1) ? SCALE_E4M3 : SCALE_UE8M0;
            v.rm = static_cast<RoundMode>(s % 5);
            v.scale_a = (v.scale_fmt == SCALE_E4M3) ? static_cast<uint8_t>(0x30u + (s % 12)) : static_cast<uint8_t>(0x7Bu + (s % 9));
            v.scale_b = (v.scale_fmt == SCALE_E4M3) ? static_cast<uint8_t>(0x38u + (s % 8)) : static_cast<uint8_t>(0x7Eu + (s % 6));
            v.accum_en = (s % 2) == 0;
            v.c_fp32 = (s % 3 == 0) ? 0xC0400000u : ((s % 3 == 1) ? 0x3E800000u : 0x00000000u);
            v.a.resize(LANES);
            v.b.resize(LANES);
            for (int l = 0; l < LANES; ++l) {
                if (s == 0) {
                    v.a[l] = fmt_is_fp4(fa) ? ((l & 1) ? 0x9u : 0x1u) : ((l & 1) ? 0x21u : 0x01u); // min subnorm alt sign
                    v.b[l] = fmt_is_fp4(fb) ? 0x1u : 0x01u;
                } else if (s == 1) {
                    v.a[l] = fmt_is_fp4(fa) ? 0x7u : 0x1Fu; // max positive
                    v.b[l] = fmt_is_fp4(fb) ? 0x7u : 0x1Fu;
                } else if (s == 2) {
                    v.a[l] = fmt_is_fp4(fa) ? 0x8u : 0x20u; // -0.0
                    v.b[l] = fmt_is_fp4(fb) ? 0x8u : 0x20u; // -0.0
                } else {
                    v.a[l] = static_cast<uint8_t>(rng() & (fmt_is_fp4(fa) ? 0xFu : 0x3Fu));
                    v.b[l] = static_cast<uint8_t>(rng() & (fmt_is_fp4(fb) ? 0xFu : 0x3Fu));
                }
            }
            v.tag = "mixed_" + std::to_string(fa) + "_" + std::to_string(fb) + "_" + std::to_string(s);
            out.push_back(v);
        }
    }
    return out;
}

std::vector<Fp46Vector> build_scale_and_edge_vectors() {
    std::vector<Fp46Vector> out;

    // 1. Scale NaN, zero, subnormal E4M3, max UE8M0, min UE8M0
    const std::vector<std::tuple<ScaleFmt, uint8_t, uint8_t, uint32_t, std::string>> scale_cases = {
        {SCALE_UE8M0, 0xFFu, 0x7Fu, 0u, "ue8m0_nan_a"},
        {SCALE_UE8M0, 0x7Fu, 0xFFu, 0u, "ue8m0_nan_b"},
        {SCALE_UE8M0, 0x00u, 0x00u, 0x3F800000u, "ue8m0_min_uf"},
        {SCALE_UE8M0, 0xFEu, 0xFEu, 0x00000000u, "ue8m0_max_ovf"},
        {SCALE_UE8M0, 0xFEu, 0x7Fu, 0x7F800000u, "ue8m0_c_pos_inf"},
        {SCALE_UE8M0, 0xFEu, 0x7Fu, 0xFF800000u, "ue8m0_c_neg_inf"},
        {SCALE_E4M3,  0x00u, 0x38u, 0x80000000u, "e4m3_scale_zero_a"},
        {SCALE_E4M3,  0x38u, 0x00u, 0x00000000u, "e4m3_scale_zero_b"},
        {SCALE_E4M3,  0x01u, 0x01u, 0x00000000u, "e4m3_scale_both_subnorm"},
        {SCALE_E4M3,  0x7Eu, 0x7Eu, 0x00000000u, "e4m3_scale_max_finite"},
        {SCALE_E4M3,  0x7Fu, 0x38u, 0x00000000u, "e4m3_scale_nan"},
        {SCALE_E4M3,  0x80u, 0x38u, 0x00000000u, "e4m3_scale_neg_invalid"},
        {SCALE_NONE,  0x00u, 0x00u, 0x7FC00000u, "c_qnan"},
        {SCALE_NONE,  0x00u, 0x00u, 0x7F800001u, "c_snan"}
    };

    for (const auto& [sfmt, sa, sb, cval, name] : scale_cases) {
        for (int rmi = 0; rmi < 5; ++rmi) {
            Fp46Vector v;
            v.fmt_a = (sfmt == SCALE_E4M3) ? FMT_NVFP4_E2M1 : FMT_MXFP4_E2M1;
            v.fmt_b = FMT_MXFP6_E2M3;
            v.scale_fmt = sfmt;
            v.rm = static_cast<RoundMode>(rmi);
            v.scale_a = sa;
            v.scale_b = sb;
            v.c_fp32 = cval;
            v.accum_en = true;
            v.a = {0x07u, 0x03u, 0x0Fu, 0x02u, 0x05u, 0x0Au, 0x01u, 0x00u};
            v.b = {0x1Fu, 0x18u, 0x3Fu, 0x08u, 0x10u, 0x28u, 0x01u, 0x00u};
            v.tag = name + "_rm" + std::to_string(rmi);
            out.push_back(v);
        }
    }

    // 2. Massive cancellation & subnormal C tests across all 5 rounding modes
    const std::array<uint32_t, 6> cancel_c = {
        0xC2400000u, // -48.0f
        0x42400000u, // +48.0f
        0x00000001u, // smallest FP32 subnormal
        0x80000001u, // negative smallest FP32 subnormal
        0x3F800000u, // 1.0f
        0x80000000u  // -0.0f
    };
    for (size_t ci = 0; ci < cancel_c.size(); ++ci) {
        for (int rmi = 0; rmi < 5; ++rmi) {
            Fp46Vector v;
            v.fmt_a = FMT_MXFP4_E2M1;
            v.fmt_b = FMT_MXFP4_E2M1;
            v.scale_fmt = SCALE_UE8M0;
            v.rm = static_cast<RoundMode>(rmi);
            v.scale_a = 0x7Fu;
            v.scale_b = 0x7Fu;
            v.c_fp32 = cancel_c[ci];
            v.accum_en = true;
            v.a = {0x06u, 0x06u, 0x06u, 0x06u, 0x0Eu, 0x0Eu, 0x0Eu, 0x0Eu}; // +4,+4,+4,+4,-4,-4,-4,-4
            v.b = {0x04u, 0x04u, 0x04u, 0x04u, 0x04u, 0x04u, 0x04u, 0x04u}; // 2.0 * all -> sum = 0
            v.tag = "cancel_c" + std::to_string(ci) + "_rm" + std::to_string(rmi);
            out.push_back(v);
        }
    }

    // 3. Signed-zero propagation (-0.0 across all lanes and C)
    for (int acc = 0; acc <= 1; ++acc) {
        for (int rmi = 0; rmi < 5; ++rmi) {
            Fp46Vector v;
            v.fmt_a = FMT_MXFP6_E3M2;
            v.fmt_b = FMT_MXFP6_E3M2;
            v.scale_fmt = SCALE_NONE;
            v.rm = static_cast<RoundMode>(rmi);
            v.scale_a = 0x7Fu;
            v.scale_b = 0x7Fu;
            v.c_fp32 = FP32_NEG_ZERO;
            v.accum_en = (acc == 1);
            v.a.assign(LANES, 0x20u); // -0.0
            v.b.assign(LANES, 0x00u); // +0.0 -> product -0.0
            v.tag = "neg_zero_acc" + std::to_string(acc) + "_rm" + std::to_string(rmi);
            out.push_back(v);
        }
    }

    // 4. Mixed +0.0/-0.0 signed-zero arbitration in RM_RDN vs all +0.0
    for (int acc = 0; acc <= 1; ++acc) {
        Fp46Vector v_mix;
        v_mix.fmt_a = FMT_MXFP4_E2M1;
        v_mix.fmt_b = FMT_MXFP4_E2M1;
        v_mix.scale_fmt = SCALE_UE8M0;
        v_mix.rm = RM_RDN;
        v_mix.scale_a = 0x7Fu;
        v_mix.scale_b = 0x7Fu;
        v_mix.c_fp32 = FP32_POS_ZERO;
        v_mix.accum_en = (acc == 1);
        v_mix.a.assign(LANES, 0x00u);
        v_mix.b.assign(LANES, 0x00u);
        v_mix.b[0] = 0x08u; // lane 0 = +0.0 * -0.0 = -0.0, lanes 1..7 = +0.0
        v_mix.tag = "mixed_zero_rdn_acc" + std::to_string(acc);
        out.push_back(v_mix);

        Fp46Vector v_pos = v_mix;
        v_pos.b[0] = 0x00u; // all +0.0
        v_pos.tag = "all_pos_zero_rdn_acc" + std::to_string(acc);
        out.push_back(v_pos);
    }

    // 5. Opposite-sign overshifted sticky borrow (1.0 - 2^-149, -1.0 + 2^-60)
    for (RoundMode rmode : {RM_RNE, RM_RTZ, RM_RDN, RM_RUP, RM_RMM}) {
        Fp46Vector v1;
        v1.fmt_a = FMT_MXFP4_E2M1;
        v1.fmt_b = FMT_MXFP4_E2M1;
        v1.scale_fmt = SCALE_UE8M0;
        v1.rm = rmode;
        v1.scale_a = 0x7Fu;
        v1.scale_b = 0x7Fu;
        v1.a.assign(LANES, 0x00u);
        v1.b.assign(LANES, 0x00u);
        v1.a[0] = 0x02u; // +1.0
        v1.b[0] = 0x02u; // +1.0
        v1.c_fp32 = 0x80000001u; // -2^-149
        v1.accum_en = true;
        v1.tag = "opp_sticky_1m2e_149_rm" + std::to_string(rmode);
        out.push_back(v1);

        Fp46Vector v2;
        v2.fmt_a = FMT_MXFP4_E2M1;
        v2.fmt_b = FMT_MXFP4_E2M1;
        v2.scale_fmt = SCALE_UE8M0;
        v2.rm = rmode;
        v2.scale_a = 0x43u; // 2^-60
        v2.scale_b = 0x7Fu;
        v2.a.assign(LANES, 0x00u);
        v2.b.assign(LANES, 0x00u);
        v2.a[0] = 0x02u;
        v2.b[0] = 0x02u;
        v2.c_fp32 = 0xBF800000u; // -1.0
        v2.accum_en = true;
        v2.tag = "opp_sticky_m1p2e_60_rm" + std::to_string(rmode);
        out.push_back(v2);
    }

    // 6. Large-scale lane cancellation preserving C=1.0 (+2^194 - 2^194 + 1.0)
    {
        Fp46Vector v;
        v.fmt_a = FMT_MXFP4_E2M1;
        v.fmt_b = FMT_MXFP4_E2M1;
        v.scale_fmt = SCALE_UE8M0;
        v.rm = RM_RNE;
        v.scale_a = 0xE0u; // +97
        v.scale_b = 0xE0u; // +97 -> +2^194
        v.a.assign(LANES, 0x00u);
        v.b.assign(LANES, 0x00u);
        v.a[0] = 0x02u; v.b[0] = 0x02u; // +2^194
        v.a[1] = 0x0Au; v.b[1] = 0x02u; // -2^194
        v.c_fp32 = 0x3F800000u; // +1.0
        v.accum_en = true;
        v.tag = "large_lane_cancel_preserve_c";
        out.push_back(v);
    }

    return out;
}

std::vector<Fp46Vector> build_randomized_vectors(std::mt19937& rng, int count) {
    std::vector<Fp46Vector> out;
    out.reserve(count);
    const std::array<Fmt, 4> fmts = {FMT_MXFP4_E2M1, FMT_NVFP4_E2M1, FMT_MXFP6_E2M3, FMT_MXFP6_E3M2};
    const std::array<uint32_t, 8> interesting_c = {
        0x00000000u, 0x80000000u, 0x3F800000u, 0xBF800000u,
        0x00400000u, 0x7F7FFFFFu, 0x3E800000u, 0xC1200000u
    };
    for (int i = 0; i < count; ++i) {
        Fp46Vector v;
        v.fmt_a = fmts[rng() % fmts.size()];
        v.fmt_b = fmts[rng() % fmts.size()];
        uint32_t sm = rng() % 3u;
        v.scale_fmt = (sm == 0) ? SCALE_NONE : ((sm == 1) ? SCALE_UE8M0 : SCALE_E4M3);
        v.rm = static_cast<RoundMode>(rng() % 5u);
        v.scale_a = (v.scale_fmt == SCALE_E4M3)
                        ? static_cast<uint8_t>(rng() & 0x7Fu)
                        : static_cast<uint8_t>(0x70u + (rng() % 32u));
        v.scale_b = (v.scale_fmt == SCALE_E4M3)
                        ? static_cast<uint8_t>(rng() & 0x7Fu)
                        : static_cast<uint8_t>(0x70u + (rng() % 32u));
        if (v.scale_a == 0x7Fu && v.scale_fmt == SCALE_E4M3) v.scale_a = 0x38u;
        if (v.scale_b == 0x7Fu && v.scale_fmt == SCALE_E4M3) v.scale_b = 0x38u;
        v.accum_en = (rng() & 1u) != 0u;
        v.c_fp32 = (rng() % 4u == 0u) ? interesting_c[rng() % interesting_c.size()]
                                      : static_cast<uint32_t>(rng());
        if (fp32_is_nan(v.c_fp32) && (rng() % 4u != 0u)) {
            v.c_fp32 = 0x3F000000u;
        }
        v.a.resize(LANES);
        v.b.resize(LANES);
        for (int l = 0; l < LANES; ++l) {
            v.a[l] = static_cast<uint8_t>(rng() & (fmt_is_fp4(v.fmt_a) ? 0xFu : 0x3Fu));
            v.b[l] = static_cast<uint8_t>(rng() & (fmt_is_fp4(v.fmt_b) ? 0xFu : 0x3Fu));
        }
        v.tag = "rand_" + std::to_string(i);
        out.push_back(v);
    }
    return out;
}

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tcu_v2_fp4_fp6_fedp_unit>();
    Fp46Driver drv(dut.get());
    drv.reset();

    std::mt19937 rng(0xB2F4F601u);

    auto v_fp4 = build_exhaustive_fp4_pairs();
    drv.drive_and_check_stream(v_fp4, false, 101);

    auto v_mix = build_fp6_and_mixed_vectors(rng);
    drv.drive_and_check_stream(v_mix, true, 202);

    auto v_edge = build_scale_and_edge_vectors();
    drv.drive_and_check_stream(v_edge, true, 303);

    auto v_rand = build_randomized_vectors(rng, 1500);
    drv.drive_and_check_stream(v_rand, true, 404);

    // Mid-flight reset recovery verification
    drv.reset();
    auto v_post = build_fp6_and_mixed_vectors(rng);
    drv.drive_and_check_stream(v_post, false, 505);

    if (drv.mismatches() != 0) {
        return 1;
    }
    std::printf("[tb_fp4_fp6_fedp] PASS: checked=%llu vectors in %llu cycles\n",
                static_cast<unsigned long long>(drv.checked()),
                static_cast<unsigned long long>(drv.cycles()));
    return 0;
}
