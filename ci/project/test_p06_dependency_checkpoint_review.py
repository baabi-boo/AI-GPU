# SPDX-License-Identifier: Apache-2.0
"""Synthetic sequential failures with real checkpoint files; no native execution."""

import contextlib
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_substitution as substitution
import p06_pending_probe as probe
from p06_managed_preflight_build_fixture import generate
from test_p06_dependency_probe import DependencyProbeHarness
from test_p06_dependency_substitution import SyntheticControlHarness


PRIMARY = "synthetic original supervisor failure"
SECONDARY = "synthetic one-time error-checkpoint write failure"
PARTIAL = b"synthetic partial supervisor trace; no native execution\n"


@contextlib.contextmanager
def fail_error_checkpoint(base, output):
    actual_write = base._write_json
    observed = {"failures": 0, "final_writes": 0}

    def write(path, report):
        selected = Path(path) == output / "report.json"
        commands = report.get("commands", [])
        if (selected and report.get("state") == "running" and commands
                and commands[-1].get("reason") == PRIMARY and not observed["failures"]):
            observed["failures"] += 1
            raise OSError(SECONDARY)
        result = actual_write(path, report)
        if selected and report.get("state") == "finished":
            observed["final_writes"] += 1
        return result

    with mock.patch.object(base, "_write_json", side_effect=write):
        yield observed


def fail_supervisor(harness, target, error_type):
    def command(argv, cwd, environment, log_path, **limits):
        if Path(log_path).stem != target:
            return harness.command(argv, cwd, environment, log_path, **limits)
        Path(log_path).write_bytes(PARTIAL)
        raise error_type(PRIMARY)

    harness.executor.side_effect = command


class DependencyCheckpointReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dependency-checkpoint-review-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.data = generate(Path(cls.temporary.name))["formats"]["fp16"]

    def assert_retained(self, harness, report, observed, target, native_state, outcome):
        self.assertEqual(observed, {"failures": 1, "final_writes": 1})
        self.assertEqual(report, harness.saved)
        self.assertEqual(report["state"], "finished")
        self.assertIn("finished_at", report)
        self.assertEqual(report["outcome"], outcome)
        self.assertEqual(report["native_execution"], native_state)
        row = report["commands"][-1]
        self.assertEqual(row["id"], target)
        self.assertIsNone(row["process_started"])
        self.assertEqual(row["reason"], PRIMARY)
        self.assertEqual(row["log_sha256"], hashlib.sha256(PARTIAL).hexdigest())
        self.assertEqual(row["log_size_bytes"], len(PARTIAL))
        for name in contract.FALSE_CLAIMS:
            self.assertIs(report[name], False)
        failures = [row["reason"] if isinstance(row, dict) else row
                    for row in report["failures"]]
        self.assertEqual(report["reason"], PRIMARY, "retained failures: " + repr(failures))
        self.assertEqual(failures[0], PRIMARY)
        self.assertIn(SECONDARY, failures[1:])

    def run_probe(self, target, native_state, error_type=RuntimeError):
        with DependencyProbeHarness(self.data) as harness:
            fail_supervisor(harness, target, error_type)
            with fail_error_checkpoint(probe.base, harness.args.output_dir) as observed:
                report = harness.run()
            self.assertIs(report["native_probe_passed"], False)
            self.assertIs(report["zero_mutation_rejected"], False)
            self.assert_retained(harness, report, observed, target, native_state, "fail")

    def run_control(self, target, native_state, outcome, error_type=RuntimeError):
        with SyntheticControlHarness() as harness:
            fail_supervisor(harness, target, error_type)
            with fail_error_checkpoint(substitution.base, harness.control.output) as observed:
                report = harness.run()
            self.assertIs(report["control_passed"], False)
            self.assertIs(report["original_provenance_rejected"], False)
            self.assertIs(report["managed_population_included"], False)
            self.assertIn(report["commands"][-1]["log"],
                          [row["path"] for row in report["retained_files"]])
            self.assert_retained(harness, report, observed, target, native_state, outcome)

    def test_probe_native_first_reason_survives_error_checkpoint_failure(self):
        for error_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(supervisor_error=error_type.__name__):
                self.run_probe("run-native", "unknown", error_type)

    def test_probe_compiler_first_reason_survives_error_checkpoint_failure(self):
        self.run_probe("compiler-version", "not_run")

    def test_probe_known_prior_execution_survives_error_checkpoint_failure(self):
        self.run_probe("run-always-zero", "run")

    def test_control_native_first_reason_survives_error_checkpoint_failure(self):
        for error_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(supervisor_error=error_type.__name__):
                self.run_control("run-alternate-extension", "unknown", "fail", error_type)

    def test_control_compiler_first_reason_survives_error_checkpoint_failure(self):
        self.run_control("compile-alternate-extension", "not_run", "blocked")


if __name__ == "__main__":
    unittest.main()
