// SPDX-License-Identifier: Apache-2.0

#include "public_hooks.h"
#include "../../../sw/runtime/common/vortex2_internal.h"
#include "../../regression/ai_bench_common/counters.h"

#include <array>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#if !defined(SIMX_CHECKED_COUNTERS) || !defined(VX_CFG_XLEN_64)
#error "The public counter diagnostic requires checked RV64 runtime flags"
#endif

namespace {

namespace hooks = counter_test::public_hooks;

constexpr uint64_t kTimeout = 30ull * 1000 * 1000 * 1000;
constexpr uint64_t kMax = std::numeric_limits<uint64_t>::max();
constexpr uint64_t kSentinel = 0xdecafbad12345678ull;
constexpr std::array<uint32_t, 3> kProgram{{0x00700193u, 0x0000700bu, 0x0000000bu}};
constexpr std::array<uint32_t, 3> kRejectedProgram{{~kProgram[0], ~kProgram[1], ~kProgram[2]}};
constexpr uint32_t kCpControl = 0x000;
constexpr uint32_t kCpStatus = 0x004;
constexpr uint32_t kQueueControl = 0x11c;
constexpr uint32_t kQueueTailLow = 0x120;
constexpr uint32_t kQueueTailHigh = 0x124;
constexpr uint32_t kQueueSequence = 0x128;
constexpr uint32_t kQueueError = 0x12c;

size_t checks = 0;

void require(bool condition, const char* message) {
  ++checks;
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void success(vx_result_t result, const char* message) {
  require(result == VX_SUCCESS, message);
}

template <typename Tag, auto Member>
struct MemberAccess {
  friend constexpr auto member(Tag) noexcept {
    return Member;
  }
};

struct Queues {
  friend constexpr auto member(Queues) noexcept;
};
struct Buffers {
  friend constexpr auto member(Buffers) noexcept;
};
struct CpExpected {
  friend constexpr auto member(CpExpected) noexcept;
};
struct CpTail {
  friend constexpr auto member(CpTail) noexcept;
};
struct CpHead {
  friend constexpr auto member(CpHead) noexcept;
};

template struct MemberAccess<Queues, &vx::Device::queues_>;
template struct MemberAccess<Buffers, &vx::Device::buffers_>;
template struct MemberAccess<CpExpected, &vx::Device::cp_expected_seqnum_>;
template struct MemberAccess<CpTail, &vx::Device::cp_tail_>;
template struct MemberAccess<CpHead, &vx::Device::cp_head_>;

class Context {
public:
  Context() {
    try {
      success(vx_device_open(0, &device), "public device open failed");
      success(vx_queue_create(device, nullptr, &queue), "public queue creation failed");
      success(vx_buffer_create(device, sizeof(kProgram), VX_MEM_READ_WRITE, &program),
              "public program buffer allocation failed");
      success(vx_buffer_address(program, &program_address_), "program address query failed");
      wait(write_program(), "public program upload failed");
      vx_event_h event = nullptr;
      success(vx_enqueue_read(queue, readback_.data(), program, 0, sizeof(readback_), 0,
                              nullptr, &event), "program readback enqueue failed");
      remember(event);
      wait(event, "program readback failed");
      require(readback_ == kProgram, "public program transfer changed the instruction words");
      const std::array<std::pair<uint32_t, uint32_t>, 19> descriptor{{
        {VX_DCR_KMU_STARTUP_ADDR0, uint32_t(program_address_)},
        {VX_DCR_KMU_STARTUP_ADDR1, uint32_t(program_address_ >> 32)},
        {VX_DCR_KMU_KERNEL_ENTRY0, uint32_t(program_address_)},
        {VX_DCR_KMU_KERNEL_ENTRY1, uint32_t(program_address_ >> 32)},
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
        wait(write_dcr(field.first, field.second), "public descriptor write failed");
      }
      success(vx_queue_finish(queue, kTimeout), "prepared queue did not finish");
    } catch (...) {
      cleanup();
      throw;
    }
  }

  Context(const Context&) = delete;
  Context& operator=(const Context&) = delete;

  ~Context() {
    cleanup();
  }

  vx_event_h launch(vx_queue_h selected = nullptr) {
    vx_launch_info_t info{};
    info.struct_size = sizeof(info);
    vx_event_h event = nullptr;
    success(vx_enqueue_launch(selected ? selected : queue, &info, 0, nullptr, &event),
            "public scalar launch enqueue failed");
    remember(event);
    return event;
  }

  vx_event_h write_dcr(uint32_t address = VX_DCR_KMU_STARTUP_ARG0, uint32_t value = 0) {
    vx_event_h event = nullptr;
    success(vx_enqueue_dcr_write(queue, address, value, 0, nullptr, &event),
            "public DCR enqueue failed");
    remember(event);
    return event;
  }

  vx_event_h write_program(const std::array<uint32_t, 3>& words = kProgram) {
    vx_event_h event = nullptr;
    success(vx_enqueue_write(queue, program, 0, words.data(), sizeof(words), 0,
                             nullptr, &event), "public DMA enqueue failed");
    remember(event);
    return event;
  }

  uint64_t program_address() const {
    return program_address_;
  }

  void close_resources() {
    for (auto& event : events_) {
      success(vx_event_release(event), "public event release failed");
      event = nullptr;
    }
    events_.clear();
    if (second_queue) {
      success(vx_queue_release(second_queue), "second queue release failed");
      second_queue = nullptr;
    }
    if (queue) {
      success(vx_queue_release(queue), "public queue release failed");
      queue = nullptr;
    }
    if (program) {
      success(vx_buffer_release(program), "public program buffer release failed");
      program = nullptr;
    }
  }

  void close_device() {
    require(queue == nullptr && second_queue == nullptr && program == nullptr
            && events_.empty(), "device release still has owned resources");
    success(vx_device_release(device), "public device release failed");
    device = nullptr;
  }

  static void wait(vx_event_h event, const char* message) {
    success(vx_event_wait_value(event, 1, kTimeout), message);
    success(vx_event_wait_value(event, 1, 0), "repeated successful event wait failed");
  }

  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_queue_h second_queue = nullptr;
  vx_buffer_h program = nullptr;

private:
  void remember(vx_event_h event) {
    require(event != nullptr, "enqueue returned no event");
    try {
      events_.push_back(event);
    } catch (...) {
      vx_event_release(event);
      throw;
    }
  }

  void cleanup() noexcept {
    if (queue) {
      vx_queue_finish(queue, kTimeout);
    }
    if (second_queue) {
      vx_queue_finish(second_queue, kTimeout);
    }
    for (auto event : events_) {
      if (event) {
        vx_event_release(event);
      }
    }
    events_.clear();
    if (second_queue) {
      vx_queue_release(second_queue);
      second_queue = nullptr;
    }
    if (queue) {
      vx_queue_release(queue);
      queue = nullptr;
    }
    if (program) {
      vx_buffer_release(program);
      program = nullptr;
    }
    if (device) {
      vx_device_release(device);
      device = nullptr;
    }
  }

  uint64_t program_address_ = 0;
  std::array<uint32_t, kProgram.size()> readback_{};
  std::vector<vx_event_h> events_;
};

struct CpState {
  uint32_t control;
  uint32_t queue_control;
  uint32_t status;
  uint32_t error;
  uint32_t retired;
  uint64_t expected;
  uint64_t head_writeback_raw;
  uint64_t runtime_tail;
  uint64_t tail_register_pair_raw;
};

uint32_t cp_read(vx::Device& device, uint32_t address) {
  uint32_t value = 0xffffffffu;
  success(device.platform()->cp_reg_read(address, &value), "terminal CP register read failed");
  return value;
}

bool exclusively_owned(vx::Device& device) {
  return device.refs() == 1 && (device.*member(Queues{})).empty()
      && (device.*member(Buffers{})).empty();
}

CpState terminal_cp(vx_device_h handle) {
  auto& device = *vx::to_device(handle);
  require(exclusively_owned(device), "terminal device is not exclusively owned");
  require(device.cp_enabled(), "terminal CP was disabled before its drain observation");
  CpState result{cp_read(device, kCpControl), cp_read(device, kQueueControl),
                 cp_read(device, kCpStatus), cp_read(device, kQueueError),
                 cp_read(device, kQueueSequence), device.*member(CpExpected{}),
                 0, device.*member(CpTail{}), 0};
  // The low register exposes the staged low word; the high register exposes
  // committed high bits. Retain this raw pair, not an independent observation
  // of the internal committed tail. Completed serialized submissions and exact
  // retirement accounting below establish their correspondence.
  const uint64_t tail_low = cp_read(device, kQueueTailLow);
  const uint64_t tail_high = cp_read(device, kQueueTailHigh);
  result.tail_register_pair_raw = tail_low | (tail_high << 32);
  const auto& head = device.*member(CpHead{});
  require(head.host_ptr != nullptr && head.size >= sizeof(result.head_writeback_raw),
          "terminal CP head storage is absent");
  success(device.platform()->host_mem_pull(head.cp_addr), "terminal CP head pull failed");
  std::memcpy(&result.head_writeback_raw, head.host_ptr, sizeof(result.head_writeback_raw));
  // This backend programs a head-writeback address but never publishes the
  // internal head there. Retain its actual initialized bytes as unsupported
  // writeback evidence; they cannot be compared with the submitted tail.
  require(result.head_writeback_raw == 0,
          "terminal CP head storage changed without a published-head contract");
  require(result.control == 1 && result.queue_control == 1,
          "terminal CP was not enabled during drain observation");
  require(result.status == 0 && result.error == 0, "terminal CP is busy or failed");
  require(result.expected > 0 && result.expected <= std::numeric_limits<uint32_t>::max()
          && result.retired == result.expected, "terminal CP did not retire all submissions");
  require(result.tail_register_pair_raw == result.runtime_tail && result.runtime_tail > 0,
          "terminal CP tail register differs from submitted runtime tail");
  require(result.runtime_tail == result.expected * 64,
          "terminal CP submissions are not one cacheline per retired command");
  // With exclusive ownership, the enabled CP's zero busy status excludes
  // head < tail, a loaded cacheline, and active command/launch engines. The
  // single-cacheline commands and exact retirement/tail accounting establish
  // drain by that source invariant, without observing an internal head value.
  return result;
}

vx_result_t failed_event(vx_event_h event) {
  const auto status = vx_event_wait_value(event, 1, kTimeout);
  require(status == VX_ERR_INVALID_VALUE,
          "native failure did not reach the public event");
  require(vx_event_wait_value(event, 1, 0) == VX_ERR_INVALID_VALUE,
          "repeated event wait lost native failure");
  require(vx_event_wait_value(event, 2, 0) == VX_ERR_INVALID_VALUE,
          "higher timeline wait lost native failure");
  const uint64_t target = 1;
  require(vx_event_wait_values(1, &event, &target, 0) == VX_ERR_INVALID_VALUE,
          "multi-event wait lost native failure");
  uint64_t value = 0;
  success(vx_event_get_value(event, &value), "failed event timeline query failed");
  require(value == 1, "failed event did not complete its timeline");
  return status;
}

void consume_queue_error(vx_queue_h queue) {
  require(vx_queue_finish(queue, kTimeout) == VX_ERR_INVALID_VALUE,
          "queue did not retain native failure");
  success(vx_queue_finish(queue, kTimeout), "queue-local error did not clear after consumption");
}

struct QueryResult {
  uint32_t perf_class = 0;
  uint32_t csr = 0;
  vx_result_t status = VX_SUCCESS;
  uint64_t before = kSentinel;
  uint64_t after = kSentinel;
};

QueryResult failed_query(vx_device_h device, uint32_t perf_class = VX_DCR_MPM_CLASS_BASE,
                         uint32_t csr = VX_CSR_MCYCLE) {
  uint64_t value = kSentinel;
  const auto status = vx_device_mpm_query(device, perf_class, csr, 0, &value);
  require(status == VX_ERR_INVALID_VALUE,
          "native query failure did not reach the public API");
  require(value == kSentinel, "failed public query changed its destination");
  return {perf_class, csr, status, kSentinel, value};
}

void same_model(const hooks::ModelState& first, const hooks::ModelState& second) {
  require(first.live && second.live && first.inventory_ready && second.inventory_ready,
          "model observation lacks live backing storage");
  require(first.generation == second.generation && first.ticks == second.ticks
          && first.reset_generation == second.reset_generation,
          "model advanced between terminal observations");
  require(first.idle == second.idle && first.any_running == second.any_running
          && first.pending_reads == second.pending_reads && first.exitcode == second.exitcode,
          "model lifecycle changed between terminal observations");
  require(first.components == second.components,
          "backing counter changed between terminal observations");
}

void healthy_model(const hooks::ModelState& state) {
  require(state.live && state.inventory_ready && state.idle && !state.any_running,
          "completed native model is not idle");
  require(state.pending_reads == 0, "completed native model has pending memory reads");
  require(state.exitcode == 7, "native scalar program did not produce its gp witness");
  require(state.core_cycles > 0 && state.core_instructions > 0,
          "native scalar program did not advance cumulative counters");
}

std::array<hooks::SelectorInfo, hooks::kSelectorCount> inventory(vx_device_h device) {
  const auto selected = hooks::selector_info();
  uint64_t flags = 0;
  success(vx_device_query(device, VX_CAPS_ISA_FLAGS, &flags), "ISA capability query failed");
  size_t available = 0;
  size_t unavailable = 0;
  size_t components = 0;
  for (const auto& counter : p06::kCounters) {
    const bool absent = counter.mpm_class == VX_DCR_MPM_CLASS_L2CACHE
        || counter.mpm_class == VX_DCR_MPM_CLASS_L3CACHE;
    if (absent) {
      require(counter.required_isa != 0 && (flags & counter.required_isa) == 0,
              "unavailable cache selector became enabled");
      ++unavailable;
      continue;
    }
    require(counter.required_isa == 0 || (flags & counter.required_isa) != 0,
            "required counter capability is absent");
    require(available < selected.size(), "native selector inventory has too few entries");
    const auto& actual = selected[available++];
    require(std::strcmp(actual.name, counter.name) == 0 && actual.perf_class == counter.mpm_class
            && actual.csr == counter.csr && counter.core_id == 0,
            "native selector differs from the frozen public inventory");
    const size_t expected_components = std::strncmp(actual.name, "dcache_", 7) == 0
        || std::strcmp(actual.name, "tcu_lmem_reads") == 0 ? 2 : 1;
    require(actual.component_count == expected_components, "native backing component count differs");
    components += actual.component_count;
  }
  require(available == 33 && unavailable == 12 && components == 40,
          "native public counter inventory is incomplete");
  return selected;
}

struct CounterRow {
  hooks::SelectorInfo selector;
  uint64_t value;
  hooks::DcrRead low;
  hooks::DcrRead high;
};

struct TerminalSnapshot {
  bool seeded;
  hooks::ModelState witness;
  hooks::ModelState before;
  hooks::ModelState after;
  CpState cp_before;
  CpState cp_after;
  std::vector<CounterRow> rows;
};

void check_half(const hooks::DcrRead& read, const hooks::SelectorInfo& selector,
                bool high, uint64_t expected, const hooks::ModelState& state) {
  const uint32_t tag = (selector.perf_class << 22)
      | ((selector.csr - VX_CSR_MPM_BASE + (high ? 32u : 0u)) << 16);
  require(read.generation == state.generation && read.addr == VX_DCR_BASE_MPM_VALUE
          && read.tag == tag, "public half-read reached the wrong model selector");
  require(read.completed && read.status == 0 && !read.overflow,
          "public half-read did not complete successfully");
  require(read.value == uint32_t(high ? expected >> 32 : expected),
          "public half-read reply differs from real backing components");
  require(read.ticks_before == state.ticks && read.ticks_after == state.ticks
          && read.reset_before == state.reset_generation
          && read.reset_after == state.reset_generation,
          "model advanced within a public half-read");
  require(read.class_before == read.class_after, "public half-read did not restore counter class");
}

TerminalSnapshot terminal_snapshot(Context& context, bool seeded,
                                   const hooks::ModelState& witness) {
  context.close_resources();
  auto& device = *vx::to_device(context.device);
  require(exclusively_owned(device), "closed resources retained the device");
  success(vx_device_retain(context.device), "diagnostic device retain failed");
  const bool rejected = !exclusively_owned(device);
  success(vx_device_release(context.device), "diagnostic device reference release failed");
  require(rejected && exclusively_owned(device), "extra retained device passed terminal ownership");
  const auto selected = inventory(context.device);
  TerminalSnapshot result{};
  result.seeded = seeded;
  result.witness = witness;
  result.cp_before = terminal_cp(context.device);
  result.before = hooks::model_state();
  healthy_model(result.before);
  hooks::clear_read_trace();
  size_t component_index = 0;
  for (const auto& selector : selected) {
    uint64_t expected = 0;
    for (size_t component = 0; component < selector.component_count; ++component) {
      const uint64_t value = result.before.components[component_index++];
      require(value <= kMax - expected, "terminal backing aggregate exceeds uint64");
      expected += value;
    }
    uint64_t value = ~expected;
    success(vx_device_mpm_query(context.device, selector.perf_class, selector.csr, 0, &value),
            "terminal public counter query failed");
    require(value == expected, "terminal public counter differs from its backing sources");
    result.rows.push_back({selector, value, {}, {}});
  }
  require(component_index == hooks::kComponentCount, "terminal component inventory ended early");
  const auto trace = hooks::read_trace();
  require(trace.size() == 66, "terminal read trace contains missing or extra model queries");
  for (size_t index = 0; index < result.rows.size(); ++index) {
    auto& row = result.rows[index];
    row.low = trace[2 * index];
    row.high = trace[2 * index + 1];
    check_half(row.low, row.selector, false, row.value, result.before);
    check_half(row.high, row.selector, true, row.value, result.before);
    require(row.high.sequence == row.low.sequence + 1,
            "counter half reads were not consecutive model calls");
    require(row.low.class_before == row.high.class_before,
            "counter class changed between public half reads");
  }
  result.cp_after = terminal_cp(context.device);
  result.after = hooks::model_state();
  same_model(result.before, result.after);
  require(result.cp_after.expected == result.cp_before.expected + 66,
          "terminal queries submitted an unexpected number of CP commands");
  require(exclusively_owned(device), "terminal queries retained device resources");
  return result;
}

void check_disposal(const hooks::Observation& before, const hooks::ModelState* terminal) {
  const auto after = hooks::observation();
  require(!after.live && after.destroyed == before.destroyed + 1
          && after.destructor_entries == after.destroyed,
          "public device release did not complete actual Processor destruction");
  const auto destroyed = hooks::destruction_trace();
  require(destroyed.size() == after.destroyed && destroyed.back().completed
          && destroyed.back().ticks_after == 0 && destroyed.back().idle_after,
          "actual Processor destruction did not clean the platform");
  if (terminal != nullptr) {
    same_model(*terminal, destroyed.back().before);
  }
}

TerminalSnapshot successful_context(bool seeded) {
  const auto initial = hooks::observation();
  require(!initial.live, "fresh public context overlaps another native model");
  Context context;
  Context::wait(context.launch(), "native scalar launch failed");
  success(vx_queue_finish(context.queue, kTimeout), "successful native queue did not finish");
  const auto witness = hooks::model_state();
  healthy_model(witness);
  const auto completed = hooks::observation();
  require(completed.constructed == initial.constructed + 1
          && completed.run_entries == initial.run_entries + 1
          && completed.run_completed == initial.run_completed + 1
          && completed.overflow_errors == initial.overflow_errors,
          "successful context omitted real native construction or execution");
  if (seeded) {
    const auto selected = inventory(context.device);
    hooks::clear_components();
    for (size_t index = 0; index < selected.size(); ++index) {
      for (size_t component = 0; component < selected[index].component_count; ++component) {
        hooks::seed_component(index, component, 0x1234567800000000ull + 2 * index + component);
      }
    }
  }
  auto result = terminal_snapshot(context, seeded, witness);
  context.close_device();
  check_disposal(initial, &result.after);
  return result;
}

struct Suppression {
  hooks::Observation before;
  hooks::Observation after;
  std::array<QueryResult, 2> queries;
  uint64_t dma_address = 0;
  vx_result_t dma_status = VX_SUCCESS;
  std::array<uint32_t, 3> dma_before{};
  std::array<uint32_t, 3> dma_attempted{};
  std::array<uint32_t, 3> dma_after{};
};

Suppression suppressed_work(Context& context) {
  Suppression result{};
  result.before = hooks::observation();
  const auto counters = hooks::model_state();
  result.queries[0] = failed_query(context.device);
  result.queries[1] = failed_query(context.device);
  failed_event(context.write_dcr());
  consume_queue_error(context.queue);
  result.dma_address = context.program_address();
  result.dma_before = hooks::read_program_words(result.dma_address);
  result.dma_attempted = kRejectedProgram;
  require(result.dma_before == kProgram, "failed context program RAM differs before DMA retry");
  require(result.dma_attempted != result.dma_before, "DMA retry does not change its payload");
  result.dma_status = failed_event(context.write_program(kRejectedProgram));
  consume_queue_error(context.queue);
  result.dma_after = hooks::read_program_words(result.dma_address);
  require(result.dma_after == result.dma_before, "failed DMA changed actual program RAM");
  success(vx_queue_create(context.device, nullptr, &context.second_queue),
          "second queue creation failed");
  failed_event(context.launch(context.second_queue));
  consume_queue_error(context.second_queue);
  result.after = hooks::observation();
  require(result.after.run_entries == result.before.run_entries
          && result.after.dcr_read_entries == result.before.dcr_read_entries
          && result.after.dcr_write_entries == result.before.dcr_write_entries
          && result.after.overflow_errors == result.before.overflow_errors,
          "failed public context reentered the native model");
  same_model(counters, hooks::model_state());
  return result;
}

struct FailureRecord {
  bool present = false;
  bool asynchronous = false;
  uint64_t seed = 0;
  hooks::ModelState before;
  hooks::ModelState after;
  QueryResult trigger_query;
  Suppression suppression;
  std::vector<hooks::DcrRead> reads;
};

FailureRecord failed_context(bool asynchronous, bool delayed) {
  const auto initial = hooks::observation();
  require(!initial.live, "fault context overlaps another native model");
  Context context;
  const auto selected = inventory(context.device);
  FailureRecord result{};
  result.present = true;
  result.asynchronous = asynchronous;
  if (!asynchronous) {
    Context::wait(context.launch(), "aggregate-fault context scalar launch failed");
    success(vx_queue_finish(context.queue, kTimeout), "aggregate-fault queue did not finish");
    healthy_model(hooks::model_state());
  }
  hooks::clear_read_trace();
  if (asynchronous) {
    require(std::strcmp(selected[0].name, "cycles") == 0
            && selected[0].component_count == 1, "cycle fault selected the wrong source");
    result.seed = delayed ? kMax - 2 : kMax;
    hooks::seed_component(0, 0, result.seed);
    result.before = hooks::model_state();
    const auto observation = hooks::observation();
    const auto event = context.launch();
    failed_event(event);
    consume_queue_error(context.queue);
    failed_event(event);
    result.after = hooks::model_state();
    const auto observed = hooks::observation();
    require(observed.run_entries == observation.run_entries + 1
            && observed.run_errors == observation.run_errors + 1
            && observed.run_completed == observation.run_completed,
            "native updater fault did not escape through the real checked entry");
    require(observed.overflow_errors == observation.overflow_errors + 1,
            "native updater did not throw the typed overflow");
    require(result.after.core_cycles == kMax,
            "overflow changed the saturated native cycle destination");
    require(result.after.core_instructions == 0, "faulting scalar launch retired instructions");
    if (delayed) {
      require(result.after.core_cycles > result.before.core_cycles
              && result.after.ticks > 0, "delayed native fault made no actual progress");
    } else {
      require(result.after.core_cycles == result.before.core_cycles,
              "immediate native overflow changed its destination");
    }
  } else {
    constexpr size_t cache_reads = 16;
    require(std::strcmp(selected[cache_reads].name, "dcache_reads") == 0
            && selected[cache_reads].component_count == 2,
            "aggregate fault selected the wrong backing sources");
    hooks::seed_component(cache_reads, 0, kMax);
    hooks::seed_component(cache_reads, 1, 1);
    result.seed = kMax;
    result.before = hooks::model_state();
    const auto observation = hooks::observation();
    result.trigger_query = failed_query(context.device, selected[cache_reads].perf_class,
                                        selected[cache_reads].csr);
    result.after = hooks::model_state();
    const auto observed = hooks::observation();
    require(observed.dcr_read_entries == observation.dcr_read_entries + 1
            && observed.dcr_read_errors == observation.dcr_read_errors + 1
            && observed.overflow_errors == observation.overflow_errors + 1,
            "aggregate fault did not traverse the real public DCR query");
    same_model(result.before, result.after);
    result.reads = hooks::read_trace();
    require(result.reads.size() == 1 && result.reads[0].overflow
            && !result.reads[0].completed && result.reads[0].addr == VX_DCR_BASE_MPM_VALUE,
            "aggregate fault trace omitted its failing native half read");
    const uint32_t expected_tag = (selected[cache_reads].perf_class << 22)
        | ((selected[cache_reads].csr - VX_CSR_MPM_BASE) << 16);
    require(result.reads[0].tag == expected_tag,
            "aggregate fault used the wrong public counter tag");
  }
  result.suppression = suppressed_work(context);
  context.close_resources();
  require(exclusively_owned(*vx::to_device(context.device)),
          "failed context retained public resources before disposal");
  context.close_device();
  check_disposal(initial, &result.after);
  return result;
}

const char* boolean(bool value) {
  return value ? "true" : "false";
}

void print_model(const hooks::ModelState& state) {
  std::printf("{\"live\":%s,\"inventory_ready\":%s,\"idle\":%s,\"any_running\":%s,"
              "\"generation\":%" PRIu64 ",\"ticks\":%" PRIu64 ",\"reset_generation\":%" PRIu64
              ",\"pending_reads\":%" PRIu64 ",\"core_cycles\":%" PRIu64
              ",\"core_instructions\":%" PRIu64 ",\"exitcode\":%d,\"components\":[",
              boolean(state.live), boolean(state.inventory_ready), boolean(state.idle),
              boolean(state.any_running), state.generation, state.ticks, state.reset_generation,
              state.pending_reads, state.core_cycles, state.core_instructions, state.exitcode);
  for (size_t index = 0; index < state.components.size(); ++index) {
    std::printf("%s%" PRIu64, index ? "," : "", state.components[index]);
  }
  std::fputs("]}", stdout);
}

void print_read(const hooks::DcrRead& read) {
  std::printf("{\"sequence\":%" PRIu64 ",\"generation\":%" PRIu64
              ",\"addr\":%u,\"tag\":%u,\"value\":%u,\"status\":%d,"
              "\"completed\":%s,\"overflow\":%s,\"ticks_before\":%" PRIu64
              ",\"ticks_after\":%" PRIu64 ",\"reset_before\":%" PRIu64
              ",\"reset_after\":%" PRIu64 ",\"class_before\":%u,\"class_after\":%u}",
              read.sequence, read.generation, read.addr, read.tag, read.value, read.status,
              boolean(read.completed), boolean(read.overflow), read.ticks_before, read.ticks_after,
              read.reset_before, read.reset_after, read.class_before, read.class_after);
}

void print_cp(const CpState& state) {
  std::printf("{\"control\":%u,\"queue_control\":%u,\"status\":%u,\"error\":%u,"
              "\"retired\":%u,\"expected\":%" PRIu64 ",\"head_writeback_raw\":%" PRIu64
              ",\"head_writeback_status\":\"not-published\",\"runtime_tail\":%" PRIu64
              ",\"tail_register_pair_raw\":%" PRIu64
              ",\"drain_basis\":\"enabled-idle-status-and-retired-sequence\"}",
              state.control, state.queue_control, state.status, state.error, state.retired,
              state.expected, state.head_writeback_raw, state.runtime_tail, state.tail_register_pair_raw);
}

void print_terminal(const TerminalSnapshot& snapshot) {
  std::printf("{\"seeded\":%s,\"selectors\":33,\"components\":40,"
              "\"unavailable_unqueried\":12,\"device_refs\":1,\"queues\":0,\"buffers\":0,"
              "\"extra_retain_rejected\":true,\"witness\":", boolean(snapshot.seeded));
  print_model(snapshot.witness);
  std::fputs(",\"before\":", stdout);
  print_model(snapshot.before);
  std::fputs(",\"after\":", stdout);
  print_model(snapshot.after);
  std::fputs(",\"cp_before\":", stdout);
  print_cp(snapshot.cp_before);
  std::fputs(",\"cp_after\":", stdout);
  print_cp(snapshot.cp_after);
  std::fputs(",\"rows\":[", stdout);
  for (size_t index = 0; index < snapshot.rows.size(); ++index) {
    const auto& row = snapshot.rows[index];
    std::printf("%s{\"name\":\"%s\",\"class\":%u,\"csr\":%u,\"components\":%zu,"
                "\"value\":%" PRIu64 ",\"low\":", index ? "," : "", row.selector.name,
                row.selector.perf_class, row.selector.csr, row.selector.component_count, row.value);
    print_read(row.low);
    std::fputs(",\"high\":", stdout);
    print_read(row.high);
    std::fputs("}", stdout);
  }
  std::fputs("]}", stdout);
}

void print_query(const QueryResult& query) {
  std::printf("{\"class\":%u,\"csr\":%u,\"status\":%d,\"before\":%" PRIu64
              ",\"after\":%" PRIu64 "}", query.perf_class, query.csr,
              int(query.status), query.before, query.after);
}

void print_entries(const hooks::Observation& observation) {
  std::printf("{\"run\":%" PRIu64 ",\"read\":%" PRIu64 ",\"write\":%" PRIu64
              ",\"overflows\":%" PRIu64 "}", observation.run_entries,
              observation.dcr_read_entries, observation.dcr_write_entries,
              observation.overflow_errors);
}

void print_words(const std::array<uint32_t, 3>& words) {
  std::printf("[%u,%u,%u]", words[0], words[1], words[2]);
}

void print_result(const char* mode, const FailureRecord& failure,
                   const std::vector<TerminalSnapshot>& terminals) {
  const auto observed = hooks::observation();
  const auto destroyed = hooks::destruction_trace();
  require(observed.constructed == 2 && observed.destroyed == 2 && !observed.live
          && observed.constructor_entries == 2 && observed.destructor_entries == 2,
          "diagnostic did not create and fully dispose exactly two native contexts");
  require(observed.run_entries == 2 && observed.run_completed == (failure.asynchronous ? 1u : 2u)
          && observed.run_errors == (failure.asynchronous ? 1u : 0u)
          && observed.dcr_read_errors == (failure.present && !failure.asynchronous ? 1u : 0u)
          && observed.overflow_errors == (failure.present ? 1u : 0u),
          "diagnostic native execution and error counts differ");
  require(observed.underflow_errors == 0 && observed.negative_operand_errors == 0
          && observed.unexpected_errors == 0 && observed.violations == 0
          && observed.dcr_write_errors == 0,
          "diagnostic observed an unexpected exception or ownership violation");
  require(observed.dcr_read_entries == observed.dcr_read_completed + observed.dcr_read_errors
          && observed.dcr_write_entries == observed.dcr_write_completed,
          "diagnostic contains an unaccounted model entry");
  std::printf("COUNTER_PUBLIC_RESULT {\"schema_version\":2,\"mode\":\"%s\","
              "\"backend\":\"simx\",\"memory_route\":\"direct-ram\",\"xlen\":64,"
              "\"checked\":true,\"native_model\":true,\"public_runtime\":true,"
              "\"checks\":%zu,\"failures\":0,\"constructed\":%" PRIu64
              ",\"destroyed\":%" PRIu64 ",\"run_entries\":%" PRIu64
              ",\"run_completed\":%" PRIu64 ",\"run_errors\":%" PRIu64
              ",\"dcr_read_entries\":%" PRIu64 ",\"dcr_read_completed\":%" PRIu64
              ",\"dcr_read_errors\":%" PRIu64 ",\"dcr_write_entries\":%" PRIu64
              ",\"dcr_write_completed\":%" PRIu64 ",\"overflow_errors\":%" PRIu64
              ",\"unexpected_errors\":0,\"violations\":0,\"fresh_context_success\":true,"
              "\"program_words_verified\":6,\"terminal_failure\":%s,"
              "\"suppressed_requests\":%u,\"failure\":",
              mode, checks, observed.constructed, observed.destroyed, observed.run_entries,
              observed.run_completed, observed.run_errors, observed.dcr_read_entries,
              observed.dcr_read_completed, observed.dcr_read_errors, observed.dcr_write_entries,
              observed.dcr_write_completed, observed.overflow_errors, boolean(failure.present),
              failure.present ? 5u : 0u);
  if (failure.present) {
    std::printf("{\"asynchronous\":%s,\"seed\":%" PRIu64 ",\"before\":",
                boolean(failure.asynchronous), failure.seed);
    print_model(failure.before);
    std::fputs(",\"after\":", stdout);
    print_model(failure.after);
    std::fputs(",\"trigger_query\":", stdout);
    if (failure.asynchronous) {
      std::fputs("null", stdout);
    } else {
      print_query(failure.trigger_query);
    }
    std::fputs(",\"suppression\":{\"before_entries\":", stdout);
    print_entries(failure.suppression.before);
    std::fputs(",\"after_entries\":", stdout);
    print_entries(failure.suppression.after);
    std::fputs(",\"queries\":[", stdout);
    for (size_t index = 0; index < failure.suppression.queries.size(); ++index) {
      if (index) {
        std::fputs(",", stdout);
      }
      print_query(failure.suppression.queries[index]);
    }
    std::printf("],\"dma\":{\"address\":%" PRIu64 ",\"status\":%d,\"before\":",
                failure.suppression.dma_address, int(failure.suppression.dma_status));
    print_words(failure.suppression.dma_before);
    std::fputs(",\"attempted\":", stdout);
    print_words(failure.suppression.dma_attempted);
    std::fputs(",\"after\":", stdout);
    print_words(failure.suppression.dma_after);
    std::fputs("}}", stdout);
    std::fputs(",\"reads\":[", stdout);
    for (size_t index = 0; index < failure.reads.size(); ++index) {
      if (index) {
        std::fputs(",", stdout);
      }
      print_read(failure.reads[index]);
    }
    std::fputs("]}", stdout);
  } else {
    std::fputs("null", stdout);
  }
  std::fputs(",\"terminal_snapshots\":[", stdout);
  for (size_t index = 0; index < terminals.size(); ++index) {
    if (index) {
      std::fputs(",", stdout);
    }
    print_terminal(terminals[index]);
  }
  std::fputs("],\"destructions\":[", stdout);
  for (size_t index = 0; index < destroyed.size(); ++index) {
    const auto& record = destroyed[index];
    std::printf("%s{\"before\":", index ? "," : "");
    print_model(record.before);
    std::printf(",\"completed\":%s,\"ticks_after\":%" PRIu64
                ",\"reset_after\":%" PRIu64 ",\"idle_after\":%s}",
                boolean(record.completed), record.ticks_after, record.reset_after,
                boolean(record.idle_after));
  }
  std::puts("],\"qualified\":false,\"ready_for_warm\":false,"
            "\"warm_execution\":false,\"acceptance_claimed\":false}");
}

} // namespace

int main(int argc, char** argv) {
  try {
    require(argc == 2, "expected one native public counter mode");
    const char* driver = std::getenv("VORTEX_DRIVER");
    require(driver != nullptr && std::strcmp(driver, "simx") == 0,
            "native public counter diagnostics require VORTEX_DRIVER=simx");
    const std::string mode(argv[1]);
    FailureRecord failure;
    std::vector<TerminalSnapshot> terminals;
    if (mode == "normal" || mode == "coherent-terminal") {
      terminals.push_back(successful_context(mode == "coherent-terminal"));
    } else if (mode == "immediate-overflow" || mode == "delayed-overflow") {
      failure = failed_context(true, mode == "delayed-overflow");
    } else if (mode == "cache-overflow") {
      failure = failed_context(false, false);
    } else {
      throw std::runtime_error("unknown native public counter mode");
    }
    terminals.push_back(successful_context(false));
    print_result(mode.c_str(), failure, terminals);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAIL native public counter diagnostic: %s\n", error.what());
    return 1;
  } catch (...) {
    std::fputs("FAIL native public counter diagnostic: unexpected exception\n", stderr);
    return 1;
  }
}
