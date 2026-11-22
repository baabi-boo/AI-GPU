// SPDX-License-Identifier: Apache-2.0
#include "simulator_error_boundary_control.h"

#ifdef ERROR_BOUNDARY_BACKEND

extern "C" void error_boundary_arm(unsigned hook, unsigned outcome) {
  error_boundary_test::outcome.store(outcome);
  error_boundary_test::armed.store(hook);
}

extern "C" unsigned error_boundary_count(bool faults) {
  return faults ? error_boundary_test::faults.load()
                : error_boundary_test::operations.load();
}

#else

#include <vortex2.h>

#include <dlfcn.h>
#include <cstdio>
#include <stdexcept>
#include <string>

namespace {

constexpr uint64_t kWait = 2ull * 1000 * 1000 * 1000;
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

void failed(vx_event_h event) {
  expect(vx_event_wait_value(event, 1, kWait) == VX_ERR_INVALID_VALUE,
         "processor failure did not retain terminal public classification");
  expect(vx_event_wait_value(event, 1, 0) == VX_ERR_INVALID_VALUE,
         "repeated wait lost processor failure");
  uint64_t value = 0;
  success(vx_event_get_value(event, &value), "failed event query failed");
  expect(value == 1, "processor failure did not finish the event timeline");
}

void check_fault(unsigned hook, unsigned outcome) {
  const char* backend = std::getenv("VORTEX_DRIVER");
  expect(backend != nullptr, "backend not selected");
  const std::string library_name = std::string("libvortex-") + backend + ".so";
  void* library = dlopen(library_name.c_str(), RTLD_NOW | RTLD_LOCAL);
  expect(library != nullptr, "controlled backend not loaded");
  auto arm = reinterpret_cast<void (*)(unsigned, unsigned)>(dlsym(library, "error_boundary_arm"));
  auto count = reinterpret_cast<unsigned (*)(bool)>(dlsym(library, "error_boundary_count"));
  expect(arm && count, "fault controls not exported");
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_buffer_h buffer = nullptr;
  success(vx_device_open(0, &device), "device open failed");
  success(vx_queue_create(device, nullptr, &queue), "queue create failed");
  success(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &buffer), "buffer create failed");
  uint32_t source = 0x1234abcd, output = 0;
  success(vx_enqueue_write(queue, buffer, 0, &source, sizeof(source), 0, nullptr, nullptr),
          "seed write enqueue failed");
  success(vx_queue_finish(queue, kWait), "seed write failed");
  vx_launch_info_t launch{};
  launch.struct_size = sizeof(launch);
  if (hook == error_boundary_test::drain) {
    // A successful launch dirties the non-LLC route; its next DMA must drain.
    success(vx_enqueue_launch(queue, &launch, 0, nullptr, nullptr), "pre-drain launch failed");
    success(vx_queue_finish(queue, kWait), "pre-drain launch did not complete");
  }
  expect(count(true) == 0, "a fault occurred before arming");
  arm(hook, outcome);
  vx_event_h event = nullptr, dependent = nullptr, later = nullptr;
  switch (hook) {
  case error_boundary_test::run:
    success(vx_enqueue_launch(queue, &launch, 0, nullptr, &event), "launch enqueue failed");
    break;
  case error_boundary_test::dcr_read:
    success(vx_enqueue_dcr_read(queue, 0x123, &output, 0, nullptr, &event), "DCR read enqueue failed");
    break;
  case error_boundary_test::dcr_write:
    success(vx_enqueue_dcr_write(queue, 0x123, 0x456, 0, nullptr, &event), "DCR write enqueue failed");
    break;
  case error_boundary_test::memory_read:
  case error_boundary_test::drain:
    success(vx_enqueue_read(queue, &output, buffer, 0, sizeof(output), 0, nullptr, &event),
            "read enqueue failed");
    break;
  case error_boundary_test::memory_write:
    success(vx_enqueue_write(queue, buffer, 0, &source, sizeof(source), 0, nullptr, &event),
            "write enqueue failed");
    break;
  default:
    throw std::runtime_error("unknown model hook");
  }
  success(vx_enqueue_dcr_write(queue, 0x123, 0x456, 1, &event, &dependent),
          "dependent enqueue failed");
  failed(event);
  failed(dependent);
  expect(count(true) == 1, "targeted model hook did not throw exactly once");
  const unsigned operations = count(false);
  expect(vx_queue_finish(queue, kWait) == VX_ERR_INVALID_VALUE, "queue lost processor failure");
  success(vx_queue_finish(queue, kWait), "queue-local error was not consumed");
  success(vx_enqueue_dcr_write(queue, 0x123, 0x456, 0, nullptr, &later), "later enqueue failed");
  failed(later);
  expect(count(false) == operations, "consuming queue error resumed the failed processor");
  expect(vx_queue_finish(queue, kWait) == VX_ERR_INVALID_VALUE, "later queue failure was lost");
  success(vx_queue_finish(queue, kWait), "later queue-local error was not consumed");
  success(vx_event_release(event), "failed event release failed");
  success(vx_event_release(dependent), "dependent event release failed");
  success(vx_event_release(later), "later event release failed");
  success(vx_buffer_release(buffer), "buffer release failed");
  success(vx_queue_release(queue), "queue release failed");
  success(vx_device_release(device), "device release failed");
  expect(count(false) == operations, "cleanup resumed the failed processor");
  expect(dlclose(library) == 0, "fixture unload failed");
}

} // namespace

int main(int argc, char** argv) {
  try {
    expect(argc == 3, "expected hook and exception kind");
    const unsigned hook = static_cast<unsigned>(std::strtoul(argv[1], nullptr, 10));
    const unsigned outcome = static_cast<unsigned>(std::strtoul(argv[2], nullptr, 10));
    expect(hook >= error_boundary_test::run && hook <= error_boundary_test::drain,
           "invalid model hook");
    expect(outcome < 2, "invalid exception kind");
    check_fault(hook, outcome);
    std::printf("PASS simulator-error-boundary hook=%u outcome=%u checks=%u\n", hook, outcome, checks);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAIL simulator-error-boundary: %s\n", error.what());
    return 1;
  } catch (...) {
    std::fprintf(stderr, "FAIL simulator-error-boundary: exception escaped public API\n");
    return 1;
  }
}

#endif
