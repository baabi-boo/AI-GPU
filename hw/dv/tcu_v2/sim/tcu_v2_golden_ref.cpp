// SPDX-License-Identifier: Apache-2.0
#include "tcu_v2_golden_ref.h"

#include <algorithm>
#include <cstdio>
#include <limits>

namespace tcu_v2_ref {

namespace {

inline uint8_t lzc_u8(uint8_t v) {
    for (int b = 7; b >= 0; --b) {
        if ((v >> b) & 1u) {
            return static_cast<uint8_t>(7 - b);
        }
    }
    return 0;
}

inline uint8_t lzc_u24(uint32_t v) {
    v &= 0xFFFFFFu;
    for (int b = 23; b >= 0; --b) {
        if ((v >> b) & 1u) {
            return static_cast<uint8_t>(23 - b);
        }
    }
    return 24;
}

inline uint8_t lzc_u64(uint64_t v) {
    for (int b = 63; b >= 0; --b) {
        if ((v >> b) & 1ULL) {
            return static_cast<uint8_t>(63 - b);
        }
    }
    return 64;
}

inline uint8_t ctz_u64(uint64_t v, bool& nz) {
    nz = (v != 0ULL);
    if (!nz) {
        return 63;
    }
    for (int b = 0; b < 64; ++b) {
        if ((v >> b) & 1ULL) {
            return static_cast<uint8_t>(b);
        }
    }
    return 63;
}

inline bool round_decision(bool sign, bool lsb, bool guard, bool sticky, RoundMode rm) {
    bool inexact = guard || sticky;
    switch (rm) {
        case RM_RNE: return guard && (sticky || lsb);
        case RM_RTZ: return false;
        case RM_RDN: return sign && inexact;
        case RM_RUP: return !sign && inexact;
        case RM_RMM: return guard;
        default:     return guard && (sticky || lsb);
    }
}

inline bool compute_round_up_grs(RoundMode rm, bool sign, bool lsb, bool g, bool r, bool s) {
    bool tail = g || r || s;
    switch (rm) {
        case RM_RNE: return g && (r || s || lsb);
        case RM_RTZ: return false;
        case RM_RDN: return sign && tail;
        case RM_RUP: return !sign && tail;
        case RM_RMM: return g;
        default:     return g && (r || s || lsb);
    }
}

inline bool select_ovf_to_inf(RoundMode rm, bool sign) {
    switch (rm) {
        case RM_RNE:
        case RM_RMM: return true;
        case RM_RTZ: return false;
        case RM_RDN: return sign;
        case RM_RUP: return !sign;
        default:     return true;
    }
}

inline bool fp32_lt_total(uint32_t a, uint32_t b) {
    bool sa = (a >> 31) & 1u;
    bool sb = (b >> 31) & 1u;
    uint32_t ma = a & 0x7FFFFFFFu;
    uint32_t mb = b & 0x7FFFFFFFu;
    if (ma == 0 && mb == 0) {
        return false;
    }
    if (sa != sb) {
        return sa;
    }
    if (sa) {
        return ma > mb;
    }
    return ma < mb;
}

inline uint32_t fp32_abs(uint32_t a) {
    return a & 0x7FFFFFFFu;
}

inline uint32_t pack_fp32(bool sign, uint8_t exp8, uint32_t man23) {
    return (static_cast<uint32_t>(sign) << 31) |
           (static_cast<uint32_t>(exp8) << 23) |
           (man23 & 0x7FFFFFu);
}

inline uint64_t mask48(uint64_t v) {
    return v & 0xFFFFFFFFFFFFULL;
}

inline int64_t sext48(uint64_t v) {
    v &= 0xFFFFFFFFFFFFULL;
    if (v & (1ULL << 47)) {
        v |= ~0xFFFFFFFFFFFFULL;
    }
    return static_cast<int64_t>(v);
}

inline uint32_t sparse_mag_key(Fmt fmt, uint32_t raw) {
    switch (fmt) {
        case FMT_TF32:
        case FMT_FP32:
            return raw & 0x7FFFFFFFu;
        case FMT_FP16:
        case FMT_BF16:
            return raw & 0x7FFFu;
        case FMT_FP8_E4M3:
        case FMT_FP8_E5M2:
        case FMT_MXFP8_E4M3:
        case FMT_MXFP8_E5M2:
            return raw & 0x7Fu;
        case FMT_MXFP6_E2M3:
        case FMT_MXFP6_E3M2:
            return raw & 0x1Fu;
        case FMT_MXFP4_E2M1:
        case FMT_NVFP4_E2M1:
            return raw & 0x7u;
        case FMT_INT8: {
            int8_t s8 = static_cast<int8_t>(raw & 0xFFu);
            int32_t abs8 = (s8 < 0) ? (-static_cast<int32_t>(s8)) : static_cast<int32_t>(s8);
            return static_cast<uint32_t>(abs8) & 0xFFu;
        }
        default:
            return raw & 0x7FFFFFFFu;
    }
}

inline bool elem_is_zero_fmt(Fmt fmt, uint32_t raw) {
    switch (fmt) {
        case FMT_TF32:
            return (raw & 0x7FFFFFFFu) == 0u;
        case FMT_FP16:
        case FMT_BF16:
            return (raw & 0x7FFFu) == 0u;
        case FMT_FP8_E4M3:
        case FMT_FP8_E5M2:
        case FMT_MXFP8_E4M3:
        case FMT_MXFP8_E5M2:
            return (raw & 0x7Fu) == 0u;
        case FMT_INT8:
            return (raw & 0xFFu) == 0u;
        case FMT_MXFP6_E2M3:
        case FMT_MXFP6_E3M2:
            return (raw & 0x1Fu) == 0u;
        case FMT_MXFP4_E2M1:
        case FMT_NVFP4_E2M1:
            return (raw & 0x7u) == 0u;
        default:
            return (raw & 0x7FFFFFFFu) == 0u;
    }
}

} // namespace

bool fmt_is_fp4(Fmt f) {
    return f == FMT_MXFP4_E2M1 || f == FMT_NVFP4_E2M1;
}

bool fmt_is_fp6(Fmt f) {
    return f == FMT_MXFP6_E2M3 || f == FMT_MXFP6_E3M2;
}

bool fmt_is_fp8(Fmt f) {
    return f == FMT_FP8_E4M3 || f == FMT_FP8_E5M2 ||
           f == FMT_MXFP8_E4M3 || f == FMT_MXFP8_E5M2;
}

bool fmt_is_mx(Fmt f) {
    return f == FMT_MXFP8_E4M3 || f == FMT_MXFP8_E5M2 ||
           f == FMT_MXFP4_E2M1 || f == FMT_NVFP4_E2M1 ||
           f == FMT_MXFP6_E2M3 || f == FMT_MXFP6_E3M2;
}

bool fmt_is_int(Fmt f) {
    return f == FMT_I32 || f == FMT_INT8;
}

bool fmt_supports_sparse(Fmt f) {
    switch (f) {
        case FMT_TF32:
        case FMT_FP16:
        case FMT_BF16:
        case FMT_FP8_E4M3:
        case FMT_FP8_E5M2:
        case FMT_MXFP8_E4M3:
        case FMT_MXFP8_E5M2:
        case FMT_MXFP4_E2M1:
        case FMT_NVFP4_E2M1:
        case FMT_MXFP6_E2M3:
        case FMT_MXFP6_E3M2:
        case FMT_INT8:
            return true;
        default:
            return false;
    }
}

uint32_t fmt_bitwidth(Fmt f) {
    switch (f) {
        case FMT_FP32:
        case FMT_TF32:
        case FMT_I32:        return 32;
        case FMT_FP16:
        case FMT_BF16:       return 16;
        case FMT_FP8_E4M3:
        case FMT_FP8_E5M2:
        case FMT_MXFP8_E4M3:
        case FMT_MXFP8_E5M2:
        case FMT_INT8:       return 8;
        case FMT_MXFP6_E2M3:
        case FMT_MXFP6_E3M2: return 6;
        case FMT_MXFP4_E2M1:
        case FMT_NVFP4_E2M1: return 4;
        default:             return 0;
    }
}

UnpackedFp unpack_fp4_e2m1(uint8_t nib) {
    UnpackedFp u;
    nib &= 0xFu;
    u.sign = (nib >> 3) & 1u;
    uint8_t e = (nib >> 1) & 0x3u;
    uint8_t m = nib & 0x1u;
    if (e == 0 && m == 0) {
        u.is_zero = true;
        u.exp = 0;
        u.sig_u1p23 = 0;
    } else if (e == 0) {
        // Subnormal +/-0.5 -> normalized 1.0 * 2^-1
        u.is_subnormal = true;
        u.exp = -1;
        u.sig_u1p23 = (1u << 23);
    } else {
        u.exp = static_cast<int32_t>(e) - 1;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 22);
    }
    return u;
}

UnpackedFp unpack_fp6_e2m3(uint8_t raw6) {
    UnpackedFp u;
    raw6 &= 0x3Fu;
    u.sign = (raw6 >> 5) & 1u;
    uint8_t e = (raw6 >> 3) & 0x3u;
    uint8_t m = raw6 & 0x7u;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = 0;
        if (m & 0x4u) lzc = 1;
        else if (m & 0x2u) lzc = 2;
        else lzc = 3;
        u.exp = (1 - 1) - static_cast<int32_t>(lzc);
        uint32_t norm_4b = (static_cast<uint32_t>(m) << lzc) & 0xFu;
        u.sig_u1p23 = norm_4b << 20;
    } else {
        u.exp = static_cast<int32_t>(e) - 1;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 20);
    }
    return u;
}

UnpackedFp unpack_fp6_e3m2(uint8_t raw6) {
    UnpackedFp u;
    raw6 &= 0x3Fu;
    u.sign = (raw6 >> 5) & 1u;
    uint8_t e = (raw6 >> 2) & 0x7u;
    uint8_t m = raw6 & 0x3u;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = (m & 0x2u) ? 1 : 2;
        u.exp = (1 - 3) - static_cast<int32_t>(lzc);
        uint32_t norm_3b = (static_cast<uint32_t>(m) << lzc) & 0x7u;
        u.sig_u1p23 = norm_3b << 21;
    } else {
        u.exp = static_cast<int32_t>(e) - 3;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 21);
    }
    return u;
}

UnpackedFp unpack_fp8_e4m3(uint8_t raw8) {
    UnpackedFp u;
    u.sign = (raw8 >> 7) & 1u;
    uint8_t e = (raw8 >> 3) & 0xFu;
    uint8_t m = raw8 & 0x7u;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0xF && m == 0x7) {
        u.is_nan = true;
        u.is_snan = false; // E4M3FN has no sNaN / no Inf
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = 0;
        if (m & 0x4u) lzc = 0;
        else if (m & 0x2u) lzc = 1;
        else lzc = 2;
        u.exp = (1 - 7) - static_cast<int32_t>(lzc) - 1;
        uint32_t norm4 = (static_cast<uint32_t>(m) << (lzc + 1)) & 0xFu;
        u.sig_u1p23 = norm4 << 20;
    } else {
        u.exp = static_cast<int32_t>(e) - 7;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 20);
    }
    return u;
}

UnpackedFp unpack_fp8_e5m2(uint8_t raw8) {
    UnpackedFp u;
    u.sign = (raw8 >> 7) & 1u;
    uint8_t e = (raw8 >> 2) & 0x1Fu;
    uint8_t m = raw8 & 0x3u;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0x1F && m == 0) {
        u.is_inf = true;
    } else if (e == 0x1F) {
        u.is_nan = true;
        u.is_snan = ((m & 0x2u) == 0u);
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = (m & 0x2u) ? 0 : 1;
        u.exp = (1 - 15) - static_cast<int32_t>(lzc) - 1;
        uint32_t norm3 = (static_cast<uint32_t>(m) << (lzc + 1)) & 0x7u;
        u.sig_u1p23 = norm3 << 21;
    } else {
        u.exp = static_cast<int32_t>(e) - 15;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 21);
    }
    return u;
}

UnpackedFp unpack_fp16(uint16_t raw16) {
    UnpackedFp u;
    u.sign = (raw16 >> 15) & 1u;
    uint16_t e = (raw16 >> 10) & 0x1Fu;
    uint16_t m = raw16 & 0x3FFu;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0x1F && m == 0) {
        u.is_inf = true;
    } else if (e == 0x1F) {
        u.is_nan = true;
        u.is_snan = ((m & 0x200u) == 0u);
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = 0;
        for (int b = 9; b >= 0; --b) {
            if ((m >> b) & 1u) {
                lzc = static_cast<uint8_t>(9 - b);
                break;
            }
        }
        u.exp = (1 - 15) - static_cast<int32_t>(lzc) - 1;
        uint32_t norm11 = (static_cast<uint32_t>(m) << (lzc + 1)) & 0x7FFu;
        u.sig_u1p23 = norm11 << 13;
    } else {
        u.exp = static_cast<int32_t>(e) - 15;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 13);
    }
    return u;
}

UnpackedFp unpack_bf16(uint16_t raw16) {
    UnpackedFp u;
    u.sign = (raw16 >> 15) & 1u;
    uint16_t e = (raw16 >> 7) & 0xFFu;
    uint16_t m = raw16 & 0x7Fu;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0xFF && m == 0) {
        u.is_inf = true;
    } else if (e == 0xFF) {
        u.is_nan = true;
        u.is_snan = ((m & 0x40u) == 0u);
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = 0;
        uint16_t m10 = static_cast<uint16_t>(m << 3);
        for (int b = 9; b >= 0; --b) {
            if ((m10 >> b) & 1u) {
                lzc = static_cast<uint8_t>(9 - b);
                break;
            }
        }
        u.exp = (1 - 127) - static_cast<int32_t>(lzc) - 1;
        uint32_t norm11 = (static_cast<uint32_t>(m10) << (lzc + 1)) & 0x7FFu;
        u.sig_u1p23 = norm11 << 13;
    } else {
        u.exp = static_cast<int32_t>(e) - 127;
        u.sig_u1p23 = (1u << 23) | (static_cast<uint32_t>(m) << 16);
    }
    return u;
}

UnpackedFp unpack_tf32(uint32_t raw32) {
    UnpackedFp u;
    u.sign = (raw32 >> 31) & 1u;
    uint32_t e = (raw32 >> 23) & 0xFFu;
    uint32_t m = (raw32 >> 13) & 0x3FFu;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0xFF && m == 0) {
        u.is_inf = true;
    } else if (e == 0xFF) {
        u.is_nan = true;
        u.is_snan = ((m & 0x200u) == 0u);
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = 0;
        for (int b = 9; b >= 0; --b) {
            if ((m >> b) & 1u) {
                lzc = static_cast<uint8_t>(9 - b);
                break;
            }
        }
        u.exp = (1 - 127) - static_cast<int32_t>(lzc) - 1;
        uint32_t norm11 = (m << (lzc + 1)) & 0x7FFu;
        u.sig_u1p23 = norm11 << 13;
    } else {
        u.exp = static_cast<int32_t>(e) - 127;
        u.sig_u1p23 = (1u << 23) | (m << 13);
    }
    return u;
}

UnpackedFp unpack_fp32(uint32_t raw32) {
    UnpackedFp u;
    u.sign = (raw32 >> 31) & 1u;
    uint32_t e = (raw32 >> 23) & 0xFFu;
    uint32_t m = raw32 & 0x7FFFFFu;
    if (e == 0 && m == 0) {
        u.is_zero = true;
    } else if (e == 0xFF && m == 0) {
        u.is_inf = true;
    } else if (e == 0xFF) {
        u.is_nan = true;
        u.is_snan = ((m & 0x400000u) == 0u);
    } else if (e == 0) {
        u.is_subnormal = true;
        uint8_t lzc = lzc_u24(m);
        u.exp = -126 - static_cast<int32_t>(lzc);
        u.sig_u1p23 = (m << lzc) & 0xFFFFFFu;
    } else {
        u.exp = static_cast<int32_t>(e) - 127;
        u.sig_u1p23 = (1u << 23) | m;
    }
    return u;
}

DecodedScale decode_scale(ScaleFmt sfmt, uint8_t raw8) {
    DecodedScale d;
    d.scale_fmt = sfmt;
    switch (sfmt) {
        case SCALE_NONE:
            d.exp_delta = 0;
            d.mant_u1p3 = 8;
            d.norm_u1p3 = 8;
            d.norm_exp = 0;
            break;
        case SCALE_UE8M0:
            if (raw8 == 0xFFu) {
                d.is_nan = true;
                d.mant_u1p3 = 0;
                d.norm_u1p3 = 0;
            } else {
                d.exp_delta = static_cast<int32_t>(raw8) - 127;
                d.mant_u1p3 = 8;
                d.norm_u1p3 = 8;
                d.norm_exp = d.exp_delta;
            }
            break;
        case SCALE_E4M3: {
            bool sign = (raw8 >> 7) & 1u;
            uint8_t e4 = (raw8 >> 3) & 0xFu;
            uint8_t m3 = raw8 & 0x7u;
            if (sign || (e4 == 0xFu && m3 == 0x7u)) {
                d.is_nan = true;
                d.mant_u1p3 = 0;
                d.norm_u1p3 = 0;
            } else if (e4 == 0 && m3 == 0) {
                d.is_zero = true;
                d.mant_u1p3 = 0;
                d.norm_u1p3 = 0;
            } else if (e4 == 0) {
                uint8_t lzc = (m3 & 0x4u) ? 1 : ((m3 & 0x2u) ? 2 : 3);
                d.exp_delta = 1 - 7;
                d.mant_u1p3 = m3;
                d.norm_u1p3 = static_cast<uint8_t>(m3 << lzc);
                d.norm_exp = d.exp_delta - static_cast<int32_t>(lzc);
            } else {
                d.exp_delta = static_cast<int32_t>(e4) - 7;
                d.mant_u1p3 = static_cast<uint8_t>(8u | m3);
                d.norm_u1p3 = d.mant_u1p3;
                d.norm_exp = d.exp_delta;
            }
            break;
        }
        default:
            d.is_nan = true;
            d.mant_u1p3 = 0;
            d.norm_u1p3 = 0;
            break;
    }
    return d;
}

// Independent exact wide fixed-point accumulator (2048-bit magnitude, signed)
// Value represented = (neg ? -1 : +1) * mag * 2^BASE_EXP, where BASE_EXP = -1024.
// Exact integer span covers 2^-1024 to 2^+1023 with zero double-rounding and zero premature truncation.
struct ExactWideAcc {
    static constexpr int BASE_EXP = -1024;
    static constexpr size_t NW    = 32; // 32 * 64 = 2048 bits
    std::array<uint64_t, NW> words{};
    bool neg = false;

    void clear() {
        words.fill(0ULL);
        neg = false;
    }

    bool is_zero() const {
        for (uint64_t w : words) {
            if (w != 0ULL) return false;
        }
        return true;
    }

    static int cmp_mag(const std::array<uint64_t, NW>& a, const std::array<uint64_t, NW>& b) {
        for (int i = static_cast<int>(NW) - 1; i >= 0; --i) {
            if (a[i] > b[i]) return 1;
            if (a[i] < b[i]) return -1;
        }
        return 0;
    }

    static void add_mag(std::array<uint64_t, NW>& dst, const std::array<uint64_t, NW>& b) {
        __uint128_t carry = 0;
        for (size_t i = 0; i < NW; ++i) {
            __uint128_t s = static_cast<__uint128_t>(dst[i]) + b[i] + carry;
            dst[i] = static_cast<uint64_t>(s);
            carry = s >> 64;
        }
    }

    // Assumes a >= b
    static void sub_mag(std::array<uint64_t, NW>& dst, const std::array<uint64_t, NW>& a, const std::array<uint64_t, NW>& b) {
        __uint128_t borrow = 0;
        for (size_t i = 0; i < NW; ++i) {
            __uint128_t ai = a[i];
            __uint128_t bi = static_cast<__uint128_t>(b[i]) + borrow;
            if (ai >= bi) {
                dst[i] = static_cast<uint64_t>(ai - bi);
                borrow = 0;
            } else {
                dst[i] = static_cast<uint64_t>(((__uint128_t(1) << 64) + ai) - bi);
                borrow = 1;
            }
        }
    }

    void add_term(bool term_neg, int32_t exp_unbiased, uint64_t sig, int sig_frac_bits) {
        if (sig == 0ULL) return;
        // term value = sig * 2^(exp_unbiased - sig_frac_bits)
        int32_t bit_pos = (exp_unbiased - sig_frac_bits) - BASE_EXP;
        std::array<uint64_t, NW> t{};
        if (bit_pos >= 0) {
            size_t word_idx = static_cast<size_t>(bit_pos) / 64;
            size_t bit_off  = static_cast<size_t>(bit_pos) % 64;
            if (word_idx < NW) {
                t[word_idx] = sig << bit_off;
                if (bit_off > 0 && (word_idx + 1) < NW) {
                    t[word_idx + 1] = sig >> (64 - bit_off);
                }
            }
        }
        if (is_zero()) {
            words = t;
            neg = term_neg;
        } else if (neg == term_neg) {
            add_mag(words, t);
        } else {
            int c = cmp_mag(words, t);
            if (c == 0) {
                clear();
            } else if (c > 0) {
                sub_mag(words, words, t);
            } else {
                sub_mag(words, t, words);
                neg = term_neg;
            }
        }
    }

    int highest_bit() const {
        for (int i = static_cast<int>(NW) - 1; i >= 0; --i) {
            if (words[i] != 0ULL) {
                return i * 64 + (63 - static_cast<int>(lzc_u64(words[i])));
            }
        }
        return -1;
    }

    bool get_bit(int bit_idx) const {
        if (bit_idx < 0 || bit_idx >= static_cast<int>(NW * 64)) return false;
        size_t w = static_cast<size_t>(bit_idx) / 64;
        size_t b = static_cast<size_t>(bit_idx) % 64;
        return ((words[w] >> b) & 1ULL) != 0ULL;
    }

    bool any_below(int bit_idx_excl) const {
        if (bit_idx_excl <= 0) return false;
        int limit = std::min(bit_idx_excl, static_cast<int>(NW * 64));
        size_t full_words = static_cast<size_t>(limit) / 64;
        size_t rem_bits   = static_cast<size_t>(limit) % 64;
        for (size_t w = 0; w < full_words; ++w) {
            if (words[w] != 0ULL) return true;
        }
        if (rem_bits > 0 && full_words < NW) {
            uint64_t mask = (1ULL << rem_bits) - 1ULL;
            if ((words[full_words] & mask) != 0ULL) return true;
        }
        return false;
    }

    FedpResult round_to_fp32(RoundMode rm, bool zero_sign_on_exact_cancel) const {
        FedpResult res;
        int msb = highest_bit();
        if (msb < 0) {
            res.d_bits = zero_sign_on_exact_cancel ? FP32_NEG_ZERO : FP32_POS_ZERO;
            return res;
        }

        int32_t norm_exp = msb + BASE_EXP;
        if (norm_exp < -126) {
            // Subnormal range: target LSB is at unbiased exponent -149
            int lsb_pos = -149 - BASE_EXP;
            uint32_t sig24 = 0;
            for (int i = 0; i < 24; ++i) {
                if (get_bit(lsb_pos + i)) {
                    sig24 |= (1u << i);
                }
            }
            bool g = get_bit(lsb_pos - 1);
            bool r = get_bit(lsb_pos - 2);
            bool s = any_below(lsb_pos - 2);
            bool inexact = g || r || s;
            bool rup = compute_round_up_grs(rm, neg, (sig24 & 1u) != 0u, g, r, s);
            uint32_t srnd = sig24 + (rup ? 1u : 0u);
            if ((srnd >> 23) & 1u) {
                // Rounded up to normal min (2^-126)
                res.d_bits = pack_fp32(neg, 1, srnd & 0x7FFFFFu);
                res.flags.nx = inexact;
                // Underflow still fires if tiny before rounding and inexact (after-rounding vs before-rounding check)
                // IEEE-754 tiny-after-rounding: exp==0; RTL checks exp==0 && inexact.
                res.flags.uf = false;
            } else if (srnd == 0u) {
                // Positive tiny underflow preserves sign (+0.0 in RM_RDN)
                res.d_bits = neg ? FP32_NEG_ZERO : FP32_POS_ZERO;
                res.flags.uf = inexact;
                res.flags.nx = inexact;
            } else {
                res.d_bits = pack_fp32(neg, 0, srnd & 0x7FFFFFu);
                res.flags.uf = inexact;
                res.flags.nx = inexact;
            }
            return res;
        }

        // Normal range: MSB is at msb, 24-bit significand sits at [msb : msb - 23]
        int lsb_pos = msb - 23;
        uint32_t sig24 = 0;
        for (int i = 0; i < 24; ++i) {
            if (get_bit(lsb_pos + i)) {
                sig24 |= (1u << i);
            }
        }
        bool g = get_bit(lsb_pos - 1);
        bool r = get_bit(lsb_pos - 2);
        bool s = any_below(lsb_pos - 2);
        bool inexact = g || r || s;
        bool rup = compute_round_up_grs(rm, neg, (sig24 & 1u) != 0u, g, r, s);
        uint32_t srnd = sig24 + (rup ? 1u : 0u);
        int32_t exp_fin = norm_exp;
        uint32_t man_fin = 0;
        if ((srnd >> 24) & 1u) {
            ++exp_fin;
            man_fin = (srnd >> 1) & 0x7FFFFFu;
        } else {
            man_fin = srnd & 0x7FFFFFu;
        }
        int32_t biased_exp = exp_fin + 127;
        if (biased_exp >= 255) {
            bool to_inf = select_ovf_to_inf(rm, neg);
            res.d_bits = to_inf ? (neg ? FP32_NEG_INF : FP32_POS_INF)
                                : (neg ? 0xFF7FFFFFu : 0x7F7FFFFFu);
            res.flags.of = true;
            res.flags.nx = true;
        } else {
            res.d_bits = pack_fp32(neg, static_cast<uint8_t>(biased_exp), man_fin);
            res.flags.nx = inexact;
        }
        return res;
    }
};

FedpResult ref_fp4_fp6_fedp(
    Fmt fmt_a, Fmt fmt_b, ScaleFmt sfmt, RoundMode rm,
    const std::vector<uint8_t>& a_bytes,
    const std::vector<uint8_t>& b_bytes,
    uint8_t scale_a, uint8_t scale_b,
    uint32_t c_fp32, bool accum_en
) {
    FedpResult res;
    size_t lanes = std::min(a_bytes.size(), b_bytes.size());
    bool fmt_valid = (fmt_is_fp4(fmt_a) || fmt_is_fp6(fmt_a)) &&
                     (fmt_is_fp4(fmt_b) || fmt_is_fp6(fmt_b));

    DecodedScale sa = decode_scale(sfmt, scale_a);
    DecodedScale sb = decode_scale(sfmt, scale_b);
    bool scale_nan = sa.is_nan || sb.is_nan;
    bool scale_zero = (!scale_nan) && (sa.is_zero || sb.is_zero);

    auto unpack_elem = [](Fmt fmt, uint8_t raw8) -> UnpackedFp {
        if (fmt == FMT_MXFP6_E2M3) return unpack_fp6_e2m3(raw8 & 0x3Fu);
        if (fmt == FMT_MXFP6_E3M2) return unpack_fp6_e3m2(raw8 & 0x3Fu);
        return unpack_fp4_e2m1(raw8 & 0xFu);
    };

    if (!fmt_valid || scale_nan) {
        res.d_bits = CANONICAL_QNAN;
        res.flags.nv = !fmt_valid;
        return res;
    }

    UnpackedFp uc = unpack_fp32(c_fp32);
    if (accum_en && uc.is_nan) {
        res.d_bits = CANONICAL_QNAN;
        res.flags.nv = uc.is_snan;
        return res;
    }
    if (accum_en && uc.is_inf) {
        res.d_bits = uc.sign ? FP32_NEG_INF : FP32_POS_INF;
        return res;
    }

    uint64_t scale_prod_u2p6 = static_cast<uint64_t>(sa.mant_u1p3) * static_cast<uint64_t>(sb.mant_u1p3);
    int32_t  scale_exp_sum   = sa.exp_delta + sb.exp_delta;
    if (scale_prod_u2p6 == 0ULL) {
        scale_zero = true;
    }

    ExactWideAcc acc;
    bool all_lanes_zero = true;
    bool all_lanes_negz = true;
    bool any_lane_negz  = false;

    for (size_t i = 0; i < lanes; ++i) {
        UnpackedFp ua = unpack_elem(fmt_a, a_bytes[i]);
        UnpackedFp ub = unpack_elem(fmt_b, b_bytes[i]);
        bool p_sign = ua.sign ^ ub.sign;
        bool p_zero = ua.is_zero || ub.is_zero || scale_zero;
        if (p_zero) {
            all_lanes_negz &= p_sign;
            any_lane_negz  |= p_sign;
        } else {
            all_lanes_zero = false;
            all_lanes_negz = false;
            // Exact product significand: a4 (u1.3 at [23:20]) * b4 (u1.3 at [23:20]) * scale_prod_u2p6 (u2.6)
            // Fractional bits = 3 + 3 + 6 = 12
            uint64_t a4 = (ua.sig_u1p23 >> 20) & 0xFu;
            uint64_t b4 = (ub.sig_u1p23 >> 20) & 0xFu;
            uint64_t exact_sig = a4 * b4 * scale_prod_u2p6;
            int32_t  exact_exp = ua.exp + ub.exp + scale_exp_sum;
            acc.add_term(p_sign, exact_exp, exact_sig, 12);
        }
    }

    bool c_zero = (!accum_en) || uc.is_zero;
    if (!c_zero) {
        acc.add_term(uc.sign, uc.exp, uc.sig_u1p23, 23);
    }

    if (all_lanes_zero && c_zero) {
        bool zsign = false;
        if (accum_en) {
            zsign = (rm == RM_RDN) ? (any_lane_negz || uc.sign) : (all_lanes_negz && uc.sign);
        } else {
            zsign = (rm == RM_RDN) ? any_lane_negz : all_lanes_negz;
        }
        res.d_bits = zsign ? FP32_NEG_ZERO : FP32_POS_ZERO;
        return res;
    }

    // IEEE-754 §6.3: exact cancellation to zero produces -0.0 iff RM_RDN
    return acc.round_to_fp32(rm, rm == RM_RDN);
}

FedpResult ref_fp8_bf16_fedp(
    Fmt fmt_a, Fmt fmt_b, ScaleFmt sfmt, RoundMode rm,
    const std::vector<uint32_t>& a_words,
    const std::vector<uint32_t>& b_words,
    uint8_t scale_a, uint8_t scale_b,
    uint32_t c_in, bool accum_en, bool int_saturate
) {
    FedpResult res;
    size_t lanes = std::min(a_words.size(), b_words.size());

    if (fmt_a == FMT_INT8 && fmt_b == FMT_INT8) {
        int64_t sum = accum_en ? static_cast<int32_t>(c_in) : 0;
        for (size_t i = 0; i < lanes; ++i) {
            int8_t av = static_cast<int8_t>(a_words[i] & 0xFFu);
            int8_t bv = static_cast<int8_t>(b_words[i] & 0xFFu);
            sum += static_cast<int64_t>(av) * static_cast<int64_t>(bv);
        }
        if (int_saturate && sum > static_cast<int64_t>(std::numeric_limits<int32_t>::max())) {
            res.d_bits = INT32_MAX_U32;
        } else if (int_saturate && sum < static_cast<int64_t>(std::numeric_limits<int32_t>::min())) {
            res.d_bits = INT32_MIN_U32;
        } else {
            res.d_bits = static_cast<uint32_t>(static_cast<int32_t>(sum));
        }
        return res;
    }

    auto unpack_w = [](Fmt f, uint32_t w) -> UnpackedFp {
        switch (f) {
            case FMT_FP8_E4M3:
            case FMT_MXFP8_E4M3: return unpack_fp8_e4m3(static_cast<uint8_t>(w & 0xFFu));
            case FMT_FP8_E5M2:
            case FMT_MXFP8_E5M2: return unpack_fp8_e5m2(static_cast<uint8_t>(w & 0xFFu));
            case FMT_BF16:       return unpack_bf16(static_cast<uint16_t>(w & 0xFFFFu));
            case FMT_FP16:       return unpack_fp16(static_cast<uint16_t>(w & 0xFFFFu));
            case FMT_TF32:       return unpack_tf32(w);
            default:             return unpack_fp32(w);
        }
    };

    bool a_mx = (fmt_a == FMT_MXFP8_E4M3) || (fmt_a == FMT_MXFP8_E5M2);
    bool b_mx = (fmt_b == FMT_MXFP8_E4M3) || (fmt_b == FMT_MXFP8_E5M2);
    bool scale_en = (sfmt != SCALE_NONE) && (a_mx || b_mx);
    DecodedScale sa = decode_scale(scale_en && a_mx ? sfmt : SCALE_NONE, scale_a);
    DecodedScale sb = decode_scale(scale_en && b_mx ? sfmt : SCALE_NONE, scale_b);
    bool scale_any_nan  = scale_en && (sa.is_nan || sb.is_nan);
    bool scale_any_zero = scale_en && (sa.is_zero || sb.is_zero);

    bool any_snan = false, any_nan = false, any_nv_zi = false, scale_inf_zero_nv = false;
    bool any_pos_inf = false, any_neg_inf = false;
    bool all_zero = true, all_neg_zero = true, any_neg_zero = false;

    uint64_t scale_prod_u2p6 = static_cast<uint64_t>(sa.mant_u1p3) * static_cast<uint64_t>(sb.mant_u1p3);
    int32_t  scale_exp_sum   = sa.exp_delta + sb.exp_delta;
    if (scale_prod_u2p6 == 0ULL) {
        scale_any_zero = true;
    }

    ExactWideAcc acc;
    for (size_t i = 0; i < lanes; ++i) {
        UnpackedFp ua = unpack_w(fmt_a, a_words[i]);
        UnpackedFp ub = unpack_w(fmt_b, b_words[i]);
        bool p_sign   = ua.sign ^ ub.sign;
        bool nv_zi    = (ua.is_zero && ub.is_inf) || (ua.is_inf && ub.is_zero);
        bool p_nan    = ua.is_nan || ub.is_nan || nv_zi;
        bool p_inf    = !p_nan && (ua.is_inf || ub.is_inf);
        bool p_zero   = !p_nan && !p_inf && (ua.is_zero || ub.is_zero);
        bool lane_inf_zero = p_inf && scale_any_zero;

        any_snan |= ua.is_snan || ub.is_snan;
        any_nv_zi |= nv_zi;
        scale_inf_zero_nv |= lane_inf_zero;

        if (p_nan || scale_any_nan || lane_inf_zero) {
            any_nan = true;
        } else if (p_inf) {
            if (p_sign) any_neg_inf = true;
            else any_pos_inf = true;
        } else if (p_zero || scale_any_zero) {
            all_neg_zero &= p_sign;
            any_neg_zero |= p_sign;
        } else {
            all_zero = false;
            all_neg_zero = false;
            // Extract exact 11-bit significands (u1.10 -> fits all FP8/BF16/FP16/TF32)
            uint64_t a11 = (ua.sig_u1p23 >> 13) & 0x7FFULL;
            uint64_t b11 = (ub.sig_u1p23 >> 13) & 0x7FFULL;
            uint64_t p22 = a11 * b11; // 20 frac bits (u2.20)
            if (scale_en) {
                uint64_t exact_sig = p22 * scale_prod_u2p6; // 26 frac bits
                int32_t  exact_exp = ua.exp + ub.exp + scale_exp_sum;
                acc.add_term(p_sign, exact_exp, exact_sig, 26);
            } else {
                acc.add_term(p_sign, ua.exp + ub.exp, p22, 20);
            }
        }
    }

    UnpackedFp uc = unpack_fp32(c_in);
    bool c_active_nan  = accum_en && uc.is_nan;
    bool c_active_snan = accum_en && uc.is_snan;
    bool c_pos_inf     = accum_en && uc.is_inf && !uc.sign;
    bool c_neg_inf     = accum_en && uc.is_inf && uc.sign;
    bool c_zero        = !accum_en || uc.is_zero;
    bool c_neg_zero    = accum_en && uc.is_zero && uc.sign;

    bool has_pos_inf = any_pos_inf || c_pos_inf;
    bool has_neg_inf = any_neg_inf || c_neg_inf;
    bool inf_cancel  = has_pos_inf && has_neg_inf;

    bool any_nan_res = any_nan || scale_any_nan || scale_inf_zero_nv || c_active_nan || inf_cancel;
    bool any_inf_res = !any_nan_res && (has_pos_inf || has_neg_inf);
    bool invalid_op  = any_snan || any_nv_zi || scale_inf_zero_nv || c_active_snan || inf_cancel;

    if (any_nan_res) {
        res.d_bits = CANONICAL_QNAN;
        res.flags.nv = invalid_op;
        return res;
    }
    if (any_inf_res) {
        res.d_bits = has_neg_inf ? FP32_NEG_INF : FP32_POS_INF;
        return res;
    }

    if (!c_zero) {
        acc.add_term(uc.sign, uc.exp, uc.sig_u1p23, 23);
    }

    if (all_zero && c_zero) {
        bool zsign = accum_en
                         ? ((rm == RM_RDN) ? (any_neg_zero || c_neg_zero) : (all_neg_zero && c_neg_zero))
                         : ((rm == RM_RDN) ? any_neg_zero : all_neg_zero);
        res.d_bits = zsign ? FP32_NEG_ZERO : FP32_POS_ZERO;
        return res;
    }

    return acc.round_to_fp32(rm, rm == RM_RDN);
}

FedpResult ref_fp32_add_exact(uint32_t a, uint32_t b, RoundMode rm) {
    FedpResult res;
    bool sa = (a >> 31) & 1u;
    bool sb = (b >> 31) & 1u;
    uint32_t ea = (a >> 23) & 0xFFu;
    uint32_t eb = (b >> 23) & 0xFFu;
    uint32_t ma = a & 0x7FFFFFu;
    uint32_t mb = b & 0x7FFFFFu;

    bool a_nan = (ea == 0xFFu) && (ma != 0u);
    bool b_nan = (eb == 0xFFu) && (mb != 0u);
    bool a_inf = (ea == 0xFFu) && (ma == 0u);
    bool b_inf = (eb == 0xFFu) && (mb == 0u);
    bool a_zero = (ea == 0u) && (ma == 0u);
    bool b_zero = (eb == 0u) && (mb == 0u);

    if (a_nan || b_nan) {
        res.flags.nv = (a_nan && ((ma & 0x400000u) == 0u)) || (b_nan && ((mb & 0x400000u) == 0u));
        res.d_bits = CANONICAL_QNAN;
        return res;
    }
    if (a_inf && b_inf) {
        if (sa != sb) {
            res.flags.nv = true;
            res.d_bits = CANONICAL_QNAN;
        } else {
            res.d_bits = sa ? FP32_NEG_INF : FP32_POS_INF;
        }
        return res;
    }
    if (a_inf) { res.d_bits = sa ? FP32_NEG_INF : FP32_POS_INF; return res; }
    if (b_inf) { res.d_bits = sb ? FP32_NEG_INF : FP32_POS_INF; return res; }
    if (a_zero && b_zero) {
        bool rs = (sa == sb) ? sa : (rm == RM_RDN);
        res.d_bits = rs ? FP32_NEG_ZERO : FP32_POS_ZERO;
        return res;
    }
    if (a_zero) { res.d_bits = b; return res; }
    if (b_zero) { res.d_bits = a; return res; }

    uint32_t sig_a = (ea == 0) ? ma : ((1u << 23) | ma);
    uint32_t sig_b = (eb == 0) ? mb : ((1u << 23) | mb);
    int32_t exp_a = (ea == 0) ? 1 : static_cast<int32_t>(ea);
    int32_t exp_b = (eb == 0) ? 1 : static_cast<int32_t>(eb);

    bool swap = (exp_b > exp_a) || (exp_b == exp_a && sig_b > sig_a);
    bool s_hi = swap ? sb : sa;
    bool s_lo = swap ? sa : sb;
    int32_t exp_hi = swap ? exp_b : exp_a;
    int32_t exp_lo = swap ? exp_a : exp_b;
    uint32_t sig_hi = swap ? sig_b : sig_a;
    uint32_t sig_lo = swap ? sig_a : sig_b;

    bool eff_sub = (s_hi != s_lo);
    int32_t shift_amt = exp_hi - exp_lo;
    uint32_t ext_hi = sig_hi << 3;
    uint32_t ext_lo = sig_lo << 3;
    bool sticky = false;
    if (shift_amt >= 28) {
        sticky = (ext_lo != 0);
        ext_lo = 0;
    } else if (shift_amt > 0) {
        uint32_t lm = (1u << shift_amt) - 1u;
        sticky = (ext_lo & lm) != 0;
        ext_lo >>= shift_amt;
    }
    ext_lo |= (sticky ? 1u : 0u);

    uint32_t sum_mag = eff_sub ? (ext_hi - ext_lo) : (ext_hi + ext_lo);
    if (sum_mag == 0) {
        res.d_bits = (rm == RM_RDN) ? FP32_NEG_ZERO : FP32_POS_ZERO;
        return res;
    }

    uint32_t norm_sig = 0;
    int32_t norm_exp = 0;
    if ((sum_mag >> 27) & 1u) {
        norm_sig = (sum_mag >> 1) | (sum_mag & 1u);
        norm_exp = exp_hi + 1;
    } else {
        uint8_t lz = 0;
        for (int k = 26; k >= 0; --k) {
            if ((sum_mag >> k) & 1u) break;
            ++lz;
        }
        if (exp_hi > static_cast<int32_t>(lz)) {
            norm_sig = (sum_mag << lz) & 0x7FFFFFFu;
            norm_exp = exp_hi - static_cast<int32_t>(lz);
        } else {
            norm_sig = (exp_hi > 1) ? ((sum_mag << (exp_hi - 1)) & 0x7FFFFFFu) : (sum_mag & 0x7FFFFFFu);
            norm_exp = 1;
        }
    }

    bool g = (norm_sig >> 2) & 1u;
    bool r = (norm_sig >> 1) & 1u;
    bool s = norm_sig & 1u;
    bool inexact = g || r || s;
    bool rup = compute_round_up_grs(rm, s_hi, ((norm_sig >> 3) & 1u) != 0u, g, r, s);
    uint32_t rounded_mant = ((norm_sig >> 3) & 0xFFFFFFu) + (rup ? 1u : 0u);
    int32_t final_exp = norm_exp;
    uint32_t final_man = 0;
    if ((rounded_mant >> 24) & 1u) {
        final_man = (rounded_mant >> 1) & 0x7FFFFFu;
        final_exp = norm_exp + 1;
    } else {
        final_man = rounded_mant & 0x7FFFFFu;
    }
    bool ovf = (final_exp >= 255);
    bool unf = (final_exp == 1) && (((rounded_mant >> 23) & 1u) == 0u) && inexact;
    res.flags.nx = inexact || ovf;
    res.flags.of = ovf;
    res.flags.uf = unf;
    if (ovf) {
        if (rm == RM_RTZ) res.d_bits = pack_fp32(s_hi, 0xFEu, 0x7FFFFFu);
        else if (rm == RM_RDN) res.d_bits = s_hi ? FP32_NEG_INF : pack_fp32(false, 0xFEu, 0x7FFFFFu);
        else if (rm == RM_RUP) res.d_bits = s_hi ? pack_fp32(true, 0xFEu, 0x7FFFFFu) : FP32_POS_INF;
        else res.d_bits = s_hi ? FP32_NEG_INF : FP32_POS_INF;
    } else if (final_exp == 1 && (((rounded_mant >> 23) & 1u) == 0u)) {
        res.d_bits = pack_fp32(s_hi, 0, final_man);
    } else {
        res.d_bits = pack_fp32(s_hi, static_cast<uint8_t>(final_exp), final_man);
    }
    return res;
}

uint32_t ref_fp32_mul_rne(uint32_t a, uint32_t b) {
    bool sa = (a >> 31) & 1u;
    bool sb = (b >> 31) & 1u;
    bool sr = sa ^ sb;
    uint32_t ea = (a >> 23) & 0xFFu;
    uint32_t eb = (b >> 23) & 0xFFu;
    uint32_t ma = a & 0x7FFFFFu;
    uint32_t mb = b & 0x7FFFFFu;

    bool a_nan = (ea == 0xFFu) && (ma != 0u);
    bool b_nan = (eb == 0xFFu) && (mb != 0u);
    bool a_inf = (ea == 0xFFu) && (ma == 0u);
    bool b_inf = (eb == 0xFFu) && (mb == 0u);
    bool a_zero = (ea == 0u) && (ma == 0u);
    bool b_zero = (eb == 0u) && (mb == 0u);

    if (a_nan || b_nan || (a_inf && b_zero) || (b_inf && a_zero)) {
        return CANONICAL_QNAN;
    }
    if (a_inf || b_inf) return sr ? FP32_NEG_INF : FP32_POS_INF;
    if (a_zero || b_zero) return sr ? FP32_NEG_ZERO : FP32_POS_ZERO;

    uint32_t sig_a = (ea == 0) ? ma : ((1u << 23) | ma);
    uint32_t sig_b = (eb == 0) ? mb : ((1u << 23) | mb);
    int32_t exp_a = (ea == 0) ? 1 : static_cast<int32_t>(ea);
    int32_t exp_b = (eb == 0) ? 1 : static_cast<int32_t>(eb);

    uint8_t lz_a = lzc_u24(sig_a);
    uint8_t lz_b = lzc_u24(sig_b);
    sig_a = (sig_a << lz_a) & 0xFFFFFFu;
    sig_b = (sig_b << lz_b) & 0xFFFFFFu;
    exp_a -= lz_a;
    exp_b -= lz_b;

    uint64_t prod = static_cast<uint64_t>(sig_a) * static_cast<uint64_t>(sig_b);
    int32_t exp_prod = exp_a + exp_b - 127;
    uint32_t mant24 = 0;
    bool g = false, r = false, s = false;
    if ((prod >> 47) & 1ULL) {
        ++exp_prod;
        mant24 = static_cast<uint32_t>((prod >> 24) & 0xFFFFFFULL);
        g = (prod >> 23) & 1ULL;
        r = (prod >> 22) & 1ULL;
        s = (prod & 0x3FFFFFULL) != 0ULL;
    } else {
        mant24 = static_cast<uint32_t>((prod >> 23) & 0xFFFFFFULL);
        g = (prod >> 22) & 1ULL;
        r = (prod >> 21) & 1ULL;
        s = (prod & 0x1FFFFFULL) != 0ULL;
    }
    if (exp_prod <= 0) {
        int32_t rsh = 1 - exp_prod;
        if (rsh >= 26) return sr ? FP32_NEG_ZERO : FP32_POS_ZERO;
        uint32_t pack = (mant24 << 3) | (g ? 4u : 0u) | (r ? 2u : 0u) | (s ? 1u : 0u);
        uint32_t lm = (1u << rsh) - 1u;
        bool sub_s = (pack & lm) != 0u;
        pack >>= rsh;
        mant24 = (pack >> 3) & 0xFFFFFFu;
        g = (pack >> 2) & 1u;
        r = (pack >> 1) & 1u;
        s = ((pack & 1u) != 0u) || sub_s;
        exp_prod = 1;
    }
    bool rup = g && (r || s || ((mant24 & 1u) != 0u));
    uint32_t mrnd = mant24 + (rup ? 1u : 0u);
    int32_t efin = exp_prod;
    uint32_t mfin = 0;
    if ((mrnd >> 24) & 1u) {
        mfin = (mrnd >> 1) & 0x7FFFFFu;
        ++efin;
    } else {
        mfin = mrnd & 0x7FFFFFu;
    }
    if (efin >= 255) return sr ? FP32_NEG_INF : FP32_POS_INF;
    if (efin == 1 && (((mrnd >> 23) & 1u) == 0u)) return pack_fp32(sr, 0, mfin);
    return pack_fp32(sr, static_cast<uint8_t>(efin), mfin);
}

FedpResult ref_int32_add_exact(uint32_t a, uint32_t b, bool saturate) {
    FedpResult res;
    int32_t sa = static_cast<int32_t>(a);
    int32_t sb = static_cast<int32_t>(b);
    uint32_t sum = static_cast<uint32_t>(sa) + static_cast<uint32_t>(sb);
    bool ovf_pos = ((a >> 31) == 0u) && ((b >> 31) == 0u) && ((sum >> 31) == 1u);
    bool ovf_neg = ((a >> 31) == 1u) && ((b >> 31) == 1u) && ((sum >> 31) == 0u);
    if (saturate && ovf_pos) {
        res.d_bits = INT32_MAX_U32;
        res.flags.of = true;
        res.flags.nx = true;
    } else if (saturate && ovf_neg) {
        res.d_bits = INT32_MIN_U32;
        res.flags.of = true;
        res.flags.nx = true;
    } else {
        res.d_bits = sum;
        res.flags.of = ovf_pos || ovf_neg;
    }
    return res;
}

FedpResult ref_epilogue_act(uint32_t x, ActMode act, uint32_t clamp_min, uint32_t clamp_max, bool is_int) {
    FedpResult res;
    if (is_int) {
        int32_t vx = static_cast<int32_t>(x);
        int32_t lo = static_cast<int32_t>(clamp_min);
        int32_t hi = static_cast<int32_t>(clamp_max);
        if (act == ACT_RELU) {
            res.d_bits = (vx < 0) ? 0u : x;
        } else if (act == ACT_CLAMP) {
            if (lo > hi) res.d_bits = x;
            else res.d_bits = static_cast<uint32_t>(std::clamp(vx, lo, hi));
        } else {
            res.d_bits = x;
        }
        return res;
    }

    if (act == ACT_CLAMP && fp32_lt_total(clamp_max, clamp_min)) {
        res.d_bits = CANONICAL_QNAN;
        res.flags.nv = true;
        return res;
    }

    switch (act) {
        case ACT_NONE:
            res.d_bits = fp32_is_nan(x) ? CANONICAL_QNAN : x;
            break;
        case ACT_RELU:
            if (fp32_is_nan(x)) res.d_bits = CANONICAL_QNAN;
            else if ((x >> 31) & 1u) res.d_bits = FP32_POS_ZERO;
            else res.d_bits = x;
            break;
        case ACT_CLAMP:
            if (fp32_is_nan(x) || fp32_is_nan(clamp_min) || fp32_is_nan(clamp_max)) {
                res.d_bits = CANONICAL_QNAN;
            } else if (fp32_lt_total(x, clamp_min)) {
                res.d_bits = clamp_min;
            } else if (fp32_lt_total(clamp_max, x)) {
                res.d_bits = clamp_max;
            } else {
                res.d_bits = x;
            }
            break;
        case ACT_SILU: {
            if (fp32_is_nan(x)) { res.d_bits = CANONICAL_QNAN; break; }
            if (!fp32_is_zero(x)) res.flags.nx = true;
            if (fp32_is_inf(x)) { res.d_bits = ((x >> 31) & 1u) ? FP32_POS_ZERO : FP32_POS_INF; break; }
            uint32_t ax = fp32_abs(x);
            uint32_t sig_pos = 0x3F800000u;
            if (!fp32_lt_total(ax, 0x3F800000u)) {
                if (!fp32_lt_total(ax, 0x40800000u)) {
                    if (!fp32_lt_total(ax, 0x40A00000u)) {
                        sig_pos = 0x3F800000u;
                    } else {
                        uint32_t term = ref_fp32_mul_rne(0x3C9374BCu, ref_fp32_add_exact(ax, 0xC0800000u, RM_RNE).d_bits);
                        sig_pos = ref_fp32_add_exact(0x3F7B645Au, term, RM_RNE).d_bits;
                    }
                } else if (!fp32_lt_total(ax, 0x40180000u)) {
                    uint32_t term = ref_fp32_mul_rne(0x3D28BE62u, ref_fp32_add_exact(ax, 0xC0180000u, RM_RNE).d_bits);
                    sig_pos = ref_fp32_add_exact(0x3F6A3D71u, term, RM_RNE).d_bits;
                } else {
                    uint32_t term = ref_fp32_mul_rne(0x3E0902DEu, ref_fp32_add_exact(ax, 0xBF800000u, RM_RNE).d_bits);
                    sig_pos = ref_fp32_add_exact(0x3F3B22D1u, term, RM_RNE).d_bits;
                }
            } else {
                uint32_t term = ref_fp32_mul_rne(0x3E6CA5E4u, ax);
                sig_pos = ref_fp32_add_exact(0x3F000000u, term, RM_RNE).d_bits;
            }
            uint32_t sig_val = ((x >> 31) & 1u)
                                   ? ref_fp32_add_exact(0x3F800000u, 0x80000000u | (sig_pos & 0x7FFFFFFFu), RM_RNE).d_bits
                                   : sig_pos;
            res.d_bits = ref_fp32_mul_rne(x, sig_val);
            break;
        }
        case ACT_GELU: {
            if (fp32_is_nan(x)) { res.d_bits = CANONICAL_QNAN; break; }
            if (!fp32_is_zero(x)) res.flags.nx = true;
            if (fp32_is_inf(x)) { res.d_bits = ((x >> 31) & 1u) ? FP32_POS_ZERO : FP32_POS_INF; break; }
            uint32_t ax = fp32_abs(x);
            uint32_t phi_pos = 0x3F800000u;
            if (!fp32_lt_total(ax, 0x40400000u)) {
                phi_pos = 0x3F800000u;
            } else if (!fp32_lt_total(ax, 0x3FC00000u)) {
                uint32_t term = ref_fp32_mul_rne(0x3D3295E9u, ref_fp32_add_exact(ax, 0xBFC00000u, RM_RNE).d_bits);
                phi_pos = ref_fp32_add_exact(0x3F6EE632u, term, RM_RNE).d_bits;
            } else if (!fp32_lt_total(ax, 0x3F400000u)) {
                uint32_t term = ref_fp32_mul_rne(0x3E5A36E3u, ref_fp32_add_exact(ax, 0xBF400000u, RM_RNE).d_bits);
                phi_pos = ref_fp32_add_exact(0x3F45FCBBu, term, RM_RNE).d_bits;
            } else {
                uint32_t term = ref_fp32_mul_rne(0x3EBA9FBEu, ax);
                phi_pos = ref_fp32_add_exact(0x3F000000u, term, RM_RNE).d_bits;
            }
            uint32_t phi_val = ((x >> 31) & 1u)
                                   ? ref_fp32_add_exact(0x3F800000u, 0x80000000u | (phi_pos & 0x7FFFFFFFu), RM_RNE).d_bits
                                   : phi_pos;
            res.d_bits = ref_fp32_mul_rne(x, phi_val);
            break;
        }
        default:
            res.d_bits = fp32_is_nan(x) ? CANONICAL_QNAN : x;
            break;
    }
    return res;
}

FedpResult ref_epilogue_cast(uint32_t val, Fmt fmt_d, RoundMode rm, bool src_is_int,
                             bool dyn_scale_en, uint32_t dyn_scale_fp32) {
    FedpResult res;
    if (dyn_scale_en && !src_is_int) {
        uint32_t scaled = ref_fp32_mul_rne(val, dyn_scale_fp32);
        if (fp32_is_inf(scaled) && !fp32_is_inf(val) && !fp32_is_inf(dyn_scale_fp32)) {
            res.flags.of = true;
            res.flags.nx = true;
        }
        if (fp32_is_nan(scaled) && !fp32_is_nan(val) && !fp32_is_nan(dyn_scale_fp32)) {
            res.flags.nv = true;
        }
        val = scaled;
    }

    bool s = (val >> 31) & 1u;
    uint32_t e = (val >> 23) & 0xFFu;
    uint32_t m = val & 0x7FFFFFu;

    switch (fmt_d) {
        case FMT_FP32:
        case FMT_I32:
            res.d_bits = val;
            break;
        case FMT_BF16: {
            if (e == 0xFFu) {
                if (m != 0u) {
                    res.flags.nv |= ((m & 0x400000u) == 0u);
                    res.d_bits = 0x7FC0u;
                } else {
                    res.d_bits = (static_cast<uint32_t>(s) << 15) | 0x7F80u;
                }
                break;
            }
            bool guard = (m >> 15) & 1u;
            bool sticky = (m & 0x7FFFu) != 0u;
            bool inexact = guard || sticky;
            bool rup = round_decision(s, ((m >> 16) & 1u) != 0u, guard, sticky, rm);
            uint32_t bf_mag = ((e << 7) | (m >> 16)) + (rup ? 1u : 0u);
            if (((bf_mag >> 15) & 1u) || (((bf_mag >> 7) & 0xFFu) == 0xFFu)) {
                res.flags.of = true;
                res.flags.nx = true;
                bool to_inf = select_ovf_to_inf(rm, s);
                res.d_bits = (static_cast<uint32_t>(s) << 15) | (to_inf ? 0x7F80u : 0x7F7Fu);
            } else {
                uint32_t bf16 = (static_cast<uint32_t>(s) << 15) | (bf_mag & 0x7FFFu);
                res.flags.nx |= inexact;
                res.flags.uf = (((bf16 >> 7) & 0xFFu) == 0u) && inexact;
                res.d_bits = bf16;
            }
            break;
        }
        case FMT_FP16: {
            if (e == 0xFFu) {
                if (m != 0u) {
                    res.flags.nv |= ((m & 0x400000u) == 0u);
                    res.d_bits = 0x7E00u;
                } else {
                    res.d_bits = (static_cast<uint32_t>(s) << 15) | 0x7C00u;
                }
                break;
            }
            if (e == 0u && m == 0u) {
                res.d_bits = static_cast<uint32_t>(s) << 15;
                break;
            }
            int32_t exp_unbiased = (e == 0u) ? -126 : (static_cast<int32_t>(e) - 127);
            uint32_t sig = (e == 0u) ? m : ((1u << 23) | m);
            int32_t exp16 = exp_unbiased + 15;
            if (exp16 >= 31) {
                res.flags.of = true;
                res.flags.nx = true;
                bool to_inf = select_ovf_to_inf(rm, s);
                res.d_bits = (static_cast<uint32_t>(s) << 15) | (to_inf ? 0x7C00u : 0x7BFFu);
                break;
            }
            uint32_t mant11 = 0;
            bool guard = false, sticky = false;
            if (exp16 <= 0) {
                int32_t rsh = 1 - exp16;
                if (rsh >= 25) {
                    bool to_min_sub = ((rm == RM_RUP) && !s) || ((rm == RM_RDN) && s);
                    res.flags.uf = true;
                    res.flags.nx = true;
                    res.d_bits = (static_cast<uint32_t>(s) << 15) | (to_min_sub ? 1u : 0u);
                    break;
                }
                uint32_t pack = sig << 1;
                uint32_t lm = (1u << (rsh + 13)) - 1u;
                sticky = (pack & lm) != 0u;
                pack >>= rsh;
                mant11 = (pack >> 14) & 0x7FFu;
                guard = (pack >> 13) & 1u;
                exp16 = 0;
            } else {
                mant11 = (sig >> 13) & 0x7FFu;
                guard = (sig >> 12) & 1u;
                sticky = (sig & 0xFFFu) != 0u;
            }
            bool inexact = guard || sticky;
            bool rup = round_decision(s, (mant11 & 1u) != 0u, guard, sticky, rm);
            uint32_t mrnd = mant11 + (rup ? 1u : 0u);
            uint32_t fp16 = 0;
            if (exp16 == 0 && ((mrnd >> 10) & 1u)) {
                exp16 = 1;
                fp16 = (static_cast<uint32_t>(s) << 15) | (1u << 10) | (mrnd & 0x3FFu);
            } else if ((mrnd >> 11) & 1u) {
                ++exp16;
                if (exp16 >= 31) {
                    res.flags.of = true;
                    bool to_inf = select_ovf_to_inf(rm, s);
                    fp16 = (static_cast<uint32_t>(s) << 15) | (to_inf ? 0x7C00u : 0x7BFFu);
                } else {
                    fp16 = (static_cast<uint32_t>(s) << 15) | (static_cast<uint32_t>(exp16) << 10) | ((mrnd >> 1) & 0x3FFu);
                }
            } else {
                fp16 = (static_cast<uint32_t>(s) << 15) | (static_cast<uint32_t>(exp16) << 10) | (mrnd & 0x3FFu);
            }
            res.flags.nx |= inexact || res.flags.of;
            res.flags.uf |= (exp16 == 0) && inexact;
            res.d_bits = fp16;
            break;
        }
        case FMT_FP8_E4M3:
        case FMT_MXFP8_E4M3: {
            if (e == 0xFFu) {
                res.flags.nv |= (m == 0u) || ((m & 0x400000u) == 0u);
                res.flags.of |= (m == 0u);
                res.d_bits = (m == 0u) ? ((static_cast<uint32_t>(s) << 7) | 0x7Eu)
                                       : ((static_cast<uint32_t>(s) << 7) | 0x7Fu);
                break;
            }
            if (e == 0u && m == 0u) {
                res.d_bits = static_cast<uint32_t>(s) << 7;
                break;
            }
            int32_t exp_unbiased = (e == 0u) ? -126 : (static_cast<int32_t>(e) - 127);
            uint32_t sig = (e == 0u) ? m : ((1u << 23) | m);
            int32_t exp8 = exp_unbiased + 7;
            if (exp8 > 15) {
                res.flags.of = true;
                res.flags.nx = true;
                res.d_bits = (static_cast<uint32_t>(s) << 7) | 0x7Eu;
                break;
            }
            uint32_t mant4 = 0;
            bool guard = false, sticky = false;
            if (exp8 <= 0) {
                int32_t rsh = 1 - exp8;
                if (rsh >= 8) {
                    bool to_min_sub = ((rm == RM_RUP) && !s) || ((rm == RM_RDN) && s);
                    res.flags.uf = true;
                    res.flags.nx = true;
                    res.d_bits = (static_cast<uint32_t>(s) << 7) | (to_min_sub ? 1u : 0u);
                    break;
                }
                uint32_t pack = sig << 1;
                uint32_t lm = (1u << (rsh + 20)) - 1u;
                sticky = ((pack & 0xFFFFFu) != 0u) || ((pack & lm) != 0u);
                pack >>= rsh;
                mant4 = (pack >> 21) & 0xFu;
                guard = (pack >> 20) & 1u;
                exp8 = 0;
            } else {
                mant4 = (sig >> 20) & 0xFu;
                guard = (sig >> 19) & 1u;
                sticky = (sig & 0x7FFFFu) != 0u;
            }
            bool inexact = guard || sticky;
            bool rup = round_decision(s, (mant4 & 1u) != 0u, guard, sticky, rm);
            uint32_t mrnd = mant4 + (rup ? 1u : 0u);
            uint32_t fp8 = 0;
            if (exp8 == 0 && ((mrnd >> 3) & 1u)) {
                exp8 = 1;
                fp8 = (static_cast<uint32_t>(s) << 7) | (1u << 3) | (mrnd & 0x7u);
            } else if ((mrnd >> 4) & 1u) {
                ++exp8;
                if (exp8 > 15 || (exp8 == 15 && ((mrnd >> 1) & 0x7u) == 0x7u)) {
                    res.flags.of = true;
                    fp8 = (static_cast<uint32_t>(s) << 7) | 0x7Eu;
                } else {
                    fp8 = (static_cast<uint32_t>(s) << 7) | (static_cast<uint32_t>(exp8) << 3) | ((mrnd >> 1) & 0x7u);
                }
            } else if (exp8 == 15 && (mrnd & 0x7u) == 0x7u) {
                res.flags.of = true;
                fp8 = (static_cast<uint32_t>(s) << 7) | 0x7Eu;
            } else {
                fp8 = (static_cast<uint32_t>(s) << 7) | (static_cast<uint32_t>(exp8) << 3) | (mrnd & 0x7u);
            }
            res.flags.nx |= inexact || res.flags.of;
            res.flags.uf |= (exp8 == 0) && inexact;
            res.d_bits = fp8;
            break;
        }
        case FMT_FP8_E5M2:
        case FMT_MXFP8_E5M2: {
            if (e == 0xFFu) {
                if (m != 0u) {
                    res.flags.nv |= ((m & 0x400000u) == 0u);
                    res.d_bits = (static_cast<uint32_t>(s) << 7) | 0x7Eu;
                } else {
                    res.d_bits = (static_cast<uint32_t>(s) << 7) | 0x7Cu;
                }
                break;
            }
            if (e == 0u && m == 0u) {
                res.d_bits = static_cast<uint32_t>(s) << 7;
                break;
            }
            int32_t exp_unbiased = (e == 0u) ? -126 : (static_cast<int32_t>(e) - 127);
            uint32_t sig = (e == 0u) ? m : ((1u << 23) | m);
            int32_t exp8 = exp_unbiased + 15;
            if (exp8 >= 31) {
                res.flags.of = true;
                res.flags.nx = true;
                bool to_inf = select_ovf_to_inf(rm, s);
                res.d_bits = (static_cast<uint32_t>(s) << 7) | (to_inf ? 0x7Cu : 0x7Bu);
                break;
            }
            uint32_t mant3 = 0;
            bool guard = false, sticky = false;
            if (exp8 <= 0) {
                int32_t rsh = 1 - exp8;
                if (rsh >= 6) {
                    bool to_min_sub = ((rm == RM_RUP) && !s) || ((rm == RM_RDN) && s);
                    res.flags.uf = true;
                    res.flags.nx = true;
                    res.d_bits = (static_cast<uint32_t>(s) << 7) | (to_min_sub ? 1u : 0u);
                    break;
                }
                uint32_t pack = sig << 1;
                uint32_t lm = (1u << (rsh + 21)) - 1u;
                sticky = ((pack & 0x1FFFFFu) != 0u) || ((pack & lm) != 0u);
                pack >>= rsh;
                mant3 = (pack >> 22) & 0x7u;
                guard = (pack >> 21) & 1u;
                exp8 = 0;
            } else {
                mant3 = (sig >> 21) & 0x7u;
                guard = (sig >> 20) & 1u;
                sticky = (sig & 0xFFFFFu) != 0u;
            }
            bool inexact = guard || sticky;
            bool rup = round_decision(s, (mant3 & 1u) != 0u, guard, sticky, rm);
            uint32_t mrnd = mant3 + (rup ? 1u : 0u);
            uint32_t fp8 = 0;
            if (exp8 == 0 && ((mrnd >> 2) & 1u)) {
                exp8 = 1;
                fp8 = (static_cast<uint32_t>(s) << 7) | (1u << 2) | (mrnd & 0x3u);
            } else if ((mrnd >> 3) & 1u) {
                ++exp8;
                if (exp8 >= 31) {
                    res.flags.of = true;
                    bool to_inf = select_ovf_to_inf(rm, s);
                    fp8 = (static_cast<uint32_t>(s) << 7) | (to_inf ? 0x7Cu : 0x7Bu);
                } else {
                    fp8 = (static_cast<uint32_t>(s) << 7) | (static_cast<uint32_t>(exp8) << 2) | ((mrnd >> 1) & 0x3u);
                }
            } else {
                fp8 = (static_cast<uint32_t>(s) << 7) | (static_cast<uint32_t>(exp8) << 2) | (mrnd & 0x3u);
            }
            res.flags.nx |= inexact || res.flags.of;
            res.flags.uf |= (exp8 == 0) && inexact;
            res.d_bits = fp8;
            break;
        }
        case FMT_INT8: {
            if (src_is_int) {
                int32_t iv = static_cast<int32_t>(val);
                if (iv > 127) { res.d_bits = 0x7Fu; res.flags.of = true; res.flags.nx = true; }
                else if (iv < -128) { res.d_bits = 0xFFFFFF80u; res.flags.of = true; res.flags.nx = true; }
                else { res.d_bits = static_cast<uint32_t>(static_cast<int32_t>(static_cast<int8_t>(iv))); }
                break;
            }
            if (fp32_is_nan(val)) { res.flags.nv = true; res.d_bits = 0; break; }
            if (fp32_is_inf(val)) {
                res.flags.of = true;
                res.flags.nx = true;
                res.d_bits = s ? 0xFFFFFF80u : 0x7Fu;
                break;
            }
            if (fp32_is_zero(val)) { res.d_bits = 0; break; }
            int32_t exp_unbiased = (e == 0u) ? -126 : (static_cast<int32_t>(e) - 127);
            uint32_t sig = (e == 0u) ? m : ((1u << 23) | m);
            uint32_t mag = 0;
            bool half_bit = false, sticky_f = false, frac_any = false;
            if (exp_unbiased < 0) {
                mag = 0;
                half_bit = (exp_unbiased == -1) && ((sig >> 23) & 1u);
                sticky_f = (exp_unbiased < -1) || ((sig & 0x7FFFFFu) != 0u);
                frac_any = true;
            } else if (exp_unbiased >= 8) {
                res.flags.of = true;
                res.flags.nx = true;
                res.d_bits = s ? 0xFFFFFF80u : 0x7Fu;
                break;
            } else {
                uint32_t shifted = sig << exp_unbiased;
                mag = shifted >> 23;
                half_bit = (shifted >> 22) & 1u;
                sticky_f = (shifted & 0x3FFFFFu) != 0u;
                frac_any = half_bit || sticky_f;
            }
            bool inc = round_decision(s, (mag & 1u) != 0u, half_bit, sticky_f, rm);
            mag += inc ? 1u : 0u;
            int32_t smag = s ? -static_cast<int32_t>(mag) : static_cast<int32_t>(mag);
            res.flags.nx |= frac_any;
            if (smag > 127) {
                res.flags.of = true; res.flags.nx = true; res.d_bits = 0x7Fu;
            } else if (smag < -128) {
                res.flags.of = true; res.flags.nx = true; res.d_bits = 0xFFFFFF80u;
            } else {
                res.d_bits = static_cast<uint32_t>(static_cast<int32_t>(static_cast<int8_t>(smag)));
            }
            break;
        }
        default:
            res.d_bits = val;
            break;
    }
    return res;
}

bool sparse_pair_legal(uint8_t meta4) {
    uint8_t idx0 = meta4 & 0x3u;
    uint8_t idx1 = (meta4 >> 2) & 0x3u;
    return idx0 < idx1;
}

static uint8_t pick_top2_meta4(const std::array<uint32_t, 4>& mags, bool& prune_loss) {
    uint8_t nz_cnt = 0;
    for (int i = 0; i < 4; ++i) {
        if (mags[i] != 0) ++nz_cnt;
    }
    uint8_t max_idx = 0;
    uint32_t max_val = mags[0];
    for (int i = 1; i < 4; ++i) {
        if (mags[i] > max_val) {
            max_val = mags[i];
            max_idx = static_cast<uint8_t>(i);
        }
    }
    uint8_t sec_idx = (max_idx == 0) ? 1 : 0;
    uint32_t sec_val = mags[sec_idx];
    for (int i = 0; i < 4; ++i) {
        if (i != max_idx) {
            if (mags[i] > sec_val || (mags[i] == sec_val && i < sec_idx)) {
                sec_val = mags[i];
                sec_idx = static_cast<uint8_t>(i);
            }
        }
    }
    uint8_t idx_a = 0, idx_b = 1;
    if (nz_cnt == 0) {
        idx_a = 0; idx_b = 1;
    } else if (nz_cnt == 1) {
        idx_a = 0; idx_b = (max_idx == 0) ? 1 : max_idx;
    } else {
        idx_a = std::min(max_idx, sec_idx);
        idx_b = std::max(max_idx, sec_idx);
    }
    prune_loss = (nz_cnt > 2);
    return static_cast<uint8_t>((idx_b << 2) | idx_a);
}

void ref_sparse_compress_row(
    Fmt fmt_a, int array_k,
    const std::vector<uint32_t>& dense_lo,
    const std::vector<uint32_t>& dense_hi,
    std::vector<uint32_t>& comp_out,
    std::vector<uint8_t>& meta_bytes_out,
    bool& prune_loss_out
) {
    comp_out.assign(array_k, 0u);
    meta_bytes_out.assign(array_k * 2, 0u);
    prune_loss_out = false;

    auto set_nibble = [&](int grp, uint8_t m4) {
        meta_bytes_out[grp / 2] |= (m4 & 0xFu) << ((grp % 2) * 4);
    };

    if (fmt_a == FMT_TF32) {
        for (int g = 0; g < array_k / 2; ++g) {
            std::array<uint32_t, 4> el{dense_lo[2 * g], dense_lo[2 * g + 1], dense_hi[2 * g], dense_hi[2 * g + 1]};
            std::array<uint32_t, 4> mg{};
            for (int i = 0; i < 4; ++i) mg[i] = sparse_mag_key(fmt_a, el[i]);
            bool loss = false;
            uint8_t m4 = pick_top2_meta4(mg, loss);
            prune_loss_out |= loss;
            comp_out[2 * g] = el[m4 & 3u];
            comp_out[2 * g + 1] = el[(m4 >> 2) & 3u];
            set_nibble(g, m4);
        }
    } else if (fmt_a == FMT_FP16 || fmt_a == FMT_BF16) {
        for (int k = 0; k < array_k; ++k) {
            std::array<uint32_t, 4> el{
                dense_lo[k] & 0xFFFFu, (dense_lo[k] >> 16) & 0xFFFFu,
                dense_hi[k] & 0xFFFFu, (dense_hi[k] >> 16) & 0xFFFFu
            };
            std::array<uint32_t, 4> mg{};
            for (int i = 0; i < 4; ++i) mg[i] = sparse_mag_key(fmt_a, el[i]);
            bool loss = false;
            uint8_t m4 = pick_top2_meta4(mg, loss);
            prune_loss_out |= loss;
            comp_out[k] = (el[m4 & 3u] & 0xFFFFu) | ((el[(m4 >> 2) & 3u] & 0xFFFFu) << 16);
            set_nibble(k, m4);
        }
    } else if (fmt_is_fp8(fmt_a) || fmt_a == FMT_INT8) {
        for (int k = 0; k < array_k; ++k) {
            std::array<uint32_t, 4> el_lo{dense_lo[k] & 0xFFu, (dense_lo[k] >> 8) & 0xFFu,
                                          dense_hi[k] & 0xFFu, (dense_hi[k] >> 8) & 0xFFu};
            std::array<uint32_t, 4> el_hi{(dense_lo[k] >> 16) & 0xFFu, (dense_lo[k] >> 24) & 0xFFu,
                                          (dense_hi[k] >> 16) & 0xFFu, (dense_hi[k] >> 24) & 0xFFu};
            std::array<uint32_t, 4> mg_lo{}, mg_hi{};
            for (int i = 0; i < 4; ++i) {
                mg_lo[i] = sparse_mag_key(fmt_a, el_lo[i]);
                mg_hi[i] = sparse_mag_key(fmt_a, el_hi[i]);
            }
            bool l0 = false, l1 = false;
            uint8_t m0 = pick_top2_meta4(mg_lo, l0);
            uint8_t m1 = pick_top2_meta4(mg_hi, l1);
            prune_loss_out |= (l0 || l1);
            comp_out[k] = (el_lo[m0 & 3u] & 0xFFu) | ((el_lo[(m0 >> 2) & 3u] & 0xFFu) << 8) |
                          ((el_hi[m1 & 3u] & 0xFFu) << 16) | ((el_hi[(m1 >> 2) & 3u] & 0xFFu) << 24);
            set_nibble(2 * k, m0);
            set_nibble(2 * k + 1, m1);
        }
    } else if (fmt_is_fp6(fmt_a)) {
        for (int k = 0; k < array_k; ++k) {
            std::array<uint32_t, 4> el_lo{dense_lo[k] & 0x3Fu, (dense_lo[k] >> 8) & 0x3Fu,
                                          dense_hi[k] & 0x3Fu, (dense_hi[k] >> 8) & 0x3Fu};
            std::array<uint32_t, 4> el_hi{(dense_lo[k] >> 16) & 0x3Fu, (dense_lo[k] >> 24) & 0x3Fu,
                                          (dense_hi[k] >> 16) & 0x3Fu, (dense_hi[k] >> 24) & 0x3Fu};
            std::array<uint32_t, 4> mg_lo{}, mg_hi{};
            for (int i = 0; i < 4; ++i) {
                mg_lo[i] = sparse_mag_key(fmt_a, el_lo[i]);
                mg_hi[i] = sparse_mag_key(fmt_a, el_hi[i]);
            }
            bool l0 = false, l1 = false;
            uint8_t m0 = pick_top2_meta4(mg_lo, l0);
            uint8_t m1 = pick_top2_meta4(mg_hi, l1);
            prune_loss_out |= (l0 || l1);
            comp_out[k] = (el_lo[m0 & 3u] & 0x3Fu) | ((el_lo[(m0 >> 2) & 3u] & 0x3Fu) << 8) |
                          ((el_hi[m1 & 3u] & 0x3Fu) << 16) | ((el_hi[(m1 >> 2) & 3u] & 0x3Fu) << 24);
            set_nibble(2 * k, m0);
            set_nibble(2 * k + 1, m1);
        }
    } else {
        // FP4: 4 groups of 4 nibbles (8 nibbles per 32-bit word)
        for (int k = 0; k < array_k; ++k) {
            uint32_t packed = 0u;
            for (int q = 0; q < 4; ++q) {
                int sh = q * 8;
                std::array<uint32_t, 4> el{
                    (dense_lo[k] >> sh) & 0xFu, (dense_lo[k] >> (sh + 4)) & 0xFu,
                    (dense_hi[k] >> sh) & 0xFu, (dense_hi[k] >> (sh + 4)) & 0xFu
                };
                std::array<uint32_t, 4> mg{};
                for (int i = 0; i < 4; ++i) mg[i] = sparse_mag_key(fmt_a, el[i]);
                bool loss = false;
                uint8_t mq = pick_top2_meta4(mg, loss);
                prune_loss_out |= loss;
                packed |= ((el[mq & 3u] & 0xFu) << sh) | ((el[(mq >> 2) & 3u] & 0xFu) << (sh + 4));
                set_nibble(4 * k + q, mq);
            }
            comp_out[k] = packed;
        }
    }
}

bool ref_sparse_validate_row(
    Fmt fmt_a, int array_k,
    const std::vector<uint32_t>& a_tile,
    const std::vector<uint32_t>& a_cand,
    const std::vector<uint8_t>& meta_bytes,
    uint32_t& group_err_mask_out
) {
    group_err_mask_out = 0u;
    if (!fmt_supports_sparse(fmt_a)) {
        return false;
    }
    int active_groups = (fmt_a == FMT_TF32) ? (array_k / 2)
                        : ((fmt_a == FMT_FP16 || fmt_a == FMT_BF16) ? array_k
                           : (fmt_is_fp4(fmt_a) ? (array_k * 4) : (array_k * 2)));
    auto get_nibble = [&](int grp) -> uint8_t {
        return (meta_bytes[grp / 2] >> ((grp % 2) * 4)) & 0xFu;
    };
    bool any_err = false;
    for (int g = 0; g < active_groups; ++g) {
        uint8_t m4 = get_nibble(g);
        uint8_t idx0 = m4 & 0x3u;
        uint8_t idx1 = (m4 >> 2) & 0x3u;
        bool legal = (idx0 < idx1);
        bool zc[4] = {false, false, false, false};
        int k = g / 2;
        int sub = g % 2;
        if (fmt_a == FMT_TF32) {
            zc[0] = elem_is_zero_fmt(fmt_a, a_tile[2 * g]);
            zc[1] = elem_is_zero_fmt(fmt_a, a_tile[2 * g + 1]);
            zc[2] = elem_is_zero_fmt(fmt_a, a_cand[2 * g]);
            zc[3] = elem_is_zero_fmt(fmt_a, a_cand[2 * g + 1]);
        } else if (fmt_a == FMT_FP16 || fmt_a == FMT_BF16) {
            zc[0] = elem_is_zero_fmt(fmt_a, a_tile[g] & 0xFFFFu);
            zc[1] = elem_is_zero_fmt(fmt_a, (a_tile[g] >> 16) & 0xFFFFu);
            zc[2] = elem_is_zero_fmt(fmt_a, a_cand[g] & 0xFFFFu);
            zc[3] = elem_is_zero_fmt(fmt_a, (a_cand[g] >> 16) & 0xFFFFu);
        } else if (fmt_is_fp8(fmt_a) || fmt_a == FMT_INT8) {
            int sh = sub * 16;
            zc[0] = elem_is_zero_fmt(fmt_a, (a_tile[k] >> sh) & 0xFFu);
            zc[1] = elem_is_zero_fmt(fmt_a, (a_tile[k] >> (sh + 8)) & 0xFFu);
            zc[2] = elem_is_zero_fmt(fmt_a, (a_cand[k] >> sh) & 0xFFu);
            zc[3] = elem_is_zero_fmt(fmt_a, (a_cand[k] >> (sh + 8)) & 0xFFu);
        } else if (fmt_is_fp6(fmt_a)) {
            int sh = sub * 16;
            zc[0] = elem_is_zero_fmt(fmt_a, (a_tile[k] >> sh) & 0x3Fu);
            zc[1] = elem_is_zero_fmt(fmt_a, (a_tile[k] >> (sh + 8)) & 0x3Fu);
            zc[2] = elem_is_zero_fmt(fmt_a, (a_cand[k] >> sh) & 0x3Fu);
            zc[3] = elem_is_zero_fmt(fmt_a, (a_cand[k] >> (sh + 8)) & 0x3Fu);
        } else {
            int k4 = g / 4;
            int q4 = g % 4;
            int sh = q4 * 8;
            zc[0] = elem_is_zero_fmt(fmt_a, (a_tile[k4] >> sh) & 0xFu);
            zc[1] = elem_is_zero_fmt(fmt_a, (a_tile[k4] >> (sh + 4)) & 0xFu);
            zc[2] = elem_is_zero_fmt(fmt_a, (a_cand[k4] >> sh) & 0xFu);
            zc[3] = elem_is_zero_fmt(fmt_a, (a_cand[k4] >> (sh + 4)) & 0xFu);
        }
        bool zero_cand = (zc[idx0] && zc[idx1]) && !(zc[0] && zc[1] && zc[2] && zc[3]);
        (void)zero_cand;
        if (!legal) {
            group_err_mask_out |= (1u << g);
            any_err = true;
        }
    }
    return !any_err;
}

std::vector<uint32_t> ref_sparse_select_row(
    Fmt fmt_a, int array_k, bool sparse_en, bool fault_suppress,
    const std::vector<uint32_t>& a_tile,
    const std::vector<uint32_t>& a_cand,
    const std::vector<uint8_t>& meta_bytes,
    uint32_t group_err_mask
) {
    if (!sparse_en) {
        if (fault_suppress) return std::vector<uint32_t>(array_k, 0u);
        return a_tile;
    }
    std::vector<uint32_t> out(array_k, 0u);
    auto get_nibble = [&](int grp) -> uint8_t {
        return (meta_bytes[grp / 2] >> ((grp % 2) * 4)) & 0xFu;
    };
    auto pick = [&](const std::array<uint32_t, 4>& c, uint8_t m4, bool sup) -> std::pair<uint32_t, uint32_t> {
        if (sup || !sparse_pair_legal(m4)) return {0u, 0u};
        return {c[m4 & 3u], c[(m4 >> 2) & 3u]};
    };
    if (fmt_a == FMT_TF32) {
        for (int g = 0; g < array_k / 2; ++g) {
            std::array<uint32_t, 4> c{a_tile[2 * g], a_tile[2 * g + 1], a_cand[2 * g], a_cand[2 * g + 1]};
            bool sup = fault_suppress || ((group_err_mask >> g) & 1u);
            auto [p0, p1] = pick(c, get_nibble(g), sup);
            out[2 * g] = p0;
            out[2 * g + 1] = p1;
        }
    } else if (fmt_a == FMT_FP16 || fmt_a == FMT_BF16) {
        for (int k = 0; k < array_k; ++k) {
            std::array<uint32_t, 4> c{a_tile[k] & 0xFFFFu, (a_tile[k] >> 16) & 0xFFFFu,
                                      a_cand[k] & 0xFFFFu, (a_cand[k] >> 16) & 0xFFFFu};
            bool sup = fault_suppress || ((group_err_mask >> k) & 1u);
            auto [p0, p1] = pick(c, get_nibble(k), sup);
            out[k] = (p0 & 0xFFFFu) | ((p1 & 0xFFFFu) << 16);
        }
    } else if (fmt_is_fp8(fmt_a) || fmt_a == FMT_INT8) {
        for (int k = 0; k < array_k; ++k) {
            std::array<uint32_t, 4> c0{a_tile[k] & 0xFFu, (a_tile[k] >> 8) & 0xFFu,
                                       a_cand[k] & 0xFFu, (a_cand[k] >> 8) & 0xFFu};
            std::array<uint32_t, 4> c1{(a_tile[k] >> 16) & 0xFFu, (a_tile[k] >> 24) & 0xFFu,
                                       (a_cand[k] >> 16) & 0xFFu, (a_cand[k] >> 24) & 0xFFu};
            auto [p0, p1] = pick(c0, get_nibble(2 * k), fault_suppress || ((group_err_mask >> (2 * k)) & 1u));
            auto [q0, q1] = pick(c1, get_nibble(2 * k + 1), fault_suppress || ((group_err_mask >> (2 * k + 1)) & 1u));
            out[k] = (p0 & 0xFFu) | ((p1 & 0xFFu) << 8) | ((q0 & 0xFFu) << 16) | ((q1 & 0xFFu) << 24);
        }
    } else if (fmt_is_fp6(fmt_a)) {
        for (int k = 0; k < array_k; ++k) {
            std::array<uint32_t, 4> c0{a_tile[k] & 0x3Fu, (a_tile[k] >> 8) & 0x3Fu,
                                       a_cand[k] & 0x3Fu, (a_cand[k] >> 8) & 0x3Fu};
            std::array<uint32_t, 4> c1{(a_tile[k] >> 16) & 0x3Fu, (a_tile[k] >> 24) & 0x3Fu,
                                       (a_cand[k] >> 16) & 0x3Fu, (a_cand[k] >> 24) & 0x3Fu};
            auto [p0, p1] = pick(c0, get_nibble(2 * k), fault_suppress || ((group_err_mask >> (2 * k)) & 1u));
            auto [q0, q1] = pick(c1, get_nibble(2 * k + 1), fault_suppress || ((group_err_mask >> (2 * k + 1)) & 1u));
            out[k] = (p0 & 0x3Fu) | ((p1 & 0x3Fu) << 8) | ((q0 & 0x3Fu) << 16) | ((q1 & 0x3Fu) << 24);
        }
    } else {
        for (int k = 0; k < array_k; ++k) {
            uint32_t word_out = 0u;
            for (int q = 0; q < 4; ++q) {
                int sh = q * 8;
                int grp_idx = 4 * k + q;
                std::array<uint32_t, 4> cq{
                    (a_tile[k] >> sh) & 0xFu, (a_tile[k] >> (sh + 4)) & 0xFu,
                    (a_cand[k] >> sh) & 0xFu, (a_cand[k] >> (sh + 4)) & 0xFu
                };
                auto [p0, p1] = pick(cq, get_nibble(grp_idx),
                                     fault_suppress || ((group_err_mask >> grp_idx) & 1u));
                word_out |= ((p0 & 0xFu) << sh) | ((p1 & 0xFu) << (sh + 4));
            }
            out[k] = word_out;
        }
    }
    return out;
}

std::vector<uint32_t> ref_tile_gemm_step(
    int m, int n, int k,
    const WgmmaDesc& desc,
    const std::vector<uint32_t>& a_tile,
    const std::vector<uint32_t>& b_tile,
    const std::vector<uint8_t>& scale_a,
    const std::vector<uint8_t>& scale_b,
    const std::vector<uint32_t>& c_tile,
    const std::vector<uint32_t>& bias,
    bool is_first_k, bool is_last_k,
    FpFlags& acc_flags_out
) {
    std::vector<uint32_t> d_tile(static_cast<size_t>(m * n), 0u);
    bool use_fp46 = fmt_is_fp4(desc.fmt_a) || fmt_is_fp6(desc.fmt_a) ||
                    fmt_is_fp4(desc.fmt_b) || fmt_is_fp6(desc.fmt_b);
    bool is_int = (desc.fmt_a == FMT_INT8) && (desc.fmt_b == FMT_INT8);
    bool eff_accum = is_first_k ? desc.accum_en : true;
    ScaleFmt eff_sfmt = (desc.scale_fmt != SCALE_NONE) ? desc.scale_fmt : SCALE_NONE;
    if (eff_sfmt == SCALE_NONE && (desc.fmt_a == FMT_NVFP4_E2M1 || desc.fmt_b == FMT_NVFP4_E2M1)) {
        eff_sfmt = SCALE_E4M3;
    } else if (eff_sfmt == SCALE_NONE && (fmt_is_mx(desc.fmt_a) || fmt_is_mx(desc.fmt_b))) {
        eff_sfmt = SCALE_UE8M0;
    }

    for (int r = 0; r < m; ++r) {
        for (int c = 0; c < n; ++c) {
            uint32_t cin = c_tile[static_cast<size_t>(r * n + c)];
            FedpResult pe;
            if (use_fp46) {
                std::vector<uint8_t> ab(k), bb(k);
                for (int i = 0; i < k; ++i) {
                    ab[i] = static_cast<uint8_t>(a_tile[static_cast<size_t>(r * k + i)] & (fmt_is_fp4(desc.fmt_a) ? 0xFu : 0x3Fu));
                    bb[i] = static_cast<uint8_t>(b_tile[static_cast<size_t>(c * k + i)] & (fmt_is_fp4(desc.fmt_b) ? 0xFu : 0x3Fu));
                }
                pe = ref_fp4_fp6_fedp(desc.fmt_a, desc.fmt_b, eff_sfmt, desc.rm,
                                      ab, bb, scale_a[r], scale_b[c], cin, eff_accum);
            } else {
                std::vector<uint32_t> aw(k), bw(k);
                for (int i = 0; i < k; ++i) {
                    aw[i] = a_tile[static_cast<size_t>(r * k + i)];
                    bw[i] = b_tile[static_cast<size_t>(c * k + i)];
                }
                pe = ref_fp8_bf16_fedp(desc.fmt_a, desc.fmt_b, eff_sfmt, desc.rm,
                                       aw, bw, scale_a[r], scale_b[c], cin, eff_accum, desc.int_saturate);
            }
            acc_flags_out.merge(pe.flags);
            uint32_t val = pe.d_bits;

            if (is_last_k) {
                if (desc.bias_en) {
                    uint32_t bv = bias[c];
                    if (is_int) {
                        if (bv != 0u) {
                            auto bres = ref_int32_add_exact(val, bv, desc.int_saturate);
                            val = bres.d_bits;
                            acc_flags_out.merge(bres.flags);
                        }
                    } else if (fp32_is_nan(bv)) {
                        val = CANONICAL_QNAN;
                        if (fp32_is_snan(bv)) acc_flags_out.nv = true;
                    } else if (!(fp32_is_zero(bv) && !fp32_is_zero(val) && !fp32_is_nan(val))) {
                        auto bres = ref_fp32_add_exact(val, bv, desc.rm);
                        val = bres.d_bits;
                        acc_flags_out.merge(bres.flags);
                    }
                }
                auto ares = ref_epilogue_act(val, desc.act, desc.clamp_min_fp32, desc.clamp_max_fp32, is_int);
                val = ares.d_bits;
                acc_flags_out.merge(ares.flags);

                auto cres = ref_epilogue_cast(val, desc.fmt_d, desc.rm, is_int, false, 0x3F800000u);
                val = cres.d_bits;
                acc_flags_out.merge(cres.flags);
            }
            d_tile[static_cast<size_t>(r * n + c)] = val;
        }
    }
    return d_tile;
}

uint8_t tmem_swizzled_bank(uint8_t row, uint16_t col, TmemSwizzle mode) {
    uint8_t base = static_cast<uint8_t>(col & 0x1Fu);
    switch (mode) {
        case SWIZZLE_NONE: return base;
        case SWIZZLE_32B:  return static_cast<uint8_t>(base ^ (row & 0x7u));
        case SWIZZLE_64B:  return static_cast<uint8_t>(base ^ (row & 0xFu));
        case SWIZZLE_128B: return static_cast<uint8_t>(base ^ (row & 0x1Fu));
        default:           return base;
    }
}

uint16_t tmem_bank_word_addr(uint8_t row, uint16_t col) {
    return static_cast<uint16_t>(((row & 0x7Fu) << 3) | ((col >> 6) & 0x7u));
}

bool tmem_cell_half_sel(uint16_t col) {
    return ((col >> 5) & 1u) != 0u;
}

uint16_t tmem_col_from_phys(uint16_t word_addr, uint8_t bank_id, bool half_sel, TmemSwizzle mode) {
    uint8_t row = static_cast<uint8_t>((word_addr >> 3) & 0x7Fu);
    uint8_t col_lo = tmem_swizzled_bank(row, bank_id, mode); // XOR involution
    return static_cast<uint16_t>(((word_addr & 0x7u) << 6) | (half_sel ? 32u : 0u) | col_lo);
}

uint8_t hsiao_ecc_parity(uint64_t data) {
    uint8_t parity = 0;
    for (int p = 0; p < 8; ++p) {
        uint64_t masked = data & HSIAO_P_MATRIX[p];
        uint8_t bit = static_cast<uint8_t>(__builtin_popcountll(masked) & 1);
        parity |= static_cast<uint8_t>(bit << p);
    }
    return parity;
}

uint64_t hsiao_ecc_encode_CW(uint64_t data, uint8_t& parity_out) {
    parity_out = hsiao_ecc_parity(data);
    return data;
}

EccDecodeResult hsiao_ecc_decode(uint64_t data_in, uint8_t parity_in) {
    EccDecodeResult r;
    uint8_t recomp = hsiao_ecc_parity(data_in);
    uint8_t syn = static_cast<uint8_t>(parity_in ^ recomp);
    r.syndrome = syn;
    r.data_out = data_in;
    r.parity_out = parity_in;
    if (syn == 0) {
        return r;
    }
    bool odd = (__builtin_popcount(syn) & 1) != 0;
    int match_data = -1;
    int match_par = -1;
    for (int d = 0; d < 64; ++d) {
        uint8_t col_sig = 0;
        for (int p = 0; p < 8; ++p) {
            if ((HSIAO_P_MATRIX[p] >> d) & 1ULL) {
                col_sig |= static_cast<uint8_t>(1u << p);
            }
        }
        if (syn == col_sig) {
            match_data = d;
            break;
        }
    }
    for (int p = 0; p < 8; ++p) {
        if (syn == static_cast<uint8_t>(1u << p)) {
            match_par = p;
            break;
        }
    }
    bool any_col = (match_data >= 0) || (match_par >= 0);
    r.ce = odd && any_col;
    r.ue = (!odd) || (!any_col);
    if (r.ce) {
        if (match_data >= 0) {
            r.data_out ^= (1ULL << match_data);
            r.err_bit_idx = static_cast<uint8_t>(match_data);
        } else {
            r.parity_out ^= static_cast<uint8_t>(1u << match_par);
            r.err_in_parity = true;
            r.err_bit_idx = static_cast<uint8_t>(64 + match_par);
        }
    }
    return r;
}

TmemAllocatorRef::TmemAllocatorRef() { reset(); }

void TmemAllocatorRef::reset() {
    regions_.fill(TmemRegionEntry{});
    bitmap_ = 0;
    peak_ = 0;
}

uint8_t TmemAllocatorRef::occupied_granules() const {
    return static_cast<uint8_t>(__builtin_popcount(bitmap_));
}

TmemAllocRsp TmemAllocatorRef::execute(uint8_t op, bool auto_place, bool buddy_align,
                                       bool strict_owner, const TmemAllocReq& req) {
    TmemAllocRsp rsp;
    rsp.valid = true;
    uint8_t rid = req.region_id & 0xFu;

    if (op == ALLOC_CMD_ALLOC) {
        bool pow2_ok = (req.num_columns != 0) && ((req.num_columns & (req.num_columns - 1)) == 0) &&
                       (req.num_columns >= 32) && (req.num_columns <= 512);
        bool rows_ok = (req.num_rows == 32) || (req.num_rows == 64) || (req.num_rows == 128);
        bool align_ok = (req.col_offset & 0x1Fu) == 0u;
        uint16_t eff_cols = req.double_buf_en ? static_cast<uint16_t>(req.num_columns << 1) : req.num_columns;
        bool dbl_ok = (eff_cols <= 512);
        uint16_t units = eff_cols >> 5;

        int free_id = -1;
        for (int r = 0; r < TMEM_MAX_REGIONS; ++r) {
            if (!regions_[r].allocated) { free_id = r; break; }
        }
        uint8_t target_id = (auto_place && regions_[rid].allocated && free_id >= 0)
                                ? static_cast<uint8_t>(free_id)
                                : rid;
        bool target_free = !regions_[target_id].allocated;

        bool auto_found = false;
        uint16_t auto_start = 0;
        uint16_t auto_mask = 0;
        if (pow2_ok && dbl_ok && units > 0) {
            for (int u = 0; u < TMEM_NUM_GRANULES; ++u) {
                bool buddy_ok = (!buddy_align) || ((u & (units - 1)) == 0);
                if (buddy_ok && (u + units <= TMEM_NUM_GRANULES)) {
                    uint16_t cmask = 0;
                    bool fits = true;
                    for (int k = u; k < u + units; ++k) {
                        cmask |= static_cast<uint16_t>(1u << k);
                        if ((bitmap_ >> k) & 1u) fits = false;
                    }
                    if (fits) {
                        auto_found = true;
                        auto_start = static_cast<uint16_t>(u);
                        auto_mask = cmask;
                        break;
                    }
                }
            }
        }

        uint16_t chosen_col = auto_place ? static_cast<uint16_t>(auto_start << 5) : req.col_offset;
        uint16_t chosen_mask = 0;
        if (auto_place) {
            chosen_mask = auto_mask;
        } else if (eff_cols <= 512) {
            uint16_t su = req.col_offset >> 5;
            for (int i = 0; i < TMEM_NUM_GRANULES; ++i) {
                if (i >= su && i < su + units) chosen_mask |= static_cast<uint16_t>(1u << i);
            }
        }

        bool exp_buddy_ok = (!buddy_align) || (((req.col_offset >> 5) & (units - 1)) == 0);
        TmemStatus st = TMEM_STATUS_OK;
        if (!pow2_ok || !rows_ok || !dbl_ok) st = TMEM_STATUS_BAD_SIZE;
        else if (!auto_place && (!align_ok || !exp_buddy_ok)) st = TMEM_STATUS_BAD_ALIGN;
        else if (!auto_place && (req.col_offset + eff_cols > 512)) st = TMEM_STATUS_BAD_SIZE;
        else if (!target_free || free_id < 0) st = TMEM_STATUS_FULL;
        else if (auto_place && !auto_found) st = TMEM_STATUS_OUT_OF_COLS;
        else if (!auto_place && (chosen_mask & bitmap_) != 0) st = TMEM_STATUS_OVERLAP;

        rsp.status = st;
        rsp.region_id = target_id;
        rsp.num_columns = req.num_columns;
        if (st == TMEM_STATUS_OK) {
            TmemRegionEntry e;
            e.allocated = true;
            e.active_buf = false;
            e.double_buf_en = req.double_buf_en;
            e.region_id = target_id;
            e.col_offset = chosen_col;
            e.num_columns = req.num_columns;
            e.num_rows = req.num_rows;
            e.swizzle = req.swizzle;
            e.owner_warp = req.owner_warp;
            e.granule_mask = chosen_mask;
            regions_[target_id] = e;
            bitmap_ |= chosen_mask;
            peak_ = std::max(peak_, occupied_granules());
            rsp.col_offset = chosen_col;
            uint16_t bb = chosen_col + req.num_columns;
            rsp.buf_b_col_offset = (req.double_buf_en && bb < 512) ? bb : chosen_col;
        }
    } else if (op == ALLOC_CMD_DEALLOC) {
        rsp.region_id = rid;
        if (!regions_[rid].allocated || (strict_owner && regions_[rid].owner_warp != req.owner_warp)) {
            rsp.status = TMEM_STATUS_NOT_ALLOCED;
        } else {
            rsp.status = TMEM_STATUS_OK;
            rsp.col_offset = regions_[rid].col_offset;
            rsp.num_columns = regions_[rid].num_columns;
            bitmap_ &= ~regions_[rid].granule_mask;
            regions_[rid] = TmemRegionEntry{};
        }
    } else if (op == ALLOC_CMD_QUERY) {
        rsp.region_id = rid;
        if (!regions_[rid].allocated) {
            rsp.status = TMEM_STATUS_NOT_ALLOCED;
        } else {
            rsp.status = TMEM_STATUS_OK;
            rsp.col_offset = regions_[rid].col_offset;
            rsp.num_columns = regions_[rid].num_columns;
            uint16_t bb = regions_[rid].col_offset + regions_[rid].num_columns;
            rsp.buf_b_col_offset = (regions_[rid].double_buf_en && bb < 512) ? bb : regions_[rid].col_offset;
        }
    } else if (op == ALLOC_CMD_RESET_OWNER) {
        rsp.region_id = rid;
        rsp.status = TMEM_STATUS_OK;
        for (int r = 0; r < TMEM_MAX_REGIONS; ++r) {
            if (regions_[r].allocated && regions_[r].owner_warp == req.owner_warp) {
                bitmap_ &= ~regions_[r].granule_mask;
                regions_[r] = TmemRegionEntry{};
            }
        }
    } else if (op == ALLOC_CMD_FLIP_BUF) {
        rsp.region_id = rid;
        if (!regions_[rid].allocated) {
            rsp.status = TMEM_STATUS_NOT_ALLOCED;
        } else if (!regions_[rid].double_buf_en) {
            rsp.status = TMEM_STATUS_BAD_SIZE;
        } else {
            regions_[rid].active_buf = !regions_[rid].active_buf;
            rsp.status = TMEM_STATUS_OK;
            rsp.col_offset = regions_[rid].col_offset;
            rsp.num_columns = regions_[rid].num_columns;
            uint16_t bb = regions_[rid].col_offset + regions_[rid].num_columns;
            rsp.buf_b_col_offset = (bb < 512) ? bb : regions_[rid].col_offset;
        }
    } else {
        rsp.status = TMEM_STATUS_BAD_SIZE;
    }
    return rsp;
}

bool desc_is_legal(const WgmmaDesc& d) {
    bool fmt_ok = fmt_bitwidth(d.fmt_a) != 0 && fmt_bitwidth(d.fmt_b) != 0 &&
                  fmt_bitwidth(d.fmt_c) != 0 && fmt_bitwidth(d.fmt_d) != 0;
    bool dim_ok = (d.tile_m != 0 && (d.tile_m % 16) == 0) &&
                  (d.tile_n != 0 && (d.tile_n % 8) == 0) &&
                  (d.tile_k != 0 && (d.tile_k % 8) == 0);
    bool mx = fmt_is_mx(d.fmt_a) || fmt_is_mx(d.fmt_b);
    bool scale_ok = mx ? (d.scale_fmt != SCALE_NONE) : (d.scale_fmt == SCALE_NONE);
    bool meta_ok = (d.rm <= RM_RMM) && (d.act <= ACT_GELU) && (d.barrier_id < 16);
    bool tmem_ok = d.tmem_a_row < 128 && d.tmem_b_row < 128 &&
                   d.tmem_c_row < 128 && d.tmem_d_row < 128 &&
                   d.tmem_a_col < 512 && d.tmem_b_col < 512 &&
                   d.tmem_c_col < 512 && d.tmem_d_col < 512;
    return fmt_ok && dim_ok && scale_ok && meta_ok && tmem_ok;
}

uint32_t uops_for_desc(const WgmmaDesc& d, int array_m, int array_n, int array_k) {
    int k_step = d.sparse_en ? (2 * array_k) : array_k;
    int sm = (d.tile_m + array_m - 1) / array_m;
    int sn = (d.tile_n + array_n - 1) / array_n;
    int sk = (d.tile_k + k_step - 1) / k_step;
    return static_cast<uint32_t>(sm * sn * sk);
}

std::string hex32(uint32_t v) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%08x", v);
    return std::string(buf);
}

std::string hex64(uint64_t v) {
    char buf[24];
    std::snprintf(buf, sizeof(buf), "0x%016llx", static_cast<unsigned long long>(v));
    return std::string(buf);
}

} // namespace tcu_v2_ref
