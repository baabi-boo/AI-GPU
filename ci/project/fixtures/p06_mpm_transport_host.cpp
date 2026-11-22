// SPDX-License-Identifier: Apache-2.0
// Host-only adapter harness: deterministic CSR storage and a scripted CP.
// The included production definitions are extracted verbatim by the Python test.
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
#include <vortex2.h>
#include "production_constants.inc"
#include "production_csr_read.inc"

namespace {

unsigned checks = 0;

void equal(uint64_t actual, uint64_t expected, const char* description) {
  ++checks;
  if (actual != expected) {
    std::cerr << "FAIL " << description << " expected=0x" << std::hex
              << expected << " got=0x" << actual << '\n';
    std::exit(1);
  }
}

struct Vector {
  uint64_t value;
  uint32_t low;
  uint32_t high;
};

// Literal independent pairs include values beyond a 44-bit hardware counter.
constexpr std::array<Vector, 10> vectors{{
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

constexpr std::array<uint32_t, 13> classes{{0, 1, 3, 4, 5, 6, 7, 11, 12, 13, 14, 15, 16}};

static_assert(VX_DCR_BASE_MPM_VALUE == 0x001 && VX_DCR_BASE_CACHE_FLUSH == 0x000);
static_assert(VX_CSR_MPM_BASE == 0xb00 && VX_CSR_MPM_BASE_H == 0xb80);
static_assert(VX_CSR_MCYCLE == 0xb00 && VX_CSR_MINSTRET == 0xb02);

#ifdef VX_CFG_XLEN_64
using Word = uint64_t;
#else
using Word = uint32_t;
#endif

struct CsrRead {
  uint32_t addr;
  uint32_t mpm_class;
  uint32_t wid;
  uint32_t tid;
};

struct CsrBacking {
  explicit CsrBacking(uint32_t& mpm_class) : mpm_class_(mpm_class) {}

  uint32_t& mpm_class_;
  uint64_t cycles = 0;
  uint64_t instrs = 0;
  std::array<std::array<uint64_t, 32>, 17> user{};
  std::vector<CsrRead> reads;

  Word get_csr(uint32_t addr, uint32_t wid, uint32_t tid) {
    reads.push_back({addr, mpm_class_, wid, tid});
    // Only the width macro is production CSR code; storage is a host test double.
    switch (addr) {
      CSR_READ_64(VX_CSR_MCYCLE, cycles);
      CSR_READ_64(VX_CSR_MINSTRET, instrs);
      CSR_READ_64(VX_CSR_MPM_BASE + 3, user.at(mpm_class_).at(3));
      CSR_READ_64(VX_CSR_MPM_BASE + 4, user.at(mpm_class_).at(4));
      CSR_READ_64(VX_CSR_MPM_BASE + 30, user.at(mpm_class_).at(30));
      default: return 0;
    }
  }
};

struct HostCore {
  uint32_t mpm_class_ = 7;
  CsrBacking backing{mpm_class_};

  CsrBacking& csr_unit() { return backing; }

#include "production_dcr_read.inc"
};

void half(HostCore& core, uint32_t mpm_class, uint32_t index, bool high, uint32_t expected) {
  auto saved = core.mpm_class_;
  auto count = core.backing.reads.size();
  uint32_t value = 0xdeadbeefu;
  uint32_t tag = (mpm_class << 6) | index | (high ? 0x20u : 0u);
  equal(core.dcr_read(0x001, tag, &value), 0, "Core adapter result");
  equal(value, expected, high ? "Core high reply" : "Core low reply");
  equal(core.mpm_class_, saved, "saved class restored");
  equal(core.backing.reads.size(), count + 1, "one CSR read per DCR");
  const auto& read = core.backing.reads.back();
#ifdef VX_CFG_XLEN_64
  equal(read.addr, 0xb00u + index, "RV64 requested low CSR address");
#else
  equal(read.addr, (high ? 0xb80u : 0xb00u) + index, "RV32 requested half CSR address");
#endif
  equal(read.mpm_class, mpm_class, "requested class visible during CSR read");
  equal(read.wid, 0, "CSR warp zero");
  equal(read.tid, 0, "CSR thread zero");
}

void core_vectors() {
  HostCore core;
  // Begin at bit 32 so the original RV64 adapter fails on a numeric reply.
  core.backing.cycles = vectors[3].value;
  half(core, 1, 0, true, 0x00000001u);
  for (size_t i = 0; i < vectors.size(); ++i) {
    const auto& current = vectors[i];
    const auto& adjacent = vectors[(i + 1) % vectors.size()];
    core.backing.cycles = current.value;
    core.backing.instrs = adjacent.value;
    for (auto mpm_class : classes) {
      core.mpm_class_ = mpm_class == 7 ? 1 : 7;
      half(core, mpm_class, 0, true, current.high);
      half(core, mpm_class, 2, false, adjacent.low);
      half(core, mpm_class, 0, false, current.low);
      half(core, mpm_class, 2, true, adjacent.high);
      half(core, mpm_class, 0, true, current.high);
      half(core, mpm_class, 0, false, current.low);
      if (mpm_class != 0) {
        core.backing.user[mpm_class][3] = current.value;
        core.backing.user[mpm_class][4] = adjacent.value;
        half(core, mpm_class, 3, true, current.high);
        half(core, mpm_class, 4, false, adjacent.low);
        half(core, mpm_class, 3, false, current.low);
        half(core, mpm_class, 4, true, adjacent.high);
      }
    }
    core.backing.user[1][30] = current.value;
    half(core, 1, 30, false, current.low);
    half(core, 1, 30, true, current.high);
  }

  // Interleave unequal class banks without changing storage between reads.
  core.backing.user[1][3] = vectors[8].value;
  core.backing.user[11][3] = vectors[5].value;
  half(core, 1, 3, true, 0xfedcba98u);
  half(core, 11, 3, false, 0x12345678u);
  half(core, 1, 3, false, 0x89abcdefu);
  half(core, 11, 3, true, 0x00000abcu);
  half(core, 0, 3, false, 0);
  half(core, 0, 3, true, 0);
  for (uint32_t hole : {1u, 24u, 25u, 31u}) {
    half(core, 1, hole, false, 0);
    half(core, 1, hole, true, 0);
  }
  auto reads = core.backing.reads.size();
  uint32_t value = 0xdeadbeefu;
  equal(core.dcr_read(0x000, 0x43, &value), 0, "cache flush result");
  equal(value, 0, "cache flush reply");
  equal(core.backing.reads.size(), reads, "cache flush bypasses CSR");
}

void device_width() {
  HostCore core;
  core.backing.cycles = 0xfedcba9889abcdefull;
  core.backing.instrs = 0xffffffffffffffffull;
#ifdef VX_CFG_XLEN_64
  equal(core.backing.get_csr(0xb00, 0, 0), 0xfedcba9889abcdefull, "device RV64 full cycle");
  equal(core.backing.get_csr(0xb02, 0, 0), 0xffffffffffffffffull, "device RV64 full instret");
  equal(core.backing.get_csr(0xb80, 0, 0), 0, "device RV64 cycle high alias absent");
  equal(core.backing.get_csr(0xb82, 0, 0), 0, "device RV64 instret high alias absent");
#else
  equal(core.backing.get_csr(0xb00, 0, 0), 0x89abcdefu, "device RV32 low cycle");
  equal(core.backing.get_csr(0xb02, 0, 0), 0xffffffffu, "device RV32 low instret");
  equal(core.backing.get_csr(0xb80, 0, 0), 0xfedcba98u, "device RV32 high cycle");
  equal(core.backing.get_csr(0xb82, 0, 0), 0xffffffffu, "device RV32 high instret");
#endif
}

} // namespace

namespace vx {

struct Reply {
  uint32_t tag;
  uint32_t value;
  vx_result_t result = VX_SUCCESS;
};

class Device {
public:
  std::vector<Reply> replies;
  size_t calls = 0;
  unsigned cap_calls = 0;
  uint64_t cores = 2;
  vx_result_t caps_result = VX_SUCCESS;

  vx_result_t cp_submit_dcr_read(uint32_t addr, uint32_t tag, uint32_t* value) {
    equal(addr, 0x001, "public DCR address");
    equal(calls < replies.size(), true, "no unexpected CP call");
    const auto& reply = replies.at(calls++);
    equal(tag, reply.tag, "public raw low/high/class/core tag");
    *value = reply.value;
    return reply.result;
  }

  vx_result_t query_caps(uint32_t cap, uint64_t* value) {
    ++cap_calls;
    equal(cap, VX_CAPS_NUM_CORES, "public core capability");
    *value = cores;
    return caps_result;
  }
};

Device* to_device(vx_device_h dev) { return static_cast<Device*>(dev); }

} // namespace vx

#include "production_mpm_query.inc"

namespace {

void public_query() {
  for (const auto& vector : vectors) {
    vx::Device device;
    device.replies = {{0x00430001, vector.low}, {0x00630001, vector.high}};
    uint64_t value = 0;
    equal(vx_device_mpm_query(&device, 1, 0xb03, 1, &value), VX_SUCCESS, "public query result");
    equal(value, vector.value, "public exact uint64 reconstruction");
    equal(device.calls, 2, "public two half reads");
    equal(device.cap_calls, 0, "selected core needs no count query");
  }
  vx::Device device;
  device.replies = {{0x02c30000, 0xffffffff}, {0x02e30000, 0},
                    {0x02c30001, 1}, {0x02e30001, 1}};
  uint64_t value = 0;
  equal(vx_device_mpm_query(&device, 11, 0xb03, 0xffffffff, &value), VX_SUCCESS, "public sum result");
  equal(value, 0x0000000200000000ull, "public sum carries beyond bit 32");
  equal(device.calls, 4, "public sum reads both cores");
  equal(device.cap_calls, 1, "public sum queries core count once");
}

void public_errors() {
  constexpr uint64_t sentinel = 0xdecafbad12345678ull;
  vx::Device invalid;
  uint64_t value = sentinel;
  equal(vx_device_mpm_query(nullptr, 1, 0xb03, 0, &value), VX_ERR_INVALID_HANDLE, "null device");
  equal(value, sentinel, "null device preserves output");
  equal(vx_device_mpm_query(&invalid, 1, 0xb03, 0, nullptr), VX_ERR_INVALID_VALUE, "null output");
  for (uint32_t addr : {0xaffu, 0xb20u, 0xb80u}) {
    equal(vx_device_mpm_query(&invalid, 1, addr, 0, &value), VX_ERR_INVALID_VALUE, "invalid CSR address");
    equal(value, sentinel, "invalid address preserves output");
  }
  equal(invalid.calls, 0, "invalid arguments do not submit DCRs");
  equal(invalid.cap_calls, 0, "invalid arguments do not query caps");

  for (size_t failure = 0; failure < 2; ++failure) {
    vx::Device device;
    device.replies = {{0x00430001, 0x89abcdef}, {0x00630001, 0xfedcba98}};
    const auto error = failure == 0 ? VX_ERR_DEVICE_LOST : VX_ERR_TIMEOUT;
    device.replies[failure].result = error;
    value = sentinel;
    equal(vx_device_mpm_query(&device, 1, 0xb03, 1, &value), error, "single core propagates half error");
    equal(value, sentinel, "failed single core leaves output untouched");
    equal(device.calls, failure + 1, "single core stops at first error");
  }

  vx::Device caps;
  caps.caps_result = VX_ERR_NOT_SUPPORTED;
  value = sentinel;
  equal(vx_device_mpm_query(&caps, 11, 0xb03, 0xffffffff, &value), VX_ERR_NOT_SUPPORTED, "caps error");
  equal(value, sentinel, "caps error preserves output");
  equal(caps.calls, 0, "caps failure does not submit DCRs");
  equal(caps.cap_calls, 1, "caps query fails once");

  for (size_t failure = 0; failure < 4; ++failure) {
    vx::Device device;
    device.replies = {{0x02c30000, 0xffffffff}, {0x02e30000, 0},
                      {0x02c30001, 1}, {0x02e30001, 1}};
    device.replies[failure].result = VX_ERR_EVENT_FAILED;
    value = sentinel;
    equal(vx_device_mpm_query(&device, 11, 0xb03, 0xffffffff, &value), VX_ERR_EVENT_FAILED, "sum half error");
    equal(value, sentinel, "failed sum preserves output after partial progress");
    equal(device.calls, failure + 1, "sum stops at first half error");
  }
}

} // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  const std::string group(argv[1]);
  if (group == "core_vectors") {
    core_vectors();
  } else if (group == "device_width") {
    device_width();
  } else if (group == "public_query") {
    public_query();
  } else if (group == "public_errors") {
    public_errors();
  } else {
    return 2;
  }
  std::cout << "PASS host-adapter " << group << " checks=" << checks << '\n';
  return 0;
}
