// SPDX-License-Identifier: Apache-2.0
#define main p06_unchanged_warm_main
#include "../ai_warm_workspace/main.cpp"
#undef main

#include "hooks.h"
#include "../../../sw/runtime/common/vortex2_internal.h"

#include <link.h>
#include <limits>
#include <stdexcept>
#include <utility>

#if !defined(SIMX_CHECKED_COUNTERS) || (SIMX_CHECKED_COUNTERS + 0) != 1
#error "Managed counter preflight requires checked counters"
#endif
static_assert(VX_CFG_XLEN == 64);

extern "C" vx_result_t __real_vx_device_mpm_query(
    vx_device_h, uint32_t, uint32_t, uint32_t, uint64_t*);

namespace managed_preflight {
namespace {

namespace hooks = p06_preflight;

constexpr size_t kSelectors = 33;
constexpr size_t kSnapshots = 4;
constexpr size_t kHalfReads = 2 * kSelectors * kSnapshots;
constexpr size_t kCacheFlushReads = 33;
constexpr const char* kNames[] = {"after_open", "after_prime", "after_batch", "before_release"};
constexpr const char* kLibraries[] = {
  "libramulator-vortex.so", "libramulator.so", "libsimx.so", "libvortex-simx.so", "libvortex.so"
};

template <typename Tag, auto Member>
struct MemberAccess {
  friend constexpr auto member(Tag) noexcept { return Member; }
};

struct Queues { friend constexpr auto member(Queues) noexcept; };
struct Buffers { friend constexpr auto member(Buffers) noexcept; };
struct CpExpected { friend constexpr auto member(CpExpected) noexcept; };
struct CpTail { friend constexpr auto member(CpTail) noexcept; };
struct CpHead { friend constexpr auto member(CpHead) noexcept; };
template struct MemberAccess<Queues, &vx::Device::queues_>;
template struct MemberAccess<Buffers, &vx::Device::buffers_>;
template struct MemberAccess<CpExpected, &vx::Device::cp_expected_seqnum_>;
template struct MemberAccess<CpTail, &vx::Device::cp_tail_>;
template struct MemberAccess<CpHead, &vx::Device::cp_head_>;

struct CpState {
  uint32_t control = 0;
  uint32_t queue_control = 0;
  uint32_t status = 0;
  uint32_t error = 0;
  uint32_t retired = 0;
  uint64_t expected = 0;
  uint64_t head_writeback_raw = 0;
  uint64_t runtime_tail = 0;
  uint64_t tail_register_pair_raw = 0;
};

struct Snapshot {
  hooks::ModelState before;
  hooks::ModelState after;
  uint64_t read_begin = 0;
  uint64_t read_end = 0;
  uint64_t cache_flush_count = 0;
  uint32_t device_refs = 0;
  size_t queues = 0;
  size_t buffers = 0;
  CpState cp_before;
  CpState cp_after;
};

struct LoadedLibraries {
  std::array<std::string, 5> paths;
  bool failed = false;
};

struct State {
  std::array<Snapshot, kSnapshots> snapshots;
  LoadedLibraries libraries;
  vx_device_h device = nullptr;
  size_t queries = 0;
  bool failed = false;
  bool lifetime = false;
  bool qualified_warm = false;
};

State state;

void require(bool value, const char* reason) {
  if (!value) {
    throw std::runtime_error(reason);
  }
}

const char* boolean(bool value) noexcept { return value ? "true" : "false"; }

bool same_model(const hooks::ModelState& left, const hooks::ModelState& right) noexcept {
  return left.live == right.live && left.idle == right.idle
      && left.any_running == right.any_running && left.generation == right.generation
      && left.ticks == right.ticks && left.reset_generation == right.reset_generation
      && left.core_cycles == right.core_cycles && left.core_instructions == right.core_instructions
      && left.exitcode == right.exitcode && left.pending_reads == right.pending_reads;
}

hooks::ModelState model() {
  hooks::ModelState result;
  require(p06_preflight_get_model_state(&result) == 0, "model observation failed");
  require(result.live && result.generation == 1 && result.idle && !result.any_running,
          "counter snapshot requires one idle native processor");
  require(!state.lifetime || result.pending_reads == 0,
          "counter snapshot has pending memory reads");
  return result;
}

hooks::Observation observation() {
  hooks::Observation result;
  require(p06_preflight_get_observation(&result) == 0, "backend observation failed");
  require(result.run_errors == 0 && result.dcr_read_errors == 0 && result.dcr_write_errors == 0
      && result.overflow_errors == 0 && result.underflow_errors == 0
      && result.negative_operand_errors == 0 && result.unexpected_errors == 0
      && result.violations == 0, "backend observation contains an error");
  return result;
}

bool canonical_path(const std::string& path) {
  if (path.empty() || path.size() > 4096 || path.front() != '/' || path.back() == '/') {
    return false;
  }
  size_t start = 1;
  for (size_t i = 1; i <= path.size(); ++i) {
    if (i == path.size() || path[i] == '/') {
      const auto part = path.substr(start, i - start);
      if (part.empty() || part == "." || part == "..") {
        return false;
      }
      start = i + 1;
    } else {
      const char c = path[i];
      if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
          || (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '+' || c == '-')) {
        return false;
      }
    }
  }
  return true;
}

int loaded_object(dl_phdr_info* info, size_t, void* opaque) noexcept {
  auto& result = *static_cast<LoadedLibraries*>(opaque);
  try {
    const std::string path = info->dlpi_name ? info->dlpi_name : "";
    const auto slash = path.find_last_of('/');
    const auto name = path.substr(slash == std::string::npos ? 0 : slash + 1);
    for (size_t i = 0; i != result.paths.size(); ++i) {
      if (name == kLibraries[i]) {
        if (!result.paths[i].empty() || !canonical_path(path)) {
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

LoadedLibraries loaded_libraries() {
  LoadedLibraries result;
  require(dl_iterate_phdr(loaded_object, &result) == 0 && !result.failed,
          "loaded library observation failed");
  require(std::all_of(result.paths.begin(), result.paths.end(),
                     [](const std::string& path) { return !path.empty(); }),
          "required native library is not loaded");
  return result;
}

uint32_t cp_read(vx::Device& device, uint32_t address) {
  uint32_t result = 0xffffffffu;
  require(device.platform()->cp_reg_read(address, &result) == VX_SUCCESS,
          "terminal CP register observation failed");
  return result;
}

CpState terminal_cp(vx::Device& device) {
  require(device.refs() == 1 && (device.*member(Queues{})).empty()
      && (device.*member(Buffers{})).empty() && device.cp_enabled(),
          "terminal CP requires exclusive ownership before disable");
  CpState result;
  result.control = cp_read(device, 0x000);
  result.queue_control = cp_read(device, 0x11c);
  result.status = cp_read(device, 0x004);
  result.error = cp_read(device, 0x12c);
  result.retired = cp_read(device, 0x128);
  result.expected = device.*member(CpExpected{});
  result.runtime_tail = device.*member(CpTail{});
  const uint64_t low = cp_read(device, 0x120);
  const uint64_t high = cp_read(device, 0x124);
  result.tail_register_pair_raw = low | (high << 32);
  const auto& head = device.*member(CpHead{});
  require(head.host_ptr && head.size >= sizeof(result.head_writeback_raw),
          "terminal CP head storage is absent");
  require(device.platform()->host_mem_pull(head.cp_addr) == VX_SUCCESS,
          "terminal CP head storage observation failed");
  std::memcpy(&result.head_writeback_raw, head.host_ptr, sizeof(result.head_writeback_raw));
  // This CP does not publish head writeback; the tail pair includes staged low bits.
  require(result.head_writeback_raw == 0 && result.control == 1 && result.queue_control == 1
      && result.status == 0 && result.error == 0 && result.expected > 0
      && result.expected <= std::numeric_limits<uint32_t>::max()
      && result.retired == result.expected && result.runtime_tail == result.expected * 64
      && result.tail_register_pair_raw == result.runtime_tail,
          "enabled CP retirement or raw storage is inconsistent");
  return result;
}

const p06::Counter& descriptor(size_t selected) {
  size_t index = 0;
  for (const auto& counter : p06::kCounters) {
    if (counter.required_isa == VX_ISA_EXT_L2CACHE || counter.required_isa == VX_ISA_EXT_L3CACHE) {
      continue;
    }
    if (index++ == selected) {
      return counter;
    }
  }
  throw std::runtime_error("counter selector inventory is incomplete");
}

void check_half(size_t index, const p06::Counter& counter, bool high, uint32_t expected) {
  hooks::DcrRead read;
  require(p06_preflight_get_read(index, &read) == 0, "raw counter reply is absent");
  const uint32_t offset = counter.csr - VX_CSR_MPM_BASE + (high ? 32u : 0u);
  const uint32_t tag = (counter.mpm_class << 22) | (offset << 16) | counter.core_id;
  const size_t sample = index / (2 * kSelectors);
  const uint64_t runs = sample == 0 ? 0 : (sample == 1 ? 1 : 33);
  require(read.sequence == index + 1 + runs && read.generation == 1 && read.completed_runs == runs
      && read.addr == VX_DCR_BASE_MPM_VALUE && read.tag == tag && read.value == expected
      && read.status == 0 && read.completed && !read.overflow
      && read.ticks_before == read.ticks_after && read.reset_before == read.reset_after
      && read.class_before == read.class_after && read.idle_before && read.idle_after
      && !read.any_running_before && !read.any_running_after,
          "raw counter reply differs from its public query");
}

void check_cache_flush(size_t index) {
  hooks::DcrRead read;
  require(p06_preflight_get_cache_flush_read(index, &read) == 0,
          "cache-flush reply is absent");
  const uint64_t runs = index + 1;
  const uint64_t sequence = runs == 1 ? 2 * kSelectors + 1 : 4 * kSelectors + runs;
  require(read.sequence == sequence && read.generation == 1 && read.completed_runs == runs
      && read.addr == VX_DCR_BASE_CACHE_FLUSH && read.tag == 0 && read.value == 0
      && read.status == 0 && read.completed && !read.overflow
      && read.ticks_after >= read.ticks_before && read.reset_before == read.reset_after
      && read.class_before == read.class_after && read.idle_before && read.idle_after
      && !read.any_running_before && !read.any_running_after,
          "cache-flush reply differs from its completed managed operation");
}

vx_result_t query(vx_device_h handle, uint32_t clss, uint32_t csr, uint32_t core, uint64_t* value) {
  require(!state.failed && handle && value && state.queries < kSelectors * kSnapshots,
          "unexpected managed preflight counter query");
  if (state.queries == 0) {
    state.device = handle;
    state.libraries = loaded_libraries();
  }
  require(state.device == handle, "counter queries changed device ownership");
  const auto& expected = descriptor(state.queries % kSelectors);
  require(clss == expected.mpm_class && csr == expected.csr && core == expected.core_id,
          "counter query changes the exact available selector order");
  const size_t sample = state.queries / kSelectors;
  auto& snapshot = state.snapshots[sample];
  auto& device = *vx::to_device(handle);
  const auto before = observation();
  const uint64_t runs = sample == 0 ? 0 : (sample == 1 ? 1 : 33);
  require(before.read_count == state.queries * 2 && before.cache_flush_count == runs
      && before.dcr_read_entries == before.read_count + before.cache_flush_count,
          "unexpected raw reads precede a public query");
  if (state.queries % kSelectors == 0) {
    snapshot.before = model();
    snapshot.read_begin = before.read_count;
    snapshot.cache_flush_count = before.cache_flush_count;
    snapshot.device_refs = device.refs();
    snapshot.queues = (device.*member(Queues{})).size();
    snapshot.buffers = (device.*member(Buffers{})).size();
    require(before.run_entries == runs && before.run_completed == runs && snapshot.queues == 0,
            "snapshot precedes complete managed operations");
    if (sample == kSnapshots - 1) {
      snapshot.cp_before = terminal_cp(device);
    }
  }
  const auto result = __real_vx_device_mpm_query(handle, clss, csr, core, value);
  require(result == VX_SUCCESS, "native public counter query failed");
  const auto after = observation();
  require(after.read_count == (state.queries + 1) * 2 && after.cache_flush_count == runs
      && after.dcr_read_entries == after.read_count + after.cache_flush_count,
          "public counter query did not produce exactly two raw replies");
  check_half(state.queries * 2, expected, false, static_cast<uint32_t>(*value));
  check_half(state.queries * 2 + 1, expected, true, static_cast<uint32_t>(*value >> 32));
  require(sample != 0 || *value == 0, "opening counter aggregate is not zero");
  ++state.queries;
  if (state.queries % kSelectors == 0) {
    snapshot.read_end = after.read_count;
    if (sample == kSnapshots - 1) {
      snapshot.cp_after = terminal_cp(device);
      require(snapshot.cp_after.expected - snapshot.cp_before.expected == 2 * kSelectors,
              "terminal snapshot did not retire exactly its counter reads");
    }
    snapshot.after = model();
    require(same_model(snapshot.before, snapshot.after)
        && snapshot.device_refs == device.refs()
        && snapshot.queues == (device.*member(Queues{})).size()
        && snapshot.buffers == (device.*member(Buffers{})).size(),
            "model or ownership changed across the counter snapshot");
  }
  return result;
}

void print_model(const hooks::ModelState& value, bool lifetime = false) {
  std::printf("{\"live\":%s,\"idle\":%s,\"any_running\":%s,\"generation\":%" PRIu64
      ",\"ticks\":%" PRIu64 ",\"reset_generation\":%" PRIu64 ",\"core_cycles\":%" PRIu64
      ",\"core_instructions\":%" PRIu64 ",\"exitcode\":%d", boolean(value.live),
      boolean(value.idle), boolean(value.any_running), value.generation, value.ticks,
      value.reset_generation, value.core_cycles, value.core_instructions, value.exitcode);
  if (lifetime) {
    std::printf(",\"pending_reads\":%" PRIu64, value.pending_reads);
  }
  std::fputc('}', stdout);
}

void print_cp(const CpState& value) {
  std::printf("{\"control\":%u,\"queue_control\":%u,\"status\":%u,\"error\":%u,"
      "\"retired\":%u,\"expected\":%" PRIu64 ",\"head_writeback_raw\":%" PRIu64
      ",\"head_writeback_status\":\"not-published\",\"runtime_tail\":%" PRIu64
      ",\"tail_register_pair_raw\":%" PRIu64
      ",\"drain_basis\":\"enabled-idle-status-and-retired-sequence\"}",
      value.control, value.queue_control, value.status, value.error, value.retired,
      value.expected, value.head_writeback_raw, value.runtime_tail, value.tail_register_pair_raw);
}

void print_observation(const hooks::Observation& value) {
  const std::pair<const char*, uint64_t> counters[] = {
    {"constructed", value.constructed}, {"destroyed", value.destroyed},
    {"constructor_entries", value.constructor_entries}, {"destructor_entries", value.destructor_entries},
    {"run_entries", value.run_entries}, {"run_completed", value.run_completed},
    {"run_errors", value.run_errors}, {"dcr_read_entries", value.dcr_read_entries},
    {"dcr_read_completed", value.dcr_read_completed}, {"dcr_read_errors", value.dcr_read_errors},
    {"dcr_write_entries", value.dcr_write_entries}, {"dcr_write_completed", value.dcr_write_completed},
    {"dcr_write_errors", value.dcr_write_errors}, {"overflow_errors", value.overflow_errors},
    {"underflow_errors", value.underflow_errors}, {"negative_operand_errors", value.negative_operand_errors},
    {"unexpected_errors", value.unexpected_errors}, {"violations", value.violations},
    {"generation", value.generation}, {"read_count", value.read_count},
    {"cache_flush_count", value.cache_flush_count},
  };
  std::fputc('{', stdout);
  for (size_t i = 0; i != sizeof(counters) / sizeof(counters[0]); ++i) {
    std::printf("%s\"%s\":%" PRIu64, i ? "," : "", counters[i].first, counters[i].second);
  }
  std::printf(",\"live\":%s,\"constructed_state\":", boolean(value.live));
  print_model(value.constructed_state);
  std::fputs(",\"destruction\":{\"before\":", stdout);
  print_model(value.destruction.before);
  std::printf(",\"completed\":%s,\"ticks_after\":%" PRIu64 ",\"reset_after\":%" PRIu64
      ",\"idle_after\":%s}}", boolean(value.destruction.completed), value.destruction.ticks_after,
      value.destruction.reset_after, boolean(value.destruction.idle_after));
}

void print_read(const hooks::DcrRead& read) {
  std::printf("{\"sequence\":%" PRIu64 ",\"generation\":%" PRIu64
      ",\"completed_runs\":%" PRIu64
      ",\"addr\":%u,\"tag\":%u,\"value\":%u,\"status\":%d,"
      "\"completed\":%s,\"overflow\":%s,\"ticks_before\":%" PRIu64
      ",\"ticks_after\":%" PRIu64 ",\"reset_before\":%" PRIu64
      ",\"reset_after\":%" PRIu64 ",\"class_before\":%u,\"class_after\":%u,"
      "\"idle_before\":%s,\"idle_after\":%s,\"any_running_before\":%s,\"any_running_after\":%s}",
      read.sequence, read.generation, read.completed_runs, read.addr, read.tag, read.value, read.status,
      boolean(read.completed), boolean(read.overflow), read.ticks_before, read.ticks_after,
      read.reset_before, read.reset_after, read.class_before, read.class_after,
      boolean(read.idle_before), boolean(read.idle_after),
      boolean(read.any_running_before), boolean(read.any_running_after));
}

void print_witness(const Options& opts, const char* format, const hooks::Observation& observed) {
  std::printf("P06_MANAGED_COUNTER_WITNESS {\"schema_version\":1,"
      "\"contract_id\":\"%s\","
      "\"process_id\":\"%s\",\"sample_id\":\"%s\","
      "\"execution_binding_sha256\":\"%s\",\"format\":\"%s\",\"policy\":\"%s\","
      "\"backend\":\"simx\",\"xlen\":64,\"checked_counter_bits\":64,"
      "\"simulation_workers\":1,\"seeded\":false,\"observation\":",
      state.qualified_warm ? "p06-qualified-warm-counter-witness-v1" : "p06-managed-counter-preflight-v1",
      (state.qualified_warm ? opts.sample_id
          : std::string("preflight-simx-") + format + "-" + opts.policy).c_str(),
      opts.sample_id.c_str(), opts.qualification_id.c_str(),
      format, opts.policy.c_str());
  print_observation(observed);
  std::fputs(",\"snapshots\":[", stdout);
  for (size_t i = 0; i != kSnapshots; ++i) {
    const auto& snapshot = state.snapshots[i];
    std::printf("%s{\"name\":\"%s\",\"before\":", i ? "," : "", kNames[i]);
    print_model(snapshot.before);
    std::fputs(",\"after\":", stdout);
    print_model(snapshot.after);
    std::printf(",\"read_begin\":%" PRIu64 ",\"read_end\":%" PRIu64
        ",\"cache_flush_count\":%" PRIu64 ",\"device_refs\":%u,"
        "\"queues\":%zu,\"buffers\":%zu,\"cp_before\":", snapshot.read_begin, snapshot.read_end,
        snapshot.cache_flush_count,
        snapshot.device_refs, snapshot.queues, snapshot.buffers);
    if (i == kSnapshots - 1) { print_cp(snapshot.cp_before); } else { std::fputs("null", stdout); }
    std::fputs(",\"cp_after\":", stdout);
    if (i == kSnapshots - 1) { print_cp(snapshot.cp_after); } else { std::fputs("null", stdout); }
    std::fputc('}', stdout);
  }
  std::fputs("],\"reads\":[", stdout);
  for (size_t i = 0; i != kHalfReads; ++i) {
    hooks::DcrRead read;
    require(p06_preflight_get_read(i, &read) == 0, "retained raw read disappeared");
    if (i) { std::fputc(',', stdout); }
    print_read(read);
  }
  std::fputs("],\"cache_flush_reads\":[", stdout);
  for (size_t i = 0; i != kCacheFlushReads; ++i) {
    hooks::DcrRead read;
    require(p06_preflight_get_cache_flush_read(i, &read) == 0, "retained cache-flush read disappeared");
    if (i) { std::fputc(',', stdout); }
    print_read(read);
  }
  std::fputs("],\"loaded_libraries\":[", stdout);
  for (size_t i = 0; i != state.libraries.paths.size(); ++i) {
    std::printf("%s{\"name\":\"%s\",\"path\":\"%s\"}", i ? "," : "",
        kLibraries[i], state.libraries.paths[i].c_str());
  }
  std::fputs("],\"unresolved_obligations\":[\"all_40_component_lifetime_and_pending_balance\","
      "\"dependency_source_to_loaded_binary_provenance\",\"independent_complete_counter_qualification\"],"
      "\"qualified\":false,\"ready_for_warm\":false,\"warm_execution\":false,"
      "\"full_warm_coverage\":false,\"acceptance_claimed\":false,\"phase_acceptance\":false,"
      "\"performance_acceptance\":false}\n", stdout);
}

void print_pending_read(const hooks::DcrRead& read) {
  std::printf("{\"sequence\":%" PRIu64 ",\"pending_before\":%" PRIu64
      ",\"pending_after\":%" PRIu64 "}", read.sequence, read.pending_before, read.pending_after);
}

void print_lifetime(const Options& opts, const char* format, const hooks::Observation& observed) {
  std::printf("P06_MANAGED_COUNTER_LIFETIME {\"schema_version\":1,"
      "\"contract_id\":\"%s\","
      "\"process_id\":\"%s\",\"sample_id\":\"%s\","
      "\"execution_binding_sha256\":\"%s\",\"format\":\"%s\",\"policy\":\"%s\","
      "\"backend\":\"simx\",\"xlen\":64,\"checked_counter_bits\":64,"
      "\"simulation_workers\":1,\"seeded\":false,\"constructed_state\":",
      state.qualified_warm ? "p06-qualified-warm-lifetime-witness-v1" : "p06-managed-counter-lifetime-v1",
      (state.qualified_warm ? opts.sample_id
          : std::string("preflight-simx-") + format + "-" + opts.policy).c_str(),
      opts.sample_id.c_str(), opts.qualification_id.c_str(),
      format, opts.policy.c_str());
  print_model(observed.constructed_state, true);
  std::fputs(",\"runs\":[", stdout);
  for (size_t i = 0; i != hooks::kMaxRuns; ++i) {
    hooks::RunObservation run;
    require(p06_preflight_get_run(i, &run) == 0, "retained run boundary disappeared");
    std::printf("%s{\"ordinal\":%" PRIu64 ",\"before\":", i ? "," : "", run.ordinal);
    print_model(run.before, true);
    std::fputs(",\"after\":", stdout);
    print_model(run.after, true);
    std::printf(",\"real_call_entered\":%s,\"completed\":%s,\"exception\":%s,"
        "\"dcr_reads_before\":%" PRIu64 ",\"dcr_reads_after\":%" PRIu64
        ",\"cache_flushes_before\":%" PRIu64 ",\"cache_flushes_after\":%" PRIu64 "}",
        boolean(run.real_call_entered), boolean(run.completed), boolean(run.exception),
        run.dcr_reads_before, run.dcr_reads_after, run.cache_flushes_before, run.cache_flushes_after);
  }
  std::fputs("],\"snapshots\":[", stdout);
  for (size_t i = 0; i != kSnapshots; ++i) {
    std::printf("%s{\"name\":\"%s\",\"before\":", i ? "," : "", kNames[i]);
    print_model(state.snapshots[i].before, true);
    std::fputs(",\"after\":", stdout);
    print_model(state.snapshots[i].after, true);
    std::fputc('}', stdout);
  }
  std::fputs("],\"reads\":[", stdout);
  for (size_t i = 0; i != kHalfReads; ++i) {
    hooks::DcrRead read;
    require(p06_preflight_get_read(i, &read) == 0, "retained raw read disappeared");
    if (i) {
      std::fputc(',', stdout);
    }
    print_pending_read(read);
  }
  std::fputs("],\"cache_flush_reads\":[", stdout);
  for (size_t i = 0; i != kCacheFlushReads; ++i) {
    hooks::DcrRead read;
    require(p06_preflight_get_cache_flush_read(i, &read) == 0, "retained cache-flush read disappeared");
    if (i) {
      std::fputc(',', stdout);
    }
    print_pending_read(read);
  }
  std::fputs("],\"destruction\":{\"before\":", stdout);
  print_model(observed.destruction.before, true);
  std::printf(",\"completed\":%s,\"ticks_after\":%" PRIu64 ",\"reset_after\":%" PRIu64
      ",\"idle_after\":%s},\"trace_overflow\":%s,",
      boolean(observed.destruction.completed), observed.destruction.ticks_after,
      observed.destruction.reset_after, boolean(observed.destruction.idle_after),
      boolean(observed.trace_overflow));
  std::fputs("\"unresolved_obligations\":[\"all_40_component_lifetime_and_pending_balance\","
      "\"dependency_source_to_loaded_binary_provenance\",\"independent_complete_counter_qualification\"],"
      "\"qualified\":false,\"ready_for_warm\":false,\"warm_execution\":false,"
      "\"full_warm_coverage\":false,\"acceptance_claimed\":false,\"phase_acceptance\":false,"
      "\"performance_acceptance\":false}\n", stdout);
}

int run_preflight(int argc, char** argv) {
  if (argc > 1 && std::strcmp(argv[1], "--lifetime") == 0) {
    state.lifetime = true;
    require(p06_preflight_enable_lifetime() == 0, "lifetime observation could not be enabled");
    for (int i = 1; i < argc; ++i) {
      argv[i] = argv[i + 1];
    }
    --argc;
  }
  if (argc > 1 && std::strcmp(argv[1], "--qualified-warm") == 0) {
    require(state.lifetime, "qualified warm execution requires lifetime observation");
    state.qualified_warm = true;
    for (int i = 1; i < argc; ++i) {
      argv[i] = argv[i + 1];
    }
    --argc;
  }
  const char* format = ai::kMatmulInputDType == 1 ? "fp16" : "bf16";
  Options opts;
  require(options(argc, argv, format, &opts)
      && (state.qualified_warm || (opts.pair_index == 0 && opts.phase == "warmup")),
          "preflight requires pair-zero warm-up or explicitly selected qualified warm arguments");
  const int status = p06_unchanged_warm_main(argc, argv);
  if (status != 0) { return status; }
  const auto observed = observation();
  require(!state.failed && state.queries == kSelectors * kSnapshots,
          "managed preflight observations are incomplete");
  require(observed.constructed == 1 && observed.destroyed == 1 && observed.constructor_entries == 1
      && observed.destructor_entries == 1 && observed.generation == 1 && !observed.live
      && observed.run_entries == 33 && observed.run_completed == 33
      && observed.read_count == kHalfReads && observed.cache_flush_count == kCacheFlushReads
      && observed.dcr_read_entries == kHalfReads + kCacheFlushReads
      && observed.dcr_read_completed == kHalfReads + kCacheFlushReads
      && observed.dcr_write_entries == observed.dcr_write_completed,
          "managed native lifecycle is incomplete");
  for (size_t i = 0; i != kCacheFlushReads; ++i) {
    check_cache_flush(i);
  }
  require(same_model(observed.constructed_state, state.snapshots[0].before)
      && same_model(observed.destruction.before, state.snapshots.back().after)
      && observed.destruction.completed && observed.destruction.idle_after
      && observed.destruction.ticks_after == 0
      && observed.destruction.reset_after == observed.destruction.before.reset_generation,
          "native construction or complete disposal differs from the snapshot lifetime");
  require(loaded_libraries().paths == state.libraries.paths, "loaded native libraries changed");
  require(!state.lifetime || (observed.lifetime_enabled && observed.run_count == hooks::kMaxRuns
      && !observed.trace_overflow && observed.destruction.before.pending_reads == 0),
          "native lifetime observations are incomplete");
  print_witness(opts, format, observed);
  if (state.lifetime) {
    print_lifetime(opts, format, observed);
  }
  require(std::fflush(stdout) == 0 && !std::ferror(stdout), "preflight witness output failed");
  return 0;
}

} // namespace
} // namespace managed_preflight

extern "C" vx_result_t __wrap_vx_device_mpm_query(
    vx_device_h device, uint32_t clss, uint32_t csr, uint32_t core, uint64_t* value) noexcept {
  try {
    return managed_preflight::query(device, clss, csr, core, value);
  } catch (...) {
    managed_preflight::state.failed = true;
    return VX_ERR_INTERNAL;
  }
}

int main(int argc, char** argv) {
  try {
    return managed_preflight::run_preflight(argc, argv);
  } catch (const std::exception& error) {
    std::fprintf(stderr, "P06_MANAGED_PREFLIGHT_FAILURE: %s\n", error.what());
  } catch (...) {
    std::fputs("P06_MANAGED_PREFLIGHT_FAILURE: unknown host failure\n", stderr);
  }
  return 1;
}
