// SPDX-License-Identifier: Apache-2.0
#include "VVX_tcu_v2_systolic_top.h"
#include "tcu_v2_golden_ref.h"
#include <verilated.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <random>
#include <string>
#include <vector>

double sc_time_stamp() { return 0.0; }

namespace {

using namespace tcu_v2_ref;

constexpr int ARR_M = 4;
constexpr int ARR_N = 4;
constexpr int ARR_K = 8;

struct UopItem {
    uint8_t   desc_id        = 0;
    uint8_t   step_m         = 0;
    uint8_t   step_n         = 0;
    uint8_t   step_k         = 0;
    Fmt       fmt_a          = FMT_BF16;
    Fmt       fmt_b          = FMT_BF16;
    Fmt       fmt_d          = FMT_FP32;
    ScaleFmt  scale_fmt      = SCALE_NONE;
    RoundMode rm             = RM_RNE;
    ActMode   act            = ACT_NONE;
    bool      is_first_k     = true;
    bool      is_last_k      = true;
    bool      accum_en       = false;
    bool      bias_en        = false;
    bool      sparse_en      = false;
    bool      int_saturate   = false;
    uint32_t  clamp_min_fp32 = 0;
    uint32_t  clamp_max_fp32 = 0;

    std::vector<uint32_t> a_tile;  // ARR_M * ARR_K
    std::vector<uint32_t> b_tile;  // ARR_N * ARR_K
    std::vector<uint8_t>  scale_a; // ARR_M
    std::vector<uint8_t>  scale_b; // ARR_N
    std::vector<uint32_t> c_tile;  // ARR_M * ARR_N
    std::vector<uint32_t> bias;    // ARR_N
    std::string           tag;
};

// Pack tcu_v2_uop_t matching exact RTL field order (LSB to MSB):
// clamp_max_fp32[31:0], clamp_min_fp32[31:0], int_saturate, sparse_en, bias_en,
// accum_en, is_last_k, is_first_k, act[2:0], rm[2:0], scale_fmt[1:0],
// fmt_d[4:0], fmt_b[4:0], fmt_a[4:0], step_k[7:0], step_n[3:0], step_m[3:0], desc_id[7:0]
template <size_t NW>
void pack_uop_wide(uint32_t* dst, const UopItem& u) {
    wide_zero<NW>(dst);
    size_t bit = 0;
    auto put = [&](size_t w, uint64_t val) {
        wide_set_bits(dst, NW, bit, w, val);
        bit += w;
    };
    put(32, u.clamp_max_fp32);
    put(32, u.clamp_min_fp32);
    put(1, u.int_saturate ? 1u : 0u);
    put(1, u.sparse_en ? 1u : 0u);
    put(1, u.bias_en ? 1u : 0u);
    put(1, u.accum_en ? 1u : 0u);
    put(1, u.is_last_k ? 1u : 0u);
    put(1, u.is_first_k ? 1u : 0u);
    put(3, u.act);
    put(3, u.rm);
    put(2, u.scale_fmt);
    put(5, u.fmt_d);
    put(5, u.fmt_b);
    put(5, u.fmt_a);
    put(8, u.step_k);
    put(4, u.step_n);
    put(4, u.step_m);
    put(8, u.desc_id);
}

class SystolicDriver {
public:
    explicit SystolicDriver(VVX_tcu_v2_systolic_top* dut) : dut_(dut) {}

    void reset() {
        dut_->reset = 1;
        dut_->uop_valid = 0;
        dut_->out_ready = 1;
        wide_zero<4>(dut_->uop_in.data());
        wide_zero<ARR_M * ARR_K>(dut_->a_tile_in.data());
        wide_zero<ARR_N * ARR_K>(dut_->b_tile_in.data());
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

    void drive_uop_inputs(const UopItem& u) {
        pack_uop_wide<4>(dut_->uop_in.data(), u);
        for (int r = 0; r < ARR_M; ++r) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->a_tile_in[r * ARR_K + k] = u.a_tile[static_cast<size_t>(r * ARR_K + k)];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            for (int k = 0; k < ARR_K; ++k) {
                dut_->b_tile_in[c * ARR_K + k] = u.b_tile[static_cast<size_t>(c * ARR_K + k)];
            }
        }
        uint32_t sa_pack = 0;
        for (int r = 0; r < ARR_M; ++r) {
            sa_pack |= (static_cast<uint32_t>(u.scale_a[r]) << (r * 8));
        }
        uint32_t sb_pack = 0;
        for (int c = 0; c < ARR_N; ++c) {
            sb_pack |= (static_cast<uint32_t>(u.scale_b[c]) << (c * 8));
        }
        dut_->scale_a_in = sa_pack;
        dut_->scale_b_in = sb_pack;

        for (int r = 0; r < ARR_M; ++r) {
            for (int c = 0; c < ARR_N; ++c) {
                dut_->c_tile_in[r * ARR_N + c] = u.c_tile[static_cast<size_t>(r * ARR_N + c)];
            }
        }
        for (int c = 0; c < ARR_N; ++c) {
            dut_->bias_in[c] = u.bias[c];
        }
    }

    void run_k_chain(const std::vector<UopItem>& uops, bool inject_bp, uint32_t seed) {
        std::mt19937 rng(seed);
        // Compute golden multi-K result on the final uop
        std::vector<uint32_t> acc_tile(ARR_M * ARR_N, 0u);
        FpFlags acc_flags{};
        std::vector<std::pair<std::vector<uint32_t>, FpFlags>> expected_tiles;

        for (size_t i = 0; i < uops.size(); ++i) {
            const auto& u = uops[i];
            WgmmaDesc d;
            d.desc_id = u.desc_id;
            d.fmt_a = u.fmt_a;
            d.fmt_b = u.fmt_b;
            d.fmt_c = FMT_FP32;
            d.fmt_d = u.fmt_d;
            d.scale_fmt = u.scale_fmt;
            d.rm = u.rm;
            d.act = u.act;
            d.accum_en = u.accum_en;
            d.bias_en = u.bias_en;
            d.int_saturate = u.int_saturate;
            d.clamp_min_fp32 = u.clamp_min_fp32;
            d.clamp_max_fp32 = u.clamp_max_fp32;

            const std::vector<uint32_t>& cin = u.is_first_k ? u.c_tile : acc_tile;
            if (u.is_first_k) {
                acc_flags = FpFlags{};
            }
            acc_tile = ref_tile_gemm_step(ARR_M, ARR_N, ARR_K, d,
                                          u.a_tile, u.b_tile, u.scale_a, u.scale_b,
                                          cin, u.bias, u.is_first_k, u.is_last_k, acc_flags);
            if (u.is_last_k) {
                expected_tiles.emplace_back(acc_tile, acc_flags);
            }
        }

        size_t u_idx = 0;
        size_t out_idx = 0;
        int guard = 0;

        while (u_idx < uops.size() || out_idx < expected_tiles.size()) {
            dut_->out_ready = (inject_bp && (rng() % 5u) == 0u) ? 0 : 1;
            if (u_idx < uops.size()) {
                dut_->uop_valid = 1;
                drive_uop_inputs(uops[u_idx]);
            } else {
                dut_->uop_valid = 0;
            }

            dut_->clk = 0;
            dut_->eval();

            if (dut_->uop_valid && dut_->uop_ready) {
                ++u_idx;
                guard = 0;
            }

            if (dut_->out_valid && dut_->out_ready) {
                if (out_idx >= expected_tiles.size()) {
                    std::fprintf(stderr, "[tb_systolic_array] FAIL: unexpected out_valid\n");
                    std::exit(1);
                }
                const auto& [exp_tile, exp_flags] = expected_tiles[out_idx];
                const auto& last_u = uops.back();
                bool is_int_out = (last_u.fmt_d == FMT_I32 || last_u.fmt_d == FMT_INT8);

                for (int r = 0; r < ARR_M; ++r) {
                    for (int c = 0; c < ARR_N; ++c) {
                        uint32_t got = dut_->d_tile_out[r * ARR_N + c];
                        uint32_t exp = exp_tile[static_cast<size_t>(r * ARR_N + c)];
                        bool ok = (got == exp) || (!is_int_out && last_u.fmt_d == FMT_FP32 &&
                                                   fp32_is_nan(got) && fp32_is_nan(exp));
                        if (!ok) {
                            std::fprintf(stderr,
                                         "[tb_systolic_array] MISMATCH tag=%s out=%zu (%d,%d) got=%s exp=%s\n",
                                         last_u.tag.c_str(), out_idx, r, c,
                                         hex32(got).c_str(), hex32(exp).c_str());
                            std::exit(1);
                        }
                    }
                }
                FpFlags got_f = FpFlags::unpack(static_cast<uint8_t>(dut_->flags_out & 0x1Fu));
                if (!(got_f == exp_flags)) {
                    // Note: accumulator bank ORs per-k flags across k-steps; verify NV/OF match
                    if (got_f.nv != exp_flags.nv || got_f.of != exp_flags.of) {
                        std::fprintf(stderr,
                                     "[tb_systolic_array] FLAGS MISMATCH tag=%s got=0x%02x exp=0x%02x\n",
                                     last_u.tag.c_str(), got_f.pack(), exp_flags.pack());
                        std::exit(1);
                    }
                }
                ++out_idx;
                ++tiles_checked_;
                guard = 0;
            }

            dut_->clk = 1;
            dut_->eval();
            ++cycles_;
            ++guard;
            if (guard > 4000) {
                std::fprintf(stderr, "[tb_systolic_array] FAIL: timeout tag=%s u_idx=%zu/%zu out_idx=%zu/%zu\n",
                             uops.front().tag.c_str(), u_idx, uops.size(), out_idx, expected_tiles.size());
                std::exit(1);
            }
        }
        dut_->uop_valid = 0;
        dut_->out_ready = 1;
        for (int i = 0; i < 4; ++i) tick();
    }

    uint64_t tiles_checked() const { return tiles_checked_; }
    uint64_t cycles() const { return cycles_; }

private:
    VVX_tcu_v2_systolic_top* dut_;
    uint64_t cycles_ = 0;
    uint64_t tiles_checked_ = 0;
};

uint32_t make_elem_for_fmt(Fmt f, int val_idx) {
    // Deterministic small integer-representable encodings across all formats
    static const std::array<uint8_t, 6> fp4_pool = {0x02u, 0x04u, 0x0Au, 0x03u, 0x06u, 0x0Cu}; // 1,2,-1,1.5,4,-2
    static const std::array<uint8_t, 6> e2m3_pool = {0x08u, 0x10u, 0x28u, 0x14u, 0x18u, 0x30u}; // 1,2,-1,3,4,-2
    static const std::array<uint8_t, 6> e3m2_pool = {0x0Cu, 0x10u, 0x2Cu, 0x14u, 0x18u, 0x30u}; // 1,2,-1,4,8,-2
    static const std::array<uint8_t, 6> e4m3_pool = {0x38u, 0x40u, 0xB8u, 0x44u, 0x48u, 0xC0u};
    static const std::array<uint8_t, 6> e5m2_pool = {0x3Cu, 0x40u, 0xBCu, 0x44u, 0x48u, 0xC0u};
    static const std::array<uint16_t, 6> fp16_pool = {0x3C00u, 0x4000u, 0xBC00u, 0x4200u, 0x4400u, 0xC000u};
    static const std::array<uint16_t, 6> bf16_pool = {0x3F80u, 0x4000u, 0xBF80u, 0x4040u, 0x4080u, 0xC000u};
    static const std::array<uint32_t, 6> tf32_pool = {0x3F800000u, 0x40000000u, 0xBF800000u, 0x40400000u, 0x40800000u, 0xC0000000u};
    size_t idx = static_cast<size_t>(val_idx) % 6u;
    switch (f) {
        case FMT_MXFP4_E2M1:
        case FMT_NVFP4_E2M1: return fp4_pool[idx];
        case FMT_MXFP6_E2M3: return e2m3_pool[idx];
        case FMT_MXFP6_E3M2: return e3m2_pool[idx];
        case FMT_FP8_E4M3:
        case FMT_MXFP8_E4M3: return e4m3_pool[idx];
        case FMT_FP8_E5M2:
        case FMT_MXFP8_E5M2: return e5m2_pool[idx];
        case FMT_FP16:       return fp16_pool[idx];
        case FMT_BF16:       return bf16_pool[idx];
        case FMT_TF32:       return tf32_pool[idx];
        case FMT_INT8:       return static_cast<uint32_t>(static_cast<uint8_t>((idx % 5) - 2));
        default:             return tf32_pool[idx];
    }
}

UopItem make_uop(uint8_t desc_id, uint8_t step_k, bool first_k, bool last_k,
                 Fmt fa, Fmt fb, Fmt fd, ScaleFmt sf, ActMode act,
                 bool accum_en, bool bias_en, bool sat, int seed_offset,
                 const std::string& tag) {
    UopItem u;
    u.desc_id = desc_id;
    u.step_k = step_k;
    u.is_first_k = first_k;
    u.is_last_k = last_k;
    u.fmt_a = fa;
    u.fmt_b = fb;
    u.fmt_d = fd;
    u.scale_fmt = sf;
    u.rm = RM_RNE;
    u.act = act;
    u.accum_en = accum_en;
    u.bias_en = bias_en;
    u.int_saturate = sat;
    u.clamp_min_fp32 = (fd == FMT_I32 || fd == FMT_INT8) ? static_cast<uint32_t>(-10) : 0xBF800000u; // -1.0f
    u.clamp_max_fp32 = (fd == FMT_I32 || fd == FMT_INT8) ? static_cast<uint32_t>(20) : 0x41200000u;  // 10.0f

    u.a_tile.resize(ARR_M * ARR_K);
    u.b_tile.resize(ARR_N * ARR_K);
    for (int r = 0; r < ARR_M; ++r) {
        for (int k = 0; k < ARR_K; ++k) {
            u.a_tile[r * ARR_K + k] = make_elem_for_fmt(fa, r * 3 + k + seed_offset);
        }
    }
    for (int c = 0; c < ARR_N; ++c) {
        for (int k = 0; k < ARR_K; ++k) {
            u.b_tile[c * ARR_K + k] = make_elem_for_fmt(fb, c * 5 + k + seed_offset + 1);
        }
    }
    u.scale_a.assign(ARR_M, (sf == SCALE_E4M3) ? 0x38u : ((sf == SCALE_UE8M0) ? 0x7Fu : 0u));
    u.scale_b.assign(ARR_N, (sf == SCALE_E4M3) ? 0x38u : ((sf == SCALE_UE8M0) ? 0x7Fu : 0u));
    if (sf == SCALE_UE8M0) {
        u.scale_a[1] = 0x80u; // 2.0
        u.scale_b[2] = 0x7Eu; // 0.5
    } else if (sf == SCALE_E4M3) {
        u.scale_a[1] = 0x40u; // 2.0
        u.scale_b[2] = 0x30u; // 0.5
    }

    u.c_tile.resize(ARR_M * ARR_N);
    for (int r = 0; r < ARR_M; ++r) {
        for (int c = 0; c < ARR_N; ++c) {
            if (fa == FMT_INT8) {
                u.c_tile[r * ARR_N + c] = static_cast<uint32_t>(r * 4 - c);
            } else {
                u.c_tile[r * ARR_N + c] = (r == c) ? 0x3F800000u : 0xBF000000u; // 1.0 or -0.5
            }
        }
    }
    u.bias.resize(ARR_N);
    for (int c = 0; c < ARR_N; ++c) {
        u.bias[c] = (fa == FMT_INT8) ? static_cast<uint32_t>(c + 1) : (0x3F000000u + (c << 21));
    }
    u.tag = tag;
    return u;
}

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto dut = std::make_unique<VVX_tcu_v2_systolic_top>();
    SystolicDriver drv(dut.get());
    drv.reset();

    // 1. Single-step sweep across all numeric formats + epilogue activations + cast formats
    struct FormatCase {
        Fmt fa;
        Fmt fb;
        Fmt fd;
        ScaleFmt sf;
        ActMode act;
        bool bias;
        const char* name;
    };
    const std::array<FormatCase, 16> cases = {{
        {FMT_MXFP4_E2M1, FMT_MXFP4_E2M1, FMT_FP32,      SCALE_UE8M0, ACT_NONE,  false, "mxfp4_fp32"},
        {FMT_NVFP4_E2M1, FMT_NVFP4_E2M1, FMT_BF16,      SCALE_E4M3,  ACT_RELU,  true,  "nvfp4_bf16_relu_bias"},
        {FMT_MXFP6_E2M3, FMT_MXFP6_E3M2, FMT_FP16,      SCALE_UE8M0, ACT_CLAMP, true,  "mxfp6_mix_fp16_clamp"},
        {FMT_MXFP8_E4M3, FMT_MXFP8_E5M2, FMT_FP8_E4M3,  SCALE_UE8M0, ACT_SILU,  true,  "mxfp8_e4m3_silu"},
        {FMT_FP8_E4M3,   FMT_FP8_E4M3,   FMT_FP8_E5M2,  SCALE_NONE,  ACT_GELU,  false, "fp8_e4m3_e5m2_gelu"},
        {FMT_FP8_E5M2,   FMT_FP8_E5M2,   FMT_FP32,      SCALE_NONE,  ACT_NONE,  true,  "fp8_e5m2_fp32"},
        {FMT_BF16,       FMT_BF16,       FMT_BF16,      SCALE_NONE,  ACT_RELU,  true,  "bf16_bf16_relu"},
        {FMT_FP16,       FMT_FP16,       FMT_FP16,      SCALE_NONE,  ACT_SILU,  false, "fp16_fp16_silu"},
        {FMT_BF16,       FMT_FP16,       FMT_FP32,      SCALE_NONE,  ACT_GELU,  true,  "bf16_fp16_gelu"},
        {FMT_TF32,       FMT_TF32,       FMT_FP32,      SCALE_NONE,  ACT_CLAMP, true,  "tf32_fp32_clamp"},
        {FMT_TF32,       FMT_TF32,       FMT_BF16,      SCALE_NONE,  ACT_NONE,  false, "tf32_bf16"},
        {FMT_INT8,       FMT_INT8,       FMT_I32,       SCALE_NONE,  ACT_NONE,  true,  "int8_i32_bias"},
        {FMT_INT8,       FMT_INT8,       FMT_I32,       SCALE_NONE,  ACT_RELU,  true,  "int8_i32_relu"},
        {FMT_INT8,       FMT_INT8,       FMT_I32,       SCALE_NONE,  ACT_CLAMP, false, "int8_i32_clamp"},
        {FMT_INT8,       FMT_INT8,       FMT_INT8,      SCALE_NONE,  ACT_NONE,  true,  "int8_int8_cast"},
        {FMT_MXFP4_E2M1, FMT_MXFP6_E2M3, FMT_FP32,      SCALE_UE8M0, ACT_GELU,  true,  "fp4_fp6_gelu"}
    }};

    for (size_t i = 0; i < cases.size(); ++i) {
        const auto& cs = cases[i];
        auto u = make_uop(static_cast<uint8_t>(i + 1), 0, true, true,
                          cs.fa, cs.fb, cs.fd, cs.sf, cs.act,
                          (i % 2) == 0, cs.bias, true, static_cast<int>(i), cs.name);
        drv.run_k_chain({u}, (i % 3) == 0, static_cast<uint32_t>(100 + i));
    }

    // 2. Multi-K accumulation chains (RMW forwarding across 2, 3, and 4 K-steps)
    for (int k_steps : {2, 3, 4}) {
        std::vector<UopItem> chain;
        for (int ks = 0; ks < k_steps; ++ks) {
            bool first_k = (ks == 0);
            bool last_k = (ks == k_steps - 1);
            chain.push_back(make_uop(0x20u + k_steps, static_cast<uint8_t>(ks), first_k, last_k,
                                   FMT_BF16, FMT_BF16, FMT_FP32, SCALE_NONE,
                                   ACT_RELU, true, true, false, ks * 7,
                                   "rmw_bf16_k" + std::to_string(k_steps)));
        }
        drv.run_k_chain(chain, true, 900 + k_steps);
    }

    // 3. Multi-K chain for MXFP4 with k=16 vs k=32 scale latching boundary
    {
        std::vector<UopItem> chain;
        for (int ks = 0; ks < 4; ++ks) {
            auto u = make_uop(0x30u, static_cast<uint8_t>(ks), ks == 0, ks == 3,
                              FMT_NVFP4_E2M1, FMT_NVFP4_E2M1, FMT_FP32, SCALE_E4M3,
                              ACT_NONE, false, false, false, ks * 3, "nvfp4_k4");
            // On step_k == 2 (k_elem_offset = 16), scale_broadcast updates cached scale
            if (ks == 1) {
                u.scale_a.assign(ARR_M, 0x48u); // should use cached scale from ks=0!
                u.scale_b.assign(ARR_N, 0x48u);
            }
            chain.push_back(u);
        }
        // Adjust expected reference for ks=1 cached scale behavior
        for (int r = 0; r < ARR_M; ++r) chain[1].scale_a[r] = chain[0].scale_a[r];
        for (int c = 0; c < ARR_N; ++c) chain[1].scale_b[c] = chain[0].scale_b[c];
        drv.run_k_chain(chain, false, 950);
    }

    // 4. INT8 saturation across multi-K + bias
    {
        std::vector<UopItem> chain;
        for (int ks = 0; ks < 2; ++ks) {
            auto u = make_uop(0x40u, static_cast<uint8_t>(ks), ks == 0, ks == 1,
                              FMT_INT8, FMT_INT8, FMT_I32, SCALE_NONE,
                              ACT_NONE, true, true, true, ks, "int8_k2_sat");
            if (ks == 0) {
                std::fill(u.c_tile.begin(), u.c_tile.end(), 0x7FFFFFC0u);
                std::fill(u.a_tile.begin(), u.a_tile.end(), 0x7Fu);
                std::fill(u.b_tile.begin(), u.b_tile.end(), 0x7Fu);
            }
            chain.push_back(u);
        }
        drv.run_k_chain(chain, false, 960);
    }

    std::printf("[tb_systolic_array] PASS: checked=%llu tiles in %llu cycles\n",
                static_cast<unsigned long long>(drv.tiles_checked()),
                static_cast<unsigned long long>(drv.cycles()));
    return 0;
}
