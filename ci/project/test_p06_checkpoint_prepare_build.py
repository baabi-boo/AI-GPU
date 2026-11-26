# SPDX-License-Identifier: Apache-2.0
"""Real checkpoint fsync faults with synthetic preparation and build observations."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
import unittest
from unittest import mock

import p02_matrix as base
import p06_dependency_build as build
import p06_dependency_contract as contract
import p06_qualified_warm_hosted as hosted
import test_p06_builder_initial_closeout as builder_fixtures
import test_p06_preparation_initial_closeout as preparation_fixtures


@contextmanager
def _fixture(case_type):
    case = case_type()
    try:
        case.setUp()
        yield case
    finally:
        case.doCleanups()


@contextmanager
def _interrupt_fsync(target, checkpoint, error):
    temporary = target.with_name(target.name + ".tmp")
    write_json, fsync = base._write_json, base.os.fsync
    observed = {"writes": [], "failures": [], "injected": []}

    def published():
        return target.read_bytes() if target.exists() else None

    def fail_fsync(descriptor):
        if len(observed["writes"]) == checkpoint and not observed["injected"]:
            opened, pending = os.fstat(descriptor), temporary.lstat()
            if (opened.st_dev, opened.st_ino) == (pending.st_dev, pending.st_ino):
                observed["injected"].append(json.loads(temporary.read_bytes()))
                raise error
        return fsync(descriptor)

    def observe_write(path, document):
        if path != target:
            return write_json(path, document)
        before = published()
        observed["writes"].append({"document": deepcopy(document), "before": before})
        try:
            return write_json(path, document)
        except BaseException as caught:
            observed["failures"].append({"error": caught, "before": before,
                "after": published(), "temporary_remains": os.path.lexists(temporary)})
            raise

    with mock.patch.object(base, "_write_json", side_effect=observe_write), \
            mock.patch.object(base.os, "fsync", side_effect=fail_fsync):
        yield observed


class CheckpointPreparationBuildTests(unittest.TestCase):
    def assert_recovered(self, target, checkpoint, error, observed, report):
        self.assertEqual(len(observed["writes"]), checkpoint + 1)
        self.assertEqual(observed["injected"], [observed["writes"][checkpoint - 1]["document"]])
        self.assertEqual(len(observed["failures"]), 1)
        failure = observed["failures"][0]
        self.assertIs(failure["error"], error)
        self.assertEqual(failure["after"], failure["before"])
        self.assertFalse(failure["temporary_remains"])
        if checkpoint == 1:
            self.assertIsNone(failure["before"])
        else:
            self.assertEqual(json.loads(failure["before"]),
                             observed["writes"][checkpoint - 2]["document"])
        self.assertEqual(observed["writes"][-1], {"document": report, "before": failure["before"]})
        self.assertEqual(json.loads(target.read_bytes()), report)
        self.assertFalse(os.path.lexists(target.with_name(target.name + ".tmp")))
        self.assertEqual(report["reason"], str(error) or "interrupted")
        self.assertNotEqual(report["outcome"], "pass")
        self.assertEqual(report["budget"], contract.BUDGET)
        for name in contract.FALSE_CLAIMS:
            self.assertIs(report[name], False, name)

    def assert_preparation_recovery(self, checkpoint):
        for error in (OSError("preparation checkpoint fsync unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), \
                    _fixture(preparation_fixtures.PreparationInitialCloseoutTests) as fixture:
                case = fixture.case
                target = case.workspace / "evidence/dependency-preparation.json"
                with _interrupt_fsync(target, checkpoint, error) as observed:
                    report = case.run_prepare()

                self.assert_recovered(target, checkpoint, error, observed, report)
                self.assertEqual(report["failures"], [{
                    "stage": "local-preparation", "reason": str(error) or "interrupted"}])
                self.assertEqual(report["native_execution"], "not_run")
                self.assertIsNone(report["source_after"])
                self.assertIsNone(report["resources_after"])
                for name in ("dependency_cache_used", "toolchain_cache_used", "network_acquisition"):
                    self.assertIs(report[name], False, name)
                if checkpoint == 1:
                    self.assertEqual(report["outcome"], "blocked")
                    self.assertIsNone(report["source_before"])
                    self.assertIsNone(report["toolchain_receipt"])
                    self.assertEqual(report["host_tools"], {})
                    self.assertEqual(report["repositories"], {})
                    for name in ("source", "resources", "objects", "tools", "git", "provision"):
                        case.mocks[name].assert_not_called()
                    self.assertEqual(case.calls, [])
                    self.assertFalse((case.workspace / "tools").exists())
                else:
                    self.assertEqual(report["outcome"], "fail")
                    self.assertEqual(report["toolchain_receipt"], case.fixture["toolchain_receipt"])
                    self.assertEqual(report["source_before"], case.fixture["source_before"])
                    self.assertEqual(report["source_manifest"], case.fixture["source_manifest"])
                    self.assertEqual(report["host_tools"], case.fixture["host_tools"])
                    for name in ("source", "resources", "objects", "tools", "provision"):
                        self.assertEqual(case.mocks[name].call_count, 1, name)
                    self.assertEqual(case.mocks["git"].call_count, 6)
                    self.assertEqual(case.calls, [(case.archives, case.workspace / "tools")])
                    self.assertTrue((case.workspace / "tools").is_dir())
                    previous = json.loads(observed["failures"][0]["before"])
                    self.assertIsNone(previous["toolchain_receipt"])
                    self.assertEqual(previous["outcome"], "blocked")

    def test_initial_preparation_fsync_fault_retains_nonstart(self):
        self.assert_preparation_recovery(1)

    def test_post_provisioning_fsync_fault_retains_one_attempt(self):
        self.assert_preparation_recovery(3)

    def assert_builder_recovery(self, checkpoint):
        for error in (OSError("builder checkpoint fsync unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), \
                    _fixture(builder_fixtures.BuilderInitialCloseoutTests) as case:
                producer = build.Builder(case.args)
                command_result = {"process_started": True, "cleanup_complete": True,
                                  "outcome": "pass", "exit_code": 0, "reason": None}
                log_body = b"synthetic dependency command; no native execution\n"

                def launch(arguments, cwd, environment, log, **limits):
                    log.write_bytes(log_body)
                    return dict(command_result)

                def collect_source(source):
                    return producer.command("synthetic-build", ["synthetic-host-tool"], producer.workspace)

                self.assertFalse(hosted.writers_finished(case.attempt, case.supervisor))
                with mock.patch.object(build, "collect_source", side_effect=collect_source) as checkout, \
                        mock.patch.object(build, "tool_inventory") as tools, \
                        mock.patch.object(build.sources, "materialize_sources") as sources, \
                        mock.patch.object(build, "run_bounded", side_effect=launch) as command, \
                        _interrupt_fsync(case.target, checkpoint, error) as observed:
                    report = producer.execute()

                self.assert_recovered(case.target, checkpoint, error, observed, report)
                self.assertEqual(report["state"], "finished")
                self.assertEqual(report["failures"], [{
                    "stage": "execution", "reason": str(error) or "interrupted"}])
                self.assertIs(report["fresh_dependency_build_passed"], False)
                self.assertEqual(command.call_count, int(checkpoint == 3))
                self.assertEqual(checkout.call_count, int(checkpoint != 1))
                tools.assert_not_called()
                sources.assert_not_called()
                self.assertTrue(hosted.writers_finished(case.attempt, case.supervisor))
                self.assertEqual(hosted.observed_native_execution(case.attempt, case.revision), "not_run")
                self.assertFalse(producer.build_root.exists())
                self.assertFalse(producer.source_root.exists())
                if checkpoint == 1:
                    case.assert_nonstart(report, str(error) or "interrupted")
                else:
                    self.assertEqual(len(report["commands"]), 1)
                    row = report["commands"][0]
                    self.assertEqual(row["id"], "synthetic-build")
                    self.assertIs(row["cleanup_complete"], True)
                    if checkpoint == 2:
                        self.assertEqual(report["outcome"], "blocked")
                        self.assertIs(row["process_started"], False)
                        self.assertEqual(row["outcome"], "blocked")
                        self.assertEqual(row["reason"], str(error) or "interrupted")
                        self.assertNotIn("exit_code", row)
                        self.assertFalse((producer.output / row["log"]).exists())
                        self.assertEqual(report["retained_files"], [])
                    else:
                        self.assertEqual(report["outcome"], "fail")
                        self.assertEqual({name: row[name] for name in command_result}, command_result)
                        self.assertEqual((producer.output / row["log"]).read_bytes(), log_body)
                        self.assertEqual([item["path"] for item in report["retained_files"]], [row["log"]])
                        previous = json.loads(observed["failures"][0]["before"])
                        self.assertIsNone(previous["commands"][0]["process_started"])

    def test_initial_builder_fsync_fault_retains_nonstart(self):
        self.assert_builder_recovery(1)

    def test_builder_prelaunch_fsync_fault_prevents_command(self):
        self.assert_builder_recovery(2)

    def test_builder_post_command_fsync_fault_preserves_result(self):
        self.assert_builder_recovery(3)


if __name__ == "__main__":
    unittest.main()
