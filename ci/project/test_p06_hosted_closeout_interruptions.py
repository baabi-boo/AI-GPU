# SPDX-License-Identifier: Apache-2.0
"""Hosted closeout interruptions retain failure evidence without restarting writers."""

from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import signal
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import test_p06_qualified_warm_hosted as fixtures


@contextmanager
def _composition(*, failed_native=False, disposition="run", monitor_error=False):
    case = fixtures.HostedCompositionTests()
    try:
        case.setUp()
        if failed_native:
            case.failures.add("p06_qualified_warm_run")

        def command(argv, *args, **kwargs):
            result = case.command(argv, *args, **kwargs)
            if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_run":
                path = case.attempt / "workspace/evidence/qualified-warm-run.json"
                report = json.loads(path.read_text())
                report.update(contract_id=hosted.runner.CONTRACT_ID, native_execution=disposition)
                report["stages"] = []
                for name in ("dependency-build", "qualified-warm"):
                    relative = name + "/report.json"
                    report["stages"].append({"id": name, "process_started": True,
                        "cleanup_complete": True, "report_path": relative})
                    case.write(path.parent / relative, {"state": "finished",
                        "commands": [{"process_started": True, "cleanup_complete": True}]})
                case.write(path, report)
                if monitor_error:
                    raise RuntimeError(fixtures.SECRET)
            return result

        with mock.patch.object(hosted, "run_bounded", side_effect=command):
            yield case
    finally:
        case.doCleanups()


class HostedCloseoutInterruptionTests(unittest.TestCase):
    def signal_second_native_read(self, case, *, before_signal=None):
        original = hosted._read
        path = case.attempt / "workspace/evidence/qualified-warm-run.json"
        observations = {"reads": 0, "snapshots": []}
        previous = signal.getsignal(signal.SIGTERM)

        def read(selected, *args, **kwargs):
            if Path(selected) == path:
                observations["reads"] += 1
                if observations["reads"] >= 2:
                    observations["snapshots"].append({"calls": deepcopy(case.calls),
                        "reports": {str(child.relative_to(path.parent)): child.read_bytes()
                                    for child in path.parent.rglob("*.json")}})
                if observations["reads"] == 2:
                    self.assertIsNot(signal.getsignal(signal.SIGTERM), previous)
                    self.assertTrue(callable(signal.getsignal(signal.SIGTERM)))
                    if before_signal is not None:
                        before_signal()
                    os.kill(os.getpid(), signal.SIGTERM)
                    raise AssertionError("SIGTERM did not interrupt the hosted receipt read")
            return original(selected, *args, **kwargs)

        return observations, mock.patch.object(hosted, "_read", side_effect=read)

    def run_cli(self, case):
        output = io.StringIO()
        provider_output = case.root / "github-output"
        previous = signal.getsignal(signal.SIGTERM)
        sigint = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(provider_output)}), redirect_stdout(output):
            status = hosted.main(["run", "--source-dir", str(case.source),
                "--expected-revision", fixtures.REVISION, "--attempt-root", str(case.attempt)])
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)
        self.assertIs(signal.getsignal(signal.SIGINT), sigint)
        self.assertEqual(status, 1)
        for private in (fixtures.SECRET, str(case.source), str(case.attempt), "token_fixture"):
            self.assertNotIn(private, output.getvalue())
        for line in output.getvalue().splitlines():
            self.assertEqual(set(json.loads(line)), {"contract_id", "expected_revision", "stage", "outcome"})
        final = case.attempt / "attempt-final.PRIVATE.json"
        self.assertTrue(final.is_file(), "closeout escaped before retaining its final failure receipt")
        report = json.loads(final.read_text())
        self.assertEqual(provider_output.read_text() if provider_output.exists() else "",
                         "encrypted_retention_ready=true\n" if report["encryption_passed"] else "")
        return report

    def assert_closeout(self, case, result, *, native="run", delivered=True):
        for relative in ("hosted/attempt-before-closeout.json", "retention/hosted-closeout.json",
                         "attempt-final.PRIVATE.json"):
            path = case.attempt / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            report = json.loads(path.read_text())
            self.assertEqual(report["state"], "finished")
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual(report["native_execution"], native)
            self.assertIs(report["writers_finished_observed"], delivered)
            for name in ("orchestration_passed", "qualified_warm_passed",
                         "counter_qualification_passed", *hosted.dependency.FALSE_CLAIMS):
                self.assertIs(report[name], False, name)
            self.assertEqual(report["expected_counts"], hosted.runner.COMPLETE_COUNTS)
            self.assertEqual(report["budget"], hosted.runner.BUDGET)
            self.assertNotIn(fixtures.SECRET, json.dumps(report["failures"]))
        self.assertIs(result["packaging_passed"], delivered)
        self.assertIs(result["encryption_passed"], delivered)
        modules = [row["module"] for row in case.calls]
        expected = ["recipient-probe", "p06_qualified_warm_control",
                    "p06_qualified_warm_inputs", "p06_qualified_warm_run"]
        if delivered:
            expected.extend(("p06_qualified_warm_pack", "p06_qualified_warm_encrypt"))
            packed = next(row for row in case.calls if row["module"] == "p06_qualified_warm_pack")
            self.assertEqual(packed["argv"][3], "partial")
            self.assertIn("--writers-finished", packed["argv"])
        else:
            self.assertFalse((case.attempt / "retention/packet").exists())
            self.assertFalse((case.attempt / "public").exists())
            for name in ("packaging", "encryption"):
                self.assertIn({"stage": name, "error_type": "HostedError"}, result["failures"])
        self.assertEqual(modules, expected)

    def test_sigterm_during_writer_read_retains_native_truth_and_partial_delivery(self):
        with _composition() as case:
            observed, interrupted = self.signal_second_native_read(case)
            with interrupted:
                result = self.run_cli(case)
            self.assert_closeout(case, result)
            self.assertEqual(result["failures"], [{"stage": "writers-closeout", "error_type": "KeyboardInterrupt"}])
            self.assertEqual(observed["reads"], 3)
            self.assertEqual(len(observed["snapshots"]), 2)
            self.assertEqual(*observed["snapshots"])

    def test_sigterm_during_failed_native_disposition_read_preserves_observed_scope(self):
        for disposition in ("not_run", "unknown", "run"):
            with self.subTest(disposition=disposition), _composition(
                    failed_native=True, disposition=disposition) as case:
                observed, interrupted = self.signal_second_native_read(case)
                with interrupted:
                    result = self.run_cli(case)
                self.assert_closeout(case, result, native=disposition)
                self.assertEqual(result["failures"], [
                    {"stage": "execution", "error_type": "HostedError"},
                    {"stage": "native-closeout", "error_type": "KeyboardInterrupt"}])
                self.assertEqual(observed["reads"], 3)
                self.assertEqual(len(observed["snapshots"]), 2)
                self.assertEqual(*observed["snapshots"])

    def test_writer_reobservation_does_not_invent_nested_completion(self):
        for damage in ("unknown-launch", "incomplete-cleanup", "missing", "malformed"):
            with self.subTest(damage=damage), _composition() as case:
                child = case.attempt / "workspace/evidence/qualified-warm/report.json"

                def change():
                    if damage == "missing":
                        child.unlink()
                    elif damage == "malformed":
                        child.write_text("invalid receipt")
                    else:
                        case.write(child, {"state": "finished", "commands": [{
                            "process_started": None if damage == "unknown-launch" else True,
                            "cleanup_complete": damage != "incomplete-cleanup"}]})

                observed, interrupted = self.signal_second_native_read(case, before_signal=change)
                with interrupted:
                    result = self.run_cli(case)
                self.assert_closeout(case, result, delivered=False)
                self.assertIn({"stage": "writers-closeout", "error_type": "KeyboardInterrupt"}, result["failures"])
                self.assertEqual(observed["reads"], 3)

    def test_second_writer_interrupt_or_error_stops_reobservation_and_blocks_delivery(self):
        for error in (KeyboardInterrupt(fixtures.SECRET), RuntimeError(fixtures.SECRET)):
            with self.subTest(error=type(error).__name__), _composition() as case:
                with mock.patch.object(hosted, "writers_finished", side_effect=[
                        KeyboardInterrupt(), error, True]) as observe:
                    result = self.run_cli(case)
                self.assert_closeout(case, result, delivered=False)
                self.assertEqual(observe.call_count, 2)
                self.assertEqual([row for row in result["failures"] if row["stage"] == "writers-closeout"], [
                    {"stage": "writers-closeout", "error_type": "KeyboardInterrupt"},
                    {"stage": "writers-closeout", "error_type": type(error).__name__}])

    def test_writer_error_is_recorded_without_retry_or_delivery(self):
        for error_type in (OSError, RuntimeError, TypeError):
            with self.subTest(error=error_type.__name__), _composition() as case:
                with mock.patch.object(hosted, "writers_finished", side_effect=[
                        error_type(fixtures.SECRET), True]) as observe:
                    result = self.run_cli(case)
                self.assert_closeout(case, result, delivered=False)
                self.assertEqual(observe.call_count, 1)
                self.assertIn({"stage": "writers-closeout", "error_type": error_type.__name__}, result["failures"])

    def test_unobserved_native_launch_stays_unknown_after_writer_interrupt(self):
        with _composition(monitor_error=True) as case:
            original = hosted.writers_finished
            calls = []

            def observe(*args):
                calls.append(deepcopy(args[1]))
                if len(calls) == 1:
                    raise KeyboardInterrupt()
                return original(*args)

            with mock.patch.object(hosted, "writers_finished", side_effect=observe), \
                    mock.patch.object(hosted, "observed_native_execution") as native:
                result = self.run_cli(case)
            self.assert_closeout(case, result, native="unknown", delivered=False)
            self.assertEqual(len(calls), 2)
            self.assertEqual(*calls)
            native.assert_not_called()
            stage = next(row for row in result["stages"] if row["id"] == "native-supervisor")
            self.assertIsNone(stage["process_started"])
            self.assertIs(stage["cleanup_complete"], False)

    def test_second_native_observation_interrupt_or_error_preserves_unknown_and_partial_delivery(self):
        for error in (KeyboardInterrupt(fixtures.SECRET), RuntimeError(fixtures.SECRET)):
            with self.subTest(error=type(error).__name__), _composition(failed_native=True) as case:
                with mock.patch.object(hosted, "observed_native_execution", side_effect=[
                        KeyboardInterrupt(), error, "run"]) as observe:
                    result = self.run_cli(case)
                self.assert_closeout(case, result, native="unknown")
                self.assertEqual(observe.call_count, 2)
                self.assertEqual([row for row in result["failures"] if row["stage"] == "native-closeout"], [
                    {"stage": "native-closeout", "error_type": "KeyboardInterrupt"},
                    {"stage": "native-closeout", "error_type": type(error).__name__}])

    def test_native_observation_error_is_not_retried_or_promoted(self):
        with _composition(failed_native=True) as case:
            with mock.patch.object(hosted, "observed_native_execution", side_effect=[
                    RuntimeError(fixtures.SECRET), "run"]) as observe:
                result = self.run_cli(case)
            self.assert_closeout(case, result, native="unknown")
            self.assertEqual(observe.call_count, 1)
            self.assertIn({"stage": "native-closeout", "error_type": "RuntimeError"}, result["failures"])


if __name__ == "__main__":
    unittest.main()
