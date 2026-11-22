# SPDX-License-Identifier: Apache-2.0
"""Production host-backend/CP tests with injected processors, not native GPU runs."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "ci/project/fixtures/simulator_completion"


def compile_backend(compiler, backend, build, environment, backend_source=None):
    binary = build / (backend + "-completion")
    source = backend_source or ROOT / "sw/runtime" / backend / "vortex.cpp"
    run_host_command([
        compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
        "-DNDEBUG", "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
        "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
        *(["-DCOMPLETION_SIMX"] if backend == "simx" else []),
        "-I", str(FIXTURES), "-I", str(build / "sw"),
        "-I", str(ROOT / "sw/runtime/common"), "-I", str(ROOT / "sw/runtime/include"),
        "-I", str(ROOT / "sw/common"), "-I", str(ROOT / "sim/simx"),
        "-I", str(ROOT / "sim/common"), str(source),
        str(ROOT / "sim/common/cmd_processor.cpp"), str(FIXTURES / "main.cpp"),
        "-Wl,--wrap=free", "-o", str(binary),
    ], cwd=build, env=environment, timeout=60)
    return binary


class SimulatorCompletionHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Simulator completion tests require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-simulator-completion-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        inputs = [
            *sorted(FIXTURES.glob("*")), Path(__file__).resolve(),
            *(ROOT / "sw/runtime" / backend / "vortex.cpp" for backend in ("simx", "rtlsim")),
            *(ROOT / "sw/runtime/common" / name for name in ("async_run.h", "callbacks.h", "callbacks.inc", "common.h")),
            *(ROOT / "sim/common" / name for name in ("cmd_processor.cpp", "cmd_processor.h")),
            ROOT / "configure", ROOT / "VX_config.toml", ROOT / "VX_types.toml",
            ROOT / "profiles/p02-tfr.json", ROOT / "ci/gen_config.py",
            ROOT / "ci/project/tensor_host_tools.py", ROOT / "ci/project/baseline_process.py",
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        run_host_command(["bash", str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                          "--osversion=ubuntu/focal",
                          "--tooldir=" + str(cls.build / "unused-tools")],
                         cwd=cls.build, env=cls.environment, timeout=120)
        cls.binaries = {backend: compile_backend(compiler, backend, cls.build, cls.environment)
                        for backend in ("simx", "rtlsim")}

    def group(self, group):
        for backend, binary in self.binaries.items():
            for memory in ("ram", "llc"):
                with self.subTest(backend=backend, memory=memory):
                    for path, digest in self.identities.items():
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                                         "Compiled fixture source changed: " + str(path))
                    output = run_host_command([str(binary), group, memory], cwd=self.build,
                                              env=self.environment, timeout=10)
                    self.assertRegex(output, r"\APASS simulator-completion " + re.escape(group)
                                     + r" checks=[1-9][0-9]*\n\Z")
                    for path, digest in self.identities.items():
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                                         "Source changed during fixture: " + str(path))

    def test_pending_and_serial_success_preserve_nonzero_legacy_gp_and_dcr(self):
        self.group("success")

    def test_standard_exceptions_fail_before_retirement_and_stay_terminal(self):
        self.group("standard_exception")

    def test_unknown_exceptions_fail_before_retirement_and_stay_terminal(self):
        self.group("unknown_exception")

    def test_post_completion_ram_llc_dma_and_rtl_drain_remain_usable(self):
        self.group("transfers")

    def test_pending_success_is_joined_before_host_memory_and_processor_destruction(self):
        self.group("destroy_success")

    def test_pending_exception_cannot_escape_destructor_or_release_memory_early(self):
        self.group("destroy_exception")


if __name__ == "__main__":
    unittest.main()
