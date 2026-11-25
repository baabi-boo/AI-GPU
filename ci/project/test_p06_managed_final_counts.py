# SPDX-License-Identifier: Apache-2.0
"""Final count interruptions preserve observations without repeating commands."""

import copy
import json
from pathlib import Path
import unittest
from unittest import mock

import p06_managed_preflight_execute as runner
from test_p06_managed_preflight_runner import ManagedHarness, SECOND


DERIVED_CLAIMS = (
    "native_preflight_passed", "native_lifetime_passed",
    "dependency_source_to_loaded_binary_verified", "counter_qualification_passed",
    "qualified_warm_passed",
)


class ManagedFinalCountsTests(unittest.TestCase):
    def interrupt_final_counts(self, fixture, *, repeated=False):
        original = runner.completion_counts
        attempts = []

        def count(processes):
            if fixture.resource_count >= 2:
                attempts.append({"processes": copy.deepcopy(processes),
                                 "processes_id": id(processes),
                                 "commands": copy.deepcopy(fixture.calls)})
                if len(attempts) == 1 or repeated:
                    raise KeyboardInterrupt()
            return original(processes)

        return attempts, mock.patch.object(runner, "completion_counts", side_effect=count)

    def recover(self, fixture):
        try:
            return fixture.run()
        except KeyboardInterrupt:
            saved = json.loads((fixture.paths["output"] / "report.json").read_text())
            self.fail("final count interruption escaped: " + repr({
                name: saved[name] for name in ("state", "outcome", "completed_counts")}))

    def assert_claims_false(self, report):
        for name in (*DERIVED_CLAIMS, *runner.manifest.FALSE_CLAIMS):
            if name in report:
                self.assertIs(report[name], False, name)

    def assert_recovered(self, fixture, result, attempts, expected, *, outcome="fail"):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], outcome)
        self.assertEqual(result["completed_counts"], expected)
        self.assertEqual(result["failures"][-1]["stage"], "final-completion-counts")
        self.assertEqual(result["failures"][-1]["reason"], "interrupted")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(result["processes"], attempts[0]["processes"])
        self.assertEqual(fixture.calls, attempts[0]["commands"])
        self.assertEqual([row["id"] for row in result["commands"]],
                         [row["id"] for row in fixture.calls])
        self.assertEqual(len(fixture.calls), len({row["id"] for row in fixture.calls}))
        self.assertEqual(fixture.resource_count, 2)
        self.assert_claims_false(result)
        for process in result["processes"]:
            if process["outcome"] == "pass":
                retained = fixture.paths["output"] / process["retained_observation"]["path"]
                self.assertEqual(json.loads(retained.read_text()), process["observation"])

    def test_first_final_interrupt_preserves_complete_managed_population(self):
        with ManagedHarness() as fixture:
            attempts, interrupted = self.interrupt_final_counts(fixture)
            with interrupted:
                result = self.recover(fixture)
            self.assert_recovered(fixture, result, attempts, runner.COMPLETE_COUNTS)
            self.assertEqual(result["native_execution"], "run")
            self.assertEqual(result["reason"], "interrupted")
            self.assertEqual(len(result["failures"]), 1)
            self.assertEqual(fixture.launches(), [row["id"] for row in runner.manifest.process_plan()])
            self.assertEqual(fixture.verify.call_count, 4)

    def test_first_final_interrupt_counts_only_completed_original_processes(self):
        with ManagedHarness() as fixture:
            fixture.results[SECOND] = {"outcome": "fail", "exit_code": 1,
                                       "reason": "original command failed"}
            attempts, interrupted = self.interrupt_final_counts(fixture)
            with interrupted:
                result = self.recover(fixture)
            expected = {name: 1 if name == "processes" else runner.manifest.PER_PROCESS[name]
                        for name in runner.COMPLETE_COUNTS}
            self.assert_recovered(fixture, result, attempts, expected)
            self.assertEqual([row["outcome"] for row in result["processes"]], ["pass", "fail"])
            self.assertEqual(result["reason"], result["failures"][0]["reason"])
            self.assertIn("original command failed", result["reason"])
            self.assertEqual(len(result["failures"]), 2)
            self.assertEqual(fixture.launches(), [row["id"] for row in runner.manifest.process_plan()[:2]])
            self.assertEqual(fixture.verify.call_count, 1)

    def test_first_final_interrupt_before_native_preserves_zero_counts(self):
        for command_started in (False, True):
            with self.subTest(command_started=command_started), ManagedHarness() as fixture:
                if command_started:
                    fixture.results["version-gpp"] = {"outcome": "fail", "exit_code": 1,
                                                       "reason": "original command failed"}
                else:
                    fixture.resources["available_memory_bytes"] = 0
                attempts, interrupted = self.interrupt_final_counts(fixture)
                with interrupted:
                    result = self.recover(fixture)
                self.assert_recovered(fixture, result, attempts, dict.fromkeys(runner.COMPLETE_COUNTS, 0),
                                      outcome="fail" if command_started else "blocked")
                self.assertEqual(result["native_execution"], "not_run")
                self.assertEqual(result["processes"], [])
                self.assertEqual(fixture.launches(), [])
                self.assertEqual(len(fixture.calls), int(command_started))
                self.assertEqual(result["reason"], result["failures"][0]["reason"])
                self.assertEqual(len(result["failures"]), 2)

    def test_complete_warm_counts_do_not_promote_any_derived_claim(self):
        from test_p06_qualified_warm_runner import WarmHarness, contract

        with WarmHarness() as fixture:
            attempts, interrupted = self.interrupt_final_counts(fixture)
            with interrupted:
                result = self.recover(fixture)
            self.assert_recovered(fixture, result, attempts, contract.COMPLETE_COUNTS)
            self.assertTrue(set(DERIVED_CLAIMS).issubset(result))
            self.assertEqual(result["native_execution"], "run")
            self.assertEqual(result["reason"], "interrupted")
            self.assertEqual(len(result["failures"]), 1)
            self.assertEqual(fixture.launches(), [row["id"] for row in contract.process_plan()])
            self.assertEqual(fixture.warm_verify.call_count, 24)

    def test_second_final_count_interrupt_propagates_without_further_attempts(self):
        with ManagedHarness() as fixture:
            attempts, interrupted = self.interrupt_final_counts(fixture, repeated=True)
            with interrupted, self.assertRaises(KeyboardInterrupt):
                fixture.run()
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])
            self.assertEqual(fixture.calls, attempts[0]["commands"])
            saved = json.loads((fixture.paths["output"] / "report.json").read_text())
            self.assertEqual(saved["state"], "running")
            self.assertEqual(saved["processes"], attempts[0]["processes"])
            self.assert_claims_false(saved)

    def test_final_persistence_failure_after_recovery_propagates_without_retry(self):
        for error in (KeyboardInterrupt(), OSError("final persistence unavailable")):
            with self.subTest(error=type(error).__name__), ManagedHarness() as fixture:
                fixture.resources["available_memory_bytes"] = 0
                attempts, interrupted = self.interrupt_final_counts(fixture)
                original_write = runner.base._write_json
                final_writes = []

                def write(path, value):
                    if (Path(path) == fixture.paths["output"] / "report.json"
                            and value["state"] == "finished"):
                        final_writes.append(copy.deepcopy(value))
                        raise error
                    return original_write(path, value)

                with interrupted, mock.patch.object(runner.base, "_write_json", side_effect=write):
                    with self.assertRaises((KeyboardInterrupt, OSError)) as caught:
                        fixture.run()
                self.assertIs(caught.exception, error)
                self.assertEqual(len(attempts), 2)
                self.assertEqual(len(final_writes), 1)
                self.assertEqual(final_writes[0]["failures"][-1]["stage"], "final-completion-counts")
                self.assertEqual(final_writes[0]["completed_counts"], dict.fromkeys(runner.COMPLETE_COUNTS, 0))
                self.assertEqual(final_writes[0]["outcome"], "blocked")
                self.assert_claims_false(final_writes[0])
                self.assertEqual(fixture.calls, [])
                saved = json.loads((fixture.paths["output"] / "report.json").read_text())
                self.assertEqual(saved["state"], "running")
                self.assert_claims_false(saved)


if __name__ == "__main__":
    unittest.main()
