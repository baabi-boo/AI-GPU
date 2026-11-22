// SPDX-License-Identifier: Apache-2.0
#ifdef SIMX_FUNCTIONAL
#include <simobject_functional.h>
#else
#include <simobject.h>
#endif

#include <cstdio>
#include <future>
#include <memory>
#include <stdexcept>
#include <string>

namespace {

unsigned checks = 0;
unsigned failures = 0;

void expect(bool condition, const char* message) {
  ++checks;
  if (!condition) {
    ++failures;
    std::fprintf(stderr, "FAIL simulator-platform-cleanup: %s\n", message);
  }
}

uint64_t inflight() {
  return vortex::SimChannelBase::inflight_count().load();
}

struct Observations {
  unsigned delivered = 0;
  unsigned consumed = 0;
  unsigned sum = 0;
  unsigned resets = 0;
  unsigned destroyed = 0;
};

class ModelFailure : public std::runtime_error {
public:
  ModelFailure() : std::runtime_error("model fault before channel pop") {}
};

class Node : public vortex::SimObject<Node> {
public:
  vortex::SimChannel<unsigned> input;

  Node(const vortex::SimContext& context, const char* name,
       Observations& observations, bool fault = false)
      : vortex::SimObject<Node>(context, name)
      , input(this, 4)
      , observations_(observations)
      , fault_(fault) {
    input.tx_callback([this](const unsigned&, uint64_t) {
      ++observations_.delivered;
    });
  }

  ~Node() override {
    ++observations_.destroyed;
  }

protected:
  void on_tick() {
    if (input.empty()) {
      return;
    }
    if (fault_) {
      throw ModelFailure();
    }
    observations_.sum += input.peek();
    ++observations_.consumed;
    input.pop();
  }

  void on_reset() {
    ++observations_.resets;
  }

  friend class vortex::SimObject<Node>;

private:
  Observations& observations_;
  bool fault_;
};

void initialize(vortex::SimPlatform& platform) {
  expect(platform.initialize(), "platform initialization failed");
  platform.set_num_workers(1);
}

void tick_worker(vortex::SimPlatform& platform, unsigned cycles) {
  // The model worker is joined before host teardown. A thrown tick leaves its
  // thread-local execution state on the exiting worker, as in the runtime.
  auto task = std::async(std::launch::async, [&platform, cycles]() {
    for (unsigned cycle = 0; cycle < cycles; ++cycle) {
      platform.tick();
    }
  });
  task.get();
}

void clean_finalize(vortex::SimPlatform& platform) {
  platform.finalize();
  expect(inflight() == 0, "full finalization retained abandoned packet accounting");
  expect(platform.idle(), "fully finalized platform did not become idle");
}

void fresh_context(Node::Ptr* late_owner = nullptr,
                   Observations* late_observations = nullptr) {
  auto& platform = vortex::SimPlatform::instance();
  Observations observations;
  initialize(platform);
  auto fresh = Node::Create("fresh", observations);
  platform.reset();
  fresh->input.send(97, 2);
  expect(inflight() == 1, "fresh reservation inherited an earlier context's count");
  expect(!platform.idle(), "fresh reservation was hidden from idle");

  if (late_owner != nullptr) {
    // The old context is finalized and never executes again. This only stresses
    // late shared-owner destruction while new packet accounting is live.
    expect(late_observations->destroyed == 0, "old owner was not retained past teardown");
    late_owner->reset();
    expect(late_observations->destroyed == 1, "late owner destruction did not complete");
    expect(inflight() == 1, "late owner destruction changed fresh packet accounting");
    expect(!platform.idle(), "late owner destruction hid a fresh reservation");
  }

  // Fixed work bounds also let the old implementation reach its semantic
  // failure: it consumes the fresh packet but never reports idle.
  tick_worker(platform, 4);
  expect(observations.delivered == 1, "fresh packet was not delivered exactly once");
  expect(observations.consumed == 1 && observations.sum == 97,
         "fresh context did not consume its own packet exactly once");
  expect(fresh->input.empty() && fresh->input.size() == 0,
         "fresh context retained packet storage or a reservation");
  expect(inflight() == 0, "fresh consumption retained stale packet accounting");
  expect(platform.idle(), "fresh context consumed its packet but remained non-idle");
  clean_finalize(platform);
  fresh.reset();
  expect(observations.destroyed == 1, "fresh owner was not destroyed");
  clean_finalize(platform);
}

void queued_exception() {
  auto& platform = vortex::SimPlatform::instance();
  Observations observations;
  initialize(platform);
  auto failed = Node::Create("failed", observations, true);
  platform.reset();
  failed->input.send(17, 0);
  bool caught = false;
  try {
    tick_worker(platform, 1);
  } catch (const ModelFailure&) {
    caught = true;
  }
  expect(caught, "queued model failure did not propagate through the worker future");
  expect(observations.delivered == 1 && observations.consumed == 0,
         "model did not fail after delivery and before consumption");
  expect(!failed->input.empty() && failed->input.size() == 1,
         "model failure did not leave a queued packet");
  expect(inflight() == 1 && !platform.idle(),
         "live failed context lost its outstanding packet accounting");
  clean_finalize(platform);
  expect(observations.destroyed == 0, "finalization destroyed an externally held owner");
  failed.reset();
  expect(observations.destroyed == 1, "failed owner destruction did not complete");
  expect(inflight() == 0, "failed owner destruction retained or underflowed accounting");
  fresh_context();
}

void scheduled_reservation() {
  auto& platform = vortex::SimPlatform::instance();
  Observations observations;
  initialize(platform);
  auto abandoned = Node::Create("scheduled", observations);
  platform.reset();
  abandoned->input.send(23, 3);
  expect(abandoned->input.empty() && abandoned->input.size() == 1,
         "scheduled packet was not an undelivered reservation");
  expect(observations.delivered == 0 && observations.consumed == 0,
         "scheduled packet executed before a tick");
  expect(inflight() == 1 && !platform.idle(),
         "undelivered reservation was hidden from idle");
  clean_finalize(platform);
  expect(observations.destroyed == 0, "scheduled owner was not retained through teardown");
  abandoned.reset();
  expect(observations.destroyed == 1, "scheduled owner destruction did not complete");
  expect(inflight() == 0, "dropped reservation survived full owner destruction");
  fresh_context();
  expect(observations.delivered == 0 && observations.consumed == 0,
         "an abandoned scheduled event executed in a fresh context");
}

void late_owner() {
  auto& platform = vortex::SimPlatform::instance();
  Observations observations;
  initialize(platform);
  auto abandoned = Node::Create("late-owner", observations, true);
  platform.reset();
  abandoned->input.send(31, 0);
  bool caught = false;
  try {
    tick_worker(platform, 1);
  } catch (const ModelFailure&) {
    caught = true;
  }
  expect(caught && observations.delivered == 1 && observations.consumed == 0,
         "late owner did not retain a packet after the model exception");
  clean_finalize(platform);
  fresh_context(&abandoned, &observations);
  expect(observations.delivered == 1 && observations.consumed == 0,
         "finalized old context resumed during fresh execution");
}

void normal() {
  auto& platform = vortex::SimPlatform::instance();
  Observations observations;
  initialize(platform);
  Node::Ptr node;
  {
    vortex::SimPlatform::LaunchKeepScope keep(true);
    node = Node::Create("kept", observations);
  }
  platform.reset();
  expect(platform.idle() && inflight() == 0, "clean platform was not initially idle");
  expect(observations.resets == 1, "initial reset did not reach the model");
  node->input.send(7, 0);
  node->input.send(11, 3);
  expect(inflight() == 2 && !platform.idle(), "normal sends lost packet accounting");
  platform.reset_launch();
  expect(observations.resets == 1, "launch reset reset a kept model");
  expect(inflight() == 2 && !platform.idle(),
         "launch reset erased live packet accounting");
  tick_worker(platform, 5);
  expect(observations.delivered == 2 && observations.consumed == 2
             && observations.sum == 18,
         "normal work did not deliver and consume both packets exactly once");
  expect(node->input.empty() && node->input.size() == 0,
         "normal completion retained a packet or reservation");
  expect(inflight() == 0 && platform.idle(), "normal completion did not become idle");
  clean_finalize(platform);
  node.reset();
  expect(observations.destroyed == 1, "normal owner was not destroyed");
  clean_finalize(platform);
}

} // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::fprintf(stderr, "usage: simulator-platform-cleanup GROUP\n");
    return 2;
  }
  const std::string group = argv[1];
  try {
    if (group == "queued_exception") {
      queued_exception();
    } else if (group == "scheduled_reservation") {
      scheduled_reservation();
    } else if (group == "late_owner") {
      late_owner();
    } else if (group == "normal") {
      normal();
    } else {
      throw std::invalid_argument("unknown test group");
    }
  } catch (const std::exception& exception) {
    std::fprintf(stderr, "ERROR simulator-platform-cleanup %s: %s\n",
                 group.c_str(), exception.what());
    return 2;
  }
  if (failures != 0) {
    std::fprintf(stderr, "FAIL simulator-platform-cleanup %s checks=%u failures=%u\n",
                 group.c_str(), checks, failures);
    return 1;
  }
  std::printf("PASS simulator-platform-cleanup %s checks=%u\n", group.c_str(), checks);
  return 0;
}
