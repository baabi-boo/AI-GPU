// SPDX-License-Identifier: Apache-2.0
#include "public_hooks.h"

#include "counter_access.h"
#include "core.h"
#include "processor.h"
#include "processor_impl.h"
#include "mem.h"

#include <mutex>
#include <limits>
#include <stdexcept>

#if !defined(SIMX_CHECKED_COUNTERS) || (SIMX_CHECKED_COUNTERS + 0) != 1
#error "The public counter diagnostic requires checked model counters"
#endif

namespace counter_test::public_hooks {
namespace {

constexpr size_t kMaxReads = 4096;
constexpr size_t kMaxDestructions = 16;

struct State {
  std::mutex mutex;
  vortex::Processor* processor = nullptr;
  Observation observed;
  bool inventory_ready = false;
  std::array<Selector, kSelectorCount> selectors;
  std::array<DcrRead, kMaxReads> reads;
  size_t read_count = 0;
  std::array<Destruction, kMaxDestructions> destructions;
  size_t destruction_count = 0;
};

State& state() {
  static State value;
  return value;
}

vortex::Core& core_locked(State& current) {
  if (current.processor == nullptr || current.processor->get_first_core() == nullptr) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic has no live native processor");
  }
  return *current.processor->get_first_core();
}

void check_owner_locked(State& current, vortex::Processor* processor) {
  if (current.processor != processor) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic processor ownership differs");
  }
}

void inventory_locked(State& current) {
  if (current.inventory_ready) {
    return;
  }
  current.selectors = counter_test::selectors(core_locked(current));
  size_t count = 0;
  for (const auto& selected : current.selectors) {
    count += selected.components.size();
  }
  if (count != kComponentCount) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic component inventory differs");
  }
  current.inventory_ready = true;
}

ModelState model_locked(State& current) {
  ModelState result;
  result.live = current.processor != nullptr;
  result.generation = current.observed.generation;
  result.inventory_ready = current.inventory_ready;
  auto& platform = vortex::SimPlatform::instance();
  result.ticks = platform.cycles();
  result.reset_generation = platform.reset_gen();
  result.idle = platform.idle();
  if (!result.live) {
    return result;
  }
  auto& core = core_locked(current);
  result.any_running = current.processor->any_running();
  result.pending_reads = counter_test::pending_reads(core);
  result.core_cycles = core.perf_stats().cycles;
  result.core_instructions = core.perf_stats().instrs;
  result.exitcode = core.get_exitcode();
  if (current.inventory_ready) {
    size_t index = 0;
    for (const auto& selected : current.selectors) {
      for (auto* component : selected.components) {
        result.components.at(index++) = uint64_t(*component);
      }
    }
  }
  return result;
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
  auto& platform = vortex::SimPlatform::instance();
  read.ticks_after = platform.cycles();
  read.reset_after = platform.reset_gen();
  read.class_after = core_locked(current).mpm_class();
}

} // namespace

Observation observation() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  return current.observed;
}

ModelState model_state() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  if (current.processor != nullptr) {
    inventory_locked(current);
  }
  return model_locked(current);
}

std::array<uint32_t, 3> read_program_words(uint64_t address) {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  auto* processor = core_locked(current).processor();
  std::array<uint32_t, 3> words{};
  if (processor == nullptr || processor->ram() == nullptr
      || address > std::numeric_limits<uint64_t>::max() - sizeof(words)) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic program RAM is unavailable");
  }
  // Observe the actual functional backing store after the public work is collected.
  // This read does not advance the timing model or use a failed CP request.
  processor->ram()->read(words.data(), address, sizeof(words));
  return words;
}

std::array<SelectorInfo, kSelectorCount> selector_info() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  inventory_locked(current);
  std::array<SelectorInfo, kSelectorCount> result;
  for (size_t index = 0; index < result.size(); ++index) {
    const auto& selected = current.selectors[index];
    result[index] = {selected.name, selected.perf_class, selected.csr, selected.components.size()};
  }
  return result;
}

void seed_component(size_t selector, size_t component, uint64_t value) {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  inventory_locked(current);
  const auto model = model_locked(current);
  if (!model.idle || model.any_running || model.pending_reads != 0) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic seed requires a quiescent model");
  }
  *current.selectors.at(selector).components.at(component) = value;
}

void clear_components() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  inventory_locked(current);
  const auto model = model_locked(current);
  if (!model.idle || model.any_running || model.pending_reads != 0) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic reset requires a quiescent model");
  }
  for (const auto& selected : current.selectors) {
    for (auto* component : selected.components) {
      *component = uint64_t{0};
    }
  }
}

std::vector<DcrRead> read_trace() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  return {current.reads.begin(), current.reads.begin() + current.read_count};
}

void clear_read_trace() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  current.read_count = 0;
}

std::vector<Destruction> destruction_trace() {
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  return {current.destructions.begin(), current.destructions.begin() + current.destruction_count};
}

} // namespace counter_test::public_hooks

extern "C" {
void __real__ZN6vortex9ProcessorC1Ev(vortex::Processor*);
void __real__ZN6vortex9ProcessorD1Ev(vortex::Processor*) noexcept;
void __real__ZN6vortex9Processor11run_checkedEv(vortex::Processor*);
int __real__ZN6vortex9Processor8dcr_readEjjPj(vortex::Processor*, uint32_t, uint32_t, uint32_t*);
int __real__ZN6vortex9Processor9dcr_writeEjj(vortex::Processor*, uint32_t, uint32_t);
}

extern "C" void __wrap__ZN6vortex9ProcessorC1Ev(vortex::Processor* processor) {
  using namespace counter_test::public_hooks;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  ++current.observed.constructor_entries;
  if (current.processor != nullptr) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic requires one live native processor");
  }
  try {
    __real__ZN6vortex9ProcessorC1Ev(processor);
  } catch (...) {
    ++current.observed.unexpected_errors;
    throw;
  }
  current.processor = processor;
  current.inventory_ready = false;
  ++current.observed.constructed;
  ++current.observed.generation;
  current.observed.live = true;
}

extern "C" void __wrap__ZN6vortex9ProcessorD1Ev(vortex::Processor* processor) noexcept {
  using namespace counter_test::public_hooks;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  ++current.observed.destructor_entries;
  Destruction* record = nullptr;
  if (current.processor == processor && current.destruction_count < kMaxDestructions) {
    record = &current.destructions[current.destruction_count++];
    record->before = model_locked(current);
  } else {
    ++current.observed.violations;
  }
  __real__ZN6vortex9ProcessorD1Ev(processor);
  if (record != nullptr) {
    auto& platform = vortex::SimPlatform::instance();
    record->completed = true;
    record->ticks_after = platform.cycles();
    record->reset_after = platform.reset_gen();
    record->idle_after = platform.idle();
  }
  current.processor = nullptr;
  current.inventory_ready = false;
  ++current.observed.destroyed;
  current.observed.live = false;
}

extern "C" void __wrap__ZN6vortex9Processor11run_checkedEv(vortex::Processor* processor) {
  using namespace counter_test::public_hooks;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  check_owner_locked(current, processor);
  ++current.observed.run_entries;
  try {
    __real__ZN6vortex9Processor11run_checkedEv(processor);
    ++current.observed.run_completed;
  } catch (const vortex::PerfCounterError& error) {
    ++current.observed.run_errors;
    counter_error_locked(current, error);
    throw;
  } catch (...) {
    ++current.observed.unexpected_errors;
    throw;
  }
}

extern "C" int __wrap__ZN6vortex9Processor8dcr_readEjjPj(
    vortex::Processor* processor, uint32_t addr, uint32_t tag, uint32_t* value) {
  using namespace counter_test::public_hooks;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  check_owner_locked(current, processor);
  ++current.observed.dcr_read_entries;
  if (current.read_count == kMaxReads) {
    ++current.observed.violations;
    throw std::logic_error("public diagnostic read trace capacity exceeded");
  }
  auto& read = current.reads[current.read_count++];
  read = DcrRead{};
  read.sequence = current.observed.dcr_read_entries;
  read.generation = current.observed.generation;
  read.addr = addr;
  read.tag = tag;
  auto& platform = vortex::SimPlatform::instance();
  read.ticks_before = platform.cycles();
  read.reset_before = platform.reset_gen();
  read.class_before = core_locked(current).mpm_class();
  try {
    read.status = __real__ZN6vortex9Processor8dcr_readEjjPj(processor, addr, tag, value);
    read.completed = true;
    if (read.status == 0 && value != nullptr) {
      read.value = *value;
    }
    ++current.observed.dcr_read_completed;
    finish_read_locked(current, read);
    return read.status;
  } catch (const vortex::PerfCounterError& error) {
    ++current.observed.dcr_read_errors;
    read.overflow = error.reason() == vortex::PerfCounterError::Reason::Overflow;
    counter_error_locked(current, error);
    finish_read_locked(current, read);
    throw;
  } catch (...) {
    ++current.observed.unexpected_errors;
    finish_read_locked(current, read);
    throw;
  }
}

extern "C" int __wrap__ZN6vortex9Processor9dcr_writeEjj(
    vortex::Processor* processor, uint32_t addr, uint32_t value) {
  using namespace counter_test::public_hooks;
  auto& current = state();
  std::lock_guard<std::mutex> lock(current.mutex);
  check_owner_locked(current, processor);
  ++current.observed.dcr_write_entries;
  try {
    int status = __real__ZN6vortex9Processor9dcr_writeEjj(processor, addr, value);
    ++current.observed.dcr_write_completed;
    return status;
  } catch (const vortex::PerfCounterError& error) {
    ++current.observed.dcr_write_errors;
    counter_error_locked(current, error);
    throw;
  } catch (...) {
    ++current.observed.unexpected_errors;
    throw;
  }
}
