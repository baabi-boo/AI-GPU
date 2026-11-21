# SPDX-License-Identifier: Apache-2.0
"""Real managed wrapper edge tests against a synthetic deferred C API.

This checks allocation rollback, the context reservation, and polling ownership.
It does not qualify GPU arithmetic, general native concurrency, or global OOM.
"""

import hashlib
import itertools
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "sw/runtime/ai"
HARNESS = ROOT / "ci/project/fixtures/p06_workspace_edge_test.cpp"
SHARED_HARNESS = ROOT / "ci/project/fixtures/p03_managed_runtime_test.cpp"
POLICIES = ("per_operation", "reusable_single_tile")
DTYPES = ("fp16", "bf16")


class WorkspaceEdgeHostTests(unittest.TestCase):
    observations = []

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Workspace edge tests require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-workspace-edges-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "workspace-edge-test"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        inputs = [
            HARNESS, SHARED_HARNESS, Path(__file__).resolve(),
            *(RUNTIME / name for name in ("runtime.h", "runtime.cpp", "contract.h", "contract.cpp")),
            ROOT / "sw/runtime/include/vortex2.h", ROOT / "sw/common/ai_matmul_args.h",
            ROOT / "ci/project/tensor_host_tools.py", ROOT / "ci/project/baseline_process.py",
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
            "-I", str(RUNTIME), "-I", str(ROOT / "sw/runtime/include"),
            "-I", str(ROOT / "sw/common"), str(HARNESS), str(RUNTIME / "runtime.cpp"),
            str(RUNTIME / "contract.cpp"), "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=45)
        cls.observations = []

    def group(self, name, expected_scenarios):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            with self.subTest(policy=policy, dtype=dtype):
                for path, expected in self.identities.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                                     "Input changed before workspace edge case: " + str(path))
                output = run_host_command([str(self.binary), name, policy, dtype],
                                          cwd=self.build, env=self.environment, timeout=10)
                match = re.fullmatch(r"PASS " + re.escape(name)
                                     + r" checks=([1-9][0-9]*) scenarios=([1-9][0-9]*)\n", output)
                self.assertIsNotNone(match, output)
                self.assertEqual(int(match[2]), expected_scenarios)
                self.observations.append(dict(group=name, policy=policy, dtype=dtype,
                                              checks=int(match[1]), scenarios=int(match[2])))
                for path, expected in self.identities.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                                     "Input changed during workspace edge case: " + str(path))
                self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*")
                                    if path.is_file()), 64 * 1024 * 1024)

    def test_simultaneous_context_create_has_exactly_one_native_open_until_both_return(self):
        self.group("create_race", 32)

    def test_each_context_allocation_failure_returns_reservation_and_frees_owned_memory(self):
        self.group("create_bad_alloc", 4)

    def test_each_context_other_exception_preserves_internal_error_and_clean_retry(self):
        self.group("create_other_exception", 4)

    def test_each_operation_allocation_failure_returns_lease_before_native_queue_creation(self):
        self.group("submit_bad_alloc", 7)

    def test_each_operation_other_exception_releases_staging_and_allows_healthy_retry(self):
        self.group("submit_other_exception", 7)

    def test_context_allocation_error_and_rollback_cleanup_error_remain_distinct_and_poison(self):
        self.group("create_cleanup_bad_alloc", 1)

    def test_context_other_exception_and_rollback_cleanup_error_poison_without_reopening(self):
        self.group("create_cleanup_other_exception", 1)

    def test_each_prefix_event_timeout_retains_resources_and_can_complete_on_retry(self):
        self.group("prefix_timeouts", 5)

    def test_completion_query_timeouts_are_retryable_without_erasing_an_earlier_wait_error(self):
        self.group("query_timeouts", 2)

    def test_completion_query_error_survives_later_prefix_timeout_and_successful_drain(self):
        self.group("query_error_prefix_timeout", 1)

    def test_each_partial_dispatch_prefix_poll_timeout_preserves_original_submit_failure(self):
        self.group("partial_prefix_timeouts", 10)

    def test_each_profiling_error_after_timeout_is_separate_from_successful_completion(self):
        self.group("profiling_after_retry", 5)
