// SPDX-License-Identifier: Apache-2.0
#include "core.h"
#include "mem.h"
#include "processor.h"
#include "VX_types.h"

#include <array>
#include <cstdint>
#include <cstdio>
#include <future>
#include <stdexcept>
#include <utility>

namespace {

constexpr uint64_t kCapacity = 4096;
constexpr uint64_t kProgramAddress = 256;

void expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void run_candidate(vortex::Processor& processor) {
#ifdef SIMX_COMPLETION_USE_LEGACY_RUN
  (void)processor.run();
#else
  processor.run_checked();
#endif
}

void launch_at(vortex::Processor& processor, uint64_t address) {
  const std::array<std::pair<uint32_t, uint32_t>, 19> descriptor{{
    {VX_DCR_KMU_STARTUP_ADDR0, static_cast<uint32_t>(address)},
    {VX_DCR_KMU_STARTUP_ADDR1, static_cast<uint32_t>(address >> 32)},
    {VX_DCR_KMU_KERNEL_ENTRY0, static_cast<uint32_t>(address)},
    {VX_DCR_KMU_KERNEL_ENTRY1, static_cast<uint32_t>(address >> 32)},
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

void check_exception() {
  vortex::RAM ram(kCapacity, kCapacity);
  ram.enable_acl(false);
  vortex::Processor processor;
  processor.attach_ram(&ram);
  launch_at(processor, kCapacity);
  auto result = std::async(std::launch::async, [&processor] { run_candidate(processor); });
  bool caught = false;
  try {
    result.get();
  } catch (const vortex::OutOfRange&) {
    caught = true;
  }
  expect(caught, "checked execution swallowed the native bounded-RAM exception");
  std::printf("native_exception type=OutOfRange consumed=1\n");
}

void check_legacy_exception() {
  vortex::RAM ram(kCapacity, kCapacity);
  ram.enable_acl(false);
  vortex::Processor processor;
  processor.attach_ram(&ram);
  launch_at(processor, kCapacity);
  expect(processor.run() == -1, "legacy caught-exception result changed");
  std::printf("native_legacy_exception result=-1\n");
}

void check_normal(int gp) {
  vortex::RAM ram(kCapacity, kCapacity);
  ram.enable_acl(false);
  const uint32_t immediate = static_cast<uint32_t>(gp) & 0xfffu;
  // Architectural x3 is data here; neither wsync nor tmc changes it.
  const std::array<uint32_t, 3> program{{
    (immediate << 20) | 0x193u, 0x0000700bu, 0x0000000bu,
  }};
  ram.write(program.data(), kProgramAddress, sizeof(program));
  vortex::Processor processor;
  processor.attach_ram(&ram);
  launch_at(processor, kProgramAddress);
  for (int index = 0; index < 3; ++index) {
    auto result = std::async(std::launch::async, [&processor] { run_candidate(processor); });
    result.get();
    expect(processor.get_first_core()->get_exitcode() == gp,
           "native checked run changed the architectural x3 witness");
  }
  expect(processor.run() == gp, "legacy run result changed");
  std::printf("native_x3 gp=%d checked_launches=3 legacy_launches=1\n", gp);
}

} // namespace

int main() {
  try {
    check_normal(7);
    check_normal(-1);
    check_legacy_exception();
    check_exception();
    check_normal(7);
    std::printf("PASSED simx_completion native_unit contexts=5 checked_success=9 legacy_success=3 checked_exceptions=1 legacy_errors=1\n");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED simx_completion native_unit: %s\n", error.what());
    return 1;
  } catch (...) {
    std::fprintf(stderr, "FAILED simx_completion native_unit: unexpected nonstandard exception\n");
    return 1;
  }
}
