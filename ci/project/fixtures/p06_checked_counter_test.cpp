// SPDX-License-Identifier: Apache-2.0

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <future>
#include <limits>
#include <type_traits>

#include <perf_counter.h>
#include <async_run.h>

using vortex::PerfCounter;

#ifdef SIMX_CHECKED_COUNTERS
static_assert(!std::is_same_v<PerfCounter, uint64_t>);
static_assert(std::is_base_of_v<std::exception, vortex::PerfCounterError>);
static_assert(std::is_nothrow_constructible_v<vortex::PerfCounterError,
                                            vortex::PerfCounterError::Reason>);
#else
static_assert(std::is_same_v<PerfCounter, uint64_t>);
#endif

namespace {

constexpr uint64_t kMax = std::numeric_limits<uint64_t>::max();
unsigned failures = 0;

void expect(const char* label, uint64_t actual, uint64_t expected) {
  if (actual != expected) {
    std::fprintf(stderr, "FAILED: %s\n", label);
    ++failures;
  }
}

int boundaries() {
  PerfCounter counter{};
  expect("zero construction", counter, 0);
  counter += true;
  counter += false;
  expect("boolean deltas", counter, 1);
  expect("postincrement old value", counter++, 1);
  expect("preincrement new value", ++counter, 3);
  expect("postdecrement old value", counter--, 3);
  expect("predecrement new value", --counter, 1);
  counter -= 1;
  expect("subtraction to zero", counter, 0);
  counter += kMax;
  counter += 0;
  expect("addition to maximum", counter, kMax);
  counter -= kMax;
  expect("maximum subtraction", counter, 0);
  counter = kMax - 1;
  expect("increment to maximum", ++counter, kMax);
  counter = 0;
  counter -= 0;
  expect("zero delta at zero", counter, 0);

  PerfCounter first = kMax / 2;
  PerfCounter second = kMax / 2;
  PerfCounter total = 1;
  total += first;
  total += second;
  expect("aggregate to maximum", total, kMax);
  first += first;
  expect("self addition", first, kMax - 1);
  second -= second;
  expect("self subtraction", second, 0);
  PerfCounter snapshot = total;
  total -= PerfCounter(kMax);
  expect("counter delta subtraction", total, 0);
  expect("copy preserves snapshot", snapshot, kMax);
  counter = snapshot;
  expect("copy assignment", counter, kMax);
  counter = 7;
  expect("nonnegative signed assignment", counter, 7);
  counter += 5;
  counter -= 3;
  expect("nonnegative signed deltas", counter, 9);
  expect("read shift", counter >> 2, 2);
  expect("read mask", counter & uint64_t(7), 1);

  if (failures != 0) {
    return 1;
  }
  std::puts("PASSED: checked-counter boundaries");
  return 0;
}

#ifdef SIMX_CHECKED_COUNTERS
using CounterError = vortex::PerfCounterError;
using Reason = CounterError::Reason;

const char* diagnostic(Reason reason) {
  switch (reason) {
  case Reason::Overflow:
    return "SIMX_CHECKED_COUNTER_FAILURE: overflow";
  case Reason::Underflow:
    return "SIMX_CHECKED_COUNTER_FAILURE: underflow";
  case Reason::NegativeOperand:
    return "SIMX_CHECKED_COUNTER_FAILURE: negative operand";
  }
  return "unexpected reason";
}

template <typename Action>
void expect_counter_failure(Reason reason, Action&& action) {
  try {
    action();
    expect("invalid arithmetic returned", 1, 0);
  } catch (const CounterError& error) {
    expect("typed failure reason", error.reason() == reason, true);
    expect("exact failure diagnostic", std::strcmp(error.what(), diagnostic(reason)), 0);
    expect("repeat diagnostic has stable storage", error.what() == error.what(), true);
  } catch (...) {
    expect("wrong exception type", 1, 0);
  }
}

template <typename Action>
void expect_terminal(Action&& action) {
  try {
    action();
    expect("failed owner permitted later work", 1, 0);
  } catch (const std::runtime_error& error) {
    expect("terminal failure diagnostic",
           std::strcmp(error.what(), "simulator execution has failed"), 0);
  } catch (...) {
    expect("wrong terminal exception type", 1, 0);
  }
}

void check_terminal(vortex::AsyncRun& owner) {
  bool later_work = false;
  for (unsigned repeat = 0; repeat < 2; ++repeat) {
    expect_terminal([&]() { owner.wait(); });
    expect_terminal([&]() { owner.check(); });
    expect_terminal([&]() { (void)owner.busy(); });
    expect_terminal([&]() { owner.wait_for(std::chrono::seconds(0)); });
    expect_terminal([&]() { owner.invoke([&]() { later_work = true; }); });
    expect_terminal([&]() { owner.start([&]() { later_work = true; }); });
    expect("failure remains terminal", owner.failed(), true);
  }
  owner.join();
  expect("join preserves terminal failure", owner.failed(), true);
  expect("later work suppressed", later_work, false);
}

void check_fresh_owner() {
  PerfCounter counter = 0;
  vortex::AsyncRun fresh;
  fresh.start([&]() { ++counter; });
  fresh.wait();
  expect("fresh owner result", counter, 1);
  expect("fresh owner remains healthy", fresh.failed(), false);
  expect("fresh owner preserves launch edge", fresh.busy(), true);
  expect("fresh owner completes", fresh.busy(), false);
}
#endif

int arithmetic(const char* mode) {
  uint64_t initial = 13;
  uint64_t ordinary_result = 13;
  uint64_t operand = 0;
  const char* reason = "overflow";
  if (std::strcmp(mode, "add-overflow") == 0
   || std::strcmp(mode, "prefix-overflow") == 0
   || std::strcmp(mode, "postfix-overflow") == 0) {
    initial = kMax;
    ordinary_result = 0;
    operand = 1;
  } else if (std::strcmp(mode, "aggregate-overflow") == 0) {
    initial = kMax - 1;
    ordinary_result = 0;
    operand = 2;
  } else if (std::strcmp(mode, "self-add-overflow") == 0) {
    initial = kMax / 2 + 1;
    ordinary_result = 0;
  } else if (std::strcmp(mode, "subtract-underflow") == 0
          || std::strcmp(mode, "prefix-underflow") == 0
          || std::strcmp(mode, "postfix-underflow") == 0) {
    initial = 0;
    ordinary_result = kMax;
    operand = 1;
    reason = "underflow";
  } else if (std::strcmp(mode, "counter-subtract-underflow") == 0) {
    initial = 1;
    ordinary_result = kMax;
    operand = 2;
    reason = "underflow";
  } else if (std::strcmp(mode, "negative-construction") == 0) {
    reason = "negative operand";
  } else if (std::strcmp(mode, "negative-assignment") == 0) {
    ordinary_result = kMax;
    reason = "negative operand";
  } else if (std::strcmp(mode, "negative-addition") == 0) {
    ordinary_result = 12;
    reason = "negative operand";
  } else if (std::strcmp(mode, "negative-subtraction") == 0) {
    ordinary_result = 14;
    reason = "negative operand";
  } else {
    std::fputs("Unknown checked-counter arithmetic scenario\n", stderr);
    return 2;
  }
  PerfCounter counter = initial;
  PerfCounter delta = operand;
  int negative = -1;
  bool completed = false;
  uint64_t constructed = 0;
  auto action = [&]() {
    if (std::strcmp(mode, "add-overflow") == 0) {
      counter += 1;
    } else if (std::strcmp(mode, "aggregate-overflow") == 0) {
      counter += delta;
    } else if (std::strcmp(mode, "self-add-overflow") == 0) {
      counter += counter;
    } else if (std::strcmp(mode, "prefix-overflow") == 0) {
      ++counter;
    } else if (std::strcmp(mode, "postfix-overflow") == 0) {
      counter++;
    } else if (std::strcmp(mode, "subtract-underflow") == 0) {
      counter -= 1;
    } else if (std::strcmp(mode, "counter-subtract-underflow") == 0) {
      counter -= delta;
    } else if (std::strcmp(mode, "prefix-underflow") == 0) {
      --counter;
    } else if (std::strcmp(mode, "postfix-underflow") == 0) {
      counter--;
    } else if (std::strcmp(mode, "negative-construction") == 0) {
      PerfCounter value = negative;
      constructed = value;
    } else if (std::strcmp(mode, "negative-assignment") == 0) {
      counter = negative;
    } else if (std::strcmp(mode, "negative-addition") == 0) {
      counter += negative;
    } else if (std::strcmp(mode, "negative-subtraction") == 0) {
      counter -= negative;
    }
    completed = true;
  };
#ifdef SIMX_CHECKED_COUNTERS
  const Reason expected = std::strcmp(reason, "overflow") == 0 ? Reason::Overflow
                        : std::strcmp(reason, "underflow") == 0 ? Reason::Underflow
                        : Reason::NegativeOperand;
  expect_counter_failure(expected, action);
  expect("failed update preserves counter", counter, initial);
  expect("failed update does not return", completed, false);
  expect("failed construction publishes no value", constructed, 0);
  (void)ordinary_result;
#else
  action();
  expect("ordinary unsigned arithmetic result", counter, ordinary_result);
  expect("ordinary operation returns", completed, true);
  if (std::strcmp(mode, "negative-construction") == 0) {
    expect("ordinary negative construction", constructed, kMax);
  }
  (void)reason;
#endif
  expect("source counter unchanged", delta, operand);
  expect("signed operand unchanged", negative == -1, true);
  if (failures != 0) {
    return 1;
  }
#ifdef SIMX_CHECKED_COUNTERS
  std::printf("PASSED: checked-counter exception %s\n", reason);
#else
  std::puts("PASSED: ordinary uint64 arithmetic retained");
#endif
  return 0;
}

#ifdef SIMX_CHECKED_COUNTERS
struct MarkExit {
  bool& exited;
  ~MarkExit() { exited = true; }
};

int completion(const char* mode) {
  PerfCounter counter = kMax;
  bool completed = false;
  if (std::strcmp(mode, "future-overflow") == 0) {
    auto task = std::async(std::launch::async, [&]() { ++counter; completed = true; });
    task.wait();
    expect_counter_failure(Reason::Overflow, [&]() { task.get(); });
  } else if (std::strcmp(mode, "destructor-overflow") == 0) {
    bool exited = false;
    {
      vortex::AsyncRun owner;
      owner.start([&]() {
        MarkExit mark{exited};
        ++counter;
        completed = true;
      });
    }
    expect("destructor joins unwinding task", exited, true);
  } else {
    vortex::AsyncRun owner;
    if (std::strcmp(mode, "async-overflow") == 0) {
      owner.start([&]() { ++counter; completed = true; });
      expect_counter_failure(Reason::Overflow, [&]() { owner.wait(); });
    } else if (std::strcmp(mode, "sync-overflow") == 0) {
      expect_counter_failure(Reason::Overflow, [&]() {
        owner.invoke([&]() { ++counter; completed = true; });
      });
    } else if (std::strcmp(mode, "join-overflow") == 0) {
      owner.start([&]() { ++counter; completed = true; });
      owner.join();
    } else {
      std::fputs("Unknown checked-counter completion scenario\n", stderr);
      return 2;
    }
    check_terminal(owner);
  }
  expect("failed task preserves counter", counter, kMax);
  expect("failed task suppresses continuation", completed, false);
  check_fresh_owner();
  if (failures != 0) {
    return 1;
  }
  std::printf("PASSED: checked-counter completion %s\n", mode);
  return 0;
}
#endif

} // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::fputs("Expected one checked-counter scenario\n", stderr);
    return 2;
  }
  const char* mode = argv[1];
  if (std::strcmp(mode, "boundaries") == 0) {
    return boundaries();
  }
  if (std::strcmp(mode, "async-overflow") == 0
   || std::strcmp(mode, "sync-overflow") == 0
   || std::strcmp(mode, "future-overflow") == 0
   || std::strcmp(mode, "join-overflow") == 0
   || std::strcmp(mode, "destructor-overflow") == 0) {
#ifdef SIMX_CHECKED_COUNTERS
    return completion(mode);
#else
    PerfCounter counter = kMax;
    vortex::AsyncRun owner;
    owner.start([&]() { ++counter; });
    owner.wait();
    expect("ordinary asynchronous wrap", counter, 0);
    expect("ordinary asynchronous owner stays healthy", owner.failed(), false);
    if (failures != 0) {
      return 1;
    }
    std::puts("PASSED: ordinary uint64 arithmetic retained");
    return 0;
#endif
  }
  return arithmetic(mode);
}
