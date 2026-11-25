# SPDX-License-Identifier: Apache-2.0
"""Conservative managed failure states for uncertain monitor receipts."""

import unittest
from unittest import mock

import p06_managed_preflight_execute as runner
from test_p06_managed_preflight_runner import ManagedHarness


FIRST_COMMAND = "version-gpp"


class ManagedFailureStateTests(unittest.TestCase):
    def assert_failed_report(self, fixture, result, outcome):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], outcome)
        self.assertTrue(result["failures"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertFalse(any(result["completed_counts"].values()))
        self.assertEqual(fixture.launches(), [])
        for name in ("native_preflight_passed", *runner.manifest.FALSE_CLAIMS):
            self.assertIs(result[name], False, name)
        self.assertEqual(result["unresolved_obligations"], list(runner.manifest.UNRESOLVED_OBLIGATIONS))

    def test_failure_without_commands_remains_blocked(self):
        with ManagedHarness() as fixture:
            fixture.resources["available_memory_bytes"] = 0
            result = fixture.run()
            self.assert_failed_report(fixture, result, "blocked")
            self.assertEqual(result["commands"], [])
            self.assertEqual(fixture.calls, [])
            self.assertEqual(result["raw_logs"], [])

    def test_confirmed_nonstart_remains_blocked(self):
        with ManagedHarness() as fixture:
            receipt = {"outcome": "blocked", "exit_code": None, "reason": "launch_failed",
                       "process_started": False, "cleanup_complete": True,
                       "log_sha256": None, "log_size_bytes": 0}
            with mock.patch.object(runner, "run_bounded", return_value=receipt) as monitor:
                result = fixture.run()
            self.assert_failed_report(fixture, result, "blocked")
            self.assertEqual(monitor.call_count, 1)
            self.assertEqual(len(result["commands"]), 1)
            self.assertIs(result["commands"][0]["process_started"], False)
            self.assertEqual(result["raw_logs"], [])

    def test_confirmed_start_with_failure_remains_fail(self):
        with ManagedHarness() as fixture:
            fixture.results[FIRST_COMMAND] = {"outcome": "fail", "exit_code": 1,
                                              "reason": "nonzero_exit"}
            result = fixture.run()
            self.assert_failed_report(fixture, result, "fail")
            self.assertEqual(len(result["commands"]), 1)
            row = result["commands"][0]
            self.assertIs(row["process_started"], True)
            self.assertEqual(result["raw_logs"][0]["path"], row["log"])

    def test_first_monitor_exception_is_fail_with_unresolved_start(self):
        for error in (OSError("monitor receipt lost"), RuntimeError("monitor stopped"),
                      KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), ManagedHarness() as fixture:
                fixture.exceptions[FIRST_COMMAND] = error
                result = fixture.run()
                self.assert_failed_report(fixture, result, "fail")
                self.assertEqual([call["id"] for call in fixture.calls], [FIRST_COMMAND])
                row = result["commands"][0]
                self.assertIsNone(row["process_started"])
                self.assertEqual(row["outcome"], "fail")
                self.assertEqual(result["raw_logs"][0]["path"], row["log"])
                self.assertEqual(result["raw_logs"][0]["sha256"], row["log_sha256"])

    def test_missing_start_observation_is_fail(self):
        with ManagedHarness() as fixture:
            fixture.remove[FIRST_COMMAND] = ("process_started",)
            result = fixture.run()
            self.assert_failed_report(fixture, result, "fail")
            self.assertEqual(len(result["commands"]), 1)
            self.assertIsNone(result["commands"][0]["process_started"])
            self.assertIn("command failed: " + FIRST_COMMAND, result["reason"])


if __name__ == "__main__":
    unittest.main()
