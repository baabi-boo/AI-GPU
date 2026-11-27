// SPDX-License-Identifier: Apache-2.0
#ifndef TCU_V2_GOLDEN_REF_H
#define TCU_V2_GOLDEN_REF_H

#include <array>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace tcu_v2_ref {

// -----------------------------------------------------------------------------
// Numeric, Scale, Rounding, Activation, and TMEM Constants (aligned with RTL)
// -----------------------------------------------------------------------------
enum Fmt : uint8_t {
    FMT_FP32       = 0,
    FMT_TF32       = 1,
    FMT_FP16       = 2,
    FMT_BF16       = 3,
    FMT_FP8_E4M3   = 4,
    FMT_FP8_E5M2   = 5,
    FMT_MXFP8_E4M3 = 8,
    FMT_MXFP8_E5M2 = 9,
    FMT_MXFP4_E2M1 = 10,
    FMT_NVFP4_E2M1 = 11,
    FMT_MXFP6_E2M3 = 12,
    FMT_MXFP6_E3M2 = 13,
    FMT_I32        = 16,
    FMT_INT8       = 17
};

enum ScaleFmt : uint8_t {
    SCALE_NONE  = 0,
    SCALE_UE8M0 = 1,
    SCALE_E4M3  = 2
};

enum RoundMode : uint8_t {
    RM_RNE = 0,
    RM_RTZ = 1,
    RM_RDN = 2,
    RM_RUP = 3,
    RM_RMM = 4
};

enum ActMode : uint8_t {
    ACT_NONE  = 0,
    ACT_RELU  = 1,
    ACT_CLAMP = 2,
    ACT_SILU  = 3,
    ACT_GELU  = 4
};

enum TmemSwizzle : uint8_t {
    SWIZZLE_NONE = 0,
    SWIZZLE_32B  = 1,
    SWIZZLE_64B  = 2,
    SWIZZLE_128B = 3
};

enum TmemOp : uint8_t {
    TMEM_OP_NOP      = 0,
    TMEM_OP_LD       = 1,
    TMEM_OP_ST       = 2,
    TMEM_OP_MMA_RD_A = 3,
    TMEM_OP_MMA_RD_B = 4,
    TMEM_OP_MMA_RD_C = 5,
    TMEM_OP_MMA_WR_D = 6,
    TMEM_OP_ALLOC    = 7,
    TMEM_OP_DEALLOC  = 8,
    TMEM_OP_WAIT     = 9,
    TMEM_OP_FENCE    = 10
};

enum TmemStatus : uint8_t {
    TMEM_STATUS_OK          = 0,
    TMEM_STATUS_BAD_ALIGN   = 1,
    TMEM_STATUS_BAD_SIZE    = 2,
    TMEM_STATUS_OUT_OF_COLS = 3,
    TMEM_STATUS_OVERLAP     = 4,
    TMEM_STATUS_NOT_ALLOCED = 5,
    TMEM_STATUS_ECC_UE      = 6,
    TMEM_STATUS_FULL        = 7
};

enum AllocCmd : uint8_t {
    ALLOC_CMD_ALLOC       = 0,
    ALLOC_CMD_DEALLOC     = 1,
    ALLOC_CMD_QUERY       = 2,
    ALLOC_CMD_RESET_OWNER = 3,
    ALLOC_CMD_FLIP_BUF    = 4
};

constexpr uint32_t CANONICAL_QNAN = 0x7FC00000u;
constexpr uint32_t FP32_POS_INF   = 0x7F800000u;
constexpr uint32_t FP32_NEG_INF   = 0xFF800000u;
constexpr uint32_t FP32_POS_ZERO  = 0x00000000u;
constexpr uint32_t FP32_NEG_ZERO  = 0x80000000u;
constexpr uint32_t INT32_MAX_U32  = 0x7FFFFFFFu;
constexpr uint32_t INT32_MIN_U32  = 0x80000000u;

constexpr int TMEM_ROWS          = 128;
constexpr int TMEM_COLS          = 512;
constexpr int TMEM_NUM_BANKS     = 32;
constexpr int TMEM_BANK_WORDS    = 1024;
constexpr int TMEM_ALLOC_GRANULE = 32;
constexpr int TMEM_NUM_GRANULES  = 16;
constexpr int TMEM_MAX_REGIONS   = 16;

constexpr std::array<uint64_t, 8> HSIAO_P_MATRIX = {
    0xFF000000001FFFFFULL, // p[0]
    0xFF00000FFFF0003FULL & 0xFF00000FFFE0003FULL, // exact match check below
    0xFF003FF003E007C1ULL,
    0x0F0FC0F03C207842ULL,
    0x7171C711C4438884ULL,
    0x92B65926488C9108ULL,
    0xA4DAAA4A91152210ULL,
    0x48ED348D221A4420ULL
};

static_assert((0xFF00000FFFF0003FULL & 0xFF00000FFFE0003FULL) == 0xFF00000FFFE0003FULL,
              "Hsiao matrix row 1 check");

struct FpFlags {
    bool nv = false;
    bool dz = false;
    bool of = false;
    bool uf = false;
    bool nx = false;

    uint8_t pack() const {
        return static_cast<uint8_t>((nv ? 16 : 0) | (dz ? 8 : 0) |
                                    (of ? 4 : 0) | (uf ? 2 : 0) | (nx ? 1 : 0));
    }
    static FpFlags unpack(uint8_t v) {
        FpFlags f;
        f.nv = (v >> 4) & 1u;
        f.dz = (v >> 3) & 1u;
        f.of = (v >> 2) & 1u;
        f.uf = (v >> 1) & 1u;
        f.nx = (v >> 0) & 1u;
        return f;
    }
    void merge(const FpFlags& o) {
        nv |= o.nv;
        dz |= o.dz;
        of |= o.of;
        uf |= o.uf;
        nx |= o.nx;
    }
    bool operator==(const FpFlags& o) const {
        return nv == o.nv && dz == o.dz && of == o.of && uf == o.uf && nx == o.nx;
    }
};

struct UnpackedFp {
    bool     sign         = false;
    int32_t  exp          = 0;     // unbiased exponent for normalized significand
    uint32_t sig_u1p23    = 0;     // normalized 24-bit significand (bit 23 == 1 when finite nz)
    bool     is_zero      = false;
    bool     is_inf       = false;
    bool     is_nan       = false;
    bool     is_snan      = false;
    bool     is_subnormal = false;
};

struct DecodedScale {
    ScaleFmt scale_fmt  = SCALE_NONE;
    bool     is_zero    = false;
    bool     is_nan     = false;
    int32_t  exp_delta  = 0;
    uint8_t  mant_u1p3  = 8; // unnormalized u1.3
    uint8_t  norm_u1p3  = 8; // normalized u1.3
    int32_t  norm_exp   = 0;
};

struct FedpResult {
    uint32_t d_bits = 0;
    FpFlags  flags{};
};

struct WgmmaDesc {
    uint8_t  desc_id        = 0;
    Fmt      fmt_a          = FMT_BF16;
    Fmt      fmt_b          = FMT_BF16;
    Fmt      fmt_c          = FMT_FP32;
    Fmt      fmt_d          = FMT_FP32;
    ScaleFmt scale_fmt      = SCALE_NONE;
    RoundMode rm            = RM_RNE;
    ActMode  act            = ACT_NONE;
    bool     sparse_en      = false;
    bool     cta_pair_en    = false;
    bool     accum_en       = false;
    bool     bias_en        = false;
    bool     int_saturate   = false;
    bool     tmem_wb_en     = false;
    uint8_t  barrier_id     = 0;
    bool     barrier_phase  = false;
    uint16_t tile_m         = 4;
    uint16_t tile_n         = 4;
    uint16_t tile_k         = 8;
    uint8_t  tmem_a_row     = 0;
    uint16_t tmem_a_col     = 0;
    uint8_t  tmem_b_row     = 0;
    uint16_t tmem_b_col     = 0;
    uint8_t  tmem_c_row     = 0;
    uint16_t tmem_c_col     = 0;
    uint8_t  tmem_d_row     = 0;
    uint16_t tmem_d_col     = 0;
    uint32_t clamp_min_fp32 = 0;
    uint32_t clamp_max_fp32 = 0;
};

struct TmemAllocReq {
    bool        is_dealloc    = false;
    uint8_t     region_id     = 0;
    uint16_t    col_offset    = 0;
    uint16_t    num_columns   = 32;
    uint8_t     num_rows      = 32;
    TmemSwizzle swizzle       = SWIZZLE_NONE;
    bool        double_buf_en = false;
    uint8_t     owner_warp    = 0;
};

struct TmemAllocRsp {
    bool       valid            = false;
    TmemStatus status           = TMEM_STATUS_OK;
    uint8_t    region_id        = 0;
    uint16_t   col_offset       = 0;
    uint16_t   num_columns      = 0;
    uint16_t   buf_b_col_offset = 0;
};

struct TmemRegionEntry {
    bool        allocated     = false;
    bool        active_buf    = false;
    bool        double_buf_en = false;
    uint8_t     region_id     = 0;
    uint16_t    col_offset    = 0;
    uint16_t    num_columns   = 0;
    uint8_t     num_rows      = 0;
    TmemSwizzle swizzle       = SWIZZLE_NONE;
    uint8_t     owner_warp    = 0;
    uint16_t    granule_mask  = 0;
};

// Format classification helpers
bool fmt_is_fp4(Fmt f);
bool fmt_is_fp6(Fmt f);
bool fmt_is_fp8(Fmt f);
bool fmt_is_mx(Fmt f);
bool fmt_is_int(Fmt f);
bool fmt_supports_sparse(Fmt f);
uint32_t fmt_bitwidth(Fmt f);

// FP32 bit predicates & exact IEEE-754 operations
inline bool fp32_is_nan(uint32_t v) { return ((v >> 23) & 0xFFu) == 0xFFu && (v & 0x7FFFFFu) != 0u; }
inline bool fp32_is_snan(uint32_t v) { return fp32_is_nan(v) && ((v & 0x00400000u) == 0u); }
inline bool fp32_is_inf(uint32_t v) { return ((v >> 23) & 0xFFu) == 0xFFu && (v & 0x7FFFFFu) == 0u; }
inline bool fp32_is_zero(uint32_t v) { return (v & 0x7FFFFFFFu) == 0u; }
inline bool fp32_is_subnormal(uint32_t v) { return ((v >> 23) & 0xFFu) == 0u && (v & 0x7FFFFFu) != 0u; }

inline float u32_to_f32(uint32_t u) {
    float f = 0.0f;
    std::memcpy(&f, &u, sizeof(f));
    return f;
}
inline uint32_t f32_to_u32(float f) {
    uint32_t u = 0;
    std::memcpy(&u, &f, sizeof(u));
    return u;
}

// Element unpackers -> normalized UnpackedFp
UnpackedFp unpack_fp4_e2m1(uint8_t nib);
UnpackedFp unpack_fp6_e2m3(uint8_t raw6);
UnpackedFp unpack_fp6_e3m2(uint8_t raw6);
UnpackedFp unpack_fp8_e4m3(uint8_t raw8);
UnpackedFp unpack_fp8_e5m2(uint8_t raw8);
UnpackedFp unpack_fp16(uint16_t raw16);
UnpackedFp unpack_bf16(uint16_t raw16);
UnpackedFp unpack_tf32(uint32_t raw32);
UnpackedFp unpack_fp32(uint32_t raw32);
DecodedScale decode_scale(ScaleFmt sfmt, uint8_t raw8);

// Exact FEDP reference models matching hardware semantics
FedpResult ref_fp4_fp6_fedp(
    Fmt fmt_a, Fmt fmt_b, ScaleFmt sfmt, RoundMode rm,
    const std::vector<uint8_t>& a_bytes,
    const std::vector<uint8_t>& b_bytes,
    uint8_t scale_a, uint8_t scale_b,
    uint32_t c_fp32, bool accum_en
);

FedpResult ref_fp8_bf16_fedp(
    Fmt fmt_a, Fmt fmt_b, ScaleFmt sfmt, RoundMode rm,
    const std::vector<uint32_t>& a_words,
    const std::vector<uint32_t>& b_words,
    uint8_t scale_a, uint8_t scale_b,
    uint32_t c_in, bool accum_en, bool int_saturate
);

// Exact IEEE-754 scalar FP32 add/mul & epilogue operations (Bias -> Act -> Cast)
FedpResult ref_fp32_add_exact(uint32_t a, uint32_t b, RoundMode rm);
uint32_t   ref_fp32_mul_rne(uint32_t a, uint32_t b);
FedpResult ref_int32_add_exact(uint32_t a, uint32_t b, bool saturate);
FedpResult ref_epilogue_act(uint32_t x, ActMode act, uint32_t clamp_min, uint32_t clamp_max, bool is_int);
FedpResult ref_epilogue_cast(uint32_t val, Fmt fmt_d, RoundMode rm, bool src_is_int,
                             bool dyn_scale_en = false, uint32_t dyn_scale_fp32 = 0x3F800000u);

// 2:4 Structured sparsity reference (compressor, validator, selector)
bool sparse_pair_legal(uint8_t meta4);
void ref_sparse_compress_row(
    Fmt fmt_a, int array_k,
    const std::vector<uint32_t>& dense_lo,
    const std::vector<uint32_t>& dense_hi,
    std::vector<uint32_t>& comp_out,
    std::vector<uint8_t>& meta_bytes_out,
    bool& prune_loss_out
);
bool ref_sparse_validate_row(
    Fmt fmt_a, int array_k,
    const std::vector<uint32_t>& a_tile,
    const std::vector<uint32_t>& a_cand,
    const std::vector<uint8_t>& meta_bytes,
    uint32_t& group_err_mask_out
);
std::vector<uint32_t> ref_sparse_select_row(
    Fmt fmt_a, int array_k, bool sparse_en, bool fault_suppress,
    const std::vector<uint32_t>& a_tile,
    const std::vector<uint32_t>& a_cand,
    const std::vector<uint8_t>& meta_bytes,
    uint32_t group_err_mask
);

// Full tile GEMM + epilogue reference
std::vector<uint32_t> ref_tile_gemm_step(
    int m, int n, int k,
    const WgmmaDesc& desc,
    const std::vector<uint32_t>& a_tile, // m * k
    const std::vector<uint32_t>& b_tile, // n * k
    const std::vector<uint8_t>& scale_a, // m
    const std::vector<uint8_t>& scale_b, // n
    const std::vector<uint32_t>& c_tile, // m * n
    const std::vector<uint32_t>& bias,   // n
    bool is_first_k, bool is_last_k,
    FpFlags& acc_flags_out
);

// TMEM Swizzle, Hsiao(72,64) SECDED ECC, and Allocator reference model
uint8_t  tmem_swizzled_bank(uint8_t row, uint16_t col, TmemSwizzle mode);
uint16_t tmem_bank_word_addr(uint8_t row, uint16_t col);
bool     tmem_cell_half_sel(uint16_t col);
uint16_t tmem_col_from_phys(uint16_t word_addr, uint8_t bank_id, bool half_sel, TmemSwizzle mode);

uint8_t  hsiao_ecc_parity(uint64_t data);
uint64_t hsiao_ecc_encode_CW(uint64_t data, uint8_t& parity_out);
struct EccDecodeResult {
    uint64_t data_out       = 0;
    uint8_t  parity_out     = 0;
    uint8_t  syndrome       = 0;
    bool     ce             = false;
    bool     ue             = false;
    bool     err_in_parity  = false;
    uint8_t  err_bit_idx    = 0;
};
EccDecodeResult hsiao_ecc_decode(uint64_t data_in, uint8_t parity_in);

class TmemAllocatorRef {
public:
    TmemAllocatorRef();
    void reset();
    TmemAllocRsp execute(uint8_t op, bool auto_place, bool buddy_align,
                         bool strict_owner, const TmemAllocReq& req);
    const std::array<TmemRegionEntry, TMEM_MAX_REGIONS>& regions() const { return regions_; }
    uint16_t granule_bitmap() const { return bitmap_; }
    uint8_t occupied_granules() const;
    uint8_t peak_granules() const { return peak_; }

private:
    std::array<TmemRegionEntry, TMEM_MAX_REGIONS> regions_{};
    uint16_t bitmap_ = 0;
    uint8_t  peak_   = 0;
};

// Descriptor legality & packing helpers for Verilator VlWide
bool desc_is_legal(const WgmmaDesc& d);
uint32_t uops_for_desc(const WgmmaDesc& d, int array_m = 16, int array_n = 8, int array_k = 8);

template <std::size_t N>
inline void wide_zero(uint32_t* dst) {
    std::memset(dst, 0, N * sizeof(uint32_t));
}

inline void wide_set_bits(uint32_t* dst, size_t n_words, size_t bit_lo, size_t width, uint64_t val) {
    for (size_t i = 0; i < width; ++i) {
        size_t b = bit_lo + i;
        size_t w = b / 32;
        size_t s = b % 32;
        if (w >= n_words) {
            break;
        }
        if ((val >> i) & 1ULL) {
            dst[w] |= (1u << s);
        } else {
            dst[w] &= ~(1u << s);
        }
    }
}

inline uint64_t wide_get_bits(const uint32_t* src, size_t n_words, size_t bit_lo, size_t width) {
    uint64_t out = 0;
    for (size_t i = 0; i < width && i < 64; ++i) {
        size_t b = bit_lo + i;
        size_t w = b / 32;
        size_t s = b % 32;
        if (w >= n_words) {
            break;
        }
        if ((src[w] >> s) & 1u) {
            out |= (1ULL << i);
        }
    }
    return out;
}

std::string hex32(uint32_t v);
std::string hex64(uint64_t v);

} // namespace tcu_v2_ref

#endif // TCU_V2_GOLDEN_REF_H
