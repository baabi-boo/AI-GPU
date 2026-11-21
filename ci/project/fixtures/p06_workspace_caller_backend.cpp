// SPDX-License-Identifier: Apache-2.0
// Host-only transport backend. Frozen fixture words are copied, not computed.

#include "runtime.h"
#include "observer.h"
#include "../../../tests/regression/sgemm_tcu/p02_fixtures.h"
#include <array>
#include <cstdio>

// Keep the deferred queue/event implementation shared with the existing host
// lifetime tests. Real ManagedMatmul, the application, and observer are separate
// translation units; the real application's four linker wrappers stay active.
#define main p03_workspace_caller_unused_main
#define vx_device_open p03_caller_device_open
#define vx_device_release p03_caller_device_release
#define vx_device_memory_info p03_caller_memory_info
#define vx_buffer_create p03_caller_buffer_create
#define vx_buffer_release p03_caller_buffer_release
#define vx_queue_create p03_caller_queue_create
#define vx_enqueue_write p03_caller_enqueue_write
#define vx_enqueue_launch p03_caller_enqueue_launch
#include "p03_managed_runtime_test.cpp"
#undef main
#undef vx_device_open
#undef vx_device_release
#undef vx_device_memory_info
#undef vx_buffer_create
#undef vx_buffer_release
#undef vx_queue_create
#undef vx_enqueue_write
#undef vx_enqueue_launch

extern "C" vx_result_t __wrap_vx_device_open(uint32_t, vx_device_h*) noexcept;
extern "C" vx_result_t __wrap_vx_device_release(vx_device_h) noexcept;
extern "C" vx_result_t __wrap_vx_buffer_create(vx_device_h, uint64_t, uint32_t,
                                              vx_buffer_h*) noexcept;
extern "C" vx_result_t __wrap_vx_buffer_release(vx_buffer_h) noexcept;

namespace {

bool fault(const char* name) {
  const char* value = std::getenv("P06_CALLER_TEST_FAULT");
  return value && std::strcmp(value, name) == 0;
}

struct Audit {
  uint64_t opens = 0;
  uint64_t releases = 0;
  uint64_t creates = 0;
  uint64_t frees = 0;
  uint64_t launches = 0;
  uint64_t input_checks = 0;
  uint64_t poison_checks = 0;
  uint64_t lingering_charge = 0;
  bool injected = false;
  std::map<Buffer*, uint64_t> charges;
  std::array<const char*, 4> ids{};
  std::vector<uint8_t> first_output;

  Audit() {
    if (fault("partial_enqueue")) {
      state.fail_call = "enqueue";
      state.fail_at = 4;
    } else if (fault("module_failure")) {
      state.fail_call = "module_load";
      state.fail_at = 1;
    } else if (fault("bad_address")) {
      state.bad_address = 1;
    }
  }

  ~Audit() {
    const char* path = std::getenv("P06_CALLER_TEST_AUDIT");
    if (!path) {
      return;
    }
    std::FILE* stream = std::fopen(path, "w");
    if (!stream) {
      std::_Exit(90);
    }
    std::fprintf(stream,
        "{\"scope\":\"host-fixture-transport-only\",\"native_opens\":%llu,"
        "\"native_releases\":%llu,\"buffer_creates\":%llu,\"buffer_releases\":%llu,"
        "\"launches\":%llu,\"input_checks\":%llu,\"poison_checks\":%llu,"
        "\"writes\":%d,\"devices\":%d,\"modules\":%d,\"kernels\":%d,"
        "\"queues\":%d,\"events\":%d,\"buffers\":%zu,\"premature\":%d,\"cases\":[",
        static_cast<unsigned long long>(opens), static_cast<unsigned long long>(releases),
        static_cast<unsigned long long>(creates), static_cast<unsigned long long>(frees),
        static_cast<unsigned long long>(launches), static_cast<unsigned long long>(input_checks),
        static_cast<unsigned long long>(poison_checks), state.writes_observed,
        state.devices, state.modules, state.kernels, state.queues, state.events,
        state.buffers.size(), state.premature);
    bool first = true;
    for (const char* id : ids) {
      if (id) {
        std::fprintf(stream, "%s\"%s\"", first ? "" : ",", id);
        first = false;
      }
    }
    std::fputs("]}\n", stream);
    if (std::fclose(stream) != 0) {
      std::_Exit(91);
    }
  }
} audit;

uint64_t integer(const std::vector<uint8_t>& bytes, size_t offset, size_t width) {
  check(offset + width <= bytes.size());
  uint64_t value = 0;
  for (size_t i = 0; i != width; ++i) {
    value |= uint64_t{bytes[offset + i]} << (i * 8);
  }
  return value;
}

Buffer* buffer_at(uint64_t address) {
  const auto found = std::find_if(state.buffers.begin(), state.buffers.end(),
      [address](const Buffer* value) { return value->address == address; });
  check(found != state.buffers.end());
  return *found;
}

bool packed_equal(const std::vector<uint8_t>& actual, const uint32_t* words, size_t count) {
  if (actual.size() != count * 4) {
    return false;
  }
  for (size_t i = 0; i != actual.size(); ++i) {
    if (actual[i] != static_cast<uint8_t>(words[i / 4] >> ((i % 4) * 8))) {
      return false;
    }
  }
  return true;
}

void fixture_transport(const std::vector<uint8_t>& args) {
  constexpr const char* suffixes[] = {
    "single-dense_boundaries", "numerical-zero", "single-k03", "single-dense_boundaries"
  };
  constexpr uint32_t poisons[] = {0xdeadbeefu, 0x7fc0deadu, 0xdeadbeefu, 0x7fc0deadu};
  check(audit.launches < 4 && args.size() == 56);
  const auto dtype = integer(args, 8, 4);
  check(dtype == 1 || dtype == 2);
  const std::array<uint64_t, 8> fields{1, 56, dtype, 0, 8, 4, 8, 0};
  for (size_t i = 0; i != fields.size(); ++i) {
    check(integer(args, i * 4, 4) == fields[i]);
  }
  auto* a = buffer_at(integer(args, 32, 8));
  auto* b = buffer_at(integer(args, 40, 8));
  auto* d = buffer_at(integer(args, 48, 8));
  check(a != b && a != d && b != d && d->bytes.size() == 128);
  const std::string id = std::string(dtype == 1 ? "fp16-" : "bf16-") + suffixes[audit.launches];
  const p02::Fixture* selected = nullptr;
  for (const auto& item : p02::kFixtures) {
    if (id == item.id) {
      check(selected == nullptr);
      selected = &item;
    }
  }
  check(selected && selected->m == 8 && selected->n == 4 && selected->k == 8
        && selected->output_count == 32);
  check(packed_equal(a->bytes, selected->a_words, selected->a_count));
  check(packed_equal(b->bytes, selected->b_words, selected->b_count));
  audit.input_checks += 2;
  for (size_t i = 0; i != d->bytes.size(); ++i) {
    check(d->bytes[i] == static_cast<uint8_t>(poisons[audit.launches] >> ((i % 4) * 8)));
  }
  ++audit.poison_checks;
  audit.ids[audit.launches] = selected->id;
  for (size_t i = 0; i != d->bytes.size(); ++i) {
    d->bytes[i] = static_cast<uint8_t>(selected->expected[i / 4] >> ((i % 4) * 8));
  }
  if (audit.launches == 0) {
    audit.first_output = d->bytes;
  }
  if (fault("altered_output") && audit.launches == 0) {
    d->bytes[0] ^= 1;
  }
  if (fault("stale_output") && audit.launches == 1) {
    d->bytes = audit.first_output;
  }
  ++audit.launches;
}

} // namespace

extern "C" {

vx_result_t vx_device_open(uint32_t index, vx_device_h* out) {
  ++audit.opens;
  const auto result = p03_caller_device_open(index, out);
  if (result == VX_SUCCESS && fault("second_open") && !audit.injected) {
    audit.injected = true;
    vx_device_h extra = nullptr;
    check(__wrap_vx_device_open(index, &extra) == VX_SUCCESS);
    check(__wrap_vx_device_release(extra) == VX_SUCCESS);
  }
  return result;
}

vx_result_t vx_device_release(vx_device_h device) {
  ++audit.releases;
  return p03_caller_device_release(device);
}

vx_result_t vx_device_memory_info(vx_device_h, uint64_t* free_bytes, uint64_t* used_bytes) {
  *used_bytes = uint64_t{512} * state.modules + uint64_t{128} * state.kernels
      + audit.lingering_charge;
  for (const auto& entry : audit.charges) {
    *used_bytes += entry.second;
  }
  *free_bytes = 0x1000000 - *used_bytes;
  if (fault("capacity_drift") && audit.frees != 0) {
    *free_bytes += 64;
  }
  if (fault("memory_failure") && audit.creates != 0) {
    return VX_ERR_DEVICE_LOST;
  }
  return VX_SUCCESS;
}

vx_result_t vx_buffer_create(vx_device_h device, uint64_t size, uint32_t flags,
                             vx_buffer_h* out) {
  if (fault("reuse_addresses") && state.buffers.empty()) {
    state.next_address = 0x100000;
  }
  const auto result = p03_caller_buffer_create(device, size, flags, out);
  if (result == VX_SUCCESS) {
    ++audit.creates;
    uint64_t charged = fault("rounded") ? ((size + 255) / 256) * 256 : size;
    if (fault("allocation_charge") && audit.creates == 1) {
      charged -= 4;
    }
    audit.charges.emplace(static_cast<Buffer*>(*out), charged);
  }
  return result;
}

vx_result_t vx_buffer_release(vx_buffer_h handle) {
  auto* buffer = static_cast<Buffer*>(handle);
  const auto found = audit.charges.find(buffer);
  check(found != audit.charges.end());
  ++audit.frees;
  if (fault("lingering_charge") && audit.frees == 1) {
    audit.lingering_charge += found->second;
  }
  audit.charges.erase(found);
  const auto result = p03_caller_buffer_release(handle);
  return fault("failed_release") && audit.frees == 1 ? VX_ERR_INVALID_VALUE : result;
}

vx_result_t vx_queue_create(vx_device_h device, const vx_queue_info_t* info, vx_queue_h* out) {
  if (fault("premature_release") && !audit.injected) {
    audit.injected = true;
    // Introduce one extra, fully cleaned temporary allocation in submit phase.
    // The observer must flag its release phase and surplus operations. No live
    // tensor is freed, so the test itself never creates a dangling tensor.
    vx_buffer_h extra = nullptr;
    check(__wrap_vx_buffer_create(device, 64, VX_MEM_READ, &extra) == VX_SUCCESS);
    check(__wrap_vx_buffer_release(extra) == VX_SUCCESS);
  }
  return p03_caller_queue_create(device, info, out);
}

vx_result_t vx_enqueue_write(vx_queue_h queue, vx_buffer_h handle, uint64_t offset,
                             const void* source, uint64_t size, uint32_t n,
                             const vx_event_h* waits, vx_event_h* out) {
  auto* buffer = static_cast<Buffer*>(handle);
  check(offset == 0 && size == buffer->bytes.size());
  return enqueue(queue, n, waits, out, [buffer, source, size] {
    std::memcpy(buffer->bytes.data(), source, size);
    ++state.writes_observed;
  });
}

vx_result_t vx_enqueue_launch(vx_queue_h queue, const vx_launch_info_t* info,
                              uint32_t n, const vx_event_h* waits, vx_event_h* out) {
  check(info->struct_size == sizeof(*info) && info->args_size == 56 && info->ndim == 2
        && info->block_dim[0] == 4 && info->block_dim[1] == 1 && info->block_dim[2] == 1
        && info->grid_dim[0] == 1 && info->grid_dim[1] == 1 && info->grid_dim[2] == 1);
  const auto* first = static_cast<const uint8_t*>(info->args_host);
  const std::vector<uint8_t> args(first, first + info->args_size);
  return enqueue(queue, n, waits, out, [args] { fixture_transport(args); });
}

} // extern "C"
