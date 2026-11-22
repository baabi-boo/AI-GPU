// SPDX-License-Identifier: Apache-2.0
#include "counter_access.h"

#include "core.h"
#include "local_mem.h"
#include "mem_coalescer.h"
#include "processor_impl.h"
#include "tcu_unit.h"

#include <stdexcept>

#if !defined(PERF_ENABLE) || !defined(VX_CFG_XLEN_64) || !defined(VX_CFG_EXT_TCU_ENABLE)
#error "Counter access requires RV64, performance counters and tensor support"
#endif
#if defined(SIMX_FUNCTIONAL) || SIMX_MT > 1 || defined(VX_CFG_VM_ENABLE)
#error "Counter access requires serial timing mode without virtual memory"
#endif
#if defined(VX_CFG_L2_ENABLE) || defined(VX_CFG_L3_ENABLE) || defined(VX_CFG_TCU_WGMMA_ENABLE)
#error "Counter access requires the ordinary single-core cache topology"
#endif

namespace {
using vortex::VX_CFG_DCACHE_NUM_REQS;

static_assert(VX_CFG_XLEN == 64 && VX_CFG_NUM_CLUSTERS == 1 && VX_CFG_NUM_CORES == 1);
static_assert(VX_CFG_SOCKET_SIZE == 1 && VX_CFG_NUM_WARPS == 4 && VX_CFG_NUM_THREADS == 4);
static_assert(VX_CFG_ISSUE_WIDTH == 1 && VX_CFG_NUM_LSU_BLOCKS == 1);
static_assert(VX_CFG_ICACHE_ENABLED && VX_CFG_DCACHE_ENABLED && VX_CFG_LMEM_ENABLED);
static_assert(VX_CFG_ICACHE_NUM_BANKS == 1 && VX_CFG_DCACHE_NUM_BANKS == 2);
static_assert(VX_CFG_NUM_TCU_BLOCKS == 1);
static_assert(vortex::CP_ON_L2 == 0 && vortex::CP_ON_L3 == 0);
} // namespace

namespace counter_test::detail {

struct ProcessorMemory {
  friend constexpr auto member(ProcessorMemory) noexcept;
};
struct MemoryReads {
  friend constexpr auto member(MemoryReads) noexcept;
};
struct MemoryWrites {
  friend constexpr auto member(MemoryWrites) noexcept;
};
struct MemoryLatency {
  friend constexpr auto member(MemoryLatency) noexcept;
};
struct PendingReads {
  friend constexpr auto member(PendingReads) noexcept;
};
template struct MemberAccess<ProcessorMemory, &vortex::ProcessorImpl::memsim_>;
template struct MemberAccess<MemoryReads, &vortex::ProcessorImpl::perf_mem_reads_>;
template struct MemberAccess<MemoryWrites, &vortex::ProcessorImpl::perf_mem_writes_>;
template struct MemberAccess<MemoryLatency, &vortex::ProcessorImpl::perf_mem_latency_>;
template struct MemberAccess<PendingReads, &vortex::ProcessorImpl::perf_mem_pending_reads_>;

} // namespace counter_test::detail

namespace counter_test {
namespace {

vortex::ProcessorImpl& processor(vortex::Core& core) {
  auto* owner = core.processor();
  if (core.id() != 0 || owner == nullptr || !(owner->*member(detail::ProcessorMemory{}))) {
    throw std::runtime_error("counter access requires core zero and its memory owner");
  }
  return *owner;
}

} // namespace

vortex::PerfCounter& pending_reads(vortex::Core& core) {
  return processor(core).*member(detail::PendingReads{});
}

std::array<Selector, 33> selectors(vortex::Core& core) {
  auto& owner = processor(core);
  if (!core.local_mem() || !core.mem_coalescer(0) || !core.tcu_unit()
      || !core.tcu_unit()->tbuf()) {
    throw std::runtime_error("counter access requires the complete memory and tensor inventory");
  }
  auto& counters = core.perf_stats();
  auto& local = const_cast<vortex::LocalMem::PerfStats&>(core.local_mem()->perf_stats());
  auto& coalescer = const_cast<vortex::MemCoalescer::PerfStats&>(core.mem_coalescer(0)->perf_stats());
  auto& tensor = const_cast<vortex::TcuUnit::PerfStats&>(core.tcu_unit()->perf_stats());
  auto& icache = detail::cache(core, true);
  auto& dcache = detail::cache(core, false);
  using CacheStats = vortex::Cache::PerfStats;
  return {{
    {"cycles", VX_DCR_MPM_CLASS_BASE, VX_CSR_MCYCLE, {&counters.cycles}},
    {"instructions", VX_DCR_MPM_CLASS_BASE, VX_CSR_MINSTRET, {&counters.instrs}},
    {"core_sched_idle", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_SCHED_IDLE, {&counters.sched_idle}},
    {"core_active_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ACTIVE_WARPS, {&counters.active_warps}},
    {"core_stalled_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALLED_WARPS, {&counters.stalled_warps}},
    {"core_issued_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ISSUED_WARPS, {&counters.issued_warps}},
    {"core_issued_threads", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ISSUED_THREADS, {&counters.issued_threads}},
    {"core_stall_scrb", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_SCRB, {&counters.scrb_stalls}},
    {"core_stall_lsu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_LSU, {&counters.lsu_stalls}},
    {"core_stall_tcu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_TCU, {&counters.tcu_stalls}},
    {"core_instr_tcu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_INSTR_TCU, {&counters.tcu_instrs}},
    {"core_loads", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_LOADS, {&counters.loads}},
    {"core_stores", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STORES, {&counters.stores}},
    {"icache_reads", VX_DCR_MPM_CLASS_ICACHE, VX_CSR_MPM_ICACHE_READS,
      detail::cache_components(icache, &CacheStats::reads, 1)},
    {"icache_miss_r", VX_DCR_MPM_CLASS_ICACHE, VX_CSR_MPM_ICACHE_MISS_R,
      detail::cache_components(icache, &CacheStats::read_misses, 1)},
    {"icache_mshr_st", VX_DCR_MPM_CLASS_ICACHE, VX_CSR_MPM_ICACHE_MSHR_ST,
      detail::cache_components(icache, &CacheStats::mshr_stalls, 1)},
    {"dcache_reads", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_READS,
      detail::cache_components(dcache, &CacheStats::reads, 2)},
    {"dcache_writes", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_WRITES,
      detail::cache_components(dcache, &CacheStats::writes, 2)},
    {"dcache_miss_r", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_MISS_R,
      detail::cache_components(dcache, &CacheStats::read_misses, 2)},
    {"dcache_miss_w", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_MISS_W,
      detail::cache_components(dcache, &CacheStats::write_misses, 2)},
    {"dcache_evicts", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_EVICTS,
      detail::cache_components(dcache, &CacheStats::evictions, 2)},
    {"dcache_mshr_st", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_MSHR_ST,
      detail::cache_components(dcache, &CacheStats::mshr_stalls, 2)},
    {"lmem_reads", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_READS, {&local.reads}},
    {"lmem_writes", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_WRITES, {&local.writes}},
    {"lmem_bank_st", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_BANK_ST, {&local.bank_stalls}},
    {"coalescer_miss", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_COALESCER_MISS, {&coalescer.misses}},
    {"memory_reads", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_READS, {&(owner.*member(detail::MemoryReads{}))}},
    {"memory_writes", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_WRITES, {&(owner.*member(detail::MemoryWrites{}))}},
    {"memory_lt", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_LT, {&(owner.*member(detail::MemoryLatency{}))}},
    {"memory_bank_st", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_BANK_ST,
      {&detail::memory_bank_stalls(*(owner.*member(detail::ProcessorMemory{})))}},
    {"tcu_tbuf_stalls", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_TBUF_STALLS, {&tensor.tbuf_stalls}},
    {"tcu_tbuf_cache_hits", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_TBUF_CACHE_HITS, {&tensor.tbuf_cache_hits}},
    {"tcu_lmem_reads", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_LMEM_READS,
      detail::tensor_reads(*core.tcu_unit()->tbuf())},
  }};
}

} // namespace counter_test
