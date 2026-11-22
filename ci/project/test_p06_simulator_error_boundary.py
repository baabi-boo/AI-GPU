# SPDX-License-Identifier: Apache-2.0
"""Real lifecycle/CP recovery versus terminal controlled-model failures."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command
from test_p06_simulator_public import COMMON_SOURCES, MEMORY_SHIM


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/simulator_error_boundary.cpp"
CONTROL = FIXTURE.with_name("simulator_error_boundary_control.h")
PROCESSOR = FIXTURE.with_name("simulator_error_boundary_processor.h")
LIFECYCLE = ROOT / "tests/runtime/test_ai_lifecycle.cpp"


class SimulatorErrorBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Simulator error boundaries require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-simulator-errors-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1", "LD_LIBRARY_PATH": str(cls.build),
            "VORTEX_CP_POLL_TIMEOUT_S": "2",
        }
        sources = [
            FIXTURE, CONTROL, PROCESSOR, LIFECYCLE, Path(__file__).resolve(),
            ROOT / "ci/project/test_p06_simulator_public.py", ROOT / "configure",
            ROOT / "VX_config.toml", ROOT / "VX_types.toml", ROOT / "profiles/p02-tfr.json",
            ROOT / "ci/gen_config.py", ROOT / "ci/project/tensor_host_tools.py",
            ROOT / "ci/project/baseline_process.py", ROOT / "sw/runtime/stub/vortex.cpp",
            *(ROOT / "sw/runtime/common" / name for name in COMMON_SOURCES),
            *(ROOT / "sw/runtime" / backend / "vortex.cpp" for backend in ("simx", "rtlsim")),
            *(ROOT / "sw/runtime/common").glob("*.h"), ROOT / "sw/runtime/common/callbacks.inc",
            *(ROOT / "sw/runtime/include").glob("*.h"), *(ROOT / "sw/common").glob("*.h"),
            ROOT / "sim/common/cmd_processor.cpp", ROOT / "sim/common/cmd_processor.h",
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        run_host_command(["bash", str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                          "--osversion=ubuntu/focal", "--tooldir=" + str(cls.build / "unused-tools")],
                         cwd=cls.build, env=cls.environment, timeout=120)
        shims = cls.build / "controlled-model"
        shims.mkdir()
        (shims / "mem.h").write_text(MEMORY_SHIM, encoding="utf-8")
        (shims / "processor.h").write_bytes(PROCESSOR.read_bytes())
        (shims / CONTROL.name).write_bytes(CONTROL.read_bytes())
        config_flags = shlex.split(run_host_command([
            "python3", str(ROOT / "ci/gen_config.py"),
            "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr",
            "--cflags=-DVX_CFG_XLEN=64",
        ], cwd=cls.build, env=cls.environment, timeout=30))
        flags = [compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                 "-DNDEBUG", *config_flags, "-fsanitize=undefined",
                 "-fno-sanitize-recover=undefined", "-pthread"]
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
                "-DERROR_BOUNDARY_BACKEND", *(["-DCOMPLETION_SIMX"] if backend == "simx" else []),
                "-fPIC", "-shared", str(ROOT / "sw/runtime" / backend / "vortex.cpp"),
                str(ROOT / "sim/common/cmd_processor.cpp"), str(FIXTURE),
                "-o", str(cls.build / ("libvortex-" + backend + ".so")),
            ], cwd=cls.build, env=cls.environment, timeout=60)
        cls.lifecycle = cls.build / "simulator-inherited-lifecycle"
        cls.binary = cls.build / "simulator-error-boundary"
        for source, output in ((LIFECYCLE, cls.lifecycle), (FIXTURE, cls.binary)):
            run_host_command([*flags, *includes, str(source), "-L", str(cls.build),
                              "-lvortex", "-ldl", "-o", str(output)],
                             cwd=cls.build, env=cls.environment, timeout=60)

    def stable(self):
        for path, digest in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                             "Error-boundary source changed: " + str(path))

    def test_inherited_lifecycle_preserves_allocation_errors_and_same_device_recovery(self):
        for backend in ("simx", "rtlsim"):
            for memory in ("ram", "llc"):
                with self.subTest(backend=backend, memory=memory):
                    self.stable()
                    output = run_host_command([str(self.lifecycle)], cwd=self.build,
                        env={**self.environment, "VORTEX_DRIVER": backend,
                             "SIMULATOR_ERROR_MEMORY": memory}, timeout=30)
                    for stage in range(3):
                        self.assertIn("[OK] real DMA allocation stage " + str(stage)
                                      + " OOM propagates, releases captures, and recovers\n", output)
                    self.assertTrue(output.endswith("P03_LIFECYCLE PASSED\n"))
                    self.stable()

    def faults(self, hooks, backends=("simx", "rtlsim"), memories=("ram", "llc")):
        for hook in hooks:
            for outcome in (0, 1):
                for backend in backends:
                    for memory in memories:
                        with self.subTest(hook=hook, outcome=outcome, backend=backend, memory=memory):
                            self.stable()
                            output = run_host_command([str(self.binary), str(hook), str(outcome)],
                                cwd=self.build, env={**self.environment, "VORTEX_DRIVER": backend,
                                                     "SIMULATOR_ERROR_MEMORY": memory}, timeout=15)
                            self.assertRegex(output, r"\APASS simulator-error-boundary hook="
                                + re.escape(str(hook)) + " outcome=" + re.escape(str(outcome))
                                + r" checks=[1-9][0-9]*\n\Z")
                            self.stable()

    def test_async_model_bad_alloc_and_unknown_remain_terminal(self):
        self.faults((1,))

    def test_synchronous_dcr_bad_alloc_and_unknown_remain_terminal(self):
        self.faults((2, 3))

    def test_synchronous_llc_bad_alloc_and_unknown_remain_terminal(self):
        self.faults((4, 5), memories=("llc",))

    def test_synchronous_rtlsim_drain_bad_alloc_and_unknown_remain_terminal(self):
        self.faults((6,), backends=("rtlsim",), memories=("ram",))


if __name__ == "__main__":
    unittest.main()
