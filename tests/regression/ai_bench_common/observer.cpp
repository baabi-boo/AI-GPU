// SPDX-License-Identifier: Apache-2.0

#include "counters.h"
#include <VX_config.h>
#include <array>
#include <chrono>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <iterator>

extern "C" vx_result_t __real_vx_device_open(uint32_t index, vx_device_h* out);
extern "C" vx_result_t __real_vx_device_release(vx_device_h device);

namespace {

struct Reading {
  vx_result_t status = VX_ERR_INTERNAL;
  uint64_t value = 0;
  bool returned = false;
};

struct Snapshot {
  uint64_t begin_ns = 0;
  uint64_t end_ns = 0;
  std::array<Reading, std::size(p06::kCapabilities)> capabilities{};
  std::array<Reading, std::size(p06::kCounters)> counters{};
  std::array<bool, std::size(p06::kCounters)> enabled{};
  bool availability_known = false;
};

struct Observer {
  char sample_id[129]{};
  vx_device_h device = nullptr;
  uint32_t device_index = 0;
  uint64_t opens = 0;
  uint64_t releases = 0;
  bool sample_valid = false;
  bool begin_taken = false;
};

Observer observer;

uint64_t now_ns() noexcept {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count());
}

void failure(const char* reason) noexcept {
  if (std::fprintf(stdout, "P06_FAILURE {\"reason\":\"%s\"}\n", reason) < 0
      || std::fflush(stdout) != 0) {
    std::fputs("P06_FAILURE {\"reason\":\"observer_output_failed\"}\n", stderr);
    std::fflush(stderr);
  }
}

bool sample_identity() noexcept {
  const auto* value = std::getenv("P06_SAMPLE_ID");
  if (!value || !value[0]) {
    return false;
  }
  size_t i = 0;
  for (; i != sizeof(observer.sample_id); ++i) {
    const char c = value[i];
    if (c == '\0') {
      observer.sample_id[i] = '\0';
      return true;
    }
    const bool alphanumeric = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
    if (!alphanumeric && (i == 0 || (c != '-' && c != '_'))) {
      return false;
    }
    if (i + 1 == sizeof(observer.sample_id)) {
      return false;
    }
    observer.sample_id[i] = c;
  }
  return false;
}

uint64_t capability(const Snapshot& snapshot, uint32_t id) noexcept {
  for (size_t i = 0; i != std::size(p06::kCapabilities); ++i) {
    if (p06::kCapabilities[i].id == id) {
      return snapshot.capabilities[i].value;
    }
  }
  return 0;
}

Snapshot capture(vx_device_h device) noexcept {
  Snapshot snapshot;
  snapshot.begin_ns = now_ns();
  bool capabilities_ok = true;
  for (size_t i = 0; i != std::size(p06::kCapabilities); ++i) {
    auto& reading = snapshot.capabilities[i];
    try {
      reading.status = vx_device_query(device, p06::kCapabilities[i].id, &reading.value);
      reading.returned = true;
    } catch (...) {
      failure("capability_query_threw");
    }
    if (!reading.returned || reading.status != VX_SUCCESS) {
      capabilities_ok = false;
      failure("capability_query_failed");
    }
  }
  snapshot.availability_known = capabilities_ok
      && capability(snapshot, VX_CAPS_NUM_CORES) == 1
      && capability(snapshot, VX_CAPS_NUM_CLUSTERS) == 1
      && capability(snapshot, VX_CAPS_SOCKET_SIZE) == 1;
  if (!snapshot.availability_known) {
    failure("unsupported_or_unavailable_topology");
  } else {
    const auto isa = capability(snapshot, VX_CAPS_ISA_FLAGS);
    for (size_t i = 0; i != std::size(p06::kCounters); ++i) {
      const auto& descriptor = p06::kCounters[i];
      snapshot.enabled[i] = descriptor.required_isa == 0
          || (isa & descriptor.required_isa) == descriptor.required_isa;
      if (!snapshot.enabled[i]) {
        continue;
      }
      auto& reading = snapshot.counters[i];
      try {
        reading.status = vx_device_mpm_query(device, descriptor.mpm_class,
            descriptor.csr, descriptor.core_id, &reading.value);
        reading.returned = true;
      } catch (...) {
        failure("counter_query_threw");
      }
      if (!reading.returned || reading.status != VX_SUCCESS) {
        failure("counter_query_failed");
      }
    }
  }
  snapshot.end_ns = now_ns();
  return snapshot;
}

void print_reading(const Reading& reading) noexcept {
  std::fputs(",\"status\":", stdout);
  if (reading.returned) {
    std::fprintf(stdout, "%u", static_cast<unsigned>(reading.status));
  } else {
    std::fputs("null", stdout);
  }
  std::fputs(",\"value\":", stdout);
  if (reading.returned && reading.status == VX_SUCCESS) {
    std::fprintf(stdout, "%" PRIu64, reading.value);
  } else {
    std::fputs("null", stdout);
  }
}

void print_snapshot(const char* marker, const Snapshot& snapshot) noexcept {
  std::fprintf(stdout, "%s {\"schema_version\":1,\"sample_id\":\"%s\","
      "\"context_id\":1,\"device_index\":%u,\"compiled_memory_block_bytes\":%u,"
      "\"query_begin_ns\":%" PRIu64 ",\"query_end_ns\":%" PRIu64 ",\"capabilities\":[",
      marker, observer.sample_id, observer.device_index,
      static_cast<unsigned>(VX_CFG_MEM_BLOCK_SIZE), snapshot.begin_ns, snapshot.end_ns);
  for (size_t i = 0; i != std::size(p06::kCapabilities); ++i) {
    const auto& descriptor = p06::kCapabilities[i];
    std::fprintf(stdout, "%s{\"name\":\"%s\",\"id\":%u", i ? "," : "",
                 descriptor.name, descriptor.id);
    print_reading(snapshot.capabilities[i]);
    std::fputc('}', stdout);
  }
  std::fputs("],\"counters\":[", stdout);
  for (size_t i = 0; i != std::size(p06::kCounters); ++i) {
    const auto& descriptor = p06::kCounters[i];
    std::fprintf(stdout, "%s{\"name\":\"%s\",\"mpm_class\":%u,\"csr\":%u,"
        "\"core_id\":%u,\"scope\":\"%s\",\"unit\":\"%s\",\"required_isa\":%" PRIu64
        ",\"enabled\":%s", i ? "," : "", descriptor.name, descriptor.mpm_class,
        descriptor.csr, descriptor.core_id, descriptor.scope, descriptor.unit,
        descriptor.required_isa, snapshot.availability_known
            ? (snapshot.enabled[i] ? "true" : "false") : "null");
    print_reading(snapshot.counters[i]);
    std::fputc('}', stdout);
  }
  std::fputs("]}\n", stdout);
  if (std::fflush(stdout) != 0 || std::ferror(stdout)) {
    failure("observer_output_failed");
  }
}

} // namespace

extern "C" vx_result_t __wrap_vx_device_open(uint32_t index, vx_device_h* out) noexcept {
  ++observer.opens;
  if (observer.opens == 1) {
    observer.sample_valid = sample_identity();
    if (!observer.sample_valid) {
      observer.sample_id[0] = '\0';
      failure("invalid_sample_identity");
    }
  } else {
    failure("multiple_device_opens");
  }
  if (index != 0) {
    failure("unsupported_device_index");
  }
  vx_result_t status;
  try {
    status = __real_vx_device_open(index, out);
  } catch (...) {
    failure("device_open_threw");
    return VX_ERR_INTERNAL;
  }
  if (status != VX_SUCCESS || !out || !*out) {
    failure("device_open_failed");
  } else if (observer.opens == 1) {
    observer.device = *out;
    observer.device_index = index;
    observer.begin_taken = true;
    print_snapshot("P06_BEGIN", capture(*out));
  }
  return status;
}

extern "C" vx_result_t __wrap_vx_device_release(vx_device_h device) noexcept {
  ++observer.releases;
  const bool matched = observer.begin_taken && device && device == observer.device
      && observer.opens == 1 && observer.releases == 1;
  if (matched) {
    print_snapshot("P06_END", capture(device));
  } else {
    failure("unmatched_device_release");
  }
  // Observation failure never prevents the owner's real cleanup call.
  vx_result_t status = VX_ERR_INTERNAL;
  bool returned = false;
  try {
    status = __real_vx_device_release(device);
    returned = true;
  } catch (...) {
    failure("device_release_threw");
  }
  if (device == observer.device) {
    observer.device = nullptr;
  }
  std::fprintf(stdout, "P06_RELEASE {\"schema_version\":1,\"sample_id\":\"%s\","
      "\"context_id\":1,\"status\":", observer.sample_id);
  if (returned) {
    std::fprintf(stdout, "%u", static_cast<unsigned>(status));
  } else {
    std::fputs("null", stdout);
  }
  std::fputs("}\n", stdout);
  if (std::fflush(stdout) != 0 || std::ferror(stdout)) {
    failure("observer_output_failed");
  }
  if (!returned || status != VX_SUCCESS) {
    failure("device_release_failed");
  }
  return status;
}
