# Licensed under the Apache License, Version 2.0.
"""Real child-process checks for truthful local qualification launch metadata."""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import baseline_process


@unittest.skipUnless(os.name == "posix" and Path("/proc/self/stat").exists(),
                     "process-group monitoring requires Linux /proc")
class LocalQualificationProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="local-qualification-process-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.log = self.root / "command.log"
        self.processes = []
        self.addCleanup(self.cleanup_processes)
        self.original_popen = subprocess.Popen
        self.popen = self.enterContext(mock.patch.object(
            baseline_process.subprocess, "Popen", side_effect=self.start_process))

    def start_process(self, *args, **kwargs):
        process = self.original_popen(*args, **kwargs)
        self.processes.append(process)
        return process

    def cleanup_processes(self):
        for process in self.processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)

    def run_script(self, script="print('ready', flush=True)", *, argv=None, **limits):
        options = {"timeout_seconds": 3, "min_free_bytes": 1,
                   "max_log_bytes": 4096, "max_rss_bytes": 256 * 1024 ** 2,
                   "poll_seconds": 0.01}
        options.update(limits)
        return baseline_process.run_bounded(
            [sys.executable, "-c", script] if argv is None else argv,
            self.root, os.environ.copy(), self.log, **options)

    def assert_started_and_reaped(self, result):
        self.assertIs(result["process_started"], True)
        self.assertIs(result["cleanup_complete"], True)
        self.assertEqual(len(self.processes), 1)
        self.assertIsNotNone(self.processes[0].poll())

    def assert_log(self, result, expected):
        self.assertEqual(self.log.read_bytes(), expected)
        self.assertEqual(result["log_size_bytes"], len(expected))
        self.assertEqual(result["log_sha256"], hashlib.sha256(expected).hexdigest())

    def test_successful_child_reports_started(self):
        result = self.run_script()
        self.assert_started_and_reaped(result)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNone(result["reason"])
        self.assert_log(result, b"ready\n")

    def test_failing_child_still_reports_started(self):
        result = self.run_script("import sys; print('failed', flush=True); sys.exit(7)")
        self.assert_started_and_reaped(result)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["reason"], "nonzero_exit")
        self.assert_log(result, b"failed\n")

    def test_prelaunch_disk_stop_reports_not_started(self):
        with mock.patch.object(baseline_process, "_disk_has_reserve", return_value=False):
            result = self.run_script()
        self.assertIs(result["process_started"], False)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], "disk_reserve")
        self.assertIsNone(result["exit_code"])
        self.popen.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_missing_executable_reports_not_started(self):
        result = self.run_script(argv=[str(self.root / "missing-executable")])
        self.assertIs(result["process_started"], False)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], "launch_failed")
        self.assertIsNone(result["exit_code"])
        self.popen.assert_called_once()
        self.assertEqual(self.processes, [])
        self.assert_log(result, b"")

    def test_timeout_reports_started_and_reaps_child(self):
        result = self.run_script("import time; time.sleep(30)", timeout_seconds=0.2)
        self.assert_started_and_reaped(result)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "timeout")
        self.assertNotEqual(result["exit_code"], 0)
        self.assertLess(result["duration_seconds"], 4)

    def test_monitor_setup_failure_after_popen_still_reports_started(self):
        with mock.patch.object(baseline_process.os, "set_blocking", side_effect=OSError):
            result = self.run_script("import time; time.sleep(30)")
        self.assert_started_and_reaped(result)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "monitor_failed")

    def test_log_cap_preserves_started_flag_and_bounded_output(self):
        result = self.run_script("import os; os.write(1, b'x' * 20000)", max_log_bytes=128)
        self.assert_started_and_reaped(result)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "log_limit")
        self.assert_log(result, b"x" * 128)

    def test_rss_cap_preserves_started_flag_without_large_allocations(self):
        snapshot = baseline_process._group_snapshot
        cap = 256 * 1024 ** 2

        def over_budget(group):
            rss, live = snapshot(group)
            return (cap + 1 if group != os.getpgrp() and live else rss), live

        with mock.patch.object(baseline_process, "_group_snapshot", side_effect=over_budget):
            result = self.run_script("import time; time.sleep(30)", max_rss_bytes=cap)
        self.assert_started_and_reaped(result)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "memory_limit")
        self.assertEqual(result["peak_rss_bytes"], cap + 1)


if __name__ == "__main__":
    unittest.main()
