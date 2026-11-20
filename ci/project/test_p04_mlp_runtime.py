# SPDX-License-Identifier: Apache-2.0
"""Fixed-model control flow with fake native operators; no GPU arithmetic."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "sw/runtime/ai"
HARNESS = ROOT / "ci/project/fixtures/p04_mlp_runtime_test.cpp"


class ManagedMlpHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Managed model tests require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p04-model-host-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "model-test"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        inputs = [HARNESS, *(RUNTIME / name for name in
                  ("mlp_runtime.h", "mlp_runtime.cpp", "mlp_host.h", "mlp_host.cpp",
                   "runtime.h", "contract.h")), ROOT / "sw/runtime/include/vortex2.h",
                  ROOT / "sw/common/ai_matmul_args.h",
                  ROOT / "tests/regression/ai_mlp/p04_fixtures.h"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
            "-I", str(RUNTIME), "-I", str(ROOT / "sw/runtime/include"),
            "-I", str(ROOT / "sw/common"), "-I", str(ROOT / "tests/regression/ai_mlp"),
            str(HARNESS), str(RUNTIME / "mlp_runtime.cpp"), str(RUNTIME / "mlp_host.cpp"),
            "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=45)

    def group(self, name):
        output = run_host_command([str(self.binary), name], cwd=self.build,
                                  env=self.environment, timeout=10)
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during model tests: " + str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024)

    def test_all_frozen_cases_both_poisons_exact_three_stage_lineage(self):
        self.group("positive_graph")

    def test_caller_input_reference_and_identity_mutation_cannot_change_owned_case(self):
        self.group("copied_ownership")

    def test_every_stage_timeout_resumes_without_duplicate_launch_or_premature_release(self):
        self.group("timeout_resume")

    def test_partial_submission_retains_prior_error_during_incomplete_drain(self):
        self.group("partial_submission")

    def test_every_stage_event_failure_stops_dependent_work_and_preserves_error(self):
        self.group("asynchronous_failures")

    def test_every_stage_cleanup_error_is_distinct_from_primary_failure(self):
        self.group("cleanup_failures")

    def test_hidden_signed_zero_bridge_and_row_corruptions_stop_at_first_boundary(self):
        self.group("comparison_stops")

    def test_invalid_actual_hidden_domain_rejects_before_native_dependent_work(self):
        self.group("bridge_domain")

    def test_explicit_close_and_destructor_only_drain_without_finishing_graph(self):
        self.group("close_boundaries")

    def test_invalid_create_and_setup_errors_preserve_output_ownership(self):
        self.group("invalid_create")

    def test_resource_queries_mismatches_and_owner_close_results_cannot_pass(self):
        self.group("resources_and_owner")

    def test_wrong_output_extents_reject_before_copy_or_comparison(self):
        self.group("output_sizes")

    def test_host_allocation_failure_preserves_pending_operation_for_drain(self):
        self.group("allocation_failures")

    def test_repeated_models_restore_owned_resources(self):
        self.group("repetitions")
