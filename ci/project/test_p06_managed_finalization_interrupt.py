# SPDX-License-Identifier: Apache-2.0
"""Bounded managed checkpoint and finalization interruption controls."""

import copy
import json
from pathlib import Path
import unittest
from unittest import mock

import p06_managed_preflight_execute as runner
from test_p06_managed_preflight_runner import ManagedHarness


class ManagedFinalizationInterruptTests(unittest.TestCase):
    def run_interrupted(self, fixture):
        try:
            return fixture.run()
        except KeyboardInterrupt:
            path = fixture.paths["output"] / "report.json"
            saved = json.loads(path.read_text()) if path.is_file() else {}
            self.fail("interruption escaped managed finalization: " + repr({
                key: saved.get(key) for key in ("state", "native_execution", "failures")}))

    def assert_failed_report(self, fixture, result, *, stage, native):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], "fail" if native else "blocked")
        self.assertEqual(result["native_execution"], "run" if native else "not_run")
        self.assertEqual(result["failures"][0]["stage"], stage)
        self.assertEqual(result["failures"][0]["reason"], "interrupted")
        self.assertEqual(result["reason"], "interrupted")
        for name in ("native_preflight_passed", *runner.manifest.FALSE_CLAIMS):
            self.assertIs(result[name], False, name)
        expected = runner.COMPLETE_COUNTS if native else dict.fromkeys(runner.COMPLETE_COUNTS, 0)
        self.assertEqual(result["completed_counts"], expected)
        planned = [row["id"] for row in runner.manifest.process_plan()] if native else []
        self.assertEqual(fixture.launches(), planned)
        self.assertEqual(len(fixture.calls), len(result["commands"]))
        self.assertEqual(len({call["id"] for call in fixture.calls}), len(fixture.calls))
        self.assertTrue(all(row["outcome"] == "pass" for row in result["processes"]))
        self.assertEqual(result["unresolved_obligations"], list(runner.manifest.UNRESOLVED_OBLIGATIONS))

    def test_initial_checkpoint_interrupt_before_or_after_write_finishes_without_commands(self):
        for persist_first in (False, True):
            with self.subTest(persist_first=persist_first), ManagedHarness() as fixture:
                write_json = runner.base._write_json
                interrupted = []

                def write(path, value):
                    if (Path(path) == fixture.paths["output"] / "report.json"
                            and not interrupted and value["state"] == "running"
                            and not value["commands"]):
                        interrupted.append(copy.deepcopy(value))
                        if persist_first:
                            write_json(path, value)
                        raise KeyboardInterrupt()
                    return write_json(path, value)

                with mock.patch.object(runner.base, "_write_json", side_effect=write):
                    result = self.run_interrupted(fixture)
                self.assert_failed_report(fixture, result, stage="execution", native=False)
                self.assertEqual(len(interrupted), 1)
                self.assertEqual(result["commands"], [])
                self.assertEqual(result["raw_logs"], [])
                self.assertEqual(fixture.resource_count, 1)
                self.assertEqual(result["resources_after"], fixture.resources)
                self.assertFalse(fixture.paths["work"].exists())

    def test_resource_interrupt_before_first_native_remains_not_run(self):
        with ManagedHarness() as fixture:
            def resources(count, value):
                if count == 1:
                    raise KeyboardInterrupt()
                return value

            fixture.mutate_resources = resources
            result = self.run_interrupted(fixture)
            self.assert_failed_report(fixture, result, stage="execution", native=False)
            self.assertEqual(result["commands"], [])
            self.assertEqual(result["resources_after"], fixture.resources)
            self.assertEqual(fixture.resource_count, 2)

    def test_final_resource_interrupt_preserves_completed_native_observations(self):
        with ManagedHarness() as fixture:
            def resources(count, value):
                if count == 2:
                    raise KeyboardInterrupt()
                return value

            fixture.mutate_resources = resources
            result = self.run_interrupted(fixture)
            self.assert_failed_report(fixture, result, stage="final-resources", native=True)
            self.assertEqual(fixture.resource_count, 2)
            self.assertNotIn("resources_after", result)
            self.assertTrue(result["retained_files_stable"])
            self.assertEqual(len(result["raw_logs"]), len(result["commands"]))

    def test_final_source_snapshot_interrupt_continues_remaining_observations(self):
        with ManagedHarness() as fixture:
            write_json = runner.base._write_json
            interrupted = []

            def write(path, value):
                if Path(path) == fixture.paths["output"] / "snapshots/source-after.json":
                    interrupted.append(Path(path))
                    raise KeyboardInterrupt()
                return write_json(path, value)

            with mock.patch.object(runner.base, "_write_json", side_effect=write):
                result = self.run_interrupted(fixture)
            self.assert_failed_report(fixture, result, stage="final-source", native=True)
            self.assertEqual(len(interrupted), 1)
            self.assertNotIn("source_after", result)
            self.assertTrue(result["tools_stable"])
            self.assertTrue(result["dependencies_stable"])
            self.assertTrue(result["retained_files_stable"])
            self.assertEqual(result["resources_after"], fixture.resources)

    def test_final_log_interrupt_keeps_receipt_and_checks_remaining_logs(self):
        with ManagedHarness() as fixture:
            digest = runner._digest
            interrupted = []
            first_log = fixture.paths["output"] / "logs/version-gpp.log"

            def observe(path):
                if (Path(path) == first_log
                        and (fixture.paths["output"] / "snapshots/dependencies-after.json").exists()):
                    interrupted.append(Path(path))
                    raise KeyboardInterrupt()
                return digest(path)

            with mock.patch.object(runner, "_digest", side_effect=observe):
                result = self.run_interrupted(fixture)
            self.assert_failed_report(fixture, result, stage="final-log-verification", native=True)
            self.assertEqual(len(interrupted), 1)
            first = result["commands"][0]
            self.assertEqual(first["id"], "version-gpp")
            self.assertEqual((first["log_sha256"], first["log_size_bytes"]), digest(first_log))
            self.assertIs(first["process_started"], True)
            self.assertEqual(first["outcome"], "pass")
            self.assertEqual({row["path"] for row in result["raw_logs"]},
                             {row["log"] for row in result["commands"][1:]})
            self.assertTrue(result["retained_files_stable"])
            self.assertEqual(result["resources_after"], fixture.resources)

    def test_final_retained_identity_interrupt_does_not_claim_stability(self):
        with ManagedHarness() as fixture:
            hash_artifacts = runner.hash_artifacts
            interrupted = []

            def observe(root, names):
                if Path(root) == fixture.paths["output"] and len(names) > 1:
                    interrupted.append(list(names))
                    raise KeyboardInterrupt()
                return hash_artifacts(root, names)

            with mock.patch.object(runner, "hash_artifacts", side_effect=observe):
                result = self.run_interrupted(fixture)
            self.assert_failed_report(fixture, result, stage="final-retained-evidence", native=True)
            self.assertEqual(len(interrupted), 1)
            self.assertIsNot(result.get("retained_files_stable"), True)
            self.assertEqual(interrupted[0], [row["path"] for row in result["retained_files"]])
            self.assertEqual(result["resources_after"], fixture.resources)

    def test_final_persistence_interrupt_propagates_without_retry_or_finished_claim(self):
        with ManagedHarness() as fixture:
            fixture.resources["available_memory_bytes"] = 0
            write_json = runner.base._write_json
            attempted = []

            def write(path, value):
                if (Path(path) == fixture.paths["output"] / "report.json"
                        and value["state"] == "finished"):
                    attempted.append(copy.deepcopy(value))
                    raise KeyboardInterrupt()
                return write_json(path, value)

            with mock.patch.object(runner.base, "_write_json", side_effect=write):
                with self.assertRaises(KeyboardInterrupt):
                    fixture.run()
            self.assertEqual(len(attempted), 1)
            self.assertEqual(fixture.calls, [])
            self.assertEqual(fixture.resource_count, 2)
            self.assertEqual(attempted[0]["state"], "finished")
            self.assertIs(attempted[0]["native_preflight_passed"], False)
            saved = json.loads((fixture.paths["output"] / "report.json").read_text())
            self.assertEqual(saved["state"], "running")
            self.assertEqual(saved["native_execution"], "not_run")
            self.assertIs(saved["native_preflight_passed"], False)

    def test_system_exit_during_finalization_still_propagates(self):
        with ManagedHarness() as fixture:
            fixture.resources["available_memory_bytes"] = 0

            def resources(count, value):
                if count == 2:
                    raise SystemExit(143)
                return value

            fixture.mutate_resources = resources
            with self.assertRaises(SystemExit) as caught:
                fixture.run()
            self.assertEqual(caught.exception.code, 143)
            self.assertEqual(fixture.resource_count, 2)
            self.assertEqual(fixture.calls, [])


if __name__ == "__main__":
    unittest.main()
