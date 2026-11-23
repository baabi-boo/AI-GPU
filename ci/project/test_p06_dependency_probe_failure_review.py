# SPDX-License-Identifier: Apache-2.0
"""Synthetic supervisor failures; no native compile or probe is executed."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_pending_probe as probe
from p06_managed_preflight_build_fixture import generate
from test_p06_dependency_probe import DependencyProbeHarness


class DependencyProbeFailureReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dependency-probe-failure-review-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = generate(Path(cls.temporary.name))

    def setUp(self):
        self.data = self.generated["formats"]["fp16"]

    def fail_supervisor(self, fixture, *, target="run-native", error=OSError,
                        mutate_input=False, oversized=False, empty_interrupt=False):
        """Substitute execution, keeping actual partial bytes and checkpoints."""
        partial = b"synthetic supervisor partial trace; no native execution\n"
        observed = {}

        def command(argv, cwd, environment, logfile, **budget):
            if logfile.stem != target:
                return fixture.command(argv, cwd, environment, logfile, **budget)
            observed["checkpoint"] = json.loads(
                (fixture.args.output_dir / "report.json").read_text())
            observed["log"] = logfile
            if oversized:
                with logfile.open("wb") as stream:
                    stream.truncate(probe.BUDGET["max_log_bytes"] + 1)
            else:
                logfile.write_bytes(partial)
            if mutate_input:
                fixture.binding_path.write_bytes(b"synthetic changed binding after failed attempt")
            if empty_interrupt:
                raise error()
            raise error("synthetic supervision failure at " + target)

        fixture.executor.side_effect = command
        return observed, partial

    def assert_failed_report(self, fixture, report, state):
        self.assertEqual(report["state"], "finished")
        self.assertEqual(report["outcome"], "fail", report["reason"])
        self.assertEqual(report["native_execution"], state)
        self.assertIs(report["native_probe_passed"], False)
        self.assertEqual(report, fixture.saved)
        self.assertIn("finished_at", report)
        for flag in contract.FALSE_CLAIMS:
            self.assertIs(report[flag], False)

    def assert_partial_log(self, report, partial, *, target="run-native",
                           reason="synthetic supervision failure"):
        row = report["commands"][-1]
        self.assertEqual(row["id"], target)
        self.assertIsNone(row["process_started"])
        self.assertEqual(row["log"], "logs/" + target + ".log")
        self.assertEqual(row["log_sha256"], hashlib.sha256(partial).hexdigest())
        self.assertEqual(row["log_size_bytes"], len(partial))
        self.assertIn(reason, row["reason"])
        return row

    def test_native_supervision_error_retains_unknown_attempt_and_partial_log(self):
        with DependencyProbeHarness(self.data) as fixture:
            observed, partial = self.fail_supervisor(fixture)
            report = fixture.run()
            self.assert_failed_report(fixture, report, "unknown")
            self.assert_partial_log(report, partial)
            self.assertEqual(observed["checkpoint"]["native_execution"], "unknown")
            self.assertEqual(observed["checkpoint"]["commands"][-1]["id"], "run-native")
            self.assertIsNone(observed["checkpoint"]["commands"][-1]["process_started"])

    def test_final_stability_failure_preserves_first_supervision_reason(self):
        with DependencyProbeHarness(self.data) as fixture:
            _, partial = self.fail_supervisor(fixture, mutate_input=True)
            report = fixture.run()
            self.assert_failed_report(fixture, report, "unknown")
            self.assert_partial_log(report, partial)
            self.assertIn("synthetic supervision failure at run-native", report["reason"])
            self.assertIn("probe input stability failed", report["failures"])
            self.assertNotEqual(report["inputs_before"], report["inputs_after"])

    def test_known_nonstart_does_not_claim_native_execution(self):
        with DependencyProbeHarness(self.data) as fixture:
            fixture.results["run-native"] = {"process_started": False,
                "outcome": "blocked", "exit_code": None, "reason": "synthetic spawn failure"}
            report = fixture.run()
            self.assert_failed_report(fixture, report, "not_run")
            self.assertEqual(report["commands"][-1]["id"], "run-native")
            self.assertIs(report["commands"][-1]["process_started"], False)
            self.assertIs(report["zero_mutation_rejected"], False)

    def test_later_unknown_attempt_preserves_prior_positive_execution(self):
        with DependencyProbeHarness(self.data) as fixture:
            observed, partial = self.fail_supervisor(fixture, target="run-always-zero")
            report = fixture.run()
            self.assert_failed_report(fixture, report, "run")
            self.assert_partial_log(report, partial, target="run-always-zero")
            self.assertEqual(observed["checkpoint"]["native_execution"], "run")
            self.assertEqual(report["products"][0]["mode"], "native")
            self.assertIs(report["zero_mutation_rejected"], False)

    def test_keyboard_interrupt_retains_attempt_and_finalizes_report(self):
        for empty in (False, True):
            with self.subTest(empty_interrupt=empty), DependencyProbeHarness(self.data) as fixture:
                _, partial = self.fail_supervisor(fixture, error=KeyboardInterrupt, empty_interrupt=empty)
                try:
                    report = fixture.run()
                except KeyboardInterrupt as error:
                    self.fail("supervisor interrupt escaped execute: " + str(error))
                self.assert_failed_report(fixture, report, "unknown")
                reason = "interrupted" if empty else "synthetic supervision failure"
                self.assert_partial_log(report, partial, reason=reason)
                self.assertIn(reason, report["reason"])

    def test_oversized_partial_log_is_not_hashed_without_a_byte_bound(self):
        with DependencyProbeHarness(self.data) as fixture:
            observed, _ = self.fail_supervisor(fixture, oversized=True)
            digest = probe._digest

            def bounded_digest(path):
                if Path(path) == observed.get("log"):
                    self.fail("oversized partial log reached the unbounded digest helper")
                return digest(path)

            with mock.patch.object(probe, "_digest", side_effect=bounded_digest):
                report = fixture.run()
            self.assert_failed_report(fixture, report, "unknown")
            row = report["commands"][-1]
            self.assertEqual(row["id"], "run-native")
            self.assertIn("synthetic supervision failure at run-native", report["reason"])
            self.assertIn("log_identity_error", row)
            self.assertIsNone(row.get("log_sha256"))

    def test_compiler_supervision_failure_is_retained_without_native_claim(self):
        with DependencyProbeHarness(self.data) as fixture:
            _, partial = self.fail_supervisor(fixture, target="compiler-version")
            report = fixture.run()
            self.assert_failed_report(fixture, report, "not_run")
            self.assert_partial_log(report, partial, target="compiler-version")
            self.assertEqual(len(report["commands"]), 1)


if __name__ == "__main__":
    unittest.main()
