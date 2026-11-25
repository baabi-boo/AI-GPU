# SPDX-License-Identifier: Apache-2.0
"""Failure dispositions from finished hosted supervisor receipts remain observable."""

from contextlib import contextmanager
import json
from pathlib import Path
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import test_p06_qualified_warm_hosted as fixtures


@contextmanager
def _composition():
    case = fixtures.HostedCompositionTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def _failed_supervisor(case, disposition, *, change=None, monitor_error=False):
    case.failures.add("p06_qualified_warm_run")

    def command(argv, *args, **kwargs):
        result = case.command(argv, *args, **kwargs)
        if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_run":
            path = case.attempt / "workspace/evidence/qualified-warm-run.json"
            report = json.loads(path.read_text())
            report.update(contract_id=hosted.runner.CONTRACT_ID, native_execution=disposition)
            if change is not None:
                report.update(change)
            case.write(path, report)
            if monitor_error:
                raise RuntimeError("monitor lost after launch")
        return result

    return command


class HostedOperationalFailureTests(unittest.TestCase):
    def test_finished_failure_preserves_observed_disposition_in_encrypted_selection(self):
        for disposition in ("not_run", "run", "unknown"):
            with self.subTest(disposition=disposition), _composition() as case:
                with mock.patch.object(hosted, "run_bounded", side_effect=_failed_supervisor(case, disposition)):
                    result = case.execute()
                self.assertEqual(result["native_execution"], disposition)
                self.assertEqual(result["outcome"], "fail")
                self.assertFalse(result["orchestration_passed"])
                self.assertFalse(result["qualified_warm_passed"])
                self.assertTrue(result["writers_finished_observed"])
                self.assertTrue(result["packaging_passed"])
                self.assertTrue(result["encryption_passed"])
                for relative in ("hosted/attempt-before-closeout.json", "retention/hosted-closeout.json"):
                    self.assertEqual(json.loads((case.attempt / relative).read_text())["native_execution"],
                                     disposition)

    def test_untrusted_or_nonterminal_failure_disposition_stays_unknown(self):
        changes = ({"state": "running"}, {"expected_revision": "b" * 40},
                   {"contract_id": "other"}, {"native_execution": True},
                   {"native_execution": "not-started"})
        for change in changes:
            with self.subTest(change=change), _composition() as case:
                with mock.patch.object(hosted, "run_bounded", side_effect=_failed_supervisor(
                        case, "not_run", change=change)):
                    result = case.execute()
                self.assertEqual(result["native_execution"], "unknown")
                self.assertEqual(result["outcome"], "fail")
                self.assertFalse(result["orchestration_passed"])

    def test_unobserved_launch_cannot_borrow_a_finished_failure_disposition(self):
        with _composition() as case:
            with mock.patch.object(hosted, "run_bounded", side_effect=_failed_supervisor(
                    case, "not_run", monitor_error=True)):
                result = case.execute()
            self.assertEqual(result["native_execution"], "unknown")
            self.assertFalse(result["writers_finished_observed"])
            self.assertFalse(result["packaging_passed"])
            self.assertFalse(result["encryption_passed"])

    def test_unresolved_nested_writer_cannot_borrow_a_finished_failure_disposition(self):
        unresolved = {"stages": [{"id": "qualified-warm", "process_started": None,
                                  "cleanup_complete": False, "report_path": "qualified-warm/report.json"}]}
        with _composition() as case:
            with mock.patch.object(hosted, "run_bounded", side_effect=_failed_supervisor(
                    case, "not_run", change=unresolved)):
                result = case.execute()
            self.assertEqual(result["native_execution"], "unknown")
            self.assertFalse(result["writers_finished_observed"])
            self.assertFalse(result["encryption_passed"])

    def test_observed_nested_prelaunch_failure_remains_not_run(self):
        blocked = {"stages": [{"id": "preparation", "process_started": False,
                              "cleanup_complete": True, "report_path": "dependency-preparation.json"}]}
        with _composition() as case:
            with mock.patch.object(hosted, "run_bounded", side_effect=_failed_supervisor(
                    case, "not_run", change=blocked)):
                result = case.execute()
            self.assertEqual(result["native_execution"], "not_run")
            self.assertEqual(result["outcome"], "fail")
            self.assertTrue(result["writers_finished_observed"])
            self.assertTrue(result["encryption_passed"])
            self.assertFalse((case.attempt / "workspace/evidence/dependency-preparation.json").exists())

    def test_source_drift_cannot_authorize_failure_disposition_or_delivery(self):
        with _composition() as case:
            command = _failed_supervisor(case, "run")

            def changed(argv, *args, **kwargs):
                result = command(argv, *args, **kwargs)
                if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_run":
                    (case.source / "ci/project/p06_qualified_warm_encrypt.py").write_bytes(b"changed source")
                return result

            with mock.patch.object(hosted, "run_bounded", side_effect=changed):
                result = case.execute()
            self.assertEqual(result["native_execution"], "unknown")
            self.assertFalse(result["selected_sources_stable"])
            self.assertFalse(result["packaging_passed"])
            self.assertFalse(result["encryption_passed"])


if __name__ == "__main__":
    unittest.main()
