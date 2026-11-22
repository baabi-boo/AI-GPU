// SPDX-License-Identifier: Apache-2.0

#include "runtime.h"
#include "observer.h"
#include <ai_matmul_profile.h>
#include "../sgemm_tcu/p02_fixtures.h"
#include <algorithm>
#include <array>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <exception>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

namespace ai = vortex::ai;
namespace observed = p06_warm;

namespace {

constexpr uint64_t kWaitNs = 120000000000ull;
constexpr size_t kOperations = 33;
constexpr size_t kWords = 32;
constexpr const char* kContractId = "p06-warm-workspace-v1";

struct Options {
  std::string policy;
  std::string module;
  std::string qualification_id;
  std::string sample_id;
  std::string pair;
  std::string phase;
  uint32_t pair_index = 0;
  bool resident = false;
};

struct Result {
  bool attempted = false;
  ai::ExecutionResult value{};

  void assign(const ai::ExecutionResult& result) noexcept {
    attempted = true;
    value = result;
  }
};

struct Interval {
  uint64_t begin_ns = 0;
  uint64_t end_ns = 0;
};

struct OperationRecord {
  uint32_t index = 0;
  uint32_t poison = 0;
  Interval interval;
  size_t checked = 0;
  size_t mismatches = 0;
  std::array<uint32_t, kWords> actual{};
  size_t actual_count = 0;
  ai::MatmulTrace trace;
  std::array<Result, 3> results{};
  observed::Counts before;
  observed::Counts after;
  bool passed = false;
};

bool options(int argc, char** argv, const char* format, Options* out) {
  if (argc != 13) {
    return false;
  }
  for (int i = 1; i < argc; i += 2) {
    const std::string name = argv[i];
    std::string* destination = nullptr;
    if (name == "--policy") {
      destination = &out->policy;
    } else if (name == "--module") {
      destination = &out->module;
    } else if (name == "--qualification-id") {
      destination = &out->qualification_id;
    } else if (name == "--sample-id") {
      destination = &out->sample_id;
    } else if (name == "--pair-index") {
      destination = &out->pair;
    } else if (name == "--phase") {
      destination = &out->phase;
    } else {
      return false;
    }
    if (!destination->empty() || !argv[i + 1][0]) {
      return false;
    }
    *destination = argv[i + 1];
  }
  out->resident = out->policy == "reusable_single_tile";
  if ((!out->resident && out->policy != "per_operation")
      || out->module.empty() || out->pair.size() != 1
      || out->pair[0] < '0' || out->pair[0] > '5'
      || out->qualification_id.size() != 64
      || !std::all_of(out->qualification_id.begin(), out->qualification_id.end(), [](char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
      })) {
    return false;
  }
  out->pair_index = static_cast<uint32_t>(out->pair[0] - '0');
  return out->phase == (out->pair_index == 0 ? "warmup" : "measured")
      && out->sample_id == std::string("warm-simx-") + format + "-pair"
          + out->pair + "-" + out->policy;
}

std::vector<uint8_t> pack(const uint32_t* words, size_t count) {
  std::vector<uint8_t> bytes(count * 4);
  for (size_t i = 0; i != count; ++i) {
    for (size_t byte = 0; byte != 4; ++byte) {
      bytes[i * 4 + byte] = static_cast<uint8_t>(words[i] >> (8 * byte));
    }
  }
  return bytes;
}

bool success(const Result& result) noexcept {
  return result.attempted && result.value.ok() && result.value.complete;
}

bool same_counts(const observed::Counts& left, const observed::Counts& right) noexcept {
  return left.device_open_calls == right.device_open_calls
      && left.device_release_calls == right.device_release_calls
      && left.buffer_create_calls == right.buffer_create_calls
      && left.buffer_release_calls == right.buffer_release_calls
      && left.live_buffers == right.live_buffers
      && left.live_requested_bytes == right.live_requested_bytes
      && left.peak_requested_payload_bytes == right.peak_requested_payload_bytes
      && left.premature_releases == right.premature_releases && left.errors == right.errors;
}

bool counts_are(const observed::Counts& value, uint64_t creates, uint64_t releases,
                bool resident, uint64_t peak, bool closed = false) noexcept {
  return value.device_open_calls == 1 && value.device_release_calls == (closed ? 1u : 0u)
      && value.buffer_create_calls == creates && value.buffer_release_calls == releases
      && value.live_buffers == (resident ? 3u : 0u)
      && value.live_requested_bytes == (resident ? 320u : 0u)
      && value.peak_requested_payload_bytes == peak && value.premature_releases == 0
      && value.errors == 0;
}

bool same_memory(const observed::Memory& left, const observed::Memory& right) noexcept {
  return left.queried && right.queried && left.status == VX_SUCCESS
      && right.status == VX_SUCCESS && left.free_bytes == right.free_bytes
      && left.used_bytes == right.used_bytes;
}

bool valid_snapshot(const observed::Snapshot& value) noexcept {
  if (value.begin_ns > value.end_ns) {
    return false;
  }
  for (const auto& reading : value.capabilities) {
    if (!reading.returned || reading.status != VX_SUCCESS) {
      return false;
    }
  }
  for (size_t i = 0; i != value.counters.size(); ++i) {
    const auto& reading = value.counters[i];
    if (value.enabled[i] && (!reading.returned || reading.status != VX_SUCCESS)) {
      return false;
    }
    if (!value.enabled[i] && reading.returned) {
      return false;
    }
  }
  return true;
}

bool counters_follow(const observed::Snapshot& before,
                     const observed::Snapshot& after, bool nonempty) noexcept {
  if (!valid_snapshot(before) || !valid_snapshot(after) || before.end_ns > after.begin_ns) {
    return false;
  }
  for (size_t i = 0; i != before.counters.size(); ++i) {
    if (before.enabled[i] != after.enabled[i]
        || (before.enabled[i] && before.counters[i].value > after.counters[i].value)) {
      return false;
    }
  }
  return !nonempty || (before.enabled[0] && before.enabled[1]
      && after.counters[0].value > before.counters[0].value
      && after.counters[1].value > before.counters[1].value);
}

bool trace_valid(const ai::MatmulTrace& trace, const Options& opts, uint32_t poison) noexcept {
  if (trace.qualification_id != opts.qualification_id
      || static_cast<uint32_t>(trace.input_dtype) != ai::kMatmulInputDType
      || trace.m != 8 || trace.n != 4 || trace.k != 8 || trace.poison != poison
      || trace.a_bytes != 128 || trace.b_bytes != 64 || trace.d_bytes != 128
      || trace.writes_enqueued != 3 || trace.launches_enqueued != 1
      || trace.reads_enqueued != 1 || trace.wait_calls != 1 || trace.timed_out_waits != 0
      || trace.profiling_enabled
      || !std::all_of(trace.event_results.begin(), trace.event_results.end(),
                      [](vx_result_t value) { return value == VX_SUCCESS; })) {
    return false;
  }
  const std::array<uint64_t, 3> addresses{trace.a_address, trace.b_address, trace.d_address};
  constexpr std::array<uint64_t, 3> sizes{128, 64, 128};
  for (size_t i = 0; i != addresses.size(); ++i) {
    if (addresses[i] % 4 != 0 || addresses[i] > UINT64_MAX - sizes[i]) {
      return false;
    }
    for (size_t j = 0; j != i; ++j) {
      if (addresses[i] < addresses[j] + sizes[j] && addresses[j] < addresses[i] + sizes[i]) {
        return false;
      }
    }
  }
  const std::array<uint64_t, 11> fields{
    1, 56, ai::kMatmulInputDType, 0, 8, 4, 8, 0,
    trace.a_address, trace.b_address, trace.d_address
  };
  size_t offset = 0;
  for (size_t field = 0; field != fields.size(); ++field) {
    const size_t width = field < 8 ? 4 : 8;
    for (size_t byte = 0; byte != width; ++byte) {
      if (trace.argument_bytes[offset++] != static_cast<uint8_t>(fields[field] >> (8 * byte))) {
        return false;
      }
    }
  }
  return offset == trace.argument_bytes.size();
}

void print_result(const Result& result) noexcept {
  if (!result.attempted) {
    std::fputs("null", stdout);
    return;
  }
  std::printf("{\"validation\":%u,\"primary\":%u,\"cleanup\":%u,\"complete\":%s}",
      static_cast<unsigned>(result.value.validation), static_cast<unsigned>(result.value.primary),
      static_cast<unsigned>(result.value.cleanup), result.value.complete ? "true" : "false");
}

void print_interval(const Interval& value) noexcept {
  std::printf("{\"begin_ns\":%" PRIu64 ",\"end_ns\":%" PRIu64 "}", value.begin_ns, value.end_ns);
}

void print_identity(const Options& opts, const char* format) noexcept {
  std::printf("\"schema_version\":1,\"contract_id\":\"%s\",\"qualification_id\":\"%s\","
      "\"sample_id\":\"%s\",\"format\":\"%s\",\"policy\":\"%s\","
      "\"pair_index\":%u,\"phase\":\"%s\"", kContractId, opts.qualification_id.c_str(),
      opts.sample_id.c_str(), format, opts.policy.c_str(), opts.pair_index, opts.phase.c_str());
}

void print_operation(const OperationRecord& record, const Options& opts,
                     const p02::Fixture& fixture) noexcept {
  std::fputs("P06_WARM_OPERATION {", stdout);
  print_identity(opts, fixture.format);
  std::printf(",\"operation_index\":%u,\"role\":\"%s\",\"case_id\":\"%s\","
      "\"m\":8,\"n\":4,\"k\":8,\"poison\":%u,\"begin_ns\":%" PRIu64
      ",\"end_ns\":%" PRIu64 ",\"checked\":%zu,\"mismatches\":%zu,\"actual_bits\":[",
      record.index, record.index == 0 ? "prime" : "sample", fixture.id, record.poison,
      record.interval.begin_ns, record.interval.end_ns, record.checked, record.mismatches);
  for (size_t i = 0; i != record.actual_count; ++i) {
    std::printf("%s\"%08x\"", i ? "," : "", static_cast<unsigned>(record.actual[i]));
  }
  const auto& trace = record.trace;
  std::printf("],\"dispatch\":{\"a_address\":%" PRIu64 ",\"b_address\":%" PRIu64
      ",\"d_address\":%" PRIu64 ",\"a_bytes\":%" PRIu64 ",\"b_bytes\":%" PRIu64
      ",\"d_bytes\":%" PRIu64 ",\"writes\":%u,\"launches\":%u,\"reads\":%u,"
      "\"waits\":%" PRIu64 ",\"timed_out_waits\":%" PRIu64 ",\"argument_bytes\":\"",
      trace.a_address, trace.b_address, trace.d_address, trace.a_bytes, trace.b_bytes, trace.d_bytes,
      trace.writes_enqueued, trace.launches_enqueued, trace.reads_enqueued,
      trace.wait_calls, trace.timed_out_waits);
  for (const auto byte : trace.argument_bytes) {
    std::printf("%02x", static_cast<unsigned>(byte));
  }
  std::fputs("\",\"event_results\":[", stdout);
  for (size_t i = 0; i != trace.event_results.size(); ++i) {
    std::printf("%s%u", i ? "," : "", static_cast<unsigned>(trace.event_results[i]));
  }
  std::printf("],\"profiling_enabled\":%s},\"results\":{", trace.profiling_enabled ? "true" : "false");
  constexpr const char* result_names[] = {"submit", "wait", "close"};
  for (size_t i = 0; i != record.results.size(); ++i) {
    std::printf("%s\"%s\":", i ? "," : "", result_names[i]);
    print_result(record.results[i]);
  }
  std::fputs("},\"counts_before\":", stdout);
  observed::print_counts(record.before);
  std::fputs(",\"counts_after\":", stdout);
  observed::print_counts(record.after);
  std::printf(",\"passed\":%s}\n", record.passed ? "true" : "false");
}

void failure(const char* reason) noexcept {
  std::printf("P06_WARM_FAILURE {\"reason\":\"%s\"}\n", reason);
  std::fflush(stdout);
}

int run(int argc, char** argv) {
  const char* format = ai::kMatmulInputDType == 1 ? "fp16" : "bf16";
  Options opts;
  if (!options(argc, argv, format, &opts)) {
    std::fputs("usage: ai_warm_workspace --policy per_operation|reusable_single_tile "
        "--module PATH --qualification-id 64_LOWERCASE_HEX_DIGITS --sample-id ID "
        "--pair-index 0..5 --phase warmup|measured\n", stderr);
    return 2;
  }
  const std::string fixture_id = std::string(format) + "-single-dense_boundaries";
  const p02::Fixture* fixture = nullptr;
  for (const auto& candidate : p02::kFixtures) {
    if (fixture_id == candidate.id) {
      fixture = &candidate;
    }
  }
  if (!fixture || std::strcmp(fixture->format, format) != 0 || fixture->m != 8
      || fixture->n != 4 || fixture->k != 8 || fixture->a_count != 32
      || fixture->b_count != 16 || fixture->output_count != kWords) {
    failure("invalid_frozen_fixture");
    return 2;
  }
  std::ifstream stream(opts.module, std::ios::binary | std::ios::ate);
  if (!stream) {
    failure("module_open_failed");
    return 2;
  }
  const auto size = stream.tellg();
  if (size < 16 || size > 16 * 1024 * 1024) {
    failure("invalid_module_size");
    return 2;
  }
  std::vector<uint8_t> image(static_cast<size_t>(size));
  stream.seekg(0);
  if (!stream.read(reinterpret_cast<char*>(image.data()), size)) {
    failure("module_read_failed");
    return 2;
  }
  const auto a = pack(fixture->a_words, fixture->a_count);
  const auto b = pack(fixture->b_words, fixture->b_count);
  std::array<OperationRecord, kOperations> records{};
  std::array<Result, 2> owner_results{};
  std::array<Interval, 2> owner_intervals{};
  std::array<observed::Memory, 5> memories{};
  std::array<observed::Snapshot, 4> snapshots{};
  ai::ExecutionBinding binding;
  binding.profile = {ai::Profile::p02_tfr_wmma_v1, true, true};
  binding.input_dtype = static_cast<ai::DType>(ai::kMatmulInputDType);
  binding.module_bytes = image.data();
  binding.module_size = image.size();
  binding.qualification_id = opts.qualification_id;
  binding.workspace_policy = opts.resident ? ai::WorkspacePolicy::reusable_single_tile
                                           : ai::WorkspacePolicy::per_operation;
  std::unique_ptr<ai::ManagedMatmul> runtime;
  observed::set_phase(observed::Phase::context_create);
  owner_intervals[0].begin_ns = observed::now_ns();
  owner_results[0].assign(ai::ManagedMatmul::create(binding, &runtime));
  owner_intervals[0].end_ns = observed::now_ns();
  bool passed = success(owner_results[0]) && static_cast<bool>(runtime);
  snapshots[0] = observed::after_open_snapshot();
  memories[0] = observed::after_open_memory();
  if (passed) {
    observed::set_phase(observed::Phase::idle);
    memories[1] = observed::memory();
    passed = memories[1].queried && memories[1].status == VX_SUCCESS;
  }
  size_t operations = 0, printed = 0, checked = 0, mismatches = 0;
  std::array<uint64_t, 3> resident_addresses{};
  for (uint32_t i = 0; passed && i != kOperations; ++i) {
    auto& record = records[i];
    record.index = i;
    record.poison = i % 2 == 0 ? 0xdeadbeefu : 0x7fc0deadu;
    record.before = observed::counts();
    std::unique_ptr<ai::MatmulOperation> operation;
    observed::set_phase(observed::Phase::submit);
    record.interval.begin_ns = observed::now_ns();
    record.results[0].assign(runtime->submit(8, 4, 8, a.data(), a.size(), b.data(), b.size(),
                                            record.poison, &operation));
    bool execution_ok = record.results[0].value.ok()
        && !record.results[0].value.complete && static_cast<bool>(operation);
    if (execution_ok) {
      record.results[1].assign(operation->wait(kWaitNs));
      execution_ok = success(record.results[1]);
      if (execution_ok) {
        const auto& actual = operation->output_words();
        record.checked = std::min(actual.size(), kWords);
        record.mismatches = actual.size() == kWords ? 0 : 1;
        for (size_t word = 0; word != record.checked; ++word) {
          if (actual[word] != fixture->expected[word]) {
            ++record.mismatches;
          }
        }
        execution_ok = record.mismatches == 0 && record.checked == kWords;
      }
    }
    if (operation) {
      observed::set_phase(observed::Phase::operation_close);
      record.results[2].assign(operation->close(kWaitNs));
      execution_ok = success(record.results[2]) && execution_ok;
    } else {
      execution_ok = false;
    }
    record.interval.end_ns = observed::now_ns();
    record.after = observed::counts();
    if (operation) {
      record.trace = operation->trace();
      const auto& actual = operation->output_words();
      record.actual_count = std::min(actual.size(), kWords);
      std::copy_n(actual.begin(), record.actual_count, record.actual.begin());
    }
    const uint64_t before_creates = opts.resident ? 3 : uint64_t{i} * 3;
    const uint64_t after_creates = opts.resident ? 3 : uint64_t{i + 1} * 3;
    record.passed = execution_ok && record.interval.end_ns > record.interval.begin_ns
        && record.actual_count == kWords && trace_valid(record.trace, opts, record.poison)
        && counts_are(record.before, before_creates, opts.resident ? 0 : before_creates,
                      opts.resident, opts.resident || i != 0 ? 320 : 0)
        && counts_are(record.after, after_creates, opts.resident ? 0 : after_creates,
                      opts.resident, 320);
    const std::array<uint64_t, 3> addresses{
      record.trace.a_address, record.trace.b_address, record.trace.d_address
    };
    if (opts.resident) {
      if (i == 0) {
        resident_addresses = addresses;
      }
      record.passed = resident_addresses == addresses && record.passed;
    }
    ++operations;
    checked += record.checked;
    mismatches += record.mismatches;
    passed = record.passed;
    if (!passed) {
      for (; printed != operations; ++printed) {
        print_operation(records[printed], opts, *fixture);
      }
      failure("operation_rejected");
    }
    operation.reset();
    record.passed = same_counts(record.after, observed::counts()) && record.passed;
    passed = record.passed;
    observed::set_phase(observed::Phase::idle);
    if (passed && (i == 0 || i + 1 == kOperations)) {
      const size_t slot = i == 0 ? 1 : 2;
      snapshots[slot] = observed::snapshot();
      memories[slot + 1] = observed::memory();
      passed = valid_snapshot(snapshots[slot]) && same_memory(memories[1], memories[slot + 1])
          && observed::counts().errors == 0;
    }
  }
  observed::set_phase(observed::Phase::owner_close);
  owner_intervals[1].begin_ns = observed::now_ns();
  if (runtime) {
    owner_results[1].assign(runtime->close());
  }
  owner_intervals[1].end_ns = observed::now_ns();
  const auto closed_counts = observed::counts();
  runtime.reset();
  snapshots[3] = observed::before_release_snapshot();
  memories[4] = observed::before_release_memory();
  const uint64_t allocation_count = opts.resident ? 3 : 99;
  passed = passed && success(owner_results[0]) && success(owner_results[1])
      && operations == kOperations && checked == kOperations * kWords && mismatches == 0
      && counts_are(closed_counts, allocation_count, allocation_count, false, 320, true)
      && same_counts(closed_counts, observed::counts())
      && observed::release_status() == VX_SUCCESS && same_memory(memories[0], memories[4])
      && counters_follow(snapshots[0], snapshots[1], true)
      && counters_follow(snapshots[1], snapshots[2], true)
      && counters_follow(snapshots[2], snapshots[3], false);
  for (; printed != operations; ++printed) {
    print_operation(records[printed], opts, *fixture);
  }
  std::fputs("P06_WARM_SUMMARY {", stdout);
  print_identity(opts, format);
  std::printf(",\"operations\":%zu,\"checked\":%zu,\"mismatches\":%zu,\"passed\":%s,\"counts\":",
      operations, checked, mismatches, passed ? "true" : "false");
  observed::print_counts(observed::counts());
  std::fputs(",\"snapshots\":{", stdout);
  constexpr const char* snapshot_names[] = {"after_open", "after_prime", "after_batch", "before_release"};
  for (size_t i = 0; i != snapshots.size(); ++i) {
    std::printf("%s\"%s\":", i ? "," : "", snapshot_names[i]);
    observed::print_snapshot(snapshots[i], opts.sample_id.c_str());
  }
  std::fputs("},\"memory\":{", stdout);
  constexpr const char* memory_names[] = {"after_open", "after_create", "after_prime", "after_batch", "before_release"};
  for (size_t i = 0; i != memories.size(); ++i) {
    std::printf("%s\"%s\":", i ? "," : "", memory_names[i]);
    observed::print_memory(memories[i]);
  }
  std::fputs("},\"results\":{\"create\":", stdout);
  print_result(owner_results[0]);
  std::fputs(",\"close\":", stdout);
  print_result(owner_results[1]);
  std::fputs("},\"host_intervals_ns\":{\"create\":", stdout);
  print_interval(owner_intervals[0]);
  std::fputs(",\"close\":", stdout);
  print_interval(owner_intervals[1]);
  std::printf("},\"device_release\":{\"schema_version\":1,\"sample_id\":\"%s\","
      "\"context_id\":1,\"status\":%u}}\n", opts.sample_id.c_str(),
      static_cast<unsigned>(observed::release_status()));
  if (std::fflush(stdout) != 0 || std::ferror(stdout)) {
    std::fputs("P06_WARM_FAILURE {\"reason\":\"output_failed\"}\n", stderr);
    return 1;
  }
  if (!passed) {
    failure("incomplete_or_invalid_batch");
    return 1;
  }
  std::puts("PASSED!");
  if (std::fflush(stdout) != 0 || std::ferror(stdout)) {
    std::fputs("P06_WARM_FAILURE {\"reason\":\"output_failed\"}\n", stderr);
    return 1;
  }
  return 0;
}

} // namespace

int main(int argc, char** argv) {
  try {
    return run(argc, argv);
  } catch (const std::exception&) {
    failure("host_exception");
  } catch (...) {
    failure("unknown_exception");
  }
  return 1;
}
