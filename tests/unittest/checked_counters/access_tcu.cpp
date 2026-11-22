// SPDX-License-Identifier: Apache-2.0
#include "../../tests/unittest/checked_counters/counter_access.h"

#include <stdexcept>

namespace counter_test::detail {

struct TensorBufferImpl {
  friend constexpr auto member(TensorBufferImpl) noexcept;
};
struct TensorBuffers {
  friend constexpr auto member(TensorBuffers) noexcept;
};
template struct MemberAccess<TensorBufferImpl, &vortex::TcuTbuf::impl_>;
template struct MemberAccess<TensorBuffers, &vortex::TcuTbuf::Impl::bufs_>;

std::vector<vortex::PerfCounter*> tensor_reads(vortex::TcuTbuf& buffer) {
  auto* impl = buffer.*member(TensorBufferImpl{});
  if (impl == nullptr || (impl->*member(TensorBuffers{})).size() != 2) {
    throw std::runtime_error("counter access requires exactly two tensor buffers");
  }
  return {&impl->buf(0).reads_, &impl->buf(1).reads_};
}

} // namespace counter_test::detail
