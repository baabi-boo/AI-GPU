#include <algorithm>
#include <array>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
#include "hooks.h"
namespace hooks = p06_preflight;
namespace ai { constexpr int kMatmulInputDType = 1; }
constexpr size_t kSnapshots=4, kHalfReads=264, kCacheFlushReads=33;
constexpr const char* kNames[]={"after_open","after_prime","after_batch","before_release"};
struct Snapshot { hooks::ModelState before; hooks::ModelState after; };
struct State { std::array<Snapshot,kSnapshots> snapshots; bool lifetime=false; } state;
std::array<hooks::RunObservation,hooks::kMaxRuns> runs;
std::array<hooks::DcrRead,kHalfReads> reads;
std::array<hooks::DcrRead,kCacheFlushReads> flushes;
void require(bool x,const char* s) { if(!x) { throw std::runtime_error(s); } }
const char* boolean(bool v) noexcept { return v ? "true" : "false"; }
extern "C" int p06_preflight_enable_lifetime() noexcept { return 0; }
extern "C" int p06_preflight_get_run(size_t i,hooks::RunObservation* o) noexcept { if(i>=runs.size()) return -1; *o=runs[i];return 0; }
extern "C" int p06_preflight_get_read(size_t i,hooks::DcrRead* o) noexcept { if(i>=reads.size()) return -1; *o=reads[i];return 0; }
extern "C" int p06_preflight_get_cache_flush_read(size_t i,hooks::DcrRead* o) noexcept { if(i>=flushes.size()) return -1; *o=flushes[i];return 0; }
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


void parent_model(const hooks::ModelState& value) {
  std::printf("{\"live\":%s,\"idle\":%s,\"any_running\":%s,\"generation\":%" PRIu64
      ",\"ticks\":%" PRIu64 ",\"reset_generation\":%" PRIu64 ",\"core_cycles\":%" PRIu64
      ",\"core_instructions\":%" PRIu64 ",\"exitcode\":%d}", boolean(value.live),
      boolean(value.idle), boolean(value.any_running), value.generation, value.ticks,
      value.reset_generation, value.core_cycles, value.core_instructions, value.exitcode);
}


void print_pending_read(const hooks::DcrRead& read) {
  std::printf("{\"sequence\":%" PRIu64 ",\"pending_before\":%" PRIu64
      ",\"pending_after\":%" PRIu64 "}", read.sequence, read.pending_before, read.pending_after);
}


void print_lifetime(const Options& opts, const char* format, const hooks::Observation& observed) {
  std::printf("P06_MANAGED_COUNTER_LIFETIME {\"schema_version\":1,"
      "\"contract_id\":\"p06-managed-counter-lifetime-v1\","
      "\"process_id\":\"preflight-simx-%s-%s\",\"sample_id\":\"%s\","
      "\"execution_binding_sha256\":\"%s\",\"format\":\"%s\",\"policy\":\"%s\","
      "\"backend\":\"simx\",\"xlen\":64,\"checked_counter_bits\":64,"
      "\"simulation_workers\":1,\"seeded\":false,\"constructed_state\":",
      format, opts.policy.c_str(), opts.sample_id.c_str(), opts.qualification_id.c_str(),
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
  const char* format = ai::kMatmulInputDType == 1 ? "fp16" : "bf16";
  Options opts;
  require(options(argc, argv, format, &opts) && opts.pair_index == 0 && opts.phase == "warmup",
          "preflight requires the unchanged pair-zero warm-up arguments");
  return 0;
}

bool admitted(std::vector<std::string> args,bool expected_lifetime) {
  state.lifetime=false;
  std::vector<char*> pointers;
  for(auto& arg:args) pointers.push_back(arg.data());
  pointers.push_back(nullptr);
  try { if(run_preflight(static_cast<int>(args.size()),pointers.data())!=0) return false; }
  catch(...) { return false; }
  return state.lifetime==expected_lifetime && pointers[args.size()-(expected_lifetime?1:0)]==nullptr;
}
int main() {
 std::vector<std::string> args={"program","--policy","per_operation","--module","/tmp/kernel.vxbin","--qualification-id",std::string(64,'a'),"--sample-id","warm-simx-fp16-pair0-per_operation","--pair-index","0","--phase","warmup"};
 require(admitted(args,false),"default CLI failed");
 auto selected=args; selected.insert(selected.begin()+1,"--lifetime");
 require(admitted(selected,true),"selected CLI failed");
 auto duplicate=selected; duplicate.insert(duplicate.begin()+1,"--lifetime");
 require(!admitted(duplicate,true),"duplicate admitted");
 auto misplaced=args; misplaced.insert(misplaced.begin()+3,"--lifetime");
 require(!admitted(misplaced,false),"misplaced admitted");
 auto unknown=args; unknown.insert(unknown.begin()+1,"--lifetime=1");
 require(!admitted(unknown,false),"unknown admitted");
 require(!admitted({"program","--lifetime"},true),"missing arguments admitted");
 auto replaced=args; replaced[1]="--lifetime";
 require(!admitted(replaced,true),"replaced option admitted");
 hooks::ModelState model;
 model.live=true; model.idle=true; model.generation=1;
 model.ticks=std::numeric_limits<uint64_t>::max(); model.reset_generation=model.ticks;
 model.core_cycles=model.ticks; model.core_instructions=model.ticks;
 model.exitcode=std::numeric_limits<int>::min(); model.pending_reads=model.ticks;
 parent_model(model); std::putchar('\n'); print_model(model); std::putchar('\n');
 print_model(model,true); std::putchar('\n');
 for(size_t i=0;i<runs.size();++i) {
   runs[i].ordinal=i+1; runs[i].before=model; runs[i].after=model;
   runs[i].after.exitcode=std::numeric_limits<int>::max();
   runs[i].real_call_entered=true; runs[i].completed=true;
 }
 for(size_t i=0;i<reads.size();++i) { reads[i].sequence=i+1; reads[i].pending_before=model.pending_reads; }
 for(size_t i=0;i<flushes.size();++i) { flushes[i].sequence=i+1; }
 for(auto& snapshot:state.snapshots) { snapshot.before=model; snapshot.after=model; }
 hooks::Observation observed; observed.constructed_state=model;
 observed.destruction.before=model; observed.destruction.completed=true;
 observed.destruction.idle_after=true; observed.destruction.reset_after=model.reset_generation;
 Options opts; require(options(static_cast<int>(args.size()),[&args](){ static std::vector<char*> p;for(auto& a:args)p.push_back(a.data());p.push_back(nullptr);return p.data();}(),"fp16",&opts),"options failed");
 print_lifetime(opts,"fp16",observed);
 require(std::fflush(stdout)==0 && !std::ferror(stdout),"stdout failed");
}
