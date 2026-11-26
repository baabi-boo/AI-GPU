# SPDX-License-Identifier: Apache-2.0
"""Hosted status failures retain launch truth without starting fixture children."""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import test_p06_qualified_warm_hosted as fixtures


STAGES = ("recipient-probe", "control-intake", "input-acquisition", "native-supervisor")
MODULES = ("recipient-probe", "p06_qualified_warm_control", "p06_qualified_warm_inputs",
           "p06_qualified_warm_run")
ERRORS = (OSError, BrokenPipeError, KeyboardInterrupt)


@contextmanager
def _composition():
    case = fixtures.HostedCompositionTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def _failed_emission(stage, error_type, *, outcome="running", before_raise=None):
    original = hosted._emit
    attempts = []

    def emit(revision, name, status):
        if (name, status) == (stage, outcome):
            attempts.append((name, status))
            if len(attempts) == 1:
                if before_raise is not None:
                    before_raise()
                raise error_type(fixtures.SECRET)
        return original(revision, name, status)

    return attempts, mock.patch.object(hosted, "_emit", side_effect=emit)


class HostedPrelaunchEmissionTests(unittest.TestCase):
    def run_cli(self, case):
        output = io.StringIO()
        provider_output = case.root / "github-output"
        previous = {name: signal.getsignal(name) for name in (signal.SIGINT, signal.SIGTERM)}
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(provider_output)}), redirect_stdout(output):
            status = hosted.main(["run", "--source-dir", str(case.source),
                "--expected-revision", fixtures.REVISION, "--attempt-root", str(case.attempt)])
        self.assertEqual(status, 1)
        for name, handler in previous.items():
            self.assertIs(signal.getsignal(name), handler)
        for private in (fixtures.SECRET, str(case.source), str(case.attempt), "token_fixture"):
            self.assertNotIn(private, output.getvalue())
        for line in output.getvalue().splitlines():
            self.assertEqual(set(json.loads(line)), {"contract_id", "expected_revision", "stage", "outcome"})
        report = json.loads((case.attempt / "attempt-final.PRIVATE.json").read_text())
        self.assertEqual(provider_output.read_text() if provider_output.exists() else "",
                         "encrypted_retention_ready=true\n" if report["encryption_passed"] else "")
        self.assertNotIn(fixtures.SECRET, json.dumps(report))
        return report

    def assert_failure_receipts(self, case, result, *, native, delivered):
        for relative in ("hosted/attempt-before-closeout.json", "retention/hosted-closeout.json",
                         "attempt-final.PRIVATE.json"):
            path = case.attempt / relative
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            report = json.loads(path.read_text())
            self.assertEqual(report["state"], "finished")
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual(report["native_execution"], native)
            self.assertIs(report["writers_finished_observed"], delivered)
            self.assertEqual(report["expected_counts"], hosted.runner.COMPLETE_COUNTS)
            self.assertEqual(report["budget"], hosted.runner.BUDGET)
            for claim in ("orchestration_passed", "qualified_warm_passed",
                          "counter_qualification_passed", *hosted.dependency.FALSE_CLAIMS):
                self.assertIs(report[claim], False, claim)
        self.assertIs(result["packaging_passed"], delivered)
        self.assertIs(result["encryption_passed"], delivered)
        if delivered:
            packed = next(row for row in case.calls if row["module"] == "p06_qualified_warm_pack")
            self.assertEqual(packed["argv"][3], "partial")
            self.assertIn("--writers-finished", packed["argv"])
        else:
            self.assertFalse((case.attempt / "retention/packet").exists())
            self.assertFalse((case.attempt / "public").exists())

    def assert_prior_launches(self, result, count):
        self.assertEqual([row["id"] for row in result["stages"][:count]], list(STAGES[:count]))
        for row in result["stages"][:count]:
            self.assertIs(row["process_started"], True)
            self.assertIs(row["cleanup_complete"], True)
            self.assertEqual(row["outcome"], "pass")
            self.assertEqual(row["exit_code"], 0)
            self.assertIsNone(row["reason"])

    def check_prelaunch_failure(self, case, stage, error_type, *, before_raise=None, delivered=True):
        attempts, failed = _failed_emission(stage, error_type, before_raise=before_raise)
        with failed, mock.patch.object(hosted, "observed_native_execution") as native:
            result = self.run_cli(case)
        native.assert_not_called()
        self.assertEqual(attempts, [(stage, "running")])
        prior = STAGES.index(stage)
        modules = list(MODULES[:prior])
        if delivered:
            modules.extend(("p06_qualified_warm_pack", "p06_qualified_warm_encrypt"))
        self.assertEqual([row["module"] for row in case.calls], modules)
        self.assert_prior_launches(result, prior)
        active = result["stages"][prior]
        self.assertEqual(active["id"], stage)
        self.assertIs(active["process_started"], False)
        self.assertIs(active["cleanup_complete"], True)
        self.assertEqual(active["outcome"], "blocked")
        self.assertIsNone(active["exit_code"])
        self.assertEqual(active["reason"], error_type.__name__)
        self.assertFalse((case.attempt / "hosted/logs" / (stage + ".log")).exists())
        self.assertFalse((case.attempt / "workspace/evidence/qualified-warm-run.json").exists())
        for relative in ("hosted/attempt-before-closeout.json", "retention/hosted-closeout.json"):
            report = json.loads((case.attempt / relative).read_text())
            self.assertEqual(report["stages"][prior], active)
        self.assert_failure_receipts(case, result, native="not_run", delivered=delivered)
        failures = [{"stage": "execution", "error_type": error_type.__name__}]
        if not delivered:
            failures.extend({"stage": name, "error_type": "HostedError"}
                            for name in ("packaging", "encryption"))
        self.assertEqual(result["failures"], failures)

    def test_early_emission_failure_confirms_nonstart_and_retains_partial(self):
        for stage in STAGES[:-1]:
            for error_type in ERRORS:
                with self.subTest(stage=stage, error=error_type.__name__), _composition() as case:
                    self.check_prelaunch_failure(case, stage, error_type)

    def test_native_emission_failure_keeps_known_not_run_and_retains_partial(self):
        for error_type in ERRORS:
            with self.subTest(error=error_type.__name__), _composition() as case:
                self.check_prelaunch_failure(case, "native-supervisor", error_type)

    def test_native_nonstart_does_not_resolve_an_earlier_nested_writer(self):
        for error_type in ERRORS:
            with self.subTest(error=error_type.__name__), _composition() as case:
                def unresolved():
                    case.write(case.attempt / "acquisition/input-acquisition.json", {
                        "state": "finished", "outcome": "pass", "expected_revision": fixtures.REVISION,
                        "commands": [{"process_started": None, "cleanup_complete": False}]})

                self.check_prelaunch_failure(case, "native-supervisor", error_type,
                                             before_raise=unresolved, delivered=False)

    def test_supervisor_exception_retains_unknown_launch_and_blocks_delivery(self):
        for error_type in ERRORS:
            with self.subTest(error=error_type.__name__), _composition() as case:
                def command(argv, *args, **kwargs):
                    result = case.command(argv, *args, **kwargs)
                    if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_run":
                        path = case.attempt / "workspace/evidence/qualified-warm-run.json"
                        report = json.loads(path.read_text())
                        report["contract_id"] = hosted.runner.CONTRACT_ID
                        case.write(path, report)
                        raise error_type(fixtures.SECRET)
                    return result

                with mock.patch.object(hosted, "run_bounded", side_effect=command), \
                        mock.patch.object(hosted, "observed_native_execution") as native:
                    result = self.run_cli(case)
                native.assert_not_called()
                self.assertEqual([row["module"] for row in case.calls], list(MODULES))
                self.assert_prior_launches(result, 3)
                active = result["stages"][-1]
                self.assertEqual(active["id"], "native-supervisor")
                self.assertIsNone(active["process_started"])
                self.assertIs(active["cleanup_complete"], False)
                self.assertEqual(active["outcome"], "fail")
                self.assertTrue((case.attempt / "hosted/logs/native-supervisor.log").is_file())
                self.assert_failure_receipts(case, result, native="unknown", delivered=False)
                self.assertEqual(result["failures"], [
                    {"stage": "execution", "error_type": error_type.__name__},
                    {"stage": "packaging", "error_type": "HostedError"},
                    {"stage": "encryption", "error_type": "HostedError"}])

    def test_finished_emission_failure_preserves_observed_native_launch(self):
        for error_type in ERRORS:
            with self.subTest(error=error_type.__name__), _composition() as case:
                attempts, failed = _failed_emission("native-supervisor", error_type, outcome="pass")

                def command(argv, *args, **kwargs):
                    result = case.command(argv, *args, **kwargs)
                    if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_run":
                        path = case.attempt / "workspace/evidence/qualified-warm-run.json"
                        report = json.loads(path.read_text())
                        report["contract_id"] = hosted.runner.CONTRACT_ID
                        case.write(path, report)
                    return result

                with failed, mock.patch.object(hosted, "run_bounded", side_effect=command):
                    result = self.run_cli(case)
                self.assertEqual(attempts, [("native-supervisor", "pass")])
                self.assertEqual([row["module"] for row in case.calls], [*MODULES,
                    "p06_qualified_warm_pack", "p06_qualified_warm_encrypt"])
                self.assert_prior_launches(result, len(STAGES))
                self.assert_failure_receipts(case, result, native="run", delivered=True)
                self.assertEqual(result["failures"], [
                    {"stage": "execution", "error_type": error_type.__name__}])


if __name__ == "__main__":
    unittest.main()
