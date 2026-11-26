#include "instr_trace.h"
#include <future>
#include <list>
#include <stdexcept>
#include <cstdio>

class RawTraceOwner : public vortex::SimObject<RawTraceOwner> {
public:
  vortex::SimChannel<vortex::instr_trace_t*> input;
  std::list<vortex::instr_trace_t*, vortex::PoolAllocator<vortex::instr_trace_t*, 64>> pending;
  vortex::PoolAllocator<vortex::instr_trace_t, 64> pool;
  RawTraceOwner(const vortex::SimContext& ctx, const char* name)
    : vortex::SimObject<RawTraceOwner>(ctx, name), input(this, 128) {}
protected:
  friend class vortex::SimObject<RawTraceOwner>;
  void on_tick() {
    if (!input.empty()) throw std::runtime_error("bounded probe fault");
  }
  void on_reset() { pending.clear(); }
};
int main() {
  auto& platform = vortex::SimPlatform::instance();
  if (!platform.initialize()) return 1;
  platform.set_num_workers(1);
  auto owner = RawTraceOwner::Create("raw_trace_owner");
  platform.reset();
  std::vector<std::weak_ptr<vortex::Instr>> witnesses;
  std::vector<vortex::instr_trace_t*> saved_for_control;
  auto task = std::async(std::launch::async, [&] {
    for (unsigned index = 0; index < 65; ++index) {
      auto* trace = new (owner->pool.allocate(1)) vortex::instr_trace_t(index);
      trace->instr_ptr = std::make_shared<vortex::Instr>(index);
      witnesses.emplace_back(trace->instr_ptr);
      saved_for_control.emplace_back(trace);
      owner->pending.push_back(trace);
      owner->input.send(trace, 0);
    }
    platform.tick();
  });
  bool caught = false;
  try { task.get(); } catch (const std::runtime_error&) { caught = true; }
  auto inflight_before = vortex::SimChannelBase::inflight_count().load();
  platform.finalize();
  owner.reset();
  unsigned retained = 0;
  for (const auto& weak : witnesses) retained += !weak.expired();
  auto inflight_after = vortex::SimChannelBase::inflight_count().load();
  vortex::PoolAllocator<vortex::instr_trace_t, 64> pool;
  for (auto* trace : saved_for_control) {
    trace->~instr_trace_t();
    pool.deallocate(trace, 1);
  }
  unsigned retained_after_control = 0;
  for (const auto& weak : witnesses) retained_after_control += !weak.expired();
  std::printf("caught=%u inflight_before=%llu inflight_after=%llu retained_after_teardown=%u retained_after_explicit_cleanup=%u\n", caught, static_cast<unsigned long long>(inflight_before), static_cast<unsigned long long>(inflight_after), retained, retained_after_control);
  return caught && inflight_before == 65 && inflight_after == 0 && retained == 65 && retained_after_control == 0 ? 0 : 2;
}
