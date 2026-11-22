// SPDX-License-Identifier: Apache-2.0

#ifdef PUBLIC_COMPLETION_BACKEND

#include <atomic>
#include <cstring>
#include <limits>
#include <perf_counter.h>

#include "simulator_public_completion.cpp"

namespace {

std::atomic<unsigned> fault_site{0};
std::atomic<unsigned> fault_kind{0};
std::atomic<unsigned> triggered{0};
std::atomic<unsigned> typed{0};
std::atomic<unsigned> destination_preserved{0};
std::atomic<unsigned> source_preserved{0};

} // namespace

extern "C" void checked_counter_arm(unsigned site, unsigned kind) {
  if (site > 2 || kind > 2) {
    throw std::logic_error("invalid counter fault selection");
  }
  fault_kind.store(kind);
  fault_site.store(site);
}

extern "C" void checked_counter_trigger(unsigned site) {
  if (fault_site.load() != site) {
    return;
  }
  const unsigned kind = fault_kind.load();
  const uint64_t initial = kind == 0 ? std::numeric_limits<uint64_t>::max() : 0;
  vortex::PerfCounter value = initial;
  const vortex::PerfCounter source = 1;
  using Reason = vortex::PerfCounterError::Reason;
  const Reason expected = kind == 0 ? Reason::Overflow
                                   : (kind == 1 ? Reason::Underflow : Reason::NegativeOperand);
  const char* diagnostic = kind == 0 ? "SIMX_CHECKED_COUNTER_FAILURE: overflow"
                           : (kind == 1 ? "SIMX_CHECKED_COUNTER_FAILURE: underflow"
                                        : "SIMX_CHECKED_COUNTER_FAILURE: negative operand");
  triggered.fetch_add(1);
  try {
    if (kind == 0) {
      value += source;
    } else if (kind == 1) {
      --value;
    } else {
      value += -1;
    }
  } catch (const vortex::PerfCounterError& error) {
    if (error.reason() == expected && std::strcmp(error.what(), diagnostic) == 0) {
      typed.fetch_add(1);
    }
    if (uint64_t(value) == initial) {
      destination_preserved.fetch_add(1);
    }
    if (uint64_t(source) == 1) {
      source_preserved.fetch_add(1);
    }
    throw;
  }
  throw std::logic_error("counter fault did not throw");
}

extern "C" unsigned checked_counter_observe(unsigned selector) {
  switch (selector) {
  case 0: return triggered.load();
  case 1: return typed.load();
  case 2: return destination_preserved.load();
  case 3: return source_preserved.load();
  case 4: return completion_test::control.dcr_reads.load();
  default: throw std::logic_error("invalid counter observation");
  }
}

#else

#include <VX_types.h>

// Reuse the retained public-runtime assertions without changing their source.
#define main retained_public_completion_main
#include "simulator_public_completion.cpp"
#undef main

namespace {

class CounterControls {
public:
  CounterControls() {
    library_ = dlopen("libvortex-simx.so", RTLD_NOW | RTLD_LOCAL);
    expect(library_ != nullptr, "counter fixture backend could not be loaded");
    arm = reinterpret_cast<void (*)(unsigned, unsigned)>(dlsym(library_, "checked_counter_arm"));
    observe = reinterpret_cast<unsigned (*)(unsigned)>(dlsym(library_, "checked_counter_observe"));
    expect(arm != nullptr && observe != nullptr, "counter fixture controls are missing");
  }

  ~CounterControls() {
    if (library_) {
      dlclose(library_);
    }
  }

  void (*arm)(unsigned, unsigned) = nullptr;
  unsigned (*observe)(unsigned) = nullptr;

private:
  void* library_ = nullptr;
};

void failed_query(vx_device_h device) {
  const uint64_t sentinel = 0xdecafbad12345678ull;
  uint64_t value = sentinel;
  expect(vx_device_mpm_query(device, VX_DCR_MPM_CLASS_BASE, VX_CSR_MCYCLE, 0, &value)
         == VX_ERR_INVALID_VALUE, "counter query failure did not reach the public API");
  expect(value == sentinel, "failed counter query published an output");
}

void synchronous_counter_failure(Controls& controls, CounterControls& counters, bool llc) {
  counters.arm(0, 0);
  controls.arm(0, llc);
  const unsigned destroyed = controls.count(2);
  Context context(controls);
  uint64_t normal = 99;
  success(vx_device_mpm_query(context.device, VX_DCR_MPM_CLASS_BASE, VX_CSR_MCYCLE, 0, &normal),
          "healthy counter query failed");
  expect(normal == 0, "controlled healthy counter value differs");
  const unsigned reads = counters.observe(4);
  const unsigned writes = controls.count(1);
  const unsigned launches = controls.count(0);
  counters.arm(2, 0);
  failed_query(context.device);
  failed_query(context.device);
  expect(counters.observe(4) == reads + 1, "terminal query failure reentered the model");

  auto event = context.write();
  failed_event(event);
  expect(controls.count(1) == writes, "query failure allowed a later processor write");
  expect(vx_queue_finish(context.queue, kTimeout) == VX_ERR_INVALID_VALUE,
         "queue did not retain processor query failure");
  success(vx_queue_finish(context.queue, kTimeout), "queue-local error consumption failed");
  failed_event(event);
  failed_query(context.device);

  auto later = context.write();
  failed_event(later);
  expect(controls.count(1) == writes, "queue error consumption revived processor writes");
  expect(vx_queue_finish(context.queue, kTimeout) == VX_ERR_INVALID_VALUE,
         "later rejected command did not fail its queue");
  success(vx_queue_finish(context.queue, kTimeout), "later queue-local error did not clear");

  success(vx_queue_create(context.device, nullptr, &context.second_queue),
          "second queue creation failed");
  failed_event(context.launch(context.second_queue));
  expect(controls.count(0) == launches, "query failure allowed a later processor launch");
  expect(vx_queue_finish(context.second_queue, kTimeout) == VX_ERR_INVALID_VALUE,
         "second queue lost the processor failure");
  context.close();
  expect(controls.count(2) == destroyed + 1, "query-failed context leaked its processor");
  expect(controls.count(3) == 0, "query-failed processor was destroyed while active");
  counters.arm(0, 0);
  successful_context(controls, llc, 1);
}

} // namespace

int main(int argc, char** argv) {
  try {
    expect(argc == 3, "expected counter case and memory route");
    const char* driver = std::getenv("VORTEX_DRIVER");
    expect(driver && std::strcmp(driver, "simx") == 0, "counter host fixture requires SimX");
    const bool llc = std::strcmp(argv[2], "llc") == 0;
    expect(llc || std::strcmp(argv[2], "ram") == 0, "unknown memory route");
    Controls controls("simx");
    CounterControls counters;
    unsigned expected_faults = 1;
    if (std::strcmp(argv[1], "success") == 0) {
      expected_faults = 0;
      counters.arm(0, 0);
      successful_context(controls, llc, 3);
    } else if (std::strcmp(argv[1], "async-overflow") == 0) {
      counters.arm(1, 0);
      failed_context(controls, llc, 1);
    } else if (std::strcmp(argv[1], "async-underflow") == 0) {
      counters.arm(1, 1);
      failed_context(controls, llc, 1);
    } else if (std::strcmp(argv[1], "async-negative") == 0) {
      counters.arm(1, 2);
      failed_context(controls, llc, 1);
    } else if (std::strcmp(argv[1], "query-overflow") == 0) {
      synchronous_counter_failure(controls, counters, llc);
    } else {
      throw std::logic_error("unknown counter public case");
    }
    for (unsigned selector = 0; selector < 4; ++selector) {
      expect(counters.observe(selector) == expected_faults,
             "counter fault was not typed with unchanged operands");
    }
    expect(controls.count(4) == controls.count(0), "public runtime omitted the checked entry");
    expect(controls.count(5) == 0, "public runtime used the legacy processor entry");
    std::printf("PASS checked-counter-public %s checks=%u typed_faults=%u native_model=0\n",
                argv[1], checks, counters.observe(1));
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAIL checked-counter-public: %s\n", error.what());
    return 1;
  } catch (...) {
    std::fputs("FAIL checked-counter-public: exception escaped the public API\n", stderr);
    return 1;
  }
}

#endif
