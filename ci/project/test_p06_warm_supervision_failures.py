# SPDX-License-Identifier: Apache-2.0
"""Controlled checkpoint failures with original stage files; no native execution."""

import unittest
from unittest import mock

import p06_qualified_warm_run as runner
import test_p06_qualified_warm_run as fixtures


class QualifiedWarmSupervisionFailureTests(unittest.TestCase):
    def test_prelaunch_checkpoint_failure_records_known_unstarted_stage(self):
        for index, stage in enumerate(runner.STAGE_NAMES):
            for error_type in (OSError, KeyboardInterrupt):
                with self.subTest(stage=stage, error=error_type.__name__):
                    fixture = fixtures.QualifiedWarmRunTests()
                    fixture.setUp()
                    try:
                        original_write = runner.base._write_json
                        failures = []
                        reason = "one-time prelaunch checkpoint failure"

                        def checkpoint(path, report):
                            stages = report.get("stages", [])
                            if (stages and stages[-1]["id"] == stage
                                    and stages[-1]["finished_at"] is None and not failures):
                                failures.append(stage)
                                raise error_type(reason)
                            return original_write(path, report)

                        with mock.patch.object(runner.base, "_write_json", side_effect=checkpoint):
                            report = fixture.run_route()
                        self.assertEqual(failures, [stage])
                        self.assertEqual([row["id"] for row in fixture.observed],
                                         list(runner.STAGE_NAMES[:index]))
                        self.assertEqual(report["outcome"], "blocked" if index == 0 else "fail")
                        self.assertEqual(report["reason"], reason)
                        self.assertEqual(report["native_execution"], "not_run")
                        self.assertFalse(report["orchestration_passed"])
                        row = report["stages"][-1]
                        self.assertIs(row["process_started"], False)
                        self.assertIs(row["cleanup_complete"], True)
                        self.assertIsNotNone(row["finished_at"])
                        self.assertEqual(row["outcome"], "blocked")
                        self.assertEqual(row["reason"], reason)
                        self.assertNotIn(stage, report["reports"])
                        self.assertFalse((fixture.workspace / "evidence" / row["report_path"]).exists())
                        self.assertFalse((fixture.workspace / "evidence" / row["log"]).exists())
                    finally:
                        fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
