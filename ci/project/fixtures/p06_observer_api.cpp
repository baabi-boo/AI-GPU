// SPDX-License-Identifier: Apache-2.0

#include <vortex2.h>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>

namespace {

int handles[3]{};
bool alive[3]{};
unsigned opens = 0, releases = 0, capabilities = 0, counters = 0;
unsigned invalid_queries = 0, queries_after_release = 0;

bool mode(const char* name) {
  const char* value = std::getenv("P06_TEST_CASE");
  return value && std::strcmp(name, value) == 0;
}

unsigned failure_index() {
  const char* value = std::getenv("P06_FAIL_N");
  return value ? static_cast<unsigned>(std::strtoul(value, nullptr, 10)) : 1;
}

int slot(vx_device_h device) {
  for (int i = 0; i != 3; ++i) {
    if (device == &handles[i]) return i;
  }
  return -1;
}

void check_query(vx_device_h device) {
  const int index = slot(device);
  if (index < 0 || !alive[index]) ++invalid_queries;
  if (releases != 0) ++queries_after_release;
}

} // namespace

extern "C" vx_result_t vx_device_open(uint32_t index, vx_device_h* out) {
  ++opens;
  std::fprintf(stderr, "MOCK_OPEN {\"index\":%u,\"null_output\":%s}\n",
               index, out ? "false" : "true");
  if (mode("open_throw")) throw std::runtime_error("mock open exception");
  if (mode("open_status")) return VX_ERR_DEVICE_LOST;
  if (!out) return VX_ERR_INVALID_VALUE;
  if (mode("open_null")) {
    *out = nullptr;
    return VX_SUCCESS;
  }
  const unsigned selected = opens == 1 ? 0 : 1;
  alive[selected] = true;
  *out = &handles[selected];
  return VX_SUCCESS;
}

extern "C" vx_result_t vx_device_release(vx_device_h device) {
  ++releases;
  const int index = slot(device);
  const bool valid = index >= 0 && alive[index];
  std::fprintf(stderr, "MOCK_RELEASE {\"slot\":%d,\"live\":%s}\n",
               index, valid ? "true" : "false");
  if (index >= 0) alive[index] = false;
  if (mode("release_throw")) throw std::runtime_error("mock release exception");
  if (mode("release_status")) return VX_ERR_DEVICE_LOST;
  return valid ? VX_SUCCESS : VX_ERR_INVALID_HANDLE;
}

extern "C" vx_result_t vx_device_query(vx_device_h device, uint32_t id,
                                        uint64_t* value) {
  ++capabilities;
  check_query(device);
  std::fprintf(stderr, "MOCK_CAP {\"id\":%u,\"call\":%u}\n", id, capabilities);
  // Write poison before failing: unsuccessful output must never become evidence.
  *value = UINT64_MAX;
  if (capabilities == failure_index()) {
    if (mode("cap_throw")) throw std::runtime_error("mock capability exception");
    if (mode("cap_status")) return VX_ERR_DEVICE_LOST;
  }
  switch (id) {
  case VX_CAPS_NUM_CORES:
    *value = mode("topology_cores") ? 2 : 1;
    break;
  case VX_CAPS_NUM_CLUSTERS:
    *value = mode("topology_clusters") ? 2 : 1;
    break;
  case VX_CAPS_SOCKET_SIZE:
    *value = mode("topology_socket") ? 2 : 1;
    break;
  case VX_CAPS_ISSUE_WIDTH: *value = 1; break;
  case VX_CAPS_NUM_THREADS: case VX_CAPS_NUM_WARPS: *value = 4; break;
  case VX_CAPS_ISA_FLAGS:
    *value = mode("no_optional_isa") ? 0 : UINT64_C(2420223512872);
    break;
  case VX_CAPS_CACHE_LINE_SIZE: *value = 64; break;
  case VX_CAPS_LOCAL_MEM_SIZE: *value = 16384; break;
  case VX_CAPS_GLOBAL_MEM_SIZE: *value = UINT64_C(8589934592); break;
  case VX_CAPS_NUM_MEM_BANKS: *value = 2; break;
  case VX_CAPS_MEM_BANK_SIZE: *value = UINT64_C(140737488355328); break;
  case VX_CAPS_VM_SUPPORT: *value = 0; break;
  default: return VX_ERR_INVALID_INFO;
  }
  return VX_SUCCESS;
}

extern "C" vx_result_t vx_device_mpm_query(vx_device_h device, uint32_t cls,
                                            uint32_t csr, uint32_t core,
                                            uint64_t* value) {
  ++counters;
  check_query(device);
  std::fprintf(stderr,
      "MOCK_COUNTER {\"mpm_class\":%u,\"csr\":%u,\"core_id\":%u,\"call\":%u}\n",
      cls, csr, core, counters);
  *value = UINT64_MAX;
  if (counters == failure_index()) {
    if (mode("counter_throw")) throw std::runtime_error("mock counter exception");
    if (mode("counter_status")) return VX_ERR_TIMEOUT;
  }
  if (!mode("unsigned_max")) *value = UINT64_C(9223372036854775808) + counters;
  return VX_SUCCESS;
}

extern "C" void p06_mock_summary() {
  std::fprintf(stderr,
      "MOCK_SUMMARY {\"opens\":%u,\"releases\":%u,\"capabilities\":%u,"
      "\"counters\":%u,\"invalid_queries\":%u,\"queries_after_release\":%u,"
      "\"live_handles\":%u}\n", opens, releases, capabilities, counters,
      invalid_queries, queries_after_release,
      static_cast<unsigned>(alive[0]) + static_cast<unsigned>(alive[1]));
}
