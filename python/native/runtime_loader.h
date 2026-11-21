// Copyright (c) AI-GPU contributors. SPDX-License-Identifier: Apache-2.0
#ifndef VORTEX_AI_PYTHON_RUNTIME_LOADER_H
#define VORTEX_AI_PYTHON_RUNTIME_LOADER_H

#include <cstdint>
#include <string>
#include <vector>

namespace vortex_ai_python {

// All metadata is copied from the immutable build receipt. The module is the
// same checked byte copy passed to the native managed owner.
struct VerifiedBundle {
  std::vector<std::string> libraries;
  std::vector<std::uint8_t> module_bytes;
  std::string format;
  std::string backend;
  std::string qualification_id;
  std::string source_revision;
  std::string bundle_sha256;
  std::string source_sha256;
};

bool verify_bundle(const std::string& root, VerifiedBundle* out,
                   std::string* error);
const char* compiled_bundle_digest();
const char* compiled_source_digest();

// paths are ordered: Ramulator, Ramulator extension, Vortex runtime,
// simulator, backend. A selected path set remains fixed for the process.
bool load_runtime(const std::vector<std::string>& paths,
                  const std::string& backend, std::string* error);
std::vector<std::string> loaded_runtime_paths();

}  // namespace vortex_ai_python

#endif  // VORTEX_AI_PYTHON_RUNTIME_LOADER_H
