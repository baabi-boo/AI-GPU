// SPDX-License-Identifier: Apache-2.0
#ifndef VORTEX_AI_BENCH_COUNTERS_H
#define VORTEX_AI_BENCH_COUNTERS_H

#include <vortex2.h>
#include <VX_types.h>
#include <cstdint>

namespace p06 {

struct Capability {
  const char* name;
  uint32_t id;
};

struct Counter {
  const char* name;
  uint32_t mpm_class;
  uint32_t csr;
  uint32_t core_id;
  const char* scope;
  const char* unit;
  uint64_t required_isa;
};

constexpr Capability kCapabilities[] = {
  {"num_cores", VX_CAPS_NUM_CORES},
  {"num_clusters", VX_CAPS_NUM_CLUSTERS},
  {"socket_size", VX_CAPS_SOCKET_SIZE},
  {"num_warps", VX_CAPS_NUM_WARPS},
  {"num_threads", VX_CAPS_NUM_THREADS},
  {"issue_width", VX_CAPS_ISSUE_WIDTH},
  {"isa_flags", VX_CAPS_ISA_FLAGS},
  {"cache_line_bytes", VX_CAPS_CACHE_LINE_SIZE},
  {"local_mem_bytes", VX_CAPS_LOCAL_MEM_SIZE},
  {"global_mem_bytes", VX_CAPS_GLOBAL_MEM_SIZE},
  {"num_mem_banks", VX_CAPS_NUM_MEM_BANKS},
  {"mem_bank_bytes", VX_CAPS_MEM_BANK_SIZE},
  {"vm_support", VX_CAPS_VM_SUPPORT},
};

constexpr Counter kCounters[] = {
  {"cycles", VX_DCR_MPM_CLASS_BASE, VX_CSR_MCYCLE, 0, "core", "active_core_cycles", 0ull},
  {"instructions", VX_DCR_MPM_CLASS_BASE, VX_CSR_MINSTRET, 0, "core", "retired_macroinstructions", 0ull},
  {"core_sched_idle", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_SCHED_IDLE, 0, "core", "cycles", 0ull},
  {"core_active_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ACTIVE_WARPS, 0, "core", "warp_cycles", 0ull},
  {"core_stalled_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALLED_WARPS, 0, "core", "warp_cycles", 0ull},
  {"core_issued_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ISSUED_WARPS, 0, "core", "warps", 0ull},
  {"core_issued_threads", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ISSUED_THREADS, 0, "core", "threads", 0ull},
  {"core_stall_scrb", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_SCRB, 0, "core", "cycles", 0ull},
  {"core_stall_lsu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_LSU, 0, "core", "cycles", 0ull},
  {"core_stall_tcu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_TCU, 0, "core", "cycles", 0ull},
  {"core_instr_tcu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_INSTR_TCU, 0, "core", "instructions", 0ull},
  {"core_loads", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_LOADS, 0, "core", "issued_lane_requests", 0ull},
  {"core_stores", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STORES, 0, "core", "issued_lane_requests", 0ull},
  {"icache_reads", VX_DCR_MPM_CLASS_ICACHE, VX_CSR_MPM_ICACHE_READS, 0, "socket", "requests", VX_ISA_EXT_ICACHE},
  {"icache_miss_r", VX_DCR_MPM_CLASS_ICACHE, VX_CSR_MPM_ICACHE_MISS_R, 0, "socket", "requests", VX_ISA_EXT_ICACHE},
  {"icache_mshr_st", VX_DCR_MPM_CLASS_ICACHE, VX_CSR_MPM_ICACHE_MSHR_ST, 0, "socket", "cycles", VX_ISA_EXT_ICACHE},
  {"dcache_reads", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_READS, 0, "socket", "requests", VX_ISA_EXT_DCACHE},
  {"dcache_writes", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_WRITES, 0, "socket", "requests", VX_ISA_EXT_DCACHE},
  {"dcache_miss_r", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_MISS_R, 0, "socket", "requests", VX_ISA_EXT_DCACHE},
  {"dcache_miss_w", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_MISS_W, 0, "socket", "requests", VX_ISA_EXT_DCACHE},
  {"dcache_evicts", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_EVICTS, 0, "socket", "requests", VX_ISA_EXT_DCACHE},
  {"dcache_mshr_st", VX_DCR_MPM_CLASS_DCACHE, VX_CSR_MPM_DCACHE_MSHR_ST, 0, "socket", "cycles", VX_ISA_EXT_DCACHE},
  {"l2cache_reads", VX_DCR_MPM_CLASS_L2CACHE, VX_CSR_MPM_L2CACHE_READS, 0, "cluster", "requests", VX_ISA_EXT_L2CACHE},
  {"l2cache_writes", VX_DCR_MPM_CLASS_L2CACHE, VX_CSR_MPM_L2CACHE_WRITES, 0, "cluster", "requests", VX_ISA_EXT_L2CACHE},
  {"l2cache_miss_r", VX_DCR_MPM_CLASS_L2CACHE, VX_CSR_MPM_L2CACHE_MISS_R, 0, "cluster", "requests", VX_ISA_EXT_L2CACHE},
  {"l2cache_miss_w", VX_DCR_MPM_CLASS_L2CACHE, VX_CSR_MPM_L2CACHE_MISS_W, 0, "cluster", "requests", VX_ISA_EXT_L2CACHE},
  {"l2cache_evicts", VX_DCR_MPM_CLASS_L2CACHE, VX_CSR_MPM_L2CACHE_EVICTS, 0, "cluster", "requests", VX_ISA_EXT_L2CACHE},
  {"l2cache_mshr_st", VX_DCR_MPM_CLASS_L2CACHE, VX_CSR_MPM_L2CACHE_MSHR_ST, 0, "cluster", "cycles", VX_ISA_EXT_L2CACHE},
  {"l3cache_reads", VX_DCR_MPM_CLASS_L3CACHE, VX_CSR_MPM_L3CACHE_READS, 0, "global", "requests", VX_ISA_EXT_L3CACHE},
  {"l3cache_writes", VX_DCR_MPM_CLASS_L3CACHE, VX_CSR_MPM_L3CACHE_WRITES, 0, "global", "requests", VX_ISA_EXT_L3CACHE},
  {"l3cache_miss_r", VX_DCR_MPM_CLASS_L3CACHE, VX_CSR_MPM_L3CACHE_MISS_R, 0, "global", "requests", VX_ISA_EXT_L3CACHE},
  {"l3cache_miss_w", VX_DCR_MPM_CLASS_L3CACHE, VX_CSR_MPM_L3CACHE_MISS_W, 0, "global", "requests", VX_ISA_EXT_L3CACHE},
  {"l3cache_evicts", VX_DCR_MPM_CLASS_L3CACHE, VX_CSR_MPM_L3CACHE_EVICTS, 0, "global", "requests", VX_ISA_EXT_L3CACHE},
  {"l3cache_mshr_st", VX_DCR_MPM_CLASS_L3CACHE, VX_CSR_MPM_L3CACHE_MSHR_ST, 0, "global", "cycles", VX_ISA_EXT_L3CACHE},
  {"lmem_reads", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_READS, 0, "core", "requests", VX_ISA_EXT_LMEM},
  {"lmem_writes", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_WRITES, 0, "core", "requests", VX_ISA_EXT_LMEM},
  {"lmem_bank_st", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_BANK_ST, 0, "core", "cycles", VX_ISA_EXT_LMEM},
  {"coalescer_miss", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_COALESCER_MISS, 0, "core", "extra_coalescing_rounds", 0ull},
  {"memory_reads", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_READS, 0, "global", "requests", 0ull},
  {"memory_writes", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_WRITES, 0, "global", "requests", 0ull},
  {"memory_lt", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_LT, 0, "global", "request_cycles", 0ull},
  {"memory_bank_st", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_MEM_BANK_ST, 0, "global", "cycles", 0ull},
  {"tcu_tbuf_stalls", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_TBUF_STALLS, 0, "core", "cycles", VX_ISA_EXT_TCU},
  {"tcu_tbuf_cache_hits", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_TBUF_CACHE_HITS, 0, "core", "tile_reuse_hits", VX_ISA_EXT_TCU},
  {"tcu_lmem_reads", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_LMEM_READS, 0, "core", "requests", VX_ISA_EXT_TCU},
};

} // namespace p06

#endif
