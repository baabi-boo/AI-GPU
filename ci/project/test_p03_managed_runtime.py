# SPDX-License-Identifier: Apache-2.0
"""Fault injection of wrapper ownership; fake transfers are not GPU evidence."""

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
HARNESS = ROOT / "ci/project/fixtures/p03_managed_runtime_test.cpp"


class ManagedRuntimeHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Managed runtime tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p03-managed-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "managed-test"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        inputs = [HARNESS, *(RUNTIME / name for name in
                  ("runtime.h", "runtime.cpp", "contract.h", "contract.cpp")),
                  ROOT / "sw/runtime/include/vortex2.h", ROOT / "sw/common/ai_matmul_args.h"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
            "-I", str(RUNTIME), "-I", str(ROOT / "sw/runtime/include"),
            "-I", str(ROOT / "sw/common"), str(HARNESS), str(RUNTIME / "runtime.cpp"),
            str(RUNTIME / "contract.cpp"), "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=45)

    def group(self, name):
        output = run_host_command([str(self.binary), name], cwd=self.build,
                                  env=self.environment, timeout=10)
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during managed runtime tests: " + str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024)

    def test_six_signatures_transfer_owned_bytes_and_report_exact_argument_record(self):
        self.group("positive_shapes")

    def test_unqualified_binding_and_unsupported_device_reject_without_leaks(self):
        self.group("invalid_binding")

    def test_bad_shape_and_host_spans_reject_before_allocating(self):
        self.group("invalid_inputs")

    def test_device_query_module_and_kernel_failures_preserve_cleanup(self):
        self.group("create_failures")

    def test_every_allocation_address_and_enqueue_failure_drains_partial_work(self):
        self.group("partial_failures")

    def test_timeout_retains_all_resources_and_operation_outlives_owner(self):
        self.group("timeout_ownership")

    def test_failed_events_preserve_primary_and_cleanup_errors_separately(self):
        self.group("asynchronous_errors")

    def test_actual_allocated_addresses_are_validated_before_dispatch(self):
        self.group("allocation_validation")

    def test_destructor_drains_and_repeated_operations_release_resources(self):
        self.group("destructor_drain")

    def test_opt_in_profiles_distinguish_observed_events_and_query_failures(self):
        self.group("profiling")
