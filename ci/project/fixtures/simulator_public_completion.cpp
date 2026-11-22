// SPDX-License-Identifier: Apache-2.0
#ifdef PUBLIC_COMPLETION_BACKEND

#include "control.h"

extern "C" void completion_test_arm(unsigned outcome, bool llc) {
  auto& state = completion_test::control;
  state.llc = llc;
  state.legacy_gp = 7;
  state.arm(static_cast<completion_test::Outcome>(outcome));
}

extern "C" void completion_test_await(unsigned count) {
  completion_test::control.await_entered(count);
}

extern "C" void completion_test_release() {
  completion_test::control.release();
}

extern "C" unsigned completion_test_count(unsigned selector) {
  auto& state = completion_test::control;
  switch (selector) {
  case 0: {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.entered;
  }
  case 1: return state.dcr_writes.load();
  case 2: return state.destroyed.load();
  case 3: return state.destroyed_active.load();
  case 4: return state.checked_calls.load();
  case 5: return state.legacy_calls.load();
  default: throw std::logic_error("unknown fixture counter");
  }
}

#else

#include <vortex2.h>

#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr uint64_t kTimeout = 2ull * 1000 * 1000 * 1000;
unsigned checks = 0;

void expect(bool condition, const char* reason) {
  ++checks;
  if (!condition) {
    throw std::runtime_error(reason);
  }
}

void success(vx_result_t result, const char* reason) {
  expect(result == VX_SUCCESS, reason);
}

class Controls {
public:
  explicit Controls(const char* backend) {
    const auto name = std::string("libvortex-") + backend + ".so";
    library_ = dlopen(name.c_str(), RTLD_NOW | RTLD_LOCAL);
    expect(library_ != nullptr, "cannot load production backend fixture");
    arm = symbol<void (*)(unsigned, bool)>("completion_test_arm");
    await = symbol<void (*)(unsigned)>("completion_test_await");
    release = symbol<void (*)()>("completion_test_release");
    count = symbol<unsigned (*)(unsigned)>("completion_test_count");
  }

  ~Controls() {
    if (library_) {
      dlclose(library_);
    }
  }

  void (*arm)(unsigned, bool) = nullptr;
  void (*await)(unsigned) = nullptr;
  void (*release)() = nullptr;
  unsigned (*count)(unsigned) = nullptr;

private:
  template <typename Function>
  Function symbol(const char* name) {
    auto result = reinterpret_cast<Function>(dlsym(library_, name));
    expect(result != nullptr, "missing fixture control symbol");
    return result;
  }

  void* library_ = nullptr;
};

class Context {
public:
  explicit Context(Controls& controls) : controls_(controls) {
    success(vx_device_open(0, &device), "public device open failed");
    success(vx_queue_create(device, nullptr, &queue), "public queue create failed");
  }

  ~Context() {
    controls_.release();
    if (queue) {
      vx_queue_finish(queue, kTimeout);
    }
    if (second_queue) {
      vx_queue_finish(second_queue, kTimeout);
    }
    for (auto event : events_) {
      vx_event_release(event);
    }
    if (second_queue) {
      vx_queue_release(second_queue);
    }
    if (queue) {
      vx_queue_release(queue);
    }
    if (device) {
      vx_device_release(device);
    }
  }

  vx_event_h launch(vx_queue_h selected = nullptr) {
    vx_launch_info_t info{};
    info.struct_size = sizeof(info);
    vx_event_h event = nullptr;
    success(vx_enqueue_launch(selected ? selected : queue, &info, 0, nullptr, &event),
            "public launch enqueue failed");
    events_.push_back(event);
    return event;
  }

  vx_event_h write(vx_event_h dependency = nullptr) {
    vx_event_h event = nullptr;
    success(vx_enqueue_dcr_write(queue, 0x123, 0x456, dependency ? 1 : 0,
                                dependency ? &dependency : nullptr, &event),
            "public DCR enqueue failed");
    events_.push_back(event);
    return event;
  }

  void close() {
    for (auto event : events_) {
      success(vx_event_release(event), "public event release failed");
    }
    events_.clear();
    if (second_queue) {
      success(vx_queue_release(second_queue), "second queue release failed");
      second_queue = nullptr;
    }
    success(vx_queue_release(queue), "public queue release failed");
    queue = nullptr;
    success(vx_device_release(device), "public device release failed");
    device = nullptr;
  }

  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_queue_h second_queue = nullptr;

private:
  Controls& controls_;
  std::vector<vx_event_h> events_;
};

void pending(Controls& controls, vx_event_h event, unsigned entered) {
  controls.await(entered);
  uint64_t value = 99;
  success(vx_event_get_value(event, &value), "pending event value query failed");
  expect(value == 0, "pending launch event was signaled");
  expect(vx_event_wait_value(event, 1, 0) == VX_ERR_TIMEOUT,
         "pending launch was not a timeout");
}

void failed_event(vx_event_h event) {
  expect(vx_event_wait_value(event, 1, kTimeout) == VX_ERR_INVALID_VALUE,
         "failed simulation did not reach the public event");
  expect(vx_event_wait_value(event, 1, 0) == VX_ERR_INVALID_VALUE,
         "repeated event wait lost the error");
  expect(vx_event_wait_value(event, 2, 0) == VX_ERR_INVALID_VALUE,
         "higher timeline wait lost the error");
  uint64_t value = 0;
  success(vx_event_get_value(event, &value), "failed event value query failed");
  expect(value == 1, "failed command did not complete the event timeline");
  const uint64_t target = 1;
  expect(vx_event_wait_values(1, &event, &target, 0) == VX_ERR_INVALID_VALUE,
         "multi-event wait lost the error");
}

void successful_context(Controls& controls, bool llc, unsigned launches) {
  controls.arm(0, llc);
  const unsigned destroyed = controls.count(2);
  Context context(controls);
  for (unsigned index = 0; index < launches; ++index) {
    controls.arm(0, llc);
    const unsigned entered = controls.count(0);
    auto event = context.launch();
    pending(controls, event, entered + 1);
    controls.release();
    success(vx_event_wait_value(event, 1, kTimeout), "successful public launch failed");
    success(vx_event_wait_value(event, 1, 0), "successful repeated wait failed");
    auto dcr = context.write(event);
    success(vx_event_wait_value(dcr, 1, kTimeout), "post-launch public DCR failed");
    success(vx_queue_finish(context.queue, kTimeout), "successful queue finish failed");
  }
  context.close();
  expect(controls.count(2) == destroyed + 1, "public cleanup did not destroy processor");
  expect(controls.count(3) == 0, "processor was destroyed with active execution");
}

void failed_context(Controls& controls, bool llc, unsigned outcome) {
  controls.arm(outcome, llc);
  const unsigned destroyed = controls.count(2);
  Context context(controls);
  const unsigned entered = controls.count(0);
  auto event = context.launch();
  pending(controls, event, entered + 1);
  const unsigned writes = controls.count(1);
  auto dependent = context.write(event);
  controls.release();
  failed_event(event);
  failed_event(dependent);
  expect(controls.count(1) == writes, "failed dependency executed its DCR command");
  expect(vx_queue_finish(context.queue, kTimeout) == VX_ERR_INVALID_VALUE,
         "queue finish did not report its asynchronous error");
  success(vx_queue_finish(context.queue, kTimeout), "consumed queue error did not clear");
  failed_event(event);

  auto later = context.write();
  failed_event(later);
  expect(controls.count(1) == writes, "queue error consumption revived backend writes");
  expect(vx_queue_finish(context.queue, kTimeout) == VX_ERR_INVALID_VALUE,
         "new failed command did not poison queue again");
  success(vx_queue_finish(context.queue, kTimeout), "second queue error consumption failed");

  success(vx_queue_create(context.device, nullptr, &context.second_queue),
          "second public queue creation failed");
  auto retry = context.launch(context.second_queue);
  failed_event(retry);
  expect(controls.count(0) == entered + 1, "new queue restarted failed backend");
  expect(vx_queue_finish(context.second_queue, kTimeout) == VX_ERR_INVALID_VALUE,
         "second queue did not report retained backend error");
  context.close();
  expect(controls.count(2) == destroyed + 1, "failed device cleanup leaked processor");
  expect(controls.count(3) == 0, "failed processor destroyed while active");
  successful_context(controls, llc, 1);
}

} // namespace

int main(int argc, char** argv) {
  try {
    expect(argc == 3, "expected case and memory route");
    const char* backend = std::getenv("VORTEX_DRIVER");
    expect(backend && (std::strcmp(backend, "simx") == 0
                      || std::strcmp(backend, "rtlsim") == 0), "unknown backend");
    const bool llc = std::strcmp(argv[2], "llc") == 0;
    expect(llc || std::strcmp(argv[2], "ram") == 0, "unknown memory route");
    Controls controls(backend);
    if (std::strcmp(argv[1], "success") == 0) {
      successful_context(controls, llc, 3);
    } else if (std::strcmp(argv[1], "standard_exception") == 0) {
      failed_context(controls, llc, 1);
    } else if (std::strcmp(argv[1], "unknown_exception") == 0) {
      failed_context(controls, llc, 2);
    } else {
      throw std::runtime_error("unknown public fixture case");
    }
    if (std::strcmp(backend, "simx") == 0) {
      expect(controls.count(4) == controls.count(0), "public runtime omitted checked SimX entry");
      expect(controls.count(5) == 0, "public runtime used legacy gp result");
    }
    std::printf("PASS simulator-public-completion %s checks=%u\n", argv[1], checks);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAIL simulator-public-completion: %s\n", error.what());
    return 1;
  } catch (...) {
    std::fprintf(stderr, "FAIL simulator-public-completion: exception escaped public API\n");
    return 1;
  }
}

#endif
