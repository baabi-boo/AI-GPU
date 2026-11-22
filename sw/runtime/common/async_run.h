// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <chrono>
#include <future>
#include <stdexcept>
#include <utility>

namespace vortex {

class AsyncRun {
public:
  AsyncRun() = default;
  AsyncRun(const AsyncRun&) = delete;
  AsyncRun& operator=(const AsyncRun&) = delete;

  ~AsyncRun() {
    join();
  }

  template <typename Task>
  void start(Task&& task) {
    check();
    if (future_.valid() || start_pending_) {
      failed_ = true;
      throw std::runtime_error("simulator launch is already pending");
    }
    try {
      future_ = std::async(std::launch::async, std::forward<Task>(task));
      start_pending_ = true;
    } catch (...) {
      failed_ = true;
      throw;
    }
  }

  void check() {
    require_healthy();
    if (future_.valid()
     && future_.wait_for(std::chrono::seconds(0)) == std::future_status::ready) {
      collect();
    }
  }

  bool busy() {
    check();
    // Completion cannot erase the launch edge before its first observation.
    if (std::exchange(start_pending_, false)) {
      return true;
    }
    return future_.valid();
  }

  void wait() {
    require_healthy();
    if (future_.valid()) {
      collect();
    }
  }

  template <typename Rep, typename Period>
  void wait_for(const std::chrono::duration<Rep, Period>& duration) {
    require_healthy();
    if (future_.valid() && future_.wait_for(duration) == std::future_status::ready) {
      collect();
    }
  }

  void fail() noexcept {
    failed_ = true;
  }

  void join() noexcept {
    if (future_.valid()) {
      try {
        future_.get();
      } catch (...) {
        failed_ = true;
      }
    }
  }

private:
  void require_healthy() const {
    if (failed_) {
      throw std::runtime_error("simulator execution has failed");
    }
  }

  void collect() {
    try {
      future_.get();
    } catch (...) {
      failed_ = true;
      throw;
    }
  }

  std::future<void> future_;
  bool start_pending_ = false;
  bool failed_ = false;
};

}
