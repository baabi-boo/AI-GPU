// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <atomic>
#include <cstdlib>
#include <cstring>
#include <new>

namespace error_boundary_test {

enum Hook { none, run, dcr_read, dcr_write, memory_read, memory_write, drain };
inline std::atomic<unsigned> armed{none};
inline std::atomic<unsigned> outcome{0};
inline std::atomic<unsigned> operations{0};
inline std::atomic<unsigned> faults{0};

inline bool llc() {
  const char* route = std::getenv("SIMULATOR_ERROR_MEMORY");
  return route && std::strcmp(route, "llc") == 0;
}

inline void visit(Hook hook) {
  operations.fetch_add(1);
  unsigned expected = hook;
  if (armed.compare_exchange_strong(expected, none)) {
    faults.fetch_add(1);
    if (outcome.load() == 0) {
      throw std::bad_alloc();
    }
    throw 37;
  }
}

} // namespace error_boundary_test
