// Copyright © 2026
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <array>
#include <cinttypes>
#include <cstddef>
#include <cstdint>
#include <cstdio>

#include "core.h"
#include "csr_unit.h"
#include "processor.h"
#include "VX_types.h"

namespace {

struct CounterValue {
  uint64_t value;
  uint32_t low;
  uint32_t high;
};

constexpr std::array<CounterValue, 10> kValues = {{
  {0x0000000000000000ull, 0x00000000u, 0x00000000u},
  {0x0000000000000001ull, 0x00000001u, 0x00000000u},
  {0x00000000ffffffffull, 0xffffffffu, 0x00000000u},
  {0x0000000100000000ull, 0x00000000u, 0x00000001u},
  {0x0000000100000001ull, 0x00000001u, 0x00000001u},
  {0x00000abc12345678ull, 0x12345678u, 0x00000abcu},
  {0x00000fffffffffffull, 0xffffffffu, 0x00000fffu},
  {0x0000100000000000ull, 0x00000000u, 0x00001000u},
  {0xfedcba9889abcdefull, 0x89abcdefu, 0xfedcba98u},
  {0xffffffffffffffffull, 0xffffffffu, 0xffffffffu},
}};

constexpr uint32_t kClasses[] = {
  VX_DCR_MPM_CLASS_BASE,
  VX_DCR_MPM_CLASS_CORE,
  VX_DCR_MPM_CLASS_ICACHE,
  VX_DCR_MPM_CLASS_DCACHE,
  VX_DCR_MPM_CLASS_L2CACHE,
  VX_DCR_MPM_CLASS_L3CACHE,
  VX_DCR_MPM_CLASS_MEM,
#ifdef VX_CFG_EXT_TCU_ENABLE
  VX_DCR_MPM_CLASS_TCU,
#endif
#ifdef VX_CFG_EXT_RASTER_ENABLE
  VX_DCR_MPM_CLASS_RASTER,
#endif
#ifdef VX_CFG_EXT_TEX_ENABLE
  VX_DCR_MPM_CLASS_TEX,
#endif
#ifdef VX_CFG_EXT_OM_ENABLE
  VX_DCR_MPM_CLASS_OM,
#endif
#ifdef VX_CFG_EXT_RTU_ENABLE
  VX_DCR_MPM_CLASS_RTU,
#endif
#ifdef VX_CFG_EXT_DXA_ENABLE
  VX_DCR_MPM_CLASS_DXA,
#endif
};

constexpr uint32_t mpm_tag(uint32_t perf_class, uint32_t index,
                           uint32_t core_id, bool high) {
  return (perf_class << 22) | ((index + (high ? 32u : 0u)) << 16) | core_id;
}

static_assert(VX_DCR_BASE_MPM_VALUE == 0x001);
static_assert(VX_CSR_MPM_BASE == 0xb00 && VX_CSR_MPM_BASE_H == 0xb80);
static_assert(VX_CSR_MCYCLE == 0xb00 && VX_CSR_MCYCLE_H == 0xb80);
static_assert(VX_CSR_MINSTRET == 0xb02 && VX_CSR_MINSTRET_H == 0xb82);
static_assert(VX_CSR_MPM_SCHED_IDLE == 0xb03);
static_assert(VX_CSR_MPM_ACTIVE_WARPS == 0xb04);
static_assert(VX_CSR_MPM_STORES == 0xb1e);
static_assert(VX_DCR_MPM_CLASS_BASE == 0 && VX_DCR_MPM_CLASS_CORE == 1);
static_assert(mpm_tag(1, 3, 1, false) == 0x00430001);
static_assert(mpm_tag(1, 3, 1, true) == 0x00630001);

class TransportTest {
public:
  TransportTest(vortex::Processor& processor, vortex::Core& core)
    : processor_(processor)
    , core_(core)
    , saved_class_(core.mpm_class()) {
    expect("initial MPM class", 0, 0, kValues[0], saved_class_,
           VX_DCR_MPM_CLASS_BASE);
  }

  void host_counter(uint32_t perf_class, uint32_t index,
                    const CounterValue& expected) {
    for (bool high_first : {false, true, false}) {
      uint32_t low;
      uint32_t high;
      if (high_first) {
        high = read_half(perf_class, index, true, expected);
        low = read_half(perf_class, index, false, expected);
      } else {
        low = read_half(perf_class, index, false, expected);
        high = read_half(perf_class, index, true, expected);
      }
      const uint64_t actual = (uint64_t(high) << 32) | low;
      expect(high_first ? "high-first reconstruction" : "low-first reconstruction",
             perf_class, index, expected, actual, expected.value);
    }
  }

  void device_counter(uint32_t index, const CounterValue& expected) {
    auto& csr = core_.csr_unit();
    const uint64_t low = csr.get_csr(0xb00 + index, 0, 0);
    const uint64_t high = csr.get_csr(0xb80 + index, 0, 0);
#ifdef VX_CFG_XLEN_64
    expect("device low CSR", saved_class_, index, expected, low, expected.value);
    expect("device high CSR", saved_class_, index, expected, high, 0);
#else
    expect("device low CSR", saved_class_, index, expected, low, expected.low);
    expect("device high CSR", saved_class_, index, expected, high, expected.high);
#endif
    expect("device class preservation", saved_class_, index, expected,
           core_.mpm_class(), saved_class_);
  }

  int result() const {
    if (failures_ != 0) {
      std::printf("FAILED: %zu of %zu MPM transport checks\n", failures_, checks_);
      return 1;
    }
    std::printf("PASSED: %zu MPM transport checks\n", checks_);
    return 0;
  }

private:
  uint32_t read_half(uint32_t perf_class, uint32_t index, bool high,
                     const CounterValue& expected) {
    const uint32_t expected_half = high ? expected.high : expected.low;
    uint32_t actual = ~expected_half;
    const uint32_t tag = mpm_tag(perf_class, index, core_.id(), high);
    const int status = processor_.dcr_read(VX_DCR_BASE_MPM_VALUE, tag, &actual);
    ++checks_;
    if (status != 0) {
      std::printf("FAILED: DCR read status=%d tag=0x%08" PRIx32 "\n", status, tag);
      ++failures_;
    }
    expect(high ? "host high reply" : "host low reply", perf_class, index,
           expected, actual, expected_half);
    expect("host class restoration", perf_class, index, expected,
           core_.mpm_class(), saved_class_);
    return actual;
  }

  void expect(const char* what, uint32_t perf_class, uint32_t index,
              const CounterValue& seed, uint64_t actual, uint64_t expected) {
    ++checks_;
    if (actual != expected) {
      std::printf("FAILED: %s core=%" PRIu32 " class=%" PRIu32
                  " index=%" PRIu32 " seed=0x%016" PRIx64
                  " actual=0x%016" PRIx64 " expected=0x%016" PRIx64 "\n",
                  what, core_.id(), perf_class, index, seed.value, actual, expected);
      ++failures_;
    }
  }

  vortex::Processor& processor_;
  vortex::Core& core_;
  uint32_t saved_class_;
  size_t checks_ = 0;
  size_t failures_ = 0;
};

} // namespace

int main() {
#ifdef PERF_ENABLE
  constexpr const char* perf = "on";
#else
  constexpr const char* perf = "off";
#endif
  std::printf("MPM transport: XLEN=%d PERF=%s\n", VX_CFG_XLEN, perf);

  vortex::Processor processor;
  processor.reset();
  auto* core = processor.get_first_core();
  if (core == nullptr) {
    std::printf("FAILED: processor has no first core\n");
    return 1;
  }
  TransportTest test(processor, *core);

  // No simulation ticks run between seeding and reads, so both halves stay stable.
  for (size_t i = 0; i < kValues.size(); ++i) {
    const auto& cycles = kValues[i];
    const auto& instrs = kValues[(i + 1) % kValues.size()];
    auto& counters = core->perf_stats();
    counters.cycles = cycles.value;
    counters.instrs = instrs.value;
#ifdef PERF_ENABLE
    const auto& sched_idle = kValues[(i + 2) % kValues.size()];
    const auto& active_warps = kValues[(i + 3) % kValues.size()];
    const auto& stores = kValues[(i + 4) % kValues.size()];
    counters.sched_idle = sched_idle.value;
    counters.active_warps = active_warps.value;
    counters.stores = stores.value;
#endif

    test.device_counter(0, cycles);
    test.device_counter(2, instrs);
    for (uint32_t perf_class : kClasses) {
      test.host_counter(perf_class, 0, cycles);
      test.host_counter(perf_class, 2, instrs);
    }

#ifdef PERF_ENABLE
    test.host_counter(VX_DCR_MPM_CLASS_CORE, 3, sched_idle);
    test.host_counter(VX_DCR_MPM_CLASS_CORE, 4, active_warps);
    test.host_counter(VX_DCR_MPM_CLASS_CORE, 30, stores);
    for (uint32_t index : {1u, 24u, 25u, 31u}) {
      test.host_counter(VX_DCR_MPM_CLASS_CORE, index, kValues[0]);
    }
#endif
    for (uint32_t index : {3u, 4u, 30u}) {
      test.host_counter(VX_DCR_MPM_CLASS_BASE, index, kValues[0]);
      test.device_counter(index, kValues[0]);
    }
    test.device_counter(0, cycles);
    test.device_counter(2, instrs);
  }

  return test.result();
}
