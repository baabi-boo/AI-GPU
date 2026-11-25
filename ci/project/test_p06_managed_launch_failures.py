# SPDX-License-Identifier: Apache-2.0
"""Bounded host faults at managed-command launch checkpoints."""

import copy
from pathlib import Path
import unittest
from unittest import mock

import p06_managed_preflight_execute as runner
from test_p06_managed_preflight_runner import FIRST, SECOND, ManagedHarness


class ManagedLaunchFailureTests(unittest.TestCase):
    def fail_checkpoint(self, fixture, name, error, *, started=None, persist_first=False):
        write_json = runner.base._write_json
        failed = []

        def write(path, value):
            commands = value.get("commands", []) if isinstance(value, dict) else []
            if (Path(path) == fixture.paths["output"] / "report.json" and not failed
                    and commands and commands[-1]["id"] == name
                    and commands[-1].get("process_started") is started):
                failed.append(copy.deepcopy(value))
                if persist_first:
                    write_json(path, value)
                raise error
            return write_json(path, value)

        fixture.stack.enter_context(mock.patch.object(runner.base, "_write_json", side_effect=write))
        return failed

    def assert_failed_report(self, fixture, result):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertIn(result["outcome"], ("blocked", "fail"))
        self.assertTrue(result["failures"])
        self.assertTrue(result["retained_files_stable"])
        for name in ("native_preflight_passed", *runner.manifest.FALSE_CLAIMS):
            self.assertIs(result[name], False, name)
        self.assertEqual(result["unresolved_obligations"], list(runner.manifest.UNRESOLVED_OBLIGATIONS))

    def test_checkpoint_failure_before_first_command_records_nonstart(self):
        with ManagedHarness() as fixture:
            name = "version-gpp"
            failed = self.fail_checkpoint(fixture, name, OSError("checkpoint unavailable"))
            result = fixture.run()
            self.assert_failed_report(fixture, result)
            self.assertEqual(len(failed), 1)
            self.assertEqual(fixture.calls, [])
            self.assertEqual(result["native_execution"], "not_run")
            self.assertEqual(result["outcome"], "blocked")
            row = result["commands"][-1]
            self.assertEqual(row["id"], name)
            self.assertIs(row["process_started"], False)
            self.assertEqual(row["outcome"], "blocked")
            self.assertIs(row["cleanup_complete"], True)
            self.assertEqual(result["raw_logs"], [])

    def test_checkpoint_failure_before_first_native_process_records_not_run(self):
        for error in (OSError("checkpoint unavailable"), ValueError("checkpoint invalid"),
                      RuntimeError("checkpoint stopped"), KeyError("checkpoint key"),
                      TypeError("checkpoint type"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), ManagedHarness() as fixture:
                failed = self.fail_checkpoint(fixture, FIRST, error)
                result = fixture.run()
                self.assert_failed_report(fixture, result)
                self.assertEqual(len(failed), 1)
                self.assertEqual(fixture.launches(), [])
                self.assertEqual(result["native_execution"], "not_run")
                self.assertEqual(result["completed_counts"]["processes"], 0)
                row = result["commands"][-1]
                self.assertEqual(row["id"], FIRST)
                self.assertIs(row["process_started"], False)
                self.assertEqual(row["outcome"], "blocked")
                self.assertIs(row["cleanup_complete"], True)
                self.assertNotIn("log_sha256", row)
                self.assertNotIn(row["log"], {item["path"] for item in result["raw_logs"]})

    def test_checkpoint_failure_after_prior_native_process_preserves_partial_results(self):
        for persist_first in (False, True):
            with self.subTest(persist_first=persist_first), ManagedHarness() as fixture:
                failed = self.fail_checkpoint(fixture, SECOND, OSError("checkpoint unavailable"),
                                              persist_first=persist_first)
                result = fixture.run()
                self.assert_failed_report(fixture, result)
                self.assertEqual(len(failed), 1)
                self.assertEqual(fixture.launches(), [FIRST])
                self.assertEqual(result["native_execution"], "run")
                self.assertEqual(result["completed_counts"]["processes"], 1)
                self.assertEqual(result["completed_counts"]["launches"], 33)
                row = result["commands"][-1]
                self.assertEqual(row["id"], SECOND)
                self.assertIs(row["process_started"], False)
                self.assertEqual(row["outcome"], "blocked")
                self.assertIs(row["cleanup_complete"], True)
                logs = {item["path"] for item in result["raw_logs"]}
                self.assertIn("logs/" + FIRST + ".log", logs)
                self.assertNotIn(row["log"], logs)

    def test_monitor_exception_remains_unknown_and_retains_partial_log(self):
        with ManagedHarness() as fixture:
            fixture.exceptions[FIRST] = OSError("monitor receipt lost")
            result = fixture.run()
            self.assert_failed_report(fixture, result)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(result["native_execution"], "unknown")
            self.assertEqual(result["completed_counts"]["processes"], 0)
            row = result["commands"][-1]
            self.assertIsNone(row["process_started"])
            self.assertEqual(row["outcome"], "fail")
            self.assertIn(row["log"], {item["path"] for item in result["raw_logs"]})

    def test_confirmed_start_survives_following_checkpoint_failure(self):
        with ManagedHarness() as fixture:
            failed = self.fail_checkpoint(fixture, FIRST, OSError("receipt checkpoint unavailable"),
                                          started=True)
            result = fixture.run()
            self.assert_failed_report(fixture, result)
            self.assertEqual(len(failed), 1)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(result["native_execution"], "run")
            self.assertEqual(result["completed_counts"]["processes"], 0)
            row = result["commands"][-1]
            self.assertIs(row["process_started"], True)
            self.assertIn(row["log"], {item["path"] for item in result["raw_logs"]})


if __name__ == "__main__":
    unittest.main()
