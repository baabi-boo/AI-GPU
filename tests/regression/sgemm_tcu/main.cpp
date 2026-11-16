#include "common.h"
#include "p02_fixture_adapter.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <rvfloats.h>
#include <string.h>
#include <tensor_cfg.h>
#include <unistd.h>
#include <util.h>
#include <vector>
#include <vortex2.h>

#define FLOAT_ULP 10
#define MAX_ERRORS 100

#define RT_CHECK(_expr)                                      \
  do {                                                       \
    int _ret = _expr;                                        \
    if (0 == _ret)                                           \
      break;                                                 \
    printf("Error: '%s' returned %d!\n", #_expr, (int)_ret); \
    cleanup();                                               \
    exit(-1);                                                \
  } while (false)

using namespace vortex;
namespace vt = tensor;

///////////////////////////////////////////////////////////////////////////////

template <typename T>
static void convert_row_to_col_major(T *dst, const T *src, uint32_t rows, uint32_t cols) {
  for (uint32_t r = 0; r < rows; ++r) {
    for (uint32_t c = 0; c < cols; ++c) {
      dst[c * rows + r] = src[r * cols + c];
    }
  }
}

static void convert_row_to_col_major_4bit(uint8_t *dst, uint32_t width, uint32_t height, const uint8_t *src) {
  // Calculate output size and stride
  uint32_t out_bytes = (width * height + 1) / 2;
  memset(dst, 0, out_bytes);
  uint32_t dst_stride = (height + 1) / 2; // Bytes per column in output

  // For each column in source (which becomes row in destination)
  for (uint32_t c = 0; c < width; ++c) {
    uint32_t base = c * dst_stride;

    // For each row in source (which becomes column in destination)
    for (uint32_t r = 0; r < height; r += 2) {
      // Calculate source indices (row-major)
      uint32_t idx_even = r * width + c;
      uint32_t idx_odd = (r + 1) * width + c;

      // Extract nibbles - consistent with data_accessor_t
      uint8_t b_even = src[idx_even / 2];
      uint8_t b_odd = (r + 1 < height) ? src[idx_odd / 2] : 0;

      uint8_t nib_even = (idx_even & 1) ? (b_even >> 4) : (b_even & 0x0F);
      uint8_t nib_odd = (r + 1 < height)
                            ? ((idx_odd & 1) ? (b_odd >> 4) : (b_odd & 0x0F))
                            : 0;

      // Pack into destination: even row in low nibble, odd row in high nibble
      dst[base + r / 2] = (nib_odd << 4) | nib_even;
    }
  }
}

///////////////////////////////////////////////////////////////////////////////

template <typename T>
struct data_accessor_t {
  using Type = typename T::dtype;
  static Type read(const Type *ptr, uint32_t offset) {
    return ptr[offset];
  }
  static void write(Type *ptr, uint32_t offset, Type value) {
    ptr[offset] = value;
  }
};

template <>
struct data_accessor_t<vt::int4> {
  static uint8_t read(const uint8_t *ptr, uint32_t offset) {
    uint32_t row_off = offset / 2;
    bool odd = offset & 0x1;
    uint8_t value8 = ptr[row_off];
    return odd ? (value8 >> 4) : (value8 & 0x0f); // to nibble
  }
  static void write(uint8_t *ptr, uint32_t offset, int32_t value) {
    uint32_t row_off = offset / 2;
    bool odd = offset & 0x1;
    uint8_t old_value = ptr[row_off];
    uint8_t new_value = odd ? ((old_value & 0x0f) | (value << 4))
                            : ((old_value & 0xf0) | (value & 0x0f));
    ptr[offset / 2] = new_value;
  }
};

template <>
struct data_accessor_t<vt::uint4> {
  static uint8_t read(const uint8_t *ptr, uint32_t offset) {
    uint32_t row_off = offset / 2;
    bool odd = offset & 0x1;
    uint8_t value8 = ptr[row_off];
    return odd ? (value8 >> 4) : (value8 & 0x0f); // to nibble
  }
  static void write(uint8_t *ptr, uint32_t offset, int32_t value) {
    uint32_t row_off = offset / 2;
    bool odd = offset & 0x1;
    uint8_t old_value = ptr[row_off];
    uint8_t new_value = odd ? ((old_value & 0x0f) | (value << 4))
                            : ((old_value & 0xf0) | (value & 0x0f));
    ptr[offset / 2] = new_value;
  }
};

///////////////////////////////////////////////////////////////////////////////

template <typename Type>
class Comparator {};

template <>
class Comparator<vt::int8> {
public:
  static int8_t generate() {
    return (int8_t)rand();
  }
  static bool compare(int8_t a, int8_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::uint8> {
public:
  static uint8_t generate() {
    return (uint8_t)rand();
  }
  static bool compare(uint8_t a, uint8_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::int4> {
public:
  static uint8_t generate() {
    return (uint8_t)rand(); // store 2 nibbles in a byte
  }
  static bool compare(uint8_t a, uint8_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::uint4> {
public:
  static uint8_t generate() {
    return (uint8_t)rand(); // store 2 nibbles in a byte
  }
  static bool compare(uint8_t a, uint8_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::int32> {
public:
  static int32_t generate() {
    return (int32_t)rand();
  }
  static bool compare(int32_t a, int32_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::fp16> {
public:
  static uint16_t generate() {
    auto fvalue = float(rand()) / RAND_MAX;
    return rv_ftoh_s(bit_cast<uint32_t>(fvalue), 0, nullptr);
  }
  static bool compare(uint16_t a, uint16_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::bf16> {
public:
  static uint16_t generate() {
    auto fvalue = float(rand()) / RAND_MAX;
    return rv_ftob_s(bit_cast<uint32_t>(fvalue), 0, nullptr);
  }
  static bool compare(uint16_t a, uint16_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::fp8> {
public:
  static uint8_t generate() {
    auto fvalue = float(rand()) / RAND_MAX;
    return rv_ftoe4m3_s(bit_cast<uint32_t>(fvalue), 0, nullptr);
  }
  static bool compare(uint8_t a, uint8_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::bf8> {
public:
  static uint8_t generate() {
    auto fvalue = float(rand()) / RAND_MAX;
    return rv_ftoe5m2_s(bit_cast<uint32_t>(fvalue), 0, nullptr);
  }
  static bool compare(uint8_t a, uint8_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::tf32> {
public:
  static uint32_t generate() {
    auto fvalue = float(rand()) / RAND_MAX;
    return rv_ftotf32_s(bit_cast<uint32_t>(fvalue), 0, nullptr);
  }
  static bool compare(uint32_t a, uint32_t b, int index, int errors) {
    if (a != b) {
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=0x%x, actual=0x%x\n", index, b, a);
      }
      return false;
    }
    return true;
  }
};

template <>
class Comparator<vt::fp32> {
public:
  static float generate() {
    return static_cast<float>(rand()) / RAND_MAX;
  }
  static bool compare(float a, float b, int index, int errors) {
    // Lower-precision inputs (fp8/bf8/fp16/bf16) accumulated into fp32
    // can drift well past the strict ULP=10 threshold used for fp32 inputs.
    // Use a relative-error tolerance for these.
    constexpr bool low_prec_input =
        std::is_same<vt::ITYPE, vt::fp8>::value
     || std::is_same<vt::ITYPE, vt::bf8>::value
     || std::is_same<vt::ITYPE, vt::fp16>::value
     || std::is_same<vt::ITYPE, vt::bf16>::value;
    if constexpr (low_prec_input) {
      if (a == 0.0f && b == 0.0f) {
        return true;
      }
      // 1% relative error is comfortably above any single-element
      // mixed-precision accumulation drift seen on the regression
      // matrices, and tight enough to catch real systematic errors.
      auto diff = std::abs((a - b) / b);
      if (diff < 0.01f) {
        return true;
      }
      if (errors < MAX_ERRORS) {
        printf("*** error: [%d] expected=%f, actual=%f\n", index, b, a);
      }
      return false;
    } else {
      union fi_t {
        float f;
        int32_t i;
      };
      fi_t fa, fb;
      fa.f = a;
      fb.f = b;
      auto d = std::abs(fa.i - fb.i);
      if (d > FLOAT_ULP) {
        if (errors < MAX_ERRORS) {
          printf("*** error: [%d] expected=%f, actual=%f\n", index, fb.f, fa.f);
        }
        return false;
      }
      return true;
    }
  }
};

///////////////////////////////////////////////////////////////////////////////

template <typename S, typename D>
struct muladd_t {
  using stype = typename S::dtype;
  using dtype = typename D::dtype;
  static dtype eval(stype a, stype b, dtype c) {
    return static_cast<dtype>(a) * static_cast<dtype>(b) + c;
  }
};

template <>
struct muladd_t<vt::fp16, vt::fp32> {
  static float eval(uint16_t a, uint16_t b, float c) {
    auto fa = bit_cast<float>(rv_htof_s(a, 0, nullptr));
    auto fb = bit_cast<float>(rv_htof_s(b, 0, nullptr));
    return fa * fb + c;
  }
};

template <>
struct muladd_t<vt::bf16, vt::fp32> {
  static float eval(uint16_t a, uint16_t b, float c) {
    auto fa = bit_cast<float>(rv_btof_s(a, 0, nullptr));
    auto fb = bit_cast<float>(rv_btof_s(b, 0, nullptr));
    return fa * fb + c;
  }
};

template <>
struct muladd_t<vt::fp8, vt::fp32> {
  static float eval(uint8_t a, uint8_t b, float c) {
    auto fa = bit_cast<float>(rv_e4m3tof_s(a, 0, nullptr));
    auto fb = bit_cast<float>(rv_e4m3tof_s(b, 0, nullptr));
    return fa * fb + c;
  }
};

template <>
struct muladd_t<vt::bf8, vt::fp32> {
  static float eval(uint8_t a, uint8_t b, float c) {
    auto fa = bit_cast<float>(rv_e5m2tof_s(a, 0, nullptr));
    auto fb = bit_cast<float>(rv_e5m2tof_s(b, 0, nullptr));
    return fa * fb + c;
  }
};

template <>
struct muladd_t<vt::tf32, vt::fp32> {
  static float eval(uint32_t a, uint32_t b, float c) {
    auto fa = bit_cast<float>(rv_tf32tof_s(a, 0, nullptr));
    auto fb = bit_cast<float>(rv_tf32tof_s(b, 0, nullptr));
    return fa * fb + c;
  }
};

template <>
struct muladd_t<vt::int4, vt::int32> {
  static int32_t eval(uint8_t a, uint8_t b, int32_t c) {
    int32_t a_val = a & 0xF;
    if (a & 0x8) {
      a_val |= 0xFFFFFFF0; // sign extend
    }
    int32_t b_val = b & 0xF;
    if (b & 0x8) {
      b_val |= 0xFFFFFFF0; // sign extend
    }
    return a_val * b_val + c;
  }
};

template <>
struct muladd_t<vt::uint4, vt::int32> {
  static int32_t eval(uint8_t a, uint8_t b, int32_t c) {
    int32_t a_val = a & 0xF;
    int32_t b_val = b & 0xF;
    return a_val * b_val + c;
  }
};

template<typename T>
inline typename T::dtype generate_A_value() {
  return Comparator<T>::generate();
}

template<typename T>
inline typename T::dtype generate_B_value() {
  return Comparator<T>::generate();
}

///////////////////////////////////////////////////////////////////////////////

static_assert(vt::tcu_output_valid(vt::ITYPE::id, vt::OTYPE::id),
              "TCU output type must be fp32 (int32 for integer inputs)");

using cfg = vt::wmma_config_t<VX_CFG_NUM_THREADS, vt::ITYPE, vt::OTYPE>;

using itype_t = typename vt::ITYPE::dtype;
using otype_t = typename vt::OTYPE::dtype;


static void matmul_cpu(otype_t *C, const itype_t *A, const itype_t *B, uint32_t M, uint32_t N, uint32_t K) {
  uint32_t subbytes = 8 / vt::ITYPE::bits;
  uint32_t KS = subbytes ? (K * subbytes) : K;
  for (uint32_t m = 0; m < M; ++m) {
    for (uint32_t n = 0; n < N; ++n) {
      if constexpr (std::is_same<vt::OTYPE, vt::fp32>::value) {
        // The tensor core accumulates the K products in a wide accumulator
        // and rounds to fp32 once; a per-step-rounded reference drifts by
        // several ULP over K. Each product is exact in fp32, so a double
        // accumulation reproduces the single-rounding dot product.
        double acc = 0.0;
        for (uint32_t k = 0; k < KS; ++k) {
          auto a = data_accessor_t<vt::ITYPE>::read(A, m * KS + k);
          auto b = data_accessor_t<vt::ITYPE>::read(B, k * N + n);
          acc += static_cast<double>(muladd_t<vt::ITYPE, vt::OTYPE>::eval(a, b, otype_t(0)));
        }
        data_accessor_t<vt::OTYPE>::write(C, m * N + n, static_cast<otype_t>(acc));
      } else {
        // int32 output (integer inputs): exact accumulation.
        otype_t sum(0);
        for (uint32_t k = 0; k < KS; ++k) {
          auto a = data_accessor_t<vt::ITYPE>::read(A, m * KS + k);
          auto b = data_accessor_t<vt::ITYPE>::read(B, k * N + n);
          sum = muladd_t<vt::ITYPE, vt::OTYPE>::eval(a, b, sum);
        }
        data_accessor_t<vt::OTYPE>::write(C, m * N + n, sum);
      }
    }
  }
}

///////////////////////////////////////////////////////////////////////////////

const char *kernel_file = "kernel.vxbin";

uint32_t xm = 64;
uint32_t xn = 64;
uint32_t xk = 64;
uint32_t xr = 1; // repeat count: relaunch the same kernel N times on one device session
bool xz = false;  // bf8: zeros next to small values in K pairs of A row 0
bool xhelp = false;
const p02::Fixture* fixture = nullptr;

vx_device_h device = nullptr;
vx_buffer_h A_buffer = nullptr;
vx_buffer_h B_buffer = nullptr;
vx_buffer_h C_buffer = nullptr;
#ifdef PROFILE_ENABLE
vx_buffer_h cycles_buffer = nullptr;
#endif
vx_queue_h  queue = nullptr;
vx_module_h module_ = nullptr;
vx_kernel_h kernel = nullptr;
kernel_arg_t kernel_arg = {};

static void show_usage() {
  std::cout << "Vortex Sgemm TCU Test." << std::endl;
  std::cout << "Usage: [-m M] [-n N] [-k K] [-r repeat] [-z] [-h]" << std::endl;
  std::cout << "       -f fixture_id [-r repeat]" << std::endl;
  std::cout << "-z selects bf8 zero pairs; -f cannot be combined with -m, -n, -k or -z." << std::endl;
}

static bool parse_positive_u32(const char* text, uint32_t* value) {
  if (text == nullptr || *text == '\0') {
    return false;
  }
  uint32_t parsed = 0;
  for (const char* digit = text; *digit != '\0'; ++digit) {
    if (*digit < '0' || *digit > '9'
        || parsed > (UINT32_MAX - uint32_t(*digit - '0')) / 10) {
      return false;
    }
    parsed = parsed * 10 + uint32_t(*digit - '0');
  }
  if (parsed == 0) {
    return false;
  }
  *value = parsed;
  return true;
}

static bool parse_args(int argc, char **argv) {
  const char* fixture_id = nullptr;
  bool dimensions_given = false;
  opterr = 0;
  int c;
  while ((c = getopt(argc, argv, "+m:n:k:r:f:hz")) != -1) {
    switch (c) {
    case 'm':
    case 'n':
    case 'k':
      dimensions_given = true;
      if (!parse_positive_u32(optarg, c == 'm' ? &xm : (c == 'n' ? &xn : &xk))) {
        std::cerr << "Error: -" << char(c) << " requires a positive uint32 integer!" << std::endl;
        return false;
      }
      break;
    case 'r':
      if (!parse_positive_u32(optarg, &xr)) {
        std::cerr << "Error: -r requires a positive uint32 repeat count!" << std::endl;
        return false;
      }
      break;
    case 'f':
      if (fixture_id != nullptr || optarg == nullptr || *optarg == '\0') {
        std::cerr << "Error: -f requires exactly one nonempty fixture ID!" << std::endl;
        return false;
      }
      fixture_id = optarg;
      break;
    case 'z':
      xz = true;
      break;
    case 'h':
      xhelp = true;
      break;
    default:
      std::cerr << "Error: unknown option or missing option argument!" << std::endl;
      return false;
    }
  }
  if (optind != argc) {
    std::cerr << "Error: positional arguments are not supported!" << std::endl;
    return false;
  }
  if (fixture_id != nullptr) {
    if (dimensions_given || xz) {
      std::cerr << "Error: -f cannot be combined with -m, -n, -k or -z!" << std::endl;
      return false;
    }
    fixture = p02::find_fixture(fixture_id);
    if (fixture == nullptr) {
      std::cerr << "Error: unknown or ambiguous fixture ID '" << fixture_id << "'!" << std::endl;
      return false;
    }
  }
  return true;
}

void cleanup() {
  if (device) {
    if (A_buffer) vx_buffer_release(A_buffer);
    if (B_buffer) vx_buffer_release(B_buffer);
    if (C_buffer) vx_buffer_release(C_buffer);
#ifdef PROFILE_ENABLE
    if (cycles_buffer) vx_buffer_release(cycles_buffer);
#endif
    if (kernel)  vx_kernel_release(kernel);
    if (module_) vx_module_release(module_);
    if (queue)   vx_queue_release(queue);
    vx_device_dump_perf(device, stdout);
    vx_device_release(device);
  }
}

int main(int argc, char *argv[]) {
  if (!parse_args(argc, argv)) {
    show_usage();
    return -1;
  }
  if (xhelp) {
    show_usage();
    return 0;
  }
  if (fixture != nullptr) {
    if (const char* error = p02::fixture_error(*fixture)) {
      std::cerr << "Error: " << error << "!" << std::endl;
      return -1;
    }
    xm = fixture->m;
    xn = fixture->n;
    xk = fixture->k;
  }
  if (xz && !std::is_same<vt::ITYPE, vt::bf8>::value) {
    std::cout << "Error: -z requires ITYPE=bf8!" << std::endl;
    return -1;
  }

  uint32_t M = xm;
  uint32_t N = xn;
  uint32_t K = xk;

  if ((M % cfg::tileM) != 0) {
    std::cout << "Error: M must be a multiple of tensor tileM=" << cfg::tileM << "!" << std::endl;
    return -1;
  }

  if ((N % cfg::tileN) != 0) {
    std::cout << "Error: N must be a multiple of tensor tileN=" << cfg::tileN << "!" << std::endl;
    return -1;
  }

  if ((K % cfg::tileK) != 0) {
    std::cout << "Error: K must be a multiple of tensor tileK=" << cfg::tileK << "!" << std::endl;
    return -1;
  }

  const uint64_t elementsA = uint64_t(M) * K;
  const uint64_t elementsB = uint64_t(K) * N;
  const uint64_t elementsC = uint64_t(M) * N;
  const size_t max_bytes = std::numeric_limits<size_t>::max();
  if (elementsA > max_bytes / sizeof(itype_t)
      || elementsB > max_bytes / sizeof(itype_t)
      || elementsC > max_bytes / sizeof(otype_t)) {
    std::cerr << "Error: matrix byte count exceeds the host address space!" << std::endl;
    return -1;
  }
  // Host loops and offsets use uint32_t, including expanded sub-byte K indices.
  constexpr uint32_t subbytes = vt::ITYPE::bits < 8 ? 8 / vt::ITYPE::bits : 1;
  if (elementsA > UINT32_MAX / subbytes || elementsB > UINT32_MAX / subbytes
      || elementsC > UINT32_MAX) {
    std::cerr << "Error: matrix elements exceed the uint32 indexing range!" << std::endl;
    return -1;
  }
  const size_t sizeA = static_cast<size_t>(elementsA);
  const size_t sizeB = static_cast<size_t>(elementsB);
  const size_t sizeC = static_cast<size_t>(elementsC);

  std::srand(50);

  std::cout << "open device connection" << std::endl;
  RT_CHECK(vx_device_open(0, &device));

  // create the command queue used for the async enqueue chain
  vx_queue_info_t qi = { sizeof(qi), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0 };
  RT_CHECK(vx_queue_create(device, &qi, &queue));

  uint64_t isa_flags;
  RT_CHECK(vx_device_query(device, VX_CAPS_ISA_FLAGS, &isa_flags));
  bool has_ext = (isa_flags & VX_ISA_EXT_TCU) != 0;
  if (!has_ext) {
    std::cout << "TCU extension not supported!" << std::endl;
    cleanup();
    return -1;
  }

  uint64_t NT;
  RT_CHECK(vx_device_query(device, VX_CAPS_NUM_THREADS, &NT));
  if (NT != VX_CFG_NUM_THREADS) {
    std::cout << "Error: device warp size (" << NT << ") must match VX_CFG_NUM_THREADS=" << VX_CFG_NUM_THREADS << "!" << std::endl;
    cleanup();
    return -1;
  }
  if (fixture != nullptr) {
    uint64_t clusters, cores, warps, issue_width;
    RT_CHECK(vx_device_query(device, VX_CAPS_NUM_CLUSTERS, &clusters));
    RT_CHECK(vx_device_query(device, VX_CAPS_NUM_CORES, &cores));
    RT_CHECK(vx_device_query(device, VX_CAPS_NUM_WARPS, &warps));
    RT_CHECK(vx_device_query(device, VX_CAPS_ISSUE_WIDTH, &issue_width));
    if (clusters != 1 || cores != 1 || warps != 4 || issue_width != 1
        || VX_ISA_ARCH(isa_flags) != 64 || (isa_flags & VX_ISA_EXT_LMEM) == 0
        || (isa_flags & VX_ISA_EXT_LDST_MATRIX) != 0) {
      std::cerr << "Error: device capabilities do not match the p02-tfr fixture profile!" << std::endl;
      cleanup();
      return -1;
    }
  }

  uint32_t grid_dim[2]  = {N / cfg::tileN, M / cfg::tileM};
  uint32_t block_dim[2] = {(uint32_t)NT, 1};

  std::cout << "input data type: " << vt::ITYPE::name << " (id=" << vt::ITYPE::id << ")" << std::endl;
  std::cout << "output data type: " << vt::OTYPE::name << " (id=" << vt::OTYPE::id << ")" << std::endl;
  std::cout << "WMMA Core Dimension: M=" << cfg::tcM << ", N=" << cfg::tcN << ", K=" << cfg::tcK << std::endl;
  std::cout << "WMMA Tile Dimension: M=" << cfg::tileM << ", N=" << cfg::tileN << ", K=" << cfg::tileK << std::endl;
  std::cout << "matrix A: " << M << "x" << K << std::endl;
  std::cout << "matrix B: " << K << "x" << N << std::endl;
  std::cout << "matrix C: " << M << "x" << N << std::endl;

  // set matrix dimensions
  kernel_arg.M = M;
  kernel_arg.N = N;
  kernel_arg.K = K;

  std::cout << "allocate device memory" << std::endl;
  RT_CHECK(vx_buffer_create(device, sizeA * sizeof(itype_t), VX_MEM_READ, &A_buffer));
  RT_CHECK(vx_buffer_address(A_buffer, &kernel_arg.A_addr));
  RT_CHECK(vx_buffer_create(device, sizeB * sizeof(itype_t), VX_MEM_READ, &B_buffer));
  RT_CHECK(vx_buffer_address(B_buffer, &kernel_arg.B_addr));
  RT_CHECK(vx_buffer_create(device, sizeC * sizeof(otype_t), VX_MEM_WRITE, &C_buffer));
  RT_CHECK(vx_buffer_address(C_buffer, &kernel_arg.C_addr));

#ifdef PROFILE_ENABLE
  uint32_t num_blocks = grid_dim[0] * grid_dim[1];
  RT_CHECK(vx_buffer_create(device, num_blocks * sizeof(uint32_t), VX_MEM_WRITE, &cycles_buffer));
  RT_CHECK(vx_buffer_address(cycles_buffer, &kernel_arg.cycles_addr));
#endif

  std::cout << "A_addr=0x" << std::hex << kernel_arg.A_addr << std::endl;
  std::cout << "B_addr=0x" << std::hex << kernel_arg.B_addr << std::endl;
  std::cout << "C_addr=0x" << std::hex << kernel_arg.C_addr << std::dec << std::endl;

  // Upload storage must outlive the asynchronous writes.
  std::vector<itype_t> h_A;
  std::vector<itype_t> h_B;
  std::vector<uint8_t> h_A_packed;
  std::vector<uint8_t> h_B_col;
  if (fixture != nullptr) {
    h_A_packed = p02::packed_bytes(fixture->a_words, fixture->a_count);
    h_B_col = p02::packed_bytes(fixture->b_words, fixture->b_count);
  } else {
    h_A.resize(sizeA);
    h_B.resize(sizeB);
    for (uint32_t i = 0; i < sizeA; ++i) {
      h_A[i] = generate_A_value<vt::ITYPE>();
    }
    for (uint32_t i = 0; i < sizeB; ++i) {
      h_B[i] = generate_B_value<vt::ITYPE>();
    }
    if constexpr (std::is_same<vt::ITYPE, vt::bf8>::value) {
      if (xz) {
        // Row 0 of A is 0 at even k and 1.75 * 2^-11 at odd k; B is 57344 in
        // even rows and 1.75 * 2^-11 in odd rows. The zero products must not
        // set the exponent of their K pair.
        for (uint32_t k = 0; k < K; ++k) {
          h_A[k] = (k & 1) ? 0x13 : 0x00;
        }
        for (uint32_t i = 0; i < sizeB; ++i) {
          h_B[i] = ((i / N) & 1) ? 0x13 : 0x7b;
        }
      }
    }
    h_B_col.resize(sizeB * sizeof(itype_t));
    if constexpr (std::is_same<vt::ITYPE, vt::int4>::value ||
                  std::is_same<vt::ITYPE, vt::uint4>::value) {
      convert_row_to_col_major_4bit(h_B_col.data(), N, 2 * K, (uint8_t*)h_B.data());
    } else {
      convert_row_to_col_major((itype_t*)h_B_col.data(), h_B.data(), K, N);
    }
  }

  const void* a_data = fixture != nullptr
      ? static_cast<const void*>(h_A_packed.data()) : static_cast<const void*>(h_A.data());
  std::cout << "upload matrix A buffer" << std::endl;
  RT_CHECK(vx_enqueue_write(queue, A_buffer, 0, a_data,
                            sizeA * sizeof(itype_t), 0, nullptr, nullptr));
  std::cout << "upload matrix B buffer" << std::endl;
  RT_CHECK(vx_enqueue_write(queue, B_buffer, 0, h_B_col.data(),
                            sizeB * sizeof(itype_t), 0, nullptr, nullptr));

  std::cout << "load kernel module" << std::endl;
  RT_CHECK(vx_module_load_file(device, kernel_file, &module_));
  RT_CHECK(vx_module_get_kernel(module_, "main", &kernel));

  // Host result buffers — must outlive the async reads enqueued below.
  std::vector<otype_t> h_C(fixture != nullptr ? 0 : sizeC);
  std::vector<uint32_t> h_C_bits(fixture != nullptr ? sizeC : 0);
  std::vector<uint32_t> h_C_poison(h_C_bits.size());
  if (fixture != nullptr) {
    for (size_t i = 0; i < sizeC; ++i) {
      h_C_poison[i] = fixture->expected[i] ^ uint32_t(1);
    }
  }
#ifdef PROFILE_ENABLE
  std::vector<uint32_t> h_cycles(num_blocks);
#endif

  // launch args are constant across repeats — args passed as a host blob (UVA)
  vx_launch_info_t li = {};
  li.struct_size  = sizeof(li);
  li.kernel       = kernel;
  li.args_host    = &kernel_arg;
  li.args_size    = sizeof(kernel_arg);
  li.ndim         = 2;
  li.grid_dim[0]  = grid_dim[0];
  li.grid_dim[1]  = grid_dim[1];
  li.block_dim[0] = block_dim[0];
  li.block_dim[1] = block_dim[1];

  // reference is input-invariant across repeats — compute once
  std::vector<otype_t> h_ref;
  if (fixture == nullptr) {
    h_ref.resize(sizeC);
    matmul_cpu(h_ref.data(), h_A.data(), h_B.data(), M, N, K);
  }

  // Every iteration recomputes the same result from the same inputs, so a
  // mismatch on a later iteration means device state leaked across launches.
  uint64_t errors = 0;
  for (uint32_t iter = 0; iter < xr; ++iter) {
    vx_event_h poison_ev = nullptr;
    if (fixture != nullptr) {
      // Poison both destinations so a missed write or read cannot reuse a pass.
      h_C_bits = h_C_poison;
      RT_CHECK(vx_enqueue_write(queue, C_buffer, 0, h_C_poison.data(),
                                sizeC * sizeof(uint32_t), 0, nullptr, &poison_ev));
    } else {
      std::fill(h_C.begin(), h_C.end(), otype_t(0));
    }

    auto time_start = std::chrono::high_resolution_clock::now();

    std::cout << "[iter " << iter << "] launch kernel" << std::endl;
    vx_event_h launch_ev = nullptr;
    RT_CHECK(vx_enqueue_launch(queue, &li, poison_ev != nullptr ? 1 : 0,
                               poison_ev != nullptr ? &poison_ev : nullptr, &launch_ev));

    // read results back — chained after the launch on the same queue
    std::cout << "[iter " << iter << "] download destination buffer" << std::endl;
    vx_event_h read_ev = nullptr;
    void* c_data = fixture != nullptr
        ? static_cast<void*>(h_C_bits.data()) : static_cast<void*>(h_C.data());
    RT_CHECK(vx_enqueue_read(queue, c_data, C_buffer, 0,
                             sizeC * sizeof(otype_t), 1, &launch_ev, &read_ev));
#ifdef PROFILE_ENABLE
    vx_event_h cyc_ev = nullptr;
    RT_CHECK(vx_enqueue_read(queue, h_cycles.data(), cycles_buffer, 0,
                             num_blocks * sizeof(uint32_t), 1, &read_ev, &cyc_ev));
#endif

    std::cout << "[iter " << iter << "] wait for completion" << std::endl;
#ifdef PROFILE_ENABLE
    RT_CHECK(vx_event_wait_value(cyc_ev, 1, VX_TIMEOUT_INFINITE));
    vx_event_release(cyc_ev);
#else
    RT_CHECK(vx_event_wait_value(read_ev, 1, VX_TIMEOUT_INFINITE));
#endif
    vx_event_release(read_ev);
    vx_event_release(launch_ev);
    if (poison_ev != nullptr) {
      vx_event_release(poison_ev);
    }

    auto time_end = std::chrono::high_resolution_clock::now();
    double elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(time_end - time_start).count();
    printf("[iter %u] Elapsed time: %lg ms\n", iter, elapsed);

#ifdef PROFILE_ENABLE
    // report TCU cycle counts
    {
      uint32_t max_cycles = 0;
      for (auto c : h_cycles) {
        max_cycles = std::max(max_cycles, c);
      }
      printf("[iter %u] TCU_CYCLES: max=%u (across %u blocks)\n", iter, max_cycles, num_blocks);
    }
#endif

    std::cout << "[iter " << iter << "] verify result" << std::endl;
    if (fixture != nullptr) {
      size_t fixture_errors = p02::report_result(*fixture, h_C_bits, iter, MAX_ERRORS);
      printf("[iter %u] %s (%zu errors)\n", iter, fixture_errors ? "MISMATCH" : "match", fixture_errors);
      errors += fixture_errors;
    } else {
      int iter_errors = 0;
      for (uint32_t i = 0; i < h_ref.size(); ++i) {
        if (!Comparator<vt::OTYPE>::compare(h_C[i], h_ref[i], i, iter_errors)) {
          ++iter_errors;
        }
      }
      printf("[iter %u] %s (%d errors)\n", iter, iter_errors ? "MISMATCH" : "match", iter_errors);
      errors += iter_errors;
    }

    // cumulative counters: a cycle count that stops advancing across
    // iterations means the device is no longer retiring work
    if (xr > 1) {
      vx_device_dump_perf(device, stdout);
    }
  }

  std::cout << "cleanup" << std::endl;
  cleanup();

  if (errors != 0) {
    std::cout << "Found " << std::dec << errors << " / " << sizeC << " errors!" << std::endl;
    std::cout << "FAILED!" << std::endl;
    return errors != 0;
  }

  std::cout << "PASSED!" << std::endl;

  return 0;
}
