# SPDX-License-Identifier: Apache-2.0
"""Conservative dependency failure outcomes; local Python children only."""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_dependency_build as build
import p06_dependency_contract as contract


CHILD_LOG = b"\xffdependency disposition probe\x00\r\n"


class DependencyFailureStateTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix="p06-dependency-failure-") as directory:
            workspace = Path(directory)
            args = SimpleNamespace(source_dir=build.ROOT, workspace_dir=workspace,
                output_dir=workspace / "evidence", expected_revision="1" * 40)
            yield build.Builder(args)

    def assert_failure(self, producer, outcome, reason):
        self.assertEqual(producer.report["outcome"], outcome)
        self.assertEqual(producer.report["reason"], reason)
        self.assertIs(producer.report["fresh_dependency_build_passed"], False)
        self.assertTrue(all(producer.report[name] is False for name in contract.FALSE_CLAIMS))

    def test_empty_or_explicitly_unstarted_commands_remain_blocked(self):
        for commands in ([], [{"process_started": False}],
                         [{"process_started": False}, {"process_started": False}]):
            with self.subTest(commands=commands), self.fixture() as producer:
                producer.report["commands"] = deepcopy(commands)
                producer.report.update(outcome="pass", fresh_dependency_build_passed=True)
                producer.fail(OSError("retention unavailable"), "final-retention")
                self.assert_failure(producer, "blocked", "retention unavailable")
                self.assertEqual(producer.report["commands"], commands)
                self.assertEqual(producer.report["failures"], [{
                    "stage": "final-retention", "reason": "retention unavailable"}])

    def test_started_or_unresolved_commands_are_failures(self):
        cases = (
            [{"process_started": True}],
            [{"process_started": None}],
            [{}],
            [{"process_started": False}, {"process_started": True}],
            [{"process_started": False}, {"process_started": None}],
            [{"process_started": False}, {}, {"process_started": False}],
            [{"process_started": 0}],
        )
        for commands in cases:
            with self.subTest(commands=commands), self.fixture() as producer:
                producer.report["commands"] = deepcopy(commands)
                producer.report.update(outcome="pass", fresh_dependency_build_passed=True)
                producer.fail(KeyboardInterrupt(), "execution")
                producer.fail(OSError("later failure"), "final-retention")
                self.assert_failure(producer, "fail", "interrupted")
                self.assertEqual(producer.report["commands"], commands)
                self.assertEqual(producer.report["failures"], [
                    {"stage": "execution", "reason": "interrupted"},
                    {"stage": "final-retention", "reason": "later failure"}])

    def command(self, producer):
        code = "import os,sys; os.write(1," + repr(CHILD_LOG) + "); sys.exit(23)"
        return producer.command("local-child", [sys.executable, "-I", "-B", "-c", code],
                                producer.workspace, timeout=5)

    def assert_retained_failure(self, producer, report, outcome, reason):
        self.assertIs(report, producer.report)
        self.assertEqual(report["state"], "finished")
        self.assert_failure(producer, outcome, reason)
        self.assertEqual(json.loads((producer.output / "report.json").read_text()), report)

    def test_execute_keeps_a_failed_prelaunch_checkpoint_blocked(self):
        for error in (OSError("prelaunch checkpoint unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), self.fixture() as producer:
                original_save = producer.save
                interrupted = False

                def checkpoint():
                    nonlocal interrupted
                    if producer.report["commands"] and not interrupted:
                        interrupted = True
                        raise error
                    original_save()

                with mock.patch.object(build, "collect_source", side_effect=lambda _: self.command(producer)), \
                        mock.patch.object(producer, "save", side_effect=checkpoint), \
                        mock.patch.object(build, "run_bounded") as launch:
                    report = producer.execute()
                launch.assert_not_called()
                self.assert_retained_failure(producer, report, "blocked", str(error) or "interrupted")
                row = report["commands"][0]
                self.assertIs(row["process_started"], False)
                self.assertIs(row["cleanup_complete"], True)
                self.assertFalse((producer.output / row["log"]).exists())

    def test_execute_fails_when_a_launched_child_result_is_unavailable(self):
        for error in (OSError("monitor result unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), self.fixture() as producer:
                observations = []

                def child(*args, **limits):
                    observations.append(run_bounded(*args, **dict(limits, min_free_bytes=1)))
                    raise error

                with mock.patch.object(build, "collect_source", side_effect=lambda _: self.command(producer)), \
                        mock.patch.object(build, "run_bounded", side_effect=child) as launch:
                    report = producer.execute()
                launch.assert_called_once()
                self.assert_retained_failure(producer, report, "fail", str(error) or "interrupted")
                self.assertEqual(len(observations), 1)
                self.assertIs(observations[0]["process_started"], True)
                self.assertIs(observations[0]["cleanup_complete"], True)
                self.assertEqual(observations[0]["exit_code"], 23)
                row = report["commands"][0]
                self.assertIsNone(row["process_started"])
                self.assertNotIn("cleanup_complete", row)
                self.assertNotIn("exit_code", row)
                self.assertEqual((producer.output / row["log"]).read_bytes(), CHILD_LOG)
                self.assertIn(row["log"], [item["path"] for item in report["retained_files"]])


if __name__ == "__main__":
    unittest.main()
