# SPDX-License-Identifier: Apache-2.0
"""Dependency launch-boundary faults with local failed children; no native work."""

from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_dependency_build as build
import p06_qualified_warm_hosted as hosted


CHILD_LOG = b"\xfflocal dependency child\x00\r\n"


class DependencyLaunchFailureTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix="p06-dependency-launch-") as directory:
            attempt = Path(directory)
            workspace = attempt / "workspace"
            (workspace / "evidence").mkdir(parents=True)
            args = SimpleNamespace(source_dir=build.ROOT, workspace_dir=workspace,
                output_dir=workspace / "evidence/dependency-build", expected_revision="1" * 40)
            yield attempt, build.Builder(args)

    def writers_finished(self, attempt, producer):
        producer.report["state"] = "finished"
        producer.save()
        build.base._write_json(attempt / "workspace/evidence/qualified-warm-run.json", {
            "state": "finished", "stages": [{"id": "dependency-build",
                "report_path": "dependency-build/report.json", "process_started": True,
                "cleanup_complete": True}]})
        return hosted.writers_finished(attempt, [{"id": "native-supervisor",
            "process_started": True, "cleanup_complete": True}])

    def command(self, producer):
        code = "import os,sys; os.write(1," + repr(CHILD_LOG) + "); sys.exit(23)"
        return producer.command("local-child", [sys.executable, "-I", "-B", "-c", code],
                                producer.workspace, timeout=5)

    def local_child(self, argv, cwd, environment, log, **limits):
        return run_bounded(argv, cwd, environment, log, **dict(limits, min_free_bytes=1))

    def test_prelaunch_checkpoint_failure_allows_closeout_without_a_child(self):
        for error in (OSError("prelaunch checkpoint unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), self.fixture() as (attempt, producer):
                with mock.patch.object(producer, "save", side_effect=error), \
                        mock.patch.object(build, "run_bounded") as launch:
                    with self.assertRaises(type(error)) as raised:
                        self.command(producer)
                self.assertIs(raised.exception, error)
                launch.assert_not_called()
                row = producer.report["commands"][0]
                self.assertIs(row["process_started"], False)
                self.assertIs(row["cleanup_complete"], True)
                self.assertEqual(row["outcome"], "blocked")
                self.assertEqual(row["reason"], str(error) or "interrupted")
                self.assertFalse((producer.output / row["log"]).exists())
                self.assertTrue(self.writers_finished(attempt, producer))

    def test_completion_checkpoint_failure_preserves_returned_child_result(self):
        for error in (OSError("completion checkpoint unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), self.fixture() as (attempt, producer):
                original_save = producer.save
                observations = []

                def child(*args, **kwargs):
                    result = self.local_child(*args, **kwargs)
                    observations.append(result)
                    return result

                def checkpoint():
                    if observations:
                        raise error
                    original_save()

                with mock.patch.object(producer, "save", side_effect=checkpoint), \
                        mock.patch.object(build, "run_bounded", side_effect=child) as launch:
                    with self.assertRaises(type(error)) as raised:
                        self.command(producer)
                self.assertIs(raised.exception, error)
                launch.assert_called_once()
                self.assertEqual(len(observations), 1)
                self.assertIs(observations[0]["process_started"], True)
                self.assertIs(observations[0]["cleanup_complete"], True)
                self.assertEqual(observations[0]["exit_code"], 23)
                row = producer.report["commands"][0]
                for key, value in observations[0].items():
                    self.assertEqual(row[key], value)
                self.assertEqual((producer.output / row["log"]).read_bytes(), CHILD_LOG)
                self.assertTrue(self.writers_finished(attempt, producer))

    def test_launcher_exception_cannot_claim_no_child_or_completed_cleanup(self):
        for error in (OSError("monitor return unavailable"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), self.fixture() as (attempt, producer):
                observations = []

                def child(*args, **kwargs):
                    observations.append(self.local_child(*args, **kwargs))
                    raise error

                with mock.patch.object(build, "run_bounded", side_effect=child) as launch:
                    with self.assertRaises(type(error)) as raised:
                        self.command(producer)
                self.assertIs(raised.exception, error)
                launch.assert_called_once()
                self.assertEqual(len(observations), 1)
                self.assertIs(observations[0]["process_started"], True)
                self.assertIs(observations[0]["cleanup_complete"], True)
                self.assertEqual(observations[0]["exit_code"], 23)
                row = producer.report["commands"][0]
                self.assertIsNone(row["process_started"])
                self.assertIsNone(row.get("cleanup_complete"))
                self.assertIsNone(row.get("exit_code"))
                self.assertEqual((producer.output / row["log"]).read_bytes(), CHILD_LOG)
                self.assertFalse(self.writers_finished(attempt, producer))


if __name__ == "__main__":
    unittest.main()
