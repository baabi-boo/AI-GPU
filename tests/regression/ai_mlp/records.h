// SPDX-License-Identifier: Apache-2.0

#ifndef P04_MLP_RECORDS_H
#define P04_MLP_RECORDS_H

#include "mlp_runtime.h"
#include "p04_fixtures.h"
#include <iomanip>
#include <ostream>
#include <stdexcept>
#include <string_view>

namespace p04 {
namespace records {

inline void string(std::ostream& out, std::string_view value) {
  constexpr char digits[] = "0123456789abcdef";
  out.put('"');
  for (const unsigned char byte : value) {
    if (byte == '"' || byte == '\\') {
      out.put('\\');
      out.put(static_cast<char>(byte));
    } else if (byte < 0x20) {
      out << "\\u00" << digits[byte >> 4] << digits[byte & 15];
    } else {
      out.put(static_cast<char>(byte));
    }
  }
  out.put('"');
}

class Object {
 public:
  explicit Object(std::ostream& out) : out_(out) { out_.put('{'); }

  void key(const char* name) {
    if (!first_) {
      out_.put(',');
    }
    first_ = false;
    string(out_, name);
    out_.put(':');
  }

  void number(const char* name, uint64_t value) {
    key(name);
    out_ << std::dec << value;
  }

  void boolean(const char* name, bool value) {
    key(name);
    out_ << (value ? "true" : "false");
  }

  void text(const char* name, std::string_view value) {
    key(name);
    string(out_, value);
  }

  void finish() { out_.put('}'); }

 private:
  std::ostream& out_;
  bool first_ = true;
};

inline const char* dtype(vortex::ai::DType value) noexcept {
  switch (value) {
    case vortex::ai::DType::fp16: return "fp16";
    case vortex::ai::DType::bf16: return "bf16";
    case vortex::ai::DType::fp32: return "fp32";
  }
  return "unknown";
}

inline void bytes(std::ostream& out, const uint8_t* values, size_t count) {
  constexpr char digits[] = "0123456789abcdef";
  out.put('"');
  for (size_t i = 0; i != count; ++i) {
    out.put(digits[values[i] >> 4]);
    out.put(digits[values[i] & 15]);
  }
  out.put('"');
}

inline void words(std::ostream& out, const uint32_t* values, size_t count) {
  constexpr char digits[] = "0123456789abcdef";
  out.put('[');
  for (size_t i = 0; i != count; ++i) {
    if (i != 0) {
      out.put(',');
    }
    out.put('"');
    for (unsigned nibble = 8; nibble != 0; --nibble) {
      out.put(digits[(values[i] >> ((nibble - 1) * 4)) & 15]);
    }
    out.put('"');
  }
  out.put(']');
}

template <typename T, size_t N>
inline void integers(std::ostream& out, const std::array<T, N>& values) {
  out.put('[');
  for (size_t i = 0; i != N; ++i) {
    if (i != 0) {
      out.put(',');
    }
    out << std::dec << static_cast<uint64_t>(values[i]);
  }
  out.put(']');
}

template <size_t N>
inline void booleans(std::ostream& out, const std::array<bool, N>& values) {
  out.put('[');
  for (size_t i = 0; i != N; ++i) {
    if (i != 0) {
      out.put(',');
    }
    out << (values[i] ? "true" : "false");
  }
  out.put(']');
}

inline void execution(std::ostream& out, const vortex::ai::ExecutionResult& value) {
  Object object(out);
  object.number("validation", static_cast<uint32_t>(value.validation));
  object.number("primary", static_cast<uint32_t>(value.primary));
  object.number("cleanup", static_cast<uint32_t>(value.cleanup));
  object.boolean("complete", value.complete);
  object.finish();
}

inline void result(std::ostream& out, const vortex::ai::MlpResult& value) {
  Object object(out);
  object.text("status", vortex::ai::mlp_status_string(value.status));
  object.key("execution");
  execution(out, value.execution);
  object.boolean("terminal", value.terminal);
  object.finish();
}

inline void profile(std::ostream& out, const vx_profile_info_t& value) {
  Object object(out);
  object.number("queued_ns", value.queued_ns);
  object.number("submit_ns", value.submit_ns);
  object.number("start_ns", value.start_ns);
  object.number("end_ns", value.end_ns);
  object.finish();
}

inline void dispatch(std::ostream& out, const vortex::ai::MatmulTrace& value) {
  Object object(out);
  object.text("qualification_id", value.qualification_id);
  object.text("input_dtype", dtype(value.input_dtype));
  object.number("m", value.m);
  object.number("n", value.n);
  object.number("k", value.k);
  object.number("poison", value.poison);
  object.number("a_address", value.a_address);
  object.number("b_address", value.b_address);
  object.number("d_address", value.d_address);
  object.number("a_bytes", value.a_bytes);
  object.number("b_bytes", value.b_bytes);
  object.number("d_bytes", value.d_bytes);
  object.key("argument_bytes");
  bytes(out, value.argument_bytes.data(), value.argument_bytes.size());
  object.number("writes_enqueued", value.writes_enqueued);
  object.number("launches_enqueued", value.launches_enqueued);
  object.number("reads_enqueued", value.reads_enqueued);
  object.number("wait_calls", value.wait_calls);
  object.number("timed_out_waits", value.timed_out_waits);
  object.key("event_results");
  integers(out, value.event_results);
  object.boolean("profiling_enabled", value.profiling_enabled);
  object.key("event_profiles");
  out.put('[');
  for (size_t i = 0; i != value.event_profiles.size(); ++i) {
    if (i != 0) {
      out.put(',');
    }
    profile(out, value.event_profiles[i]);
  }
  out.put(']');
  object.key("event_profile_results");
  integers(out, value.event_profile_results);
  object.key("event_profile_queried");
  booleans(out, value.event_profile_queried);
  object.finish();
}

inline void native(std::ostream& out, const vortex::ai::MlpNativeStage& value) {
  if (value.a_size > value.a_bytes.size() || value.b_size > value.b_bytes.size()
      || value.output_count > value.output_words.size()) {
    throw std::runtime_error("model trace array extent is invalid");
  }
  Object object(out);
  object.text("operation_id", value.operation_id ? value.operation_id : "");
  object.number("sequence", value.sequence);
  object.number("row_begin", value.row_begin);
  object.number("row_end", value.row_end);
  object.boolean("submitted", value.submitted);
  object.boolean("waited", value.waited);
  object.boolean("trace_valid", value.trace_valid);
  object.boolean("output_valid", value.output_valid);
  object.boolean("compared", value.compared);
  object.boolean("closed", value.closed);
  object.key("submission");
  execution(out, value.submission);
  object.key("completion");
  execution(out, value.completion);
  object.key("cleanup");
  execution(out, value.cleanup);
  object.key("dispatch");
  dispatch(out, value.dispatch);
  object.number("a_size", value.a_size);
  object.number("b_size", value.b_size);
  object.number("output_count", value.output_count);
  object.key("a_bytes");
  bytes(out, value.a_bytes.data(), value.a_size);
  object.key("b_bytes");
  bytes(out, value.b_bytes.data(), value.b_size);
  object.key("output_words");
  words(out, value.output_words.data(), value.output_count);
  object.number("checked_words", value.checked_words);
  object.number("mismatches", value.mismatches);
  object.number("submit_begin_ns", value.submit_begin_ns);
  object.number("submit_end_ns", value.submit_end_ns);
  object.number("wait_ns", value.wait_ns);
  object.number("compare_ns", value.compare_ns);
  object.number("close_ns", value.close_ns);
  object.finish();
}

inline void resources(std::ostream& out, const vortex::ai::MlpResources& value) {
  Object object(out);
  object.boolean("before_valid", value.before_valid);
  object.boolean("after_valid", value.after_valid);
  object.number("before_status", static_cast<uint32_t>(value.before_status));
  object.number("after_status", static_cast<uint32_t>(value.after_status));
  object.number("free_before", value.free_before);
  object.number("used_before", value.used_before);
  object.number("free_after", value.free_after);
  object.number("used_after", value.used_after);
  object.finish();
}

inline void trace(std::ostream& out, const vortex::ai::MlpTrace& value) {
  Object object(out);
  object.text("case_id", value.case_id);
  object.text("input_dtype", dtype(value.input_dtype));
  object.number("poison", value.poison);
  object.key("native");
  out.put('[');
  for (size_t i = 0; i != value.native.size(); ++i) {
    if (i != 0) {
      out.put(',');
    }
    native(out, value.native[i]);
  }
  out.put(']');
  object.boolean("hidden_valid", value.hidden_valid);
  object.boolean("bridge_attempted", value.bridge_attempted);
  object.boolean("bridge_valid", value.bridge_valid);
  object.boolean("bridge_compared", value.bridge_compared);
  object.boolean("assembled", value.assembled);
  object.boolean("logits_valid", value.logits_valid);
  object.boolean("logits_compared", value.logits_compared);
  object.boolean("owner_closed", value.owner_closed);
  object.number("bridge_status", static_cast<uint32_t>(value.bridge_status));
  object.key("hidden_words");
  words(out, value.hidden_words.data(), value.hidden_words.size());
  object.key("bridge_bytes");
  bytes(out, value.bridge_bytes.data(), value.bridge_bytes.size());
  object.key("bridge_words");
  words(out, value.bridge_words.data(), value.bridge_words.size());
  object.key("output_words");
  words(out, value.output_words.data(), value.output_words.size());
  object.number("bridge_checked_words", value.bridge_checked_words);
  object.number("bridge_mismatches", value.bridge_mismatches);
  object.number("output_checked_words", value.output_checked_words);
  object.number("output_mismatches", value.output_mismatches);
  object.number("create_begin_ns", value.create_begin_ns);
  object.number("create_end_ns", value.create_end_ns);
  object.number("advance_ns", value.advance_ns);
  object.number("bridge_ns", value.bridge_ns);
  object.number("bridge_compare_ns", value.bridge_compare_ns);
  object.number("assembly_ns", value.assembly_ns);
  object.number("output_compare_ns", value.output_compare_ns);
  object.number("close_ns", value.close_ns);
  object.key("resources");
  resources(out, value.resources);
  object.key("owner_cleanup");
  execution(out, value.owner_cleanup);
  object.key("result");
  result(out, value.result);
  object.finish();
}

} // namespace records

inline void write_result(std::ostream& out, const vortex::ai::MlpTrace& value,
                         std::string_view backend, std::string_view source_revision,
                         std::string_view qualification_id, uint32_t iteration) {
  records::Object object(out);
  object.number("schema_version", 1);
  object.text("model_id", kModelId);
  object.text("fixture_id", kFixtureId);
  object.text("fixture_sha256", kFixtureSha256);
  object.text("source_revision", source_revision);
  object.text("backend", backend);
  object.number("iteration", iteration);
  object.text("qualification_id", qualification_id);
  object.text("clock", "std::chrono::steady_clock");
  object.text("timing_scope", "host_runtime_observations");
  object.key("trace");
  records::trace(out, value);
  object.finish();
}

} // namespace p04

#endif
