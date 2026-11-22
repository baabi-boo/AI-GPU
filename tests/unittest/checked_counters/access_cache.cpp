// SPDX-License-Identifier: Apache-2.0
#include "counter_access.h"
#include "../../../sim/simx/mem/cache.cpp"

#include <stdexcept>

namespace counter_test::detail {

struct CacheImpl {
  friend constexpr auto member(CacheImpl) noexcept;
};
struct CacheConfig {
  friend constexpr auto member(CacheConfig) noexcept;
};
struct CacheBanks {
  friend constexpr auto member(CacheBanks) noexcept;
};
struct BankCounters {
  friend constexpr auto member(BankCounters) noexcept;
};
template struct MemberAccess<CacheImpl, &vortex::Cache::impl_>;
template struct MemberAccess<CacheConfig, &vortex::Cache::Impl::config_>;
template struct MemberAccess<CacheBanks, &vortex::Cache::Impl::banks_>;
template struct MemberAccess<BankCounters, &CacheBank::perf_stats_>;

std::vector<vortex::PerfCounter*> cache_components(
    vortex::Cache& cache, vortex::PerfCounter vortex::Cache::PerfStats::* field,
    size_t expected_banks) {
  auto* impl = cache.*member(CacheImpl{});
  if (field == nullptr || impl == nullptr) {
    throw std::runtime_error("counter access requires a live cache field");
  }
  const auto& banks = impl->*member(CacheBanks{});
  if ((impl->*member(CacheConfig{})).bypass || banks.size() != expected_banks) {
    throw std::runtime_error("counter access cache bank topology differs");
  }
  std::vector<vortex::PerfCounter*> result;
  result.reserve(expected_banks);
  for (const auto& bank : banks) {
    if (!bank) {
      throw std::runtime_error("counter access cache bank is missing");
    }
    result.push_back(&(((*bank).*member(BankCounters{})).*field));
  }
  return result;
}

} // namespace counter_test::detail
