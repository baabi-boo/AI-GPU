# SPDX-License-Identifier: Apache-2.0
"""Independent launch-boundary controls with local failed children; no native work."""

from contextlib import contextmanager
import hashlib
import sys
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_run as runner
import test_p06_qualified_warm_run as fixtures


class QualifiedWarmPrelaunchReviewTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        fixture = fixtures.QualifiedWarmRunTests()
        fixture.setUp()
        fixture.workspace = fixture.root / "workspace"
        fixture.args.workspace_dir = fixture.workspace
        fixture.paths["workspace"] = str(fixture.workspace)

        def child_commands(name, document, argv):
            if name == "dependency-build":
                document["commands"] = []
            return 0

        fixture.change = child_commands
        try:
            yield fixture
        finally:
            fixture.doCleanups()

    def writers_finished(self, fixture):
        return hosted.writers_finished(fixture.root, [{"id": "native-supervisor",
            "process_started": True, "cleanup_complete": True}])

    def test_unstarted_warm_stage_allows_closeout_without_fabricated_child_files(self):
        with self.fixture() as fixture:
            original_write = runner.base._write_json
            failures = []

            def checkpoint(path, report):
                rows = report.get("stages", [])
                if rows and rows[-1]["id"] == "qualified-warm" and not failures:
                    failures.append(True)
                    raise OSError("prelaunch checkpoint unavailable")
                return original_write(path, report)

            with mock.patch.object(runner.base, "_write_json", side_effect=checkpoint):
                report = fixture.run_route()
            self.assertEqual(failures, [True])
            self.assertEqual([row["id"] for row in fixture.observed],
                             ["preparation", "dependency-build"])
            row = report["stages"][-1]
            self.assertIs(row["process_started"], False)
            self.assertIs(row["cleanup_complete"], True)
            self.assertEqual(report["native_execution"], "not_run")
            self.assertNotIn("qualified-warm", report["reports"])
            for key in ("report_path", "log"):
                self.assertFalse((fixture.workspace / "evidence" / row[key]).exists())
            self.assertTrue(self.writers_finished(fixture))

    def test_failed_child_bytes_do_not_substitute_for_a_returned_monitor_result(self):
        for boundary in ("completed", "completion-checkpoint", "monitor-return"):
            with self.subTest(boundary=boundary), self.fixture() as fixture:
                original_write = runner.base._write_json
                failures, observations = [], []
                report_bytes = (b'{"state":"finished","commands":[],"outcome":"fail",'
                                b'"native_execution":"not_run","reason":"local child failure"} \r\n')
                log_bytes = b"\xfflocal child failed\x00\r\n"

                def child(argv, cwd, environment, log, **limits):
                    if log.stem != "qualified-warm":
                        return fixture.child(argv, cwd, environment, log, **limits)
                    path = fixture.workspace / "evidence/qualified-warm/report.json"
                    code = ("import os,pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                            "p.parent.mkdir(parents=True); p.write_bytes(" + repr(report_bytes) + "); "
                            "os.write(1," + repr(log_bytes) + "); sys.exit(23)")
                    result = run_bounded([sys.executable, "-I", "-B", "-c", code, str(path)],
                                         cwd, environment, log, **limits)
                    observations.append(result)
                    if boundary == "monitor-return":
                        raise OSError("monitor return unavailable")
                    return result

                def checkpoint(path, report):
                    rows = report.get("stages", [])
                    if (boundary == "completion-checkpoint" and rows
                            and rows[-1]["id"] == "qualified-warm"
                            and rows[-1].get("exit_code") == 23 and not failures):
                        failures.append(True)
                        raise OSError("completion checkpoint unavailable")
                    return original_write(path, report)

                with mock.patch.object(runner.base, "_write_json", side_effect=checkpoint):
                    report = fixture.run_route(child)
                self.assertEqual(len(observations), 1)
                self.assertEqual(failures, [True] if boundary == "completion-checkpoint" else [])
                self.assertEqual(report["outcome"], "fail")
                self.assertFalse(report["orchestration_passed"])
                self.assertIs(observations[0]["process_started"], True)
                self.assertIs(observations[0]["cleanup_complete"], True)
                self.assertEqual(observations[0]["exit_code"], 23)
                row = report["stages"][-1]
                for data, descriptor in ((report_bytes, report["reports"]["qualified-warm"]),
                                         (log_bytes, row["raw_log"])):
                    self.assertEqual((fixture.workspace / "evidence" / descriptor["path"]).read_bytes(), data)
                    self.assertEqual(descriptor["sha256"], hashlib.sha256(data).hexdigest())
                    self.assertEqual(descriptor["size_bytes"], len(data))
                if boundary == "monitor-return":
                    self.assertIsNone(row["process_started"])
                    self.assertIsNone(row.get("cleanup_complete"))
                    self.assertFalse(self.writers_finished(fixture))
                else:
                    for key, value in observations[0].items():
                        self.assertEqual(row[key], value)
                    self.assertTrue(self.writers_finished(fixture))


if __name__ == "__main__":
    unittest.main()
