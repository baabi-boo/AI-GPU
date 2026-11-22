// Copyright © 2019-2023
// Licensed under the Apache License, Version 2.0.

#include <VX_config.h>
#include "vl_simulator.h"
#include "VVX_mpm_transport_top.h"

#include <array>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

static uint64_t timestamp = 0;
double sc_time_stamp() { return timestamp; }

struct Counter {
  uint64_t value;
  uint32_t low;
  uint32_t high;
};

// Expected words are literal oracles, independent of the decoder's slicing.
static constexpr std::array<Counter, 9> kBoundaries{{
  {0x00000000000ull, 0x00000000u, 0x00000000u},
  {0x00000000001ull, 0x00000001u, 0x00000000u},
  {0x000ffffffffull, 0xffffffffu, 0x00000000u},
  {0x00100000000ull, 0x00000000u, 0x00000001u},
  {0x00100000001ull, 0x00000001u, 0x00000001u},
  {0xabc12345678ull, 0x12345678u, 0x00000abcu},
  {0xfffffffffffULL, 0xffffffffu, 0x00000fffu},
  {0x135fedcba98ull, 0xfedcba98u, 0x00000135u},
  {0x80076543210ull, 0x76543210u, 0x00000800u},
}};

static constexpr Counter kZero{0, 0, 0};
static constexpr std::array<uint8_t, 9> kClasses{{0, 1, 3, 4, 5, 6, 7, 11, 255}};

// Host tags: class[29:22], high/index[21:16], target core[15:0].
static constexpr uint32_t tag(uint8_t mpm_class, uint8_t index,
                              bool high, uint16_t core) {
  return (uint32_t(mpm_class) << 22)
       | (uint32_t(index | (high ? 32 : 0)) << 16)
       | core;
}

static_assert(tag(1, 3, false, 1) == 0x00430001u, "low tag encoding");
static_assert(tag(1, 3, true, 1) == 0x00630001u, "high tag encoding");

class Testbench {
public:
  vl_simulator<VVX_mpm_transport_top> sim;
  unsigned reads = 0;
  unsigned assertions = 0;
  unsigned ignored_requests = 0;

  void expect(bool condition, const char* message) {
    ++assertions;
    if (!condition) {
      std::fprintf(stderr, "FAIL tick=%" PRIu64 " tag=%08x: %s\n",
                   timestamp, active_tag_, message);
      std::exit(1);
    }
  }

  void tick() {
    timestamp = sim.step(timestamp, 2);
    sim->eval();
    expect(sim->csr_ready == 1, "counter decoder introduced backpressure");
  }

  void idle(unsigned count = 1) {
    sim->dcr_req_valid = 0;
    for (unsigned i = 0; i < count; ++i) {
      tick();
      expect(sim->dcr_rsp_valid == 0, "unexpected or repeated response");
      expect(sim->csr_valid == 0, "unexpected pending read");
    }
  }

  void reset() {
    sim->dcr_req_valid = 0;
    sim->reset = 1;
    tick();
    expect(sim->dcr_rsp_valid == 0, "response survived reset");
    expect(sim->dcr_rsp_data == 0, "response data did not reset");
    expect(sim->csr_valid == 0, "pending read survived reset");
    expect(sim->csr_addr == 0, "latched address did not reset");
    expect(sim->csr_class == 0, "latched class did not reset");
    sim->reset = 0;
    idle(3);
  }

  void issue(uint8_t mpm_class, uint8_t index, bool high) {
    expect(index < 32, "test index exceeds the host tag field");
    active_tag_ = tag(mpm_class, index, high, sim->core_id);
    sim->dcr_req_valid = 1;
    sim->dcr_req_rw = 0;
    sim->dcr_req_addr = 0x001;
    sim->dcr_req_data = active_tag_;
    sim->eval();
    expect(sim->dcr_rsp_valid == 0, "response before request clock edge");
    expect(sim->csr_valid == 0, "request was not initially idle");

    tick();
    expect(sim->dcr_rsp_valid == 0, "response arrived on capture edge");
    expect(sim->csr_valid == 1, "request was not captured on first edge");
    expect(sim->csr_addr == (high ? 0xb80u : 0xb00u) + index,
           "raw host selector decoded to the wrong CSR address");
    expect(sim->csr_class == mpm_class, "raw host class was not captured");

    // Changing inactive host wires must not change the accepted request.
    sim->dcr_req_valid = 0;
    sim->dcr_req_rw = 1;
    sim->dcr_req_addr = 0xfff;
    sim->dcr_req_data = ~active_tag_;
    sim->eval();
    expect(sim->csr_addr == (high ? 0xb80u : 0xb00u) + index,
           "latched selector followed inactive host wires");
    expect(sim->csr_class == mpm_class,
           "latched class followed inactive host wires");
  }

  uint32_t read(uint8_t mpm_class, uint8_t index, bool high, uint32_t expected) {
    issue(mpm_class, index, high);
    tick();
    expect(sim->dcr_rsp_valid == 1, "response missing on second edge");
    expect(sim->csr_valid == 0, "pending read did not retire on second edge");
    uint32_t actual = sim->dcr_rsp_data;
    ++assertions;
    if (actual != expected) {
      std::fprintf(stderr,
                   "FAIL RV%d tick=%" PRIu64 " tag=%08x: expected=%08x actual=%08x\n",
                   VX_CFG_XLEN, timestamp, active_tag_, expected, actual);
      std::exit(1);
    }
    if (high) {
      expect((actual & 0xfffff000u) == 0, "44-bit high word was not zero extended");
    }
    idle();
    ++reads;
    return actual;
  }

  void pair(uint8_t mpm_class, uint8_t index, const Counter& expected,
            bool high_first = false) {
    uint32_t low;
    uint32_t high;
    if (high_first) {
      high = read(mpm_class, index, true, expected.high);
      low = read(mpm_class, index, false, expected.low);
    } else {
      low = read(mpm_class, index, false, expected.low);
      high = read(mpm_class, index, true, expected.high);
    }
    expect(((uint64_t(high) << 32) | low) == expected.value,
           "two host words did not reconstruct the injected counter");
  }

  void no_response(uint32_t request_tag, bool write, uint16_t address,
                   bool valid = true) {
    active_tag_ = request_tag;
    sim->dcr_req_valid = valid;
    sim->dcr_req_rw = write;
    sim->dcr_req_addr = address;
    sim->dcr_req_data = request_tag;
    for (unsigned i = 0; i < 4; ++i) {
      tick();
      expect(sim->csr_valid == 0, "ignored request reached the counter decoder");
      expect(sim->dcr_rsp_valid == 0, "ignored request produced a response");
    }
    idle(4);
    ++ignored_requests;
  }

private:
  uint32_t active_tag_ = 0;
};

#ifdef PERF_ENABLE
struct PerfCase {
  QData* input;
  uint8_t mpm_class;
  uint8_t index;
  Counter expected;
};
#endif

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  Testbench tb;
  tb.sim->core_id = 1;
  tb.sim->dcr_req_valid = 0;
  tb.sim->dcr_req_rw = 0;
  tb.sim->dcr_req_addr = 0;
  tb.sim->dcr_req_data = 0;
  tb.sim->cycles = 0;
  tb.sim->instret = 0;

#ifdef PERF_ENABLE
  PerfCase perf_cases[] = {
    {&tb.sim->core_sched_idle,     1,  3, {0x12389abcdefull, 0x89abcdefu, 0x123u}},
    {&tb.sim->core_active_warps,   1,  4, {0x45610203040ull, 0x10203040u, 0x456u}},
    {&tb.sim->core_loads,          1, 28, {0x20855667788ull, 0x55667788u, 0x208u}},
    {&tb.sim->core_stores,         1, 30, {0xfed76543210ull, 0x76543210u, 0xfedu}},
    {&tb.sim->icache_reads,        3,  3, {0x234a1b2c3d4ull, 0xa1b2c3d4u, 0x234u}},
    {&tb.sim->icache_read_misses,  3,  4, {0x345b2c3d4e5ull, 0xb2c3d4e5u, 0x345u}},
    {&tb.sim->icache_mshr_stalls,  3,  5, {0x567c3d4e5f6ull, 0xc3d4e5f6u, 0x567u}},
    {&tb.sim->dcache_reads,        4,  3, {0x678d4e5f607ull, 0xd4e5f607u, 0x678u}},
    {&tb.sim->dcache_writes,       4,  4, {0x789e5f60718ull, 0xe5f60718u, 0x789u}},
    {&tb.sim->dcache_mshr_stalls,  4,  9, {0x89af6071829ull, 0xf6071829u, 0x89au}},
    {&tb.sim->l2cache_reads,       5,  3, {0x9ab0718293aull, 0x0718293au, 0x9abu}},
    {&tb.sim->l2cache_writes,      5,  4, {0xabc18293a4bull, 0x18293a4bu, 0xabcu}},
    {&tb.sim->l2cache_mshr_stalls, 5,  9, {0xbcd293a4b5cull, 0x293a4b5cu, 0xbcdu}},
    {&tb.sim->l3cache_reads,       6,  3, {0xcde3a4b5c6dull, 0x3a4b5c6du, 0xcdeu}},
    {&tb.sim->l3cache_writes,      6,  4, {0xdef4b5c6d7eull, 0x4b5c6d7eu, 0xdefu}},
    {&tb.sim->l3cache_mshr_stalls, 6,  9, {0xef05c6d7e8full, 0x5c6d7e8fu, 0xef0u}},
    {&tb.sim->mem_reads,          7,  3, {0xf016d7e8f90ull, 0x6d7e8f90u, 0xf01u}},
    {&tb.sim->mem_writes,         7,  4, {0x0127e8f901aull, 0x7e8f901au, 0x012u}},
    {&tb.sim->mem_latency,        7,  5, {0x0248f901a2bull, 0x8f901a2bu, 0x024u}},
    {&tb.sim->lmem_reads,         7,  7, {0x048901a2b3cull, 0x901a2b3cu, 0x048u}},
    {&tb.sim->lmem_writes,        7,  8, {0x090a1b2c3d4ull, 0xa1b2c3d4u, 0x090u}},
    {&tb.sim->lmem_bank_stalls,   7,  9, {0x120b2c3d4e5ull, 0xb2c3d4e5u, 0x120u}},
    {&tb.sim->coalescer_misses,   7, 10, {0x240c3d4e5f6ull, 0xc3d4e5f6u, 0x240u}},
  #ifdef VX_CFG_EXT_TCU_ENABLE
    {&tb.sim->tcu_tbuf_stalls,    11, 3, {0x480d4e5f607ull, 0xd4e5f607u, 0x480u}},
    {&tb.sim->tcu_tbuf_cache_hits,11, 4, {0x900e5f60718ull, 0xe5f60718u, 0x900u}},
    {&tb.sim->tcu_lmem_reads,     11, 5, {0xffef6071829ull, 0xf6071829u, 0xffeu}},
  #endif
  };
  for (auto& test : perf_cases) {
    *test.input = test.expected.value;
  }
#endif

  tb.reset();
  tb.idle(4);

  for (size_t i = 0; i < kBoundaries.size(); ++i) {
    const Counter& cycles = kBoundaries[i];
    const Counter& instret = kBoundaries[(i + 3) % kBoundaries.size()];
    tb.sim->cycles = cycles.value;
    tb.sim->instret = instret.value;
    tb.pair(0, 0, cycles, (i & 1) != 0);
    tb.pair(0, 2, instret, (i & 1) == 0);
    tb.read(0, 0, true, cycles.high);
    tb.read(0, 2, false, instret.low);
  }

  tb.sim->cycles = kBoundaries[5].value;
  tb.sim->instret = kBoundaries[7].value;
  for (auto mpm_class : kClasses) {
    tb.pair(mpm_class, 0, kBoundaries[5], true);
    tb.pair(mpm_class, 2, kBoundaries[7]);
    tb.pair(mpm_class, 1, kZero, true);
  }

#ifdef PERF_ENABLE
  for (auto& test : perf_cases) {
    tb.pair(test.mpm_class, test.index, test.expected, true);
    tb.pair(test.mpm_class, test.index, test.expected);
  }

  // Each representative input is updated through rollover and width boundaries.
  for (auto& test : perf_cases) {
    if (test.index != 3) {
      continue;
    }
    for (const auto& counter : kBoundaries) {
      *test.input = counter.value;
      tb.pair(test.mpm_class, test.index, counter, true);
    }
    *test.input = test.expected.value;
  }

  for (uint8_t index : {uint8_t(24), uint8_t(25), uint8_t(31)}) {
    tb.pair(1, index, kZero);
  }
  for (uint8_t mpm_class : {uint8_t(0), uint8_t(2), uint8_t(255)}) {
    tb.pair(mpm_class, 3, kZero, true);
    tb.pair(mpm_class, 30, kZero);
  }
  #ifndef VX_CFG_EXT_TCU_ENABLE
  for (uint8_t index : {uint8_t(3), uint8_t(4), uint8_t(5)}) {
    tb.pair(11, index, kZero);
  }
  #endif
#else
  for (auto mpm_class : kClasses) {
    for (uint8_t index : {uint8_t(3), uint8_t(4), uint8_t(30), uint8_t(31)}) {
      tb.pair(mpm_class, index, kZero, true);
    }
  }
#endif

  tb.no_response(tag(1, 3, false, 0), false, 0x001);
  tb.no_response(tag(1, 3, true, 0x0101), false, 0x001);
  tb.no_response(tag(7, 3, true, 0xffff), false, 0x001);
  tb.no_response(tag(0, 0, true, 1), true, 0x001);
  tb.no_response(tag(0, 0, true, 1), false, 0xfff);
  tb.no_response(tag(0, 0, true, 1), false, 0x001, false);

  tb.sim->core_id = 0;
  tb.no_response(tag(0, 0, true, 1), false, 0x001);
  tb.pair(0, 0, kBoundaries[5], true);
  tb.sim->core_id = 1;
  tb.pair(0, 2, kBoundaries[7]);

  // Reset cancels a captured request and does not produce a delayed reply.
  tb.issue(7, 0, true);
  tb.reset();
  tb.pair(0, 0, kBoundaries[5]);
  tb.pair(0, 2, kBoundaries[7], true);
  tb.reset();

#ifdef PERF_ENABLE
  constexpr unsigned perf_enabled = 1;
#else
  constexpr unsigned perf_enabled = 0;
#endif
#ifdef VX_CFG_EXT_TCU_ENABLE
  constexpr unsigned tcu_enabled = 1;
#else
  constexpr unsigned tcu_enabled = 0;
#endif
  std::printf("PASSED mpm_transport RV%d PERF=%u TCU=%u read_count=%u "
              "assertion_count=%u ignored=%u "
              "response_edges=2 counter_bits=44\n",
              VX_CFG_XLEN, perf_enabled, tcu_enabled,
              tb.reads, tb.assertions, tb.ignored_requests);
  return 0;
}
