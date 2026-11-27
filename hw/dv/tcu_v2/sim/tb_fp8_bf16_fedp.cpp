// SPDX-License-Identifier: Apache-2.0
#include "VVX_tcu_v2_fp8_bf16_fedp_unit.h"
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

struct Fp816Vector {
    Fmt fmt_a = FMT_BF16;
    Fmt fmt_b = FMT_BF16;
    ScaleFmt scale_fmt = SCALE_NONE;
    RoundMode rm = RM_RNE;
    std::vector<uint32_t> a;
    std::vector<uint32_t> b;
    uint8_t scale_a = 0x7Fu;
    uint8_t scale_b = 0x7Fu;
    uint32_t c_in = 0u;
    bool accum_en = true;
    bool int_saturate = false;
    std::string tag;
};

class Fp816Driver {
public:
    explicit Fp816Driver(VVX_tcu_v2_fp8_bf16_fedp_unit* dut) : dut_(dut) {}

    void reset() {
        dut_->reset = 1;
        dut_->valid_in = 0;
        dut_->ready_out = 1;
        dut_->fmt_a = FMT_BF16;
        dut_->fmt_b = FMT_BF16;
        dut_->scale_fmt = SCALE_NONE;
        dut_->rm = RM_RNE;
        wide_zero<8>(dut_->a_raw.data());
        wide_zero<8>(dut_->b_raw.data());
        dut_->scale_a_raw = 0;
        dut_->scale_b_raw = 0;
        dut_->c_in = 0;
        dut_->accum_en = 0;
        dut_->int_saturate = 0;
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

    void drive_stream(const std::vector<Fp816Vector>& vecs, bool inject_stall, uint32_t seed) {
        std::mt19937 rng(seed);
        std::deque<std::pair<Fp816Vector, FedpResult>> expected_q;
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
                for (int l = 0; l < LANES; ++l) {
                    dut_->a_raw[l] = (l < static_cast<int>(v.a.size())) ? v.a[l] : 0u;
                    dut_->b_raw[l] = (l < static_cast<int>(v.b.size())) ? v.b[l] : 0u;
                }
                dut_->scale_a_raw = v.scale_a;
                dut_->scale_b_raw = v.scale_b;
                dut_->c_in = v.c_in;
                dut_->accum_en = v.accum_en ? 1 : 0;
                dut_->int_saturate = v.int_saturate ? 1 : 0;
            } else {
                dut_->valid_in = 0;
            }

            dut_->clk = 0;
            dut_->eval();

            bool fire_in = dut_->valid_in && dut_->ready_in;
            bool fire_out = dut_->valid_out && dut_->ready_out;

            if (fire_in) {
                const auto& v = vecs[idx];
                FedpResult exp = ref_fp8_bf16_fedp(v.fmt_a, v.fmt_b, v.scale_fmt, v.rm,
                                                   v.a, v.b, v.scale_a, v.scale_b,
                                                   v.c_in, v.accum_en, v.int_saturate);
                expected_q.emplace_back(v, exp);
                ++idx;
                idle_guard = 0;
            }

            if (fire_out) {
                if (expected_q.empty()) {
                    std::fprintf(stderr, "[tb_fp8_bf16_fedp] FAIL: spurious valid_out at cycle %llu\n",
                                 static_cast<unsigned long long>(cycles_));
                    std::exit(1);
                }
                auto [v, exp] = expected_q.front();
                expected_q.pop_front();
                uint32_t got_d = dut_->d_out;
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
                std::fprintf(stderr, "[tb_fp8_bf16_fedp] FAIL: pipeline deadlock at idx=%zu pending=%zu\n",
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
    void check_result(const Fp816Vector& v, const FedpResult& exp, uint32_t got_d, FpFlags got_f) {
        bool is_int = (v.fmt_a == FMT_INT8) && (v.fmt_b == FMT_INT8);
        bool d_match = (got_d == exp.d_bits) ||
                       (!is_int && fp32_is_nan(got_d) && fp32_is_nan(exp.d_bits));
        if (!d_match || !(got_f == exp.flags)) {
            std::fprintf(stderr,
                         "[tb_fp8_bf16_fedp] MISMATCH tag=%s fmtA=%u fmtB=%u sfmt=%u rm=%u "
                         "sa=0x%02x sb=0x%02x c=%s acc=%d sat=%d | got_d=%s exp_d=%s | got_f=0x%02x exp_f=0x%02x\n",
                         v.tag.c_str(), v.fmt_a, v.fmt_b, v.scale_fmt, v.rm,
                         v.scale_a, v.scale_b, hex32(v.c_in).c_str(), v.accum_en ? 1 : 0, v.int_saturate ? 1 : 0,
                         hex32(got_d).c_str(), hex32(exp.d_bits).c_str(),
                         got_f.pack(), exp.flags.pack());
            ++mismatches_;
            std::exit(1);
        }
    }

    VVX_tcu_v2_fp8_bf16_fedp_unit* dut_;
    uint64_t cycles_ = 0;
    uint64_t checked_ = 0;
    uint64_t mismatches_ = 0;
};

std::vector<Fp816Vector> build_fp8_vectors(std::mt19937& rng) {
    std::vector<Fp816Vector> out;
    const std::array<std::pair<Fmt, Fmt>, 8> fp8_pairs = {{
        {FMT_FP8_E4M3, FMT_FP8_E4M3},
        {FMT_FP8_E4M3, FMT_FP8_E5M2},
        {FMT_FP8_E5M2, FMT_FP8_E4M3},
        {FMT_FP8_E5M2, FMT_FP8_E5M2},
        {FMT_MXFP8_E4M3, FMT_MXFP8_E4M3},
        {FMT_MXFP8_E4M3, FMT_MXFP8_E5M2},
        {FMT_MXFP8_E5M2, FMT_MXFP8_E4M3},
        {FMT_MXFP8_E5M2, FMT_MXFP8_E5M2}
    }};

    const std::array<uint8_t, 12> e4m3_vals = {
        0x00u, 0x80u, 0x01u, 0x81u, 0x38u, 0xB8u, 0x40u, 0x7Eu, 0xFEu, 0x7Fu, 0xFFu, 0x2Au
    };
    const std::array<uint8_t, 12> e5m2_vals = {
        0x00u, 0x80u, 0x01u, 0x81u, 0x3Cu, 0xBCu, 0x7Bu, 0x7Cu, 0xFCu, 0x7Du, 0x7Eu, 0xFFu
    };

    for (const auto& [fa, fb] : fp8_pairs) {
        bool is_mx = fmt_is_mx(fa);
        const auto& pool_a = (fa == FMT_FP8_E4M3 || fa == FMT_MXFP8_E4M3) ? e4m3_vals : e5m2_vals;
        const auto& pool_b = (fb == FMT_FP8_E4M3 || fb == FMT_MXFP8_E4M3) ? e4m3_vals : e5m2_vals;

        // Sweep interesting corner combinations
        for (size_t i = 0; i < pool_a.size(); ++i) {
            for (int rmi = 0; rmi < 5; ++rmi) {
                Fp816Vector v;
                v.fmt_a = fa;
                v.fmt_b = fb;
                v.scale_fmt = is_mx ? ((i & 1) ? SCALE_E4M3 : SCALE_UE8M0) : SCALE_NONE;
                v.rm = static_cast<RoundMode>(rmi);
                v.scale_a = (v.scale_fmt == SCALE_E4M3) ? static_cast<uint8_t>(0x38u + (i % 6)) : static_cast<uint8_t>(0x7Cu + (i % 7));
                v.scale_b = (v.scale_fmt == SCALE_E4M3) ? static_cast<uint8_t>(0x34u + (i % 8)) : static_cast<uint8_t>(0x7Eu + (i % 5));
                v.accum_en = (i % 2) == 0;
                v.c_in = (i == 7) ? FP32_NEG_INF : ((i == 8) ? FP32_POS_INF : 0x3F800000u);
                v.a.assign(LANES, 0u);
                v.b.assign(LANES, 0u);
                for (int l = 0; l < LANES; ++l) {
                    v.a[l] = pool_a[(i + l) % pool_a.size()];
                    v.b[l] = pool_b[(i * 3 + l) % pool_b.size()];
                }
                // Avoid mixing Inf and NaN accidentally when testing clean cases
                if (i < 4) {
                    for (int l = 0; l < LANES; ++l) {
                        v.a[l] = pool_a[i];
                        v.b[l] = pool_b[i];
                    }
                }
                v.tag = "fp8_" + std::to_string(fa) + "_" + std::to_string(fb) + "_" + std::to_string(i) + "_rm" + std::to_string(rmi);
                out.push_back(v);
            }
        }

        // E4M3FN non-NaN 0x7E * E5M2 Inf/sNaN/0*Inf checks
        {
            Fp816Vector v;
            v.fmt_a = fa;
            v.fmt_b = fb;
            v.scale_fmt = is_mx ? SCALE_UE8M0 : SCALE_NONE;
            v.scale_a = 0x7Fu;
            v.scale_b = 0x7Fu;
            v.accum_en = true;
            v.c_in = (fb == FMT_FP8_E5M2 || fb == FMT_MXFP8_E5M2) ? FP32_NEG_INF : 0x00000000u;
            v.a.assign(LANES, (fa == FMT_FP8_E4M3 || fa == FMT_MXFP8_E4M3) ? 0x7Eu : 0x00u);
            v.b.assign(LANES, (fb == FMT_FP8_E5M2 || fb == FMT_MXFP8_E5M2) ? 0x7Cu : 0x38u);
            v.tag = "fp8_zero_inf_edge_" + std::to_string(fa) + "_" + std::to_string(fb);
            out.push_back(v);
        }

        for (int r = 0; r < 60; ++r) {
            Fp816Vector v;
            v.fmt_a = fa;
            v.fmt_b = fb;
            v.scale_fmt = is_mx ? ((r & 1) ? SCALE_UE8M0 : SCALE_E4M3) : SCALE_NONE;
            v.rm = static_cast<RoundMode>(rng() % 5u);
            v.scale_a = (v.scale_fmt == SCALE_E4M3) ? static_cast<uint8_t>(0x20u + (rng() % 0x50u))
                                                    : static_cast<uint8_t>(0x70u + (rng() % 32u));
            v.scale_b = (v.scale_fmt == SCALE_E4M3) ? static_cast<uint8_t>(0x20u + (rng() % 0x50u))
                                                    : static_cast<uint8_t>(0x70u + (rng() % 32u));
            v.accum_en = (rng() & 1u) != 0u;
            v.c_in = ((rng() % 5u) == 0u) ? 0x00000000u : (0x3C000000u + (rng() & 0x07FFFFFFu));
            v.a.resize(LANES);
            v.b.resize(LANES);
            for (int l = 0; l < LANES; ++l) {
                v.a[l] = static_cast<uint8_t>(rng() & 0xFFu);
                v.b[l] = static_cast<uint8_t>(rng() & 0xFFu);
            }
            v.tag = "fp8_rand_" + std::to_string(fa) + "_" + std::to_string(fb) + "_" + std::to_string(r);
            out.push_back(v);
        }
    }
    return out;
}

std::vector<Fp816Vector> build_bf16_fp16_tf32_vectors(std::mt19937& rng) {
    std::vector<Fp816Vector> out;
    const std::array<std::pair<Fmt, Fmt>, 5> combos = {{
        {FMT_BF16, FMT_BF16},
        {FMT_FP16, FMT_FP16},
        {FMT_BF16, FMT_FP16},
        {FMT_FP16, FMT_BF16},
        {FMT_TF32, FMT_TF32}
    }};

    const std::array<uint16_t, 12> bf16_pool = {
        0x0000u, 0x8000u, 0x0001u, 0x8001u, 0x3F80u, 0xBF80u,
        0x4049u, 0x7F7Fu, 0xFF7Fu, 0x7F80u, 0xFF80u, 0x7FC0u
    };
    const std::array<uint16_t, 12> fp16_pool = {
        0x0000u, 0x8000u, 0x0001u, 0x8001u, 0x3C00u, 0xBC00u,
        0x4248u, 0x7BFFu, 0xFBFFu, 0x7C00u, 0xFC00u, 0x7E00u
    };
    const std::array<uint32_t, 10> tf32_pool = {
        0x00000000u, 0x80000000u, 0x00002000u, 0x3F800000u, 0xBF800000u,
        0x40490000u, 0x7F7FE000u, 0x7F800000u, 0xFF800000u, 0x7FC00000u
    };

    for (const auto& [fa, fb] : combos) {
        for (int c = 0; c < 20; ++c) {
            Fp816Vector v;
            v.fmt_a = fa;
            v.fmt_b = fb;
            v.scale_fmt = SCALE_NONE;
            v.rm = static_cast<RoundMode>(c % 5);
            v.accum_en = (c % 3) != 0;
            v.c_in = (c == 0) ? FP32_NEG_ZERO : ((c == 1) ? 0x00000001u : (0x3F800000u ^ ((c & 1) ? 0x80000000u : 0u)));
            v.a.resize(LANES);
            v.b.resize(LANES);
            for (int l = 0; l < LANES; ++l) {
                auto pick_val = [&](Fmt f, size_t idx) -> uint32_t {
                    if (f == FMT_BF16) return bf16_pool[idx % bf16_pool.size()];
                    if (f == FMT_FP16) return fp16_pool[idx % fp16_pool.size()];
                    return tf32_pool[idx % tf32_pool.size()];
                };
                v.a[l] = (c < 10) ? pick_val(fa, c) : pick_val(fa, c + l);
                v.b[l] = (c < 10) ? pick_val(fb, (c + 3)) : pick_val(fb, c * 2 + l);
            }
            v.tag = "f16bf16tf32_" + std::to_string(fa) + "_" + std::to_string(fb) + "_" + std::to_string(c);
            out.push_back(v);
        }

        // Massive cancellation & tie-to-even boundary test
        for (int rmi = 0; rmi < 5; ++rmi) {
            Fp816Vector v;
            v.fmt_a = fa;
            v.fmt_b = fb;
            v.rm = static_cast<RoundMode>(rmi);
            v.accum_en = true;
            v.c_in = 0xC1000000u; // -8.0f
            v.a.resize(LANES);
            v.b.resize(LANES);
            uint32_t one_a = (fa == FMT_FP16) ? 0x3C00u : ((fa == FMT_BF16) ? 0x3F80u : 0x3F800000u);
            uint32_t one_b = (fb == FMT_FP16) ? 0x3C00u : ((fb == FMT_BF16) ? 0x3F80u : 0x3F800000u);
            v.a.assign(LANES, one_a);
            v.b.assign(LANES, one_b);
            v.tag = "cancel8_" + std::to_string(fa) + "_" + std::to_string(fb) + "_rm" + std::to_string(rmi);
            out.push_back(v);
        }

        for (int r = 0; r < 120; ++r) {
            Fp816Vector v;
            v.fmt_a = fa;
            v.fmt_b = fb;
            v.rm = static_cast<RoundMode>(rng() % 5u);
            v.accum_en = (rng() & 1u) != 0u;
            v.c_in = static_cast<uint32_t>(rng());
            if (fp32_is_nan(v.c_in) && (rng() % 8u != 0u)) v.c_in = 0xBF800000u;
            v.a.resize(LANES);
            v.b.resize(LANES);
            for (int l = 0; l < LANES; ++l) {
                if (fa == FMT_TF32) {
                    v.a[l] = (rng() & 0xFFFFE000u);
                    if (((v.a[l] >> 23) & 0xFFu) == 0xFFu && (rng() % 4u != 0u)) v.a[l] &= 0xBFFFFFFFu;
                } else {
                    uint32_t h = rng() & 0xFFFFu;
                    if (fa == FMT_FP16 && ((h >> 10) & 0x1Fu) == 0x1Fu && (rng() % 4u != 0u)) h &= 0xFBFFu;
                    if (fa == FMT_BF16 && ((h >> 7) & 0xFFu) == 0xFFu && (rng() % 4u != 0u)) h &= 0xFEFFu;
                    v.a[l] = h;
                }
                if (fb == FMT_TF32) {
                    v.b[l] = (rng() & 0xFFFFE000u);
                    if (((v.b[l] >> 23) & 0xFFu) == 0xFFu && (rng() % 4u != 0u)) v.b[l] &= 0xBFFFFFFFu;
                } else {
                    uint32_t h = rng() & 0xFFFFu;
                    if (fb == FMT_FP16 && ((h >> 10) & 0x1Fu) == 0x1Fu && (rng() % 4u != 0u)) h &= 0xFBFFu;
                    if (fb == FMT_BF16 && ((h >> 7) & 0xFFu) == 0xFFu && (rng() % 4u != 0u)) h &= 0xFEFFu;
                    v.b[l] = h;
                }
            }
            v.tag = "rand16_" + std::to_string(fa) + "_" + std::to_string(fb) + "_" + std::to_string(r);
            out.push_back(v);
        }
    }
    return out;
}

std::vector<Fp816Vector> build_int8_vectors(std::mt19937& rng) {
    std::vector<Fp816Vector> out;

    // Corner cases: -128 * -128 * 8 + INT32_MAX/MIN saturation & wraparound
    const std::array<std::tuple<uint8_t, uint8_t, uint32_t, bool, bool, std::string>, 8> corners = {{
        {0x80u, 0x80u, 0x7FFFF000u, true, true,  "int8_sat_pos"},
        {0x80u, 0x80u, 0x7FFFF000u, true, false, "int8_wrap_pos"},
        {0x80u, 0x7Fu, 0x80001000u, true, true,  "int8_sat_neg"},
        {0x80u, 0x7Fu, 0x80001000u, true, false, "int8_wrap_neg"},
        {0x00u, 0x00u, 0x12345678u, true, true,  "int8_zero_prod"},
        {0x00u, 0x00u, 0x12345678u, false, true, "int8_no_accum"},
        {0xFFu, 0x01u, 0x00000008u, true, true,  "int8_exact_cancel"},
        {0x7Fu, 0x7Fu, 0x00000000u, false, false,"int8_max_pos"}
    }};

    for (const auto& [av, bv, cin, acc, sat, name] : corners) {
        Fp816Vector v;
        v.fmt_a = FMT_INT8;
        v.fmt_b = FMT_INT8;
        v.scale_fmt = SCALE_NONE;
        v.accum_en = acc;
        v.int_saturate = sat;
        v.c_in = cin;
        v.a.assign(LANES, av);
        v.b.assign(LANES, bv);
        v.tag = name;
        out.push_back(v);
    }

    for (int r = 0; r < 300; ++r) {
        Fp816Vector v;
        v.fmt_a = FMT_INT8;
        v.fmt_b = FMT_INT8;
        v.scale_fmt = SCALE_NONE;
        v.accum_en = (rng() & 1u) != 0u;
        v.int_saturate = (rng() & 1u) != 0u;
        v.c_in = (r % 3 == 0) ? (0x7FFF0000u + (rng() & 0xFFFFu))
                              : ((r % 3 == 1) ? (0x80000000u + (rng() & 0xFFFFu)) : static_cast<uint32_t>(rng()));
        v.a.resize(LANES);
        v.b.resize(LANES);
        for (int l = 0; l < LANES; ++l) {
            v.a[l] = static_cast<uint32_t>(rng() & 0xFFu);
            v.b[l] = static_cast<uint32_t>(rng() & 0xFFu);
        }
        v.tag = "int8_rand_" + std::to_string(r);
        out.push_back(v);
    }
    return out;
}

std::vector<Fp816Vector> build_exception_priority_vectors() {
    std::vector<Fp816Vector> out;
    // +Inf + (-Inf) in products, sNaN vs qNaN, 0 * Inf, scale_zero * Inf
    {
        Fp816Vector v;
        v.fmt_a = FMT_FP16;
        v.fmt_b = FMT_FP16;
        v.a = {0x7C00u, 0xFC00u, 0x3C00u, 0x3C00u, 0, 0, 0, 0}; // +Inf, -Inf
        v.b = {0x3C00u, 0x3C00u, 0x3C00u, 0x3C00u, 0, 0, 0, 0};
        v.c_in = 0;
        v.accum_en = false;
        v.tag = "exc_inf_cancel_prods";
        out.push_back(v);
    }
    {
        Fp816Vector v;
        v.fmt_a = FMT_FP16;
        v.fmt_b = FMT_FP16;
        v.a = {0x7C00u, 0, 0, 0, 0, 0, 0, 0};
        v.b = {0x0000u, 0, 0, 0, 0, 0, 0, 0}; // Inf * 0
        v.c_in = 0;
        v.accum_en = false;
        v.tag = "exc_inf_mul_zero";
        out.push_back(v);
    }
    {
        Fp816Vector v;
        v.fmt_a = FMT_BF16;
        v.fmt_b = FMT_BF16;
        v.a = {0x7F81u, 0, 0, 0, 0, 0, 0, 0}; // sNaN
        v.b = {0x3F80u, 0, 0, 0, 0, 0, 0, 0};
        v.c_in = 0x7FC00000u; // qNaN
        v.accum_en = true;
        v.tag = "exc_snan_over_qnan";
        out.push_back(v);
    }
    {
        Fp816Vector v;
        v.fmt_a = FMT_MXFP8_E5M2;
        v.fmt_b = FMT_MXFP8_E5M2;
        v.scale_fmt = SCALE_E4M3;
        v.scale_a = 0x00u; // zero scale
        v.scale_b = 0x38u;
        v.a = {0x7Cu, 0, 0, 0, 0, 0, 0, 0}; // +Inf
        v.b = {0x3Cu, 0, 0, 0, 0, 0, 0, 0}; // 1.0
        v.c_in = 0;
        v.accum_en = false;
        v.tag = "exc_scale_zero_x_inf";
        out.push_back(v);
    }

    // Signed-sticky borrow across all 5 rounding modes
    for (RoundMode rmode : {RM_RNE, RM_RTZ, RM_RDN, RM_RUP, RM_RMM}) {
        Fp816Vector v_tie;
        v_tie.fmt_a = FMT_TF32;
        v_tie.fmt_b = FMT_TF32;
        v_tie.rm = rmode;
        v_tie.a = {0x33800000u, 0xA1800000u, 0, 0, 0, 0, 0, 0}; // +2^-24, -2^-60
        v_tie.b = {0x3F800000u, 0x3F800000u, 0, 0, 0, 0, 0, 0}; // 1.0, 1.0
        v_tie.c_in = 0x3F800000u; // 1.0
        v_tie.accum_en = true;
        v_tie.tag = "signed_sticky_borrow_1p2e_24_m2e_60_rm" + std::to_string(rmode);
        out.push_back(v_tie);

        Fp816Vector v_sub;
        v_sub.fmt_a = FMT_TF32;
        v_sub.fmt_b = FMT_TF32;
        v_sub.rm = rmode;
        v_sub.a = {0xA1800000u, 0, 0, 0, 0, 0, 0, 0}; // -2^-60
        v_sub.b = {0x3F800000u, 0, 0, 0, 0, 0, 0, 0}; // 1.0
        v_sub.c_in = 0x3F800000u; // 1.0
        v_sub.accum_en = true;
        v_sub.tag = "signed_sticky_borrow_1m2e_60_rm" + std::to_string(rmode);
        out.push_back(v_sub);
    }

    // Positive tiny BF16 underflow +2^-252 in RM_RDN -> +0.0 (not -0.0)
    for (RoundMode rmode : {RM_RNE, RM_RTZ, RM_RDN, RM_RUP, RM_RMM}) {
        Fp816Vector v;
        v.fmt_a = FMT_BF16;
        v.fmt_b = FMT_BF16;
        v.rm = rmode;
        v.a = {0x0080u, 0, 0, 0, 0, 0, 0, 0}; // +2^-126
        v.b = {0x0080u, 0, 0, 0, 0, 0, 0, 0}; // +2^-126
        v.c_in = 0;
        v.accum_en = false;
        v.tag = "tiny_pos_uf_rm" + std::to_string(rmode);
        out.push_back(v);
    }

    // Large-scale lane cancellation preserving C = +1.0
    {
        Fp816Vector v;
        v.fmt_a = FMT_TF32;
        v.fmt_b = FMT_TF32;
        v.rm = RM_RNE;
        v.a = {0x7F000000u, 0xFF000000u, 0, 0, 0, 0, 0, 0}; // +2^127, -2^127
        v.b = {0x3F800000u, 0x3F800000u, 0, 0, 0, 0, 0, 0};
        v.c_in = 0x3F800000u; // +1.0
        v.accum_en = true;
        v.tag = "fp816_large_lane_cancel_preserve_c";
        out.push_back(v);
    }

    // Primary-frame lane cancellation promoting finite secondary tail (+2^100 - 2^100 + 1.0)
    for (RoundMode rmode : {RM_RNE, RM_RTZ, RM_RDN, RM_RUP, RM_RMM}) {
        Fp816Vector v_noacc;
        v_noacc.fmt_a = FMT_TF32;
        v_noacc.fmt_b = FMT_TF32;
        v_noacc.rm = rmode;
        v_noacc.a = {0x58800000u, 0xD8800000u, 0x3F800000u, 0, 0, 0, 0, 0}; // +2^50, -2^50, +1.0
        v_noacc.b = {0x58800000u, 0x58800000u, 0x3F800000u, 0, 0, 0, 0, 0}; // +2^50, +2^50, +1.0
        v_noacc.c_in = 0x00000000u;
        v_noacc.accum_en = false;
        v_noacc.tag = "primary_cancel_tail_promo_noacc_rm" + std::to_string(rmode);
        out.push_back(v_noacc);

        Fp816Vector v_acc = v_noacc;
        v_acc.c_in = 0x3F800000u; // +1.0 -> exact +2.0
        v_acc.accum_en = true;
        v_acc.tag = "primary_cancel_tail_promo_acc_rm" + std::to_string(rmode);
        out.push_back(v_acc);
    }

    // Exact 3-term remainder cancellation without false sticky (4.0 + 2^-63 + 2*2^-64 - 2^-62 == 4.0, NX=0)
    for (RoundMode rmode : {RM_RNE, RM_RTZ, RM_RDN, RM_RUP, RM_RMM}) {
        Fp816Vector v;
        v.fmt_a = FMT_TF32;
        v.fmt_b = FMT_TF32;
        v.rm = rmode;
        // lanes 0..3 = +1.0, lane 4 = +2^-63, lanes 5..6 = +2^-64, C = -2^-62
        v.a = {0x3F800000u, 0x3F800000u, 0x3F800000u, 0x3F800000u, 0x30000000u, 0x2F800000u, 0x2F800000u, 0};
        v.b = {0x3F800000u, 0x3F800000u, 0x3F800000u, 0x3F800000u, 0x2F800000u, 0x2F800000u, 0x2F800000u, 0};
        v.c_in = 0xA0800000u; // -2^-62
        v.accum_en = true;
        v.tag = "exact_rem_cancel_no_false_sticky_rm" + std::to_string(rmode);
        out.push_back(v);
    }

    // Cancelling ls_rem and c_rem while an overshifted secondary tail preserves positive sticky (RM_RUP)
    for (RoundMode rmode : {RM_RNE, RM_RTZ, RM_RDN, RM_RUP, RM_RMM}) {
        Fp816Vector v;
        v.fmt_a = FMT_TF32;
        v.fmt_b = FMT_TF32;
        v.rm = rmode;
        // lanes 0..3 = +1.0, lane 4 = +2^-62 (2^-31 * 2^-31), lane 5 = +2^-130 (2^-65 * 2^-65), C = -2^-62
        v.a = {0x3F800000u, 0x3F800000u, 0x3F800000u, 0x3F800000u, 0x30000000u, 0x1F000000u, 0, 0};
        v.b = {0x3F800000u, 0x3F800000u, 0x3F800000u, 0x3F800000u, 0x30000000u, 0x1F000000u, 0, 0};
        v.c_in = 0xA0800000u; // -2^-62
        v.accum_en = true;
        v.tag = "overshifted_tail_sticky_after_rem_cancel_rm" + std::to_string(rmode);
        out.push_back(v);
    }

    return out;
}

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tcu_v2_fp8_bf16_fedp_unit>();
    Fp816Driver drv(dut.get());
    drv.reset();

    std::mt19937 rng(0xB2F8B160u);

    auto v_exc = build_exception_priority_vectors();
    drv.drive_stream(v_exc, false, 11);

    auto v_fp8 = build_fp8_vectors(rng);
    drv.drive_stream(v_fp8, true, 22);

    auto v_16 = build_bf16_fp16_tf32_vectors(rng);
    drv.drive_stream(v_16, true, 33);

    auto v_i8 = build_int8_vectors(rng);
    drv.drive_stream(v_i8, true, 44);

    // Reset recovery check
    drv.reset();
    drv.drive_stream(v_exc, false, 55);

    if (drv.mismatches() != 0) {
        return 1;
    }
    std::printf("[tb_fp8_bf16_fedp] PASS: checked=%llu vectors in %llu cycles\n",
                static_cast<unsigned long long>(drv.checked()),
                static_cast<unsigned long long>(drv.cycles()));
    return 0;
}
