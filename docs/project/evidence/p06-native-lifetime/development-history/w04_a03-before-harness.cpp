// SPDX-License-Identifier: Apache-2.0
#include "hooks.h"
#include "processor.h"

#include <cstdio>
#include <limits>
#include <string>

extern "C" {
void __wrap__ZN6vortex9ProcessorC1Ev(vortex::Processor*);
void __wrap__ZN6vortex9ProcessorD1Ev(vortex::Processor*) noexcept;
void __wrap__ZN6vortex9Processor11run_checkedEv(vortex::Processor*);
int __wrap__ZN6vortex9Processor8dcr_readEjjPj(vortex::Processor*, uint32_t, uint32_t, uint32_t*);
int __wrap__ZN6vortex9Processor9dcr_writeEjj(vortex::Processor*, uint32_t, uint32_t);
}

namespace {

void expect(bool condition, const char* reason) {
  if (!condition) {
    throw std::runtime_error(reason);
  }
}

void fault(fixture::Fault selected) {
  using Reason = vortex::PerfCounterError::Reason;
  switch (selected) {
  case fixture::Fault::None: return;
  case fixture::Fault::Standard: throw std::runtime_error("original execution fault");
  case fixture::Fault::Secondary:
    fixture::state.observation_fault = true;
    throw fixture::Sentinel{73};
  case fixture::Fault::Nonstandard: throw fixture::Sentinel{73};
  case fixture::Fault::Overflow: throw vortex::PerfCounterError(Reason::Overflow);
  case fixture::Fault::Underflow: throw vortex::PerfCounterError(Reason::Underflow);
  case fixture::Fault::Negative: throw vortex::PerfCounterError(Reason::NegativeOperand);
  }
}

class Session {
public:
  Session() { __wrap__ZN6vortex9ProcessorC1Ev(&processor); }
  ~Session() { close(); }

  void close() {
    if (open) {
      __wrap__ZN6vortex9ProcessorD1Ev(&processor);
      open = false;
    }
  }

  void run() { __wrap__ZN6vortex9Processor11run_checkedEv(&processor); }

  int read(bool flush, uint32_t* value) {
    return __wrap__ZN6vortex9Processor8dcr_readEjjPj(&processor,
        flush ? VX_DCR_BASE_CACHE_FLUSH : VX_DCR_BASE_MPM_VALUE, 0, value);
  }

  vortex::Processor processor;
  bool open = true;
};

template <typename Call>
void expect_logic(Call&& call) {
  bool caught = false;
  try {
    call();
  } catch (const std::logic_error&) {
    caught = true;
  }
  expect(caught, "expected lifetime guard rejection");
}

#ifndef P06_PARENT_CONTROL

p06_preflight::Observation observation() {
  p06_preflight::Observation result;
  expect(p06_preflight_get_observation(&result) == 0, "observation export failed");
  return result;
}

p06_preflight::RunObservation run_record(size_t index = 0) {
  p06_preflight::RunObservation result;
  expect(p06_preflight_get_run(index, &result) == 0, "run export failed");
  return result;
}

void enable() {
  expect(p06_preflight_enable_lifetime() == 0, "lifetime selection failed");
}

void check_balanced() {
  const auto observed = observation();
  expect(observed.destroyed == 1 && fixture::state.destructors == 1,
         "real destructor did not execute exactly once");
  expect(observed.destruction.completed && !observed.live && fixture::state.dead_queries == 0,
         "destruction read a dead processor or failed to complete");
}

void success(const std::string& mode) {
  auto& state = fixture::state;
  const bool legacy = mode == "default-v1";
  if (!legacy) {
    enable();
  }
  Session session;
  state.next_gp = mode == "success-minus-one" ? -1 : 7;
  const uint64_t baseline = state.reset;
  const unsigned count = legacy ? 34 : 33;
  for (unsigned index = 0; index < count; ++index) {
    if (legacy) {
      state.pending = 1;
    }
    session.run();
    expect(state.gp == state.next_gp, "legacy gp was interpreted as an error");
    if (!legacy) {
      const auto run = run_record(index);
      expect(run.ordinal == index + 1 && run.real_call_entered && run.completed && !run.exception,
             "successful real call was not recorded");
      expect(run.before.pending_reads == 0 && run.after.pending_reads == 0
          && run.before.reset_generation == baseline + index
          && run.after.reset_generation == baseline + index + 1
          && run.after.exitcode == state.next_gp,
             "run record differs from the controlled real boundary");
    }
  }
  const auto before = observation();
  expect(before.run_entries == count && before.run_completed == count && before.run_errors == 0,
         "successful run accounting differs");
  if (legacy) {
    expect(!before.lifetime_enabled && before.run_count == 0 && state.pending_queries == 0,
           "default mode selected lifetime behavior");
  } else {
    p06_preflight::ModelState terminal;
    expect(p06_preflight_get_model_state(&terminal) == 0, "terminal observation failed");
    session.close();
    const auto destroyed = observation().destruction;
    expect(destroyed.before.pending_reads == terminal.pending_reads
        && destroyed.before.ticks == terminal.ticks
        && destroyed.before.reset_generation == terminal.reset_generation
        && destroyed.before.core_cycles == terminal.core_cycles
        && destroyed.before.core_instructions == terminal.core_instructions
        && destroyed.before.exitcode == terminal.exitcode
        && destroyed.ticks_after == 0 && destroyed.reset_after == terminal.reset_generation,
           "destruction did not preserve the last live state");
  }
  session.close();
  check_balanced();
}

void before_run(const std::string& mode) {
  enable();
  Session session;
  auto& state = fixture::state;
  if (mode == "before-pending") {
    state.pending = 1;
  }
  if (mode == "before-idle") {
    state.idle = false;
  }
  if (mode == "before-running") {
    state.running = true;
  }
  if (mode == "reset-exhausted") {
    state.reset = std::numeric_limits<uint64_t>::max();
  }
  const auto reset = state.reset;
  expect_logic([&] { session.run(); });
  expect(state.runs == 0 && state.reset == reset, "pre-run guard allowed the real reset");
  const auto run = run_record();
  expect(!run.real_call_entered && !run.completed && run.exception,
         "rejected entry was reported as a completed real call");
  if (mode == "before-pending") {
    expect(state.pending == 1 && run.before.pending_reads == 1 && run.after.pending_reads == 1,
           "pre-run observation erased the nonzero pending balance");
  }
  expect(observation().run_errors == 1 && observation().violations > 0,
         "rejected entry lacks failure accounting");
  state.idle = true;
  state.running = false;
  session.close();
  check_balanced();
}

void after_run(const std::string& mode) {
  enable();
  Session session;
  auto& state = fixture::state;
  if (mode == "after-pending") {
    state.after_pending = 1;
  }
  if (mode == "after-idle") {
    state.after_idle = false;
  }
  if (mode == "after-running") {
    state.after_running = true;
  }
  if (mode == "reset-skip") {
    state.reset_step = 0;
  }
  if (mode == "reset-extra") {
    state.reset_step = 2;
  }
  expect_logic([&] { session.run(); });
  const auto run = run_record();
  expect(state.runs == 1 && run.real_call_entered && run.completed && run.exception,
         "post-return failure lost actual call completion or rejection");
  expect(observation().run_errors == 1 && observation().violations > 0,
         "post-return failure lacks accounting");
  state.idle = true;
  state.running = false;
  session.close();
  check_balanced();
}

fixture::Fault selected_fault(const std::string& mode) {
  if (mode.find("secondary") != std::string::npos) {
    return fixture::Fault::Secondary;
  }
  if (mode.find("nonstandard") != std::string::npos) {
    return fixture::Fault::Nonstandard;
  }
  if (mode.find("overflow") != std::string::npos) {
    return fixture::Fault::Overflow;
  }
  if (mode.find("underflow") != std::string::npos) {
    return fixture::Fault::Underflow;
  }
  if (mode.find("negative") != std::string::npos) {
    return fixture::Fault::Negative;
  }
  return fixture::Fault::Standard;
}

template <typename Call>
void expect_original(Call&& call, fixture::Fault selected) {
  bool caught = false;
  try {
    call();
  } catch (const fixture::Sentinel& error) {
    caught = (selected == fixture::Fault::Secondary || selected == fixture::Fault::Nonstandard)
        && error.value == 73;
  } catch (const vortex::PerfCounterError& error) {
    using Reason = vortex::PerfCounterError::Reason;
    caught = (selected == fixture::Fault::Overflow && error.reason() == Reason::Overflow)
        || (selected == fixture::Fault::Underflow && error.reason() == Reason::Underflow)
        || (selected == fixture::Fault::Negative && error.reason() == Reason::NegativeOperand);
  } catch (const std::runtime_error& error) {
    caught = selected == fixture::Fault::Standard && std::string(error.what()) == "original execution fault";
  }
  expect(caught, "wrapper replaced or swallowed the original execution exception");
}

void exceptions(const std::string& mode) {
  enable();
  Session session;
  auto& state = fixture::state;
  const auto selected = selected_fault(mode);
  uint32_t value = 0;
  if (mode.rfind("read-", 0) == 0) {
    state.read_fault = selected;
    expect_original([&] { session.read(false, &value); }, selected);
    expect(observation().dcr_read_errors == 1, "read exception was not counted");
  } else if (mode.rfind("write-", 0) == 0) {
    state.write_fault = selected;
    expect_original([&] { __wrap__ZN6vortex9Processor9dcr_writeEjj(&session.processor, 0, 0); }, selected);
    expect(observation().dcr_write_errors == 1, "write exception was not counted");
  } else {
    state.run_fault = selected;
    expect_original([&] { session.run(); }, selected);
    const auto run = run_record();
    expect(run.real_call_entered && !run.completed && run.exception && observation().run_errors == 1,
           "execution exception was recorded as completed");
  }
  const auto observed = observation();
  if (selected == fixture::Fault::Overflow) {
    expect(observed.overflow_errors == 1, "overflow kind lost");
  }
  if (selected == fixture::Fault::Underflow) {
    expect(observed.underflow_errors == 1, "underflow kind lost");
  }
  if (selected == fixture::Fault::Negative) {
    expect(observed.negative_operand_errors == 1, "negative kind lost");
  }
  if (selected == fixture::Fault::Secondary) {
    expect(observed.unexpected_errors >= 2, "secondary observation failure was not retained");
  }
  state.observation_fault = false;
  session.close();
  check_balanced();
}

void reads(const std::string& mode) {
  enable();
  Session session;
  auto& state = fixture::state;
  const bool flush = mode.find("flush") != std::string::npos;
  uint32_t value = 0xfeedu;
  const bool before = mode.find("before") != std::string::npos;
  const bool after = mode.find("after") != std::string::npos;
  if (before) {
    state.pending = 1;
  }
  if (after) {
    state.after_pending = 1;
  }
  if (before || after) {
    expect_logic([&] { session.read(flush, &value); });
    expect(state.reads == (before ? 0 : 1), "read guard ran at the wrong side of the real call");
  } else if (mode == "read-null") {
    expect(session.read(flush, nullptr) == 0, "null-output status changed");
  } else {
    state.read_status = -9;
    expect(session.read(flush, &value) == -9, "failed read status was suppressed");
  }
  p06_preflight::DcrRead read;
  const int result = flush ? p06_preflight_get_cache_flush_read(0, &read) : p06_preflight_get_read(0, &read);
  expect(result == 0 && observation().dcr_read_errors == 1, "failed read record was lost");
  if (before) {
    expect(read.pending_before == 1 && !read.completed, "pre-read balance was not retained");
  }
  if (after) {
    expect(read.pending_after == 1 && read.completed, "post-read balance was not retained");
  }
  if (mode == "read-status" || mode == "flush-status") {
    expect(read.status == -9 && read.completed && value == 0xfeedu, "raw error status/output changed");
  }
  session.close();
  check_balanced();
}

void capacity(const std::string& mode) {
  enable();
  Session session;
  auto& state = fixture::state;
  if (mode == "run-capacity") {
    for (size_t index = 0; index < p06_preflight::kMaxRuns; ++index) { session.run(); }
    const auto reset = state.reset;
    expect_logic([&] { session.run(); });
    expect(state.runs == 33 && state.reset == reset && observation().run_count == 33,
           "overflow entered a thirty-fourth real run");
    p06_preflight::RunObservation run;
    expect(p06_preflight_get_run(33, &run) == -1, "overflow exposed an out-of-bounds run");
  } else {
    const bool flush = mode == "flush-capacity";
    uint32_t value = 0;
    for (size_t index = 0; index < p06_preflight::kMaxReads; ++index) { session.read(flush, &value); }
    expect_logic([&] { session.read(flush, &value); });
    expect(state.reads == p06_preflight::kMaxReads, "overflow entered another real read");
    p06_preflight::DcrRead read;
    expect((flush ? p06_preflight_get_cache_flush_read(512, &read)
                  : p06_preflight_get_read(512, &read)) == -1,
           "overflow exposed an out-of-bounds read");
  }
  expect(observation().trace_overflow && observation().violations > 0, "trace overflow was not retained");
  session.close();
  check_balanced();
}

void ownership(const std::string& mode) {
  if (mode != "late-enable") {
    enable();
  }
  if (mode == "duplicate-enable") {
    expect(p06_preflight_enable_lifetime() == -1 && observation().violations == 1,
           "duplicate mode selection was accepted");
    return;
  }
  Session session;
  if (mode == "late-enable") {
    expect(p06_preflight_enable_lifetime() == -1 && !observation().lifetime_enabled,
           "late mode selection was accepted");
  } else if (mode == "wrong-owner") {
    vortex::Processor unrelated;
    expect_logic([&] { __wrap__ZN6vortex9Processor11run_checkedEv(&unrelated); });
    expect(fixture::state.runs == 0, "wrong owner entered real run");
  } else {
    session.close();
    expect_logic([&] { __wrap__ZN6vortex9ProcessorC1Ev(&session.processor); });
    expect(fixture::state.constructors == 1, "failed lifetime was replaced by a fresh processor");
  }
  session.close();
  check_balanced();
}

void disposal(const std::string& mode) {
  enable();
  Session session;
  if (mode == "destructor-pending") {
    fixture::state.pending = 1;
  }
  if (mode == "destructor-secondary") {
    fixture::state.observation_fault = true;
  }
  session.close();
  fixture::state.observation_fault = false;
  check_balanced();
  const auto observed = observation();
  expect(observed.unexpected_errors > 0, "invalid destruction boundary was treated as valid");
  if (mode == "destructor-pending") {
    expect(observed.destruction.before.pending_reads == 1 && observed.violations > 0,
           "disposal erased the pre-destruction pending observation");
  }
  p06_preflight::ModelState model;
  expect(p06_preflight_get_model_state(&model) == -1 && fixture::state.dead_queries == 0,
         "post-disposal inspection accessed destroyed processor state");
}

void run_case(const std::string& mode) {
  if (mode.rfind("success-", 0) == 0 || mode == "default-v1") {
    success(mode);
  } else if (mode.rfind("before-", 0) == 0 || mode == "reset-exhausted") {
    before_run(mode);
  } else if (mode.rfind("after-", 0) == 0 || mode == "reset-skip" || mode == "reset-extra") {
    after_run(mode);
  } else if (mode.find("exception-") != std::string::npos) {
    exceptions(mode);
  } else if (mode.find("capacity") != std::string::npos) {
    capacity(mode);
  } else if (mode == "duplicate-enable" || mode == "late-enable" || mode == "wrong-owner" || mode == "reconstruct") {
    ownership(mode);
  } else if (mode.rfind("destructor-", 0) == 0) {
    disposal(mode);
  } else if (mode.rfind("read-", 0) == 0 || mode.rfind("flush-", 0) == 0) {
    reads(mode);
  } else {
    throw std::runtime_error("unknown hook-control case");
  }
}

#endif

} // namespace

extern "C" void __real__ZN6vortex9ProcessorC1Ev(vortex::Processor*) {
  ++fixture::state.constructors;
  fixture::state.alive = true;
}

extern "C" void __real__ZN6vortex9ProcessorD1Ev(vortex::Processor*) noexcept {
  ++fixture::state.destructors;
  fixture::state.alive = false;
  fixture::state.pending = 0;
  fixture::state.ticks = 0;
  fixture::state.idle = true;
  fixture::state.running = false;
}

extern "C" void __real__ZN6vortex9Processor11run_checkedEv(vortex::Processor* processor) {
  auto& state = fixture::state;
  ++state.runs;
  state.pending = 0;
  state.reset += state.reset_step;
  state.ticks = 100 + state.runs;
  fault(state.run_fault);
  processor->core.stats.cycles += 20;
  processor->core.stats.instrs += 4;
  state.gp = state.next_gp;
  state.pending = state.after_pending;
  state.idle = state.after_idle;
  state.running = state.after_running;
}

extern "C" int __real__ZN6vortex9Processor8dcr_readEjjPj(
    vortex::Processor*, uint32_t addr, uint32_t, uint32_t* value) {
  auto& state = fixture::state;
  ++state.reads;
  fault(state.read_fault);
  state.pending = state.after_pending;
  if (addr == VX_DCR_BASE_CACHE_FLUSH) {
    state.ticks += 7;
  }
  if (value != nullptr && state.read_status == 0) {
    *value = 0;
  }
  return state.read_status;
}

extern "C" int __real__ZN6vortex9Processor9dcr_writeEjj(vortex::Processor*, uint32_t, uint32_t) {
  ++fixture::state.writes;
  fault(fixture::state.write_fault);
  return fixture::state.write_status;
}

#ifdef P06_PARENT_CONTROL
extern "C" int p06_preflight_enable_lifetime() noexcept __attribute__((weak));

int main() {
  try {
    if (p06_preflight_enable_lifetime != nullptr) {
      expect(p06_preflight_enable_lifetime() == 0, "lifetime selection failed");
    }
    Session session;
    fixture::state.pending = 1;
    const auto reset = fixture::state.reset;
    bool caught = false;
    try { session.run(); } catch (const std::logic_error&) { caught = true; }
    expect(fixture::state.runs == 0, "pending-before-reset: reset-bearing real run was entered");
    expect(caught && fixture::state.pending == 1 && fixture::state.reset == reset,
           "pending-before-reset: nonzero state was erased or not rejected");
    std::puts("PASS pending-before-reset");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED %s\n", error.what());
    return 1;
  }
}
#else
int main(int argc, char** argv) {
  const std::string mode = argc == 2 ? argv[1] : "";
  try {
    run_case(mode);
    std::printf("PASS %s\n", mode.c_str());
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED %s: %s\n", mode.c_str(), error.what());
  } catch (...) {
    std::fprintf(stderr, "FAILED %s: unexpected exception type\n", mode.c_str());
  }
  return 1;
}
#endif
