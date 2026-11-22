# SPDX-License-Identifier: Apache-2.0
"""Actual timing/functional SimObject teardown checks, without native GPU execution."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/simulator_platform_cleanup.cpp"
KERNEL_HEADERS = ("simobject.h", "simobject_functional.h")
SHARED_HEADERS = (
    "bitmanip.h", "linked_list.h", "mempool.h", "ringqueue.h", "smallfunc.h", "util.h",
)


class SimulatorPlatformCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Simulator platform checks require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-simulator-platform-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        source_files = (
            FIXTURE, Path(__file__).resolve(), ROOT / "ci/project/tensor_host_tools.py",
            ROOT / "ci/project/baseline_process.py",
            *(ROOT / "sim/common" / name for name in KERNEL_HEADERS),
            *(ROOT / "sw/common" / name for name in SHARED_HEADERS),
        )
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
        cls.binaries = {}
        for kernel in ("timing", "functional"):
            binary = cls.build / ("simulator-platform-" + kernel)
            run_host_command([
                compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
                *(["-DSIMX_FUNCTIONAL"] if kernel == "functional" else []),
                "-I", str(ROOT / "sim/common"), "-I", str(ROOT / "sw/common"),
                str(FIXTURE), "-o", str(binary),
            ], cwd=cls.build, env=cls.environment, timeout=60)
            cls.binaries[kernel] = binary

    def assert_sources_stable(self):
        for path, digest in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                             "Simulator platform or fixture source changed: " + str(path))

    def group(self, name):
        for kernel, binary in self.binaries.items():
            with self.subTest(kernel=kernel):
                self.assert_sources_stable()
                output = run_host_command([str(binary), name], cwd=self.build,
                                          env=self.environment, timeout=15)
                self.assertRegex(output, r"\APASS simulator-platform-cleanup " + re.escape(name)
                                 + r" checks=[1-9][0-9]*\n\Z")
                self.assert_sources_stable()

    def test_queued_model_exception_teardown_allows_fresh_context_idle(self):
        self.group("queued_exception")

    def test_scheduled_undelivered_reservation_is_retired_on_full_teardown(self):
        self.group("scheduled_reservation")

    def test_late_owner_destruction_preserves_fresh_context_accounting(self):
        self.group("late_owner")

    def test_normal_completion_launch_keep_and_repeated_clean_finalize(self):
        self.group("normal")


if __name__ == "__main__":
    unittest.main()
