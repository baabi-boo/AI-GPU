// Copyright (c) AI-GPU contributors. SPDX-License-Identifier: Apache-2.0
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "runtime_loader.h"

#include "p05_build_config.h"
#include "vortex2.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <limits>
#include <link.h>
#include <memory>
#include <mutex>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>

namespace vortex_ai_python {
namespace {

constexpr std::uint64_t kManifestLimit = 4 * 1024 * 1024;
constexpr std::uint64_t kModuleLimit = 16 * 1024 * 1024;
constexpr std::uint64_t kLibraryLimit = 256 * 1024 * 1024;
constexpr std::size_t kPathLimit = 4096;
constexpr std::array<const char*, 6> kRoles = {{
    "ramulator", "ramulator_extension", "runtime", "simulator", "backend", "module"}};
constexpr std::array<const char*, 6> kRelativePaths = {{
    "lib/libramulator.so", "lib/libramulator-vortex.so", "lib/libvortex.so",
    "lib/libsimx.so", "lib/libvortex-simx.so", "kernel.vxbin"}};
const pid_t kImportProcess = getpid();

bool fail(std::string* error, const std::string& message) {
  if (error != nullptr) {
    *error = message;
  }
  return false;
}

std::string system_error(const std::string& action, int code) {
  return action + ": " + std::strerror(code);
}

class FileDescriptor {
public:
  explicit FileDescriptor(int fd = -1) : fd_(fd) {}
  ~FileDescriptor() {
    if (fd_ >= 0) {
      close(fd_);
    }
  }
  FileDescriptor(const FileDescriptor&) = delete;
  FileDescriptor& operator=(const FileDescriptor&) = delete;
  FileDescriptor(FileDescriptor&& other) noexcept : fd_(other.fd_) {
    other.fd_ = -1;
  }
  FileDescriptor& operator=(FileDescriptor&& other) noexcept {
    if (this != &other) {
      if (fd_ >= 0) {
        close(fd_);
      }
      fd_ = other.fd_;
      other.fd_ = -1;
    }
    return *this;
  }
  int get() const { return fd_; }

private:
  int fd_;
};

// The standard SHA-256 compression function uses unsigned, modulo-2^32
// arithmetic. File bounds keep its byte counter far below overflow.
class Sha256 {
public:
  void update(const std::uint8_t* data, std::size_t size) {
    total_ += size;
    while (size != 0) {
      const std::size_t count = std::min(size, buffer_.size() - used_);
      std::memcpy(buffer_.data() + used_, data, count);
      used_ += count;
      data += count;
      size -= count;
      if (used_ == buffer_.size()) {
        compress(buffer_.data());
        used_ = 0;
      }
    }
  }

  std::string finish() {
    const std::uint64_t bits = total_ * 8;
    const std::uint8_t marker = 0x80;
    const std::uint8_t zero = 0;
    update(&marker, 1);
    while (used_ != 56) {
      update(&zero, 1);
    }
    std::array<std::uint8_t, 8> length{};
    for (std::size_t i = 0; i < length.size(); ++i) {
      length[7 - i] = static_cast<std::uint8_t>(bits >> (i * 8));
    }
    update(length.data(), length.size());
    constexpr char hex[] = "0123456789abcdef";
    std::string result(64, '0');
    for (std::size_t i = 0; i < state_.size(); ++i) {
      for (std::size_t j = 0; j < 8; ++j) {
        result[i * 8 + j] = hex[(state_[i] >> ((7 - j) * 4)) & 15];
      }
    }
    return result;
  }

private:
  static std::uint32_t rotate(std::uint32_t value, unsigned count) {
    return (value >> count) | (value << (32 - count));
  }

  void compress(const std::uint8_t* block) {
    static constexpr std::array<std::uint32_t, 64> constants = {{
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
        0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
        0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
        0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
        0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2}};
    std::array<std::uint32_t, 64> words{};
    for (std::size_t i = 0; i < 16; ++i) {
      words[i] = (std::uint32_t(block[4 * i]) << 24)
                 | (std::uint32_t(block[4 * i + 1]) << 16)
                 | (std::uint32_t(block[4 * i + 2]) << 8)
                 | std::uint32_t(block[4 * i + 3]);
    }
    for (std::size_t i = 16; i < words.size(); ++i) {
      const auto first = rotate(words[i - 15], 7) ^ rotate(words[i - 15], 18)
                         ^ (words[i - 15] >> 3);
      const auto second = rotate(words[i - 2], 17) ^ rotate(words[i - 2], 19)
                          ^ (words[i - 2] >> 10);
      words[i] = words[i - 16] + first + words[i - 7] + second;
    }
    auto a = state_[0];
    auto b = state_[1];
    auto c = state_[2];
    auto d = state_[3];
    auto e = state_[4];
    auto f = state_[5];
    auto g = state_[6];
    auto h = state_[7];
    for (std::size_t i = 0; i < words.size(); ++i) {
      const auto first = h + (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25))
                         + ((e & f) ^ (~e & g)) + constants[i] + words[i];
      const auto second = (rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22))
                          + ((a & b) ^ (a & c) ^ (b & c));
      h = g;
      g = f;
      f = e;
      e = d + first;
      d = c;
      c = b;
      b = a;
      a = first + second;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
  }

  std::array<std::uint32_t, 8> state_ = {{
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19}};
  std::array<std::uint8_t, 64> buffer_{};
  std::size_t used_ = 0;
  std::uint64_t total_ = 0;
};

bool is_hex(const char* value, std::size_t length) {
  if (value == nullptr || std::strlen(value) != length) {
    return false;
  }
  for (std::size_t i = 0; i < length; ++i) {
    if (!((value[i] >= '0' && value[i] <= '9')
          || (value[i] >= 'a' && value[i] <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool compiled_artifacts(std::array<const build::Artifact*, 6>* ordered,
                        std::string* error) {
  if (build::bundle_sha256[0] == '\0') {
    return fail(error, "this vortex_ai wheel is unbound and cannot execute; install a wheel "
                       "built for a qualified native bundle (VORTEX_AI_BUNDLE at build time)");
  }
  if (!is_hex(build::bundle_sha256, 64) || !is_hex(build::source_sha256, 64)
      || !is_hex(build::qualification_id, 64) || !is_hex(build::source_revision, 40)
      || std::strcmp(build::backend, "simx") != 0
      || (std::strcmp(build::format, "fp16") != 0
          && std::strcmp(build::format, "bf16") != 0)) {
    return fail(error, "installed extension contains an invalid compiled bundle receipt; "
                       "rebuild it from a validated qualified bundle");
  }
  ordered->fill(nullptr);
  for (const auto& artifact : build::artifacts) {
    bool matched = false;
    for (std::size_t i = 0; i < kRoles.size(); ++i) {
      if (artifact.role != nullptr && std::strcmp(artifact.role, kRoles[i]) == 0) {
        const auto limit = i == 5 ? kModuleLimit : kLibraryLimit;
        if ((*ordered)[i] != nullptr || artifact.path == nullptr
            || std::strcmp(artifact.path, kRelativePaths[i]) != 0
            || !is_hex(artifact.sha256, 64) || artifact.size == 0
            || artifact.size > limit || (i == 5 && artifact.size < 16)) {
          return fail(error, "installed extension contains an invalid artifact record for "
                             + std::string(kRoles[i]));
        }
        (*ordered)[i] = &artifact;
        matched = true;
        break;
      }
    }
    if (!matched) {
      return fail(error, "installed extension contains an unknown compiled artifact role");
    }
  }
  for (const auto* artifact : *ordered) {
    if (artifact == nullptr) {
      return fail(error, "installed extension has an incomplete compiled artifact inventory");
    }
  }
  return true;
}

bool safe_path_text(const std::string& path) {
  if (path.empty() || path.size() >= kPathLimit) {
    return false;
  }
  for (unsigned char character : path) {
    if (character < 32 || character == 127) {
      return false;
    }
  }
  return true;
}

// Traverse each directory with O_NOFOLLOW, including the bundle root's
// ancestors. The retained descriptors anchor subsequent artifact reads.
bool open_root(const std::string& root, FileDescriptor* directory,
               std::string* absolute, std::string* error) {
  if (!safe_path_text(root)) {
    return fail(error, "native bundle root must be a nonempty path without control characters");
  }
  std::string path = root;
  if (path.front() != '/') {
    std::unique_ptr<char, decltype(&std::free)> cwd(getcwd(nullptr, 0), &std::free);
    if (cwd == nullptr) {
      return fail(error, system_error("cannot resolve native bundle directory", errno));
    }
    path = std::string(cwd.get()) + "/" + path;
  }
  if (path.size() >= kPathLimit) {
    return fail(error, "native bundle root exceeds the supported path length");
  }
  if (!safe_path_text(path) || path.find_first_of(":;$") != std::string::npos) {
    return fail(error, "native bundle root contains loader separators or expansion tokens");
  }
  FileDescriptor current(open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC));
  if (current.get() < 0) {
    return fail(error, system_error("cannot open filesystem root", errno));
  }
  std::vector<std::string> parts;
  std::size_t position = 1;
  while (position <= path.size()) {
    const auto slash = path.find('/', position);
    const auto end = slash == std::string::npos ? path.size() : slash;
    const auto component = path.substr(position, end - position);
    position = end + 1;
    if (component.empty() || component == ".") {
      continue;
    }
    FileDescriptor next(openat(current.get(), component.c_str(),
                               O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    if (next.get() < 0) {
      return fail(error, system_error("cannot open native bundle directory (symlinks are "
                                      "not allowed): " + path, errno));
    }
    current = std::move(next);
    if (component == "..") {
      if (!parts.empty()) {
        parts.pop_back();
      }
    } else {
      parts.push_back(component);
    }
  }
  absolute->clear();
  for (const auto& part : parts) {
    *absolute += "/" + part;
  }
  if (absolute->empty()) {
    *absolute = "/";
  }
  *directory = std::move(current);
  return true;
}

std::string child_path(const std::string& root, const std::string& child) {
  return root + (root == "/" ? "" : "/") + child;
}

bool same_file(const struct stat& first, const struct stat& second) {
  return first.st_dev == second.st_dev && first.st_ino == second.st_ino
         && first.st_mode == second.st_mode && first.st_size == second.st_size
         && first.st_mtim.tv_sec == second.st_mtim.tv_sec
         && first.st_mtim.tv_nsec == second.st_mtim.tv_nsec
         && first.st_ctim.tv_sec == second.st_ctim.tv_sec
         && first.st_ctim.tv_nsec == second.st_ctim.tv_nsec;
}

bool check_library_directory(int fd, std::string* error) {
  struct stat before{};
  if (fstat(fd, &before) != 0) {
    return fail(error, system_error("cannot inspect native bundle lib directory", errno));
  }
  // A separate open description keeps repeated scans independent of readdir's
  // offset; dup would share that offset with the retained directory descriptor.
  const int copy = openat(fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (copy < 0) {
    return fail(error, system_error("cannot inspect native bundle lib directory", errno));
  }
  DIR* raw = fdopendir(copy);
  if (raw == nullptr) {
    const int code = errno;
    close(copy);
    return fail(error, system_error("cannot list native bundle lib directory", code));
  }
  std::unique_ptr<DIR, int (*)(DIR*)> directory(raw, closedir);
  std::array<bool, 5> seen{};
  for (;;) {
    errno = 0;
    const dirent* entry = readdir(directory.get());
    if (entry == nullptr) {
      if (errno != 0) {
        return fail(error, system_error("cannot list native bundle lib directory", errno));
      }
      break;
    }
    if (std::strcmp(entry->d_name, ".") == 0 || std::strcmp(entry->d_name, "..") == 0) {
      continue;
    }
    bool expected = false;
    for (std::size_t i = 0; i < seen.size(); ++i) {
      if (std::strcmp(entry->d_name, kRelativePaths[i] + 4) == 0) {
        struct stat file{};
        if (seen[i] || fstatat(fd, entry->d_name, &file, AT_SYMLINK_NOFOLLOW) != 0
            || !S_ISREG(file.st_mode)) {
          return fail(error, "native bundle lib entries must be regular files without symlinks: "
                             + std::string(entry->d_name));
        }
        seen[i] = true;
        expected = true;
        break;
      }
    }
    if (!expected) {
      return fail(error, "native bundle lib directory must contain exactly the five declared DSOs; "
                         "unexpected entry: " + std::string(entry->d_name));
    }
  }
  for (std::size_t i = 0; i < seen.size(); ++i) {
    if (!seen[i]) {
      return fail(error, "native bundle lib directory is missing "
                         + std::string(kRelativePaths[i] + 4));
    }
  }
  struct stat after{};
  if (fstat(fd, &after) != 0 || !same_file(before, after)) {
    return fail(error, "native bundle lib directory changed while being verified");
  }
  return true;
}

bool checked_file(int parent, const char* name, const std::string& label,
                  std::uint64_t limit, std::uint64_t expected_size,
                  const char* expected_digest, std::vector<std::uint8_t>* retained,
                  std::string* error) {
  // O_NONBLOCK prevents an unexpected FIFO/device from blocking before fstat.
  FileDescriptor fd(openat(parent, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK));
  if (fd.get() < 0) {
    return fail(error, system_error("cannot read required bundle file (no symlinks): "
                                    + label, errno));
  }
  struct stat before{};
  if (fstat(fd.get(), &before) != 0) {
    return fail(error, system_error("cannot inspect required bundle file: " + label, errno));
  }
  if (!S_ISREG(before.st_mode) || before.st_size <= 0
      || static_cast<std::uint64_t>(before.st_size) > limit) {
    return fail(error, "bundle file must be a bounded, nonempty regular file: " + label);
  }
  if (expected_size != 0 && static_cast<std::uint64_t>(before.st_size) != expected_size) {
    return fail(error, "bundle file size differs from the installed extension's receipt: " + label);
  }
  if (retained != nullptr) {
    retained->clear();
    retained->reserve(static_cast<std::size_t>(before.st_size));
  }
  Sha256 sha;
  std::array<std::uint8_t, 64 * 1024> block{};
  std::uint64_t total = 0;
  for (;;) {
    const auto count = read(fd.get(), block.data(), block.size());
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return fail(error, system_error("cannot read required bundle file: " + label, errno));
    }
    if (count == 0) {
      break;
    }
    total += static_cast<std::uint64_t>(count);
    if (total > limit || total > static_cast<std::uint64_t>(before.st_size)) {
      return fail(error, "bundle file grew while being verified: " + label);
    }
    sha.update(block.data(), static_cast<std::size_t>(count));
    if (retained != nullptr) {
      retained->insert(retained->end(), block.begin(), block.begin() + count);
    }
  }
  struct stat after{};
  struct stat current{};
  if (fstat(fd.get(), &after) != 0
      || fstatat(parent, name, &current, AT_SYMLINK_NOFOLLOW) != 0) {
    return fail(error, system_error("cannot recheck bundle file: " + label, errno));
  }
  if (total != static_cast<std::uint64_t>(before.st_size)
      || !same_file(before, after) || !same_file(before, current)) {
    return fail(error, "bundle file changed while being verified: " + label);
  }
  if (sha.finish() != expected_digest) {
    return fail(error, "bundle SHA-256 mismatch for " + label
                       + "; provide the complete native bundle pinned into this installed wheel");
  }
  return true;
}

std::string basename(const std::string& path) {
  const auto position = path.rfind('/');
  return position == std::string::npos ? path : path.substr(position + 1);
}

bool relevant_library(const std::string& name) {
  return name == "libramulator.so" || name == "libramulator-vortex.so"
         || name == "libvortex.so" || name == "libsimx.so" || name == "librtlsim.so"
         || (name.compare(0, 10, "libvortex-") == 0 && name.size() >= 13
             && name.compare(name.size() - 3, 3, ".so") == 0);
}

bool canonical_loaded_path(const char* path, std::string* result) {
  if (path == nullptr || path[0] == '\0') {
    return false;
  }
  std::unique_ptr<char, decltype(&std::free)> resolved(realpath(path, nullptr), &std::free);
  if (resolved == nullptr) {
    return false;
  }
  *result = resolved.get();
  return true;
}

bool mapped_range(const dl_phdr_info& info, std::uintptr_t address, std::size_t size) {
  if (size > std::numeric_limits<std::uintptr_t>::max() - address) {
    return false;
  }
  for (ElfW(Half) i = 0; i < info.dlpi_phnum; ++i) {
    const auto& header = info.dlpi_phdr[i];
    if (header.p_type != PT_LOAD) {
      continue;
    }
    const std::uintptr_t start = info.dlpi_addr + header.p_vaddr;
    if (header.p_memsz <= std::numeric_limits<std::uintptr_t>::max() - start
        && address >= start && address + size <= start + header.p_memsz) {
      return true;
    }
  }
  return false;
}

// Also inspect SONAME so renaming a foreign project DSO does not hide a
// conflicting loader identity from the basename check.
const char* object_soname(const dl_phdr_info& info) {
  const ElfW(Dyn)* dynamic = nullptr;
  std::size_t count = 0;
  for (ElfW(Half) i = 0; i < info.dlpi_phnum; ++i) {
    const auto& header = info.dlpi_phdr[i];
    if (header.p_type == PT_DYNAMIC) {
      const std::uintptr_t address = info.dlpi_addr + header.p_vaddr;
      if (!mapped_range(info, address, header.p_memsz)) {
        return nullptr;
      }
      dynamic = reinterpret_cast<const ElfW(Dyn)*>(address);
      count = header.p_memsz / sizeof(ElfW(Dyn));
      break;
    }
  }
  std::uintptr_t strings = 0;
  std::size_t strings_size = 0;
  std::size_t name = std::numeric_limits<std::size_t>::max();
  for (std::size_t i = 0; i < count && dynamic[i].d_tag != DT_NULL; ++i) {
    if (dynamic[i].d_tag == DT_STRTAB) {
      strings = dynamic[i].d_un.d_ptr;
    } else if (dynamic[i].d_tag == DT_STRSZ) {
      strings_size = dynamic[i].d_un.d_val;
    } else if (dynamic[i].d_tag == DT_SONAME) {
      name = dynamic[i].d_un.d_val;
    }
  }
  if (strings == 0 || name >= strings_size) {
    return nullptr;
  }
  if (!mapped_range(info, strings, strings_size)) {
    if (strings > std::numeric_limits<std::uintptr_t>::max() - info.dlpi_addr) {
      return nullptr;
    }
    strings += info.dlpi_addr;
    if (!mapped_range(info, strings, strings_size)) {
      return nullptr;
    }
  }
  const auto* result = reinterpret_cast<const char*>(strings + name);
  return std::memchr(result, '\0', strings_size - name) != nullptr ? result : nullptr;
}

struct LoadedObject {
  std::string path;
  std::string soname;
};

struct LoadedObjects {
  std::vector<LoadedObject> values;
  bool failed = false;
};

int collect_loaded(dl_phdr_info* info, std::size_t, void* opaque) {
  auto* objects = static_cast<LoadedObjects*>(opaque);
  try {
    const char* soname = object_soname(*info);
    const std::string path = info->dlpi_name == nullptr ? "" : info->dlpi_name;
    if (relevant_library(basename(path)) || (soname != nullptr && relevant_library(soname))) {
      objects->values.push_back({path, soname == nullptr ? "" : soname});
    }
    return 0;
  } catch (...) {
    objects->failed = true;
    return 1;
  }
}

bool check_loaded_objects(const std::vector<std::string>& expected, bool require_all,
                          std::string* error, bool reject_existing = false) {
  LoadedObjects objects;
  dl_iterate_phdr(collect_loaded, &objects);
  if (objects.failed) {
    return fail(error, "cannot inspect loaded native library identities");
  }
  std::array<bool, 5> seen{};
  for (const auto& object : objects.values) {
    std::string actual;
    if (!canonical_loaded_path(object.path.c_str(), &actual)) {
      return fail(error, "cannot resolve an already loaded native library: " + object.path
                         + "; start a fresh process with the matched native bundle");
    }
    bool matched = false;
    for (std::size_t i = 0; i < expected.size(); ++i) {
      if (actual == expected[i]) {
        if (!object.soname.empty() && relevant_library(object.soname)
            && object.soname != basename(expected[i])) {
          return fail(error, "loaded native library has a conflicting SONAME: " + actual);
        }
        seen[i] = true;
        matched = true;
        break;
      }
    }
    if (!matched) {
      return fail(error, "foreign native library is already loaded: " + actual
                         + "; use a fresh process with only the pinned bundle's libraries");
    }
    if (reject_existing) {
      // A path may have been replaced after another caller loaded its bytes.
      // Only this loader's permanently retained objects have a known origin.
      return fail(error, "native library was already loaded outside this binding: " + actual
                         + "; start a fresh process and open the bundle through vortex_ai");
    }
  }
  if (require_all) {
    for (std::size_t i = 0; i < seen.size(); ++i) {
      if (!seen[i]) {
        return fail(error, "required native library was not observed at its verified path: "
                           + expected[i]);
      }
    }
  }
  return true;
}

bool check_environment(const std::string& library_directory,
                       const std::string& backend, std::string* error) {
  for (const char* name : {"LD_PRELOAD", "LD_AUDIT"}) {
    const char* value = std::getenv(name);
    if (value != nullptr && value[0] != '\0') {
      return fail(error, std::string(name)
                         + " conflicts with verified native loading; unset it before starting "
                           "a fresh Python process");
    }
  }
  const char* search = std::getenv("LD_LIBRARY_PATH");
  if (search != nullptr && library_directory != search) {
    return fail(error, "LD_LIBRARY_PATH must be absent or exactly " + library_directory
                       + " at process startup, with no additional or empty path segments");
  }
  const char* driver = std::getenv("VORTEX_DRIVER");
  if (driver != nullptr && backend != driver) {
    return fail(error, "VORTEX_DRIVER conflicts with this wheel's " + backend
                       + " backend; select the matched backend before starting a fresh process");
  }
  return true;
}

#define VORTEX_AI_FUNCTIONS(X) \
  X(vx_buffer_address) \
  X(vx_buffer_create) \
  X(vx_buffer_release) \
  X(vx_device_memory_info) \
  X(vx_device_open) \
  X(vx_device_query) \
  X(vx_device_release) \
  X(vx_enqueue_launch) \
  X(vx_enqueue_read) \
  X(vx_enqueue_write) \
  X(vx_event_get_profiling) \
  X(vx_event_get_value) \
  X(vx_event_release) \
  X(vx_event_wait_value) \
  X(vx_kernel_release) \
  X(vx_module_get_kernel) \
  X(vx_module_load_bytes) \
  X(vx_module_release) \
  X(vx_queue_create) \
  X(vx_queue_release)

struct ApiTable {
#define VORTEX_AI_ENTRY(name) decltype(&::name) name = nullptr;
  VORTEX_AI_FUNCTIONS(VORTEX_AI_ENTRY)
#undef VORTEX_AI_ENTRY
};

struct LoadState {
  std::mutex mutex;
  std::vector<std::string> selected_paths;
  std::vector<std::string> actual_paths;
  std::array<void*, 5> handles{};
  std::string backend;
  std::string failure;
  ApiTable api;
  bool attempted = false;
  bool ready = false;
};

std::atomic<const ApiTable*> published_api{nullptr};

LoadState& load_state() {
  // Owners and dispatcher globals may outlive interpreter/module teardown.
  // Deliberately keep the function table and all dlopen references until exit.
  static auto* state = new LoadState;
  return *state;
}

const ApiTable* current_api() noexcept {
  return getpid() == kImportProcess ? published_api.load(std::memory_order_acquire) : nullptr;
}

bool handle_path(void* handle, const std::string& expected, std::string* actual,
                 std::string* error) {
  link_map* map = nullptr;
  if (dlinfo(handle, RTLD_DI_LINKMAP, &map) != 0 || map == nullptr
      || !canonical_loaded_path(map->l_name, actual) || *actual != expected) {
    return fail(error, "dynamic loader selected a different object for " + expected
                       + "; start a fresh process with the matched native bundle");
  }
  return true;
}

template <typename Function>
bool resolve_function(void* handle, const char* name, const std::string& expected,
                      Function* result, std::string* error) {
  dlerror();
  void* symbol = dlsym(handle, name);
  const char* diagnostic = dlerror();
  if (symbol == nullptr || diagnostic != nullptr) {
    return fail(error, "native library " + expected + " is missing required symbol " + name
                       + (diagnostic == nullptr ? "" : ": " + std::string(diagnostic))
                       + "; install its matched runtime build");
  }
  Dl_info origin{};
  std::string actual;
  if (dladdr(symbol, &origin) == 0 || !canonical_loaded_path(origin.dli_fname, &actual)
      || actual != expected) {
    return fail(error, "required native symbol " + std::string(name)
                       + " resolves outside the verified library " + expected);
  }
  static_assert(sizeof(Function) == sizeof(symbol), "POSIX function pointers must fit dlsym");
  std::memcpy(result, &symbol, sizeof(symbol));
  return true;
}

}  // namespace

const char* compiled_bundle_digest() {
  return build::bundle_sha256;
}

const char* compiled_source_digest() {
  return build::source_sha256;
}

bool verify_bundle(const std::string& root, VerifiedBundle* out, std::string* error) {
  if (error != nullptr) {
    error->clear();
  }
  if (out == nullptr) {
    return fail(error, "bundle verification requires an output owner");
  }
  *out = VerifiedBundle{};
  std::array<const build::Artifact*, 6> artifacts{};
  if (!compiled_artifacts(&artifacts, error)) {
    return false;
  }
  FileDescriptor directory;
  std::string absolute;
  if (!open_root(root, &directory, &absolute, error)) {
    return false;
  }
  // Build preparation validates the receipt schema and derives the immutable
  // table from it. Matching the exact manifest bytes needs no runtime parser.
  if (!checked_file(directory.get(), "manifest.json", "manifest.json", kManifestLimit,
                    0, build::bundle_sha256, nullptr, error)) {
    return false;
  }
  FileDescriptor libraries(openat(directory.get(), "lib",
                                  O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
  if (libraries.get() < 0) {
    return fail(error, system_error("cannot open native bundle lib directory (no symlinks)", errno));
  }
  if (!check_library_directory(libraries.get(), error)) {
    return false;
  }
  VerifiedBundle verified;
  verified.libraries.reserve(5);
  for (std::size_t i = 0; i < artifacts.size(); ++i) {
    const auto& artifact = *artifacts[i];
    const bool module = i == 5;
    const char* leaf = module ? artifact.path : artifact.path + 4;
    if (!checked_file(module ? directory.get() : libraries.get(), leaf, artifact.path,
                      module ? kModuleLimit : kLibraryLimit, artifact.size, artifact.sha256,
                      module ? &verified.module_bytes : nullptr, error)) {
      return false;
    }
    if (!module) {
      verified.libraries.push_back(child_path(absolute, artifact.path));
    }
  }
  if (!check_library_directory(libraries.get(), error)) {
    return false;
  }
  verified.format = build::format;
  verified.backend = build::backend;
  verified.qualification_id = build::qualification_id;
  verified.source_revision = build::source_revision;
  verified.bundle_sha256 = build::bundle_sha256;
  verified.source_sha256 = build::source_sha256;
  *out = std::move(verified);
  return true;
}

bool load_runtime(const std::vector<std::string>& paths,
                  const std::string& backend, std::string* error) {
  if (error != nullptr) {
    error->clear();
  }
  if (getpid() != kImportProcess) {
    return fail(error, "native runtime use after fork is unsupported; start a fresh Python process");
  }
  if (paths.size() != 5 || backend != build::backend || backend != "simx") {
    return fail(error, "native loading requires the five verified libraries and the compiled SimX backend");
  }
  const std::string suffix = "/lib/libramulator.so";
  if (!safe_path_text(paths[0]) || paths[0].front() != '/'
      || paths[0].size() < suffix.size()
      || paths[0].compare(paths[0].size() - suffix.size(), suffix.size(), suffix) != 0) {
    return fail(error, "native library paths must be absolute paths from a verified bundle");
  }
  auto root = paths[0].substr(0, paths[0].size() - suffix.size());
  if (root.empty()) {
    root = "/";
  }
  VerifiedBundle checked;
  // Recheck immediately before dlopen, including when reusing a loaded bundle.
  // The supported integrity model does not include hostile concurrent writers.
  if (!verify_bundle(root, &checked, error)) {
    return false;
  }
  if (checked.libraries != paths || checked.backend != backend) {
    return fail(error, "native library paths do not match the compiled bundle's exact artifact roles");
  }
  const auto library_directory = child_path(root, "lib");
  if (!check_environment(library_directory, backend, error)) {
    return false;
  }
  auto& state = load_state();
  std::lock_guard<std::mutex> guard(state.mutex);
  if (state.attempted) {
    if (state.selected_paths != paths || state.backend != backend) {
      return fail(error, "one native bundle variant and path is permanent per process; "
                         "start a fresh process to select another bundle");
    }
    if (!state.ready) {
      return fail(error, state.failure + "; an earlier native load attempt fixed this process's "
                                        "library state; start a fresh process after correcting it");
    }
    return check_loaded_objects(paths, true, error);
  }
  if (!check_loaded_objects(paths, false, error, true)) {
    return false;
  }
  state.selected_paths = paths;
  state.backend = backend;
  state.actual_paths.reserve(paths.size());
  state.failure = "native library loading did not complete";
  state.attempted = true;
  // Ramulator must precede its registration extension; the runtime exports
  // common/VM symbols required by the backend. All are global and eager.
  for (std::size_t i = 0; i < paths.size(); ++i) {
    dlerror();
    state.handles[i] = dlopen(paths[i].c_str(), RTLD_NOW | RTLD_GLOBAL);
    if (state.handles[i] == nullptr) {
      const char* diagnostic = dlerror();
      state.failure = "cannot load verified native library " + paths[i] + ": "
                      + (diagnostic == nullptr ? "unknown dynamic loader error" : diagnostic)
                      + "; install its system dependencies and launch a fresh Python process "
                        "with LD_LIBRARY_PATH=" + library_directory;
      return fail(error, state.failure);
    }
    std::string actual;
    if (!handle_path(state.handles[i], paths[i], &actual, &state.failure)
        || !check_loaded_objects(paths, false, &state.failure)) {
      return fail(error, state.failure);
    }
    state.actual_paths.push_back(std::move(actual));
  }
  ApiTable api;
#define VORTEX_AI_RESOLVE(name) \
  if (!resolve_function(state.handles[2], #name, paths[2], &api.name, &state.failure)) { \
    return fail(error, state.failure); \
  }
  VORTEX_AI_FUNCTIONS(VORTEX_AI_RESOLVE)
#undef VORTEX_AI_RESOLVE
  void (*backend_entry)() = nullptr;
  if (!resolve_function(state.handles[4], "vx_dev_init", paths[4], &backend_entry, &state.failure)
      || !check_loaded_objects(paths, true, &state.failure)) {
    return fail(error, state.failure);
  }
  VerifiedBundle after_load;
  if (!verify_bundle(root, &after_load, &state.failure)) {
    return fail(error, state.failure);
  }
  if (after_load.libraries != state.actual_paths) {
    state.failure = "native library paths changed while the verified bundle was loading";
    return fail(error, state.failure);
  }
  state.api = api;
  state.ready = true;
  state.failure.clear();
  published_api.store(&state.api, std::memory_order_release);
  return true;
}

std::vector<std::string> loaded_runtime_paths() {
  if (getpid() != kImportProcess) {
    return {};
  }
  auto& state = load_state();
  std::lock_guard<std::mutex> guard(state.mutex);
  return state.actual_paths;
}

}  // namespace vortex_ai_python

// Explicit visibility keeps the forwarding functions out of the extension's
// dynamic export table even in a host test build without -fvisibility=hidden.
#define VORTEX_AI_FORWARD(name, parameters, arguments) \
  extern "C" __attribute__((visibility("hidden"))) vx_result_t name parameters { \
    const auto* api = vortex_ai_python::current_api(); \
    return api == nullptr ? VX_ERR_NOT_SUPPORTED : api->name arguments; \
  }

extern "C" __attribute__((visibility("hidden"))) vx_result_t
vx_device_open(std::uint32_t index, vx_device_h* out) {
  const auto* api = vortex_ai_python::current_api();
  if (api == nullptr) {
    return VX_ERR_NOT_SUPPORTED;
  }
  const char* driver = std::getenv("VORTEX_DRIVER");
  if (driver != nullptr && std::strcmp(driver, vortex_ai_python::build::backend) != 0) {
    return VX_ERR_INVALID_VALUE;
  }
  return api->vx_device_open(index, out);
}

VORTEX_AI_FORWARD(vx_device_query,
    (vx_device_h dev, std::uint32_t caps_id, std::uint64_t* out_value), (dev, caps_id, out_value))
VORTEX_AI_FORWARD(vx_device_release, (vx_device_h dev), (dev))
VORTEX_AI_FORWARD(vx_device_memory_info,
    (vx_device_h dev, std::uint64_t* free_bytes, std::uint64_t* used_bytes),
    (dev, free_bytes, used_bytes))
VORTEX_AI_FORWARD(vx_buffer_create,
    (vx_device_h dev, std::uint64_t size, std::uint32_t flags, vx_buffer_h* out),
    (dev, size, flags, out))
VORTEX_AI_FORWARD(vx_buffer_address, (vx_buffer_h buf, std::uint64_t* out_addr), (buf, out_addr))
VORTEX_AI_FORWARD(vx_buffer_release, (vx_buffer_h buf), (buf))
VORTEX_AI_FORWARD(vx_module_load_bytes,
    (vx_device_h dev, const void* bytes, std::size_t size, vx_module_h* out),
    (dev, bytes, size, out))
VORTEX_AI_FORWARD(vx_module_get_kernel,
    (vx_module_h mod, const char* name, vx_kernel_h* out), (mod, name, out))
VORTEX_AI_FORWARD(vx_module_release, (vx_module_h mod), (mod))
VORTEX_AI_FORWARD(vx_kernel_release, (vx_kernel_h kernel), (kernel))
VORTEX_AI_FORWARD(vx_queue_create,
    (vx_device_h dev, const vx_queue_info_t* info, vx_queue_h* out), (dev, info, out))
VORTEX_AI_FORWARD(vx_queue_release, (vx_queue_h queue), (queue))
VORTEX_AI_FORWARD(vx_enqueue_launch,
    (vx_queue_h queue, const vx_launch_info_t* info, std::uint32_t count,
     const vx_event_h* waits, vx_event_h* out), (queue, info, count, waits, out))
VORTEX_AI_FORWARD(vx_enqueue_read,
    (vx_queue_h queue, void* destination, vx_buffer_h source, std::uint64_t offset,
     std::uint64_t size, std::uint32_t count, const vx_event_h* waits, vx_event_h* out),
    (queue, destination, source, offset, size, count, waits, out))
VORTEX_AI_FORWARD(vx_enqueue_write,
    (vx_queue_h queue, vx_buffer_h destination, std::uint64_t offset, const void* source,
     std::uint64_t size, std::uint32_t count, const vx_event_h* waits, vx_event_h* out),
    (queue, destination, offset, source, size, count, waits, out))
VORTEX_AI_FORWARD(vx_event_get_profiling,
    (vx_event_h event, vx_profile_info_t* out), (event, out))
VORTEX_AI_FORWARD(vx_event_get_value,
    (vx_event_h event, std::uint64_t* out), (event, out))
VORTEX_AI_FORWARD(vx_event_wait_value,
    (vx_event_h event, std::uint64_t value, std::uint64_t timeout_ns), (event, value, timeout_ns))
VORTEX_AI_FORWARD(vx_event_release, (vx_event_h event), (event))

#undef VORTEX_AI_FORWARD
#undef VORTEX_AI_FUNCTIONS
