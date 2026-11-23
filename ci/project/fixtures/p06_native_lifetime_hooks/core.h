// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "perf_counter.h"

#include <cstdint>
#include <stdexcept>

namespace fixture {

enum class Fault {
  None, Standard, Nonstandard, Secondary, Overflow, Underflow, Negative
};

struct Sentinel {
  int value;
};

struct State {
  bool alive = false;
  bool idle = true;
  bool running = false;
  bool observation_fault = false;
  bool after_idle = true;
  bool after_running = false;
  uint64_t ticks = 0;
  uint64_t reset = 11;
  uint64_t pending = 0;
  uint64_t after_pending = 0;
  uint64_t reset_step = 1;
  uint64_t constructors = 0;
  uint64_t destructors = 0;
  uint64_t runs = 0;
  uint64_t reads = 0;
  uint64_t writes = 0;
  uint64_t pending_queries = 0;
  uint64_t dead_queries = 0;
  uint32_t mpm_class = 3;
  int gp = 0;
  int next_gp = 7;
  int read_status = 0;
  int write_status = 0;
  Fault run_fault = Fault::None;
  Fault read_fault = Fault::None;
  Fault write_fault = Fault::None;
};

inline State state;

inline void observe() {
  if (!state.alive) {
    ++state.dead_queries;
    throw std::runtime_error("dead processor observation");
  }
  if (state.observation_fault) {
    throw std::runtime_error("secondary observation fault");
  }
}

} // namespace fixture

namespace vortex {

constexpr unsigned SIMX_NUM_WORKERS = 1;

class SimPlatform {
public:
  static SimPlatform& instance() {
    static SimPlatform platform;
    return platform;
  }

  uint64_t cycles() const {
    return fixture::state.ticks;
  }

  uint64_t reset_gen() const {
    return fixture::state.reset;
  }

  bool idle() const {
    return fixture::state.idle;
  }
};

class Core {
public:
  struct PerfStats {
    uint64_t cycles = 0;
    uint64_t instrs = 0;
  };

  const PerfStats& perf_stats() const {
    fixture::observe();
    return stats;
  }

  int get_exitcode() const {
    fixture::observe();
    return fixture::state.gp;
  }

  uint32_t mpm_class() const {
    fixture::observe();
    return fixture::state.mpm_class;
  }

  PerfStats stats;
};

} // namespace vortex
