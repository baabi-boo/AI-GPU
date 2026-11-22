// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <stdexcept>

namespace completion_test {

enum class Outcome { success, standard_exception, unknown_exception };

struct Control {
  std::mutex mutex;
  std::condition_variable changed;
  Outcome outcome = Outcome::success;
  bool released = false;
  bool llc = false;
  int legacy_gp = 0;
  unsigned entered = 0;
  unsigned returned = 0;
  std::atomic<unsigned> active{0};
  std::atomic<unsigned> checked_calls{0};
  std::atomic<unsigned> legacy_calls{0};
  std::atomic<unsigned> dcr_reads{0};
  std::atomic<unsigned> dcr_writes{0};
  std::atomic<unsigned> memory_reads{0};
  std::atomic<unsigned> memory_writes{0};
  std::atomic<unsigned> drains{0};
  std::atomic<unsigned> destroyed{0};
  std::atomic<unsigned> destroyed_active{0};
  std::atomic<unsigned> premature_frees{0};
  std::array<std::atomic<void*>, 8> tracked{};

  void arm(Outcome next) {
    std::lock_guard<std::mutex> lock(mutex);
    if (active.load() != 0) {
      throw std::logic_error("rearming active fixture");
    }
    outcome = next;
    released = false;
  }

  void await_entered(unsigned count) {
    std::unique_lock<std::mutex> lock(mutex);
    if (!changed.wait_for(lock, std::chrono::seconds(2), [&] { return entered >= count; })) {
      throw std::runtime_error("processor did not start");
    }
  }

  void release() {
    std::lock_guard<std::mutex> lock(mutex);
    released = true;
    changed.notify_all();
  }

  void execute() {
    Outcome result;
    {
      std::unique_lock<std::mutex> lock(mutex);
      ++entered;
      active.fetch_add(1);
      changed.notify_all();
      if (!changed.wait_for(lock, std::chrono::seconds(3), [&] { return released; })) {
        active.fetch_sub(1);
        throw std::runtime_error("fixture launch gate not released");
      }
      result = outcome;
      active.fetch_sub(1);
      ++returned;
      changed.notify_all();
    }
    if (result == Outcome::standard_exception) {
      throw std::runtime_error("injected simulator exception");
    }
    if (result == Outcome::unknown_exception) {
      throw 17;
    }
  }
};

inline Control control;

}  // namespace completion_test
