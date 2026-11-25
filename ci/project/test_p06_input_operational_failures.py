# SPDX-License-Identifier: Apache-2.0
"""Acquisition checkpoint and failed-transfer retention; no network or native work."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import sys
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_inputs as inputs
import test_p06_qualified_warm_inputs as fixtures


class QualifiedWarmInputOperationalFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.QualifiedWarmInputAcquisitionTests.setUpClass()
        cls.addClassCleanup(fixtures.QualifiedWarmInputAcquisitionTests.doClassCleanups)

    @contextmanager
    def fixture(self):
        fixture = fixtures.QualifiedWarmInputAcquisitionTests()
        fixture.setUp()
        fixture.args.output_dir = fixture.root / "acquisition"
        try:
            yield fixture
        finally:
            fixture.doCleanups()

    def writers_finished(self, fixture):
        return hosted.writers_finished(fixture.root, [{"id": "input-acquisition",
            "process_started": True, "cleanup_complete": True}])

    def test_prelaunch_checkpoint_failure_records_known_unstarted_command(self):
        commands = (("yaml-cpp-init", 0), ("yaml-cpp-fetch", 1),
                    ("toolchain-part-01", 6), ("toolchain-part-02", 7))
        for identifier, preceding in commands:
            for error_type in (OSError, KeyboardInterrupt):
                with self.subTest(command=identifier, error=error_type.__name__), self.fixture() as fixture:
                    original_write = inputs.base._write_json
                    failures = []
                    reason = "one-time acquisition prelaunch checkpoint failure"

                    def checkpoint(path, report):
                        rows = report.get("commands", [])
                        if rows and rows[-1]["id"] == identifier and not failures:
                            failures.append(identifier)
                            raise error_type(reason)
                        return original_write(path, report)

                    with mock.patch.object(inputs.base, "_write_json", side_effect=checkpoint):
                        report = fixture.acquire()
                    self.assertEqual(failures, [identifier])
                    self.assertEqual(len(fixture.observed), preceding)
                    self.assertEqual(len(report["commands"]), preceding + 1)
                    self.assertEqual(report["outcome"], "fail")
                    self.assertEqual(report["reason"], reason)
                    row = report["commands"][-1]
                    self.assertIs(row.get("process_started"), False)
                    self.assertIs(row.get("cleanup_complete"), True)
                    self.assertEqual(row.get("outcome"), "blocked")
                    self.assertEqual(row.get("reason"), reason)
                    self.assertIsNone(row.get("exit_code"))
                    self.assertFalse((fixture.args.output_dir / row["log"]).exists())
                    self.assertTrue(self.writers_finished(fixture))

    def test_unobserved_command_exception_still_blocks_writer_closeout(self):
        with self.fixture() as fixture:
            fixture.run_mock.side_effect = KeyboardInterrupt
            report = fixture.acquire()
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual(report["reason"], "interrupted")
            self.assertEqual(fixture.run_mock.call_count, 1)
            self.assertIsNone(report["commands"][0].get("process_started"))
            self.assertFalse(self.writers_finished(fixture))

    def test_failed_transfer_preserves_raw_bytes_and_completed_process_status(self):
        for checkpoint_failure in (False, True):
            with self.subTest(checkpoint_failure=checkpoint_failure), self.fixture() as fixture:
                original_write = inputs.base._write_json
                failures = []
                partial_bytes = b"\xff\x00incomplete transfer\r\n"
                log_bytes = b"\xfftransfer failed\x00\r\n000\n"
                result_observed = []

                def command(argv, cwd, environment, log, **limits):
                    if Path(log).name != "toolchain-part-02.log":
                        return fixture.command(argv, cwd, environment, log, **limits)
                    fixture.observed.append((argv, cwd, dict(environment), limits))
                    partial = argv[argv.index("--output") + 1]
                    code = ("import os,pathlib,sys; "
                            "pathlib.Path(sys.argv[1]).write_bytes(" + repr(partial_bytes) + "); "
                            "os.write(1," + repr(log_bytes) + "); sys.exit(28)")
                    result = run_bounded([sys.executable, "-I", "-B", "-c", code, partial],
                                         cwd, environment, log, **limits)
                    result_observed.append(result)
                    return result

                def checkpoint(path, report):
                    rows = report.get("commands", [])
                    if (checkpoint_failure and rows and rows[-1]["id"] == "toolchain-part-02"
                            and rows[-1].get("exit_code") == 28 and not failures):
                        failures.append(True)
                        raise OSError("one-time acquisition completion checkpoint failure")
                    return original_write(path, report)

                fixture.run_mock.side_effect = command
                with mock.patch.object(inputs.base, "_write_json", side_effect=checkpoint):
                    report = fixture.acquire()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(failures, [True] if checkpoint_failure else [])
                self.assertEqual(len(fixture.observed), 8)
                self.assertEqual([part["state"] for part in report["parts"]], ["verified", "acquiring"])
                row = report["commands"][-1]
                self.assertTrue(result_observed)
                for key, value in result_observed[0].items():
                    self.assertEqual(row[key], value)
                self.assertIs(row["process_started"], True)
                self.assertIs(row["cleanup_complete"], True)
                self.assertEqual((row["outcome"], row["exit_code"], row["reason"]),
                                 ("fail", 28, "nonzero_exit"))
                self.assertEqual((fixture.args.output_dir / row["log"]).read_bytes(), log_bytes)
                self.assertEqual(row["log_size_bytes"], len(log_bytes))
                self.assertEqual(row["log_sha256"], hashlib.sha256(log_bytes).hexdigest())
                first, failed = report["parts"]
                self.assertEqual((fixture.args.archive_root / first["path"]).read_bytes(),
                                 fixture.part_bodies[first["path"]])
                self.assertEqual((fixture.args.archive_root / failed["partial_path"]).read_bytes(), partial_bytes)
                self.assertFalse((fixture.args.archive_root / failed["path"]).exists())
                self.assertIs(report["network_acquisition"], True)
                self.assertTrue(self.writers_finished(fixture))


if __name__ == "__main__":
    unittest.main()
