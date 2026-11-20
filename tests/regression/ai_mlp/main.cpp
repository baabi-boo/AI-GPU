// SPDX-License-Identifier: Apache-2.0

#include "mlp_runtime.h"
#include "records.h"
#include <ai_matmul_profile.h>
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace ai = vortex::ai;

namespace {

constexpr uint64_t kWaitNanoseconds = 1000000000ull;

struct Options {
  std::string case_id;
  std::string module_path;
  std::string binding_id;
  std::string backend;
  std::string source_revision;
  uint32_t iterations = 0;
};

bool hex_identity(const std::string& value, size_t size) noexcept {
  return value.size() == size && std::all_of(value.begin(), value.end(), [](char digit) {
    return (digit >= '0' && digit <= '9') || (digit >= 'a' && digit <= 'f');
  });
}

bool parse_options(int argc, char** argv, Options* out) {
  uint32_t seen = 0;
  for (int i = 1; i < argc; i += 2) {
    if (i + 1 == argc) {
      return false;
    }
    const std::string option = argv[i];
    const std::string value = argv[i + 1];
    uint32_t bit = 0;
    if (option == "--case") {
      bit = 1u << 0;
      out->case_id = value;
    } else if (option == "--module") {
      bit = 1u << 1;
      out->module_path = value;
    } else if (option == "--qualification-id") {
      bit = 1u << 2;
      out->binding_id = value;
    } else if (option == "--backend") {
      bit = 1u << 3;
      out->backend = value;
    } else if (option == "--source-revision") {
      bit = 1u << 4;
      out->source_revision = value;
    } else if (option == "--iterations" && (value == "1" || value == "2")) {
      bit = 1u << 5;
      out->iterations = static_cast<uint32_t>(value[0] - '0');
    } else {
      return false;
    }
    if ((seen & bit) != 0 || value.empty()) {
      return false;
    }
    seen |= bit;
  }
  const char* selected_driver = std::getenv("VORTEX_DRIVER");
  return seen == 63 && hex_identity(out->binding_id, 64)
      && hex_identity(out->source_revision, 40)
      && (out->backend == "simx" || out->backend == "rtlsim")
      && selected_driver && out->backend == selected_driver;
}

bool read_module(const std::string& path, std::vector<uint8_t>* image) {
  std::ifstream stream(path, std::ios::binary | std::ios::ate);
  if (!stream) {
    return false;
  }
  const auto size = stream.tellg();
  if (size < 16 || size > 16 * 1024 * 1024) {
    return false;
  }
  image->resize(static_cast<size_t>(size));
  stream.seekg(0);
  if (!stream.read(reinterpret_cast<char*>(image->data()), size)) {
    return false;
  }
  return stream.peek() == std::char_traits<char>::eof();
}

void error(const char* action, const ai::ExecutionResult& result) {
  std::cerr << "FAILED " << action << ": validation="
            << ai::status_string(result.validation) << " primary="
            << vx_result_string(result.primary) << " cleanup="
            << vx_result_string(result.cleanup) << " complete="
            << result.complete << '\n';
}

bool profiled(const ai::MlpTrace& trace) noexcept {
  for (const auto& stage : trace.native) {
    const auto& dispatch = stage.dispatch;
    if (!stage.submitted || !stage.waited || !stage.trace_valid || !stage.output_valid
        || !stage.compared || !stage.closed || !dispatch.profiling_enabled
        || dispatch.writes_enqueued != 3 || dispatch.launches_enqueued != 1
        || dispatch.reads_enqueued != 1 || dispatch.wait_calls == 0) {
      return false;
    }
    for (size_t i = 0; i != dispatch.event_profiles.size(); ++i) {
      const auto& profile = dispatch.event_profiles[i];
      if (dispatch.event_results[i] != VX_SUCCESS || !dispatch.event_profile_queried[i]
          || dispatch.event_profile_results[i] != VX_SUCCESS
          || profile.queued_ns > profile.submit_ns || profile.submit_ns > profile.start_ns
          || profile.start_ns > profile.end_ns) {
        return false;
      }
    }
  }
  return true;
}

void record(const char* marker, const ai::MlpTrace& trace, const Options& options,
            uint32_t iteration) {
  std::cout << marker << ' ';
  p04::write_result(std::cout, trace, options.backend, options.source_revision,
                    options.binding_id, iteration);
  std::cout << '\n' << std::flush;
  if (!std::cout) {
    throw std::runtime_error("could not retain model execution record");
  }
}

int run(int argc, char** argv) {
  Options options;
  if (!parse_options(argc, argv, &options)) {
    std::cerr << "FAILED invalid or incomplete model invocation\n";
    return 2;
  }
  const auto* fixture = p04::find_case(options.case_id);
  const auto dtype = static_cast<ai::DType>(ai::kMatmulInputDType);
  if (!fixture || fixture->format != std::string_view(p04::records::dtype(dtype))) {
    std::cerr << "FAILED model case does not match the compiled input format\n";
    return 2;
  }
  std::vector<uint8_t> image;
  if (!read_module(options.module_path, &image)) {
    std::cerr << "FAILED missing, truncated or oversized native module\n";
    return 2;
  }
  ai::ExecutionBinding binding;
  binding.profile = {ai::Profile::p02_tfr_wmma_v1, true, true};
  binding.input_dtype = dtype;
  binding.module_bytes = image.data();
  binding.module_size = image.size();
  binding.qualification_id = options.binding_id;
  binding.enable_profiling = true;

  for (uint32_t iteration = 0; iteration != options.iterations; ++iteration) {
    ai::MlpCase input;
    input.case_id = fixture->id;
    input.input_dtype = dtype;
    input.inputs.input_words = fixture->inputs.input_words;
    input.inputs.w1_words = fixture->inputs.w1_words;
    input.inputs.w2_words = fixture->inputs.w2_words;
    input.expected.hidden_words = fixture->expected.hidden_words;
    input.expected.bridge_words = fixture->expected.bridge_words;
    input.expected.output_words = fixture->expected.output_words;
    input.poison = iteration == 0 ? 0x7fc0deadu : 0xdeadbeefu;
    std::unique_ptr<ai::ManagedMlp> model;
    auto created = ai::ManagedMlp::create(binding, input, &model);
    if (!created.ok() || !created.complete || !model) {
      error("create", created);
      return 1;
    }
    ai::MlpResult inference;
    bool advance_failed = false;
    while (true) {
      inference = model->advance(kWaitNanoseconds);
      if (inference.terminal) {
        break;
      }
      if (inference.execution.complete || inference.execution.primary != VX_ERR_TIMEOUT
          || inference.execution.validation != ai::Status::success
          || inference.execution.cleanup != VX_SUCCESS) {
        error("advance", inference.execution);
        advance_failed = true;
        break;
      }
    }
    if (advance_failed || !inference.ok()) {
      error(ai::mlp_status_string(inference.status), inference.execution);
      record("P04_FAILURE", model->trace(), options, iteration);
    }
    ai::ExecutionResult cleanup;
    bool pending_reported = false;
    do {
      cleanup = model->close(kWaitNanoseconds);
      if (!cleanup.complete) {
        if (!pending_reported) {
          std::cerr << "P04_DRAIN pending operation remains owned\n";
          pending_reported = true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
    } while (!cleanup.complete);
    const auto& trace = model->trace();
    if (advance_failed || !inference.ok() || !cleanup.ok() || !trace.result.ok()
        || !trace.owner_closed || !trace.owner_cleanup.ok()
        || !trace.owner_cleanup.complete || !profiled(trace)) {
      error("model completion, cleanup or profiling", cleanup);
      record("P04_FAILURE", trace, options, iteration);
      return 1;
    }
    record("P04_RESULT", trace, options, iteration);
    model.reset();
  }
  std::cout << "PASSED!\n" << std::flush;
  return std::cout ? 0 : 1;
}

} // namespace

int main(int argc, char** argv) {
  try {
    return run(argc, argv);
  } catch (const std::exception& failure) {
    std::cerr << "FAILED managed model: " << failure.what() << '\n';
    return 1;
  } catch (...) {
    std::cerr << "FAILED managed model: unknown exception\n";
    return 1;
  }
}
