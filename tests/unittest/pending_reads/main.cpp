// SPDX-License-Identifier: Apache-2.0
#include "core.h"
#include "mem.h"
#include "processor.h"
#include "VX_types.h"

#include <array>
#include <cinttypes>
#include <cstdio>
#include <link.h>
#include <stdexcept>
#include <string>
#include <utility>

#if !defined(SIMX_CHECKED_COUNTERS) || (SIMX_CHECKED_COUNTERS + 0) != 1
#error "Pending-read probe requires checked model counters"
#endif
#ifdef SIMX_FUNCTIONAL
#error "Pending-read probe requires the timing simulator"
#endif
static_assert(VX_CFG_XLEN == 64);
static_assert(vortex::SIMX_NUM_WORKERS == 1);
static_assert(VX_CFG_CP_ON_LLC == 0);

namespace {

constexpr uint64_t kCapacity = 4096;
constexpr uint64_t kProgramAddress = 256;
constexpr uint64_t kMaxSteps = 200000;
constexpr const char* kLibraries[] = {"libsimx.so", "libramulator.so", "libramulator-vortex.so"};

void expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

struct ModelState {
  uint64_t ticks;
  uint64_t resets;
  uint64_t cycles;
  uint64_t instructions;
  int gp;
  bool running;
  bool idle;

  bool operator==(const ModelState& other) const {
    return ticks == other.ticks && resets == other.resets && cycles == other.cycles
        && instructions == other.instructions && gp == other.gp
        && running == other.running && idle == other.idle;
  }
};

ModelState snapshot(const vortex::Processor& processor) {
  const auto& platform = vortex::SimPlatform::instance();
  const auto* core = processor.get_first_core();
  expect(core != nullptr, "processor has no core");
  return {platform.cycles(), platform.reset_gen(), core->perf_stats().cycles,
          core->perf_stats().instrs, core->get_exitcode(), processor.any_running(), platform.idle()};
}

uint64_t read_pending(const vortex::Processor& processor) {
#ifdef P06_PENDING_FORCE_ZERO
  (void)processor;
  return 0;
#else
  return processor.pending_mem_reads();
#endif
}

uint64_t observe(const vortex::Processor& processor) {
  const auto before = snapshot(processor);
  const auto first = read_pending(processor);
  const auto middle = snapshot(processor);
  const auto second = read_pending(processor);
  const auto after = snapshot(processor);
  expect(before == middle && middle == after && first == second,
         "pending getter changed model state");
  return first;
}

void launch_at(vortex::Processor& processor) {
  const std::array<std::pair<uint32_t, uint32_t>, 19> descriptor{{
    {VX_DCR_KMU_STARTUP_ADDR0, static_cast<uint32_t>(kProgramAddress)},
    {VX_DCR_KMU_STARTUP_ADDR1, 0},
    {VX_DCR_KMU_KERNEL_ENTRY0, static_cast<uint32_t>(kProgramAddress)},
    {VX_DCR_KMU_KERNEL_ENTRY1, 0},
    {VX_DCR_KMU_STARTUP_ARG0, 0}, {VX_DCR_KMU_STARTUP_ARG1, 0},
    {VX_DCR_KMU_BLOCK_DIM_X, 1}, {VX_DCR_KMU_BLOCK_DIM_Y, 1},
    {VX_DCR_KMU_BLOCK_DIM_Z, 1}, {VX_DCR_KMU_GRID_DIM_X, 1},
    {VX_DCR_KMU_GRID_DIM_Y, 1}, {VX_DCR_KMU_GRID_DIM_Z, 1},
    {VX_DCR_KMU_BLOCK_SIZE, 1}, {VX_DCR_KMU_WARP_STEP_X, 1},
    {VX_DCR_KMU_WARP_STEP_Y, 1}, {VX_DCR_KMU_WARP_STEP_Z, 1},
    {VX_DCR_KMU_CLUSTER_DIM_X, 1}, {VX_DCR_KMU_CLUSTER_DIM_Y, 1},
    {VX_DCR_KMU_CLUSTER_DIM_Z, 1},
  }};
  for (const auto& field : descriptor) {
    expect(processor.dcr_write(field.first, field.second) == 0, "launch descriptor write failed");
  }
}

void check_context(int gp) {
  vortex::RAM ram(kCapacity, kCapacity);
  ram.enable_acl(false);
  const uint32_t immediate = static_cast<uint32_t>(gp) & 0xfffu;
  const std::array<uint32_t, 3> program{{
    (immediate << 20) | 0x193u, 0x0000700bu, 0x0000000bu,
  }};
  ram.write(program.data(), kProgramAddress, sizeof(program));
  vortex::Processor processor;
  processor.attach_ram(&ram);
  launch_at(processor);
  const auto initial = snapshot(processor);
  expect(observe(processor) == 0, "new processor has pending reads");
  uint64_t steps = 0;
  uint64_t positive_samples = 0;
  uint64_t maximum = 0;
  bool drained = false;
  while (steps < kMaxSteps) {
    (void)processor.cycle();
    ++steps;
    const uint64_t pending = observe(processor);
    maximum = pending > maximum ? pending : maximum;
    positive_samples += pending != 0;
    const auto current = snapshot(processor);
    if (!current.running && current.idle) {
      expect(pending == 0, "completed processor retains pending reads");
      drained = true;
      break;
    }
  }
  expect(drained, "stepped launch exceeded its cycle bound");
  const auto stepped = snapshot(processor);
  expect(stepped.gp == gp && stepped.resets == initial.resets + 1,
         "stepped launch changed legacy gp or reset count");
  expect(maximum > 0 && positive_samples > 0,
         "pending getter did not observe an outstanding read");
  processor.run_checked();
  expect(observe(processor) == 0, "checked launch retains pending reads");
  const auto checked = snapshot(processor);
  expect(checked.gp == gp && checked.idle && !checked.running
      && checked.resets == stepped.resets + 1,
         "checked launch changed legacy gp or completion state");
  std::printf("P06_PENDING_CONTEXT {\"gp\":%d,\"steps\":%" PRIu64
      ",\"positive_samples\":%" PRIu64 ",\"max_pending\":%" PRIu64
      ",\"readonly_checks\":%" PRIu64 ",\"stepped_reset_delta\":1,"
      "\"checked_reset_delta\":1,\"pending_final\":0,\"checked_gp\":%d}\n",
      gp, steps, positive_samples, maximum, steps + 2, checked.gp);
}

struct Libraries {
  std::array<std::string, 3> paths;
  bool failed = false;
};

int loaded_object(dl_phdr_info* info, size_t, void* opaque) noexcept {
  auto& result = *static_cast<Libraries*>(opaque);
  try {
    const std::string path = info->dlpi_name ? info->dlpi_name : "";
    const auto name = path.substr(path.find_last_of('/') + 1);
    for (size_t i = 0; i < result.paths.size(); ++i) {
      if (name == kLibraries[i]) {
        if (!result.paths[i].empty() || path.empty() || path.front() != '/') {
          result.failed = true;
          return 1;
        }
        result.paths[i] = path;
      }
    }
  } catch (...) {
    result.failed = true;
    return 1;
  }
  return 0;
}

void print_libraries() {
  Libraries libraries;
  expect(dl_iterate_phdr(loaded_object, &libraries) == 0 && !libraries.failed,
         "native loader observation failed");
  for (size_t i = 0; i < libraries.paths.size(); ++i) {
    const auto& path = libraries.paths[i];
    expect(!path.empty() && path.find_first_not_of(
        "/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.+-") == std::string::npos,
        "native library path is absent or unsupported");
    std::printf("P06_PENDING_LIBRARY {\"name\":\"%s\",\"path\":\"%s\"}\n",
                kLibraries[i], path.c_str());
  }
  expect(std::fflush(stdout) == 0, "native loader output failed");
}

} // namespace

int main() {
  try {
    print_libraries();
    check_context(7);
    check_context(-1);
    std::puts("PASSED pending_reads native_probe contexts=2 stepped_runs=2 checked_runs=2 readonly=1");
    expect(std::fflush(stdout) == 0 && !std::ferror(stdout), "native probe output failed");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED pending_reads native_probe: %s\n", error.what());
  } catch (...) {
    std::fputs("FAILED pending_reads native_probe: unexpected nonstandard exception\n", stderr);
  }
  return 1;
}
