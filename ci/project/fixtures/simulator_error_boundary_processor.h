// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "simulator_error_boundary_control.h"
#include "mem.h"

namespace vortex {

class Processor {
public:
  void attach_ram(RAM* ram) { ram_ = ram; }
#ifdef COMPLETION_SIMX
  int run() {
    try {
      run_checked();
      return 7;
    } catch (...) {
      return -1;
    }
  }
  void run_checked() { error_boundary_test::visit(error_boundary_test::run); }
#else
  void run() { error_boundary_test::visit(error_boundary_test::run); }
#endif
  bool cp_llc_client() const { return error_boundary_test::llc(); }
  uint64_t cp_llc_size() const { return 4096; }
  void cp_mem_read(uint64_t address, void* destination, uint64_t bytes) {
    error_boundary_test::visit(error_boundary_test::memory_read);
    ram_->read(static_cast<uint8_t*>(destination), address, bytes);
  }
  void cp_mem_write(uint64_t address, const void* source, uint64_t bytes, bool) {
    error_boundary_test::visit(error_boundary_test::memory_write);
    ram_->write(static_cast<const uint8_t*>(source), address, bytes);
  }
  int dcr_write(uint32_t, uint32_t) {
    error_boundary_test::visit(error_boundary_test::dcr_write);
    return 0;
  }
  int dcr_read(uint32_t, uint32_t, uint32_t* value) {
    error_boundary_test::visit(error_boundary_test::dcr_read);
    *value = 0;
    return 0;
  }
  void drain() { error_boundary_test::visit(error_boundary_test::drain); }

private:
  RAM* ram_ = nullptr;
};

} // namespace vortex
