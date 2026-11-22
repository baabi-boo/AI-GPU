# SPDX-License-Identifier: Apache-2.0
"""Actual public runtime and backend integration with controlled processor faults."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/simulator_public_completion.cpp"
CONTROL = ROOT / "ci/project/fixtures/simulator_completion/control.h"
COMMON_SOURCES = (
    "graphics.cpp", "result.cpp", "device.cpp", "buffer.cpp", "queue.cpp", "event.cpp",
    "module.cpp", "runtime_helpers.cpp", "perf.cpp", "legacy_runtime.cpp",
    "legacy_utils.cpp", "utils.cpp", "vm.cpp",
)

MEMORY_SHIM = r'''#pragma once
#include <cstdint>
#include <limits>
#include <map>
#include <stdexcept>
namespace vortex {
class RAM {
public:
  RAM(uint64_t, uint64_t) {}
  void enable_acl(bool) {}
  void read(uint8_t* destination, uint64_t address, uint64_t bytes) {
    bounds(address, bytes);
    for (uint64_t i = 0; i < bytes; ++i) {
      auto found = bytes_.find(address + i);
      destination[i] = found == bytes_.end() ? 0 : found->second;
    }
  }
  void write(const uint8_t* source, uint64_t address, uint64_t bytes) {
    bounds(address, bytes);
    for (uint64_t i = 0; i < bytes; ++i) {
      bytes_[address + i] = source[i];
    }
  }
private:
  void bounds(uint64_t address, uint64_t bytes) const {
    if (bytes > 65536 || address > std::numeric_limits<uint64_t>::max() - bytes) {
      throw std::out_of_range("public fixture memory request");
    }
  }
  std::map<uint64_t, uint8_t> bytes_;
};
}
'''

PROCESSOR_SHIM = r'''#pragma once
#include "control.h"
#include "mem.h"
namespace vortex {
class Processor {
public:
  void attach_ram(RAM* ram) { ram_ = ram; }
  ~Processor() {
    auto& state = completion_test::control;
    if (state.active.load() != 0) {
      state.destroyed_active.fetch_add(1);
    }
    state.destroyed.fetch_add(1);
  }
#ifdef COMPLETION_SIMX
  int run() {
    auto& state = completion_test::control;
    state.legacy_calls.fetch_add(1);
    try {
      state.execute();
      return state.legacy_gp;
    } catch (...) {
      return -1;
    }
  }
  void run_checked() {
    completion_test::control.checked_calls.fetch_add(1);
    completion_test::control.execute();
  }
#else
  void run() { completion_test::control.execute(); }
#endif
  bool cp_llc_client() const { return completion_test::control.llc; }
  uint64_t cp_llc_size() const { return 4096; }
  void cp_mem_read(uint64_t address, void* destination, uint64_t bytes) {
    completion_test::control.memory_reads.fetch_add(1);
    ram_->read(static_cast<uint8_t*>(destination), address, bytes);
  }
  void cp_mem_write(uint64_t address, const void* source, uint64_t bytes, bool) {
    completion_test::control.memory_writes.fetch_add(1);
    ram_->write(static_cast<const uint8_t*>(source), address, bytes);
  }
  int dcr_write(uint32_t, uint32_t) {
    completion_test::control.dcr_writes.fetch_add(1);
    return 0;
  }
  int dcr_read(uint32_t, uint32_t, uint32_t* value) {
    completion_test::control.dcr_reads.fetch_add(1);
    *value = 0;
    return 0;
  }
  void drain() { completion_test::control.drains.fetch_add(1); }
private:
  RAM* ram_ = nullptr;
};
}
'''


class SimulatorPublicCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Public completion integration requires C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-simulator-public-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1", "LD_LIBRARY_PATH": str(cls.build),
            "VORTEX_CP_POLL_TIMEOUT_S": "2",
        }
        source_files = [
            FIXTURE, CONTROL, Path(__file__).resolve(), ROOT / "configure",
            ROOT / "VX_config.toml", ROOT / "VX_types.toml", ROOT / "profiles/p02-tfr.json",
            ROOT / "ci/gen_config.py", ROOT / "ci/project/tensor_host_tools.py",
            ROOT / "ci/project/baseline_process.py", ROOT / "sw/runtime/stub/vortex.cpp",
            *(ROOT / "sw/runtime/common" / name for name in COMMON_SOURCES),
            *(ROOT / "sw/runtime" / backend / "vortex.cpp" for backend in ("simx", "rtlsim")),
            *(ROOT / "sw/runtime/common").glob("*.h"), ROOT / "sw/runtime/common/callbacks.inc",
            *(ROOT / "sw/runtime/include").glob("*.h"), *(ROOT / "sw/common").glob("*.h"),
            ROOT / "sim/common/cmd_processor.cpp", ROOT / "sim/common/cmd_processor.h",
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
        run_host_command(["bash", str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                          "--osversion=ubuntu/focal", "--tooldir=" + str(cls.build / "unused-tools")],
                         cwd=cls.build, env=cls.environment, timeout=120)
        shims = cls.build / "controlled-model"
        shims.mkdir()
        (shims / "mem.h").write_text(MEMORY_SHIM, encoding="utf-8")
        (shims / "processor.h").write_text(PROCESSOR_SHIM, encoding="utf-8")
        (shims / "control.h").write_bytes(CONTROL.read_bytes())
        # Match runtime/common.mk: resolve the complete hardware configuration
        # to compiler definitions, rather than supplying a partial hand list.
        config_flags = shlex.split(run_host_command([
            "python3", str(ROOT / "ci/gen_config.py"),
            "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr",
            "--cflags=-DVX_CFG_XLEN=64",
        ], cwd=cls.build, env=cls.environment, timeout=30))
        flags = [compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                 "-DNDEBUG", *config_flags,
                 "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread"]
        includes = ["-I", str(cls.build / "sw"), "-I", str(ROOT / "sw/runtime/common"),
                    "-I", str(ROOT / "sw/runtime/include"), "-I", str(ROOT / "sw/common"),
                    "-I", str(ROOT / "sw/kernel/include")]
        runtime_sources = [ROOT / "sw/runtime/stub/vortex.cpp",
                           *(ROOT / "sw/runtime/common" / name for name in COMMON_SOURCES)]
        run_host_command([*flags, *includes, "-fPIC", "-shared", *map(str, runtime_sources),
                          "-ldl", "-Wl,-soname,libvortex.so", "-o", str(cls.build / "libvortex.so")],
                         cwd=cls.build, env=cls.environment, timeout=180)
        for backend in ("simx", "rtlsim"):
            run_host_command([
                *flags, "-I", str(shims), *includes,
                "-I", str(ROOT / "sim/simx"), "-I", str(ROOT / "sim/common"),
                "-DPUBLIC_COMPLETION_BACKEND", *(["-DCOMPLETION_SIMX"] if backend == "simx" else []),
                "-fPIC", "-shared", str(ROOT / "sw/runtime" / backend / "vortex.cpp"),
                str(ROOT / "sim/common/cmd_processor.cpp"), str(FIXTURE),
                "-o", str(cls.build / ("libvortex-" + backend + ".so")),
            ], cwd=cls.build, env=cls.environment, timeout=60)
        cls.binary = cls.build / "simulator-public-completion"
        run_host_command([*flags, *includes, str(FIXTURE), "-L", str(cls.build),
                          "-lvortex", "-ldl", "-o", str(cls.binary)],
                         cwd=cls.build, env=cls.environment, timeout=60)

    def group(self, group):
        for backend in ("simx", "rtlsim"):
            for memory in ("ram", "llc"):
                with self.subTest(backend=backend, memory=memory):
                    for path, digest in self.identities.items():
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                                         "Public integration source changed: " + str(path))
                    output = run_host_command([str(self.binary), group, memory], cwd=self.build,
                        env={**self.environment, "VORTEX_DRIVER": backend}, timeout=15)
                    self.assertRegex(output, r"\APASS simulator-public-completion "
                                     + re.escape(group) + r" checks=[1-9][0-9]*\n\Z")
                    for path, digest in self.identities.items():
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                                         "Public integration source changed during execution: " + str(path))

    def test_public_success_waits_and_cleanup_preserve_nonzero_legacy_gp(self):
        self.group("success")

    def test_standard_exception_survives_event_waits_queue_finish_and_new_queue(self):
        self.group("standard_exception")

    def test_unknown_exception_survives_event_waits_queue_finish_and_new_queue(self):
        self.group("unknown_exception")


if __name__ == "__main__":
    unittest.main()
