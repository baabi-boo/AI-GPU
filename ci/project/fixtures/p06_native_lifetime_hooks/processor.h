// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "core.h"

#define VX_DCR_BASE_MPM_VALUE 0x001
#define VX_DCR_BASE_CACHE_FLUSH 0x003

namespace vortex {

class Processor {
public:
  Core* get_first_core() const {
    fixture::observe();
    return &core;
  }

  bool any_running() const {
    fixture::observe();
    return fixture::state.running;
  }

  uint64_t pending_mem_reads() const {
    fixture::observe();
    ++fixture::state.pending_queries;
    return fixture::state.pending;
  }

  mutable Core core;
};

} // namespace vortex
