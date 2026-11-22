# SPDX-License-Identifier: Apache-2.0
"""Release-build counter arithmetic checks; these do not execute a GPU model."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

from baseline_process import GIB, MIB, run_bounded
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "sim/common/perf_counter.h"
FIXTURE = ROOT / "ci/project/fixtures/p06_checked_counter_test.cpp"
COMPLETION_HEADER = ROOT / "sw/runtime/common/async_run.h"
FLAGS = (
    "-std=c++17", "-O2", "-DNDEBUG", "-g0", "-Wall", "-Wextra", "-Werror",
    "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
)


class CheckedCounterHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise AssertionError("Checked-counter tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-checked-counter-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name).resolve()
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        cls.source_bodies = {path: path.read_bytes() for path in (HEADER, FIXTURE, COMPLETION_HEADER)}
        cls.binaries = {}
        for mode in ("ordinary", "checked"):
            binary = cls.build / mode
            run_host_command([
                cls.compiler, *FLAGS,
                *(["-DSIMX_CHECKED_COUNTERS=1"] if mode == "checked" else []),
                "-I", str(HEADER.parent), "-I", str(COMPLETION_HEADER.parent),
                str(FIXTURE), "-o", str(binary),
            ], cwd=cls.build, env=cls.environment, timeout=45)
            cls.binaries[mode] = binary

    def setUp(self):
        self.assertEqual({path: path.read_bytes() for path in self.source_bodies},
                         self.source_bodies, "Counter inputs changed after compilation")

    def bounded_failure(self, argv):
        log = self.build / ("negative-" + uuid4().hex + ".log")
        result = run_bounded(
            list(map(str, argv)), self.build, self.environment, log,
            timeout_seconds=15, min_free_bytes=GIB, max_rss_bytes=GIB,
            max_log_bytes=MIB, resource_paths=(self.build,),
        )
        output = log.read_text(encoding="utf-8", errors="strict") if log.exists() else ""
        self.assertTrue(result["process_started"], (result, output))
        self.assertTrue(result["cleanup_complete"], (result, output))
        self.assertEqual(result["outcome"], "fail", (result, output))
        self.assertEqual(result["reason"], "nonzero_exit", (result, output))
        return result, output

    def assert_counter_failure(self, mode, reason):
        output = run_host_command([str(self.binaries["checked"]), mode], cwd=self.build,
                                  env=self.environment, timeout=10)
        self.assertEqual(output, "PASSED: checked-counter exception " + reason + "\n")

    def assert_completion(self, mode):
        output = run_host_command([str(self.binaries["checked"]), mode], cwd=self.build,
                                  env=self.environment, timeout=10)
        self.assertEqual(output, "PASSED: checked-counter completion " + mode + "\n")

    def assert_compile_rejected(self, body, defines, diagnostic):
        source = self.build / ("rejected-" + uuid4().hex + ".cpp")
        source.write_text("#include <perf_counter.h>\n" + body + "\n", encoding="utf-8")
        result, output = self.bounded_failure([
            self.compiler, *FLAGS, *defines, "-I", HEADER.parent, "-fsyntax-only", source,
        ])
        self.assertGreater(result["exit_code"], 0, output)
        self.assertIn(diagnostic, output)

    def test_exact_boundaries_and_copy_semantics_in_release_builds(self):
        for mode, binary in self.binaries.items():
            with self.subTest(mode=mode):
                output = run_host_command([str(binary), "boundaries"], cwd=self.build,
                                          env=self.environment, timeout=10)
                self.assertEqual(output, "PASSED: checked-counter boundaries\n")

    def test_ordinary_alias_retains_unsigned_wrap_behavior(self):
        for mode in ("add-overflow", "aggregate-overflow", "self-add-overflow",
                     "prefix-overflow", "postfix-overflow", "subtract-underflow",
                     "counter-subtract-underflow", "prefix-underflow", "postfix-underflow",
                     "negative-construction", "negative-assignment", "negative-addition",
                     "negative-subtraction", "async-overflow"):
            with self.subTest(mode=mode):
                output = run_host_command([str(self.binaries["ordinary"]), mode], cwd=self.build,
                                          env=self.environment, timeout=10)
                self.assertEqual(output, "PASSED: ordinary uint64 arithmetic retained\n")

    def test_additions_and_both_increment_forms_throw_before_mutation(self):
        for mode in ("add-overflow", "aggregate-overflow", "self-add-overflow",
                     "prefix-overflow", "postfix-overflow"):
            with self.subTest(mode=mode):
                self.assert_counter_failure(mode, "overflow")

    def test_subtractions_and_both_decrement_forms_throw_before_mutation(self):
        for mode in ("subtract-underflow", "counter-subtract-underflow",
                     "prefix-underflow", "postfix-underflow"):
            with self.subTest(mode=mode):
                self.assert_counter_failure(mode, "underflow")

    def test_signed_negative_values_cannot_become_large_unsigned_counts(self):
        for mode in ("negative-construction", "negative-assignment",
                     "negative-addition", "negative-subtraction"):
            with self.subTest(mode=mode):
                self.assert_counter_failure(mode, "negative operand")

    def test_async_owner_consumes_counter_failure_and_keeps_it_terminal(self):
        self.assert_completion("async-overflow")

    def test_synchronous_processor_invocation_keeps_counter_failure_terminal(self):
        self.assert_completion("sync-overflow")

    def test_direct_future_get_retrieves_counter_failure_after_wait(self):
        self.assert_completion("future-overflow")

    def test_join_and_destruction_finish_faulting_tasks_and_fresh_owners_work(self):
        for mode in ("join-overflow", "destructor-overflow"):
            with self.subTest(mode=mode):
                self.assert_completion(mode)

    def test_defined_option_requires_exact_enabled_value(self):
        for value in ("0", "2", ""):
            with self.subTest(value=value):
                self.assert_compile_rejected(
                    "int main() { return 0; }", ["-DSIMX_CHECKED_COUNTERS=" + value],
                    "SIMX_CHECKED_COUNTERS must be 1 when defined",
                )

    def test_binary_addition_and_subtraction_cannot_bypass_checked_updates(self):
        for expression in ("left + right", "left + 1", "1 + right",
                           "left - right", "left - 1", "1 - right"):
            with self.subTest(expression=expression):
                self.assert_compile_rejected(
                    "int main() { vortex::PerfCounter left = 1, right = 2; "
                    "(void)(" + expression + "); }",
                    ["-DSIMX_CHECKED_COUNTERS=1"], "deleted",
                )

    def test_unary_negation_cannot_create_a_wrapped_counter(self):
        self.assert_compile_rejected(
            "int main() { vortex::PerfCounter value = 1; (void)(-value); }",
            ["-DSIMX_CHECKED_COUNTERS=1"], "deleted",
        )


if __name__ == "__main__":
    unittest.main()
