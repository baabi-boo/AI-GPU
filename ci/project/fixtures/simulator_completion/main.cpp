// SPDX-License-Identifier: Apache-2.0
#include "control.h"
#include <callbacks.h>

#include <array>
#include <cstring>
#include <future>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

extern "C" void __real_free(void* pointer);
extern "C" void __wrap_free(void* pointer) {
  auto& state = completion_test::control;
  if (pointer && state.active.load() != 0) {
    for (auto& tracked : state.tracked) {
      if (tracked.load() == pointer) {
        state.premature_frees.fetch_add(1);
        break;
      }
    }
  }
  __real_free(pointer);
}

namespace {
using completion_test::control;
using completion_test::Outcome;
std::atomic<unsigned> checks{0};

void expect(bool condition, const char* reason) {
  ++checks;
  if (!condition) {
    throw std::runtime_error(reason);
  }
}

void put64(uint8_t* destination, uint64_t value) {
  for (unsigned index = 0; index < 8; ++index) {
    destination[index] = uint8_t(value >> (8 * index));
  }
}

void command(uint8_t* destination, uint8_t opcode, uint64_t arg0 = 0,
             uint64_t arg1 = 0, uint64_t arg2 = 0) {
  destination[0] = opcode;
  put64(destination + 4, arg0);
  if (opcode != 0x06 && opcode != 0x0A && opcode != 0x0C) {
    put64(destination + 12, arg1);
    if (opcode == 0x01 || opcode == 0x02 || opcode == 0x03) {
      put64(destination + 20, arg2);
    }
  }
}

class Device {
public:
  Device() {
    expect(vx_dev_init(&callbacks_) == 0, "callback installation failed");
    expect(callbacks_.dev_open(&context_) == 0, "backend open failed");
    ring_ = static_cast<uint8_t*>(allocate(1024));
    completion_ = static_cast<uint64_t*>(allocate(64));
    data_ = static_cast<uint8_t*>(allocate(128));
    write64(0x100, reinterpret_cast<uint64_t>(ring_));
    write64(0x110, reinterpret_cast<uint64_t>(completion_));
    expect(write(0x118, 10) == 0, "ring size setup failed");
    expect(write(0x11C, 1) == 0, "queue enable failed");
    expect(write(0x000, 1) == 0, "CP enable failed");
  }

  ~Device() {
    control.release();
    if (context_) {
      callbacks_.dev_close(context_);
    }
  }

  void* allocate(uint64_t size) {
    void* pointer = nullptr;
    uint64_t address = 0;
    expect(callbacks_.host_mem_alloc(context_, size, &pointer, &address) == 0,
           "backend host allocation failed");
    expect(address == reinterpret_cast<uint64_t>(pointer), "unified host address differs");
    std::memset(pointer, 0, size);
    expect(regions_.size() < control.tracked.size(), "too many fixture allocations");
    control.tracked[regions_.size()].store(pointer);
    regions_.push_back(address);
    return pointer;
  }

  int write(uint32_t offset, uint32_t value) {
    try {
      return callbacks_.cp_reg_write(context_, offset, value);
    } catch (...) {
      throw std::runtime_error("exception escaped CP write callback");
    }
  }

  int read(uint32_t offset, uint32_t* value) {
    try {
      return callbacks_.cp_reg_read(context_, offset, value);
    } catch (...) {
      throw std::runtime_error("exception escaped CP read callback");
    }
  }

  void write64(uint32_t offset, uint64_t value) {
    expect(write(offset, uint32_t(value)) == 0, "register low write failed");
    expect(write(offset + 4, uint32_t(value >> 32)) == 0, "register high write failed");
  }

  uint8_t* next_line() {
    expect(tail_ < 1024, "fixture ring exhausted");
    auto* line = ring_ + tail_;
    std::memset(line, 0, 64);
    return line;
  }

  int submit() {
    tail_ += 64;
    int result = write(0x120, uint32_t(tail_));
    return result == 0 ? write(0x124, 0) : result;
  }

  int await_terminal(uint32_t target) {
    for (unsigned index = 0; index < 100000; ++index) {
      uint32_t sequence = 0;
      int result = read(0x128, &sequence);
      if (result != 0 || sequence >= target) {
        return result;
      }
      std::this_thread::yield();
    }
    throw std::runtime_error("completion remained pending after released worker");
  }

  void close(bool release_regions) {
    if (release_regions) {
      for (std::size_t index = 0; index < regions_.size(); ++index) {
        expect(callbacks_.host_mem_free(context_, regions_[index]) == 0,
               "host cleanup failed after completion");
        control.tracked[index].store(nullptr);
      }
    }
    expect(callbacks_.dev_close(context_) == 0, "backend close failed");
    context_ = nullptr;
  }

  uint64_t completion() const { return *completion_; }
  uint8_t* data() const { return data_; }

private:
  callbacks_t callbacks_{};
  void* context_ = nullptr;
  uint8_t* ring_ = nullptr;
  uint64_t* completion_ = nullptr;
  uint8_t* data_ = nullptr;
  uint64_t tail_ = 0;
  std::vector<uint64_t> regions_;
};

void launch_pending(Device& device, Outcome outcome, unsigned ordinal,
                    bool queued_dcr = false) {
  control.arm(outcome);
  auto* line = device.next_line();
  command(line, 0x06);
  if (queued_dcr) {
    command(line + 12, 0x04, 0x180, 0xDEAD);
  }
  expect(device.submit() == 0, "held launch submission failed");
  control.await_entered(ordinal);
  uint32_t sequence = 0xA5A5A5A5;
  expect(device.read(0x128, &sequence) == 0, "pending launch poll failed");
  expect(sequence == ordinal - 1, "pending launch retired prematurely");
  expect(device.completion() == ordinal - 1, "pending completion was published");
  expect(control.active.load() == 1, "held processor is not active");
}

void sticky_failure(Outcome outcome) {
  Device device;
  launch_pending(device, outcome, 1, true);
  control.release();
  expect(device.await_terminal(1) != 0, "failed launch was accepted as successful");
  expect(device.completion() == 0, "failed launch published completion");
  expect(control.dcr_writes.load() == 0, "later command executed after failed launch");
  for (uint32_t offset : {0x004u, 0x128u, 0x130u, 0x018u}) {
    uint32_t sentinel = 0xA5A5A5A5;
    expect(device.read(offset, &sentinel) != 0, "failed device accepted another read");
    expect(sentinel == 0xA5A5A5A5, "failed read modified caller output");
  }
  for (uint32_t offset : {0x000u, 0x11Cu, 0x120u, 0x124u}) {
    expect(device.write(offset, 0) != 0, "reset/submission cleared terminal failure");
  }
  expect(control.entered == 1, "failed device started another processor");
  device.close(true);
  expect(control.destroyed_active.load() == 0, "processor destroyed while active");
  expect(control.premature_frees.load() == 0, "host memory freed while worker active");
}

void serial_success() {
  Device device;
  control.legacy_gp = 7;
  for (unsigned ordinal = 1; ordinal <= 3; ++ordinal) {
    launch_pending(device, Outcome::success, ordinal);
    control.release();
    expect(device.await_terminal(ordinal) == 0, "valid launch reported failure");
    expect(device.completion() == ordinal, "successful completion count differs");
  }
#ifdef COMPLETION_SIMX
  expect(control.checked_calls.load() == 3, "SimX did not use checked execution entry");
  expect(control.legacy_calls.load() == 0, "SimX used legacy gp-derived status entry");
#endif
  auto* line = device.next_line();
  command(line, 0x05, 0x155, 0x37);
  expect(device.submit() == 0 && device.await_terminal(4) == 0, "post-launch DCR failed");
  uint32_t value = 0;
  expect(device.read(0x130, &value) == 0 && value == (0x155u ^ 0x37u ^ 0x12345678u),
         "post-launch DCR response differs");
  expect(control.dcr_reads.load() == 1, "DCR did not reach processor");
  device.close(true);
}

void transfers() {
  Device device;
  launch_pending(device, Outcome::success, 1);
  control.release();
  expect(device.await_terminal(1) == 0, "transfer prerequisite launch failed");
  for (unsigned index = 0; index < 64; ++index) {
    device.data()[index] = uint8_t(index * 3 + 1);
  }
  auto* line = device.next_line();
  command(line, 0x01, 0x1000, reinterpret_cast<uint64_t>(device.data()), 64);
  expect(device.submit() == 0 && device.await_terminal(2) == 0, "device write failed");
  line = device.next_line();
  command(line, 0x02, reinterpret_cast<uint64_t>(device.data() + 64), 0x1000, 64);
  expect(device.submit() == 0 && device.await_terminal(3) == 0, "device read failed");
  expect(std::memcmp(device.data(), device.data() + 64, 64) == 0, "round-trip bytes differ");
  if (control.llc) {
    expect(control.memory_reads.load() == 1, "LLC read route not exercised");
    expect(control.memory_writes.load() == 1, "LLC write route not exercised");
  } else {
    expect(control.memory_reads.load() == 0 && control.memory_writes.load() == 0,
           "unified RAM unexpectedly routed through LLC");
  }
  line = device.next_line();
  command(line, 0x0A, 1);
  expect(device.submit() == 0 && device.await_terminal(4) == 0, "cache drain failed");
#ifndef COMPLETION_SIMX
  expect(control.drains.load() == 1, "RTL drain hook was not exercised");
#endif
  device.close(true);
}

void destroy_pending(Outcome outcome) {
  Device device;
  launch_pending(device, outcome, 1);
  std::promise<void> entering;
  auto entered = entering.get_future();
  auto closer = std::async(std::launch::async, [&] {
    entering.set_value();
    device.close(false);
  });
  entered.get();
  expect(control.active.load() == 1, "destruction test lost pending worker");
  expect(control.destroyed.load() == 0, "pending processor was destroyed");
  control.release();
  closer.get();
  expect(control.destroyed.load() == 1, "processor destruction did not finish");
  expect(control.destroyed_active.load() == 0, "processor destroyed while active");
  expect(control.premature_frees.load() == 0, "host memory freed before worker joined");
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    return 2;
  }
  const std::string group(argv[1]);
  control.llc = std::string(argv[2]) == "llc";
  try {
    if (group == "success") {
      serial_success();
    } else if (group == "standard_exception") {
      sticky_failure(Outcome::standard_exception);
    } else if (group == "unknown_exception") {
      sticky_failure(Outcome::unknown_exception);
    } else if (group == "transfers") {
      transfers();
    } else if (group == "destroy_success") {
      destroy_pending(Outcome::success);
    } else if (group == "destroy_exception") {
      destroy_pending(Outcome::standard_exception);
    } else {
      throw std::runtime_error("unknown fixture group");
    }
    std::cout << "PASS simulator-completion " << group << " checks=" << checks.load() << '\n';
    return 0;
  } catch (const std::exception& error) {
    control.release();
    std::cerr << "FAIL simulator-completion " << group << ": " << error.what() << '\n';
    return 1;
  }
}
