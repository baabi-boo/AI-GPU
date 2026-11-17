// SPDX-License-Identifier: Apache-2.0
#include <VX_config.h>
#include <VVX_tcu_wgmma_top.h>
#include <verilated.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__)
#error "The WGMMA contract forbids fast math"
#endif
static_assert(VX_CFG_XLEN == 64 && VX_CFG_NUM_THREADS == 8 && VX_CFG_NUM_WARPS == 8);
static_assert(VX_CFG_ISSUE_WIDTH == 4 && VX_CFG_NUM_TCU_BLOCKS == 4);
static_assert(VX_CFG_NUM_LSU_LANES == 8 && VX_CFG_LMEM_NUM_BANKS == 8);
#ifndef VX_CFG_TCU_TYPE_TFR
#error "The WGMMA contract requires native TFR"
#endif

namespace {
constexpr unsigned Slots = 4, Lanes = 8;
constexpr uint64_t CycleLimit = 100000;
constexpr uint64_t PressureLimit = 256;
constexpr unsigned PoisonA = 0x3c00, PoisonB = 0x3e00;
using Words = std::array<uint32_t, 8>;
using Lanes64 = std::array<uint64_t, 8>;
using Matrix = std::array<std::array<int, 16>, 8>;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

uint32_t integer_bits(int value, unsigned fraction, unsigned exponent_bits) {
  if (value == 0) {
    return 0;
  }
  const uint32_t magnitude = static_cast<uint32_t>(value < 0 ? -value : value);
  unsigned leading = 0;
  for (uint32_t n = magnitude; n > 1; n >>= 1) {
    ++leading;
  }
  require(leading <= fraction, "fixture integer does not fit exact significand");
  const uint32_t bias = (1u << (exponent_bits - 1)) - 1;
  return (uint32_t(value < 0) << (fraction + exponent_bits)) | ((leading + bias) << fraction) | ((magnitude - (1u << leading)) << (fraction - leading));
}
uint32_t fp32(int value) {
  return integer_bits(value, 23, 8);
}
uint16_t input_bits(int value, unsigned format) {
  return static_cast<uint16_t>(format == 2 ? integer_bits(value, 10, 5)
                                           : integer_bits(value, 7, 8));
}
uint32_t packed(int a, int b, unsigned format) {
  return uint32_t(input_bits(a, format)) | (uint32_t(input_bits(b, format)) << 16);
}

struct Task {
  unsigned slot, wis, cta, format;
  bool sparse, shared_a, row_major;
  unsigned pattern, a_base, b_base, meta_base;
  uint64_t start;
  bool wait_for_owner = false;
  unsigned nregs = 8;
  Matrix a{}, b{}, c{}, result{};
  std::array<std::array<unsigned, 8>, 8> keep{};
  Words metadata{};
  unsigned next = 0, committed = 0;
  bool meta_sent = false, meta_done = false;
  uint32_t meta_seen = 0;
  std::array<bool, 16> first_checked{};
  unsigned total() const {
    return sparse ? nregs : 2 * nregs;
  }
};

Task make_task(unsigned slot, unsigned wis, unsigned cta, unsigned pattern,
               bool shared_a = true, bool row_major = false, bool sparse = false,
               unsigned format = 2, uint64_t start = 0, unsigned base_shift = 0,
               unsigned nregs = 8) {
  Task t{slot, wis, cta, format, sparse, shared_a, row_major, pattern,
         0x100 + base_shift + slot * 0x100 + wis * 0x800,
         0x600 + base_shift + cta * 0x800,
         0x2000 + (slot + 4 * wis) * 0x100, start};
  require(nregs == 8 || (nregs == 16 && !sparse && !shared_a), "unsupported fixture register count");
  t.nregs = nregs;
  constexpr unsigned masks[] = {3, 5, 6, 9, 10, 12};
  constexpr unsigned bit_map[] = {0, 1, 4, 5, 2, 3, 6, 7};
  for (unsigned r = 0; r < 8; ++r) {
    for (unsigned k = 0; k < 8; ++k) {
      t.a[r][k] = int((r * 5 + k * 3 + slot * 7 + wis * 4 + pattern * 11) % 15) - 7;
      const unsigned mask = masks[(r + slot * 2 + wis + pattern + k / 4) % 6];
      t.keep[r][k] = !sparse || ((mask >> (k % 4)) & 1u);
      if (sparse && t.keep[r][k]) {
        t.metadata[2 * (r / 4)] |= 1u << ((r % 4) * 8 + bit_map[k]);
      }
    }
    for (unsigned c = 0; c < nregs; ++c) {
      t.b[r][c] = int((r * 7 + c * 4 + cta * 3 + pattern * 5) % 15) - 7;
      t.c[r][c] = int((r * 9 + c * 5 + slot * 3 + pattern * 7) % 63) - 31;
    }
  }
  return t;
}

struct Packet {
  unsigned task = 0, uop = 0;
  bool metadata = false;
  uint64_t uuid = 0, pc = 0;
  unsigned slot = 0, wis = 0, cta = 0, rd = 0, wr_xregs = 0;
  unsigned op = 0, format = 0, m = 0, n = 0, k = 0, cd_nregs = 0;
  bool shared_a = false, first = false, last = false;
  Lanes64 a{}, b{}, c{}, expected{};
};

struct LmemResponse {
  uint64_t due, tag;
  Lanes64 data;
};
struct MetaResponse {
  uint64_t due;
  Words tag;
  Lanes64 data;
  unsigned mask, task;
  bool sop, eop;
};
struct Coverage {
  uint64_t accepted = 0, commits = 0, words = 0, dispatch_stalls = 0;
  uint64_t commit_holds = 0, lmem_holds = 0, lmem_requests = 0, lmem_responses = 0;
  uint64_t delayed_lmem = 0, metadata_requests = 0, metadata_writes = 0, metadata_lanes = 0;
  uint64_t delayed_metadata = 0, cta_conflicts = 0, cta_entries = 0, overlapping = 0;
  uint64_t pressure_holds = 0, pressure_qualified = 0, pressure_tail = 0;
  uint64_t descriptor_a_poisoned = 0, descriptor_b_poisoned = 0, cycles = 0;
};
struct Options {
  bool hold_commit = false, hold_memory = false, require_conflict = false, force_pressure = false;
};

class Harness {
public:
  explicit Harness(std::string name)
      : name_(std::move(name))
      , context_(new VerilatedContext)
      , dut_(new VVX_tcu_wgmma_top(context_.get())) {
    context_->assertOn(true);
    clear_inputs();
    dut_->reset = 1;
    for (unsigned i = 0; i < 8; ++i) {
      clock();
    }
    dut_->reset = 0;
    for (unsigned i = 0; i < 4; ++i) {
      clock();
    }
  }
  ~Harness() {
    dut_->final();
  }

  std::vector<Task> run(std::vector<Task> tasks, Options options = {}, const char *group_name = nullptr) {
    require(lmem_.empty() && metadata_.empty(), "responses remain before group");
    if (group_name) {
      name_ = group_name;
    }
    tasks_ = std::move(tasks);
    options_ = options;
    group_start_ = cycle_;
    memory_hold_end_ = commit_hold_end_ = 0;
    memory_hold_started_ = commit_hold_started_ = false;
    pressure_started_ = pressure_seen_ = false;
    pressure_start_ = pressure_first_ = pressure_release_ = 0;
    if (options.force_pressure) {
      require(!options.hold_memory && !options.hold_commit && !options.require_conflict && tasks_.size() == 1 && !tasks_[0].sparse && !tasks_[0].shared_a && tasks_[0].nregs == 16, "pressure group must isolate one dense NRC16 RS expansion");
      pressure_slot_ = tasks_[0].slot;
    }
    const auto before = coverage_;
    for (const auto &t : tasks_) {
      install(t);
    }
    while (!finished()) {
      step();
    }
    for (unsigned i = 0; i < 24; ++i) {
      step();
    }
    require(lmem_.empty() && metadata_.empty(), "responses remain after group");
    require(dut_->observe_resident == 0, "WGMMA ownership did not drain");
    for (unsigned b = 0; b < Slots; ++b) {
      require(expected_[b].empty() && !pending_[b], "transaction queue did not drain");
    }
    if (options.hold_memory) {
      require(coverage_.lmem_holds - before.lmem_holds == 8, "eight LMEM request stalls were not exercised");
      require(coverage_.delayed_lmem > before.delayed_lmem, "delayed LMEM response was not exercised");
    }
    if (options.hold_commit) {
      require(coverage_.commit_holds > before.commit_holds, "commit backpressure was not exercised");
    }
    if (options.force_pressure) {
      require(pressure_started_ && pressure_seen_, "compute pressure chain was not observed");
      require(coverage_.pressure_qualified > before.pressure_qualified && coverage_.pressure_tail - before.pressure_tail == 8,
              "compute pressure did not retain eight additional stable cycles");
      require(coverage_.pressure_holds - before.pressure_holds <= PressureLimit && coverage_.lmem_holds == before.lmem_holds && coverage_.delayed_lmem == before.delayed_lmem && coverage_.cta_conflicts == before.cta_conflicts,
              "compute pressure was not isolated from memory holds or CTA conflicts");
    }
    if (options.require_conflict) {
      require(coverage_.cta_conflicts > before.cta_conflicts, "conflicting CTA was never blocked");
      require(coverage_.cta_entries > before.cta_entries, "waiting CTA never entered");
    }
    require(cycle_ - group_start_ < CycleLimit, "group exceeded cycle bound");
    coverage_.cycles += cycle_ - group_start_;
    std::printf("WGMMA_GROUP name=%s accepted=%llu commits=%llu words=%llu cycles=%llu\n",
                name_.c_str(), ull(coverage_.accepted - before.accepted), ull(coverage_.commits - before.commits),
                ull(coverage_.words - before.words), ull(cycle_ - group_start_));
    return tasks_;
  }

  const Coverage &coverage() const {
    return coverage_;
  }

private:
  static unsigned long long ull(uint64_t v) {
    return static_cast<unsigned long long>(v);
  }
  void clock() {
    dut_->clk = 0;
    dut_->eval();
    context_->timeInc(1);
    dut_->clk = 1;
    dut_->eval();
    context_->timeInc(1);
    ++cycle_;
  }
  void clear_inputs() {
    dut_->dispatch_valid = dut_->dispatch_wb = dut_->dispatch_a_smem = 0;
    dut_->dispatch_first = dut_->dispatch_last = dut_->dispatch_sop = dut_->dispatch_eop = 0;
    dut_->commit_ready = 15;
    dut_->lmem_req_ready = dut_->meta_req_ready = 1;
    dut_->lmem_rsp_valid = dut_->meta_rsp_valid = 0;
    dut_->lmem_rsp_tag = 0;
    dut_->meta_rsp_mask = dut_->meta_rsp_sop = dut_->meta_rsp_eop = 0;
    for (unsigned b = 0; b < Slots; ++b) {
      dut_->dispatch_uuid[b] = dut_->dispatch_pc[b] = 0;
      dut_->dispatch_wis[b] = dut_->dispatch_cta[b] = dut_->dispatch_sid[b] = 0;
      dut_->dispatch_tmask[b] = dut_->dispatch_wr_xregs[b] = dut_->dispatch_rd[b] = 0;
      dut_->dispatch_bytesel[b] = dut_->dispatch_op[b] = dut_->dispatch_fmt_s[b] = 0;
      dut_->dispatch_fmt_d[b] = dut_->dispatch_m[b] = dut_->dispatch_n[b] = dut_->dispatch_k[b] = 0;
      dut_->dispatch_cd_nregs[b] = 0;
      for (unsigned l = 0; l < Lanes; ++l) {
        dut_->dispatch_rs1[b][l] = dut_->dispatch_rs2[b][l] = dut_->dispatch_rs3[b][l] = 0;
      }
    }
    for (unsigned l = 0; l < Lanes; ++l) {
      dut_->lmem_rsp_data[l] = dut_->meta_rsp_data[l] = 0;
      dut_->meta_rsp_tag[l] = 0;
    }
  }
  void write16(unsigned address, uint16_t bits) {
    require(address + 1 < memory_.size(), "fixture address out of memory");
    memory_[address] = bits & 255;
    memory_[address + 1] = bits >> 8;
  }
  uint64_t read64(unsigned address) const {
    require(address + 7 < memory_.size(), "LMEM request outside fixture memory");
    uint64_t value = 0;
    for (unsigned n = 0; n < 8; ++n) {
      value |= uint64_t(memory_[address + n]) << (8 * n);
    }
    return value;
  }
  void install(const Task &t) {
    for (unsigned r = 0; r < 8; ++r) {
      unsigned compressed = 0;
      for (unsigned k = 0; k < 8; ++k) {
        if (t.sparse && !t.keep[r][k]) {
          continue;
        }
        unsigned index;
        if (t.sparse) {
          index = r * 4 + compressed++;
        } else if (t.row_major) {
          index = r * 8 + k;
        } else {
          index = ((k / 4) * 2 + r / 4) * 16 + (r % 4) * 4 + k % 4;
        }
        write16(t.a_base + 2 * index, input_bits(t.a[r][k], t.format));
      }
    }
    for (unsigned k = 0; k < 8; ++k) {
      for (unsigned c = 0; c < t.nregs; ++c) {
        const unsigned index = t.sparse ? c * 8 + k
                                        : ((k / 4) * (t.nregs / 2) + c / 2) * 8 + (c % 2) * 4 + k % 4;
        write16(t.b_base + 2 * index, input_bits(t.b[k][c], t.format));
      }
    }
  }
  Packet make_packet(unsigned index, bool metadata) {
    const auto &t = tasks_[index];
    Packet p;
    p.task = index;
    p.uop = t.next;
    p.metadata = metadata;
    p.uuid = next_uuid_++;
    p.pc = 0x80000000 + p.uuid * 4;
    p.slot = t.slot;
    p.wis = t.wis;
    p.cta = t.cta;
    p.rd = metadata ? 0 : 32 + (t.next % t.nregs);
    p.wr_xregs = metadata ? 1 : 0;
    p.op = metadata ? 5 : (t.sparse ? 4 : 1);
    p.format = t.format;
    p.m = t.next & 1;
    p.n = (t.next >> 1) & (t.nregs / 2 - 1);
    p.k = t.sparse ? 0 : t.next / t.nregs;
    p.cd_nregs = t.nregs == 16 ? 1 : 0;
    p.shared_a = t.shared_a;
    p.first = t.next == 0;
    p.last = t.next + 1 == t.total();
    if (metadata) {
      p.a[0] = t.meta_base;
      return p;
    }
    const uint64_t astride = t.sparse ? 2 : (t.row_major ? 4 : 0);
    // Later uops do not read these descriptor registers in production.
    p.b[0] = (p.first ? t.b_base : PoisonB) | (uint64_t(t.sparse ? 4 : 0) << 18);
    if (t.shared_a) {
      p.a[0] = (p.first ? t.a_base : PoisonA) | (astride << 18);
    } else {
      for (unsigned row = 0; row < 4; ++row) {
        std::array<int, 4> values{};
        unsigned n = 0;
        for (unsigned k = t.sparse ? 0 : p.k * 4; k < (t.sparse ? 8 : p.k * 4 + 4); ++k) {
          if (t.keep[p.m * 4 + row][k]) {
            values[n++] = t.a[p.m * 4 + row][k];
          }
        }
        require(n == 4, "RS fixture must supply four products");
        for (unsigned pair = 0; pair < 2; ++pair) {
          p.a[row * 2 + pair] = packed(values[2 * pair], values[2 * pair + 1], t.format);
        }
      }
    }
    for (unsigned lane = 0; lane < 8; ++lane) {
      const unsigned row = p.m * 4 + lane / 2, column = p.n * 2 + lane % 2;
      int result = p.k == 0 ? t.c[row][column] : t.result[row][column];
      p.c[lane] = UINT64_C(0xffffffff00000000) | fp32(result);
      for (unsigned k = t.sparse ? 0 : p.k * 4; k < (t.sparse ? 8 : p.k * 4 + 4); ++k) {
        if (t.keep[row][k]) {
          result += t.a[row][k] * t.b[k][column];
        }
      }
      p.expected[lane] = UINT64_C(0xffffffff00000000) | fp32(result);
    }
    return p;
  }
  bool finished() const {
    for (const auto &t : tasks_) {
      if (t.committed != t.total() || (t.sparse && !t.meta_done)) {
        return false;
      }
    }
    return true;
  }
  void select_packets() {
    for (unsigned index = 0; index < tasks_.size(); ++index) {
      auto &t = tasks_[index];
      if (pending_[t.slot] || cycle_ < group_start_ + t.start || t.next == t.total()) {
        continue;
      }
      if (t.wait_for_owner) {
        if ((dut_->observe_resident & 1) == 0 || dut_->observe_owner[0] != 0) {
          continue;
        }
        t.wait_for_owner = false;
      }
      if (t.sparse && !t.meta_done) {
        if (!t.meta_sent) {
          pending_[t.slot] = make_packet(index, true);
        }
        continue;
      }
      if (!t.sparse && t.next >= t.nregs && !t.first_checked[t.next % t.nregs]) {
        continue;
      }
      pending_[t.slot] = make_packet(index, false);
    }
  }
  void drive_packets() {
    dut_->dispatch_valid = dut_->dispatch_wb = dut_->dispatch_a_smem = 0;
    dut_->dispatch_first = dut_->dispatch_last = dut_->dispatch_sop = dut_->dispatch_eop = 0;
    for (unsigned b = 0; b < Slots; ++b) {
      if (!pending_[b]) {
        continue;
      }
      const auto &p = *pending_[b];
      const unsigned bit = 1u << b;
      dut_->dispatch_valid |= bit;
      if (!p.metadata) {
        dut_->dispatch_wb |= bit;
      }
      if (p.shared_a) {
        dut_->dispatch_a_smem |= bit;
      }
      if (p.first) {
        dut_->dispatch_first |= bit;
      }
      if (p.last) {
        dut_->dispatch_last |= bit;
      }
      dut_->dispatch_sop |= bit;
      dut_->dispatch_eop |= bit;
      dut_->dispatch_uuid[b] = p.uuid;
      dut_->dispatch_pc[b] = p.pc;
      dut_->dispatch_wis[b] = p.wis;
      dut_->dispatch_cta[b] = p.cta;
      dut_->dispatch_sid[b] = 0;
      dut_->dispatch_tmask[b] = 255;
      dut_->dispatch_wr_xregs[b] = p.wr_xregs;
      dut_->dispatch_rd[b] = p.rd;
      dut_->dispatch_bytesel[b] = 56;
      dut_->dispatch_op[b] = p.op;
      dut_->dispatch_fmt_s[b] = p.format;
      dut_->dispatch_fmt_d[b] = 0;
      dut_->dispatch_m[b] = p.m;
      dut_->dispatch_n[b] = p.n;
      dut_->dispatch_k[b] = p.k;
      dut_->dispatch_cd_nregs[b] = p.cd_nregs;
      for (unsigned l = 0; l < Lanes; ++l) {
        dut_->dispatch_rs1[b][l] = p.a[l];
        dut_->dispatch_rs2[b][l] = p.b[l];
        dut_->dispatch_rs3[b][l] = p.c[l];
      }
    }
  }
  std::vector<uint64_t> commit_signature(unsigned b) const {
    std::vector<uint64_t> s = {dut_->commit_uuid[b], dut_->commit_pc[b], dut_->commit_wid[b],
                               dut_->commit_cta[b], dut_->commit_sid[b], dut_->commit_tmask[b],
                               uint64_t((dut_->commit_wb >> b) & 1), dut_->commit_wr_xregs[b], dut_->commit_rd[b],
                               dut_->commit_bytesel[b], uint64_t((dut_->commit_sop >> b) & 1), uint64_t((dut_->commit_eop >> b) & 1)};
    for (unsigned l = 0; l < Lanes; ++l) {
      s.push_back(dut_->commit_data[b][l]);
    }
    return s;
  }
  void check_commit(unsigned b) {
    require(!expected_[b].empty(), "unexpected or duplicated commit");
    const auto p = expected_[b].front();
    expected_[b].pop_front();
    auto &t = tasks_[p.task];
    require(dut_->commit_uuid[b] == p.uuid && dut_->commit_pc[b] == p.pc && dut_->commit_wid[b] == p.wis * 4 + b && dut_->commit_cta[b] == p.cta && dut_->commit_sid[b] == 0 && dut_->commit_tmask[b] == 255 && ((dut_->commit_wb >> b) & 1) == !p.metadata && dut_->commit_wr_xregs[b] == p.wr_xregs && dut_->commit_rd[b] == p.rd && dut_->commit_bytesel[b] == 56 && ((dut_->commit_sop >> b) & 1) && ((dut_->commit_eop >> b) & 1), "commit transaction identity changed");
    for (unsigned l = 0; l < Lanes; ++l) {
      if (dut_->commit_data[b][l] != p.expected[l]) {
        std::printf("WGMMA_MISMATCH name=%s slot=%u uop=%u lane=%u actual=%016llx expected=%016llx\n",
                    name_.c_str(), b, p.uop, l, ull(dut_->commit_data[b][l]), ull(p.expected[l]));
        throw std::runtime_error("exact native output mismatch");
      }
      if (!p.metadata) {
        const unsigned row = p.m * 4 + l / 2, column = p.n * 2 + l % 2;
        int value = p.k == 0 ? t.c[row][column] : t.result[row][column];
        for (unsigned k = t.sparse ? 0 : p.k * 4; k < (t.sparse ? 8 : p.k * 4 + 4); ++k) {
          if (t.keep[row][k]) {
            value += t.a[row][k] * t.b[k][column];
          }
        }
        t.result[row][column] = value;
        ++coverage_.words;
      }
    }
    if (p.metadata) {
      require(t.meta_seen == 255, "metadata completion preceded complete lane writes");
      t.meta_done = true;
    } else {
      ++t.committed;
      if (p.k == 0) {
        t.first_checked[p.uop % t.nregs] = true;
      }
    }
    ++coverage_.commits;
  }
  void drive_responses() {
    dut_->lmem_rsp_valid = !lmem_.empty() && lmem_.front().due <= cycle_;
    if (dut_->lmem_rsp_valid) {
      const auto &r = lmem_.front();
      dut_->lmem_rsp_tag = r.tag;
      for (unsigned l = 0; l < Lanes; ++l) {
        dut_->lmem_rsp_data[l] = r.data[l];
      }
    }
    dut_->meta_rsp_valid = !metadata_.empty() && metadata_.front().due <= cycle_;
    if (dut_->meta_rsp_valid) {
      const auto &r = metadata_.front();
      dut_->meta_rsp_mask = r.mask;
      dut_->meta_rsp_sop = r.sop;
      dut_->meta_rsp_eop = r.eop;
      for (unsigned l = 0; l < Lanes; ++l) {
        dut_->meta_rsp_data[l] = r.data[l];
        dut_->meta_rsp_tag[l] = r.tag[l];
      }
    }
  }
  void accept_metadata_request() {
    require(dut_->meta_req_rw == 0 && dut_->meta_req_mask == 255, "invalid metadata request direction/mask");
    unsigned index = tasks_.size();
    for (unsigned i = 0; i < tasks_.size(); ++i) {
      if (tasks_[i].sparse && tasks_[i].meta_base == dut_->meta_req_addr[0] * 8) {
        index = i;
      }
    }
    require(index < tasks_.size(), "unknown metadata address");
    const auto &t = tasks_[index];
    Words tag{};
    Lanes64 data{};
    for (unsigned l = 0; l < Lanes; ++l) {
      require(dut_->meta_req_addr[l] == t.meta_base / 8 + l / 2 && dut_->meta_req_byteen[l] == 255 && dut_->meta_req_attr[l] == 0,
              "metadata lane address, byte-enable, or attribute mismatch");
      tag[l] = dut_->meta_req_tag[l];
      data[l] = t.metadata[(l / 2) * 2] | (uint64_t(t.metadata[(l / 2) * 2 + 1]) << 32);
    }
    require((tag[0] & 3) == t.slot, "metadata response tag lost TCU routing bits");
    metadata_.push_back({cycle_ + 13, tag, data, 0x55, index, true, false});
    metadata_.push_back({cycle_ + 14, tag, data, 0xaa, index, false, true});
    ++coverage_.metadata_requests;
    ++coverage_.delayed_metadata;
  }
  void check_metadata_writes() {
    for (unsigned b = 0; b < Slots; ++b) {
      if (((dut_->observe_meta_write >> b) & 1) == 0) {
        continue;
      }
      require(dut_->meta_rsp_valid && dut_->meta_rsp_ready && !metadata_.empty(), "unexpected metadata SRAM write");
      auto &t = tasks_[metadata_.front().task];
      const unsigned mask = metadata_.front().mask;
      require(b == t.slot && dut_->observe_meta_wid[b] == t.wis * 4 + b && dut_->observe_meta_idx[b] == 0 && dut_->observe_meta_mask[b] == mask,
              "metadata SRAM warp, slot, or lane mask mismatch");
      require((t.meta_seen & mask) == 0, "metadata lane duplicated");
      for (unsigned l = 0; l < Lanes; ++l) {
        if ((mask >> l) & 1) {
          require(dut_->observe_meta_data[b][l] == t.metadata[l], "metadata SRAM value mismatch");
          ++coverage_.metadata_lanes;
        }
      }
      t.meta_seen |= mask;
      ++coverage_.metadata_writes;
    }
  }
  void check_pressure() {
    const unsigned bit = 1u << pressure_slot_;
    if (!options_.force_pressure || !pressure_started_ || (dut_->commit_ready & bit)) {
      return;
    }
    require((dut_->commit_valid & dut_->commit_wb & bit) != 0,
            "pressure window lost its pending compute commit");
    require(!dut_->meta_req_valid && !dut_->observe_meta_write,
            "metadata activity contaminated the compute pressure window");
    ++coverage_.pressure_holds;
    const unsigned qualified = dut_->observe_result_valid & ~dut_->observe_result_ready & dut_->observe_result_wb & dut_->observe_exec_valid & ~dut_->observe_exec_ready & dut_->observe_tbuf_ready & ~dut_->observe_conflict & dut_->observe_admission_blocked & dut_->dispatch_valid & ~dut_->dispatch_ready;
    if (qualified & bit) {
      ++coverage_.pressure_qualified;
      if (!pressure_seen_) {
        pressure_seen_ = true;
        pressure_first_ = cycle_;
        pressure_release_ = cycle_ + 9;
      }
    }
    if (pressure_seen_ && cycle_ > pressure_first_) {
      ++coverage_.pressure_tail;
    }
  }
  void step() {
    require(cycle_ - group_start_ < CycleLimit, "100000-cycle watchdog expired");
    select_packets();
    drive_packets();
    drive_responses();
    dut_->clk = 0;
    dut_->commit_ready = 15;
    dut_->lmem_req_ready = 1;
    dut_->meta_req_ready = 1;
    dut_->eval();
    if (options_.hold_memory && !memory_hold_started_ && dut_->lmem_req_valid) {
      memory_hold_started_ = true;
      memory_hold_end_ = cycle_ + 8;
    }
    if (options_.hold_commit && !commit_hold_started_ && dut_->commit_valid) {
      commit_hold_started_ = true;
      commit_hold_end_ = cycle_ + 8;
    }
    const unsigned pressure_bit = 1u << pressure_slot_;
    if (options_.force_pressure && !pressure_started_ && (dut_->commit_valid & dut_->commit_wb & pressure_bit)) {
      pressure_started_ = true;
      pressure_start_ = cycle_;
    }
    if (cycle_ < memory_hold_end_) {
      dut_->lmem_req_ready = 0;
    }
    if (cycle_ < commit_hold_end_) {
      dut_->commit_ready = 0;
    }
    if (options_.force_pressure && pressure_started_ && (!pressure_seen_ || cycle_ < pressure_release_)) {
      require(cycle_ - pressure_start_ < PressureLimit,
              "256-cycle compute pressure deadline expired");
      dut_->commit_ready &= ~pressure_bit;
    }
    dut_->eval();
    check_pressure();

    for (unsigned b = 0; b < Slots; ++b) {
      const bool valid = (dut_->commit_valid >> b) & 1, ready = (dut_->commit_ready >> b) & 1;
      if (held_commit_[b]) {
        require(valid && *held_commit_[b] == commit_signature(b), "blocked commit payload was not stable");
      }
      if (valid && !ready) {
        held_commit_[b] = commit_signature(b);
        ++coverage_.commit_holds;
      } else {
        held_commit_[b].reset();
      }
      if (valid && ready) {
        check_commit(b);
      }
      if (((dut_->dispatch_valid >> b) & 1) && !((dut_->dispatch_ready >> b) & 1)) {
        ++coverage_.dispatch_stalls;
      }
      if (((dut_->dispatch_valid & dut_->dispatch_ready) >> b) & 1) {
        require(bool(pending_[b]), "accepted dispatch has no transaction");
        const auto p = *pending_[b];
        expected_[b].push_back(p);
        pending_[b].reset();
        if (p.metadata) {
          tasks_[p.task].meta_sent = true;
        } else {
          ++tasks_[p.task].next;
        }
        if (!p.metadata && !p.first) {
          ++coverage_.descriptor_b_poisoned;
          if (p.shared_a) {
            ++coverage_.descriptor_a_poisoned;
          }
        }
        ++coverage_.accepted;
      }
      if ((dut_->observe_conflict >> b) & 1) {
        ++coverage_.cta_conflicts;
        require(!((dut_->observe_exec_valid & dut_->observe_exec_ready) >> b & 1), "conflicting CTA executed");
      }
      if (((dut_->observe_exec_valid & dut_->observe_exec_ready & dut_->observe_first) >> b & 1) && dut_->observe_cta[b] == 1) {
        ++coverage_.cta_entries;
      }
    }
    if (__builtin_popcount(unsigned(dut_->observe_resident)) > 1) {
      ++coverage_.overlapping;
    }
    std::array<uint64_t, 4> request = {dut_->lmem_req_addr, dut_->lmem_req_tag, dut_->lmem_req_attr, dut_->lmem_req_rw};
    if (held_lmem_) {
      require(dut_->lmem_req_valid && *held_lmem_ == request, "blocked LMEM request was not stable");
    }
    if (dut_->lmem_req_valid && !dut_->lmem_req_ready) {
      held_lmem_ = request;
      ++coverage_.lmem_holds;
    } else {
      held_lmem_.reset();
    }
    check_metadata_writes();
    if (dut_->lmem_rsp_valid && dut_->lmem_rsp_ready) {
      lmem_.pop_front();
      ++coverage_.lmem_responses;
    }
    if (dut_->meta_rsp_valid && dut_->meta_rsp_ready) {
      metadata_.pop_front();
    }
    if (dut_->lmem_req_valid && dut_->lmem_req_ready) {
      require(dut_->lmem_req_rw == 0, "LMEM request unexpectedly writes");
      Lanes64 data{};
      const unsigned address = dut_->lmem_req_addr * 64;
      for (unsigned l = 0; l < Lanes; ++l) {
        data[l] = read64(address + l * 8);
      }
      const uint64_t delay = options_.hold_memory ? 11 : 1;
      lmem_.push_back({cycle_ + delay, dut_->lmem_req_tag, data});
      ++coverage_.lmem_requests;
      if (delay == 11) {
        ++coverage_.delayed_lmem;
      }
    }
    if (dut_->meta_req_valid && dut_->meta_req_ready) {
      accept_metadata_request();
    }
    context_->timeInc(1);
    dut_->clk = 1;
    dut_->eval();
    context_->timeInc(1);
    ++cycle_;
    require(!context_->gotFinish(), "RTL requested unexpected finish");
  }

  std::string name_;
  std::unique_ptr<VerilatedContext> context_;
  std::unique_ptr<VVX_tcu_wgmma_top> dut_;
  std::array<uint8_t, 16384> memory_{};
  std::vector<Task> tasks_;
  std::array<std::optional<Packet>, 4> pending_{};
  std::array<std::deque<Packet>, 4> expected_{};
  std::array<std::optional<std::vector<uint64_t>>, 4> held_commit_{};
  std::optional<std::array<uint64_t, 4>> held_lmem_;
  std::deque<LmemResponse> lmem_;
  std::deque<MetaResponse> metadata_;
  uint64_t cycle_ = 0, group_start_ = 0, next_uuid_ = 1;
  uint64_t memory_hold_end_ = 0, commit_hold_end_ = 0;
  bool memory_hold_started_ = false, commit_hold_started_ = false;
  unsigned pressure_slot_ = 0;
  uint64_t pressure_start_ = 0, pressure_first_ = 0, pressure_release_ = 0;
  bool pressure_started_ = false, pressure_seen_ = false;
  Options options_{};
  Coverage coverage_{};
};

Coverage add(Coverage a, const Coverage &b) {
#define ADD(field) a.field += b.field
  ADD(accepted);
  ADD(commits);
  ADD(words);
  ADD(dispatch_stalls);
  ADD(commit_holds);
  ADD(lmem_holds);
  ADD(lmem_requests);
  ADD(lmem_responses);
  ADD(delayed_lmem);
  ADD(metadata_requests);
  ADD(metadata_writes);
  ADD(metadata_lanes);
  ADD(delayed_metadata);
  ADD(cta_conflicts);
  ADD(cta_entries);
  ADD(overlapping);
  ADD(pressure_holds);
  ADD(pressure_qualified);
  ADD(pressure_tail);
  ADD(descriptor_a_poisoned);
  ADD(descriptor_b_poisoned);
  ADD(cycles);
#undef ADD
  return a;
}

Coverage scenarios() {
  Coverage total{};
  {
    Harness h("dense_ss_initial");
    std::vector<Task> tasks;
    for (unsigned b = 0; b < 4; ++b) {
      tasks.push_back(make_task(b, 0, 0, 0, true, false, false, 2, b * 5));
    }
    auto previous = h.run(tasks, {true, true, false});
    tasks.clear();
    for (unsigned b = 0; b < 4; ++b) {
      auto t = make_task(b, 0, 0, 1);
      t.c = previous[b].result;
      tasks.push_back(t);
    }
    h.run(tasks, {}, "dense_ss_descriptor_reuse");
    tasks.clear();
    for (unsigned b = 0; b < 4; ++b) {
      tasks.push_back(make_task(b, 0, 0, 2, true, true, false, 2, b * 3, 0x1000));
    }
    h.run(tasks, {}, "dense_ss_row_major");
    require(h.coverage().overlapping > 0, "multiple warp expansions were never resident");
    total = add(total, h.coverage());
  }
  {
    Harness h("dense_rs_bf16");
    std::vector<Task> tasks;
    for (unsigned b = 0; b < 4; ++b) {
      tasks.push_back(make_task(b, 0, 0, 3, false, false, false, 3, b * 4));
    }
    h.run(tasks, {true, true, false});
    total = add(total, h.coverage());
  }
  {
    Harness h("cta_exclusion");
    auto first = make_task(0, 0, 0, 4);
    auto second = make_task(1, 1, 1, 5);
    second.wait_for_owner = true;
    h.run({first, second}, {false, true, true});
    total = add(total, h.coverage());
  }
  {
    Harness h("sparse_metadata_initial");
    std::vector<Task> tasks;
    for (unsigned b = 0; b < 4; ++b) {
      tasks.push_back(make_task(b, 0, 0, 6, true, true, true, 2, b * 3));
    }
    auto previous = h.run(tasks, {true, true, false});
    tasks.clear();
    for (unsigned b = 0; b < 4; ++b) {
      auto t = make_task(b, 0, 0, 7, false, true, true);
      t.c = previous[b].result;
      tasks.push_back(t);
    }
    h.run(tasks, {}, "sparse_metadata_reload");
    require(h.coverage().metadata_requests == 8 && h.coverage().metadata_writes == 16 && h.coverage().metadata_lanes == 64, "metadata reload coverage incomplete");
    total = add(total, h.coverage());
  }
  {
    Harness h("dense_rs_commit_pressure");
    h.run({make_task(0, 0, 0, 8, false, false, false, 2, 0, 0, 16)},
          {false, false, false, true});
    total = add(total, h.coverage());
  }
  require(total.accepted == 392 && total.commits == 392 && total.words == 3072 && total.dispatch_stalls > 0,
          "dispatch/commit coverage incomplete");
  require(total.descriptor_a_poisoned == 238 && total.descriptor_b_poisoned == 357,
          "descriptor latch coverage incomplete");
  require(total.lmem_requests == total.lmem_responses && total.cta_conflicts > 0 && total.overlapping > 0 && total.delayed_metadata > 0, "memory/concurrency coverage incomplete");
  return total;
}
} // namespace

int main(int argc, char **argv) {
  if (argc != 2 || std::string(argv[1]) != "--all") {
    std::fprintf(stderr, "usage: tcu_wgmma --all\n");
    return 2;
  }
  try {
    const auto c = scenarios();
    std::printf("WGMMA_COVERAGE accepted=%llu commits=%llu words=%llu dispatch_stalls=%llu commit_holds=%llu lmem_holds=%llu lmem_requests=%llu lmem_responses=%llu delayed_lmem=%llu metadata_requests=%llu metadata_writes=%llu metadata_lanes=%llu delayed_metadata=%llu cta_conflicts=%llu cta_entries=%llu overlapping=%llu pressure_holds=%llu pressure_qualified=%llu pressure_tail=%llu descriptor_a_poisoned=%llu descriptor_b_poisoned=%llu cycles=%llu watchdog=%llu pressure_limit=%llu\n",
                static_cast<unsigned long long>(c.accepted), static_cast<unsigned long long>(c.commits),
                static_cast<unsigned long long>(c.words), static_cast<unsigned long long>(c.dispatch_stalls),
                static_cast<unsigned long long>(c.commit_holds), static_cast<unsigned long long>(c.lmem_holds),
                static_cast<unsigned long long>(c.lmem_requests), static_cast<unsigned long long>(c.lmem_responses),
                static_cast<unsigned long long>(c.delayed_lmem), static_cast<unsigned long long>(c.metadata_requests),
                static_cast<unsigned long long>(c.metadata_writes), static_cast<unsigned long long>(c.metadata_lanes),
                static_cast<unsigned long long>(c.delayed_metadata), static_cast<unsigned long long>(c.cta_conflicts),
                static_cast<unsigned long long>(c.cta_entries), static_cast<unsigned long long>(c.overlapping),
                static_cast<unsigned long long>(c.pressure_holds), static_cast<unsigned long long>(c.pressure_qualified),
                static_cast<unsigned long long>(c.pressure_tail), static_cast<unsigned long long>(c.descriptor_a_poisoned),
                static_cast<unsigned long long>(c.descriptor_b_poisoned), static_cast<unsigned long long>(c.cycles),
                static_cast<unsigned long long>(CycleLimit), static_cast<unsigned long long>(PressureLimit));
    std::puts("WGMMA_DIRECTED_PASS");
    return 0;
  } catch (const std::exception &e) {
    std::fprintf(stderr, "WGMMA_DIRECTED_FAIL: %s\n", e.what());
    return 1;
  }
}
