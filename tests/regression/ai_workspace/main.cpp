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
namespace observed = p06_workspace;

namespace {

constexpr uint64_t kWaitNs = 120000000000ull;
constexpr const char* kContractId = "p06-serial-workspace-correctness-v1";
constexpr const char* kSuffixes[] = {
  "single-dense_boundaries", "numerical-zero", "single-k03", "single-dense_boundaries"
};
constexpr uint32_t kPoisons[] = {0xdeadbeefu, 0x7fc0deadu, 0xdeadbeefu, 0x7fc0deadu};

struct Options {
  std::string policy;
  std::string module;
  std::string qualification_id;
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

struct Probe {
  Result result;
  bool returned_object = false;
  observed::Counts before;
  observed::Counts after;
};

struct Snapshot {
  observed::Memory memory;
  observed::Counts counts;
};

struct OperationRecord {
  const p02::Fixture* fixture = nullptr;
  uint32_t sequence = 0;
  uint32_t poison = 0;
  std::vector<uint32_t> actual;
  size_t mismatches = 0;
  ai::MatmulTrace trace;
  std::array<Result, 3> results{};
  std::array<Probe, 6> probes{};
  std::array<Snapshot, 4> resources{};
  bool passed = false;
};

bool options(int argc, char** argv, Options* out) {
  if (argc != 7) {
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
    } else {
      return false;
    }
    if (!destination->empty() || !argv[i + 1][0]) {
      return false;
    }
    *destination = argv[i + 1];
  }
  out->resident = out->policy == "reusable_single_tile";
  return (out->resident || out->policy == "per_operation") && !out->module.empty()
      && out->qualification_id.size() == 64
      && std::all_of(out->qualification_id.begin(), out->qualification_id.end(), [](char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')
            || (c >= 'A' && c <= 'F');
      });
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

bool rejected(const Probe& probe, ai::Status validation, vx_result_t primary,
              bool complete) noexcept {
  return probe.result.attempted && !probe.returned_object
      && probe.result.value.validation == validation
      && probe.result.value.primary == primary
      && probe.result.value.cleanup == VX_SUCCESS
      && probe.result.value.complete == complete
      && observed::same_counts(probe.before, probe.after);
}

Snapshot snapshot(ai::ManagedMatmul* runtime) noexcept {
  Snapshot result;
  result.memory.queried = true;
  result.memory.status = runtime->memory_info(&result.memory.free_bytes,
                                             &result.memory.used_bytes);
  result.counts = observed::counts();
  return result;
}

bool same_memory(const observed::Memory& left, const observed::Memory& right) noexcept {
  return left.queried && right.queried && left.status == VX_SUCCESS
      && right.status == VX_SUCCESS && left.used_bytes == right.used_bytes
      && left.free_bytes == right.free_bytes;
}

bool counts_are(const observed::Counts& value, uint64_t creates, uint64_t releases,
                bool live, uint64_t peak) noexcept {
  return value.device_open_calls == 1 && value.device_release_calls == 0
      && value.buffer_create_calls == creates && value.buffer_release_calls == releases
      && value.live_buffers == (live ? 3u : 0u)
      && value.live_requested_bytes == (live ? 320u : 0u)
      && value.peak_requested_payload_bytes == peak && value.premature_releases == 0
      && value.errors == 0;
}

Probe context_probe(const ai::ExecutionBinding& binding, int32_t sequence) {
  Probe probe;
  probe.before = observed::counts();
  observed::set_phase(observed::Phase::competing_context, sequence);
  std::unique_ptr<ai::ManagedMatmul> other;
  probe.result.assign(ai::ManagedMatmul::create(binding, &other));
  probe.returned_object = static_cast<bool>(other);
  if (other) {
    observed::set_phase(observed::Phase::owner_close, sequence);
    other->close();
    other.reset();
  }
  probe.after = observed::counts();
  observed::set_phase(observed::Phase::live, sequence);
  return probe;
}

Probe operation_probe(ai::ManagedMatmul* runtime, int32_t sequence,
                      uint32_t m, uint32_t n, uint32_t k,
                      const std::vector<uint8_t>& a, const std::vector<uint8_t>& b,
                      uint32_t poison) {
  Probe probe;
  probe.before = observed::counts();
  observed::set_phase(observed::Phase::competing_operation, sequence);
  std::unique_ptr<ai::MatmulOperation> other;
  probe.result.assign(runtime->submit(m, n, k, a.data(), a.size(), b.data(), b.size(),
                                      poison, &other));
  probe.returned_object = static_cast<bool>(other);
  if (other) {
    observed::set_phase(observed::Phase::operation_close, sequence);
    other->close(kWaitNs);
    other.reset();
  }
  probe.after = observed::counts();
  observed::set_phase(observed::Phase::live, sequence);
  return probe;
}

Probe owner_close_probe(ai::ManagedMatmul* runtime, int32_t sequence) noexcept {
  Probe probe;
  probe.before = observed::counts();
  observed::set_phase(observed::Phase::owner_close_live, sequence);
  probe.result.assign(runtime->close());
  probe.after = observed::counts();
  observed::set_phase(observed::Phase::live, sequence);
  return probe;
}

bool trace_valid(const ai::MatmulTrace& trace, const Options& opts,
                 uint32_t poison) noexcept {
  if (trace.qualification_id != opts.qualification_id
      || static_cast<uint32_t>(trace.input_dtype) != ai::kMatmulInputDType
      || trace.m != 8 || trace.n != 4 || trace.k != 8 || trace.poison != poison
      || trace.a_bytes != 128 || trace.b_bytes != 64 || trace.d_bytes != 128
      || trace.writes_enqueued != 3 || trace.launches_enqueued != 1
      || trace.reads_enqueued != 1 || trace.wait_calls != 1 || trace.timed_out_waits != 0
      || trace.profiling_enabled
      || !std::all_of(trace.event_results.begin(), trace.event_results.end(),
                      [](vx_result_t result) { return result == VX_SUCCESS; })
      || !observed::matches_live_buffer(trace.a_address, 128, VX_MEM_READ)
      || !observed::matches_live_buffer(trace.b_address, 64, VX_MEM_READ)
      || !observed::matches_live_buffer(trace.d_address, 128, VX_MEM_WRITE)) {
    return false;
  }
  const std::array<uint64_t, 3> addresses{trace.a_address, trace.b_address, trace.d_address};
  const std::array<uint64_t, 3> sizes{128, 64, 128};
  for (size_t i = 0; i != addresses.size(); ++i) {
    if (addresses[i] % 4 != 0 || addresses[i] > UINT64_MAX - sizes[i]) {
      return false;
    }
    for (size_t j = 0; j != i; ++j) {
      if (addresses[i] < addresses[j] + sizes[j]
          && addresses[j] < addresses[i] + sizes[i]) {
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

void print_probe(const Probe& probe, bool shape = false, uint32_t m = 0,
                  uint32_t n = 0, uint32_t k = 0) noexcept {
  std::fputc('{', stdout);
  if (shape) {
    std::printf("\"m\":%u,\"n\":%u,\"k\":%u,", m, n, k);
  }
  std::fputs("\"result\":", stdout);
  print_result(probe.result);
  std::printf(",\"returned_object\":%s,\"before\":", probe.returned_object ? "true" : "false");
  observed::print_counts(probe.before);
  std::fputs(",\"after\":", stdout);
  observed::print_counts(probe.after);
  std::fputc('}', stdout);
}

void print_identity(const Options& opts, const char* format) noexcept {
  std::printf("\"schema_version\":1,\"contract_id\":\"%s\",\"qualification_id\":\"%s\","
      "\"policy\":\"%s\",\"format\":\"%s\"", kContractId,
      opts.qualification_id.c_str(), opts.policy.c_str(), format);
}

void print_operation(const OperationRecord& record, const Options& opts,
                     const char* format) noexcept {
  std::fputs("P06_WORKSPACE_RESULT {", stdout);
  print_identity(opts, format);
  std::printf(",\"sequence_index\":%u,\"case_id\":\"%s\",\"m\":%u,\"n\":%u,\"k\":%u,"
      "\"poison\":%u,\"checked\":%zu,\"mismatches\":%zu,\"actual_bits\":[",
      record.sequence, record.fixture->id, record.fixture->m, record.fixture->n,
      record.fixture->k, record.poison, record.actual.size(), record.mismatches);
  for (size_t i = 0; i != record.actual.size(); ++i) {
    std::printf("%s\"%08x\"", i ? "," : "", static_cast<unsigned>(record.actual[i]));
  }
  const auto& trace = record.trace;
  std::printf("],\"dispatch\":{\"a_address\":%" PRIu64 ",\"b_address\":%" PRIu64
      ",\"d_address\":%" PRIu64 ",\"a_bytes\":%" PRIu64 ",\"b_bytes\":%" PRIu64
      ",\"d_bytes\":%" PRIu64 ",\"writes\":%u,\"launches\":%u,\"reads\":%u,"
      "\"waits\":%" PRIu64 ",\"timed_out_waits\":%" PRIu64 ",\"argument_bytes\":\"",
      trace.a_address, trace.b_address, trace.d_address, trace.a_bytes, trace.b_bytes,
      trace.d_bytes, trace.writes_enqueued, trace.launches_enqueued, trace.reads_enqueued,
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
  std::fputs("},\"probes\":{", stdout);
  constexpr const char* probe_names[] = {
    "context_before_wait", "operation_before_wait", "owner_close_before_wait",
    "context_after_wait", "operation_after_wait", "owner_close_after_wait"
  };
  for (size_t i = 0; i != record.probes.size(); ++i) {
    std::printf("%s\"%s\":", i ? "," : "", probe_names[i]);
    print_probe(record.probes[i]);
  }
  std::fputs("},\"resources\":{", stdout);
  constexpr const char* resource_names[] = {"before_submit", "after_submit", "after_wait", "after_close"};
  for (size_t i = 0; i != record.resources.size(); ++i) {
    std::printf("%s\"%s\":{\"memory\":", i ? "," : "", resource_names[i]);
    observed::print_memory(record.resources[i].memory);
    std::fputs(",\"counts\":", stdout);
    observed::print_counts(record.resources[i].counts);
    std::fputc('}', stdout);
  }
  std::printf("},\"passed\":%s}\n", record.passed ? "true" : "false");
  std::fflush(stdout);
}

bool final_resources(bool resident) noexcept {
  const auto& state = observed::observation();
  const auto& counts = state.counts;
  const uint64_t buffers = resident ? 3 : 12;
  if (counts.device_open_calls != 1 || counts.device_release_calls != 1
      || counts.buffer_create_calls != buffers || counts.buffer_release_calls != buffers
      || counts.live_buffers != 0 || counts.live_requested_bytes != 0
      || counts.peak_requested_payload_bytes != 320 || counts.premature_releases != 0
      || counts.errors != 0 || state.device_count != 1 || state.buffer_count != buffers) {
    return false;
  }
  const auto& device = state.devices[0];
  if (device.device_id != 1 || device.index != 0 || device.live
      || device.open_status != VX_SUCCESS || !device.release_called
      || device.release_status != VX_SUCCESS || !same_memory(device.after_open, device.before_release)) {
    return false;
  }
  constexpr uint64_t sizes[] = {128, 64, 128};
  for (size_t i = 0; i != state.buffer_count; ++i) {
    const auto& buffer = state.buffers[i];
    const int32_t expected_sequence = resident ? -1 : static_cast<int32_t>(i / 3);
    if (!observed::reconciled(buffer) || buffer.buffer_id != i + 1 || buffer.device_id != 1
        || buffer.requested_bytes != sizes[i % 3]
        || buffer.flags != (i % 3 == 2 ? VX_MEM_WRITE : VX_MEM_READ)
        || buffer.create_phase != (resident ? observed::Phase::context_create : observed::Phase::submit)
        || buffer.release_phase != (resident ? observed::Phase::owner_close : observed::Phase::operation_close)
        || buffer.create_sequence != expected_sequence || buffer.release_sequence != expected_sequence) {
      return false;
    }
  }
  return true;
}

int run(int argc, char** argv) {
  Options opts;
  if (!options(argc, argv, &opts)) {
    std::fputs("usage: ai_workspace --policy per_operation|reusable_single_tile "
               "--module PATH --qualification-id 64_HEX_DIGITS\n", stderr);
    return 2;
  }
  const char* format = ai::kMatmulInputDType == 1 ? "fp16" : "bf16";
  std::array<const p02::Fixture*, 4> fixtures{};
  for (size_t i = 0; i != fixtures.size(); ++i) {
    const std::string id = std::string(format) + "-" + kSuffixes[i];
    for (const auto& fixture : p02::kFixtures) {
      if (id == fixture.id) {
        fixtures[i] = &fixture;
      }
    }
    if (!fixtures[i] || std::strcmp(fixtures[i]->format, format) != 0
        || fixtures[i]->m != 8 || fixtures[i]->n != 4 || fixtures[i]->k != 8
        || fixtures[i]->a_count != 32 || fixtures[i]->b_count != 16
        || fixtures[i]->output_count != 32) {
      return 2;
    }
  }
  std::ifstream stream(opts.module, std::ios::binary | std::ios::ate);
  if (!stream) {
    return 2;
  }
  const auto size = stream.tellg();
  if (size < 16 || size > 16 * 1024 * 1024) {
    return 2;
  }
  std::vector<uint8_t> image(static_cast<size_t>(size));
  stream.seekg(0);
  if (!stream.read(reinterpret_cast<char*>(image.data()), size)) {
    return 2;
  }
  ai::ExecutionBinding binding;
  binding.profile = {ai::Profile::p02_tfr_wmma_v1, true, true};
  binding.input_dtype = static_cast<ai::DType>(ai::kMatmulInputDType);
  binding.module_bytes = image.data();
  binding.module_size = image.size();
  binding.qualification_id = opts.qualification_id;
  binding.workspace_policy = opts.resident ? ai::WorkspacePolicy::reusable_single_tile
                                           : ai::WorkspacePolicy::per_operation;
  std::array<Result, 3> results{};
  std::unique_ptr<ai::ManagedMatmul> runtime;
  observed::set_phase(observed::Phase::context_create);
  results[0].assign(ai::ManagedMatmul::create(binding, &runtime));
  bool passed = success(results[0]) && static_cast<bool>(runtime);
  Probe unsupported;
  const uint32_t unsupported_m = opts.resident ? 8 : 7;
  const uint32_t unsupported_k = opts.resident ? 16 : 8;
  if (passed) {
    const std::vector<uint8_t> a(unsupported_m * unsupported_k * 2);
    const std::vector<uint8_t> b(unsupported_k * 4 * 2);
    unsupported = operation_probe(runtime.get(), -1, unsupported_m, 4, unsupported_k, a, b, 0);
    passed = rejected(unsupported, ai::Status::unsupported_shape, VX_SUCCESS, true);
  }
  size_t operations = 0, checked = 0, mismatches = 0;
  std::array<uint64_t, 3> resident_addresses{};
  for (uint32_t i = 0; passed && i != fixtures.size(); ++i) {
    OperationRecord record;
    record.fixture = fixtures[i];
    record.sequence = i;
    record.poison = kPoisons[i];
    const auto a = pack(record.fixture->a_words, record.fixture->a_count);
    const auto b = pack(record.fixture->b_words, record.fixture->b_count);
    observed::set_phase(observed::Phase::idle, static_cast<int32_t>(i));
    record.resources[0] = snapshot(runtime.get());
    std::unique_ptr<ai::MatmulOperation> operation;
    observed::set_phase(observed::Phase::submit, static_cast<int32_t>(i));
    record.results[0].assign(runtime->submit(8, 4, 8, a.data(), a.size(), b.data(), b.size(),
                                            record.poison, &operation));
    observed::set_phase(observed::Phase::live, static_cast<int32_t>(i));
    record.resources[1] = snapshot(runtime.get());
    bool valid_trace = false;
    if (record.results[0].value.ok() && operation) {
      record.probes[0] = context_probe(binding, static_cast<int32_t>(i));
      record.probes[1] = operation_probe(runtime.get(), static_cast<int32_t>(i), 8, 4, 8, a, b,
                                        record.poison);
      record.probes[2] = owner_close_probe(runtime.get(), static_cast<int32_t>(i));
      observed::set_phase(observed::Phase::wait, static_cast<int32_t>(i));
      record.results[1].assign(operation->wait(kWaitNs));
      observed::set_phase(observed::Phase::live, static_cast<int32_t>(i));
      record.resources[2] = snapshot(runtime.get());
      if (success(record.results[1])) {
        record.actual = operation->output_words();
        record.probes[3] = context_probe(binding, static_cast<int32_t>(i));
        record.probes[4] = operation_probe(runtime.get(), static_cast<int32_t>(i), 8, 4, 8, a, b,
                                          record.poison);
        record.probes[5] = owner_close_probe(runtime.get(), static_cast<int32_t>(i));
        valid_trace = trace_valid(operation->trace(), opts, record.poison);
      }
    }
    if (operation) {
      observed::set_phase(observed::Phase::operation_close, static_cast<int32_t>(i));
      record.results[2].assign(operation->close(kWaitNs));
      record.trace = operation->trace();
      operation.reset();
    }
    observed::set_phase(observed::Phase::idle, static_cast<int32_t>(i));
    record.resources[3] = snapshot(runtime.get());
    if (record.actual.size() != record.fixture->output_count) {
      ++record.mismatches;
    }
    for (size_t word = 0; word != std::min(record.actual.size(), record.fixture->output_count); ++word) {
      if (record.actual[word] != record.fixture->expected[word]) {
        ++record.mismatches;
      }
    }
    const uint64_t before_creates = opts.resident ? 3 : uint64_t{i} * 3;
    const uint64_t after_creates = opts.resident ? 3 : uint64_t{i + 1} * 3;
    const uint64_t before_releases = opts.resident ? 0 : uint64_t{i} * 3;
    const uint64_t after_releases = opts.resident ? 0 : uint64_t{i + 1} * 3;
    record.passed = record.results[0].attempted && record.results[0].value.ok()
        && !record.results[0].value.complete && success(record.results[1])
        && success(record.results[2]) && valid_trace && record.actual.size() == 32
        && record.mismatches == 0
        && same_memory(record.resources[0].memory, record.resources[3].memory)
        && counts_are(record.resources[0].counts, before_creates, before_releases,
                      opts.resident, opts.resident || i != 0 ? 320 : 0)
        && counts_are(record.resources[1].counts, after_creates, before_releases, true, 320)
        && counts_are(record.resources[2].counts, after_creates, before_releases, true, 320)
        && counts_are(record.resources[3].counts, after_creates, after_releases, opts.resident, 320);
    for (size_t probe = 0; probe != record.probes.size(); ++probe) {
      record.passed = rejected(record.probes[probe], ai::Status::success, VX_ERR_TIMEOUT,
                              probe % 3 != 2) && record.passed;
    }
    for (const auto& resource : record.resources) {
      record.passed = resource.memory.queried && resource.memory.status == VX_SUCCESS && record.passed;
    }
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
    checked += record.actual.size();
    mismatches += record.mismatches;
    passed = record.passed;
    print_operation(record, opts, format);
  }
  observed::set_phase(observed::Phase::owner_close);
  if (runtime) {
    results[1].assign(runtime->close());
    results[2].assign(runtime->close());
    runtime.reset();
  }
  passed = passed && success(results[0]) && success(results[1]) && success(results[2])
      && operations == 4 && checked == 128 && mismatches == 0 && final_resources(opts.resident);
  std::fputs("P06_WORKSPACE_SUMMARY {", stdout);
  print_identity(opts, format);
  std::printf(",\"operations\":%zu,\"checked\":%zu,\"mismatches\":%zu,\"results\":{",
      operations, checked, mismatches);
  constexpr const char* names[] = {"setup", "teardown", "teardown_repeat"};
  for (size_t i = 0; i != results.size(); ++i) {
    std::printf("%s\"%s\":", i ? "," : "", names[i]);
    print_result(results[i]);
  }
  std::fputs("},\"unsupported_shape\":", stdout);
  print_probe(unsupported, true, unsupported_m, 4, unsupported_k);
  std::fputs(",\"counts\":", stdout);
  observed::print_counts(observed::counts());
  std::fputs(",\"devices\":", stdout);
  observed::print_devices();
  std::fputs(",\"buffers\":", stdout);
  observed::print_buffers();
  std::printf(",\"passed\":%s}\n", passed ? "true" : "false");
  // Complete the structured failure record before main writes to stderr; the
  // bounded runner merges both streams into the same retained log.
  const int flush_status = std::fflush(stdout);
  if (!passed || flush_status != 0 || std::ferror(stdout)) {
    return 1;
  }
  if (std::puts("PASSED!") < 0 || std::fflush(stdout) != 0) {
    return 1;
  }
  return 0;
}

} // namespace

int main(int argc, char** argv) {
  try {
    const int result = run(argc, argv);
    if (result != 0) {
      std::fprintf(stderr, "FAILED workspace correctness, exit=%d\n", result);
    }
    return result;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED workspace correctness: %s\n", error.what());
    return 1;
  }
}
