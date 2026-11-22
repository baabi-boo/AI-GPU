// SPDX-License-Identifier: Apache-2.0
#include "counter_access.h"
#include "../../../sim/simx/socket.cpp"

#include <stdexcept>

namespace counter_test::detail {

struct SocketImpl {
  friend constexpr auto member(SocketImpl) noexcept;
};
struct InstructionCaches {
  friend constexpr auto member(InstructionCaches) noexcept;
};
struct DataCaches {
  friend constexpr auto member(DataCaches) noexcept;
};
struct ClusterCaches {
  friend constexpr auto member(ClusterCaches) noexcept;
};
template struct MemberAccess<SocketImpl, &vortex::Socket::impl_>;
template struct MemberAccess<InstructionCaches, &vortex::Socket::Impl::icaches_>;
template struct MemberAccess<DataCaches, &vortex::Socket::Impl::dcaches_>;
template struct MemberAccess<ClusterCaches, &vortex::CacheCluster::caches_>;

vortex::Cache& cache(vortex::Core& core, bool instruction) {
  auto* socket = core.socket();
  if (socket == nullptr) {
    throw std::runtime_error("counter access requires an attached socket");
  }
  auto* impl = socket->*member(SocketImpl{});
  if (impl == nullptr) {
    throw std::runtime_error("counter access requires a live socket implementation");
  }
  const auto& cluster = instruction ? impl->*member(InstructionCaches{})
                                    : impl->*member(DataCaches{});
  if (!cluster) {
    throw std::runtime_error("counter access requires a cache cluster");
  }
  const auto& caches = (*cluster).*member(ClusterCaches{});
  if (caches.size() != 1 || !caches.front()) {
    throw std::runtime_error("counter access requires exactly one cache per cluster");
  }
  return *caches.front();
}

} // namespace counter_test::detail
