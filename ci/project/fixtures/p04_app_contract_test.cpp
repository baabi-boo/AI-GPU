// SPDX-License-Identifier: Apache-2.0
// Host-only application boundary and synthetic serializer fixture; no GPU execution.

#define main p04_native_application_main
#include "../../../tests/regression/ai_mlp/main.cpp"
#undef main

#include <limits>
#include <sstream>

namespace {
constexpr const char* kBinding = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
constexpr const char* kRevision = "1234567890abcdef1234567890abcdef12345678";
unsigned checks = 0;
unsigned native_create_calls = 0;
bool native_binding_valid = false;

void require(bool value, const char* message) {
  ++checks;
  if (!value) {
    throw std::runtime_error(message);
  }
}
} // namespace

// These fail-closed stubs only let run() reach its native-create boundary. They
// neither implement a model nor claim to test the runtime status-string mapping.
namespace vortex::ai {
namespace detail {
struct OperationState {};
}
MatmulOperation::~MatmulOperation() = default;
ManagedMatmul::~ManagedMatmul() = default;
ManagedMlp::~ManagedMlp() = default;
ExecutionResult ManagedMlp::create(const ExecutionBinding& binding, const MlpCase& input,
                                  std::unique_ptr<ManagedMlp>*) noexcept {
  ++native_create_calls;
  const auto* fixture = p04::find_case(input.case_id);
  native_binding_valid = fixture && binding.enable_profiling && binding.module_bytes
      && binding.module_size == 16 && binding.qualification_id == kBinding
      && binding.input_dtype == static_cast<DType>(kMatmulInputDType)
      && input.input_dtype == binding.input_dtype && input.poison == 0x7fc0deadu
      && input.inputs.input_words == fixture->inputs.input_words
      && input.inputs.w1_words == fixture->inputs.w1_words
      && input.inputs.w2_words == fixture->inputs.w2_words
      && input.expected.hidden_words == fixture->expected.hidden_words
      && input.expected.bridge_words == fixture->expected.bridge_words
      && input.expected.output_words == fixture->expected.output_words;
  return {Status::success, VX_ERR_NOT_SUPPORTED, VX_SUCCESS, true};
}
MlpResult ManagedMlp::advance(uint64_t) noexcept { std::abort(); }
ExecutionResult ManagedMlp::close(uint64_t) noexcept { std::abort(); }
const MlpTrace& ManagedMlp::trace() const noexcept { std::abort(); }
const char* mlp_status_string(MlpStatus status) noexcept {
  return status == MlpStatus::success ? "success" : "host-only-status-stub";
}
const char* status_string(Status) noexcept { return "host-only-validation-stub"; }
} // namespace vortex::ai

extern "C" const char* vx_result_string(vx_result_t) { return "host-only-runtime-stub"; }

namespace {
std::vector<std::string> arguments(const std::string& module = "module.vxbin") {
  return {"ai_mlp", "--case", std::string(p04::records::dtype(
              static_cast<ai::DType>(ai::kMatmulInputDType))) + "-zero",
          "--module", module, "--qualification-id", kBinding, "--backend", "simx",
          "--source-revision", kRevision, "--iterations", "2"};
}

std::vector<char*> pointers(std::vector<std::string>& values) {
  std::vector<char*> raw;
  for (auto& value : values) {
    raw.push_back(value.data());
  }
  return raw;
}

bool parse(std::vector<std::string> values, Options* result = nullptr) {
  auto raw = pointers(values);
  Options local;
  return parse_options(static_cast<int>(raw.size()), raw.data(), result ? result : &local);
}

void cli() {
  require(setenv("VORTEX_DRIVER", "simx", 1) == 0, "set driver");
  const auto valid = arguments();
  Options parsed;
  require(parse(valid, &parsed), "valid invocation");
  require(parsed.case_id == valid[2] && parsed.module_path == valid[4]
      && parsed.binding_id == kBinding && parsed.backend == "simx"
      && parsed.source_revision == kRevision && parsed.iterations == 2,
      "all option values retained");
  auto changed = valid;
  changed.back() = "1";
  require(parse(changed), "one iteration");
  changed = {valid.front()};
  for (size_t i = valid.size(); i > 1; i -= 2) {
    changed.insert(changed.end(), {valid[i - 2], valid[i - 1]});
  }
  require(parse(changed), "option order is irrelevant");
  for (size_t i = 1; i < valid.size(); i += 2) {
    changed = valid;
    changed.insert(changed.end(), {valid[i], valid[i + 1]});
    require(!parse(changed), "duplicate option rejected");
    changed = valid;
    changed.erase(changed.begin() + i, changed.begin() + i + 2);
    require(!parse(changed), "missing option rejected");
    changed = valid;
    changed[i + 1].clear();
    require(!parse(changed), "empty option rejected");
  }
  require(!parse({"ai_mlp"}), "empty invocation rejected");
  changed = valid;
  changed.push_back("--case");
  require(!parse(changed), "unpaired option rejected");
  changed = valid;
  changed.insert(changed.end(), {"--unknown", "value"});
  require(!parse(changed), "unknown option rejected");
  for (const char* value : {"0", "3", "-1", "+1", "01", "02", "2junk", "1.0", " 1"}) {
    changed = valid;
    changed.back() = value;
    require(!parse(changed), "malformed iteration rejected");
  }
  for (const size_t index : {size_t{6}, size_t{10}}) {
    for (const char digit : {'A', 'g', '-', '\n'}) {
      changed = valid;
      changed[index][0] = digit;
      require(!parse(changed), "noncanonical identity rejected");
    }
    changed = valid;
    changed[index].pop_back();
    require(!parse(changed), "short identity rejected");
    changed = valid;
    changed[index].push_back('a');
    require(!parse(changed), "long identity rejected");
  }
  for (const char* backend : {"rtlsim", "xrt", "SIMX", " simx"}) {
    changed = valid;
    changed[8] = backend;
    require(!parse(changed), "backend mismatch rejected");
  }
  require(setenv("VORTEX_DRIVER", "rtlsim", 1) == 0, "set rtl driver");
  changed = valid;
  changed[8] = "rtlsim";
  require(parse(changed), "bound rtl invocation");
  require(!parse(valid), "simulator binding mismatch rejected");
  require(unsetenv("VORTEX_DRIVER") == 0, "unset driver");
  require(!parse(valid), "missing driver rejected");
}

void modules(const std::string& directory) {
  for (const size_t size : {size_t{0}, size_t{15}, size_t{16}, size_t{64},
                           size_t{16 * 1024 * 1024}, size_t{16 * 1024 * 1024 + 1}}) {
    std::vector<uint8_t> image{0x5a};
    const bool accepted = read_module(directory + "/module-" + std::to_string(size), &image);
    const bool expected = size >= 16 && size <= 16 * 1024 * 1024;
    require(accepted == expected, "module length boundary");
    if (expected) {
      require(image.size() == size && image.front() == 0x12 && image.back() == 0xab,
              "entire module retained");
    } else {
      require(image == std::vector<uint8_t>{0x5a}, "invalid extent does not allocate output");
    }
  }
  std::vector<uint8_t> image;
  require(!read_module(directory + "/absent", &image), "missing module rejected");
}

void guards(const std::string& directory) {
  require(setenv("VORTEX_DRIVER", "simx", 1) == 0, "set app driver");
  const auto valid = arguments(directory + "/module-16");
  auto invoke = [&](std::vector<std::string> values, int expected) {
    auto raw = pointers(values);
    std::ostringstream diagnostics;
    auto* previous = std::cerr.rdbuf(diagnostics.rdbuf());
    int code;
    try {
      code = run(static_cast<int>(raw.size()), raw.data());
    } catch (...) {
      std::cerr.rdbuf(previous);
      throw;
    }
    std::cerr.rdbuf(previous);
    require(code == expected, "native app guard exit status");
    require(diagnostics.str().find("FAILED ") == 0, "native app guard diagnostic");
  };
  for (const char* case_id : {"missing-case", ai::kMatmulInputDType == 1 ? "bf16-zero" : "fp16-zero"}) {
    auto changed = valid;
    changed[2] = case_id;
    invoke(changed, 2);
    require(native_create_calls == 0, "format guard precedes native create");
  }
  auto changed = valid;
  changed[8] = "rtlsim";
  invoke(changed, 2);
  require(native_create_calls == 0, "backend guard precedes native create");
  changed = valid;
  changed[4] = directory + "/absent";
  invoke(changed, 2);
  require(native_create_calls == 0, "module guard precedes native create");
  invoke(valid, 1);
  require(native_create_calls == 1 && native_binding_valid,
          "accepted app parameters reach fail-closed create stub");
}

ai::MlpTrace observed() {
  ai::MlpTrace value;
  for (auto& stage : value.native) {
    stage.submitted = stage.waited = stage.trace_valid = stage.output_valid = true;
    stage.compared = stage.closed = true;
    stage.dispatch.profiling_enabled = true;
    stage.dispatch.writes_enqueued = 3;
    stage.dispatch.launches_enqueued = stage.dispatch.reads_enqueued = 1;
    stage.dispatch.wait_calls = 1;
    stage.dispatch.event_profile_queried.fill(true);
    stage.dispatch.event_profile_results.fill(VX_SUCCESS);
  }
  return value;
}

void profiles() {
  const auto valid = observed();
  require(profiled(valid), "observed zero-duration profiles accepted");
  for (size_t index = 0; index != 3; ++index) {
    for (auto member : {&ai::MlpNativeStage::submitted, &ai::MlpNativeStage::waited,
                       &ai::MlpNativeStage::trace_valid, &ai::MlpNativeStage::output_valid,
                       &ai::MlpNativeStage::compared, &ai::MlpNativeStage::closed}) {
      auto changed = valid;
      changed.native[index].*member = false;
      require(!profiled(changed), "unobserved native stage rejected");
    }
    auto changed = valid;
    changed.native[index].dispatch.profiling_enabled = false;
    require(!profiled(changed), "disabled profiling rejected");
    for (auto member : {&ai::MatmulTrace::writes_enqueued, &ai::MatmulTrace::launches_enqueued,
                       &ai::MatmulTrace::reads_enqueued}) {
      changed = valid;
      ++(changed.native[index].dispatch.*member);
      require(!profiled(changed), "incorrect event count rejected");
    }
    changed = valid;
    changed.native[index].dispatch.wait_calls = 0;
    require(!profiled(changed), "unwaited dispatch rejected");
    for (size_t event = 0; event != 5; ++event) {
      changed = valid;
      changed.native[index].dispatch.event_profile_queried[event] = false;
      require(!profiled(changed), "unqueried event rejected");
      changed = valid;
      changed.native[index].dispatch.event_profile_results[event] = VX_ERR_NOT_SUPPORTED;
      require(!profiled(changed), "failed profile observation rejected");
      changed = valid;
      changed.native[index].dispatch.event_results[event] = VX_ERR_TIMEOUT;
      require(!profiled(changed), "failed event rejected");
      for (const auto& profile : {vx_profile_info_t{1, 0, 0, 0},
                                  vx_profile_info_t{0, 1, 0, 0},
                                  vx_profile_info_t{0, 0, 1, 0}}) {
        changed = valid;
        changed.native[index].dispatch.event_profiles[event] = profile;
        require(!profiled(changed), "reversed event timestamp rejected");
      }
    }
  }
}

void extents() {
  for (const size_t index : {size_t{0}, size_t{1}, size_t{2}}) {
    for (auto member : {&ai::MlpNativeStage::a_size, &ai::MlpNativeStage::b_size,
                       &ai::MlpNativeStage::output_count}) {
      for (const size_t size : {size_t{513}, std::numeric_limits<size_t>::max()}) {
        ai::MlpTrace value;
        value.native[index].*member = size;
        bool rejected = false;
        try {
          std::ostringstream output;
          p04::write_result(output, value, "simx", kRevision, kBinding, 0);
        } catch (const std::runtime_error&) {
          rejected = true;
        }
        require(rejected, "invalid trace extent rejected before buffer read");
      }
    }
  }
  for (auto member : {&ai::MlpNativeStage::a_size, &ai::MlpNativeStage::b_size,
                     &ai::MlpNativeStage::output_count}) {
    ai::MlpNativeStage value;
    value.*member = member == &ai::MlpNativeStage::a_size ? 513
        : member == &ai::MlpNativeStage::b_size ? 257 : 129;
    bool rejected = false;
    try {
      std::ostringstream output;
      p04::records::native(output, value);
    } catch (const std::runtime_error&) {
      rejected = true;
    }
    require(rejected, "one-past-capacity extent rejected");
  }
}

template <size_t N>
void put(std::array<uint8_t, N>& bytes, size_t offset, uint64_t value, size_t count) {
  require(offset <= N && count <= N - offset, "synthetic byte fixture capacity");
  for (size_t index = 0; index != count; ++index) {
    bytes[offset + index] = static_cast<uint8_t>(value >> (index * 8));
  }
}

template <size_t N, size_t M>
void packed(std::array<uint8_t, N>& bytes, const std::array<uint32_t, M>& words,
            size_t first = 0, size_t count = M) {
  for (size_t index = 0; index != count; ++index) {
    put(bytes, index * 4, words[first + index], 4);
  }
}

ai::MlpTrace synthetic(const p04::Fixture& fixture, uint32_t iteration) {
  ai::MlpTrace value = observed();
  value.case_id = fixture.id;
  value.input_dtype = static_cast<ai::DType>(ai::kMatmulInputDType);
  value.poison = iteration == 0 ? 0x7fc0deadu : 0xdeadbeefu;
  value.hidden_valid = value.bridge_attempted = value.bridge_valid = value.bridge_compared = true;
  value.assembled = value.logits_valid = value.logits_compared = value.owner_closed = true;
  value.bridge_status = ai::BridgeStatus::success;
  value.hidden_words = fixture.expected.hidden_words;
  value.bridge_words = fixture.expected.bridge_words;
  value.output_words = fixture.expected.output_words;
  packed(value.bridge_bytes, value.bridge_words);
  value.bridge_checked_words = value.output_checked_words = 64;
  const uint64_t epoch = iteration * 10000;
  value.create_begin_ns = epoch + 100;
  value.create_end_ns = epoch + 200;
  value.advance_ns = 4000;
  value.bridge_ns = 11;
  value.bridge_compare_ns = 12;
  value.assembly_ns = 13;
  value.output_compare_ns = 14;
  value.close_ns = 15;
  value.resources = {true, true, VX_SUCCESS, VX_SUCCESS, 0x100000, 0x20000, 0x100000, 0x20000};
  value.result = {ai::MlpStatus::success, {}, true};
  const char* names[] = {"hidden_matmul", "output_rows_0_7", "output_rows_8_15"};
  for (size_t index = 0; index != 3; ++index) {
    auto& stage = value.native[index];
    auto& dispatch = stage.dispatch;
    stage.operation_id = names[index];
    stage.sequence = static_cast<uint32_t>(index);
    stage.row_begin = index == 2 ? 8 : 0;
    stage.row_end = index == 1 ? 8 : 16;
    stage.submission.complete = false;
    dispatch.qualification_id = kBinding;
    dispatch.input_dtype = value.input_dtype;
    dispatch.poison = value.poison;
    dispatch.m = index == 0 ? 16 : 8;
    dispatch.n = index == 0 ? 8 : 4;
    dispatch.k = index == 0 ? 16 : 8;
    dispatch.a_address = 0x1000;
    dispatch.b_address = 0x2000;
    dispatch.d_address = 0x3000;
    dispatch.a_bytes = stage.a_size = dispatch.m * dispatch.k * 2;
    dispatch.b_bytes = stage.b_size = dispatch.k * dispatch.n * 2;
    stage.output_count = stage.checked_words = dispatch.m * dispatch.n;
    dispatch.d_bytes = stage.output_count * 4;
    const uint32_t header[] = {1, 56, ai::kMatmulInputDType, 0,
                               dispatch.m, dispatch.n, dispatch.k, 0};
    for (size_t word = 0; word != 8; ++word) {
      put(dispatch.argument_bytes, word * 4, header[word], 4);
    }
    put(dispatch.argument_bytes, 32, dispatch.a_address, 8);
    put(dispatch.argument_bytes, 40, dispatch.b_address, 8);
    put(dispatch.argument_bytes, 48, dispatch.d_address, 8);
    if (index == 0) {
      packed(stage.a_bytes, fixture.inputs.input_words);
      packed(stage.b_bytes, fixture.inputs.w1_words);
      stage.output_words = fixture.expected.hidden_words;
    } else {
      packed(stage.a_bytes, value.bridge_words, (index - 1) * 32, 32);
      packed(stage.b_bytes, fixture.inputs.w2_words);
      std::copy_n(value.output_words.begin() + (index - 1) * 32, 32, stage.output_words.begin());
    }
    stage.submit_begin_ns = epoch + 1000 + index * 1000;
    stage.submit_end_ns = stage.submit_begin_ns + 10;
    stage.wait_ns = 100;
    stage.compare_ns = 16 + index;
    stage.close_ns = 19 + index;
    for (size_t event = 0; event != 5; ++event) {
      const uint64_t begin = stage.submit_begin_ns;
      dispatch.event_profiles[event] = {begin + event, begin + 20 + event * 10,
                                        begin + 22 + event * 10, begin + 25 + event * 10};
    }
  }
  return value;
}

void emit(const std::string& case_id, const std::string& backend) {
  const auto* fixture = p04::find_case(case_id);
  require(fixture && fixture->format == std::string_view(p04::records::dtype(
      static_cast<ai::DType>(ai::kMatmulInputDType))), "synthetic fixture matches build");
  require(backend == "simx" || backend == "rtlsim", "synthetic backend label");
  std::cout << "host-only synthetic record fixture; no GPU execution\n";
  for (uint32_t iteration = 0; iteration != 2; ++iteration) {
    const auto trace = synthetic(*fixture, iteration);
    require(profiled(trace), "synthetic profile predicate");
    std::cout << "P04_RESULT ";
    p04::write_result(std::cout, trace, backend, kRevision, kBinding, iteration);
    std::cout << '\n';
  }
  std::cout << "PASSED!\n";
}

void edges() {
  ai::MlpTrace value;
  value.case_id = "quote\"\\tab\tline\n";
  value.case_id.append({char{0}, char{1}, char{31}});
  value.case_id += "\xc3\xa9";
  value.input_dtype = static_cast<ai::DType>(0xffffffffu);
  value.hidden_words.front() = 0xffffffffu;
  value.hidden_words.back() = 0x80000000u;
  value.bridge_bytes.front() = 0xff;
  value.bridge_bytes.back() = 0x80;
  value.create_begin_ns = std::numeric_limits<uint64_t>::max();
  value.result.status = ai::MlpStatus::success;
  for (size_t index = 0; index != 3; ++index) {
    auto& stage = value.native[index];
    stage.a_size = index == 2 ? stage.a_bytes.size() : index;
    stage.b_size = index == 2 ? stage.b_bytes.size() : index;
    stage.output_count = index == 2 ? stage.output_words.size() : index;
    stage.a_bytes.fill(0xab);
    stage.b_bytes.fill(0xcd);
    stage.output_words.fill(0x80000001u);
    stage.dispatch.input_dtype = ai::DType::fp32;
    stage.dispatch.wait_calls = std::numeric_limits<uint64_t>::max();
    stage.dispatch.event_results.fill(VX_ERR_TIMEOUT);
  }
  std::cout << std::hex << std::boolalpha;
  p04::write_result(std::cout, value, "simx", kRevision, kBinding, 1);
  std::cout << '\n';
}
} // namespace

int main(int argc, char** argv) {
  try {
    require(argc >= 2, "host test group required");
    const std::string group = argv[1];
    if (group == "cli") {
      cli();
    } else if (group == "modules" || group == "guards") {
      require(argc == 3, "module fixture directory required");
      if (group == "modules") { modules(argv[2]); } else { guards(argv[2]); }
    } else if (group == "profiles") {
      profiles();
    } else if (group == "extents") {
      extents();
    } else if (group == "edges") {
      edges();
      return 0;
    } else if (group == "synthetic") {
      require(argc == 4, "synthetic case and backend required");
      emit(argv[2], argv[3]);
      return 0;
    } else {
      throw std::runtime_error("unknown host test group");
    }
    std::cout << "PASS " << group << " checks=" << checks << '\n';
    return 0;
  } catch (const std::exception& failure) {
    std::cerr << "host-only app contract failure: " << failure.what() << '\n';
    return 1;
  }
}
