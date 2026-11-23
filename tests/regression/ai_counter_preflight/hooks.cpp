// SPDX-License-Identifier: Apache-2.0
#include "hooks.h"

#include "core.h"
#include "processor.h"

#include <array>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <type_traits>

#if !defined(SIMX_CHECKED_COUNTERS) || (SIMX_CHECKED_COUNTERS + 0) != 1
#error "Managed counter preflight requires checked model counters"
#endif
#ifdef SIMX_FUNCTIONAL
#error "Managed counter preflight requires the timing simulator"
#endif
static_assert(vortex::SIMX_NUM_WORKERS == 1);
static_assert(VX_CFG_XLEN == 64);
static_assert(std::is_trivially_copyable_v<p06_preflight::Observation>);
static_assert(std::is_trivially_copyable_v<p06_preflight::DcrRead>);
static_assert(std::is_trivially_copyable_v<p06_preflight::RunObservation>);

namespace p06_preflight {
namespace {

struct State {
  std::mutex mutex;
  vortex::Processor* processor = nullptr;
  Observation observed;
  std::array<DcrRead, kMaxReads> reads;
  std::array<DcrRead, kMaxReads> cache_flush_reads;
  std::array<RunObservation, kMaxRuns> runs;
};

State& state() {
  static State value;
  return value;
}

const vortex::Core& core_locked(State& current) {
  if (current.processor == nullptr || current.processor->get_first_core() == nullptr) {
    ++current.observed.violations;
    throw std::logic_error("managed preflight has no live native processor");
  }
  return *current.processor->get_first_core();
}

void check_owner_locked(State& current, vortex::Processor* processor) {
  if (current.processor != processor || !current.observed.live) {
    ++current.observed.violations;
    throw std::logic_error("managed preflight processor ownership differs");
  }
}

ModelState model_locked(State& current) {
  ModelState result;
  result.live = current.processor != nullptr;
  result.generation = current.observed.generation;
  const auto& platform = vortex::SimPlatform::instance();
  result.ticks = platform.cycles();
  result.reset_generation = platform.reset_gen();
  result.idle = platform.idle();
  if (result.live) {
    const auto& core = core_locked(current);
    result.any_running = current.processor->any_running();
    result.core_cycles = core.perf_stats().cycles;
    result.core_instructions = core.perf_stats().instrs;
    result.exitcode = core.get_exitcode();
    if (current.observed.lifetime_enabled) {
      result.pending_reads = current.processor->pending_mem_reads();
    }
  }
  return result;
}

void require_drained_locked(State& current, const ModelState& model) {
  if (!model.live || !model.idle || model.any_running || model.pending_reads != 0) {
    ++current.observed.violations;
    throw std::logic_error("managed lifetime requires an idle processor with no pending reads");
  }
}

void finish_run_locked(State& current, RunObservation& run) {
  run.dcr_reads_after = current.observed.dcr_read_entries;
  run.cache_flushes_after = current.observed.cache_flush_count;
  run.after = model_locked(current);
}

void observe_failed_run_locked(State& current, RunObservation* run) noexcept {
  if (run == nullptr) {
    return;
  }
  run->exception = true;
  try {
    finish_run_locked(current, *run);
  } catch (...) {
    ++current.observed.unexpected_errors;
  }
}

void counter_error_locked(State& current, const vortex::PerfCounterError& error) {
  switch (error.reason()) {
  case vortex::PerfCounterError::Reason::Overflow:
    ++current.observed.overflow_errors;
    break;
  case vortex::PerfCounterError::Reason::Underflow:
    ++current.observed.underflow_errors;
    break;
  case vortex::PerfCounterError::Reason::NegativeOperand:
    ++current.observed.negative_operand_errors;
    break;
  }
}

void finish_read_locked(State& current, DcrRead& read) {
  const auto& platform = vortex::SimPlatform::instance();
  read.ticks_after = platform.cycles();
  read.reset_after = platform.reset_gen();
  read.class_after = core_locked(current).mpm_class();
  read.idle_after = platform.idle();
  read.any_running_after = current.processor->any_running();
  if (current.observed.lifetime_enabled) {
    read.pending_after = current.processor->pending_mem_reads();
  }
}

void observe_failed_read_locked(State& current, DcrRead& read) noexcept {
  try {
    finish_read_locked(current, read);
  } catch (...) {
    ++current.observed.unexpected_errors;
  }
}

void require_read_drained_locked(State& current, uint64_t pending, bool idle, bool running) {
  if (pending != 0 || !idle || running) {
    ++current.observed.violations;
    throw std::logic_error("managed lifetime read boundary is not drained");
  }
}

} // namespace
} // namespace p06_preflight

extern "C" int p06_preflight_enable_lifetime() noexcept {
  try {
    auto& current = p06_preflight::state();
    std::lock_guard<std::mutex> lock(current.mutex);
    if (current.observed.lifetime_enabled || current.processor != nullptr
        || current.observed.constructor_entries != 0 || current.observed.run_entries != 0) {
      ++current.observed.violations;
      return -1;
    }
    current.observed.lifetime_enabled = true;
    return 0;
  } catch (...) {
    return -1;
  }
}

extern "C" int p06_preflight_get_observation(p06_preflight::Observation* out) noexcept {
  if (out == nullptr) {
    return -1;
  }
  try {
    auto& current = p06_preflight::state();
    std::lock_guard<std::mutex> lock(current.mutex);
    *out = current.observed;
    return 0;
  } catch (...) {
    return -1;
  }
}

extern "C" int p06_preflight_get_model_state(p06_preflight::ModelState* out) noexcept {
  if (out == nullptr) {
    return -1;
  }
  try {
    auto& current = p06_preflight::state();
    std::lock_guard<std::mutex> lock(current.mutex);
    *out = p06_preflight::model_locked(current);
    if (current.observed.lifetime_enabled) {
      p06_preflight::require_drained_locked(current, *out);
    }
    return 0;
  } catch (...) {
    return -1;
  }
}

extern "C" int p06_preflight_get_run(size_t index, p06_preflight::RunObservation* out) noexcept {
  if (out == nullptr) {
    return -1;
  }
  try {
    auto& current = p06_preflight::state();
    std::lock_guard<std::mutex> lock(current.mutex);
    if (!current.observed.lifetime_enabled || index >= current.observed.run_count
        || index >= p06_preflight::kMaxRuns) {
      return -1;
    }
    *out = current.runs[index];
    return 0;
  } catch (...) {
    return -1;
  }
}

extern "C" int p06_preflight_get_read(size_t index, p06_preflight::DcrRead* out) noexcept {
  if (out == nullptr) {
    return -1;
  }
  try {
    auto& current = p06_preflight::state();
    std::lock_guard<std::mutex> lock(current.mutex);
    if (index >= current.observed.read_count) {
      return -1;
    }
    *out = current.reads[index];
    return 0;
  } catch (...) {
    return -1;
  }
}

extern "C" int p06_preflight_get_cache_flush_read(size_t index, p06_preflight::DcrRead* out) noexcept {
  if (out == nullptr) {
    return -1;
  }
  try {
    auto& current = p06_preflight::state();
    std::lock_guard<std::mutex> lock(current.mutex);
    if (index >= current.observed.cache_flush_count) {
      return -1;
    }
    *out = current.cache_flush_reads[index];
    return 0;
  } catch (...) {
    return -1;
  }
}

extern "C" {
void __real__ZN6vortex9ProcessorC1Ev(vortex::Processor*);
void __real__ZN6vortex9ProcessorD1Ev(vortex::Processor*) noexcept;
void __real__ZN6vortex9Processor11run_checkedEv(vortex::Processor*);
int __real__ZN6vortex9Processor8dcr_readEjjPj(vortex::Processor*, uint32_t, uint32_t, uint32_t*);
int __real__ZN6vortex9Processor9dcr_writeEjj(vortex::Processor*, uint32_t, uint32_t);
}

extern "C" void __wrap__ZN6vortex9ProcessorC1Ev(vortex::Processor* processor) {
  using namespace p06_preflight;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  ++current.observed.constructor_entries;
  if (current.processor != nullptr || current.observed.constructed != 0) {
    ++current.observed.violations;
    throw std::logic_error("managed preflight requires one native processor lifetime");
  }
  try {
    __real__ZN6vortex9ProcessorC1Ev(processor);
  } catch (...) {
    ++current.observed.unexpected_errors;
    throw;
  }
  current.processor = processor;
  ++current.observed.constructed;
  ++current.observed.generation;
  current.observed.live = true;
  try {
    current.observed.constructed_state = model_locked(current);
    if (current.observed.lifetime_enabled) {
      require_drained_locked(current, current.observed.constructed_state);
    }
  } catch (...) {
    ++current.observed.unexpected_errors;
  }
}

extern "C" void __wrap__ZN6vortex9ProcessorD1Ev(vortex::Processor* processor) noexcept {
  using namespace p06_preflight;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  ++current.observed.destructor_entries;
  const bool owned = current.processor == processor && current.observed.destroyed == 0;
  if (owned) {
    try {
      current.observed.destruction.before = model_locked(current);
      if (current.observed.lifetime_enabled) {
        require_drained_locked(current, current.observed.destruction.before);
      }
    } catch (...) {
      ++current.observed.unexpected_errors;
    }
  } else {
    ++current.observed.violations;
  }
  __real__ZN6vortex9ProcessorD1Ev(processor);
  if (owned) {
    const auto& platform = vortex::SimPlatform::instance();
    auto& record = current.observed.destruction;
    record.completed = true;
    record.ticks_after = platform.cycles();
    record.reset_after = platform.reset_gen();
    record.idle_after = platform.idle();
    current.processor = nullptr;
    current.observed.live = false;
  }
  ++current.observed.destroyed;
}

extern "C" void __wrap__ZN6vortex9Processor11run_checkedEv(vortex::Processor* processor) {
  using namespace p06_preflight;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  check_owner_locked(current, processor);
  ++current.observed.run_entries;
  RunObservation* run = nullptr;
  try {
    if (current.observed.lifetime_enabled) {
      if (current.observed.run_count >= kMaxRuns) {
        current.observed.trace_overflow = true;
        ++current.observed.violations;
        throw std::logic_error("managed lifetime run trace capacity exceeded");
      }
      run = &current.runs[current.observed.run_count++];
      run->ordinal = current.observed.run_count;
      run->dcr_reads_before = current.observed.dcr_read_entries;
      run->cache_flushes_before = current.observed.cache_flush_count;
      run->before = model_locked(current);
      require_drained_locked(current, run->before);
      if (run->before.reset_generation == std::numeric_limits<uint64_t>::max()) {
        ++current.observed.violations;
        throw std::logic_error("managed lifetime reset generation is exhausted");
      }
      run->real_call_entered = true;
    }
    __real__ZN6vortex9Processor11run_checkedEv(processor);
    ++current.observed.run_completed;
    if (run != nullptr) {
      run->completed = true;
      finish_run_locked(current, *run);
      require_drained_locked(current, run->after);
      if (run->after.reset_generation != run->before.reset_generation + 1) {
        ++current.observed.violations;
        throw std::logic_error("managed lifetime run requires exactly one reset");
      }
    }
  } catch (const vortex::PerfCounterError& error) {
    ++current.observed.run_errors;
    counter_error_locked(current, error);
    observe_failed_run_locked(current, run);
    throw;
  } catch (...) {
    ++current.observed.run_errors;
    ++current.observed.unexpected_errors;
    observe_failed_run_locked(current, run);
    throw;
  }
}

extern "C" int __wrap__ZN6vortex9Processor8dcr_readEjjPj(
    vortex::Processor* processor, uint32_t addr, uint32_t tag, uint32_t* value) {
  using namespace p06_preflight;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  check_owner_locked(current, processor);
  ++current.observed.dcr_read_entries;
  const bool cache_flush = addr == VX_DCR_BASE_CACHE_FLUSH;
  if (!cache_flush && addr != VX_DCR_BASE_MPM_VALUE) {
    ++current.observed.violations;
    throw std::logic_error("managed preflight received an unexpected DCR read");
  }
  auto& count = cache_flush ? current.observed.cache_flush_count : current.observed.read_count;
  auto& reads = cache_flush ? current.cache_flush_reads : current.reads;
  if (count >= kMaxReads) {
    ++current.observed.violations;
    if (current.observed.lifetime_enabled) {
      current.observed.trace_overflow = true;
    }
    throw std::logic_error("managed preflight read trace capacity exceeded");
  }
  auto& read = reads[count++];
  read.sequence = current.observed.dcr_read_entries;
  read.generation = current.observed.generation;
  read.completed_runs = current.observed.run_completed;
  read.addr = addr;
  read.tag = tag;
  const auto& platform = vortex::SimPlatform::instance();
  read.ticks_before = platform.cycles();
  read.reset_before = platform.reset_gen();
  read.class_before = core_locked(current).mpm_class();
  read.idle_before = platform.idle();
  read.any_running_before = current.processor->any_running();
  try {
    if (current.observed.lifetime_enabled) {
      read.pending_before = current.processor->pending_mem_reads();
      require_read_drained_locked(current, read.pending_before, read.idle_before, read.any_running_before);
    }
    read.status = __real__ZN6vortex9Processor8dcr_readEjjPj(processor, addr, tag, value);
    read.completed = true;
    if (read.status == 0 && value != nullptr) {
      read.value = *value;
    } else {
      ++current.observed.dcr_read_errors;
    }
    ++current.observed.dcr_read_completed;
    finish_read_locked(current, read);
    if (current.observed.lifetime_enabled) {
      require_read_drained_locked(current, read.pending_after, read.idle_after, read.any_running_after);
    }
    return read.status;
  } catch (const vortex::PerfCounterError& error) {
    ++current.observed.dcr_read_errors;
    read.overflow = error.reason() == vortex::PerfCounterError::Reason::Overflow;
    counter_error_locked(current, error);
    observe_failed_read_locked(current, read);
    throw;
  } catch (...) {
    ++current.observed.dcr_read_errors;
    ++current.observed.unexpected_errors;
    observe_failed_read_locked(current, read);
    throw;
  }
}

extern "C" int __wrap__ZN6vortex9Processor9dcr_writeEjj(
    vortex::Processor* processor, uint32_t addr, uint32_t value) {
  using namespace p06_preflight;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  check_owner_locked(current, processor);
  ++current.observed.dcr_write_entries;
  try {
    const int status = __real__ZN6vortex9Processor9dcr_writeEjj(processor, addr, value);
    ++current.observed.dcr_write_completed;
    if (status != 0) {
      ++current.observed.dcr_write_errors;
    }
    return status;
  } catch (const vortex::PerfCounterError& error) {
    ++current.observed.dcr_write_errors;
    counter_error_locked(current, error);
    throw;
  } catch (...) {
    ++current.observed.dcr_write_errors;
    ++current.observed.unexpected_errors;
    throw;
  }
}
