# SPDX-License-Identifier: Apache-2.0
"""Deterministic host completion-owner checks, without native processor execution."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/simulator_async_run_test.cpp"
HELPER = ROOT / "sw/runtime/common/async_run.h"


class SimulatorAsyncRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Simulator completion checks require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-async-run-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "simulator-async-run"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        cls.identities = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (FIXTURE, HELPER, Path(__file__).resolve(),
                         ROOT / "ci/project/tensor_host_tools.py",
                         ROOT / "ci/project/baseline_process.py")
        }
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
            "-I", str(HELPER.parent), str(FIXTURE), "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=60)

    def assert_sources_stable(self):
        for path, digest in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                             "Compiled helper or test source changed: " + str(path))

    def group(self, name):
        self.assert_sources_stable()
        output = run_host_command([str(self.binary), name], cwd=self.build,
                                  env=self.environment, timeout=15)
        self.assertRegex(output, r"\APASS simulator-async-run " + re.escape(name)
                         + r" checks=[1-9][0-9]*\n\Z")
        self.assert_sources_stable()

    def test_completed_before_first_poll_has_one_edge_across_serial_tasks(self):
        self.group("immediate_wait")

    def test_bounded_wait_and_nonblocking_checks_preserve_unobserved_edge(self):
        self.group("immediate_bounded")

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "Ready check requires the Linux procfs worker-exit witness")
    def test_ready_check_consumes_completion_before_first_busy_observation(self):
        self.group("immediate_check")

    def test_pending_observations_cannot_end_a_held_task_or_repeat_its_edge(self):
        self.group("pending")

    def test_standard_and_unknown_exceptions_are_consumed_and_sticky(self):
        self.group("exceptions")

    def test_overlapping_pending_start_rejects_without_abandoning_original_work(self):
        self.group("overlap_pending")

    def test_completed_unobserved_launch_cannot_be_overwritten(self):
        self.group("overlap_edge")

    def test_failed_owner_destruction_joins_pending_exception_without_throwing(self):
        self.group("failed_cleanup")


if __name__ == "__main__":
    unittest.main()
