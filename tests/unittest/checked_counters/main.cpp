// SPDX-License-Identifier: Apache-2.0

#include <array>
#include <chrono>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <type_traits>
#include <utility>

#include "core.h"
#include "processor.h"
#include "processor_impl.h"
#include "cache.h"
#include "local_mem.h"
#include "mem_coalescer.h"
#include "tcu_unit.h"
#include "mem.h"
#include "../../../sw/runtime/common/async_run.h"

#if !defined(PERF_ENABLE) || !defined(VX_CFG_XLEN_64) || !defined(VX_CFG_EXT_TCU_ENABLE)
#error "The linked counter test requires RV64, PERF and TCU"
#endif
#if defined(SIMX_FUNCTIONAL) || SIMX_MT > 1
#error "The linked counter test requires serial timing mode"
#endif
#if !defined(VX_CFG_FPU_TYPE_STD) || !defined(VX_CFG_TCU_TYPE_TFR)
#error "The linked counter test requires STD scalar and TFR tensor arithmetic"
#endif
#if defined(VX_CFG_L2_ENABLE) || defined(VX_CFG_L3_ENABLE)
#error "The linked counter test requires the single-core cache topology"
#endif

static_assert(VX_CFG_XLEN == 64);
static_assert(VX_CFG_NUM_CLUSTERS == 1 && VX_CFG_NUM_CORES == 1);
static_assert(VX_CFG_NUM_WARPS == 4 && VX_CFG_NUM_THREADS == 4);
static_assert(VX_CFG_ISSUE_WIDTH == 1 && VX_CFG_NUM_LSU_BLOCKS == 1);

using vortex::PerfCounter;

static_assert(std::is_same_v<decltype(vortex::ProcessorImpl::PerfStats::mem_reads), PerfCounter>);
static_assert(std::is_same_v<decltype(vortex::ProcessorImpl::PerfStats::mem_writes), PerfCounter>);
static_assert(std::is_same_v<decltype(vortex::ProcessorImpl::PerfStats::mem_latency), PerfCounter>);

namespace {

constexpr uint64_t kMax = std::numeric_limits<uint64_t>::max();

struct CounterValue {
  uint64_t value;
  uint32_t low;
  uint32_t high;
};

constexpr std::array<CounterValue, 10> kValues = {{
  {0x0000000000000000ull, 0x00000000u, 0x00000000u},
  {0x0000000000000001ull, 0x00000001u, 0x00000000u},
  {0x00000000ffffffffull, 0xffffffffu, 0x00000000u},
  {0x0000000100000000ull, 0x00000000u, 0x00000001u},
  {0x0000000100000001ull, 0x00000001u, 0x00000001u},
  {0x00000abc12345678ull, 0x12345678u, 0x00000abcu},
  {0x00000fffffffffffull, 0xffffffffu, 0x00000fffu},
  {0x0000100000000000ull, 0x00000000u, 0x00001000u},
  {0xfedcba9889abcdefull, 0x89abcdefu, 0xfedcba98u},
  {0xffffffffffffffffull, 0xffffffffu, 0xffffffffu},
}};

struct Selector {
  const char* name;
  uint32_t perf_class;
  uint32_t csr;
  PerfCounter* storage;
};

constexpr const char* kUnseeded[] = {
  "icache_reads", "icache_miss_r", "icache_mshr_st",
  "dcache_reads", "dcache_writes", "dcache_miss_r", "dcache_miss_w",
  "dcache_evicts", "dcache_mshr_st", "memory_reads", "memory_writes",
  "memory_lt", "memory_bank_st", "tcu_lmem_reads",
};

constexpr std::array<PerfCounter vortex::Cache::PerfStats::*, 8> kCacheFields = {{
  &vortex::Cache::PerfStats::reads,
  &vortex::Cache::PerfStats::writes,
  &vortex::Cache::PerfStats::read_misses,
  &vortex::Cache::PerfStats::write_misses,
  &vortex::Cache::PerfStats::evictions,
  &vortex::Cache::PerfStats::bank_stalls,
  &vortex::Cache::PerfStats::mshr_stalls,
  &vortex::Cache::PerfStats::mem_latency,
}};

constexpr std::array<PerfCounter vortex::LocalMem::PerfStats::*, 3> kLocalFields = {{
  &vortex::LocalMem::PerfStats::reads,
  &vortex::LocalMem::PerfStats::writes,
  &vortex::LocalMem::PerfStats::bank_stalls,
}};

constexpr std::array<PerfCounter vortex::TcuUnit::PerfStats::*, 4> kTensorFields = {{
  &vortex::TcuUnit::PerfStats::latency,
  &vortex::TcuUnit::PerfStats::tbuf_stalls,
  &vortex::TcuUnit::PerfStats::tbuf_cache_hits,
  &vortex::TcuUnit::PerfStats::lmem_reads,
}};

constexpr std::array<PerfCounter vortex::MemCoalescer::PerfStats::*, 1> kCoalescerFields = {{
  &vortex::MemCoalescer::PerfStats::misses,
}};

constexpr std::array<PerfCounter vortex::Memory::PerfStats::*, 1> kMemoryFields = {{
  &vortex::Memory::PerfStats::bank_stalls,
}};

std::array<Selector, 19> selectors(vortex::Core& core) {
  auto& counters = core.perf_stats();
  // These references expose storage owned by non-const model objects.
  auto& local = const_cast<vortex::LocalMem::PerfStats&>(core.local_mem()->perf_stats());
  auto& coalescer = const_cast<vortex::MemCoalescer::PerfStats&>(core.mem_coalescer(0)->perf_stats());
  auto& tensor = const_cast<vortex::TcuUnit::PerfStats&>(core.tcu_unit()->perf_stats());
  return {{
    {"cycles", VX_DCR_MPM_CLASS_BASE, VX_CSR_MCYCLE, &counters.cycles},
    {"instructions", VX_DCR_MPM_CLASS_BASE, VX_CSR_MINSTRET, &counters.instrs},
    {"core_sched_idle", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_SCHED_IDLE, &counters.sched_idle},
    {"core_active_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ACTIVE_WARPS, &counters.active_warps},
    {"core_stalled_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALLED_WARPS, &counters.stalled_warps},
    {"core_issued_warps", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ISSUED_WARPS, &counters.issued_warps},
    {"core_issued_threads", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_ISSUED_THREADS, &counters.issued_threads},
    {"core_stall_scrb", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_SCRB, &counters.scrb_stalls},
    {"core_stall_lsu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_LSU, &counters.lsu_stalls},
    {"core_stall_tcu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STALL_TCU, &counters.tcu_stalls},
    {"core_instr_tcu", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_INSTR_TCU, &counters.tcu_instrs},
    {"core_loads", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_LOADS, &counters.loads},
    {"core_stores", VX_DCR_MPM_CLASS_CORE, VX_CSR_MPM_STORES, &counters.stores},
    {"lmem_reads", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_READS, &local.reads},
    {"lmem_writes", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_WRITES, &local.writes},
    {"lmem_bank_st", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_LMEM_BANK_ST, &local.bank_stalls},
    {"coalescer_miss", VX_DCR_MPM_CLASS_MEM, VX_CSR_MPM_COALESCER_MISS, &coalescer.misses},
    {"tcu_tbuf_stalls", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_TBUF_STALLS, &tensor.tbuf_stalls},
    {"tcu_tbuf_cache_hits", VX_DCR_MPM_CLASS_TCU, VX_CSR_MPM_TCU_TBUF_CACHE_HITS, &tensor.tbuf_cache_hits},
  }};
}

class BoundaryTest {
public:
  BoundaryTest(vortex::Processor& processor, vortex::Core& core)
    : processor_(processor)
    , core_(core)
    , saved_class_(core.mpm_class()) {}

  void expect(const char* label, uint64_t actual, uint64_t expected) {
    ++checks_;
    if (actual != expected) {
      ++failures_;
      std::fprintf(stderr, "FAILED: %s actual=0x%016" PRIx64 " expected=0x%016" PRIx64 "\n",
                   label, actual, expected);
    }
  }

  void transport(const Selector& selector, const CounterValue& expected) {
    for (bool high_first : {false, true}) {
      uint32_t low;
      uint32_t high;
      if (high_first) {
        high = read_half(selector, true, expected.high);
        low = read_half(selector, false, expected.low);
      } else {
        low = read_half(selector, false, expected.low);
        high = read_half(selector, true, expected.high);
      }
      expect(selector.name, (uint64_t(high) << 32) | low, expected.value);
    }
  }

  template <typename Stats, size_t N>
  void aggregate(const std::array<PerfCounter Stats::*, N>& fields) {
    Stats first{};
    Stats second{};
    for (auto member : fields) {
      first.*member = kMax / 2;
      second.*member = kMax / 2 + 1;
    }
    first += second;
    Stats copied{};
    copied += first;
    for (auto member : fields) {
      expect("aggregate carry", first.*member, kMax);
      expect("aggregate source preserved", second.*member, kMax / 2 + 1);
      expect("aggregate copy", copied.*member, kMax);
    }
  }

  int result(const std::array<Selector, 19>& selected) const {
    if (failures_ != 0) {
      return 1;
    }
#ifdef SIMX_CHECKED_COUNTERS
    constexpr const char* checked = "true";
#else
    constexpr const char* checked = "false";
#endif
    std::printf("CHECKED_COUNTERS_RESULT {\"schema_version\":1,\"mode\":\"boundaries\","
                "\"xlen\":64,\"perf\":true,\"tcu\":true,\"checked\":%s,"
                "\"transport_selectors\":[", checked);
    for (size_t index = 0; index < selected.size(); ++index) {
      std::printf("%s\"%s\"", index == 0 ? "" : ",", selected[index].name);
    }
    std::printf("],\"vectors_per_selector\":10,\"transport_reads\":%zu,\"checks\":%zu,"
                "\"failures\":0,\"unseeded_available_selectors\":[", reads_, checks_);
    for (size_t index = 0; index < std::size(kUnseeded); ++index) {
      std::printf("%s\"%s\"", index == 0 ? "" : ",", kUnseeded[index]);
    }
    std::puts("],\"unavailable_selectors\":12,\"full_warm_coverage\":false,\"warm_execution\":false}");
    return 0;
  }

private:
  uint32_t read_half(const Selector& selector, bool high, uint32_t expected) {
    const uint32_t index = selector.csr - VX_CSR_MPM_BASE;
    const uint32_t tag = (selector.perf_class << 22) | ((index + (high ? 32u : 0u)) << 16) | core_.id();
    uint32_t value = ~expected;
    const int status = processor_.dcr_read(VX_DCR_BASE_MPM_VALUE, tag, &value);
    ++reads_;
    expect("DCR status", uint64_t(status), 0);
    expect(selector.name, value, expected);
    expect("MPM class restored", core_.mpm_class(), saved_class_);
    return value;
  }

  vortex::Processor& processor_;
  vortex::Core& core_;
  uint32_t saved_class_;
  size_t checks_ = 0;
  size_t reads_ = 0;
  size_t failures_ = 0;
};

int boundaries() {
  vortex::Processor processor;
  processor.reset();
  auto* core = processor.get_first_core();
  if (core == nullptr) {
    std::fputs("FAILED: processor has no first core\n", stderr);
    return 1;
  }
  auto selected = selectors(*core);
  BoundaryTest test(processor, *core);
  for (const auto& selector : selected) {
    test.expect("initial zero", *selector.storage, 0);
  }

  // Reads occur between ticks; the two halves observe the same seeded value.
  for (const auto& target : selected) {
    for (const auto& value : kValues) {
      for (size_t index = 0; index < selected.size(); ++index) {
        *selected[index].storage = 0x13579bdf00010000ull + index;
      }
      *target.storage = value.value;
      test.transport(target, value);
    }
  }

  for (size_t index = 0; index < selected.size(); ++index) {
    *selected[index].storage = 0x13579bdf00010000ull + index;
  }
  processor.reset();
  for (size_t index = 0; index < selected.size(); ++index) {
    test.expect("reset preserves cumulative storage", *selected[index].storage,
                0x13579bdf00010000ull + index);
  }
  test.aggregate(kCacheFields);
  test.aggregate(kLocalFields);
  test.aggregate(kTensorFields);
  test.aggregate(kCoalescerFields);
  test.aggregate(kMemoryFields);
  return test.result(selected);
}

#ifdef SIMX_CHECKED_COUNTERS

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

template <typename Action>
void expect_counter_error(Action&& action, vortex::PerfCounterError::Reason reason,
                          const char* diagnostic) {
  bool caught = false;
  try {
    std::forward<Action>(action)();
  } catch (const vortex::PerfCounterError& error) {
    require(error.reason() == reason, "counter exception reason differs");
    require(std::strcmp(error.what(), diagnostic) == 0, "counter exception diagnostic differs");
    caught = true;
  }
  require(caught, "invalid arithmetic did not throw PerfCounterError");
}

template <typename Action>
void expect_terminal_error(Action&& action) {
  bool caught = false;
  try {
    std::forward<Action>(action)();
  } catch (const std::runtime_error& error) {
    require(std::strcmp(error.what(), "simulator execution has failed") == 0,
            "terminal failure diagnostic differs");
    caught = true;
  }
  require(caught, "failed completion owner admitted an operation");
}

constexpr uint64_t kCapacity = 4096;
constexpr uint64_t kProgramAddress = 256;

void prepare_program(vortex::RAM& ram, vortex::Processor& processor) {
  ram.enable_acl(false);
  const std::array<uint32_t, 3> program{{0x00700193u, 0x0000700bu, 0x0000000bu}};
  ram.write(program.data(), kProgramAddress, sizeof(program));
  processor.attach_ram(&ram);
  const std::array<std::pair<uint32_t, uint32_t>, 19> descriptor{{
    {VX_DCR_KMU_STARTUP_ADDR0, static_cast<uint32_t>(kProgramAddress)},
    {VX_DCR_KMU_STARTUP_ADDR1, 0},
    {VX_DCR_KMU_KERNEL_ENTRY0, static_cast<uint32_t>(kProgramAddress)},
    {VX_DCR_KMU_KERNEL_ENTRY1, 0},
    {VX_DCR_KMU_STARTUP_ARG0, 0}, {VX_DCR_KMU_STARTUP_ARG1, 0},
    {VX_DCR_KMU_BLOCK_DIM_X, 1}, {VX_DCR_KMU_BLOCK_DIM_Y, 1},
    {VX_DCR_KMU_BLOCK_DIM_Z, 1}, {VX_DCR_KMU_GRID_DIM_X, 1},
    {VX_DCR_KMU_GRID_DIM_Y, 1}, {VX_DCR_KMU_GRID_DIM_Z, 1},
    {VX_DCR_KMU_BLOCK_SIZE, 1}, {VX_DCR_KMU_WARP_STEP_X, 1},
    {VX_DCR_KMU_WARP_STEP_Y, 1}, {VX_DCR_KMU_WARP_STEP_Z, 1},
    {VX_DCR_KMU_CLUSTER_DIM_X, 1}, {VX_DCR_KMU_CLUSTER_DIM_Y, 1},
    {VX_DCR_KMU_CLUSTER_DIM_Z, 1},
  }};
  for (const auto& field : descriptor) {
    require(processor.dcr_write(field.first, field.second) == 0,
            "launch descriptor write failed");
  }
}

void check_fresh_context() {
  vortex::RAM ram(kCapacity, kCapacity);
  vortex::Processor processor;
  vortex::AsyncRun run;
  prepare_program(ram, processor);
  run.start([&processor] { processor.run_checked(); });
  run.wait();
  require(!run.failed(), "fresh completion owner failed");
  require(run.busy() && !run.busy(), "fresh completion launch edge differs");
  auto* core = processor.get_first_core();
  require(core != nullptr && core->get_exitcode() == 7,
          "fresh context did not execute its architectural witness");
  require(uint64_t(core->perf_stats().cycles) > 0 && uint64_t(core->perf_stats().instrs) > 0,
          "fresh context did not update production counters");
  require(!processor.any_running(), "fresh context did not complete");
  run.join();
}

int core_overflow() {
  {
    vortex::RAM ram(kCapacity, kCapacity);
    vortex::Processor processor;
    unsigned later_tasks = 0;
    vortex::AsyncRun run;
    prepare_program(ram, processor);
    auto* core = processor.get_first_core();
    require(core != nullptr, "processor has no first core");
    core->perf_stats().cycles = kMax;
    run.start([&processor] { processor.run_checked(); });
    expect_counter_error([&run] { run.wait(); }, vortex::PerfCounterError::Reason::Overflow,
                         "SIMX_CHECKED_COUNTER_FAILURE: overflow");
    require(uint64_t(core->perf_stats().cycles) == kMax, "overflow changed the protected counter");
    require(uint64_t(core->perf_stats().instrs) == 0, "faulting launch retired instructions");
    require(run.failed(), "counter failure was not terminal");
    for (unsigned index = 0; index < 2; ++index) {
      expect_terminal_error([&run] { run.wait(); });
    }
    expect_terminal_error([&run] { run.check(); });
    expect_terminal_error([&run] { (void)run.busy(); });
    expect_terminal_error([&run] { run.wait_for(std::chrono::seconds(0)); });
    expect_terminal_error([&run, &later_tasks] { run.start([&later_tasks] { ++later_tasks; }); });
    expect_terminal_error([&run, &later_tasks] { run.invoke([&later_tasks] { ++later_tasks; }); });
    run.join();
    expect_terminal_error([&run] { run.check(); });
    require(run.failed() && later_tasks == 0, "failed completion admitted later work");
  }
  // The old model and its joined fault thread are gone before a new platform is born.
  check_fresh_context();
  std::puts("CHECKED_COUNTERS_FAILURE_RESULT {\"schema_version\":1,\"mode\":\"core-overflow\","
            "\"reason\":\"overflow\",\"checked\":true,\"exception_type\":\"PerfCounterError\","
            "\"protected_value_unchanged\":true,\"actual_model_updater\":true,\"terminal_failure\":true,"
            "\"sticky_failure_checks\":8,\"later_work_suppressed\":true,\"suppressed_tasks\":2,"
            "\"joined\":true,\"fresh_context_success\":true,\"public_runtime\":false,\"warm_execution\":false}");
  return 0;
}

int cache_overflow() {
  vortex::Cache::PerfStats first{};
  vortex::Cache::PerfStats second{};
  first.reads = kMax;
  second.reads = 1;
  const auto first_before = first;
  const auto second_before = second;
  expect_counter_error([&first, &second] { first += second; }, vortex::PerfCounterError::Reason::Overflow,
                       "SIMX_CHECKED_COUNTER_FAILURE: overflow");
  for (auto member : kCacheFields) {
    require(uint64_t(first.*member) == uint64_t(first_before.*member), "failed cache field changed");
    require(uint64_t(second.*member) == uint64_t(second_before.*member), "cache source field changed");
  }
  std::puts("CHECKED_COUNTERS_FAILURE_RESULT {\"schema_version\":1,\"mode\":\"cache-aggregate-overflow\","
            "\"reason\":\"overflow\",\"checked\":true,\"exception_type\":\"PerfCounterError\","
            "\"protected_value_unchanged\":true,\"source_unchanged\":true,"
            "\"scope\":\"production-cache-aggregate\",\"public_runtime\":false,\"warm_execution\":false}");
  return 0;
}

int pending_underflow() {
  PerfCounter pending = 0;
  expect_counter_error([&pending] { --pending; }, vortex::PerfCounterError::Reason::Underflow,
                       "SIMX_CHECKED_COUNTER_FAILURE: underflow");
  require(uint64_t(pending) == 0, "underflow changed the protected counter");
  std::puts("CHECKED_COUNTERS_FAILURE_RESULT {\"schema_version\":1,\"mode\":\"pending-underflow\","
            "\"reason\":\"underflow\",\"checked\":true,\"exception_type\":\"PerfCounterError\","
            "\"protected_value_unchanged\":true,\"scope\":\"pending-counter-primitive\","
            "\"public_runtime\":false,\"warm_execution\":false}");
  return 0;
}

#endif

} // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::fputs("Expected one linked counter scenario\n", stderr);
    return 2;
  }
  try {
    if (std::strcmp(argv[1], "boundaries") == 0) {
      return boundaries();
    }
#ifdef SIMX_CHECKED_COUNTERS
    if (std::strcmp(argv[1], "core-overflow") == 0) {
      return core_overflow();
    }
    if (std::strcmp(argv[1], "cache-aggregate-overflow") == 0) {
      return cache_overflow();
    }
    if (std::strcmp(argv[1], "pending-underflow") == 0) {
      return pending_underflow();
    }
    std::fputs("Unknown linked counter scenario\n", stderr);
    return 2;
#else
    std::fputs("Negative scenarios require checked counters\n", stderr);
    return 2;
#endif
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED: linked counter scenario: %s\n", error.what());
    return 1;
  } catch (...) {
    std::fputs("FAILED: linked counter scenario: unexpected exception\n", stderr);
    return 1;
  }
}
