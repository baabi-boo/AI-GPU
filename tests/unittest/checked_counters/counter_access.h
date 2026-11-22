// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "cache.h"

namespace vortex {
class Core;
class Memory;
class TcuTbuf;
}

namespace counter_test {

struct Selector {
  const char* name;
  uint32_t perf_class;
  uint32_t csr;
  std::vector<vortex::PerfCounter*> components;
};

std::array<Selector, 33> selectors(vortex::Core& core);
vortex::PerfCounter& pending_reads(vortex::Core& core);

namespace detail {

// Explicit instantiation leaves access checking in included model code intact.
template <typename Tag, auto Member>
struct MemberAccess {
  friend constexpr auto member(Tag) noexcept {
    return Member;
  }
};

vortex::Cache& cache(vortex::Core& core, bool instruction);
std::vector<vortex::PerfCounter*> cache_components(
    vortex::Cache& cache, vortex::PerfCounter vortex::Cache::PerfStats::* member,
    size_t expected_banks);
vortex::PerfCounter& memory_bank_stalls(vortex::Memory& memory);
std::vector<vortex::PerfCounter*> tensor_reads(vortex::TcuTbuf& buffer);

} // namespace detail
} // namespace counter_test
