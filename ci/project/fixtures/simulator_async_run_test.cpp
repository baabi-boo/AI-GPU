// SPDX-License-Identifier: Apache-2.0
#include <async_run.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <exception>
#include <future>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

#ifdef __linux__
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace {

using namespace std::chrono_literals;

unsigned checks = 0;

void expect(bool condition, const char* message) {
  ++checks;
  if (!condition) {
    throw std::runtime_error(message);
  }
}

template <typename Operation>
void expect_rejected(Operation&& operation) {
  bool rejected = false;
  try {
    operation();
  } catch (const std::runtime_error&) {
    rejected = true;
  }
  expect(rejected, "terminal owner accepted an operation");
}

class Gate {
public:
  struct State {
    std::promise<void> entered;
    std::promise<void> release;
    std::shared_future<void> entry = entered.get_future().share();
    std::shared_future<void> released = release.get_future().share();
    std::atomic<bool> complete{false};
    std::atomic<bool> opened{false};
  };

  ~Gate() {
    open();
  }

  auto task(bool exceptional = false, bool unknown = false) const {
    return [state = state_, exceptional, unknown]() {
      state->entered.set_value();
      state->released.get();
      state->complete.store(true);
      if (exceptional) {
        if (unknown) {
          throw 47;
        }
        throw std::runtime_error("controlled task exception");
      }
    };
  }

  void await_entry() const {
    expect(state_->entry.wait_for(5s) == std::future_status::ready,
           "controlled task did not enter");
  }

  void open() noexcept {
    if (!state_->opened.exchange(true)) {
      state_->release.set_value();
    }
  }

  bool complete() const {
    return state_->complete.load();
  }

private:
  std::shared_ptr<State> state_ = std::make_shared<State>();
};

void expect_single_completed_edge(vortex::AsyncRun& run) {
  expect(run.busy(), "completed task lost its initial busy observation");
  expect(!run.busy(), "completed task did not become idle after the busy edge");
  expect(!run.busy(), "idle task repeated its launch edge");
}

void immediate_wait() {
  vortex::AsyncRun run;
  std::atomic<unsigned> executions{0};
  for (unsigned index = 1; index <= 16; ++index) {
    run.start([&executions]() { executions.fetch_add(1); });
    run.wait();
    expect(executions.load() == index, "wait did not complete exactly one task");
    run.check();
    run.wait_for(0s);
    expect_single_completed_edge(run);
  }
}

void immediate_bounded_wait() {
  vortex::AsyncRun run;
  Gate gate;
  run.start(gate.task());
  gate.await_entry();
  run.check();
  run.wait_for(0s);
  expect(!gate.complete(), "nonblocking observation released a held task");
  gate.open();
  run.wait_for(5s);
  expect(gate.complete(), "bounded wait did not observe the released task");
  run.check();
  expect_single_completed_edge(run);
}

#ifdef __linux__
void immediate_check() {
  vortex::AsyncRun run;
  Gate gate;
  std::promise<long> worker_id;
  auto identified = worker_id.get_future();
  run.start([id = std::move(worker_id), task = gate.task()]() mutable {
    id.set_value(::syscall(SYS_gettid));
    task();
  });
  gate.await_entry();
  const auto tid = identified.get();
  expect(tid > 0 && tid != ::syscall(SYS_gettid),
         "async task did not identify a distinct worker");
  const auto worker_path = "/proc/self/task/" + std::to_string(tid);
  struct stat status;
  expect(::stat(worker_path.c_str(), &status) == 0 && S_ISDIR(status.st_mode),
         "held async worker is missing from procfs");
  run.check();
  expect(!gate.complete(), "nonblocking check released the held worker");
  gate.open();

  // A task-return signal can precede future readiness; worker exit cannot.
  const auto deadline = std::chrono::steady_clock::now() + 5s;
  while (::stat(worker_path.c_str(), &status) == 0) {
    expect(std::chrono::steady_clock::now() < deadline,
           "async worker did not exit before the ready check");
    std::this_thread::yield();
  }
  expect(errno == ENOENT, "could not observe async worker exit through procfs");
  expect(::stat("/proc/self/task", &status) == 0 && S_ISDIR(status.st_mode),
         "procfs task directory disappeared while observing worker exit");
  expect(gate.complete(), "async worker exited before completing its task");
  run.check();
  expect_single_completed_edge(run);
}
#endif

void pending_observations() {
  vortex::AsyncRun run;
  Gate gate;
  run.start(gate.task());
  gate.await_entry();
  for (unsigned index = 0; index < 4; ++index) {
    run.check();
    run.wait_for(0s);
    expect(run.busy(), "held task became idle");
    expect(!gate.complete(), "held task completed before release");
  }
  gate.open();
  run.wait();
  expect(gate.complete(), "released task did not complete");
  expect(!run.busy(), "observed launch edge was repeated after completion");
  run.start([]() {});
  run.wait();
  expect_single_completed_edge(run);
}

void terminal_methods(vortex::AsyncRun& run) {
  std::atomic<unsigned> unexpected_executions{0};
  expect_rejected([&run]() { run.check(); });
  expect_rejected([&run]() { (void)run.busy(); });
  expect_rejected([&run]() { run.wait(); });
  expect_rejected([&run]() { run.wait_for(0s); });
  expect_rejected([&]() {
    run.start([&unexpected_executions]() { unexpected_executions.fetch_add(1); });
  });
  run.join();
  run.join();
  expect(unexpected_executions.load() == 0, "terminal owner launched replacement work");
  expect_rejected([&run]() { run.check(); });
}

void task_exception(const char* method, bool unknown) {
  vortex::AsyncRun run;
  Gate gate;
  run.start(gate.task(true, unknown));
  gate.await_entry();
  gate.open();
  std::exception_ptr observed;
  const auto deadline = std::chrono::steady_clock::now() + 5s;
  do {
    try {
      if (std::strcmp(method, "check") == 0) {
        run.check();
      } else if (std::strcmp(method, "bounded") == 0) {
        run.wait_for(5s);
      } else {
        run.wait();
      }
    } catch (...) {
      observed = std::current_exception();
    }
    if (!observed) {
      expect(std::strcmp(method, "check") == 0,
             "blocking observation discarded the task exception");
      expect(std::chrono::steady_clock::now() < deadline,
             "nonblocking observation never consumed the task exception");
      std::this_thread::yield();
    }
  } while (!observed);

  bool exact = false;
  try {
    std::rethrow_exception(observed);
  } catch (int value) {
    exact = unknown && value == 47;
  } catch (const std::runtime_error& error) {
    exact = !unknown && std::strcmp(error.what(), "controlled task exception") == 0;
  }
  expect(exact, "first observation did not preserve the original task exception");
  expect(gate.complete(), "exception observed before task execution");
  terminal_methods(run);
}

void overlap_pending() {
  vortex::AsyncRun run;
  Gate gate;
  run.start(gate.task());
  gate.await_entry();
  std::atomic<unsigned> replacement{0};
  expect_rejected([&]() {
    run.start([&replacement]() { replacement.fetch_add(1); });
  });
  expect(!gate.complete(), "overlap rejection released the original task");
  gate.open();
  run.join();
  expect(gate.complete(), "cleanup did not join the original task after overlap");
  expect(replacement.load() == 0, "overlapping task was executed");
  terminal_methods(run);
}

void overlap_completed_edge() {
  vortex::AsyncRun run;
  std::atomic<unsigned> executions{0};
  run.start([&executions]() { executions.fetch_add(1); });
  run.wait();
  expect_rejected([&]() {
    run.start([&executions]() { executions.fetch_add(1); });
  });
  expect(executions.load() == 1, "replacement consumed an unobserved launch edge");
  terminal_methods(run);
}

void failed_pending_cleanup() {
  std::atomic<bool> destroyed{false};
  std::atomic<bool> task_completed{false};
  std::promise<void> entered;
  std::promise<void> release;
  auto entered_future = entered.get_future();
  auto released = release.get_future().share();
  auto run = std::make_unique<vortex::AsyncRun>();
  run->start([&]() {
    entered.set_value();
    released.get();
    task_completed.store(true);
    throw 47;
  });
  expect(entered_future.wait_for(5s) == std::future_status::ready,
         "cleanup task did not enter");
  run->fail();
  expect_rejected([&run]() { run->check(); });
  std::promise<void> closing;
  auto closing_future = closing.get_future();
  std::thread closer([owned = std::move(run), &closing, &destroyed]() mutable {
    closing.set_value();
    owned.reset();
    destroyed.store(true);
  });
  closing_future.wait();
  const bool prematurely_destroyed = destroyed.load();
  release.set_value();
  closer.join();
  expect(!prematurely_destroyed, "failed owner detached the pending task");
  expect(destroyed.load() && task_completed.load(),
         "failed owner destruction did not join the exceptional task");
}

} // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::fprintf(stderr, "one test group is required\n");
    return 2;
  }
  try {
    if (std::strcmp(argv[1], "immediate_wait") == 0) {
      immediate_wait();
    } else if (std::strcmp(argv[1], "immediate_bounded") == 0) {
      immediate_bounded_wait();
    #ifdef __linux__
    } else if (std::strcmp(argv[1], "immediate_check") == 0) {
      immediate_check();
    #endif
    } else if (std::strcmp(argv[1], "pending") == 0) {
      pending_observations();
    } else if (std::strcmp(argv[1], "exceptions") == 0) {
      for (const auto* method : {"wait", "check", "bounded"}) {
        task_exception(method, false);
        task_exception(method, true);
      }
    } else if (std::strcmp(argv[1], "overlap_pending") == 0) {
      overlap_pending();
    } else if (std::strcmp(argv[1], "overlap_edge") == 0) {
      overlap_completed_edge();
    } else if (std::strcmp(argv[1], "failed_cleanup") == 0) {
      failed_pending_cleanup();
    } else {
      throw std::runtime_error("unknown test group");
    }
    std::printf("PASS simulator-async-run %s checks=%u\n", argv[1], checks);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAIL simulator-async-run %s: %s\n", argv[1], error.what());
    return 1;
  } catch (...) {
    std::fprintf(stderr, "FAIL simulator-async-run %s: unexpected exception\n", argv[1]);
    return 1;
  }
}
