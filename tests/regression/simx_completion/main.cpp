// SPDX-License-Identifier: Apache-2.0
#include <vortex2.h>
#include "common.h"

#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>

namespace {

constexpr uint64_t kWaitNanoseconds = 30ull * 1000 * 1000 * 1000;

void check(vx_result_t result, const char* operation) {
  if (result != VX_SUCCESS) {
    throw std::runtime_error(std::string(operation) + ": " + vx_result_string(result));
  }
}

void expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

struct Event {
  vx_event_h value = nullptr;
  ~Event() {
    if (value) {
      vx_event_release(value);
    }
  }
  void close() {
    check(vx_event_release(value), "event release");
    value = nullptr;
  }
};

struct Context {
  vx_device_h device = nullptr;
  vx_queue_h queue = nullptr;
  vx_module_h module = nullptr;
  vx_kernel_h kernel = nullptr;
  vx_buffer_h output = nullptr;
  CompletionOutput actual{};

  ~Context() {
    if (queue) {
      vx_queue_finish(queue, kWaitNanoseconds);
    }
    if (output) {
      vx_buffer_release(output);
    }
    if (kernel) {
      vx_kernel_release(kernel);
    }
    if (module) {
      vx_module_release(module);
    }
    if (queue) {
      vx_queue_release(queue);
    }
    if (device) {
      vx_device_release(device);
    }
  }

  void close() {
    check(vx_queue_finish(queue, kWaitNanoseconds), "queue finish");
    check(vx_buffer_release(output), "output release");
    output = nullptr;
    check(vx_kernel_release(kernel), "kernel release");
    kernel = nullptr;
    check(vx_module_release(module), "module release");
    module = nullptr;
    check(vx_queue_release(queue), "queue release");
    queue = nullptr;
    check(vx_device_release(device), "device release");
    device = nullptr;
  }
};

void run_context(const char* path, uint32_t context_index) {
  Context context;
  check(vx_device_open(0, &context.device), "device open");
  vx_queue_info_t queue_info{};
  queue_info.struct_size = sizeof(queue_info);
  queue_info.priority = VX_QUEUE_PRIORITY_NORMAL;
  check(vx_queue_create(context.device, &queue_info, &context.queue), "queue create");
  check(vx_module_load_file(context.device, path, &context.module), "module load");
  check(vx_module_get_kernel(context.module, "main", &context.kernel), "kernel lookup");
  check(vx_buffer_create(context.device, sizeof(CompletionOutput), VX_MEM_READ_WRITE,
                         &context.output), "output create");

  CompletionArgs args{};
  check(vx_buffer_address(context.output, &args.output_address), "output address");
  vx_launch_info_t launch_info{};
  launch_info.struct_size = sizeof(launch_info);
  launch_info.kernel = context.kernel;
  launch_info.args_host = &args;
  launch_info.args_size = sizeof(args);
  launch_info.ndim = 1;
  launch_info.grid_dim[0] = 1;
  launch_info.block_dim[0] = 1;

  for (uint32_t index = 0; index < 3; ++index) {
    args.input = 0x2468ace0u + 17u * index + context_index;
    args.sequence = context_index * 3 + index;
    auto& actual = context.actual;
    std::memset(&actual, 0xa5, sizeof(actual));
    Event poison;
    check(vx_enqueue_write(context.queue, context.output, 0, &actual, sizeof(actual),
                            0, nullptr, &poison.value), "poison enqueue");
    check(vx_event_wait_value(poison.value, 1, kWaitNanoseconds), "poison wait");
    poison.close();

    Event launch;
    check(vx_enqueue_launch(context.queue, &launch_info, 0, nullptr, &launch.value),
          "launch enqueue");
    check(vx_event_wait_value(launch.value, 1, kWaitNanoseconds), "launch wait");
    check(vx_event_wait_value(launch.value, 1, 0), "completed launch wait");
    Event read;
    check(vx_enqueue_read(context.queue, &actual, context.output, 0, sizeof(actual),
                           1, &launch.value, &read.value), "read enqueue");
    check(vx_event_wait_value(read.value, 1, kWaitNanoseconds), "read wait");

    expect(static_cast<uint32_t>(actual.global_pointer) != 0,
           "kernel did not retain a nonzero low global-pointer word");
    expect(actual.global_value == kCompletionGlobal, "global data mismatch");
    expect(actual.value == (kCompletionGlobal ^ args.input), "kernel result mismatch");
    expect(actual.sequence == args.sequence && actual.reserved == 0,
           "output sequence or completion mismatch");
    std::printf("native_success context=%u launch=%u gp=%016" PRIx64 " value=%08" PRIx32 "\n",
                context_index, index, actual.global_pointer, actual.value);
    read.close();
    launch.close();
  }
  context.close();
}

} // namespace

int main(int argc, char** argv) {
  const char* path = "kernel.vxbin";
  if (argc == 3 && std::strcmp(argv[1], "-k") == 0) {
    path = argv[2];
  } else if (argc != 1) {
    std::fprintf(stderr, "Usage: simx_completion [-k kernel.vxbin]\n");
    return 2;
  }
  const char* driver = std::getenv("VORTEX_DRIVER");
  if (!driver || std::strcmp(driver, "simx") != 0) {
    std::fprintf(stderr, "simx_completion requires VORTEX_DRIVER=simx\n");
    return 2;
  }
  try {
    for (uint32_t index = 0; index < 2; ++index) {
      run_context(path, index);
    }
    std::printf("PASSED simx_completion native_success contexts=2 launches=6 gp_nonzero=6\n");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED simx_completion: %s\n", error.what());
    return 1;
  }
}
