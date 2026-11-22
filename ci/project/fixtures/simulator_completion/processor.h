// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "control.h"
#include "mem.h"

namespace vortex {

class Processor {
public:
  void attach_ram(RAM* ram) { ram_ = ram; }

  ~Processor() {
    auto& state = completion_test::control;
    if (state.active.load() != 0) {
      state.destroyed_active.fetch_add(1);
    }
    state.destroyed.fetch_add(1);
  }

#ifdef COMPLETION_SIMX
  int run() {
    auto& state = completion_test::control;
    state.legacy_calls.fetch_add(1);
    try {
      state.execute();
      return state.legacy_gp;
    } catch (...) {
      return -1;
    }
  }

  void run_checked() {
    completion_test::control.checked_calls.fetch_add(1);
    completion_test::control.execute();
  }
#else
  void run() { completion_test::control.execute(); }
#endif

  bool cp_llc_client() const { return completion_test::control.llc; }
  uint64_t cp_llc_size() const { return 4096; }

  void cp_mem_read(uint64_t address, void* destination, uint64_t bytes) {
    completion_test::control.memory_reads.fetch_add(1);
    ram_->read(static_cast<uint8_t*>(destination), address, bytes);
  }

  void cp_mem_write(uint64_t address, const void* source, uint64_t bytes, bool) {
    completion_test::control.memory_writes.fetch_add(1);
    ram_->write(static_cast<const uint8_t*>(source), address, bytes);
  }

  int dcr_write(uint32_t, uint32_t) {
    completion_test::control.dcr_writes.fetch_add(1);
    return 0;
  }

  int dcr_read(uint32_t address, uint32_t tag, uint32_t* value) {
    completion_test::control.dcr_reads.fetch_add(1);
    *value = address ^ tag ^ 0x12345678u;
    return 0;
  }

  void drain() { completion_test::control.drains.fetch_add(1); }

private:
  RAM* ram_ = nullptr;
};

}  // namespace vortex
