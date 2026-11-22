// SPDX-License-Identifier: Apache-2.0
#include "counter_access.h"
#include "../../../sim/simx/mem/memory.cpp"

#include <stdexcept>

namespace counter_test::detail {

struct MemoryImpl {
  friend constexpr auto member(MemoryImpl) noexcept;
};
struct MemoryCrossbar {
  friend constexpr auto member(MemoryCrossbar) noexcept;
};
struct RequestCrossbar {
  friend constexpr auto member(RequestCrossbar) noexcept;
};
struct CrossbarCollisions {
  friend constexpr auto member(CrossbarCollisions) noexcept;
};
template struct MemberAccess<MemoryImpl, &vortex::Memory::impl_>;
template struct MemberAccess<MemoryCrossbar, &vortex::Memory::Impl::mem_xbar_>;
template struct MemberAccess<RequestCrossbar, &vortex::MemCrossBar::crossbar_>;
template struct MemberAccess<CrossbarCollisions, &vortex::TxCrossBar<vortex::MemReq>::collisions_>;

vortex::PerfCounter& memory_bank_stalls(vortex::Memory& memory) {
  auto* impl = memory.*member(MemoryImpl{});
  if (impl == nullptr) {
    throw std::runtime_error("counter access requires a live memory implementation");
  }
  const auto& crossbar = impl->*member(MemoryCrossbar{});
  if (!crossbar || crossbar->ReqOut.size() != 2) {
    throw std::runtime_error("counter access requires the two-bank memory crossbar");
  }
  const auto& requests = (*crossbar).*member(RequestCrossbar{});
  if (!requests) {
    throw std::runtime_error("counter access requires the two-bank memory crossbar");
  }
  return (*requests).*member(CrossbarCollisions{});
}

} // namespace counter_test::detail
