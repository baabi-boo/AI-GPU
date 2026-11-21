// SPDX-License-Identifier: Apache-2.0

#include <vortex2.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

extern "C" void p06_mock_summary();

namespace {

bool mode(const char* name) {
  const char* value = std::getenv("P06_TEST_CASE");
  return value && std::strcmp(name, value) == 0;
}

void release(vx_device_h device) {
  const auto status = vx_device_release(device);
  std::fprintf(stderr, "MOCK_RETURN {\"operation\":\"release\",\"status\":%u}\n",
               static_cast<unsigned>(status));
}

} // namespace

int main() {
  if (mode("output_full") && !std::freopen("/dev/full", "w", stdout)) return 2;
  if (mode("release_without_open")) {
    release(nullptr);
    p06_mock_summary();
    return 0;
  }
  vx_device_h device = nullptr;
  const auto status = vx_device_open(mode("device_index") ? 7 : 0,
                                     mode("null_output") ? nullptr : &device);
  std::fprintf(stderr, "MOCK_RETURN {\"operation\":\"open\",\"status\":%u}\n",
               static_cast<unsigned>(status));
  vx_device_h second = nullptr;
  if (mode("duplicate_open")) vx_device_open(0, &second);
  if (status == VX_SUCCESS && device) {
    if (mode("wrong_release")) {
      int unknown = 0;
      release(&unknown);
    }
    release(device);
    if (mode("release_twice")) release(device);
  }
  if (second) release(second);
  p06_mock_summary();
  return 0;
}
