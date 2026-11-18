// SPDX-License-Identifier: Apache-2.0

#include <ai_matmul_args.h>
#include <ai_matmul_profile.h>
#include <vx_spawn2.h>
#include <vx_tensor.h>

namespace va = vortex::ai;
namespace vt = vortex::tensor;
using ctx = vt::wmma_context<VX_CFG_NUM_THREADS, vt::ITYPE, vt::OTYPE, false, 8, 0, false>;

static_assert(ctx::tileM == 8 && ctx::tileN == 4 && ctx::tileK == 8);
static_assert(sizeof(uintptr_t) == 8);

__kernel void kernel_main(const uint8_t* __UNIFORM__ bytes) {
  va::MatmulArguments arg;
  if (!va::decode_matmul_arguments(bytes, va::kArgumentBytes, va::kMatmulInputDType, &arg)
      || blockDim.x != 4 || blockDim.y != 1 || blockDim.z != 1
      || gridDim.x != arg.n / 4 || gridDim.y != arg.m / 8 || gridDim.z != 1
      || blockIdx.x >= arg.n / 4 || blockIdx.y >= arg.m / 8 || blockIdx.z != 0) {
    return;
  }

  auto a = reinterpret_cast<const ctx::input_t*>(arg.a_address);
  auto b = reinterpret_cast<const ctx::input_t*>(arg.b_address);
  auto d = reinterpret_cast<ctx::output_t*>(arg.d_address);
  const size_t tile_row = blockIdx.y * ctx::tileM;
  const size_t tile_col = blockIdx.x * ctx::tileN;

  ctx::fragment_a frag_a;
  ctx::fragment_b frag_b;
  ctx::fragment_acc frag_d;
  ctx::fill_fragment(frag_d, 0);

  for (size_t k = 0; k < arg.k; k += ctx::tileK) {
    ctx::load_matrix_sync(frag_a, a + tile_row * arg.k + k, arg.k);
    ctx::load_matrix_sync<vt::col_major>(frag_b, b + tile_col * arg.k + k, arg.k);
    ctx::mma_sync(frag_d, frag_a, frag_b, frag_d);
  }
  ctx::store_matrix_sync(d + tile_row * arg.n + tile_col, frag_d, arg.n);
}
