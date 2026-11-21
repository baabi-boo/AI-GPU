# SPDX-License-Identifier: Apache-2.0
"""Real model/managed-wrapper composition over a fake C API; no GPU arithmetic."""

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
HARNESS = ROOT / "ci/project/fixtures/p06_workspace_model_guard_test.cpp"
SHARED_HARNESS = ROOT / "ci/project/fixtures/p03_managed_runtime_test.cpp"
POLICIES = ("per_operation", "reusable_single_tile")
DTYPES = ("fp16", "bf16")


class WorkspaceModelGuardHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Model/managed-wrapper guard tests require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-model-guard-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "model-guard-test"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        inputs = [
            HARNESS, SHARED_HARNESS, Path(__file__).resolve(),
            *(RUNTIME / name for name in ("runtime.h", "runtime.cpp", "contract.h", "contract.cpp",
                                         "mlp_runtime.h", "mlp_runtime.cpp", "mlp_host.h", "mlp_host.cpp")),
            ROOT / "sw/runtime/include/vortex2.h", ROOT / "sw/common/ai_matmul_args.h",
            ROOT / "ci/project/tensor_host_tools.py", ROOT / "ci/project/baseline_process.py",
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
            "-I", str(RUNTIME), "-I", str(ROOT / "sw/runtime/include"),
            "-I", str(ROOT / "sw/common"), str(HARNESS), str(RUNTIME / "runtime.cpp"),
            str(RUNTIME / "contract.cpp"), str(RUNTIME / "mlp_runtime.cpp"),
            str(RUNTIME / "mlp_host.cpp"), "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=45)

    def group(self, name, dtype, policy="per_operation", *arguments):
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed before model guard case: " + str(path))
        output = run_host_command(
            [str(self.binary), name, policy, dtype, *arguments],
            cwd=self.build, env=self.environment, timeout=10,
        )
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during model guard case: " + str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024)

    def formats(self, name):
        for dtype in DTYPES:
            with self.subTest(dtype=dtype):
                self.group(name, dtype)

    def policies_and_formats(self, name):
        for policy, dtype in itertools.product(POLICIES, DTYPES):
            with self.subTest(policy=policy, dtype=dtype):
                self.group(name, dtype, policy)

    def test_idle_live_and_waited_direct_owners_exclude_real_models_until_owner_close(self):
        self.policies_and_formats("matmul_excludes_model")

    def test_operation_outliving_direct_owner_excludes_real_model_until_completed_close(self):
        self.policies_and_formats("retained_operation")

    def test_real_model_excludes_models_and_matmul_when_idle_suspended_and_terminal(self):
        self.formats("model_excludes_contexts")

    def test_terminal_arithmetic_and_runtime_failures_retain_owner_until_explicit_close(self):
        self.formats("terminal_failures")

    def test_every_partial_model_dispatch_retains_shared_guard_through_incomplete_close(self):
        self.formats("partial_submission")

    def test_nondefault_and_unknown_model_policies_reject_before_native_open(self):
        self.formats("invalid_policy")

    def test_model_setup_and_initial_memory_query_failures_return_shared_reservation(self):
        self.formats("setup_rollback")

    def test_direct_operation_and_owner_cleanup_failures_poison_real_model_creation(self):
        for dtype, policy, phase in itertools.product(DTYPES, POLICIES, ("operation", "owner")):
            with self.subTest(dtype=dtype, policy=policy, phase=phase):
                self.group("direct_cleanup_poison", dtype, policy, phase)

    def test_model_cleanup_destructor_and_rollback_failures_poison_all_managed_creation(self):
        for dtype, phase in itertools.product(DTYPES, ("operation", "owner", "destructor", "rollback")):
            with self.subTest(dtype=dtype, phase=phase):
                self.group("model_cleanup_poison", dtype, "per_operation", phase)

    def test_all_default_signatures_and_three_stage_models_allow_serial_healthy_handoffs(self):
        self.formats("default_shapes")

    def test_idle_suspended_and_terminal_model_destruction_returns_healthy_reservation(self):
        self.formats("model_destructor")
