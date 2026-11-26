# SPDX-License-Identifier: Apache-2.0
"""Serial workspace host ownership tests; synthetic output is not GPU arithmetic."""

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
HARNESS = ROOT / "ci/project/fixtures/p06_workspace_runtime_test.cpp"
SHARED_HARNESS = ROOT / "ci/project/fixtures/p03_managed_runtime_test.cpp"
POLICIES = ("per_operation", "reusable_single_tile")
DTYPES = ("fp16", "bf16")


class WorkspaceRuntimeHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Workspace runtime tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-workspace-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "workspace-test"
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

    def group(self, name, policy, dtype, *arguments):
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed before workspace runtime case: " + str(path))
        output = run_host_command(
            [str(self.binary), name, policy, dtype, *(str(value) for value in arguments)],
            cwd=self.build, env=self.environment, timeout=10,
        )
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during workspace runtime case: " + str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024)

    def matrix_group(self, name):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            with self.subTest(policy=policy, dtype=dtype):
                self.group(name, policy, dtype)

    def test_competing_contexts_reject_before_native_open_and_clean_close_returns_lease(self):
        self.matrix_group("context_lease")

    def test_queued_and_successfully_waited_operations_exclude_resubmission_until_close(self):
        self.matrix_group("operation_lease")

    def test_timeout_preserves_resources_then_successful_drain_permits_serial_reuse(self):
        self.matrix_group("timeout_retention")

    def test_queued_and_waited_operations_retain_context_after_owner_destruction(self):
        self.matrix_group("owner_destruction")

    def test_32_changed_input_calls_rewrite_poison_and_bound_allocations_and_saved_output(self):
        self.matrix_group("serial_reuse")

    def test_default_six_signatures_remain_supported_and_fixed_workspace_rejects_other_shapes(self):
        self.matrix_group("policy_validation")

    def test_every_capability_query_and_resident_setup_failure_rolls_back_before_retry(self):
        self.matrix_group("setup_rollback")

    def test_workspace_and_per_operation_addresses_are_validated_before_enqueue(self):
        self.matrix_group("address_validation")

    def test_each_post_create_resident_address_failure_returns_lease_and_preserves_buffers(self):
        for dtype in DTYPES:
            with self.subTest(dtype=dtype):
                self.group("resident_address_rollback", "reusable_single_tile", dtype)

    def test_every_partial_submission_preserves_primary_and_lease_until_drain(self):
        self.matrix_group("partial_rollback")

    def test_wait_and_completion_query_errors_remain_primary_after_eventual_drain(self):
        self.matrix_group("completion_observation")

    def test_each_operation_release_error_is_sticky_and_suppresses_completed_output(self):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            targets = [("event", ordinal) for ordinal in range(1, 6)] + [("queue", 1)]
            if policy == "per_operation":
                targets += [("buffer", ordinal) for ordinal in range(1, 4)]
            for target, ordinal in targets:
                with self.subTest(policy=policy, dtype=dtype, target=target, ordinal=ordinal):
                    self.group("cleanup_operation", policy, dtype, target, ordinal)

    def test_async_primary_and_cleanup_failures_remain_distinct(self):
        self.matrix_group("cleanup_primary")

    def test_first_cleanup_error_survives_later_operation_and_context_release_failures(self):
        self.matrix_group("cleanup_first")

    def test_each_context_release_error_survives_close_and_last_operation_teardown(self):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            targets = [("kernel", 1), ("module", 1), ("device", 1)]
            if policy == "reusable_single_tile":
                targets += [("buffer", ordinal) for ordinal in range(1, 4)]
            for group, (target, ordinal) in itertools.product(
                    ("cleanup_context", "cleanup_retained_context"), targets):
                with self.subTest(policy=policy, dtype=dtype, group=group,
                                  target=target, ordinal=ordinal):
                    self.group(group, policy, dtype, target, ordinal)

    def test_destructor_cleanup_failure_poison_is_observed_by_future_work(self):
        for policy, dtype, target in itertools.product(POLICIES, DTYPES, ("owner", "operation")):
            with self.subTest(policy=policy, dtype=dtype, target=target):
                self.group("cleanup_destructor", policy, dtype, target)

    def test_setup_and_partial_rollback_cleanup_failures_poison_without_reset_hook(self):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            phases = ["context", "no_work", "partial"]
            if policy == "reusable_single_tile":
                phases.append("workspace")
            for phase in phases:
                with self.subTest(policy=policy, dtype=dtype, phase=phase):
                    self.group("cleanup_rollback", policy, dtype, phase)

    def test_poisoned_instance_recovery_uses_a_fresh_process(self):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            with self.subTest(policy=policy, dtype=dtype):
                self.group("cleanup_destructor", policy, dtype, "owner")
                self.group("context_lease", policy, dtype)
