// SPDX-License-Identifier: Apache-2.0

#include "vortex2_internal.h"

#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <limits>

namespace {
thread_local int fail_allocation_after = -1;
thread_local unsigned injected_allocation_failures = 0;
thread_local std::size_t arm_failure_at_size = 0;
thread_local int armed_failure_budget = -1;
thread_local bool allocation_caller = false;
std::atomic<int> fail_background_allocation_after{-1};
std::atomic<unsigned> background_allocation_failures{0};
}

void* operator new(std::size_t size) {
  if (arm_failure_at_size != 0 && size == arm_failure_at_size) {
    arm_failure_at_size = 0;
    fail_allocation_after = armed_failure_budget;
  }
  if (!allocation_caller) {
    int budget = fail_background_allocation_after.load();
    while (budget >= 0) {
      if (fail_background_allocation_after.compare_exchange_weak(budget, budget - 1)) {
        if (budget == 0) {
          ++background_allocation_failures;
          throw std::bad_alloc();
        }
        break;
      }
    }
  }
  if (fail_allocation_after == 0) {
    ++injected_allocation_failures;
    throw std::bad_alloc();
  }
  if (fail_allocation_after > 0) {
    --fail_allocation_after;
  }
  if (void* result = std::malloc(size ? size : 1)) {
    return result;
  }
  throw std::bad_alloc();
}
void* operator new[](std::size_t size) { return ::operator new(size); }
void operator delete(void* ptr) noexcept { std::free(ptr); }
void operator delete[](void* ptr) noexcept { std::free(ptr); }
void operator delete(void* ptr, std::size_t) noexcept { std::free(ptr); }
void operator delete[](void* ptr, std::size_t) noexcept { std::free(ptr); }

#define EXPECT(expr) do { \
  if (!(expr)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); \
    return 1; \
  } \
} while (0)
#define CHECK(expr) EXPECT((expr) == VX_SUCCESS)

namespace {

constexpr uint64_t kWait = 30ull * 1000 * 1000 * 1000;

int test_bounds(vx_device_h device) {
  vx_queue_h queue = nullptr;
  vx_buffer_h a = nullptr, b = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &a));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &b));
  uint32_t word = 0;
  constexpr uint64_t offset = std::numeric_limits<uint64_t>::max() - 7;
  EXPECT(vx_enqueue_write(queue, a, offset, &word, 16, 0, nullptr, nullptr) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_enqueue_read(queue, &word, a, offset, 16, 0, nullptr, nullptr) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_enqueue_copy(queue, a, offset, b, 0, 16, 0, nullptr, nullptr) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_enqueue_copy(queue, a, 0, b, offset, 16, 0, nullptr, nullptr) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_enqueue_fill_buffer(queue, a, offset, 16, &word, sizeof(word), 0, nullptr, nullptr) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_buffer_access(a, offset, 16, VX_MEM_READ) == VX_ERR_INVALID_VALUE);
  void* mapped = nullptr;
  EXPECT(vx_buffer_map(a, offset, 16, VX_MEM_READ, &mapped) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_enqueue_map(queue, a, offset, 16, VX_MEM_READ, 0, nullptr, nullptr, &mapped) == VX_ERR_INVALID_VALUE);
  EXPECT(mapped == nullptr);
  CHECK(vx_buffer_access(a, 64, 0, VX_MEM_READ));
  EXPECT(vx_buffer_access(a, 65, 0, VX_MEM_READ) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_buffer_access(a, 60, 8, VX_MEM_READ) == VX_ERR_INVALID_VALUE);
  CHECK(vx_queue_finish(queue, kWait));
  CHECK(vx_buffer_release(a));
  CHECK(vx_buffer_release(b));
  CHECK(vx_queue_release(queue));
  std::puts("[OK] overflowing and boundary buffer spans");
  return 0;
}

int test_invalid_waits(vx_device_h device) {
  vx_queue_h queue = nullptr;
  vx_buffer_h buffer = nullptr;
  vx_event_h gate = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &buffer));
  CHECK(vx_event_create(device, &gate));
  vx_event_h waits[] = {gate, nullptr};
  vx_event_h result = gate;
  uint32_t word = 9;
  EXPECT(vx_enqueue_write(queue, buffer, 0, &word, sizeof(word), 2, waits, &result) == VX_ERR_INVALID_HANDLE);
  EXPECT(result == gate);
  EXPECT(vx::to_buffer(buffer)->refs() == 1);
  EXPECT(vx::to_event(gate)->refs() == 1);
  EXPECT(vx_enqueue_signal(queue, gate, 1, 2, waits, nullptr) == VX_ERR_INVALID_HANDLE);
  EXPECT(vx_enqueue_wait_value(queue, gate, 1, 2, waits, nullptr) == VX_ERR_INVALID_HANDLE);
  EXPECT(vx::to_event(gate)->refs() == 1);
  void* mapped = nullptr;
  EXPECT(vx_enqueue_map(queue, buffer, 0, 64, VX_MEM_READ, 2, waits, nullptr, &mapped) == VX_ERR_INVALID_HANDLE);
  EXPECT(mapped == nullptr);
  CHECK(vx_buffer_map(buffer, 0, 64, VX_MEM_WRITE, &mapped));
  std::memset(mapped, 0, 64);
  CHECK(vx_buffer_unmap(buffer, mapped));
  CHECK(vx_event_release(gate));
  CHECK(vx_buffer_release(buffer));
  CHECK(vx_queue_release(queue));
  std::puts("[OK] rejected wait lists preserve ownership and outputs");
  return 0;
}

int test_timeout(vx_device_h device) {
  vx_queue_h queue = nullptr;
  vx_buffer_h buffer = nullptr;
  vx_event_h gate = nullptr, done = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  uint64_t free_before = 0, used_before = 0;
  CHECK(vx_device_memory_info(device, &free_before, &used_before));
  CHECK(vx_buffer_create(device, 4096, VX_MEM_READ_WRITE, &buffer));
  CHECK(vx_event_create(device, &gate));
  std::array<uint32_t, 16> source{};
  source.fill(0x1234abcd);
  CHECK(vx_enqueue_write(queue, buffer, 0, source.data(), sizeof(source), 1, &gate, &done));
  EXPECT(vx_event_wait_value(done, 1, 0) == VX_ERR_TIMEOUT);
  EXPECT(vx::to_buffer(buffer)->refs() == 2);
  CHECK(vx_buffer_release(buffer));
  uint64_t free_pending = 0, used_pending = 0;
  CHECK(vx_device_memory_info(device, &free_pending, &used_pending));
  EXPECT(used_pending > used_before);
  CHECK(vx_event_signal(gate, 1));
  CHECK(vx_event_wait_value(done, 1, kWait));
  CHECK(vx_queue_finish(queue, kWait));
  uint64_t free_after = 0, used_after = 0;
  CHECK(vx_device_memory_info(device, &free_after, &used_after));
  EXPECT(used_after == used_before && free_after == free_before);
  CHECK(vx_event_release(done));
  CHECK(vx_event_release(gate));
  CHECK(vx_queue_release(queue));
  std::puts("[OK] timeout retains pending allocation until completion");
  return 0;
}

int test_skipped_commands(vx_device_h device) {
  vx_queue_h queue = nullptr;
  vx_buffer_h a = nullptr, b = nullptr;
  vx_event_h failed = nullptr, target = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &a));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &b));
  CHECK(vx_event_create(device, &failed));
  CHECK(vx_event_create(device, &target));
  vx::to_event(failed)->complete(VX_ERR_EVENT_FAILED);

  // This inert image is retained by skipped launches and must never execute.
  const std::array<uint64_t, 2> image{{0x80000000, 0x80000040}};
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  CHECK(vx_module_load_bytes(device, image.data(), sizeof(image), &module));
  CHECK(vx_module_get_kernel(module, "main", &kernel));
  std::array<uint32_t, 16> source{}, output{};
  source.fill(0xabcdef12);
  output.fill(0x76543210);
  vx_rect_info_t rect{};
  rect.struct_size = sizeof(rect);
  rect.region[0] = 64;
  rect.region[1] = rect.region[2] = 1;
  vx_launch_info_t launch{};
  launch.struct_size = sizeof(launch);
  launch.kernel = kernel;
  launch.ndim = 1;
  launch.grid_dim[0] = launch.block_dim[0] = 1;
  vx_command_t command{};
  command.type = VX_COMMAND_LAUNCH;
  command.data.launch = &launch;

  std::array<vx_event_h, 14> events{};
  CHECK(vx_enqueue_write(queue, a, 0, source.data(), sizeof(source), 1, &failed, &events[0]));
  CHECK(vx_enqueue_read(queue, output.data(), a, 0, sizeof(output), 0, nullptr, &events[1]));
  CHECK(vx_enqueue_copy(queue, b, 0, a, 0, 64, 0, nullptr, &events[2]));
  CHECK(vx_enqueue_fill_buffer(queue, a, 0, 64, source.data(), 4, 0, nullptr, &events[3]));
  CHECK(vx_enqueue_write_rect(queue, a, source.data(), &rect, 0, nullptr, &events[4]));
  CHECK(vx_enqueue_read_rect(queue, output.data(), a, &rect, 0, nullptr, &events[5]));
  CHECK(vx_enqueue_copy_rect(queue, b, a, &rect, 0, nullptr, &events[6]));
  void* mapped = nullptr;
  CHECK(vx_enqueue_map(queue, a, 0, 64, VX_MEM_READ, 0, nullptr, &events[7], &mapped));
  CHECK(vx_enqueue_unmap(queue, a, mapped, 0, nullptr, &events[8]));
  CHECK(vx_enqueue_signal(queue, target, 1, 0, nullptr, &events[9]));
  CHECK(vx_enqueue_wait_value(queue, target, 1, 0, nullptr, &events[10]));
  CHECK(vx_enqueue_launch(queue, &launch, 0, nullptr, &events[11]));
  CHECK(vx_enqueue_commands(queue, &command, 1, 0, nullptr, &events[12]));
  CHECK(vx_enqueue_draw(queue, &command, 1, 0, nullptr, &events[13]));
  for (auto event : events) {
    EXPECT(vx_event_wait_value(event, 1, kWait) == VX_ERR_EVENT_FAILED);
    CHECK(vx_event_release(event));
  }
  EXPECT(vx_queue_finish(queue, kWait) == VX_ERR_EVENT_FAILED);
  EXPECT(vx::to_buffer(a)->refs() == 1 && vx::to_buffer(b)->refs() == 1);
  EXPECT(vx::to_kernel(kernel)->refs() == 1);
  EXPECT(vx::to_module(module)->refs() == 2);
  EXPECT(vx::to_event(failed)->refs() == 1 && vx::to_event(target)->refs() == 1);
  EXPECT(vx::to_event(target)->get_value() == 0);
  for (auto word : output) {
    EXPECT(word == 0x76543210);
  }
  CHECK(vx_buffer_map(a, 0, 64, VX_MEM_WRITE, &mapped));
  std::memset(mapped, 0, 64);
  CHECK(vx_buffer_unmap(a, mapped));
  CHECK(vx_queue_finish(queue, kWait));
  CHECK(vx_kernel_release(kernel));
  CHECK(vx_module_release(module));
  CHECK(vx_event_release(target));
  CHECK(vx_event_release(failed));
  CHECK(vx_buffer_release(a));
  CHECK(vx_buffer_release(b));
  CHECK(vx_queue_release(queue));
  std::puts("[OK] 14 failed-dependency/sticky commands release captures before completion");
  return 0;
}

int test_transfer_failure(vx_device_h device) {
  vx_queue_h queue = nullptr;
  vx_buffer_h buffer = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &buffer));
  vx_event_h failed = nullptr, skipped = nullptr;
  CHECK(vx_enqueue_unmap(queue, buffer, nullptr, 0, nullptr, &failed));
  uint32_t word = 0;
  CHECK(vx_enqueue_write(queue, buffer, 0, &word, sizeof(word), 1, &failed, &skipped));
  EXPECT(vx_event_wait_value(failed, 1, kWait) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_event_wait_value(skipped, 1, kWait) == VX_ERR_INVALID_VALUE);
  EXPECT(vx_queue_finish(queue, kWait) == VX_ERR_INVALID_VALUE);
  EXPECT(vx::to_buffer(buffer)->refs() == 1);
  CHECK(vx_event_release(failed));
  CHECK(vx_event_release(skipped));
  CHECK(vx_enqueue_write(queue, buffer, 0, &word, sizeof(word), 0, nullptr, nullptr));
  CHECK(vx_queue_finish(queue, kWait));
  CHECK(vx_buffer_release(buffer));
  CHECK(vx_queue_release(queue));
  std::puts("[OK] failed unmap propagates error and finish restores queue");
  return 0;
}

int test_host_exhaustion(vx_device_h device) {
  vx_queue_h queue = nullptr;
  vx_buffer_h buffer = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  CHECK(vx_buffer_create(device, 64, VX_MEM_READ_WRITE, &buffer));
  unsigned failures = 0, successes = 0;
  for (int budget = 0; budget != 16; ++budget) {
    vx_event_h gate = nullptr, done = nullptr;
    CHECK(vx_event_create(device, &gate));
    uint32_t word = 0x98765432;
    fail_allocation_after = budget;
    auto result = vx_enqueue_write(queue, buffer, 0, &word, sizeof(word), 1, &gate, &done);
    fail_allocation_after = -1;
    if (result == VX_ERR_OUT_OF_HOST_MEMORY) {
      ++failures;
      EXPECT(done == nullptr);
      EXPECT(vx::to_event(gate)->refs() == 1);
      EXPECT(vx::to_buffer(buffer)->refs() == 1);
    } else {
      EXPECT(result == VX_SUCCESS);
      ++successes;
      CHECK(vx_event_signal(gate, 1));
      CHECK(vx_event_wait_value(done, 1, kWait));
      CHECK(vx_event_release(done));
    }
    CHECK(vx_queue_finish(queue, kWait));
    CHECK(vx_event_release(gate));
    EXPECT(vx::to_buffer(buffer)->refs() == 1);
  }
  EXPECT(failures >= 3 && successes > 0);
  CHECK(vx_buffer_release(buffer));
  CHECK(vx_queue_release(queue));
  std::printf("[OK] host-allocation unwind: %u failures, %u successful enqueues\n", failures, successes);
  return 0;
}

int test_module_exhaustion(vx_device_h device) {
  auto* internal = vx::to_device(device);
  const auto refs_before = internal->refs();
  uint64_t free_before = 0, used_before = 0;
  CHECK(vx_device_memory_info(device, &free_before, &used_before));

  // Fail the BSS temporary after the real image reservation has succeeded.
  // Its odd size distinguishes this allocation from runtime bookkeeping.
  constexpr std::size_t bss_size = 65537;
  const std::array<uint64_t, 2> bss_image{{0x80000000, 0x80000000 + bss_size}};
  vx_module_h module = nullptr;
  unsigned faults_before = injected_allocation_failures;
  arm_failure_at_size = bss_size;
  armed_failure_budget = 0;
  auto result = vx_module_load_bytes(device, bss_image.data(), sizeof(bss_image), &module);
  const bool bss_armed = arm_failure_at_size == 0;
  arm_failure_at_size = 0;
  fail_allocation_after = -1;
  EXPECT(bss_armed && injected_allocation_failures == faults_before + 1);
  EXPECT(result == VX_ERR_OUT_OF_HOST_MEMORY && module == nullptr);
  EXPECT(internal->refs() == refs_before);
  uint64_t free_after = 0, used_after = 0;
  CHECK(vx_device_memory_info(device, &free_after, &used_after));
  EXPECT(free_after == free_before && used_after == used_before);

  // A single long-name symbol exercises Module allocation, string storage,
  // the first symbol vector, and the automatically added public main alias.
  alignas(uint64_t) std::array<uint8_t, 172> symbol_image{};
  const std::array<uint64_t, 2> image_header{{0x80000000, 0x80000040}};
  std::memcpy(symbol_image.data(), image_header.data(), sizeof(image_header));
  std::memset(symbol_image.data() + 80, 'k', 64);
  const uint16_t name_length = 64;
  std::memcpy(symbol_image.data() + 148, &name_length, sizeof(name_length));
  std::memcpy(symbol_image.data() + 152, image_header.data(), sizeof(uint64_t));
  const uint32_t symbol_count = 1;
  std::memcpy(symbol_image.data() + 160, &symbol_count, sizeof(symbol_count));
  std::memcpy(symbol_image.data() + 164, "VXSYMTAB", 8);
  unsigned failures = 0, successes = 0;
  for (int budget = 0; budget != 6; ++budget) {
    module = nullptr;
    faults_before = injected_allocation_failures;
    arm_failure_at_size = sizeof(vx::Module);
    armed_failure_budget = budget;
    result = vx_module_load_bytes(device, symbol_image.data(), symbol_image.size(), &module);
    const bool module_armed = arm_failure_at_size == 0;
    arm_failure_at_size = 0;
    fail_allocation_after = -1;
    EXPECT(module_armed);
    if (result == VX_ERR_OUT_OF_HOST_MEMORY) {
      ++failures;
      EXPECT(injected_allocation_failures == faults_before + 1);
      EXPECT(module == nullptr);
    } else {
      EXPECT(result == VX_SUCCESS);
      ++successes;
      CHECK(vx_module_release(module));
    }
    EXPECT(internal->refs() == refs_before);
    CHECK(vx_device_memory_info(device, &free_after, &used_after));
    EXPECT(free_after == free_before && used_after == used_before);
  }
  EXPECT(failures >= 4 && successes > 0);

  // The cache insertion follows Kernel construction and its Module retain.
  // Failing either allocation must leave no raw kernel or retained module.
  const std::array<uint64_t, 2> image{{0x80000000, 0x80000040}};
  CHECK(vx_module_load_bytes(device, image.data(), sizeof(image), &module));
  unsigned kernel_failures = 0, kernel_successes = 0;
  for (int budget = 0; budget != 5; ++budget) {
    vx_kernel_h kernel = nullptr;
    fail_allocation_after = budget;
    result = vx_module_get_kernel(module, "main", &kernel);
    fail_allocation_after = -1;
    if (result == VX_ERR_OUT_OF_HOST_MEMORY) {
      ++kernel_failures;
      EXPECT(kernel == nullptr);
    } else {
      EXPECT(result == VX_SUCCESS);
      ++kernel_successes;
      CHECK(vx_kernel_release(kernel));
    }
    EXPECT(vx::to_module(module)->refs() == 1);
    CHECK(vx_module_get_kernel(module, "main", &kernel));
    CHECK(vx_kernel_release(kernel));
    EXPECT(vx::to_module(module)->refs() == 1);
  }
  EXPECT(kernel_failures >= 2 && kernel_successes > 0);
  CHECK(vx_module_release(module));
  EXPECT(internal->refs() == refs_before);
  CHECK(vx_device_memory_info(device, &free_after, &used_after));
  EXPECT(free_after == free_before && used_after == used_before);
  std::printf("[OK] module setup OOM: BSS, %u symbol failures, %u kernel failures; all references and memory restored\n",
        failures, kernel_failures);
  return 0;
}

int test_transfer_allocation_failure(vx_device_h device, int budget) {
  vx_queue_h queue = nullptr;
  vx_buffer_h buffer = nullptr;
  vx_event_h gate = nullptr, failed = nullptr, skipped = nullptr;
  uint64_t free_before = 0, used_before = 0;
  CHECK(vx_device_memory_info(device, &free_before, &used_before));
  CHECK(vx_queue_create(device, nullptr, &queue));
  CHECK(vx_buffer_create(device, 4096, VX_MEM_READ_WRITE, &buffer));
  CHECK(vx_event_create(device, &gate));
  std::array<uint32_t, 1024> source{}, output{};
  source.fill(0x7abc0123);
  output.fill(0x1234fedc);
  CHECK(vx_enqueue_write(queue, buffer, 0, output.data(), sizeof(output), 0, nullptr, nullptr));
  CHECK(vx_queue_finish(queue, kWait));
  CHECK(vx_enqueue_write(queue, buffer, 0, source.data(), sizeof(source), 1, &gate, &failed));
  CHECK(vx_enqueue_read(queue, output.data(), buffer, 0, sizeof(output), 1, &failed, &skipped));
  const unsigned faults_before = background_allocation_failures.load();
  // SimX and processor RTL first register the host staging region in the
  // backend, then in Device::host_alloc, then allocate the software CP's
  // copy scratch. Fail each stage, including after descriptor publication.
  fail_background_allocation_after.store(budget);
  CHECK(vx_event_signal(gate, 1));
  const auto result = vx_event_wait_value(failed, 1, kWait);
  fail_background_allocation_after.store(-1);
  EXPECT(background_allocation_failures.load() == faults_before + 1);
  EXPECT(result == VX_ERR_OUT_OF_HOST_MEMORY);
  EXPECT(vx_event_wait_value(skipped, 1, kWait) == VX_ERR_OUT_OF_HOST_MEMORY);
  EXPECT(vx_queue_finish(queue, kWait) == VX_ERR_OUT_OF_HOST_MEMORY);
  EXPECT(vx::to_buffer(buffer)->refs() == 1);
  for (auto word : output) {
    EXPECT(word == 0x1234fedc);
  }
  CHECK(vx_event_release(failed));
  CHECK(vx_event_release(skipped));
  CHECK(vx_event_release(gate));
  // A failed transfer must not be replayed by the next CP transaction.
  // Inspect the seeded destination before recovery can overwrite evidence.
  CHECK(vx_enqueue_read(queue, output.data(), buffer, 0, sizeof(output), 0, nullptr, &failed));
  CHECK(vx_event_wait_value(failed, 1, kWait));
  for (auto word : output) {
    EXPECT(word == 0x1234fedc);
  }
  CHECK(vx_event_release(failed));
  CHECK(vx_enqueue_write(queue, buffer, 0, source.data(), sizeof(source), 0, nullptr, &failed));
  CHECK(vx_enqueue_read(queue, output.data(), buffer, 0, sizeof(output), 1, &failed, &skipped));
  CHECK(vx_event_wait_value(skipped, 1, kWait));
  EXPECT(output == source);
  CHECK(vx_queue_finish(queue, kWait));
  CHECK(vx_event_release(failed));
  CHECK(vx_event_release(skipped));
  CHECK(vx_buffer_release(buffer));
  CHECK(vx_queue_release(queue));
  uint64_t free_after = 0, used_after = 0;
  CHECK(vx_device_memory_info(device, &free_after, &used_after));
  EXPECT(free_after == free_before && used_after == used_before);
  std::printf("[OK] real DMA allocation stage %d OOM propagates, releases captures, and recovers\n", budget);
  return 0;
}

int test_repeated_cleanup(vx_device_h device) {
  vx_queue_h queue = nullptr;
  CHECK(vx_queue_create(device, nullptr, &queue));
  uint64_t free_before = 0, used_before = 0;
  CHECK(vx_device_memory_info(device, &free_before, &used_before));
  EXPECT(free_before <= std::numeric_limits<uint64_t>::max() - 4096);
  vx_buffer_h oversized = nullptr;
  EXPECT(vx_buffer_create(device, free_before + 4096, VX_MEM_READ_WRITE, &oversized) == VX_ERR_OUT_OF_DEVICE_MEMORY);
  EXPECT(oversized == nullptr);
  for (uint32_t i = 0; i != 32; ++i) {
    vx_buffer_h buffer = nullptr;
    CHECK(vx_buffer_create(device, 4096, VX_MEM_READ_WRITE, &buffer));
    const uint32_t source = 0x11220000 | i;
    uint32_t output = 0;
    vx_event_h written = nullptr, read = nullptr;
    CHECK(vx_enqueue_write(queue, buffer, 0, &source, sizeof(source), 0, nullptr, &written));
    CHECK(vx_enqueue_read(queue, &output, buffer, 0, sizeof(output), 1, &written, &read));
    CHECK(vx_buffer_release(buffer));
    CHECK(vx_event_release(written));
    CHECK(vx_event_wait_value(read, 1, kWait));
    EXPECT(output == source);
    CHECK(vx_event_release(read));
    CHECK(vx_queue_finish(queue, kWait));
    uint64_t free_after = 0, used_after = 0;
    CHECK(vx_device_memory_info(device, &free_after, &used_after));
    EXPECT(free_after == free_before && used_after == used_before);
  }
  CHECK(vx_queue_release(queue));
  std::puts("[OK] allocation exhaustion and 32 transfer/release cycles restore memory");
  return 0;
}

int test_scratch_cleanup(vx_device_h device) {
  auto* internal = vx::to_device(device);
  uint64_t free_before = 0, used_before = 0;
  CHECK(vx_device_memory_info(device, &free_before, &used_before));
  std::array<uint64_t, 128> slots{};
  for (auto& slot : slots) {
    bool pooled = false;
    CHECK(internal->args_slot_acquire(1, &slot, &pooled));
    EXPECT(pooled);
  }
  const unsigned faults_before = injected_allocation_failures;
  fail_allocation_after = 0;
  for (auto slot : slots) {
    internal->args_slot_release(slot, true);
  }
  fail_allocation_after = -1;
  EXPECT(injected_allocation_failures > faults_before);
  uint64_t free_after = 0, used_after = 0;
  CHECK(vx_device_memory_info(device, &free_after, &used_after));
  EXPECT(free_before == free_after && used_before == used_after);
  std::printf("[OK] scratch-pool OOM frees %u uncached slots\n",
        injected_allocation_failures - faults_before);
  return 0;
}

} // namespace

int main() {
  allocation_caller = true;
  vx_device_h device = nullptr;
  CHECK(vx_device_open(0, &device));
  if (test_bounds(device) || test_invalid_waits(device) || test_timeout(device)
    || test_skipped_commands(device) || test_transfer_failure(device)
    || test_host_exhaustion(device) || test_module_exhaustion(device)
    || test_transfer_allocation_failure(device, 0)
    || test_transfer_allocation_failure(device, 1)
    || test_transfer_allocation_failure(device, 2) || test_scratch_cleanup(device)
    || test_repeated_cleanup(device)) {
    return 1;
  }
  EXPECT(vx::to_device(device)->refs() == 1);
  CHECK(vx_device_release(device));
  std::puts("P03_LIFECYCLE PASSED");
  return 0;
}
